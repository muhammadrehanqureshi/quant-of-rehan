"""Tests for the scan's market leg.

Owner order 2026-11-12 (Karachi): the relative strength strategy is removed
with every other previous strategy. The market leg it used to gate entries is
not a strategy: it is the one measured number the running hybrid law reads to
know which side of the pair is cheap. These tests pin the measurement and its
refusals, and pin that it opens nothing on its own.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import market_leg  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)


def row(index: int, close: float, open_: float | None = None) -> object:
    return scanner.MinuteBar(SESSION_OPEN + timedelta(minutes=index),
                             close if open_ is None else open_,
                             round(close + 0.02, 4), round(close - 0.02, 4),
                             close, 10_000.0)


def session_of(bars: dict) -> scanner.SessionData:
    rows = next(iter(bars.values()))
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars=bars, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0)


class MarketTest(unittest.TestCase):
    def test_the_market_leg_is_the_equal_weight_mean(self):
        session = session_of({"AAA": [row(0, 100.0), row(1, 110.0)],
                              "BBB": [row(0, 100.0), row(1, 90.0)]})
        view, reason = market_leg.market_return(
            scanner.SessionData(day=DAY, as_of=session.as_of,
                                bars={**session.bars,
                                      **{f"F{index}": [row(0, 100.0),
                                                       row(1, 100.0)]
                                         for index in range(
                                             config.MARKET_LEG_MIN_SYMBOLS)}},
                                volume_available=True, bars_seen=2,
                                bars_rejected=0, duplicate_bars=0))
        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(view["mean_return"], 0.0, places=6)
        self.assertEqual(view["rule"], market_leg.MARKET_LEG_VERSION)
        self.assertIn("equal-weight", view["proxy"])

    def test_a_thin_capture_has_no_market_leg(self):
        session = session_of({"AAA": [row(0, 100.0), row(1, 101.0)]})
        view, reason = market_leg.market_return(session)
        self.assertIsNone(view)
        self.assertEqual(reason, "market_leg_too_thin")

    def test_a_session_return_needs_a_completed_bar(self):
        rows = [row(0, 100.0)]
        as_of = SESSION_OPEN            # nothing is complete yet
        self.assertIsNone(market_leg.session_return(rows, SESSION_OPEN, as_of))
        value = market_leg.session_return(rows, SESSION_OPEN,
                                          SESSION_OPEN + timedelta(minutes=1))
        self.assertAlmostEqual(value, 0.0, places=9)

    def test_the_market_leg_opens_nothing_on_its_own(self):
        for name in ("entry_view", "STRATEGY_VERSION", "summary"):
            self.assertFalse(hasattr(market_leg, name),
                             f"the removed relative strength strategy is back: {name}")


if __name__ == "__main__":
    unittest.main()
