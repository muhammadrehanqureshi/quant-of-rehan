"""Watch for any tick fire while the market is closed (owner report harness).

Started after the task was re-registered with session-window triggers. Samples
every 200ms and records:

  * any python/pythonw process whose command line mentions kmiall_tick, which is
    what a scheduled fire would look like;
  * the tick log's line count, which grows on every fire (a fire always logs at
    least "tick start").

A closed day must produce nothing at all. The previous registration fired every
4 minutes around the clock, so a window of several minutes spans at least one
would-be fire.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "logs" / "kmiall_tick.log"
OUT = ROOT / "tmp" / "no_fire_watch.json"
SECONDS = 420.0
SAMPLE = 0.2


def tick_processes() -> list[str]:
    ps = ("Get-CimInstance Win32_Process | "
          "Where-Object { $_.CommandLine -like '*kmiall_tick*' } | "
          "ForEach-Object { $_.Name + '|' + $_.ProcessId }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, errors="replace")
    return [line.strip() for line in (r.stdout or "").splitlines() if line.strip()]


def log_lines() -> int:
    if not LOG.is_file():
        return 0
    with LOG.open(encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def main() -> int:
    start_lines = log_lines()
    found: list[dict] = []
    deadline = time.monotonic() + SECONDS
    samples = 0
    while time.monotonic() < deadline:
        seen = tick_processes()
        samples += 1
        if seen:
            found.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "processes": seen})
        time.sleep(SAMPLE)
    result = {
        "watched_seconds": SECONDS,
        "samples": samples,
        "started_log_lines": start_lines,
        "ended_log_lines": log_lines(),
        "fires_detected": found,
        "verdict": ("no fire at all" if not found
                    and log_lines() == start_lines
                    else "a fire happened"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
