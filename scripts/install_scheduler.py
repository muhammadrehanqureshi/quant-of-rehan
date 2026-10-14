"""Register the local notification scheduler to start at login (SO-9).

Creates a Windows scheduled task "quant-of-rehan-scheduler" that runs
python -m src.notify.schedule_runner in the repo root at owner logon.
Idempotent: registering twice replaces the task. Removing:

    schtasks /delete /tn "quant-of-rehan-scheduler" /f

SO-12 (owner order 2026-10-14) parks this path. The Cloudflare relay's own
cron already delivers the owner's open and close texts with his PC off, so a
logon task that keeps a process resident all day was spending his machine on
work the edge already does. main() now refuses to register unless the owner
asked for this exact run; the removal command above stays available, because
taking the task away is the repair, not the offence.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_owner_requested  # noqa: E402

TASK = "quant-of-rehan-scheduler"


def main() -> int:
    guard_owner_requested("scripts/install_scheduler.py")
    python = sys.executable
    cmd = (
        f'schtasks /create /tn "{TASK}" /tr '
        f'"\\"{python}\\" -m src.notify.schedule_runner" '
        f'/sc onlogon /rl limited /f'
    )
    print("registering:", cmd)
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
