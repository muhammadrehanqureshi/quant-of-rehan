"""The feed forensic audit: catalogue, cadence, duplicates and print lag.

Why these tests exist: the capability report cites these numbers, so each
one must be produced from the banked wire rather than assumed. The fixture
below reproduces the exact shapes seen in a real capture on 2026-10-23:

  * repeated snapshots that must count as duplicates, not rows;
  * a print clock that advances only when the venue printed something;
  * EXS-FEED breadth (advancing, declining, unchanged, volume, turnover);
  * MKT-STATS segment totals;
  * a RUCAP circuit-cap frame whose semantics are inferred, never claimed.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import feed_forensic_audit as ffa  # noqa: E402

EXS_RAW = ("EXS-FEED*10/23/2026 10:31:08 AM^KSE100;163303.31;-621.00;"
           "163966.86;42.54688;163238.14;-686.1719;192;237;24;14255840;"
           "1154064466.05;|^$")
STATS_RAW = ("MKT-STATS*REG;OPEN;83339305.00;67223.00;3668393693.07|"
             "FUT;OPEN;16973000.00;6872.00;1206238350.00|")
CAP_RAW = "RUCAP*SZTM*132.52"


def tick(symbol, volume, last, tick_time, bid="9.99", ask="10.01",
         trades=0, market="REG") -> dict:
    return {"scrip": symbol, "market": market, "status": "OPN",
            "bid": bid, "ask": ask, "last": last,
            "volume": str(volume), "trades": str(trades),
            "tick_time": tick_time, "last_volume": "1"}


def record(at, ticks=None, kind="MKT-FEED", raw="") -> dict:
    rec = {"kind": kind, "raw": raw, "ts": at}
    if ticks is not None:
        rec["ticks"] = ticks
    return rec


class AuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "capture_20261023.ndjson"
        self.write([
            record("2026-10-23T09:52:00+05:00", [tick("AAA", 100, "10.00",
                                                      "09:52:00", trades=2)]),
            record("2026-10-23T09:52:30+05:00", [tick("AAA", 100, "10.00",
                                                      "09:52:00", trades=2)]),
            record("2026-10-23T09:53:00+05:00", [tick("AAA", 160, "10.01",
                                                      "09:52:55", trades=5)]),
            record("2026-10-23T09:53:00+05:00", kind="EXS-FEED", raw=EXS_RAW),
            record("2026-10-23T09:53:01+05:00", kind="MKT-STATS", raw=STATS_RAW),
            record("2026-10-23T09:53:02+05:00", kind="RUCAP", raw=CAP_RAW),
        ])

    def write(self, records) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec) + "\n")

    def test_the_catalogue_counts_every_frame_kind(self):
        report = ffa.audit(self.path)
        self.assertEqual(report["frames"]["MKT-FEED"], 3)
        self.assertEqual(report["frames"]["EXS-FEED"], 1)
        self.assertEqual(report["frames"]["MKT-STATS"], 1)
        self.assertEqual(report["frames"]["RUCAP"], 1)
        self.assertEqual(report["tick_rows"], 3)
        self.assertEqual(report["symbols"], 1)
        self.assertEqual(report["universe_coverage"], round(1 / 319, 4))

    def test_echoed_snapshots_count_as_duplicates_not_rows(self):
        report = ffa.audit(self.path)
        self.assertEqual(report["duplicate_consecutive_rows"], 1)
        self.assertAlmostEqual(report["duplicate_share"], 1 / 3, places=4)
        self.assertEqual(report["out_of_order_records"], 0)

    def test_cadence_and_new_print_lag_are_measured_from_the_wire(self):
        report = ffa.audit(self.path)
        self.assertEqual(report["median_snapshot_gap_seconds"], 30.0)
        lag = report["new_print_lag_seconds"]
        self.assertEqual(lag["samples"], 1)
        self.assertEqual(lag["p50"], 5.0)      # 09:53:00 minus 09:52:55

    def test_breadth_stats_and_caps_are_parsed_not_invented(self):
        report = ffa.audit(self.path)
        breadth = report["last_breadth"]
        self.assertEqual(breadth["advancing"], 192)
        self.assertEqual(breadth["declining"], 237)
        self.assertEqual(breadth["unchanged"], 24)
        self.assertEqual(breadth["session_volume"], 14255840)
        stats = report["last_market_stats"]["segments"]
        reg = [row for row in stats if row["segment"] == "REG"][0]
        self.assertEqual(reg["state"], "OPEN")
        self.assertEqual(reg["volume"], 83339305)
        caps = report["circuit_caps"]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0]["symbol"], "SZTM")
        self.assertEqual(caps[0]["price"], 132.52)
        self.assertIn("inferred", caps[0]["basis"])

    def test_out_of_order_records_are_counted_not_reordered(self):
        path = Path(self.dir.name) / "capture_20261024.ndjson"
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(record("2026-10-24T10:00:00+05:00",
                                           [tick("AAA", 100, "10.00",
                                                 "09:59:55")])) + "\n")
            handle.write(json.dumps(record("2026-10-24T09:59:00+05:00",
                                           [tick("BBB", 100, "10.00",
                                                 "09:58:55")])) + "\n")
        self.assertEqual(ffa.audit(path)["out_of_order_records"], 1)

    def test_main_writes_the_json_report(self):
        out = Path(self.dir.name) / "audit.json"
        code = ffa.main(["--file", str(self.path), "--json", str(out)])
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["file"], self.path.name)

    def test_a_missing_file_is_a_status_not_a_traceback(self):
        code = ffa.main(["--file", str(Path(self.dir.name) / "absent.ndjson")])
        self.assertEqual(code, 2)


class FrameParserTest(unittest.TestCase):
    def test_cap_frames_parse_and_unknown_kinds_refuse(self):
        parsed = ffa.parse_cap_frame("RLCAP*BAPL*18.62")
        self.assertEqual(parsed["kind"], "RLCAP")
        self.assertEqual(parsed["symbol"], "BAPL")
        self.assertEqual(parsed["price"], 18.62)
        self.assertIsNone(ffa.parse_cap_frame("RUCAP*BROKEN"))
        self.assertIsNone(ffa.parse_cap_frame("HELLO*"))

    def test_an_exs_frame_without_the_named_index_is_refused(self):
        raw = ("EXS-FEED*10/23/2026 10:31:08 AM^KSE30;48104.31;-209.49;"
               "48313.80;|^$")
        self.assertIsNone(ffa.parse_exs_group(raw, index="KSE100"))


if __name__ == "__main__":
    unittest.main()
