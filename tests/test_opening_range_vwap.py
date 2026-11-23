"""Tests for the opening range and the three VWAP frames.

Owner order 2026-11-23 (Karachi): the day trading law is the opening range
with the VWAP on the 5, 15 and 30 minute charts, three calls a day at most,
every call scored out of 100. The law is pure: completed one minute bars in,
a candidate or a named refusal out. No network, no clock and no Kalman state.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import opening_range_vwap as law  # noqa: E402

DAY = date(2026, 10, 7)
SESSION_OPEN = datetime.combine(DAY, time(*open_time(DAY)), tzinfo=KARACHI)


def minute_rows(count: int, start: float = 100.0, step: float = 0.05,
                volume: float = 5_000.0) -> list:
    rows = []
    price = start
    for index in range(count):
        price = round(price + step, 4)
        rows.append(scanner.MinuteBar(
            SESSION_OPEN + timedelta(minutes=index),
            price, round(price + 0.01, 4), round(price - 0.01, 4),
            price, volume))
    return rows


def session_of(rows: list) -> scanner.SessionData:
    last = rows[-1].close if rows else 0.0
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars={"OGDC": rows}, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0,
        previous_close={"OGDC": last}, buy_volume={"OGDC": 200_000},
        sell_volume={"OGDC": 100_000})


class OpeningRangeTest(unittest.TestCase):
    def test_the_range_is_the_first_thirty_completed_bars(self):
        rows = minute_rows(60)
        view = law.opening_range(rows, SESSION_OPEN,
                                 SESSION_OPEN + timedelta(minutes=60))

        self.assertIsNotNone(view)
        self.assertEqual(view["bars"], config.OPENING_RANGE_MINUTES)
        self.assertEqual(view["high"], max(row.high for row in rows[:30]))
        self.assertEqual(view["low"], min(row.low for row in rows[:30]))

    def test_a_missing_minute_means_no_range_at_all(self):
        rows = minute_rows(60)
        holed = rows[:7] + rows[8:]
        self.assertIsNone(law.opening_range(holed, SESSION_OPEN,
                                            SESSION_OPEN + timedelta(minutes=60)))

    def test_a_forming_range_is_never_read(self):
        rows = minute_rows(20)
        self.assertIsNone(law.opening_range(rows, SESSION_OPEN,
                                            SESSION_OPEN + timedelta(minutes=20)))


class EntryLawTest(unittest.TestCase):
    def test_a_held_breakout_with_three_vwap_frames_passes(self):
        rows = minute_rows(60)
        view, reason = law.entry_view("OGDC", rows, session_of(rows))

        self.assertEqual(reason, "ok", reason)
        self.assertEqual(view["rule"], law.READER_VERSION)
        self.assertGreater(view["close"], view["range_high"])
        self.assertEqual(set(view["frames"]), {"5m", "15m", "30m"})
        for frame in view["frames"].values():
            self.assertTrue(frame["above_vwap"])

    def test_a_close_inside_the_range_is_refused(self):
        rows = minute_rows(30)
        view, reason = law.entry_view("OGDC", rows, session_of(rows))
        self.assertIsNone(view)
        self.assertEqual(reason, "opening_range_not_broken")

    def test_a_breakout_far_past_the_range_is_a_chase(self):
        rows = minute_rows(30)
        rows.append(scanner.MinuteBar(
            SESSION_OPEN + timedelta(minutes=30), 110.0, 110.1, 109.9,
            110.0, 5_000.0))
        view, reason = law.entry_view("OGDC", rows, session_of(rows))
        self.assertIsNone(view)
        self.assertEqual(reason, "opening_range_too_far_past")

    def test_a_frame_below_its_own_vwap_is_refused(self):
        # Up through the range and on to 102, then a measured slide back to
        # just above the range high: the breakout holds, but the 5 minute
        # frame's completed close is under its own VWAP by then.
        rows = minute_rows(45)
        price = rows[-1].close
        for index in range(45, 60):
            price = round(price - 0.02, 4)
            rows.append(scanner.MinuteBar(
                SESSION_OPEN + timedelta(minutes=index),
                price, round(price + 0.01, 4), round(price - 0.01, 4),
                price, 5_000.0))
        view, reason = law.entry_view("OGDC", rows, session_of(rows))
        self.assertIsNone(view)
        self.assertTrue(reason.startswith("opening_range_"), reason)
        self.assertIn("vwap", reason)


class ScoreTest(unittest.TestCase):
    def test_a_legal_call_scores_out_of_one_hundred_above_the_floor(self):
        rows = minute_rows(60)
        session = session_of(rows)
        tally: dict = {}
        row = law.candidate("OGDC", rows, session, tally, frames=True)

        self.assertIsNotNone(row, tally)
        self.assertGreater(row["score"], config.MIN_CALL_SCORE)
        self.assertLessEqual(row["score"], 100.0)
        self.assertEqual(row["strategy"], config.OPENING_RANGE_STRATEGY_VERSION)
        self.assertEqual(tally, {})

    def test_a_stronger_breakout_scores_higher_than_a_weaker_one(self):
        weak = {"range_height": 1.0, "extension": 0.1, "breakout_volume": 1000,
                "opening_range": {"bars": 30, "volume": 30_000},
                "frames": {"5m": {"close": 100.2, "vwap": 100.0},
                           "15m": {"close": 100.2, "vwap": 100.0},
                           "30m": {"close": 100.2, "vwap": 100.0}}}
        strong = {**weak, "extension": 0.9, "breakout_volume": 3000}
        self.assertGreater(law.score(strong), law.score(weak))
        self.assertEqual(law.score(None), 0.0)

    def test_the_frames_must_be_read(self):
        rows = minute_rows(130)
        tally: dict = {}
        row = law.candidate("OGDC", rows, session_of(rows), tally)
        self.assertIsNone(row)
        self.assertIn("opening_range_frames_not_read", tally)


if __name__ == "__main__":
    unittest.main()
