"""The async scan scheduler: every 4 minutes while PSX trades, idle otherwise.

Refactor of 2026-10-14. Until now the *scheduled* runner existed only as five
GitHub Actions crons (SCHEDULE_PLAN in src/data/session_gate.py, mirrored in
.github/workflows/intraday-capture.yml): five scans a day, by budget. This
module is the long-running alternative: an asyncio scheduler that wakes on the
4-minute grid (config.TICK_INTERVAL_MINUTES) for as long as the session law
says the exchange is trading, and sleeps through every break, weekend,
holiday and pre/post-market window.

One authority per question (SO-8). The scheduler decides nothing itself:

    src/data/scan_schedule.py   what may happen here: scan, finalize, wait
    src/data/sessions.py        the law: bands, warmup, holidays, next_open
    src/config.py               the cadence: TICK_INTERVAL_MINUTES = 4

Why not exchange_calendars (the obvious third-party market-hours library)?
It does ship an XKAR Pakistan calendar, but adding it would create a second
authority on PSX hours next to src/data/sessions.py, which every runner, the
relay and the phone app already read (SO-8), and no third-party calendar
knows this system's own rules: the owner's 09:32 band starts, the Friday
split sessions, the 20 minute warmup, or the pre-market and post-market
never-scan orders of 2026-10-11. requirements.txt is deliberately four
lines and CI installs exactly it (SO-4), so the library would also be a new
dependency for a question this repo already answers in one tested place.

Why asyncio and not APScheduler: the stdlib needs no dependency, the loop is
a single coroutine with absolute wake targets, and every input is injectable
(clock, sleep, stop, scanner), which is what makes the mock test in
tests/test_scan_scheduler.py run a whole session without sleeping.

Wake rules, first match wins (decided fresh from the law every cycle):

    wait + CLOSED/PRE_OPEN ....... sleep to sessions.next_open: one long
                                   sleep over the weekend or the pre-market,
                                   no polling, no sockets
    wait + WARMUP/BREAK .......... sleep to the next 4-minute slot boundary
    scan ......................... fire, then sleep to the next slot boundary
    finalize ..................... fire, then sleep to next_open (the day's
                                   scans are done; never spin on a closed day)
    the scanner raised ........... exponential backoff with jitter, retry;
                                   give up cleanly after N failures in a row

Timing precision: every wake target is an absolute Asia/Karachi instant and
the wait re-checks the clock until it is reached, so a slow or over-long
scan never drifts the grid (the 10:04 slot stays 10:04) and an early wake
just sleeps the remainder again. A fire therefore belongs to exactly one
slot, and two fires can never claim the same slot in this process.

Timezones: the zone is the one fixed SO-8 offset, UTC+5 (Asia/Karachi has no
DST, so a fixed offset is the whole truth). The injected clock may return
naive, UTC or local instants; every one is normalised through
sessions.as_karachi before the law, the slot label or the scanner sees it.

Errors: the scanner contract is "raise to fail". A dead or unreachable
market-data API therefore becomes a typed, counted failure with a backoff
delay instead of an exception that kills the loop; max_consecutive_failures
in a row stops the scheduler with exit code 3, the same dead-feed stance as
scripts/scan_loop.py. A hung API is bounded by scan_timeout_seconds when one
is configured.

One grid, two runners. `next_slot` is the grid itself, and it is used twice:
this module sleeps to it, and scripts/scan_loop.py sleeps to it as well
(`--loop`, the cloud's own mode), so a 4 minute fire and a 30 second fire can
never sit on two different grids. `scripts/scan_loop.py --scheduled` goes
further and hands this scheduler the whole schedule, calling back into the
loop's cycle body for each fire; the loop then owns what a cycle does and this
module owns when it runs and how it retries.

Shutdown: pass an asyncio.Event as `stop`; it is honoured between cycles and
inside every wait, so a stop request finishes the current scan and returns a
report. install_signal_handlers wires SIGINT and SIGTERM to that event for
callers running the scheduler as a process (call it from inside the running
loop, which is where an asyncio.Event may install handlers).

Usage::

    async def main() -> None:
        stop = asyncio.Event()
        install_signal_handlers(stop)
        report = await run_scanner_schedule(scanner, stop=stop)
        return report.exit_code
"""

from __future__ import annotations

import asyncio
import logging
import random
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src import config
from src.data.scan_schedule import (
    ACTION_SCAN,
    ACTION_WAIT,
    PHASE_CLOSED,
    PHASE_PRE_OPEN,
    decide,
    phase_of,
    slot_of,
)
from src.data.sessions import as_karachi, next_open, now_karachi

LOGGER = logging.getLogger("scan_scheduler")

#: Wait phases whose next useful instant is the next band start: sleeping to
#: the next 4-minute slot through a weekend would be a pointless poll.
IDLE_TO_OPEN = frozenset({PHASE_CLOSED, PHASE_PRE_OPEN})

