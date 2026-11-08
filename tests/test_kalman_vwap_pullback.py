"""Tests for the 2026-11-06 Kalman Trend VWAP pullback entry, updated to the
owner's three frame law of 2026-11-08.

The law is pure: completed one minute bars, the session's own high and low,
and the owner's fixed TP/SL in, a candidate or a named refusal out. The
integration tests patch the one minute filter and the three frame reader at
their seams, so what they measure is the orchestration of the two entry
paths; tests/test_mtf_vwap.py measures the frames themselves.
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
from src.signals import kalman_trend  # noqa: E402
from src.signals import kalman_vwap_pullback as pullback  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import mtf_vwap  # noqa: E402
from src.signals import trade_state  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)

#: The three frame agreement, already measured by test_mtf_vwap.py. The
#: orchestration tests patch the reader with this so they measure the entry
#: paths rather than repeating the frame law.
MTF_VIEW = {
    "rule": mtf_vwap.MTF_VERSION,
    "frames": {key: {"kalman_state": 1, "above_vwap": True}
               for key in ("5m", "15m", "60m")},
    "entry_clock": "test clock",
}


def row(index: int, open_: float, high: float, low: float, close: float,
        volume: float = 10_000.0):
    return scanner.MinuteBar(SESSION_OPEN + timedelta(minutes=index),
                             open_, high, low, close, volume)


def series(prices: list[float]) -> list:
    """One bar per price, high and low a little wider than the close."""
    return [row(index, price, round(price + 0.02, 4),
                round(price - 0.02, 4), price)
            for index, price in enumerate(prices)]


def pullback_rows(early_price: float = 130.0) -> list:
    """Sixty completed minutes with the pullback inside the last thirty.

    The first thirty bars set the session's high (*early_price*, or the
    tail's own peak when that is higher) and its low; bars 30 to 59 rise to a
    swing high at bar 50, dip 2.8 percent to bar 54, then resume at bar 55.
    The entry is bar 59's close.
    """
    prices = ([early_price] * 15 + [104.0] * 15
              + [round(107.0 + 0.1 * index, 4) for index in range(20)]
              + [109.5, 109.0, 108.0, 107.0, 106.5]
              + [107.0, 107.5, 108.0, 108.5, 109.0])
    return series(prices)


def rising_rows(count: int = 60) -> list:
    return series([100.0 + 0.1 * index for index in range(count)])


def session_of(rows: list) -> scanner.SessionData:
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars={"OGDC": rows}, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0)


def flat_trace(count: int, slope: float = 1e-4,
               flip_at: int | None = None) -> list[dict]:
    """A trend that is already up, with the fresh flip only where asked."""
    return [{"level": 0.0, "slope": slope, "state": 1,
             "flip_up": index == flip_at} for index in range(count)]


class DetectTest(unittest.TestCase):
    def test_a_dip_and_its_resumption_are_measured(self):
        setup, reason = pullback.detect(series([100.0, 100.2, 100.0, 99.5,
                                                99.2, 99.6, 99.9]),
                                        30, 5, 0.005)

        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(setup["peak_high"], 100.22, places=4)
        self.assertAlmostEqual(setup["trough_low"], 99.18, places=4)
        self.assertGreater(setup["depth_pct"], 0.01)
        self.assertEqual(setup["resume_bars"], 1)
        self.assertEqual(setup["resumed_at"],
                         (SESSION_OPEN + timedelta(minutes=5)).isoformat())

    def test_a_dip_below_the_depth_floor_is_refused(self):
        setup, reason = pullback.detect(series([100.0, 100.01, 100.0, 100.0,
                                                100.01]),
                                        30, 5, 0.005)
        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_too_shallow")

    def test_a_dip_with_no_resumption_is_refused(self):
        setup, reason = pullback.detect(series([100.0, 100.2, 99.8, 99.5,
                                                99.4]),
                                        30, 5, 0.005)
        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_no_resumption")

    def test_a_new_high_with_no_dip_after_it_is_refused(self):
        setup, reason = pullback.detect(series([100.0, 100.1, 100.2]),
                                        30, 5, 0.005)
        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_no_dip_yet")

    def test_a_resumption_older_than_the_window_is_history(self):
        setup, reason = pullback.detect(series([100.0, 100.2, 100.0, 99.5,
                                                99.2, 99.9, 99.8]),
                                        30, 0, 0.005)
        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_resumption_stale")

    def test_too_few_bars_are_refused(self):
        setup, reason = pullback.detect(series([100.0, 100.1]), 30, 5, 0.005)
        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_window_too_short")


class LocationTest(unittest.TestCase):
    def test_a_dip_and_entry_near_the_day_low_pass(self):
        wide = [row(0, 111.0, 120.0, 100.0, 111.0)]
        rows = series([101.5, 101.8, 101.6, 101.2, 101.5, 101.8])

        setup, reason = pullback.entry_view(rows, wide, 101.8)

        self.assertEqual(reason, "ok")
        self.assertEqual(setup["closer_to"], "daily low")
        self.assertLess(setup["trough_low"], setup["session_midpoint"])
        self.assertLess(setup["entry"], setup["session_midpoint"])

    def test_a_dip_near_the_day_high_is_refused(self):
        wide = [row(0, 111.0, 120.0, 100.0, 111.0)]
        rows = series([117.5, 117.8, 117.6, 117.0, 117.6, 118.2])

        setup, reason = pullback.entry_view(rows, wide, 118.2)

        self.assertIsNone(setup)
        self.assertEqual(reason, "pullback_not_near_day_low")

    def test_the_day_low_comes_from_the_whole_session_not_the_band(self):
        wide = [row(0, 130.0, 130.0, 100.0, 130.0),
                row(1, 101.5, 101.8, 101.1, 101.6)]
        rows = series([101.5, 101.8, 101.6, 101.2, 101.5, 101.8])

        setup, reason = pullback.entry_view(rows, wide, 101.8)

        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(setup["session_low"], 100.0, places=4)
        self.assertAlmostEqual(setup["session_high"], 130.0, places=4)


class CandidateTest(unittest.TestCase):
    def _candidate(self, rows: list, trace: list[dict],
                   tally: dict | None = None):
        tally = {} if tally is None else tally
        with patch.object(config, "MTF_ENABLED", True), \
                patch.object(kalman_trend, "filter_series", return_value=trace), \
                patch.object(mtf_vwap, "evaluate",
                             return_value=(MTF_VIEW, "ok")):
            return kalman_trend.candidate("OGDC", rows, session_of(rows), tally,
                                          frames=True)

    def test_the_pullback_entry_carries_its_own_strategy(self):
        result = self._candidate(pullback_rows(), flat_trace(60))

        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], pullback.STRATEGY_VERSION)
        self.assertEqual(result["side"], "LONG")
        self.assertIn("pullback", result["setup"])
        self.assertEqual(result["setup"]["mtf"], MTF_VIEW)
        self.assertGreater(result["score"], 0.0)
        entry = result["price"]["last"]
        self.assertAlmostEqual(result["stop_loss"], round(entry * 0.99, 4),
                               places=4)
        self.assertAlmostEqual(result["target"], round(entry * 1.02, 4),
                               places=4)

    def test_the_pullback_path_does_not_need_a_fresh_flip(self):
        result = self._candidate(pullback_rows(), flat_trace(60))
        self.assertIsNotNone(result)
        self.assertNotIn("flip_at", result["setup"])

    def test_an_entry_in_the_upper_half_of_the_day_is_refused(self):
        # The same pullback shape, read against a day whose high sits close
        # to the entry: the midpoint moves above the entry, so the resumption
        # is nearer the high than the low and the entry is refused.
        rows = pullback_rows(early_price=110.0)
        tally: dict = {}
        result = self._candidate(rows, flat_trace(len(rows)), tally)

        self.assertIsNone(result)
        self.assertIn("pullback_not_near_day_low", tally)

    def test_the_flip_entry_survives_as_the_first_path(self):
        rows = rising_rows()
        result = self._candidate(rows, flat_trace(len(rows), flip_at=len(rows) - 1))

        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], config.SCANNER_VERSION)
        self.assertIn("flip_at", result["setup"])

    def test_a_trend_that_is_not_up_opens_neither_path(self):
        rows = pullback_rows()
        trace = [{"level": 0.0, "slope": -1e-4, "state": -1,
                  "flip_up": False} for _ in rows]
        tally: dict = {}
        with patch.object(config, "MTF_ENABLED", True), \
                patch.object(kalman_trend, "filter_series", return_value=trace), \
                patch.object(mtf_vwap, "evaluate",
                             return_value=(MTF_VIEW, "ok")):
            result = kalman_trend.candidate("OGDC", rows, session_of(rows),
                                            tally, frames=True)
        self.assertIsNone(result)
        self.assertIn("pullback_trend_not_up", tally)
        self.assertIn("no_upward_flip_yet", tally)

    def test_the_higher_score_wins_and_the_flip_keeps_a_tie(self):
        flip = {"score": 70.0, "strategy": config.SCANNER_VERSION}
        dip = {"score": 80.0, "strategy": pullback.STRATEGY_VERSION}

        self.assertIs(kalman_trend.best_candidate([flip, dip]), dip)
        self.assertIs(
            kalman_trend.best_candidate([flip, {**dip, "score": 70.0}]), flip)


class MessageTest(unittest.TestCase):
    def test_the_signal_names_the_pullback_strategy(self):
        candidate = {"symbol": "OGDC", "score": 80.0, "stop_loss": 107.4,
                     "strategy": pullback.STRATEGY_VERSION,
                     "setup": {"pullback": {"depth_pct": 0.028}}}
        text = scanner.signal_message(candidate, {"status": "SUPPORTIVE"},
                                      108.5, SESSION_OPEN)

        self.assertIn(f"Strategy: {pullback.STRATEGY_VERSION}", text)
        self.assertIn("pullback resumed", text)
        self.assertIn("daily low", text)

    def test_the_signal_keeps_the_flip_wording_for_the_flip(self):
        candidate = {"symbol": "OGDC", "score": 70.0, "stop_loss": 107.4,
                     "setup": {}}
        text = scanner.signal_message(candidate, {"status": "SUPPORTIVE"},
                                      108.5, SESSION_OPEN)

        self.assertIn(f"Strategy: {config.SCANNER_VERSION}", text)
        self.assertIn("upward Kalman trend flip", text)


class TradeStateTest(unittest.TestCase):
    def _state(self):
        state = trade_state.SessionState(day=DAY.isoformat())
        state.begin_session()
        state.begin_scan()
        return state

    def test_the_entry_records_the_strategy_that_spoke(self):
        state = self._state()
        state.enter("OGDC", 108.5, SESSION_OPEN, 80.0, stop_loss=107.4,
                    strategy=pullback.STRATEGY_VERSION)
        self.assertEqual(state.scanner_version, pullback.STRATEGY_VERSION)

    def test_the_entry_defaults_to_the_flip_version(self):
        state = self._state()
        state.enter("OGDC", 108.5, SESSION_OPEN, 80.0, stop_loss=107.4)
        self.assertEqual(state.scanner_version, config.SCANNER_VERSION)


if __name__ == "__main__":
    unittest.main()
