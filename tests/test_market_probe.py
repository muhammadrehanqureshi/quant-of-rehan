"""Offline tests for the live PSX market-state probe.

The parser is checked against the portal's own markup, captured verbatim on
2026-10-10 into tests/fixtures/psx_portal_market_panel.html. Every network path
is mocked, so this suite passes with the network unplugged.

The properties that matter here are not "does it read the page" but:

  * it never raises, whatever the socket does;
  * it never guesses: an unrecognised or empty state is UNKNOWN, not CLOSED;
  * it reads the Regular segment and cannot be fooled by another segment.
"""

from __future__ import annotations

import socket
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.market_probe import (  # noqa: E402
    REGULAR_SEGMENT,
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    classify_state,
    parse_market_panel,
    parse_regular_state,
    probe_market_state,
)

FIXTURE = (Path(__file__).resolve().parent / "fixtures"
           / "psx_portal_market_panel.html")


def segment(key: str, state: str) -> str:
    """One market segment block, in the portal's own shape."""
    return (f'<div class="glide__slide" data-key="{key}">'
            f'<div class="markets__item__title c0">Segment {key}</div>'
            f'<div class="markets__item__stat">'
            f'<div class="markets__item__stat__label">State</div>'
            f'<div>{state}</div></div></div>')


def page(*blocks: str) -> str:
    return '<div class="glide__slides">' + "".join(blocks) + "</div>"


def fake_response(payload: bytes) -> mock.MagicMock:
    """A urlopen() context manager returning `payload` from read()."""
    response = mock.MagicMock()
    response.read.return_value = payload
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    return response


