"""
Sentinel-EOD watchdog - the scheduled runs' safety net.

GitHub's cron indexer has already dropped a live pick slot once
(2026-09-16: the 15:20 PKT pick cron never fired; the only scheduled
run arrived 4.5 hours late, after the close - the owner's call email
went out only because a manual dispatch happened to run first).

This script runs in the rescue slots (pick minute +10/+20) and takes
action ONLY when needed:

  * before the target minute        -> exit (too early)
  * heartbeat shows today's run     -> exit (already landed)
  * inside the grace window         -> run the production runner
                                       DIRECTLY in-process, verify
                                       today's artifact
  * after the grace window          -> exit (slot lost; next slot/day)

Two guarded modes:
  reference - 14:20 PKT Mon-Thu, 15:20 PKT Fri (30-min grace); a
              dropped reference silently degrades the pick's
              last-hour feature.
  pick      - 15:26 PKT Mon-Thu, 16:26 PKT Fri (+2 grace: alive
              through :28, closed after - the owner orders at :29).

It never decides anything itself - it only invokes src/run_eod.py,
which keeps every guard: weekday check, PKT window, one-pick-per-day,
circuit veto. The workflow's Commit state step then pushes whatever
the rescue produced.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT = REPO_ROOT / "data" / "heartbeat.json"
PICKS_DIR = REPO_ROOT / "data" / "picks"
PKT = ZoneInfo("Asia/Karachi")

GRACE_MINUTES = {"reference": 30, "pick": 2}


def mode_target(mode: str, weekday: int) -> tuple[int, int]:
    """The day's target minute-of-day in PKT for this mode.

    v2.2.1: the pick target is the FIRST rescue slot (:26) - the
    primary (:21) and backup (:24) own the minutes before it. The +2
    grace keeps rescue alive through :28 (the last minute a rescued
    pick is still usable - the owner orders at :29) and closes after.
    """
    if mode == "reference":
        return (15, 20) if weekday == 4 else (14, 20)
    return (16, 26) if weekday == 4 else (15, 26)


def watchdog_decision(
    now: datetime,
    heartbeat: dict | None,
    mode: str = "pick",
) -> tuple[str, tuple[int, int]]:
    """
    Pure decision core (unit-tested).

    Returns (decision, target) where decision is one of:
      weekend | too_early | already_done | rescue_needed | window_closed
    """
    wd = now.weekday()
    target = mode_target(mode, wd)
    if wd >= 5:
        return "weekend", target

    now_min = now.hour * 60 + now.minute
    target_min = target[0] * 60 + target[1]
    if now_min < target_min:
        return "too_early", target
    if now_min > target_min + GRACE_MINUTES[mode]:
        return "window_closed", target

    stamp = (heartbeat or {}).get("utc", "")
    if stamp:
        try:
            hb = datetime.fromisoformat(stamp)
            same_day = hb.astimezone(PKT).date() == now.date()
            if same_day and (heartbeat or {}).get("source") == mode:
                return "already_done", target
        except ValueError:
            pass
    return "rescue_needed", target


def load_heartbeat() -> dict | None:
    if not HEARTBEAT.exists():
        return None
    try:
        return json.loads(HEARTBEAT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def run_rescue(mode: str, token: str | None) -> int:
    """Invoke the production runner directly, in-process."""
    cmd = [sys.executable, str(REPO_ROOT / "src" / "run_eod.py"), mode]
    if token:
        cmd += ["--token", token]
    env = dict(os.environ)
    print(f"watchdog: RESCUE - running `run_eod.py {mode}` directly")
    return subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode


def verify(mode: str, today: str) -> bool:
    """Did today's run land? Local heartbeat + artifact check."""
    hb = load_heartbeat() or {}
    try:
        stamp_ok = (
            datetime.fromisoformat(hb.get("utc", ""))
            .astimezone(PKT)
            .date()
            .isoformat() == today
            and hb.get("source") == mode
        )
    except ValueError:
        stamp_ok = False
    if mode == "pick":
        return stamp_ok and (PICKS_DIR / f"{today}.json").exists()
    return stamp_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Sentinel-EOD watchdog")
    parser.add_argument("--mode", choices=["reference", "pick"],
                        default="pick")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    token = args.token or os.environ.get("GITHUB_TOKEN")
    now = datetime.now(PKT)
    today = now.date().isoformat()

    decision, target = watchdog_decision(now, load_heartbeat(),
                                         mode=args.mode)
    print(f"watchdog[{args.mode}]: {decision} at {now:%H:%M} PKT "
          f"(target {target[0]:02d}:{target[1]:02d}, {today})")

    if decision != "rescue_needed":
        return 0
    if run_rescue(args.mode, token) != 0:
        print("watchdog: rescue run failed")
        return 1
    if verify(args.mode, today):
        print(f"watchdog: RESCUED - today's {args.mode} verified")
        return 0
    print(f"watchdog: rescue ran but today's {args.mode} not verified")
    return 1


if __name__ == "__main__":
    sys.exit(main())