#: What the scheduler calls: (action, slot, moment). Raise to report failure.
ScanFunc = Callable[[str, str, datetime], Awaitable[None]]

#: How the scheduler sleeps: seconds, and the stop event to honour meanwhile.
SleepFunc = Callable[[float, asyncio.Event], Awaitable[None]]


@dataclass(frozen=True)
class SchedulerConfig:
    """Everything the scheduler's behaviour depends on, in one typed place."""

    interval_minutes: float = config.TICK_INTERVAL_MINUTES
    warmup_minutes: float = config.TICK_WARMUP_MINUTES
    #: 0 disables the wrapper; a positive value bounds one scanner call.
    scan_timeout_seconds: float = 0.0
    backoff_base_seconds: float = 30.0
    backoff_max_seconds: float = 900.0
    backoff_jitter: float = 0.25
    max_consecutive_failures: int = 5
    max_cycles: int | None = None

    def __post_init__(self) -> None:
        if self.interval_minutes <= 0:
            raise ValueError("interval_minutes must be positive")
        if self.warmup_minutes < 0:
            raise ValueError("warmup_minutes cannot be negative")
        if self.scan_timeout_seconds < 0:
            raise ValueError("scan_timeout_seconds cannot be negative")
        if self.backoff_base_seconds <= 0 or self.backoff_max_seconds <= 0:
            raise ValueError("backoff bounds must be positive")
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("backoff base cannot exceed the backoff cap")
        if not 0.0 <= self.backoff_jitter < 1.0:
            raise ValueError("backoff_jitter must be within [0, 1)")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")
        if self.max_cycles is not None and self.max_cycles < 1:
            raise ValueError("max_cycles must be at least 1 when set")

    def backoff_for(self, failures: int,
                    rng: random.Random | None = None) -> float:
        """Delay after N consecutive failures, with jitter, capped."""
        if failures <= 0:
            return self.interval_minutes * 60.0
        raw = min(self.backoff_max_seconds,
                  self.backoff_base_seconds * (2 ** (failures - 1)))
        if self.backoff_jitter:
            spread = raw * self.backoff_jitter
            raw = raw - spread / 2 + (rng or random).random() * spread
        return max(0.0, min(raw, self.backoff_max_seconds))


@dataclass
class SchedulerReport:
    """What the scheduler did before it stopped, and why."""

    started_at: str = ""
    stopped_at: str = ""
    cycles: int = 0
    scans: int = 0
    finalizes: int = 0
    pauses: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    fault_counts: dict[str, int] = field(default_factory=dict)
    last_action: str = ""
    last_reason: str = ""
    exit_code: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def next_slot(moment: datetime,
              interval_minutes: float | None = None,
              interval_seconds: float | None = None) -> datetime:
    """The next grid boundary strictly after `moment`, on the slot grid.

    Pure and zone-pinning: the input may be naive (read as Karachi), UTC or
    any other zone; the result is always an Asia/Karachi instant on the same
    grid `scan_schedule.slot_of` labels, so a runner that sleeps to this
    instant wakes exactly when the next slot begins, and the slot label it
    reports is the slot it actually worked in. At a boundary already, the
    answer is the following boundary.

    Seconds are accepted because the cloud runs a 30 second cadence (owner
    order 2026-10-14, SO-13) and the grid has to be the same one for both
    cadences: the arithmetic is a day-relative second grid, which for whole
    minute intervals lands on the whole minute labels the tick has always
    used. `timedelta` does the modulo, so it also applies to the epoch-looking
    float result of a fractional step without any rounding of its own.
    """
    if interval_seconds is not None:
        step_seconds = max(1.0, float(interval_seconds))
    elif interval_minutes is not None:
        step_seconds = max(1.0, float(interval_minutes) * 60.0)
    else:
        step_seconds = max(1.0, float(config.TICK_INTERVAL_MINUTES) * 60.0)
    step = timedelta(seconds=step_seconds)
    k = as_karachi(moment)
    midnight = datetime(k.year, k.month, k.day, tzinfo=k.tzinfo)
    into = (k - midnight) % step
    delta = (step - into) if into else step
    return k + delta


async def _sleep(seconds: float, stop: asyncio.Event) -> None:
    """Sleep `seconds`, waking early when `stop` is set."""
    if seconds <= 0:
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _wait_until(target: datetime, *, clock: Callable[[], datetime],
                      sleep: SleepFunc, stop: asyncio.Event) -> None:
    """Wait for the absolute instant `target`, re-checking the clock.

    The loop is the drift correction: a wake that lands early (coarse timer,
    wall clock versus monotonic) just sleeps the remainder again, so the
    scheduler reaches every target boundary and never a hair before it.
    A stop request ends the wait immediately.
    """
    while not stop.is_set():
        remaining = (target - clock()).total_seconds()
        if remaining <= 0:
            return
        await sleep(remaining, stop)


