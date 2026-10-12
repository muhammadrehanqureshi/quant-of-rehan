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
  * a mirror that answers with no bars never MASKS a mirror that is serving
    bars: the search continues to the next mirror, and the serving host is
    named so a fallback is visible instead of silent;
  * a source that has gone quiet is asked once per symbol, not once per
    mirror, so an outage cannot triple the load on a downed vendor;
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
    BarsFetch,
    acknowledged_without_bars,
    capture_coverage_ok,
    fetch_bars,
    fetch_bars_ex,
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


class TestMirrorFallThrough(unittest.TestCase):
    """A mirror with no bars must never mask a mirror that has them.

    The measured vendor behaviour is a bare `SYM;MKT;` acknowledgement, and
    the redundancy layer used to return on the first mirror that answered AT
    ALL: a primary that answered with nothing ended the search, so a healthy
    mirror was never asked and the symbol was charged as a coverage failure.
    A slot that loses symbols that way writes a coverage figure that is a lie
    about the source, which is exactly the silent drop these tests forbid.
    """

    BARS = f"{AK};REG;10;11;9;10.5;09:31|".encode()

    def test_an_empty_envelope_does_not_mask_a_serving_mirror(self):
        opener = _opener(
            vt__eclear__com__pk=f"{AK};REG;\r\n".encode(),
            nxg1__eclear__com__pk=self.BARS,
        )
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "ok")
        self.assertEqual(fetch.host, "nxg1.eclear.com.pk")
        self.assertEqual([b["t"] for b in fetch.bars], ["09:31"])
        self.assertEqual(opener.requested,
                         ["vt.eclear.com.pk", "nxg1.eclear.com.pk"])

    def test_an_empty_body_does_not_mask_a_serving_mirror(self):
        opener = _opener(vt__eclear__com__pk=b"", nxg1__eclear__com__pk=self.BARS)
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "ok")
        self.assertEqual(fetch.host, "nxg1.eclear.com.pk")

    def test_foreign_rows_do_not_mask_a_serving_mirror(self):
        opener = _opener(
            vt__eclear__com__pk=b"PRL;REG;10;11;9;10.5;09:31|",
            nxg2__eclear__com__pk=self.BARS,
        )
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "ok")
        self.assertEqual(fetch.host, "nxg2.eclear.com.pk")

    def test_malformed_only_rows_do_not_mask_a_serving_mirror(self):
        opener = _opener(
            vt__eclear__com__pk=f"{AK};REG;nan;11;9;10.5;09:31|".encode(),
            nxg1__eclear__com__pk=self.BARS,
        )
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "ok")
        self.assertEqual(fetch.host, "nxg1.eclear.com.pk")

    def test_the_serving_host_is_named_for_a_primary_capture(self):
        fetch = fetch_bars_ex(_opener(vt__eclear__com__pk=self.BARS), AK)
        self.assertEqual(fetch.host, "vt.eclear.com.pk")

    def test_every_mirror_answering_empty_is_no_bars_not_unreachable(self):
        """A mute source is not an unreachable one: the pass answers them differently."""
        opener = _opener(
            vt__eclear__com__pk=f"{AK};REG;\r\n".encode(),
            nxg1__eclear__com__pk=b"",
            nxg2__eclear__com__pk=f"{AK};REG;\r\n".encode(),
        )
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "no_bars")
        self.assertIsNone(fetch.bars)
        self.assertIsNone(fetch.host)
        self.assertEqual(len(opener.requested), len(poller.OHLC_HOSTS))

    def test_no_mirror_answering_is_unreachable(self):
        opener = _opener(
            vt__eclear__com__pk=OSError("unexpected eof"),
            nxg1__eclear__com__pk=OSError("unexpected eof"),
            nxg2__eclear__com__pk=OSError("unexpected eof"),
        )
        fetch = fetch_bars_ex(opener, AK)

        self.assertEqual(fetch.status, "unreachable")
        self.assertIsNone(fetch.bars)

    def test_fetch_bars_keeps_its_plain_contract(self):
        opener = _opener(vt__eclear__com__pk=f"{AK};REG;\r\n".encode(),
                         nxg1__eclear__com__pk=self.BARS)
        self.assertEqual([b["t"] for b in fetch_bars(opener, AK)], ["09:31"])

    def test_a_narrowed_host_list_is_honoured(self):
        """The pass may pin the search to one mirror; unreachable ones are skipped."""
        opener = _opener(  # only nxg1 is configured to answer
            nxg1__eclear__com__pk=self.BARS,
        )
        fetch = fetch_bars_ex(opener, AK, hosts=["nxg1.eclear.com.pk"])

        self.assertEqual(fetch.status, "ok")
        self.assertEqual(opener.requested, ["nxg1.eclear.com.pk"])


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
        patch.object(
            poller, "fetch_bars_ex",
            return_value=BarsFetch([self.BAR] if bars is None else bars, "ok",
                                   poller.OHLC_HOSTS[0]),
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
        poller.fetch_bars_ex.assert_not_called()

    def test_a_pass_inside_its_budget_is_complete(self):
        machine = self._machine(["A", "B"], deadline=600)
        machine.run_pass()

        self.assertTrue(machine.pass_complete)
        self.assertEqual(machine.counters["symbols_skipped"], 0)
        self.assertEqual(machine.counters["symbols_ok"], 2)

    def test_a_symbol_served_by_a_later_mirror_is_counted_as_a_fallback(self):
        machine = self._machine(["A", "B"], deadline=None)
        with patch.object(
                poller, "fetch_bars_ex",
                return_value=BarsFetch([self.BAR], "ok", poller.OHLC_HOSTS[1])):
            machine.run_pass()

        self.assertEqual(machine.counters["symbols_ok"], 2)
        self.assertEqual(machine.counters["fallback_symbols"], 2)

    def test_a_primary_capture_is_never_counted_as_a_fallback(self):
        machine = self._machine(["A", "B"], deadline=None)
        machine.run_pass()

        self.assertEqual(machine.counters["symbols_ok"], 2)
        self.assertEqual(machine.counters["fallback_symbols"], 0)

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


class TestDegradedSourcePoliteness(unittest.TestCase):
    """A source that has gone quiet is asked once per symbol, not once per mirror.

    All three mirrors are the same servlet, so falling through on every empty
    answer during a vendor outage would triple the request count on the host
    that is already down: 319 symbols x 3 hosts is more than twice the whole
    pass budget. After a short streak the pass pins itself to the first mirror
    and asks once per symbol, which is the pacing law this file already keeps.
    """

    def _machine(self, symbols: list[str]):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        machine = poller.OhlcPoller(symbols, once=True)
        self.addCleanup(patch.stopall)
        self.addCleanup(machine.close)
        patch.object(poller, "CAPTURE_DIR", Path(temp_dir.name)).start()
        patch.object(poller, "STATUS_PATH",
                     Path(temp_dir.name) / "ohlc_status.json").start()
        patch.object(poller.time, "sleep", lambda _seconds: None).start()
        return machine

    def _mute(self, hosts_seen: list[list[str]], status: str = "no_bars"):
        def fetch(_opener, _symbol, interval=1, hosts=None):
            hosts_seen.append(list(hosts or poller.OHLC_HOSTS))
            return BarsFetch(None, status, None)
        return fetch

    def test_a_mute_source_is_probed_once_per_symbol_after_the_streak(self):
        hosts_seen: list[list[str]] = []
        machine = self._machine(["A", "B", "C", "D", "E", "F"])
        with patch.object(poller, "fetch_bars_ex",
                          side_effect=self._mute(hosts_seen)):
            machine.run_pass()

        self.assertEqual(len(hosts_seen), 6)
        self.assertEqual(hosts_seen[0], list(poller.OHLC_HOSTS))
        self.assertEqual(hosts_seen[1], list(poller.OHLC_HOSTS))
        self.assertEqual(hosts_seen[2], list(poller.OHLC_HOSTS))
        # From the third quiet symbol on, one mirror only.
        self.assertEqual(hosts_seen[3], poller.OHLC_HOSTS[:1])
        self.assertEqual(hosts_seen[-1], poller.OHLC_HOSTS[:1])
        self.assertEqual(machine.counters["symbols_err"], 6)
        self.assertEqual(machine.counters["symbols_ok"], 0)

    def test_an_unreachable_source_narrows_the_same_way(self):
        hosts_seen: list[list[str]] = []
        machine = self._machine(["A", "B", "C", "D"])
        with patch.object(poller, "fetch_bars_ex",
                          side_effect=self._mute(hosts_seen, "unreachable")):
            machine.run_pass()

        self.assertEqual(hosts_seen[3], poller.OHLC_HOSTS[:1])

    def test_a_recovered_symbol_widens_the_search_again(self):
        """Widening matters: a brief outage must not pin the pass for good."""
        calls: list[list[str]] = []
        bars = {"t": "09:31", "o": 10.0, "h": 11.0, "l": 9.5, "c": 10.5}

        def flaky(_opener, symbol, interval=1, hosts=None):
            calls.append(list(hosts or poller.OHLC_HOSTS))
            if symbol in ("A", "B", "C"):
                return BarsFetch(None, "no_bars", None)
            return BarsFetch([bars], "ok", poller.OHLC_HOSTS[0])

        machine = self._machine(["A", "B", "C", "D", "E"])
        with patch.object(poller, "fetch_bars_ex", side_effect=flaky):
            machine.run_pass()

        # D is served after the streak, so E must be asked of every mirror again.
        self.assertEqual(calls[4], list(poller.OHLC_HOSTS))
        self.assertEqual(machine.counters["symbols_ok"], 2)

    def test_the_wide_search_is_restored_at_the_next_pass(self):
        hosts_seen: list[list[str]] = []
        machine = self._machine(["A", "B", "C", "D"])
        with patch.object(poller, "fetch_bars_ex",
                          side_effect=self._mute(hosts_seen)):
            machine.run_pass()
            machine.run_pass()

        # The second pass starts wide again rather than staying pinned.
        self.assertEqual(hosts_seen[4], list(poller.OHLC_HOSTS))
        self.assertEqual(machine.counters["passes"], 2)


class TestDiagnosticRunNeverPagesTheOwner(unittest.TestCase):
    """A --limit smoke test must not raise the market-wide degraded alert.

    Owner report 2026-10-12: a Telegram alert arrived reading "capture
    degraded (coverage 0.0%, 0/5 symbols)". The universal half of that was
    true, the source really was serving no bars, but "0/5" was not: it was the
    five symbol slice of a diagnostic run (this module documents `--limit 5`
    as its own smoke test), because the coverage gate compared the slice
    against itself and then wrote the production flag. A slice is not a
    market, and a smoke test must not be able to page the owner.
    """

    def _run(self, argv: list[str], universe: int = 8):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        flag = root / "ohlc_low_coverage.flag"
        patch.object(poller, "load_universe",
                     lambda *_a, **_k: [f"S{i}" for i in range(universe)]).start()
        patch.object(poller, "is_trading_day", lambda *_a, **_k: True).start()
        patch.object(poller, "CAPTURE_DIR", root).start()
        patch.object(poller, "STATUS_PATH", root / "ohlc_status.json").start()
        patch.object(poller, "LOW_COVERAGE_FLAG", flag).start()
        patch.object(poller, "fetch_bars_ex",
                     return_value=BarsFetch(None, "no_bars", None)).start()
        patch.object(poller.time, "sleep", lambda _seconds: None).start()
        self.addCleanup(patch.stopall)
        return poller.main(argv), flag

    def test_a_limited_run_never_writes_the_market_wide_flag(self):
        code, flag = self._run(["--once", "--limit", "5"])

        self.assertFalse(flag.exists(),
                         "a diagnostic slice must not raise the owner alert")
        self.assertEqual(code, 0)

    def test_the_slice_size_never_reaches_the_flag(self):
        """The 5 in "0/5 symbols" can no longer be produced by a 319 universe."""
        _code, flag = self._run(["--once", "--limit", "5"], universe=319)

        self.assertFalse(flag.exists())

    def test_a_full_run_with_no_bars_still_raises_the_flag(self):
        code, flag = self._run(["--once"])

        self.assertTrue(flag.exists(),
                        "a real market-wide outage must still be reported")
        payload = json.loads(flag.read_text(encoding="utf-8"))
        self.assertEqual(payload["universe"], 8)
        self.assertEqual(payload["symbols_ok"], 0)
        self.assertEqual(code, 0)

    def test_the_flag_reports_the_tracked_universe_not_a_slice(self):
        _code, flag = self._run(["--once"], universe=319)

        payload = json.loads(flag.read_text(encoding="utf-8"))
        self.assertEqual(payload["universe"], 319)


if __name__ == "__main__":
    unittest.main()
