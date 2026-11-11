"""Run the session failsafe once: read the relay, restart the band if it is dead.

Owner order 2026-11-11: Quant of Rehan must always scan the pre and post market.
The workflow that calls this script fires on the clock every ten minutes while a
window is open; the script decides once, dispatches the band loop if the feed is
dead or the relay is silent, and exits. It is never a daemon and it sleeps for
nothing, so it cannot become work on the owner's PC.

Why a second dispatcher exists at all: the relay's own watchdog restarts a band
whose capture died, but it can only do that while the relay is answering. A
GitHub schedule that never arrived, and a relay that is unreachable, both leave
nobody watching. This is that watcher, from the other side.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import failsafe  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

BASE = (os.environ.get("RELAY_URL")
        or "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev").rstrip("/")
API = "https://api.github.com"
WORKFLOW = "intraday-session.yml"
REF = os.environ.get("FAILSAFE_REF", "master")


def read(path: str, attempts: int = 3, timeout: float = 20.0):
    """Read one relay route, or None when every attempt failed.

    No sleep between attempts on purpose: the three attempts are what turn one
    busy instant into a retry instead of an alert, and a paced wait in a
    scheduled job is a wait the owner's rules do not allow.
    """
    last: Exception | None = None
    for _ in range(attempts):
        try:
            with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001 - the reason is logged below
            last = exc
    print(f"failsafe: {path} did not answer after {attempts} attempts "
          f"({type(last).__name__ if last else 'unknown'})", flush=True)
    return None


def api(token: str, method: str, path: str, body: dict | None = None):
    """One GitHub API call. Returns the decoded answer, or None on failure."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "quant-of-rehan-failsafe")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8").strip()
            return json.loads(raw) if raw else {}
    except Exception as exc:  # noqa: BLE001 - reported by the caller
        print(f"failsafe: GitHub {method} {path} failed "
              f"({type(exc).__name__})", flush=True)
        return None


def band_running(token: str, repo: str) -> bool:
    """True when a band job is already in flight, so a second one is skipped."""
    answer = api(token, "GET",
                 f"/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
                 "?status=in_progress&per_page=1")
    if not isinstance(answer, dict):
        return False
    return int(answer.get("total_count") or 0) > 0


def notify(text: str) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from src.notify.owner_email import send

    day = datetime.now(ZoneInfo("Asia/Karachi")).date().isoformat()
    send(text, f"failsafe-relay:{day}")


def main(argv: list[str] | None = None) -> int:
    moment = now_karachi()
    health = read("/health")
    flow = read("/flow")
    decision = failsafe.decide(moment, health, flow)
    print(f"failsafe: {decision.reason}", flush=True)
    if not decision.dispatch:
        return 0
    if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        print("failsafe: not a cloud job, so nothing is dispatched", flush=True)
        return 0
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("failsafe: no GitHub token or repository, so nothing is "
              "dispatched", flush=True)
        return 1
    if band_running(token, repo):
        print("failsafe: a band job is already running, so no second one is "
              "started", flush=True)
        return 0
    answer = api(token, "POST",
                 f"/repos/{repo}/actions/workflows/{WORKFLOW}/dispatches",
                 {"ref": REF, "inputs": {
                     "seconds": str(failsafe.DISPATCH_SECONDS)}})
    if answer is None:
        print("failsafe: the dispatch was refused, so the next fire retries it",
              flush=True)
        return 1
    print(f"failsafe: dispatched {WORKFLOW} for "
          f"{failsafe.DISPATCH_SECONDS} s at {moment:%H:%M} PKT", flush=True)
    if decision.alert:
        notify(
            "Quant of Rehan relay did not answer /health three times at "
            f"{moment:%H:%M} PKT on {moment:%Y-%m-%d}. The band loop was "
            "dispatched again from GitHub so the session is still scanned, but "
            "the card and the order flow cannot update until the relay "
            "answers. This alert repeats at most once a day."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
