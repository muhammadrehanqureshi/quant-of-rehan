"""Behaviour tests for src/ci/resource_governor.py.

The governor's whole promise is arithmetic, so the tests run it against a fake
clock: CPU seconds and wall seconds move in a script the test controls, and
the sleeps are recorded instead of waited. That is the only way to assert a
two percent ceiling without making the suite itself cost minutes of CPU, which
would be the exact thing the module exists to prevent.
"""

from __future__ import annotations

import io
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.resource_governor import (  # noqa: E402
    APPROVAL_ENV,
    MAX_CPU_PERCENT,
    ApprovalRequest,
    CpuMeter,
    GovernorConfigurationError,
    GovernorPolicy,
    ResourceGovernor,
    ResourcePermissionDenied,
    console_approver,
)


class FakeMachine:
    """A clock where the test decides when work happens and how much it costs."""

    def __init__(self) -> None:
        self.cpu = 0.0
        self.wall = 0.0
        self.sleeps: list[float] = []

    def meter(self) -> CpuMeter:
        return CpuMeter(
            process_seconds=lambda: self.cpu,
            children_seconds=lambda: 0.0,
            wall_seconds=lambda: self.wall,
        )

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.wall += seconds

    def burn(self, seconds: float) -> None:
        """Work that costs CPU at a full core for exactly that long."""
        self.cpu += seconds
        self.wall += seconds

    @property
    def slept(self) -> float:
        return sum(self.sleeps)


def governor(machine: FakeMachine, **policy_kwargs) -> ResourceGovernor:
    return ResourceGovernor(
        GovernorPolicy(**policy_kwargs),
        meter=machine.meter(),
        sleep=machine.sleep,
        approver=lambda request: False,
        stream=io.StringIO(),
    )


class BudgetTest(unittest.TestCase):
    def test_a_busy_second_costs_fifty_seconds_of_wall_clock(self):
        machine = FakeMachine()
        gov = governor(machine)
        machine.burn(1.0)
        slept = gov.checkpoint()
        self.assertAlmostEqual(slept, 49.0, delta=0.05)
        gov.snapshot()
        self.assertLessEqual(gov.stats.utilization_percent, 2.0 + 0.01,
                             "one CPU second must settle at or under two percent")

    def test_an_idle_process_is_never_delayed(self):
        machine = FakeMachine()
        gov = governor(machine)
        self.assertEqual(gov.checkpoint(), 0.0)
        machine.wall += 5.0  # five quiet seconds earn five seconds of allowance
        self.assertEqual(gov.checkpoint(), 0.0)
        self.assertEqual(machine.sleeps, [])

    def test_the_running_average_never_exceeds_the_cap(self):
        machine = FakeMachine()
        gov = governor(machine)
        for _ in range(40):
            machine.burn(0.05)
            gov.checkpoint()
            self.assertLessEqual(gov.debt_seconds(), 0.0,
                                 "a checkpoint must leave no debt behind")
        gov.snapshot()
        self.assertLessEqual(gov.stats.utilization_percent, 2.0 + 0.01)
        self.assertGreater(machine.slept, 90.0,
                           "forty units at two percent is over two minutes of wall clock")

    def test_children_are_charged_to_the_same_budget(self):
        children = [0.0]
        meter = CpuMeter(process_seconds=lambda: 0.0,
                         children_seconds=lambda: children[0],
                         wall_seconds=lambda: 0.0)
        gov = ResourceGovernor(GovernorPolicy(), meter=meter,
                               sleep=lambda seconds: None,
                               approver=lambda request: False,
                               stream=io.StringIO())
        self.assertEqual(gov.debt_seconds(), 0.0)
        children[0] = 0.5  # a subprocess burned half a second
        self.assertEqual(meter.cpu_seconds(), 0.5)
        self.assertAlmostEqual(gov.debt_seconds(), 0.5, places=6,
                               msg="child CPU must be charged like our own")

    def test_the_policy_refuses_a_cap_above_the_owner_ceiling(self):
        self.assertEqual(MAX_CPU_PERCENT, 2.0)
        with self.assertRaises(GovernorConfigurationError):
            GovernorPolicy(max_cpu_percent=2.5)
        with self.assertRaises(GovernorConfigurationError):
            GovernorPolicy(max_cpu_percent=0.0)
        GovernorPolicy(max_cpu_percent=2.0)  # the ceiling itself is allowed

    def test_a_bad_denial_mode_is_refused_at_construction(self):
        with self.assertRaises(GovernorConfigurationError):
            GovernorPolicy(on_denied="ignore")


