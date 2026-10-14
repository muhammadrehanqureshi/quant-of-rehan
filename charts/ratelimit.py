"""Polite request pacing, bounded retries, and a circuit breaker.

Every upstream this service reads is somebody else's server, and the
project's own data memo says the polite thing out loud: PSX requests are
paced, not hammered. Three mechanisms live here, all of them injectable with
a clock so the tests can prove the behaviour without sleeping:

* ``TokenBucket`` paces requests to a sustained rate with a small burst.
  ``acquire()`` returns the seconds the caller must wait, and the caller
  decides whether to sleep, so this module never blocks on its own.
* ``retry_call`` retries only the failures that can succeed on a second
  attempt (timeouts, connection errors, 429, 5xx) with exponential backoff
  and jitter, and it stops at a hard attempt ceiling. A 404 is never
  retried: retrying a wrong URL is noise, not resilience.
* ``CircuitBreaker`` refuses to call an upstream that has failed repeatedly,
  for a cooldown, then lets exactly one probe through. That is what stops a
  dead source from turning every chart request into a fresh timeout.

The retry and breaker decisions are recorded in a small ``Ledger`` so the
service can report them in ``notes``, which is how the chart stays honest
about a degraded source instead of drawing an empty chart with no reason.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")


class UpstreamError(RuntimeError):
    """A source failure, with the category a consumer can act on."""

    #: Categories, ordered from most transient to least. The name travels in
    #: the API's notes and in the log line, so it is part of the contract.
    TIMEOUT = "TIMEOUT"
    CONNECTION = "CONNECTION"
    RATE_LIMITED = "RATE_LIMITED"
    HTTP_ERROR = "HTTP_ERROR"
    SCHEMA_CHANGE = "SCHEMA_CHANGE"
    EMPTY_ACK = "EMPTY_ACK"

    def __init__(self, category: str, detail: str, *, status: int | None = None):
        super().__init__(f"{category}: {detail}")
        self.category = category
        self.detail = detail
        self.status = status

    @property
    def retryable(self) -> bool:
        """Can a second attempt plausibly succeed?"""
        if self.category in (self.TIMEOUT, self.CONNECTION):
            return True
        if self.category == self.RATE_LIMITED:
            return True
        if self.category == self.HTTP_ERROR and self.status is not None:
            return self.status >= 500
        return False


class CircuitOpen(UpstreamError):
    """The breaker refused this call: the upstream is in its cooldown."""

    def __init__(self, detail: str):
        super().__init__(UpstreamError.CONNECTION, detail)
        self.category = "CIRCUIT_OPEN"


@dataclass
class TokenBucket:
    """Sustained-rate pacing with a burst allowance."""

    rate_per_second: float
    burst: int = 1
    _tokens: float = 0.0
    _stamp: float = field(default=0.0)
    _clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least one request")
        self._tokens = float(self.burst)
        self._stamp = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._stamp)
        self._stamp = now
        self._tokens = min(float(self.burst),
                           self._tokens + elapsed * self.rate_per_second)

    def acquire(self) -> float:
        """Take one token, returning the seconds the caller must wait first."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return 0.0
        missing = 1.0 - self._tokens
        self._tokens = 0.0
        return missing / self.rate_per_second


@dataclass
class CircuitBreaker:
    """Fail fast after repeated failures, then probe once per cooldown."""

    fail_threshold: int = 3
    reset_after_seconds: float = 60.0
    _failures: int = 0
    _opened_at: float | None = None
    _clock: Callable[[], float] = time.monotonic

    @property
    def open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.reset_after_seconds:
            # The cooldown has passed: allow one probe through.
            self._opened_at = None
            self._failures = self.fail_threshold - 1
            return False
        return True

    def before_call(self) -> None:
        if self.open:
            raise CircuitOpen(
                f"the source failed {self._failures} times in a row; "
                f"waiting {self.reset_after_seconds:.0f}s before probing it")

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_threshold and self._opened_at is None:
            self._opened_at = self._clock()


def retry_call(
    call: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay: float = 0.4,
    max_delay: float = 5.0,
    breaker: CircuitBreaker | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    on_retry: Callable[[int, UpstreamError, float], None] | None = None,
) -> T:
    """Call once, or a bounded number of times for a retryable failure.

    The jitter is proportional, not uniform: a herd of clients retrying the
    same source at the same instant is the failure mode this avoids, and
    proportionate jitter keeps the mean delay close to the backoff curve.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    chooser = rng or random
    last: UpstreamError | None = None
    for attempt in range(1, attempts + 1):
        if breaker is not None:
            breaker.before_call()
        try:
            result = call()
        except UpstreamError as exc:
            last = exc
            if breaker is not None:
                breaker.record_failure()
            if not exc.retryable or attempt == attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            # Jitter stays inside the ceiling: an upper bound that jitter can
            # exceed is not an upper bound, and the promise here is bounded
            # retries.
            delay = min(max_delay, delay * (0.5 + chooser.random()))
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            sleep(delay)
            continue
        if breaker is not None:
            breaker.record_success()
        return result
    raise last or UpstreamError(UpstreamError.CONNECTION, "no attempt was made")


@dataclass
class Ledger:
    """What the service did to a source, for the payload's own notes."""

    requests: int = 0
    retries: int = 0
    failures: dict[str, int] = field(default_factory=dict)

    def record_attempt(self) -> None:
        self.requests += 1

    def record_retry(self, exc: UpstreamError) -> None:
        self.retries += 1
        self.record_failure(exc)

    def record_failure(self, exc: UpstreamError) -> None:
        self.failures[exc.category] = self.failures.get(exc.category, 0) + 1

    def notes(self) -> Iterable[str]:
        if not self.requests:
            return ()
        lines = [f"upstream requests this payload: {self.requests}"]
        if self.retries:
            lines.append(f"retries: {self.retries}")
        for category, count in sorted(self.failures.items()):
            lines.append(f"{category}: {count}")
        return lines
