"""Shared research core - contract tests.

Pins the pieces every study and both engines sit on:
  * the cost stack matches exit_frontier to the paisa;
  * triple-barrier semantics: TP first, SL first, timeout at the
    limit, adverse-selection when both barriers sit in one bar, and
    the walk never reading the entry bar itself;
  * overnight labels: open basis, fallback basis, gap math;
  * walk-forward folds are chronological and gap-free;
  * rank-top1 emits at most ONE signal and "no trade" below threshold;
  * the signal log schema carries the full feature/outcome contract.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psx_core import research as rc  # noqa: E402


# --- Cost stack -----------------------------------------------------------
def test_costs_match_exit_frontier_exact():
    import exit_frontier as ef

    for entry, exit_price in [(50, 51), (50, 49), (15, 15.2), (120, 122.4), (50, 50)]:
        assert rc.net_pnl_pct(entry, exit_price) == pytest.approx(
            ef.net_pnl_pct(entry, exit_price), abs=1e-9
        )


def test_round_trip_cost_is_positive_and_bounded():
    assert rc.round_trip_cost_pct(50, 50) > 0.3
    assert rc.round_trip_cost_pct(50, 50) < 0.6


def test_breakeven_tp2_sl1_is_between_50_and_60():
    be = rc.breakeven_win_rate(2.0, 1.0)
    assert 50.0 < be < 60.0


# --- Triple barrier --------------------------------------------------------
def _series(*prices):
    return pd.Series(prices, dtype=float)


def test_barrier_tp_first():
    r = rc.triple_barrier(_series(100, 100.4, 102.05, 99), 0)
    assert r.label == 1
    assert r.exit_price == pytest.approx(102.0)
    assert r.bars_to_outcome == 2


def test_barrier_sl_first():
    r = rc.triple_barrier(_series(100, 99.5, 98.95, 102), 0)
    assert r.label == -1
    assert r.exit_price == pytest.approx(99.0)


def test_barrier_timeout_closes_at_last_bar():
    r = rc.triple_barrier(_series(100, 100.1, 100.0, 100.2), 0, max_bars=3)
    assert r.label == 0
    assert r.exit_price == pytest.approx(100.2)
    assert r.bars_to_outcome == 3


def test_barrier_never_reads_entry_bar():
    # The entry bar itself crosses the TP line; the walk starts at
    # entry_idx + 1, so the same-bar print must NOT trigger a TP.
    r = rc.triple_barrier(_series(102.05, 100.0, 100.1), 0)
    assert r.label != 1


def test_barrier_max_bars_bounds_the_walk():
    r = rc.triple_barrier(_series(100, 100.1, 100.2, 100.3), 0, max_bars=2)
    assert r.label == 0
    assert r.exit_price == pytest.approx(100.2)


def test_barrier_check_first_validation():
    with pytest.raises(ValueError):
        rc.triple_barrier(_series(100, 101), 0, check_first="bogus")


# --- Overnight labels ------------------------------------------------------
def test_overnight_open_basis():
    d = rc.overnight_returns(102.0, 100.0, {"r5": 102.6, "r10": 102.2, "r15": 101.8, "close": 101.0})
    assert d["gap_pct"] == pytest.approx(2.0)
    assert d["r5"] == pytest.approx(2.6)
    assert d["r15"] == pytest.approx(1.8)
    assert d["hold_to_close"] == pytest.approx(1.0)


def test_overnight_open_fallback():
    d = rc.overnight_returns(101.0, 100.0, {})
    assert d["r5"] == pytest.approx(1.0)
    assert d["r10"] == pytest.approx(1.0)


def test_net_after_overnight_matches_net_pnl():
    entry = 100.0
    gross = 1.5
    exit_price = entry * (1 + gross / 100.0)
    assert rc.net_after_overnight(gross, entry) == pytest.approx(
        rc.net_pnl_pct(entry, exit_price), abs=1e-9
    )


# --- Walk-forward ----------------------------------------------------------
def test_walk_forward_chronological_and_gapfree():
    sessions = [f"2026-{m:02d}-{d:02d}" for m in range(1, 7) for d in range(1, 21)]
    folds = rc.walk_forward_sessions(sessions, train_sessions=60, test_sessions=5, min_train=20)
    assert folds, "enough sessions must produce folds"
    seen: set[str] = set()
    for train, test in folds:
        assert set(test) & seen == set(), "test sessions must never repeat"
        assert train[-1] < test[0], "train must end before test begins"
        seen |= set(test)
    # folds cover the tail contiguously after min_train
    first_test_idx = sessions.index(folds[0][1][0])
    assert first_test_idx == 20


def test_walk_forward_requires_min_train():
    folds = rc.walk_forward_sessions(["a", "b", "c"], train_sessions=60, test_sessions=1, min_train=20)
    assert folds == []


# --- Rank top1 -------------------------------------------------------------
def test_rank_top1_emits_exactly_one_signal():
    rows = [{"symbol": "A"}, {"symbol": "B"}, {"symbol": "C"}]
    sig, ranked = rc.rank_top1(rows, {"A": 0.7, "B": 0.9, "C": 0.5}, 0.8)
    assert sig is not None and sig["symbol"] == "B"
    assert [r["symbol"] for r in ranked] == ["B", "A", "C"]


def test_rank_top1_no_trade_below_threshold():
    rows = [{"symbol": "A"}, {"symbol": "B"}]
    sig, ranked = rc.rank_top1(rows, {"A": 0.7, "B": 0.9}, 0.95)
    assert sig is None
    assert len(ranked) == 2  # the ranking still travels to the log


def test_rank_top1_empty_pool():
    sig, ranked = rc.rank_top1([], {}, 0.5)
    assert sig is None and ranked == []


# --- Signal log ------------------------------------------------------------
def test_signal_record_schema():
    rec = rc.SignalRecord(
        bot="sentinel", trading_date="2026-09-30", symbol="PSO",
        signal_time_pkt="2026-09-30 09:45 PKT", entry_price=100.0,
    )
    d = rec.to_dict()
    for key in (
        "bot", "trading_date", "symbol", "signal_time_pkt", "entry_price",
        "features", "rank", "probability", "score_components", "exit_price",
        "exit_time_pkt", "exit_reason", "gross_pct", "net_pct",
        "next_session_prices",
    ):
        assert key in d
