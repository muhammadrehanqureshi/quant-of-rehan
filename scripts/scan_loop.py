#!/usr/bin/env python3
"""The supervised scan loop: one process, interval scans, typed outcomes.

Rebuild 2026-10-10. This is the second supported way to drive the ONE
orchestrator, next to the Windows 5-minute tick:

    tick       scripts/kmiall_tick.py + Task Scheduler   (survives reboots)
    loop       scripts/scan_loop.py --loop               (supervises itself)

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
    python scripts/scan_loop.py --loop --interval 300  # 5 minutes
    python scripts/scan_loop.py --dry-run --loop       # decide, never scan
    python scripts/scan_loop.py --status               # print loop health
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI, MarketPhase, market_phase, next_open, now_karachi,
    session_window_text,
)
from src.signals import ai_model  # noqa: E402
from src.signals.contracts import (  # noqa: E402
    ScanFault, ScanOutcome, Verdict, verdict_from_status,
)
from src.signals.trade_state import SessionState  # noqa: E402

LOG_FILE = ROOT / "logs" / "scan_loop.log"
HEALTH_FILE = ROOT / "data" / "scan_loop_health.json"

# Phase names as strings, mirroring src.data.sessions.MarketPhase (SO-8).
PHASE_CLOSED = "CLOSED"
PHASE_PRE_OPEN = "PRE_OPEN"
PHASE_WARMUP = "WARMUP"
PHASE_OPEN = "OPEN"
PHASE_BREAK = "BREAK"
PHASE_POST_CLOSE = "POST_CLOSE"

LOGGER = logging.getLogger("scan_loop")


# --------------------------------------------------------------------- config

@dataclass(frozen=True)
class LoopConfig:
    """Everything the loop's behaviour depends on, in one typed place."""

    interval_seconds: float = 300.0
    warmup_minutes: float = 20.0
    max_consecutive_failures: int = 5
    backoff_base_seconds: float = 30.0
    backoff_max_seconds: float = 900.0
    backoff_jitter: float = 0.25
    max_cycles: int | None = None
    dry_run: bool = False
    capture: bool = True
    capture_timeout_seconds: float = 240.0

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

def phase_of(moment: datetime, warmup_minutes: float = 20.0) -> str:
    """Which part of the trading day this instant is in.

    One session law, in src/data/sessions.py (SO-8). This used to derive
    the phase from a single open/close window, which made the Friday
    midday break look like OPEN and put the loop to work on a shut market.
    """
    return market_phase(moment, warmup_minutes=warmup_minutes).value


def slot_of(moment: datetime, interval_minutes: int | None = None) -> str:
    """The slot label for this cycle, floored to the configured interval."""
    step = max(1, int(interval_minutes
                      if interval_minutes is not None
                      else config.TICK_INTERVAL_MINUTES))
    minute = (moment.minute // step) * step
    return f"{moment.hour:02d}:{minute:02d}"


# -------------------------------------------------------------------- logging

def configure_logging(log_file: Path = LOG_FILE) -> None:
    """Structured, timestamped logging to stdout and a file.

    The scanner itself prints for humans; this loop logs for operators, which
    is why it uses the stdlib logging module rather than more prints. It is
    idempotent so a second call does not duplicate handlers.
    """
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

        Actions: scan, finalize, or wait. Pure and clock-injected, so the
        decision table is testable without sleeping.
        """
        phase = phase_of(moment, self.config.warmup_minutes)
        if phase in (PHASE_CLOSED, PHASE_PRE_OPEN):
            return "wait", (f"{phase}: {session_window_text(moment.date())}")
        if phase == PHASE_WARMUP:
            return "wait", (f"{phase}: first {self.config.warmup_minutes:g} "
                            f"minutes after the open")
        if phase == PHASE_BREAK:
            return "wait", (f"{phase}: the exchange's midday break; "
                            f"today {session_window_text(moment.date())}")
        if phase == PHASE_OPEN:
            return "scan", f"{phase}: inside the session"
        return "finalize", f"{phase}: the session has closed"

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
        slot = slot_of(moment)
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
        """Refresh the bar capture. A failure is a classified fault."""
        import subprocess

        command = [sys.executable, "-m", "src.data.ohlc_poller",
                   "--symbols-file", str((ROOT / "src" / "data" /
                                          "universe_kmiall.json")
                                         .relative_to(ROOT)), "--once"]
        try:
            result = subprocess.run(
                command, cwd=str(ROOT), capture_output=True, text=True,
                timeout=self.config.capture_timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise ScanFault(
                f"capture timed out after {self.config.capture_timeout_seconds:g}s"
            ) from exc
        except OSError as exc:
            raise ScanFault(f"capture could not start: {type(exc).__name__}") from exc
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
                        default=config.TICK_INTERVAL_MINUTES * 60,
                        help="seconds between cycles")
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
    raise SystemExit(main())
