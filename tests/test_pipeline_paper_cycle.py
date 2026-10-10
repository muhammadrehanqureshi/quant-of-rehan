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
exercise the plumbing offline. Real sessions come from the capture poller.
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


class RelayRecorder:
    """Stand in for the relay: record every call, answer ok, never dial out."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __call__(self, method: str, route: str, payload: dict | None = None) -> dict:
        self.calls.append((method, route, payload))
        return {"ok": True}

    def routes(self) -> list[str]:
        return [route for _, route, _ in self.calls]

    def payload_for(self, route: str):
        for _, called_route, payload in self.calls:
            if called_route == route:
                return payload
        return None


def _slope(minute: int, strong: bool) -> float:
    if not strong:
        return 0.00005
    if minute < 25:
        return 0.0004
    if minute < 38:
        return 0.0010
    if minute < 44:
        return 0.0025
    return 0.0040


def build_capture(path: Path, symbols: list[str], minutes: int = 60) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        for symbol in symbols:
            strong = symbol == WINNER
            price = 100.0
            bars = []
            for minute in range(minutes):
                price *= 1.0 + _slope(minute, strong)
                stamp = OPEN_AT + timedelta(minutes=minute)
                volume = 25000.0 if (strong and minute >= 39) else 5000.0
                bars.append({"t": stamp.strftime("%H:%M"), "o": round(price, 4),
                             "h": round(price * 1.0002, 4),
                             "l": round(price * 0.9998, 4),
                             "c": round(price, 4), "v": volume})
            handle.write(json.dumps({
                "ts": (OPEN_AT + timedelta(minutes=minutes - 1)).isoformat(),
                "symbol": symbol, "bars": bars}) + "\n")
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
        self.assertEqual(
            _snapshot_dir(REAL_FORWARD), self.before,
            "the pipeline wrote into the owner's real data/forward directory; "
            "a test run must never rewrite a session record")

    def test_full_paper_cycle(self):
        first = self.scan("10:00")
        quality = first["data_quality"]

        self.assertEqual(quality["status"], "OK")
        self.assertEqual(quality["symbols_with_bars"], quality["symbols_expected"])
        self.assertEqual(quality["symbols_expected"], 319)
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

        # the outcome and the gate are archived, and the local record says so
        routes = self.relay.routes()
        self.assertIn("/research/outcome", routes)
        self.assertIn("/research/gate", routes)
        self.assertEqual(final["outcome"]["storage_status"], "relay+local")
        self.assertEqual(
            self.relay.payload_for("/research/outcome")["date"], FRIDAY.isoformat())

        self.assert_real_forward_untouched()

    def test_missing_capture_is_data_blocked_and_never_trades(self):
        """TEST 4 at pipeline level: no capture, no trade, honest reason."""
        missing = Path(self._dir.name) / "does_not_exist.ndjson"
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", missing)

        self.assertEqual(result["status"], scanner.DATA_BLOCKED)
        self.assertEqual(result["trade_state"]["trades_today"], 0)
        self.assertIsNone(result["trade_state"]["entry_price"])
        self.assertIn("coverage 0/319", result["reason"])

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


if __name__ == "__main__":
    unittest.main()
