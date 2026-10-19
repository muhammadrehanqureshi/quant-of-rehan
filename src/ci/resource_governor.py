"""An in-process CPU governor for anything this repository runs by hand.

SO-21 (owner order 2026-10-19) is that this machine is not used at all, and
nothing in this repository runs a backtest, a suite or a validation here.
`guard_cloud_backtest` enforces that. This module is the second belt: if the
owner ever orders one local run, the cap below is the most it may take from
the machine underneath him, and the approval gate makes that run a decision he
makes rather than one a script makes for him.

The model
---------
CPU time is a budget, and a budget is spent at a rate. The governor keeps a
token bucket whose fill rate is the cap:

    allowance(t) = cap_fraction * (t - t0)

    debt = cpu_used - allowance

Whenever ``checkpoint()`` is called and the process has spent more CPU than
its allowance, the governor sleeps exactly long enough to earn the debt back:

    sleep = debt / cap_fraction

At 2 percent that means one CPU second costs fifty seconds of wall clock. This
is the only honest way to hold a *useful* process to a 2 percent average: an
instantaneous cap cannot be met by code that is running at all, because a
single Python bytecode loop on an idle core is 100 percent of that core for as
long as it runs. What is enforceable, and what this module enforces, is the
time-averaged ceiling over the governor's own lifetime, plus a checkpoint
between every unit of work so the overshoot is bounded by one unit.

The clock is injectable on purpose (``CpuMeter`` and ``sleep``), so the
arithmetic is testable without spending the wall clock it describes.

Approval, not silence
---------------------
A task that is expected to cost more than ``high_compute_cpu_seconds`` (five
CPU seconds, which is over four minutes of wall clock at 2 percent), or a
caller that asks for an intensity above the cap, must be approved before it
starts. The approver is a callable, so three cases stay separate:

  * an interactive owner answers a y/N prompt on a real terminal;
  * a pinned environment variable records his standing consent for an
    unattended run (``QOR_APPROVE_HIGH_COMPUTE=1``), set per process and
    never committed;
  * anything else, including every GitHub runner and every piped shell,
    answers no. A refusal is never a crash: the task either drops back to the
    cap and runs chunked, or raises ``ResourcePermissionDenied`` when the
    caller asked for ``on_denied="raise"`` because a fifty times slower run
    would be worse than none.

Blocking and asyncio
The waiting comes in two forms that share one budget: ``checkpoint``,
``governed`` and ``chunked`` block the thread, while ``acheckpoint``,
``agoverned``, ``arun`` and ``achunked`` pay the same debt with
``asyncio.sleep``. A scanner that already owns an event loop should use the
second, or its sockets would sit unread for the whole wait.

What this module does not do
----------------------------
It starts no thread, no timer and no watcher. A resident monitor would itself
be a background process on the owner's PC, which is the thing the machine rule
forbids. The governor only acts when the code it wraps calls back into it, so
a process that stops calling ``checkpoint()`` also stops being governed, and
the caller is responsible for calling it between units of work (``chunked``
and ``run`` do that for them).

It also cannot cap the rest of the machine. ``system_load_percent`` reads the
load so a caller can refuse to start while something else owns the CPU, but
the only process this module can throttle is its own.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import sys
import time
from dataclasses import dataclass, field
from typing import (AsyncIterator, Awaitable, Callable, Iterable, Iterator,
                    TypeVar)

__all__ = [
    "MAX_CPU_PERCENT",
    "APPROVAL_ENV",
    "ApprovalRequest",
    "CpuMeter",
    "GovernorPolicy",
    "GovernorStats",
    "GovernorConfigurationError",
    "ResourceGovernor",
    "ResourcePermissionDenied",
    "console_approver",
]

# Owner constraint, quoted in the docstring above: nothing wrapped by this
# module may average more than this share of one core. It is a constant rather
# than an argument so that no call site can quietly raise it; a task that
# genuinely needs more asks for ``requested_percent`` and pays for the answer
# with an approval.
MAX_CPU_PERCENT = 2.0

# Per-process consent, set by the owner in the shell that runs the task. It is
# deliberately not read from any file and never exported in a profile: the
# repo's governance tests treat inherited consent as the offence they guard.
APPROVAL_ENV = "QOR_APPROVE_HIGH_COMPUTE"

T = TypeVar("T")
R = TypeVar("R")


class GovernorConfigurationError(ValueError):
    """A policy that would let unattended work exceed the owner's ceiling."""


