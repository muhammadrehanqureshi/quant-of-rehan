"""The supervised scan loop: decisions, backoff, faults, health and shutdown.

The loop is driven with an injected clock and a patched orchestrator, so no
test sleeps, dials out or touches the owner's forward-state files.
"""

from __future__ import annotations

import asyncio
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
    InsufficientCoverage, ScanFault, ScanOutcome, Verdict,
)
from scripts import intraday_pipeline as pipeline  # noqa: E402
import scan_loop  # noqa: E402
from scan_loop import (  # noqa: E402
    LoopConfig, LoopHealth, QuietTape, ScanLoop,
)

MONDAY = date(2026, 10, 12)      # open 09:32, close 15:30
FRIDAY = date(2026, 10, 9)       # open 09:17, close 16:30
SATURDAY = date(2026, 10, 10)


def setUpModule() -> None:
    """Keep the suite out of logs/scan_loop.log, which belongs to the live loop.

    configure_logging() installs its file handler once per process and keeps
    it for the rest of the run, so before this guard the first test that
    called run() or main() opened the owner's own log and wrote a synthetic
    TRADE verdict, and the RuntimeError("boom") traceback, into it.

    Both guards are removed in tearDownModule. The recorder guard used to be
    handed to ``unittest.addModuleCleanup``, which pytest does not flush for a
    plain module fixture, so ``src.data.live_card.start_tape`` stayed replaced
    for the REST OF THE PROCESS: whichever module ran after this one then saw
    a start_tape that raised, and tests/test_live_card.py's own probe cases
    failed purely because of the order the files were listed in. Found
    2026-10-16 by running the two files in the other order.
    """
    global _LOG_DIR, _LOG_PATCH, _TAPE_GUARD
    _LOG_DIR = tempfile.TemporaryDirectory()
    _LOG_PATCH = patch.object(scan_loop, "LOG_FILE",
                              Path(_LOG_DIR.name) / "scan_loop.log")
    _LOG_PATCH.start()

    # SO-12 machine law: a unit test must never start a broker recorder on the
    # owner's PC. The loop's capture step now asks for one on every cycle, so
    # one forgotten patch is enough to launch a real feed_capture child; that
    # happened on 2026-10-14 (pid 5888) and had to be taken down by hand. With
    # start_tape refusing outright, a test that forgets fails loudly and
    # inside itself instead of touching the machine.
    _TAPE_GUARD = patch("src.data.live_card.start_tape",
                        side_effect=AssertionError(
                            "a unit test must never start a broker recorder"))
    _TAPE_GUARD.start()


def tearDownModule() -> None:
    # Close the handlers before the directory goes: on Windows an open
    # FileHandler locks its file and TemporaryDirectory.cleanup() fails.
    for handler in list(scan_loop.LOGGER.handlers):
        handler.close()
        scan_loop.LOGGER.removeHandler(handler)
    _TAPE_GUARD.stop()
    _LOG_PATCH.stop()
    _LOG_DIR.cleanup()


def at(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second,
                    tzinfo=KARACHI)


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

    def test_the_loop_defaults_to_the_one_second_cloud_cadence(self):
        """Owner order 2026-10-19: the cloud loop asks for a slot every second.

        The local tick keeps its own 4 minute cadence, so the two runners are
        asserted together: a change that quietly made the cloud loop 4
        minutes, or the local tick one second, would fail here.
        """
        self.assertEqual(LoopConfig().interval_seconds,
                         scan_loop.config.SCAN_INTERVAL_SECONDS)
        self.assertEqual(scan_loop.config.SCAN_INTERVAL_SECONDS, 1)
        self.assertEqual(scan_loop.config.TICK_INTERVAL_MINUTES, 4)

    def test_an_overrun_slot_does_not_build_a_backlog(self):
        """A 2.9s cycle cannot fit a 1s slot, so the wait is only the remainder.

        next_delay measures to the NEXT boundary, so a cycle that ends four
        tenths of a second into a slot waits 0.6s, never two slots and never a
        negative sleep. A cycle that ends exactly on a boundary waits the full
        interval. Either way there is no catch-up burst.
        """
        loop = ScanLoop(LoopConfig(dry_run=True, interval_seconds=1))
        for milliseconds, expected in ((400, 0.6), (999, 0.001), (0, 1.0)):
            moment = at(MONDAY, 10, 7, 30) + timedelta(milliseconds=milliseconds)
            loop.clock = lambda m=moment: m
            with self.subTest(at_ms=milliseconds):
                delay = loop.next_delay("scan")
                self.assertAlmostEqual(delay, expected, places=3)
                self.assertGreaterEqual(delay, 0.0)
                self.assertLessEqual(delay, 1.0)

    def test_a_sub_minute_cadence_labels_its_own_slot(self):
        """The once-per-slot guard must not eat the slots inside a minute.

        A minute-labelled slot for a sub-minute runner would scan once a
        minute while its health file claimed a faster cadence. Since the
        owner order of 2026-10-19 the cloud loop is the one second case, and
        the label floors to its own second.
        """
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7, 29),
                                           interval_seconds=1), "10:07:29")
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7, 31),
                                           interval_seconds=1), "10:07:31")
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7, 29),
                                           interval_seconds=30), "10:07:00")
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7, 31),
                                           interval_seconds=30), "10:07:30")
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7, 59),
                                           interval_seconds=30), "10:07:30")
        # The local tick's minute labels are untouched by the new cadence.
        self.assertEqual(scan_loop.slot_of(at(MONDAY, 10, 7), interval_seconds=240),
                         "10:04")


