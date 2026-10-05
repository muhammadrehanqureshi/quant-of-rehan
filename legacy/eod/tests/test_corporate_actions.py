"""
Corporate-actions layer (v2.2.5) - the owner's DIVIDEND-RUNWAY doctrine:

  * weeks before the book-closure window = RUNWAY: dividend-chasers
    accumulate and we ride that demand (capital gain, never the
    dividend); >= 3 trading sessions of runway left = TRADEABLE;
  * the last 3 sessions before the window/ex-date, the window itself,
    and the ex-date are BLOCKED - an EOD pick holds one night, so a
    3-session runway guarantees the holding day clears the circus;
  * fresh earnings results -> visible evidence on the pick card.

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
{d:{id:232400,symbol:"PPLT",announcement_type:"MISV001",title:"Cash Dividend Rs. 8.00 per share i.e. 40% AND Book Closure From 19.10.2026",name:"PPL-like",date:"2026-09-19",book_closure_date_from:"2026-10-19",book_closure_date_to:"2026-10-20",ex_date:null,unconsolidated_eps:null,growth_in_pat:null,is_update:0}},
"""


def test_parse_records_extracts_structured_fields():
    recs = ca.parse_records(PAGE_SAMPLE)
    assert {r["symbol"] for r in recs} == {"THCCL", "LUCK", "PPLT"}


def test_build_map_book_closure_and_results():
    m = ca.build_map(ca.parse_records(PAGE_SAMPLE))
    assert m["THCCL"]["book_closure_from"] == "2026-09-17"
    assert m["THCCL"]["book_closure_to"] == "2026-09-21"
    assert m["LUCK"]["results"][0]["eps"] == pytest.approx(42.71)
    # v2.2.5: dividend size rides along when the title carries it.
    assert m["PPLT"]["book_closure_from"] == "2026-10-19"
    assert m["PPLT"]["dividend_per_share"] == pytest.approx(8.0)


# --------------------------- the veto ---------------------------

ACTIONS = {
    "CLOSER": {
        "book_closure_from": "2026-09-24",
        "book_closure_to": "2026-09-25",
        "ex_date": None,
        "results": [],
        "notices": [],
    },
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
    chasers; the last 2 sessions, the window, and behind it = veto.
    An EOD pick on Sep 21 would hold into the Sep 24 window - vetoed."""
    # 4 sessions of runway -> tradeable (the v2.2.4 rule blocked this).
    assert ca.book_closure_block("CLOSER", date(2026, 9, 17), actions=ACTIONS) is None
    # Exactly 3 sessions left -> still clean (exit guaranteed).
    assert ca.book_closure_block("CLOSER", date(2026, 9, 18), actions=ACTIONS) is None
    # 2 or 1 sessions -> cannot exit cleanly before the circus.
    assert ca.book_closure_block("CLOSER", date(2026, 9, 21), actions=ACTIONS)
    assert ca.book_closure_block("CLOSER", date(2026, 9, 22), actions=ACTIONS)
    assert ca.book_closure_block("CLOSER", date(2026, 9, 23), actions=ACTIONS)
    # The window itself -> circus, veto.
    assert ca.book_closure_block("CLOSER", date(2026, 9, 24), actions=ACTIONS)


def test_runway_counts_sessions_not_days_and_skips_holidays():
    """Runway is SESSIONS: weekends and official holidays don't count."""
    # PPL scenario: closure Oct 19-20; Fri Oct 16 has only the weekend
    # before it -> 0 sessions -> veto.
    ppl = {"book_closure_from": "2026-10-19", "book_closure_to": "2026-10-20"}
    assert ca.dividend_runway("P", date(2026, 10, 16), actions={"P": ppl}) == 0
    assert ca.book_closure_block("P", date(2026, 10, 16), actions={"P": ppl})
    # Iqbal-week: closure Tue Nov 10 seen from Fri Nov 6 -> the only
    # inter-session day is the Monday holiday -> 0 sessions -> veto.
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
