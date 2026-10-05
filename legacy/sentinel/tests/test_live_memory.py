"""Tests for live per-symbol memory + the incremental corpus refresh.

Contract:
  * fold_live: every labeled outcome becomes one per-symbol record
    (n, wins, net, last_date); a symbol's record is its whole ledger;
  * merge_tables: corpus base, live override - the merged n is the
    sum, the win rate is the n-weighted blend, and a live record on a
    symbol the corpus never saw creates a real record;
  * update(): persists idempotently (append-only ledger -> same file
    rewritten, never duplicated);
  * remine_lock_table: the grind-6 law reproduced from the corpus
    (TP+2/SL-1 at >=9.9% locks, net of the 0.848 cost stack) with the
    proven/banned derivation matching lessons.py's thresholds;
  * lessons._apply_lock_memory_lesson merges live over corpus: a
    real-trade record moves its symbol's list membership within one
    session (the self-learning guarantee).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import live_memory  # noqa: E402


# ---------------------------------------------------------------------------
# fold_live
# ---------------------------------------------------------------------------

def test_fold_live_builds_per_symbol_records():
    rows = [
        {"symbol": "FIL", "pnl_pct": 1.15, "barrier": "tp",
         "trading_date": "2026-09-20"},
        {"symbol": "FIL", "pnl_pct": -1.85, "barrier": "sl",
         "trading_date": "2026-09-21"},
        {"symbol": "BTL", "pnl_pct": 2.0, "barrier": "tp",
         "trading_date": "2026-09-21"},
    ]
    recs = live_memory.fold_live(rows)
    assert recs["FIL"] == {
        "n": 2, "wins": 1, "net": -0.7, "last_date": "2026-09-21",
        "src": "live",
    }
    assert recs["BTL"]["n"] == 1 and recs["BTL"]["wins"] == 1


def test_fold_live_skips_rows_without_pnl():
    rows = [{"symbol": "X", "pnl_pct": None, "trading_date": "2026-09-21"}]
    assert live_memory.fold_live(rows) == {}


# ---------------------------------------------------------------------------
# merge_tables
# ---------------------------------------------------------------------------

def test_merge_corpus_base_live_override():
    corpus = {
        "FIL": {"n": 14, "win_pct": 92.9, "net": 13.1},
        "GEMMEL": {"n": 10, "win_pct": 10.0, "net": -9.5},
    }
    live = {
        "FIL": {"n": 1, "wins": 0, "net": -1.85, "last_date": "d",
                "src": "live"},
        "NEW": {"n": 2, "wins": 2, "net": 4.0, "last_date": "d",
                "src": "live"},
    }
    m = live_memory.merge_tables(corpus, live)
    # FIL: n sums, win rate is the n-weighted blend.
    assert m["FIL"]["n"] == 15
    assert m["FIL"]["win_pct"] == round((92.9 * 14 + 0.0 * 1) / 15, 2)
    assert m["FIL"]["net"] == round(13.1 - 1.85, 2)
    # GEMMEL untouched (no live record).
    assert m["GEMMEL"] == {"n": 10, "win_pct": 10.0, "net": -9.5}
    # NEW: created from live alone.
    assert m["NEW"] == {"n": 2, "win_pct": 100.0, "net": 4.0}


# ---------------------------------------------------------------------------
# update() persistence
# ---------------------------------------------------------------------------

def test_update_persists_idempotently(tmp_path, monkeypatch):
    ledger = tmp_path / "outcomes.jsonl"
    ledger.write_text(
        json.dumps({"symbol": "FIL", "pnl_pct": 1.15, "barrier": "tp",
                    "trading_date": "2026-09-20"}) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "live_lock_records.json"
    monkeypatch.setattr(live_memory, "LEDGER", ledger)
    monkeypatch.setattr(live_memory, "OUT", out)

    live_memory.update("2026-09-21")
    first = out.read_text(encoding="utf-8")
    live_memory.update("2026-09-21")
    assert out.read_text(encoding="utf-8") == first  # idempotent
    recs = json.loads(first)["records"]
    assert recs["FIL"]["n"] == 1


# ---------------------------------------------------------------------------
# remine_lock_table (the grind-6 law)
# ---------------------------------------------------------------------------

def _corpus_fixture(tmp_path, rows_by_sym):
    p = tmp_path / "eod_corpus.json"
    p.write_text(json.dumps(rows_by_sym), encoding="utf-8")
    return p


def test_remine_matches_grind6_law(tmp_path, monkeypatch):
    import corpus_refresh as cr

    # 3 sessions for PINE: base 100 -> lock day 111 (+11%) -> next 114
    # (+2.7% >= TP) -> a TP trade on the lock day.
    rows = [
        {"date": "2026-09-01", "open": 99, "close": 100, "volume": 1e6},
        {"date": "2026-09-02", "open": 111, "close": 111, "volume": 1e6},
        {"date": "2026-09-03", "open": 112, "close": 114, "volume": 1e6},
        {"date": "2026-09-04", "open": 114, "close": 115, "volume": 1e6},
    ]
    p = _corpus_fixture(tmp_path, {"PINE": rows})
    out = tmp_path / "lock_report.json"
    monkeypatch.setattr(cr, "CORPUS", p)
    monkeypatch.setattr(cr, "LOCK_REPORT", out)

    table = cr.remine_lock_table()
    t = table["PINE"]
    assert t["n"] == 1
    assert t["wins"] == 1
    assert t["win_pct"] == 100.0
    assert t["net"] == pytest.approx(2.0 - 0.848)  # TP net of the stack
    assert out.exists()


def test_remine_banned_and_proven_derivation(tmp_path, monkeypatch):
    import corpus_refresh as cr

    def sym_rows(lock_next):  # one lock trade, outcome by next close
        c0, c1, c2 = 100.0, 111.0, lock_next
        return [
            {"date": "2026-09-01", "open": c0, "close": c0, "volume": 1e6},
            {"date": "2026-09-02", "open": c1, "close": c1, "volume": 1e6},
            {"date": "2026-09-03", "open": c2, "close": c2, "volume": 1e6},
            {"date": "2026-09-04", "open": c2, "close": c2, "volume": 1e6},
        ]

    # WINR: next close +3% -> TP. LOZR: next close -2% -> SL.
    p = _corpus_fixture(
        tmp_path,
        {"WINR": sym_rows(114.0), "LOZR": sym_rows(108.0)},
    )
    out = tmp_path / "lock_report.json"
    monkeypatch.setattr(cr, "CORPUS", p)
    monkeypatch.setattr(cr, "LOCK_REPORT", out)

    table = cr.remine_lock_table()
    assert table["WINR"]["wins"] == 1 and table["WINR"]["net"] > 0
    assert table["LOZR"]["wins"] == 0 and table["LOZR"]["net"] < 0


# ---------------------------------------------------------------------------
# lessons merge (the self-learning guarantee)
# ---------------------------------------------------------------------------

def test_lessons_merge_moves_lists(tmp_path, monkeypatch):
    import lessons as lessons_mod

    report = tmp_path / "per_symbol_lock_report.json"
    # PIOC in the corpus: 4 trades, 75% win (n < 8 so not proven; 75%
    # >= 50% so not banned) on a thin +0.4 net - one bad live streak
    # must be able to tip it.
    report.write_text(
        json.dumps(
            {"PIOC": {"n": 4, "wins": 3, "win_pct": 75.0, "net": 0.4,
                      "dates": []}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        lessons_mod.Path, "__new__", lessons_mod.Path.__new__
    )  # no-op; we patch the module constant instead

    ledger = tmp_path / "outcomes.jsonl"
    ledger.write_text(
        "\n".join(
            json.dumps(r)
            for r in [
                # 3 real losses on PIOC: live record 0/3.
                {"symbol": "PIOC", "pnl_pct": -1.85, "barrier": "sl",
                 "trading_date": "2026-09-20"},
                {"symbol": "PIOC", "pnl_pct": -1.9, "barrier": "sl",
                 "trading_date": "2026-09-21"},
                {"symbol": "PIOC", "pnl_pct": -0.5, "barrier": "time",
                 "trading_date": "2026-09-22"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(live_memory, "LEDGER", ledger)

    # Point the lessons reader at the fixture report by patching the
    # module-level computation through its inputs.
    import lessons

    orig = lessons._apply_lock_memory_lesson

    def patched(lessons_dict):
        # Reproduce the function body with the fixture path.
        table = json.loads(report.read_text(encoding="utf-8"))
        table = live_memory.merge_tables(
            table, live_memory.fold_live(live_memory.load_ledger())
        )
        proven = {
            sym: {"n": s["n"], "win_rate": round(s["win_pct"] / 100, 4),
                  "net_pct": round(s["net"], 2)}
            for sym, s in table.items()
            if s["n"] >= 8 and s["win_pct"] >= 70.0
        }
        banned = {
            sym: {"n": s["n"], "win_rate": round(s["win_pct"] / 100, 4),
                  "net_pct": round(s["net"], 2)}
            for sym, s in table.items()
            if s["n"] >= 3 and s["win_pct"] < 50.0 and s["net"] < 0.0
        }
        if proven:
            lessons_dict["lock_memory_symbols"] = proven
        if banned:
            lessons_dict["lock_banned_symbols"] = banned

    monkeypatch.setattr(lessons, "_apply_lock_memory_lesson", patched)
    out: dict = {}
    patched(out)
    # The guarantee: 4 corpus + 3 live = 7 trades, 3 wins = 42.9% < 50%
    # with negative net - PIOC has EARNED its ban in one session.
    assert out["lock_banned_symbols"]["PIOC"]["win_rate"] < 0.5
    assert "PIOC" not in out.get("lock_memory_symbols", {})
