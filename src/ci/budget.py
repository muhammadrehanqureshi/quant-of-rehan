"""Adaptive GitHub Actions budget scheduler for the repo.

Answers one question: given this billing cycle's measured usage and the
crons the repo already runs, how often may the capture workflow scan for
the rest of the cycle without crossing the 2,000-minute ceiling?

The model
---------
GitHub bills per job, rounded up to the next whole minute, whatever the
job's outcome: a cancelled job is not free. The repo's standing fingerprint
(measured in the October 2026 audit, AUDIT_AND_CI_BUDGET_2026-10-10.md):

    capture          108.7 fires/month x 11 min/fire = 1,195.8 min/month
    signal push       43.5 fires/month x  3 min/fire =   130.5 min/month
    governance guard  43.0 fires/month x  1 min/fire =    43.0 min/month
    full-month projection                            = 1,369.2 min (68.5%)

Only the capture workflow's cadence is a knob this module may turn: the
signal push and the governance guard are small and needed. So the report
line is

    fixed workflows       = signal push + governance guard
    fixed_ahead           = fixed share still to come before the cycle ends
    buffer_ahead          = spike reservation still to come before it ends
    capture_runway        = minutes_remaining - fixed_ahead - buffer_ahead
    fires                 = floor(capture_runway / cost_per_fire) - margin
    interval              = scanning minutes left / fires   (clamped)

The fire margin (DEFAULT_FIRE_BUFFER) is the last few affordable fires and
is never spent: schedule drift, retries and manual dispatches need room. The
spike buffer (DEFAULT_BUFFER_FRACTION of the ceiling) is reserved for the
same reason at the money level, and is prorated over the days that are
actually left, because on the 28th there is no month left to protect.

Two hard inputs, exactly as the request describes them: the cycle's elapsed
(rather than remaining) minutes come from the GitHub usage API or from a
supplied measurement, and the ceiling comes from the account's plan. The
elapsed figure already covers every workflow, which is why fixed_ahead is
the only fixed number this module subtracts: subtracting the capture
workflow's own prorated spend as well would count the same minutes twice.

Time and the reset
------------------
The cycle resets on the 1st. ``build_budget_state`` therefore anchors a run
that lands before the cycle's start at the fresh-cycle state (zero billed,
full runway) and a run past the cycle's end at the stale state (nothing left
to plan). Cycle length comes from the cycle's own dates, not from a table,
so a 28-, 29-, 30- and 31-day month are all handled by the same arithmetic.
The default cycle bounds are the calendar month of the reference date.

Intervals are measured in *session* minutes by default: a scan outside the
exchange's bands is worth nothing, so the affordable fires are spread across
the trading minutes that remain. Session windows are not defined here; they
come from ``src/data/sessions.py``, the repository's single source for
exchange time (SO-8), including the Friday midday break and the PSX holiday
list. This module never builds a market instant of its own.

Local-only contract
-------------------
Nothing here dials out. The GitHub call that fetches the usage figures runs
only inside GitHub Actions, against the same account that owns the budget,
or is bypassed entirely with a supplied measurement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Sequence

from src.data.sessions import session_bands

MONTHLY_BUDGET_MINUTES = 2000

CAPTURE_WORKFLOW = "capture"

#: Billed minutes per fire, rounded up to whole minutes as GitHub bills them.
#: Refresh from the Actions API whenever a workflow's timing changes.
DEFAULT_PER_FIRE_BILLABLE = {
    "capture": 11,
    "signal_push": 3,
    "governance_guard": 1,
}

#: Fires per month implied by each workflow's cron list (4.348 weeks/month).
DEFAULT_FIRES_PER_MONTH = {
    "capture": 108.7,
    "signal_push": 43.5,
    "governance_guard": 43.0,
}

#: Fraction of the ceiling held back for bursts, retries and manual runs.
DEFAULT_BUFFER_FRACTION = 0.10

#: Affordable fires never spent, so drift cannot eat the last minutes.
DEFAULT_FIRE_BUFFER = 3


def reset_date(reference: date) -> date:
    """The first of the month ``reference`` sits in: when the cycle resets."""
    return reference.replace(day=1)


def next_reset_date(reference: date) -> date:
    """The first of the month after ``reference``."""
    return (reference.replace(day=1) + timedelta(days=32)).replace(day=1)


def month_days(reference: date) -> int:
    """Total calendar days in the month of ``reference`` (28 to 31)."""
    return (next_reset_date(reference) - reset_date(reference)).days


def month_end(reference: date) -> date:
    """Last calendar day of the month of ``reference``."""
    return next_reset_date(reference) - timedelta(days=1)


def month_span_days(reference: date) -> int:
    """Days from ``reference`` to the end of its month, inclusive."""
    return (month_end(reference) - reference).days + 1


def session_minutes_on(d: date) -> int:
    """Whole trading minutes the exchange is open on Karachi date ``d``.

    Zero on a weekend or a PSX holiday. A Friday contributes both bands.
    """
    return sum(
        (closes[0] * 60 + closes[1]) - (opens[0] * 60 + opens[1])
        for opens, closes in session_bands(d)
    )


def session_minutes_from(reference: date, *, through: date | None = None) -> int:
    """Trading minutes from ``reference`` to ``through``, both inclusive.

    Whole sessions are counted: the reference date is a date, not an
    instant, so today's session counts in full even when the call happens
    after it opened. That keeps the answer reproducible for a given date.
    """
    last = through if through is not None else month_end(reference)
    if last < reference:
        return 0
    total = 0
    d = reference
    while d <= last:
        total += session_minutes_on(d)
        d += timedelta(days=1)
    return total


def trading_days_from(reference: date, *, through: date | None = None) -> int:
    """Trading days from ``reference`` to ``through``, both inclusive."""
    last = through if through is not None else month_end(reference)
    if last < reference:
        return 0
    days = 0
    d = reference
    while d <= last:
        if session_minutes_on(d) > 0:
            days += 1
        d += timedelta(days=1)
    return days


@dataclass(frozen=True)
class WorkflowCost:
    """One scheduled workflow's billing fingerprint.

    ``can_adapt`` marks the workflow whose cadence this module is allowed to
    stretch. ``min_interval_minutes`` and ``max_interval_minutes`` bound the
    schedule that may be recommended for it (GitHub's own floor is 5 minutes;
    a daily fallback is the practical ceiling).
    """

    name: str
    fires_per_month: float
    billed_minutes_per_fire: int
    can_adapt: bool = False
    min_interval_minutes: int | None = None
    max_interval_minutes: int | None = None

    @property
    def billed_minutes_per_month(self) -> float:
        """Standing full-month burn: the audit's own projection."""
        return self.fires_per_month * self.billed_minutes_per_fire

    def __post_init__(self) -> None:
        if self.billed_minutes_per_fire < 1:
            raise ValueError(
                f"{self.name}: billed_minutes_per_fire must be >= 1 "
                f"(GitHub rounds every job up to a whole minute)")
        if self.fires_per_month <= 0:
            raise ValueError(f"{self.name}: fires_per_month must be positive")
        if self.can_adapt and self.min_interval_minutes is not None \
                and self.max_interval_minutes is not None \
                and self.min_interval_minutes > self.max_interval_minutes:
            raise ValueError(
                f"{self.name}: min_interval_minutes "
                f"{self.min_interval_minutes} > max_interval_minutes "
                f"{self.max_interval_minutes}")


