"""Tests for the Kalman Trend, 5m/15m/30m VWAP and z-score spread law.

Owner order 2026-11-16 (Karachi): the running intraday strategy is the Kalman
Trend with VWAP on the 5, 15 and 30 minute charts, and the mathematical base
is the z-score of the price minus VWAP spread. The law is pure: completed
bars, the session clock and measured spreads in, a view or a named refusal
out. No network, no clock, no daily file.

Owner order 2026-11-19 (Karachi), the later order: all three frames stay, the
call must still come early, the pick may not be more than 2% up on the day,
and its buyers must be at least twice its sellers. The tests below pin the
frame set, the timing arithmetic and both gates.
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
from src.signals import kalman_zscore_vwap as zlaw  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import mtf_vwap  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)


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


def frame(close: float, vwap: float, state: int, z: float | None,
          bars: int = 12) -> dict:
    return {"minutes": 0, "bars": bars, "close": close, "vwap": vwap,
            "kalman_state": state, "above_vwap": close > vwap,
            "spread_z": z, "spread": close - vwap, "spread_mean": 0.0,
            "spread_sigma": 1.0, "spread_samples": 8}


def frames_ready(*, fast_state: int = 1, fast_z: float = -1.8,
                 middle_state: int = 1, slow_state: int = 1) -> dict:
    return {
        "5m": frame(103.45, 103.77, fast_state, fast_z),
        "15m": frame(103.45, 102.80, middle_state, 0.2),
        "30m": frame(103.45, 102.60, slow_state, 0.1),
    }


class SpreadTest(unittest.TestCase):
    def test_a_dislocated_short_frame_spread_is_negative_in_sigmas(self):
        prices = [100.0 + 0.05 * i for i in range(60)]
        prices += [103.0 - 0.05 * i for i in range(20)]
        bars = [mtf_vwap.Frame(SESSION_OPEN + timedelta(minutes=i),
                               p, p + 0.05, p - 0.05, p, 10_000.0)
                for i, p in enumerate(prices)]
        view = zlaw.spread_zscore(bars, 12)
        self.assertIsNotNone(view)
        self.assertLess(view["z"], 0.0)
        self.assertGreater(view["samples"], 0)

    def test_an_unmeasurable_spread_says_nothing(self):
        self.assertIsNone(zlaw.spread_zscore([], 12))
        flat = [mtf_vwap.Frame(SESSION_OPEN, 100, 100, 100, 100, 0)
                for _ in range(20)]
        self.assertIsNone(zlaw.spread_zscore(flat, 12))


class FrameTest(unittest.TestCase):
    def test_the_three_frames_are_the_5_15_and_30_minute_charts(self):
        rows = series([100.0 + 0.03 * i for i in range(150)])
        views, reason = zlaw.frame_views(rows, session_of(rows))
        self.assertEqual(reason, "ok")
        self.assertEqual(set(views), {"5m", "15m", "30m"})
        for view in views.values():
            self.assertGreater(view["vwap"], 0.0)
            self.assertIn(view["kalman_state"], (-1, 1))

    def test_a_short_tape_fails_closed_with_a_named_reason(self):
        rows = series([100.0] * 20)
        views, reason = zlaw.frame_views(rows, session_of(rows))
        self.assertIsNone(views)
        self.assertTrue(reason.startswith("zscore_"), reason)


class EntryTest(unittest.TestCase):
    def build(self, *, frames: dict):
        rows = series([100.0] * 130)
        session = session_of(rows)
        with patch.object(zlaw, "frame_views", return_value=(frames, "ok")):
            return zlaw.entry_view("AAA", rows, session)

    def test_a_stretched_5m_spread_in_a_rising_regime_earns_a_view(self):
        view, reason = self.build(frames=frames_ready())
        self.assertEqual(reason, "ok")
        self.assertEqual(view["rule"], zlaw.ZSCORE_VERSION)
        self.assertEqual(view["side"], "LONG")
        self.assertEqual(view["signal_minutes"], 5)
        self.assertLess(view["z"], 0.0)
        self.assertEqual(view["frames"]["15m"]["kalman_state"], 1)
        self.assertEqual(view["frames"]["30m"]["kalman_state"], 1)

    def test_a_fast_frame_that_has_not_turned_up_is_refused(self):
        view, reason = self.build(frames=frames_ready(fast_state=-1))
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_fast_frame_not_up")

    def test_a_slow_frame_below_its_vwap_is_refused(self):
        frames = frames_ready()
        frames["30m"] = frame(101.0, 102.0, 1, 0.0)
        view, reason = self.build(frames=frames)
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_30m_below_vwap")

    def test_a_fifteen_minute_frame_trend_not_up_is_refused(self):
        view, reason = self.build(frames=frames_ready(middle_state=-1))
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_15m_trend_not_up")

    def test_a_slow_frame_trend_not_up_is_refused(self):
        view, reason = self.build(frames=frames_ready(slow_state=-1))
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_30m_trend_not_up")

    def test_an_unstretched_spread_is_refused(self):
        view, reason = self.build(frames=frames_ready(fast_z=-0.2))
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_not_stretched_below_mean")

    def test_a_missing_spread_is_refused(self):
        view, reason = self.build(frames=frames_ready(fast_z=None))
        self.assertIsNone(view)
        self.assertEqual(reason, "zscore_spread_unmeasurable")


class LabelTest(unittest.TestCase):
    def test_the_law_carries_its_own_strategy_label(self):
        self.assertEqual(zlaw.STRATEGY_VERSION, config.ZSCORE_STRATEGY_VERSION)
        self.assertTrue(config.ZSCORE_ENABLED)
        self.assertGreater(config.ZSCORE_Z_MIN, 0.0)
        self.assertEqual(config.MTF_TIMEFRAMES, (5, 15, 30))

    def test_the_summary_line_names_the_spread_and_the_frames(self):
        view, _ = EntryTest().build(frames=frames_ready())
        line = zlaw.summary(view)
        self.assertIn("Z-SPREAD", line)
        self.assertIn("5m VWAP", line)
        self.assertIn("5m/15m/30m", line)


class TimingTest(unittest.TestCase):
    """Owner order 2026-11-19 (Karachi): three frames stay, the call is early.

    The session opens at 09:32. The old law needed 17 completed 5 minute bars
    before its z alone could exist (10:57), which is why the call was late;
    that history is 7 bars now (10:07). The 30 minute frame is kept and (owner
    order 2026-11-19, latest) votes on its first completed bar, the one that
    closes at 10:02, so the fast frame's z history is the binding clock.
    """

    def test_the_fast_frame_and_its_z_are_ready_at_seven_past_ten(self):
        need = config.MTF_VWAP_LOOKBACK[5] + config.ZSCORE_MIN_SPREADS + 1
        self.assertEqual(need, 7, "the z-score history must fit by 10:07")
        ready = SESSION_OPEN + timedelta(minutes=5 * need)
        self.assertEqual(ready.strftime("%H:%M"), "10:07")

    def test_all_three_frames_are_kept(self):
        self.assertEqual(config.MTF_TIMEFRAMES, (5, 15, 30))

    def test_the_thirty_minute_frame_votes_on_its_first_completed_bar(self):
        """Owner order 2026-11-19 (latest): one completed bar, never two, so
        the slow frame is ready at 10:02 and the z history sets the clock."""
        self.assertEqual(config.MTF_MIN_BARS[30], 1)
        ready = SESSION_OPEN + timedelta(minutes=30 * config.MTF_MIN_BARS[30])
        self.assertEqual(ready.strftime("%H:%M"), "10:02")
        fast = 5 * (config.MTF_VWAP_LOOKBACK[5] + config.ZSCORE_MIN_SPREADS + 1)
        self.assertEqual(fast, 35, "seven 5 minute bars is the binding history")
        self.assertEqual(
            (SESSION_OPEN + timedelta(minutes=fast)).strftime("%H:%M"), "10:07")


if __name__ == "__main__":
    unittest.main()
