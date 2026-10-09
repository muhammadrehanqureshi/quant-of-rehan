"""Tests for causal 1m to 5m KMIALL signal generation and forward labels."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
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
    Bar, CANDIDATE_RULES, aggregate_5m, parse_capture, scan_snapshot, TP_PCT,
)
from scripts.intraday_pipeline import (
    annotate_source_quality, load_kmiall, missing_scan_slots, signal_text,
    universe_fingerprint,
)


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


class TestUniverseFingerprint(unittest.TestCase):
    def test_fingerprint_is_order_independent_and_changes_with_membership(self):
        self.assertEqual(universe_fingerprint(["AAA", "BBB"]),
                         universe_fingerprint(["BBB", "AAA"]))
        self.assertNotEqual(universe_fingerprint(["AAA", "BBB"]),
                            universe_fingerprint(["AAA", "CCC"]))


class TestSourceApproval(unittest.TestCase):
    def test_production_data_is_not_ready_without_rights_and_latency_confirmation(self):
        with patch.dict("os.environ", {}, clear=True):
            result = annotate_source_quality({"quality": "verified"})
        self.assertFalse(result["production_data_ready"])
        self.assertEqual(result["source_latency"], "unverified")
        self.assertEqual(result["data_rights"], "unverified")
        self.assertEqual(result["universe_membership"], "unverified-currentness")

    def test_production_data_requires_both_confirmations(self):
        with patch.dict("os.environ", {
                "KMIALL_DATA_RIGHTS_CONFIRMED": "true",
                "KMIALL_DATA_LATENCY_CONFIRMED": "true",
                "KMIALL_UNIVERSE_CONFIRMED": "true",
        }, clear=True):
            result = annotate_source_quality({"quality": "verified"})
        self.assertTrue(result["production_data_ready"])


class TestPipelineCaptureCompleteness(unittest.TestCase):
    @staticmethod
    def _verified(slot):
        return {"slot": slot, "snapshot": {
            "data_quality": {"quality": "verified"},
        }}

    def test_missing_weekday_scan_is_unverifiable(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        missing = missing_scan_slots(day, [
            self._verified("10:45"), self._verified("14:45"),
        ])
        self.assertEqual(missing, ["12:45"])

    def test_friday_midday_break_is_not_a_required_scan(self):
        day = datetime(2026, 10, 9, tzinfo=KARACHI).date()
        missing = missing_scan_slots(day, [
            self._verified("10:45"), self._verified("14:45"),
        ])
        self.assertEqual(missing, [])

    def test_degraded_scan_does_not_count_as_a_complete_session(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        observations = [self._verified(slot) for slot in ("10:45", "12:45")]
        observations.append({"slot": "14:45", "snapshot": {
            "data_quality": {"quality": "degraded"},
        }})
        self.assertEqual(missing_scan_slots(day, observations), ["14:45"])


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

    def test_candidate_is_rejected_when_latest_complete_bar_is_stale(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        closes = [100.02] * 65 + [100.85] * 5
        bars = {"AAA": make_minute_rows("AAA", 100, closes, day),
                "BBB": make_minute_rows("BBB", 100, [100.01] * 70, day)}
        snap = scan_snapshot(bars, ["AAA", "BBB"], start + timedelta(minutes=80),
                             {"quality": "verified"})
        self.assertEqual(snap["status"], "NO_TRADE")
        self.assertIsNone(snap["candidate"])

    def test_60_minute_range_rule_waits_for_its_full_opening_range(self):
        day = datetime(2026, 10, 8, tzinfo=KARACHI).date()
        start = session_open(day)
        bars = {"AAA": make_minute_rows("AAA", 100, [100.02] * 64, day),
                "BBB": make_minute_rows("BBB", 100, [100.01] * 64, day)}
        snap = scan_snapshot(bars, ["AAA", "BBB"], start + timedelta(minutes=64),
                             {"quality": "verified"},
                             rule_version="opening_range_60m_rs_v1")
        self.assertEqual(snap["status"], "NO_TRADE")
        self.assertEqual(snap["reason"], "market observation period not complete")

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
                symbol, 100, [100.15] * 70, day)
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

    def _synthetic_rows(self, oos_win=True):
        rows = []
        start = datetime(2025, 1, 1)
        for i in range(180):
            outcomes = {}
            for rule in CANDIDATE_RULES:
                win = oos_win or i < 120 or i % 4 != 0
                net = 0.01 if win else -0.02
                outcomes[rule] = {
                    "candidate": {"symbol": f"S{i % 20:02d}"},
                    "label": "TP_FIRST" if win else "SL_FIRST",
                    "gross_return": 0.02 if win else -0.01,
                    "net_return": net,
                    "minutes_held": 45,
                }
            rows.append({
                "date": (start + timedelta(days=i)).date().isoformat(),
                "data_quality": {"quality": "verified", "production_data_ready": True},
                "storage_status": "available",
                "outcomes_by_rule": outcomes,
            })
        return rows

    def test_candidate_library_passes_only_after_locked_chronological_evidence(self):
        gate = evaluate_gate(self._synthetic_rows())
        self.assertTrue(gate["eligible"])
        self.assertTrue(gate["window_locked"])
        self.assertEqual(gate["window_sessions"], 180)
        self.assertIn(gate["selected_rule_version"], CANDIDATE_RULES)
        self.assertGreater(gate["metrics"]["oos"]["net_expectancy_ci_lower"], 0)
        self.assertIsNone(gate["metrics"]["oos"]["profit_factor"])

    def test_positive_statistics_without_source_approval_remain_paper_only(self):
        rows = self._synthetic_rows()
        for row in rows:
            row["data_quality"]["production_data_ready"] = False
        gate = evaluate_gate(rows)
        self.assertEqual(gate["status"], "PAPER_VALIDATED")
        self.assertFalse(gate["eligible"])
        self.assertFalse(gate["live_signal_enabled"])
        self.assertIn("rights and latency", gate["previous_cycle"]["reason"])

    def test_failed_locked_oos_does_not_reselect_from_oos(self):
        gate = evaluate_gate(self._synthetic_rows(oos_win=False))
        self.assertFalse(gate["eligible"])
        self.assertFalse(gate["live_signal_enabled"])
        self.assertIn(gate["previous_cycle"]["status"], {"RESEARCH_FAILED", "PAPER_VALIDATED"})

    def test_production_monitoring_automatically_demotes_after_health_failure(self):
        rows = self._synthetic_rows()
        start = datetime(2025, 7, 1)
        for i in range(20):
            for outcome in rows[0]["outcomes_by_rule"].values():
                outcome["net_return"] = -0.02
                outcome["gross_return"] = -0.01
                outcome["label"] = "SL_FIRST"
            row = {
                "date": (start + timedelta(days=i)).date().isoformat(),
                "data_quality": {"quality": "verified", "production_data_ready": True},
                "storage_status": "available",
                "outcomes_by_rule": {
                    rule: dict(value) for rule, value in rows[0]["outcomes_by_rule"].items()
                },
            }
            rows.append(row)
        gate = evaluate_gate(rows)
        self.assertEqual(gate["status"], "PRODUCTION_DEGRADED")
        self.assertFalse(gate["eligible"])
        self.assertFalse(gate["live_signal_enabled"])

    def test_unverifiable_days_do_not_consume_research_sessions(self):
        rows = self._synthetic_rows()[:119]
        rows.append({
            "date": "2026-01-01", "data_quality": {"quality": "degraded"},
            "storage_status": "available", "outcomes_by_rule": {},
        })
        gate = evaluate_gate(rows)
        self.assertFalse(gate["eligible"])
        self.assertEqual(gate["sessions_collected"], 119)

    def test_signal_payload_is_explicitly_paper_and_has_exact_target(self):
        candidate = {
            "symbol": "AAA", "timestamp": "2026-10-08T10:00+05:00",
            "entry_reference": 100.0, "target": 102.0,
            "rationale": "range breakout and relative strength",
        }
        text = signal_text(candidate, {"median_return": 0.003},
                           {"quality": "verified"})
        self.assertIn("PAPER SIGNAL | KMIALL LONG ONLY", text)
        self.assertIn("PAPER CANDIDATE: AAA", text)
        self.assertIn("Entry reference: 100.0000", text)
        self.assertIn("Target: 102.0000 (+2.00%)", text)
        self.assertIn("not executable", text)
        self.assertNotIn("PRODUCTION SIGNAL", text)
        self.assertNotIn("BUY AAA", text)


if __name__ == "__main__":
    unittest.main()
