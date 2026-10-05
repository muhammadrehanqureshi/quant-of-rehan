"""
The Sentinel - session watchdog (v0.15.8).

Self-chaining (chain_next_pass.py) died three ways in one day: it
self-looped at 1 min/cycle (v0.15.3), declined to chain when a ghost
run looked "fresh" (v0.15.6), and left the last pass childless. Every
variant shared one flaw: the chain's continuity depended on the
judgment of a pass that might itself be broken or gone.

The watchdog inverts the model. It is stateless, external, and dumb:

  * fires every 10 minutes during PSX hours (its own cron);
  * if the market is closed -> do nothing;
  * if the newest SUCCESSFUL cloud pass is younger than the interval
    -> cadence healthy, do nothing (a 12-second failed ghost does NOT
    count as healthy - only a pass that actually worked does);
  * if a cloud pass was created very recently (queued or starting)
    -> do nothing, it is about to run;
  * if the day's total run count is over budget -> do nothing (the
    runaway brake, measured from GitHub's own records, no state file);
  * otherwise -> dispatch one cloud pass. The machine is beating again.

It can never cause a pile-up: it only fires when cadence is BEHIND,
and it refuses while a sibling exists. If every cron firing fails and
the chain is dead, the watchdog is the one that brings it back.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import psx_core.paths as paths  # noqa: E402
import psx_core.sessions as sessions  # noqa: E402
import heartbeat  # noqa: E402

WATCH_INTERVAL_MIN = 16.0   # metadata staleness fallback (no heartbeat yet)
KEEP_INTERVAL_MIN = 12.0    # heartbeat older than this -> cadence behind
RECENT_CREATION_MIN = 6.0   # a pass created this recently -> let it run
DAILY_RUN_BUDGET = 60       # hard ceiling: all cloud-intraday runs/day


def _print(*args: object) -> None:
    print(*args, flush=True)


def _api(method: str, url: str, token: str, payload: dict | None = None):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def decide(
    runs: list[dict], now: datetime, hb_age_min: float | None = None
) -> str:
    """Pure decision core - testable without any API.

    `runs`: this workflow's runs, newest first. `hb_age_min`: minutes
    since the last REAL pass per data/heartbeat.json (None = unknown).

    Trust order (2026-09-16 incident): a SKIPPED pass concludes
    "success" in run metadata, so metadata can report a healthy bot
    that is actually dead. The heartbeat is written only by a pass
    that actually polled/exited/decided, so it is checked FIRST;
    metadata is only the fallback for the very first boot of a repo
    that has no heartbeat yet.
    """
    # ---- Layer 1: the heartbeat (ground truth) ----------------------
    if hb_age_min is not None:
        if hb_age_min < KEEP_INTERVAL_MIN:
            return (
                f"healthy (real pass heartbeat {hb_age_min:.1f} min old "
                f"< {KEEP_INTERVAL_MIN:g})"
            )
        return _rescue_or_wait(runs, now, hb_age_min, "heartbeat")

    # ---- Layer 2: metadata fallback (pre-heartbeat boot only) -------
    completed_ok = [
        r for r in runs
        if r.get("status") == "completed"
        and r.get("conclusion") in ("success", "neutral")
    ]
    if not completed_ok:
        return "dispatch"  # nothing has ever succeeded today: boot

    newest_ok = max(
        datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        for r in completed_ok
    )
    age_min = (now - newest_ok).total_seconds() / 60.0
    if age_min < WATCH_INTERVAL_MIN:
        return (
            f"healthy (newest successful pass {age_min:.1f} min old "
            f"< {WATCH_INTERVAL_MIN:g} - metadata; heartbeat absent)"
        )
    return _rescue_or_wait(runs, now, age_min, "metadata")


def _rescue_or_wait(
    runs: list[dict], now: datetime, age_min: float, source: str
) -> str:
    """Cadence is behind: guard against pile-ups and budget, then fire."""
    recent_cutoff = now - timedelta(minutes=RECENT_CREATION_MIN)
    if any(
        datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        >= recent_cutoff
        for r in runs
    ):
        return (
            "waiting (cadence behind but a pass was created within "
            f"{RECENT_CREATION_MIN:g} min - queued/starting)"
        )

    # Budget: count ALL of today's runs (any conclusion), from GitHub's
    # own records - no state file to lose or clobber.
    today_count = sum(
        1
        for r in runs
        if datetime.fromisoformat(
            r["created_at"].replace("Z", "+00:00")
        ).date() == now.date()
    )
    if today_count >= DAILY_RUN_BUDGET:
        return f"capped ({today_count} runs today >= {DAILY_RUN_BUDGET})"

    return f"dispatch (real pass {age_min:.1f} min old per {source})"


def main() -> int:
    paths.enable_utf8_stdout()
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not (token and repo):
        _print("watchdog: not running inside Actions - nothing to do.")
        return 0

    now = datetime.now(timezone.utc)
    if not sessions.is_open(now):
        _print("watchdog: market closed - nothing to do.")
        return 0

    status, data = _api(
        "GET",
        f"https://api.github.com/repos/{repo}/actions"
        f"/workflows/cloud-intraday.yml/runs?per_page=100",
        token,
    )
    if status != 200 or not data:
        _print(f"watchdog: could not list runs (HTTP {status}).")
        return 0
    runs = data.get("workflow_runs", [])

    hb_age = heartbeat.read_age()
    verdict = decide(runs, now, hb_age)
    if not verdict.startswith("dispatch"):
        _print(f"watchdog: {verdict} - no action.")
        return 0

    status, _ = _api(
        "POST",
        f"https://api.github.com/repos/{repo}/actions"
        f"/workflows/cloud-intraday.yml/dispatches",
        token,
        {"ref": "master"},
    )
    if status in (200, 204):
        _print(f"watchdog: {verdict} - rescue pass dispatched.")
    else:
        _print(f"watchdog: dispatch refused (HTTP {status}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
