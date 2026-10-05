"""
Tests for the open bell (v3.1.0).

The contract:
  * one card per trading leg - a retried pass never double-sends;
  * Friday's two legs each get their own card;
  * silent on weekends, PSX holidays and closed hours;
  * a refused Telegram send is retried by the next pass of the same
    leg (state is recorded only after a confirmed send);
  * the kill-switch (open_bell_enabled=false) silences it cleanly;
  * a broken book file or a raising channel never raises out.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import open_bell
import psx_core.sessions as sessions

# Monday, a normal trading day, inside the morning leg.
_MONDAY_0945 = datetime(2026, 9, 28, 9, 45, tzinfo=sessions.PKT)
_MONDAY_0800 = datetime(2026, 9, 28, 8, 0, tzinfo=sessions.PKT)
# Friday leg 1 morning and leg 2 afternoon.
_FRIDAY_0930 = datetime(2026, 9, 25, 9, 30, tzinfo=sessions.PKT)
_FRIDAY_1500 = datetime(2026, 9, 25, 15, 0, tzinfo=sessions.PKT)
_SATURDAY = datetime(2026, 9, 26, 10, 0, tzinfo=sessions.PKT)
# Pakistan Day (Mon 2026-03-23), an official PSX holiday.
_HOLIDAY_MONDAY = datetime(2026, 3, 23, 10, 0, tzinfo=sessions.PKT)


@pytest.fixture
def bell(tmp_path, monkeypatch):
    """Isolated bell: state, book and config all point into tmp_path."""
    state = tmp_path / "open_bell.json"
    book = tmp_path / "portfolio.json"
    cfg = tmp_path / "config.json"
    book.write_text(
        json.dumps([{"symbol": "PPL", "status": "CLOSED"}]), encoding="utf-8"
    )
    cfg.write_text(json.dumps({"open_bell_enabled": True}), encoding="utf-8")
    monkeypatch.setattr(open_bell, "STATE_FILE", state)
    monkeypatch.setattr(open_bell, "BOOK_FILE", book)
    monkeypatch.setattr(open_bell, "CONFIG_FILE", cfg)
    return state


class TestOpenBell:
    def test_sends_once_per_leg(self, bell, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok1, note1 = open_bell.announce_open(_MONDAY_0945)
        ok2, note2 = open_bell.announce_open(_MONDAY_0945)
        assert ok1 is True and "sent" in note1
        assert ok2 is False and "already announced" in note2
        assert len(sent) == 1
        assert "The Sentinel is online" in sent[0]
        assert "flat" in sent[0]  # the book line reflects the real book

    def test_friday_legs_each_get_a_card(self, bell, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok1, _ = open_bell.announce_open(_FRIDAY_0930)
        ok2, _ = open_bell.announce_open(_FRIDAY_1500)
        assert ok1 is True and ok2 is True
        assert len(sent) == 2
        assert "Leg 1" in sent[0] and "Leg 2" in sent[1]

    def test_silent_on_weekend(self, bell, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, note = open_bell.announce_open(_SATURDAY)
        assert ok is False and "no session" in note
        assert sent == []

    def test_silent_on_psx_holiday(self, bell, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, note = open_bell.announce_open(_HOLIDAY_MONDAY)
        assert ok is False and "no session" in note
        assert sent == []

    def test_silent_outside_session_hours(self, bell, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, note = open_bell.announce_open(_MONDAY_0800)
        assert ok is False and "not open" in note
        assert sent == []

    def test_refused_send_retries_next_pass(self, bell, monkeypatch):
        calls = []

        def flaky(msg):
            calls.append(msg)
            return len(calls) > 1  # first pass refused, second succeeds

        monkeypatch.setattr("notify.send_telegram", flaky)
        ok1, note1 = open_bell.announce_open(_MONDAY_0945)
        ok2, _ = open_bell.announce_open(_MONDAY_0945)
        assert ok1 is False and "retry" in note1
        assert ok2 is True
        assert len(calls) == 2  # the card was not lost, only delayed

    def test_kill_switch_off_silences(self, bell, monkeypatch):
        cfg_path = open_bell.CONFIG_FILE
        cfg_path.write_text(
            json.dumps({"open_bell_enabled": False}), encoding="utf-8"
        )
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, note = open_bell.announce_open(_MONDAY_0945)
        assert ok is False and "kill-switch" in note
        assert sent == []
        assert not bell.exists()  # no state was written either

    def test_missing_config_defaults_on(self, bell, monkeypatch):
        open_bell.CONFIG_FILE.unlink()
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, _ = open_bell.announce_open(_MONDAY_0945)
        assert ok is True and len(sent) == 1

    def test_open_positions_named_in_card(self, bell, monkeypatch):
        book_path = open_bell.BOOK_FILE
        book_path.write_text(
            json.dumps(
                [
                    {"symbol": "PPL", "status": "CLOSED"},
                    {"symbol": "KEL", "status": "OPEN"},
                ]
            ),
            encoding="utf-8",
        )
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, _ = open_bell.announce_open(_MONDAY_0945)
        assert ok is True
        assert "1 open position(s)" in sent[0]

    def test_broken_book_file_never_raises(self, bell, monkeypatch):
        open_bell.BOOK_FILE.write_text("{not json", encoding="utf-8")
        sent = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        ok, _ = open_bell.announce_open(_MONDAY_0945)
        assert ok is True
        assert "unreadable" in sent[0]

    def test_raising_channel_never_raises_out(self, bell, monkeypatch):
        def boom(msg):
            raise RuntimeError("telegram down")

        monkeypatch.setattr("notify.send_telegram", boom)
        ok, note = open_bell.announce_open(_MONDAY_0945)  # must not raise
        assert ok is False and "failed (non-fatal)" in note

    def test_state_file_prunes_old_sessions(self, bell, monkeypatch):
        old = (sessions.trading_date(_MONDAY_0945) - timedelta(days=10)).isoformat()
        bell.write_text(
            json.dumps({old: [1], "2026-09-24": [1]}), encoding="utf-8"
        )
        monkeypatch.setattr("notify.send_telegram", lambda msg: True)
        open_bell.announce_open(_MONDAY_0945)
        state = json.loads(bell.read_text(encoding="utf-8"))
        assert old not in state
        assert "2026-09-24" in state  # inside the 7-day window, kept
        assert state["2026-09-28"] == [1]
