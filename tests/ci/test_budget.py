"""Tests for src/ci/budget.py and src/ci/budget_orchestrator.py.

Everything here is pure arithmetic, well-defined parsing, and output
capture. No network call is made: the GitHub API surface is exercised
through the payload parsers only.

The headline figures asserted below are the audit's own, from
AUDIT_AND_CI_BUDGET_2026-10-10.md: the standing fingerprint projects to
1,369.2 minutes a month (68.5%), leaving 630.8 minutes of the 2,000.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ci.budget import (  # noqa: E402
    CAPTURE_WORKFLOW,
    DEFAULT_FIRE_BUFFER,
    DEFAULT_PER_FIRE_BILLABLE,
    DEFAULT_FIRES_PER_MONTH,
    MONTHLY_BUDGET_MINUTES,
    BudgetState,
    GitHubUsage,
    WorkflowCost,
    adaptive_interval_minutes,
    allowed_fires_for,
    build_budget_state,
    default_workflow_costs,
    fits_at_current_cadence,
    github_usage_from_run_summary,
    month_days,
    month_end,
    month_span_days,
    next_reset_date,
    plan_scan_interval,
    projected_burn_at_cadence,
    recommended_static_cron_for,
    remaining_fires_at_cadence,
    reset_date,
    session_minutes_from,
    session_minutes_on,
    trading_days_from,
)
from src.ci.budget_orchestrator import (  # noqa: E402
    _apply_overrides,
    _override_workflow_costs,
    main,
    print_decisions,
    resolve_today,
)

AUDIT_DAY = date(2026, 10, 10)


def state_at(reference: date, *, used: int = 0,
             costs: list[WorkflowCost] | None = None,
             **kwargs) -> BudgetState:
    """A budget state anchored on a date, with the standing fingerprint."""
    return BudgetState(
        reference=reference,
        monthly_budget_minutes=MONTHLY_BUDGET_MINUTES,
        minutes_already_billed=used,
        workflow_costs=costs if costs is not None
        else default_workflow_costs(),
        **kwargs,
    )


class TestMonthBookkeeping(unittest.TestCase):
    def test_reset_date_is_first_of_month(self) -> None:
        for d in (date(2026, 10, 1), date(2026, 10, 17), date(2026, 10, 31)):
            self.assertEqual(reset_date(d), date(2026, 10, 1))
        self.assertEqual(reset_date(date(2026, 2, 15)), date(2026, 2, 1))

    def test_next_reset_date_crosses_the_year(self) -> None:
        self.assertEqual(next_reset_date(date(2026, 10, 10)),
                         date(2026, 11, 1))
        self.assertEqual(next_reset_date(date(2026, 12, 31)),
                         date(2027, 1, 1))

    def test_month_end(self) -> None:
        self.assertEqual(month_end(date(2026, 10, 10)), date(2026, 10, 31))
        self.assertEqual(month_end(date(2026, 2, 10)), date(2026, 2, 28))
        self.assertEqual(month_end(date(2028, 2, 10)), date(2028, 2, 29))

    def test_month_lengths_cover_every_shape(self) -> None:
        self.assertEqual(month_days(date(2026, 2, 15)), 28)
        self.assertEqual(month_days(date(2028, 2, 15)), 29)
        self.assertEqual(month_days(date(2026, 4, 15)), 30)
        self.assertEqual(month_days(date(2026, 10, 15)), 31)

    def test_month_span_days_counts_the_reference_day(self) -> None:
        self.assertEqual(month_span_days(AUDIT_DAY), 22)
        self.assertEqual(month_span_days(date(2026, 10, 1)), 31)
        self.assertEqual(month_span_days(date(2026, 10, 31)), 1)
        self.assertEqual(month_span_days(date(2026, 2, 15)), 14)

    def test_budget_default(self) -> None:
        self.assertEqual(MONTHLY_BUDGET_MINUTES, 2000)


class TestSessionMath(unittest.TestCase):
    """Session minutes come from the exchange law, not from a second copy."""

    def test_weekday_session_has_its_own_share(self) -> None:
        self.assertEqual(session_minutes_on(date(2026, 10, 14)), 358)

    def test_friday_break_is_not_trading_time(self) -> None:
        self.assertEqual(session_minutes_on(date(2026, 10, 16)), 281)

    def test_weekend_is_closed(self) -> None:
        self.assertEqual(session_minutes_on(date(2026, 10, 10)), 0)
        self.assertEqual(session_minutes_on(date(2026, 10, 11)), 0)

    def test_psx_holiday_is_closed(self) -> None:
        self.assertEqual(session_minutes_on(date(2026, 11, 9)), 0)

    def test_session_minutes_from_a_saturday(self) -> None:
        # 15 trading days remain from Sat 10 Oct: 3 Fridays and 12 weekdays.
        self.assertEqual(session_minutes_from(AUDIT_DAY), 3 * 281 + 12 * 358)
        self.assertEqual(session_minutes_from(AUDIT_DAY), 5139)

    def test_session_minutes_from_can_be_bounded(self) -> None:
        self.assertEqual(session_minutes_from(AUDIT_DAY,
                                              through=date(2026, 10, 12)),
                         358)

    def test_session_minutes_from_rejects_a_backwards_window(self) -> None:
        self.assertEqual(
            session_minutes_from(date(2026, 10, 12),
                                 through=date(2026, 10, 1)), 0)

    def test_trading_days_from(self) -> None:
        self.assertEqual(trading_days_from(AUDIT_DAY), 15)
        self.assertEqual(trading_days_from(date(2026, 11, 1)), 20)


class TestWorkflowCost(unittest.TestCase):
    def test_billed_minutes_per_month(self) -> None:
        wc = WorkflowCost(name="x", fires_per_month=10.0,
                          billed_minutes_per_fire=11)
        self.assertEqual(wc.billed_minutes_per_month, 110.0)

    def test_rejects_sub_one_billed_minute(self) -> None:
        with self.assertRaises(ValueError):
            WorkflowCost(name="x", fires_per_month=1.0,
                         billed_minutes_per_fire=0)

    def test_rejects_zero_fires(self) -> None:
        with self.assertRaises(ValueError):
            WorkflowCost(name="x", fires_per_month=0.0,
                         billed_minutes_per_fire=1)

    def test_rejects_inverted_interval_bounds(self) -> None:
        with self.assertRaises(ValueError):
            WorkflowCost(name="x", fires_per_month=1.0,
                         billed_minutes_per_fire=1, can_adapt=True,
                         min_interval_minutes=60, max_interval_minutes=30)


class TestBudgetState(unittest.TestCase):
    def test_rejects_negative_already_billed(self) -> None:
        with self.assertRaises(ValueError):
            BudgetState(reference=AUDIT_DAY, minutes_already_billed=-1)

    def test_rejects_non_positive_budget(self) -> None:
        with self.assertRaises(ValueError):
            BudgetState(reference=AUDIT_DAY, monthly_budget_minutes=0)

    def test_rejects_a_backwards_cycle(self) -> None:
        with self.assertRaises(ValueError):
            BudgetState(reference=AUDIT_DAY,
                        cycle_start=date(2026, 10, 31),
                        cycle_end=date(2026, 10, 1))

    def test_remaining_never_goes_negative(self) -> None:
        self.assertEqual(state_at(AUDIT_DAY, used=2500).minutes_remaining, 0)

    def test_buffer_is_prorated_over_the_days_left(self) -> None:
        state = state_at(AUDIT_DAY)
        self.assertEqual(state.buffer_reservation_minutes, 200)
        # 22 of 31 days left: 200 * 22 / 31, rounded.
        self.assertEqual(state.buffer_minutes, round(200 * 22 / 31))

    def test_fixed_minutes_remaining_is_prorated(self) -> None:
        state = state_at(AUDIT_DAY)
        fixed_month = (DEFAULT_FIRES_PER_MONTH["signal_push"]
                       * DEFAULT_PER_FIRE_BILLABLE["signal_push"]
                       + DEFAULT_FIRES_PER_MONTH["governance_guard"]
                       * DEFAULT_PER_FIRE_BILLABLE["governance_guard"])
        self.assertEqual(state.fixed_minutes_remaining,
                         round(fixed_month * 22 / 31))

    def test_runway_subtracts_fixed_costs_and_buffer(self) -> None:
        state = state_at(AUDIT_DAY, used=1369)
        self.assertEqual(state.minutes_remaining, 631)
        self.assertEqual(state.adaptive_budget_minutes,
                         631 - state.fixed_minutes_remaining
                         - state.buffer_minutes)
        self.assertEqual(state.adaptive_budget_minutes, 366)

    def test_runway_is_zero_when_the_ceiling_is_reached(self) -> None:
        self.assertEqual(state_at(AUDIT_DAY, used=2000).adaptive_budget_minutes,
                         0)

    def test_standing_projection_matches_the_audit(self) -> None:
        state = state_at(AUDIT_DAY)
        self.assertAlmostEqual(state.projected_month_minutes, 1369.2,
                               places=1)
        self.assertAlmostEqual(state.projected_remaining_minutes, 630.8,
                               places=1)
        self.assertAlmostEqual(state.projected_month_minutes
                               / state.monthly_budget_minutes * 100, 68.5,
                               places=1)

    def test_longer_timeout_projection_matches_the_audit(self) -> None:
        # The audit's second headline: capture at 14 min/fire is 1,695/month.
        costs = default_workflow_costs()
        costs[0] = WorkflowCost(
            name=CAPTURE_WORKFLOW,
            fires_per_month=DEFAULT_FIRES_PER_MONTH["capture"],
            billed_minutes_per_fire=14,
            can_adapt=True,
            min_interval_minutes=5,
            max_interval_minutes=1440,
        )
        state = state_at(AUDIT_DAY, costs=costs)
        self.assertAlmostEqual(state.projected_month_minutes, 1695.3,
                               places=1)


class TestFitsAtCurrentCadence(unittest.TestCase):
    def test_fresh_cycle_fits(self) -> None:
        self.assertTrue(
            fits_at_current_cadence(state_at(date(2026, 10, 1)),
                                    CAPTURE_WORKFLOW))

    def test_heavy_usage_does_not_fit(self) -> None:
        # The audit's own figures, read as usage on the 10th: 1,369 minutes
        # burned with 22 days to go cannot hold the standing cadence.
        self.assertFalse(
            fits_at_current_cadence(state_at(AUDIT_DAY, used=1369),
                                    CAPTURE_WORKFLOW))

    def test_raises_for_a_non_adaptable_workflow(self) -> None:
        with self.assertRaises(ValueError):
            fits_at_current_cadence(state_at(AUDIT_DAY), "signal_push")

    def test_helpers_report_the_standing_cadence_share(self) -> None:
        state = state_at(AUDIT_DAY)
        self.assertAlmostEqual(
            remaining_fires_at_cadence(state, CAPTURE_WORKFLOW),
            DEFAULT_FIRES_PER_MONTH["capture"] * 22 / 31, places=3)
        self.assertAlmostEqual(
            projected_burn_at_cadence(state, CAPTURE_WORKFLOW),
            DEFAULT_FIRES_PER_MONTH["capture"] * 22 / 31 * 11, places=1)


class TestAllowedFires(unittest.TestCase):
    def test_zero_when_the_cycle_is_spent(self) -> None:
        self.assertEqual(
            allowed_fires_for(state_at(AUDIT_DAY, used=2000),
                              CAPTURE_WORKFLOW), 0)

    def test_zero_when_only_the_margin_remains(self) -> None:
        # Under DEFAULT_FIRE_BUFFER affordable fires: nothing is scheduled.
        costs = [WorkflowCost(name=CAPTURE_WORKFLOW, fires_per_month=1.0,
                              billed_minutes_per_fire=1, can_adapt=True)]
        state = state_at(AUDIT_DAY, used=1997, costs=costs)
        self.assertEqual(allowed_fires_for(state, CAPTURE_WORKFLOW), 0)

    def test_raises_for_a_non_adaptable_workflow(self) -> None:
        with self.assertRaises(ValueError):
            allowed_fires_for(state_at(AUDIT_DAY), "governance_guard")

    def test_raises_for_an_unknown_workflow(self) -> None:
        with self.assertRaises(ValueError):
            allowed_fires_for(state_at(AUDIT_DAY), "no_such_workflow")


class TestAdaptiveInterval(unittest.TestCase):
    def test_none_when_no_runway_is_left(self) -> None:
        # 250 minutes left on the 10th no longer cover the fixed costs still
        # to come plus the spike buffer, so nothing is affordable.
        self.assertIsNone(
            adaptive_interval_minutes(state_at(AUDIT_DAY, used=1750),
                                      CAPTURE_WORKFLOW))

    def test_none_when_no_session_time_is_left(self) -> None:
        # Sat 31 Oct: the month still has hours, but the exchange does not.
        self.assertIsNone(
            adaptive_interval_minutes(state_at(date(2026, 10, 31)),
                                      CAPTURE_WORKFLOW))

    def test_interval_is_a_whole_positive_number(self) -> None:
        interval = adaptive_interval_minutes(state_at(AUDIT_DAY, used=1369),
                                             CAPTURE_WORKFLOW)
        self.assertIsInstance(interval, int)
        self.assertGreater(interval, 0)

    def test_interval_stays_inside_the_workflow_bounds(self) -> None:
        costs = [WorkflowCost(name=CAPTURE_WORKFLOW, fires_per_month=1.0,
                              billed_minutes_per_fire=1, can_adapt=True,
                              min_interval_minutes=30,
                              max_interval_minutes=60)]
        state = state_at(AUDIT_DAY, costs=costs)
        interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
        self.assertEqual(interval, 30)

    def test_interval_is_capped_by_the_workflow_maximum(self) -> None:
        costs = [WorkflowCost(name=CAPTURE_WORKFLOW, fires_per_month=1.0,
                              billed_minutes_per_fire=1, can_adapt=True,
                              max_interval_minutes=40)]
        state = state_at(date(2026, 10, 11), used=1835, costs=costs)
        self.assertEqual(
            adaptive_interval_minutes(state, CAPTURE_WORKFLOW), 40)

    def test_wall_clock_interval_exceeds_the_session_interval(self) -> None:
        state = state_at(AUDIT_DAY, used=1369)
        session = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
        wall = adaptive_interval_minutes(state, CAPTURE_WORKFLOW,
                                         within_sessions=False)
        self.assertGreater(wall, session)

    def test_the_interval_never_implies_more_fires_than_affordable(self) -> None:
        state = state_at(AUDIT_DAY, used=1369)
        fires = allowed_fires_for(state, CAPTURE_WORKFLOW)
        interval = adaptive_interval_minutes(state, CAPTURE_WORKFLOW)
        implied = state.session_minutes_available // interval
        self.assertLessEqual(implied, fires)

    def test_raises_for_a_non_adaptable_workflow(self) -> None:
        with self.assertRaises(ValueError):
            adaptive_interval_minutes(state_at(AUDIT_DAY), "signal_push")


class TestTwoNumberEntryPoint(unittest.TestCase):
    """The narrow entry point: elapsed minutes plus minutes remaining."""

    def test_interval_matches_the_state_based_answer(self) -> None:
        self.assertEqual(plan_scan_interval(398, 1602, reference=AUDIT_DAY),
                         44)
        self.assertEqual(plan_scan_interval(1369, 631, reference=AUDIT_DAY),
                         172)

    def test_ceiling_comes_from_the_two_numbers(self) -> None:
        # The same 100 minutes spent in a 500-minute plan and in a
        # 2,000-minute plan: the tighter plan has to scan slower.
        tight = plan_scan_interval(100, 400, reference=AUDIT_DAY)
        loose = plan_scan_interval(100, 1900, reference=AUDIT_DAY)
        self.assertIsNotNone(tight)
        self.assertLess(loose, tight)

    def test_none_when_the_runway_is_gone(self) -> None:
        self.assertIsNone(plan_scan_interval(1750, 250, reference=AUDIT_DAY))

    def test_rejects_impossible_numbers(self) -> None:
        with self.assertRaises(ValueError):
            plan_scan_interval(0, 0, reference=AUDIT_DAY)
        with self.assertRaises(ValueError):
            plan_scan_interval(-1, 10, reference=AUDIT_DAY)

    def test_reset_day_gets_the_fast_plan(self) -> None:
        self.assertEqual(
            plan_scan_interval(0, 2000, reference=date(2026, 10, 1)), 53)


class TestMonthProgression(unittest.TestCase):
    """How the plan moves as the month burns, the deliverable's own demo."""

    def test_affordable_fires_decline_through_the_month(self) -> None:
        # A burn that tracks the standing cadence: about 44.2 min/day.
        fires = []
        for day in range(1, 32):
            reference = date(2026, 10, day)
            state = state_at(reference, used=round(44.2 * (day - 1)))
            fires.append(allowed_fires_for(state, CAPTURE_WORKFLOW))
        self.assertEqual(fires[0], 144)
        self.assertEqual(fires[-1], 57)
        self.assertTrue(all(b <= a for a, b in zip(fires, fires[1:])),
                        f"fires must not grow as the month burns: {fires}")

    def test_the_plan_tightens_against_the_audit_day(self) -> None:
        start = state_at(date(2026, 10, 1))
        mid = state_at(AUDIT_DAY, used=1369)
        self.assertEqual(allowed_fires_for(start, CAPTURE_WORKFLOW), 144)
        self.assertEqual(allowed_fires_for(mid, CAPTURE_WORKFLOW), 30)
        self.assertEqual(adaptive_interval_minutes(start, CAPTURE_WORKFLOW), 53)
        self.assertEqual(adaptive_interval_minutes(mid, CAPTURE_WORKFLOW), 172)

    def test_a_burst_slows_the_scan_and_shrinks_the_allowance(self) -> None:
        normal = state_at(AUDIT_DAY, used=300)
        burst = state_at(AUDIT_DAY, used=900)
        self.assertGreater(allowed_fires_for(normal, CAPTURE_WORKFLOW),
                           allowed_fires_for(burst, CAPTURE_WORKFLOW))
        self.assertLess(adaptive_interval_minutes(normal, CAPTURE_WORKFLOW),
                        adaptive_interval_minutes(burst, CAPTURE_WORKFLOW))
        self.assertEqual(allowed_fires_for(burst, CAPTURE_WORKFLOW), 72)
        self.assertEqual(adaptive_interval_minutes(burst, CAPTURE_WORKFLOW),
                         72)

    def test_fire_buffer_is_really_held_back(self) -> None:
        state = state_at(date(2026, 10, 1))
        runway_fires = state.adaptive_budget_minutes \
            // DEFAULT_PER_FIRE_BILLABLE["capture"]
        self.assertEqual(allowed_fires_for(state, CAPTURE_WORKFLOW),
                         runway_fires - DEFAULT_FIRE_BUFFER)


