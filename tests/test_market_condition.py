"""The three market conditions, and the instant each one begins.

Owner order 2026-10-11: the interface states exactly three conditions, and
one of them is the exchange's own midday break on a Friday, 12:00 to 14:32.

    Market is on a break right now.     the Friday break, and only that
    Market is closed right now.         every other shut instant
    (nothing)                           while the exchange is trading

Each condition is folded from the session bands in src/data/sessions.py, so
a condition can never disagree with the bands the scanner, the relay and the
phone app all read. These tests pin the boundaries, because a boundary is
where the reported bug of 2026-10-10 lived: the app said ONLINE at 14:23 on
a Friday while the exchange was shut.

Everything here is offline: instants are built in Karachi time and passed in
directly, and no clock is read.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    KARACHI,
    MSG_CONDITION_BREAK,
    MSG_CONDITION_CLOSED,
    MarketCondition,
    condition_text,
    is_scan_window,
    market_condition_at,
    market_state,
)

FRIDAY = "2026-10-09"      # a PSX trading day with two bands
MONDAY = "2026-10-12"      # one band
SUNDAY = "2026-10-11"      # never a trading day
HOLIDAY = "2026-11-09"     # on the published PSX 2026 holiday list


def at(date: str, clock: str) -> datetime:
    """An instant on that Karachi date, in the one true zone."""
    return datetime.fromisoformat(f"{date}T{clock}").replace(tzinfo=KARACHI)


class ConditionSetTest(unittest.TestCase):
    def test_there_are_exactly_three_conditions(self):
        self.assertEqual([condition.value for condition in MarketCondition],
                         ["OPERATIONAL", "BREAK", "CLOSED"])

    def test_the_texts_are_the_owners_exact_words(self):
        self.assertEqual(MSG_CONDITION_BREAK, "Market is on a break right now.")
        self.assertEqual(MSG_CONDITION_CLOSED, "Market is closed right now.")
        self.assertEqual(condition_text(at(FRIDAY, "13:00")),
                         MSG_CONDITION_BREAK)
        self.assertEqual(condition_text(at(SUNDAY, "13:00")),
                         MSG_CONDITION_CLOSED)

    def test_only_operational_is_live(self):
        self.assertTrue(MarketCondition.OPERATIONAL.is_live)
        self.assertFalse(MarketCondition.BREAK.is_live)
        self.assertFalse(MarketCondition.CLOSED.is_live)


class FridayBreakTest(unittest.TestCase):
    """The break window, edge by edge, in both directions."""

    def test_the_morning_band_runs_to_the_break(self):
        self.assertEqual(market_condition_at(at(FRIDAY, "09:16")),
                         MarketCondition.CLOSED)
        self.assertEqual(market_condition_at(at(FRIDAY, "09:17")),
                         MarketCondition.OPERATIONAL)
        self.assertEqual(market_condition_at(at(FRIDAY, "11:59:59")),
                         MarketCondition.OPERATIONAL)
        self.assertEqual(condition_text(at(FRIDAY, "11:59:59")), "")

    def test_the_break_starts_at_noon(self):
        self.assertEqual(market_condition_at(at(FRIDAY, "12:00:00")),
                         MarketCondition.BREAK)
        self.assertEqual(condition_text(at(FRIDAY, "12:00:00")),
                         MSG_CONDITION_BREAK)

    def test_the_break_holds_until_the_afternoon_band(self):
        self.assertEqual(market_condition_at(at(FRIDAY, "12:30")),
                         MarketCondition.BREAK)
        self.assertEqual(market_condition_at(at(FRIDAY, "14:23")),
                         MarketCondition.BREAK)   # the reported bug, exact
        self.assertEqual(market_condition_at(at(FRIDAY, "14:31:59")),
                         MarketCondition.BREAK)

    def test_trading_resumes_at_1432(self):
        self.assertEqual(market_condition_at(at(FRIDAY, "14:32:00")),
                         MarketCondition.OPERATIONAL)
        self.assertEqual(condition_text(at(FRIDAY, "14:32:00")), "")
        self.assertEqual(market_condition_at(at(FRIDAY, "16:29:59")),
                         MarketCondition.OPERATIONAL)

    def test_the_friday_close_is_closed_and_not_a_break(self):
        self.assertEqual(market_condition_at(at(FRIDAY, "16:30:00")),
                         MarketCondition.CLOSED)
        self.assertEqual(condition_text(at(FRIDAY, "16:30:00")),
                         MSG_CONDITION_CLOSED)
        self.assertEqual(market_condition_at(at(FRIDAY, "19:00")),
                         MarketCondition.CLOSED)

    def test_the_scanner_runs_only_in_the_operational_condition(self):
        for clock in ("09:16", "09:17", "11:59:59", "12:00:00", "14:23",
                      "14:31:59", "14:32:00", "16:29:59", "16:30:00"):
            moment = at(FRIDAY, clock)
            with self.subTest(clock=clock):
                self.assertEqual(is_scan_window(moment),
                                 market_condition_at(moment)
                                 is MarketCondition.OPERATIONAL)


class OtherDaysTest(unittest.TestCase):
    def test_a_weekday_has_no_break_at_all(self):
        for clock in ("11:59:59", "12:00:00", "14:31:59", "14:32:00"):
            with self.subTest(clock=clock):
                self.assertEqual(market_condition_at(at(MONDAY, clock)),
                                 MarketCondition.OPERATIONAL)

    def test_the_morning_gap_is_closed_not_a_break(self):
        self.assertEqual(market_condition_at(at(MONDAY, "09:00")),
                         MarketCondition.CLOSED)
        self.assertEqual(condition_text(at(MONDAY, "09:00")),
                         MSG_CONDITION_CLOSED)

    def test_the_weekday_close_and_the_post_market_window_are_closed(self):
        for clock in ("15:29:59", "15:30:00", "15:31:00", "15:35:00",
                      "18:00:00"):
            with self.subTest(clock=clock):
                condition = market_condition_at(at(MONDAY, clock))
                expected = (MarketCondition.OPERATIONAL
                            if clock == "15:29:59" else MarketCondition.CLOSED)
                self.assertEqual(condition, expected)

    def test_the_weekend_is_closed_and_never_a_break(self):
        for clock in ("11:00", "12:30", "14:23"):
            with self.subTest(clock=clock):
                self.assertEqual(market_condition_at(at(SUNDAY, clock)),
                                 MarketCondition.CLOSED)
                self.assertEqual(condition_text(at(SUNDAY, clock)),
                                 MSG_CONDITION_CLOSED)

    def test_a_psx_holiday_is_closed_and_never_a_break(self):
        self.assertEqual(market_condition_at(at(HOLIDAY, "13:00")),
                         MarketCondition.CLOSED)
        self.assertEqual(condition_text(at(HOLIDAY, "13:00")),
                         MSG_CONDITION_CLOSED)


class ConditionPayloadTest(unittest.TestCase):
    """The relay and the app read the condition out of market_state."""

    def test_the_payload_carries_the_condition_and_its_sentence(self):
        state = market_state(at(FRIDAY, "13:00"))
        self.assertEqual(state["condition"], "BREAK")
        self.assertEqual(state["condition_text"], MSG_CONDITION_BREAK)
        self.assertEqual(state["phase"], "BREAK")
        self.assertFalse(state["market_open"])

    def test_an_operational_payload_carries_no_sentence(self):
        state = market_state(at(FRIDAY, "14:35"))
        self.assertEqual(state["condition"], "OPERATIONAL")
        self.assertEqual(state["condition_text"], "")
        self.assertTrue(state["market_open"])

    def test_every_condition_is_serialisable(self):
        for moment in (at(FRIDAY, "10:00"), at(FRIDAY, "13:00"),
                       at(SUNDAY, "13:00")):
            state = market_state(moment)
            self.assertIn(state["condition"],
                          ("OPERATIONAL", "BREAK", "CLOSED"))
            self.assertIsInstance(state["condition_text"], str)
            if state["condition"] == "OPERATIONAL":
                self.assertEqual(state["condition_text"], "")
            else:
                self.assertIn(state["condition_text"],
                              (MSG_CONDITION_BREAK, MSG_CONDITION_CLOSED))


if __name__ == "__main__":
    unittest.main()
