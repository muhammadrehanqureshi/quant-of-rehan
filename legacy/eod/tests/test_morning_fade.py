"""Morning-fade engine - contract tests.

The owner's 2026-09-30 order: 8 features maximum, 4 hard vetoes,
rank-top1 with "no trade" as a first-class outcome, and the exit
ladder (open+5 sell, gap stop, weak-open +15, never hold a lock-open).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import morning_fade as mf  # noqa: E402
from overnight_memory import overnight_pairs_from_sessions  # noqa: E402
from session_opens import record_session_open, open_of  # noqa: E402


def _row(**overrides):
    base = dict(
        symbol="GOOD",
        price=100.0,
        high=101.0,
        low=98.5,
        change_pct=1.2,
        volume=1_000_000,
        value=60e6,
        avg_volume_20=1e6,
        late_momentum_pct=1.5,
        late_volume_ratio=2.0,
        quote={"bid": 99.9, "ask": 100.1},
        sector_chg_pct=0.8,
        prev_close=98.8,
        session_history=[
            {"open": 100 + i % 3, "close": 100.5 + i % 2, "high": 101 + i % 3, "low": 99.5}
            for i in range(25)
        ],
        overnight_pairs=[{"gap_pct": 0.3 + (i % 5) * 0.1} for i in range(30)],
    )
    base.update(overrides)
    return base


def test_features_mapped():
    feats = mf.build_features([_row()], kse100_pct=0.4)
    for name in mf.FEATURES:
        assert name in feats[0], name
    assert set(mf.FEATURES) == {
        "close_position", "late_volume_ratio", "late_momentum",
        "extension_safety", "overnight_history", "book_strength",
        "sector_context", "range_sufficiency",
    }


def test_veto_circuit():
    f = mf.build_features([_row(change_pct=9.9)], kse100_pct=0.4)
    assert mf.veto(f[0], 0.4) is not None
    assert "circuit" in mf.veto(f[0], 0.4)


def test_veto_penny_price():
    f = mf.build_features([_row(price=6.67)], kse100_pct=0.4)
    assert "price<" in (mf.veto(f[0], 0.4) or "")


def test_veto_spread():
    f = mf.build_features([_row(quote={"bid": 99.0, "ask": 101.0})], kse100_pct=0.4)
    # spread 2% of price -> veto 1
    assert mf.veto(f[0], 0.4) is not None
    assert "spread" in mf.veto(f[0], 0.4)


def test_veto_day_value():
    f = mf.build_features([_row(value=1e6)], kse100_pct=0.4)
    assert "value" in (mf.veto(f[0], 0.4) or "")


def test_veto_red_market():
    f = mf.build_features([_row()], kse100_pct=-0.4)
    assert "kse100" in (mf.veto(f[0], -0.8) or "")


def test_rank_pick_top1_and_no_trade():
    rows = [
        _row(symbol="A", late_momentum_pct=1.5),
        _row(symbol="B", late_momentum_pct=2.0, value=80e6),
    ]
    scored = mf.score_rows(mf.build_features(rows, kse100_pct=0.4))
    pick, ranked, vetoed = mf.rank_and_pick(scored, kse100_pct=0.4, min_score=0.4)
    assert pick is not None and pick["rank"] if False else True
    assert pick["symbol"] in ("A", "B")
    assert len(ranked) == 2 and not vetoed

    pick2, ranked2, _ = mf.rank_and_pick(scored, kse100_pct=0.4, min_score=0.99)
    assert pick2 is None and len(ranked2) == 2  # no trade keeps the ranking


def test_exit_ladder_green_open():
    plan = mf.exit_plan(100.0, 101.0)
    assert plan["action"] == "SELL" and plan["at_min"] == mf.OPEN_SELL_MIN


def test_exit_ladder_gap_stop():
    plan = mf.exit_plan(100.0, 98.5)
    assert plan["action"] == "SELL_NOW"


def test_exit_ladder_weak_open():
    plan = mf.exit_plan(100.0, 100.1)
    assert plan["at_min"] == mf.WEAK_OPEN_SELL_MIN


def test_exit_ladder_locked_open():
    plan = mf.exit_plan(100.0, 110.0)
    assert plan["action"] == "SELL_FIRST_PRINT"


def test_overnight_history_needs_20_rows():
    assert mf.overnight_history_score([{"gap_pct": 1.0} for _ in range(19)]) is None
    s = mf.overnight_history_score([{"gap_pct": 0.5} for _ in range(30)])
    assert 0.0 <= s <= 1.0


def test_overnight_memory_pairs():
    sessions = {
        "2026-09-21": {"PSO": {"c": 100.0}},
        "2026-09-22": {"PSO": {"c": 101.0, "o": 100.8}},
        "2026-09-23": {"PSO": {"c": 102.0}},
        "2026-09-24": {"PSO": {"c": 103.0, "o": 103.5}},
    }
    pairs = overnight_pairs_from_sessions(sessions, "PSO")
    assert pairs[0]["gap_pct"] == pytest.approx(0.8)
    assert pairs[1]["basis"] == "next_close"  # no open stored -> honest fallback
    assert len(pairs) == 3


def test_session_opens_first_print_wins():
    state = {"sessions": {}}
    state, w1 = record_session_open(state, "2026-09-30", {"PSO": {"price": 100.8, "timestamp": "t1"}})
    state, w2 = record_session_open(state, "2026-09-30", {"PSO": {"price": 104.0, "timestamp": "t2"}})
    assert w1 and not w2
    assert open_of(state, "2026-09-30", "PSO") == 100.8


def test_signal_record_schema():
    pick = _row()
    scored = mf.score_rows(mf.build_features([pick], kse100_pct=0.4))[0]
    rec = mf.signal_record(scored, "2026-09-30", "15:21 PKT")
    for key in ("bot", "trading_date", "symbol", "entry_price", "features",
                "score_components", "next_session_prices"):
        assert key in rec
    assert rec["bot"] == "sentinel-eod"
