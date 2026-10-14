#!/usr/bin/env python3
"""The supervised scan loop: one process, interval scans, typed outcomes.

Rebuild 2026-10-10. This is the second supported way to drive the ONE
orchestrator, next to the Windows 4-minute tick:

    tick       scripts/kmiall_tick.py + Task Scheduler   (a local trial)
    loop       scripts/scan_loop.py --loop               (supervises itself)

Since the owner's order of 2026-10-14 (SO-13) the loop is also the cloud's
runner: `.github/workflows/intraday-session.yml` starts it for the length of
each PSX band at a 30 second interval, and one scan serves both the phone's
card and the intraday paper strategy. That cadence is only possible because
the loop keeps the read-only broker tape alive instead of fetching per cycle:
a cycle measures a bar series that already exists (2.9s measured on the real
2026-10-13 session tape: 44.6 MB, 314 symbols, 56,618 rows).

Same scanner, same state machine, same one-trade-per-day lock. The loop exists
for hosts where Task Scheduler does not exist (a Linux VM, a container, a
laptop run in the foreground during development) and for anyone who wants one
process whose retry policy is visible in one file. It never reimplements
strategy: every scan is delegated to scripts/intraday_pipeline.py, and every
session decision is delegated to src/data/sessions.py.

What the loop is responsible for:

  * SCHEDULING   wake on a fixed interval with drift correction, so a slow scan
                 does not push every later scan late;
  * PAUSING      outside the session, before the open, in the warm-up window
                 and after a finalize, it sleeps instead of scanning;
  * BACKOFF      consecutive failures raise an exponential delay with jitter,
                 capped by config, and one success resets it. A dead feed does
                 not become a hot loop;
  * ISOLATION    a failure is classified with the typed fault taxonomy from
                 src/signals/contracts.py, logged with its class, and never
                 reported as a market verdict;
  * STATE        a health file (JSON) with the last cycle, fault counts and the
                 consecutive-failure streak, plus structured logs to file and
                 stdout;
  * SHUTDOWN     SIGINT and SIGTERM stop the loop cleanly between cycles, never
                 mid-scan, and always release the lock.

Usage:
    python scripts/scan_loop.py --once                 # one cycle, then exit
    python scripts/scan_loop.py --loop                 # run until stopped
    python scripts/scan_loop.py --loop --interval 30   # the cloud cadence (SO-13)
    python scripts/scan_loop.py --loop --interval 240  # 4 minutes (local trial)
    python scripts/scan_loop.py --dry-run --loop       # decide, never scan
    python scripts/scan_loop.py --status               # print loop health
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.ci.local_only import guard_owner_requested  # noqa: E402
from src.data import tape_bars  # noqa: E402
from src.data.sessions import (  # noqa: E402
    next_open, now_karachi, session_window_text,
)

# The one pause table and slot clock, shared with scripts/kmiall_tick.py, so
# the tick and this loop cannot disagree about when the exchange is tradeable.
from src.data.scan_schedule import (  # noqa: E402
    decide, phase_of, slot_of,
)

# The capture's own budget: the poller owns its pacing and its pass estimate,
# so the loop asks for a budget instead of setting a timeout of its own.
from src.data.ohlc_poller import (  # noqa: E402
    EXIT_PASS_INCOMPLETE,
    capture_budget_seconds as budget_for_cadence,
)
from src.signals.contracts import (  # noqa: E402
    ScanFault, ScanOutcome, Verdict, verdict_from_status,
)
from src.signals.trade_state import SessionState  # noqa: E402

LOG_FILE = ROOT / "logs" / "scan_loop.log"
HEALTH_FILE = ROOT / "data" / "scan_loop_health.json"

# Phase names come from src/data/scan_schedule.py, the one schedule law
# (SO-8); this loop no longer keeps its own copies of them.

LOGGER = logging.getLogger("scan_loop")


# --------------------------------------------------------------------- config

@dataclass(frozen=True)
class LoopConfig:
    """Everything the loop's behaviour depends on, in one typed place."""

    # Owner order 2026-10-14 (SO-13): scan the whole KMIALL universe every 30
    # seconds for the session, and the same scan serves the phone's card and
    # the intraday paper strategy. The local 4 minute tick keeps its own
    # TICK_INTERVAL_MINUTES; this loop is the cloud session runner.
    interval_seconds: float = config.SCAN_INTERVAL_SECONDS
    warmup_minutes: float = 20.0
    max_consecutive_failures: int = 5
    backoff_base_seconds: float = 30.0
    backoff_max_seconds: float = 900.0
    backoff_jitter: float = 0.25
    max_cycles: int | None = None
    dry_run: bool = False
    capture: bool = True
    #: Seconds the capture may spend. 0 means "derive it from interval_seconds
    #: minus the reserve the scan needs" (see capture_budget_seconds in
    #: src/data/ohlc_poller.py). A positive value is used as given.
    capture_deadline_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if self.backoff_base_seconds <= 0 or self.backoff_max_seconds <= 0:
            raise ValueError("backoff bounds must be positive")
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("backoff base cannot exceed the backoff cap")
        if not 0.0 <= self.backoff_jitter < 1.0:
            raise ValueError("backoff_jitter must be within [0, 1)")
        if self.max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be at least 1")

    def backoff_for(self, failures: int, rng: random.Random | None = None) -> float:
        """Delay after N consecutive failures, with jitter, capped."""
        if failures <= 0:
            return self.interval_seconds
        raw = min(self.backoff_max_seconds,
                  self.backoff_base_seconds * (2 ** (failures - 1)))
        if self.backoff_jitter:
            spread = raw * self.backoff_jitter
            raw = raw - spread / 2 + (rng or random).random() * spread
        return max(0.0, min(raw, self.backoff_max_seconds))

    def should_keep_going(self, failures: int) -> bool:
        """The streak that ends the loop instead of retrying for ever."""
        return failures < self.max_consecutive_failures


