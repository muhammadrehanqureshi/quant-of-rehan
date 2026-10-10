#!/usr/bin/env python3
"""The local 5-minute KMIALL scanner tick (owner's own PC, Windows).

Why a tick script plus Windows Task Scheduler, and not an in-process loop:

  * an in-process loop dies with the shell that started it. This project has
    already lost a running loop to a desktop restart, and a market session that
    silently stops being scanned is exactly the failure this design exists to
    prevent;
  * Task Scheduler survives logoff, sleep and reboot, needs no terminal open,
    and its own retry/history is visible in Task Scheduler;
  * the loop's job is trivial (fire every 5 minutes), and every part that needs
    judgement -- is the market open, was this slot already scanned, did the
    capture work, is it time to finalize -- belongs in code that can be tested.
    That is this file.

What a tick does, in order:

    1. PAUSE     outside the session, before the open, or during the warm-up
                 window, the tick exits 0 immediately and says so. It never
                 scans a closed market and never scans before enough bars exist
                 to score anything.
    2. GUARD     one scan per 5-minute slot per trading day (persisted in the
                 session state), so a scheduler retry, a manual run or a laptop
                 waking from sleep cannot double-scan.
    3. LOCK      one tick at a time. A lock file holding a live pid makes a
                 concurrent tick exit 4 instead of fighting over the state file;
                 a lock older than the stale limit is reclaimed with a log line.
    4. CAPTURE   refresh the bar capture from the source. A capture failure is
                 recorded and the tick continues: the scanner then reports a
                 data failure honestly rather than a market verdict.
    5. SCAN      hand the whole job to the one orchestrator
                 (scripts/intraday_pipeline.py --scan), which does its own
                 session, coverage and one-trade-per-day enforcement.
    6. FINALIZE  after the close, value the day and write the session record
                 ONCE. A finalized day is never finalized twice.

Exit codes (Task Scheduler "last result"):

    0  healthy: scanned, finalized, or correctly paused
    2  the bar capture failed (the scan still ran and would have blocked)
    3  the scan or finalization raised
    4  another tick holds the lock

Usage:
    python scripts/kmiall_tick.py                 # one tick, what the task runs
    python scripts/kmiall_tick.py --status        # where are we right now
    python scripts/kmiall_tick.py --force         # ignore slot and finalize guards
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI, MarketPhase, market_phase, now_karachi, session_window_text,
)
from src.signals.trade_state import SessionState  # noqa: E402

LOG_FILE = ROOT / "logs" / "kmiall_tick.log"
LOCK_FILE = ROOT / "data" / "tick.lock"
HEALTH_FILE = ROOT / "data" / "tick_health.json"
UNIVERSE = ROOT / "src" / "data" / "universe_kmiall.json"

# Phase names as strings, mirroring src.data.sessions.MarketPhase (SO-8).
# Kept as module constants because the tick log and its tests read them.
PHASE_CLOSED = "CLOSED"
PHASE_PRE_OPEN = "PRE_OPEN"
PHASE_WARMUP = "WARMUP"
PHASE_OPEN = "OPEN"
PHASE_BREAK = "BREAK"
PHASE_POST_CLOSE = "POST_CLOSE"

CAPTURE_TIMEOUT = 240
ALERT_AFTER_FAILURES = 3


# ---------------------------------------------------------------------- basics

def log(message: str) -> None:
    """Append to the tick log and echo, so a manual run shows the same thing."""
    stamp = now_karachi().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp} PKT  {message}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        # A tick must never fail because its log could not be written.
        pass


def slot_of(moment: datetime) -> str:
    """The 5-minute slot a tick belongs to, floored: 10:07 -> 10:05."""
    interval = max(1, int(config.TICK_INTERVAL_MINUTES))
    minute = (moment.minute // interval) * interval
    return f"{moment.hour:02d}:{minute:02d}"


def phase_of(moment: datetime) -> str:
    """Which part of the trading day this instant is in.

    Delegates to src/data/sessions.py, the one session law (SO-8). Before
    the Friday midday break existed as a band, this function computed the
    phase from a single open/close window and therefore called the break
    OPEN, so the tick tried to scan a market that was shut.
    """
    return market_phase(moment, warmup_minutes=config.TICK_WARMUP_MINUTES).value


# ------------------------------------------------------------------------ lock

def _pid_alive(pid: int) -> bool:
    """Is this process still running? Windows-safe, no psutil dependency."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=20)
            return str(pid) in (result.stdout or "")
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(moment: datetime) -> tuple[bool, str]:
    """Claim the tick lock, reclaiming a stale one. Returns (held, detail)."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_FILE.is_file():
        try:
            held = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            held = {}
        pid = int(held.get("pid") or 0)
        started = held.get("started_iso")
        age = None
        try:
            age = (moment - datetime.fromisoformat(str(started))).total_seconds() / 60
        except (TypeError, ValueError):
            age = None
        if _pid_alive(pid) and age is not None and age < config.TICK_STALE_LOCK_MINUTES:
            return False, f"pid {pid} has held the lock for {age:.1f} minutes"
        log(f"reclaiming lock from pid {pid} (age {age} min, alive "
            f"{_pid_alive(pid)})")
    LOCK_FILE.write_text(json.dumps({
        "pid": os.getpid(),
        "started_iso": moment.isoformat(timespec="seconds"),
        "slot": slot_of(moment),
    }, indent=1), encoding="utf-8")
    return True, f"lock acquired by pid {os.getpid()}"


def release_lock() -> None:
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


# --------------------------------------------------------------------- capture

def run_capture() -> tuple[bool, str]:
    """Refresh the bar capture. Never raises: a failure is data, not a crash."""
    command = [sys.executable, "-m", "src.data.ohlc_poller",
               "--symbols-file", str(UNIVERSE.relative_to(ROOT)), "--once"]
    try:
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                text=True, timeout=CAPTURE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, f"capture timed out after {CAPTURE_TIMEOUT}s"
    except OSError as exc:
        return False, f"capture could not start: {type(exc).__name__}: {exc}"
    tail = (result.stdout or result.stderr or "").strip().splitlines()[-3:]
    detail = " | ".join(line.strip() for line in tail if line.strip())
    if result.returncode != 0:
        return False, f"capture exit {result.returncode}: {detail}"
    return True, detail or "capture ok"


def read_health() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_health(ok: bool, detail: str) -> dict:
    """Record capture health and alert once when it starts failing repeatedly.

    The alert fires exactly at the threshold, not every failure after it, so a
    broken feed produces one message rather than one every five minutes.
    """
    health = read_health()
    failures = 0 if ok else int(health.get("consecutive_failures") or 0) + 1
    health.update({
        "last_check": now_karachi().isoformat(timespec="seconds"),
        "last_ok": ok,
        "last_detail": detail,
        "consecutive_failures": failures,
    })
    if ok:
        health["last_success"] = health["last_check"]
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
    if not ok and failures == ALERT_AFTER_FAILURES:
        try:
            from scripts import intraday_pipeline as pipeline

            pipeline.deliver(
                f"KMIALL local tick: bar capture has failed {failures} times "
                f"in a row.\nLast error: {detail}\nThe scanner will report a "
                f"data failure until the feed recovers.", "ops")
            log(f"ops alert sent after {failures} capture failures")
        except Exception as exc:  # noqa: BLE001 - an alert is best effort
            log(f"ops alert failed: {type(exc).__name__}")
    return health


# ------------------------------------------------------------------------ main

def status_line(moment: datetime) -> str:
    state = SessionState.load(moment.date())
    return (f"phase={phase_of(moment)} slot={slot_of(moment)} "
            f"day={state.day} state={state.state} scans={state.scans} "
            f"trades={state.trades_today} last_tick={state.last_tick_slot} "
            f"finalized={state.finalized}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local 5-minute KMIALL tick")
    parser.add_argument("--force", action="store_true",
                        help="ignore the slot and finalize guards")
    parser.add_argument("--status", action="store_true",
                        help="describe the current phase and state, then stop")
    parser.add_argument("--skip-capture", action="store_true",
                        help="scan the capture already on disk")
    args = parser.parse_args(argv)

    moment = now_karachi()
    if args.status:
        print(status_line(moment))
        return 0

    log(f"tick start: {status_line(moment)}")
    phase = phase_of(moment)
    if phase in (PHASE_CLOSED, PHASE_PRE_OPEN, PHASE_WARMUP, PHASE_BREAK):
        reason = {
            PHASE_CLOSED: "not a PSX trading day (weekend or holiday)",
            PHASE_PRE_OPEN: "before the session open",
            PHASE_WARMUP: (f"inside the first {config.TICK_WARMUP_MINUTES:g} "
                           f"minutes after the open; not enough bars yet"),
            PHASE_BREAK: ("the exchange is in its midday break "
                          f"(today {session_window_text(moment.date())})"),
        }[phase]
        log(f"paused: {reason}. nothing scanned.")
        return 0

    state = SessionState.load(moment.date())
    slot = slot_of(moment)

    if phase == PHASE_POST_CLOSE:
        if state.finalized and not args.force:
            log("day already finalized; nothing to do")
            return 0
        return _finalize(moment, args.skip_capture)

    if state.claimed_slot(slot) and not args.force:
        log(f"slot {slot} already scanned today; skipping this tick")
        return 0

    held, detail = acquire_lock(moment)
    if not held:
        log(f"refusing to run: {detail}")
        return 4
    try:
        capture_ok, capture_detail = (True, "capture skipped by flag")
        if not args.skip_capture:
            capture_ok, capture_detail = run_capture()
            note_health(capture_ok, capture_detail)
            log(f"capture {'ok' if capture_ok else 'FAILED'}: {capture_detail}")

        from scripts import intraday_pipeline as pipeline

        payload = pipeline.run_scan(slot)
        state = SessionState.load(moment.date())
        state.note_tick(slot)
        state.save()
        log(f"scan done: status={payload.get('status')} "
            f"reason={str(payload.get('reason'))[:160]}")
        return 0 if capture_ok else 2
    except Exception as exc:  # noqa: BLE001 - reported, then non-zero exit
        log(f"scan FAILED: {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return 3
    finally:
        release_lock()


def _finalize(moment: datetime, skip_capture: bool) -> int:
    held, detail = acquire_lock(moment)
    if not held:
        log(f"refusing to finalize: {detail}")
        return 4
    try:
        capture_ok, capture_detail = (True, "capture skipped by flag")
        if not skip_capture:
            capture_ok, capture_detail = run_capture()
            note_health(capture_ok, capture_detail)
            log(f"finalize capture {'ok' if capture_ok else 'FAILED'}: "
                f"{capture_detail}")
        from scripts import intraday_pipeline as pipeline

        result = pipeline.run_finalize()
        outcome = result.get("outcome", {}).get("outcomes_by_rule", {})
        for record in outcome.values():
            log(f"finalized {record.get('date')}: outcome="
                f"{record.get('outcome')} net={record.get('net_return')} "
                f"storage={result.get('outcome', {}).get('storage_status')}")
        state = SessionState.load(moment.date())
        state.finalized = True
        state.save()
        return 0 if capture_ok else 2
    except Exception as exc:  # noqa: BLE001 - reported, then non-zero exit
        log(f"finalize FAILED: {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return 3
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
