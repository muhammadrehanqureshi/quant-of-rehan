"""Local spark - the out-of-GitHub cadence rescuer.

WHY THIS EXISTS: GitHub's cron scheduler is unreliable for this repo
during market hours. Measured 2026-09-16: the keeper workflow fired on
schedule exactly once in two days; every 5-minute slot from 04:32 to
06:32 UTC (market open through midday PKT) was silently dropped while
the market sat unpolled. The keeper is correct but cannot run if the
scheduler never fires it. The fix must live OUTSIDE GitHub.

WHAT: a ~1-second, stdlib-only script meant to be registered with
Windows Task Scheduler every 5 minutes during market hours. It reads
data/heartbeat.json (stamped ONLY by a real pass that polled, exited
and decided - a skipped pass cannot fake it), and dispatches one cloud
pass ONLY when that heartbeat is older than 12 minutes.

COST ON THE OWNER'S PC: one cold python start (~1 s) every 5 minutes -
no pip, no pandas, no feed polling, no browser. On a healthy day it
dispatches nothing and exits. Remove any time with:

    schtasks /delete /tn "Sentinel Spark" /f

TRUST: the token comes from the Windows Credential Manager via
`git credential fill` (the same store git itself uses) - nothing
secret is written to disk here.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ALL spark windows are Karachi wall-clock (the market's zone). Pinning
# the clock makes the guards correct even if the PC's system timezone
# ever changes - the owner's standing order: Karachi time everywhere.
PKT = ZoneInfo("Asia/Karachi")

REPO = Path(__file__).resolve().parents[1]
OWNER_REPO = "muhammadrehanqureshi/the-sentinel"
WORKFLOW = "cloud-intraday.yml"

# Sentinel-EOD trace guard (2026-09-17): GitHub's scheduler dropped the
# ENTIRE */5 trace window that morning - SGPL/FCEPL had crossed +2% at
# the bell but no outcome was recorded or emailed for hours. The spark
# now guards the tracer too: within the morning trace window, if the
# book is open for today and the trace heartbeat is stale, dispatch.
EOD_REPO = "muhammadrehanqureshi/sentinel-eod"
EOD_WORKFLOW = "eod-trace.yml"
EOD_STATE = REPO / "data" / ".spark_last_eod"
TRACE_WINDOW = ((9, 35), (11, 50))   # PKT
TRACE_STALE_MIN = 20

# EOD evening-pick rescue (2026-09-18): the 15:17/16:17 PKT crons and
# the :29 last-chance slots are all indexer-fodder - measured drops two
# days running. The owner's contract is the pick EMAIL BY 15:20/16:20,
# so the rescue is PROACTIVE: from :13 (three minutes before the cron
# would fire) a missing pick is dispatched immediately - a run started
# at :16 publishes at ~:18-19, on contract even when cron is fully
# dead. If the cron DID fire, its run publishes first and this guard
# exits on the pick_date check (first book wins, duplicates harmless).
EOD_EVENING_WORKFLOW = "eod-evening.yml"
EOD_PICK_STATE = REPO / "data" / ".spark_last_eod_pick"
PICK_WINDOW_MON_THU = ((15, 13), (15, 32))   # PKT
PICK_WINDOW_FRIDAY = ((16, 13), (16, 32))    # PKT

STALE_AFTER_MIN = 12   # same threshold as the GitHub-side keeper
MIN_BETWEEN_SPARKS_MIN = 10  # local pile-up guard
SESSION_START = (9, 15)   # PKT - bot decides from 10:00, but keep the book warm
SESSION_END = (15, 30)    # PKT - close
SPARK_STATE = REPO / "data" / ".spark_last"


def _credential_token() -> str | None:
    """Read the GitHub PAT from the Windows Credential Manager (git's own store).

    Strictly non-interactive (v0.18.3): GCM_INTERACTIVE=Never +
    GIT_TERMINAL_PROMPT=0 mean a second stored GitHub account can
    never pop the "Select an account" dialog on the owner's screen -
    the fill either answers silently or fails, and the spark does
    nothing on failure. (2026-09-17: an x-access-token entry stored by
    a scripted push made GCM prompt for account selection every spark
    run; the entry was rejected and the dialog is now impossible.)
    """
    import os

    env = dict(os.environ)
    env["GCM_INTERACTIVE"] = "Never"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        out = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n",
            capture_output=True, text=True, cwd=REPO, timeout=20,
            env=env,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                           if sys.platform == "win32" else 0),
        ).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:
        return None
    return None


def _fetch_heartbeat_age(token: str) -> float | None:
    """Age in minutes of the committed heartbeat, or None if unreadable."""
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{OWNER_REPO}/contents/data/heartbeat.json",
        headers={"Authorization": f"token {token}", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.load(resp)
        content = json.loads(__import__("base64").b64decode(payload["content"]))
        hb = datetime.fromisoformat(content["utc"])
        now = datetime.now(timezone.utc)
        if hb.tzinfo is None:
            hb = hb.replace(tzinfo=timezone.utc)
        return (now - hb).total_seconds() / 60
    except Exception:
        return None


def should_dispatch(
    hb_age_min: float | None, now_local: datetime, last_spark_min: float | None
) -> tuple[bool, str]:
    """Pure decision core - unit-tested. (dispatch?, reason)"""
    if now_local.weekday() >= 5:
        return False, "weekend"
    mins = now_local.hour * 60 + now_local.minute
    if mins < SESSION_START[0] * 60 + SESSION_START[1]:
        return False, "before session"
    if mins > SESSION_END[0] * 60 + SESSION_END[1]:
        return False, "after session"
    if last_spark_min is not None and last_spark_min < MIN_BETWEEN_SPARKS_MIN:
        return False, f"last spark {last_spark_min:.0f} min ago (guard)"
    if hb_age_min is None:
        return True, "heartbeat unreadable - assume stale"
    if hb_age_min < STALE_AFTER_MIN:
        return False, f"heartbeat fresh ({hb_age_min:.0f} min < {STALE_AFTER_MIN})"
    return True, f"heartbeat stale ({hb_age_min:.0f} min >= {STALE_AFTER_MIN})"


def _gh_get_json(token: str, repo: str, path: str):
    """Fetch and decode a JSON file from a repo's default branch."""
    import base64
    import urllib.request

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/contents/{path}",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.load(resp)
    return json.loads(base64.b64decode(payload["content"]))


def trace_guard_decision(
    now_local: datetime, tracker: dict | None, heartbeat: dict | None
) -> tuple[bool, str]:
    """Pure decision core - unit-tested. (dispatch?, reason)"""
    if now_local.weekday() >= 5:
        return False, "weekend"
    mins = now_local.hour * 60 + now_local.minute
    start = TRACE_WINDOW[0][0] * 60 + TRACE_WINDOW[0][1]
    end = TRACE_WINDOW[1][0] * 60 + TRACE_WINDOW[1][1]
    if mins < start:
        return False, "before trace window"
    if mins > end:
        return False, "after trace window"
    today = now_local.date().isoformat()
    if not (tracker or {}).get("open"):
        return False, "no open book"
    pick_date = (tracker or {}).get("pick_date", "")
    if pick_date == today:
        return False, "picks are for the next session"
    if pick_date > today:
        return False, "pick date in the future"
    stamp = (heartbeat or {}).get("utc", "")
    if stamp and (heartbeat or {}).get("source") == "trace":
        try:
            hb = datetime.fromisoformat(stamp)
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if hb.date() == datetime.now(timezone.utc).date():
                age = (datetime.now(timezone.utc) - hb).total_seconds() / 60
                if age < TRACE_STALE_MIN:
                    return False, f"trace fresh ({age:.0f} min)"
        except ValueError:
            pass
    return True, "trace stale/missing - rescue"


def pick_guard_decision(
    now_local: datetime, tracker: dict | None, notified: dict | None
) -> tuple[bool, str]:
    """Pure decision core - unit-tested. (dispatch?, reason)

    Contract: the owner has the evening pick in hand BY 15:20 PKT
    (Mon-Thu) / 16:20 PKT (Friday). From :13 a missing pick is a
    dropped-cron emergency, not a wait-and-see situation.
    """
    if now_local.weekday() >= 5:
        return False, "weekend"
    mins = now_local.hour * 60 + now_local.minute
    start, end = (
        PICK_WINDOW_FRIDAY if now_local.weekday() == 4 else PICK_WINDOW_MON_THU
    )
    s, e = start[0] * 60 + start[1], end[0] * 60 + end[1]
    if mins < s:
        return False, "before pick window"
    if mins > e:
        return False, "after pick window"
    today = now_local.date().isoformat()
    if (tracker or {}).get("pick_date") == today:
        return False, "pick already published today"
    if f"pick:{today}" in ((notified or {}).get("posted") or []):
        return False, "pick already delivered today"
    return True, (
        f"no pick by {start[0]:02d}:{start[1]:02d} - rescue for the "
        f"{start[0]:02d}:{start[1] - 0:02d}+20 contract"
    )


def _minutes_since_state_file(path: Path = SPARK_STATE) -> float | None:
    try:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return None


def main() -> int:
    now = datetime.now(PKT)
    last_spark = _minutes_since_state_file()
    token = _credential_token()
    if not token:
        print("spark: no GitHub credential available - doing nothing")
        return 0

    import urllib.request

    # ---- Guard 1: the Sentinel's intraday cadence ---------------------
    try:
        hb_age = _fetch_heartbeat_age(token)
        dispatch, reason = should_dispatch(hb_age, now, last_spark)
        if dispatch:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{OWNER_REPO}/actions/workflows/{WORKFLOW}/dispatches",
                data=b'{"ref":"master"}',
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    status = resp.status
                SPARK_STATE.write_text(now.isoformat(), encoding="utf-8")
                print(f"spark: dispatched a pass (HTTP {status}) - {reason}")
            except Exception as exc:
                print(f"spark: dispatch FAILED - {exc}")
        else:
            print(f"spark: no action - {reason}")
    except Exception as exc:
        print(f"spark: sentinel guard skipped - {exc}")

    # ---- Guard 2: the Sentinel-EOD morning tracer ---------------------
    try:
        tracker = _gh_get_json(token, EOD_REPO, "data/tracker.json")
        # The heartbeat may be absent from the remote (404) - treat as
        # "unknown", not as a hard error; trace_guard_decision already
        # treats a missing/invalid stamp as stale (rescue).
        try:
            eod_hb = _gh_get_json(token, EOD_REPO, "data/heartbeat.json")
        except Exception:
            eod_hb = None
        t_dispatch, t_reason = trace_guard_decision(now, tracker, eod_hb)
        last_eod = _minutes_since_state_file(EOD_STATE)
        if t_dispatch and last_eod is not None \
                and last_eod < MIN_BETWEEN_SPARKS_MIN:
            t_dispatch = False
            t_reason = f"last eod spark {last_eod:.0f} min ago (guard)"
        if not t_dispatch:
            print(f"spark: eod trace - no action ({t_reason})")
        else:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{EOD_REPO}/actions/workflows/{EOD_WORKFLOW}/dispatches",
                data=b'{"ref":"main","inputs":{"mode":"trace"}}',
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                t_status = resp.status
            EOD_STATE.write_text(now.isoformat(), encoding="utf-8")
            print(f"spark: dispatched EOD trace (HTTP {t_status}) - {t_reason}")
    except Exception as exc:
        print(f"spark: eod trace guard skipped - {exc}")

    # ---- Guard 3: the Sentinel-EOD evening pick (the 15:20/16:20
    #      contract). Proactive from :13; first book wins.
    try:
        tracker = _gh_get_json(token, EOD_REPO, "data/tracker.json")
        notified = _gh_get_json(token, EOD_REPO, "data/notified.json")
        p_dispatch, p_reason = pick_guard_decision(now, tracker, notified)
        last_pick = _minutes_since_state_file(EOD_PICK_STATE)
        if p_dispatch and last_pick is not None \
                and last_pick < MIN_BETWEEN_SPARKS_MIN:
            p_dispatch = False
            p_reason = f"last pick spark {last_pick:.0f} min ago (guard)"
        if not p_dispatch:
            print(f"spark: eod pick - no action ({p_reason})")
        else:
            req = urllib.request.Request(
                f"https://api.github.com/repos/{EOD_REPO}/actions/workflows/{EOD_EVENING_WORKFLOW}/dispatches",
                data=b'{"ref":"main","inputs":{"mode":"pick"}}',
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github+json",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                p_status = resp.status
            EOD_PICK_STATE.write_text(now.isoformat(), encoding="utf-8")
            print(f"spark: dispatched EOD pick rescue (HTTP {p_status}) - {p_reason}")
    except Exception as exc:
        print(f"spark: eod pick guard skipped - {exc}")

    # ---- Guard 4: tier-3 PC-direct emergency pick (2026-09-18).
    #      Guards 1-3 all DISPATCH to GitHub Actions - if Actions itself
    #      is dead at 15:24/16:24 PKT, nothing anywhere can deliver. This
    #      tier runs the pick ON THIS PC and sends Telegram DIRECTLY;
    #      api.github.com is never touched on the delivery path.
    try:
        import eod_emergency_pick as emergency

        # Recovery duty (all day, cheap): if an earlier emergency run
        # left unpushed state in the local clone, keep trying to push
        # it so GitHub's recovery can never double-publish.
        sync = emergency.sync_state_to_github()
        if sync not in ("no clone", "pushed"):
            print(f"spark: eod emergency sync - {sync}")

        mins_now = now.hour * 60 + now.minute
        win = (emergency.WINDOW_FRIDAY if now.weekday() == 4
               else emergency.WINDOW_MON_THU)
        in_window = (win[0][0] * 60 + win[0][1] <= mins_now
                     <= win[1][0] * 60 + win[1][1])
        if in_window:
            emergency.run_emergency_pick()
        else:
            print("spark: eod emergency - outside window")
    except Exception as exc:
        print(f"spark: eod emergency guard skipped - {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
