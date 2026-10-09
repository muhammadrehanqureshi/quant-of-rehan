"""End-to-end paper cycle test through the real pipeline.

This drives scripts.intraday_pipeline exactly as the scheduled job does, on a
synthetic capture written to a temporary file. It asserts the whole chain:

  TEST 5   the scanner ranks the whole captured universe
  TEST 6   exactly one candidate is entered
  TEST 8   the target is +2.0% of the ACTUAL entry price
  TEST 9   a second scan cannot enter a second trade, and a taken trade is
           never reported as NO TRADE
  TEST 10  a target hit keeps the session online and locked
  TEST 4   a missing capture is DATA BLOCKED, not a fake NO TRADE

The synthetic bars are a fixture, not a data claim: they exist only to
exercise the plumbing offline. Real sessions come from the capture poller.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import contextlib
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
from scripts.intraday_pipeline import run_finalize, run_scan  # noqa: E402

FRIDAY = date(2026, 10, 9)      # open 09:17, close 16:30 Karachi
OPEN_AT = datetime.combine(FRIDAY, __import__("datetime").time(*open_time(FRIDAY)),
                           tzinfo=KARACHI)
WINNER = "OGDC"


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
        # never touch a real session lock.
        patcher = patch.object(trade_state, "ROOT", root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.state_path = root / "data" / "forward" / "session_state.json"

    @staticmethod
    def symbols() -> list[str]:
        universe = json.loads((ROOT / "src" / "data" / "universe_kmiall.json")
                              .read_text(encoding="utf-8"))
        return [row["symbol"].strip().upper() for row in universe]

    def scan(self, slot: str) -> dict:
        with contextlib.redirect_stdout(io.StringIO()):
            return run_scan(slot, self.capture)

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
        self.assertEqual(record["trades_taken"], 1)
        self.assertEqual(record["trade_status"], State.DAILY_LOCKED)
        self.assertFalse(final["gate"]["eligible"])
        self.assertFalse(final["gate"]["live_signal_enabled"])

    def test_missing_capture_is_data_blocked_and_never_trades(self):
        """TEST 4 at pipeline level: no capture, no trade, honest reason."""
        missing = Path(self._dir.name) / "does_not_exist.ndjson"
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("10:00", missing)

        self.assertEqual(result["status"], scanner.DATA_BLOCKED)
        self.assertEqual(result["trade_state"]["trades_today"], 0)
        self.assertIsNone(result["trade_state"]["entry_price"])
        self.assertIn("coverage 0/319", result["reason"])

    def test_scan_outside_the_session_is_refused(self):
        """TEST 19: an illegal slot never scans and never writes a trade."""
        with contextlib.redirect_stdout(io.StringIO()):
            result = run_scan("17:00", self.capture)

        self.assertEqual(result["status"], "OUTSIDE_SESSION")
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()
