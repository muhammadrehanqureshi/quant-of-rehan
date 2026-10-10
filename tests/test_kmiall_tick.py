"""The local 5-minute tick: pause, guard, lock, capture failure, finalize.

Nothing here touches the network, the real relay or the owner's real
data/forward directory: the session state root is redirected to a temporary
directory and the pipeline entry points are patched.
"""

from __future__ import annotations

import json
import os
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
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 7)), "10:05")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 5)), "10:05")
        self.assertEqual(kmiall_tick.slot_of(at(MONDAY, 10, 59)), "10:55")


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
        state.note_tick("10:05")
        state.save()
        self.fake_clock(moment)
        with patch.object(pipeline, "run_scan") as scan:
            self.assertEqual(kmiall_tick.main([]), 0)
        scan.assert_not_called()

    def test_force_rescans_the_slot(self):
        moment = at(MONDAY, 10, 7)
        state = self.saved_state(MONDAY)
        state.note_tick("10:05")
        state.save()
        self.fake_clock(moment)
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", return_value={"status": "NO_TRADE"}) as scan:
            self.assertEqual(kmiall_tick.main(["--force"]), 0)
        scan.assert_called_once_with("10:05")


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

    def test_a_successful_tick_records_the_slot(self):
        moment = at(MONDAY, 10, 7)
        self.fake_clock(moment)
        with patch.object(kmiall_tick, "run_capture", return_value=(True, "ok")), \
                patch.object(pipeline, "run_scan", return_value={"status": "NO_TRADE"}):
            self.assertEqual(kmiall_tick.main([]), 0)
        self.assertEqual(self.saved_state(MONDAY).last_tick_slot, "10:05")


class FinalizeTest(TickTestCase):
    def test_a_finalized_day_is_not_finalized_twice(self):
        self.fake_clock(at(MONDAY, 15, 40))
        state = self.saved_state(MONDAY)
        state.finalized = True
        state.save()
        with patch.object(pipeline, "run_finalize") as finalize:
            self.assertEqual(kmiall_tick.main([]), 0)
        finalize.assert_not_called()

    def test_post_close_finalizes_and_marks_the_day(self):
        self.fake_clock(at(MONDAY, 15, 40))
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
