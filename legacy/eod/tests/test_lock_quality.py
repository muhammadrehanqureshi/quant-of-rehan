"""Tests for the lock-quality gate (grind 8/9, v2.3.3).

Contract:
  * vetoes apply ONLY to locked closes (>=9.9%) - other picks pass;
  * volume-ratio ceiling: a lock on >5x 20-day volume is refused;
  * prior-day floor: a lock after a dead prior day is refused;
  * missing evidence never gates (None passes);
  * both gates together are what grind 9 validated (disc 68% / val 78%).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lock_quality_gate import apply_lock_quality  # noqa: E402


def _locked(**over):
    p = {"symbol": "FIL", "change_pct": 10.0}
    p.update(over)
    return p


def test_non_locked_pass_through():
    picks = [_locked(change_pct=5.0, volume_surge=99.0, prev_day_value=0)]
    kept, blocked = apply_lock_quality(picks)
    assert len(kept) == 1 and not blocked


def test_volume_ceiling_refuses_distribution_lock():
    picks = [_locked(volume_surge=7.2)]
    kept, blocked = apply_lock_quality(picks)
    assert not kept and len(blocked) == 1
    assert "distribution" in blocked[0][1]


def test_volume_ceiling_boundary_passes():
    kept, blocked = apply_lock_quality([_locked(volume_surge=5.0)])
    assert len(kept) == 1 and not blocked


def test_prior_day_floor_refuses_dead_participation():
    picks = [_locked(volume_surge=2.0, prev_day_value=300_000.0)]
    kept, blocked = apply_lock_quality(picks)
    assert not kept and len(blocked) == 1
    assert "follow-through" in blocked[0][1]


def test_missing_evidence_never_gates():
    picks = [_locked(volume_surge=None, prev_day_value=None)]
    kept, blocked = apply_lock_quality(picks)
    assert len(kept) == 1 and not blocked


def test_healthy_lock_survives_both_gates():
    picks = [_locked(volume_surge=3.1, prev_day_value=12_000_000.0)]
    kept, blocked = apply_lock_quality(picks)
    assert len(kept) == 1 and not blocked
