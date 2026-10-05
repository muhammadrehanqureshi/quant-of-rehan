"""
Tests for the morning health report.

Contract:
  * market day vs holiday verdicts are correct;
  * book, heartbeat, and learning lines render from the state files;
  * missing/corrupt state files degrade to honest lines, never a crash;
  * the once-per-day guard round-trips.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psx_core.paths as paths
import morning_report


@pytest.fixture
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "_eod_src_current" / "data").mkdir(parents=True)
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(morning_report, "SENTINEL_STATE", data)
    monkeypatch.setattr(
        morning_report, "EOD_STATE", data / "_eod_src_current" / "data"
    )
    monkeypatch.setattr(
        morning_report, "STATE_FILE", data / "morning_report_state.json"
    )
    return data


NOW = datetime(2026, 9, 21, 4, 15, tzinfo=timezone.utc)  # Monday 09:15 PKT


class TestMorningReport:
    def test_market_day_verdict(self, env):
        msg = morning_report.build_report(NOW)
        assert "OPEN today" in msg
        assert "09:32 PKT" in msg

    def test_friday_bell_is_0917(self, env):
        fri = datetime(2026, 9, 25, 4, 15, tzinfo=timezone.utc)
        msg = morning_report.build_report(fri)
        assert "09:17 PKT" in msg

    def test_book_lines(self, env):
        (env / "portfolio.json").write_text(json.dumps({
            "positions": [{
                "symbol": "STL", "status": "OPEN",
                "entry_price": 23.8, "target_price": 24.5,
            }]
        }), encoding="utf-8")
        msg = morning_report.build_report(NOW)
        assert "OPEN STL" in msg

    def test_heartbeat_age_line(self, env):
        stamp = datetime(2026, 9, 21, 4, 0, tzinfo=timezone.utc)
        (env / "heartbeat.json").write_text(
            json.dumps({"utc": stamp.isoformat()}), encoding="utf-8"
        )
        msg = morning_report.build_report(NOW)
        assert "15 min ago" in msg

    def test_learning_line(self, env):
        (env / "lessons.json").write_text(
            json.dumps({"labeled": 11}), encoding="utf-8"
        )
        (env / "gate_refit.json").write_text(json.dumps({
            "trades": 22, "moves": [{"key": "min_master_score"}],
        }), encoding="utf-8")
        msg = morning_report.build_report(NOW)
        assert "11 outcomes absorbed" in msg
        assert "1 knob(s) moved" in msg

    def test_eod_sibling_read(self, env):
        ledger = env / "_eod_src_current" / "data" / "ledger.jsonl"
        ledger.write_text(
            '{"outcome": "WIN"}\n{"outcome": "FORCE"}\n{"outcome": "WIN"}\n',
            encoding="utf-8",
        )
        msg = morning_report.build_report(NOW)
        assert "3 picks traced, 2 wins" in msg
        assert "15:25 PKT" in msg  # Monday -> Mon-Thu card time

    def test_corrupt_state_never_crashes(self, env):
        for name in ("portfolio.json", "heartbeat.json", "lessons.json",
                     "gate_refit.json"):
            (env / name).write_text("{not json", encoding="utf-8")
        msg = morning_report.build_report(NOW)  # must not raise
        assert "Morning check" in msg

    def test_once_per_day_guard(self, env):
        assert morning_report.already_sent("2026-09-21") is False
        morning_report.mark_sent("2026-09-21")
        assert morning_report.already_sent("2026-09-21") is True
        assert morning_report.already_sent("2026-09-22") is False
