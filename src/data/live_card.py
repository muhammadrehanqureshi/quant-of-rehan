"""Keep the phone's market card real: a live trade tape, and the card pushed.

Owner order 2026-10-12: the card must show the day's top three KMIALL stocks
with their buy and sell volumes split from the market's own real-time trades,
not just the exchange's total volume.

The split has exactly one genuine source in this repository: the broker's
per-trade tape (``data/feed_capture/capture_YYYYMMDD.ndjson``), which exists
only while ``src/data/feed_capture.py`` is running. That recorder is not a
standing process (SO-10), and the whole session has to be covered: a capture
that starts mid-session has classified only the trades after it started, so
``src/data/tick_volume.py`` reports its split as a floor rather than a whole
day and ``src/data/volume_split.py`` refuses it.

So the live session gets one job with two halves, in the order the data needs
them:

    1. TAPE  is a capture alive and current? If not, start one on this PC and
             leave it running for the rest of the session. A capture that was
             never running is why every card on the phone showed the total
             volume alone with no buy and sell sides (measured 2026-10-12:
             the capture had connected and received only index, movers and
             market-stats frames).
    2. CARD  build the snapshot -- src/data/market_snapshot.py ranks by the
             exchange's own session volume and splits it from the tape just
             checked -- and push it to the relay, which is where the phone
             reads it.

Caller: the owner's 4-minute tick (``scripts/kmiall_tick.py``), which already
fires inside a live session and already owns this PC's market work. Both
halves are best effort by design: a card that cannot be published must never
turn a scan into a failure, and a tape that cannot start is reported in the
tick log rather than swallowed.

Usage (from the repo root, usually by the tick):
    python -m src.data.live_card                 # tape, then card
    python -m src.data.live_card --status         # what is true right now
    python -m src.data.live_card --no-tape        # card only, never start one
    python -m src.data.live_card --dry-run        # build the card, do not push
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import market_snapshot  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

STATUS_PATH = ROOT / "data" / "feed_capture" / "status.json"
TAPE_LOG = ROOT / "logs" / "feed_capture.log"

#: How old the recorder's own heartbeat may be before the tape counts as
#: dead. The daemon rewrites status.json every 20 seconds, so three missed
#: beats means it is gone whether or not its pid is still around.
TAPE_STALE_SECONDS = 70.0

#: How long a freshly spawned recorder is watched before start_tape counts it
#: as started. Long enough for the child to die on its first line (a missing
#: universe file, a bad argument), short enough to cost one start and never a
#: cycle. Measured 2026-10-14 on a GitHub Actions runner: the child returned
#: in under a second while start_tape reported success, so five straight
#: cycles blamed the tape for bars a dead recorder never wrote.
START_PROBE_SECONDS = 2.0

# Owner order 2026-11-03, after Cloudflare emailed the daily request limit
# to the owner twice on 2026-11-02: the card POST is the loop's largest
# draw on the relay. The Workers free plan grants 100,000 requests a day
# and emails the owner at 80% and 100%; one loop at the 2026-10-19 one
# second cadence alone spends about 21,600 of them on POST /market in a
# session, and two overlapping loops (one live, one queued behind it)
# multiply a bad day past the cap. The pushes are also largely wasted: the
# edge keeps a pushed card for five minutes (cloud/worker.js POST /market)
# and /market grafts the frames the durable store already holds, so a
# push faster than the interval only refreshes a copy the edge is still
# serving. The two laws below are the small change that removes the burn;
# the SCAN cadence itself stays one second, owner order untouched.
#
#   CONTENT  a card whose snapshot is identical to the last one pushed is
#            not sent again (the exchange's own answers move every cycle,
#            so quiet stretches collapse into zero requests);
#   INTERVAL a card that differs is sent at most once per minute, so even
#            a market in constant motion spends about 360 requests a
#            session where one push a second spent 21,600.
CARD_PUSH_MIN_INTERVAL_SECONDS = 60.0

#: Snapshot keys that travel with every cycle without carrying card
#: content: the clock labels. Everything else (the index, the leaders,
#: their volumes and buy/sell split, the notes) decides whether the edge
#: should hold a different card at all.
CARD_PUSH_VOLATILE_KEYS = ("as_of", "age_seconds")

#: The last card this process pushed. The band loop is one long-lived
#: process, so this in-memory ledger is the state the throttle needs;
#: a fresh process always publishes its first card.
CARD_PUSH_STATE: dict = {"signature": None, "epoch": 0.0}


def card_signature(snapshot: dict) -> str:
    """Fingerprint the card content the edge can actually tell apart."""
    volatile = set(CARD_PUSH_VOLATILE_KEYS)

    def strip(value):
        if isinstance(value, dict):
            return {key: strip(item) for key, item in value.items()
                    if key not in volatile}
        if isinstance(value, list):
            return [strip(item) for item in value]
        return value

    return json.dumps(strip(snapshot), sort_keys=True, separators=(",", ":"),
                      default=str)


def _card_epoch(now: datetime | None) -> float:
    """The push clock: the caller's own moment when it carries a zone."""
    if now is not None and now.tzinfo is not None:
        return now.timestamp()
    return time.time()


