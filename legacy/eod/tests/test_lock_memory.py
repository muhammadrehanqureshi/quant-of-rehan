"""
Tests for the per-symbol lock memory (v2.3.2).

The contract:
  * classify() buckets records: proven (win >= 70%, n >= 8),
    zero_win (n >= 3, win == 0), fake (n >= 3, win < 50%, net < 0),
    neutral otherwise;
  * memory_factor: proven -> bonus 5-15% scaled by record strength,
    fake -> -30%, zero_win -> 0.0 (refused), unknown -> untouched;
  * a missing/stale/corrupt report degrades to no-op - learning must
    never break a pick run;
  * pick_top applies the factor: a zero-win fake never surfaces even
    with the strongest tape, a proven continuer outranks an equal
    unproven rival, and the flag travels on the pick for the card.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import eod_bot
from lock_memory import (
    FAKE_DISCOUNT,
    BONUS_MAX,
    classify,
    load_memory,
    memory_factor,
)


# --------------------------------------------------------------------------
# classify
# --------------------------------------------------------------------------

def test_classify_proven():
    assert classify({"n": 8, "win_pct": 70.0, "net": 1.0}) == "proven"
    assert classify({"n": 44, "win_pct": 79.5, "net": 23.7}) == "proven"
    assert classify({"n": 14, "win_pct": 92.9, "net": 13.1}) == "proven"


def test_classify_zero_win_refused():
    assert classify({"n": 3, "win_pct": 0.0, "net": -2.0}) == "zero_win"
    assert classify({"n": 4, "win_pct": 0.0, "net": -6.9}) == "zero_win"


def test_classify_fake():
    assert classify({"n": 10, "win_pct": 10.0, "net": -9.5}) == "fake"
    assert classify({"n": 7, "win_pct": 14.3, "net": -8.2}) == "fake"


def test_classify_neutral():
    # too few samples
    assert classify({"n": 2, "win_pct": 0.0, "net": -5.0}) == "neutral"
    # sub-50% win but POSITIVE net (not a money-loser)
    assert classify({"n": 5, "win_pct": 40.0, "net": 3.0}) == "neutral"
    # win 50-70% on real sample: neither bonus nor ban
    assert classify({"n": 9, "win_pct": 55.0, "net": 1.0}) == "neutral"
    assert classify({}) == "neutral"
    assert classify({"n": "x", "win_pct": None, "net": None}) == "neutral"


# --------------------------------------------------------------------------
# memory_factor
# --------------------------------------------------------------------------

def test_factor_proven_bonus_scaled():
    mem = {"FIL": {"n": 14, "win_pct": 92.9, "net": 13.1}}
    f, flag = memory_factor("FIL", mem)
    assert 1.0 < f <= 1.0 + BONUS_MAX
    # strongest record approaches the cap
    assert f >= 1.10
    assert "lock-memory" in flag and "bonus" in flag


def test_factor_proven_floor():
    mem = {"X": {"n": 8, "win_pct": 70.0, "net": 0.5}}
    f, _ = memory_factor("X", mem)
    assert abs(f - 1.05) < 1e-9  # floor bonus 5%


def test_factor_fake_discount():
    mem = {"GEMMEL": {"n": 10, "win_pct": 10.0, "net": -9.5}}
    f, flag = memory_factor("GEMMEL", mem)
    assert abs(f - (1.0 - FAKE_DISCOUNT)) < 1e-9
    assert "discounted" in flag


def test_factor_zero_win_refused():
    mem = {"IBLHL": {"n": 4, "win_pct": 0.0, "net": -6.9}}
    f, flag = memory_factor("IBLHL", mem)
    assert f == 0.0
    assert "refused" in flag


def test_factor_unknown_untouched():
    f, flag = memory_factor("NOTREAL", {"A": {"n": 9, "win_pct": 80.0, "net": 5.0}})
    assert f == 1.0 and flag == ""


# --------------------------------------------------------------------------
# load degradation
# --------------------------------------------------------------------------

def test_load_missing_file_noop(tmp_path):
    assert load_memory(tmp_path / "nope.json") == {}


def test_load_corrupt_file_noop(tmp_path):
    p = tmp_path / "report.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_memory(p) == {}


def test_load_stale_file_noop(tmp_path):
    import os as _os
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"SGPL": {"n": 44, "win_pct": 79.5, "net": 23.7}}), encoding="utf-8")
    old = os.path.getmtime(p) - 11 * 86400  # past STALE_DAYS
    _os.utime(p, (old, old))
    assert load_memory(p) == {}


# --------------------------------------------------------------------------
# pick_top integration
# --------------------------------------------------------------------------

def _row(sym, price=25.0, late=1.2, chg=2.0):
    return {
        "symbol": sym,
        "price": price,
        "late_momentum_pct": late,
        "change_pct": chg,
        "high": price * 1.01,
        "low": price * 0.99,
        "volume": 1_300_000,
        "avg_volume_20": 1_200_000,  # baseline*price clears MIN_AVG_VALUE
        "value": 25_000_000,  # clears MIN_DAY_VALUE
    }


def test_pick_top_zero_win_fake_never_picked(monkeypatch):
    monkeypatch.setattr(
        eod_bot, "_LOCK_MEMORY_CACHE", {"IBLHL": {"n": 4, "win_pct": 0.0, "net": -6.9}},
        raising=False,
    )
    # v3.0.0: memory layers are opt-in in production; arm them here.
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top([_row("IBLHL")], close_history={})
    assert picks == []


def test_pick_top_proven_outranks_equal_rival(monkeypatch):
    mem = {"PROV": {"n": 44, "win_pct": 84.6, "net": 26.9}}
    monkeypatch.setattr(eod_bot, "_LOCK_MEMORY_CACHE", mem, raising=False)
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top(
        [_row("PLAIN"), _row("PROV")], top_n=2, close_history={}
    )
    assert [p["symbol"] for p in picks][0] == "PROV"
    flag = picks[0]["lock_memory_flag"]
    assert flag and "bonus" in flag
    # the raw score is unchanged; only the rank moved
    prov = next(p for p in picks if p["symbol"] == "PROV")
    plain = next(p for p in picks if p["symbol"] == "PLAIN")
    assert prov["raw_score"] == pytest.approx(plain["raw_score"], abs=1e-9)
    assert prov["score"] > plain["score"]


def test_pick_top_memory_load_failure_is_noop(monkeypatch):
    class _Boom(dict):
        def get(self, *a, **k):
            raise RuntimeError("disk gone")

    monkeypatch.setattr(eod_bot, "_LOCK_MEMORY_CACHE", _Boom(), raising=False)
    monkeypatch.setattr(eod_bot, "MEMORY_LAYERS_ENABLED", True)
    picks = eod_bot.pick_top([_row("ANY")], close_history={})
    assert picks and picks[0]["lock_memory_flag"] is None
