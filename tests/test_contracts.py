"""The typed contract boundary: invariants, adapters, faults, fallback mode.

The fallback test is the important one: pydantic is not in requirements.txt,
so the models must validate the same way when it is absent. It is exercised in
a subprocess with pydantic blocked at import time.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI  # noqa: E402
from src.signals import contracts as C  # noqa: E402

AT = datetime(2026, 10, 9, 10, 0, tzinfo=KARACHI)
_UTC = timezone.utc


def bar(**overrides) -> C.Bar:
    payload = dict(symbol="OGDC", timestamp=AT, open=100.0, high=101.0,
                   low=99.0, close=100.5, volume=5000.0)
    payload.update(overrides)
    return C.Bar(**payload)


def quality(**overrides) -> C.DataQuality:
    payload = dict(status=C.Quality.OK, reason="coverage, freshness, structure "
                                               "and volume present",
                   coverage=1.0, fresh_coverage=1.0, symbols_expected=319,
                   symbols_with_bars=319, volume_available=True)
    payload.update(overrides)
    return C.DataQuality(**payload)


class BarInvariantTest(unittest.TestCase):
    def test_a_valid_bar_is_accepted(self):
        self.assertEqual(bar().symbol, "OGDC")
        # high 101.0, low 99.0 over a 100.5 close
        self.assertAlmostEqual(bar().range_pct, 2.0 / 100.5, places=6)

    def test_naive_timestamp_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            bar(timestamp=datetime(2026, 10, 9, 10, 0))

    def test_impossible_high_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            bar(high=99.5)

    def test_impossible_low_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            bar(low=100.6)

    def test_non_positive_price_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            bar(close=0.0)

    def test_negative_volume_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            bar(volume=-1.0)

    def test_a_flat_bar_is_recognised(self):
        flat = bar(open=100.0, high=100.0, low=100.0, close=100.0, volume=0.0)
        self.assertTrue(flat.is_flat)

    def test_staleness_is_measured_against_the_scan_instant(self):
        old = bar(timestamp=AT - timedelta(minutes=9))
        self.assertTrue(old.is_stale(AT, minutes=5))
        self.assertFalse(bar().is_stale(AT, minutes=5))


class ModelInvariantTest(unittest.TestCase):
    def test_coverage_above_one_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            quality(coverage=1.5)

    def test_more_bars_than_expected_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            quality(symbols_with_bars=400)

    def test_quality_reports_blocked(self):
        blocked = quality(status=C.Quality.DATA_BLOCKED, reason="stale data")
        self.assertTrue(blocked.is_blocked)
        self.assertFalse(blocked.is_usable)

    def test_score_outside_range_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            C.Candidate(symbol="X", score=101.0)

    def test_probability_outside_range_is_refused(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            C.Candidate(symbol="X", score=60.0, ai_probability=1.4)

    def test_a_trade_outcome_must_carry_its_candidate(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            C.ScanOutcome(as_of=AT, slot="10:00", verdict=C.Verdict.TRADE,
                          reason="took it")

    def test_a_no_trade_outcome_cannot_carry_an_entered_candidate(self):
        with self.assertRaises((ValueError, C.ValidationError)):
            C.ScanOutcome(as_of=AT, slot="10:00", verdict=C.Verdict.NO_TRADE,
                          reason="nothing qualified",
                          candidate=C.Candidate(symbol="X", score=60.0))

    def test_a_no_trade_is_a_market_decision_and_a_block_is_not(self):
        no_trade = C.ScanOutcome(as_of=AT, slot="10:00",
                                 verdict=C.Verdict.NO_TRADE, reason="flat")
        blocked = C.ScanOutcome(as_of=AT, slot="10:00",
                                verdict=C.Verdict.DATA_BLOCKED, reason="no bars")
        self.assertTrue(no_trade.is_market_decision)
        self.assertFalse(blocked.is_market_decision)


class FaultMappingTest(unittest.TestCase):
    def mapping(self, reason: str, **overrides):
        return C.fault_from_quality(
            quality(status=C.Quality.DATA_BLOCKED, reason=reason, **overrides))

    def test_clean_quality_has_no_fault(self):
        self.assertIsNone(C.fault_from_quality(quality()))

    def test_holiday_maps_to_market_closed(self):
        fault = self.mapping("2026-10-10 is not a PSX trading day")
        self.assertIsInstance(fault, C.MarketClosed)
        self.assertFalse(fault.retryable)

    def test_empty_capture_maps_to_source_unavailable(self):
        fault = self.mapping("KMIALL coverage 0/319 (0.0%). The intraday source "
                             "returned no usable current-session bars.")
        self.assertIsInstance(fault, C.SourceUnavailable)
        self.assertTrue(fault.retryable)

    def test_coverage_floor_maps_to_insufficient_coverage(self):
        fault = self.mapping("KMIALL coverage 100/319 (31.3%) is below the 80% "
                             "floor. Data source incomplete.")
        self.assertIsInstance(fault, C.InsufficientCoverage)

    def test_stale_maps_to_stale_feed(self):
        fault = self.mapping("newest bar is 12.0 minutes old, above the 5 "
                             "minute freshness limit")
        self.assertIsInstance(fault, C.StaleFeed)

    def test_missing_volume_maps_to_volume_unavailable(self):
        fault = self.mapping("the source carries no volume, and this strategy "
                             "requires volume expansion")
        self.assertIsInstance(fault, C.VolumeUnavailable)
        self.assertFalse(fault.retryable)

    def test_malformed_share_maps_to_source_unavailable(self):
        fault = self.mapping("200/500 captured bar rows were malformed, "
                             "impossible or contradictory; refusing to scan them")
        self.assertIsInstance(fault, C.SourceUnavailable)

    def test_a_warming_up_capture_is_not_a_fault_at_all(self):
        """A countdown must not enter a retry policy or a fault count."""
        report = quality(
            status=C.Quality.DATA_BLOCKED,
            reason=("bar history: only 0/301 captured symbols (0.0%) hold the "
                    "20 bars the strategy needs, below the 80% floor; the bar "
                    "source has been alive 8 of the 20 minutes this needs, so "
                    "the scan is WARMING UP and resumes on its own in about "
                    "12 minute(s)"),
            warming_up=True, warmup_minutes_remaining=12.0,
            rankable_symbols=0, leader_symbols=20, leaders_fresh=0,
            coverage=0.94, fresh_coverage=0.94)

        self.assertIsNone(C.fault_from_quality(report))
        outcome = C.ScanOutcome(as_of=AT, slot="10:04",
                                verdict=C.Verdict.DATA_BLOCKED,
                                reason=report.reason, quality=report)
        self.assertIsNone(outcome.fault(),
                          "a warming-up block was reported as a typed fault")
        self.assertFalse(outcome.is_market_decision)
        self.assertEqual(outcome.quality.warmup_minutes_remaining, 12.0)
        self.assertTrue(outcome.quality.as_dict()["warming_up"])

    def test_the_same_reason_without_a_young_capture_is_a_fault(self):
        """The block still matters when the source is not simply filling."""
        fault = self.mapping("bar history: only 12/301 captured symbols "
                             "(4.0%) hold the 20 bars the strategy needs, "
                             "below the 80% floor, so a ranking built now "
                             "would say nothing about the market")
        self.assertIsInstance(fault, C.InsufficientCoverage)

    def test_the_rankable_population_is_carried_by_the_contract(self):
        report = quality(rankable_symbols=245, leader_symbols=20,
                         leaders_fresh=19)
        payload = report.as_dict()
        self.assertEqual(payload["rankable_symbols"], 245)
        self.assertEqual(payload["leaders_fresh"], 19)
        self.assertFalse(payload["warming_up"])

    def test_fault_carries_context_and_serialises(self):
        fault = self.mapping("KMIALL coverage 0/319 (0.0%). The intraday source "
                             "returned no usable current-session bars.")
        payload = fault.as_dict()
        self.assertEqual(payload["fault"], "SourceUnavailable")
        self.assertTrue(payload["retryable"])
        self.assertEqual(payload["symbols_expected"], 319)
        json.dumps(payload)  # must be serialisable for logs


class AdapterTest(unittest.TestCase):
    def test_candidate_from_a_real_ranking_row(self):
        row = {
            "symbol": "OGDC", "score": 69.87, "momentum": "STRONG",
            "acceleration_label": "STRONG", "volume_label": "STRONG",
            "components": {"momentum": 0.79}, "returns": {"fast_5m": 0.015},
            "volume": {"relative": 2.0, "volume_source": "captured bar volume"},
            "price": {"last": 103.9}, "ai_probability": 0.31,
            "ai_percentile": 0.82, "ai_active": True,
            "last_bar": AT.isoformat(), "bars": 45,
        }
        candidate = C.candidate_from_row(row)
        self.assertEqual(candidate.symbol, "OGDC")
        self.assertAlmostEqual(candidate.entry_price, 103.9)
        self.assertAlmostEqual(candidate.ai_percentile, 0.82)
        self.assertEqual(candidate.volume["volume_source"],
                         "captured bar volume")

    def test_a_non_mapping_row_is_an_aborted_scan(self):
        with self.assertRaises(C.ScanAborted):
            C.candidate_from_row(["not", "a", "row"])

    def test_outcome_adapts_a_scanner_result(self):
        ranked = [{"symbol": "OGDC", "score": 69.87, "price": {"last": 103.9}}]
        result = SimpleNamespace(status="TRADE", reason="strongest momentum",
                                quality=quality(), ranked=ranked,
                                candidate=ranked[0], coverage_text="319/319")
        outcome = C.ScanOutcome.of(result, slot="10:00", as_of=AT,
                                   universe_size=319, scanner_version="v1")
        self.assertTrue(outcome.is_actionable)
        self.assertEqual(outcome.candidate.symbol, "OGDC")
        self.assertEqual(outcome.eligible_count, 1)
        self.assertIsNone(outcome.fault())

    def test_a_locked_day_is_monitoring_not_a_fault(self):
        """The orchestrator reports a trade STATE once the day is locked."""
        for status in ("TARGET_MONITORING", "DAILY_LOCKED", "TRADE_ENTERED"):
            self.assertIs(C.verdict_from_status(status), C.Verdict.MONITORING)
        result = SimpleNamespace(status="TARGET_MONITORING",
                                 reason="one trade already taken today",
                                 quality=quality(), ranked=[])
        outcome = C.ScanOutcome.of(result, slot="10:05", as_of=AT)
        self.assertIs(outcome.verdict, C.Verdict.MONITORING)
        self.assertTrue(outcome.is_monitoring)
        self.assertIsNone(outcome.fault())
        self.assertFalse(outcome.is_market_decision)

    def test_verdict_names_still_map_directly(self):
        self.assertIs(C.verdict_from_status("TRADE"), C.Verdict.TRADE)
        self.assertIs(C.verdict_from_status("data_blocked"),
                      C.Verdict.DATA_BLOCKED)
        self.assertIs(C.verdict_from_status("SOMETHING_NEW"), None)

    def test_outcome_with_an_unknown_verdict_is_aborted(self):
        result = SimpleNamespace(status="SOMETHING_NEW", reason="?", quality=quality())
        with self.assertRaises(C.ScanAborted):
            C.ScanOutcome.of(result, slot="10:00", as_of=AT)

    def test_blocked_outcome_reports_its_fault(self):
        result = SimpleNamespace(
            status="DATA_BLOCKED", reason="stale data: 12 symbols have no bar",
            quality=quality(status=C.Quality.DATA_BLOCKED,
                            reason="stale data: 12 symbols have no bar within 5 "
                                   "minutes of the scan time (fresh coverage 88.0%)",
                            fresh_coverage=0.88),
            coverage_text="307/319")
        outcome = C.ScanOutcome.of(result, slot="10:00", as_of=AT)
        self.assertIsInstance(outcome.fault(), C.StaleFeed)
        self.assertFalse(outcome.is_market_decision)


class IngestionTest(unittest.TestCase):
    day = date(2026, 10, 9)
    as_of = datetime(2026, 10, 9, 10, 5, tzinfo=KARACHI)

    def good_row(self, symbol="OGDC", minutes=5, volume=5000.0):
        bars = [{"t": f"10:{minute:02d}", "o": 100.0, "h": 100.5, "l": 99.5,
                 "c": 100.2, "v": volume} for minute in range(minutes)]
        return {"symbol": symbol, "ts": self.as_of.isoformat(), "bars": bars}

    def test_valid_rows_are_accepted_and_counted(self):
        bars, report = C.validate_bar_rows(
            [self.good_row("OGDC"), self.good_row("PSO")],
            session_day=self.day, as_of=self.as_of,
            universe=["OGDC", "PSO", "AASM"])
        self.assertEqual(report.accepted, 10)
        self.assertEqual(report.rejected, 0)
        self.assertEqual(report.symbols, 2)
        self.assertEqual(len(bars["OGDC"]), 5)

    def test_rows_outside_the_universe_are_not_refusals(self):
        _, report = C.validate_bar_rows([self.good_row("NOT_IN_UNIVERSE")],
                                        session_day=self.day, as_of=self.as_of,
                                        universe=["OGDC"])
        self.assertEqual(report.accepted, 0)
        self.assertEqual(report.rejected, 0)

    def test_each_refusal_is_counted_against_its_reason(self):
        rows = [
            self.good_row("OGDC"),
            {"symbol": "PSO", "bars": [{"t": "10:01", "o": 0, "h": 0, "l": 0,
                                        "c": 0, "v": 1}]},          # non-positive
            {"symbol": "AASM", "bars": [{"t": "10:01", "o": 100, "h": 99, "l": 101,
                                         "c": 100, "v": 1}]},       # impossible
            {"symbol": "PRL", "bars": [{"t": "10:30", "o": 100, "h": 101, "l": 99,
                                        "c": 100, "v": 1}]},        # future bar
            {"symbol": "MLCF", "bars": [{"t": "10:01", "o": 100, "h": 101, "l": 99,
                                         "c": 100, "v": -5}]},      # negative volume
            {"symbol": "HBL", "bars": [{"t": "bad", "o": 1, "h": 1, "l": 1,
                                        "c": 1, "v": 1}]},          # malformed
            {"symbol": "FFC", "bars": [{"t": "09:00", "o": 100, "h": 101, "l": 99,
                                        "c": 100, "v": 1}]},        # wrong session
        ]
        with self.assertRaises(C.SourceUnavailable) as caught:
            C.validate_bar_rows(rows, session_day=self.day, as_of=self.as_of,
                                max_share=0.0)
        self.assertIn("by_reason", caught.exception.context)

    def test_a_mostly_garbage_feed_is_a_source_fault(self):
        rows = [self.good_row("OGDC", minutes=1)] + [
            {"symbol": f"X{index}", "bars": [{"t": "bad"}]} for index in range(20)]
        with self.assertRaises(C.SourceUnavailable):
            C.validate_bar_rows(rows, session_day=self.day, as_of=self.as_of)

    def test_wall_clock_bars_are_read_as_karachi_not_as_the_callers_offset(self):
        """SO-8: a captured "10:01" is 10:01 PKT, whatever zone the caller holds.

        If the caller's instant were UTC, stamping the bar with its offset
        would silently shift every bar five hours into the next day and turn
        the whole session into future or out-of-session bars.
        """
        utc_scan = datetime(2026, 10, 9, 5, 5, tzinfo=_UTC)
        bars, report = C.validate_bar_rows([self.good_row("OGDC")],
                                           session_day=self.day, as_of=utc_scan)
        self.assertEqual(report.rejected, 0)
        first = bars["OGDC"][0].timestamp
        self.assertEqual((first.hour, first.minute), (10, 0))
        self.assertEqual(first.utcoffset(), timedelta(hours=5))
        self.assertEqual(first.date(), self.day)

    def test_a_naive_scan_instant_is_refused_rather_than_guessed(self):
        naive = datetime(2026, 10, 9, 10, 5)
        with self.assertRaises(C.SourceUnavailable) as caught:
            C.validate_bar_rows([self.good_row("OGDC")] * 2,
                                session_day=self.day, as_of=naive, max_share=0.0)
        self.assertIn("MALFORMED", caught.exception.context["by_reason"])

    def test_ingestion_report_share_and_fault(self):
        report = C.IngestionReport(accepted=99, rejected=1)
        self.assertAlmostEqual(report.rejection_share, 0.01)
        self.assertIsNone(report.raises(0.02))
        self.assertIsInstance(report.raises(0.001), C.SourceUnavailable)


class FallbackModeTest(unittest.TestCase):
    def test_models_validate_without_pydantic(self):
        """pydantic is not in requirements.txt, so this path must hold."""
        code = (
            "import sys, types\n"
            "class Blocker:\n"
            "    def find_module(self, name, path=None):\n"
            "        return self if name == 'pydantic' or "
            "name.startswith('pydantic.') else None\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'pydantic' or name.startswith('pydantic.'):\n"
            "            raise ImportError('blocked for the fallback test')\n"
            "        return None\n"
            "sys.meta_path.insert(0, Blocker())\n"
            "from datetime import datetime\n"
            "from src.signals import contracts as C\n"
            "print(C.MODEL_MODE)\n"
            "assert C.MODEL_MODE == 'dataclass', C.MODEL_MODE\n"
            "from src.data.sessions import KARACHI\n"
            "b = C.Bar(symbol='X', timestamp=datetime(2026,10,9,10,0,tzinfo=KARACHI),\n"
            "          open=1.0, high=1.0, low=1.0, close=1.0)\n"
            "print('ok', b.symbol)\n"
            "try:\n"
            "    C.Bar(symbol='X', timestamp=datetime(2026,10,9,10,0,tzinfo=KARACHI),\n"
            "          open=1.0, high=0.5, low=1.0, close=1.0)\n"
            "except ValueError as exc:\n"
            "    print('invariant enforced')\n"
            "else:\n"
            "    raise SystemExit('invariant NOT enforced without pydantic')\n"
        )
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("dataclass", result.stdout)
        self.assertIn("invariant enforced", result.stdout)

    def test_this_interpreter_reports_its_mode(self):
        self.assertIn(C.MODEL_MODE, ("pydantic", "dataclass"))
        self.assertEqual(C.MODEL_MODE == "pydantic", C.PYDANTIC_AVAILABLE)


if __name__ == "__main__":
    unittest.main()