def _parse_stamp(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def tape_state(now: datetime | None = None) -> tuple[bool, str]:
    """Is a broker trade tape being banked right now? (alive, why)

    Liveness is read from the recorder's own heartbeat rather than from the
    process table: the daemon rewrites ``data/feed_capture/status.json`` every
    20 seconds with ``running``, its pid and ``updated_at``, and a recorder
    that was killed leaves that file stale. That makes the answer the same on
    Windows and on Linux without a process-table probe.
    """
    moment = now or now_karachi()
    if not STATUS_PATH.is_file():
        return False, "no broker tape is running (no status.json yet)"
    try:
        saved = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"broker tape status unreadable: {type(exc).__name__}"
    if not saved.get("running"):
        return False, "the last broker tape run has ended"
    stamp = _parse_stamp(saved.get("updated_at", ""))
    if stamp is None:
        return False, "the broker tape status carries no heartbeat time"
    age = (moment - stamp).total_seconds()
    if age > TAPE_STALE_SECONDS:
        return False, (f"the broker tape stopped reporting {age:.0f}s ago, "
                       f"so it is not banking ticks")
    counters = saved.get("counters") or {}
    detail = (f"broker tape alive, last frame "
              f"{saved.get('last_frame_at') or 'unknown'} "
              f"({counters.get('messages', 0)} messages banked)")
    error = str(saved.get("last_error") or "").strip()
    if error:
        # The heartbeat carries the recorder's own last error, so a tape that
        # is running but cannot reach the venue says why in the caller's log
        # instead of only inside a downloaded artifact.
        detail += f"; last error: {error}"
    return True, detail


def _probe_child(child: subprocess.Popen, timeout: float) -> int | None:
    """The child's exit code if it stopped inside the window, else None.

    A recorder that survives the window has no reason to exit on its own:
    it runs until killed, and its first act is writing status.json, which is
    the next question tape_state answers.
    """
    deadline = time.monotonic() + timeout
    while True:
        code = child.poll()
        if code is not None:
            return code
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.05)


def _tape_log_tail(lines: int = 3) -> str:
    """The recorder's own last words, for a start that failed."""
    try:
        text = TAPE_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    kept = [line.strip() for line in text.splitlines()[-lines:]
            if line.strip()]
    return " | ".join(kept)


def start_tape() -> tuple[bool, str]:
    """Start the read-only recorder on this PC, detached for the session.

    Detached on purpose: the tick that starts it exits seconds later, and the
    tape must outlive it until the session closes. Its output goes to
    ``logs/feed_capture.log`` because a child of a scheduled task has nowhere
    to print. The recorder itself enforces the owner's read-only law, so this
    can only ever begin a subscription and a heartbeat.

    Started is not running: the child is watched for START_PROBE_SECONDS and
    an exit inside that window is a failed start carrying the exit code and
    the recorder's own last log line, because a crash at startup reported as
    success sends every later cycle looking for bars a dead recorder never
    wrote (measured 2026-10-14, five faulted cycles in the cloud).
    """
    # Unbuffered (-u) on purpose: the child's stdout is a file, so Python block
    # buffers it and the recorder's own lines never reach the log. Measured
    # 2026-10-14 on a GitHub Actions runner, the band's feed_capture.log came
    # back 0 bytes while the tape itself was working, which makes a failure at
    # the venue impossible to read from the artifact.
    command = [sys.executable, "-u", "-m", "src.data.feed_capture"]
    creationflags = 0
    if os.name == "nt":
        # New process group and no console: the tape must not die with the
        # tick's process group or hold the task's console open.
        creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    try:
        TAPE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(TAPE_LOG, "a", encoding="utf-8") as sink:
            child = subprocess.Popen(command, cwd=str(ROOT), stdout=sink,
                                     stderr=subprocess.STDOUT,
                                     creationflags=creationflags)
    except OSError as exc:
        return False, f"the broker tape could not start: {type(exc).__name__}: {exc}"
    # Started is not running: watch the child long enough to catch a crash at
    # startup, and report that with the recorder's own last log line rather
    # than claiming a tape that is not there.
    stopped = _probe_child(child, START_PROBE_SECONDS)
    if stopped is not None:
        where = TAPE_LOG.relative_to(ROOT)
        reason = _tape_log_tail() or f"see {where}"
        return False, (f"the broker tape exited with code {stopped} at start: "
                       f"{reason}")
    return True, (f"broker tape started (pid {child.pid}), log "
                  f"{TAPE_LOG.relative_to(ROOT)}")


def ensure_tape(now: datetime | None = None) -> tuple[bool, str]:
    """Guarantee a tape is running for this session, starting one if needed."""
    alive, detail = tape_state(now)
    if alive:
        return True, detail
    started, start_detail = start_tape()
    if not started:
        return False, f"{detail}; {start_detail}"
    return True, f"{detail}; {start_detail}"


