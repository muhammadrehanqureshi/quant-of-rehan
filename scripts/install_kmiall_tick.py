#!/usr/bin/env python3
"""Register (or remove) the local 5-minute KMIALL scanner task on Windows.

Creates a Task Scheduler task that runs scripts/kmiall_tick.py every
TICK_INTERVAL_MINUTES, all day, for the current user. The task itself knows
nothing about market sessions: the tick script pauses when the market is shut,
so the task can safely fire around the clock and there is no scheduler state to
keep in step with the PSX calendar.

The task is deliberately registered with an ABSOLUTE interpreter path and an
absolute script path, and the tick computes the repository root from its own
file location, so it does not depend on a working directory that Task Scheduler
would otherwise have to be told about.

    python scripts/install_kmiall_tick.py            # create / replace
    python scripts/install_kmiall_tick.py --remove   # delete
    python scripts/install_kmiall_tick.py --show     # query current definition
    python scripts/install_kmiall_tick.py --print    # print the command only
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402

TASK = "quant-of-rehan-kmiall-tick"
TICK_SCRIPT = ROOT / "scripts" / "kmiall_tick.py"


def create_command() -> list[str]:
    """The schtasks command, as an argv list (no shell quoting games)."""
    interval = int(config.TICK_INTERVAL_MINUTES)
    action = f'"{sys.executable}" "{TICK_SCRIPT}"'
    return [
        "schtasks", "/create", "/tn", TASK,
        "/tr", action,
        "/sc", "MINUTE", "/mo", str(interval),
        "/rl", "LIMITED",
        "/f",
    ]


def run(argv: list[str]) -> int:
    print("running:", " ".join(argv))
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"could not run schtasks: {type(exc).__name__}: {exc}")
        return 5
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if output:
        print(output)
    if error:
        print(error, file=sys.stderr)
    if result.returncode != 0:
        print(f"schtasks exit {result.returncode}. If this is an access error, "
              f"create the task once from an elevated shell, or open Task "
              f"Scheduler and import a task running:\n  {create_command()[-1]}")
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="install the KMIALL tick task")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--remove", action="store_true",
                       help="delete the scheduled task")
    group.add_argument("--show", action="store_true",
                       help="query the scheduled task as it stands")
    group.add_argument("--print", dest="print_only", action="store_true",
                       help="print the command without running it")
    args = parser.parse_args(argv)

    if not TICK_SCRIPT.is_file():
        print(f"missing tick script: {TICK_SCRIPT}", file=sys.stderr)
        return 2

    if args.print_only:
        print(" ".join(create_command()))
        return 0
    if args.remove:
        return run(["schtasks", "/delete", "/tn", TASK, "/f"])
    if args.show:
        return run(["schtasks", "/query", "/tn", TASK, "/v", "/fo", "LIST"])
    return run(create_command())


if __name__ == "__main__":
    raise SystemExit(main())