def install_signal_handlers(stop: asyncio.Event) -> None:
    """Make SIGINT and SIGTERM set `stop`, so the loop ends between cycles.

    Uses the event loop's own handlers where the platform has them (any
    Unix), and falls back to signal.signal elsewhere (Windows). Like
    scripts/scan_loop.py, a stop request never interrupts a scan in flight.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError("install_signal_handlers needs a running loop") from None
    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, stop.set)
            continue
        except (NotImplementedError, RuntimeError, ValueError):
            pass
        try:
            signal.signal(sig, lambda *_args: stop.set())
        except (ValueError, OSError):  # not the main thread: fine
            continue


async def run_scanner_schedule(
    scanner: ScanFunc,
    *,
    scheduler_config: SchedulerConfig | None = None,
    stop: asyncio.Event | None = None,
    clock: Callable[[], datetime] = now_karachi,
    sleep: SleepFunc | None = None,
    rng: random.Random | None = None,
    logger: logging.Logger | None = None,
) -> SchedulerReport:
    """Run the 4-minute schedule until stopped, capped, or the feed dies.

    `scanner(action, slot, moment)` is the injected work: await it and the
    fire succeeded, raise and it failed (an unreachable market-data API is
    exactly that raise). `clock` and `sleep` are injectable so tests drive a
    whole session on a virtual clock without real waiting. `stop` ends the
    run cleanly between cycles. The returned SchedulerReport carries the
    counters and the exit code: 0 for a stopped or capped run, 3 when
    max_consecutive_failures gave up on a dead feed.
    """
    cfg = scheduler_config or SchedulerConfig()
    stop_event = stop if stop is not None else asyncio.Event()
    log = logger or LOGGER
    sleep_fn = sleep if sleep is not None else _sleep

    def clock_karachi() -> datetime:
        # Every instant is normalised before the law, the slot label or the
        # scanner may see it: the injected clock is free to be in any zone.
        return as_karachi(clock())

    report = SchedulerReport(started_at=clock_karachi()
                             .isoformat(timespec="seconds"))
    consecutive = 0

    while not stop_event.is_set():
        if cfg.max_cycles is not None and report.cycles >= cfg.max_cycles:
            break
        moment = clock_karachi()
        action, reason = decide(moment, cfg.warmup_minutes)
        slot = slot_of(moment, cfg.interval_minutes)
        report.cycles += 1
        report.last_action = action
        report.last_reason = reason

        if action == ACTION_WAIT:
            report.pauses += 1
            phase = phase_of(moment, cfg.warmup_minutes)
            if phase in IDLE_TO_OPEN:
                target = next_open(moment)
            else:
                target = next_slot(moment, cfg.interval_minutes)
            log.info("cycle %d: waiting at %s (%s); waking at %s",
                     report.cycles, moment.strftime("%H:%M"), reason,
                     target.strftime("%H:%M:%S"))
            await _wait_until(target, clock=clock_karachi,
                              sleep=sleep_fn, stop=stop_event)
            continue

        try:
            call = scanner(action, slot, moment)
            if cfg.scan_timeout_seconds > 0:
                await asyncio.wait_for(call, cfg.scan_timeout_seconds)
            else:
                await call
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - counted, backed off, reported
            consecutive += 1
            report.failures += 1
            report.consecutive_failures = consecutive
            name = type(exc).__name__
            report.fault_counts[name] = report.fault_counts.get(name, 0) + 1
            log.warning("cycle %d: %s failed at slot %s (%s: %s); "
                        "consecutive=%d", report.cycles, action, slot,
                        name, exc, consecutive)
            if consecutive >= cfg.max_consecutive_failures:
                log.error("%d consecutive failures; stopping rather than "
                          "retrying into a dead feed (%s)",
                          consecutive, report.fault_counts)
                report.exit_code = 3
                report.stopped_at = clock_karachi().isoformat(
                    timespec="seconds")
                return report
            delay = cfg.backoff_for(consecutive, rng)
            retry_at = clock_karachi() + timedelta(seconds=delay)
            await _wait_until(retry_at, clock=clock_karachi,
                              sleep=sleep_fn, stop=stop_event)
            continue

        consecutive = 0
        report.consecutive_failures = 0
        if action == ACTION_SCAN:
            report.scans += 1
            target = next_slot(moment, cfg.interval_minutes)
        else:
            report.finalizes += 1
            target = next_open(moment)
        log.info("cycle %d: %s ok at slot %s (%s)", report.cycles, action,
                 slot, reason)
        await _wait_until(target, clock=clock_karachi,
                          sleep=sleep_fn, stop=stop_event)

    report.stopped_at = clock_karachi().isoformat(timespec="seconds")
    return report
