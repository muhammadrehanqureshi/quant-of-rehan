"""Tests for relay URL resolution and the daily push preflight.

Owner bug report 2026-10-11: the scheduled daily push went red with a
traceback, `data/relay_url.txt missing`, and that traceback was the reason
line in the Telegram alert he received. The file is gitignored, so a fresh
GitHub Actions runner never has it, and the preflight read it before the job
wrote it. These tests hold the resolution order, hold the preflight to
returning a sentence instead of raising, and hold the write-then-preflight
order in scripts/signal_daily.py, which is load-bearing rather than cosmetic.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.sessions import MSG_MARKET_OPEN  # noqa: E402


def _relay_env(url: str):
    """An environment that pins RELAY_URL to one URL (other vars kept)."""
    return mock.patch.dict(os.environ, {"RELAY_URL": url}, clear=False)


def _no_relay_env():
    """An environment with RELAY_URL absent, so the file or default decides."""
    env = {k: v for k, v in os.environ.items() if k != "RELAY_URL"}
    return mock.patch.dict(os.environ, env, clear=True)


class TestRelayUrlResolution(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_the_env_url_is_used_before_the_file(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "relay_url.txt"), \
             mock.patch.object(sr, "NOTIFY_LOG",
                               Path(self._tmp.name) / "notify_log.jsonl"):
            sr.RELAY_URL_FILE.write_text("https://relay-file.example/\n")
            with _relay_env("https://relay-env.example/"):
                with mock.patch.object(sr, "send_via_relay",
                                       return_value=True) as send:
                    sr.deliver("OPEN", "open", MSG_MARKET_OPEN)
                self.assertEqual(send.call_args.args[0],
                                 "https://relay-env.example")

    def test_the_file_is_used_when_the_env_is_empty(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "relay_url.txt"), \
             mock.patch.object(sr, "NOTIFY_LOG",
                               Path(self._tmp.name) / "notify_log.jsonl"), \
             _no_relay_env():
            sr.RELAY_URL_FILE.write_text("https://relay-file.example/\n")
            self.assertEqual(sr.load_relay_url(), "https://relay-file.example")

    def test_nothing_configured_still_fails_closed(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "absent.txt"), \
             _no_relay_env():
            with self.assertRaises(RuntimeError) as caught:
                sr.load_relay_url()
        self.assertIn("relay_url.txt", str(caught.exception))
        self.assertIn("RELAY_URL", str(caught.exception))


class TestDailyPushPreflight(unittest.TestCase):
    """The CI path of scripts/signal_daily.py."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._scripts = Path(__file__).resolve().parents[1] / "scripts"
        sys.path.insert(0, str(self._scripts))
        self.addCleanup(self._drop_scripts_path)

    def _drop_scripts_path(self):
        while str(self._scripts) in sys.path:
            sys.path.remove(str(self._scripts))

    def _job(self):
        import signal_daily
        return signal_daily

    def test_the_url_file_is_written_before_the_preflight_reads_it(self):
        order: list[str] = []
        sd = self._job()
        with mock.patch.object(sd, "relay_url_file",
                               lambda: order.append("url_file")), \
             mock.patch.object(sd, "relay_preflight",
                               lambda: order.append("preflight") or ""), \
             mock.patch.object(sd, "fetch_window",
                               lambda kdate: order.append("fetch")), \
             mock.patch.object(sd, "filter_to_universe",
                               lambda: order.append("filter")), \
             mock.patch("src.signals.signal_push.main",
                        lambda argv=None: order.append("push") or 0):
            rc = sd.main([])
        self.assertEqual(rc, 0)
        self.assertEqual(order[:2], ["url_file", "preflight"])
        self.assertLess(order.index("preflight"), order.index("fetch"))

    def test_a_fresh_runner_resolves_a_url_with_no_config_at_all(self):
        """No env, no file: the preflight must still check a real URL."""
        root = Path(self._tmp.name)
        sd = self._job()
        from src.notify import schedule_runner as sr
        from src.signals import signal_push as sp
        with mock.patch.object(sd, "ROOT", root), \
             mock.patch.object(sd, "DEFAULT_RELAY", "https://relay.known"), \
             mock.patch.object(sr, "RELAY_URL_FILE",
                               root / "data" / "relay_url.txt"), \
             _no_relay_env():
            sd.relay_url_file()
            self.assertEqual(
                (root / "data" / "relay_url.txt").read_text(
                    encoding="utf-8").strip(),
                "https://relay.known")
            with mock.patch.object(sp, "read_admin_token", lambda: "t"), \
                 mock.patch.object(sp, "relay_preflight",
                                   lambda url, token: "" if
                                   url == "https://relay.known" else
                                   f"wrong url: {url}"):
                self.assertEqual(sd.relay_preflight(), "")

    def test_a_missing_url_is_reported_as_a_reason_never_raised(self):
        sd = self._job()
        from src.notify import schedule_runner as sr
        from src.signals import signal_push as sp
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "absent.txt"), \
             mock.patch.object(sp, "read_admin_token", lambda: "t"), \
             _no_relay_env():
            reason = sd.relay_preflight()
        self.assertIn("relay_url.txt", reason)
        self.assertIn("RELAY_URL", reason)
        self.assertNotIn("Traceback", reason)

    def test_a_missing_token_is_reported_as_a_reason_never_raised(self):
        sd = self._job()
        from src.signals import signal_push as sp
        with mock.patch.object(sp, "read_admin_token",
                               mock.Mock(side_effect=RuntimeError(
                                   "RELAY_ADMIN_TOKEN missing (env and .env)"))):
            reason = sd.relay_preflight()
        self.assertEqual(reason, "RELAY_ADMIN_TOKEN missing (env and .env)")


if __name__ == "__main__":
    unittest.main()
