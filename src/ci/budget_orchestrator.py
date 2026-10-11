"""Run the adaptive budget scheduler against live or known GitHub usage.

This is the monitoring tool: it consumes the cycle's elapsed minutes and the
ceiling, then reports how often the capture workflow may scan for the rest of
the cycle without crossing 2,000 minutes.

Two modes, both supported on purpose:

1. Live mode. Fetch the billing figures from GitHub's own billing endpoint
   (inside GitHub Actions, against the account that owns the budget) and run
   the scheduler on the real numbers.

2. Known-info mode. When the endpoint is not available for the account type,
   supply the measured minutes and the cycle end on the command line. The
   scheduler still runs, it just does not read its inputs from the API.

Either way the tool never dials out from anywhere but GitHub's own billing
endpoint for the same account, so no external credential or third-party
dependency is introduced.

Usage::

    python -m src.ci.budget_orchestrator --today 2026-10-10
    python -m src.ci.budget_orchestrator --known-used 1369 --period-end 2026-10-31
    python -m src.ci.budget_orchestrator --known-used 1369 --json

Exit codes: 0 when the standing cadence fits, 1 when adaptation is needed,
2 when no usable usage figure could be obtained.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ci.budget import (  # noqa: E402
    CAPTURE_WORKFLOW,
    MONTHLY_BUDGET_MINUTES,
    BudgetState,
    GitHubUsage,
    adaptive_interval_minutes,
    allowed_fires_for,
    build_budget_state,
    default_workflow_costs,
    fits_at_current_cadence,
    month_end,
    next_reset_date,
    projected_burn_at_cadence,
    recommended_static_cron_for,
    remaining_fires_at_cadence,
    WorkflowCost,
)

FITS_EXIT = 0
ADAPT_EXIT = 1
NO_DATA_EXIT = 2


def resolve_today(raw: str | None) -> date:
    """Parse a YYYY-MM-DD argument (argparse type)."""
    if raw is None:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"cannot parse {raw!r} as YYYY-MM-DD: {exc}")


def _gh_api(path: str, *, jq: str | None = None) -> Any:
    """One ``gh api`` GET. Raises RuntimeError on any failure."""
    argv = ["gh", "api", path, "--method", "GET"]
    if jq:
        argv += ["--jq", jq]
    try:
        result = subprocess.run(argv, capture_output=True, text=True,
                                timeout=20)
    except FileNotFoundError:
        raise RuntimeError("gh is not on PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gh api {path} timed out")
    if result.returncode != 0:
        raise RuntimeError(
            f"gh api {path} exited {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}")
    if jq:
        return result.stdout.strip()
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh api {path} returned non-JSON: {exc}")


def live_usage(*, today: date, quiet: bool = False) -> GitHubUsage | None:
    """Read this cycle's usage from GitHub's billing endpoint.

    Returns ``None`` (never raises) when the endpoint cannot be read, so the
    caller can fall back to a supplied measurement. The billing response has
    no period of its own, so the calendar month around ``today`` is used.
    """
    try:
        login = _gh_api("user", jq=".login")
        if not login:
            raise RuntimeError("could not resolve the account login")
        # Personal accounts expose usage under users/<login>; an org-owned
        # repo needs its org endpoint, which is left to known-info mode.
        payload = _gh_api(f"users/{login}/settings/billing/actions")
    except RuntimeError as exc:
        if not quiet:
            print(f"GitHub billing endpoint unavailable: {exc}",
                  file=sys.stderr)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return GitHubUsage.from_billing_payload(payload, today=today)
    except (ValueError, TypeError, KeyError) as exc:
        if not quiet:
            print(f"GitHub billing payload unusable: {exc}", file=sys.stderr)
        return None


def print_decisions(state: BudgetState, usage: GitHubUsage) -> int:
    """Print the scheduler's decisions and return the process exit code.

    Returns 0 when the standing cadence fits the remaining runway, 1 when
    adaptation is needed so an outer monitor can alert, 2 when the state has
    no capture fingerprint to plan for.
    """
    if not any(wc.name == CAPTURE_WORKFLOW for wc in state.workflow_costs):
        print("No capture workflow fingerprint in state.", file=sys.stderr)
        return NO_DATA_EXIT

    used = usage.total_minutes_used
    pct = used / usage.total_minutes_limit * 100 if usage.total_minutes_limit \
        else 0.0
    projection = state.projected_month_minutes
    projection_pct = (projection / state.monthly_budget_minutes * 100
                      if state.monthly_budget_minutes else 0.0)

    print(f"=== GitHub Actions budget, {state.reference.isoformat()} ===")
    print(f"Billing cycle: {usage.period_start.isoformat()} to "
          f"{usage.period_end.isoformat()} "
          f"({usage.cycle_days} days; {state.days_left_in_cycle} left; "
          f"next reset {next_reset_date(state.reference).isoformat()})")
    print(f"Usage this cycle: {used:,} min of "
          f"{usage.total_minutes_limit:,} ({pct:.1f}%); "
          f"{state.minutes_remaining:,} min remaining")
    print(f"Standing full-cycle projection: {projection:,.1f} min "
          f"({projection_pct:.1f}%), "
          f"{state.projected_remaining_minutes:,.1f} min to spare")
    print()
    print(f"Fixed workflows still ahead: {state.fixed_minutes_remaining:,} "
          f"min (signal push + governance guard)")
    print(f"Spike buffer still ahead: {state.buffer_minutes:,} min "
          f"({state.buffer_reservation_minutes:,} min/cycle, prorated to "
          f"{state.days_left_in_cycle} days)")
    print(f"Capture runway for the rest of the cycle: "
          f"{state.adaptive_budget_minutes:,} min")
    print()

    fires = allowed_fires_for(state, CAPTURE_WORKFLOW)
    interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
    wall_interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW,
                                              within_sessions=False)
    cadence_fires = remaining_fires_at_cadence(state, CAPTURE_WORKFLOW)
    cadence_burn = projected_burn_at_cadence(state, CAPTURE_WORKFLOW)
    cost = _capture_cost(state)
    fits = fits_at_current_cadence(state, CAPTURE_WORKFLOW)

    if state.session_minutes_available > 0:
        print(f"Sessions left: {state.trading_days_available} trading days, "
              f"{state.session_minutes_available:,} session minutes")
    if interval is not None:
        print(f"Affordable capture fires: {fires} at {cost} min/fire "
              f"(the last few are held back as margin)")
        print(f"Adaptive cadence: one scan every {interval} min of session "
              f"time ({wall_interval} min around the clock)")
    else:
        print("Affordable capture fires: 0")
    print()

    if fits:
        print("Verdict: capture's standing cadence FITS the runway for the "
              f"rest of the cycle ({cadence_burn:,.0f} min against "
              f"{state.adaptive_budget_minutes:,} min).")
        if interval is not None:
            print(f"It implies {cadence_fires:.1f} fires at the standing rate; "
                  f"up to {fires} are affordable, so no adaptation is needed.")
        return FITS_EXIT

    print("Verdict: adaptation needed. The standing cadence would bill "
          f"{cadence_burn:,.0f} min against {state.adaptive_budget_minutes:,} "
          "min of runway.")
    if interval is None:
        print("Recommendation: stop the capture workflow until the reset on "
              f"{next_reset_date(state.reference).isoformat()}; nothing is "
              "affordable for the rest of this cycle.")
        return ADAPT_EXIT

    print(f"Recommendation: stretch capture to one scan every {interval} min "
          f"of session time for the rest of the cycle ({fires} fires at "
          f"{cost} min each).")
    crons = recommended_static_cron_for(state, CAPTURE_WORKFLOW)
    if crons:
        print(f"Nearest static approximation: keep {len(crons)} of the "
              "standing cron entries (each entry fires on every matching "
              "weekday):")
        for cron in crons:
            print(f"  - cron: {cron!r}")
    else:
        print("No static cron entry fits this runway: keep capture out of "
              "Actions for the rest of the cycle.")
    print("For a finer cadence than a static cron can express, run the "
          "capture job on the local always-on runner at the computed "
          "interval instead.")
    return ADAPT_EXIT


def plan_as_dict(state: BudgetState, usage: GitHubUsage) -> dict[str, Any]:
    """Machine-readable plan, for a run summary or an outer monitor."""
    fires = allowed_fires_for(state, CAPTURE_WORKFLOW)
    return {
        "reference": state.reference.isoformat(),
        "cycle_start": usage.period_start.isoformat(),
        "cycle_end": usage.period_end.isoformat(),
        "cycle_days": usage.cycle_days,
        "days_left": state.days_left_in_cycle,
        "minutes_used": usage.total_minutes_used,
        "minutes_limit": usage.total_minutes_limit,
        "minutes_remaining": state.minutes_remaining,
        "projected_month_minutes": round(state.projected_month_minutes, 1),
        "projected_remaining_minutes":
            round(state.projected_remaining_minutes, 1),
        "fixed_minutes_remaining": state.fixed_minutes_remaining,
        "buffer_minutes": state.buffer_minutes,
        "capture_runway_minutes": state.adaptive_budget_minutes,
        "trading_days_left": state.trading_days_available,
        "session_minutes_left": state.session_minutes_available,
        "fires_affordable": fires,
        "interval_minutes": adaptive_interval_minutes(
            state, CAPTURE_WORKFLOW),
        "interval_minutes_wall_clock": adaptive_interval_minutes(
            state, CAPTURE_WORKFLOW, within_sessions=False),
        "fits_current_cadence": fits_at_current_cadence(
            state, CAPTURE_WORKFLOW),
        "projected_burn_at_cadence": round(
            projected_burn_at_cadence(state, CAPTURE_WORKFLOW), 1),
        "next_reset": next_reset_date(state.reference).isoformat(),
        "suggested_crons": recommended_static_cron_for(
            state, CAPTURE_WORKFLOW),
    }


def _capture_cost(state: BudgetState) -> int:
    for wc in state.workflow_costs:
        if wc.name == CAPTURE_WORKFLOW:
            return wc.billed_minutes_per_fire
    return 0


def _override_workflow_costs(path: Path) -> list[WorkflowCost]:
    """Read a JSON array of workflow-cost objects, replacing the fingerprint.

    Each entry needs at least ``name``; every other field falls back to a
    conservative default. Unknown workflow names are rejected downstream by
    ``_apply_overrides``, so the file may not invent a workflow.
    """
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, list):
        raise ValueError("workflow-costs-json must be a JSON array of objects")
    costs: list[WorkflowCost] = []
    for entry in blob:
        if not isinstance(entry, dict):
            raise ValueError("workflow-costs-json must be a JSON array of "
                             "objects")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise ValueError("each override object needs a non-empty name")
        costs.append(WorkflowCost(
            name=name,
            fires_per_month=float(entry.get("fires_per_month", 1.0)),
            billed_minutes_per_fire=int(entry.get("billed_minutes_per_fire", 1)),
            can_adapt=bool(entry.get("can_adapt", False)),
            min_interval_minutes=(
                int(entry["min_interval_minutes"])
                if entry.get("min_interval_minutes") is not None else None),
            max_interval_minutes=(
                int(entry["max_interval_minutes"])
                if entry.get("max_interval_minutes") is not None else None),
        ))
    return costs


def _apply_overrides(state: BudgetState, path: Path) -> BudgetState:
    """Return a state whose fingerprint is replaced by the override file."""
    overrides = _override_workflow_costs(path)
    known = {wc.name for wc in state.workflow_costs}
    for cost in overrides:
        if cost.name not in known:
            raise ValueError(
                f"workflow-costs-json names unknown workflow {cost.name!r}; "
                f"known: {', '.join(sorted(known)) or 'none'}")
    return BudgetState(
        reference=state.reference,
        monthly_budget_minutes=state.monthly_budget_minutes,
        minutes_already_billed=state.minutes_already_billed,
        workflow_costs=overrides,
        cycle_start=state.cycle_start,
        cycle_end=state.cycle_end,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="budget_orchestrator",
        description="Adaptive GitHub Actions budget scheduler for the repo.")
    ap.add_argument(
        "--today", type=resolve_today, default=None,
        help="Anchor date for the scheduler (default today). "
             "Use --today 2026-10-10 to reproduce the October audit.")
    ap.add_argument(
        "--known-used", type=int, default=None,
        help="Measured billed minutes used this cycle; bypasses the API. "
             "Use it whenever the billing endpoint is unavailable.")
    ap.add_argument(
        "--known-limit", type=int, default=MONTHLY_BUDGET_MINUTES,
        help="Monthly budget in minutes (default 2000).")
    ap.add_argument(
        "--period-end", type=resolve_today, default=None,
        help="End of the current billing cycle (default: end of today's "
             "month).")
    ap.add_argument(
        "--workflow-costs-json", type=Path, default=None,
        help="JSON file replacing the workflow cost fingerprint "
             "(name, fires_per_month, billed_minutes_per_fire, can_adapt).")
    ap.add_argument(
        "--json", action="store_true", default=False,
        help="Print the plan as JSON instead of a report.")
    args = ap.parse_args(argv)

    today = args.today or date.today()
    period_end = args.period_end or None

    if args.known_used is not None:
        usage = GitHubUsage.from_known_info(
            period_end=period_end or month_end(today),
            total_minutes_used=args.known_used,
            total_minutes_limit=args.known_limit,
        )
    else:
        usage = live_usage(today=today, quiet=args.json)
        if usage is None:
            print("No usable GitHub usage figure: the billing endpoint is not "
                  "available for this account type.", file=sys.stderr)
            print("Supply one with --known-used and --period-end.",
                  file=sys.stderr)
            return NO_DATA_EXIT

    state = build_budget_state(usage, workflow_costs=default_workflow_costs(),
                               today=today)
    if args.workflow_costs_json is not None:
        state = _apply_overrides(state, args.workflow_costs_json)

    if args.json:
        print(json.dumps(plan_as_dict(state, usage), indent=2, sort_keys=True))
        return FITS_EXIT if fits_at_current_cadence(state, CAPTURE_WORKFLOW) \
            else ADAPT_EXIT
    return print_decisions(state, usage)


if __name__ == "__main__":
    raise SystemExit(main())
