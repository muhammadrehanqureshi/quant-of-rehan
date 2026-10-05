"""Backtest engine + walk-forward tests on synthetic bars (no network).

Fixture convention: the signal is decided at the close of D0; the entry is
D1's open. Every bar the engine walks is relative to that entry.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.engine import (  # noqa: E402
    DEFAULT_COST_SIDE_BPS,
    run_backtest,
    summarize,
)
from src.backtest.walkforward import (  # noqa: E402
    assert_no_leakage,
    walk_forward_splits,
)


def hl_frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (date, open, high, low, close) for one symbol."""
    return pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close"]
    ).assign(symbol="TEST")


def oc_frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (date, open, close): DPS timeseries reality (no high/low)."""
    return pd.DataFrame(rows, columns=["date", "open", "close"]).assign(symbol="TEST")


D0 = "2026-01-02"   # signal day (close)
D1, D2, D3, D4 = "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"
SIG = [(D0, "TEST")]


class TestHLMode(unittest.TestCase):
    def test_tp_fills_at_exact_limit_even_on_gap_up(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),        # signal at this close
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry at open 100
            (D2, 105.0, 106.0, 104.0, 105.5),    # gap up through TP(102)
            (D3, 104.0, 104.5, 103.5, 104.0),
        ])
        trades, s = run_backtest(df, SIG, touch_mode="hl")
        self.assertEqual(s["touch_mode"], "hl")
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.at[0, "outcome"], "TP")
        self.assertAlmostEqual(trades.at[0, "exit"], 102.0)  # limit, never better
        self.assertAlmostEqual(trades.at[0, "gross_ret"], 0.02)

    def test_sl_fills_at_stop(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry at open 100
            (D2, 100.0, 100.4, 97.0, 98.0),      # low pierces 99 stop
        ])
        trades, _ = run_backtest(df, SIG, touch_mode="hl")
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertAlmostEqual(trades.at[0, "exit"], 99.0)
        self.assertAlmostEqual(trades.at[0, "gross_ret"], -0.01)

    def test_same_bar_touchable_both_sl_wins(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry 100
            (D2, 100.0, 103.0, 98.0, 100.0),     # high>=102 AND low<=99
        ])
        trades, _ = run_backtest(df, SIG, touch_mode="hl")
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertAlmostEqual(trades.at[0, "exit"], 99.0)

    def test_gap_down_through_stop_fills_at_open_worse(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry 100, stop 99
            (D2, 95.0, 96.0, 94.0, 95.5),        # opens below the stop
        ])
        trades, _ = run_backtest(df, SIG, touch_mode="hl")
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertAlmostEqual(trades.at[0, "exit"], 95.0)   # worse fill
        self.assertAlmostEqual(trades.at[0, "gross_ret"], -0.05)

    def test_unadjusted_corporate_action_flagged_data_invalid(self):
        """10:1 par reconstruction must NOT book a fake -90% loss (SO-3)."""
        df = oc_frame([
            (D0, 99.0, 99.0),
            (D1, 100.0, 100.2),                  # entry 100
            (D2, 10.5, 10.0),                    # reconstruction crash
        ])
        trades, s = run_backtest(df, SIG)
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertTrue(bool(trades.at[0, "data_invalid"]))
        self.assertEqual(s["n_data_invalid"], 1)
        self.assertNotIn("win_rate", s)          # excluded from metrics

    def test_max_drawdown_is_chronological(self):
        """Trades arrive symbol-ordered; the equity curve must NOT compound
        that order (unrelated losses chaining into a fake 100% wipeout)."""
        def row(sym, exit_date, net):
            return {"symbol": sym, "entry_date": exit_date, "exit_date": exit_date,
                    "net_ret": net, "gross_ret": net, "outcome": "SL",
                    "bars_held": 1, "mae": min(net, 0.0), "mfe": max(net, 0.0),
                    "data_invalid": False, "touch_mode": "close"}
        # frame order (symbol-ordered): -50%, +25%, -50%, +10%;
        # chronological order (by exit_date): +10%, -50%, +25%, -50%
        df = pd.DataFrame([
            row("DDD", "2026-01-06", -0.50),
            row("CCC", "2026-01-05", 0.25),
            row("BBB", "2026-01-04", -0.50),
            row("AAA", "2026-01-02", 0.10),
        ])
        s = summarize(df, skipped=0, touch_mode="close", tp=0.02, sl=0.01, max_hold=3)
        # chronological equity: 1.0 -> 1.10 -> 0.55 -> 0.6875 -> 0.34375;
        # peak stays 1.10 -> worst dd = 1 - 0.34375/1.10 = 0.6875
        # (symbol-ordered compounding would fake only ~0.10)
        self.assertAlmostEqual(s["max_drawdown"], 0.6875, places=6)
        self.assertAlmostEqual(s["final_equity"], 0.34375, places=6)

    def test_normal_stop_loss_not_flagged(self):
        df = oc_frame([
            (D0, 99.0, 99.0),
            (D1, 100.0, 100.2),
            (D2, 100.0, 95.0),                   # honest -5% close exit
        ])
        trades, s = run_backtest(df, SIG)
        self.assertFalse(bool(trades.at[0, "data_invalid"]))
        # summary always reports the counter; honest data -> zero flagged
        self.assertEqual(s.get("n_data_invalid", 0), 0)

    def test_ten_x_open_vs_close_column_corruption_flagged(self):
        """Real corpus defect: open column ~10x close column (BLUEX et al.).
        Closes are self-consistent, so only a print-pair screen catches it."""
        df = oc_frame([
            (D0, 99.0, 6.45),
            (D1, 65.0, 6.37),                    # open 10x the close column
            (D2, 64.0, 6.30),
        ])
        trades, s = run_backtest(df, SIG)
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertTrue(bool(trades.at[0, "data_invalid"]))
        self.assertEqual(s["n_data_invalid"], 1)
        self.assertNotIn("win_rate", s)          # excluded from metrics

    def test_mae_mfe_track_excursions(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry 100
            (D2, 100.0, 101.0, 99.2, 100.0),     # low 99.2 -> MAE -0.8%
            (D3, 100.2, 103.0, 99.8, 102.0),     # high 103 -> MFE +3%, TP
        ])
        trades, _ = run_backtest(df, SIG, touch_mode="hl")
        self.assertAlmostEqual(trades.at[0, "mae"], -0.008)
        self.assertAlmostEqual(trades.at[0, "mfe"], 0.03)
        self.assertEqual(trades.at[0, "outcome"], "TP")


class TestCloseMode(unittest.TestCase):
    def test_close_above_tp_fills_at_limit(self):
        df = oc_frame([
            (D0, 99.0, 99.0),                    # signal at close
            (D1, 100.0, 100.2),                  # entry 100
            (D2, 100.5, 103.0),                  # close crosses TP
        ])
        trades, s = run_backtest(df, SIG)        # auto -> close (no H/L)
        self.assertEqual(s["touch_mode"], "close")
        self.assertEqual(trades.at[0, "outcome"], "TP")
        self.assertAlmostEqual(trades.at[0, "exit"], 102.0)  # limit fill

    def test_close_below_sl_fills_at_close_worse(self):
        df = oc_frame([
            (D0, 99.0, 99.0),
            (D1, 100.0, 100.2),                  # entry 100
            (D2, 100.0, 95.0),                   # close crashes through stop
        ])
        trades, _ = run_backtest(df, SIG)
        self.assertEqual(trades.at[0, "outcome"], "SL")
        self.assertAlmostEqual(trades.at[0, "exit"], 95.0)

    def test_timeout_exits_at_third_close(self):
        df = oc_frame([
            (D0, 99.0, 99.0),
            (D1, 100.0, 100.2),                  # entry 100, bar 1
            (D2, 100.4, 100.6),                  # bar 2
            (D3, 100.6, 100.8),                  # bar 3 -> timeout close
            (D4, 100.8, 101.0),                  # never reached
        ])
        trades, _ = run_backtest(df, SIG)
        self.assertEqual(trades.at[0, "outcome"], "TIMEOUT")
        self.assertEqual(trades.at[0, "bars_held"], 3)
        self.assertAlmostEqual(trades.at[0, "exit"], 100.8)

    def test_hl_mode_requested_without_columns_raises(self):
        df = oc_frame([(D0, 100.0, 100.2)])
        with self.assertRaises(ValueError):
            run_backtest(df, SIG, touch_mode="hl")


class TestNoLookaheadAndCosts(unittest.TestCase):
    def test_entry_is_next_bar_open_not_signal_close(self):
        df = oc_frame([
            (D0, 90.0, 100.0),                   # signal at this close
            (D1, 88.0, 89.0),                    # entry at 88.0 open
        ])
        trades, _ = run_backtest(df, SIG)
        self.assertEqual(str(trades.at[0, "entry_date"]), D1)
        self.assertAlmostEqual(trades.at[0, "entry"], 88.0)

    def test_signal_on_last_bar_is_skipped(self):
        df = oc_frame([(D0, 100.0, 100.2)])
        trades, s = run_backtest(df, SIG)
        self.assertEqual(len(trades), 0)
        self.assertEqual(s["n_signals_skipped"], 1)

    def test_costs_and_cgt_exact(self):
        df = hl_frame([
            (D0, 99.0, 99.5, 98.5, 99.0),
            (D1, 100.0, 100.5, 99.5, 100.2),     # entry 100
            (D2, 100.0, 103.0, 99.6, 101.0),     # clean TP at 102
        ])
        trades, _ = run_backtest(df, SIG, touch_mode="hl")
        net_before_cgt = 0.02 - 2 * DEFAULT_COST_SIDE_BPS / 1e4
        expected_net = net_before_cgt * (1 - 0.15)
        self.assertAlmostEqual(trades.at[0, "net_ret"], expected_net, places=12)

    def test_no_signals_yields_zero_trades_note(self):
        df = oc_frame([(D0, 100.0, 100.2)])
        trades, s = run_backtest(df, [])
        self.assertEqual(len(trades), 0)
        self.assertIn("NO TRADES", s["note"])


class TestWalkForward(unittest.TestCase):
    def test_folds_are_chronological_and_disjoint(self):
        dates = list(range(100))
        folds = walk_forward_splits(dates, n_folds=3, test_size=10, val_size=10)
        self.assertEqual(len(folds), 3)
        f0, f2 = folds[0], folds[2]
        self.assertEqual(f0["test"][-1], 79)
        self.assertEqual(f2["test"][0], 90)
        assert_no_leakage(folds)  # raises on any violation

    def test_too_short_date_axis_raises(self):
        with self.assertRaises(ValueError):
            walk_forward_splits(list(range(30)), n_folds=3,
                                test_size=10, val_size=10)

    def test_overlap_is_detected(self):
        folds = [{"fold": 0, "train": [1, 2], "val": [2, 3], "test": [4, 5]}]
        with self.assertRaises(ValueError):
            assert_no_leakage(folds)


if __name__ == "__main__":
    unittest.main()
