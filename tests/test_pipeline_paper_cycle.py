"""End-to-end paper cycle test through the real pipeline.

This drives scripts.intraday_pipeline exactly as the scheduled job does, on a
synthetic capture written to a temporary file, with a FIXED Friday session
instant (so the suite behaves identically on a weekend, a holiday or any other
day) and with the relay stubbed (so no test ever touches the network or a real
signal card). It asserts the whole chain:

  TEST 5   the scanner ranks the whole captured universe
  TEST 6   exactly one candidate is entered
  TEST 8   the target is +2.0% of the ACTUAL entry price
  TEST 9   a second scan cannot enter a second trade, and a taken trade is
           never reported as NO TRADE
  TEST 10  a target hit keeps the session online and locked
  TEST 4   a missing capture is DATA BLOCKED, not a fake NO TRADE

Plus the integrity rules the rebuild must never lose:

  * a test run must not overwrite the owner's real forward-state files
    (observation, outcome, gate) under data/forward/;
  * every verdict reaches the app's signal card (POST /signals), so the card
    can never go stale;
  * observations, the daily outcome and the production gate are archived to
    the relay's durable research store (/research/*);
  * the paper outcome carries a real net return (costs and CGT applied), not
    the gross return relabelled.

The synthetic bars are a fixture, not a data claim: they exist only to
exercise the plumbing offline. Real sessions come from the broker tape (owner
order 2026-10-14), or from the servlet capture when no tape exists for the
day, so both shapes are driven end to end below.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.research import session_history  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import trade_state  # noqa: E402
from src.signals.trade_state import State  # noqa: E402
from scripts import intraday_pipeline as pipeline  # noqa: E402
from scripts.intraday_pipeline import run_finalize, run_scan  # noqa: E402

FRIDAY = date(2026, 10, 9)      # open 09:17, close 16:30 Karachi
OPEN_AT = datetime.combine(FRIDAY, __import__("datetime").time(*open_time(FRIDAY)),
                           tzinfo=KARACHI)
# The clock the pipeline sees. Pinned so the suite is weekday independent.
FIXED_NOW = datetime(2026, 10, 9, 10, 0, tzinfo=KARACHI)
WINNER = "OGDC"
REAL_FORWARD = ROOT / "data" / "forward"


def _snapshot_dir(path: Path) -> dict:
    if not path.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(path.glob("*")) if p.is_file()}


#: The forward records that carry a session day of their own.
DAY_KEYS = ("date", "day", "as_of", "updated_at")


def _day_evidence(content: bytes) -> set[str]:
    """Every ISO day a forward record carries, JSON files and JSONL alike."""
    days: set[str] = set()

    def collect(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (key in DAY_KEYS and isinstance(value, str)
                        and len(value) >= 10 and value[4] == "-" and value[7] == "-"):
                    days.add(value[:10])
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)

    for line in content.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            collect(json.loads(line))
        except json.JSONDecodeError:
            continue
    return days


def _last_record_days(content: bytes) -> set[str]:
    """The day evidence of the newest record only (the last line of a JSONL)."""
    lines = [line for line in content.decode("utf-8", "replace").splitlines()
             if line.strip()]
    return _day_evidence(lines[-1].encode("utf-8")) if lines else set()


def assert_forward_untouched(before: dict[str, bytes], after: dict[str, bytes],
                             synthetic_day: str) -> None:
    """Fail when the owner's real forward records carry the test's own session.

    The live 4 minute tick legitimately owns those files during a session and
    rewrites them on the real clock, while this test pins its clock to a past
    Friday. Comparing snapshots alone therefore reads the scheduler's honest
    write as pollution, which is a failure the owner can do nothing about.
    The evidence is the record's own day:

      * a day the synthetic session wrote, appearing where it was not before,
        is a leak (a journal that already carried that Friday from a past real
        session is not, which is why the check is 'newly present');
      * a change with no session day in it at all is not the scheduler's doing
        either, so it is refused;
      * a live rewrite of today's file passes, because its day is already the
        day it was before.

    Known limit: a leak that appends the synthetic day to a journal which
    already carried an identical row from history is indistinguishable here.
    The overwrite paths (observation, session_state, daily_outcome) are the
    ones this guard exists for, and they are caught.
    """
    changed = sorted({name for name in set(before) | set(after)
                      if before.get(name) != after.get(name)})
    if not changed:
        return
    evidence: set[str] = set()
    for name in changed:
        fresh = (_day_evidence(after.get(name, b""))
                 - _day_evidence(before.get(name, b"")))
        assert synthetic_day not in fresh, (
            f"{name} now carries this test's synthetic session "
            f"({synthetic_day}): the pipeline wrote into the owner's real "
            "data/forward directory; a test run must never rewrite a session "
            "record")
        assert synthetic_day not in _last_record_days(after.get(name, b"")), (
            f"{name} was appended to with this test's synthetic session "
            f"({synthetic_day}): a test run must never rewrite a session record")
        evidence |= _day_evidence(after.get(name, b""))
    assert evidence, (
        "the owner's real data/forward files changed with no session day in "
        f"them at all: {changed}; a test run must never rewrite a session "
        "record")


class RelayRecorder:
    """Stand in for the relay: record every call, answer ok, never dial out.

    ``refuse`` names the routes this stand-in rejects, so the failure half of
    a route can be exercised without a network: a refused route raises exactly
    what ``scripts.intraday_pipeline.relay_request`` raises when the relay
    answers an error (a RuntimeError carrying the relay's own reason).
    """

    def __init__(self, refuse: tuple[str, ...] = (), claims: bool = True) -> None:
        self.calls: list[tuple] = []
        self.refuse = refuse
        #: Whether the day's one signal is still unclaimed. The real relay
        #: answers /research/claim with {"claimed": bool}, and the pipeline
        #: reads that answer as the shared once-per-day lock, so the stand-in
        #: has to answer it as the route does rather than with a bare ok.
        self.claims = claims

    def __call__(self, method: str, route: str, payload: dict | None = None) -> dict:
        self.calls.append((method, route, payload))
        if route in self.refuse:
            raise RuntimeError(f"the relay refused {route} (test stand-in)")
        if route == "/research/claim":
            return {"ok": True, "claimed": self.claims}
        return {"ok": True}

    def routes(self) -> list[str]:
        return [route for _, route, _ in self.calls]

    def payload_for(self, route: str):
        for _, called_route, payload in self.calls:
            if called_route == route:
                return payload
        return None


from smc_fixture import setup_values


def build_capture(path: Path, symbols: list[str], minutes: int = 60) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        for symbol in symbols:
            bars = []
            for minute in range(minutes):
                op, hi, lo, close, volume = (setup_values(minute) if symbol == WINNER
                                           else (100, 100.01, 99.99, 100, 5000))
                bars.append(dict(t=(OPEN_AT + timedelta(minutes=minute)).strftime("%H:%M"),
                                 o=op, h=hi, l=lo, c=close, v=volume))
            handle.write(json.dumps({"ts": OPEN_AT.isoformat(), "symbol": symbol,
                                     "bars": bars}) + "\n")
    return path


def build_tape(path: Path, symbols: list[str], minutes: int = 60) -> Path:
    """Four prints per minute reproduce real OHLC, not venue daily highs."""
    with path.open("w", encoding="utf-8") as handle:
        for symbol in symbols:
            total = 0
            for minute in range(minutes):
                op, hi, lo, close, volume = (setup_values(minute) if symbol == WINNER
                                           else (100, 100.01, 99.99, 100, 5000))
                for second, price in zip((0, 10, 20, 50), (op, hi, lo, close)):
                    total += volume // 4
                    stamp = OPEN_AT + timedelta(minutes=minute, seconds=second)
                    handle.write(json.dumps({"kind": "MKT-FEED|SUB%", "ts": stamp.isoformat(),
                        "ticks": [{"scrip": f"{symbol}:REG", "last": str(price),
                                   "volume": str(total), "tick_time": stamp.strftime("%H:%M:%S"),
                                   "trades": str(minute * 4 + second + 1)}]}) + "\n")
    return path


class PipelineCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        self.capture = build_capture(root / "capture.ndjson", self.symbols())

        # Point the state machine at the temporary directory so the test can
        # never touch a real session lock. The pipeline derives its forward
        # directory from trade_state.ROOT, so this one patch redirects the
        # observation, outcome and gate files too.
        state_patcher = patch.object(trade_state, "ROOT", root)
        state_patcher.start()
        self.addCleanup(state_patcher.stop)
        self.state_path = root / "data" / "forward" / "session_state.json"

        relay_patcher = patch.object(pipeline, "relay_request", RelayRecorder())
        self.relay = relay_patcher.new
        relay_patcher.start()
        self.addCleanup(relay_patcher.stop)

        # The finalize asks the gate for the accumulated session evidence, and
        # that loader reads the relay's two-year archive. A unit test must
        # never dial out, and must never pull the owner's real archived
        # sessions into a synthetic gate, so the remote half is stubbed here
        # while the LOCAL half still runs for real against the temporary
        # forward directory this class already redirects.
        history_patcher = patch.object(
            session_history, "_relay_records",
            lambda timeout_s=20.0: ([], "stubbed: a unit test never dials "
                                        "the relay archive"))
        history_patcher.start()
        self.addCleanup(history_patcher.stop)

        clock_patcher = patch.object(pipeline, "now_karachi", lambda: FIXED_NOW)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)

        self.before = _snapshot_dir(REAL_FORWARD)

    @staticmethod
    def symbols() -> list[str]:
        universe = json.loads((ROOT / "src" / "data" / "universe_kmiall.json")
                              .read_text(encoding="utf-8"))
        return [row["symbol"].strip().upper() for row in universe]

    def scan(self, slot: str) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_scan(slot, self.capture)

    def assert_real_forward_untouched(self) -> None:
        """See assert_forward_untouched: the live tick's own writes are fine."""
        assert_forward_untouched(self.before, _snapshot_dir(REAL_FORWARD),
                                 FRIDAY.isoformat())

    def test_an_unchanged_verdict_does_not_rewrite_the_card(self):
        """Owner report 2026-10-19: the relay's KV write quota.

        The card header carries the slot, so a one second loop used to
        republish the card every second even when the verdict had not moved.
        The relay's free plan allows about 1,000 KV writes a day, which such a
        loop exhausts in minutes, and the phone was left holding a card from
        three days earlier once the writes were refused. What must be
        republished is a CHANGED VERDICT, and what makes the app fresh every
        second is /health plus the broker feed, not a rewritten card.
        """
        state = trade_state.SessionState.load(FRIDAY, path=self.state_path)
        body = "One trade already taken today: HCAR entered at 203.0, target 207.06."

        first = pipeline.push_card(pipeline.card_text(FRIDAY, "10:00", body, False),
                                   state, signature=f"{FRIDAY}|{body}")
        self.assertTrue(first, "the first verdict must reach the card")
        self.assertEqual(
            len([c for c in self.relay.calls if c[1] == "/signals"]), 1)

        second = pipeline.push_card(pipeline.card_text(FRIDAY, "10:01", body, False),
                                    state, signature=f"{FRIDAY}|{body}")
        self.assertFalse(second, "an unchanged verdict must not republish")
        self.assertEqual(
            len([c for c in self.relay.calls if c[1] == "/signals"]), 1,
            "a new slot with the same verdict spent a KV write")

        changed = body + " A fresh candidate was observed and refused."
        third = pipeline.push_card(pipeline.card_text(FRIDAY, "10:02", changed, False),
                                   state, signature=f"{FRIDAY}|{changed}")
        self.assertTrue(third, "a changed verdict must reach the card")
        self.assertEqual(
            len([c for c in self.relay.calls if c[1] == "/signals"]), 2)

    def test_the_card_header_is_ascii_and_dated(self):
        """Owner report 2026-10-20: the header reached the relay double decoded.

        The separator was U+00B7 and arrived as the two characters U+00C2 and
        U+00B7, so a reader saw a stray A-circumflex before the dot. The header
        now carries no non-ASCII at all, which makes the transport's charset
        irrelevant, and it still names the session and the slot a reader needs.
        """
        text = pipeline.card_text(FRIDAY, "10:00", "body", False)
        self.assertEqual(text.splitlines()[0],
                         f"QoR intraday {FRIDAY.isoformat()} | 10:00 PKT")
        self.assertEqual(pipeline.card_text(FRIDAY, "10:00", "body", True)
                         .splitlines()[0],
                         f"INTRADAY ALERT {FRIDAY.isoformat()} | 10:00 PKT")
        # Raises if a non-ASCII character ever returns to the header.
        text.encode("ascii")

    def test_full_paper_cycle(self):
        first = self.scan("10:00")
        quality = first["data_quality"]

        self.assertEqual(quality["status"], "OK")
        self.assertEqual(quality["symbols_with_bars"], quality["symbols_expected"])
        # Owner order 2026-10-15: the two exchange ETFs are excluded from every
        # scan (basket instruments are not intraday material).
        self.assertEqual(quality["symbols_expected"], 317)
        self.assertNotIn("MIIETF", (quality.get("symbols_missing") or ()))
        self.assertTrue(quality["volume_available"])
        self.assertEqual(quality["resolution"], "1-minute")

        self.assertEqual(first["status"], scanner.TRADE)
        self.assertEqual(first["eligible_count"], 1)
        winner = first["candidate"]
        self.assertEqual(winner["symbol"], WINNER)

        state = first["trade_state"]
        self.assertEqual(state["trades_today"], 1)
        self.assertEqual(state["symbol"], WINNER)
        self.assertAlmostEqual(state["target_price"],
                               round(state["entry_price"] * 1.02, 4), places=4)
        self.assertEqual(state["state"], State.TARGET_MONITORING)

        # a trade verdict reaches the app card as an ALERT and is archived
        card = self.relay.payload_for("/signals")
        self.assertIsNotNone(card, "the verdict never reached the app card")
        self.assertIn("INTRADAY ALERT", card["signals"])
        self.assertIn(WINNER, card["signals"])
        self.assertIn("/research/observation", self.relay.routes())

        # a later scan must not enter a second trade, and must not pretend the
        # day is a market NO TRADE either
        second = self.scan("10:15")
        self.assertEqual(second["trade_state"]["trades_today"], 1)
        self.assertEqual(second["trade_state"]["symbol"], WINNER)
        self.assertNotEqual(second["status"], scanner.NO_TRADE)
        self.assertIn(second["status"], (State.TARGET_MONITORING, State.DAILY_LOCKED))
        self.assertIsNone(second["candidate"])
        self.assertEqual(second["delivered"], "LOCKED")
        # the target was touched, so the paper position is closed and still online
        self.assertTrue(second["trade_state"]["target_hit"])
        self.assertGreaterEqual(second["trade_state"]["return_pct"], config.TARGET_PCT)

        with contextlib.redirect_stdout(io.StringIO()):
            final = run_finalize(self.capture)
        record = list(final["outcome"]["outcomes_by_rule"].values())[0]
        self.assertEqual(record["outcome"], "TARGET_HIT")
        self.assertEqual(record["gross_return"], round(config.TARGET_PCT, 6))
        # net is charged, and it is NOT the gross return relabelled
        self.assertEqual(record["net_return"], config.net_return(record["gross_return"]))
        self.assertLess(record["net_return"], record["gross_return"])
        self.assertEqual(record["trades_taken"], 1)
        self.assertEqual(record["trade_status"], State.DAILY_LOCKED)
        self.assertFalse(final["gate"]["eligible"])
        self.assertFalse(final["gate"]["live_signal_enabled"])

        # Owner defect 2026-10-16: the gate used to be asked to score an EMPTY
        # list, so sessions_collected was pinned at 0 for ever. The evidence
        # block now names what it actually read, and today's own session is
        # among it, filed under the live rule.
        evidence = final["gate"]["evidence"]
        self.assertEqual(evidence["sessions_loaded"], 1)
        self.assertIn("caller(1)", evidence["sources"])
        self.assertTrue(any(src.startswith("relay(")
                            for src in evidence["sources"]))
        self.assertEqual(final["gate"]["sessions_required"], 120)
        self.assertTrue(any(src.startswith("local(") for src in evidence["sources"]),
                        "the local forward state was not reported as a source")
        # Read twice (the finalize's own record and the journal line it just
        # appended), counted once: one day is one research session.
        self.assertGreaterEqual(evidence["records_read"], 2)

        # This synthetic capture stops an hour into a session that closes six
        # hours later, so the FINALIZE's own data-quality law calls it stale
        # and the loader refuses to verify it. That refusal is the point: a
        # session the system could not value at the close does not spend one
        # of the 120 research sessions, and the gate says so rather than
        # counting it.
        self.assertEqual(evidence["sessions_verified"], 0)
        self.assertEqual(final["gate"]["sessions_collected"], 0)

        # the outcome and the gate are archived, and the local record says so
        routes = self.relay.routes()
        self.assertIn("/research/outcome", routes)
        self.assertIn("/research/gate", routes)
        self.assertEqual(final["outcome"]["storage_status"], "relay+local")
        self.assertEqual(
            self.relay.payload_for("/research/outcome")["date"], FRIDAY.isoformat())

        self.assert_real_forward_untouched()

    def test_the_days_one_signal_is_claimed_before_any_entry(self):
        """Owner order 2026-10-16: one accepted BUY per Karachi day.

        The local session file cannot see another runner, and the cloud runs a
        band loop plus backstop slots from a restored copy of the day's state,
        so two runs can both believe the day is theirs. The relay's
        /research/claim is the one shared answer, and the entry must wait for
        it: the claim is taken before the trade is recorded, its answer is part
        of the observation, and the archive slot it sends is the minute
        precision the relay's research routes validate (the 30 second slot
        label is refused with 400 "invalid observation").
        """
        first = self.scan("10:00")
        self.assertEqual(first["status"], scanner.TRADE)
        self.assertEqual(first["claim"]["ok"], True)
        self.assertEqual(first["claim"]["detail"], "claimed")

        routes = self.relay.routes()
        self.assertIn("/research/claim", routes)
        self.assertLess(routes.index("/research/claim"), routes.index("/notify"),
                        "the shared lock was asked AFTER the notification")
        slot = self.relay.payload_for("/research/claim")["slot"]
        self.assertRegex(slot, r"^\d{2}:\d{2}$")
        self.assertRegex(
            self.relay.payload_for("/research/observation")["slot"],
            r"^\d{2}:\d{2}$",
            "the archive route only accepts HH:MM, so a seconds slot is lost")

    def test_a_refused_claim_cannot_enter_a_second_trade(self):
        """A second runner arriving on the same day is refused, and says so."""
        self.relay.claims = False
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", self.capture)

        self.assertEqual(result["status"], State.DAILY_LOCKED)
        self.assertEqual(result["delivered"], "LOCKED")
        self.assertIsNone(result["candidate"])
        self.assertEqual(result["trade_state"]["trades_today"], 0)
        self.assertFalse(result["claim"]["ok"])
        self.assertIn("already claimed", result["reason"])
        self.assertIn(WINNER, result["reason"])
        self.assertNotIn("/notify", self.relay.routes(),
                         "a refused claim still reached the notification path")

    def test_a_relay_that_cannot_answer_the_claim_fails_closed(self):
        """No answer, no entry: an unverifiable lock cannot promise one trade."""
        self.relay.refuse = ("/research/claim",)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", self.capture)

        self.assertEqual(result["status"], State.DAILY_LOCKED)
        self.assertEqual(result["trade_state"]["trades_today"], 0)
        self.assertIn("could not be taken", result["reason"])

    def test_a_seconds_slot_is_normalised_for_the_relay(self):
        """The 30 second cadence labels slots HH:MM:SS; the relay wants HH:MM.

        Measured 2026-10-16: the loop's slots are seconds precision, the
        relay's /research/observation and /research/claim validate HH:MM, and
        every observation since the cadence change was answered 400 and
        dropped. The guard keeps its seconds; the relay gets the minute.
        """
        self.assertEqual(pipeline.relay_slot("11:34:00"), "11:34")
        self.assertEqual(pipeline.relay_slot("11:34:30"), "11:34")
        self.assertEqual(pipeline.relay_slot("11:34"), "11:34")
        self.assertEqual(pipeline.relay_slot("9:05"), "09:05")
        for bad in ("", "abc", "11", "1:2:3:4"):
            with self.subTest(slot=bad):
                with self.assertRaises(ValueError):
                    pipeline.relay_slot(bad)

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00:30", self.capture)
        self.assertEqual(result["slot"], "10:00:30")
        self.assertEqual(self.relay.payload_for("/research/observation")["slot"],
                         "10:00", "a seconds slot was sent to the archive route")

    def test_a_refused_notification_is_never_reported_as_a_delivered_trade(self):
        """Owner defect 2026-10-16: delivered said TRADE even when nothing was.

        The candidate is genuine and the paper position is real either way.
        What must not survive is the claim that the owner was told about a
        trade the relay never accepted: the verdict reads TRADE_UNDELIVERED,
        the delivery block carries the relay's own refusal, and the reason
        says so.
        """
        self.relay.refuse = ("/notify",)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", self.capture)

        self.assertEqual(result["status"], scanner.TRADE)
        self.assertEqual(result["trade_state"]["trades_today"], 1)
        self.assertEqual(result["trade_state"]["symbol"], WINNER)
        self.assertEqual(result["delivered"], "TRADE_UNDELIVERED")
        self.assertIsNotNone(result["delivery"])
        self.assertFalse(result["delivery"]["ok"])
        self.assertEqual(result["delivery"]["kind"], "signals")
        self.assertIn("did NOT accept the notification", result["reason"])

        self.assert_real_forward_untouched()

    def test_missing_capture_is_data_blocked_and_never_trades(self):
        """TEST 4 at pipeline level: no capture, no trade, honest reason."""
        missing = Path(self._dir.name) / "does_not_exist.ndjson"
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", missing)

        self.assertEqual(result["status"], scanner.DATA_BLOCKED)
        self.assertEqual(result["trade_state"]["trades_today"], 0)
        self.assertIsNone(result["trade_state"]["entry_price"])
        self.assertIn("coverage 0/317", result["reason"])

        # Owner order 2026-10-15: a blocked scan NEVER textes. The card, the
        # archived observation and the printed payload carry the state; the
        # Telegram op channel stays silent for a background cadence.
        self.assertNotIn("/notify", self.relay.routes())

        # a blocked verdict is still shown on the card, dated, but not as an ALERT
        card = self.relay.payload_for("/signals")
        self.assertIsNotNone(card)
        self.assertIn("SCAN BLOCKED", card["signals"])
        self.assertNotIn("INTRADAY ALERT", card["signals"])
        self.assertIn("/research/observation", self.relay.routes())

        self.assert_real_forward_untouched()

    def test_scan_outside_the_session_is_refused(self):
        """TEST 19: an illegal slot never scans and never writes a trade."""
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("17:00", self.capture)

        self.assertEqual(result["status"], "OUTSIDE_SESSION")
        self.assertFalse(self.state_path.exists())
        self.assertEqual(self.relay.calls, [])
        self.assert_real_forward_untouched()


class TapeBarCycleTest(PipelineCycleTest):
    """The whole scheduled cycle, driven by bars built from the tape.

    Owner order 2026-10-14: the scanner must stop depending on the dead OHLC
    servlet. This subclass runs the SAME pipeline assertions on a capture in
    the tape's shape, so the wiring the scheduled job uses is proven in the
    shape the scheduled job now produces, not only in the old one.
    """

    def setUp(self) -> None:
        super().setUp()
        self.capture = build_tape(self.capture.parent / "tape.ndjson",
                                  self.symbols())

    def test_the_cycle_runs_on_tape_bars_and_says_so(self):
        first = self.scan("10:00")
        quality = first["data_quality"]

        self.assertIn("MKT-FEED tape", quality["source"])
        self.assertEqual(first["capture"]["format"], scanner.FORMAT_TAPE)
        self.assertEqual(first["capture"]["source"], quality["source"])
        self.assertEqual(quality["status"], "OK", quality["reason"])
        self.assertEqual(quality["symbols_expected"], 317)
        self.assertTrue(quality["volume_available"])
        self.assertEqual(quality["symbols_with_history"],
                         quality["symbols_with_bars"])

        self.assertEqual(first["status"], scanner.TRADE)
        self.assertEqual(first["candidate"]["symbol"], WINNER)
        self.assertIn(first["trade_state"]["state"], State.IN_POSITION)

    def test_a_thin_tape_blocks_instead_of_inventing_a_no_trade(self):
        thin = build_tape(self.capture.parent / "thin.ndjson", self.symbols(),
                          minutes=5)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", thin)

        self.assertEqual(result["status"], scanner.DATA_BLOCKED)
        self.assertIn("bar history", result["reason"])
        self.assertEqual(result["trade_state"]["trades_today"], 0)


class ForwardGuardTest(unittest.TestCase):
    """The guard must read the live tick's honest write as honest.

    Before this rule, a suite run that overlapped a scheduled tick failed on
    the owner's own scheduler: the assert compared snapshots and the tick had
    legitimately rewritten them. These cases pin both directions, with the
    synthetic day (a past Friday) and the live day kept apart on purpose.
    """

    SYNTHETIC = "2026-10-09"
    LIVE = "2026-10-13"

    @staticmethod
    def observation(day: str, slot: str) -> bytes:
        return json.dumps({
            "date": day, "slot": slot,
            "as_of": f"{day}T{slot}:00+05:00",
        }).encode("utf-8")

    def test_a_live_rewrite_of_todays_record_is_not_a_leak(self):
        before = {"observation.json": self.observation(self.LIVE, "10:36")}
        after = {"observation.json": self.observation(self.LIVE, "10:40")}
        assert_forward_untouched(before, after, self.SYNTHETIC)

    def test_a_synthetic_record_appearing_is_a_leak(self):
        before = {"observation.json": self.observation(self.LIVE, "10:36")}
        after = {"observation.json": self.observation(self.SYNTHETIC, "10:00")}
        with self.assertRaises(AssertionError):
            assert_forward_untouched(before, after, self.SYNTHETIC)

    def test_a_new_file_written_by_the_synthetic_session_is_a_leak(self):
        after = {"session_state.json":
                 json.dumps({"day": self.SYNTHETIC}).encode("utf-8")}
        with self.assertRaises(AssertionError):
            assert_forward_untouched({}, after, self.SYNTHETIC)

    def test_a_removed_file_is_refused(self):
        before = {"observation.json": self.observation(self.LIVE, "10:40")}
        with self.assertRaises(AssertionError):
            assert_forward_untouched(before, {}, self.SYNTHETIC)

    def test_a_change_with_no_session_day_at_all_is_refused(self):
        before = {"production_gate.json": b'{"status": "CLOSED"}'}
        after = {"production_gate.json": b'{"status": "PAPER"}'}
        with self.assertRaises(AssertionError):
            assert_forward_untouched(before, after, self.SYNTHETIC)

    def test_a_journal_that_already_held_history_passes_a_live_append(self):
        old = json.dumps({"day": self.SYNTHETIC, "state": "DAILY_LOCKED"})
        live = json.dumps({"day": self.LIVE, "state": "DAILY_LOCKED"})
        before = {"session_journal.jsonl": old.encode("utf-8") + b"\n"}
        after = {"session_journal.jsonl":
                 old.encode("utf-8") + b"\n" + live.encode("utf-8") + b"\n"}
        assert_forward_untouched(before, after, self.SYNTHETIC)

    def test_a_synthetic_append_is_a_leak_even_with_live_history(self):
        old = json.dumps({"day": self.LIVE, "state": "DAILY_LOCKED"})
        synthetic = json.dumps({"day": self.SYNTHETIC,
                                "state": "TARGET_MONITORING"})
        before = {"session_journal.jsonl": old.encode("utf-8") + b"\n"}
        after = {"session_journal.jsonl":
                 old.encode("utf-8") + b"\n" + synthetic.encode("utf-8") + b"\n"}
        with self.assertRaises(AssertionError):
            assert_forward_untouched(before, after, self.SYNTHETIC)

    def test_an_unchanged_directory_passes(self):
        snapshot = {"observation.json": self.observation(self.LIVE, "10:40")}
        assert_forward_untouched(snapshot, dict(snapshot), self.SYNTHETIC)


if __name__ == "__main__":
    unittest.main()
