"""The supervised scan loop: decisions, backoff, faults, health and shutdown.

The loop is driven with an injected clock and a patched orchestrator, so no
test sleeps, dials out or touches the owner's forward-state files.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.data.sessions import KARACHI  # noqa: E402
from src.signals.contracts import (  # noqa: E402
    InsufficientCoverage, ScanFault, Verdict,
)
from scripts import intraday_pipeline as pipeline  # noqa: E402
import scan_loop  # noqa: E402
from scan_loop import LoopConfig, LoopHealth, ScanLoop  # noqa: E402

MONDAY = date(2026, 10, 12)      # open 09:32, close 15:30
FRIDAY = date(2026, 10, 9)       # open 09:17, close 16:30
SATURDAY = date(2026, 10, 10)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KARACHI)


def blocked_payload(reason: str = "KMIALL coverage 40/319 (12.5%) is below the "
                                  "80% floor. Data source incomplete.") -> dict:
    return {
        "status": "DATA_BLOCKED", "reason": reason, "slot": "10:05",
        "data_quality": {"status": "DATA_BLOCKED", "reason": reason,
                         "coverage": 0.125, "fresh_coverage": 0.125,
                         "symbols_expected": 319, "symbols_with_bars": 40,
                         "volume_available": True, "malformed_bars": 0,
                         "duplicate_bars": 0, "impossible_ohlc": 0,
                         "data_age_minutes": 1.0, "resolution": "1-minute",
                         "source": "test"},
        "eligible_count": 0, "candidate": None, "ai": {"active": False},
        "universe_size": 319, "scanner_version": "test",
    }


def trade_payload() -> dict:
    return {
        "status": "TRADE", "reason": "strongest current momentum plus volume",
        "slot": "10:05",
        "data_quality": {"status": "OK", "reason": "coverage present",
                         "coverage": 1.0, "fresh_coverage": 1.0,
                         "symbols_expected": 319, "symbols_with_bars": 319,
                         "volume_available": True},
        "eligible_count": 1,
        "candidate": {"symbol": "OGDC", "score": 69.87, "momentum": "STRONG",
                      "price": {"last": 103.9}, "ai_probability": 0.31,
                      "ai_percentile": 0.82},
        "ai": {"active": True}, "universe_size": 319,
        "scanner_version": "momentum_volume_acceleration_v1",
        "delivered": "TRADE",
    }


class ClockPhaseTest(unittest.TestCase):
    def test_phases_across_the_day(self):
        self.assertEqual(scan_loop.phase_of(at(SATURDAY, 11, 0)), "CLOSED")
        self.assertEqual(scan_loop.phase_of(at(MONDAY, 9, 0)), "PRE_OPEN")
        self.assertEqual(scan_loop.phase_of(at(MONDAY, 9, 40)), "WARMUP")
        self.assertEqual(scan_loop.phase_of(at(MONDAY, 10, 0)), "OPEN")
        self.assertEqual(scan_loop.phase_of(at(MONDAY, 15, 35)), "POST_CLOSE")

    def test_warmup_is_configurable(self):
        self.assertEqual(scan_loop.phase_of(at(MONDAY, 9, 40), warmup_minutes=5),
                         "OPEN")

    def test_slot_is_floored_to_the_interval(self):
        # Owner order 2026-10-11: the cadence is 4 minutes, not 5.
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7)), "10:04")
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 4)), "10:04")

    def test_the_default_cadence_is_four_minutes(self):
        self.assertEqual(scan_loop.config.TICK_INTERVAL_MINUTES, 4)
        self.assertEqual(LoopConfig().interval_seconds, 240.0)


class LoopConfigTest(unittest.TestCase):
    def test_invalid_configuration_is_refused(self):
        bad = [
            {"interval_seconds": 0},
            {"backoff_base_seconds": -1},
            {"backoff_base_seconds": 100, "backoff_max_seconds": 10},
            {"backoff_jitter": 1.5},
            {"max_consecutive_failures": 0},
        ]
        for overrides in bad:
            with self.assertRaises(ValueError, msg=overrides):
                LoopConfig(**overrides)

    def test_backoff_grows_then_caps(self):
        config = LoopConfig(backoff_base_seconds=10, backoff_max_seconds=40,
                            backoff_jitter=0.0)
        delays = [config.backoff_for(failures) for failures in range(1, 6)]
        self.assertEqual(delays, [10, 20, 40, 40, 40])

    def test_no_failures_means_a_normal_interval(self):
        config = LoopConfig(interval_seconds=300, backoff_jitter=0.0)
        self.assertEqual(config.backoff_for(0), 300)

    def test_jitter_stays_inside_its_band(self):
        config = LoopConfig(backoff_base_seconds=100, backoff_max_seconds=100,
                            backoff_jitter=0.5)
        for seed in range(20):
            delay = config.backoff_for(1, random.Random(seed))
            self.assertGreaterEqual(delay, 75.0)
            self.assertLessEqual(delay, 100.0)

    def test_the_failure_streak_ends_the_loop(self):
        config = LoopConfig(max_consecutive_failures=3)
        self.assertTrue(config.should_keep_going(2))
        self.assertFalse(config.should_keep_going(3))


class DecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"

    def loop(self, moment: datetime) -> ScanLoop:
        return ScanLoop(LoopConfig(capture=False), health_path=self.health,
                        clock=lambda: moment)

    def test_closed_market_waits_without_scanning(self):
        loop = self.loop(at(SATURDAY, 11, 0))
        with patch.object(pipeline, "run_scan") as scan:
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "wait")
        self.assertIsNone(outcome)
        scan.assert_not_called()
        self.assertEqual(loop.health.pauses, 1)
        self.assertTrue(self.health.is_file())

    def test_in_session_scans(self):
        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=trade_payload()):
            action, _ = loop.run_cycle()
        self.assertEqual(action, "scan")
        self.assertEqual(loop.health.last_verdict, "TRADE")
        self.assertEqual(loop.health.consecutive_failures, 0)

    def test_post_close_finalizes(self):
        loop = self.loop(at(MONDAY, 15, 35))
        self.assertEqual(loop.decide(at(MONDAY, 15, 35))[0], "finalize")

    def test_pre_market_never_scans(self):
        # Owner order 2026-10-11: the pre-market window is never scanned.
        loop = self.loop(at(MONDAY, 9, 5))
        action, detail = loop.decide(at(MONDAY, 9, 5))
        self.assertEqual(action, "wait")
        self.assertIn("PRE_MARKET", detail)
        self.assertIn("never scanned", detail)

    def test_post_market_finalizes_and_never_scans(self):
        loop = self.loop(at(MONDAY, 15, 40))
        action, detail = loop.decide(at(MONDAY, 15, 40))
        self.assertEqual(action, "finalize")
        self.assertIn("POST_MARKET", detail)
        self.assertIn("finalize-only", detail)

    def test_friday_post_market_finalizes_and_never_scans(self):
        loop = self.loop(at(FRIDAY, 16, 40))
        self.assertEqual(loop.decide(at(FRIDAY, 16, 40))[0], "finalize")

    def test_dry_run_never_scans(self):
        loop = ScanLoop(LoopConfig(capture=False, dry_run=True),
                        health_path=self.health, clock=lambda: at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan") as scan:
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "scan")
        self.assertIsNone(outcome)
        scan.assert_not_called()

    def test_next_delay_after_finalize_waits_for_the_next_session(self):
        loop = self.loop(at(MONDAY, 15, 35))
        delay = loop.next_delay("finalize")
        self.assertGreater(delay, loop.config.interval_seconds)


class CycleOutcomeTest(unittest.TestCase):
    """run_cycle must hand back the typed outcome, not just a health record.

    The tokenized verdict is what --once prints and what any caller logs; a
    swallowed return value would leave the operator without a verdict.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"

    def loop(self, moment: datetime) -> ScanLoop:
        return ScanLoop(LoopConfig(capture=False), health_path=self.health,
                        clock=lambda: moment)

    def test_a_scan_returns_its_typed_outcome(self):
        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=trade_payload()):
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "scan")
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.verdict, Verdict.TRADE)
        self.assertTrue(outcome.is_actionable)
        self.assertEqual(outcome.candidate.symbol, "OGDC")
        self.assertIn("TRADE", outcome.summary())
        self.assertEqual(loop.health.scans, 1)

    def test_a_blocked_scan_returns_its_outcome_and_its_fault(self):
        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan",
                          return_value=blocked_payload()):
            _, outcome = loop.run_cycle()
        self.assertEqual(outcome.verdict, Verdict.DATA_BLOCKED)
        self.assertIsInstance(outcome.fault(), InsufficientCoverage)
        self.assertFalse(outcome.is_market_decision)
        self.assertEqual(loop.health.scans, 1)

    def test_a_taken_trade_reads_as_monitoring_not_a_fault(self):
        payload = {"status": "TARGET_MONITORING",
                   "reason": "the day's trade is live", "slot": "10:35",
                   "data_quality": {"status": "OK", "coverage": 1.0,
                                    "fresh_coverage": 1.0,
                                    "symbols_expected": 319,
                                    "symbols_with_bars": 319}}
        loop = self.loop(at(MONDAY, 10, 35))
        with patch.object(pipeline, "run_scan", return_value=payload):
            _, outcome = loop.run_cycle()
        self.assertEqual(outcome.verdict, Verdict.MONITORING)
        self.assertIsNone(outcome.fault())
        self.assertEqual(loop.health.consecutive_failures, 0)
        self.assertEqual(loop.health.last_verdict, "MONITORING")

    def test_finalize_returns_an_outcome_and_is_not_counted_as_a_scan(self):
        loop = self.loop(at(MONDAY, 15, 35))
        with patch.object(scan_loop.SessionState, "load", return_value=_OPEN_DAY), \
             patch.object(pipeline, "run_finalize",
                          return_value={"outcome": {"outcomes_by_rule": {"r": {}},
                                                    "storage_status": "archived"}}):
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "finalize")
        self.assertEqual(outcome.verdict, Verdict.FINALIZED)
        self.assertIn("archived", outcome.reason)
        self.assertEqual(loop.health.scans, 0)
        self.assertEqual(loop.health.cycles, 1)

    def test_a_waiting_cycle_reports_no_outcome(self):
        loop = self.loop(at(SATURDAY, 11, 0))
        action, outcome = loop.run_cycle()
        self.assertEqual(action, "wait")
        self.assertIsNone(outcome)
        self.assertEqual(loop.health.scans, 0)

    def test_once_on_the_command_line_prints_the_verdict(self):
        loop = self.loop(at(MONDAY, 10, 5))
        printed: list[str] = []
        with patch.object(pipeline, "run_scan", return_value=trade_payload()), \
             patch.object(scan_loop, "ScanLoop", return_value=loop), \
             patch.object(scan_loop, "now_karachi", return_value=at(MONDAY, 10, 5)), \
             patch.object(sys, "stdout", new=_Recording(printed)):
            code = scan_loop.main(["--once", "--skip-capture"])
        self.assertEqual(code, 0)
        verdict_lines = [text.strip() for text in printed
                         if text.strip().startswith("TRADE")]
        self.assertTrue(verdict_lines, printed)
        self.assertIn("OGDC", verdict_lines[0])


