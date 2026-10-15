"""The chart side of the session law: minute lists, bands, market context.

`src/data/sessions.py` owns PSX hours; `charts/sessions.py` shapes them for a
chart. The tests here fix the two things a chart reads from it:

  * the expected minute list a session is measured against, both as it stands
    now and as a whole finished day; and
  * the market context that travels with every payload, including the live
    band, which is only ever exercised when a moment inside the session is
    rendered (the wall clock is often outside it, which is how a band that
    was silently never read could pass unnoticed).

Every moment here is stated, never taken from the clock, so the file passes
at 03:00 and at noon alike.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts import sessions  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY = date(2026, 10, 12)
FRIDAY = date(2026, 10, 9)
SUNDAY = date(2026, 10, 11)


class MinutesTest(unittest.TestCase):

    def test_the_whole_session_is_every_band_minute(self):
        minutes = sessions.session_minutes(MONDAY)
        self.assertEqual(len(minutes), 359)  # 09:32 to 15:30, minute by minute
        self.assertEqual(minutes[0].isoformat(), "2026-10-12T09:32:00+05:00")
        self.assertEqual(minutes[-1].isoformat(), "2026-10-12T15:30:00+05:00")
        self.assertEqual(minutes, sorted(minutes))

    def test_a_friday_break_is_never_a_minute(self):
        """The midday break is outside the session, not missing from it."""
        minutes = sessions.session_minutes(FRIDAY)
        self.assertEqual(minutes[0].isoformat(), "2026-10-09T09:17:00+05:00")
        self.assertEqual(minutes[-1].isoformat(), "2026-10-09T16:30:00+05:00")
        stamps = {moment.strftime("%H:%M") for moment in minutes}
        self.assertNotIn("13:00", stamps)  # inside the Friday break
        self.assertIn("14:32", stamps)  # the second band is still there
        self.assertEqual(len(minutes), 283)

    def test_expected_minutes_runs_up_to_the_stated_moment(self):
        moment = datetime(2026, 10, 12, 10, 0, tzinfo=KARACHI)
        minutes = sessions.expected_minutes(moment)
        self.assertEqual(minutes[0].isoformat(), "2026-10-12T09:32:00+05:00")
        self.assertEqual(minutes[-1].isoformat(), "2026-10-12T10:00:00+05:00")

    def test_before_the_open_there_is_nothing_expected_yet(self):
        moment = datetime(2026, 10, 12, 9, 0, tzinfo=KARACHI)
        self.assertEqual(sessions.expected_minutes(moment), [])
        # The same moment, asked for the whole day rather than up to now.
        self.assertEqual(sessions.expected_minutes(moment, now_only=False),
                         sessions.session_minutes(MONDAY))

    def test_a_non_trading_day_expects_no_minutes(self):
        self.assertEqual(sessions.session_minutes(SUNDAY), [])
        self.assertEqual(
            sessions.expected_minutes(
                datetime(2026, 10, 11, 12, 0, tzinfo=KARACHI)),
            [])


class ContextTest(unittest.TestCase):

    def test_a_mid_session_moment_carries_the_live_band_as_clock_strings(self):
        context = sessions.market_context(
            datetime(2026, 10, 12, 10, 0, tzinfo=KARACHI))
        self.assertEqual(context.phase, "OPEN")
        self.assertEqual(context.state, "MARKET")
        self.assertEqual(context.band, {"open": "09:32", "close": "15:30"})
        self.assertEqual(context.as_of, "2026-10-12T10:00:00+05:00")
        self.assertTrue(context.trading_day)
        self.assertEqual(context.next_event["event"], "CLOSE")
        self.assertEqual(context.next_event["at"], "2026-10-12T15:30:00+05:00")

    def test_a_pre_open_moment_has_no_band_yet(self):
        context = sessions.market_context(
            datetime(2026, 10, 12, 9, 0, tzinfo=KARACHI))
        self.assertEqual(context.phase, "PRE_OPEN")
        self.assertIsNone(context.band)
        self.assertEqual(context.next_event["event"], "OPEN")

    def test_a_non_trading_day_says_so_and_points_at_the_next_open(self):
        context = sessions.market_context(
            datetime(2026, 10, 11, 12, 0, tzinfo=KARACHI))
        self.assertFalse(context.trading_day)
        self.assertEqual(context.phase, "CLOSED")
        self.assertIsNone(context.band)
        self.assertEqual(context.next_event["at"], "2026-10-12T09:32:00+05:00")

    def test_the_context_as_dict_is_what_the_wire_carries(self):
        context = sessions.market_context(
            datetime(2026, 10, 12, 10, 0, tzinfo=KARACHI))
        body = context.as_dict()
        self.assertEqual(sorted(body), ["as_of", "band", "next_event", "phase",
                                        "state", "timezone", "trading_day"])
        self.assertEqual(body["timezone"], "Asia/Karachi")


if __name__ == "__main__":
    unittest.main()
