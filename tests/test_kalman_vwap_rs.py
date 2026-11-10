"""Tests for the relative strength leg of the latest intraday strategy.

Owner order 2026-11-09 (Karachi): the Kalman Trend with VWAP on the 5
minute, 15 minute and 1 hour charts and relative strength. The leg is pure:
completed one minute bars, the session's own clock and the scan's own market
measure in, a view or a named refusal out. No network, no clock, no daily
file.
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
from src.signals import kalman_vwap_rs as rs  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import mtf_vwap  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)

#: The three frame agreement, already measured by test_mtf_vwap.py. Patching
#: it here keeps these tests on the relative strength leg.
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
    return [row(index, price, round(price + 0.02, 4),
                round(price - 0.02, 4), price)
            for index, price in enumerate(prices)]


def pullback_rows(early_price: float = 130.0) -> list:
    """The same shape test_kalman_vwap_pullback.py measures the dip on."""
    prices = ([early_price] * 15 + [104.0] * 15
              + [round(107.0 + 0.1 * index, 4) for index in range(20)]
              + [109.5, 109.0, 108.0, 107.0, 106.5]
              + [107.0, 107.5, 108.0, 108.5, 109.0])
    return series(prices)


def session_of(bars: dict) -> scanner.SessionData:
    rows = next(iter(bars.values()))
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars=bars, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0)


def flat_trace(count: int) -> list[dict]:
    """A trend that is already up, with no fresh flip."""
    return [{"level": 0.0, "slope": 1e-4, "state": 1, "flip_up": False}
            for _ in range(count)]


def quality_of(session: scanner.SessionData) -> scanner.QualityReport:
    return scanner.QualityReport(
        status=scanner.NO_TRADE, reason="test fixture", coverage=1.0,
        fresh_coverage=1.0, symbols_expected=len(session.bars),
        symbols_with_bars=len(session.bars), symbols_missing=(),
        symbols_stale=(), newest_bar=None, oldest_bar=None,
        data_age_minutes=0.0, duplicate_bars=0, malformed_bars=0,
        impossible_ohlc=0, zero_volume_bars=0, volume_available=True)


class MarketTest(unittest.TestCase):
    def test_the_market_leg_is_the_equal_weight_mean(self):
        session = session_of({"AAA": series([100.0, 110.0]),
                              "BBB": series([100.0, 90.0])})
        with patch.object(config, "RS_MIN_MARKET_SYMBOLS", 2):
            view, reason = rs.market_return(session)

        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(view["mean_return"], 0.0, places=9)
        self.assertEqual(view["symbols"], 2)
        self.assertEqual(view["rule"], rs.RS_VERSION)
        self.assertIn("equal-weight mean", view["proxy"])

    def test_a_thin_capture_has_no_market_leg(self):
        session = session_of({"AAA": series([100.0, 110.0])})
        with patch.object(config, "RS_MIN_MARKET_SYMBOLS", 2):
            view, reason = rs.market_return(session)

        self.assertIsNone(view)
        self.assertEqual(reason, "rs_market_too_thin")

    def test_the_session_return_is_the_first_open_to_the_last_close(self):
        rows = series([100.0, 105.0, 110.0])
        self.assertAlmostEqual(
            rs.session_return(rows, rs.session_open_of(session_of({"AAA": rows})),
                              SESSION_OPEN + timedelta(minutes=3)),
            0.1, places=9)


class GateTest(unittest.TestCase):
    def _view(self, mean_return: float):
        rows = series([100.0, 110.0])
        return rs.entry_view("AAA", rows, session_of({"AAA": rows}),
                             {"mean_return": mean_return, "symbols": 100})

    def test_a_name_ahead_of_the_market_passes(self):
        view, reason = self._view(0.0)

        self.assertEqual(reason, "ok")
        self.assertAlmostEqual(view["relative_strength"], 0.1, places=6)
        self.assertAlmostEqual(view["symbol_return"], 0.1, places=6)
        self.assertEqual(view["market_symbols"], 100)

    def test_a_name_behind_the_market_is_refused(self):
        view, reason = self._view(0.2)
        self.assertIsNone(view)
        self.assertEqual(reason, "rs_not_positive")

    def test_a_name_matching_the_market_is_not_enough(self):
        # The market leg is the name's own return, so the difference is
        # exactly zero: the gate wants a name AHEAD of the market, not level
        # with it.
        rows = series([100.0, 110.0])
        session = session_of({"AAA": rows})
        own = rs.session_return(rows, rs.session_open_of(session),
                               session.as_of)
        view, reason = rs.entry_view("AAA", rows, session,
                                     {"mean_return": own, "symbols": 100})

        self.assertIsNone(view)
        self.assertEqual(reason, "rs_not_positive")

    def test_a_missing_market_leg_fails_closed(self):
        rows = series([100.0, 110.0])
        view, reason = rs.entry_view("AAA", rows, session_of({"AAA": rows}),
                                     None)
        self.assertIsNone(view)
        self.assertEqual(reason, "rs_market_unavailable")

    def test_the_card_line_names_the_market(self):
        view = {"relative_strength": 0.0123, "market_return": -0.004,
                "market_symbols": 265}
        self.assertEqual(
            rs.summary(view),
            "RS +1.23 pp vs market -0.40% (equal weight of 265 names)")
        self.assertEqual(rs.summary(None), "")


class CandidateTest(unittest.TestCase):
    def _candidate(self, rs_market, tally: dict | None = None,
                   frames: bool = True):
        tally = {} if tally is None else tally
        rows = pullback_rows()
        session = session_of({"OGDC": rows})
        with patch.object(config, "MTF_ENABLED", True), \
                patch.object(kalman_trend, "filter_series",
                             return_value=flat_trace(len(rows))), \
                patch.object(mtf_vwap, "evaluate", return_value=(MTF_VIEW, "ok")):
            return kalman_trend.candidate("OGDC", rows, session, tally,
                                          frames=frames, rs_market=rs_market)

    def test_the_entry_carries_the_latest_strategy(self):
        # OGDC's own session return is about -16%, so a market that fell 30%
        # leaves the name ahead of the market.
        result = self._candidate({"mean_return": -0.30, "symbols": 120})

        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], config.RS_STRATEGY_VERSION)
        self.assertEqual(result["setup"]["entry_path"], "pullback")
        self.assertGreater(
            result["setup"]["relative_strength"]["relative_strength"], 0.0)
        self.assertAlmostEqual(result["stop_loss"],
                               round(result["price"]["last"] * 0.99, 4),
                               places=4)

    def test_a_name_lagging_the_market_opens_no_entry(self):
        tally: dict = {}
        result = self._candidate({"mean_return": 0.25, "symbols": 120}, tally)

        self.assertIsNone(result)
        self.assertIn("rs_not_positive", tally)

    def test_without_a_market_leg_the_previous_label_stays(self):
        result = self._candidate(None)

        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], pullback.STRATEGY_VERSION)
        self.assertIsNone(result["setup"]["relative_strength"])


class ScanTest(unittest.TestCase):
    def test_a_thin_capture_stops_the_scan_before_it_ranks(self):
        rows = series([100.0 + index for index in range(60)])
        session = session_of({"OGDC": rows})

        result = scanner.select_one(session, quality_of(session), frames=True)

        self.assertEqual(result.status, scanner.NO_TRADE)
        self.assertIn("relative strength unavailable", result.reason)
        self.assertEqual(result.ranked, [])


class MessageTest(unittest.TestCase):
    def test_the_message_states_the_relative_strength(self):
        candidate = {"symbol": "OGDC", "score": 84.0, "stop_loss": 107.4,
                     "strategy": config.RS_STRATEGY_VERSION,
                     "setup": {"pullback": {"depth_pct": 0.028},
                               "relative_strength":
                                   {"relative_strength": 0.0123,
                                    "market_return": -0.004}}}
        text = scanner.signal_message(candidate, {"status": "SUPPORTIVE"},
                                      108.5, SESSION_OPEN)

        self.assertIn(f"Strategy: {config.RS_STRATEGY_VERSION}", text)
        self.assertIn(
            "Relative strength: +1.23 pp over the equal-weight market", text)
        self.assertIn("outperforming the equal-weight market", text)


if __name__ == "__main__":
    unittest.main()
