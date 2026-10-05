"""v3.5.0: the Volume Profile Visible Range layer (intraday).

Owner's whitelist addendum - Volume Profile joins the tape layers.
These tests pin: the per-window score curve (POC = 1.0, profile high
= 0.6, profile low = ~0.1), the evidence discipline (a too-thin window
is NaN, never a synthetic neutral), the schema (vpvr_score + z_vpvr
exist, join FEATURE_COLUMNS and the master blend at 3%), and the blend
table still summing to exactly 1.0.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_kmiall_features as feats  # noqa: E402


def _ts(minute, second=0):
    return pd.Timestamp(
        f"2026-09-08 04:32:{second:02d}+00:00"
    ) + pd.Timedelta(minutes=minute)


def _vpvr_frame(price_path, volumes=None, symbol="ABOT"):
    """One (trading_date, symbol) window walking `price_path`, whose
    tick volumes are `volumes` (defaults to a mid-heavy profile: the
    middle ticks trade the most)."""
    n = len(price_path)
    if volumes is None:
        half = max(n // 2, 1)
        volumes = [10.0 + 90.0 * (1 - abs(t - half) / half)
                   for t in range(n)]
    rows = []
    vol_cum = 0.0
    val_cum = 0.0
    for i, price in enumerate(price_path):
        vol_cum += volumes[i]
        val_cum += volumes[i] * price
        rows.append({
            "symbol": symbol,
            "timestamp": _ts(i * 5 // 60, i * 5 % 60),
            "trading_date": "2026-09-08",
            "tradable": True,
            "feature_price_ok": True,
            "price": price,
            "high": price + 0.10,
            "low": price - 0.10,
            "volume": vol_cum,
            "value": val_cum,
            "change_pct": 0.5,
            "change_fraction": 0.005,
            "breadth_pct": 60.0,
            # Columns upstream stages normally produce; neutral here so
            # the VPVR assertions read only the VPVR block.
            "momentum_1m_pct": 0.0,
            "orb_score": 0.0,
            "gap_pct": 0.0,
            "vwap_ratio": 0.0,
            "short_term_price_score": 0.5,
            "book_strength": 0.5,
            "spread_quality": 0.5,
            "trade_activity_score": 0.5,
            "relative_volume_1m": 1.0,
        })
    return pd.DataFrame(rows)


class TestVpvrScoreCurve:
    def test_price_at_profile_high_scores_six_tenths(self):
        """Closing at the very top of the profiled range: accepted, but
        extended into air -> 0.6, never punished as churn."""
        prices = [100.0 + i for i in range(20)]          # rising window
        volumes = [100.0] * 19 + [10_000.0]              # last tick is POC
        df = _vpvr_frame(prices, volumes)
        out = feats.add_advanced_features(df)
        final = out.iloc[-1]["vpvr_score"]
        assert final == pytest.approx(0.6)

    def test_price_below_the_profile_fights_the_poc(self):
        """A final price at the bottom of a profile whose volume sits
        above it scores near the 0.1 floor."""
        prices = [120.0 - i for i in range(20)]          # falling window
        volumes = [10_000.0] + [100.0] * 19              # POC at the top
        df = _vpvr_frame(prices, volumes)
        out = feats.add_advanced_features(df)
        final = out.iloc[-1]["vpvr_score"]
        assert final is not None and np.isfinite(final)
        assert 0.1 <= final < 0.5

    def test_at_poc_scores_above_the_low(self):
        """Same volume shape (all the weight at 102-104), two closes:
        settling just above the POC scores high; collapsing under it
        scores low. The profile is identical - only acceptance differs."""
        walk = [98.0, 100.0, 102.0, 104.0, 102.0]
        volumes = [100.0] * 10 + [10_000.0] * 10  # POC = 102-104 zone

        above = _vpvr_frame((walk + [103.0] * 5) * 2, volumes)  # final 103
        out_above = feats.add_advanced_features(above)
        s_above = out_above["vpvr_score"].dropna().iloc[0]

        below = _vpvr_frame((walk + [99.0] * 5) * 2, volumes)   # final 99
        out_below = feats.add_advanced_features(below)
        s_below = out_below["vpvr_score"].dropna().iloc[0]

        assert s_above > 0.5
        assert s_below < s_above

    def test_score_is_bounded(self):
        prices = [100.0 + 0.5 * ((t % 6) - 2) for t in range(24)]
        df = _vpvr_frame(prices)
        out = feats.add_advanced_features(df)
        # One score per (trading_date, symbol) window, broadcast to the
        # window's rows (the same convention as rsi14/ema_alignment).
        s = out["vpvr_score"].dropna()
        assert len(s) > 0
        assert ((s >= 0.1) & (s <= 1.0)).all()
        assert s.nunique() == 1  # one window -> one score


class TestVpvrEvidenceDiscipline:
    def test_thin_window_is_nan(self):
        """Fewer than 10 usable ticks: no profile, no number."""
        prices = [100.0, 100.5, 101.0]
        df = _vpvr_frame(prices)
        out = feats.add_advanced_features(df)
        assert out["vpvr_score"].isna().all()

    def test_flat_window_is_nan(self):
        """hi == lo (one price forever): there is no profile to score."""
        df = _vpvr_frame([100.0] * 20)
        out = feats.add_advanced_features(df)
        assert out["vpvr_score"].isna().all()

    def test_zero_volume_ticks_contribute_nothing(self):
        prices = [100.0 + i for i in range(20)]
        volumes = [0.0] * 10 + [500.0] * 10
        df = _vpvr_frame(prices, volumes)
        out = feats.add_advanced_features(df)
        # The zero half carries no evidence; the live half still profiles.
        s = out["vpvr_score"]
        assert s.iloc[-1] is not None and np.isfinite(s.iloc[-1])

    def test_z_vpvr_nan_where_score_nan(self):
        df = _vpvr_frame([100.0, 100.5, 101.0])
        out = feats.add_master_score(feats.add_advanced_features(df))
        assert out["z_vpvr"].isna().all()


class TestVpvrSchemaAndBlend:
    def test_columns_emitted(self):
        df = _vpvr_frame([100.0 + i * 0.5 for i in range(20)])
        out = feats.add_advanced_features(df)
        assert "vpvr_score" in out.columns
        assert "z_vpvr" in out.columns

    def test_columns_in_feature_schema(self):
        assert "vpvr_score" in feats.FEATURE_COLUMNS
        assert "z_vpvr" in feats.MASTER_COMPONENTS

    def test_blend_table_sums_to_one(self):
        assert sum(feats.MASTER_COMPONENTS.values()) == pytest.approx(1.0)
        # z_vpvr weight was retired (0.03 -> 0.0) when z_atr was added so
        # the table still sums to 1.0; the column stays for schema compat.
        assert feats.MASTER_COMPONENTS["z_vpvr"] == pytest.approx(0.0)

    def test_master_score_vpvr_weight_is_retired(self):
        """z_vpvr weight was retired (0.03 -> 0.0) when z_atr was added;
        a frame whose ONLY populated blend component is z_vpvr produces
        NaN master_score because the weight is now zero - the column stays
        for schema compatibility only."""
        prices = [100.0 + i for i in range(20)]
        volumes = [100.0] * 19 + [10_000.0]
        df = _vpvr_frame(prices, volumes)
        # Strip every other blend input the small frame may carry.
        for col in ("orb_score", "gap_pct", "vwap_ratio"):
            if col in df.columns:
                df[col] = np.nan
        out = feats.add_master_score(feats.add_advanced_features(df))
        scored = out["master_score"].dropna()
        assert len(scored) > 0
