"""
Tests for v0.18.0 - the evidence-backed rulebook upgrade.

The 44-trade forensics + 450-panel mine found three structural killers:
  * the engine's top score tail was ANTI-predictive (11.6% vs 29.5%
    forward wins) -> Rule 22 score-ceiling veto;
  * only the tape-confirmed momentum cohort won forwards (36.7% of
    forward wins carried the entry-time markers)
    -> Rule 23 momentum-core cohort (retired again v3.1.1/v3.2.2);
  * the book held overnight and died on max-hold closes (1W/30L) ->
    Rule 6 only fires when the session is actually over.
"""

from __future__ import annotations

import pandas as pd
import pytest

from decision_engine import DecisionConfig, DecisionEngine
from portfolio import Portfolio, Position


def _frame(scores, evidence=6, master_scores=None):
    """One timestamp, symbols with the given (rank, evidence) profile."""
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


class TestRule22ScoreCeiling:
    def test_top_tail_vetoed_when_enabled(self):
        df = _frame([("ABOT", 0.75), ("MEBL", 0.60)])
        cfg = DecisionConfig(score_ceiling_veto=True, score_ceiling=0.70)
        decision = DecisionEngine(cfg).evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "Rule 22" in decision.reason
        assert decision.metadata["gate"] == "rule22_score_ceiling"

    def test_below_ceiling_enters_when_enabled(self):
        df = _frame([("ABOT", 0.65), ("MEBL", 0.55)])
        cfg = DecisionConfig(
            score_ceiling_veto=True, score_ceiling=0.70,
            dead_zone_veto_enabled=False,
        )
        decision = DecisionEngine(cfg).evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"

    def test_disabled_by_default(self):
        # Plain DecisionConfig() keeps the old behavior: 0.75 enters.
        df = _frame([("ABOT", 0.75), ("MEBL", 0.60)])
        decision = DecisionEngine(
            DecisionConfig(dead_zone_veto_enabled=False)
        ).evaluate(df)
        assert decision.action == "ENTER"


class TestRule23MomentumCore:
    """Rule 23 (the Kalman >= 0.80 momentum-core floor) is RETIRED
    v3.1.1 by owner's order and DELETED v3.2.2 in the dead-code sweep:
    the config fields no longer exist, so the gate can never be
    re-armed by accident."""

    def test_retired_knobs_are_gone(self):
        assert not hasattr(DecisionConfig(), "momentum_core_enabled")
        assert not hasattr(DecisionConfig(), "momentum_core_min_kalman")

    def test_candidates_enter_without_kalman_evidence(self):
        df = _frame([("ABOT", 0.65)])
        decision = DecisionEngine(
            DecisionConfig(dead_zone_veto_enabled=False)
        ).evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"


def json_trace(decision) -> str:
    return str(getattr(decision, "metadata", {}) or {})


class TestRule6SessionGuard:
    """Rule 6 (max-hold close) must not fire while the session is open."""

    def _book(self):
        pos = Position(
            symbol="ABOT", entry_price=100.0,
            entry_date="2026-09-17", target_price=102.0,
        )
        book = Portfolio(max_holding_days=1)
        book.positions = [pos]
        return book, pos

    def test_no_force_close_while_session_open(self, monkeypatch):
        book, pos = self._book()
        import psx_core.sessions as sessions

        monkeypatch.setattr(sessions, "is_open", lambda now: True)
        reason = book._check_exit_conditions(
            pos, current_price=100.5, current_date="2026-09-18",
            now=pd.Timestamp("2026-09-18T05:40:00+00:00").to_pydatetime(),
        )
        assert reason is None or "Rule 6" not in reason

    def test_force_close_after_session(self, monkeypatch):
        book, pos = self._book()
        import psx_core.sessions as sessions

        monkeypatch.setattr(sessions, "is_open", lambda now: False)
        reason = book._check_exit_conditions(
            pos, current_price=100.5, current_date="2026-09-18",
            now=pd.Timestamp("2026-09-18T11:00:00+00:00").to_pydatetime(),
        )
        assert reason is not None and "Rule 6" in reason
