"""Acceptance tests for the schedule layer of the rebuild.

Owner acceptance list (2026-10-09) covered here:
  TEST 12  Monday-Thursday open state begins at 09:32 Asia/Karachi
  TEST 13  Friday open state begins at 09:17 Asia/Karachi
  TEST 14  Monday-Thursday close state begins at 15:30 Asia/Karachi
  TEST 15  Friday close state begins at 16:30 Asia/Karachi
  TEST 16  the open/close texts are the owner's exact words, one per edge
  TEST 17  every GitHub Actions cron lands inside the session (scan) or
           strictly after the close (finalize) once converted to PKT
  TEST 18  every Cloudflare cron matches a session edge exactly
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
    def test_worker_crons_match_the_session_edges_exactly(self):
        """TEST 18: one authoritative clock, the worker included."""
        crons = crons_of(WRANGLER)
        edges = []
        # Every band edge of the week: Friday is two sessions, so the worker
        # fires six notifications a week, not four (owner order 2026-10-10:
        # the midday break is closed, so it gets a close and a reopen).
        for weekday, bands in ((range(1, 5), WEEKDAY_BANDS), ((5,), FRIDAY_BANDS)):
            for band in bands:
                for hour_minute in (band[0], band[1]):
                    converted = ((hour_minute[0] - 5) % 24, hour_minute[1])
                    edges.append((converted, weekday, hour_minute))
        expected = len(WEEKDAY_BANDS) * 2 + len(FRIDAY_BANDS) * 2
        self.assertEqual(len(crons), expected,
                         f"the worker must fire exactly {expected} edges")
        self.assertEqual(expected, 6, "the exchange's week has six edges")
        for converted, weekday, hour_minute in edges:
            minute, hour, mask = parse_cron(
                next(expression for expression in crons
                     if parse_cron(expression)[0] == converted[1]
                     and parse_cron(expression)[1] == converted[0]))
            with self.subTest(edge=hour_minute):
                self.assertEqual((hour, minute), converted)
                self.assertTrue(set(weekdays_of(mask)) == set(weekday))


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