class TestStaticCronRecommendation(unittest.TestCase):
    def test_keeps_the_whole_list_when_every_cron_is_affordable(self) -> None:
        costs = [WorkflowCost(name=CAPTURE_WORKFLOW, fires_per_month=1.0,
                              billed_minutes_per_fire=1, can_adapt=True)]
        self.assertEqual(
            len(recommended_static_cron_for(state_at(AUDIT_DAY, costs=costs),
                                            CAPTURE_WORKFLOW)), 7)

    def test_shortens_the_list_under_pressure(self) -> None:
        # 15 affordable fires against 100 a month is exactly one cron entry.
        costs = [WorkflowCost(name=CAPTURE_WORKFLOW, fires_per_month=100.0,
                              billed_minutes_per_fire=11, can_adapt=True)]
        state = state_at(date(2026, 10, 31), used=1796, costs=costs)
        self.assertEqual(allowed_fires_for(state, CAPTURE_WORKFLOW), 15)
        kept = recommended_static_cron_for(state, CAPTURE_WORKFLOW)
        self.assertEqual(len(kept), 1)

    def test_kept_entries_are_spread_across_the_day(self) -> None:
        # 47 affordable fires against 108.7 a month is three whole cron
        # entries, centred in their slice of the day instead of clipped to
        # the morning: one early, one mid, one late session entry.
        state = state_at(AUDIT_DAY, used=1185)
        self.assertEqual(allowed_fires_for(state, CAPTURE_WORKFLOW), 47)
        self.assertEqual(
            recommended_static_cron_for(state, CAPTURE_WORKFLOW),
            ["37 6 * * 1-5", "47 10 * * 1-4", "47 11 * * 5"])

    def test_no_entry_is_kept_when_even_one_would_overshoot(self) -> None:
        # A single cron entry fires on every matching weekday, about 15
        # times in the 22 days left, which is more than these 10 fires.
        state = state_at(AUDIT_DAY, used=1592)
        self.assertEqual(allowed_fires_for(state, CAPTURE_WORKFLOW), 10)
        self.assertEqual(
            recommended_static_cron_for(state, CAPTURE_WORKFLOW), [])

    def test_empty_when_nothing_is_affordable(self) -> None:
        state = state_at(date(2026, 10, 31), used=2000)
        self.assertEqual(
            recommended_static_cron_for(state, CAPTURE_WORKFLOW), [])

    def test_raises_for_a_non_adaptable_workflow(self) -> None:
        with self.assertRaises(ValueError):
            recommended_static_cron_for(state_at(AUDIT_DAY), "signal_push")


