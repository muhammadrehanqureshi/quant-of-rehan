"""The session failsafe: always scanning, never on one cron fire.

Owner order 2026-11-11, verbatim: "I want you to introduce a fail safe for Quant
of Rehan. So the Quant of Rehan can possibly never be down and always scan the
pre and post market."

These tests pin the decision table and the two things the workflow must do:
carry the permission to dispatch, and call the one script. Everything is
offline: no socket is opened and nothing is dispatched.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import failsafe  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "session-failsafe.yml"
GUARD = ROOT / ".github" / "workflows" / "relay-budget-guard.yml"

WEDNESDAY = (2026, 11, 11)          # a PSX trading day
SATURDAY = (2026, 11, 14)


def at(day: tuple[int, int, int], hour: int, minute: int) -> datetime:
    return datetime(day[0], day[1], day[2], hour, minute, tzinfo=KARACHI)


def flow_stamped(moment: datetime, age_seconds: float) -> dict:
    return {"as_of": (moment - timedelta(seconds=age_seconds)).isoformat()}


class FailsafeDecisionTest(unittest.TestCase):

    def test_a_weekend_dispatches_nothing(self):
        decision = failsafe.decide(at(SATURDAY, 9, 20),
                                   {"market_feed": {"age_seconds": 900}},
                                   {"as_of": "2026-11-14T09:00:00+05:00"})
        self.assertFalse(decision.dispatch)
        self.assertFalse(decision.alert)
        self.assertIn("not a PSX trading day", decision.reason)

    def test_outside_every_window_dispatches_nothing(self):
        # 08:31 PKT is before the pre-open window starts.
        decision = failsafe.decide(at(WEDNESDAY, 8, 31), {}, {})
        self.assertFalse(decision.dispatch)
        self.assertIn("outside every scan window", decision.reason)

    def test_a_stale_feed_in_the_pre_open_dispatches_without_an_email(self):
        moment = at(WEDNESDAY, 9, 20)
        decision = failsafe.decide(
            moment, {"market_feed": {"age_seconds": 900}},
            flow_stamped(moment, 900))
        self.assertTrue(decision.dispatch)
        self.assertFalse(decision.alert)
        self.assertIn("old inside PRE_MARKET", decision.reason)

    def test_nothing_dispatches_before_the_pre_open_opens(self):
        # Owner order 2026-11-12 (latest): the capture starts with the 09:15
        # pre-open, so 09:00 Wednesday is outside every window and a stale feed
        # there starts no band.
        moment = at(WEDNESDAY, 9, 0)
        decision = failsafe.decide(
            moment, {"market_feed": {"age_seconds": 900}},
            flow_stamped(moment, 900))
        self.assertFalse(decision.dispatch)
        self.assertFalse(decision.alert)
        self.assertIn("outside every scan window", decision.reason)

    def test_a_fresh_capture_before_the_pre_open_dispatches_nothing(self):
        moment = at(WEDNESDAY, 9, 0)
        decision = failsafe.decide(
            moment, {"market_feed": {"age_seconds": 2}},
            flow_stamped(moment, 2))
        self.assertFalse(decision.dispatch)
        self.assertIn("outside every scan window", decision.reason)

    def test_a_stale_feed_in_the_post_market_dispatches(self):
        moment = at(WEDNESDAY, 15, 45)
        decision = failsafe.decide(
            moment, {"market_feed": {"age_seconds": failsafe.STALE_SECONDS + 1}},
            flow_stamped(moment, failsafe.STALE_SECONDS + 1))
        self.assertTrue(decision.dispatch)
        self.assertIn("POST_MARKET", decision.reason)

    def test_a_fresh_feed_dispatches_nothing(self):
        moment = at(WEDNESDAY, 10, 30)
        decision = failsafe.decide(
            moment, {"market_feed": {"age_seconds": 2}},
            flow_stamped(moment, 2))
        self.assertFalse(decision.dispatch)
        self.assertFalse(decision.alert)
        self.assertIn("the feed is 2 s old", decision.reason)

    def test_a_silent_relay_dispatches_and_alerts(self):
        decision = failsafe.decide(at(WEDNESDAY, 9, 20), None, None)
        self.assertTrue(decision.dispatch)
        self.assertTrue(decision.alert)
        self.assertIn("/health", decision.reason)

    def test_a_relay_without_a_frame_time_is_treated_as_dead(self):
        decision = failsafe.decide(at(WEDNESDAY, 9, 20), {}, {})
        self.assertTrue(decision.dispatch)
        self.assertFalse(decision.alert)
        self.assertIn("cannot be shown alive", decision.reason)

    def test_the_flow_stamp_is_the_fallback_when_health_names_no_age(self):
        moment = at(WEDNESDAY, 9, 20)
        health = {"market_feed": {"age_seconds": None}}
        decision = failsafe.decide(moment, health, flow_stamped(moment, 600))
        self.assertTrue(decision.dispatch)
        self.assertIn("600 s old", decision.reason)

    def test_a_naive_instant_is_refused(self):
        with self.assertRaises(ValueError):
            failsafe.decide(datetime(2026, 11, 11, 9, 20), {}, {})


class FailsafeWorkflowTest(unittest.TestCase):

    def test_a_queued_band_counts_as_running(self):
        """GitHub keeps one pending run per group; a retry that lands on top
        of it cancels the band it was trying to save."""
        script = (ROOT / "scripts" / "session_failsafe.py").read_text(
            encoding="utf-8")
        self.assertIn('for status in ("in_progress", "queued"):', script)

    def test_the_workflow_may_dispatch_and_calls_the_one_script(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("actions: write", text)
        self.assertIn("python scripts/session_failsafe.py", text)
        self.assertIn("*/10 4-10 * * 1-5", text)

    def test_the_script_dispatches_the_band_loop_and_never_sleeps(self):
        source = (ROOT / "scripts" / "session_failsafe.py").read_text(
            encoding="utf-8")
        self.assertIn("intraday-session.yml", source)
        self.assertIn("dispatches", source)
        self.assertNotIn("time.sleep(", source)

    def test_the_budget_guard_retries_before_it_emails(self):
        """Three tries through the shared reader, never a bare urllib call."""
        text = GUARD.read_text(encoding="utf-8")
        self.assertIn('read_json(BASE, "/health", attempts=3)', text)
        self.assertIn("after three attempts", text)
        self.assertIn("from src.data.relay_http import read_json", text,
                      "a browser style identity, or Cloudflare answers 403")
        self.assertNotIn("urllib.request.urlopen(BASE", text)


if __name__ == "__main__":
    unittest.main()
