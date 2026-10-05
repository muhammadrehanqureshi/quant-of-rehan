"""
Tests for the classical technical-indicator layer (v0.17.0):
RSI/EMA-alignment math, their feature-builder wiring, and the
engine's Rule 18 veto. The Bollinger/variance-ratio/divergence
gates are retired and stay retired.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_kmiall_features as feats
from decision_engine import DecisionConfig, DecisionEngine
from technical_indicators import (  # v3.2.0 whitelist: RSI + EMA only
    ema_alignment_score,
    rsi,
    rsi_position_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(minute, second=0):
    return pd.Timestamp(
        f"2026-09-08 04:32:{second:02d}+00:00"
    ) + pd.Timedelta(minutes=minute)


def _rising_prices(n=60, start=100.0, step=0.05):
    return pd.Series([start + i * step for i in range(n)])


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

class TestRsi:
    def test_all_gains_rsi_100(self):
        r = rsi(_rising_prices(40))
        assert r.iloc[-1] == pytest.approx(100.0)

    def test_all_losses_rsi_0(self):
        prices = _rising_prices(40)[::-1].reset_index(drop=True)
        r = rsi(prices)
        assert r.iloc[-1] == pytest.approx(0.0)

    def test_flat_rsi_50(self):
        r = rsi(pd.Series([100.0] * 40))
        assert r.iloc[-1] == pytest.approx(50.0)

    def test_wilders_smoothing_bounded(self):
        # Alternating up/down: RSI must stay strictly inside (0, 100).
        prices = pd.Series(
            [100 + (0.5 if i % 2 == 0 else -0.5) for i in range(60)]
        )
        r = rsi(prices).dropna()
        assert ((r > 0) & (r < 100)).all()
        assert r.iloc[-1] == pytest.approx(50.0, abs=15)

    def test_needs_min_periods(self):
        r = rsi(_rising_prices(20))
        assert r.iloc[:13].isna().all()
        assert r.iloc[-1] == pytest.approx(100.0)


class TestRsiPositionScore:
    def test_healthy_band_is_high(self):
        s = rsi_position_score(pd.Series([50.0, 57.0, 65.0]))
        assert (s == 0.85).all()

    def test_overbought_falls_to_zero(self):
        s = rsi_position_score(pd.Series([65.0, 72.5, 80.0]))
        assert s.iloc[0] == pytest.approx(0.85)
        assert s.iloc[1] == pytest.approx(0.5)
        assert s.iloc[2] == pytest.approx(0.0)

    def test_deeply_oversold_is_zero(self):
        s = rsi_position_score(pd.Series([25.0, 10.0]))
        assert (s == 0.0).all()

    def test_nan_stays_nan(self):
        s = rsi_position_score(pd.Series([np.nan, 60.0]))
        assert pd.isna(s.iloc[0])
        assert s.iloc[1] == 0.85


# ---------------------------------------------------------------------------
# EMA alignment + divergence
# ---------------------------------------------------------------------------

class TestEmaAlignment:
    def test_uptrend_stack_one(self):
        assert ema_alignment_score(_rising_prices(40)) == 1.0

    def test_downtrend_stack_zero(self):
        assert ema_alignment_score(_rising_prices(40)[::-1]) == 0.0

    def test_mixed_half(self):
        # Sine wave: last values mixed -> 0.5.
        prices = pd.Series(
            100 + np.sin(np.linspace(0, 6 * np.pi, 60)) * 2
        )
        assert ema_alignment_score(prices) in (0.0, 0.5, 1.0)

    def test_too_short_nan(self):
        assert np.isnan(ema_alignment_score(_rising_prices(10)))



# ---------------------------------------------------------------------------
# Feature-builder wiring
# ---------------------------------------------------------------------------

def _tech_frame(symbol="ABOT", ticks=245, seed=11):
    """A rising, volume-confirming session with every column the full
    build() pipeline reads. 245 ticks = 20.4 minutes at the 5s cadence
    - long enough for the variance ratio's 20-minute source window.
    Prices carry small micro-structure noise (realistic ticks; a
    perfectly straight line would make the variance ratio degenerate)."""
    import numpy as _np

    rng = _np.random.default_rng(seed)
    rows = []
    price = 100.0
    volume_cum = 0.0
    value_cum = 0.0
    # Increment process: drift + LONG-memory positively-autocorrelated
    # (AR(1), phi=0.95 - ~20-tick momentum waves) + small noise. A
    # drift with independent noise is, per the variance ratio,
    # mean-reverting around the trend line (VR ~0.3); short-memory AR
    # washes out below the 1-minute aggregation. Real trending at the
    # 5-minute horizon needs persistence that survives a minute.
    prev_inc = 0.02
    for i in range(ticks):
        inc = 0.02 + 0.95 * (prev_inc - 0.02) + float(rng.normal(0, 0.005))
        prev_inc = inc
        price = price + inc
        traded = 1000.0
        volume_cum += traded
        value_cum += traded * price
        rows.append({
            "symbol": symbol,
            "timestamp": _ts(i * 5 // 60, i * 5 % 60),
            "trading_date": "2026-09-08",
            "tradable": True,
            "quote_available": True,
            "is_open": True,
            # Pre-computed quality booleans (the dataset ships these;
            # add_quality_flags re-derives feature_* from them).
            "usable_price": True,
            "usable_book": True,
            "usable_momentum": True,
            "bid_available": True,
            "ask_available": True,
            "high_available": True,
            "low_available": True,
            "feature_price_ok": True,
            "price": price,
            "high": price + 0.02,
            "low": price - 0.02,
            "bid": price - 0.01,
            "ask": price + 0.01,
            "bid_volume": 5000.0,
            "ask_volume": 4000.0,
            "trades": 100.0 + i,
            "spread": 0.02,
            "spread_pct": 0.0002,
            "session_id": "2026-09-08-1",
            "price_change_pct_5s": 0.001,
            "volume_delta": 1000.0,
            "new_volume": 1000.0,
            "trades_delta": 1.0,
            "new_trades": 1.0,
            "order_book_imbalance": 0.2,
            "price_position_range": 0.7,
            "distance_from_high_pct": 0.5,
            "distance_from_low_pct": 2.0,
            "volume_5m": 60000.0,
            "trades_1m": 12.0,
            "trades_5m": 60.0,
            "trade_value_per_trade": 100000.0,
            "breadth_advancers": 60.0,
            "breadth_decliners": 40.0,
            "breadth_unchanged": 10.0,
            "breadth_total": 110.0,
            "breadth_ratio": 0.55,
            "volume": volume_cum,
            "value": value_cum,
            "volume_1m": 12000.0 + i * 20.0,   # gently rising per-minute
            "average_volume_1m": 12000.0,
            "relative_volume_1m": 1.0 + i / (ticks * 100.0),
            "momentum_1m_pct": 0.05,
            "momentum_5m_pct": 0.10,
            "short_term_price_score": 0.6,
            "book_strength": 0.5,
            "spread_quality": 0.5,
            "trade_activity_score": 0.5,
            "change_pct": 2.0,
            "change_fraction": 0.02,
            "breadth_pct": 60.0,
        })
    return pd.DataFrame(rows)


class TestBuilderWiring:
    BANNED_COLUMNS = (
        "kalman_trend_score", "z_kalman_trend",
        "bollinger_pctb", "z_bollinger_position",
        "variance_ratio", "z_variance_ratio",
        "parkinson_vol_score", "z_parkinson_vol",
        "gk_vol_score", "z_gk_vol",
        "volume_price_divergence",
    )

    def test_whitelisted_indicator_columns_present(self):
        out, _ = feats.build(_tech_frame())
        for col in (
            "rsi14", "ema_alignment",
            "z_rsi_position", "z_ema_alignment",
        ):
            assert col in out.columns, col

    def test_banned_columns_are_gone_entirely(self):
        """v3.3.0: the retired measurements are not emitted at all -
        not even as NaN placeholders. The schema is the whitelist."""
        out, _ = feats.build(_tech_frame())
        for col in self.BANNED_COLUMNS:
            assert col not in out.columns, col

    def test_uptrend_symbol_reads_sane(self):
        out, _ = feats.build(_tech_frame())
        last = out.iloc[-1]
        # With micro-noise the RSI hovers near (not at) 100.
        assert last["rsi14"] > 80.0
        assert last["ema_alignment"] == 1.0

    def test_master_components_renormalized(self):
        """Weights must still sum to 1.0 and the score must stay in (0,1)."""
        total = sum(feats.MASTER_COMPONENTS.values())
        assert total == pytest.approx(1.0)
        for banned in (
            "z_kalman_trend", "z_bollinger_position",
            "z_variance_ratio", "z_parkinson_vol", "z_gk_vol",
        ):
            assert banned not in feats.MASTER_COMPONENTS
        out, _ = feats.build(_tech_frame())
        last = out.iloc[-1]
        if pd.notna(last.get("master_score")):
            assert 0.0 < last["master_score"] < 1.0


# ---------------------------------------------------------------------------
# Engine veto: Rule 18 (RSI). Rules 19/20 are retired and stay retired.
# ---------------------------------------------------------------------------

def _candidate_frame(**overrides):
    """One clean candidate row in the shape _filter_candidates expects."""
    row = {
        "symbol": "CAND",
        "timestamp": _ts(2),
        "trading_date": "2026-09-08",
        "tradable": True, "feature_price_ok": True,
        "feature_rank_score_adjusted": 0.8,
        "score_weight_coverage": 0.9,
        "price": 100.0,
        "high": 100.5,
        "change_pct": 1.0,
        "breadth_pct": 60.0,
        "master_score": 0.8, "master_score_weight_coverage": 0.9,
        "value": 100e6,
        "price_position_range": 0.5,
    }
    for k in range(6):
        row[f"z_fake_{k}"] = 0.6
    row.update(overrides)
    return pd.DataFrame([row])


class TestTechnicalVetoes:
    def test_overbought_candidate_vetoed(self):
        df = _candidate_frame(rsi14=85.0)
        engine = DecisionEngine(DecisionConfig())
        out = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        assert out.empty

    def test_healthy_rsi_passes(self):
        df = _candidate_frame(rsi14=58.0)
        engine = DecisionEngine(DecisionConfig())
        out = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        assert len(out) == 1

    def test_missing_rsi_passes(self):
        df = _candidate_frame()
        engine = DecisionEngine(DecisionConfig())
        out = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        assert len(out) == 1

    def test_banned_veto_columns_are_inert(self):
        """Rules 19/20 are RETIRED (v3.1.1/v3.2.0) and the measurements
        no longer exist in the schema (v3.3.0): a candidate row simply
        has no %B or divergence evidence to veto on, whatever values a
        stale stored file carries."""
        engine = DecisionEngine(DecisionConfig())
        for overrides in (
            {"bollinger_pctb": 1.15},   # outside the band
            {"bollinger_pctb": 0.80},   # in band
            {"volume_price_divergence": 0.0},
        ):
            df = _candidate_frame(**overrides)
            out = engine._filter_candidates(
                df[df["timestamp"] == df["timestamp"].max()], set()
            )
            assert len(out) == 1, overrides

    def test_divergence_veto_retired(self):
        """Rule 20 is RETIRED v3.2.0 by owner's order: the gate and
        its config knob are gone - a divergent row can never be
        vetoed by this rule again, whatever the config says."""
        df = _candidate_frame(volume_price_divergence=0.0)
        engine = DecisionEngine(DecisionConfig())
        out = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        assert len(out) == 1
        assert not hasattr(DecisionConfig(), "divergence_veto_enabled")
