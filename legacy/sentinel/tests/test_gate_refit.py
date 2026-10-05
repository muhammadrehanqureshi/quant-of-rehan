"""
Tests for the gate refit (the ledger tunes the entry knobs).

Contract:
  * thin samples move NOTHING (the note says why);
  * with both buckets >= BUCKET_MIN, a knob moves one step in the
    direction the win/loss means vote;
  * clamps hold - the ledger can tune a knob, never weld it shut;
  * apply() persists the config change and an audit line.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psx_core.paths as paths
import gate_refit


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(gate_refit, "CONFIG", tmp_path / "config.json")
    monkeypatch.setattr(gate_refit, "GATE_REFIT", data / "gate_refit.json")
    monkeypatch.setattr(
        gate_refit, "GATE_HISTORY", data / "refit_history.jsonl"
    )
    (tmp_path / "config.json").write_text(
        json.dumps({
            "min_master_score": 0.55,
            "max_entry_off_low_pct": 3.0,
            "hard_min_breadth_pct": 40.0,
        }),
        encoding="utf-8",
    )
    return tmp_path, data


def _write_book(data: Path, rows: list[dict]) -> None:
    (data / "portfolio.json").write_text(
        json.dumps({"positions": rows}), encoding="utf-8"
    )


def _trade(score: float, offlow: float, breadth: float, pnl: float) -> dict:
    return {
        "status": "CLOSED",
        "pnl": pnl,
        "min_master_score": score,
        "max_entry_off_low_pct": offlow,
        "hard_min_breadth_pct": breadth,
    }


class TestGateRefit:
    def test_thin_sample_moves_nothing(self, env):
        tmp, data = env
        _write_book(data, [_trade(0.6, 1.0, 45, 2.0)] * 5)
        v = gate_refit.evaluate()
        assert v["moves"] == []
        assert "thin sample" in v["note"]

    def test_winners_cleared_higher_bar_raises_it(self, env):
        tmp, data = env
        # 20 wins entered with high scores, 20 losses with low ones:
        # the ledger says winners cleared a higher bar -> raise it.
        rows = (
            [_trade(0.70, 1.0, 45, 2.0)] * 20
            + [_trade(0.58, 1.0, 45, -1.0)] * 20
        )
        _write_book(data, rows)
        v = gate_refit.evaluate()
        moves = {m["key"]: m for m in v["moves"]}
        assert moves["min_master_score"]["to"] == pytest.approx(0.57)

    def test_step_not_jump(self, env):
        tmp, data = env
        rows = (
            [_trade(0.75, 1.0, 45, 2.0)] * 25
            + [_trade(0.50, 1.0, 45, -1.0)] * 25
        )
        _write_book(data, rows)
        cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
        v = gate_refit.evaluate(cfg)
        mv = next(m for m in v["moves"] if m["key"] == "min_master_score")
        assert mv["to"] - mv["from"] == pytest.approx(0.02)

    def test_clamp_holds(self, env):
        tmp, data = env
        # Conviction gate already at its 0.75 ceiling and the evidence
        # still votes higher: no move - the ledger can tune, not weld.
        (tmp / "config.json").write_text(
            json.dumps({"min_master_score": 0.75,
                        "max_entry_off_low_pct": 3.0,
                        "hard_min_breadth_pct": 40.0}),
            encoding="utf-8",
        )
        rows = (
            [_trade(0.80, 1.0, 45, 2.0)] * 20
            + [_trade(0.60, 1.0, 45, -1.0)] * 20
        )
        _write_book(data, rows)
        v = gate_refit.evaluate()
        assert not any(
            m["key"] == "min_master_score" and m["to"] > 0.75
            for m in v["moves"]
        )
        # And the mirror case: at the 0.50 floor with evidence voting
        # lower, nothing moves below the clamp either.
        (tmp / "config.json").write_text(
            json.dumps({"min_master_score": 0.50,
                        "max_entry_off_low_pct": 3.0,
                        "hard_min_breadth_pct": 40.0}),
            encoding="utf-8",
        )
        rows = (
            [_trade(0.60, 1.0, 45, 2.0)] * 20
            + [_trade(0.80, 1.0, 45, -1.0)] * 20
        )
        _write_book(data, rows)
        v = gate_refit.evaluate()
        assert not any(
            m["key"] == "min_master_score" and m["to"] < 0.50
            for m in v["moves"]
        )

    def test_apply_persists_config_and_audit(self, env):
        tmp, data = env
        rows = (
            [_trade(0.70, 0.5, 45, 2.0)] * 20
            + [_trade(0.58, 2.5, 45, -1.0)] * 20
        )
        _write_book(data, rows)
        v = gate_refit.apply()
        assert v["moves"], "expected at least one move"
        cfg = json.loads((tmp / "config.json").read_text(encoding="utf-8"))
        for mv in v["moves"]:
            assert cfg[mv["key"]] == mv["to"]
        audit = (data / "refit_history.jsonl").read_text(encoding="utf-8")
        assert json.loads(audit.splitlines()[-1])["moves"]

    def test_missing_feature_rows_do_not_crash(self, env):
        tmp, data = env
        rows = [{"status": "CLOSED", "pnl": 1.0}] * 40  # no feature keys
        _write_book(data, rows)
        v = gate_refit.evaluate()  # must not raise
        assert v["moves"] == []
