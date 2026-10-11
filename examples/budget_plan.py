"""How the scan interval adapts as the month burns, printed day by day.

Run from the repo root:

    python examples/budget_plan.py
    python examples/budget_plan.py --month 2026-02

The walk assumes a burn that tracks the standing cadence (about 44.2 billed
minutes a day: capture at 108.7 fires a month plus the two fixed workflows),
then shows the two cases worth watching:

* the audit's own day, 2026-10-10 with 1,369 minutes already burned: the
  standing cadence no longer fits, so the scheduler stretches the scan;
* a burst day, where the same date with more minutes burned scans slower.

Nothing here touches the network or the owner's state files.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.budget import (  # noqa: E402
    CAPTURE_WORKFLOW,
    MONTHLY_BUDGET_MINUTES,
    BudgetState,
    adaptive_interval_minutes,
    allowed_fires_for,
    default_workflow_costs,
    month_days,
    reset_date,
)

#: Billed minutes a day at the standing fingerprint (1,369.2 a month).
STANDING_DAILY_BURN = 1369.2 / 31


def plan_for(reference: date, used: int) -> BudgetState:
    return BudgetState(
        reference=reference,
        monthly_budget_minutes=MONTHLY_BUDGET_MINUTES,
        minutes_already_billed=used,
        workflow_costs=default_workflow_costs(),
    )


def walk(anchor: date) -> None:
    first = reset_date(anchor)
    days = month_days(anchor)
    print(f"Adaptive scan plan for {first.strftime('%B %Y')}")
    print(f"Ceiling {MONTHLY_BUDGET_MINUTES:,} min, "
          f"{days} days, standing burn "
          f"{STANDING_DAILY_BURN:.1f} min/day")
    print()
    header = (f"{'date':<12}{'used':>7}{'runway':>8}{'fires':>7}"
              f"{'one scan every':>16}{'around the clock':>18}")
    print(header)
    print("-" * len(header))
    for offset in range(days):
        day = first.fromordinal(first.toordinal() + offset)
        used = round(STANDING_DAILY_BURN * offset)
        state = plan_for(day, used)
        fires = allowed_fires_for(state, CAPTURE_WORKFLOW)
        interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
        wall = adaptive_interval_minutes(state, CAPTURE_WORKFLOW,
                                        within_sessions=False)
        session = "closed" if interval is None else f"{interval} min"
        wall_text = "closed" if wall is None else f"{wall} min"
        print(f"{day.isoformat():<12}{used:>7,}"
              f"{state.adaptive_budget_minutes:>8,}{fires:>7}"
              f"{session:>16}{wall_text:>18}")
    print()


def case(title: str, reference: date, used: int) -> None:
    state = plan_for(reference, used)
    interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
    print(f"{title}: {reference.isoformat()} with {used:,} min burned")
    print(f"  remaining {state.minutes_remaining:,} min, "
          f"fixed ahead {state.fixed_minutes_remaining:,} min, "
          f"buffer ahead {state.buffer_minutes:,} min, "
          f"runway {state.adaptive_budget_minutes:,} min")
    cadence = "never (no runway)" if interval is None else f"every {interval} min"
    print(f"  affordable fires {allowed_fires_for(state, CAPTURE_WORKFLOW)}, "
          f"one scan {cadence}")
    print()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="budget_plan")
    ap.add_argument("--month", default="2026-10",
                    help="Any date inside the month to walk (default 2026-10).")
    args = ap.parse_args(argv)
    anchor = date.fromisoformat(args.month + "-01") \
        if len(args.month) == 7 else date.fromisoformat(args.month)

    walk(anchor)
    case("Audit day", date(2026, 10, 10), 1369)
    case("Burst on the same day", date(2026, 10, 10), 1400)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
