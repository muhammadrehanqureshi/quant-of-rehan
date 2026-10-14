#!/usr/bin/env python3
"""The local 4-minute KMIALL scanner tick (owner's own PC, Windows).

Why a tick script plus Windows Task Scheduler, and not an in-process loop:

  * an in-process loop dies with the shell that started it. This project has
    already lost a running loop to a desktop restart, and a market session that
    silently stops being scanned is exactly the failure this design exists to
    prevent;
  * Task Scheduler survives logoff, sleep and reboot, needs no terminal open,
    and its own retry/history is visible in Task Scheduler;
  * the loop's job is trivial (fire every 4 minutes, the owner's standing
    order of 2026-10-11), and every part that needs judgement -- which market
    state is this, was this slot already scanned, did the capture work, is it
    time to finalize -- belongs in code that can be tested. That is this file.

What a tick does, in order:

    1. PAUSE     outside the session, in the pre-market window, before the
                 open, or during the warm-up window, the tick exits 0
                 immediately and says so. It never scans a closed market,
                 never scans pre-market or post-market (owner order
                 2026-10-11) and never scans before enough bars exist to score
                 anything. Post-market is finalize-only.
    2. GUARD     one scan per 4-minute slot per trading day (persisted in the
                 session state), so a scheduler retry, a manual run or a laptop
                 waking from sleep cannot double-scan.
    3. LOCK      one tick at a time. A lock file holding a live pid makes a
                 concurrent tick exit 4 instead of fighting over the state file;
                 a lock older than the stale limit is reclaimed with a log line.
    4. CAPTURE   refresh the bars. The bar source is the broker tape (owner
                 order 2026-10-14): the tick keeps that read-only recorder
                 alive and measures the bars it holds, falling back to the
                 eClear OHLC servlet only when no tape exists for the day. A
                 capture failure is recorded and the tick continues: the
                 scanner then reports a data failure honestly rather than a
                 market verdict.
    5. SCAN      hand the whole job to the one orchestrator
                 (scripts/intraday_pipeline.py --scan), which does its own
                 session, coverage and one-trade-per-day enforcement.
    6. CARD      keep the phone's market card real (src/data/live_card.py of
                 the owner's order of 2026-10-12): the broker trade tape is
                 kept alive for the session, so the card's buy/sell split
                 comes from the day's own trades, and the rebuilt card is
                 pushed to the relay the phone reads. Best effort both ways:
                 a card problem never turns a scan into a failure.
    7. FINALIZE  after the close, value the day and write the session record
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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.ci.local_only import guard_owner_requested  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402
from src.data import scan_schedule  # noqa: E402

# One pause table and one slot clock, shared with scripts/scan_loop.py. The
# tick used to carry its own copy of the phase check, which is how the Friday
# midday break and the owner's pre-market and post-market never-scan rules
# came to exist twice (see src/data/scan_schedule.py).
from src.data.scan_schedule import (  # noqa: E402
    ACTION_FINALIZE,
    ACTION_WAIT,
    decide,
    phase_of,
    slot_of,
    state_of,
)

# The capture owns its own pacing and pass estimate, so the tick asks the
# poller how long a pass needs rather than guessing a timeout of its own.
from src.data.ohlc_poller import (  # noqa: E402
    EXIT_PASS_INCOMPLETE,
    capture_budget_seconds as budget_for_cadence,
    nominal_pass_seconds,
)
from src.data import live_card  # noqa: E402
from src.data import tape_bars  # noqa: E402
from src.signals.trade_state import SessionState  # noqa: E402

LOG_FILE = ROOT / "logs" / "kmiall_tick.log"
LOCK_FILE = ROOT / "data" / "tick.lock"
HEALTH_FILE = ROOT / "data" / "tick_health.json"
UNIVERSE = ROOT / "src" / "data" / "universe_kmiall.json"

# Phase names as strings, re-exported from the one schedule law (SO-8) so the
# tick log and its tests keep reading them here. A tick scans only in MARKET;
# PRE_MARKET is logged and skipped, POST_MARKET is finalize-only.
PHASE_CLOSED = scan_schedule.PHASE_CLOSED
PHASE_PRE_OPEN = scan_schedule.PHASE_PRE_OPEN
PHASE_WARMUP = scan_schedule.PHASE_WARMUP
PHASE_OPEN = scan_schedule.PHASE_OPEN
PHASE_BREAK = scan_schedule.PHASE_BREAK
PHASE_POST_CLOSE = scan_schedule.PHASE_POST_CLOSE

#: Alert at the third consecutive capture failure, then once per Karachi day
#: while the failure continues (owner order 2026-10-12, the zero-defect law):
#: one message when the feed breaks, and one reminder a day so an outage that
#: lasts a session, a weekend or a vendor holiday cannot go quiet.
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

def universe_size() -> int:
    """How many symbols the tracked KMIALL universe holds (0 if unreadable)."""
    return len(universe_symbols())


def universe_symbols() -> list[str]:
    """The tracked KMIALL symbols, in the same shape the scanner reads."""
    try:
        payload = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return sorted({
        str(row["symbol"]).strip().upper() for row in payload
        if isinstance(row, dict) and row.get("symbol")
        and "KMIALLSHR" in (row.get("listedIn") or [])
    })


def tape_capture_present(moment: datetime | None = None) -> bool:
    """Is there a tape capture for the session day with rows in it?

    Named as its own question so a caller (and a test) can answer it without
    touching the network or the disk layout, and so the tick's fallback to the
    servlet capture is decided in one readable place.
    """
    day = (moment or now_karachi()).date()
    path = tape_bars.capture_path(day)
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def capture_budget_seconds() -> float:
    """Seconds one capture may spend inside a single tick cadence.

    The owner's cadence is 4 minutes (2026-10-11) and one full sequential pass
    over the universe needs about seven, so the capture gets the cadence minus
    a reserve for the scan and stops itself at that budget. It used to be given
    a flat CAPTURE_TIMEOUT of 240s, which every trading-day tick exceeded: the
    tick then logged a timeout for a pass that was never allowed to finish.
    config.CAPTURE_BUDGET_SECONDS overrides the derivation when a longer
    cadence or a one-off manual run should be allowed to complete a pass.
    """
    if config.CAPTURE_BUDGET_SECONDS > 0:
        return config.CAPTURE_BUDGET_SECONDS
    cadence = max(1.0, config.TICK_INTERVAL_MINUTES) * 60.0
    return budget_for_cadence(cadence)


def run_capture() -> tuple[bool, str]:
    """Refresh the session's bars. Never raises: a failure is data, not a crash.

    Owner order 2026-10-14: the bar source is the broker tape, so a tick keeps
    that tape alive and measures what it holds. The eClear OHLC pass is still
    asked when no tape exists for the day at all, because a capture on disk is
    better than none, but it is the fallback now rather than the source.
    """
    if tape_capture_present():
        return _tape_pass()
    return _poller_pass()


def _tape_pass() -> tuple[bool, str]:
    """Keep the read-only tape alive and report the bars it holds.

    The tape is the source the scanner reads (src/data/tape_bars.py), so the
    honest question here is not "did a fetch finish" but "is the tape alive
    and does it hold bars for the session". A dead tape is reported as a dead
    tape, with no bars claimed for it.
    """
    moment = now_karachi()
    alive, note = live_card.ensure_tape(moment)
    tape = tape_bars.build(tape_bars.capture_path(moment.date()),
                           universe_symbols(), moment)
    bars = tape.priced_bars + tape.carried_bars
    detail = (f"tape bars: {tape.symbols_with_bars} symbol(s), {bars} bar(s), "
              f"volume counter on {tape.counter_rows} row(s), "
              f"{tape.carried_bars} carried minute(s)| {note}")
    if not alive:
        return False, f"broker tape down: {note}; {detail}"
    if tape.symbols_with_bars == 0:
        return False, f"the tape is alive but holds no bars yet: {detail}"
    return True, detail


def _poller_pass() -> tuple[bool, str]:
    """The fallback: one bounded pass over the eClear OHLC servlet.

    The pass is handed the tick's own budget, so it stops itself cleanly and
    says how much of the universe it did not reach. The subprocess timeout is
    only a backstop for a wedged process, never the expected outcome.
    """
    budget = capture_budget_seconds()
    kill_after = budget + config.CAPTURE_KILL_MARGIN_SECONDS
    command = [sys.executable, "-m", "src.data.ohlc_poller",
               "--symbols-file", str(UNIVERSE.relative_to(ROOT)), "--once",
               "--deadline-seconds", f"{budget:.0f}"]
    try:
        result = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                text=True, timeout=kill_after)
    except subprocess.TimeoutExpired:
        return False, (f"capture ignored its {budget:.0f}s budget and was "
                       f"killed after {kill_after:.0f}s")
    except OSError as exc:
        return False, f"capture could not start: {type(exc).__name__}: {exc}"
    tail = (result.stdout or result.stderr or "").strip().splitlines()[-3:]
    detail = " | ".join(line.strip() for line in tail if line.strip())
    if result.returncode == EXIT_PASS_INCOMPLETE:
        nominal = nominal_pass_seconds(universe_size())
        return False, (f"capture stopped at its {budget:.0f}s budget, a partial "
                       f"pass: a full pass needs about {nominal:.0f}s for "
                       f"{universe_size()} symbols at the source's pacing, so "
                       f"the 4 minute cadence cannot contain one: {detail}")
    if result.returncode != 0:
        return False, f"capture exit {result.returncode}: {detail}"
    return True, detail or "capture ok"


def read_health() -> dict:
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def note_health(ok: bool, detail: str) -> dict:
    """Record capture health, alert at the threshold, then once per day.

    The first alert fires exactly at the threshold, so a broken feed produces
    one message when it starts failing rather than one per failed tick. A feed
    that STAYS broken must not go quiet for the rest of the outage (owner
    order 2026-10-12, the zero-defect law): once the threshold is crossed, a
    continuing failure re-alerts once per Karachi day, the same cadence the
    CI-side flag-gated alert uses. A healthy pass clears the day stamp, so the
    next outage starts its own count and earns its own reminder.
    """
    health = read_health()
    failures = 0 if ok else int(health.get("consecutive_failures") or 0) + 1
    today = now_karachi().date().isoformat()
    health.update({
        "last_check": now_karachi().isoformat(timespec="seconds"),
        "last_ok": ok,
        "last_detail": detail,
        "consecutive_failures": failures,
    })
    if ok:
        health["last_success"] = health["last_check"]
        health.pop("last_failure_alert_day", None)
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
    if not ok and failures >= ALERT_AFTER_FAILURES:
        at_threshold = failures == ALERT_AFTER_FAILURES
        day_unalerted = health.get("last_failure_alert_day") != today
        if at_threshold or day_unalerted:
            try:
                from scripts import intraday_pipeline as pipeline

                pipeline.deliver(
                    f"KMIALL local tick: bar capture has failed {failures} times "
                    f"in a row.\nLast error: {detail}\nThe scanner will report a "
                    f"data failure until the feed recovers.", "ops")
                health["last_failure_alert_day"] = today
                HEALTH_FILE.write_text(json.dumps(health, indent=2),
                                       encoding="utf-8")
                log(f"ops alert sent after {failures} capture failures")
            except Exception as exc:  # noqa: BLE001 - an alert is best effort
                log(f"ops alert failed: {type(exc).__name__}")
    return health


# ------------------------------------------------------------------------ main

def status_line(moment: datetime) -> str:
    state = SessionState.load(moment.date())
    return (f"state={state_of(moment)} phase={phase_of(moment)} "
            f"slot={slot_of(moment)} day={state.day} trade_state="
            f"{state.state} scans={state.scans} trades={state.trades_today} "
            f"last_tick={state.last_tick_slot} finalized={state.finalized}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="local 4-minute KMIALL tick")
    parser.add_argument("--force", action="store_true",
                        help="ignore the slot and finalize guards")
    parser.add_argument("--status", action="store_true",
                        help="describe the current phase and state, then stop")
    parser.add_argument("--skip-capture", action="store_true",
                        help="scan the capture already on disk")
    parser.add_argument("--skip-card", action="store_true",
                        help="do not touch the broker tape or publish the card")
    args = parser.parse_args(argv)

    moment = now_karachi()
    if args.status:
        print(status_line(moment))
        return 0

    log(f"tick start: {status_line(moment)}")

    # One decision table, shared with scripts/scan_loop.py. It answers scan,
    # finalize or wait and names the market state that decided, so the owner's
    # never-scan rules live in src/data/scan_schedule.py rather than in a copy
    # per runner.
    action, reason = decide(moment)

    if action == ACTION_WAIT:
        log(f"paused: {reason}. nothing scanned.")
        return 0

    state = SessionState.load(moment.date())

    if action == ACTION_FINALIZE:
        # Post-market values the session that has just closed. It is
        # finalize-only and never scans (owner order 2026-10-11).
        if state.finalized and not args.force:
            log("day already finalized; nothing to do")
            return 0
        return _finalize(moment, args.skip_capture)

    # action is ACTION_SCAN: the owner's never-scan windows are already gone.
    slot = slot_of(moment)
    if state.claimed_slot(slot) and not args.force:
        log(f"slot {slot} already scanned today; skipping this tick")
        return 0

    held, detail = acquire_lock(moment)
    if not held:
        log(f"refusing to run: {detail}")
        return 4
    try:
        # The tape first, before the slow bar capture: the split on the
        # phone can only be measured from a capture that has been banking
        # ticks since the open, so a dead one is restarted as early in the
        # slot as possible (owner's order, 2026-10-12).
        tape_note = "skipped by flag"
        if not args.skip_card:
            tape_ok, tape_note = live_card.ensure_tape(moment)
            log(f"trade tape {'ok' if tape_ok else 'UNAVAILABLE'}: {tape_note}")

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

        # The card is published last, on the tape the step above just made
        # sure is running, and its outcome is logged either way. The scan's
        # own verdict is already decided, so a card failure cannot change it.
        if not args.skip_card:
            card = live_card.publish_card(moment)
            log(f"market card {'ok' if card['ok'] else 'FAILED'}: "
                f"{card['detail']} | {card['split']}")
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
    # SO-12 (owner order 2026-10-14): the 4-minute scanner belongs to GitHub
    # Actions minutes and to the Cloudflare relay. This script is the tick the
    # Windows task used to fire on the owner's PC, so a real process starting
    # here is refused unless the owner asked for this exact run. Inside
    # Actions the guard passes straight through, and main() stays callable
    # from the test suite exactly as before.
    guard_owner_requested("scripts/kmiall_tick.py")
    raise SystemExit(main())
