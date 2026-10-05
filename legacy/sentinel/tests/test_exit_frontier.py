"""
Tests for the exit-frontier simulator's policy replay.

The simulator is the measuring instrument for exit-policy decisions, so
its barrier semantics and cost model must be exact:
  * target fills AT the target (limit order);
  * stop fills AT the breaching level (market order);
  * costs are the REAL PSX schedule: commission 0.15% of value per side
    for stocks > 20 PKR (0.03 PKR/share for cheaper), SST 16% of the
    commission, ~0.05% levies per side, 15% CGT on gross wins;
  * trailing ratchets upward only and activates above the threshold;
  * the stale-trade timeout exits below the gain gate at market;
  * no barrier hit -> time exit at the last tick.
"""

from __future__ import annotations

import pytest

import exit_frontier as ef
from exit_frontier import replay_policy

T0 = "2026-09-07T05:00:00"


def _path(prices: list[float], step_min: int = 1) -> list[tuple[str, float]]:
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(T0)
    return [
        ((base + timedelta(minutes=i * step_min)).isoformat(), px)
        for i, px in enumerate(prices)
    ]


def _side(price: float) -> float:
    """Expected one-side cost in PKR/share (commission+SST+levies)."""
    return ef._side_cost_pkr(price)


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

def test_side_cost_above_20_pkr_band():
    # 0.15% commission + 16% SST on it + 0.05% levies (all of value).
    assert _side(100.0) == pytest.approx(0.15 * 1.16 + 0.05)
    assert _side(21.0) == pytest.approx((0.0015 * 1.16 + 0.0005) * 21.0)


def test_side_cost_per_share_below_20_pkr_band():
    # 0.03 PKR/share commission (flat), SST on it, levies on value.
    assert _side(20.0) == pytest.approx(0.03 * 1.16 + 0.05 * 0.20)
    assert _side(10.0) == pytest.approx(0.03 * 1.16 + 0.05 * 0.10)


def test_round_trip_pct_defaults_to_value_band():
    # 2 * (0.15% * 1.16 + 0.05%) = 0.448% of traded value.
    assert ef.round_trip_cost_pct(100.0, 100.0) == pytest.approx(0.448)


# ---------------------------------------------------------------------------
# Barrier semantics under the full cost stack
# ---------------------------------------------------------------------------

def test_target_fills_at_target_after_costs():
    # Fill at 101.0 from 100.0: gross +1.0 PKR/share; costs 0.224 +
    # 0.22624; CGT 0.15. Net = 1 - 0.45024 - 0.15 = +0.39976%.
    pnl, kind = replay_policy(
        _path([100.0, 101.2]), 100.0,
        target_pct=1.0, stop_pct=1.5,
        trail_activation_pct=10**9, trail_pct=0,
    )
    assert kind == "target"
    assert pnl == pytest.approx(1.0 - _side(100.0) - _side(101.0) - 0.15)


def test_stop_fills_at_stop_after_costs():
    # Fill at 98.5: gross -1.5 PKR/share, costs 0.224 + 0.22064, no CGT.
    pnl, kind = replay_policy(
        _path([100.0, 98.4]), 100.0,
        target_pct=1.0, stop_pct=1.5,
        trail_activation_pct=10**9, trail_pct=0,
    )
    assert kind == "stop"
    assert pnl == pytest.approx(
        -(1.5 + _side(100.0) + _side(98.5)) 
    )


def test_trailing_ratchets_upward_only_and_locks_profit():
    # Rises to 101.9 (trail ratchets to 100.881); the next print 100.5
    # breaches it: fills AT the trailing level per the sim convention.
    pnl, kind = replay_policy(
        _path([100.0, 101.9, 100.5, 99.0]), 100.0,
        target_pct=2.0, stop_pct=1.5,
        trail_activation_pct=0.5, trail_pct=1.0,
    )
    assert kind == "stop"
    gross = 0.881
    assert pnl == pytest.approx(
        gross - _side(100.0) - _side(100.881) - 0.15 * gross
    )


def test_stale_timeout_exits_below_gain_gate():
    # 22 minutes with no meaningful gain -> stale exit at market (100.05).
    pnl, kind = replay_policy(
        _path([100.0, 100.1, 100.05], step_min=11), 100.0,
        target_pct=2.0, stop_pct=1.5,
        trail_activation_pct=10**9, trail_pct=0,
        stale_min=20, stale_gain_pct=0.3,
    )
    assert kind == "stale"
    gross = 0.05
    assert pnl == pytest.approx(
        gross - _side(100.0) - _side(100.05) - 0.15 * gross
    )


def test_stale_timeout_spares_a_mover():
    # Within the window the stock is above the gain gate: no stale exit;
    # it eventually reaches target.
    _, kind = replay_policy(
        _path([100.0, 100.4, 100.6, 102.2], step_min=8), 100.0,
        target_pct=2.0, stop_pct=1.5,
        trail_activation_pct=10**9, trail_pct=0,
        stale_min=20, stale_gain_pct=0.3,
    )
    assert kind == "target"


def test_no_barrier_time_exit_at_last_tick():
    pnl, kind = replay_policy(
        _path([100.0, 100.5, 101.0]), 100.0,
        target_pct=2.0, stop_pct=3.0,
        trail_activation_pct=10**9, trail_pct=0,
    )
    assert kind == "time"
    assert pnl == pytest.approx(1.0 - _side(100.0) - _side(101.0) - 0.15)


def test_cheap_stock_costs_halve_a_two_percent_target():
    # A 10 PKR stock paying 0.03 PKR/share per side: a +2% gross move
    # (10 -> 10.2) nets only ~0.9% after costs and CGT. This is why the
    # engine must not chase penny prints.
    pnl, kind = replay_policy(
        _path([10.0, 10.21]), 10.0,
        target_pct=2.0, stop_pct=1.5,
        trail_activation_pct=10**9, trail_pct=0,
    )
    assert kind == "target"
    gross = 0.2
    expected = (gross - _side(10.0) - _side(10.2) - 0.15 * gross) / 10.0 * 100
    assert pnl == pytest.approx(expected)
    assert pnl < 1.0  # half the gross gone


# ---------------------------------------------------------------------------
# Breakeven math
# ---------------------------------------------------------------------------

def test_breakeven_win_rate_value_band():
    # Default round trip 0.448%: tgt 2/stop 1.5 ->
    # 1.948 / (1.948 + 1.252) = 60.875%.
    assert ef.breakeven_win_rate(2.0, 1.5) == pytest.approx(60.875)
    # tgt 3/stop 1.5 -> 1.948 / (1.948 + 2.102).
    assert ef.breakeven_win_rate(3.0, 1.5) == pytest.approx(
        1.948 / (1.948 + 2.102) * 100.0
    )


def test_breakeven_win_rate_cheap_stock_band():
    # 10 PKR stock: round trip ~0.797% -> tgt 2/stop 1.5 breakeven
    # rises to ~66%.
    rt = ef.round_trip_cost_pct(10.0, 10.2)
    be = ef.breakeven_win_rate(2.0, 1.5, rt)
    assert be == pytest.approx((1.5 + rt) / (1.5 + rt + 1.7 - rt) * 100.0)
    assert be > 60.0


def test_grid_targets_are_in_tradable_band():
    # v0.11.0: the frontier only studies targets Mr. Rehan can actually
    # trade after real costs.
    assert min(ef.TARGETS) >= 2.0
    assert max(ef.TARGETS) <= 3.0
