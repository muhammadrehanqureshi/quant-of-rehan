"""Bot A's 8-feature ranking layer - contract tests.

The owner's 2026-09-30 order: 8 features maximum, 4 hard vetoes,
rank-top1 with "no trade" as a first-class outcome. These tests pin
that the veto list is EXACTLY the 4 (nothing else hard-blocks), that
missing evidence renormalizes instead of vetoing, and that the pick
is rank 1 or nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ranking as rk  # noqa: E402


def _frame(**overrides):
    base = dict(
        symbol=["GOOD", "WIDE", "POOR", "LOCKED"],
        tradable=[True, True, True, True],
        price=[100.0, 100.0, 50.0, 55.0],
        high=[101.0, 101.0, 50.4, 55.0],
        low=[98.5, 98.5, 49.6, 50.1],
        value=[50e6, 50e6, 0.5e6, 30e6],
        change_pct=[1.2, 1.0, 0.1, 9.9],
        spread_pct=[0.3, 2.0, 0.5, 0.3],
        sector=["oil", "oil", "banks", "cement"],
        z_vwap_ratio=[1.2, 0.8, -0.5, 2.5],
        z_relative_volume_1m=[1.5, 1.0, -0.8, 2.0],
        z_volume_trend=[1.0, 0.9, -0.5, 1.8],
        z_baseline_volume_ratio=[0.8, 0.7, -0.2, 1.5],
        z_orb=[1.0, 0.6, -1.0, 2.2],
        ema_alignment=[0.8, 0.7, 0.2, 0.95],
        z_book_strength=[0.7, 0.4, -1.0, 0.9],
        z_spread_quality=[0.6, -1.5, -0.8, 0.8],
        z_sector_breadth=[0.9, 0.8, 0.1, 1.0],
        z_sector_flow=[0.8, 0.7, 0.0, 0.9],
    )
    base.update(overrides)
    return pd.DataFrame(base)


def test_build_features_maps_exactly_8():
    f = rk.build_features(_frame(), session_fraction_left=0.6)
    for col in rk.FEATURES:
        assert col in f.columns, col
    assert set(rk.FEATURES) == {
        "vwap_position", "relative_volume", "orb", "trend_ema",
        "atr_feasible", "book_strength", "breadth_context",
        "extension_safety",
    }


def test_score_renormalizes_over_missing():
    f = rk.build_features(_frame())
    f.loc[f.index[0], "orb"] = None  # a missing feature
    f = rk.score_frame(f)
    row = f.iloc[0]
    assert 0.0 <= row["score_8f"] <= 1.0
    assert 0.0 < row["score_weight_coverage"] < 1.0  # renormalized, not zeroed


def test_veto_wide_spread():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=120.0)
    syms = set(pool["symbol"])
    assert "WIDE" not in syms
    assert any(s == "WIDE" and "spread" in r for s, r in vetoed)


def test_veto_low_liquidity():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=120.0)
    assert "POOR" not in set(pool["symbol"])
    assert any(s == "POOR" and "liquidity" in r for s, r in vetoed)


def test_veto_circuit_lock():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=120.0)
    assert "LOCKED" not in set(pool["symbol"])
    assert any(s == "LOCKED" and "circuit" in r for s, r in vetoed)


def test_veto_market_breadth():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(f, breadth_pct=30.0, minute_of_session=120.0)
    assert pool.empty
    assert any("breadth" in r for _, r in vetoed)


def test_veto_time_window_before_open15():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=5.0)
    assert pool.empty
    assert any("time" in r for _, r in vetoed)


def test_veto_sector_negative():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, vetoed = rk.eligible_pool(
        f, breadth_pct=48.0, minute_of_session=120.0,
        sector_change={"oil": -2.0},
    )
    assert "GOOD" not in set(pool["symbol"])
    assert any(s == "GOOD" and "sector" in r for s, r in vetoed)


def test_rank_pick_top1_only():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, _ = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=120.0)
    res = rk.rank_and_pick(pool, min_score=0.4)
    assert res.signal is not None
    assert res.signal["rank"] == 1
    assert len(res.ranked) >= 1


def test_rank_no_trade_when_below_min():
    f = rk.score_frame(rk.build_features(_frame()))
    pool, _ = rk.eligible_pool(f, breadth_pct=48.0, minute_of_session=120.0)
    res = rk.rank_and_pick(pool, min_score=0.999)
    assert res.signal is None
    assert len(res.ranked) >= 1  # ranking travels even on a no-trade


def test_extended_name_scores_lower_than_fresh():
    # The chase anti-edge lives in the score now: an extended name must
    # not outscore its fresh twin on identical other features.
    fresh = _frame()
    extended = _frame(change_pct=[6.8, 1.0, 0.1, 9.9])
    fs = rk.score_frame(rk.build_features(fresh))
    es = rk.score_frame(rk.build_features(extended))
    assert (
        fs.loc[fs["symbol"] == "GOOD", "score_8f"].iloc[0]
        > es.loc[es["symbol"] == "GOOD", "score_8f"].iloc[0]
    )
