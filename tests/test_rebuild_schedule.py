"""Acceptance tests for the schedule layer of the rebuild.

Owner acceptance list (2026-10-09) covered here:
  TEST 12  Monday-Thursday open state begins at 09:32 Asia/Karachi
  TEST 13  Friday open state begins at 09:17 Asia/Karachi
  TEST 14  Monday-Thursday close state begins at 15:30 Asia/Karachi
  TEST 15  Friday close state begins at 16:30 Asia/Karachi
  TEST 16  the open/close texts are the owner's exact words, one per edge
  TEST 17  every GitHub Actions cron lands inside the session (scan) or
           strictly after the close (finalize) once converted to PKT
  TEST 18  every session edge is covered by the Cloudflare crons exactly once,
           within the Workers Free five cron cap
  TEST 19  the scanner refuses to run outside the configured session

Parsing the two schedule files is deliberate: a cron string that is merely
present is not evidence that the timings are right.
"""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    FRIDAY_BANDS, KARACHI, MSG_MARKET_CLOSED, MSG_MARKET_OPEN, MarketPhase,
    WEEKDAY_BANDS, close_time, is_market_open, market_phase, next_event,
    open_time, session_bands,
)
from scripts.intraday_pipeline import session_legal  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "intraday-capture.yml"
# SO-13 (owner order 2026-10-14): the 30 second cadence runs in its own
# workflow, one band per fire, so it is parsed here too.
SESSION_WORKFLOW = ROOT / ".github" / "workflows" / "intraday-session.yml"
WRANGLER = ROOT / "cloud" / "wrangler.toml"

MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)
WEDNESDAY = date(2026, 10, 7)
THURSDAY = date(2026, 10, 8)
FRIDAY = date(2026, 10, 9)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KARACHI)


def crons_of(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found = re.findall(r'cron:\s*"([^"]+)"', text)
    if found:
        return found
    # wrangler.toml declares crons as a plain array of quoted strings
    block = re.search(r"crons\s*=\s*\[(.*?)\]", text, re.DOTALL)
    return re.findall(r'"([^"]+)"', block.group(1)) if block else []


def parse_js_bands(source: str, name: str) -> list[tuple[tuple[int, int],
                                                       tuple[int, int]]]:
    """Read a band table out of worker.js and return it as Python bands.

    The JavaScript literal is plain JSON, so it can be parsed rather than
    pattern matched, and a drifted table fails the parity test instead of
    silently disagreeing with src/data/sessions.py.
    """
    import json

    match = re.search(rf"const {name}\s*=\s*(\[.*?\]);", source, re.DOTALL)
    if not match:
        raise AssertionError(f"{name} not found in worker.js")
    raw = json.loads(match.group(1))
    return [((band[0][0], band[0][1]), (band[1][0], band[1][1]))
            for band in raw]


def parse_cron(expression: str) -> tuple[int, int, str]:
    minute, hour, _dom, _month, weekday = expression.split()
    return int(minute), int(hour), weekday


def weekdays_of(mask: str) -> list[int]:
    out: set[int] = set()
    for part in mask.split(","):
        if "-" in part:
            start, end = (int(value) for value in part.split("-"))
            out.update(range(start, end + 1))
        else:
            out.add(int(part))
    return sorted(out)


def cron_fires(expression: str) -> list[tuple[int, int, list[int]]]:
    """Every (hour, minute, weekdays) a cron expression can fire.

    Comma lists are expanded, because one expression may carry several times:
    `0,32 7,9 * * 5` fires at four instants, which is how the two Friday midday
    edges fit inside the Workers Free cap of five cron triggers per account.
    """
    minute_field, hour_field, _dom, _month, weekday_field = expression.split()
    minutes = [int(value) for value in minute_field.split(",")]
    hours = [int(value) for value in hour_field.split(",")]
    weekdays = weekdays_of(weekday_field)
    return [(hour, minute, weekdays) for hour in hours for minute in minutes]


def crons_deployed_by_pair(path: Path) -> list[str]:
    """The CRONS list cloud/pair.py actually pushes to Cloudflare.

    Tested separately from wrangler.toml because the two are independent
    edits: if they drift, the deployed schedule stops matching the schedule
    this suite proved correct.
    """
    block = re.search(r"^CRONS = \[(.*?)\]", path.read_text(encoding="utf-8"),
                      re.DOTALL | re.MULTILINE)
    return re.findall(r'"([^"]+)"', block.group(1)) if block else []


class TestSessionBoundaries(unittest.TestCase):
    def test_monday_to_thursday_boundaries(self):
        """TEST 12 and TEST 14."""
        for day in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY):
            with self.subTest(day=day.isoformat()):
                self.assertEqual(open_time(day), (9, 32))
                self.assertEqual(close_time(day), (15, 30))
                self.assertFalse(is_market_open(at(day, 9, 31)))
                self.assertTrue(is_market_open(at(day, 9, 32)))
                self.assertTrue(is_market_open(at(day, 15, 29)))
                self.assertFalse(is_market_open(at(day, 15, 30)))

    def test_friday_boundaries(self):
        """TEST 13 and TEST 15."""
        self.assertEqual(open_time(FRIDAY), (9, 17))
        self.assertEqual(close_time(FRIDAY), (16, 30))
        self.assertFalse(is_market_open(at(FRIDAY, 9, 16)))
        self.assertTrue(is_market_open(at(FRIDAY, 9, 17)))
        self.assertTrue(is_market_open(at(FRIDAY, 16, 29)))
        self.assertFalse(is_market_open(at(FRIDAY, 16, 30)))

    def test_weekend_is_never_a_session(self):
        saturday = date(2026, 10, 10)
        self.assertFalse(is_market_open(at(saturday, 11, 0)))

    def test_owner_texts_are_exact(self):
        """TEST 16: the words are the owner's law and are never reworded."""
        self.assertEqual(MSG_MARKET_OPEN, "Market is open. Quant is online now.")
        self.assertEqual(MSG_MARKET_CLOSED, "Market is closed. Quant is sleeping now.")


