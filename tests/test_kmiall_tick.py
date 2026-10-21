"""The local 4-minute tick: pause, guard, lock, capture failure, finalize.

Nothing here touches the network, the real relay or the owner's real
data/forward directory: the session state root is redirected to a temporary
directory and the pipeline entry points are patched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI  # noqa: E402
from src.signals import trade_state  # noqa: E402
from src.signals.trade_state import SessionState  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import kmiall_tick  # noqa: E402

# Imported the same way the tick imports it (as scripts.intraday_pipeline), so
# patching here patches the module the tick actually calls. A top-level
# `import intraday_pipeline` would be a second, separate module object.
from scripts import intraday_pipeline as pipeline  # noqa: E402

MONDAY = date(2026, 10, 12)
FRIDAY = date(2026, 10, 9)
SATURDAY = date(2026, 10, 10)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KARACHI)


class PhaseTest(unittest.TestCase):
    def test_weekend_is_closed(self):
        self.assertEqual(kmiall_tick.phase_of(at(SATURDAY, 11, 0)),
                         kmiall_tick.PHASE_CLOSED)

    def test_before_the_open_is_pre_open(self):
        self.assertEqual(kmiall_tick.phase_of(at(MONDAY, 9, 0)),
                         kmiall_tick.PHASE_PRE_OPEN)

    def test_the_warmup_window_does_not_scan(self):
        # Monday opens 09:32; the strategy needs 20 bars and three volume
        # buckets, so the first TICK_WARMUP_MINUTES are paused.
        self.assertEqual(kmiall_tick.phase_of(at(MONDAY, 9, 40)),
                         kmiall_tick.PHASE_WARMUP)
        self.assertEqual(kmiall_tick.phase_of(at(MONDAY, 9, 52)),
                         kmiall_tick.PHASE_OPEN)

    def test_friday_uses_its_own_session(self):
        self.assertEqual(kmiall_tick.phase_of(at(FRIDAY, 9, 20)),
                         kmiall_tick.PHASE_WARMUP)
        self.assertEqual(kmiall_tick.phase_of(at(FRIDAY, 15, 45)),
                         kmiall_tick.PHASE_OPEN)
        self.assertEqual(kmiall_tick.phase_of(at(FRIDAY, 16, 31)),
                         kmiall_tick.PHASE_POST_CLOSE)

    def test_after_the_close_is_post_close(self):
        self.assertEqual(kmiall_tick.phase_of(at(MONDAY, 15, 35)),
                         kmiall_tick.PHASE_POST_CLOSE)

    def test_slot_is_floored_to_the_interval(self):
        # Owner order 2026-10-11: the cadence is 4 minutes, not 5.
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 7)), "10:04")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 4)), "10:04")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 59)), "10:56")


class TickTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        self.addCleanup(patch.object(trade_state, "ROOT", root).stop)
        patch.object(trade_state, "ROOT", root).start()
        self.lock = root / "tick.lock"
        self.health = root / "tick_health.json"
        self.logfile = root / "tick.log"
        patch.object(kmiall_tick, "LOCK_FILE", self.lock).start()
        patch.object(kmiall_tick, "HEALTH_FILE", self.health).start()
        patch.object(kmiall_tick, "LOG_FILE", self.logfile).start()
        self.addCleanup(patch.stopall)

    def fake_clock(self, moment: datetime):
        patcher = patch.object(kmiall_tick, "now_karachi", lambda: moment)
        patcher.start()
        return patcher

    def saved_state(self, day: date = MONDAY) -> SessionState:
        return SessionState.load(day)


class PauseTest(TickTestCase):
    def test_closed_market_pauses_without_scanning(self):
        self.fake_clock(at(SATURDAY, 11, 0))
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_not_called()
        self.assertIn("paused", self.logfile.read_text(encoding="utf-8"))

    def test_warmup_pauses_without_scanning(self):
        self.fake_clock(at(MONDAY, 9, 40))
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_not_called()


class SlotGuardTest(TickTestCase):
    def test_the_same_slot_is_scanned_once(self):
        moment = at(MONDAY, 10, 7)
        state = self.saved_state(MONDAY)
        state.note_tick("10:04")
        state.save()
        self.fake_clock(moment)
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_not_called()

    def test_force_rescans_the_slot(self):
        moment = at(MONDAY, 10, 7)
        state = self.saved_state(MONDAY)
        state.note_tick("10:04")
        state.save()
        self.fake_clock(moment)
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", return_value={"status": "NO_TRADE"}) as scan:
            self.assertEqual(kmiall_tick.main(["--force"]), 0)
        scan.assert_called_once_with("10:04")


class LockTest(TickTestCase):
    def test_a_live_lock_refuses_to_run(self):
        moment = at(MONDAY, 10, 7)
        self.fake_clock(moment)
        self.lock.write_text(json.dumps({
            "pid": os.getpid(), "started_iso": moment.isoformat()}), encoding="utf-8")
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 4)
        scan.assert_not_called()

    def test_a_stale_lock_is_reclaimed(self):
        moment = at(MONDAY, 10, 7)
        self.lock.write_text(json.dumps({
            "pid": 999_999,
            "started_iso": (moment - timedelta(hours=2)).isoformat()}), encoding="utf-8")
        held, detail = kmiall_tick.acquire_lock(moment)
        self.assertTrue(held, detail)
        self.assertIn("reclaim", self.logfile.read_text(encoding="utf-8"))

    def test_the_lock_is_released_after_a_tick(self):
        moment = at(MONDAY, 10, 7)
        self.fake_clock(moment)
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", return_value={"status": "NO_TRADE"}):
            self.assertEqual(kmiall_tick.main([]), 0)
        self.assertFalse(self.lock.exists(), "a finished tick must release its lock")


class CaptureTest(TickTestCase):
    def test_a_failed_capture_still_scans_and_reports_exit_2(self):
        self.fake_clock(at(MONDAY, 10, 7))
        with patch.object(kmiall_tick, "run_capture",
                          return_value=(False, "feed down")), \
                patch.object(pipeline, "run_scan",
                             return_value={"status": "DATA_BLOCKED"}):
            self.assertEqual(kmiall_tick.main([]), 2)
        health = json.loads(self.health.read_text(encoding="utf-8"))
        self.assertEqual(health["consecutive_failures"], 1)
        self.assertFalse(health["last_ok"])

    def test_health_resets_after_a_good_capture(self):
        kmiall_tick.note_health(False, "down")
        kmiall_tick.note_health(True, "ok")
        health = json.loads(self.health.read_text(encoding="utf-8"))
        self.assertEqual(health["consecutive_failures"], 0)
        self.assertTrue(health["last_ok"])

    def test_the_ops_alert_fires_once_at_the_threshold(self):
        with patch.object(pipeline, "deliver") as deliver:
            for _ in range(2):
                kmiall_tick.note_health(False, "feed down")
            deliver.assert_not_called()
            kmiall_tick.note_health(False, "feed down")   # third failure
            self.assertEqual(deliver.call_count, 1)
            kmiall_tick.note_health(False, "feed down")   # fourth
            self.assertEqual(deliver.call_count, 1)
        self.assertIn("ops alert sent", self.logfile.read_text(encoding="utf-8"))

    def test_a_continuing_outage_re_alerts_once_per_day(self):
        # Owner order 2026-10-12 (zero-defect law): a feed that stays broken
        # must not go quiet after the first alert. One reminder per Karachi
        # day, never one per tick.
        self.fake_clock(at(MONDAY, 10, 7))
        with patch.object(pipeline, "deliver") as deliver:
            for _ in range(kmiall_tick.ALERT_AFTER_FAILURES):
                kmiall_tick.note_health(False, "feed down")
            self.assertEqual(deliver.call_count, 1)   # the threshold alert
            kmiall_tick.note_health(False, "feed down")      # same day, quiet
            self.assertEqual(deliver.call_count, 1)
            self.fake_clock(at(MONDAY + timedelta(days=1), 10, 7))  # day two
            kmiall_tick.note_health(False, "feed down")
            self.assertEqual(deliver.call_count, 2)   # the daily reminder
            kmiall_tick.note_health(False, "feed down")      # still one a day
            self.assertEqual(deliver.call_count, 2)

    def test_a_healthy_pass_re_arms_the_daily_reminder(self):
        self.fake_clock(at(MONDAY, 10, 7))
        with patch.object(pipeline, "deliver") as deliver:
            for _ in range(kmiall_tick.ALERT_AFTER_FAILURES):
                kmiall_tick.note_health(False, "feed down")
            self.assertEqual(deliver.call_count, 1)
            kmiall_tick.note_health(True, "ok")              # the feed recovers
            for _ in range(kmiall_tick.ALERT_AFTER_FAILURES):
                kmiall_tick.note_health(False, "feed down")  # a new outage
            self.assertEqual(deliver.call_count, 2)

    def test_a_healthy_pass_clears_the_day_stamp(self):
        kmiall_tick.note_health(False, "feed down")
        kmiall_tick.note_health(True, "ok")
        health = json.loads(self.health.read_text(encoding="utf-8"))
        self.assertNotIn("last_failure_alert_day", health)

    def test_a_successful_tick_records_the_slot(self):
        moment = at(MONDAY, 10, 7)
        self.fake_clock(moment)
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", return_value={"status": "NO_TRADE"}):
            self.assertEqual(kmiall_tick.main([]), 0)
        self.assertEqual(self.saved_state(MONDAY).last_tick_slot, "10:04")


class ScanWindowTest(TickTestCase):
    """Owner order 2026-10-21: the pre-market and post-market windows scan on
    the live broker feed; the morning gap and CLOSED stay asleep."""

    def test_pre_market_scans_on_the_live_broker_feed(self):
        self.fake_clock(at(MONDAY, 9, 5))
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan",
                             return_value={"status": "NO_TRADE"}) as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_called_once()
        log = self.logfile.read_text(encoding="utf-8")
        self.assertIn("PRE_MARKET", log)

    def test_the_gap_between_pre_market_and_the_open_never_scans(self):
        self.fake_clock(at(MONDAY, 9, 20))
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_not_called()

    def test_post_market_scans_until_the_window_closes(self):
        self.fake_clock(at(MONDAY, 15, 40))
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan",
                             return_value={"status": "NO_TRADE"}) as scan, \
                patch.object(pipeline, "run_finalize") as finalize:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_called_once()
        finalize.assert_not_called()
        self.assertFalse(self.saved_state(MONDAY).finalized)

    def test_friday_post_market_scans(self):
        self.fake_clock(at(FRIDAY, 16, 40))
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan",
                             return_value={"status": "NO_TRADE"}) as scan, \
                patch.object(pipeline, "run_finalize") as finalize:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_called_once()
        finalize.assert_not_called()

    def test_the_state_is_reported_in_the_log(self):
        self.assertEqual(kmiall_tick.state_of(at(MONDAY, 11, 0)), "MARKET")
        self.assertEqual(kmiall_tick.state_of(at(MONDAY, 9, 5)), "PRE_MARKET")
        self.assertEqual(kmiall_tick.state_of(at(MONDAY, 15, 40)),
                         "POST_MARKET")


class CadenceTest(unittest.TestCase):
    """Owner order 2026-10-11: every 4 minutes, forever until further notice."""

    def test_config_default_is_four_minutes(self):
        self.assertEqual(kmiall_tick.config.TICK_INTERVAL_MINUTES, 4)

    def test_slot_math_is_four_minute_floored(self):
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 3)), "10:00")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 4)), "10:04")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 59)), "10:56")

    def test_the_installed_task_asks_for_four_minutes(self):
        import install_kmiall_tick

        command = install_kmiall_tick.create_command()
        self.assertIn("/mo", command)
        self.assertEqual(command[command.index("/mo") + 1], "4")

    def test_the_installed_task_cannot_flash_a_console_window(self):
        """Owner report 2026-10-11: a window flashed every few minutes.

        The task ran python.exe, a console program, in the owner's own
        session, so Windows opened a console on every fire and the tick (a
        second or less on a closed day) had come and gone before he could
        read it. The registered action must name the windowless interpreter,
        so a re-install cannot bring the flash back.

        Written for both platforms on purpose. pythonw.exe exists on Windows
        only, and the test suite also runs on the Linux CI runner, where the
        first version of this test demanded pythonw.exe and failed there: the
        installer was right to fall back and the test was wrong. So the
        contract is asserted platform-neutrally, and the Windows-specific
        expectation is asserted only where a windowless interpreter exists.
        """
        import install_kmiall_tick

        command = install_kmiall_tick.create_command()
        action = command[command.index("/tr") + 1]
        interpreter = install_kmiall_tick.windowless_interpreter()

        self.assertIn(str(interpreter), action)
        self.assertIn(str(install_kmiall_tick.TICK_SCRIPT), action)

        windowless = Path(sys.executable).with_name("pythonw.exe")
        if windowless.is_file():
            # The interpreter field of the action is the first quoted token.
            self.assertTrue(action.split('"')[1].endswith("pythonw.exe"),
                            action)
            self.assertEqual(interpreter, windowless)
        else:
            self.assertEqual(interpreter, Path(sys.executable))

    def test_a_build_without_pythonw_still_registers_something(self):
        import install_kmiall_tick
        from unittest import mock

        with mock.patch("pathlib.Path.is_file", return_value=False):
            fallback = install_kmiall_tick.windowless_interpreter()
        self.assertEqual(fallback, Path(sys.executable))


class SessionTriggerTest(unittest.TestCase):
    """The task must not fire outside the owner's session windows at all.

    Owner order 2026-10-11: scan every 4 minutes, in market hours only, with
    pre-market, post-market and the Friday midday break explicitly excluded.
    Before this the registered trigger repeated every 4 minutes around the
    clock for ever and relied entirely on the tick to pause, so the machine
    woke 360 times a day to do nothing.
    """

    MON_THU = ("Monday", "Tuesday", "Wednesday", "Thursday")

    def setUp(self) -> None:
        import install_kmiall_tick

        self.installer = install_kmiall_tick
        self.triggers = install_kmiall_tick.session_triggers()

    @staticmethod
    def _minute(hhmm: str) -> int:
        return int(hhmm[:2]) * 60 + int(hhmm[3:])

    def bands_for(self, day: str) -> list[tuple[int, int]]:
        return [
            (self._minute("09:32"), self._minute("15:30")),
        ] if day in self.MON_THU else [
            (self._minute("09:17"), self._minute("12:00")),
            (self._minute("14:32"), self._minute("16:30")),
        ]

    def fires(self, trigger: dict) -> list[tuple[str, int]]:
        """Every (weekday, minute of day) this trigger can fire at."""
        start = self._minute(trigger["start"])
        if not trigger["every_minutes"]:
            minutes = [start]
        else:
            minutes = list(range(start,
                                 start + trigger["duration_minutes"] + 1,
                                 trigger["every_minutes"]))
        return [(day, minute) for day in trigger["days"] for minute in minutes]

    def scan_triggers(self) -> list[dict]:
        return [t for t in self.triggers if t["every_minutes"]]

    def finalize_triggers(self) -> list[dict]:
        return [t for t in self.triggers if not t["every_minutes"]]

    def test_the_cadence_is_the_owner_four_minutes(self):
        self.assertEqual(kmiall_tick.config.TICK_INTERVAL_MINUTES, 4)
        for trigger in self.scan_triggers():
            self.assertEqual(trigger["every_minutes"], 4, trigger)

    def test_every_scan_fire_lands_inside_a_live_band(self):
        for trigger in self.scan_triggers():
            for day, minute in self.fires(trigger):
                bands = self.bands_for(day)
                self.assertTrue(
                    any(opens <= minute < closes for opens, closes in bands),
                    f"{trigger['name']} would fire at "
                    f"{minute // 60:02d}:{minute % 60:02d} on {day}, outside "
                    f"{bands}")

    def test_a_band_trigger_covers_the_whole_band_and_nothing_else(self):
        for trigger in self.scan_triggers():
            for day in trigger["days"]:
                start = self._minute(trigger["start"])
                match = [band for band in self.bands_for(day) if band[0] == start]
                self.assertEqual(len(match), 1,
                                 f"{trigger['name']} on {day} starts "
                                 f"{trigger['start']}, which is no band edge")
                self.assertEqual(start + trigger["duration_minutes"],
                                 match[0][1], trigger)

    def test_nothing_fires_in_the_pre_market_window(self):
        pre_open = self._minute("09:00")
        pre_close = self._minute("09:15")
        for trigger in self.triggers:
            for day, minute in self.fires(trigger):
                self.assertFalse(pre_open <= minute < pre_close,
                                 f"{trigger['name']} fires inside the "
                                 f"pre-market window on {day}")

    def test_nothing_fires_in_the_friday_midday_break(self):
        break_open = self._minute("12:00")
        break_close = self._minute("14:32")
        for trigger in self.triggers:
            if "Friday" not in trigger["days"]:
                continue
            for day, minute in self.fires(trigger):
                self.assertFalse(break_open <= minute < break_close,
                                 f"{trigger['name']} fires inside the break")

    def test_the_finalize_fires_once_inside_the_post_market_window(self):
        for trigger in self.finalize_triggers():
            fires = self.fires(trigger)
            days = set(day for day, _ in fires)
            for day in days:
                at = [m for d, m in fires if d == day]
                self.assertEqual(len(at), 1, trigger)
            if days == set(self.MON_THU):
                at, opens, closes = "15:47", "15:32", "15:49"
            else:
                at, opens, closes = "16:47", "16:32", "16:49"
            self.assertEqual(self._minute(trigger["start"]), self._minute(at))
            self.assertTrue(self._minute(opens) <= self._minute(at)
                            < self._minute(closes), trigger)

    def test_the_task_xml_parses_and_carries_the_cadence(self):
        from xml.etree import ElementTree

        xml = self.installer.task_xml()
        root = ElementTree.fromstring(xml)
        namespace = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"

        intervals = [node.text for node in root.iter(f"{namespace}Interval")]
        self.assertEqual(intervals, ["PT4M"] * 3)
        self.assertEqual(len(list(root.iter(f"{namespace}CalendarTrigger"))), 5)
        # The definition must name the interpreter the installer chose, which
        # is pythonw.exe wherever it exists and the running interpreter
        # everywhere else (the CI job runs on Linux, where the first version of
        # this test wrongly demanded an .exe). Asserting the installer's own
        # answer keeps that one contract on every platform.
        command = next(root.iter(f"{namespace}Command")).text
        self.assertEqual(command, str(self.installer.windowless_interpreter()))
        arguments = next(root.iter(f"{namespace}Arguments")).text
        self.assertIn("kmiall_tick.py", arguments)

    def test_the_definition_still_works_where_there_is_no_pythonw(self):
        """The CI runner is Linux and has no pythonw.exe at all.

        The first version of the test above asserted an .exe suffix and went
        red in CI while passing on Windows, which is the same mistake this
        repository already recorded once for the installer test. So the
        no-pythonw case is asserted directly: the XML must still be a working
        definition that names the interpreter the installer picked.
        """
        from unittest import mock
        from xml.etree import ElementTree

        namespace = "{http://schemas.microsoft.com/windows/2004/02/mit/task}"
        with mock.patch("pathlib.Path.is_file", return_value=False):
            xml = self.installer.task_xml()
            expected = self.installer.windowless_interpreter()

        root = ElementTree.fromstring(xml)
        self.assertEqual(next(root.iter(f"{namespace}Command")).text,
                         str(expected))
        self.assertIn("kmiall_tick.py",
                      next(root.iter(f"{namespace}Arguments")).text)
        self.assertEqual(
            [node.text for node in root.iter(f"{namespace}Interval")],
            ["PT4M"] * 3)

    def test_the_written_task_file_is_utf16_for_schtasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "task.xml"
            self.installer.write_xml(target)
            raw = target.read_bytes()

        self.assertTrue(raw.startswith(b"\xff\xfe"), "schtasks wants UTF-16")

class CaptureBudgetTest(unittest.TestCase):
    """The capture must be given a budget it can meet.

    Owner report 2026-10-11, found in logs/kmiall_tick.log: on a trading day
    every tick logged "capture FAILED: capture timed out after 240s", because
    the flat limit was smaller than one sequential pass over the 319 symbol
    universe (about seven minutes). The tick now derives the budget from the
    cadence the owner fixed and reports a short pass as a short pass.
    """

    @staticmethod
    def _finished(returncode: int, stdout: str = ""):
        return subprocess.CompletedProcess([], returncode, stdout, "")

    def test_the_budget_is_the_cadence_minus_the_scan_reserve(self):
        expected = (kmiall_tick.config.TICK_INTERVAL_MINUTES * 60
                    - kmiall_tick.config.CAPTURE_BUDGET_RESERVE_SECONDS)
        self.assertEqual(kmiall_tick.capture_budget_seconds(), expected)

    def test_an_explicit_budget_wins_over_the_derived_one(self):
        with patch.object(kmiall_tick.config, "CAPTURE_BUDGET_SECONDS", 900.0):
            self.assertEqual(kmiall_tick.capture_budget_seconds(), 900.0)

    def test_the_universe_size_comes_from_the_tracked_file(self):
        self.assertGreater(kmiall_tick.universe_size(), 0)

    def test_the_capture_is_told_its_budget(self):
        # The servlet pass is the FALLBACK since owner order 2026-10-14: it is
        # asked only when no tape exists for the day, so the tape question is
        # answered False here to exercise the branch that still has a budget.
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=False), \
                patch.object(kmiall_tick.subprocess, "run",
                             return_value=self._finished(0, "banked 12 bars")) as run:
            ok, detail = kmiall_tick.run_capture()

        self.assertTrue(ok, detail)
        command = run.call_args[0][0]
        self.assertIn("--deadline-seconds", command)
        self.assertEqual(command[command.index("--deadline-seconds") + 1],
                         f"{kmiall_tick.capture_budget_seconds():.0f}")
        # The subprocess timeout is a backstop above the budget, so a pass
        # that respects its budget is never the thing that gets killed.
        self.assertEqual(
            run.call_args.kwargs["timeout"],
            kmiall_tick.capture_budget_seconds()
            + kmiall_tick.config.CAPTURE_KILL_MARGIN_SECONDS)

    def test_a_partial_pass_is_reported_with_the_arithmetic(self):
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=False), \
                patch.object(
                    kmiall_tick.subprocess, "run",
                    return_value=self._finished(
                        3, "capture pass stopped at its 195s budget")):
            ok, detail = kmiall_tick.run_capture()

        self.assertFalse(ok)
        self.assertIn("partial", detail)
        self.assertIn("budget", detail)
        self.assertIn(f"{kmiall_tick.universe_size()} symbols", detail)
        self.assertIn("cadence cannot contain", detail)

    def test_a_capture_that_ignores_its_budget_is_reported_as_killed(self):
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=False), \
                patch.object(kmiall_tick.subprocess, "run",
                             side_effect=subprocess.TimeoutExpired([], 1)):
            ok, detail = kmiall_tick.run_capture()

        self.assertFalse(ok)
        self.assertIn("killed", detail)


class TapeFirstCaptureTest(unittest.TestCase):
    """The bar source is the broker tape; the servlet is the fallback.

    Owner order 2026-10-14: the eClear OHLC servlet serves no bars, so a tick
    keeps the read-only tape alive and reports the bars it holds. Ported on
    2026-10-14, when the same order made the whole 4-minute runner cloud-only:
    these tests were written for the local tick and now hold the code path the
    owner runs himself when he asks for a local trial.
    """

    @staticmethod
    def _tape(symbols: int = 2) -> "kmiall_tick.tape_bars.TapeBars":
        minute = datetime(2026, 10, 12, 10, 5)
        bars = {
            f"SYM{i}": [kmiall_tick.tape_bars.TapeBar(minute, 10.0, 10.1, 9.9,
                                                      10.0, 500.0, 1, False)]
            for i in range(symbols)
        }
        return kmiall_tick.tape_bars.TapeBars(
            day=minute.date(), bars=bars, priced_bars=symbols, counter_rows=99,
        )

    def test_the_tape_is_the_source_and_the_servlet_is_not_asked(self):
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=True), \
                patch.object(kmiall_tick.live_card, "ensure_tape",
                             return_value=(True, "tape alive")) as ensure, \
                patch.object(kmiall_tick.tape_bars, "build",
                             return_value=self._tape()), \
                patch.object(kmiall_tick.subprocess, "run") as run:
            ok, detail = kmiall_tick.run_capture()

        self.assertTrue(ok, detail)
        self.assertIn("tape bars", detail)
        self.assertIn("2 symbol(s)", detail)
        ensure.assert_called_once()
        run.assert_not_called()

    def test_a_dead_tape_is_reported_as_a_dead_tape(self):
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=True), \
                patch.object(kmiall_tick.live_card, "ensure_tape",
                             return_value=(False, "no recorder running")), \
                patch.object(kmiall_tick.tape_bars, "build",
                             return_value=self._tape()):
            ok, detail = kmiall_tick.run_capture()

        self.assertFalse(ok)
        self.assertIn("broker tape down", detail)
        self.assertIn("no recorder running", detail)

    def test_a_live_tape_with_no_bars_is_not_a_success(self):
        empty = kmiall_tick.tape_bars.TapeBars(day=date(2026, 10, 12), bars={})
        with patch.object(kmiall_tick, "tape_capture_present",
                          return_value=True), \
                patch.object(kmiall_tick.live_card, "ensure_tape",
                             return_value=(True, "tape alive")), \
                patch.object(kmiall_tick.tape_bars, "build", return_value=empty):
            ok, detail = kmiall_tick.run_capture()

        self.assertFalse(ok)
        self.assertIn("holds no bars yet", detail)

    def test_the_universe_is_read_in_the_scanner_s_own_shape(self):
        symbols = kmiall_tick.universe_symbols()

        self.assertGreater(len(symbols), 0)
        self.assertEqual(symbols, sorted(symbols))
        self.assertTrue(all(symbol.isupper() for symbol in symbols))


class FinalizeTest(TickTestCase):
    def test_a_finalized_day_is_not_finalized_twice(self):
        # After the post-market window (15:32 to 15:49) closes, the tick
        # returns to finalize-only.
        self.fake_clock(at(MONDAY, 15, 52))
        state = self.saved_state(MONDAY)
        state.finalized = True
        state.save()
        with patch.object(pipeline, "run_finalize") as finalize:
            self.assertEqual(kmiall_tick.main([]), 0)
        finalize.assert_not_called()

    def test_post_close_finalizes_and_marks_the_day(self):
        self.fake_clock(at(MONDAY, 15, 52))
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_finalize",
                             return_value={"outcome": {"outcomes_by_rule": {
                                 "v1": {"date": MONDAY.isoformat(),
                                        "outcome": "NO_CANDIDATE",
                                        "net_return": None}},
                                 "storage_status": "relay+local"}}):
            self.assertEqual(kmiall_tick.main([]), 0)
        self.assertTrue(self.saved_state(MONDAY).finalized)

    def test_a_failing_scan_exits_3_and_releases_the_lock(self):
        self.fake_clock(at(MONDAY, 10, 7))
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", side_effect=RuntimeError("boom")):
            self.assertEqual(kmiall_tick.main([]), 3)
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