# ---------------------------------------------------------------- clock logic
# phase_of and slot_of are imported from src/data/scan_schedule.py, the one
# schedule law this loop shares with the local tick (SO-8). This module used to
# derive the phase itself from a single open/close window, which made the
# Friday midday break look like OPEN and put the loop to work on a shut market.


# -------------------------------------------------------------------- logging

def configure_logging(log_file: Path | None = None) -> None:
    """Structured, timestamped logging to stdout and a file.

    The scanner itself prints for humans; this loop logs for operators, which
    is why it uses the stdlib logging module rather than more prints. It is
    idempotent so a second call does not duplicate handlers.

    The file resolves at call time rather than as a bound default, so a
    caller that points LOG_FILE elsewhere is obeyed. Bound at import time it
    could not be redirected, and the first test that called run() or main()
    appended its synthetic verdicts to the live logs/scan_loop.log.
    """
    log_file = LOG_FILE if log_file is None else log_file
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    LOGGER.addHandler(stream)
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handle = logging.FileHandler(log_file, encoding="utf-8")
        handle.setFormatter(fmt)
        LOGGER.addHandler(handle)
    except OSError as exc:  # a loop must not die because it cannot log
        LOGGER.warning("file logging unavailable: %s", type(exc).__name__)


# --------------------------------------------------------------------- health

@dataclass
class LoopHealth:
    """What the loop has done, and how badly it has been failing."""

    started_at: str = ""
    last_cycle_at: str = ""
    last_slot: str = ""
    last_phase: str = ""
    last_verdict: str = ""
    last_reason: str = ""
    last_latency_ms: float | None = None
    cycles: int = 0
    scans: int = 0
    pauses: int = 0
    failures: int = 0
    consecutive_failures: int = 0
    fault_counts: dict[str, int] = field(default_factory=dict)
    stopped_at: str = ""

    def note_fault(self, fault: ScanFault) -> None:
        name = type(fault).__name__
        self.fault_counts[name] = self.fault_counts.get(name, 0) + 1
        self.failures += 1
        self.consecutive_failures += 1

    def note_success(self) -> None:
        self.consecutive_failures = 0

    def as_dict(self) -> dict:
        return {
            **{k: v for k, v in self.__dict__.items()},
            "fault_counts": dict(self.fault_counts),
        }

    def save(self, path: Path = HEALTH_FILE) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(self.as_dict(), indent=2),
                            encoding="utf-8")
        except OSError as exc:
            LOGGER.warning("could not write health file: %s", type(exc).__name__)

    @classmethod
    def load(cls, path: Path = HEALTH_FILE) -> "LoopHealth":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})


# ----------------------------------------------------------------- the loop