class TestGitHubUsage(unittest.TestCase):
    def test_from_api_call_parses_the_documented_shape(self) -> None:
        usage = GitHubUsage.from_api_call({
            "period": {"start": "2026-10-01T00:00:00Z",
                       "end": "2026-10-31T23:59:59Z"},
            "total_minutes_used": 1369,
            "total_minutes_limit": 2000,
        })
        self.assertEqual(usage.period_start, date(2026, 10, 1))
        self.assertEqual(usage.period_end, date(2026, 10, 31))
        self.assertEqual(usage.total_minutes_used, 1369)
        self.assertEqual(usage.minutes_remaining, 631)
        self.assertEqual(usage.cycle_days, 31)
        self.assertEqual(usage.days_remaining_from(AUDIT_DAY), 22)

    def test_from_api_call_rejects_missing_dates(self) -> None:
        with self.assertRaises(ValueError):
            GitHubUsage.from_api_call({})

    def test_from_api_call_rejects_a_zero_limit(self) -> None:
        with self.assertRaises(ValueError):
            GitHubUsage.from_api_call({
                "period": {"start": "2026-10-01", "end": "2026-10-31"},
                "total_minutes_used": 10,
                "total_minutes_limit": 0,
            })

    def test_from_api_call_rejects_a_backwards_period(self) -> None:
        with self.assertRaises(ValueError):
            GitHubUsage.from_api_call({
                "period": {"start": "2026-10-31", "end": "2026-10-01"},
                "total_minutes_limit": 2000,
            })

    def test_from_known_info_anchors_the_cycle_on_the_month(self) -> None:
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=1369)
        self.assertEqual(usage.period_start, date(2026, 10, 1))
        self.assertEqual(usage.minutes_remaining, 631)

    def test_from_known_info_rejects_a_zero_limit(self) -> None:
        with self.assertRaises(ValueError):
            GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                        total_minutes_used=0,
                                        total_minutes_limit=0)

    def test_from_billing_payload_reads_the_billing_shape(self) -> None:
        usage = GitHubUsage.from_billing_payload(
            {"included_minutes": 2000, "total_minutes_used": 1369,
             "total_paid_minutes_used": 0},
            today=AUDIT_DAY)
        self.assertEqual(usage.period_start, date(2026, 10, 1))
        self.assertEqual(usage.period_end, date(2026, 10, 31))
        self.assertEqual(usage.total_minutes_used, 1369)
        self.assertEqual(usage.minutes_remaining, 631)

    def test_from_billing_payload_does_not_double_count_the_overage(self) -> None:
        usage = GitHubUsage.from_billing_payload(
            {"included_minutes": 2000, "total_minutes_used": 2100,
             "total_paid_minutes_used": 100},
            today=AUDIT_DAY)
        self.assertEqual(usage.total_minutes_used, 2100)
        self.assertEqual(usage.minutes_remaining, 0)

    def test_from_billing_payload_rejects_a_missing_allowance(self) -> None:
        with self.assertRaises(ValueError):
            GitHubUsage.from_billing_payload({"total_minutes_used": 1},
                                             today=AUDIT_DAY)

    def test_february_cycle_is_twenty_eight_days(self) -> None:
        usage = GitHubUsage.from_known_info(period_end=date(2026, 2, 28),
                                            total_minutes_used=0)
        self.assertEqual(usage.cycle_days, 28)
        self.assertEqual(usage.days_remaining_from(date(2026, 2, 15)), 14)

    def test_run_summary_anchor(self) -> None:
        usage = github_usage_from_run_summary(500,
                                              period_end=date(2026, 10, 31))
        self.assertEqual(usage.period_start, date(2026, 10, 1))
        self.assertEqual(usage.minutes_remaining, 1500)


