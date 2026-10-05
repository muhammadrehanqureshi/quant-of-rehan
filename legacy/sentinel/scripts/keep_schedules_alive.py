"""Cycle every workflow disable->enable so GitHub re-registers crons.

GitHub's scheduler can stop firing a repo's crons after an outage and
NEVER resumes them (community discussion 206019). Re-saving the
workflow files would also work, but the repo's own token cannot push
workflow-file changes (that needs a `workflows` permission the
workflow_permissions block cannot grant - proved 2026-10-01 10:25
PKT). The API cure needs only `actions: write`, which GITHUB_TOKEN
CAN carry: disable each workflow, re-enable it, and GitHub rebuilds
the schedule registry. This is exactly the manual hammer that worked
at 15:5x PKT today, done mechanically.

Run via the schedule-keep-alive workflow (weekly) or on demand.
"""
from __future__ import annotations

import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / ".github" / "workflows"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")


def api(method: str, path: str) -> tuple[int, str]:
    req = urllib.request.Request(
        f"https://api.github.com{path}", method=method
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def main() -> int:
    if not (REPO and TOKEN):
        print("need GITHUB_REPOSITORY and a token - nothing cycled")
        return 1
    ok, failed = 0, []
    for wf in sorted(WF_DIR.glob("*.yml")):
        name = wf.name
        c1, _ = api("PUT", f"/repos/{REPO}/actions/workflows/{name}/disable")
        c2, body = api("PUT", f"/repos/{REPO}/actions/workflows/{name}/enable")
        if c1 in (204, 200) and c2 in (204, 200):
            ok += 1
        else:
            failed.append(f"{name} (disable={c1} enable={c2})")
    print(f"cycled {ok}/{ok + len(failed)} workflows disable->enable")
    if failed:
        print("FAILED:", "; ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
