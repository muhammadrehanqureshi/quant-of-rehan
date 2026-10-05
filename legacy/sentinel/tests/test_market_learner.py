"""Tests for the daily market-learner (v2.6.0).

Contract:
  * analyze_day refuses to invent a lesson (no tape / no quotes -> None);
  * a lesson carries breadth, leaders, trending, dead, verdict, and a
    human "taught" line;
  * index changePercent is PERCENT, quote changePercent is FRACTION;
  * value is cumulative - the last snapshot wins, no double counting;
  * the rolling store tracks dead/trend streaks and confirms at 3;
  * load_market_lessons degrades safely (missing/corrupt -> empty).
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import market_learner as ml  # noqa: E402


def _snap(idx_pct, quotes):
    return {
        "index": {"symbol": "KSE100", "changePercent": idx_pct},
        "quotes": quotes,
    }


def _q(price, chg_frac, value):
    return {
        "price": price,
        "changePercent": chg_frac,
        "value": value,
        "volume": 1000,
    }


def _write_tape(tmp_path, date, snaps):
    d = tmp_path / "snapshots"
    d.mkdir(exist_ok=True)
    with gzip.open(d / f"{date}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for s in snaps:
            fh.write(json.dumps(s) + "\n")


@pytest.fixture()
def learner_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ml.paths, "DATA_DIR", tmp_path)
    monkeypatch.setattr(ml, "LESSONS_PATH", tmp_path / "market_lessons.json")
    yield tmp_path


def test_no_tape_returns_none(learner_env):
    assert ml.analyze_day("2026-09-23") is None


def test_no_quotes_returns_none(learner_env):
    _write_tape(learner_env, "2026-09-23", [{"quotes": {}}])
    assert ml.analyze_day("2026-09-23") is None


def test_full_lesson_fields(learner_env):
    _write_tape(
        learner_env,
        "2026-09-23",
        [
            _snap(
                0.30,
                {
                    "FIL": _q(101.0, 0.011, 5_000_000),
                    "BTL": _q(52.0, 0.008, 3_000_000),
                    "GEMMEL": _q(1.05, 0.0002, 40_000),
                    "EMCO": _q(19.0, -0.012, 900_000),
                },
            ),
            _snap(
                0.38,
                {
                    "FIL": _q(102.0, 0.012, 7_500_000),
                    "BTL": _q(53.0, 0.009, 3_600_000),
                    "GEMMEL": _q(1.05, 0.0001, 45_000),
                    "EMCO": _q(18.6, -0.013, 950_000),
                },
            ),
        ],
    )
    lesson = ml.analyze_day("2026-09-23")
    assert lesson is not None
    # Units: index is percent already, quotes are fractions.
    assert lesson["index_chg_pct"] == 0.38
    assert lesson["breadth_pct"] == 50.0
    # Leaders by CUMULATIVE value (last snapshot), not the sum.
    fil = next(l for l in lesson["leaders"] if l["symbol"] == "FIL")
    assert fil["value_m"] == 7.5
    # Trending: green every snapshot + real turnover.
    assert set(lesson["trending"]) == {"FIL", "BTL"}
    # Dead: flat AND illiquid.
    assert "GEMMEL" in lesson["dead"]
    # Verdict: index +0.38 >= 0.2 but breadth 50% < 55 -> mixed.
    assert lesson["verdict"] == "mixed"
    assert lesson["taught"].startswith("2026-09-23:")


def test_streaks_and_confirmation(learner_env):
    def tape(date, dead_sym, trend_sym):
        _write_tape(
            learner_env,
            date,
            [
                _snap(
                    0.0,
                    {
                        dead_sym: _q(5.0, 0.0001, 30_000),
                        trend_sym: _q(10.0, 0.010, 4_000_000),
                    },
                ),
                _snap(
                    0.0,
                    {
                        dead_sym: _q(5.0, 0.0001, 31_000),
                        trend_sym: _q(10.2, 0.011, 4_100_000),
                    },
                ),
            ],
        )

    for i, d in enumerate(("2026-09-21", "2026-09-22", "2026-09-23"), 1):
        tape(d, "GEMMEL", "FIL")
        lesson = ml.build_and_store(d)
        assert lesson is not None
        store = ml._read_store()
        assert store["dead_streak"].get("GEMMEL") == i
        assert store["trend_streak"].get("FIL") == i
        if i < 3:
            assert "GEMMEL" not in store["dead_confirmed"]
    store = ml._read_store()
    assert "GEMMEL" in store["dead_confirmed"]
    assert "FIL" in store["trend_confirmed"]

    view = ml.load_market_lessons()
    assert view["dead_confirmed"] == {"GEMMEL"}
    assert view["trend_confirmed"] == {"FIL"}


def test_missing_store_degrades(learner_env):
    view = ml.load_market_lessons()
    assert view["dead_confirmed"] == set()
    assert view["trend_confirmed"] == set()
    assert view["last"] in ("", None)


def test_corrupt_store_degrades(learner_env):
    learner_env.joinpath("market_lessons.json").write_text("{oops")
    view = ml.load_market_lessons()
    assert view["dead_confirmed"] == set()


def test_engine_consumes_market_lessons():
    from decision_engine import DecisionConfig, DecisionEngine

    eng = DecisionEngine(
        DecisionConfig(),
        lessons={
            "market_dead_symbols": {"GEMMEL"},
            "market_trend_symbols": {"FIL"},
        },
    )
    assert eng.market_dead_symbols == {"GEMMEL"}
    assert eng.market_trend_symbols == {"FIL"}
