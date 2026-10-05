"""v2.0.1 delivery-layer contract tests.

The 2026-09-17 incident: SNGP closed at 20:19 PKT but no pass ran
after the closer, so the exit email never fired. These tests pin the
fixes: exits are collectable events, Telegram is a silent no-op
without secrets, and the closing paths stamp exit_ts.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import notify


def test_exit_events_collected(tmp_path, monkeypatch):
    monkeypatch.setattr(notify, "PORTFOLIO_PATH", tmp_path / "portfolio.json")
    (tmp_path / "portfolio.json").write_text(
        json.dumps(
            [
                {
                    "symbol": "SNGP",
                    "status": "CLOSED",
                    "exit_date": "2026-09-17",
                    "exit_ts": "2026-09-17T15:04:00+00:00",
                    "exit_price": 91.09,
                    "pnl_pct": 0.6,
                }
            ]
        )
    )
    events = notify.collect_events()
    exits = [e for e in events if e["kind"] == "EXIT"]
    assert exits, "a closed position must be a deliverable EXIT event"
    assert exits[0]["key"].startswith("exit:SNGP:2026-09-17")


def test_telegram_silent_noop_without_secrets(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    importlib.reload(notify)
    assert notify._telegram_config() is None
    assert notify.send_telegram("hi") is False
    assert notify.send_event_telegram({"kind": "BUY", "fields": {}}) is False


def test_telegram_enabled_with_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    importlib.reload(notify)
    assert notify._telegram_config() == ("t", "c")


def test_open_status_matching_is_case_insensitive(tmp_path, monkeypatch):
    # render_status_md reads ROOT/data/portfolio.json directly, so the
    # whole root is redirected to the temp tree.
    monkeypatch.setattr(notify, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "portfolio.json").write_text(
        json.dumps(
            [
                {"symbol": "X", "status": "OPEN", "entry_price": 10},
                {"symbol": "Y", "status": "open", "entry_price": 11},
                {"symbol": "Z", "status": "CLOSED", "entry_price": 12},
            ]
        )
    )
    html = notify.render_status_md()
    assert "X" in html and "Y" in html
    assert "book is flat" not in html
