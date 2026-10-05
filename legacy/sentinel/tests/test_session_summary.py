"""
Tests for the session summary - the end-of-day report of the bot's calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from psx_core import paths, sessions
import session_summary as ss


@pytest.fixture
def summary_env(tmp_path, monkeypatch):
    """Redirect logs/ and data/ to a temp directory."""
    logs_dir = tmp_path / "logs"
    data_dir = tmp_path / "data"
    logs_dir.mkdir()
    data_dir.mkdir()
    monkeypatch.setattr(paths, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    return tmp_path


def _write_ledger(logs_dir: Path, lines: list[dict]) -> None:
    with (logs_dir / "decisions.jsonl").open("w", encoding="utf-8") as f:
        for record in lines:
            f.write(json.dumps(record, default=str) + "\n")


def _decision(at: str, action: str, symbol=None, score=None, reason=""):
    return {
        "at": at,
        "action": action,
        "symbol": symbol,
        "score": score,
        "reason": reason,
    }


# PKT is UTC+5: 05:00 UTC = 10:00 PKT - same trading date both sides.
_AT_1000 = "2026-09-07T05:00:00+00:00"
_AT_1030 = "2026-09-07T05:30:00+00:00"
_AT_1100 = "2026-09-07T06:00:00+00:00"
# Previous day (must be excluded).
_AT_PREV = "2026-09-06T05:00:00+00:00"


class TestLoading:
    def test_loads_only_the_days_lines(self, summary_env):
        _write_ledger(paths.LOGS_DIR, [
            _decision(_AT_PREV, "STAND_ASIDE", reason="old day"),
            _decision(_AT_1000, "STAND_ASIDE", reason="warming up"),
            _decision(_AT_1030, "ENTER", "ECOP", score=0.59),
        ])
        decisions = ss.load_decisions("2026-09-07")
        assert len(decisions) == 2
        assert decisions[1]["symbol"] == "ECOP"

    def test_skips_corrupt_lines(self, summary_env):
        ledger = paths.LOGS_DIR / "decisions.jsonl"
        ledger.write_text(
            "not json\n"
            + json.dumps(_decision(_AT_1000, "STAND_ASIDE", reason="ok"))
            + "\n\n",
            encoding="utf-8",
        )
        assert len(ss.load_decisions("2026-09-07")) == 1

    def test_missing_ledger_is_empty(self, summary_env):
        assert ss.load_decisions("2026-09-07") == []


class TestBuildSummary:
    def _portfolio(self, data_dir: Path, positions: list[dict]) -> None:
        (data_dir / "portfolio.json").write_text(
            json.dumps(positions), encoding="utf-8"
        )

    def test_full_day(self, summary_env):
        _write_ledger(paths.LOGS_DIR, [
            _decision(_AT_1000, "STAND_ASIDE",
                      reason="Warming up: no current-session data yet"),
            _decision(_AT_1030, "STAND_ASIDE",
                      reason="Below conviction gate: best score 0.5321 < 0.55"),
            _decision(_AT_1030, "ENTER", "ECOP", score=0.5908),
            _decision(_AT_1100, "STAND_ASIDE",
                      reason="Daily entry limit reached (1/3)"),
        ])
        self._portfolio(paths.DATA_DIR, [
            {"symbol": "ECOP", "entry_price": 49.01,
             "entry_date": "2026-09-07", "target_price": 49.99,
             "status": "CLOSED", "exit_price": 50.14,
             "exit_date": "2026-09-07",
             "exit_reason": "Rule 3: profit target reached",
             "pnl": 1.13, "pnl_pct": 2.3057, "trading_days_held": 0},
        ])

        s = ss.build_summary("2026-09-07")
        assert s["cycles"] == 4
        assert s["enters"] == 1
        assert s["stand_asides"] == 3
        assert s["realised_pnl"] == pytest.approx(1.13)
        assert s["wins"] == 1 and s["losses"] == 0
        assert s["still_open"] == 0
        # Category grouping
        assert s["stand_aside_reasons"]["warming up"] == 1
        assert s["stand_aside_reasons"]["below conviction gate"] == 1
        assert s["stand_aside_reasons"]["entry cap reached"] == 1
        # Trade carries the decision-time score
        assert s["trades"][0]["score"] == pytest.approx(0.5908)

    def test_open_positions_counted(self, summary_env):
        _write_ledger(paths.LOGS_DIR, [
            _decision(_AT_1000, "ENTER", "PIOC", score=0.57),
        ])
        self._portfolio(paths.DATA_DIR, [
            {"symbol": "PIOC", "entry_price": 259.47,
             "entry_date": "2026-09-07", "target_price": 264.66,
             "status": "OPEN", "pnl": None, "pnl_pct": None},
        ])
        s = ss.build_summary("2026-09-07")
        assert s["still_open"] == 1
        assert s["wins"] == 0 and s["losses"] == 0

    def test_loss_counts_as_loss(self, summary_env):
        _write_ledger(paths.LOGS_DIR, [])
        self._portfolio(paths.DATA_DIR, [
            {"symbol": "X", "entry_price": 100.0,
             "entry_date": "2026-09-07", "target_price": 102.0,
             "status": "CLOSED", "exit_price": 98.0,
             "exit_date": "2026-09-07", "exit_reason": "stop",
             "pnl": -2.0, "pnl_pct": -2.0, "trading_days_held": 0},
        ])
        s = ss.build_summary("2026-09-07")
        assert s["losses"] == 1
        assert s["realised_pnl"] == pytest.approx(-2.0)

    def test_positions_from_other_days_excluded(self, summary_env):
        _write_ledger(paths.LOGS_DIR, [])
        self._portfolio(paths.DATA_DIR, [
            {"symbol": "OLD", "entry_price": 10.0,
             "entry_date": "2026-09-04", "target_price": 10.5,
             "status": "CLOSED", "pnl": 0.5, "pnl_pct": 5.0},
        ])
        s = ss.build_summary("2026-09-07")
        assert s["trades"] == []
        assert s["realised_pnl"] == 0.0


class TestRendering:
    def _summary(self):
        return {
            "trading_date": "2026-09-07",
            "cycles": 21, "enters": 3, "stand_asides": 18,
            "stand_aside_reasons": {"entry cap reached": 13,
                                    "below conviction gate": 3},
            "trades": [
                {"symbol": "ECOP", "action": "ENTER", "score": 0.5908,
                 "entry_price": 49.01, "entry_time": _AT_1000,
                 "target_price": 49.99, "status": "CLOSED",
                 "exit_price": 50.14, "exit_time": _AT_1100,
                 "exit_reason": "Rule 3: profit target reached",
                 "pnl": 1.13, "pnl_pct": 2.3057},
                {"symbol": "PIOC", "action": "ENTER", "score": 0.5743,
                 "entry_price": 259.47, "entry_time": _AT_1030,
                 "target_price": 264.66, "status": "OPEN",
                 "exit_price": None, "exit_time": None,
                 "exit_reason": "", "pnl": None, "pnl_pct": None},
            ],
            "realised_pnl": 1.13, "wins": 1, "losses": 0,
            "still_open": 1,
        }

    def test_text_report_contains_trades(self):
        text = ss.render_text(self._summary())
        assert "SESSION SUMMARY - 2026-09-07" in text
        assert "ECOP" in text and "PIOC" in text
        assert "+2.31%" in text
        assert "Rule 3" in text
        assert "entry cap reached" in text
        assert "Rs. +1.13" in text
        assert "1 wins / 0 losses" in text

    def test_text_report_empty_day(self):
        text = ss.render_text({
            "trading_date": "2026-09-07", "cycles": 0, "enters": 0,
            "stand_asides": 0, "stand_aside_reasons": {}, "trades": [],
            "realised_pnl": 0.0, "wins": 0, "losses": 0, "still_open": 0,
        })
        assert "no entries today" in text

    def test_markdown_compact(self):
        md = ss.render_markdown(self._summary())
        assert "**DAY SUMMARY - 2026-09-07**" in md
        assert "`ECOP`" in md
        assert "**WIN**" in md
        assert "Rs. +1.13" in md

    def test_pkt_time_conversion(self):
        # 05:00 UTC -> 10:00 PKT
        assert ss._pkt_time(_AT_1000) == "10:00"
        assert ss._pkt_time(None) == "--:--"


class TestReasonGrouping:
    def test_known_categories(self):
        cases = {
            "warming up": [
                "Warming up: no current-session data yet (latest snapshot X)",
                "No current-session data on disk (dataset ends X). Run the collector.",
            ],
            "entry cap reached": ["Daily entry limit reached (3/3)"],
            "below conviction gate": [
                "Below conviction gate: best score 0.5321 < 0.55 - no genuine signal",
            ],
            "thin evidence": ["Thin evidence: 2 supporting components < 5"],
            "weak breadth": ["Rule 5: broad-market breadth is weak (25.0%)"],
            "correlation block": ["All top candidates blocked: correlated"],
            "no eligible candidates": ["No eligible candidates after filtering"],
        }
        for expected, reasons in cases.items():
            for reason in reasons:
                assert ss._short_reason(reason) == expected, reason

    def test_unknown_reason_kept_short(self):
        assert ss._short_reason("Something entirely new happened here") \
            == "Something entirely new happened here"
