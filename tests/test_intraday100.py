from __future__ import annotations

import unittest
from datetime import datetime

import numpy as np
import pandas as pd

from src.data.sessions import KARACHI
from src.research.intraday100.data import attach_sessions
from src.research.intraday100.engine import ExitRule, simulate_strategy, summarize_trades


def _ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=KARACHI).timestamp())


def _session_frame() -> pd.DataFrame:
    rows = []
    for stamp in (
        _ts(2024, 1, 1, 9, 30),
        _ts(2024, 1, 1, 9, 35),
        _ts(2024, 1, 1, 15, 25),
        _ts(2024, 1, 1, 15, 30),
        _ts(2024, 1, 5, 9, 15),
        _ts(2024, 1, 5, 9, 20),
        _ts(2024, 1, 5, 11, 55),
        _ts(2024, 1, 5, 12, 0),
        _ts(2024, 1, 5, 14, 35),
        _ts(2024, 1, 5, 16, 25),
        _ts(2024, 1, 5, 16, 30),
    ):
        rows.append({
            "symbol": "TEST",
            "ts": stamp,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
            "regular": True,
        })
    return pd.DataFrame(rows)


class SessionBandTests(unittest.TestCase):
    def test_regular_bar_must_fit_inside_band(self):
        frame = attach_sessions(_session_frame(), "5m")
        by_ts = dict(zip(frame["ts"], frame["valid_bar"]))
        self.assertFalse(by_ts[_ts(2024, 1, 1, 9, 30)])
        self.assertTrue(by_ts[_ts(2024, 1, 1, 9, 35)])
        self.assertTrue(by_ts[_ts(2024, 1, 1, 15, 25)])
        self.assertFalse(by_ts[_ts(2024, 1, 1, 15, 30)])

    def test_friday_break_is_not_continuous(self):
        frame = attach_sessions(_session_frame(), "5m")
        by_ts = dict(zip(frame["ts"], frame["valid_bar"]))
        self.assertTrue(by_ts[_ts(2024, 1, 5, 11, 55)])
        self.assertFalse(by_ts[_ts(2024, 1, 5, 12, 0)])
        self.assertTrue(by_ts[_ts(2024, 1, 5, 14, 35)])
        self.assertTrue(by_ts[_ts(2024, 1, 5, 16, 25)])
        self.assertFalse(by_ts[_ts(2024, 1, 5, 16, 30)])


def _trade_frame() -> pd.DataFrame:
    stamps = [
        _ts(2024, 1, 1, 9, 35), _ts(2024, 1, 1, 9, 40),
        _ts(2024, 1, 1, 9, 45), _ts(2024, 1, 1, 9, 50),
        _ts(2024, 1, 1, 9, 55), _ts(2024, 1, 1, 10, 0),
    ]
    # 09:35 to 10:00; all bars fit before 15:30.
    band_end = _ts(2024, 1, 1, 15, 30)
    rows = []
    for i, stamp in enumerate(stamps):
        rows.append({
            "symbol": "AAA",
            "ts": stamp,
            "open": 100.0,
            "high": 102.0 if i == 1 else 100.8,
            "low": 99.5 if i == 1 else 99.8,
            "close": 100.5,
            "volume": 1000.0,
            "regular": True,
            "valid_bar": True,
            "band_key": 1,
            "band_end": band_end,
            "day_ord": stamps[0] - 5 * 3600,
            "atr_pct": 0.010,
        })
    return pd.DataFrame(rows)


class EngineTests(unittest.TestCase):
    def test_entry_is_next_bar_and_target_uses_costs_and_capital(self):
        frame = _trade_frame()
        mask = np.zeros(len(frame), dtype=bool)
        mask[0] = True
        trades = simulate_strategy(
            frame, mask, np.zeros(len(frame)), "T1",
            ExitRule(target_atr=1.5, stop_atr=0.9, max_hold_bars=4),
            capital=10_000_000.0, trade_fraction=0.10,
            cost_side_bps=32.4, spread_side_bps=5.0, bar_seconds=300,
        )
        self.assertEqual(len(trades), 1)
        trade = trades.iloc[0]
        self.assertEqual(int(trade["entry_ts"]), int(frame.iloc[1]["ts"]))
        self.assertEqual(trade["exit_reason"], "target")
        self.assertAlmostEqual(trade["entry_price"], 100.0)
        expected_gross = 0.015
        expected_net = expected_gross - 2 * (32.4 + 5.0) / 10_000.0
        expected_net -= 0.15 * expected_net
        self.assertAlmostEqual(float(trade["net_return"]), expected_net, places=7)
        self.assertAlmostEqual(float(trade["pnl_pkr"]), 1_000_000.0 * expected_net, places=3)

    def test_only_one_trade_per_day(self):
        frame = _trade_frame()
        mask = np.zeros(len(frame), dtype=bool)
        mask[0] = True
        mask[2] = True
        trades = simulate_strategy(
            frame, mask, np.arange(len(frame), dtype=float), "T2",
            ExitRule(target_atr=1.5, stop_atr=1.0, max_hold_bars=4),
            bar_seconds=300,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(int(trades.iloc[0]["entry_ts"]), int(frame.iloc[1]["ts"]))

    def test_stop_wins_when_both_levels_are_touched(self):
        frame = _trade_frame()
        frame.loc[1, "high"] = 103.0
        frame.loc[1, "low"] = 97.0
        mask = np.zeros(len(frame), dtype=bool)
        mask[0] = True
        trades = simulate_strategy(
            frame, mask, np.zeros(len(frame)), "T3",
            ExitRule(target_atr=1.0, stop_atr=1.0, max_hold_bars=4),
            bar_seconds=300,
        )
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["exit_reason"], "stop")
        self.assertLess(float(trades.iloc[0]["net_return"]), 0.0)

    def test_summary_uses_fixed_one_million_notional(self):
        frame = _trade_frame()
        mask = np.zeros(len(frame), dtype=bool)
        mask[0] = True
        trades = simulate_strategy(
            frame, mask, np.zeros(len(frame)), "T4",
            ExitRule(target_atr=1.5, stop_atr=1.0, max_hold_bars=4),
            bar_seconds=300,
        )
        summary = summarize_trades(trades, "T4")
        self.assertEqual(summary["notional_per_trade_pkr"], 1_000_000.0)
        self.assertEqual(summary["trades"], 1)
        self.assertGreater(summary["net_return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
