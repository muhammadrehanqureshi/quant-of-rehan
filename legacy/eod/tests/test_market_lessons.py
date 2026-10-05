"""Tests for the market-lessons sync in Sentinel-EOD (v2.4.0).

Contract:
  * load_market_lessons: missing/corrupt store -> empty (pick runs on);
  * streaks confirm at 3+ sessions;
  * memory_factor: dead-confirmed -> 0.0 (refused), trend-confirmed ->
    +3% rank, unknown -> None (untouched);
  * pick_top refuses a market-dead name even when it is the only
    candidate - a refusal is a refusal, never "the best of nothing";
  * a failed store read never breaks a pick run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import market_lessons  # noqa: E402
from market_lessons import (  # noqa: E402
    load_market_lessons,
    memory_factor,
)


def _store(tmp_path, dead_streak, trend_streak, last_date="2026-09-23"):
    store = {
        "updated": "2026-09-23T15:30:00+00:00",
        "days": {
            last_date: {
                "date": last_date,
                "taught": f"{last_date}: risk-on - breadth 65% up",
            }
        },
        "dead_streak": dead_streak,
        "trend_streak": trend_streak,
        "dead_confirmed": [
            s for s, n in dead_streak.items() if n >= 3
        ],
        "trend_confirmed": [
            s for s, n in trend_streak.items() if n >= 3
        ],
        "last_date": last_date,
    }
    p = tmp_path / "market_lessons.json"
    p.write_text(json.dumps(store), encoding="utf-8")
    return p


def test_missing_store_degrades(tmp_path):
    view = load_market_lessons(tmp_path / "nope.json")
    assert view["dead"] == set() and view["trending"] == set()
    assert view["last"] is None


def test_corrupt_store_degrades(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{oops", encoding="utf-8")
    view = load_market_lessons(p)
    assert view["dead"] == set()


def test_streak_thresholds(tmp_path):
    p = _store(
        tmp_path,
        dead_streak={"GEMMEL": 4, "EMCO": 2},
        trend_streak={"FIL": 3, "BTL": 1},
    )
    view = load_market_lessons(p)
    assert view["dead"] == {"GEMMEL"}
    assert view["trending"] == {"FIL"}
    assert view["last"]["taught"].endswith("breadth 65% up")


def test_memory_factor_verdicts(tmp_path):
    p = _store(
        tmp_path,
        dead_streak={"GEMMEL": 5},
        trend_streak={"FIL": 3},
    )
    lessons = load_market_lessons(p)
    assert memory_factor("GEMMEL", lessons) == 0.0
    assert memory_factor("FIL", lessons) > 1.0
    assert memory_factor("PRL", lessons) is None
    assert memory_factor("PRL", {}) is None


def _candidate_row(symbol, price=25.0):
    # Liquidity fields sized to clear score_symbol's bars (same
    # fixture shape the lock-memory tests use).
    return {
        "symbol": symbol,
        "price": price,
        "change_pct": 2.0,
        "late_momentum_pct": 1.2,
        "high": price * 1.01,
        "low": price * 0.99,
        "volume": 1_300_000,
        "avg_volume_20": 1_200_000,
        "value": 25_000_000,
    }


def test_pick_top_refuses_market_dead(tmp_path, monkeypatch):
    import eod_bot

    p = _store(tmp_path, dead_streak={"GEMMEL": 4}, trend_streak={})
    monkeypatch.setattr(market_lessons, "STORE_PATH", p)
    monkeypatch.setattr(
        eod_bot, "_LOCK_MEMORY_CACHE", {}, raising=False
    )
    # v3.0.0: the memory layers are retired from the default path;
    # these tests exercise the armed behavior explicitly.
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top(
        [_candidate_row("GEMMEL")], close_history={}
    )
    assert picks == []


def test_pick_top_passes_untouched_symbol(tmp_path, monkeypatch):
    import eod_bot

    p = _store(tmp_path, dead_streak={"GEMMEL": 4}, trend_streak={})
    monkeypatch.setattr(market_lessons, "STORE_PATH", p)
    monkeypatch.setattr(
        eod_bot, "_LOCK_MEMORY_CACHE", {}, raising=False
    )
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top(
        [_candidate_row("PRL")], close_history={}
    )
    assert len(picks) == 1
    assert picks[0]["symbol"] == "PRL"


def test_pick_top_trend_bonus_flags_card(tmp_path, monkeypatch):
    import eod_bot

    p = _store(
        tmp_path,
        dead_streak={},
        trend_streak={"PRL": 3},
        last_date="2026-09-23",
    )
    monkeypatch.setattr(market_lessons, "STORE_PATH", p)
    monkeypatch.setattr(
        eod_bot, "_LOCK_MEMORY_CACHE", {}, raising=False
    )
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top(
        [_candidate_row("PRL")], close_history={}
    )
    assert len(picks) == 1
    flag = picks[0]["lock_memory_flag"]
    assert flag and "trending" in flag
    assert "risk-on" in (picks[0]["market_context"] or "")
