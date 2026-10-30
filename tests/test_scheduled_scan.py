"""The 4-minute schedule driving the REAL pipeline on simulated market data.

This is the test the refactor had to have: not a scheduler firing a mock, and
not a pipeline run once by hand, but the two together, with the schedule
running on a virtual clock and a tape that grows the way a real recorder's
does.

What it holds in place, and why each part is here:

  * THE GRID.  A fire belongs to a 4-minute slot, and it happens AT the slot
    boundary rather than at "the last fire plus four minutes". A scan that
    takes nine seconds of a 240 second slot must not push every later fire
    nine seconds late, and the slot label the observation carries must be the
    slot the fire actually worked in (src/data/scan_scheduler.next_slot, which
    scripts/scan_loop.py now sleeps to as well, so both cadences sit on one
    grid).

  * A REAL SIGNAL, FROM SIMULATED BARS.  The scanner callback is
    scripts.intraday_pipeline.run_scan itself, the same function the cloud job
    runs, reading a synthetic capture written in the MKT-FEED tape's shape. A
    market that is genuinely moving must produce a TRADE through the real
    gates, the real ranking and the real one-trade-per-day lock, not a mock
    verdict.

  * A YOUNG CAPTURE IS A COUNTDOWN, NOT A FAULT.  The tape starts empty at the
    band's open, exactly as a recorder's does, so the first fires hold fewer
    than the 20 bars the strategy needs. Measured 2026-10-14, that state used
    to be counted as a coverage fault (86 of them in one band), which made a
    working tape read as a dead feed. Here it must pause, and the first real
    scan must follow on its own once the bars exist.

  * NO NETWORK, NO REAL SESSION STATE.  The relay, the clock and the forward
    directory are all patched, so the suite never touches the owner's live
    files or a real signal card (the same discipline
    tests/test_pipeline_paper_cycle.py uses for the scheduled cycle).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.scan_schedule import slot_of  # noqa: E402
from src.data.scan_scheduler import (  # noqa: E402
    SchedulerConfig,
    next_slot,
    run_scanner_schedule,
)
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import trade_state  # noqa: E402
from scripts import intraday_pipeline as pipeline  # noqa: E402

# A Monday: one band, 09:32 to 15:30, so the schedule has a single open to
# work from and the assertions do not have to know about Friday's split.
MONDAY = date(2026, 10, 12)
OPEN_AT = datetime.combine(MONDAY, __import__("datetime").time(*open_time(MONDAY)),
                           tzinfo=KARACHI)
WINNER = "OGDC"
INTERVAL_MINUTES = 4


def _universe() -> list[str]:
    universe = json.loads((ROOT / "src" / "data" / "universe_kmiall.json")
                          .read_text(encoding="utf-8"))
    return [row["symbol"].strip().upper() for row in universe]


from kalman_fixture import setup_values


class GrowingTape:
    """A capture that grows a minute at a time, like the recorder's own file.

    A test that writes the whole session up front cannot tell a warm-up from a
    stale tape: every cycle would see the full day. This one appends only the
    minutes that have passed by the instant it is asked for, so the bar source
    really is younger than the bars it is asked to hold at the start.
    """

    def __init__(self, path: Path, symbols: list[str]) -> None:
        self.path = path
        self.symbols = symbols
        self._totals = {sym: 0.0 for sym in symbols}
        self._minutes = 0

    def advance_to(self, moment: datetime) -> None:
        """Append one row per symbol for every minute up to `moment`."""
        minutes = int((moment - OPEN_AT).total_seconds() // 60)
        if minutes <= self._minutes:
            return
        with self.path.open("a", encoding="utf-8") as handle:
            for minute in range(self._minutes, max(0, minutes)):
                for symbol in self.symbols:
                    op, hi, lo, close, volume = (setup_values(minute - 1) if symbol == WINNER
                                               else (100, 100.01, 99.99, 100, 5000))
                    for second, price in zip((0, 10, 20, 50), (op, hi, lo, close)):
                        self._totals[symbol] += volume // 4
                        stamp = OPEN_AT + timedelta(minutes=minute, seconds=second)
                        handle.write(json.dumps({"kind": "MKT-FEED|SUB%", "ts": stamp.isoformat(),
                            "ticks": [{"scrip": f"{symbol}:REG", "last": str(price),
                                       "volume": str(int(self._totals[symbol])),
                                       "tick_time": stamp.strftime("%H:%M:%S"),
                                       "trades": str(minute * 4 + second + 1)}]}) + "\n")
        self._minutes = minutes


class VirtualClock:
    """A clock that only moves when the scheduler sleeps."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    async def sleep(self, seconds: float, stop=None) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class ScheduledScanTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        root = Path(self._dir.name)
        self.tape = GrowingTape(root / "tape.ndjson", _universe())

        # The pipeline writes the observation, the session lock and the gate
        # into trade_state.ROOT, so redirecting it there keeps the owner's real
        # forward files untouched.
        state_patcher = patch.object(trade_state, "ROOT", root)
        state_patcher.start()
        self.addCleanup(state_patcher.stop)
        self.forward = root / "data" / "forward"
        self.before = {p.name: p.read_bytes()
                       for p in sorted((ROOT / "data" / "forward").glob("*"))
                       if p.is_file()}

        # No network: every relay call is answered locally and recorded, with
        # the one route whose answer the pipeline reads as a decision: the
        # day's signal claim is the shared once-per-day lock, so the stand-in
        # answers it the way the relay does ({"claimed": bool}) instead of a
        # bare ok, which the pipeline would read as a refusal.
        self.calls: list[tuple] = []

        def relay(method, route, payload=None):
            self.calls.append((method, route, payload))
            if route == "/research/claim":
                return {"ok": True, "claimed": True}
            return {"ok": True}

        relay_patcher = patch.object(pipeline, "relay_request", relay)
        relay_patcher.start()
        self.addCleanup(relay_patcher.stop)

        # The pipeline dates the session from its own clock, so it reads the
        # virtual one, the same instant the scheduler is working at.
        #: Every verdict the schedule actually produced, in order.
        self.statuses: list[str] = []
        self.clock = VirtualClock(OPEN_AT)
        clock_patcher = patch.object(pipeline, "now_karachi", self.clock)
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)

    # ---- the scanner callback, exactly as a runner wires it ------------
    def scan_once(self, action: str, slot: str, moment: datetime) -> dict:
        """One scheduled fire: grow the tape, then run the real orchestrator."""
        self.tape.advance_to(moment)
        with contextlib.redirect_stdout(io.StringIO()):
            return pipeline.run_scan(slot, self.tape.path)

    async def run_schedule(self, *, stop_after: datetime, warmup: float = 0.0,
                           failures: list | None = None):
        """Drive the schedule on the virtual clock, recording every fire.

        The stop request is raised from inside the sleep, which is the one
        place the run touches the world: the schedule then reaches `stop_after`
        exactly and the test never waits in real time.
        """
        fires: list[tuple[str, str, datetime]] = []
        stop = asyncio.Event()

        async def scanner_callback(action: str, slot: str,
                                   moment: datetime) -> None:
            fires.append((action, slot, moment))
            payload = self.scan_once(action, slot, moment)
            self.statuses.append(str(payload.get("status", "")))
            quality = payload.get("data_quality") or {}
            if failures is None:
                return
            if quality.get("warming_up"):
                failures.append("warming_up")
            elif quality.get("status") == "DATA_BLOCKED":
                failures.append(quality.get("reason", ""))

        async def sleep(seconds: float, _stop=None) -> None:
            self.clock.now = self.clock.now + timedelta(seconds=seconds)
            if self.clock.now >= stop_after:
                stop.set()

        scheduler_config = SchedulerConfig(
            interval_minutes=INTERVAL_MINUTES, warmup_minutes=warmup,
            max_cycles=60)
        report = await run_scanner_schedule(
            scanner_callback, scheduler_config=scheduler_config, stop=stop,
            clock=self.clock, sleep=sleep)
        return report, fires

    async def test_it_fires_on_the_grid_and_turns_bars_into_a_signal(self):
        # A recorder that starts with the band: the first fire is one minute
        # into it, which is off the four minute grid on purpose (a mid-slot
        # start works at once and joins the grid from the next fire on).
        self.clock_start = OPEN_AT + timedelta(minutes=1)
        self.clock.now = self.clock_start
        report, fires = await self.run_schedule(
            stop_after=OPEN_AT + timedelta(minutes=52))

        scans = [(slot, moment) for action, slot, moment in fires
                 if action == "scan"]
        self.assertTrue(scans, "the schedule never scanned")

        # A runner that starts mid-slot works at once and then joins the grid:
        # the first fire is the instant it started, and every fire after it is
        # an absolute four minute boundary, never "the last one plus four".
        self.assertEqual(scans[0][1], self.clock_start)
        self.assertEqual(scans, sorted(scans, key=lambda item: item[1]))
        for slot, moment in scans[1:]:
            self.assertEqual(moment.second, 0)
            self.assertEqual(moment.minute % INTERVAL_MINUTES, 0)
        for (_, earlier), (_, later) in zip(scans[1:], scans[2:]):
            self.assertEqual(later - earlier,
                             timedelta(minutes=INTERVAL_MINUTES))

        # Every fire's slot label is the slot that fire belongs to, so a slow
        # cycle can never report a slot it did not work in.
        for slot, moment in scans:
            self.assertEqual(slot, slot_of(moment,
                                           interval_minutes=INTERVAL_MINUTES))

        # The virtual clock stopped where the test asked, so the schedule ran
        # the whole window without a real sleep.
        self.assertGreaterEqual(self.clock.now, OPEN_AT + timedelta(minutes=52))
        self.assertGreater(report.scans, 0)
        self.assertEqual(report.failures, 0)

        # A real signal, from simulated bars, through the real pipeline: the
        # verdicts themselves are the proof, not the report's counters.
        self.assertIn(scanner.TRADE, self.statuses,
                      f"no fire produced a signal: {self.statuses}")
        entry = self.statuses.index(scanner.TRADE)
        locked = self.statuses[entry + 1:]
        self.assertTrue(locked, "the schedule stopped at the entry")
        for status in locked:
            # One trade a day: after the entry the day can only be monitored,
            # and a taken trade is never reported as a market NO TRADE.
            self.assertIn(status, ("TARGET_MONITORING", "DAILY_LOCKED"),
                          self.statuses)
        self.assertNotIn(scanner.NO_TRADE, locked)

        state = json.loads((self.forward / "session_state.json")
                           .read_text(encoding="utf-8"))
        self.assertEqual(state["trades_today"], 1)
        self.assertEqual(state["symbol"], WINNER)

        alerts = [payload["signals"] for _, route, payload in self.calls
                  if route == "/signals" and "INTRADAY ALERT" in payload["signals"]]
        self.assertTrue(alerts, "the entry never reached the app card as an alert")
        self.assertIn(WINNER, alerts[0])

        observation = json.loads((self.forward / "observation.json")
                                 .read_text(encoding="utf-8"))
        self.assertEqual(observation["trade_state"]["trades_today"], 1)
        self.assertFalse(observation["data_quality"]["warming_up"])

    async def test_a_young_tape_warms_up_instead_of_faulting(self):
        """The first fires hold too few bars; none of them is a failure."""
        self.clock_start = OPEN_AT + timedelta(minutes=4)   # on the grid
        self.clock.now = self.clock_start
        failures: list = []
        report, fires = await self.run_schedule(
            stop_after=OPEN_AT + timedelta(minutes=32), failures=failures)

        warmups = [entry for entry in failures if entry == "warming_up"]
        self.assertTrue(warmups, "a young tape did not report a warm-up")
        blocks = [entry for entry in failures if entry != "warming_up"]
        self.assertEqual(blocks, [], f"a young tape was reported as a data "
                                     f"failure: {blocks}")
        self.assertEqual(report.failures, 0,
                         "a warming-up cycle was counted as a fault")

        # The scan resumes by itself once the bars exist: after the 20 bars
        # MIN_BARS_PER_SYMBOL needs, the pipeline renders a market verdict
        # rather than another block.
        self.assertGreaterEqual(self.clock.now,
                                OPEN_AT + timedelta(minutes=20))
        observation = json.loads((self.forward / "observation.json")
                                 .read_text(encoding="utf-8"))
        self.assertIn(observation["status"], (scanner.TRADE, scanner.NO_TRADE))
        self.assertFalse(observation["data_quality"]["warming_up"])

        # The owner's own forward files were never touched by this run.
        after = {p.name: p.read_bytes()
                 for p in sorted((ROOT / "data" / "forward").glob("*"))
                 if p.is_file()}
        self.assertEqual(self.before, after)

    async def test_a_dead_bar_source_gives_up_rather_than_spinning(self):
        """Five consecutive failures end the run with exit code 3."""
        calls: list = []

        async def broken(action: str, slot: str, moment: datetime) -> None:
            calls.append(moment)
            raise ConnectionError("market data API unreachable")

        self.clock.now = OPEN_AT + timedelta(minutes=1)
        report = await run_scanner_schedule(
            broken, scheduler_config=SchedulerConfig(
                interval_minutes=INTERVAL_MINUTES, warmup_minutes=0.0,
                backoff_base_seconds=1.0, backoff_max_seconds=4.0,
                max_consecutive_failures=5),
            stop=asyncio.Event(), clock=self.clock, sleep=self.clock.sleep)

        self.assertEqual(report.exit_code, 3)
        self.assertEqual(report.failures, 5)
        self.assertEqual(len(calls), 5)
        self.assertIn("ConnectionError", report.fault_counts)