class TestBuildBudgetState(unittest.TestCase):
    def test_anchors_on_today_inside_the_cycle(self) -> None:
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=1369)
        state = build_budget_state(usage, today=AUDIT_DAY)
        self.assertEqual(state.reference, AUDIT_DAY)
        self.assertEqual(state.minutes_already_billed, 1369)
        self.assertEqual(state.cycle_days, 31)

    def test_a_run_on_the_first_starts_a_fresh_cycle(self) -> None:
        # The monthly reset: the cycle's first day bills nothing yet, so the
        # whole runway is available even though the previous month was tight.
        usage = GitHubUsage(period_start=date(2026, 11, 1),
                            period_end=date(2026, 11, 30),
                            total_minutes_used=0,
                            total_minutes_limit=2000)
        state = build_budget_state(usage, today=date(2026, 11, 1))
        self.assertEqual(state.reference, date(2026, 11, 1))
        self.assertEqual(state.minutes_already_billed, 0)
        self.assertEqual(state.days_left_in_cycle, 30)
        self.assertEqual(state.adaptive_budget_minutes, 1626)

    def test_a_stale_cycle_clamps_to_its_end(self) -> None:
        # On 1 Nov GitHub may still report the October cycle. The scheduler
        # must not plan against a closed cycle.
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=1695)
        state = build_budget_state(usage, today=date(2026, 11, 1))
        self.assertEqual(state.reference, date(2026, 10, 31))
        self.assertEqual(state.days_left_in_cycle, 1)
        self.assertIsNone(adaptive_interval_minutes(state, CAPTURE_WORKFLOW))

    def test_a_cycle_that_has_not_started_is_fresh(self) -> None:
        usage = GitHubUsage(period_start=date(2026, 11, 1),
                            period_end=date(2026, 11, 30),
                            total_minutes_used=0,
                            total_minutes_limit=2000)
        state = build_budget_state(usage, today=date(2026, 10, 5))
        self.assertEqual(state.reference, date(2026, 11, 1))
        self.assertEqual(state.minutes_already_billed, 0)