class ResourcePermissionDenied(RuntimeError):
    """The task needed more than the cap and nobody approved the intensity."""


def _children_cpu_seconds() -> float:
    """CPU seconds spent by child processes, or zero where the OS hides it."""
    try:
        times = os.times()
    except (AttributeError, OSError):  # pragma: no cover - platform specific
        return 0.0
    return float(times.children_user) + float(times.children_system)


@dataclass
class CpuMeter:
    """Where the governor reads CPU time and the clock.

    Defaults charge the whole process and its children: a subprocess that
    burns a core is exactly the case the owner's rule is about, and
    ``time.process_time()`` alone would never see it.
    """

    process_seconds: Callable[[], float] = time.process_time
    children_seconds: Callable[[], float] = _children_cpu_seconds
    wall_seconds: Callable[[], float] = time.monotonic

    def cpu_seconds(self) -> float:
        return float(self.process_seconds()) + float(self.children_seconds())


@dataclass(frozen=True)
class GovernorPolicy:
    """The cap, the approval threshold and what a refusal means.

    ``max_cpu_percent`` may never exceed :data:`MAX_CPU_PERCENT`. An approval
    is not a policy edit: it is a one-shot escalation carried by the
    ``GovernorStats.approvals`` entry for the task that asked for it.
    """

    max_cpu_percent: float = MAX_CPU_PERCENT
    high_compute_cpu_seconds: float = 5.0
    on_denied: str = "throttle"  # "throttle" keeps the cap, "raise" stops
    sleep_slack_seconds: float = 0.005

    def __post_init__(self) -> None:
        if not 0.0 < self.max_cpu_percent <= MAX_CPU_PERCENT:
            raise GovernorConfigurationError(
                f"max_cpu_percent must be in (0, {MAX_CPU_PERCENT}]; "
                f"got {self.max_cpu_percent}. A higher intensity has to be "
                f"approved per task with requested_percent, not configured.")
        if self.high_compute_cpu_seconds < 0:
            raise GovernorConfigurationError(
                "high_compute_cpu_seconds must not be negative")
        if self.on_denied not in {"throttle", "raise"}:
            raise GovernorConfigurationError(
                f"on_denied must be 'throttle' or 'raise'; got {self.on_denied!r}")


@dataclass(frozen=True)
class ApprovalRequest:
    """What the owner is being asked to allow, in the units he cares about."""

    label: str
    reason: str
    estimated_cpu_seconds: float | None
    requested_percent: float
    estimated_wall_seconds: float | None

    def describe(self) -> str:
        if self.estimated_cpu_seconds is None:
            cost = "cost unknown"
        else:
            cost = f"about {self.estimated_cpu_seconds:.2f} CPU seconds"
        if self.estimated_wall_seconds is None:
            wall = "wall clock unknown"
        else:
            wall = f"about {self.estimated_wall_seconds / 60.0:.1f} minutes of wall clock"
        return (f"{self.label}: {cost} at {self.requested_percent:g} percent "
                f"({wall}). {self.reason}".strip())


@dataclass
class GovernorStats:
    """Measured, never assumed: the governor reports what actually happened."""

    cpu_seconds: float = 0.0
    wall_seconds: float = 0.0
    slept_seconds: float = 0.0
    checkpoints: int = 0
    chunks: int = 0
    approvals_granted: int = 0
    approvals_denied: int = 0
    escalations: list[dict] = field(default_factory=list)

    @property
    def utilization_percent(self) -> float:
        if self.wall_seconds <= 0:
            return 0.0
        return 100.0 * self.cpu_seconds / self.wall_seconds

    def as_dict(self) -> dict:
        return {
            "cpu_seconds": round(self.cpu_seconds, 4),
            "wall_seconds": round(self.wall_seconds, 4),
            "slept_seconds": round(self.slept_seconds, 4),
            "utilization_percent": round(self.utilization_percent, 4),
            "checkpoints": self.checkpoints,
            "chunks": self.chunks,
            "approvals_granted": self.approvals_granted,
            "approvals_denied": self.approvals_denied,
            "escalations": list(self.escalations),
        }


