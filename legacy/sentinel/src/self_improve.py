"""
Self-improvement trigger - the bot tunes ITSELF on a schedule of
evidence, not of calendar.

Contract: after each session's close-out, count the labeled trades in
the outcomes ledger. When (a) the ledger has at least MIN_LABELS
labels and (b) at least STEP labels have accumulated since the last
dispatched sweep, fire the "cloud backtest sweep" workflow via the
GitHub API so the walk-forward analysis runs on GitHub's machines.
A marker file (data/last_autotune.json) makes the trigger idempotent:
the same label count never fires twice, and a failed dispatch leaves
the marker untouched so the next close-out retries.

Runs inside the cloud close-out (which has GITHUB_TOKEN with
actions:write). On a machine without a token it logs and skips - the
trigger never blocks bookkeeping.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths  # noqa: E402

MIN_LABELS = 30   # first walk-forward sweep at 30 labeled trades
STEP = 15         # re-sweep after every 15 additional labels
MARKER = "last_autotune.json"
WORKFLOW = "cloud-backtest.yml"


def count_labels() -> int:
    """Valid labeled trades in the outcomes ledger."""
    ledger = paths.DATA_DIR / "outcomes.jsonl"
    if not ledger.exists():
        return 0
    n = 0
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("entry_time") and r.get("symbol"):
            n += 1
    return n


def _marker_path() -> Path:
    return paths.DATA_DIR / MARKER


def _load_marker() -> dict:
    f = _marker_path()
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def should_trigger(count: int | None = None,
                   marker: dict | None = None) -> tuple[bool, str]:
    """(fire?, reason) for the current ledger and marker state."""
    count = count_labels() if count is None else count
    marker = _load_marker() if marker is None else marker
    last = int(marker.get("labels", 0))
    if count < MIN_LABELS:
        return False, f"{count} labels < first sweep threshold {MIN_LABELS}"
    if count - last < STEP:
        return False, f"{count - last} new labels since last sweep (< {STEP})"
    return True, f"{count} labels, {count - last} new since last sweep"


def dispatch_workflow() -> tuple[bool, str]:
    """Fire the cloud backtest workflow. (ok, message)."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return False, "no GITHUB_TOKEN/GITHUB_REPOSITORY - not on Actions"
    try:
        import requests
        resp = requests.post(
            f"https://api.github.com/repos/{repo}/actions/workflows/"
            f"{WORKFLOW}/dispatches",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            json={"ref": "master"},
            timeout=30,
        )
        if resp.status_code == 204:
            return True, "cloud backtest sweep dispatched"
        return False, f"dispatch failed: HTTP {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, f"dispatch error: {exc}"


def maybe_trigger() -> tuple[bool, str]:
    """Called after each close-out. Fires the sweep when earned."""
    fire, reason = should_trigger()
    if not fire:
        return False, reason
    ok, msg = dispatch_workflow()
    if ok:
        marker = _load_marker()
        marker["labels"] = count_labels()
        marker["when"] = datetime.now(timezone.utc).isoformat()
        _marker_path().write_text(
            json.dumps(marker, indent=2), encoding="utf-8"
        )
        return True, f"self-improve: {msg} ({reason})"
    return False, f"self-improve deferred: {msg} ({reason})"