class TestPrintDecisions(unittest.TestCase):
    def run_print(self, state: BudgetState, usage: GitHubUsage):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = print_decisions(state, usage)
        return code, out.getvalue()

    def test_reproduces_the_audit_headline_figures(self) -> None:
        state = state_at(AUDIT_DAY, used=1369)
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=1369)
        code, text = self.run_print(state, usage)
        self.assertEqual(code, 1, "1369 burned by the 10th needs adaptation")
        self.assertIn("=== GitHub Actions budget, 2026-10-10 ===", text)
        self.assertIn("1,369 min of 2,000 (68.5%)", text)
        self.assertIn("631 min remaining", text)
        self.assertIn("1,369.2 min", text)
        self.assertIn("630.8 min to spare", text)
        self.assertIn("366 min", text)
        self.assertIn("one scan every 172 min of session time", text)

    def test_reports_a_fitting_cycle_without_adaptation(self) -> None:
        state = state_at(date(2026, 10, 1))
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=0)
        code, text = self.run_print(state, usage)
        self.assertEqual(code, 0)
        self.assertIn("FITS the runway", text)
        self.assertIn("53 min of session time", text)
        self.assertIn("no adaptation is needed", text)

    def test_reports_no_runway_at_all(self) -> None:
        state = state_at(date(2026, 10, 31), used=2000)
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=2000)
        code, text = self.run_print(state, usage)
        self.assertEqual(code, 1)
        self.assertIn("adaptation needed", text)
        self.assertIn("stop the capture workflow", text)

    def test_reports_a_missing_capture_fingerprint(self) -> None:
        costs = [WorkflowCost(name="signal_push", fires_per_month=1.0,
                              billed_minutes_per_fire=3)]
        state = state_at(AUDIT_DAY, costs=costs)
        usage = GitHubUsage.from_known_info(period_end=date(2026, 10, 31),
                                            total_minutes_used=0)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.run_print(state, usage)
        self.assertEqual(code, 2)
        self.assertIn("No capture workflow fingerprint", err.getvalue())