def _env_consent() -> bool:
    return os.environ.get(APPROVAL_ENV, "").strip().lower() in {"1", "true", "yes"}


def _unattended() -> bool:
    """True where a prompt would block on something nobody is watching.

    A runner can still hand the process a stream that claims to be a TTY, so
    the CI markers are checked before ``isatty()``: a scheduled job must never
    sit waiting for an answer that cannot arrive.
    """
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() in {"1", "true"}:
        return True
    if os.environ.get("CI", "").strip().lower() in {"1", "true"}:
        return True
    return False


def console_approver(request: ApprovalRequest, *,
                     stream: object | None = None) -> bool:
    """Ask the owner on a real terminal, honour a pinned env var, else refuse.

    The env var is checked first so an unattended run the owner started with
    consent never blocks on a prompt that is not attached to anything.
    """
    if _env_consent():
        return True
    out = stream if stream is not None else sys.stderr
    if _unattended():
        print(f"[resource-governor] refused (unattended run): "
              f"{request.describe()}", file=out)
        return False
    try:
        interactive = bool(sys.stdin) and sys.stdin.isatty()
    except (AttributeError, ValueError):  # pragma: no cover - odd streams
        interactive = False
    if not interactive:
        print(f"[resource-governor] refused (no terminal to ask): "
              f"{request.describe()}", file=out)
        return False
    print(f"[resource-governor] permission needed: {request.describe()}", file=out)
    try:
        answer = input("Proceed? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("", file=out)
        return False
    return answer in {"y", "yes"}


class ResourceGovernor:
    """Holds this process to a CPU duty cycle, and asks before it goes over.

    One governor belongs to one thread. It is not re-entrant, because a nested
    ``governed()`` block would have two competing budgets for the same CPU
    time; the inner block simply inherits the outer cap.
    """

    def __init__(self, policy: GovernorPolicy | None = None, *,
                 meter: CpuMeter | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 approver: Callable[[ApprovalRequest], bool] | None = None,
                 stream: object | None = None) -> None:
        self.policy = policy or GovernorPolicy()
        self._meter = meter or CpuMeter()
        self._sleep = sleep
        self._stream = stream if stream is not None else sys.stderr
        self._approver = approver or (lambda request: console_approver(
            request, stream=self._stream))
        self._cpu0 = self._meter.cpu_seconds()
        self._wall0 = self._meter.wall_seconds()
        self._cap = self.policy.max_cpu_percent
        self._depth = 0
        self.stats = GovernorStats()

    # ---------------------------------------------------------------- budget

    def _fraction(self, percent: float) -> float:
        return percent / 100.0

    def cpu_seconds(self) -> float:
        return max(0.0, self._meter.cpu_seconds() - self._cpu0)

    def wall_seconds(self) -> float:
        return max(0.0, self._meter.wall_seconds() - self._wall0)

    def allowance_seconds(self) -> float:
        """CPU seconds this process has earned so far at the active cap."""
        return self._fraction(self._cap) * self.wall_seconds()

    def debt_seconds(self) -> float:
        """CPU seconds spent beyond the allowance. Positive means overspent."""
        return self.cpu_seconds() - self.allowance_seconds()

    def _delay_seconds(self) -> float:
        """How long to wait for the debt to be earned back, or zero."""
        debt = self.debt_seconds()
        if debt <= 0:
            return 0.0
        return debt / self._fraction(self._cap) + self.policy.sleep_slack_seconds

    def checkpoint(self) -> float:
        """Sleep until the process is back inside its cap; return slept seconds.

        Call this between units of work. The sleep is computed from measured
        CPU time, never from an estimate, so a slow unit is paid for by the
        next checkpoint rather than by a guess.
        """
        self.stats.checkpoints += 1
        delay = self._delay_seconds()
        if delay <= 0:
            return 0.0
        self._sleep(delay)
        self.stats.slept_seconds += delay
        return delay

    async def acheckpoint(self) -> float:
        """The checkpoint for asyncio callers: yield, do not block the loop.

        The arithmetic is identical; only the wait differs. A scanner that
        already owns an event loop can pay its CPU debt without freezing the
        socket reads it is supposed to be watching.
        """
        self.stats.checkpoints += 1
        delay = self._delay_seconds()
        if delay <= 0:
            return 0.0
        await asyncio.sleep(delay)
        self.stats.slept_seconds += delay
        return delay

    def snapshot(self) -> dict:
        """Refresh stats from the meter and return them as plain JSON data."""
        self.stats.cpu_seconds = self.cpu_seconds()
        self.stats.wall_seconds = self.wall_seconds()
        return self.stats.as_dict()

    # -------------------------------------------------------------- approval

    def request_high_compute(self, label: str, *,
                             estimated_cpu_seconds: float | None = None,
                             requested_percent: float | None = None,
                             reason: str = "") -> bool:
        """Ask whether this task may run above the ceiling.

        Returns the owner's answer. It records the request either way, so a
        refused task is visible in the run's stats instead of silently
        shrinking to the cap.
        """
        percent = requested_percent if requested_percent is not None \
            else self.policy.max_cpu_percent
        if percent <= 0:
            raise GovernorConfigurationError(
                f"requested_percent must be positive; got {percent}")
        request = ApprovalRequest(
            label=label,
            reason=reason or "high-compute task",
            estimated_cpu_seconds=estimated_cpu_seconds,
            requested_percent=percent,
            estimated_wall_seconds=(
                None if estimated_cpu_seconds is None
                else estimated_cpu_seconds / self._fraction(percent)),
        )
        granted = bool(self._approver(request))
        if granted:
            self.stats.approvals_granted += 1
            self.stats.escalations.append({
                "label": label,
                "percent": percent,
                "estimated_cpu_seconds": estimated_cpu_seconds,
            })
        else:
            self.stats.approvals_denied += 1
        return granted

    def _needs_approval(self, estimated_cpu_seconds: float | None,
                        requested_percent: float | None) -> bool:
        if requested_percent is not None and \
                requested_percent > self.policy.max_cpu_percent:
            return True
        if estimated_cpu_seconds is not None and \
                estimated_cpu_seconds >= self.policy.high_compute_cpu_seconds:
            return True
        return False

    # ------------------------------------------------------------- execution

    def _begin(self, label: str, estimated_cpu_seconds: float | None,
               requested_percent: float | None, reason: str) -> float:
        """Settle the approval question and enter the block; return the cap."""
        previous = self._cap
        if self._depth == 0 and self._needs_approval(estimated_cpu_seconds,
                                                     requested_percent):
            granted = self.request_high_compute(
                label,
                estimated_cpu_seconds=estimated_cpu_seconds,
                requested_percent=requested_percent,
                reason=reason)
            if granted:
                self._cap = requested_percent if requested_percent is not None \
                    else self.policy.max_cpu_percent
            elif requested_percent is not None and \
                    requested_percent > self.policy.max_cpu_percent:
                if self.policy.on_denied == "raise":
                    raise ResourcePermissionDenied(
                        f"{label}: {requested_percent:g} percent was refused; "
                        f"the cap is {self.policy.max_cpu_percent:g} percent "
                        f"and on_denied is 'raise'")
                print(f"[resource-governor] {label} runs at "
                      f"{self.policy.max_cpu_percent:g} percent instead",
                      file=self._stream)
        self._depth += 1
        return previous

    def _release(self, previous: float) -> None:
        self._depth -= 1
        self._cap = previous

    @contextlib.contextmanager
    def governed(self, label: str, *,
                 estimated_cpu_seconds: float | None = None,
                 requested_percent: float | None = None,
                 reason: str = "") -> Iterator["ResourceGovernor"]:
        """Run a block under the cap, or under an approved intensity.

        Refusal behaviour follows ``policy.on_denied``:
        ``"throttle"`` runs the block at the cap, ``"raise"`` stops before any
        work is done.
        """
        previous = self._begin(label, estimated_cpu_seconds,
                               requested_percent, reason)
        try:
            yield self
        finally:
            self.checkpoint()
            self._release(previous)

    @contextlib.asynccontextmanager
    async def agoverned(self, label: str, *,
                        estimated_cpu_seconds: float | None = None,
                        requested_percent: float | None = None,
                        reason: str = "") -> AsyncIterator["ResourceGovernor"]:
        """``governed`` for asyncio: the debt is paid with ``asyncio.sleep``."""
        previous = self._begin(label, estimated_cpu_seconds,
                               requested_percent, reason)
        try:
            yield self
        finally:
            await self.acheckpoint()
            self._release(previous)

    def run(self, task: Callable[[], R], *, label: str,
            estimated_cpu_seconds: float | None = None,
            requested_percent: float | None = None,
            reason: str = "") -> R:
        """Run one callable under the governor, then pay for its CPU."""
        with self.governed(label, estimated_cpu_seconds=estimated_cpu_seconds,
                           requested_percent=requested_percent, reason=reason):
            result = task()
        return result

    def chunked(self, items: Iterable[T], task: Callable[[T], R], *,
                label: str, estimated_cpu_seconds: float | None = None,
                requested_percent: float | None = None,
                reason: str = "") -> list[R]:
        """Run ``task`` over ``items``, checkpointing after every item.

        A single item cannot be preempted from outside: if one call burns a
        whole core for a second, the overshoot is that second and the
        checkpoint after it sleeps fifty seconds. Splitting the work finer is
        the caller's lever, which is why the estimate is explicit.
        """
        results: list[R] = []
        with self.governed(label, estimated_cpu_seconds=estimated_cpu_seconds,
                           requested_percent=requested_percent, reason=reason):
            for item in items:
                results.append(task(item))
                self.stats.chunks += 1
                self.checkpoint()
        return results

    async def arun(self, task: Callable[[], R] | Callable[[], Awaitable[R]], *,
                   label: str, estimated_cpu_seconds: float | None = None,
                   requested_percent: float | None = None,
                   reason: str = "") -> R:
        """``run`` for asyncio; a coroutine function is awaited, a plain one is called."""
        async with self.agoverned(label,
                                  estimated_cpu_seconds=estimated_cpu_seconds,
                                  requested_percent=requested_percent,
                                  reason=reason):
            outcome = task()
            if inspect.isawaitable(outcome):
                outcome = await outcome
        return outcome  # type: ignore[return-value]

    async def achunked(
            self, items: Iterable[T],
            task: Callable[[T], R] | Callable[[T], Awaitable[R]], *,
            label: str, estimated_cpu_seconds: float | None = None,
            requested_percent: float | None = None,
            reason: str = "") -> list[R]:
        """``chunked`` for asyncio, so the wait does not freeze the event loop."""
        results: list[R] = []
        async with self.agoverned(label,
                                  estimated_cpu_seconds=estimated_cpu_seconds,
                                  requested_percent=requested_percent,
                                  reason=reason):
            for item in items:
                outcome = task(item)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                results.append(outcome)  # type: ignore[arg-type]
                self.stats.chunks += 1
                await self.acheckpoint()
        return results


def system_load_percent(sample_seconds: float = 0.1) -> float:
    """Machine-wide CPU busy share over a short sample, 0 to 100.

    Stdlib only: no psutil dependency and no resident sampler. This is a
    reading, not a control, so it exists for callers that want to refuse to
    start while something else is using the machine.
    """
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        psutil = None
    if psutil is not None:  # pragma: no cover - optional dependency
        return float(psutil.cpu_percent(interval=sample_seconds))

    if hasattr(os, "getloadavg"):  # pragma: no cover - POSIX only
        start = time.monotonic()
        before = os.getloadavg()[0]
        time.sleep(sample_seconds)
        after = os.getloadavg()[0]
        idle = max(0.05, time.monotonic() - start)
        # getloadavg is a moving average, not an instant; the delta over the
        # sample is the closest stdlib proxy and is reported as such.
        return max(0.0, min(100.0, 100.0 * (after - before) / idle))

    return 0.0