class TestParserAgainstRealMarkup(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")

    def test_fixture_is_present_and_real(self):
        self.assertGreater(len(self.html), 2000,
                           "fixture should be the portal's real panel")

    def test_reads_every_segment(self):
        panel = parse_market_panel(self.html)
        for key in ("REG", "BNB", "DFC", "CSF", "ODL", "SQR", "SIF", "NDM",
                    "MTS"):
            self.assertIn(key, panel)

    def test_regular_market_state_from_the_live_page(self):
        # Captured Saturday 2026-10-10: the equity market read Closed.
        self.assertEqual(parse_regular_state(self.html), "Closed")

    def test_regular_is_not_confused_with_the_suspended_segment(self):
        panel = parse_market_panel(self.html)
        self.assertEqual(panel["MTS"], "Suspended")
        self.assertNotEqual(parse_regular_state(self.html), "Suspended")

    def test_parses_an_open_page(self):
        self.assertEqual(parse_regular_state(page(segment("REG", "Open"))),
                         "Open")


class TestSegmentSelection(unittest.TestCase):
    def test_reads_regular_not_the_first_or_last_segment(self):
        html = page(segment("BNB", "Closed"),
                    segment("REG", "Open"),
                    segment("MTS", "Suspended"))
        self.assertEqual(parse_regular_state(html), "Open")

    def test_block_without_a_state_stat_is_not_a_segment(self):
        stray = '<div class="glide__slide" data-key="XYZ"><div>no state</div></div>'
        html = page(stray, segment("REG", "Closed"))
        panel = parse_market_panel(html)
        self.assertNotIn("XYZ", panel)
        self.assertEqual(panel["REG"], "Closed")

    def test_missing_regular_segment_is_none_not_empty_string(self):
        self.assertIsNone(parse_regular_state(page(segment("BNB", "Open"))))

    def test_empty_document(self):
        self.assertEqual(parse_market_panel(""), {})
        self.assertIsNone(parse_regular_state(""))


class TestClassifyNeverGuesses(unittest.TestCase):
    def test_open_words(self):
        for word in ("Open", "open", "OPEN", "  Open  ", "Trading",
                     "In Progress", "Live"):
            with self.subTest(word=word):
                status, _ = classify_state(word)
                self.assertEqual(status, STATUS_OPEN)

    def test_closed_words(self):
        for word in ("Closed", "closed", "Suspended", "Halted", "Pre-Open",
                     "Closing Auction", "Not Opened", "Settlement"):
            with self.subTest(word=word):
                status, _ = classify_state(word)
                self.assertEqual(status, STATUS_CLOSED)

    def test_unknown_words_are_not_guessed(self):
        for word in ("Whatever", "Restricted", "?", "Officially weird"):
            with self.subTest(word=word):
                status, note = classify_state(word)
                self.assertEqual(status, STATUS_UNKNOWN)
                self.assertIn("not guessed", note)

    def test_missing_and_empty_states_are_unknown(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                status, _ = classify_state(value)
                self.assertEqual(status, STATUS_UNKNOWN)

    def test_note_quotes_the_portal_word(self):
        _, note = classify_state("Closed")
        self.assertIn("Closed", note)


class TestProbeNeverRaises(unittest.TestCase):
    def test_reads_the_panel_through_a_real_response_object(self):
        payload = FIXTURE.read_bytes()
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(payload)):
            result = probe_market_state()
        self.assertEqual(result.status, STATUS_CLOSED)
        self.assertEqual(result.raw_state, "Closed")
        self.assertTrue(result.verified)
        self.assertIs(result.is_open, False)
        self.assertEqual(result.segment, REGULAR_SEGMENT)

    def test_open_page_round_trip(self):
        payload = page(segment("REG", "Open")).encode("utf-8")
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(payload)):
            result = probe_market_state()
        self.assertEqual(result.status, STATUS_OPEN)
        self.assertIs(result.is_open, True)

    def test_applies_the_configured_timeout(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(b"<html></html>")) as opened:
            probe_market_state(timeout=3.5)
        self.assertEqual(opened.call_args.kwargs.get("timeout"), 3.5)

    def test_timeout_argument_overrides_config(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(b"<html></html>")) as opened:
            probe_market_state(timeout=1.25)
        self.assertEqual(opened.call_args.kwargs.get("timeout"), 1.25)

    def test_network_failures_return_unknown_and_never_raise(self):
        failures = {
            "timeout": socket.timeout("timed out"),
            "urlerror": urllib.error.URLError("dns"),
            "typed_urlerror": urllib.error.URLError(
                socket.timeout("timed out")),
            "connection_reset": ConnectionResetError("reset"),
            "oserror": OSError("broken"),
            "value_error": ValueError("nonsense"),
            "runtime_error": RuntimeError("unexpected"),
        }
        for label, exc in failures.items():
            with self.subTest(failure=label):
                with mock.patch("urllib.request.urlopen", side_effect=exc):
                    result = probe_market_state()
                self.assertEqual(result.status, STATUS_UNKNOWN)
                self.assertFalse(result.verified)
                self.assertIsNone(result.is_open)
                self.assertTrue(result.note)

    def test_http_status_is_reported_with_its_code(self):
        error = urllib.error.HTTPError("https://dps.psx.com.pk/", 503,
                                       "Service Unavailable", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            result = probe_market_state()
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn("503", result.note)

    def test_unparseable_body_is_unknown_not_closed(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(b"<html>nothing</html>")):
            result = probe_market_state()
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertIn(REGULAR_SEGMENT, result.note)

    def test_undecodable_bytes_do_not_raise(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(b"\xff\xfe\x00\x01")):
            result = probe_market_state()
        self.assertEqual(result.status, STATUS_UNKNOWN)

    def test_result_serialises_without_losing_the_verdict(self):
        with mock.patch("urllib.request.urlopen",
                        return_value=fake_response(FIXTURE.read_bytes())):
            payload = probe_market_state().as_dict()
        self.assertFalse(payload["is_open"])
        self.assertTrue(payload["verified"])
        self.assertEqual(payload["raw_state"], "Closed")


if __name__ == "__main__":
    unittest.main()
