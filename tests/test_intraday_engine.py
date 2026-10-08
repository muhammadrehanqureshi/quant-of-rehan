"""Tests for causal 1m to 5m KMIALL signal generation and forward labels."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI, open_time
from src.research.forward_validation import (
    evaluate_gate, label_candidate, COST_SIDE_BPS, SLIPPAGE_SIDE_BPS,
)
from src.signals.intraday_engine import (
    Bar, aggregate_5m, parse_capture, scan_snapshot, TP_PCT,
)
from scripts.intraday_pipeline import load_kmiall, signal_text


def session_open(day):
    return datetime(day.year, day.month, day.day, *open_time(day), tzinfo=KARACHI)


def make_minute_rows(symbol, op, closes, day):
    start = session_open(day)
    rows = []
    prev = op
    for i, close in enumerate(closes):
        stamp = start + timedelta(minutes=i)
        rows.append(Bar(symbol, stamp, prev, max(prev, close) + 0.01,
                        min(prev, close) - 0.01, close))
        prev = close
    return rows


class TestUniverse(unittest.TestCase):
    def test_universe_is_shariah_compliant_kmiall_only(self):
        symbols = load_kmiall()
        self.assertGreater(len(symbols), 100)
        rows = json.loads((ROOT / "src" / "data" / "universe_kmiall.json").read_text())
        by_symbol = {row["symbol"]: row for row in rows}
        for sym in symbols:
            self.assertIs(by_symbol[sym]["isShariahCompliant"], True)
            self.assertIn("KMIALLSHR", by_symbol[sym]["listedIn"])


class TestChronologicalIntradayEngine(unittest.TestCase):
    def test_5m_aggregation_requires_five_consecutive_closed_minutes(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        rows = [Bar("AAA", start + timedelta(minutes=i), 100+i/10,
                    101+i/10, 99+i/10, 100.5+i/10) for i in range(6)]
        bars = aggregate_5m(rows, start, start + timedelta(minutes=6))
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["timestamp"], start + timedelta(minutes=5))
        self.assertEqual(bars[0]["open"], 100)
        self.assertEqual(bars[0]["close"], 100.9)

    def test_parse_rejects_future_rows_and_non_universe_symbols(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        records = [{
            "ts": (start + timedelta(minutes=14)).isoformat(),
            "symbol": "AAA",
            "bars": [
                {"t": (start + timedelta(minutes=i)).strftime("%H:%M"),
                 "o": 100, "h": 101, "l": 99, "c": 100+i/100}
                for i in range(15)
            ],
        }, {
            "ts": (start + timedelta(minutes=14)).isoformat(),
            "symbol": "OUTSIDE",
            "bars": [{"t": start.strftime("%H:%M"), "o": 1, "h": 2, "l": 0.5, "c": 1}],
        }]
        as_of = start + timedelta(minutes=14)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.ndjson"
            path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
            bars, quality = parse_capture(path, ["AAA"], as_of)
        self.assertIn("AAA", bars)
        self.assertEqual(len(bars["AAA"]), 14)
        self.assertTrue(all(b.timestamp < as_of for b in bars["AAA"]))
        self.assertEqual(quality["symbols_with_bars"], 1)

    def test_stale_capture_is_rejected(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        record = {
            "ts": start.isoformat(), "symbol": "AAA",
            "bars": [{"t": (start + timedelta(minutes=i)).strftime("%H:%M"),
                      "o": 100, "h": 101, "l": 99, "c": 100}
                     for i in range(5)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.ndjson"
            path.write_text(json.dumps(record), encoding="utf-8")
            _bars, quality = parse_capture(
                path, ["AAA"], start + timedelta(minutes=90))
        self.assertEqual(quality["quality"], "degraded")

    def _snapshot(self, a_return, b_return, quality=None, asof_minute=70):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        as_of = start + timedelta(minutes=asof_minute)
        # First 30 one-minute bars define the opening range. A breakout
        # after that range remains at the requested session return.
        a_closes = [100.02] * 65 + [100.0 * (1 + a_return)] * 5
        b_closes = [100.0 + i * (b_return / 69) for i in range(70)]
        a_rows = make_minute_rows("AAA", 100.0, a_closes, day)
        b_rows = make_minute_rows("BBB", 100.0, b_closes, day)
        q = quality or {"quality": "verified", "coverage": 1.0}
        return scan_snapshot({"AAA": a_rows, "BBB": b_rows},
                             ["AAA", "BBB"], as_of, q)

    def test_candidate_is_causal_and_entry_target_exact(self):
        snap = self._snapshot(0.0099, 0.001)
        self.assertEqual(snap["status"], "PAPER_CANDIDATE")
        candidate = snap["candidate"]
        self.assertEqual(candidate["symbol"], "AAA")
        self.assertAlmostEqual(candidate["target"] / candidate["entry_reference"] - 1, TP_PCT)
        self.assertLessEqual(candidate["session_return"], 0.01)

    def test_old_breakout_is_not_replayed_at_a_later_scan(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        as_of = start + timedelta(minutes=70)
        old_breakout = [100.02] * 30 + [100.85] * 40
        steady_peer = [100.01] * 70
        bars = {
            "AAA": make_minute_rows("AAA", 100, old_breakout, day),
            "BBB": make_minute_rows("BBB", 100, steady_peer, day),
        }
        snap = scan_snapshot(bars, ["AAA", "BBB"], as_of,
                             {"quality": "verified"})
        self.assertEqual(snap["status"], "NO_TRADE")

    def test_bad_data_and_hostile_market_fail_closed(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        stale = scan_snapshot({}, ["AAA"], start + timedelta(minutes=90),
                              {"quality": "degraded"})
        self.assertEqual(stale["status"], "NO_TRADE")
        hostile = self._snapshot(0.0002, -0.003)
        self.assertEqual(hostile["status"], "NO_TRADE")

    def test_anti_chasing_rejects_extended_candidate(self):
        snap = self._snapshot(0.012, 0.001)
        self.assertEqual(snap["status"], "NO_TRADE")

    def test_close_candidates_with_small_score_margin_produce_no_trade(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        as_of = start + timedelta(minutes=70)
        closes_a = [100.02] * 65 + [100.85] * 5
        closes_b = [100.01] * 65 + [100.84] * 5
        bars = {
            "AAA": make_minute_rows("AAA", 100, closes_a, day),
            "BBB": make_minute_rows("BBB", 100, closes_b, day),
        }
        for symbol in ("CCC", "DDD", "EEE"):
            bars[symbol] = make_minute_rows(
                symbol, 100, [100.01] * 70, day)
        universe = ["AAA", "BBB", "CCC", "DDD", "EEE"]
        snap = scan_snapshot(bars, universe, as_of,
                             {"quality": "verified"})
        self.assertEqual(snap["status"], "NO_TRADE")
        self.assertIn("too close", snap["reason"])


class TestForwardLabelsAndGate(unittest.TestCase):
    def candidate(self):
        return {
            "symbol": "AAA",
            "timestamp": "2026-10-08T10:00+05:00",
            "entry_reference": 100.0,
            "target": 102.0,
            "stop_reference": 99.0,
        }

    def test_exact_target_first_and_costs(self):
        result = label_candidate(self.candidate(), [{
            "timestamp": "2026-10-08T10:05+05:00",
            "open": 100, "high": 102.2, "low": 99.5, "close": 102,
        }])
        self.assertEqual(result["label"], "TP_FIRST")
        self.assertEqual(result["target"], 102.0)
        self.assertAlmostEqual(result["gross_return"], 0.02)
        self.assertGreater(result["net_return"], 0)
        self.assertEqual(result["cost_side_bps"], COST_SIDE_BPS)
        self.assertEqual(result["slippage_bps_per_side"], SLIPPAGE_SIDE_BPS)

    def test_same_bar_tie_is_stop_first_and_gap_fills_at_open(self):
        result = label_candidate(self.candidate(), [{
            "timestamp": "2026-10-08T10:05+05:00",
            "open": 98.5, "high": 102.2, "low": 98.0, "close": 100,
        }])
        self.assertEqual(result["label"], "SL_AMBIG")
        self.assertAlmostEqual(result["exit_price"], 98.5)
        self.assertLess(result["net_return"], -0.02)

    def test_timeout_exits_at_last_close(self):
        result = label_candidate(self.candidate(), [{
            "timestamp": "2026-10-08T10:05+05:00",
            "open": 100, "high": 100.5, "low": 99.5, "close": 100.4,
        }])
        self.assertEqual(result["label"], "TIMEOUT")
        self.assertEqual(result["exit_price"], 100.4)

    def test_no_future_bar_is_unclosed(self):
        result = label_candidate(self.candidate(), [{
            "timestamp": "2026-10-08T10:00+05:00",
            "open": 100, "high": 101, "low": 99.5, "close": 100,
        }])
        self.assertEqual(result["label"], "UNCLOSED")
        self.assertIsNone(result["net_return"])

    def test_eligibility_requires_locked_positive_chronological_evidence(self):
        too_early = evaluate_gate([{"date": f"2026-01-{i:02d}", "candidate": None}
                                   for i in range(1, 60)])
        self.assertFalse(too_early["eligible"])
        rows = []
        start = datetime(2025, 1, 1)
        for i in range(180):
            win = i % 4 != 0
            net = 0.01 if win else -0.004
            rows.append({
                "date": (start + timedelta(days=i)).date().isoformat(),
                "candidate": {"symbol": f"S{i % 20:02d}"},
                "label": "TP_FIRST" if win else "SL_FIRST",
                "gross_return": 0.02 if win else -0.01,
                "net_return": net,
                "minutes_held": 45,
            })
        gate = evaluate_gate(rows)
        self.assertTrue(gate["eligible"])
        self.assertTrue(gate["window_locked"])
        self.assertEqual(gate["window_sessions"], 180)
        rows[-1]["net_return"] = -0.10
        failed = evaluate_gate(rows)
        self.assertFalse(failed["eligible"])

    def test_all_positive_oos_keeps_undefined_profit_factor_gateable(self):
        rows = []
        start = datetime(2025, 1, 1)
        for i in range(180):
            rows.append({
                "date": (start + timedelta(days=i)).date().isoformat(),
                "candidate": {"symbol": f"S{i % 20:02d}"},
                "label": "TP_FIRST",
                "gross_return": 0.02,
                "net_return": 0.01,
                "minutes_held": 45,
            })
        gate = evaluate_gate(rows)
        self.assertTrue(gate["eligible"])
        self.assertIsNone(gate["metrics"]["oos"]["profit_factor"])

    def test_signal_payload_labels_entry_as_reference_and_has_target(self):
        candidate = {
            "symbol": "AAA", "timestamp": "2026-10-08T10:00+05:00",
            "entry_reference": 100.0, "target": 102.0,
            "rationale": "range breakout and relative strength",
        }
        text = signal_text(candidate, {"median_return": 0.003},
                           {"quality": "verified"})
        self.assertIn("KMIALL LONG SIGNAL", text)
        self.assertIn("Entry reference: 100.0000", text)
        self.assertIn("Target: 102.0000 (+2.00%)", text)
        self.assertIn("not executable", text)
        self.assertNotIn("BUY AAA", text)


if __name__ == "__main__":
    unittest.main()