class _OpenDay:
    """A session state that has not been finalized yet."""

    finalized = False


_OPEN_DAY = _OpenDay()


class _Recording:
    """A stdout stand-in that keeps what was written."""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def write(self, text: str) -> int:
        self._sink.append(text)
        return len(text)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class FaultClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"
        self.loop = ScanLoop(LoopConfig(capture=False), health_path=self.health,
                             clock=lambda: at(MONDAY, 10, 5))

    def test_a_blocked_scan_is_classified_and_counted(self):
        with patch.object(pipeline, "run_scan",
                          return_value=blocked_payload()):
            self.loop.run_cycle()
        self.assertEqual(self.loop.health.consecutive_failures, 1)
        self.assertEqual(self.loop.health.fault_counts, {"InsufficientCoverage": 1})
        self.assertEqual(self.loop.health.last_verdict, "DATA_BLOCKED")

    def test_a_raised_fault_is_caught_by_class(self):
        with patch.object(pipeline, "run_scan",
                          side_effect=ScanFault("opaque failure")):
            self.loop.run_cycle()
        self.assertEqual(self.loop.health.fault_counts, {"ScanFault": 1})
        self.assertEqual(self.loop.health.last_verdict, "FAULT")

    def test_an_unexpected_exception_does_not_kill_the_loop(self):
        with patch.object(pipeline, "run_scan", side_effect=RuntimeError("boom")):
            self.loop.run_cycle()
        self.assertEqual(self.loop.health.consecutive_failures, 1)
        self.assertEqual(self.loop.health.last_verdict, "FAULT")

    def test_one_success_resets_the_streak(self):
        with patch.object(pipeline, "run_scan", side_effect=RuntimeError("boom")):
            self.loop.run_cycle()
            self.loop.run_cycle()
        self.assertEqual(self.loop.health.consecutive_failures, 2)
        with patch.object(pipeline, "run_scan", return_value=trade_payload()):
            self.loop.run_cycle()
        self.assertEqual(self.loop.health.consecutive_failures, 0)
        self.assertEqual(self.loop.health.failures, 2)  # the tally is kept


class DriverTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"

    def test_the_cycle_cap_stops_the_loop(self):
        loop = ScanLoop(LoopConfig(capture=False, interval_seconds=0.01),
                        health_path=self.health, clock=lambda: at(SATURDAY, 11, 0))
        self.assertEqual(loop.run(max_cycles=2), 0)
        self.assertEqual(loop.health.cycles, 2)

    def test_a_stop_request_is_honoured_between_cycles(self):
        loop = ScanLoop(LoopConfig(capture=False, interval_seconds=0.01),
                        health_path=self.health, clock=lambda: at(MONDAY, 10, 5))
        loop.request_stop()
        self.assertEqual(loop.run(), 0)
        self.assertEqual(loop.health.cycles, 0)

    def test_the_loop_gives_up_after_the_failure_limit(self):
        loop = ScanLoop(LoopConfig(capture=False, interval_seconds=0.01,
                                   max_consecutive_failures=2,
                                   backoff_base_seconds=0.01,
                                   backoff_jitter=0.0),
                        health_path=self.health, clock=lambda: at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", side_effect=RuntimeError("boom")):
            self.assertEqual(loop.run(), 3)
        self.assertGreaterEqual(loop.health.cycles, 2)
        self.assertTrue(loop.health.stopped_at)

    def test_health_round_trips_through_disk(self):
        loop = ScanLoop(LoopConfig(capture=False), health_path=self.health,
                        clock=lambda: at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=trade_payload()):
            loop.run_cycle()
        stored = json.loads(self.health.read_text(encoding="utf-8"))
        self.assertEqual(stored["last_verdict"], "TRADE")
        reloaded = LoopHealth.load(self.health)
        self.assertEqual(reloaded.cycles, 1)
        self.assertEqual(reloaded.last_verdict, "TRADE")

    def test_status_reports_a_decision_without_scanning(self):
        with patch.object(pipeline, "run_scan") as scan:
            with patch.object(sys, "stdout", new=_Sink()):
                code = scan_loop.main(["--status"])
        self.assertEqual(code, 0)
        scan.assert_not_called()


class _Sink:
    def write(self, _text: str) -> int:
        return 0

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class HealthTest(unittest.TestCase):
    def test_fault_tally_and_reset(self):
        health = LoopHealth()
        health.note_fault(ScanFault("one"))
        health.note_fault(ScanFault("two"))
        self.assertEqual(health.consecutive_failures, 2)
        health.note_success()
        self.assertEqual(health.consecutive_failures, 0)
        self.assertEqual(health.failures, 2)
        self.assertIn("ScanFault", health.as_dict()["fault_counts"])


if __name__ == "__main__":
    unittest.main()
