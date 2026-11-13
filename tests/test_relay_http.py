"""The relay reader's identity, and the alert that must never lie again.

Owner report 2026-11-12: the pre-open readiness mail said the relay was down
("HTTP 403") at 09:20 while the edge was serving the phone and every quote
push. Cloudflare's browser integrity check refuses a default Python user agent
with that exact status and the body "error code: 1010". These tests pin the
one shared reader every Actions job now uses, and pin that the two scheduled
readers cannot quietly fall back to a bare urllib call.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.relay_http import (  # noqa: E402
    RELAY_USER_AGENT,
    read_json,
    relay_headers,
)


class HeaderTest(unittest.TestCase):
    def test_the_reader_names_itself_in_a_browser_style(self):
        headers = relay_headers()
        self.assertTrue(headers["User-Agent"].startswith("Mozilla/5.0"))
        self.assertIn("QuantOfRehan", headers["User-Agent"])
        self.assertEqual(headers["Accept"], "application/json")

    def test_extra_headers_are_kept(self):
        self.assertEqual(relay_headers({"x-admin-token": "t"})["x-admin-token"],
                         "t")
        self.assertEqual(RELAY_USER_AGENT, relay_headers()["User-Agent"])


class Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class ReadTest(unittest.TestCase):
    def test_a_healthy_read_returns_the_payload(self):
        seen: dict = {}

        def fake(request, timeout=0):
            seen["ua"] = request.get_header("User-agent")
            return Response({"ok": True})

        with patch("urllib.request.urlopen", fake):
            payload, trouble = read_json("https://relay.test", "/health")
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(trouble, "")
        self.assertTrue(seen["ua"].startswith("Mozilla/5.0"))

    def test_an_edge_refusal_names_its_status_and_body(self):
        def fake(request, timeout=0):
            raise urllib.error.HTTPError(
                "https://relay.test/health", 403, "Forbidden", {},
                io.BytesIO(b"error code: 1010"))

        with patch("urllib.request.urlopen", fake):
            payload, trouble = read_json("https://relay.test", "/health",
                                         attempts=3)
        self.assertIsNone(payload)
        self.assertEqual(trouble, "HTTP 403 error code: 1010")

    def test_a_dead_network_names_its_exception(self):
        def fake(request, timeout=0):
            raise TimeoutError("timed out")

        with patch("urllib.request.urlopen", fake):
            payload, trouble = read_json("https://relay.test", "/quotes")
        self.assertIsNone(payload)
        self.assertEqual(trouble, "TimeoutError")


class WorkflowTest(unittest.TestCase):
    def workflow(self, name: str) -> str:
        return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_the_pre_open_check_reads_through_the_shared_reader(self):
        text = self.workflow("preopen-readiness.yml")
        self.assertIn("from src.data.relay_http import read_json", text)
        self.assertNotIn("urllib.request.urlopen(BASE", text)
        self.assertIn("preopen-ready:", text)

    def test_the_budget_guard_reads_through_the_shared_reader(self):
        text = self.workflow("relay-budget-guard.yml")
        self.assertIn("from src.data.relay_http import read_json", text)
        self.assertNotIn("urllib.request.urlopen(BASE", text)


if __name__ == "__main__":
    unittest.main()