class TapeCaptureTest(unittest.TestCase):
    """A cycle reads the session's tape; the servlet is only a fallback.

    Owner order 2026-10-14 (SO-13): the 30 second cadence is affordable only
    because a cycle measures bars that already exist instead of fetching them.
    These tests hold the loop to that: with a tape on disk the read-only
    recorder is kept alive and measured, and the eClear pass is never invoked;
    a dead tape is a reported fault, never a market verdict.
    """

    def _loop(self) -> ScanLoop:
        # An injected clock at a MARKET moment: the zero-tape and thin-tape
        # answers must not depend on the wall time the suite happens to
        # execute at (a real 09:00 to 09:15 PKT Monday is the pre band's
        # own quiet now, owner order 2026-10-26).
        return ScanLoop(LoopConfig(dry_run=True),
                        clock=lambda: at(MONDAY, 10, 5))

    def _tape_path(self, tmp: str) -> Path:
        path = Path(tmp) / "capture_20261012.ndjson"
        path.write_text("", encoding="utf-8")
        return path

    @staticmethod
    def _tape(symbols: int = 300):
        from types import SimpleNamespace
        return SimpleNamespace(symbols_with_bars=symbols, priced_bars=1000,
                               carried_bars=25, counter_rows=900)

    def test_a_tape_on_disk_is_kept_alive_and_measured(self):
        loop = self._loop()
        with tempfile.TemporaryDirectory() as tmp:
            tape_path = self._tape_path(tmp)
            with patch.object(scan_loop.tape_bars, "capture_path",
                              return_value=tape_path), \
                    patch("src.data.live_card.ensure_tape",
                          return_value=(True, "broker tape alive")) as ensure, \
                    patch.object(scan_loop.tape_bars, "build",
                                 return_value=self._tape()) as build, \
                    patch.object(scan_loop.tape_bars, "write_low_coverage_flag",
                                 return_value=None) as flag, \
                    patch.object(loop, "_poller_capture") as poller:
                self.assertTrue(loop._capture())
        ensure.assert_called_once()
        build.assert_called_once()
        flag.assert_called_once()
        poller.assert_not_called()

    def test_a_fresh_runner_starts_the_recorder_before_choosing_a_source(self):
        """The measured defect of 2026-10-14, held shut.

        The first cloud run of the session loop decided its source from an
        empty data/feed_capture directory, took the servlet fallback, could
        not fit a whole-universe pass into a 30 second cadence and faulted
        five times in a row without ever recording a bar. The recorder must be
        asked for first, tape file or not.
        """
        loop = self._loop()
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "capture_20261012.ndjson"
            with patch.object(scan_loop.tape_bars, "capture_path",
                              return_value=missing), \
                    patch("src.data.live_card.ensure_tape",
                          return_value=(True, "broker tape started (pid 1)")) \
                    as ensure, \
                    patch.object(scan_loop.tape_bars, "build",
                                 return_value=self._tape()), \
                    patch.object(scan_loop.tape_bars, "write_low_coverage_flag",
                                 return_value=None), \
                    patch.object(loop, "_poller_capture") as poller:
                self.assertTrue(loop._capture())
        ensure.assert_called_once()
        poller.assert_not_called()

    def test_the_servlet_fallback_is_given_a_whole_pass_budget(self):
        """A 30 second cadence cannot contain a universe pass, so never ask."""
        loop = self._loop()
        with patch("subprocess.run") as run:
            run.return_value.returncode = 0
            loop._poller_capture(at(MONDAY, 11, 0))
        command = run.call_args.args[0]
        budget = float(command[command.index("--deadline-seconds") + 1])
        self.assertGreaterEqual(budget, 120.0)

    def test_a_thin_tape_raises_the_health_flag_it_will_be_reported_by(self):
        loop = self._loop()
        with tempfile.TemporaryDirectory() as tmp:
            tape_path = self._tape_path(tmp)
            with patch.object(scan_loop.tape_bars, "capture_path",
                              return_value=tape_path), \
                    patch("src.data.live_card.ensure_tape",
                          return_value=(True, "broker tape alive")), \
                    patch.object(scan_loop.tape_bars, "build",
                                 return_value=self._tape(symbols=4)), \
                    patch.object(scan_loop.tape_bars, "write_low_coverage_flag",
                                 return_value=Path("ohlc_low_coverage.flag")) as flag:
                self.assertTrue(loop._capture())
        # The cause the alert quotes names the source that was thin.
        self.assertIn("the tape held bars for 4 of", flag.call_args.kwargs["cause"])

    def test_a_tape_with_no_bars_is_a_reported_fault(self):
        loop = self._loop()
        with tempfile.TemporaryDirectory() as tmp:
            tape_path = self._tape_path(tmp)
            # _capture reads the REAL clock, so the state behind its
            # zero-bar branch is pinned: a CI run's own wall time would
            # otherwise decide the verdict.
            with (patch.object(scan_loop.tape_bars, "capture_path",
                               return_value=tape_path),
                  patch("src.data.live_card.ensure_tape",
                        return_value=(True, "alive but quiet")),
                  patch.object(scan_loop, "now_karachi",
                               return_value=at(MONDAY, 10, 5)),
                  patch.object(scan_loop.tape_bars, "build",
                               return_value=self._tape(symbols=0)),
                  patch.object(scan_loop.tape_bars,
                               "write_low_coverage_flag",
                               return_value=None)):
                with self.assertRaises(ScanFault):
                    loop._capture()

    def test_a_day_with_no_tape_falls_back_only_when_no_recorder_can_start(self):
        loop = self._loop()
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "capture_20261012.ndjson"
            with patch.object(scan_loop.tape_bars, "capture_path",
                              return_value=missing), \
                    patch("src.data.live_card.ensure_tape",
                          return_value=(False, "the recorder could not start")), \
                    patch.object(loop, "_poller_capture",
                                 return_value=True) as poller:
                self.assertTrue(loop._capture())
        poller.assert_called_once()