class TestFridayMiddayBreak(unittest.TestCase):
    """The exchange shuts for its Friday midday break and so does everything.

    Owner bug report, 2026-10-10: the app showed ONLINE at 14:23 on a Friday
    while the exchange was shut, with trading resuming at 14:32. The law is
    now two bands on a Friday, and every consumer of it is pinned here:
    the Python phase engine, both local runners, the scanner guard, and the
    Cloudflare worker's own band table.
    """

    def test_break_is_closed_and_the_reopen_is_open(self):
        for hour, minute in ((12, 0), (12, 1), (13, 7), (14, 23), (14, 31)):
            with self.subTest(at=f"{hour:02d}:{minute:02d}"):
                moment = at(FRIDAY, hour, minute)
                self.assertEqual(market_phase(moment), MarketPhase.BREAK)
                self.assertFalse(is_market_open(moment))
        for hour, minute in ((11, 59), (14, 32), (16, 29)):
            with self.subTest(at=f"{hour:02d}:{minute:02d}"):
                self.assertTrue(is_market_open(at(FRIDAY, hour, minute)))
        self.assertEqual(market_phase(at(FRIDAY, 16, 30)), MarketPhase.POST_CLOSE)

    def test_the_second_session_gets_its_own_warmup(self):
        """A reopen needs fresh bars; the break must not count as warmup."""
        self.assertEqual(market_phase(at(FRIDAY, 14, 23), warmup_minutes=20),
                         MarketPhase.BREAK)
        self.assertEqual(market_phase(at(FRIDAY, 14, 40), warmup_minutes=20),
                         MarketPhase.WARMUP)
        self.assertEqual(market_phase(at(FRIDAY, 14, 55), warmup_minutes=20),
                         MarketPhase.OPEN)

    def test_weekend_and_holiday_are_closed_all_day(self):
        saturday, sunday = date(2026, 10, 10), date(2026, 10, 11)
        holiday = date(2026, 11, 9)          # PSX holiday list
        for day in (saturday, sunday, holiday):
            for hour in (9, 11, 13, 15, 16):
                with self.subTest(day=day.isoformat(), hour=hour):
                    self.assertEqual(market_phase(at(day, hour, 0)),
                                     MarketPhase.CLOSED)
                    self.assertFalse(is_market_open(at(day, hour, 0)))

    def test_the_scanner_refuses_inside_the_break(self):
        self.assertFalse(session_legal(at(FRIDAY, 13, 7)))
        self.assertFalse(session_legal(at(FRIDAY, 14, 23)))
        self.assertTrue(session_legal(at(FRIDAY, 14, 37)))

    def test_both_local_runners_use_this_one_law(self):
        """The runners pass their own warmup, so the law is asked with it.

        A runner is not free to disagree about the phase: it may only add
        its warmup window, which is what makes the reopen at 14:32 WARMUP
        for the tick and OPEN for the law itself.
        """
        sys.path.insert(0, str(ROOT / "scripts"))
        import kmiall_tick  # noqa: E402
        import scan_loop  # noqa: E402

        from src import config  # noqa: E402

        for hour, minute in ((9, 0), (10, 0), (12, 30), (14, 23), (14, 32),
                             (14, 55), (16, 45)):
            moment = at(FRIDAY, hour, minute)
            with self.subTest(at=f"{hour:02d}:{minute:02d}"):
                self.assertEqual(
                    kmiall_tick.phase_of(moment),
                    market_phase(moment,
                                 warmup_minutes=config.TICK_WARMUP_MINUTES).value)
                self.assertEqual(scan_loop.phase_of(moment, 0.0),
                                 market_phase(moment, warmup_minutes=0.0).value)

    def test_the_phase_table_reaches_the_relay(self):
        """A band table the worker does not share would re-open the bug."""
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("BREAK", worker)
        self.assertIn("market_state", worker)
        for name in ("PRE_OPEN", "POST_CLOSE", "CLOSED", "OPEN"):
            self.assertIn(name, worker)
        self.assertEqual(parse_js_bands(worker, "WEEKDAY_BANDS"),
                         [(band[0], band[1]) for band in WEEKDAY_BANDS])
        self.assertEqual(parse_js_bands(worker, "FRIDAY_BANDS"),
                         [(band[0], band[1]) for band in FRIDAY_BANDS])

    def test_the_relay_wins_the_session_question_over_a_local_push(self):
        """A pushed snapshot carries data, never the session verdict.

        The local runner pushes market data (index, leaders, split) and may
        run on a PC whose clock has drifted, so its market_open must not be
        able to override the edge's own phase. In the /market handler the
        edge's state is therefore applied after the snapshot spread.
        """
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        start = worker.index("const edgeState = marketState(now);")
        handler = worker[start:start + 900]
        spread = handler.index("...snapshot")
        applied = handler.index("market_state: edgeState")
        self.assertGreater(
            applied, spread,
            "the pushed snapshot would override the relay's own phase")
        self.assertIn("market_open: edgeState.market_open", handler)

    def test_market_transition_function_uses_exact_karachi_edges_and_live_feed(self):
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        start = worker.index("async function trackMarketTransitions(")
        end = worker.index("// A pushed snapshot", start)
        body = worker[start:end]
        self.assertIn('edge.condition === "BREAK"', body)
        self.assertIn('edge.phase === "POST_CLOSE"', body)
        self.assertIn('edge.phase === "PRE_OPEN"', body)
        self.assertIn('edge.date}T${lastBand.close}:00+05:00', body)
        self.assertIn("sessionJustClosed", body)
        self.assertIn("now.getTime() - closeAt <= MARKET_OPEN_GRACE_MS", body)
        self.assertIn("MARKET_OPEN_GRACE_MS", body)
        self.assertIn('feed.status !== "OPEN" && feed.status !== "HALTED"', body)
        # Friday edges resolve from the shared bands, not hard-coded scans.
        for minute, expected in (("12:00", "BREAK"), ("14:32", "OPEN")):
            with self.subTest(minute=minute):
                self.assertIn(minute, worker)
                self.assertIn(f'"{expected}"', body)
        # No feed or session event may invoke the protected scan at 1s.
        self.assertNotIn("SCAN_INTERVAL_SECONDS = 1", worker)
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 30)',
                      (ROOT / "src" / "config.py").read_text(encoding="utf-8"))

    def test_the_next_edges_on_a_friday_are_the_four_band_edges(self):
        seen = []
        moment = at(FRIDAY, 9, 0)
        for _ in range(4):
            event, when = next_event(moment)
            seen.append((event, when.strftime("%H:%M")))
            moment = when + timedelta(minutes=1)
        self.assertEqual(seen, [("OPEN", "09:17"), ("CLOSE", "12:00"),
                                ("OPEN", "14:32"), ("CLOSE", "16:30")])


