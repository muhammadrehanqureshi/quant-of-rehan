"""
Tests for the conviction gate - the anti-forcing rule.

The bot must only ENTER when a candidate clears BOTH quality bars:
  1. score >= min_master_score (0.55 default)
  2. >= min_evidence_components (5 default) distinct components

A weak field, early session, or sparse data must end in STAND_ASIDE
with the reason recorded - never the best-of-a-bad-lot ENTER.
"""

from __future__ import annotations

import pandas as pd
import pytest

from decision_engine import DecisionConfig, DecisionEngine


def _frame(scores, evidence=6, master_scores=None, dead_zone=True):
    """
    One timestamp, symbols with the given (rank, evidence) profile.

    scores: list of (symbol, rank_score) or (symbol, rank, master).
    dead_zone: the fixture's change_pct (0.5) sits in Rule 26's banned
    band; tests whose subject is NOT Rule 26 keep it disarmed.
    """
    if master_scores is None:
        master_scores = [s for _, s in scores]
    rows = []
    for i, item in enumerate(scores):
        symbol, rank = item[0], item[1]
        row = {
            "symbol": symbol,
            "timestamp": pd.to_datetime(["2026-09-04T05:30:00+00:00"])[0],
            "tradable": True,
            "feature_price_ok": True,
            "feature_rank_score_adjusted": rank,
            "score_weight_coverage": 0.9,
            "price": 100.0 + i,
            "change_pct": 0.5,
            "price_position_range": 0.4,
            "breadth_pct": 60.0,
            "master_score": master_scores[i],
            "master_score_weight_coverage": 0.9,
        }
        for k in range(max(evidence, 0)):
            row[f"z_fake_{k}"] = 0.6
        rows.append(row)
    return pd.DataFrame(rows)


class TestScoreGate:
    def test_below_gate_stands_aside(self):
        # Best candidate at 0.50 - neutral, no genuine signal. The old
        # engine would have ENTERed it as "best available".
        df = _frame([("ABOT", 0.50), ("MEBL", 0.45), ("OGDC", 0.40)])
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "conviction" in decision.reason.lower()
        assert decision.metadata["gate"] == "min_master_score"
        assert decision.metadata["best_score"] == pytest.approx(0.50)

    def test_above_gate_enters(self):
        df = _frame([("ABOT", 0.72), ("MEBL", 0.45)])
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"

    def test_gate_boundary_inclusive(self):
        # Exactly at the gate: 0.55 >= 0.55 passes.
        df = _frame([("ABOT", 0.55)])
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_gate_uses_master_score_not_rank(self):
        # Master 0.50 (below gate) even though rank is 0.90: the gate
        # reads the preferred score - the master - and stands aside.
        df = _frame(
            [("ABOT", 0.90)], master_scores=[0.50],
        )
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert decision.metadata["best_score"] == pytest.approx(0.50)

    def test_gate_configurable(self):
        # A stricter gate raises the bar; a lower one admits more.
        # (Rule 26 disarmed - this fixture's 0.5% day sits in its band
        # and the conviction gate is the subject here, not Rule 26.)
        df = _frame([("ABOT", 0.60)])
        strict = DecisionEngine(
            DecisionConfig(min_master_score=0.70, dead_zone_veto_enabled=False)
        )
        loose = DecisionEngine(
            DecisionConfig(min_master_score=0.50, dead_zone_veto_enabled=False)
        )
        assert strict.evaluate(df).action == "STAND_ASIDE"
        assert loose.evaluate(df).action == "ENTER"


class TestEvidenceGate:
    def test_thin_evidence_stands_aside(self):
        # Score is fine (0.8) but only 2 components behind it - the
        # signal is a two-column coincidence, not conviction.
        df = _frame([("ABOT", 0.80)], evidence=2)
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert decision.metadata["gate"] == "min_evidence_components"
        assert decision.metadata["evidence_count"] == 2

    def test_full_evidence_enters(self):
        df = _frame([("ABOT", 0.80)], evidence=6)
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_evidence_configurable(self):
        df = _frame([("ABOT", 0.80)], evidence=3)
        low_bar = DecisionEngine(DecisionConfig(min_evidence_components=2))
        assert low_bar.evaluate(df).action == "ENTER"

    def test_no_evidence_at_all_stands_aside(self):
        # A frame with neither z_* nor rank_* columns: evidence=0.
        df = _frame([("ABOT", 0.90)], evidence=0)
        engine = DecisionEngine(DecisionConfig(dead_zone_veto_enabled=False))
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert decision.metadata["evidence_count"] == 0


class TestGateReasonsAreAuditable:
    def test_stand_aside_carries_best_candidate(self):
        # Even when refusing, the decision records WHICH symbol almost
        # made it and why not - the user can see what the bot was
        # "thinking".
        df = _frame([("ABOT", 0.52), ("MEBL", 0.40)])
        engine = DecisionEngine(
            DecisionConfig(dead_zone_veto_enabled=False)
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert decision.metadata["best_symbol"] == "ABOT"
        assert "no genuine signal" in decision.reason
