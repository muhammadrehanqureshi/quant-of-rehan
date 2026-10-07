"""Regression tests for collector status and heartbeat freshness."""

from __future__ import annotations

import json
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
from src.data.ohlc_poller import OhlcPoller  # noqa: E402


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