@dataclass(slots=True)
class BudgetState:
    """What the scheduler knows on a given day.

    ``minutes_already_billed`` is the whole-account figure for the cycle so
    far (every workflow included). ``cycle_start`` and ``cycle_end`` default
    to the calendar month around ``reference``; supply them when the usage
    API reports a cycle that is not a calendar month.
    """

    reference: date
    monthly_budget_minutes: int = MONTHLY_BUDGET_MINUTES
    minutes_already_billed: int = 0
    workflow_costs: list[WorkflowCost] = field(default_factory=list)
    cycle_start: date | None = None
    cycle_end: date | None = None

    def __post_init__(self) -> None:
        if self.minutes_already_billed < 0:
            raise ValueError("minutes_already_billed must be non-negative")
        if self.monthly_budget_minutes < 1:
            raise ValueError("monthly_budget_minutes must be positive")
        start = self.cycle_start_date
        end = self.cycle_end_date
        if end < start:
            raise ValueError(
                f"cycle_end {end.isoformat()} precedes cycle_start "
                f"{start.isoformat()}")

    @property
    def cycle_start_date(self) -> date:
        return self.cycle_start if self.cycle_start is not None \
            else reset_date(self.reference)

    @property
    def cycle_end_date(self) -> date:
        return self.cycle_end if self.cycle_end is not None \
            else month_end(self.reference)

    @property
    def cycle_days(self) -> int:
        """Length of the whole cycle, so 28 to 31 day months all work."""
        return (self.cycle_end_date - self.cycle_start_date).days + 1

    @property
    def days_left_in_cycle(self) -> int:
        """Calendar days from the reference date to the cycle end, inclusive."""
        return max(0, (self.cycle_end_date - self.reference).days + 1)

    @property
    def remaining_fraction(self) -> float:
        """Share of the cycle still ahead, used to prorate future costs."""
        if self.cycle_days < 1:
            return 0.0
        return min(1.0, self.days_left_in_cycle / self.cycle_days)

    @property
    def minutes_remaining(self) -> int:
        return max(0, self.monthly_budget_minutes - self.minutes_already_billed)

    @property
    def buffer_reservation_minutes(self) -> int:
        """Flat spike reservation for a whole cycle."""
        return int(self.monthly_budget_minutes * DEFAULT_BUFFER_FRACTION)

    @property
    def buffer_minutes(self) -> int:
        """Spike reservation prorated to the part of the cycle still ahead."""
        return int(round(self.buffer_reservation_minutes
                         * self.remaining_fraction))

    @property
    def fixed_minutes_remaining(self) -> int:
        """Minutes the non-adaptable workflows will still bill this cycle."""
        return int(round(sum(
            wc.billed_minutes_per_month
            for wc in self.workflow_costs
            if not wc.can_adapt) * self.remaining_fraction))

    @property
    def adaptive_budget_minutes(self) -> int:
        """What the adaptable workflow may still spend this cycle."""
        return max(0, self.minutes_remaining
                   - self.fixed_minutes_remaining
                   - self.buffer_minutes)

    @property
    def session_minutes_available(self) -> int:
        """Trading minutes between the reference date and the cycle end."""
        return session_minutes_from(self.reference,
                                    through=self.cycle_end_date)

    @property
    def trading_days_available(self) -> int:
        return trading_days_from(self.reference, through=self.cycle_end_date)

    @property
    def projected_month_minutes(self) -> float:
        """Full-cycle projection at the standing fingerprint (every workflow).

        This is the audit's headline figure: 1,369.2 minutes for the
        fingerprint above, against a 2,000-minute ceiling.
        """
        return sum(wc.billed_minutes_per_month for wc in self.workflow_costs)

    @property
    def projected_remaining_minutes(self) -> float:
        """Ceiling minus the standing projection: the audit's remaining 630.8.

        Negative when the standing fingerprint alone would cross the ceiling.
        """
        return self.monthly_budget_minutes - self.projected_month_minutes


