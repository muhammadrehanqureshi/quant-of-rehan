"""The order-flow layer: only fields the snapshot wire carries, labelled.

These tests pin the laws the owner's audit depends on:

  * a feature is computed only from fields the wire actually sends, and an
    absent input yields None, never a zero or an invented number;
  * consecutive identical snapshots are one observation (the feed echoes
    unchanged symbols on most frames), so nothing is double counted;
  * a window's value and VWAP come from the venue's own average price
    identity (total x average differences), not from estimated prices;
  * the buy/sell side is INFERRED (print at the ask or bid, then the tick
    rule) and the module says so; the wire has no aggressor flag;
  * OBI, spread, replenishment and absorption refuse to answer when their
    quote fields are missing, and the latter two are labelled cadence
    proxies rather than per-order events.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import order_flow  # noqa: E402

NOW = "2026-10-23T09:52:00+05:00"


def tick(symbol: str, volume, last, bid, ask, bid_size=None, ask_size=None,
         avg=None, trades=0, tick_time="09:52:00", last_volume=0,
         status="OPN", market="REG") -> dict:
    """A modern snapshot row: named fields, exactly as the wire sends them."""
    row = {
        "scrip": symbol, "market": market, "status": status,
        "bid": bid, "ask": ask, "last": last,
        "volume": str(volume), "trades": str(trades),
        "tick_time": tick_time, "last_volume": str(last_volume),
    }
    if bid_size is not None:
        row["bid_size"] = str(bid_size)
    if ask_size is not None:
        row["ask_size"] = str(ask_size)
    if avg is not None:
        row["avg"] = avg
    return row


def record(at: str, ticks: list[dict], kind: str = "MKT-FEED") -> dict:
    return {"kind": kind, "raw": "", "ts": at, "ticks": ticks}


class FlowTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "capture_20261023.ndjson"

    def write(self, records: list[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec) + "\n")


class IncrementTest(FlowTestBase):
    def test_buy_side_window_value_spread_and_obi(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01",
                     bid_size=100, ask_size=300, avg="10.00", trades=2,
                     tick_time="09:52:00"),
            ]),
            record("2026-10-23T09:52:30+05:00", [
                tick("AAA", 160, "10.01", "9.99", "10.01",
                     bid_size=120, ask_size=240, avg="10.005", trades=5,
                     tick_time="09:52:05"),
            ]),
        ])
        flow = order_flow.symbol_flow(self.path)["AAA"]
        row = flow.as_dict()
        self.assertEqual(row["snapshots"], 2)
        self.assertEqual(row["windows"], 1)
        self.assertEqual(row["volume_delta"], 60)
        self.assertEqual(row["buy_volume_inferred"], 60)
        self.assertEqual(row["sell_volume_inferred"], 0)
        self.assertEqual(row["cvd_inferred"], 60)
        self.assertEqual(row["trades_delta"], 3)
        self.assertAlmostEqual(row["traded_value"], 600.8, places=2)
        self.assertAlmostEqual(row["window_vwap_median"], 10.0133, places=4)
        self.assertAlmostEqual(row["session_vwap"], 10.005, places=4)
        self.assertAlmostEqual(row["spread"], 0.02, places=4)
        self.assertAlmostEqual(row["spread_bps"], 20.0, places=1)
        self.assertAlmostEqual(row["obi_top1"], -0.3333, places=4)
        self.assertAlmostEqual(row["feed_print_lag_seconds"], 25.0, places=1)

    def test_identical_snapshots_are_one_observation(self):
        same = tick("AAA", 100, "10.00", "9.99", "10.01", bid_size=10,
                    ask_size=10, avg="10.00")
        self.write([
            record("2026-10-23T09:52:00+05:00", [same]),
            record("2026-10-23T09:52:30+05:00", [dict(same)]),
            record("2026-10-23T09:53:00+05:00", [dict(same)]),
        ])
        flow = order_flow.symbol_flow(self.path)["AAA"]
        self.assertEqual(flow.snapshots, 1)
        self.assertEqual(flow.windows, 0)
        self.assertIsNone(flow.as_dict()["cvd_inferred"])

    def test_a_print_off_both_quotes_stays_unclassified(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", bid_size=10,
                     ask_size=10, avg="10.00"),
            ]),
            record("2026-10-23T09:52:30+05:00", [
                tick("AAA", 160, "10.00", "9.99", "10.01", bid_size=10,
                     ask_size=10, avg="10.00", tick_time="09:52:20"),
            ]),
        ])
        row = order_flow.symbol_flow(self.path)["AAA"].as_dict()
        self.assertEqual(row["volume_delta"], 60)
        self.assertEqual(row["unclassified_volume"], 60)
        self.assertIsNone(row["buy_volume_inferred"])
        self.assertIsNone(row["cvd_inferred"])

    def test_a_window_longer_than_the_capture_bound_is_refused(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", bid_size=10,
                     ask_size=10, avg="10.00"),
            ]),
            record("2026-10-23T10:05:00+05:00", [
                tick("AAA", 160, "10.01", "9.99", "10.01", bid_size=10,
                     ask_size=10, avg="10.00", tick_time="10:04:50"),
            ]),
        ])
        flow = order_flow.symbol_flow(self.path)["AAA"]
        self.assertEqual(flow.gap_windows, 1)
        self.assertEqual(flow.buy_volume, 0)
        self.assertEqual(flow.unclassified_volume, 60)
        self.assertTrue(any("minutes" in note for note in flow.notes))

    def test_a_quiet_symbol_reports_no_flow_instead_of_zeros(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("BBB", 0, "10.00", "9.99", "10.01", bid_size=0,
                     ask_size=0, avg="10.00"),
            ]),
        ])
        row = order_flow.symbol_flow(self.path)["BBB"].as_dict()
        self.assertEqual(row["snapshots"], 1)
        self.assertIsNone(row["cvd_inferred"])
        self.assertIsNone(row["buy_volume_inferred"])
        self.assertIsNone(row["traded_value"])
        self.assertIsNone(row["obi_top1"])       # both sizes zero: no answer
        self.assertAlmostEqual(row["session_vwap"], 10.0, places=4)

    def test_replenishment_and_absorption_are_counted_at_quote_evidence(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01",
                     bid_size=100, ask_size=300, avg="10.00"),
            ]),
            record("2026-10-23T09:53:00+05:00", [
                tick("AAA", 160, "9.99", "9.99", "10.01",
                     bid_size=150, ask_size=300, avg="10.00",
                     tick_time="09:52:05"),
            ]),
            record("2026-10-23T09:54:00+05:00", [
                tick("AAA", 220, "10.01", "9.99", "10.01",
                     bid_size=150, ask_size=100, avg="10.00",
                     tick_time="09:52:10"),
            ]),
        ])
        row = order_flow.symbol_flow(self.path)["AAA"].as_dict()
        self.assertEqual(row["bid_replenishment_rate"], 1.0)
        self.assertEqual(row["ask_absorption_rate"], 1.0)


class CapabilityTest(unittest.TestCase):
    def test_the_wire_capability_is_stated_not_implied(self):
        self.assertEqual(order_flow.CAPABILITY["level_1"]["status"],
                         "VERIFIED AVAILABLE")
        self.assertEqual(order_flow.CAPABILITY["level_2_mbp"]["status"],
                         "NOT AVAILABLE")
        self.assertEqual(order_flow.CAPABILITY["level_2_mbo"]["status"],
                         "NOT AVAILABLE")
        self.assertEqual(order_flow.CAPABILITY["time_and_sales"]["status"],
                         "PARTIALLY AVAILABLE")
        self.assertEqual(order_flow.CAPABILITY["aggressor_side"]["status"],
                         "NOT AVAILABLE")
        self.assertEqual(order_flow.CAPABILITY["sequence_numbers"]["status"],
                         "NOT AVAILABLE")

    def test_impossible_features_are_named_impossible(self):
        for feature in ("depth_within_band", "order_cancellations",
                        "price_impact_by_level"):
            self.assertEqual(order_flow.FEATURE_STATUS[feature],
                             "NOT AVAILABLE")
        self.assertEqual(order_flow.FEATURE_STATUS["cvd_inferred"],
                         "INFERRED_LIMITED")


class CliTest(FlowTestBase):
    def test_main_writes_the_report_and_returns_zero(self):
        self.write([
            record("2026-10-23T09:52:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", bid_size=10,
                     ask_size=20, avg="10.00"),
            ]),
            record("2026-10-23T09:52:30+05:00", [
                tick("AAA", 160, "10.01", "9.99", "10.01", bid_size=10,
                     ask_size=20, avg="10.00", tick_time="09:52:25"),
            ]),
        ])
        out = Path(self.dir.name) / "order_flow.json"
        code = order_flow.main(["--file", str(self.path), "--json", str(out)])
        self.assertEqual(code, 0)
        written = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(written["file"], self.path.name)
        self.assertEqual(written["summary"]["symbols"], 1)
        self.assertEqual(written["symbols"][0]["symbol"], "AAA")

    def test_a_missing_capture_is_a_status_not_a_traceback(self):
        code = order_flow.main(["--file", str(Path(self.dir.name) / "absent.ndjson")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
