"""WhatsApp (CallMeBot) second backup channel - contract tests.

The owner's order (2026-09-27): the pick, outcome and ops cards also
land on his WhatsApp, sent through the CallMeBot relay once he adds
the two repo secrets. These tests pin the same promises the Telegram
channel makes: silent no-op without secrets, config picked up from
the environment, and WhatsApp riding every successful Telegram send.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import telegram_notify


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("CALLMEBOT_PHONE", raising=False)
    monkeypatch.delenv("CALLMEBOT_APIKEY", raising=False)


def test_whatsapp_silent_noop_without_secrets():
    assert telegram_notify._whatsapp_config() is None
    assert telegram_notify._send_whatsapp("hi") is False


def test_whatsapp_config_from_environment(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    assert telegram_notify._whatsapp_config() == ("+923001234567", "123456")


def test_whatsapp_needs_both_secrets(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.delenv("CALLMEBOT_APIKEY", raising=False)
    assert telegram_notify._whatsapp_config() is None


def test_plain_strips_html_tags():
    text = "<b>PSO</b> entry 0.59 &amp; more &lt;up&gt;"
    assert telegram_notify._plain(text) == "PSO entry 0.59 & more <up>"


def test_successful_send_also_fires_whatsapp(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    fired = {"whatsapp": 0, "message": ""}

    monkeypatch.setattr(telegram_notify, "_config", lambda: ("t", "c"))

    class FakeResp:
        ok = True

    monkeypatch.setattr(
        telegram_notify.requests, "post", lambda *a, **k: FakeResp()
    )

    def fake_whatsapp(message: str) -> bool:
        fired["whatsapp"] += 1
        fired["message"] = message
        return True

    monkeypatch.setattr(telegram_notify, "_send_whatsapp", fake_whatsapp)
    assert telegram_notify.send("<b>PSO</b> buy") is True
    assert fired["whatsapp"] == 1
    assert "<b>" not in fired["message"], "the relay renders no HTML"
    assert "PSO" in fired["message"]


def test_failed_send_does_not_fire_whatsapp(monkeypatch):
    monkeypatch.setenv("CALLMEBOT_PHONE", "+923001234567")
    monkeypatch.setenv("CALLMEBOT_APIKEY", "123456")
    fired = {"whatsapp": 0}

    monkeypatch.setattr(telegram_notify, "_config", lambda: ("t", "c"))

    class FakeResp:
        ok = False

    monkeypatch.setattr(
        telegram_notify.requests, "post", lambda *a, **k: FakeResp()
    )
    monkeypatch.setattr(telegram_notify, "_send_whatsapp", lambda m: fired.__setitem__("whatsapp", fired["whatsapp"] + 1) or True)
    assert telegram_notify.send("pick card") is False
    assert fired["whatsapp"] == 0, "WhatsApp rides Telegram success, never failure"
