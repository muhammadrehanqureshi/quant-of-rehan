"""The tape capability report: measured from venue increments, never print sums.

Why this file exists: the broker feed echoes the same last print across
consecutive snapshots, so summing raw print sizes double counts it and can
even exceed the volume the venue itself reports traded. The report therefore
counts a print size only when the venue's cumulative volume actually moved,
and these tests pin that rule with tapes where the naive sum and the honest
sum disagree on purpose.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import tape_capability_report as tcr  # noqa: E402


def record(kind: str, at: str, ticks: list[dict] | None = None) -> dict:
    rec = {"kind": kind, "raw": "", "ts": at}
    if ticks is not None:
        rec["ticks"] = ticks
    return rec


def tick(symbol: str, volume: float, last: str, bid: str, ask: str,
         last_volume: float, market: str = "REG", status: str = "OPN",
         trades: float = 0) -> dict:
    """A modern tick: named fields plus the wire indexes, as the wire sends."""
    return {
        "scrip": symbol, "market": market, "status": status,
        "bid": bid, "ask": ask, "last": last,
        "volume": str(volume), "last_volume": str(last_volume),
        "trades": str(trades),
    }


class SummariseTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "capture_20261013.ndjson"

    def write(self, records: list[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec) + "\n")

    def test_a_print_size_counts_only_when_the_venue_volume_moved(self):
        # AAA: three snapshots, two real increments. The first snapshot's
        # print is not an increment, so its size is not counted.
        self.write([
            record("MKT-FEED", "2026-10-13T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", 0),
            ]),
            record("MKT-FEED", "2026-10-13T09:52:30+05:00", [
                tick("AAA", 160, "10.01", "9.99", "10.01", 40),
            ]),
            record("MKT-FEED", "2026-10-13T09:53:00+05:00", [
                tick("AAA", 200, "9.99", "9.99", "10.01", 30),
            ]),
        ])
        report = tcr.analyse(self.path)
        row = report["detail"][0]
        self.assertEqual(row["symbol"], "AAA")
        self.assertEqual(row["snapshots"], 3)
        self.assertEqual(row["median_gap_seconds"], 30.0)
        self.assertEqual(row["volume_delta"], 100)
        self.assertEqual(row["volume_steps"], 2)
        self.assertEqual(row["visible_new_print_sizes"], 70)
        self.assertAlmostEqual(row["print_fidelity"], 0.70)
        # Side is read from where the print traded, never from the change sign.
        self.assertEqual(row["buy_volume"], 60)     # the 160 step, at the ask
        self.assertEqual(row["sell_volume"], 40)    # the 200 step, at the bid
        self.assertEqual(row["unclassified_volume"], 0)
        self.assertEqual(row["prints_at_ask"], 1)
        self.assertEqual(row["prints_at_bid"], 1)
        self.assertEqual(row["prints_off_quote"], 1)
        self.assertEqual(row["distinct_last_prices"], 3)
        self.assertEqual(row["median_spread"], 0.02)

    def test_a_repeated_print_on_a_small_increment_is_counted_once(self):
        # CCC prints 50 shares while the venue total moves 2. The same print
        # is echoed on the next snapshot with no volume change at all.
        self.write([
            record("MKT-FEED", "2026-10-13T09:52:00+05:00", [
                tick("CCC", 5, "10.00", "9.99", "10.00", 50),
            ]),
            record("MKT-FEED", "2026-10-13T09:52:30+05:00", [
                tick("CCC", 7, "10.00", "9.99", "10.00", 50),
            ]),
            record("MKT-FEED", "2026-10-13T09:53:00+05:00", [
                tick("CCC", 7, "10.00", "9.99", "10.00", 50),
            ]),
        ])
        row = tcr.analyse(self.path)["detail"][0]
        self.assertEqual(row["volume_delta"], 2)
        self.assertEqual(row["volume_steps"], 1)
        # Counted once, and the overshoot is left visible rather than hidden.
        self.assertEqual(row["visible_new_print_sizes"], 50)
        self.assertEqual(row["print_fidelity"], 25.0)

    def test_a_quiet_symbol_reports_no_fidelity_instead_of_zero(self):
        # BBB is quoted but never trades: 0 volume must not read as 0% coverage.
        quiet = {"0": "BBB", "1": "REG", "2": "10", "3": "9.99", "4": "10.01",
                 "5": "10", "6": "OPN", "7": "=", "8": "0.00", "9": "09:52:00",
                 "10": "10.00", "11": " ", "12": "10.00", "13": "10.01",
                 "14": "9.99", "15": "0", "16": "10", "17": "5", "18": "10.00",
                 "19": "10.00"}
        self.write([
            record("MKT-FEED", "2026-10-13T09:52:00+05:00", [quiet]),
            record("MKT-FEED", "2026-10-13T09:52:30+05:00", [dict(quiet)]),
        ])
        report = tcr.analyse(self.path)
        row = report["detail"][0]
        self.assertEqual(row["symbol"], "BBB")      # read via the wire indexes
        self.assertEqual(row["volume_delta"], 0)
        self.assertEqual(row["volume_steps"], 0)
        self.assertIsNone(row["print_fidelity"])
        self.assertEqual(report["quiet_symbols"], 1)
        self.assertIsNone(report["median_print_fidelity"])

    def test_other_frames_and_other_markets_are_left_out(self):
        self.write([
            record("EXS-FEED", "2026-10-13T09:52:00+05:00", [
                tick("KSE100", 1, "165776.55", "0", "0", 0),
            ]),
            record("MKT-FEED", "2026-10-13T09:52:00+05:00", [
                tick("FUT9", 100, "10.00", "9.99", "10.01", 5, market="FUT"),
                tick("AAA", 100, "10.00", "9.99", "10.01", 5),
            ]),
            record("MKT-STATS", "2026-10-13T09:52:01+05:00"),
            record("MKT-FEED", "2026-10-13T09:52:30+05:00"),
        ])
        report = tcr.analyse(self.path)
        self.assertEqual([row["symbol"] for row in report["detail"]], ["AAA"])
        self.assertEqual(report["frames"]["EXS-FEED"], 1)
        self.assertEqual(report["frames"]["MKT-STATS"], 1)

    def test_the_aggregate_carries_the_numbers_the_doc_quotes(self):
        self.write([
            record("MKT-FEED", "2026-10-13T09:52:00+05:00", [
                tick("AAA", 0, "10.00", "9.99", "10.01", 0),
                tick("BBB", 0, "20.00", "19.99", "20.01", 0),
            ]),
            record("MKT-FEED", "2026-10-13T09:52:30+05:00", [
                tick("AAA", 100, "10.01", "9.99", "10.01", 60),
                tick("BBB", 200, "19.99", "19.99", "20.01", 40),
            ]),
        ])
        report = tcr.analyse(self.path, expected_universe=2)
        self.assertEqual(report["symbols"], 2)
        self.assertEqual(report["universe_coverage"], 1.0)
        self.assertEqual(report["volume_traded"], 300)
        self.assertEqual(report["buy_volume"], 100)
        self.assertEqual(report["sell_volume"], 200)
        self.assertEqual(report["unclassified_volume"], 0)
        self.assertEqual(report["unclassified_share"], 0.0)
        self.assertEqual(report["volume_steps"], 2)
        self.assertEqual(report["median_snapshot_gap_seconds"], 30.0)

    def test_blank_lines_and_a_missing_ticks_key_do_not_stop_the_read(self):
        with self.path.open("w", encoding="utf-8") as handle:
            handle.write("\n")
            handle.write(json.dumps(record("MKT-FEED",
                                           "2026-10-13T09:52:00+05:00")) + "\n")
            handle.write("   \n")
            handle.write(json.dumps(record("MKT-FEED",
                                           "2026-10-13T09:52:30+05:00",
                                           [tick("AAA", 10, "10.00",
                                                 "9.99", "10.01", 1)])) + "\n")
        report = tcr.analyse(self.path)
        self.assertEqual(report["symbols"], 1)


class MainTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.directory = Path(self.dir.name)
        self.path = self.directory / "capture_20261013.ndjson"
        self.path.write_text(
            json.dumps(record("MKT-FEED", "2026-10-13T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", 5),
            ])) + "\n", encoding="utf-8")

    def test_main_writes_the_report_and_returns_zero(self):
        out = self.directory / "report.json"
        code = tcr.main(["--file", str(self.path), "--json", str(out),
                         "--top", "1", "--expected", "319"])
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["file"], self.path.name)
        self.assertEqual(written["symbols"], 1)
        self.assertEqual(written["expected_universe"], 319)

    def test_a_missing_file_is_refused_with_a_status_not_a_traceback(self):
        code = tcr.main(["--file", str(self.directory / "absent.ndjson")])
        self.assertEqual(code, 2)

    def test_the_default_file_skips_a_future_dated_leftover(self):
        # This machine once ran with its clock a month ahead, which left a
        # capture_20261211.ndjson behind. It must not be read as the latest
        # session, by name or by modification time.
        stale = self.directory / "capture_20261211.ndjson"
        stale.write_text(json.dumps(record("Hello",
                                           "2026-12-11T10:00:00+05:00")) + "\n",
                         encoding="utf-8")
        fresh = self.directory / "capture_20261013.ndjson"
        fresh.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(stale, (1_800_000_000, 1_800_000_000))   # newer than `fresh`
        os.utime(fresh, (1_700_000_000, 1_700_000_000))
        with mock.patch.object(tcr, "CAPTURE_DIR", self.directory):
            self.assertEqual(tcr.newest_capture(date(2026, 10, 13)), fresh)
            out = self.directory / "picked.json"
            with mock.patch.object(tcr, "today_karachi",
                                   lambda: date(2026, 10, 13)):
                code = tcr.main(["--json", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["file"],
                         fresh.name)

    def test_with_nothing_but_future_dated_files_the_newest_by_time_is_read(self):
        # Refusing to report would hide the situation; the fallback reads the
        # newest file by time and says what it contains. Both mtimes are set
        # explicitly: equal timestamps would let iteration order decide, which
        # is exactly the kind of accident this test exists to exclude.
        older = self.path
        newer = self.directory / "capture_20261211.ndjson"
        newer.write_text(self.path.read_text(encoding="utf-8"), encoding="utf-8")
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_700_000_100, 1_700_000_100))
        with mock.patch.object(tcr, "CAPTURE_DIR", self.directory):
            picked = tcr.newest_capture(date(2026, 1, 1))
        self.assertEqual(picked, newer)

    def test_no_capture_file_at_all_is_a_status_not_a_traceback(self):
        empty = self.directory / "empty"
        empty.mkdir()
        with mock.patch.object(tcr, "CAPTURE_DIR", empty):
            code = tcr.main([])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
