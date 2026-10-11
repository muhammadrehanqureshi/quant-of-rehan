"""Capture-contract tests for the eClear 1-minute OHLC poller.

Context (measured live 2026-10-09, 10:20-10:45 PKT, inside the Friday
session): `vt.eclear.com.pk/pero/GetOHLCData` answers HTTP 200 with the bare
body `SYM;REG;` and ZERO bar rows for every symbol (including a nonexistent
scrip), every interval, every market value, every header set and with and
without cookies. The other configured mirrors 404 on that path. The source
therefore serves no OHLC at present.

These tests pin the properties that keep that outage honest instead of
turning it into a fake capture:

  * a bare acknowledgement (or an empty body) is a FAILED symbol, never an
    empty set of genuine bars;
  * rows for another symbol are never copied onto the requested symbol;
  * malformed rows are dropped while genuine rows survive;
  * coverage stays fail-closed below 80%, so no scan can run;
  * repeated bar times are never banked twice.

Everything here is offline: the opener is a stub, so the suite never touches
the network, never hammers the endpoint, and does not fail merely because
the vendor is still down.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.ohlc_poller as poller  # noqa: E402
from src.data.ohlc_poller import (  # noqa: E402
    acknowledged_without_bars,
    capture_coverage_ok,
    fetch_bars,
    fetch_body,
)


AK = "OGDC"


class _Response:
    """Minimal stand-in for the http.client response used by urllib."""

    def __init__(self, body: bytes):
        self._body = body
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class _Open:
    """Opener stub: maps each host to a body, or to an exception to raise."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.requested: list[str] = []

    def open(self, request, timeout=None):
        host = request.full_url.split("//", 1)[1].split("/", 1)[0]
        self.requested.append(host)
        outcome = self.responses.get(host)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            raise OSError(f"no route to {host}")
        return _Response(outcome)


def _opener(**responses: bytes | Exception) -> _Open:
    return _Open({host.replace("__", "."): body for host, body in responses.items()})


class TestAcknowledgedWithoutBars(unittest.TestCase):
    def test_bare_acknowledgement_is_not_data(self):
        self.assertTrue(acknowledged_without_bars(f"{AK};REG;\r\n"))

    def test_market_echo_variants_are_still_acknowledgements(self):
        for body in (f"{AK};FUT;\r\n", f"{AK};REGULAR;\r\n", f"{AK};REG;"):
            with self.subTest(body=body):
                self.assertTrue(acknowledged_without_bars(body))

    def test_empty_and_whitespace_bodies_are_not_data(self):
        self.assertTrue(acknowledged_without_bars(""))
        self.assertTrue(acknowledged_without_bars("  \r\n "))

    def test_genuine_bar_row_is_data(self):
        self.assertFalse(
            acknowledged_without_bars(f"{AK};REG;10;11;9;10.5;09:31|")
        )

    def test_multiple_rows_are_data(self):
        body = f"{AK};REG;10;11;9;10.5;09:31|{AK};REG;10.5;12;10;11.8;09:32|"
        self.assertFalse(acknowledged_without_bars(body))