class ApprovalTest(unittest.TestCase):
    def test_a_refusal_stops_the_task_when_the_caller_asked_to_stop(self):
        machine = FakeMachine()
        gov = governor(machine, on_denied="raise")
        ran: list[str] = []
        with self.assertRaises(ResourcePermissionDenied):
            gov.run(lambda: ran.append("x"), label="monte carlo",
                    estimated_cpu_seconds=60.0, requested_percent=80.0)
        self.assertEqual(ran, [], "a refused task must not have started")
        self.assertEqual(gov.stats.approvals_denied, 1)

    def test_a_refusal_drops_back_to_the_cap_when_throttling(self):
        machine = FakeMachine()
        gov = governor(machine, on_denied="throttle")
        with gov.governed("grid search", requested_percent=50.0,
                          estimated_cpu_seconds=30.0) as inner:
            self.assertEqual(inner._cap, MAX_CPU_PERCENT)
            machine.burn(0.1)
        self.assertEqual(gov.stats.approvals_denied, 1)
        self.assertEqual(gov.stats.escalations, [])

    def test_an_approved_escalation_runs_at_that_intensity(self):
        machine = FakeMachine()
        gov = ResourceGovernor(GovernorPolicy(), meter=machine.meter(),
                               sleep=machine.sleep,
                               approver=lambda request: True,
                               stream=io.StringIO())
        with gov.governed("factor sweep", requested_percent=25.0,
                          estimated_cpu_seconds=30.0) as inner:
            self.assertEqual(inner._cap, 25.0)
            machine.burn(1.0)
        self.assertAlmostEqual(gov.stats.slept_seconds, 3.0, delta=0.05,
                               msg="at 25 percent one CPU second needs three more")
        self.assertEqual(gov.stats.approvals_granted, 1)
        self.assertEqual(gov.stats.escalations[0]["percent"], 25.0)
        # The escalation is for that block only.
        self.assertEqual(gov._cap, MAX_CPU_PERCENT)

    def test_the_estimate_alone_triggers_the_prompt(self):
        machine = FakeMachine()
        gov = governor(machine)
        gov.run(lambda: None, label="walk forward", estimated_cpu_seconds=10.0)
        self.assertEqual(gov.stats.approvals_denied, 1,
                         "ten CPU seconds is over four minutes at the cap")
        self.assertEqual(gov.stats.escalations, [])

    def test_a_cheap_task_is_never_asked_about(self):
        machine = FakeMachine()
        gov = governor(machine)
        gov.run(lambda: None, label="tidy", estimated_cpu_seconds=0.1)
        self.assertEqual(gov.stats.approvals_granted + gov.stats.approvals_denied, 0)


class ChunkedTest(unittest.TestCase):
    def test_every_item_runs_in_order_and_the_budget_is_paid(self):
        machine = FakeMachine()
        gov = governor(machine)

        def work(item: int) -> int:
            machine.burn(0.01)
            return item * 2

        results = gov.chunked(range(5), work, label="bars")
        self.assertEqual(results, [0, 2, 4, 6, 8])
        self.assertEqual(gov.stats.chunks, 5)
        self.assertGreaterEqual(gov.stats.checkpoints, 5)
        self.assertLessEqual(gov.debt_seconds(), 0.0)

    def test_a_block_pays_on_the_way_out(self):
        machine = FakeMachine()
        gov = governor(machine)
        with gov.governed("one burst"):
            machine.burn(0.5)
        self.assertGreater(gov.stats.slept_seconds, 20.0)


class ApprovalSurfaceTest(unittest.TestCase):
    class _PipedStdin(io.StringIO):
        def isatty(self) -> bool:
            return False

    def _request(self) -> ApprovalRequest:
        return ApprovalRequest("sweep", "needs 30 percent", 60.0, 30.0, 200.0)

    def test_a_piped_shell_refuses_without_asking(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(APPROVAL_ENV, None)
            with patch.object(sys, "stdin", self._PipedStdin()):
                granted = console_approver(self._request(), stream=stream)
        self.assertFalse(granted)
        self.assertIn("refused", stream.getvalue())

    def test_a_runner_never_waits_for_an_answer(self):
        stream = io.StringIO()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with patch.object(sys, "stdin", self._PipedStdin()):
                granted = console_approver(self._request(), stream=stream)
        self.assertFalse(granted)
        self.assertIn("unattended", stream.getvalue())
        self.assertNotIn("Proceed?", stream.getvalue(),
                         "a scheduled job must not print a prompt it cannot read")

    def test_a_pinned_environment_variable_records_consent(self):
        with patch.dict(os.environ, {APPROVAL_ENV: "1"}):
            with patch.object(sys, "stdin", self._PipedStdin()):
                self.assertTrue(console_approver(self._request(),
                                                 stream=io.StringIO()))


if __name__ == "__main__":
    unittest.main()