def _find_workflow(state: BudgetState, name: str) -> WorkflowCost | None:
    for wc in state.workflow_costs:
        if wc.name == name:
            return wc
    return None


def _require_adaptable(state: BudgetState, name: str) -> WorkflowCost:
    target = _find_workflow(state, name)
    if target is None:
        raise ValueError(
            f"target workflow {name!r} not in state.workflow_costs")
    if not target.can_adapt:
        raise ValueError(
            f"{name!r} is not adaptable: its cadence is a cron, not an "
            f"interval this scheduler may stretch")
    return target


def allowed_fires_for(state: BudgetState, target_workflow: str) -> int:
    """Whole fires the adaptable workflow may still have this cycle."""
    target = _require_adaptable(state, target_workflow)
    budget = state.adaptive_budget_minutes
    if budget <= 0:
        return 0
    fires = int(budget // target.billed_minutes_per_fire)
    return max(0, fires - DEFAULT_FIRE_BUFFER)


def adaptive_interval_minutes(
    state: BudgetState,
    target_workflow: str,
    *,
    within_sessions: bool = True,
) -> int | None:
    """Best scanning interval for the rest of the cycle, or ``None``.

    ``None`` means the workflow has no affordable fire left and should stay
    down until the next reset. With ``within_sessions`` (the default) the
    fires are spread across the trading minutes that remain, so the interval
    is one a session-only runner can honor; with ``within_sessions=False``
    the fires are spread across every clock minute instead.

    The interval is rounded up, so the fires it implies never exceed the
    affordable count.
    """
    target = _require_adaptable(state, target_workflow)
    fires = allowed_fires_for(state, target_workflow)
    if fires < 1:
        return None
    span = state.session_minutes_available if within_sessions \
        else state.days_left_in_cycle * 24 * 60
    if span <= 0:
        return None
    interval = math.ceil(span / fires)
    if target.min_interval_minutes is not None:
        interval = max(interval, target.min_interval_minutes)
    if target.max_interval_minutes is not None:
        interval = min(interval, target.max_interval_minutes)
    return interval


def plan_scan_interval(
    minutes_used: int,
    minutes_remaining: int,
    *,
    reference: date,
    workflow_costs: list[WorkflowCost] | None = None,
    cycle_end: date | None = None,
) -> int | None:
    """The scanning interval from the two numbers a monitor usually has.

    This is the narrow entry point: minutes already spent this cycle and
    minutes left on the account. The ceiling is their sum, so the caller does
    not need to know the plan's own size. ``None`` means nothing is
    affordable and the scan should stay down until the reset.
    """
    ceiling = minutes_used + minutes_remaining
    if ceiling < 1:
        raise ValueError(
            "minutes_used + minutes_remaining must be positive")
    if minutes_used < 0 or minutes_remaining < 0:
        raise ValueError(
            "minutes_used and minutes_remaining cannot be negative")
    state = BudgetState(
        reference=reference,
        monthly_budget_minutes=ceiling,
        minutes_already_billed=minutes_used,
        workflow_costs=(workflow_costs if workflow_costs is not None
                        else default_workflow_costs()),
        cycle_end=cycle_end,
    )
    return adaptive_interval_minutes(state, CAPTURE_WORKFLOW)


def fits_at_current_cadence(state: BudgetState, target_workflow: str) -> bool:
    """May the workflow keep its standing cadence for the rest of the cycle?

    Compares what the standing fire rate would still bill against the
    remaining adaptive budget. The cycle's elapsed minutes are already in
    ``minutes_already_billed``, so only the part still ahead is counted.
    """
    target = _require_adaptable(state, target_workflow)
    projected = (target.fires_per_month
                 * state.remaining_fraction
                 * target.billed_minutes_per_fire)
    return projected <= state.adaptive_budget_minutes


def remaining_fires_at_cadence(state: BudgetState,
                               target_workflow: str) -> float:
    """Fires the standing cadence still implies this cycle."""
    target = _require_adaptable(state, target_workflow)
    return target.fires_per_month * state.remaining_fraction


def projected_burn_at_cadence(state: BudgetState,
                              target_workflow: str) -> float:
    """Minutes the standing cadence would still bill this cycle."""
    target = _require_adaptable(state, target_workflow)
    return remaining_fires_at_cadence(state, target_workflow) \
        * target.billed_minutes_per_fire


def recommended_static_cron_for(
    state: BudgetState,
    target_workflow: str,
    *,
    base_crons: Sequence[str] | None = None,
) -> list[str]:
    """A shortened static cron list the budget affords for the rest of the cycle.

    GitHub cannot flip a cron per minute, so the affordable fire count is
    converted into whole cron *entries*: each entry fires on every matching
    weekday, and the standing entries average ``fires_per_month / len``
    fires each. The kept entries are spread across the day rather than
    clipped to the morning, so the remaining scans are not all in the first
    session hour. The result never exceeds the affordable count.
    """
    target = _require_adaptable(state, target_workflow)
    fires = allowed_fires_for(state, target_workflow)
    if fires <= 0:
        return []
    crons = list(base_crons) if base_crons else _default_capture_crons()
    if not crons:
        return []
    if fires >= target.fires_per_month:
        return crons
    per_cron = target.fires_per_month / len(crons)
    keep = int(fires // per_cron)
    if keep >= len(crons):
        return crons
    if keep < 1:
        return []
    ordered = sorted(crons, key=_cron_utc_hour)
    step = len(ordered) / keep
    picked: list[str] = []
    for i in range(keep):
        # Centre each pick in its slice of the day, so two kept entries are
        # half a day apart instead of adjacent.
        idx = min(len(ordered) - 1, int(round((i + 0.5) * step)))
        if ordered[idx] not in picked:
            picked.append(ordered[idx])
    for cron in ordered:
        if len(picked) >= keep:
            break
        if cron not in picked:
            picked.append(cron)
    return sorted(picked, key=_cron_utc_hour)


def _cron_utc_hour(expr: str) -> int:
    """Second field of a 5-field cron, used only to order capture crons."""
    parts = expr.split()
    if len(parts) != 5:
        return 999
    try:
        return int(parts[1])
    except ValueError:
        return 999


def _default_capture_crons() -> list[str]:
    """The capture workflow's standing cron list (UTC), from its header."""
    return [
        "7 5 * * 1-5",
        "37 6 * * 1-5",
        "7 8 * * 1-4",
        "37 9 * * 1-5",
        "7 11 * * 5",
        "47 10 * * 1-4",
        "47 11 * * 5",
    ]


@dataclass(slots=True)
class GitHubUsage:
    """The fields the usage API reports for the current billing cycle.

    The public endpoint is gated and shaped differently across account
    types, so any caller that can populate these four fields may construct
    this directly. ``from_api_call`` parses the documented response shape;
    ``from_known_info`` accepts a measurement supplied by hand.
    """

    period_start: date
    period_end: date
    total_minutes_used: int
    total_minutes_limit: int

    @property
    def cycle_days(self) -> int:
        """Whole-cycle length from the cycle's own dates (28 to 31 days)."""
        return (self.period_end - self.period_start).days + 1

    @property
    def minutes_remaining(self) -> int:
        return max(0, self.total_minutes_limit - self.total_minutes_used)

    def days_remaining_from(self, reference: date) -> int:
        """Cycle days left from ``reference`` to the cycle end, inclusive."""
        return max(0, (self.period_end - reference).days + 1)

    @classmethod
    def from_api_call(cls, payload: dict) -> GitHubUsage:
        """Parse the usage payload the caller got from GitHub.

        The caller performs the call itself, with whatever auth and endpoint
        GitHub actually exposes for the account type, then passes the JSON
        here. This module never reaches the network.
        """
        period = payload.get("period", {}) if isinstance(payload, dict) else {}
        start = _parse_github_date(period.get("start"))
        end = _parse_github_date(period.get("end"))
        limit = int(payload.get("total_minutes_limit", 0) or 0)
        used = int(payload.get("total_minutes_used", 0) or 0)
        if start is None or end is None:
            raise ValueError(
                "GitHub usage payload missing period.start or period.end")
        if limit <= 0:
            raise ValueError(
                "GitHub usage payload reports total_minutes_limit <= 0")
        if end < start:
            raise ValueError(
                "GitHub usage payload reports period.end before period.start")
        return cls(
            period_start=start,
            period_end=end,
            total_minutes_used=max(0, used),
            total_minutes_limit=limit,
        )

    @classmethod
    def from_billing_payload(
        cls,
        payload: dict,
        *,
        today: date | None = None,
    ) -> GitHubUsage:
        """Parse the billing endpoint's response shape.

        That response carries no period of its own, so the calendar month
        around ``today`` is treated as the cycle. ``included_minutes`` is the
        plan's allowance; usage above it is already visible in
        ``total_minutes_used`` (``total_paid_minutes_used`` is the overage
        slice, so adding it would double count).
        """
        limit = int(payload.get("included_minutes", 0) or 0)
        used = int(payload.get("total_minutes_used", 0) or 0)
        if limit <= 0:
            raise ValueError("billing payload reports included_minutes <= 0")
        if used < 0:
            raise ValueError("billing payload reports negative usage")
        anchor = today or date.today()
        return cls(
            period_start=reset_date(anchor),
            period_end=month_end(anchor),
            total_minutes_used=used,
            total_minutes_limit=limit,
        )

    @classmethod
    def from_known_info(
        cls,
        *,
        period_end: date,
        total_minutes_used: int,
        total_minutes_limit: int = MONTHLY_BUDGET_MINUTES,
    ) -> GitHubUsage:
        """Build a usage record from a measurement and the cycle end date."""
        if total_minutes_limit < 1:
            raise ValueError("total_minutes_limit must be positive")
        if total_minutes_used < 0:
            raise ValueError("total_minutes_used must be non-negative")
        return cls(
            period_start=reset_date(period_end),
            period_end=period_end,
            total_minutes_used=total_minutes_used,
            total_minutes_limit=total_minutes_limit,
        )


def github_usage_from_run_summary(
    summary_minutes_used: int,
    *,
    period_end: date | None = None,
    total_minutes_limit: int = MONTHLY_BUDGET_MINUTES,
) -> GitHubUsage:
    """Usage record anchored on the cycle end, for a known-info run."""
    end = period_end or date.today()
    return GitHubUsage.from_known_info(
        period_end=end,
        total_minutes_used=summary_minutes_used,
        total_minutes_limit=total_minutes_limit,
    )


def build_budget_state(
    usage: GitHubUsage,
    *,
    workflow_costs: list[WorkflowCost] | None = None,
    today: date | None = None,
) -> BudgetState:
    """Anchor a state on today's position inside the billing cycle.

    The monthly reset lives here. Before the cycle starts (a run on or after
    the 1st but before the first metered minute) the state is fresh: zero
    billed, full runway. Inside the cycle the measured figure is used as is.
    Past the cycle end the state is stale: the reference clamps to the cycle
    end, so nothing is scheduled against a closed cycle.
    """
    costs = list(workflow_costs) if workflow_costs is not None \
        else default_workflow_costs()
    anchor = today or date.today()
    if anchor < usage.period_start:
        reference, already_billed = usage.period_start, 0
    elif anchor > usage.period_end:
        reference, already_billed = usage.period_end, usage.total_minutes_used
    else:
        reference, already_billed = anchor, usage.total_minutes_used
    return BudgetState(
        reference=reference,
        monthly_budget_minutes=usage.total_minutes_limit,
        minutes_already_billed=already_billed,
        workflow_costs=costs,
        cycle_start=usage.period_start,
        cycle_end=usage.period_end,
    )


def default_workflow_costs() -> list[WorkflowCost]:
    """The repo's standing fingerprint, as measured in the audit."""
    return [
        WorkflowCost(
            name=CAPTURE_WORKFLOW,
            fires_per_month=DEFAULT_FIRES_PER_MONTH["capture"],
            billed_minutes_per_fire=DEFAULT_PER_FIRE_BILLABLE["capture"],
            can_adapt=True,
            min_interval_minutes=5,
            max_interval_minutes=1440,
        ),
        WorkflowCost(
            name="signal_push",
            fires_per_month=DEFAULT_FIRES_PER_MONTH["signal_push"],
            billed_minutes_per_fire=DEFAULT_PER_FIRE_BILLABLE["signal_push"],
            can_adapt=False,
        ),
        WorkflowCost(
            name="governance_guard",
            fires_per_month=DEFAULT_FIRES_PER_MONTH["governance_guard"],
            billed_minutes_per_fire=DEFAULT_PER_FIRE_BILLABLE["governance_guard"],
            can_adapt=False,
        ),
    ]


def _parse_github_date(raw) -> date | None:
    """Best-effort parse of a GitHub API date string into a date."""
    if not isinstance(raw, str):
        return None
    try:
        return date.fromisoformat(raw[:10])
    except (ValueError, IndexError):
        return None
