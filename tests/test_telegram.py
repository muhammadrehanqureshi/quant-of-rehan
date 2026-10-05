"""Offline tests for the signal-only Telegram notifier (no network)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.notify import telegram  # noqa: E402


class TestLoadBotToken(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _env_file(self, content: str) -> Path:
        p = Path(self._tmp.name) / "t.env"
        p.write_text(content, encoding="utf-8")
        return p

    def test_env_var_wins(self):
        with mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "123:ABCDEF"}):
            self.assertEqual(telegram.load_bot_token(), "123:ABCDEF")

    def test_env_file_fallback(self):
        with mock.patch.object(telegram, "ENV_FILE",
                               self._env_file("# comment\nOTHER=x\nTELEGRAM_BOT_TOKEN=987:XYZABC\n")), \
             mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            self.assertEqual(telegram.load_bot_token(), "987:XYZABC")

    def test_chat_id_from_env_file(self):
        with mock.patch.object(telegram, "ENV_FILE",
                               self._env_file("TELEGRAM_CHAT_ID=424242\n")), \
             mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            resp = mock.Mock(status_code=200)
            resp.json.return_value = {"ok": True}
            with mock.patch.object(telegram.requests, "post", return_value=resp) as p, \
                 mock.patch.object(telegram.time, "sleep"):
                ok = telegram.send_message("hi", token="111:AAAAA", retries=1)
            self.assertTrue(ok)
            self.assertEqual(p.call_args.kwargs["json"]["chat_id"], "424242")

    def test_missing_returns_none(self):
        with mock.patch.object(telegram, "ENV_FILE", Path("/nonexistent/.env")), \
             mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            self.assertIsNone(telegram.load_bot_token())


class TestMaskToken(unittest.TestCase):
    def test_masks_secret_keeps_bot_id(self):
        self.assertEqual(telegram.mask_token("8714849787:AAExxxYyyZzzs38"),
                         "8714849787:***s38")

    def test_garbage_is_never_shown(self):
        self.assertEqual(telegram.mask_token("no-colon"), "***")


class TestSendMessage(unittest.TestCase):
    def _run(self, side_effects):
        with mock.patch.object(telegram.requests, "post",
                               side_effect=side_effects) as p, \
             mock.patch.object(telegram.time, "sleep"):
            ok = telegram.send_message(
                "test", token="111:AAAAA", chat_id="42", retries=3, pause_s=0.01)
        return ok, p

    def test_success_true_on_ok(self):
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"ok": True}
        ok, p = self._run([resp])
        self.assertTrue(ok)
        self.assertEqual(p.call_count, 1)
        # token must go to the URL path, never into a log
        self.assertIn("/bot111:AAAAA/", p.call_args.args[0])

    def test_fail_closed_after_retries(self):
        import requests as rq
        ok, p = self._run([rq.ReadTimeout()] * 3)
        self.assertFalse(ok)          # fail closed, no exception
        self.assertEqual(p.call_count, 3)

    def test_retries_on_http_error_then_succeeds(self):
        bad = mock.Mock(status_code=500)
        bad.json.return_value = {"ok": False, "description": "boom"}
        good = mock.Mock(status_code=200)
        good.json.return_value = {"ok": True}
        ok, p = self._run([bad, good])
        self.assertTrue(ok)
        self.assertEqual(p.call_count, 2)


class TestSignalOnlyGuard(unittest.TestCase):
    def test_module_exposes_no_trade_surface(self):
        # SO-1: the notifier must never gain order-placement surface.
        forbidden = {"place_order", "buy", "sell", "cancel_order"}
        for name in forbidden:
            self.assertFalse(hasattr(telegram, name))


if __name__ == "__main__":
    unittest.main()