class ScanLoop:
    """One supervised process that scans on an interval inside the session."""

    def __init__(self, loop_config: LoopConfig | None = None,
                 *, health_path: Path = HEALTH_FILE,
                 clock=now_karachi, rng: random.Random | None = None) -> None:
        self.config = loop_config or LoopConfig()
        self.health_path = health_path
        self.clock = clock
        self.rng = rng or random.Random(20261010)
        self.health = LoopHealth()
        self._stopping = False
        self._sleeping = False

    # ---- lifecycle -----------------------------------------------------
    def request_stop(self, signum: int | None = None,
                     frame: FrameType | None = None) -> None:
        """Stop between cycles. Never interrupts a scan in flight."""
        self._stopping = True
        LOGGER.info("stop requested (signal %s); finishing the current cycle",
                    signum)

    def install_signal_handlers(self) -> None:
        for name in ("SIGINT", "SIGTERM"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                signal.signal(number, self.request_stop)
            except (ValueError, OSError):  # not the main thread: fine
                LOGGER.debug("could not install handler for %s", name)

    # ---- decisions -----------------------------------------------------
    def decide(self, moment: datetime) -> tuple[str, str]:
        """What this cycle should do, as (action, detail).

        Actions: scan, finalize, or wait. Delegates to
        src/data/scan_schedule.py, which is the one pause table this loop and
        the local 4-minute tick both read, so the owner's pre-market and
        post-market never-scan rules and the Friday midday break are decided
        in exactly one place. Pure and clock-injected, so the decision table
        is testable without sleeping.
        """
        return decide(moment, self.config.warmup_minutes)

    def next_delay(self, action: str) -> float:
        """Seconds to sleep after this cycle.

        A completed finalize ends the day: sleep until the next session rather
        than spinning on a closed market.
        """
        if action == "finalize":
            moment = self.clock()
            # Sleep to the next band start, which may be tomorrow or after a
            # weekend or a holiday (sessions.next_open is band aware).
            nxt = next_open(moment)
            return max(self.config.interval_seconds,
                       (nxt - moment).total_seconds())
        return self.config.interval_seconds

    # ---- one cycle -----------------------------------------------------
    def run_cycle(self) -> tuple[str, ScanOutcome | None]:
        """Run exactly one cycle. Returns (action, typed outcome or None)."""
        moment = self.clock()
        action, detail = self.decide(moment)
        slot = slot_of(moment, interval_seconds=self.config.interval_seconds)
        started = time.perf_counter()
        self.health.cycles += 1
        self.health.last_cycle_at = moment.isoformat(timespec="seconds")
        self.health.last_phase = phase_of(moment, self.config.warmup_minutes)
        self.health.last_slot = slot

        if action == "wait":
            self.health.pauses += 1
            LOGGER.info("cycle %d: waiting (%s)", self.health.cycles, detail)
            self.health.save(self.health_path)
            return action, None

        if self.config.dry_run:
            LOGGER.info("cycle %d: dry run would %s at %s (%s)",
                        self.health.cycles, action, slot, detail)
            self.health.save(self.health_path)
            return action, None

        outcome: ScanOutcome | None = None
        fault: ScanFault | None = None
        try:
            outcome = self._execute(action, slot, moment)
        except ScanFault as fault:
            self.health.note_fault(fault)
            LOGGER.warning("cycle %d: %s class=%s retryable=%s detail=%s",
                           self.health.cycles, action, type(fault).__name__,
                           fault.retryable, fault.detail)
            self.health.last_verdict = "FAULT"
            self.health.last_reason = fault.detail
        except Exception as exc:  # noqa: BLE001 - classified, then re-decided
            fault = ScanFault(f"{type(exc).__name__}: {exc}")
            self.health.note_fault(fault)
            LOGGER.error("cycle %d: unexpected failure: %s\n%s",
                         self.health.cycles, exc, traceback.format_exc())
            self.health.last_verdict = "FAULT"
            self.health.last_reason = str(exc)
        else:
            self.health.note_success()
            self.health.last_verdict = outcome.verdict.value
            self.health.last_reason = outcome.reason
            fault = outcome.fault()
            if fault is not None:
                self.health.note_fault(fault)
            LOGGER.info("cycle %d: %s latency=%.0fms focus=%s",
                        self.health.cycles, outcome.summary(),
                        outcome.latency_ms or 0.0,
                        outcome.candidate.symbol if outcome.candidate else "-")

        self.health.last_latency_ms = round(
            (time.perf_counter() - started) * 1000, 1)
        if outcome is not None and action == "scan":
            self.health.scans += 1
        self.health.save(self.health_path)
        return action, outcome

    def _execute(self, action: str, slot: str,
                 moment: datetime) -> ScanOutcome:
        """Delegate to the ONE orchestrator and adapt its result."""
        if self.config.capture and not self._capture():
            raise ScanFault("bar capture failed before the scan")

        from scripts import intraday_pipeline as pipeline

        started = time.perf_counter()
        if action == "finalize":
            state = SessionState.load(moment.date())
            if state.finalized:
                LOGGER.info("day already finalized; nothing to do")
                return ScanOutcome(
                    as_of=moment, slot=slot, verdict=Verdict.FINALIZED,
                    reason="the trading day is already finalized",
                    scanner_version=config.SCANNER_VERSION,
                    latency_ms=(time.perf_counter() - started) * 1000)
            result = pipeline.run_finalize()
            outcome = result.get("outcome", {})
            records = list((outcome.get("outcomes_by_rule") or {}).values())
            return ScanOutcome(
                as_of=moment, slot=slot, verdict=Verdict.FINALIZED,
                reason=(f"finalized {len(records)} session record(s); storage "
                        f"{outcome.get('storage_status')}"),
                scanner_version=config.SCANNER_VERSION,
                latency_ms=(time.perf_counter() - started) * 1000,
                delivered="FINALIZE")

        payload = pipeline.run_scan(slot)
        return self._adapt(payload, moment, started)

    def _adapt(self, payload: dict, moment: datetime,
               started: float) -> ScanOutcome:
        """Copy the orchestrator's payload into the typed contract."""
        status = str(payload.get("status", "")).upper()
        quality_payload = payload.get("data_quality") or {}
        from src.signals.contracts import DataQuality, as_quality

        quality = DataQuality(
            status=as_quality(quality_payload.get("status", "OK")),
            reason=str(quality_payload.get("reason", "")),
            coverage=float(quality_payload.get("coverage", 0.0)),
            fresh_coverage=float(quality_payload.get("fresh_coverage", 0.0)),
            symbols_expected=int(quality_payload.get("symbols_expected", 0)),
            symbols_with_bars=int(quality_payload.get("symbols_with_bars", 0)),
            volume_available=bool(quality_payload.get("volume_available", False)),
            malformed_bars=int(quality_payload.get("malformed_bars", 0)),
            duplicate_bars=int(quality_payload.get("duplicate_bars", 0)),
            impossible_ohlc=int(quality_payload.get("impossible_ohlc", 0)),
            data_age_minutes=quality_payload.get("data_age_minutes"),
            resolution=str(quality_payload.get("resolution", "1-minute")),
            source=str(quality_payload.get("source", "")),
        )
        # The orchestrator reports a scanner verdict, or a trade-state name
        # once the day is locked (TARGET_MONITORING and friends). Reading the
        # latter as an aborted scan would count a healthy cycle as a fault.
        verdict = verdict_from_status(status) or Verdict.ABORTED
        candidate = payload.get("candidate")
        return ScanOutcome(
            as_of=moment, slot=str(payload.get("slot", "")), verdict=verdict,
            reason=str(payload.get("reason", "")), quality=quality,
            candidate=(None if candidate is None
                       else _candidate(candidate)),
            eligible_count=int(payload.get("eligible_count", 0) or 0),
            coverage_text=str(payload.get("coverage_text", "")),
            universe_size=int(payload.get("universe_size", 0) or 0),
            universe_sha256=payload.get("universe_sha256"),
            scanner_version=str(payload.get("scanner_version", "")),
            ai_active=bool((payload.get("ai") or {}).get("active", False)),
            latency_ms=(time.perf_counter() - started) * 1000,
            delivered=payload.get("delivered"),
        )

    def _capture(self) -> bool:
        """Keep the session's bar source alive. A failure is a classified fault.

        Owner order 2026-10-14: the bar source is the broker tape, so the
        question a cycle asks is not "did a fetch finish" but "is the tape
        alive, and does it hold bars for this session". The read-only recorder
        is kept alive for the whole session (src/data/live_card.py), which is
        what makes a 30 second cadence possible at all: the bars already
        exist, and one cycle costs about three seconds on the largest real
        session tape (44.6 MB, 314 symbols). A thin tape is reported through
        the same capture-health flag the ops alert reads, never padded.

        The bounded eClear OHLC pass survives only for a day with no tape at
        all, which is the same fallback the local tick uses.
        """
        from src.data import live_card

        moment = now_karachi()
        # Ask for the session's recorder FIRST, then decide the source. On a
        # fresh runner the day's tape file does not exist yet, and deciding
        # from an empty directory sent every cycle to the dead servlet, whose
        # pass cannot fit a 30 second cadence: measured live 2026-10-14, five
        # consecutive faults and a loop that gave up without recording a bar.
        alive, note = live_card.ensure_tape(moment)
        if alive or tape_bars.capture_path(moment.date()).is_file():
            return self._tape_capture(moment, alive, note)
        LOGGER.warning("no recorder and no tape for %s: trying the servlet "
                       "fallback (%s)", moment.date().isoformat(), note)
        return self._poller_capture(moment)

    def _tape_capture(self, moment: datetime, alive: bool, note: str) -> bool:
        """The bar source: a live tape, measured rather than assumed."""
        from scripts.intraday_pipeline import load_kmiall

        symbols = load_kmiall()
        tape = tape_bars.build(tape_bars.capture_path(moment.date()), symbols,
                               moment)
        if not alive:
            raise ScanFault(f"broker tape down: {note}")
        if tape.symbols_with_bars == 0:
            raise ScanFault(f"the tape is alive but holds no bars yet: {note}")
        flag = tape_bars.write_low_coverage_flag(
            tape, len(symbols),
            cause=(f"the tape held bars for {tape.symbols_with_bars} of "
                   f"{len(symbols)} KMIALL symbols at "
                   f"{moment:%Y-%m-%d %H:%M} PKT"))
        LOGGER.info(
            "tape: %d symbol(s), %d bar(s) (%d carried), counter on %d row(s), "
            "health flag %s | %s",
            tape.symbols_with_bars, tape.priced_bars + tape.carried_bars,
            tape.carried_bars, tape.counter_rows,
            flag.name if flag else "not raised", note)
        return True

    def _poller_capture(self, moment: datetime) -> bool:
        """The fallback: one bounded pass over the eClear OHLC servlet.

        Used only when the day has no tape at all. The pass is given this
        loop's own budget, derived from its cadence unless
        LoopConfig.capture_deadline_seconds names one, so it stops cleanly and
        reports a partial pass instead of being killed at a subprocess timeout
        the pass could never meet.
        """
        import subprocess

        # A sweep of the whole universe is what a servlet pass is, so it gets
        # the cadence the pass actually needs rather than this runner's own 30
        # seconds: handed 30 seconds it stops incomplete on every cycle, which
        # is a fault the fallback cannot ever pass.
        budget = self.config.capture_deadline_seconds or budget_for_cadence(
            max(self.config.interval_seconds,
                config.TICK_INTERVAL_MINUTES * 60.0))
        kill_after = budget + config.CAPTURE_KILL_MARGIN_SECONDS
        command = [sys.executable, "-m", "src.data.ohlc_poller",
                   "--symbols-file", str((ROOT / "src" / "data" /
                                          "universe_kmiall.json")
                                         .relative_to(ROOT)), "--once",
                   "--deadline-seconds", f"{budget:.0f}"]
        try:
            result = subprocess.run(
                command, cwd=str(ROOT), capture_output=True, text=True,
                timeout=kill_after)
        except subprocess.TimeoutExpired as exc:
            raise ScanFault(
                f"capture ignored its {budget:.0f}s budget and was killed "
                f"after {kill_after:.0f}s") from exc
        except OSError as exc:
            raise ScanFault(f"capture could not start: {type(exc).__name__}") from exc
        if result.returncode == EXIT_PASS_INCOMPLETE:
            raise ScanFault(
                f"capture stopped at its {budget:.0f}s budget: a partial pass "
                f"(the cadence cannot contain a full one)")
        if result.returncode != 0:
            tail = (result.stderr or result.stdout or "").strip().splitlines()
            raise ScanFault(
                f"capture exited {result.returncode}: "
                f"{tail[-1].strip() if tail else 'no output'}")
        return True

    # ---- driver --------------------------------------------------------
    def run(self, max_cycles: int | None = None) -> int:
        """Run the loop until stopped, the cycle cap is hit, or it gives up."""
        configure_logging()
        self.install_signal_handlers()
        limit = max_cycles if max_cycles is not None else self.config.max_cycles
        self.health.started_at = self.clock().isoformat(timespec="seconds")
        LOGGER.info("loop starting: interval=%gs warmup=%gmin window=%s dry_run=%s",
                    self.config.interval_seconds, self.config.warmup_minutes,
                    _window_text(self.clock()), self.config.dry_run)
        try:
            while not self._stopping:
                if limit is not None and self.health.cycles >= limit:
                    LOGGER.info("cycle cap %d reached; stopping", limit)
                    break
                action, _ = self.run_cycle()
                if self._stopping:
                    break
                if not self.config.should_keep_going(
                        self.health.consecutive_failures):
                    LOGGER.error(
                        "%d consecutive failures (%s); stopping rather than "
                        "retrying into a dead feed",
                        self.health.consecutive_failures,
                        self.health.fault_counts)
                    self.health.stopped_at = self.clock().isoformat(timespec="seconds")
                    self.health.save(self.health_path)
                    return 3
                delay = (self.config.backoff_for(
                    self.health.consecutive_failures, self.rng)
                    if self.health.consecutive_failures
                    else self.next_delay(action))
                LOGGER.info("sleeping %.0fs (failures=%d, action=%s)",
                            delay, self.health.consecutive_failures, action)
                self._sleep(delay)
        finally:
            self.health.stopped_at = self.clock().isoformat(timespec="seconds")
            self.health.save(self.health_path)
            LOGGER.info("loop stopped after %d cycles", self.health.cycles)
        return 0

    def _sleep(self, seconds: float) -> None:
        """Sleep in bounded slices so a stop request is honoured promptly."""
        deadline = time.monotonic() + seconds
        while not self._stopping:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 1.0))