class TestOrchestratorCli(unittest.TestCase):
    def test_resolve_today_parses_iso(self) -> None:
        self.assertEqual(resolve_today("2026-10-10"), date(2026, 10, 10))

    def test_resolve_today_rejects_a_bogus_value(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            resolve_today("10/10/2026")

    def test_known_info_run_returns_the_adaptation_exit(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--today", "2026-10-10", "--known-used", "1369",
                         "--period-end", "2026-10-31"])
        self.assertEqual(code, 1)
        self.assertIn("one scan every 172 min", out.getvalue())

    def test_json_plan_carries_the_numbers(self) -> None:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--today", "2026-10-10", "--known-used", "1369",
                         "--period-end", "2026-10-31", "--json"])
        self.assertEqual(code, 1)
        plan = json.loads(out.getvalue())
        self.assertEqual(plan["minutes_used"], 1369)
        self.assertEqual(plan["minutes_remaining"], 631)
        self.assertEqual(plan["capture_runway_minutes"], 366)
        self.assertEqual(plan["fires_affordable"], 30)
        self.assertEqual(plan["interval_minutes"], 172)
        self.assertEqual(plan["next_reset"], "2026-11-01")
        self.assertFalse(plan["fits_current_cadence"])

    def test_workflow_cost_override_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "costs.json"
            path.write_text(json.dumps([
                {"name": CAPTURE_WORKFLOW, "fires_per_month": 108.7,
                 "billed_minutes_per_fire": 14, "can_adapt": True,
                 "min_interval_minutes": 5, "max_interval_minutes": 1440},
                {"name": "signal_push", "fires_per_month": 43.5,
                 "billed_minutes_per_fire": 3},
                {"name": "governance_guard", "fires_per_month": 43.0,
                 "billed_minutes_per_fire": 1},
            ]), encoding="utf-8")
            overrides = _override_workflow_costs(path)
            self.assertEqual(overrides[0].billed_minutes_per_fire, 14)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--today", "2026-10-10", "--known-used", "1369",
                             "--period-end", "2026-10-31",
                             "--workflow-costs-json", str(path), "--json"])
            plan = json.loads(out.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(plan["fires_affordable"], 23)

    def test_override_naming_an_unknown_workflow_is_rejected(self) -> None:
        state = state_at(AUDIT_DAY)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "costs.json"
            path.write_text(json.dumps([{"name": "made_up_workflow",
                                         "fires_per_month": 1.0,
                                         "billed_minutes_per_fire": 1}]),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                _apply_overrides(state, path)

    def test_override_file_must_be_a_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "costs.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                _override_workflow_costs(path)

    def test_override_entry_needs_a_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "costs.json"
            path.write_text(json.dumps([{"fires_per_month": 1.0}]),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                _override_workflow_costs(path)


if __name__ == "__main__":
    unittest.main()
