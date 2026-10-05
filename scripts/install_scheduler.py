"""Register the local notification scheduler to start at login (SO-9).

Creates a Windows scheduled task "quant-of-rehan-scheduler" that runs
python -m src.notify.schedule_runner in the repo root at owner logon.
Idempotent: registering twice replaces the task. Removing:

    schtasks /delete /tn "quant-of-rehan-scheduler" /f
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASK = "quant-of-rehan-scheduler"


def main() -> int:
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