def split_summary(snapshot: dict) -> str:
    """One honest sentence about the split the snapshot actually carries.

    Owner order 2026-10-30 (one law for every stock): the card's rows
    answer with the row's own frame split, the same range-position pair the
    app's search box ranks from, so the normal sentence is the range one.
    The tape's own methods remain counted in case a legacy pushed card is
    still in the relay, and the sentence names whichever produced a number,
    so the tick log never calls an estimate a measurement.
    """
    rows = snapshot.get("top_volume") or []
    if not rows:
        return "no volume ranking to split"
    measured = sum(1 for row in rows
                   if row.get("split_method") == "quote_rule" and
                   row.get("buy_volume") is not None and
                   row.get("sell_volume") is not None)
    if measured == len(rows):
        return f"B/S measured at the wire for all {len(rows)} leaders"
    if measured:
        return (f"{measured} of {len(rows)} leaders carry a measured B/S "
                f"pair; the rest are U")
    return (f"no measured B/S pair for any of the {len(rows)} leaders; "
            f"their totals are U")


def publish_card(now: datetime | None = None, dry_run: bool = False) -> dict:
    """Build the card and push it to the relay. Never raises.

    Returns a small result dict: ``ok``, a one line ``detail`` for the tick
    log, and the split sentence. A failure names its own cause; nothing here
    invents a success, and nothing here can stop a scan.

    The push itself is throttled (owner order 2026-11-03): a card whose
    content is identical to the last one pushed is never sent again, and a
    card that differs is sent at most once per minute, because the edge
    serves a pushed card for five minutes anyway and every relay request
    counts against the Workers free plan. A skipped push still reports
    ``ok``: the card the phone reads already shows what this snapshot
    describes.
    """
    try:
        snapshot = market_snapshot.build_snapshot()
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        return {"ok": False, "detail": f"card build failed: {type(exc).__name__}: {exc}",
                "split": "unknown"}
    split = split_summary(snapshot)
    if dry_run:
        return {"ok": True, "dry_run": True,
                "detail": "card built (dry run, not pushed)", "split": split,
                "snapshot": snapshot}
    signature = card_signature(snapshot)
    if signature == CARD_PUSH_STATE["signature"]:
        # The edge is already serving exactly this card byte for byte, so
        # repeating it spends a request the cap will eventually bill for
        # nothing the phone could see (owner order 2026-11-03).
        return {"ok": True,
                "detail": ("card unchanged since the last push; the edge "
                           "still holds it (no relay request)"),
                "split": split, "snapshot": snapshot}
    epoch = _card_epoch(now)
    last_epoch = float(CARD_PUSH_STATE["epoch"] or 0.0)
    if last_epoch > 0.0 and epoch - last_epoch < CARD_PUSH_MIN_INTERVAL_SECONDS:
        return {"ok": True,
                "detail": (f"card changed {epoch - last_epoch:.0f}s after "
                           f"the last push, inside the "
                           f"{CARD_PUSH_MIN_INTERVAL_SECONDS:.0f}s push "
                           "interval; the pushed card stands"),
                "split": split, "snapshot": snapshot}
    try:
        reply = market_snapshot.push_snapshot(snapshot)
    except SystemExit as exc:  # missing credential: a configuration fact
        return {"ok": False, "detail": f"card not pushed: {exc}", "split": split}
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        return {"ok": False,
                "detail": f"card push failed: {type(exc).__name__}: {exc}",
                "split": split}
    if not reply.get("ok"):
        return {"ok": False,
                "detail": f"the relay refused the card: {reply.get('error')}",
                "split": split}
    CARD_PUSH_STATE["signature"] = signature
    CARD_PUSH_STATE["epoch"] = epoch
    return {"ok": True, "detail": "card published to the relay", "split": split,
            "snapshot": snapshot}


def run_once(now: datetime | None = None, manage_tape: bool = True,
             dry_run: bool = False) -> dict:
    """One session pass: keep the tape alive, then publish the card."""
    moment = now or now_karachi()
    result: dict = {"at": moment.isoformat(timespec="seconds")}
    if manage_tape:
        tape_ok, tape_detail = ensure_tape(moment)
    else:
        tape_ok, tape_detail = tape_state(moment)
    result["tape_ok"] = tape_ok
    result["tape"] = tape_detail
    card = publish_card(moment, dry_run=dry_run)
    result["card_ok"] = card["ok"]
    result["card"] = card["detail"]
    result["split"] = card["split"]
    result["ok"] = bool(card["ok"])
    result["detail"] = f"tape: {tape_detail} | card: {card['detail']} | {card['split']}"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="keep the broker trade tape alive and publish the card")
    parser.add_argument("--status", action="store_true",
                        help="report the tape and the last card, then stop")
    parser.add_argument("--no-tape", action="store_true",
                        help="never start a capture, only report one")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the card but do not push it")
    args = parser.parse_args(argv)

    if args.status:
        alive, detail = tape_state()
        print(json.dumps({"tape_alive": alive, "tape": detail}, indent=1))
        return 0 if alive else 1

    result = run_once(manage_tape=not args.no_tape, dry_run=args.dry_run)
    print(json.dumps({key: value for key, value in result.items()
                      if key != "snapshot"}, indent=1))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
