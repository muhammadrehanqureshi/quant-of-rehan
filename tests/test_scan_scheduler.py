"""The async scan scheduler: the 4-minute grid inside the session, idle outside.

Every test drives run_scanner_schedule on a virtual clock with a recording
scanner, so a whole trading day passes without a real sleep and no socket is
ever opened: the mock scanner either returns, raises "market data API
unreachable", or hangs, and the clock only moves when the scheduler sleeps.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.scan_schedule import decide, slot_of  # noqa: E402
from src.data.scan_scheduler import (  # noqa: E402
    SchedulerConfig,
    install_signal_handlers,
    next_slot,
    run_scanner_schedule,
)
from src.data.sessions import KARACHI  # noqa: E402

MONDAY = date(2026, 10, 12)      # one band: 09:32-15:30
FRIDAY = date(2026, 10, 9)       # two bands: 09:17-12:00, 14:32-16:30
SATURDAY = date(2026, 10, 10)    # weekend: never a session

LOGGER = logging.getLogger("scan_scheduler.tests")


def setUpModule() -> None:
    # The library logs to whatever the host configured; the test host has
    # not, and logging's last resort would print every warning to stderr.
    LOGGER.addHandler(logging.NullHandler())
    LOGGER.propagate = False


def at(day: date, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second,
                    tzinfo=KARACHI)


class VirtualClock:
    """A clock and a sleep that move only when the scheduler asks.

    `after_sleep` is a hook the tests use to stop the run at a chosen
    instant; it runs after every sleep, once the clock has advanced.
    """

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.sleeps: list[float] = []
        self.after_sleep = None

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float, stop=None) -> None:
        self.sleeps.append(seconds)
        self.now = self.now + timedelta(seconds=seconds)
        if self.after_sleep is not None:
            await self.after_sleep(self)


class Recorder:
    """A scanner that records its fires and can fail or hang on demand."""

    def __init__(self, fail_on=(), hang: bool = False) -> None:
        self.calls: list[tuple[str, str, datetime]] = []
        self.fail_on = set(fail_on)
        self.hang = hang

    async def __call__(self, action: str, slot: str,
                       moment: datetime) -> None:
        self.calls.append((action, slot, moment))
        if self.hang:
            await asyncio.sleep(60)   # an API that accepts and never answers
        if len(self.calls) in self.fail_on:
            raise ConnectionError("market data API unreachable")

    def slots(self, action: str = "scan") -> list[str]:
        return [slot for act, slot, _ in self.calls if act == action]


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def run_schedule(self, scanner, clock, *, scheduler_config=None,
                           stop=None, hook=None):
        stop = stop if stop is not None else asyncio.Event()
        clock.after_sleep = hook
        report = await run_scanner_schedule(
            scanner, scheduler_config=scheduler_config or SchedulerConfig(),
            stop=stop, clock=clock, sleep=clock.sleep, logger=LOGGER)
        return report, stop

    async def test_it_fires_on_the_four_minute_grid_through_a_live_session(self):
        clock = VirtualClock(at(MONDAY, 9, 10))
        rec = Recorder()
        stop = asyncio.Event()

        async def stop_after_ten(c):
            if c.now >= at(MONDAY, 10, 11):
                stop.set()

        report, _ = await self.run_schedule(rec, clock, stop=stop,
                                            hook=stop_after_ten)

        # pre-open, then warmup, then the session's slots on the 4-min grid
        self.assertEqual(rec.slots(),
                         ["09:52", "09:56", "10:00", "10:04", "10:08"])
        self.assertTrue(all(act == "scan" for act, _, _ in rec.calls))
        self.assertEqual(report.scans, 5)
        self.assertEqual(report.pauses, 6)   # 09:10 pre-open + 5 warmup slots
        self.assertEqual(report.cycles, 11)
        self.assertEqual(report.failures, 0)
        self.assertEqual(report.exit_code, 0)
        # 09:10 -> 09:32 is ONE sleep to the open, not 35 polls; every later
        # sleep is exactly one slot boundary (high-precision, drift free).
        self.assertEqual(clock.sleeps[0],
                         (at(MONDAY, 9, 32) - at(MONDAY, 9, 10)).total_seconds())
        self.assertEqual({round(s) for s in clock.sleeps[1:]}, {240})
        # every fire carries the one true zone and its own slot label
        for _, slot, moment in rec.calls:
            self.assertEqual(moment.utcoffset(), timedelta(hours=5))
            self.assertEqual(slot, slot_of(moment))

    async def test_it_stays_idle_through_the_friday_midday_break(self):
        clock = VirtualClock(at(FRIDAY, 11, 56))
        rec = Recorder()
        stop = asyncio.Event()

        async def stop_after_break(c):
            if c.now >= at(FRIDAY, 14, 53):
                stop.set()

        report, _ = await self.run_schedule(rec, clock, stop=stop,
                                            hook=stop_after_break)

        # before the break, and after the second band's warmup: never inside
        self.assertEqual(rec.slots(), ["11:56", "14:52"])
        self.assertFalse([m for _, _, m in rec.calls
                          if at(FRIDAY, 12, 0) <= m < at(FRIDAY, 14, 32)],
                         "the exchange's midday break must never be scanned")
        self.assertFalse([m for _, _, m in rec.calls
                          if at(FRIDAY, 14, 32) <= m < at(FRIDAY, 14, 52)],
                         "the second band has its own warmup")
        # every fire is one the one schedule law allows (SO-8)
        for act, _slot, moment in rec.calls:
            self.assertEqual(decide(moment)[0], act)
        self.assertEqual(report.pauses, 43)  # 12:00..14:48, every four minutes
        self.assertEqual(report.exit_code, 0)

    async def test_it_sleeps_through_the_weekend_without_firing(self):
        clock = VirtualClock(at(SATURDAY, 10, 0))
        rec = Recorder()
        stop = asyncio.Event()

        async def stop_after_first_sleep(c):
            stop.set()

        report, _ = await self.run_schedule(rec, clock, stop=stop,
                                            hook=stop_after_first_sleep)

        self.assertEqual(rec.calls, [])      # idle: nothing outside a band
        self.assertEqual(report.pauses, 1)
        self.assertEqual(report.scans, 0)
        self.assertEqual(len(clock.sleeps), 1)   # one long sleep, not a poll
        expected = (at(MONDAY, 9, 32) - at(SATURDAY, 10, 0)).total_seconds()
        self.assertEqual(clock.sleeps[0], expected)
        self.assertEqual(report.exit_code, 0)

    async def test_an_unreachable_market_api_backs_off_and_gives_up_cleanly(self):
        clock = VirtualClock(at(MONDAY, 10, 0))
        rec = Recorder(fail_on=range(1, 6))  # every attempt raises
        cfg = SchedulerConfig(backoff_jitter=0.0)
        report, _ = await self.run_schedule(rec, clock, scheduler_config=cfg)

        self.assertEqual(len(rec.calls), 5)  # five attempts, then a clean stop
        self.assertEqual(clock.sleeps, [30.0, 60.0, 120.0, 240.0])
        self.assertEqual(report.failures, 5)
        self.assertEqual(report.consecutive_failures, 5)
        self.assertEqual(report.fault_counts, {"ConnectionError": 5})
        self.assertEqual(report.exit_code, 3)   # dead feed, not a crash

    async def test_one_success_resets_the_failure_streak(self):
        clock = VirtualClock(at(MONDAY, 10, 0))
        rec = Recorder(fail_on={1, 2, 4})
        stop = asyncio.Event()

        async def stop_after_four_calls(c):
            if len(rec.calls) >= 4:
                stop.set()

        cfg = SchedulerConfig(backoff_jitter=0.0)
        report, _ = await self.run_schedule(rec, clock, scheduler_config=cfg,
                                            stop=stop,
                                            hook=stop_after_four_calls)

        # 30 and 60 for the first two failures, 150 while the success waits
        # for the 10:04 boundary, then 30 again: the success reset the
        # streak, where an unbroken one would have asked for 480.
        self.assertEqual(clock.sleeps, [30.0, 60.0, 150.0, 30.0])
        self.assertEqual(report.scans, 1)
        self.assertEqual(report.failures, 3)
        self.assertEqual(report.consecutive_failures, 1)
        self.assertEqual(report.exit_code, 0)

    async def test_a_stop_request_ends_the_run_between_cycles(self):
        clock = VirtualClock(at(MONDAY, 10, 0))
        stop = asyncio.Event()
        rec = Recorder()

        async def scanner(action, slot, moment):
            await rec(action, slot, moment)
            stop.set()                   # the owner asked to stop mid-scan

        report, _ = await self.run_schedule(scanner, clock, stop=stop)
        self.assertEqual(len(rec.calls), 1)   # the scan in flight finished
        self.assertEqual(report.scans, 1)
        self.assertEqual(clock.sleeps, [])    # and nothing else was started
        self.assertEqual(report.exit_code, 0)

    async def test_a_hung_market_api_is_bounded_by_the_timeout(self):
        clock = VirtualClock(at(MONDAY, 10, 0))
        rec = Recorder(hang=True)
        stop = asyncio.Event()

        async def stop_after_first_sleep(c):
            stop.set()

        cfg = SchedulerConfig(scan_timeout_seconds=0.05, backoff_jitter=0.0)
        report, _ = await self.run_schedule(rec, clock, scheduler_config=cfg,
                                            stop=stop,
                                            hook=stop_after_first_sleep)

        self.assertEqual(len(rec.calls), 1)   # the hang was cancelled
        self.assertEqual(report.failures, 1)
        self.assertEqual(report.fault_counts, {"TimeoutError": 1})
        self.assertEqual(clock.sleeps, [30.0])  # one backoff, then the stop
        self.assertEqual(report.exit_code, 0)

    async def test_a_clock_from_another_zone_is_read_as_karachi(self):
        # 05:00 UTC is 10:00 in Karachi: inside the session, on the grid.
        clock = VirtualClock(datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc))
        rec = Recorder()
        cfg = SchedulerConfig(max_cycles=1)
        report, _ = await self.run_schedule(rec, clock, scheduler_config=cfg)

        self.assertEqual(report.cycles, 1)
        self.assertEqual(rec.slots(), ["10:00"])
        _action, slot, moment = rec.calls[0]
        self.assertEqual(moment.utcoffset(), timedelta(hours=5))
        self.assertEqual(moment.hour, 10)
        self.assertEqual(slot, slot_of(moment))

    async def test_it_finalizes_once_after_the_close_then_waits_for_the_open(self):
        clock = VirtualClock(at(MONDAY, 15, 40))
        rec = Recorder()
        stop = asyncio.Event()

        async def stop_after_first_sleep(c):
            stop.set()

        report, _ = await self.run_schedule(rec, clock, stop=stop,
                                            hook=stop_after_first_sleep)

        self.assertEqual(rec.calls[0][0], "finalize")  # post-market, finalize
        self.assertEqual(rec.slots("scan"), [])  # a closed day is never scanned
        self.assertEqual(report.finalizes, 1)
        self.assertEqual(report.scans, 0)
        expected = (at(date(2026, 10, 13), 9, 32)
                    - at(MONDAY, 15, 40)).total_seconds()
        self.assertEqual(clock.sleeps, [expected])   # straight to tomorrow
        self.assertEqual(report.exit_code, 0)

    def test_signal_handlers_require_a_running_loop(self):
        with self.assertRaises(RuntimeError):
            install_signal_handlers(asyncio.Event())


class NextSlotTest(unittest.TestCase):
    def test_it_lands_on_the_grid_and_always_ahead(self):
        self.assertEqual(next_slot(at(MONDAY, 10, 3)), at(MONDAY, 10, 4))
        self.assertEqual(next_slot(at(MONDAY, 10, 4)), at(MONDAY, 10, 8))
        self.assertEqual(next_slot(at(MONDAY, 10, 4, 30)), at(MONDAY, 10, 8))
        edge = at(MONDAY, 14, 59, 59)
        self.assertEqual(next_slot(edge), at(MONDAY, 15, 0))
        self.assertGreater(next_slot(edge), edge)

    def test_it_reads_other_zones_and_naive_input_as_karachi(self):
        utc_moment = at(MONDAY, 10, 3).astimezone(timezone.utc)
        self.assertEqual(next_slot(utc_moment), at(MONDAY, 10, 4))
        naive = at(MONDAY, 10, 3).replace(tzinfo=None)
        self.assertEqual(next_slot(naive), at(MONDAY, 10, 4))

    def test_it_honours_a_different_interval(self):
        self.assertEqual(next_slot(at(MONDAY, 10, 3), 5), at(MONDAY, 10, 5))


class SchedulerConfigTest(unittest.TestCase):
    def test_invalid_configuration_is_refused(self):
        bad = [
            {"interval_minutes": 0},
            {"warmup_minutes": -1},
            {"scan_timeout_seconds": -1},
            {"backoff_base_seconds": -1},
            {"backoff_base_seconds": 100, "backoff_max_seconds": 10},
            {"backoff_jitter": 1.5},
            {"max_consecutive_failures": 0},
            {"max_cycles": 0},
        ]
        for overrides in bad:
            with self.assertRaises(ValueError, msg=overrides):
                SchedulerConfig(**overrides)

    def test_backoff_is_exponential_and_capped(self):
        cfg = SchedulerConfig(backoff_jitter=0.0)
        self.assertEqual(cfg.backoff_for(0), 240.0)
        self.assertEqual(cfg.backoff_for(1), 30.0)
        self.assertEqual(cfg.backoff_for(4), 240.0)
        self.assertEqual(cfg.backoff_for(10), 900.0)  # cap, never 15360

    def test_the_default_cadence_is_the_shared_four_minutes(self):
        self.assertEqual(SchedulerConfig().interval_minutes,
                         config.TICK_INTERVAL_MINUTES)
        self.assertEqual(config.TICK_INTERVAL_MINUTES, 4)


if __name__ == "__main__":
    unittest.main()