class TestOutsideSessionGuard(unittest.TestCase):
    def test_scanner_refuses_outside_the_session(self):
        """TEST 19."""
        self.assertTrue(session_legal(at(WEDNESDAY, 10, 0)))
        self.assertTrue(session_legal(at(FRIDAY, 16, 0)))
        self.assertFalse(session_legal(at(WEDNESDAY, 9, 0)))
        self.assertFalse(session_legal(at(WEDNESDAY, 16, 0)))
        self.assertFalse(session_legal(at(FRIDAY, 16, 45)))
        self.assertFalse(session_legal(at(date(2026, 10, 10), 11, 0)))


class TestTheThirtySecondSessionWorkflow(unittest.TestCase):
    """SO-13: the band loop that scans every 30 seconds, checked at the PR.

    The owner's order of 2026-10-14 made the repository public for free cloud
    minutes and asked for a 30 second scan. These tests hold the workflow that
    carries it: its crons inside real bands, its job inside GitHub's own
    six-hour cap, and the interval actually passed to the loop.
    """

    def test_each_band_starts_a_loop_inside_a_real_band(self):
        crons = crons_of(SESSION_WORKFLOW)
        self.assertEqual(len(crons), 4, "one window per band, Mon-Thu and Fri")
        for expression in crons:
            minute, hour, mask = parse_cron(expression)
            for weekday in weekdays_of(mask):
                pkt = datetime(2026, 10, 5, hour, minute, tzinfo=KARACHI) \
                    + timedelta(hours=5, days=weekday - 1)
                day = pkt.date()
                bands = session_bands(day)
                inside = any(band[0] <= (pkt.hour, pkt.minute) < band[1]
                             for band in bands)
                with self.subTest(cron=expression, weekday=weekday,
                                  pkt=pkt.strftime("%H:%M")):
                    self.assertTrue(
                        inside,
                        f"{expression} starts the loop at {pkt:%H:%M} PKT on "
                        f"{day.isoformat()}, outside every band ({bands})")

    def test_the_loop_runs_at_thirty_seconds(self):
        text = SESSION_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--interval 30", text)
        self.assertIn("scripts/scan_loop.py", text)
        self.assertIn("timeout --signal=TERM", text,
                      "a band job must stop the loop itself, not be killed")

    def test_the_job_stays_inside_git_hub_six_hour_cap(self):
        """A job over six hours is cancelled by GitHub, so the cap is checked."""
        text = SESSION_WORKFLOW.read_text(encoding="utf-8")
        minutes = [int(m) for m in re.findall(r"timeout-minutes:\s*(\d+)", text)]
        self.assertTrue(minutes, "the band job must declare its own cap")
        self.assertLess(max(minutes), 360,
                        "GitHub cancels a job that runs longer than six hours")


