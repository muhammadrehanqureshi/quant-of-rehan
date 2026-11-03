"""The desktop terminal's data core, tested without PySide6.

Everything here runs in the standard CI environment: bridge.py imports no
Qt. The laws pinned:

  * the live table takes the newest observation per symbol and refuses a
    quote older than its freshness window (a stale quote shown as live is
    the failure this table exists to avoid);
  * the feed health distinguishes DEAD, STALE and FRESH from the recorder's
    own heartbeat, never from a connected socket;
  * the session gauge follows the one session law;
  * a missing field prints as a dash (None), never as a zero;
  * order flow carries its inferred basis and the registry's footprint
    availability with every row.
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

from src.desktop import bridge  # noqa: E402

NOW = datetime.fromisoformat("2026-10-22T10:00:00+05:00")


def tick(symbol, volume, last, bid, ask, tick_time="09:59:00",
         close="10.00", trades=2, market="REG", high=None, low=None) -> dict:
    row = {"scrip": symbol, "market": market, "status": "OPN",
           "bid": bid, "ask": ask, "last": last, "close": close,
           "volume": str(volume), "trades": str(trades),
           "tick_time": tick_time, "bid_size": "100", "ask_size": "100",
           "avg": "10.00"}
    if high is not None:
        row["high"] = high
    if low is not None:
        row["low"] = low
    return row


def record(at, ticks) -> dict:
    return {"kind": "MKT-FEED", "raw": "", "ts": at, "ticks": ticks}


class BridgeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "capture_20261022.ndjson"

    def write(self, records) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            for rec in records:
                handle.write(json.dumps(rec) + "\n")


class QuoteRowsTest(BridgeTestBase):
    def test_newest_row_per_symbol_and_limit(self):
        self.write([
            record("2026-10-22T09:59:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", "09:58:00"),
                tick("BBB", 500, "20.00", "19.99", "20.01", "09:58:30"),
            ]),
            record("2026-10-22T09:59:40+05:00", [
                tick("AAA", 160, "10.05", "10.04", "10.06", "09:59:30"),
            ]),
        ])
        rows = bridge.quote_rows(self.path, now=NOW, max_age_seconds=3600)
        self.assertEqual([row.symbol for row in rows], ["BBB", "AAA"])
        aaa = [row for row in rows if row.symbol == "AAA"][0]
        self.assertEqual(aaa.volume, 160)
        self.assertAlmostEqual(aaa.last, 10.05)
        self.assertAlmostEqual(aaa.spread, 0.02)
        self.assertAlmostEqual(aaa.change_pct, 0.5)
        self.assertEqual(len(bridge.quote_rows(self.path, now=NOW, limit=1,
                                               max_age_seconds=3600)), 1)

    def test_a_stale_tail_yields_no_rows_instead_of_old_ones(self):
        self.write([
            record("2026-10-22T09:00:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01"),
            ]),
        ])
        self.assertEqual(bridge.quote_rows(self.path, now=NOW,
                                           max_age_seconds=60), [])

    def test_missing_capture_is_an_empty_table(self):
        self.assertEqual(bridge.quote_rows(Path(self.dir.name) / "absent.ndjson",
                                           now=NOW), [])


class QuoteUpdateTest(unittest.TestCase):
    def test_spread_and_age_from_a_live_quote(self):
        row = bridge.quote_from_update({
            "symbol": "OGDC", "price": 101.5, "bid": 101.4, "ask": 101.6,
            "volume": 12345, "change_pct": 1.5, "status": "OPEN",
            "observed_at": "2026-10-22T09:59:50+05:00",
        }, now=NOW)
        self.assertEqual(row.symbol, "OGDC")
        self.assertAlmostEqual(row.spread, 0.2)
        self.assertEqual(row.age_seconds, 10.0)

    def test_an_absent_ask_leaves_spread_none(self):
        row = bridge.quote_from_update({
            "symbol": "OGDC", "price": 101.5, "bid": 101.4, "ask": None,
            "volume": None, "status": "OPEN",
        }, now=NOW)
        self.assertIsNone(row.spread)
        self.assertIsNone(row.volume)


class SessionTest(unittest.TestCase):
    def test_the_gauge_follows_the_band(self):
        moment = datetime.fromisoformat("2026-10-22T10:00:00+05:00")
        fraction, label = bridge.session_progress(moment)
        self.assertGreater(fraction, 0.0)
        self.assertLess(fraction, 0.2)
        self.assertEqual(label, "09:32-15:30")

    def test_outside_the_band_the_gauge_is_empty(self):
        moment = datetime.fromisoformat("2026-10-22T08:00:00+05:00")
        fraction, label = bridge.session_progress(moment)
        self.assertEqual(fraction, 0.0)
        # The label is the session law's own phase name, never a word of
        # the terminal's invention.
        self.assertEqual(label, bridge.session_status(moment)["phase"])
        self.assertFalse(bridge.session_status(moment)["market_open"])

    def test_the_status_is_the_one_law(self):
        state = bridge.session_status(NOW)
        self.assertEqual(state["phase"], "OPEN")
        self.assertTrue(state["market_open"])
        self.assertEqual(state["live_band"], {"open": "09:32", "close": "15:30"})


class FeedHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "status.json"

    def test_missing_heartbeat_is_dead(self):
        self.assertEqual(bridge.feed_health(self.path, NOW)["state"], "DEAD")

    def test_a_fresh_heartbeat_is_fresh(self):
        self.path.write_text(json.dumps({
            "running": True, "updated_at": "2026-10-22T09:59:50+05:00",
            "counters": {"messages": 10, "ticks": 90}, "universe_size": 319,
        }), encoding="utf-8")
        health = bridge.feed_health(self.path, NOW)
        self.assertEqual(health["state"], "FRESH")
        self.assertEqual(health["counters"]["ticks"], 90)

    def test_a_stopped_recorder_is_dead_even_with_a_recent_file(self):
        self.path.write_text(json.dumps({
            "running": False, "updated_at": "2026-10-22T09:59:50+05:00",
        }), encoding="utf-8")
        self.assertEqual(bridge.feed_health(self.path, NOW)["state"], "DEAD")

    def test_a_quiet_heartbeat_is_stale(self):
        self.path.write_text(json.dumps({
            "running": True, "updated_at": "2026-10-22T09:57:00+05:00",
        }), encoding="utf-8")
        self.assertEqual(bridge.feed_health(self.path, NOW)["state"], "STALE")


class SettingsTest(unittest.TestCase):
    def test_defaults_then_roundtrip(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            settings = bridge.load_settings(directory)
            self.assertTrue(settings["auto_start_feed"])
            settings["max_symbols"] = 120
            bridge.save_settings(settings, directory)
            again = bridge.load_settings(directory)
            self.assertEqual(again["max_symbols"], 120)

    def test_an_unreadable_file_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            bridge.settings_path(directory).write_text("{broken", encoding="utf-8")
            self.assertEqual(bridge.load_settings(directory)["max_symbols"], 80)


class DecisionTest(unittest.TestCase):
    def test_the_record_is_read_not_invented(self):
        from src.signals.trade_state import SessionState

        state = SessionState(day="2026-10-22")
        state.state = "NO_TRADE_LOCKED"
        state.last_reason = "nothing passed the gate"
        record = bridge.trade_decision(state=state)
        self.assertEqual(record["state"], "NO_TRADE_LOCKED")
        self.assertIsNone(record["symbol"])
        self.assertIn("gate", record["last_reason"])


class OrderFlowRowsTest(BridgeTestBase):
    def test_rows_carry_their_inferred_basis_and_registry_status(self):
        self.write([
            record("2026-10-22T09:59:00+05:00", [
                tick("AAA", 100, "10.00", "9.99", "10.01", "09:58:55"),
            ]),
            record("2026-10-22T09:59:40+05:00", [
                tick("AAA", 160, "10.01", "9.99", "10.01", "09:59:30"),
            ]),
        ])
        rows = bridge.order_flow_rows(self.path, symbols=["AAA"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["symbol"], "AAA")
        self.assertEqual(row["buy_volume_inferred"], 60)
        self.assertIn("inferred", row["basis"]["sides"])
        self.assertEqual(row["basis"]["footprint_registry"], "UNAVAILABLE")


class LeaderFlowTest(BridgeTestBase):
    """The home page's B/S split: the card's labelled range estimate."""

    def test_leaders_carry_buy_sell_volume_and_basis(self):
        self.write([
            record("2026-10-22T09:59:40+05:00", [
                tick("AAA", 1_000_000, "20.00", "19.99", "20.01",
                     high="21.00", low="19.00"),
                tick("BBB", 400_000, "52.00", "51.99", "52.01",
                     high="52.00", low="51.00"),
            ]),
        ])
        rows, note = bridge.leader_flow(self.path, now=NOW, limit=2)
        self.assertEqual(len(rows), 2)
        top = rows[0]
        self.assertEqual(top["symbol"], "AAA")
        # close sits at the middle of 19..21, so the split is even
        self.assertEqual(top["buy_volume"], 500_000)
        self.assertEqual(top["sell_volume"], 500_000)
        self.assertEqual(
            top["buy_volume"] + top["sell_volume"], top["volume"])
        bbb = rows[1]
        # close at the top of 51..52 attributes the session to buying
        self.assertEqual(bbb["buy_volume"], 400_000)
        self.assertEqual(bbb["sell_volume"], 0)
        self.assertIn("estimate", note)

    def test_missing_tape_reports_it_instead_of_zeroes(self):
        rows, note = bridge.leader_flow(
            Path(self.dir.name) / "capture_19990101.ndjson", now=NOW)
        self.assertEqual(rows, [])
        self.assertIn("no banked tape", note)


class SparkSeriesTest(BridgeTestBase):
    def test_series_are_chronological_and_bounded(self):
        self.write([
            record("2026-10-22T09:58:00+05:00", [
                tick("AAA", 100_000, "10.00", "9.99", "10.01"),
            ]),
            {"kind": "EXS-FEED", "raw": ("EXS-FEED*11/03/2026 10:01:00 AM^"
                                         "KSE100;168000.0;1000.0"), "ts":
             "2026-10-22T09:58:30+05:00"},
            record("2026-10-22T09:59:00+05:00", [
                tick("AAA", 150_000, "10.10", "10.09", "10.11"),
                tick("BBB", 300_000, "52.50", "52.49", "52.51"),
            ]),
            {"kind": "EXS-FEED", "raw": ("EXS-FEED*11/03/2026 10:02:00 AM^"
                                         "KSE100;168100.0;1100.0"), "ts":
             "2026-10-22T09:59:30+05:00"},
            record("2026-10-22T09:59:50+05:00", [
                tick("AAA", 200_000, "10.20", "10.19", "10.21"),
            ]),
        ])
        series, index_values, note = bridge.spark_series(
            ["AAA", "BBB"], self.path, now=NOW, minutes=60)
        self.assertEqual(series["AAA"], [10.00, 10.10, 10.20])
        self.assertEqual(len(series["BBB"]), 1)
        self.assertEqual(len(index_values), 2)
        self.assertGreater(series["AAA"][-1], series["AAA"][0])
        self.assertIn("minutes", note)

    def test_missing_tape_yields_empty_series(self):
        series, index_values, note = bridge.spark_series(
            ["AAA"], Path(self.dir.name) / "capture_19990101.ndjson",
            now=NOW)
        self.assertEqual(series, {})
        self.assertEqual(index_values, [])


if __name__ == "__main__":
    unittest.main()