def _candidate(row: dict):
    from src.signals.contracts import candidate_from_row

    return candidate_from_row(row)


def _window_text(moment: datetime) -> str:
    """The day's bands, break included, from the one session law (SO-8)."""
    return session_window_text(moment.date()) + " PKT"


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="supervised interval scan loop")
    parser.add_argument("--loop", action="store_true",
                        help="keep running (default is a single cycle)")
    parser.add_argument("--once", action="store_true", help="one cycle (default)")
    parser.add_argument("--interval", type=float,
                        default=config.SCAN_INTERVAL_SECONDS,
                        help="seconds between cycles (owner order: 30)")
    parser.add_argument("--warmup", type=float, default=config.TICK_WARMUP_MINUTES,
                        help="minutes after the open before the first scan")
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-failures", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true",
                        help="decide and log, but never capture or scan")
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--status", action="store_true",
                        help="print the health file and the current decision")
    args = parser.parse_args(argv)

    loop_config = LoopConfig(
        interval_seconds=args.interval, warmup_minutes=args.warmup,
        max_cycles=args.max_cycles,
        max_consecutive_failures=args.max_failures,
        dry_run=args.dry_run, capture=not args.skip_capture,
    )
    configure_logging()
    loop = ScanLoop(loop_config)

    if args.status:
        health = LoopHealth.load()
        moment = now_karachi()
        action, detail = loop.decide(moment)
        print(json.dumps({
            "now": moment.isoformat(timespec="seconds"),
            "phase": phase_of(moment, loop_config.warmup_minutes),
            "window": _window_text(moment),
            "would_do": action, "why": detail,
            "interval_seconds": loop_config.interval_seconds,
            "health": health.as_dict(),
        }, indent=2))
        return 0

    if args.loop:
        return loop.run()

    action, outcome = loop.run_cycle()
    if outcome is not None:
        print(outcome.summary())
    else:
        print(f"{action}: {loop.decide(now_karachi())[1]}")
    return 0 if loop.health.consecutive_failures == 0 else 1


if __name__ == "__main__":
    # SO-12 (owner order 2026-10-14): a supervised loop that sleeps between
    # scans is the definition of the resident workload the owner forbade on
    # his PC. Cloud minutes carry it now; a local process is refused unless
    # the owner asked for this exact run.
    guard_owner_requested("scripts/scan_loop.py")
    raise SystemExit(main())