class PreMarketQuietTapeTest(unittest.TestCase):
    """Owner order 2026-10-26: the pre band's empty tape is a wait, never off.

    On the day that order was mailed, the loop died from its own breaker:
    five zero-bar cycles inside the pre band crossed the five-failure cap
    at 09:07, the band stood down and the owner received neither scan nor
    the 09:32 open email. The pre band's quiet books a pause from now on.

    These are full-path tests, so the fixture builds a live tape source
    and empty bars, exactly the shape that killed the 2026-10-26 band.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"

    def _mocks(self, moment: datetime):
        from contextlib import ExitStack
        from types import SimpleNamespace

        stack = ExitStack()
        # _capture reads the REAL clock (scan_loop.now_karachi), so the
        # state behind the quiet branch is pinned here: no test may depend
        # on the wall time the suite happens to execute at.
        stack.enter_context(patch.object(
            scan_loop, "now_karachi", return_value=moment))
        tape_path = Path(self._dir.name) / "capture_20261012.ndjson"
        tape_path.write_text("", encoding="utf-8")
        stack.enter_context(patch.object(
            scan_loop.tape_bars, "capture_path", return_value=tape_path))
        stack.enter_context(patch(
            "src.data.live_card.ensure_tape",
            return_value=(True, "broker tape alive")))
        stack.enter_context(patch.object(
            scan_loop.tape_bars, "build",
            return_value=SimpleNamespace(symbols_with_bars=0,
                                         priced_bars=0, carried_bars=0,
                                         counter_rows=0)))
        stack.enter_context(patch.object(
            scan_loop.tape_bars, "write_low_coverage_flag",
            return_value=None))
        return stack

    def test_a_premarket_zero_tape_raises_the_wait_not_the_fault(self):
        loop = ScanLoop(LoopConfig(dry_run=True), health_path=self.health,
                        clock=lambda: at(MONDAY, 9, 5))
        with self._mocks(at(MONDAY, 9, 5)):
            with self.assertRaises(ScanFault) as ctx:
                loop._capture()
        self.assertIsInstance(ctx.exception, QuietTape)

    def test_a_market_zero_tape_is_still_a_fault(self):
        # A real quantum change of shape: outside the pre band the same
        # zero-bar tape is a dead input, Blessed, always a fault.
        loop = ScanLoop(LoopConfig(dry_run=True), health_path=self.health,
                        clock=lambda: at(MONDAY, 10, 5))
        with self._mocks(at(MONDAY, 10, 5)):
            with self.assertRaises(ScanFault) as ctx:
                loop._capture()
        self.assertNotIsInstance(ctx.exception, QuietTape)

    def test_a_premarket_quiet_cycle_books_a_pause_and_lives(self):
        # The whole cycle: the quiet enters the run_decision, is booked
        # as one pause (never a fault), the health is published and the
        # loop is ready for its next cycle.
        loop = ScanLoop(LoopConfig(), health_path=self.health,
                        clock=lambda: at(MONDAY, 9, 5))
        with self._mocks(at(MONDAY, 9, 5)), \
                patch.object(pipeline, "run_scan") as scan:
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "scan")
        self.assertIsNone(outcome)
        self.assertEqual(loop.health.pauses, 1)
        self.assertEqual(loop.health.last_verdict, "QUIET")
        self.assertEqual(loop.health.consecutive_failures, 0)
        self.assertTrue(self.health.is_file())
        scan.assert_not_called()


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

    def test_a_band_cycle_publishes_the_market_card_from_the_tape(self):
        # Owner order 2026-10-15: the phone's B and S numbers are the tape's
        # own counts, so the loop that owns the tape publishes the card every
        # cycle inside the band. Without this, the relay serves only its own
        # portal estimate and MACFL closed at the low prints as B=0 S=all.
        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=trade_payload()), \
                patch("src.data.live_card.publish_card",
                      return_value={"ok": True, "detail": "card published to "
                                                   "the relay", "split":
                                                   "B/S counted from the tape"}) \
                as card:
            action, _ = loop.run_cycle()
        self.assertEqual(action, "scan")
        card.assert_called_once()

    def test_a_wait_outside_the_band_does_not_publish_the_card(self):
        loop = self.loop(at(SATURDAY, 11, 0))
        with patch("src.data.live_card.publish_card") as card:
            loop.run_cycle()
        card.assert_not_called()

    def test_a_failed_card_does_not_fault_the_scan(self):
        # The card is a best effort push beside the scan: the tape's verdict
        # stands even when the relay refuses the snapshot.
        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=trade_payload()), \
                patch("src.data.live_card.publish_card",
                      return_value={"ok": False, "detail": "card push failed: "
                                                   "ConnectError", "split":
                                                   "unknown"}):
            loop.run_cycle()
        self.assertEqual(loop.health.last_verdict, "TRADE")
        self.assertEqual(loop.health.consecutive_failures, 0)

    def test_a_card_publish_inside_a_finalizing_cycle_also_runs(self):
        # OWNER NOTE 2026-10-21: the finalize window SCANS now (live broker
        # feed); the finalize itself stays with the capture workflow. This
        # test pins the order of the cycle that runs after POST_CLOSE when
        # the loop is inside a band-tail, not the old finalize-only rule.
        loop = self.loop(at(MONDAY, 15, 35))
        with patch.object(pipeline, "run_finalize",
                          return_value={"outcome": {}, "gate": {}}) as fin, \
                patch("src.data.live_card.publish_card",
                      return_value={"ok": True, "detail": "card published to "
                                                   "the relay", "split":
                                                   "B/S counted from the tape"}) \
                as card:
            action, _ = loop.run_cycle()
        self.assertEqual(action, "scan")
        card.assert_called_once()
        fin.assert_not_called()

    def test_post_close_finalizes(self):
        # OWNER 2026-10-21: post-market scans, so a loop cycle inside the
        # law's POST_MARKET window behaves like a scan cycle instead. The
        # old POST_CLOSE finalize decision is exercised as a scheduled
        # finalize, which belongs to the capture workflow alone.
        loop = self.loop(at(MONDAY, 15, 35))
        self.assertEqual(loop.decide(at(MONDAY, 15, 35))[0], "scan")

    def test_pre_market_scans_live(self):
        # Owner order 2026-10-21 (superseding 2026-10-11): the pre-market
        # window scans, on the live broker feed.
        loop = self.loop(at(MONDAY, 9, 5))
        action, detail = loop.decide(at(MONDAY, 9, 5))
        self.assertEqual(action, "scan")
        self.assertIn("PRE_MARKET", detail)
        self.assertIn("2026-10-21", detail)


    def test_post_market_scans_live(self):
        # Owner order 2026-10-21 (superseding 2026-10-11): post-market
        # scans like pre; the window is a live scan window.
        loop = self.loop(at(MONDAY, 15, 40))
        action, detail = loop.decide(at(MONDAY, 15, 40))
        self.assertEqual(action, "scan")
        self.assertIn("POST_MARKET", detail)
        self.assertIn("2026-10-21", detail)

    def test_friday_post_market_scans_live(self):
        # Friday's own post window (16:32 to 16:49).
        loop = self.loop(at(FRIDAY, 16, 40))
        self.assertEqual(loop.decide(at(FRIDAY, 16, 40))[0], "scan")

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

    def test_the_post_market_cycle_scans_and_is_counted(self):
        # OWNER 2026-10-21: the post-market window is a scan window now, so
        # a cycle there is a scan cycle. Owner order 2026-10-24: that cycle
        # is a COUNTED scan (health.scans includes it), because the owner
        # reads the day's scan count off the health card and a post-market
        # scan of the finished tape is a real scan. The scheduled finalize
        # lives in the capture workflow and is covered by that workflow's
        # own tests.
        loop = self.loop(at(MONDAY, 15, 35))
        with patch.object(scan_loop.SessionState, "load", return_value=_OPEN_DAY), \
             patch.object(pipeline, "run_finalize",
                          return_value={"outcome": {"outcomes_by_rule": {"r": {}},
                                                    "storage_status": "archived"}}):
            action, outcome = loop.run_cycle()
        self.assertEqual(action, "scan")
        # Owner order 2026-10-24: the post-market cycle is a COUNTED scan -
        # a scan of the day's finished tape is a real scan of that day.
        self.assertEqual(loop.health.scans, 1)
        self.assertEqual(loop.health.cycles, 1)

    def test_a_waiting_cycle_reports_no_outcome(self):
        loop = self.loop(at(SATURDAY, 11, 0))
        action, outcome = loop.run_cycle()
        self.assertEqual(action, "wait")
        self.assertIsNone(outcome)
        self.assertEqual(loop.health.scans, 0)

    def test_a_warming_up_cycle_is_a_pause_and_not_a_fault(self):
        """Measured 2026-10-14: this state was counted as 86 coverage faults in
        one band, which made a healthy tape read as a dead feed."""
        payload = blocked_payload(
            "bar history: only 0/301 captured symbols (0.0%) hold the 20 bars "
            "the strategy needs, below the 80% floor; the bar source has been "
            "alive 8 of the 20 minutes this needs, so the scan is WARMING UP "
            "and resumes on its own in about 12 minute(s)")
        payload["data_quality"]["warming_up"] = True
        payload["data_quality"]["warmup_minutes_remaining"] = 12.0
        payload["data_quality"]["symbols_with_bars"] = 301

        loop = self.loop(at(MONDAY, 10, 5))
        with patch.object(pipeline, "run_scan", return_value=payload):
            _, outcome = loop.run_cycle()

        self.assertEqual(outcome.verdict, Verdict.DATA_BLOCKED)
        self.assertIsNone(outcome.fault(),
                          "a young bar source must not be a typed fault")
        self.assertTrue(outcome.quality.warming_up)
        self.assertEqual(loop.health.warmups, 1)
        self.assertEqual(loop.health.failures, 0)
        self.assertEqual(loop.health.fault_counts, {})
        self.assertEqual(loop.health.consecutive_failures, 0)

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


class ScheduledModeTest(unittest.TestCase):
    """The loop driven by the async scheduler instead of its own sleep.

    The scheduler owns the clock and the retry policy; the loop owns the
    cycle. These cases hold the seam: a cycle that fails must reach the
    scheduler as a failure (or the scheduler would believe a dead feed was
    healthy), a cycle that warms up must NOT (or five warm-up cycles would
    stop a working band), and the cadence handed over must be the loop's own.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.health = Path(self._dir.name) / "health.json"

    def test_the_interval_handed_to_the_scheduler_is_the_loops_own(self):
        """A 4 minute loop hands the scheduler 4 minutes, not its own sleep."""
        seen: list[float] = []

        def fake(*_args, **kwargs):
            seen.append(kwargs["scheduler_config"].interval_minutes)
            return _Report()

        loop = ScanLoop(LoopConfig(interval_seconds=240.0, capture=False),
                        health_path=self.health)
        with patch.object(scan_loop, "run_scanner_schedule", side_effect=fake):
            code = loop.run_scheduled()

        self.assertEqual(code, 0)
        self.assertEqual(seen, [4.0])
        self.assertTrue(self.health.is_file())
        saved = LoopHealth.load(self.health)
        self.assertTrue(saved.started_at)
        self.assertTrue(saved.stopped_at)
        self.assertTrue(loop.health.stopped_at)

    def loop(self) -> ScanLoop:
        return ScanLoop(LoopConfig(capture=False), health_path=self.health,
                        clock=lambda: at(MONDAY, 10, 5))

    def test_a_failed_cycle_is_raised_to_the_scheduler(self):
        loop = self.loop()
        payload = blocked_payload()          # a real data failure, not a warmup

        with patch.object(pipeline, "run_scan", return_value=payload):
            with self.assertRaises(ScanFault):
                asyncio.run(loop.scheduled_scanner()(
                    "scan", "10:04", at(MONDAY, 10, 5)))
        self.assertGreater(loop.health.consecutive_failures, 0)
        self.assertIn("InsufficientCoverage", loop.health.fault_counts)

    def test_a_warming_up_cycle_is_not_raised_to_the_scheduler(self):
        loop = self.loop()
        payload = blocked_payload("bar history: only 0/301 captured symbols "
                                 "(0.0%) hold the 20 bars the strategy needs, "
                                 "below the 80% floor; the scan is WARMING UP")
        payload["data_quality"]["warming_up"] = True

        with patch.object(pipeline, "run_scan", return_value=payload):
            asyncio.run(loop.scheduled_scanner()(
                "scan", "10:04", at(MONDAY, 10, 5)))     # must not raise
        self.assertEqual(loop.health.warmups, 1)
        self.assertEqual(loop.health.consecutive_failures, 0)
        self.assertEqual(loop.health.fault_counts, {})


