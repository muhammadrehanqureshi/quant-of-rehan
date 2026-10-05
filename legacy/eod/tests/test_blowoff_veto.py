"""
Tests for the EOD veto layer (v2.3.0 - the refined corpus law).

Contracts pinned here:

  * apply_momentum_gate: only LOCKED closes (>=9.9%) survive, with the
    >=Rs 500M distribution trap vetoed (15.4% forward win, n=13);
    almost-locked (8.0-9.9%) refused with evidence (36.7% win);
  * apply_blowoff_veto: the close-at-extreme refusal applies ONLY to
    the sub-8% class (FABL signature) - inside the lock class a
    close at the high is the lock, never vetoed;
  * apply_lock_rank_bonus: 2nd lock day earns the top bonus (73.3%
    forward win), 3+ the half bonus, green-streak >=3 the streak bonus;
  * missing data never manufactures a veto (value absent = no trap).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from run_eod import (  # noqa: E402
    apply_blowoff_veto,
    apply_lock_rank_bonus,
    apply_momentum_gate,
)


def _pick(symbol, cp=None, chg=None, value=None):
    return {
        "symbol": symbol, "close_position": cp, "change_pct": chg,
        "value": value, "score": 0.7,
    }


# ------------------------- momentum gate -------------------------

def test_sub8_refused_with_evidence():
    kept, blocked = apply_momentum_gate([_pick("WEAK", chg=4.4)])
    assert kept == []
    sym, reason = blocked[0]
    assert sym == "WEAK" and "locked close line" in reason


def test_almost_locked_refused():
    # 8.0-9.9% wins only 36.7% - the lock seal is the edge.
    kept, blocked = apply_momentum_gate([_pick("NEARLY", chg=9.5)])
    assert kept == [] and "36.7%" in blocked[0][1]


def test_locked_class_kept():
    kept, blocked = apply_momentum_gate([_pick("LOCK", chg=9.9), _pick("BIG", chg=10.0)])
    assert [p["symbol"] for p in kept] == ["LOCK", "BIG"] and blocked == []


def test_boundary_exactly_9_9_kept():
    kept, _ = apply_momentum_gate([_pick("EDGE", chg=9.9)])
    assert [p["symbol"] for p in kept] == ["EDGE"]


def test_distribution_trap_vetoed():
    kept, blocked = apply_momentum_gate([_pick("CROWD", chg=10.0, value=500_000_000)])
    assert kept == [] and "distribution trap" in blocked[0][1]


def test_huge_value_missing_passes():
    # Missing value must never manufacture the trap veto.
    kept, blocked = apply_momentum_gate([_pick("NOVAL", chg=10.0, value=None)])
    assert [p["symbol"] for p in kept] == ["NOVAL"] and blocked == []


def test_healthy_value_kept():
    kept, blocked = apply_momentum_gate([_pick("OK", chg=10.0, value=80_000_000)])
    assert [p["symbol"] for p in kept] == ["OK"] and blocked == []


def test_missing_change_disqualified():
    kept, blocked = apply_momentum_gate([_pick("NODATA", chg=None)])
    assert kept == [] and len(blocked) == 1


# ------------------------- lock-history rank bonus -------------------------

def test_second_lock_day_gets_top_bonus():
    picks = apply_lock_rank_bonus(
        [_pick("L2", chg=10.0)],
        {"L2": [{"chg": 10.0, "c": 11.0}]},  # yesterday also locked
    )
    assert picks[0]["lock_days"] == 2
    assert picks[0]["lock_bonus"] >= 0.15


def test_first_lock_day_gets_no_lock_bonus():
    picks = apply_lock_rank_bonus(
        [_pick("L1", chg=10.0)],
        {"L1": [{"chg": 1.0, "c": 10.1}]},  # yesterday green, not locked
    )
    assert picks[0]["lock_days"] == 1
    assert picks[0]["lock_bonus"] < 0.15


def test_three_plus_lock_days_half_bonus():
    # History (newest last): two lock days, then an older down day -
    # consecutive locks ending today = 3, green streak = 4 (all positive).
    picks = apply_lock_rank_bonus(
        [_pick("L3", chg=10.0)],
        {"L3": [{"chg": -2.0, "c": 9.8}, {"chg": 10.0, "c": 11.9},
                {"chg": 10.0, "c": 13.1}]},
    )
    assert picks[0]["lock_days"] == 3
    assert picks[0]["green_streak"] == 3  # today + 2 positive prior sessions
    assert picks[0]["lock_bonus"] == 0.075  # half lock bonus, streak not ranked


def test_green_streak_is_evidence_not_bonus():
    # v2.3.1: the streak bonus is gone (collinear with lock_days and
    # it cost picks); the streak still travels on the card.
    picks = apply_lock_rank_bonus(
        [_pick("GS", chg=10.0)],
        {"GS": [{"chg": 2.0, "c": 8.2}, {"chg": 1.5, "c": 8.0}]},
    )
    assert picks[0]["green_streak"] == 3
    assert picks[0]["lock_bonus"] == 0.0  # first lock day: no bonus


def test_no_history_first_lock():
    picks = apply_lock_rank_bonus([_pick("NEW", chg=10.0)], None)
    assert picks[0]["lock_days"] == 1 and picks[0]["lock_bonus"] == 0.0


# ------------------------- blow-off veto -------------------------

def test_sub8_close_at_extreme_refused():
    # The FABL signature: +1.85% day picked at close_position 1.00.
    kept, blocked = apply_blowoff_veto([_pick("FABL", cp=1.00, chg=1.85)])
    assert kept == [] and "exhaustion" in blocked[0][1]


def test_momentum_close_at_extreme_never_vetoed():
    # In the >=8% class the lock close IS the edge - the veto stands down.
    kept, blocked = apply_blowoff_veto([_pick("LOCK", cp=1.00, chg=9.5)])
    assert len(kept) == 1 and blocked == []


def test_missing_close_position_passes():
    p = _pick("NODATA", cp=None, chg=3.0)
    kept, blocked = apply_blowoff_veto([p])
    assert kept == [p] and blocked == []


def test_missing_change_treated_as_sub8():
    # No extension evidence = not proven momentum = the veto applies.
    kept, blocked = apply_blowoff_veto([_pick("UNPROVEN", cp=1.00, chg=None)])
    assert kept == [] and len(blocked) == 1
