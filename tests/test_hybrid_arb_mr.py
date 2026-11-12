"""Tests for the hybrid statistical arbitrage and mean reversion law.

Owner order 2026-11-12 (Karachi): the new intraday strategy is the Kalman
Trend with the VWAP on the 5 minute, 15 minute and 1 hour charts and a hybrid
statistical arbitrage and mean reversion model. The law is pure: completed
bars, the session's clock and the scan's own market measure in, a view or a
named refusal out. No network, no clock, no daily file.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import hybrid_arb_mr as hybrid  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)
MARKET = {"mean_return": 0.005, "symbols": 25}


def series(prices: list[float]) -> list:
    """One continuous one minute tape from the session open."""
    return [scanner.MinuteBar(SESSION_OPEN + timedelta(minutes=index),
                              price, round(price + 0.02, 4),
                              round(price - 0.02, 4), price, 10_000.0)
            for index, price in enumerate(prices)]


def session_of(rows: list) -> scanner.SessionData:
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars={"AAA": rows}, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0)


def frame(close: float, vwap: float, closes: list[float], state: int,
          bars: int = 12) -> dict:
    return {"minutes": 0, "bars": bars, "close": close, "vwap": vwap,
            "kalman_state": state, "above_vwap": close > vwap,
            "closes": closes}


def frames_ready(*, fast_state: int = 1) -> dict:
    """The three frames a stretched name would carry."""
    return {
        "5m": frame(108.0, 107.0, [109.0, 108.5, 108.0], fast_state),
        "15m": frame(108.0, 110.0, [112.0, 111.0, 110.0, 109.0, 108.0], 0),
        "60m": frame(108.0, 106.0, [104.0, 106.0, 108.0], 1),
    }


class StretchTest(unittest.TestCase):
    def test_a_close_below_the_mean_is_negative_in_sigmas(self):
        closes = [112.0, 111.0, 110.0, 109.0, 108.0]
        z = hybrid.stretch(closes, 110.0)
        self.assertIsNotNone(z)
        self.assertLess(z, 0.0)
        # A close above the same mean is the same distance on the other side.
        self.assertGreater(hybrid.stretch(closes, 106.0), 0.0)

    def test_an_unmeasurable_stretch_says_nothing(self):
        # Fewer than three closes, no VWAP, and a frame that never moved.
        self.assertIsNone(hybrid.stretch([100.0, 101.0], 100.0))
        self.assertIsNone(hybrid.stretch([100.0, 101.0, 102.0], None))
        self.assertIsNone(hybrid.stretch([100.0, 100.0, 100.0], 100.0))


class FrameTest(unittest.TestCase):
    def test_the_three_frames_are_read_from_the_session_tape(self):
        prices = ([100.0 + index for index in range(60)]
                  + [120.0 - 0.4 * index for index in range(58)]
                  + [96.0 + index for index in range(12)])
        views, reason = hybrid.frame_views(series(prices), session_of(series(prices)))
        self.assertEqual(reason, "ok")
        for key in ("5m", "15m", "60m"):
            self.assertIn(key, views)
            self.assertGreater(views[key]["vwap"], 0.0)
            self.assertIn(views[key]["kalman_state"], (-1, 1))

    def test_a_short_tape_fails_closed_with_a_named_reason(self):
        rows = series([100.0] * 20)
        views, reason = hybrid.frame_views(rows, session_of(rows))
        self.assertIsNone(views)
        self.assertTrue(reason.startswith("hybrid_"), reason)


class EntryTest(unittest.TestCase):
    def build(self, *, frames: dict, market, own: float):
        rows = series([100.0] * 130)
        session = session_of(rows)
        with patch.object(hybrid, "frame_views", return_value=(frames, "ok")), \
                patch.object(hybrid, "_session_return", return_value=own):
            return hybrid.entry_view("AAA", rows, session, market)

    def test_a_stretched_laggard_with_the_fast_frame_up_earns_a_view(self):
        view, reason = self.build(frames=frames_ready(), market=MARKET,
                                  own=-0.010)
        self.assertEqual(reason, "ok")
        self.assertEqual(view["rule"], hybrid.HYBRID_VERSION)
        self.assertEqual(view["side"], "LONG")
        self.assertLess(view["z"], 0.0)
        self.assertLess(view["relative_strength"], 0.0)
        self.assertEqual(view["fast_state"], 1)

    def test_no_market_leg_means_no_view(self):
        view, reason = self.build(frames=frames_ready(), market=None, own=-0.01)
        self.assertIsNone(view)
        self.assertEqual(reason, "hybrid_market_unavailable")

    def test_a_name_that_is_not_below_its_mean_is_refused(self):
        frames = frames_ready()
        frames["15m"] = frame(112.0, 110.0, [111.0, 112.0, 112.0], 1)
        view, reason = self.build(frames=frames, market=MARKET, own=-0.01)
        self.assertIsNone(view)
        self.assertEqual(reason, "hybrid_not_stretched_below_mean")

    def test_a_fast_frame_that_has_not_turned_up_is_refused(self):
        view, reason = self.build(frames=frames_ready(fast_state=-1),
                                  market=MARKET, own=-0.01)
        self.assertIsNone(view)
        self.assertEqual(reason, "hybrid_fast_frame_not_up")

    def test_a_name_that_is_keeping_up_with_the_market_is_refused(self):
        view, reason = self.build(frames=frames_ready(), market=MARKET,
                                  own=0.010)
        self.assertIsNone(view)
        self.assertEqual(reason, "hybrid_not_lagging_market")


class LabelTest(unittest.TestCase):
    def test_the_law_carries_its_own_strategy_label(self):
        self.assertEqual(hybrid.STRATEGY_VERSION, config.HYBRID_STRATEGY_VERSION)
        self.assertTrue(config.HYBRID_ENABLED)
        self.assertGreater(config.HYBRID_Z_MIN, 0.0)

    def test_the_summary_line_names_the_sigma_and_the_lag(self):
        view, _ = EntryTest().build(frames=frames_ready(), market=MARKET,
                                    own=-0.010)
        line = hybrid.summary(view)
        self.assertIn("HYBRID", line)
        self.assertIn("VWAP", line)
        self.assertIn("lagging the market", line)


if __name__ == "__main__":
    unittest.main()