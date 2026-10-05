"""WhatsApp (CallMeBot) second backup channel - contract tests.

The owner's order (2026-09-27): every BUY/EXIT card also lands on his
WhatsApp, sent through the CallMeBot relay once he adds the two repo
secrets. These tests pin the same promises the Telegram channel makes:
silent no-op without secrets, config picked up from the environment,
and the event card riding the same delivery moment as Telegram.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import notify


def test_whatsapp_silent_noop_without_secrets(monkeypatch):
    monkeypatch.delenv("CALLMEBOT_PHONE", raising=False)
    monkeypatch.delenv("CALLMEBOT_APIKEY", raising=False)
    importlib.reload(notify)
    assert notify._whatsapp_config() is None
    assert notify.send_whatsapp("hi") is False
    assert notify.send_event_whatsapp("BUY", {"fields": {}}) is False


def test_whatsapp_config_from_environment(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    importlib.reload(notify)
    assert notify._whatsapp_config() == ("+923001234567", "123456")


def test_whatsapp_needs_both_secrets(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.delenv("CALLMEBOT_APIKEY", raising=False)
    importlib.reload(notify)
    assert notify._whatsapp_config() is None


def test_event_card_carries_the_message_body(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    importlib.reload(notify)
    seen = {}

    def fake_send(message: str) -> bool:
        seen["message"] = message
        return True

    monkeypatch.setattr(notify, "send_whatsapp", fake_send)
    ok = notify.send_event_whatsapp("BUY", {"kind": "BUY", "fields": {"symbol": "PSO"}})
    assert ok is True
    assert "BUY" in seen["message"] and "PSO" in seen["message"]


def test_telegram_delivery_also_fires_whatsapp(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    importlib.reload(notify)
    fired = {"whatsapp": 0}

    monkeypatch.setattr(
        notify, "send_telegram", lambda message: True
    )

    def fake_send_whatsapp(kind: str, event: dict) -> bool:
        fired["whatsapp"] += 1
        return True

    monkeypatch.setattr(notify, "send_event_whatsapp", fake_send_whatsapp)
    event = {"kind": "BUY", "fields": {"symbol": "PSO"}}
    assert notify.send_event_telegram(event) is True
    assert fired["whatsapp"] == 1, "Telegram success must also fire WhatsApp"


def test_telegram_failure_does_not_fire_whatsapp(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    importlib.reload(notify)
    fired = {"whatsapp": 0}

    monkeypatch.setattr(notify, "send_telegram", lambda message: False)

    def fake_send_whatsapp(kind: str, event: dict) -> bool:
        fired["whatsapp"] += 1
        return True

    monkeypatch.setattr(notify, "send_event_whatsapp", fake_send_whatsapp)
    event = {"kind": "BUY", "fields": {"symbol": "PSO"}}
    assert notify.send_event_telegram(event) is False
    assert fired["whatsapp"] == 0, "WhatsApp rides Telegram success, never failure"
