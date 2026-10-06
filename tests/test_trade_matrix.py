"""Tests for scripts/build_trade_matrix.py: determinism, schema, causality.

Synthetic tests run everywhere (no data needed). The real-dataset test is
skipped when data/trade_matrix.parquet is absent (LOCAL ONLY, SO-4).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_trade_matrix import build_trade_rows, FEATURE_COLS  # noqa: E402
from src.signals.engine import add_features  # noqa: E402


def make_df(n_days: int = 80, seed: int = 7) -> pd.DataFrame:
    """Two symbols of legal daily bars (no band-breaking prints)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    frames = []
    for sym, start in (("AAA", 100.0), ("BBB", 50.0)):
        ret = rng.normal(0.0005, 0.012, n_days)
        close = start * np.cumprod(1 + ret)
        opn = close * (1 + rng.normal(0, 0.004, n_days))
        high = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, 0.003, n_days)))
        low = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, 0.003, n_days)))
        vol = rng.integers(50_000, 200_000, n_days).astype(float)
        frames.append(pd.DataFrame({
            "date": dates, "symbol": sym, "name": sym + " Ltd",
            "open": opn, "high": high, "low": low, "close": close, "volume": vol,
        }))
    return pd.concat(frames, ignore_index=True)


def baseline_signals(df: pd.DataFrame) -> list[tuple]:
    df = df.sort_values(["symbol", "date"])
    ma20 = df.groupby("symbol")["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    vmed = df.groupby("symbol")["volume"].transform(lambda s: s.rolling(20, min_periods=20).median())
    ok = (df["close"] > ma20) & (df["volume"] > vmed)
    return list(df.loc[ok, ["date", "symbol"]].itertuples(index=False, name=None))


class TestTradeMatrix(unittest.TestCase):
    def setUp(self):
        self.df = make_df()
        self.signals = baseline_signals(self.df)
        self.matrix = build_trade_rows(self.df, self.signals)

    def test_schema_complete(self):
        required = {"symbol", "signal_date", "entry_date", "entry_price",
                    "o1", "h1", "l1", "c1", "o2", "h2", "l2", "c2",
                    "o3", "h3", "l3", "c3",
                    "mae_1bar", "mae_3bar", "mfe_1bar", "mfe_3bar",
                    "t_to_mae", "t_to_mfe",
                    "t_to_p05", "t_to_p10", "t_to_p15", "t_to_p20",
                    "t_to_m10", "t_to_m20",
                    "p05_before_m10", "p10_before_m10", "p15_before_m10",
                    "p20_before_m10", "m10_before_p20", "p20_before_m20",
                    "ret_close1", "ret_close2", "ret_close3",
                    "ret_close5", "ret_close10", "gap_next_open",
                    "holding_bars", "data_invalid",
                    "feat_close", "feat_ma20", "feat_relvol", "feat_vol_accel",
                    "feat_sweep_low", "feat_bos_up", "feat_displacement",
                    "feat_clv_position", "feat_equal_lows",
                    "feat_fvg_bull_age1", "feat_fvg_size_pct", "feat_fvg_retrace",
                    "feat_20d_high_break", "feat_ret_20d",
                    "regime", "proxy_ret20", "member_note"}
        missing = required - set(self.matrix.columns)
        self.assertEqual(missing, set(), f"missing columns: {missing}")

    def test_determinism(self):
        again = build_trade_rows(self.df, self.signals)
        pd.testing.assert_frame_equal(self.matrix, again)

    def test_entry_is_next_bar_open(self):
        m = self.matrix.set_index(["symbol", "signal_date"])
        df = self.df.set_index(["symbol", "date"])
        for (sym, sdate), row in m.iterrows():
            i = df.index.get_loc((sym, sdate))
            nxt = df.iloc[i + 1]
            self.assertEqual(row["entry_date"], nxt.name[1])
            self.assertAlmostEqual(row["entry_price"], float(nxt["open"]), places=10)

    def test_mae_mfe_consistency(self):
        m = self.matrix
        held = m[m["holding_bars"] >= 1]
        self.assertTrue((held["mae_3bar"] <= 0).all() and (held["mfe_3bar"] >= 0).all())
        # MFE3 >= MFE1 and MAE3 <= MAE1 by construction (same windows grow)
        self.assertTrue((held["mfe_3bar"] >= held["mfe_1bar"] - 1e-9).all())
        self.assertTrue((held["mae_3bar"] <= held["mae_1bar"] + 1e-9).all())

    def test_feature_causality_full_history_identical(self):
        """Features at T are identical whether later data exists or not."""
        df = self.df
        full = build_trade_rows(df, self.signals)
        # keep only signals at least 10 sessions before the end
        cutoffs = df.groupby("symbol")["date"].max().sort_values().to_dict()
        late = [(d, s) for d, s in self.signals
                if d <= cutoffs[s] - pd.Timedelta(days=14)]
        early_df = df[df["date"] <= max(cutoffs.values()) - pd.Timedelta(days=21)]
        early = build_trade_rows(early_df, [x for x in late
                                            if x[0] <= early_df["date"].max()])
        a = full.set_index(["symbol", "signal_date"])
        b = early.set_index(["symbol", "signal_date"])
        shared = a.index.intersection(b.index)
        self.assertGreater(len(shared), 0)
        self.assertEqual(len(a.loc[shared]), len(shared), "duplicate index rows")
        feat_cols = [c for c in a.columns if c.startswith("feat_")] + \
                    ["mae_1bar", "mfe_1bar", "gap_next_open", "regime",
                     "proxy_ret20", "entry_price"]
        for col in feat_cols:
            x = a.loc[shared, col]
            y = b.loc[shared, col]
            if pd.api.types.is_float_dtype(x) and pd.api.types.is_float_dtype(y):
                same = np.allclose(x.to_numpy(dtype=float), y.to_numpy(dtype=float),
                                   equal_nan=True, rtol=0, atol=1e-12)
            else:
                same = bool((x.astype(str).to_numpy() == y.astype(str).to_numpy()).all())
            self.assertTrue(same, f"feature {col} changed when future rows removed")

    def test_horizon_returns_use_their_own_bar(self):
        """ret_close5/10 read the horizon bar when it exists (they are
        horizon reads, independent of the 3-bar holding window)."""
        m = self.matrix
        df = self.df.set_index(["symbol", "date"])
        last = pd.Series(df.index.get_level_values(1),
                         index=df.index.get_level_values(0)).groupby(level=0).max()
        checked = 0
        for row in m.itertuples(index=False):
            sdate = pd.Timestamp(row.signal_date)
            # 16 calendar days covers 10 business sessions
            if sdate <= last[row.symbol] - pd.Timedelta(days=16):
                i = df.index.get_loc((row.symbol, sdate))
                c5 = float(df.iloc[i + 5]["close"])
                expected = (c5 / row.entry_price - 1.0) * 100.0
                self.assertAlmostEqual(float(row.ret_close5), expected, places=8)
                c10 = float(df.iloc[i + 10]["close"])
                expected10 = (c10 / row.entry_price - 1.0) * 100.0
                self.assertAlmostEqual(float(row.ret_close10), expected10, places=8)
                checked += 1
        self.assertGreater(checked, 0)

    def test_add_features_has_required_columns(self):
        feat = add_features(self.df)
        for c in FEATURE_COLS:
            self.assertIn(c, feat.columns)


if __name__ == "__main__":
    unittest.main()
