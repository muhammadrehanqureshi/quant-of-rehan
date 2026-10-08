"""Regression tests for collector status and heartbeat freshness."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.capture_health import status_view  # noqa: E402
from src.data.feed_capture import CaptureSession  # noqa: E402
from src.data.ohlc_poller import (  # noqa: E402
    OhlcPoller, capture_coverage_ok, make_opener,
)
from scripts.ops_alert import capture_health_message, main as ops_main  # noqa: E402


KARACHI = timezone(timedelta(hours=5))


class TestCaptureHealth(unittest.TestCase):
    def test_fresh_heartbeat_with_pid_is_running(self):
        now = datetime(2026, 10, 7, 12, 0, tzinfo=KARACHI)
        view = status_view({
            "running": True,
            "pid": 1234,
            "updated_at": now.isoformat(),
        }, now=now)

        self.assertEqual(view["health_state"], "RUNNING")
        self.assertTrue(view["running"])
        self.assertEqual(view["heartbeat_age_seconds"], 0.0)

    def test_stale_heartbeat_is_not_reported_running(self):
        now = datetime(2026, 10, 7, 12, 2, tzinfo=KARACHI)
        old = now - timedelta(seconds=91)
        view = status_view({
            "running": True,
            "pid": 1234,
            "updated_at": old.isoformat(),
        }, now=now)

        self.assertEqual(view["health_state"], "STALE")
        self.assertFalse(view["running"])

    def test_missing_pid_is_unknown(self):
        now = datetime(2026, 10, 7, 12, 0, tzinfo=KARACHI)
        view = status_view({
            "running": True,
            "updated_at": now.isoformat(),
        }, now=now)

        self.assertEqual(view["health_state"], "UNKNOWN")
        self.assertFalse(view["running"])

    def test_ohlc_poller_verifies_tls_certificate_and_hostname(self):
        opener = make_opener()
        context = next(handler._context for handler in opener.handlers
                         if hasattr(handler, "_context"))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, __import__("ssl").CERT_REQUIRED)

    def test_one_pass_capture_requires_eighty_percent_symbol_coverage(self):
        self.assertTrue(capture_coverage_ok(80, 100))
        self.assertFalse(capture_coverage_ok(79, 100))
        self.assertFalse(capture_coverage_ok(0, 0))

    def test_capture_degraded_alert_says_what_happened(self):
        message = capture_health_message()
        self.assertIn("capture degraded", message)
        self.assertIn("production remains disabled", message)
        self.assertIn("once per day", message)
        self.assertNotIn("Entry reference", message)

    def test_capture_degraded_alert_includes_run_details_when_in_ci(self):
        with patch.dict(os.environ, {
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_RUN_ID": "123",
        }):
            message = capture_health_message()
        self.assertIn("https://github.com/owner/repo/actions/runs/123", message)

    def test_healthy_capture_writes_no_alert(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            with patch("scripts.ops_alert.FLAG", flag):
                self.assertEqual(ops_main(["--capture-health"]), 0)
            self.assertFalse(flag.exists())

    def test_low_coverage_flag_is_consumed_by_the_alert_step(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            flag.write_text(json.dumps({"coverage": 0.0, "symbols_ok": 0,
                                        "universe": 5}), encoding="utf-8")
            with patch("scripts.ops_alert.FLAG", flag), \
                    patch.dict(os.environ, {"RELAY_ADMIN_TOKEN": ""}):
                self.assertEqual(ops_main(["--capture-health"]), 0)
            # the flag is cleared either way so the next slot starts clean
            self.assertFalse(flag.exists())

    def test_closed_collectors_write_stopped_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            feed_status = directory / "feed_status.json"
            ohlc_status = directory / "ohlc_status.json"
            with patch("src.data.feed_capture.CAPTURE_DIR", directory), \
                    patch("src.data.feed_capture.STATUS_PATH", feed_status):
                feed = CaptureSession(["OGDC"], duration=1)
                feed.running = True
                feed.close()
            with patch("src.data.ohlc_poller.CAPTURE_DIR", directory), \
                    patch("src.data.ohlc_poller.STATUS_PATH", ohlc_status):
                poller = OhlcPoller(["OGDC"], once=True)
                poller.running = True
                poller.close()

            for status_path in (feed_status, ohlc_status):
                with self.subTest(path=status_path.name):
                    saved = json.loads(status_path.read_text(encoding="utf-8"))
                    self.assertFalse(saved["running"])
                    self.assertIsNone(saved["pid"])


if __name__ == "__main__":
    unittest.main()

