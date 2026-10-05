"""Tests for the daily self-audit (src/self_audit.py).

The audit is the machine's own deep dive - these tests pin its verdicts
without touching the network or the production tree:

  * check_book: green on a well-formed book, RED on an open position
    missing the fields the exits need;
  * check_corporate_actions: green when fresh, RED when stale or
    corrupt;
  * check_calendar: weekend is green "closed", not a trading day;
  * check_universe: green on a current universe, RED when the refresh
    refuses (degenerate parse), green-fixes on drift.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import self_audit as sa


NOW = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)  # a Sunday


class TestBook:
    def test_green_when_intact(self, tmp_path):
        book = tmp_path / "portfolio.json"
        book.write_text(json.dumps([
            {"symbol": "STL", "entry_price": 23.8,
             "profit_target_price": 24.28, "exit_price": None},
            {"symbol": "SNGP", "entry_price": 100.0,
             "profit_target_price": 103.0, "exit_price": 103.5},
        ]), encoding="utf-8")
        verdict, msg = sa.check_book(book)
        assert verdict == "GREEN" and "1 open" in msg

    def test_red_when_open_position_missing_target(self, tmp_path):
        book = tmp_path / "portfolio.json"
        book.write_text(json.dumps([
            {"symbol": "STL", "entry_price": 23.8, "exit_price": None},
        ]), encoding="utf-8")
        verdict, msg = sa.check_book(book)
        # The book's field is target_price (the card renderer's
        # profit_target_price alias is also accepted) - the Sep-21
        # false alarm flagged every real position on a naming mismatch.
        assert verdict == "RED" and "missing target_price" in msg

    def test_green_when_target_under_either_name(self, tmp_path):
        # Both spellings must pass: a real position is never a failure
        # just because of field-name drift.
        book = tmp_path / "portfolio.json"
        book.write_text(json.dumps([
            {"symbol": "STL", "entry_price": 23.8,
             "target_price": 24.28, "exit_price": None},
            {"symbol": "PPL", "entry_price": 230.6,
             "profit_target_price": 235.21, "exit_price": None},
        ]), encoding="utf-8")
        verdict, msg = sa.check_book(book)
        assert verdict == "GREEN" and "2 open" in msg

    def test_red_on_corrupt_json(self, tmp_path):
        book = tmp_path / "portfolio.json"
        book.write_text("{not json", encoding="utf-8")
        verdict, _ = sa.check_book(book)
        assert verdict == "RED"


class TestCorporate:
    def _file(self, tmp_path, fetched_at):
        p = tmp_path / "corporate_actions.json"
        p.write_text(json.dumps({"fetchedAt": fetched_at}), encoding="utf-8")
        return p

    def test_green_when_fresh(self, tmp_path):
        fresh = datetime.now(timezone.utc) - timedelta(hours=5)
        verdict, _ = sa.check_corporate_actions(
            self._file(tmp_path, fresh.isoformat())
        )
        assert verdict == "GREEN"

    def test_acknowledged_when_veto_off(self, tmp_path, monkeypatch):
        # The source retired with psxterminal.com (v4.0.0); with the
        # veto off the stale file is a known state, not a failure.
        monkeypatch.setattr(sa, "_corp_veto_enabled", lambda: False)
        verdict, msg = sa.check_corporate_actions(
            self._file(tmp_path, "2020-01-01T00:00:00+00:00")
        )
        assert verdict == "GREEN" and "inert" in msg

    def test_red_when_stale_and_veto_on(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sa, "_corp_veto_enabled", lambda: True)
        stale = datetime.now(timezone.utc) - timedelta(hours=100)
        verdict, msg = sa.check_corporate_actions(
            self._file(tmp_path, stale.isoformat())
        )
        assert verdict == "RED" and "stale" in msg


class TestCalendar:
    def test_weekend_is_closed_not_red(self):
        verdict, msg = sa.check_calendar(NOW.date())  # Sunday
        assert verdict == "GREEN" and "weekend" in msg

    def test_weekday_verdict(self):
        monday = datetime(2026, 9, 21, tzinfo=timezone.utc).date()
        verdict, msg = sa.check_calendar(monday)
        assert verdict == "GREEN" and "trading day" in msg


class TestUniverse:
    def test_green_when_current(self, monkeypatch):
        import refresh_universe as ru
        monkeypatch.setattr(ru, "fetch_fundamentals", lambda: [])
        monkeypatch.setattr(ru, "refresh", lambda records: {
            "members": 313, "added": [], "removed": [],
            "flag_flips": [], "changed": False,
        })
        verdict, msg = sa.check_universe()
        assert verdict == "GREEN" and "313" in msg

    def test_green_fix_when_drift(self, monkeypatch):
        import refresh_universe as ru
        monkeypatch.setattr(ru, "fetch_fundamentals", lambda: [])
        monkeypatch.setattr(ru, "refresh", lambda records: {
            "members": 314, "added": ["NEWONE"], "removed": [],
            "flag_flips": [], "changed": True,
        })
        verdict, msg = sa.check_universe()
        assert verdict == "GREEN" and "NEWONE" in msg

    def test_red_when_refresh_refuses(self, monkeypatch):
        import refresh_universe as ru
        monkeypatch.setattr(ru, "fetch_fundamentals", lambda: [])
        def _boom(records):
            raise RuntimeError("refusing to replace")
        monkeypatch.setattr(ru, "refresh", _boom)
        verdict, msg = sa.check_universe()
        assert verdict == "RED" and "refused" in msg

    def test_red_when_source_dead(self, monkeypatch):
        import refresh_universe as ru
        def _dead():
            raise ConnectionError("no route")
        monkeypatch.setattr(ru, "fetch_fundamentals", _dead)
        verdict, msg = sa.check_universe()
        assert verdict == "RED" and "unreachable" in msg


class TestVerdict:
    def test_any_red_makes_report_red(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sa, "check_suite", lambda: ("GREEN", "ok"))
        monkeypatch.setattr(sa, "check_universe",
                            lambda: ("RED", "universe source unreachable"))
        monkeypatch.setattr(sa, "check_corporate_actions",
                            lambda path=None: ("GREEN", "fresh"))
        monkeypatch.setattr(sa, "check_book",
                            lambda path=None: ("GREEN", "intact"))
        monkeypatch.setattr(sa, "check_notified",
                            lambda path=None: ("GREEN", "intact"))
        monkeypatch.setattr(sa, "check_calendar",
                            lambda today=None: ("GREEN", "closed"))
        report = sa.run_audit()
        assert report["verdict"] == "RED"
        assert report["reds"][0][0] == "universe"

    def test_message_names_the_reds(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sa, "check_suite",
                            lambda: ("GREEN", "suite green"))
        monkeypatch.setattr(sa, "check_universe",
                            lambda: ("RED", "universe source unreachable"))
        monkeypatch.setattr(sa, "check_corporate_actions",
                            lambda path=None: ("GREEN", "fresh"))
        monkeypatch.setattr(sa, "check_book",
                            lambda path=None: ("GREEN", "intact"))
        monkeypatch.setattr(sa, "check_notified",
                            lambda path=None: ("GREEN", "intact"))
        monkeypatch.setattr(sa, "check_calendar",
                            lambda today=None: ("GREEN", "closed"))
        msg = sa.render_message(sa.run_audit())
        assert "FAILURE(S)" in msg and "universe source unreachable" in msg

class TestPennyTripwire:
    """Rule 27 tripwire: the audit proves today's entries from the
    bot's own decisions log respect the penny floor (the KEL lesson).
    """

    def _write_log(self, path, rows):
        path.write_text(
            chr(10).join(json.dumps(r) for r in rows) + chr(10),
            encoding="utf-8",
        )

    def test_green_when_no_calls_today(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        verdict, detail = sa.check_penny_calls(path=log, today="2026-10-02")
        assert verdict == "GREEN"
        assert "no calls today" in detail

    def test_green_when_entries_respect_floor(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        self._write_log(log, [{
            "at": "2026-10-02T05:26:38+00:00", "action": "ENTER",
            "symbol": "OGDC", "price": 315.9,
        }])
        verdict, detail = sa.check_penny_calls(path=log, today="2026-10-02")
        assert verdict == "GREEN", detail
        assert "1 entry(ies)" in detail

    def test_red_on_penny_entry_today(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        self._write_log(log, [{
            "at": "2026-10-02T05:26:38+00:00", "action": "ENTER",
            "symbol": "KEL", "price": 7.12,
        }])
        verdict, detail = sa.check_penny_calls(path=log, today="2026-10-02")
        assert verdict == "RED"
        assert "KEL @ Rs 7.12" in detail

    def test_yesterday_entries_do_not_trip_today(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        self._write_log(log, [{
            "at": "2026-09-04T10:26:38+00:00", "action": "ENTER",
            "symbol": "KEL", "price": 7.12,
        }])
        verdict, _ = sa.check_penny_calls(path=log, today="2026-10-02")
        assert verdict == "GREEN"

    def test_floor_follows_engine_config(self, tmp_path, monkeypatch):
        class Cfg:
            min_entry_price = 25.0
        import decision_engine
        monkeypatch.setattr(
            decision_engine, "DecisionConfig", Cfg, raising=False)
        log = tmp_path / "decisions.jsonl"
        self._write_log(log, [{
            "at": "2026-10-02T05:26:38+00:00", "action": "ENTER",
            "symbol": "SOME", "price": 20.0,
        }])
        verdict, detail = sa.check_penny_calls(path=log, today="2026-10-02")
        assert verdict == "RED"
        assert "floor 25" in detail