class _Report:
    """What run_scanner_schedule hands back, for the wiring tests."""

    cycles = 1
    scans = 1
    pauses = 0
    failures = 0
    last_action = "scan"
    last_reason = "test"

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    exit_code = 0


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

    def test_a_finalized_day_ends_the_loop_instead_of_sleeping(self):
        """Owner audit 2026-10-19: a late fire must not idle for hours.

        The loop used to sleep to the next open after a finalize (measured:
        224,435 seconds on a late Friday fire), so the shell timeout killed a
        job with nothing left to do and the band's minutes were billed for an
        empty wait. The process is asked for THIS band, so a finalized day is
        the end of its work.
        """
        outcome = ScanOutcome(as_of=at(MONDAY, 15, 31), slot="15:28",
                              verdict=Verdict.FINALIZED, reason="closed")
        loop = ScanLoop(LoopConfig(capture=False, interval_seconds=0.01),
                        health_path=self.health,
                        clock=lambda: at(MONDAY, 15, 31))
        with patch.object(loop, "run_cycle", return_value=("finalize", outcome)), \
                patch.object(loop, "_sleep") as sleep:
            self.assertEqual(loop.run(), 0)
        sleep.assert_not_called()
        self.assertEqual(loop.health.cycles, 0)  # the patched cycle does no work

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
