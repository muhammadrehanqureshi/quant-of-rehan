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
from src.data.feed_capture import CaptureSession, parse_message  # noqa: E402
from src.data.ohlc_poller import (  # noqa: E402
    OhlcPoller, capture_coverage_ok, make_opener,
)
from scripts.ops_alert import capture_health_message, main as ops_main  # noqa: E402


KARACHI = timezone(timedelta(hours=5))


class TestTickFrameParsing(unittest.TestCase):
    """A tick frame carries several symbols, and all of them must be banked.

    Measured on the 2026-10-12 capture: 902 rows arrived and the parser kept
    64 of them, because it split the frame on '$' (a separator this wire does
    not use) and read each frame as a single row. The other symbols in every
    frame were banked as unnamed numeric slots: real exchange data, unusable,
    and silently so. The wire separates rows with '||'.

    The field map was corrected on the same wire on the same day: the bid and
    ask live at [3] and [4], the last price at [10] and the market status at
    [6]. The older map read [6] as the ask, so the quote rule in
    src/data/tick_volume.py was reading "OPN" as a price and no row could
    ever be classified. The assertions below pin the corrected positions.
    """

    ROW = ("{sym};REG;22;1568.00;1569.00;49;OPN;-;-15.32;10:24:02;1568.00; "
           ";1569.21;1578.00;1555.56;799;39285;9;1583.32;1555.56")

    def frame(self, symbols: list[str]) -> dict:
        payload = "||".join(self.ROW.format(sym=s) for s in symbols)
        return parse_message(f"MKT-FEED*{payload}")

    def test_every_row_in_the_frame_becomes_a_named_tick(self):
        record = self.frame(["SAZEW", "PSEL", "LUCK", "PICT"])
        self.assertEqual([t["scrip"] for t in record["ticks"]],
                         ["SAZEW", "PSEL", "LUCK", "PICT"])
        for tick in record["ticks"]:
            self.assertEqual(tick["market"], "REG")
            self.assertEqual(tick["change_sign"], "-")
            self.assertEqual(tick["bid"], "1568.00")
            self.assertEqual(tick["ask"], "1569.00")
            self.assertEqual(tick["last"], "1568.00")
            self.assertEqual(tick["status"], "OPN")
            self.assertEqual(tick["trades"], "799")
            self.assertEqual(tick["volume"], "39285")
            self.assertEqual(tick["last_volume"], "9")

    def test_a_frame_of_one_row_still_parses(self):
        record = self.frame(["OGDC"])
        self.assertEqual(len(record["ticks"]), 1)
        self.assertEqual(record["ticks"][0]["scrip"], "OGDC")

    def test_the_older_dollar_separator_is_still_accepted(self):
        """A capture written by an older recon of the wire still reads."""
        payload = "$".join(self.ROW.format(sym=s) for s in ["OGDC", "PSO"])
        record = parse_message(f"MKT-FEED*{payload}")
        self.assertEqual([t["scrip"] for t in record["ticks"]], ["OGDC", "PSO"])

    def test_a_non_tick_frame_is_never_split_into_ticks(self):
        """A stats frame's semicolon list is a different layout (SO-3)."""
        record = parse_message("MKT-STATS*REG;OPEN;150219.00;17799.00")
        self.assertEqual(len(record["ticks"]), 1)
        self.assertNotIn("scrip", record["ticks"][0])


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


class TestTheCaptureAlertQuotesItsCause(unittest.TestCase):
    """The owner's alert must carry the measured cause, not an assumption.

    Live 2026-10-12: the deduped alert asserted "the KMIALL intraday data
    source is not serving bars" while the flag held no cause at all, so the
    one sentence the owner received was a guess dressed as a finding. The
    capture pass now measures which way the source refused, the flag carries
    that, and the alert quotes it.
    """

    def message(self, payload: dict) -> str:
        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            flag.write_text(json.dumps(payload), encoding="utf-8")
            with patch("scripts.ops_alert.FLAG", flag):
                return capture_health_message()

    def test_the_measured_cause_is_quoted_when_the_flag_carries_one(self):
        text = self.message({
            "coverage": 0.0, "symbols_ok": 0, "universe": 319,
            "cause": "319 of 319 symbol(s) failed: 319 answered with no bars "
                     "(the bare acknowledgement from every mirror)",
        })

        self.assertIn("Measured cause:", text)
        self.assertIn("bare acknowledgement", text)
        self.assertIn("0/319 symbols", text)

    def test_a_flag_without_a_cause_does_not_invent_one(self):
        text = self.message({"coverage": 0.0, "symbols_ok": 0,
                             "universe": 319})

        self.assertIn("capture degraded", text)
        self.assertNotIn("Measured cause:", text)


if __name__ == "__main__":
    unittest.main()

