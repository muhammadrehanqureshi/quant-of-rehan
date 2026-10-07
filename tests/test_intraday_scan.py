"""Safety checks for the market-hour KMIALL observation scan."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.intraday_scan import (  # noqa: E402
    aggregate_minute_bars,
    candidate_for_session,
    evaluate_scan,
)


class TestIntradayScan(unittest.TestCase):
    def test_aggregator_uses_only_bars_available_by_scan_time(self):
        pkt = timezone(timedelta(hours=5))
        as_of = datetime(2026, 10, 7, 10, 6, tzinfo=pkt)
        records = [{
            "ts": "2026-10-07T10:05:00+05:00",
            "symbol": "OGDC",
            "bars": [
                {"t": "10:00", "o": 100, "h": 101, "l": 99, "c": 100.5},
                {"t": "10:05", "o": 100.5, "h": 102, "l": 100, "c": 101},
                {"t": "10:07", "o": 101, "h": 103, "l": 101, "c": 102},
            ],
        }, {
            "ts": "2026-10-07T10:05:00+05:00",
            "symbol": "OUTSIDE",
            "bars": [{"t": "10:05", "o": 10, "h": 11, "l": 9, "c": 10}],
        }]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.ndjson"
            path.write_text(
                "\n".join(json.dumps(record) for record in records),
                encoding="utf-8",
            )
            frame = aggregate_minute_bars(path, ["OGDC"], "2026-10-07", as_of)
        self.assertEqual(len(frame), 1)
        row = frame.iloc[0]
        self.assertEqual(row["symbol"], "OGDC")
        self.assertEqual(row["open"], 100)
        self.assertEqual(row["high"], 102)
        self.assertEqual(row["low"], 99)
        self.assertEqual(row["close"], 101)
        self.assertTrue(pd.isna(row["volume"]))

    def test_stale_bars_are_excluded(self):
        pkt = timezone(timedelta(hours=5))
        as_of = datetime(2026, 10, 7, 10, 0, tzinfo=pkt)
        record = {
            "ts": "2026-10-07T09:00:00+05:00",
            "symbol": "OGDC",
            "bars": [{"t": "09:00", "o": 100, "h": 101, "l": 99, "c": 100}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.ndjson"
            path.write_text(json.dumps(record), encoding="utf-8")
            frame = aggregate_minute_bars(path, ["OGDC"], "2026-10-07", as_of)
        self.assertTrue(frame.empty)

    def test_low_coverage_fails_closed(self):
        dates = pd.date_range("2026-09-01", periods=21, freq="D")
        history = pd.DataFrame({"date": dates})
        partial = pd.DataFrame({"symbol": [f"S{i}" for i in range(7)]})
        selected, reason = evaluate_scan(history, partial, 10, "2026-10-07")
        self.assertIsNone(selected)
        self.assertIn("70.0%", reason)

    def test_multiple_candidates_are_not_arbitrarily_ranked(self):
        candidates = [
            SimpleNamespace(signal_date="2026-10-07"),
            SimpleNamespace(signal_date="2026-10-07"),
        ]
        selected, reason = candidate_for_session(candidates, "2026-10-07")
        self.assertIsNone(selected)
        self.assertIn("no arbitrary ranking", reason)

    def test_other_session_candidates_are_ignored(self):
        selected, reason = candidate_for_session(
            [SimpleNamespace(signal_date="2026-10-06")], "2026-10-07")
        self.assertIsNone(selected)
        self.assertEqual(reason, "no candidate passed the existing rule")


if __name__ == "__main__":
    unittest.main()
