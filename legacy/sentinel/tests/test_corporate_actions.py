"""
Corporate-actions layer (v0.20.1) - the owner's DIVIDEND-RUNWAY
doctrine as contracts:

  * WEEKS before the book-closure window = RUNWAY: dividend-chasers
    accumulate, and we ride that demand (intraday capital gain, never
    the dividend). A stock with >= 3 trading sessions of runway left
    is TRADEABLE, even desirable;
  * the last 3 sessions before the window/ex-date, the window itself,
    and the ex-date are VETOED - an entry there cannot be exited
    cleanly before the mechanical ex-dividend drop;
  * fresh earnings results -> a queryable catalyst, never lost to
    title-parsing guesswork; dividend size extracted when the notice
    title carries it.

Parsing is tested against REAL page structure (the {d:{...}} embedded
records), not an invented fixture.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import corporate_actions as ca


# --------------------------- parsing ---------------------------

PAGE_SAMPLE = """
garbage before
{d:{id:232104,symbol:"THCCL",announcement_type:"MISV001",title:"Book Closure Notice TCCL SUKUK Certificate",name:"Thatta Cement Company Limited",date:"2026-09-17",book_closure_date_from:"2026-09-17",book_closure_date_to:"2026-09-21",ex_date:null,unconsolidated_eps:null,growth_in_pat:null,is_update:1}},
{d:{id:232200,symbol:"LUCK",announcement_type:"FRYEV1003",title:"Financial Results for the Year Ended 2026-06-30",name:"Lucky Cement Limited",date:"2026-09-18",book_closure_date_from:null,book_closure_date_to:null,ex_date:null,unconsolidated_eps:42.71,consolidated_eps:45.10,growth_in_pat:18.4,is_update:0}},
{d:{id:232300,symbol:"NO.sym-here",announcement_type:"PSX_NOTICE",title:"x",name:"y",date:"2026-09-18",book_closure_date_from:null}},
{d:{id:232400,symbol:"PPLT",announcement_type:"MISV001",title:"Cash Dividend Rs. 8.00 per share i.e. 40% AND Book Closure From 19.10.2026",name:"PPL-like",date:"2026-09-19",book_closure_date_from:"2026-10-19",book_closure_date_to:"2026-10-20",ex_date:null,unconsolidated_eps:null,growth_in_pat:null,is_update:0}},
"""


def test_parse_records_extracts_structured_fields():
    recs = ca.parse_records(PAGE_SAMPLE)
    syms = {r["symbol"] for r in recs}
    assert syms == {"THCCL", "LUCK", "NO.sym-here", "PPLT"}


def test_build_map_book_closure_and_results():
    recs = ca.parse_records(PAGE_SAMPLE)
    m = ca.build_map(recs)
    thccl = m["THCCL"]
    assert thccl["book_closure_from"] == "2026-09-17"
    assert thccl["book_closure_to"] == "2026-09-21"
    luck = m["LUCK"]
    assert luck["results"] and luck["results"][0]["eps"] == pytest.approx(42.71)
    assert luck["results"][0]["growth_in_pat"] == pytest.approx(18.4)
    # v0.20.1: dividend size rides along when the title carries it.
    ppl = m["PPLT"]
    assert ppl["book_closure_from"] == "2026-10-19"
    assert ppl["dividend_per_share"] == pytest.approx(8.0)


# --------------------- the runway doctrine ---------------------

ACTIONS = {
    # Window Thu-Fri Sep 24-25 2026. Sessions before it: 21, 22, 23.
    "CLOSER": {
        "book_closure_from": "2026-09-24",
        "book_closure_to": "2026-09-25",
        "ex_date": None,
        "results": [],
        "notices": [],
    },
    # Bare ex-date Tue Sep 22. Sessions before it: 16, 17, 18, 21.
    "EXDATE": {
        "book_closure_from": None,
        "book_closure_to": None,
        "ex_date": "2026-09-22",
        "results": [],
        "notices": [],
    },
    "CLEAN": {"results": [], "notices": []},
    "EARNER": {
        "results": [{
            "date": "2026-09-18", "eps": 12.3, "growth_in_pat": 5.0,
            "title": "Financial Results",
        }],
        "notices": [],
    },
}


def test_runway_is_tradeable_and_stampeded_late_is_vetoed():
    """The owner's doctrine: >= 3 sessions of runway = ride the
    chasers; the last 2 sessions, the window, and behind it = veto."""
    # 4 sessions of runway -> tradeable (v0.19.0 would have blocked).
    assert ca.book_closure_block("CLOSER", date(2026, 9, 17), actions=ACTIONS) is None
    # Exactly 3 sessions left -> still clean (exit is guaranteed).
    assert ca.book_closure_block("CLOSER", date(2026, 9, 18), actions=ACTIONS) is None
    # 2 sessions -> too late to exit cleanly -> veto.
    assert ca.book_closure_block("CLOSER", date(2026, 9, 21), actions=ACTIONS)
    assert ca.book_closure_block("CLOSER", date(2026, 9, 22), actions=ACTIONS)
    assert ca.book_closure_block("CLOSER", date(2026, 9, 23), actions=ACTIONS)
    # The window itself and the day after -> circus, veto.
    assert ca.book_closure_block("CLOSER", date(2026, 9, 24), actions=ACTIONS)
    assert ca.book_closure_block("CLOSER", date(2026, 9, 25), actions=ACTIONS)


def test_runway_counts_sessions_not_days_and_skips_holidays():
    """Runway is SESSIONS: weekends and official holidays don't count
    (Iqbal Day Mon Nov 9 sits inside the runway math here)."""
    # PPL scenario: closure Oct 19-20; Fri Oct 16 has only the weekend
    # before it -> 0 sessions -> veto.
    ppl = {"book_closure_from": "2026-10-19", "book_closure_to": "2026-10-20"}
    assert ca.dividend_runway("P", date(2026, 10, 16), actions={"P": ppl}) == 0
    assert ca.book_closure_block("P", date(2026, 10, 16), actions={"P": ppl})
    # Sat Sep 19 -> Oct 19 = 20 sessions (verified against the calendar).
    assert ca.dividend_runway("P", date(2026, 9, 19), actions={"P": ppl}) == 20
    # Iqbal-week: closure Tue Nov 10 seen from Fri Nov 6 -> the only
    # inter-session day is the Monday holiday -> 0 sessions -> veto
    # (an EOD pick Friday would hold into the circus Tuesday).
    x = {"book_closure_from": "2026-11-10", "book_closure_to": "2026-11-11"}
    assert ca.dividend_runway("X", date(2026, 11, 6), actions={"X": x}) == 0
    assert ca.book_closure_block("X", date(2026, 11, 6), actions={"X": x})


def test_ex_date_zone_uses_the_same_doctrine():
    assert ca.book_closure_block("EXDATE", date(2026, 9, 16), actions=ACTIONS) is None  # 3 sessions
    assert ca.book_closure_block("EXDATE", date(2026, 9, 17), actions=ACTIONS)  # 2
    assert ca.book_closure_block("EXDATE", date(2026, 9, 22), actions=ACTIONS)  # circus day


def test_clean_symbol_never_blocked_and_missing_data_inert():
    assert ca.book_closure_block("CLEAN", date(2026, 9, 24), actions=ACTIONS) is None
    assert ca.book_closure_block("UNKNOWN", date(2026, 9, 24), actions={}) is None


def test_fresh_results_found_and_expired_not():
    got = ca.fresh_results("EARNER", date(2026, 9, 19), actions=ACTIONS)
    assert got and got["eps"] == pytest.approx(12.3)
    assert ca.fresh_results("EARNER", date(2026, 9, 25), actions=ACTIONS) is None
    assert ca.fresh_results("CLEAN", date(2026, 9, 19), actions=ACTIONS) is None


# --------------------------- Rule 25 in the engine ---------------------------
# The engine vets against date.today(), so the fixture windows are built
# RELATIVE to today: CLOSER opens in 2 days (inside the 3-day lead
# buffer -> blocked), LATER opens in 6 days (outside -> safe).
_TODAY = date.today()
_ENGINE_ACTIONS = {
    "CLOSER": {
        "book_closure_from": (_TODAY + __import__("datetime").timedelta(days=2)).isoformat(),
        "book_closure_to": (_TODAY + __import__("datetime").timedelta(days=3)).isoformat(),
        "ex_date": None,
        "results": [],
        "notices": [],
    },
    "LATER": {
        "book_closure_from": (_TODAY + __import__("datetime").timedelta(days=6)).isoformat(),
        "book_closure_to": (_TODAY + __import__("datetime").timedelta(days=7)).isoformat(),
        "ex_date": None,
        "results": [],
        "notices": [],
    },
    "CLEAN": {"results": [], "notices": []},
}


def _frame(symbols, scores=None):
    import pandas as pd
    rows = []
    scores = scores or [0.8] * len(symbols)
    ts = pd.Timestamp("2026-09-18T05:30:00+00:00")
    for i, sym in enumerate(symbols):
        row = {
            "symbol": sym,
            "timestamp": ts,
            "tradable": True,
            "feature_rank_score_adjusted": scores[i],
            "master_score": scores[i],
            "price": 100.0,
            "change_pct": 1.0,
            "price_position_range": 0.5,
            "score_weight_coverage": 0.9,
            "breadth_pct": 50.0,
        }
        for k in range(8):
            row[f"z_fake_{k}"] = 0.6
        rows.append(row)
    return pd.DataFrame(rows)


def test_engine_blocks_book_closure_symbol():
    """The top-scored symbol sits inside its closure lead buffer ->
    vetoed despite the best score; the best ELIGIBLE symbol wins."""
    from decision_engine import DecisionEngine
    engine = DecisionEngine()
    engine.corporate_actions = _ENGINE_ACTIONS
    decision = engine.evaluate(
        _frame(["CLOSER", "LATER", "CLEAN"], scores=[0.9, 0.7, 0.6])
    )
    assert decision.action == "ENTER"
    assert decision.symbol == "LATER"  # CLOSER (0.9) vetoed, LATER eligible


def test_engine_rule_25_inert_without_data():
    from decision_engine import DecisionEngine
    engine = DecisionEngine()
    engine.corporate_actions = None
    decision = engine.evaluate(_frame(["CLOSER"]))
    assert decision.action == "ENTER"
    assert decision.symbol == "CLOSER"


def test_engine_window_far_in_future_is_safe():
    from decision_engine import DecisionEngine
    engine = DecisionEngine()
    engine.corporate_actions = _ENGINE_ACTIONS
    decision = engine.evaluate(_frame(["LATER"]))
    assert decision.action == "ENTER"
    assert decision.symbol == "LATER"