class GridTest(unittest.TestCase):
    """The grid itself, without a scheduler: pure and clock-free."""

    def test_next_slot_is_the_next_boundary_not_the_interval(self):
        four = next_slot(datetime(2026, 10, 12, 10, 5, 30, tzinfo=KARACHI),
                         interval_minutes=4)
        self.assertEqual(four.strftime("%H:%M:%S"), "10:08:00")

        at_boundary = next_slot(datetime(2026, 10, 12, 10, 8, tzinfo=KARACHI),
                                interval_minutes=4)
        self.assertEqual(at_boundary.strftime("%H:%M:%S"), "10:12:00")

        # The configured cadence since 2026-10-19 is one second, so the next
        # boundary is the next second, not the next half minute.
        cadence = next_slot(datetime(2026, 10, 12, 10, 7, 31, tzinfo=KARACHI),
                            interval_seconds=config.SCAN_INTERVAL_SECONDS)
        self.assertEqual(cadence.strftime("%H:%M:%S"), "10:07:32")
        self.assertEqual(config.SCAN_INTERVAL_SECONDS, 1)
        # The sub-minute grid itself still rounds up to its own boundary.
        half = next_slot(datetime(2026, 10, 12, 10, 7, 31, tzinfo=KARACHI),
                         interval_seconds=30)
        self.assertEqual(half.strftime("%H:%M:%S"), "10:08:00")
        at_half = next_slot(datetime(2026, 10, 12, 10, 7, 30, tzinfo=KARACHI),
                            interval_seconds=30)
        self.assertEqual(at_half.strftime("%H:%M:%S"), "10:08:00")

    def test_a_naive_or_utc_instant_is_read_as_karachi(self):
        naive = next_slot(datetime(2026, 10, 12, 10, 0), interval_minutes=4)
        self.assertEqual(naive.strftime("%H:%M:%S"), "10:04:00")
        self.assertEqual(naive.utcoffset(), timedelta(hours=5))

        utc = next_slot(datetime(2026, 10, 12, 5, 0, tzinfo=timezone.utc),
                        interval_minutes=4)
        self.assertEqual(utc.strftime("%H:%M:%S"), "10:04:00")


if __name__ == "__main__":
    unittest.main()
