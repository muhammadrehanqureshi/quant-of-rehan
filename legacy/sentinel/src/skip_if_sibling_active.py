"""
Workflow step: stand down if a sibling cloud pass is already
queued/running. Writes SKIP=true to $GITHUB_ENV so later steps (pip
install, the pass itself) are skipped - saving ~90s of runner minutes
and, more importantly, preventing a stale-tree commit racing the
active sibling. Kept as a file because multi-line python inside a
workflow `run: |` block is a YAML trap (v0.15.6 incident).
"""
from __future__ import annotations

import json
import os
import urllib.request


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    me = os.environ.get("GITHUB_RUN_ID", "")
    env_file = os.environ.get("GITHUB_ENV", "")
    if not (token and repo):
        print("skip-check: no repo/token context - proceeding.")
        return 0

    url = (
        f"https://api.github.com/repos/{repo}/actions"
        f"/workflows/cloud-intraday.yml/runs?per_page=10"
    )
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            runs = json.loads(resp.read().decode()).get("workflow_runs", [])
    except Exception as exc:  # noqa: BLE001 - fail open, let the pass run
        print(f"skip-check: API unavailable ({exc}) - proceeding.")
        return 0

    active = sum(
        1
        for r in runs
        if str(r["id"]) != str(me)
        and r.get("status") in ("queued", "in_progress", "waiting")
    )
    # Grace: a run created seconds ago may not appear in the API list
    # yet. If the newest pass started less than GRACE_MIN ago, treat
    # that as a probable in-flight sibling and stand down (the
    # 09:25 collision: two dispatches 75s apart, the second blind to
    # the first).
    GRACE_MIN = 3.0
    import datetime as _dt

    newest = None
    for r in runs:
        if str(r["id"]) == str(me):
            continue
        try:
            created = _dt.datetime.fromisoformat(
                r["created_at"].replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if newest is None or created > newest:
            newest = created
    within_grace = False
    if newest is not None:
        now = _dt.datetime.now(_dt.timezone.utc)
        within_grace = (now - newest).total_seconds() < GRACE_MIN * 60

    if active or within_grace:
        if active:
            print(f"Sibling pass active ({active}) - this pass stands down.")
        else:
            print(
                f"Newest pass started < {GRACE_MIN:g} min ago - probable "
                "in-flight sibling (API lag), standing down."
            )
        if env_file:
            with open(env_file, "a", encoding="utf-8") as fh:
                fh.write("SKIP=true\n")
        return 0
    print("No sibling active - proceeding with the pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