class TestGitHubActionsSchedule(unittest.TestCase):
    def test_every_cron_is_inside_a_session_or_after_the_close(self):
        """TEST 17: cron is UTC; the converted PKT time must be legal."""
        crons = crons_of(WORKFLOW)
        self.assertGreaterEqual(len(crons), 5, "the scan cadence went missing")
        for expression in crons:
            minute, hour, mask = parse_cron(expression)
            for weekday in weekdays_of(mask):
                pkt = datetime(2026, 10, 5, hour, minute, tzinfo=KARACHI) \
                    + timedelta(hours=5, days=weekday - 1)
                day = pkt.date()
                bands = session_bands(day)
                open_hm, close_hm = open_time(day), close_time(day)
                # Band aware: a scan cron must land inside a real band, never
                # in the Friday midday break. Before the break existed as a
                # band, a 13:00 Friday scan looked legal and ran on a shut
                # market.
                inside = any(band[0] <= (pkt.hour, pkt.minute) < band[1]
                             for band in bands)
                after_close = (pkt.hour, pkt.minute) >= close_hm
                with self.subTest(cron=expression, weekday=weekday,
                                  pkt=pkt.strftime("%H:%M")):
                    self.assertTrue(
                        inside or after_close,
                        f"{expression} lands at {pkt:%H:%M} PKT on "
                        f"{day.isoformat()}, outside every band "
                        f"({bands}) and before the "
                        f"{close_hm[0]:02d}:{close_hm[1]:02d} close")

    def test_scan_slots_appear_inside_both_sessions(self):
        crons = crons_of(WORKFLOW)
        converted = {parse_cron(expression)[:2] for expression in crons}
        monday_slots = {(hour + 5 or 24, minute) for minute, hour in converted}
        self.assertTrue(any((9, 32) <= slot <= (15, 30) for slot in monday_slots),
                        "no weekday in-session scan slot")
        self.assertTrue(any((9, 17) <= slot <= (16, 30) for slot in monday_slots),
                        "no Friday in-session scan slot")

    def test_finalize_slot_is_after_every_close(self):
        """The post-close job must not start while the market is still open."""
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--finalize", text)
        for expression in crons_of(WORKFLOW):
            minute, hour, mask = parse_cron(expression)
            for weekday in weekdays_of(mask):
                pkt = datetime(2026, 10, 5, hour, minute, tzinfo=KARACHI) \
                    + timedelta(hours=5, days=weekday - 1)
                if f'"{expression}") FINALIZE=' in text:
                    close_hm = close_time(pkt.date())
                    with self.subTest(cron=expression):
                        self.assertGreater((pkt.hour, pkt.minute), close_hm)

    def test_concurrency_and_artifacts_are_declared(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("concurrency:", text)
        self.assertIn("group: intraday-momentum", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("upload-artifact", text)

    def test_workflow_runs_the_single_scanner(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/intraday_pipeline.py", text)
        self.assertNotIn("intraday_engine", text)


class TestCloudflareSchedule(unittest.TestCase):
    """TEST 18: one authoritative clock, the worker included.

    The schedule must hit every session edge of the week exactly once. It used
    to do that with one cron per edge, six strings, which the Workers Free plan
    rejects outright: Cloudflare caps cron triggers at five per ACCOUNT and
    answers error 10072. Two Friday edges are therefore packed into one
    expression.

    So this checks the property that actually matters rather than the shape of
    the list, and it is a stronger check than the old count:

      * every edge of the week is covered, and
      * every edge is covered EXACTLY ONCE, because the worker notifies
        whenever a cron lands within two minutes of an edge, so a second fire
        in that window would send the owner the same message twice, and
      * a fire near no edge sends nothing (the harmless extra fires), and
      * the list fits the plan cap, so the deploy cannot be rejected, and
      * pair.py deploys the same list wrangler.toml declares.
    """

    #: Cloudflare Workers Free: cron triggers per account, per its own docs.
    FREE_PLAN_CRON_LIMIT = 5

    def test_worker_crons_cover_every_session_edge_exactly_once(self):
        crons = crons_of(WRANGLER)
        edges = []
        # Every band edge of the week: Friday is two sessions, so the worker
        # fires six notifications a week, not four (owner order 2026-10-10:
        # the midday break is closed, so it gets a close and a reopen).
        for weekday, bands in ((range(1, 5), WEEKDAY_BANDS), ((5,), FRIDAY_BANDS)):
            for band in bands:
                for hour_minute in (band[0], band[1]):
                    converted = ((hour_minute[0] - 5) % 24, hour_minute[1])
                    edges.append((converted, set(weekday), hour_minute))
        expected = len(WEEKDAY_BANDS) * 2 + len(FRIDAY_BANDS) * 2
        self.assertEqual(expected, 6, "the exchange's week has six edges")
        self.assertLessEqual(
            len(crons), self.FREE_PLAN_CRON_LIMIT,
            "Workers Free allows at most five cron triggers per account; a "
            "six entry list is rejected with Cloudflare error 10072")

        # Expand each cron to the instants it fires, then apply the worker's
        # own rule: a fire notifies only within two minutes of a band edge.
        fires: list[tuple[tuple[int, int], set[int]]] = []
        for expression in crons:
            for hour, minute, mask in cron_fires(expression):
                fires.append(((hour, minute), set(mask)))

        def minutes_of(hm: tuple[int, int]) -> int:
            return hm[0] * 60 + hm[1]

        for converted, weekdays, hour_minute in edges:
            hits = [(h, m) for (h, m), days in fires
                    if (h, m) == converted and days & weekdays]
            with self.subTest(edge=hour_minute):
                self.assertEqual(
                    len(hits), 1,
                    f"edge {hour_minute} PKT must be covered exactly once, "
                    f"found {len(hits)} covering fires")

        # A fire that lands within the worker's two minute window of an edge on
        # a day it shares would send a second, duplicate notification.
        for (hour, minute), days in fires:
            for converted, weekdays, hour_minute in edges:
                if not (days & weekdays):
                    continue
                gap = abs(minutes_of((hour, minute)) - minutes_of(converted))
                if (hour, minute) == converted:
                    continue
                with self.subTest(extra=(hour, minute), near=hour_minute):
                    self.assertGreater(
                        gap, 2,
                        f"the fire at {hour}:{minute:02d} UTC sits {gap} "
                        f"minutes from the {hour_minute} PKT edge, inside the "
                        f"worker's window, so it would duplicate it")

    def test_pair_deploys_the_same_schedule_as_wrangler(self):
        """The deployed list and the declared list must be one schedule."""
        pair_crons = crons_deployed_by_pair(ROOT / "cloud" / "pair.py")
        self.assertTrue(pair_crons, "cloud/pair.py must declare a CRONS list")
        self.assertEqual(sorted(pair_crons), sorted(crons_of(WRANGLER)),
                         "cloud/pair.py and cloud/wrangler.toml disagree about "
                         "the cron schedule, so the deploy would set something "
                         "other than the schedule this suite just proved")


class TestScheduleRobustness(unittest.TestCase):
    """GitHub's scheduler is not a cron daemon, so defend against its drop modes.

    Documented behaviour: schedule events are delayed under load, and the top
    of every hour is the load spike where queued events can be dropped. A cron
    that fires exactly on minute zero is therefore the likeliest to be lost,
    which is a silent failure: nothing runs and nothing reports a problem.
    """

    def test_no_cron_fires_exactly_on_the_hour(self):
        for expression in crons_of(WORKFLOW):
            minute = parse_cron(expression)[0]
            with self.subTest(cron=expression):
                self.assertNotEqual(
                    minute, 0,
                    f"{expression} fires on the top of the hour, where GitHub "
                    f"delays and drops schedule events under load")

    def test_every_cron_has_a_slot_mapping(self):
        """A cron with no case arm exits 2 at runtime; catch it at build time."""
        text = WORKFLOW.read_text(encoding="utf-8")
        for expression in crons_of(WORKFLOW):
            with self.subTest(cron=expression):
                self.assertIn(
                    f'"{expression}"', text,
                    f"{expression} has no arm in the slot mapping step")


class TestRetiredEngineContainment(unittest.TestCase):
    """The retired opening-range engine is kept only for the frozen gate.

    It is dead on the trading path, but "dead" was a claim in a report. This
    test makes it an invariant: within src/, the retired engine may be imported
    by exactly one module, the frozen research gate that reads its candidate
    rules and TP/SL constants. Any new import on the trading path fails here.
    """

    ALLOWED_IMPORTER = "src/research/forward_validation.py"

    def test_only_the_frozen_gate_imports_the_retired_engine(self):
        importers = []
        for path in sorted((ROOT / "src").rglob("*.py")):
            if path.name == "intraday_engine.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"intraday_engine", text):
                importers.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(
            importers, [self.ALLOWED_IMPORTER],
            "the retired intraday engine leaked back onto a non-research path")

    def test_the_orchestrator_does_not_reach_the_retired_engine(self):
        pipeline = (ROOT / "scripts" / "intraday_pipeline.py").read_text(
            encoding="utf-8")
        self.assertNotIn("intraday_engine", pipeline)


if __name__ == "__main__":
    unittest.main()
