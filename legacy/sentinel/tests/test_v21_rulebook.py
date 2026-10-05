"""
Tests for v2.1.0 - the 45-trade forensics rulebook.

The forensics (45 closed trades, 4W/41L) and the 450-panel forward-path
mine pinned four structural killers, each now a live guard:

  * Rule 13b - the lunch doldrums: 12:30-14:50 PKT entries won 5-10%
    of forwards, the worst hours of the PSX day. No entries fire
    inside the window; exits are unaffected.
  * entry context is stamped on every position (score, premium over
    the prior close, breadth) so the ledger can be mined
    feature-vs-outcome without forensics workarounds again.
"""

from __future__ import annotations

import pandas as pd
import pytest

from decision_engine import DecisionConfig, DecisionEngine
from portfolio import Position


def _frame_at(pkt_minutes, breadth=60.0):
    """One symbol, one poll at a given PKT minute-of-day (UTC frame)."""
    ts = pd.to_datetime(["2026-09-16T00:00:00+00:00"])[0] + pd.Timedelta(
        minutes=pkt_minutes - 300
    )
    row = {
        "symbol": "ABOT",
        "timestamp": ts,
        "tradable": True,
        "feature_price_ok": True,
        "feature_rank_score_adjusted": 0.8,
        "score_weight_coverage": 0.9,
        "price": 100.0,
        "change_pct": 0.5,
        "price_position_range": 0.4,
        "breadth_pct": breadth,
        "master_score": 0.8,
        "master_score_weight_coverage": 0.9,
        "value": 20_000_000.0,
        "vwap_ratio": 0.01,
    }
    for k in range(6):
        row[f"z_fake_{k}"] = 0.6
    return pd.DataFrame([row])


class TestRule13bLunchDoldrums:
    def test_blocked_inside_window(self):
        engine = DecisionEngine()
        decision = engine.evaluate(_frame_at(13 * 60 + 30))  # 13:30 PKT
        assert decision.action == "STAND_ASIDE"
        assert "Rule 13b" in decision.reason
        assert "13:30" in decision.reason

    def test_morning_leg_still_allowed(self):
        engine = DecisionEngine()
        decision = engine.evaluate(_frame_at(12 * 60 + 15))  # 12:15 PKT
        assert decision.action != "STAND_ASIDE" or "Rule 13b" not in decision.reason

    def test_late_leg_still_allowed(self):
        engine = DecisionEngine()
        decision = engine.evaluate(_frame_at(15 * 60 + 5))  # 15:05 PKT
        assert decision.action != "STAND_ASIDE" or "Rule 13b" not in decision.reason

    def test_window_disabled_by_config(self):
        engine = DecisionEngine(
            DecisionConfig(no_entry_window_start_min=0.0)
        )
        decision = engine.evaluate(_frame_at(13 * 60 + 30))
        assert "Rule 13b" not in decision.reason


class TestEntryContext:
    def test_position_stamps_entry_context(self):
        p = Position(
            symbol="ABOT",
            entry_price=100.0,
            entry_date="2026-09-18",
            target_price=103.0,
            entry_score=0.734,
            entry_change_pct=2.2,
            entry_breadth_pct=52.0,
        )
        assert p.entry_score == 0.734
        assert p.entry_change_pct == 2.2

    def test_round_trip_preserves_context(self):
        p = Position(
            symbol="ABOT",
            entry_price=100.0,
            entry_date="2026-09-18",
            target_price=103.0,
            entry_score=0.734,
            entry_change_pct=2.2,
            entry_breadth_pct=52.0,
        )
        restored = Position.from_dict(p.to_dict())
        assert restored.entry_score == 0.734
        assert restored.entry_change_pct == 2.2
        assert restored.entry_breadth_pct == 52.0

    def test_legacy_row_without_context_loads(self):
        legacy = {
            "symbol": "OLD",
            "entry_price": 50.0,
            "entry_date": "2026-09-01",
            "target_price": 51.0,
            "status": "CLOSED",
        }
        restored = Position.from_dict(legacy)
        assert restored.entry_score is None
        assert restored.entry_change_pct is None
