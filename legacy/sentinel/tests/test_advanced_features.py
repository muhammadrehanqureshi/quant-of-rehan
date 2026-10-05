"""
Tests for the advanced feature layer - sector breadth, master score,
and the decision engine's use of both.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pathlib import Path

import build_kmiall_features as feats
from decision_engine import DecisionConfig, DecisionEngine


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Fixture: a minimal but well-formed feature frame with advanced columns
# ---------------------------------------------------------------------------

def _frame(symbols, *, sector_breadths=None, master_scores=None,
           timestamps=None, evidence=6):
    if timestamps is None:
        timestamps = pd.to_datetime(["2026-09-04T05:30:00+00:00"])
    n_ts = len(timestamps)
    rows = []
    for i, sym in enumerate(symbols):
        for ts in timestamps:
            row = {
                "symbol": sym,
                "timestamp": ts,
                "trading_date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                "tradable": True,
                "feature_price_ok": True,
                "feature_rank_score_adjusted": 0.5,
                "score_weight_coverage": 0.9,
                "price": 100.0 + i,
                # Red on the day contradicts a long signal - the
                # red-tape floor would reject MEBL before the score
                # fallback under test could act. Keep every symbol
                # green/flat so the score logic alone decides.
                "change_pct": abs(float(i - len(symbols) / 2)),
                "price_position_range": 0.5,
                "breadth_pct": 60.0,
                "master_score": (
                    master_scores[i] if master_scores else 0.5 + i * 0.01
                ),
                "master_score_weight_coverage": 0.9,
                "sector_breadth": (
                    sector_breadths[i] if sector_breadths else 0.5
                ),
                "momentum_1m_pct": 0.1,
            }
            for k in range(max(evidence, 0)):
                row[f"z_fake_{k}"] = 0.6
            rows.append(row)
    return pd.DataFrame(rows)


class TestSectorBreadth:
    def test_computed_from_frame(self):
        # 3 symbols in "cement", 2 advancing
        df = pd.DataFrame({
            "timestamp": pd.to_datetime(["2026-09-04"] * 3),
            "sector": ["cement", "cement", "cement"],
            "change_pct": [1.0, -1.0, 2.0],
            "tradable": [True, True, True],
            "_adv": [1.0, 0.0, 1.0],
        })
        breadth = df.groupby(["timestamp", "sector"])["_adv"].mean()
        assert breadth.iloc[0] == pytest.approx(2 / 3)


class TestMasterScoreLayer:
    def test_master_score_in_build(self):
        """
        Full integration: the real archived dataset must build with a
        master_score column, non-null coverage, and sane values.

        Skipped (not failed) when the dataset is absent, so the suite
        still runs green on a fresh checkout.
        """
        pytest.importorskip("pandas")
        csv = _project_root() / "data" / "processed" / "kmiall_intraday.csv"
        if not csv.exists():
            pytest.skip("No intraday dataset on disk")
        df = feats.load_dataset(csv)
        out, summary = feats.build(df, top=3)
        assert "master_score" in out.columns
        assert "master_score_weight_coverage" in out.columns
        scored = out["master_score"].notna().sum()
        assert scored > 0
        assert out["master_score_weight_coverage"].dropna().between(0, 1).all()
        # Scores live in (0, 1) - never NaN-masked to an extreme.
        s = out["master_score"].dropna()
        assert s.between(0, 1).all()
        assert s.max() < 1.0 and s.min() > 0.0


class TestDecisionEngineMaster:
    def test_prefers_master_score(self):
        # ABOT has the higher master score; MEBL the higher rank score.
        # The engine must pick by master when present.
        df = _frame(
            ["ABOT", "MEBL"],
            master_scores=[0.8, 0.4],
        )
        df.loc[df["symbol"] == "MEBL", "feature_rank_score_adjusted"] = 0.95
        df.loc[df["symbol"] == "ABOT", "feature_rank_score_adjusted"] = 0.5

        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.symbol == "ABOT"
        assert decision.metadata.get("score_kind") == "master"
        assert decision.score == pytest.approx(0.8)

    def test_falls_back_to_rank_score(self):
        df = _frame(["ABOT", "MEBL"], master_scores=[np.nan, np.nan])
        df.loc[df["symbol"] == "MEBL", "feature_rank_score_adjusted"] = 0.95
        df.loc[df["symbol"] == "ABOT", "feature_rank_score_adjusted"] = 0.5

        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.symbol == "MEBL"
        assert decision.metadata.get("score_kind") == "rank"

    def test_prefers_master_can_be_disabled(self):
        df = _frame(["ABOT", "MEBL"], master_scores=[0.8, 0.4])
        df.loc[df["symbol"] == "MEBL", "feature_rank_score_adjusted"] = 0.95
        df.loc[df["symbol"] == "ABOT", "feature_rank_score_adjusted"] = 0.5

        engine = DecisionEngine(
            DecisionConfig(prefer_master_score=False, dead_zone_veto_enabled=False)
        )
        decision = engine.evaluate(df)
        assert decision.symbol == "MEBL"

    def test_missing_master_column_uses_rank(self):
        df = _frame(["ABOT", "MEBL"])
        df = df.drop(columns=["master_score", "master_score_weight_coverage"])
        df.loc[df["symbol"] == "MEBL", "feature_rank_score_adjusted"] = 0.95

        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.symbol == "MEBL"


class TestDecisionEngineCorrelationBlocking:
    """v3.2.0: the correlation gate is RETIRED by owner's order.
    These tests prove the retirement cannot resurrect: a candidate
    perfectly correlated with the held position is now picked on its
    own merits (the one-call-per-day law owns duplicate exposure)."""

    def _frame_with_history(self):
        """Several timestamps of prices. CLONE's returns track HELD's
        exactly; OTHER's are independent."""
        held = [100.0, 101.0, 102.5, 103.0, 105.0, 106.5]
        clone = [50.0, 50.5, 51.25, 51.5, 52.5, 53.25]   # same returns
        other = [80.0, 79.5, 80.2, 79.8, 80.1, 79.9]     # independent
        series_map = {"HELD": held, "CLONE": clone, "OTHER": other}
        n_ts = len(held)
        timestamps = pd.to_datetime(
            [f"2026-09-04T05:3{i}:00+00:00" for i in range(n_ts)]
        )
        rows = []
        for i, t in enumerate(timestamps):
            for sym in ("HELD", "CLONE", "OTHER"):
                row = {
                    "symbol": sym,
                    "timestamp": t,
                    "trading_date": "2026-09-04",
                    "tradable": True,
                    "feature_price_ok": True,
                    "feature_rank_score_adjusted": 0.9 if sym == "CLONE" else 0.5,
                    "score_weight_coverage": 0.9,
                    "price": series_map[sym][i],
                    "change_pct": 0.5,
                    "price_position_range": 0.5,
                    "breadth_pct": 60.0,
                    "master_score": (
                        0.9 if sym == "CLONE"
                        else (0.7 if sym == "OTHER" else 0.5)
                    ),
                    "master_score_weight_coverage": 0.9,
                }
                for k in range(6):
                    row[f"z_fake_{k}"] = 0.6
                rows.append(row)
        return pd.DataFrame(rows)

    def test_correlated_candidate_no_longer_blocked(self):
        df = self._frame_with_history()
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        # HELD is held; CLONE (top scorer) is perfectly correlated with
        # it - and still wins, because the gate is retired.
        decision = engine.evaluate(df, held_symbols={"HELD"})
        assert decision.symbol == "CLONE"
        assert "correlation_blocked" not in decision.metadata