class TestFetchBars(unittest.TestCase):
    def test_genuine_rows_parse_in_order_with_ohlc(self):
        body = (f"{AK};REG;10.0;11.0;9.5;10.5;09:31|"
                f"{AK};REG;10.5;12.0;10.0;11.8;09:32|").encode()
        bars = fetch_bars(_opener(**{"vt__eclear__com__pk": body}), AK)

        self.assertEqual([b["t"] for b in bars], ["09:31", "09:32"])
        self.assertEqual(bars[0], {"t": "09:31", "o": 10.0, "h": 11.0,
                                   "l": 9.5, "c": 10.5})
        self.assertIsInstance(bars[1]["c"], float)

    def test_live_acknowledgement_returns_none_not_zero_bars(self):
        opener = _opener(**{"vt__eclear__com__pk": b"OGDC;REG;\r\n"})
        self.assertIsNone(fetch_bars(opener, AK))

    def test_empty_body_returns_none(self):
        opener = _opener(**{"vt__eclear__com__pk": b""})
        self.assertIsNone(fetch_bars(opener, AK))

    def test_acknowledgement_prefix_does_not_poison_genuine_rows(self):
        body = f"{AK};REG;|{AK};REG;10;11;9;10.5;09:31|".encode()
        bars = fetch_bars(_opener(**{"vt__eclear__com__pk": body}), AK)
        self.assertEqual([b["t"] for b in bars], ["09:31"])

    def test_non_finite_prices_are_never_banked(self):
        body = (f"{AK};REG;nan;11;9;10.5;09:31|"
                f"{AK};REG;inf;11;9;10.5;09:32|"
                f"{AK};REG;10.5;12;10;11.8;09:33|").encode()
        bars = fetch_bars(_opener(**{"vt__eclear__com__pk": body}), AK)
        self.assertEqual([b["t"] for b in bars], ["09:33"])

    def test_falls_through_to_the_next_mirror(self):
        opener = _opener(
            vt__eclear__com__pk=OSError("unexpected eof"),
            nxg1__eclear__com__pk=f"{AK};REG;10;11;9;10.5;09:31|".encode(),
        )
        bars = fetch_bars(opener, AK)

        self.assertEqual(len(bars), 1)
        self.assertEqual(opener.requested, ["vt.eclear.com.pk", "nxg1.eclear.com.pk"])

    def test_all_mirrors_failing_returns_none(self):
        opener = _opener(
            vt__eclear__com__pk=OSError("unexpected eof"),
            nxg1__eclear__com__pk=OSError("unexpected eof"),
            nxg2__eclear__com__pk=OSError("unexpected eof"),
        )
        self.assertIsNone(fetch_bars(opener, AK))
        self.assertEqual(len(opener.requested), len(poller.OHLC_HOSTS))

    def test_another_symbols_rows_are_never_copied(self):
        body = b"PRL;REG;10;11;9;10.5;09:31|PRL;REG;10.5;12;10;11.8;09:32|"
        self.assertIsNone(fetch_bars(_opener(**{"vt__eclear__com__pk": body}), AK))

    def test_malformed_rows_are_dropped_and_valid_rows_survive(self):
        body = (f"{AK};REG;not-a-number;11;9;10.5;09:31|"
                f"{AK};REG;10.5;12;10;11.8;09:32|"
                f"{AK};REG;11;12;10;11.5|").encode()
        bars = fetch_bars(_opener(**{"vt__eclear__com__pk": body}), AK)

        self.assertEqual([b["t"] for b in bars], ["09:32"])
        self.assertEqual(bars[0]["c"], 11.8)

    def test_fetch_body_reports_the_answering_host(self):
        opener = _opener(**{"vt__eclear__com__pk": b"OGDC;REG;\r\n"})
        host, raw = fetch_body(opener, AK)
        self.assertEqual(host, "vt.eclear.com.pk")
        self.assertEqual(raw, b"OGDC;REG;\r\n")

    def test_fetch_body_returns_none_when_no_mirror_answers(self):
        self.assertIsNone(fetch_body(_opener(), AK))


class TestCoverageGate(unittest.TestCase):
    def test_outage_coverage_is_rejected(self):
        self.assertFalse(capture_coverage_ok(0, 319))
        self.assertFalse(capture_coverage_ok(1, 319))

    def test_coverage_boundary_is_eighty_percent(self):
        self.assertTrue(capture_coverage_ok(256, 320))
        self.assertFalse(capture_coverage_ok(255, 320))

    def test_empty_universe_is_rejected(self):
        self.assertFalse(capture_coverage_ok(0, 0))


