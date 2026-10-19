"""Usage example: wrap a task with the 2 percent governor.

    python examples/resource_governor_demo.py
    python examples/resource_governor_demo.py --cpu-seconds 0.1 --chunks 4

The task here is arithmetic, not market data, because the point is the
accounting rather than the result. It burns a measured amount of CPU in
chunks; the governor sleeps between chunks to hold the average at or under
two percent, then the script reads the measured utilization back from
``snapshot()`` and fails if the cap was broken.

Asking for a higher intensity is the second half of the contract:

    python examples/resource_governor_demo.py --intensity 25

That prints the approval request. On a real terminal the owner answers it;
piped or from a runner there is nobody to ask, so the run drops back to two
percent and says so. Nothing is ever silently sped up.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ci.resource_governor import (  # noqa: E402
    MAX_CPU_PERCENT,
    GovernorPolicy,
    ResourceGovernor,
)


def burn_cpu(seconds: float) -> int:
    """Spin in pure Python until this process has spent ``seconds`` of CPU.

    Measured rather than assumed: the loop asks the same clock the governor
    reads, so the demo cannot overstate or understate what it cost.
    """
    start = time.process_time()
    rounds = 0
    while time.process_time() - start < seconds:
        sum(i * i for i in range(500))
        rounds += 1
    return rounds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-seconds", type=float, default=0.05,
                        help="total CPU seconds to spend (default 0.05)")
    parser.add_argument("--chunks", type=int, default=5,
                        help="how many units to split that into (default 5)")
    parser.add_argument("--intensity", type=float, default=None,
                        help="percent to ask for; above 2 needs approval")
    args = parser.parse_args(argv)
    if args.chunks < 1 or args.cpu_seconds <= 0:
        parser.error("--cpu-seconds must be positive and --chunks at least 1")

    governor = ResourceGovernor(GovernorPolicy())
    per_chunk = args.cpu_seconds / args.chunks
    print(f"machine load before start: {_load():.1f} percent busy")
    print(f"asking for {args.cpu_seconds:g} CPU seconds in {args.chunks} chunks "
          f"at {args.intensity or MAX_CPU_PERCENT:g} percent")

    rounds = governor.chunked(
        range(args.chunks),
        lambda _: burn_cpu(per_chunk),
        label="demo arithmetic",
        estimated_cpu_seconds=args.cpu_seconds,
        requested_percent=args.intensity,
        reason="usage example for the resource governor",
    )

    stats = governor.snapshot()
    print("stats:", stats)
    print(f"rounds: {sum(rounds)}")
    # An approved escalation IS the cap for that block; without one the cap is
    # the owner's ceiling. The check has to follow the authority that applied,
    # or an approved 25 percent run would be scored against 2 percent.
    allowed = (stats["escalations"][0]["percent"] if stats["escalations"]
               else MAX_CPU_PERCENT)
    if stats["utilization_percent"] > allowed + 0.05:
        print(f"FAIL: measured {stats['utilization_percent']} percent, "
              f"above the {allowed:g} percent cap that applied", file=sys.stderr)
        return 1
    print(f"PASS: measured {stats['utilization_percent']} percent of one core, "
          f"cap {allowed:g} percent")
    return 0


def _load() -> float:
    try:
        from src.ci.resource_governor import system_load_percent
        return system_load_percent()
    except Exception:  # noqa: BLE001 - a reading is never worth failing on
        return float("nan")


if __name__ == "__main__":
    raise SystemExit(main())
