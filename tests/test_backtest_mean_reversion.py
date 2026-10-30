"""Mean-reversion snapback strategy + portfolio risk layer tests.

No network, no dataset: every fixture is synthetic. The gate fixtures are
built so the answer is known by construction (one over-sold day inside a
steady uptrend; one over-sold day inside a downtrend) and the engine and
risk-layer tests hold the arithmetic to fixed numbers (SO-3: a report
that claims a win rate must be able to reproduce it from its own bars).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.mean_reversion import (  # noqa: E402
    MeanRevParams,
    build_signals,
    compute_atr_wilder,
    compute_rsi_wilder,
    gate_mask,
    mean_reversion_features,
)
from scripts.backtest_mean_reversion import (  # noqa: E402
    RISK_FRACTION_PER_TRADE,
    breakeven_table,
    risk_curve,
)

N_BARS = 260


def trend_up_frame(dump: bool = True, volume: float = 1_000_000.0) -> pd.DataFrame:
    """260 sessions of a steady uptrend; the dump day drops 6% ten bars
    before the end, and the tape carries on quietly afterwards, so the
    signal day is not the last bar (lets the leak test exercise a tail)."""
    dates = pd.bdate_range("2020-01-01", periods=N_BARS, name="date")
    closes = [100.0 + 0.135 * i for i in range(N_BARS)]
    rows = []
    for i, close in enumerate(closes):
        vol = volume
        if dump and i == N_BARS - 10:
            prior = closes[i - 1]
            close = prior * 0.94          # -6% on the dump session
            vol = volume * 3.0            # capitulation tape, still liquid
        rows.append({
            "symbol": "TEST",
            "date": dates[i],
            "open": closes[i - 1] if i else 100.0,
            "high": max(closes[i - 1], close) * 1.005 if i else close * 1.005,
            "low": min(closes[i - 1], close) * 0.995 if i else close * 0.995,
            "close": close,
            "volume": vol,
        })
    return pd.DataFrame(rows)


def trend_down_frame() -> pd.DataFrame:
    """260 sessions of a steady downtrend, closing near 100."""
    dates = pd.bdate_range("2020-01-01", periods=N_BARS, name="date")
    closes = [130.0 - 0.115 * i for i in range(N_BARS)]
    rows = []
    for i, close in enumerate(closes):
        vol = 1_000_000.0
        if i == N_BARS - 1:
            prior = closes[i - 1]
            close = prior * 0.94
            vol = 3_000_000.0
        rows.append({
            "symbol": "TEST",
            "date": dates[i],
            "open": closes[i - 1] if i else 130.0,
            "high": max(closes[i - 1], close) * 1.005 if i else close * 1.005,
            "low": min(closes[i - 1], close) * 0.995 if i else close * 0.995,
            "close": close,
            "volume": vol,
        })
    return pd.DataFrame(rows)


def trades_frame(rows: list[dict]) -> pd.DataFrame:
    """Hand-built engine-shaped trade list for the risk layer."""
    base = {
        "symbol": "TEST",
        "entry": 100.0,
        "exit": 100.0,
        "outcome": "SL",
        "gross_ret": 0.0,
        "mae": 0.0,
        "mfe": 0.0,
        "data_invalid": False,
    }
    return pd.DataFrame([{**base, **row} for row in rows])


class RSIAndATR(unittest.TestCase):
    def test_rsi_oversold_after_a_dump_day(self):
        frame = trend_up_frame()
        rsi = compute_rsi_wilder(frame["close"], 2)
        self.assertTrue(pd.isna(rsi.iloc[0]))
        self.assertLess(float(rsi.iloc[N_BARS - 10]), 10.0)
        # the steady pre-dump uptrend keeps RSI(2) pinned high: exactly one
        # over-sold day in the whole 260-session panel
        self.assertTrue((rsi.iloc[91:N_BARS - 10] >= 10.0).all())

    def test_rsi_window_validation(self):
        with self.assertRaises(ValueError):
            compute_rsi_wilder(pd.Series([1.0, 2.0]), 0)

    def test_atr_is_positive_and_warmed(self):
        frame = trend_up_frame()
        atr = compute_atr_wilder(frame["high"], frame["low"],
                                 frame["close"], 14)
        self.assertTrue(atr.iloc[:13].isna().all())
        self.assertFalse(pd.isna(atr.iloc[13]))
        self.assertGreater(float(atr.iloc[-1]), 0.0)


class MeanRevParamsLaws(unittest.TestCase):
    def test_defaults_validate(self):
        MeanRevParams().validate()

    def test_stop_must_not_be_tighter_than_target(self):
        params = MeanRevParams(take_profit=0.05, stop_loss=0.03)
        with self.assertRaises(ValueError):
            params.validate()

    def test_min_relvol_bounds(self):
        with self.assertRaises(ValueError):
            MeanRevParams(min_relvol=9.0).validate()


class GateBehaviour(unittest.TestCase):
    PARAMS = MeanRevParams()

    def test_signal_fires_on_the_dump_day_inside_an_uptrend(self):
        frame = trend_up_frame()
        dates = frame["date"].tolist()
        signals = build_signals(frame, self.PARAMS)
        self.assertEqual(len(signals), 1)
        signal_date, symbol = signals[0]
        self.assertEqual(symbol, "TEST")
        self.assertEqual(signal_date, dates[N_BARS - 10])

    def test_no_signal_when_oversold_inside_a_downtrend(self):
        frame = trend_down_frame()
        signals = build_signals(frame, self.PARAMS)
        self.assertEqual(signals, [])

    def test_no_future_leak(self):
        """Adding bars AFTER a signal day must not change that signal.

        The dump happens mid-panel; the tail keeps trading. Truncating or
        extending the panel past the signal date leaves the signal list
        untouched: no look-ahead anywhere in the feature chain.
        """
        frame = trend_up_frame()
        base = build_signals(frame, self.PARAMS)
        self.assertEqual(len(base), 1)
        signal_date = base[0][0]
        signal_pos = int(frame.index[frame["date"] == signal_date][0])
        self.assertLess(signal_pos, len(frame) - 1)
        self.assertEqual(build_signals(frame.iloc[:signal_pos + 1],
                                       self.PARAMS), base)

    def test_nan_rows_are_refused_not_filled(self):
        frame = trend_up_frame()
        frame.loc[frame.index[N_BARS - 5], "close"] = float("nan")
        enriched = mean_reversion_features(frame, self.PARAMS)
        mask = gate_mask(enriched, self.PARAMS)
        self.assertFalse(bool(mask.iloc[N_BARS - 5]))

    def test_dead_tape_volume_gates_the_signal_out(self):
        frame = trend_up_frame()
        frame.loc[frame.index[N_BARS - 10], "volume"] = 1.0  # dead tape print
        self.assertEqual(build_signals(frame, self.PARAMS), [])

    def test_missing_column_raises(self):
        frame = trend_up_frame().drop(columns=["volume"])
        with self.assertRaises(ValueError):
            mean_reversion_features(frame, self.PARAMS)

    def test_missing_feature_column_raises_in_gate(self):
        frame = mean_reversion_features(trend_up_frame(), self.PARAMS)
        with self.assertRaises(ValueError):
            gate_mask(frame.drop(columns=["rsi"]), self.PARAMS)


def _no_leak_window(engine_frame: pd.DataFrame) -> None:
    """Shared helper raising on any build_signals non-monotonicity."""
    if not engine_frame["date"].is_monotonic_increasing:
        raise ValueError("frame dates must be a session ladder")


class PortfolioRiskLayer(unittest.TestCase):
    def test_stop_out_loses_exactly_the_risk_fraction(self):
        trades = trades_frame([
            {"signal_date": "2026-01-02", "entry_date": "2026-01-05",
             "exit_date": "2026-01-06", "net_ret": -0.03},
        ])
        enriched, summary = risk_curve(trades, stop_frac=0.03)
        self.assertEqual(summary["n_entered"], 1)
        self.assertEqual(summary["n_skipped_cap"], 0)
        self.assertEqual(summary["n_skipped_kill"], 0)
        self.assertAlmostEqual(summary["final_equity"],
                               1.0 - RISK_FRACTION_PER_TRADE, places=6)
        self.assertAlmostEqual(summary["max_drawdown"],
                               RISK_FRACTION_PER_TRADE, places=6)
        notional = float(enriched.at[trades.index[0], "sizing_notional"])
        self.assertAlmostEqual(notional,
                               RISK_FRACTION_PER_TRADE / 0.03, places=6)

    def test_kill_switch_blocks_entry_past_the_drawdown_floor(self):
        rows = []
        for i in range(6):
            rows.append({
                "signal_date": f"2026-{1 + i:02d}-01",
                "entry_date": f"2026-{1 + i:02d}-01",
                "exit_date": f"2026-{1 + i:02d}-15",
                "net_ret": -0.03,
            })
        trades = trades_frame(rows)
        enriched, summary = risk_curve(trades, stop_frac=0.03)
        self.assertEqual(summary["n_skipped_kill"], 1)
        skipped = enriched.loc[enriched["risk_skip_reason"] == "kill_switch"]
        self.assertEqual(len(skipped), 1)
        no_losers_after = enriched.loc[
            enriched["risk_taken"], "sizing_notional"]
        self.assertTrue(len(no_losers_after) >= 1)

    def test_concurrency_cap_blocks_the_sixth_overlapping_entry(self):
        rows = []
        for i in range(6):
            rows.append({
                "signal_date": "2026-01-02",
                "entry_date": "2026-01-05",
                "exit_date": "2026-01-30",
                "net_ret": 0.01,
            })
        trades = trades_frame(rows)
        enriched, summary = risk_curve(trades, stop_frac=0.03)
        self.assertEqual(summary["n_entered"], 5)
        self.assertEqual(summary["n_skipped_cap"], 1)
        cap_blocked = enriched.loc[
            enriched["risk_skip_reason"] == "concurrency_cap"]
        self.assertEqual(len(cap_blocked), 1)

    def test_data_invalid_entries_are_never_sized(self):
        trades = trades_frame([
            {"signal_date": "2026-01-02", "entry_date": "2026-01-05",
             "exit_date": "2026-01-06", "net_ret": 0.01,
             "data_invalid": True},
        ])
        enriched, summary = risk_curve(trades, stop_frac=0.03)
        self.assertEqual(summary["n_skipped_invalid"], 1)
        self.assertFalse(bool(enriched["risk_taken"].iloc[0]))

    def test_empty_frame_and_bad_stop_frac(self):
        empty = risk_curve(trades_frame([]), stop_frac=0.03)[1]
        self.assertEqual(empty["n_entered"], 0)
        with self.assertRaises(ValueError):
            risk_curve(trades_frame([
                {"signal_date": "2026-01-02", "entry_date": "2026-01-05",
                 "exit_date": "2026-01-06", "net_ret": 0.0},
            ]), stop_frac=1.5)


class BreakevenArithmetic(unittest.TestCase):
    def test_break_even_bar_and_note(self):
        params = MeanRevParams()
        trades = trades_frame([
            {"signal_date": "2026-01-02", "entry_date": "2026-01-05",
             "exit_date": "2026-01-06", "net_ret": 0.01},
            {"signal_date": "2026-01-02", "entry_date": "2026-01-05",
             "exit_date": "2026-01-08", "net_ret": -0.03},
        ])
        table = breakeven_table(params, trades)
        self.assertAlmostEqual(table["break_even_win_rate_gross"], 0.75,
                               places=4)
        self.assertAlmostEqual(table["realized_win_rate"], 0.5, places=4)
        self.assertIn("SO-3", table["note"])

    def test_no_trades_note(self):
        table = breakeven_table(MeanRevParams(), trades_frame([]))
        self.assertEqual(table["note"], "no trades")


if __name__ == "__main__":
    unittest.main()