class TestBanking(unittest.TestCase):
    def _bank(self, calls: list[list[dict]]) -> tuple[dict, list[dict]]:
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_dir = Path(temp_dir)
            with patch.object(poller, "CAPTURE_DIR", capture_dir):
                machine = poller.OhlcPoller([AK], once=True)
                for bars in calls:
                    machine.bank(AK, bars)
                machine._fh.close()
                machine._fh = None
            written = [json.loads(line) for line in
                       (capture_dir / f"ohlc_{poller.now():%Y%m%d}.ndjson")
                       .read_text(encoding="utf-8").splitlines()]
        return machine.counters, written

    def test_repeated_bar_times_are_banked_once(self):
        bar = {"t": "09:31", "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5}
        counters, written = self._bank([[bar], [bar], [{**bar, "t": "09:32"}]])

        self.assertEqual(counters["bars"], 2)
        self.assertEqual(len(written), 2)
        self.assertEqual([record["symbol"] for record in written], [AK, AK])
        self.assertEqual([b["t"] for record in written for b in record["bars"]],
                         ["09:31", "09:32"])

    def test_nothing_is_banked_from_repeats_only(self):
        bar = {"t": "09:31", "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5}
        counters, written = self._bank([[bar], [bar]])

        self.assertEqual(counters["bars"], 1)
        self.assertEqual(len(written), 1)


class TestPassBudget(unittest.TestCase):
    """A pass must be able to tell a short refresh from a complete one.

    Found in logs/kmiall_tick.log (owner report 2026-10-11): on a trading day
    every single tick logged "capture FAILED: capture timed out after 240s",
    while one sequential pass over the 319 symbol universe needs about seven
    minutes. The limit was smaller than the work, so the pass was killed
    mid-flight and the logged reason was never the truth. The poller now stops
    itself at a budget and says what it did not reach.
    """

    BAR = {"t": "09:31", "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5}

    def _machine(self, symbols: list[str], deadline: float | None,
                 bars: list[dict] | None = None):
        """A poller whose fetch, status and banks never touch real data."""
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        machine = poller.OhlcPoller(symbols, once=True,
                                    deadline_seconds=deadline)
        self.addCleanup(patch.stopall)
        self.addCleanup(machine.close)
        patch.object(poller, "CAPTURE_DIR", Path(temp_dir.name)).start()
        patch.object(poller, "STATUS_PATH",
                     Path(temp_dir.name) / "ohlc_status.json").start()
        patch.object(poller, "fetch_bars",
                     return_value=([self.BAR] if bars is None else bars)
                     ).start()
        patch.object(poller.time, "sleep", lambda _seconds: None).start()
        return machine

    def test_the_nominal_estimate_scales_with_the_universe(self):
        self.assertEqual(poller.nominal_pass_seconds(0), 0)
        self.assertAlmostEqual(poller.nominal_pass_seconds(200),
                               2 * poller.nominal_pass_seconds(100), places=6)
        # Calibrated on the measured pass: 741s for 319 symbols in CI.
        self.assertAlmostEqual(
            poller.nominal_pass_seconds(319),
            319 * (poller.PACING_SECONDS + poller.REQUEST_ALLOWANCE_SECONDS),
            places=6)

    def test_the_budget_is_the_cadence_minus_the_scan_reserve(self):
        self.assertEqual(
            poller.capture_budget_seconds(240, reserve_seconds=45), 195.0)
        self.assertEqual(poller.capture_budget_seconds(240),
                         240 - poller.config.CAPTURE_BUDGET_RESERVE_SECONDS)

    def test_a_silly_cadence_still_gets_a_usable_floor(self):
        self.assertEqual(poller.capture_budget_seconds(10), 60.0)

    def test_a_spent_budget_stops_the_pass_before_any_fetch(self):
        machine = self._machine(["A", "B", "C"], deadline=0)
        machine.run_pass()

        self.assertFalse(machine.pass_complete)
        self.assertEqual(machine.counters["symbols_skipped"], 3)
        self.assertEqual(machine.counters["symbols_ok"], 0)
        poller.fetch_bars.assert_not_called()

    def test_a_pass_inside_its_budget_is_complete(self):
        machine = self._machine(["A", "B"], deadline=600)
        machine.run_pass()

        self.assertTrue(machine.pass_complete)
        self.assertEqual(machine.counters["symbols_skipped"], 0)
        self.assertEqual(machine.counters["symbols_ok"], 2)

    def test_the_status_file_carries_the_budget_and_completeness(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            status = Path(temp_dir) / "ohlc_status.json"
            machine = poller.OhlcPoller(["A"], once=True, deadline_seconds=0)
            with patch.object(poller, "STATUS_PATH", status), \
                    patch.object(poller, "CAPTURE_DIR", Path(temp_dir)), \
                    patch.object(poller.time, "sleep", lambda _s: None):
                machine.run_pass()
            saved = json.loads(status.read_text(encoding="utf-8"))

        self.assertEqual(saved["budget_seconds"], 0)
        self.assertFalse(saved["pass_complete"])
        self.assertEqual(saved["counters"]["symbols_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
