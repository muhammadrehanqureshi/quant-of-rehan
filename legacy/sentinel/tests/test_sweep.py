"""Tests for the data-driven rule sweeper (src/sweep.py).

The sweeper replaces hand-picked thresholds, so its own math must be
airtight: fee stack, gate semantics (vwap_ratio >= 0 means ABOVE vwap),
forward-only exit pricing, the honest book (slot frees at exit minute,
3/day cap), and worst-session winner selection.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import sweep  # noqa: E402
from sweep import Rulebook, _minutes_since_open, _price_exit  # noqa: E402


# ---------------------------------------------------------------------------
# Fee stack - the owner's real costs, verified against his specification
# ---------------------------------------------------------------------------

def test_round_trip_cost_matches_owner_spec():
    # broker 0.15% x2 + levies 0.05% x2 + SST 16% of broker x2
    # + slippage 0.20% x2
    expected = 2.0 * (0.15 + 0.05 + 0.15 * 0.16) + 2.0 * 0.20
    assert sweep.COSTS_PCT == pytest.approx(expected, abs=1e-6)
    assert sweep.COSTS_PCT == pytest.approx(0.848, abs=0.01)


# ---------------------------------------------------------------------------
# Gate semantics
# ---------------------------------------------------------------------------

def test_vwap_above_means_ge_zero_not_one():
    rb = Rulebook()
    row = _row(vwap_ratio=0.004, score=0.9, evidence=8)
    assert sweep._passes_stock_gates(row, rb) is True
    row_below = _row(vwap_ratio=-0.003, score=0.9, evidence=8)
    assert sweep._passes_stock_gates(row_below, rb) is False


def test_rows_without_kalman_pass_all_gates():
    """v3.1.1 retired the Kalman gate from the sweep rulebook;
    v3.2.2 deleted the capture field outright. A row without it
    passes on its own evidence."""
    rb = Rulebook()
    no_kalman = _row(score=0.9, evidence=8)
    assert sweep._passes_stock_gates(no_kalman, rb) is True


def test_breadth_floor_and_window():
    rb = Rulebook(hard_min_breadth_pct=35.0, opening_hold_minutes=30.0)
    assert sweep._passes_market_gates(
        _row(breadth=34.9, minutes_open=120.0), rb
    ) is False
    assert sweep._passes_market_gates(
        _row(breadth=35.0, minutes_open=120.0), rb
    ) is True
    assert sweep._passes_market_gates(
        _row(breadth=80.0, minutes_open=29.0), rb
    ) is False
    # Unknown clock (None) passes - never blocks on missing data.
    assert sweep._passes_market_gates(
        _row(breadth=80.0, minutes_open=None), rb
    ) is True


def test_green_tape_gate():
    rb = Rulebook(green_tape_only=True)
    assert sweep._passes_market_gates(_row(market_vw=-0.1), rb) is False
    assert sweep._passes_market_gates(_row(market_vw=0.0), rb) is True
    assert sweep._passes_market_gates(_row(market_vw=None), rb) is False
    rb_off = Rulebook(green_tape_only=False)
    assert sweep._passes_market_gates(_row(market_vw=-0.1), rb_off) is True


def test_minutes_since_open_afternoon_leg_semantics():
    opens = [572, 872]  # 09:32 and 14:32
    assert _minutes_since_open(_hm(9, 40), opens) == 8.0
    assert _minutes_since_open(_hm(9, 20), opens) is None  # pre-open
    # Inside the afternoon leg's own open window: not a fresh open.
    assert _minutes_since_open(_hm(14, 40), opens) is None
    # Afternoon, well past its leg open: window does not apply.
    assert _minutes_since_open(_hm(15, 10), opens) == 999.0


def _hm(h: int, m: int):
    from datetime import datetime
    return datetime(2026, 9, 14, h, m)


# ---------------------------------------------------------------------------
# Exit pricing
# ---------------------------------------------------------------------------

def test_exit_target_and_stop_net_of_costs():
    rb = Rulebook(profit_target_pct=2.0, max_loss_pct=1.5)
    pnl, _ = _price_exit([[0.0, 100.0], [5.0, 102.0]], 100.0, rb)
    assert pnl == pytest.approx(2.0 - sweep.COSTS_PCT)
    pnl, _ = _price_exit([[0.0, 100.0], [5.0, 98.5]], 100.0, rb)
    assert pnl == pytest.approx(-1.5 - sweep.COSTS_PCT)


def test_exit_forward_only_no_pre_entry_fills():
    rb = Rulebook(profit_target_pct=2.0, max_loss_pct=1.5)
    # Pre-entry price would have hit the target; the trade must NOT be
    # priced from history.
    path = [[-3.0, 103.0], [0.0, 100.0], [4.0, 100.4]]
    pnl, exit_min = _price_exit(path, 100.0, rb)
    assert pnl == pytest.approx((100.4 / 100 - 1) * 100 - sweep.COSTS_PCT)
    assert exit_min == 4.0


def test_exit_trail_activates_and_dumps():
    rb = Rulebook(profit_target_pct=99.0, max_loss_pct=99.0)
    path = [[0.0, 100.0], [2.0, 101.5], [6.0, 101.0]]
    pnl, _ = _price_exit(path, 100.0, rb)
    # Trail activates at +1.0 (best 101.5 -> stop 100.9925); 101.0 <= stop.
    expected = (101.0 / 100.0 - 1) * 100 - sweep.COSTS_PCT
    assert pnl == pytest.approx(expected, abs=1e-4)


def test_exit_time_fallback_at_last_price():
    rb = Rulebook(profit_target_pct=2.0, max_loss_pct=1.5)
    pnl, exit_min = _price_exit(
        [[0.0, 100.0], [10.0, 100.6]], 100.0, rb
    )
    assert pnl == pytest.approx(0.6 - sweep.COSTS_PCT)
    assert exit_min == 10.0


# ---------------------------------------------------------------------------
# The honest book
# ---------------------------------------------------------------------------

def _row(**over) -> dict:
    base = {
        "ts": "10:00", "ts_min": 600, "symbol": "X", "price": 100.0,
        "score": 0.7, "vwap_ratio": 0.01, "evidence": 8,
        "off_low": 1.0, "change_pct": 2.0, "day_value": 20e6,
        "breadth": 45.0, "market_vw": 0.3, "minutes_open": 120.0,
        "sector": "s", "sector_change": 0.5,
        "path": [[0.0, 100.0], [30.0, 100.2]], "date": "d1",
    }
    base.update(over)
    return base


def _flat_path(pnl_px: float, minutes: float = 30.0) -> list:
    return [[0.0, 100.0], [minutes, pnl_px]]


def test_book_slot_frees_at_exit_minute():
    # Trade 1 exits at +10 min (TP); a second candidate at +12 min must
    # be takeable - the slot is not held for the rest of the day.
    s1 = [
        _row(ts="10:00", ts_min=600, symbol="A",
             path=[[0.0, 100.0], [10.0, 102.5]]),
        _row(ts="10:12", ts_min=612, symbol="B",
             path=[[0.0, 100.0], [10.0, 102.5]]),
    ]
    rb = Rulebook(hard_min_breadth_pct=0.0, opening_hold_minutes=0.0,
                  green_tape_only=False)
    res = sweep.simulate([s1], rb)
    assert res.n == 2


def test_book_three_per_day_cap():
    rows = [
        _row(ts_min=600 + i * 15, symbol=c,
             path=[[0.0, 100.0], [10.0, 102.5]])
        for i, c in enumerate("ABCD")
    ]
    rb = Rulebook(hard_min_breadth_pct=0.0, opening_hold_minutes=0.0,
                  green_tape_only=False)
    res = sweep.simulate([rows], rb)
    assert res.n == 3


def test_no_reentry_same_symbol_while_held():
    # Same symbol again 2 min after entry (still held, 20-min exit) -
    # must be skipped, not double-entered.
    s1 = [
        _row(ts_min=600, symbol="A", path=[[0.0, 100.0], [20.0, 100.5]]),
        _row(ts_min=612, symbol="A", path=[[0.0, 100.0], [20.0, 100.5]]),
    ]
    rb = Rulebook(hard_min_breadth_pct=0.0, opening_hold_minutes=0.0,
                  green_tape_only=False)
    res = sweep.simulate([s1], rb)
    assert res.n == 1


# ---------------------------------------------------------------------------
# Winner selection: worst-session robustness, minimum trade count
# ---------------------------------------------------------------------------

def test_winner_is_robust_not_lucky(monkeypatch):
    monkeypatch.setattr(sweep, "MIN_TRADES_FOR_WINNER", 2)
    d1 = [
        _row(ts_min=600, symbol="A",
             path=[[0.0, 100.0], [10.0, 103.0]]),  # +3% TP both books
    ]
    d2 = [
        _row(ts_min=600, symbol="A",
             path=[[0.0, 100.0], [10.0, 103.0]]),
    ]
    results = sweep.evaluate(
        [d1, d2],
        books=[
            Rulebook(hard_min_breadth_pct=0.0, opening_hold_minutes=0.0,
                     green_tape_only=False),
        ],
    )
    assert results["winner"] is not None
    w = results["winner"]
    assert w["n"] == 2
    assert w["win_rate"] == 1.0
    # Both session folds positive.
    assert all(f > 0 for f in w["session_avgs"])


def test_winner_requires_min_trades():
    d1 = [_row(ts_min=600, symbol="A",
               path=[[0.0, 100.0], [10.0, 103.0]])]
    results = sweep.evaluate(
        [d1],
        books=[Rulebook(hard_min_breadth_pct=0.0,
                        opening_hold_minutes=0.0,
                        green_tape_only=False)],
    )
    # 1 trade < MIN_TRADES_FOR_WINNER -> no winner crowned.
    assert results["winner"] is None
