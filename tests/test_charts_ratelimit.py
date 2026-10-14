"""Polite pacing, bounded retries and the circuit breaker.

The tests drive a fake clock and a fake sleep, so the behaviour is proven
without waiting: a bucket that paces a second request, a retry that backs off
and gives up at its ceiling, a 404 that is never retried (retrying a wrong
URL is noise, not resilience), and a breaker that stops a dead source from
turning every request into a fresh timeout.
"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.ratelimit import (  # noqa: E402
    CircuitBreaker, Ledger, TokenBucket, UpstreamError, retry_call,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.advance(seconds)


class BucketTest(unittest.TestCase):

    def test_the_burst_is_available_immediately(self):
        bucket = TokenBucket(rate_per_second=1.0, burst=2, _clock=FakeClock())
        self.assertEqual(bucket.acquire(), 0.0)
        self.assertEqual(bucket.acquire(), 0.0)

    def test_the_third_request_is_paced(self):
        clock = FakeClock()
        bucket = TokenBucket(rate_per_second=2.0, burst=2, _clock=clock)
        bucket.acquire()
        bucket.acquire()
        self.assertAlmostEqual(bucket.acquire(), 0.5)

    def test_tokens_refill_with_time(self):
        clock = FakeClock()
        bucket = TokenBucket(rate_per_second=1.0, burst=1, _clock=clock)
        bucket.acquire()
        clock.advance(1.0)
        self.assertEqual(bucket.acquire(), 0.0)

    def test_nonsense_settings_are_refused(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate_per_second=0.0)
        with self.assertRaises(ValueError):
            TokenBucket(rate_per_second=1.0, burst=0)


class RetryTest(unittest.TestCase):

    def test_a_timeout_is_retried_and_can_succeed(self):
        clock = FakeClock()
        calls = []

        def call():
            calls.append(1)
            if len(calls) < 3:
                raise UpstreamError(UpstreamError.TIMEOUT, "no answer")
            return "ok"

        got = retry_call(call, attempts=3, base_delay=0.4, sleep=clock.sleep,
                         rng=random.Random(1))
        self.assertEqual(got, "ok")
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(clock.slept), 2)
        # Jitter is proportional: each delay stays within its backoff band.
        self.assertGreaterEqual(clock.slept[0], 0.4 * 0.5)
        self.assertLessEqual(clock.slept[0], 0.4 * 1.5)
        self.assertGreaterEqual(clock.slept[1], 0.8 * 0.5)
        self.assertLessEqual(clock.slept[1], 0.8 * 1.5)

    def test_a_404_is_never_retried(self):
        clock = FakeClock()
        calls = []

        def call():
            calls.append(1)
            raise UpstreamError(UpstreamError.HTTP_ERROR, "HTTP 404",
                                status=404)

        with self.assertRaises(UpstreamError):
            retry_call(call, attempts=3, sleep=clock.sleep)
        self.assertEqual(len(calls), 1)
        self.assertEqual(clock.slept, [])

    def test_a_500_is_retried(self):
        clock = FakeClock()
        calls = []

        def call():
            calls.append(1)
            raise UpstreamError(UpstreamError.HTTP_ERROR, "HTTP 503",
                                status=503)

        with self.assertRaises(UpstreamError):
            retry_call(call, attempts=3, sleep=clock.sleep,
                       rng=random.Random(2))
        self.assertEqual(len(calls), 3)

    def test_retries_stop_at_the_attempt_ceiling(self):
        clock = FakeClock()
        calls = []

        def call():
            calls.append(1)
            raise UpstreamError(UpstreamError.CONNECTION, "reset")

        with self.assertRaises(UpstreamError):
            retry_call(call, attempts=4, sleep=clock.sleep,
                       rng=random.Random(3))
        self.assertEqual(len(calls), 4)
        self.assertEqual(len(clock.slept), 3)

    def test_a_delay_can_never_exceed_the_ceiling(self):
        clock = FakeClock()

        def call():
            raise UpstreamError(UpstreamError.TIMEOUT, "slow")

        with self.assertRaises(UpstreamError):
            retry_call(call, attempts=5, base_delay=1.0, max_delay=2.0,
                       sleep=clock.sleep, rng=random.Random(4))
        self.assertTrue(all(delay <= 2.0 for delay in clock.slept))

    def test_on_retry_is_told_what_happened(self):
        clock = FakeClock()
        seen = []

        def call():
            if not seen:
                raise UpstreamError(UpstreamError.RATE_LIMITED, "429")
            return 1

        retry_call(call, attempts=2, sleep=clock.sleep,
                   on_retry=lambda attempt, exc, delay: seen.append(
                       (attempt, exc.category, delay)))
        self.assertEqual(seen[0][0], 1)
        self.assertEqual(seen[0][1], UpstreamError.RATE_LIMITED)
        self.assertGreater(seen[0][2], 0)


class BreakerTest(unittest.TestCase):

    def test_the_breaker_opens_after_repeated_failures(self):
        clock = FakeClock()
        breaker = CircuitBreaker(fail_threshold=2, reset_after_seconds=30.0,
                                 _clock=clock)
        calls = []

        def call():
            calls.append(1)
            raise UpstreamError(UpstreamError.CONNECTION, "refused")

        for _ in range(2):
            with self.assertRaises(UpstreamError):
                retry_call(call, attempts=1, breaker=breaker)
        with self.assertRaises(UpstreamError) as caught:
            retry_call(call, attempts=1, breaker=breaker)
        self.assertEqual(caught.exception.category, "CIRCUIT_OPEN")
        self.assertEqual(len(calls), 2, "the third call never reached source")

    def test_a_success_resets_the_breaker(self):
        clock = FakeClock()
        breaker = CircuitBreaker(fail_threshold=2, reset_after_seconds=30.0,
                                 _clock=clock)

        def fail():
            raise UpstreamError(UpstreamError.TIMEOUT, "no")

        for _ in range(2):
            with self.assertRaises(UpstreamError):
                retry_call(fail, attempts=1, breaker=breaker)
        self.assertTrue(breaker.open)
        clock.advance(30.0)  # the probe window opens
        retry_call(lambda: "ok", attempts=1, breaker=breaker)
        self.assertFalse(breaker.open)

    def test_the_cooldown_lets_one_probe_through(self):
        clock = FakeClock()
        breaker = CircuitBreaker(fail_threshold=2, reset_after_seconds=30.0,
                                 _clock=clock)

        def fail():
            raise UpstreamError(UpstreamError.CONNECTION, "refused")

        for _ in range(2):
            with self.assertRaises(UpstreamError):
                retry_call(fail, attempts=1, breaker=breaker)
        self.assertTrue(breaker.open)
        clock.advance(30.0)
        self.assertFalse(breaker.open)
        # The probe is allowed, and its failure re-arms the breaker.
        with self.assertRaises(UpstreamError) as caught:
            retry_call(fail, attempts=1, breaker=breaker)
        self.assertNotEqual(caught.exception.category, "CIRCUIT_OPEN")
        self.assertTrue(breaker.open)
        with self.assertRaises(UpstreamError) as blocked:
            retry_call(fail, attempts=1, breaker=breaker)
        self.assertEqual(blocked.exception.category, "CIRCUIT_OPEN")


class LedgerTest(unittest.TestCase):

    def test_the_ledger_says_what_happened_to_the_source(self):
        ledger = Ledger()
        ledger.record_attempt()
        ledger.record_attempt()
        ledger.record_retry(UpstreamError(UpstreamError.TIMEOUT, "slow"))
        lines = list(ledger.notes())
        self.assertIn("upstream requests this payload: 2", lines)
        self.assertIn("retries: 1", lines)
        self.assertIn("TIMEOUT: 1", lines)

    def test_an_unused_ledger_says_nothing(self):
        self.assertEqual(list(Ledger().notes()), [])

    def test_retryable_classification(self):
        self.assertTrue(UpstreamError(UpstreamError.TIMEOUT, "x").retryable)
        self.assertTrue(UpstreamError(UpstreamError.CONNECTION, "x").retryable)
        self.assertTrue(UpstreamError(UpstreamError.RATE_LIMITED, "x").retryable)
        self.assertTrue(UpstreamError(UpstreamError.HTTP_ERROR, "x",
                                      status=502).retryable)
        self.assertFalse(UpstreamError(UpstreamError.HTTP_ERROR, "x",
                                       status=404).retryable)
        self.assertFalse(UpstreamError(UpstreamError.SCHEMA_CHANGE,
                                       "x").retryable)
        self.assertFalse(UpstreamError(UpstreamError.EMPTY_ACK,
                                       "x").retryable)


if __name__ == "__main__":
    unittest.main()
