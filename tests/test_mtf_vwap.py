"""Tests for the 2026-11-08 three frame VWAP plus Kalman law.

The law is pure: completed one minute bars in, a frame agreement or a named
refusal out. No network, no daily file and no clock.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import kalman_trend  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import mtf_vwap  # noqa: E402

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
    return scanner.SessionData(
        day=DAY, as_of=SESSION_OPEN + timedelta(minutes=len(rows)),
        bars={"OGDC": rows}, volume_available=True, bars_seen=len(rows),
        bars_rejected=0, duplicate_bars=0)


class AggregationTest(unittest.TestCase):
    def test_a_complete_bucket_carries_the_sessions_own_ohlcv(self):
        rows = minute_rows(5)
        bars = mtf_vwap.completed(rows, 5, SESSION_OPEN,
                                  SESSION_OPEN + timedelta(minutes=5))

        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].open, rows[0].open)
        self.assertEqual(bars[0].close, rows[-1].close)
        self.assertEqual(bars[0].high, max(row.high for row in rows))
        self.assertEqual(bars[0].low, min(row.low for row in rows))
        self.assertEqual(bars[0].volume, 25_000.0)

    def test_a_missing_minute_is_a_hole_not_a_padded_bar(self):
        rows = minute_rows(25)
        gapped = rows[:3] + rows[4:]
        bars = mtf_vwap.completed(gapped, 5, SESSION_OPEN,
                                  SESSION_OPEN + timedelta(minutes=25))

        self.assertEqual(len(bars), 4)
        self.assertEqual([bar.timestamp for bar in bars],
                         [SESSION_OPEN + timedelta(minutes=5 * index)
                          for index in (1, 2, 3, 4)])

    def test_a_forming_bucket_is_never_emitted(self):
        rows = minute_rows(9)
        bars = mtf_vwap.completed(rows, 5, SESSION_OPEN,
                                  SESSION_OPEN + timedelta(minutes=9))
        self.assertEqual(len(bars), 1)


class VwapTest(unittest.TestCase):
    def test_vwap_is_volume_weighted_typical_price(self):
        first = mtf_vwap.Frame(SESSION_OPEN, 10, 10, 10, 10, 1)
        second = mtf_vwap.Frame(SESSION_OPEN + timedelta(minutes=5),
                                20, 20, 20, 20, 3)
        self.assertEqual(mtf_vwap.rolling_vwap([first, second], 2), 17.5)

    def test_no_volume_means_no_vwap(self):
        bar = mtf_vwap.Frame(SESSION_OPEN, 10, 10, 10, 10, 0)
        self.assertIsNone(mtf_vwap.rolling_vwap([bar], 2))


class LawTest(unittest.TestCase):
    def test_three_frames_that_agree_pass(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows))

        self.assertEqual(reason, "ok")
        self.assertEqual(view["rule"], mtf_vwap.MTF_VERSION)
        self.assertEqual(set(view["frames"]), {"5m", "15m", "60m"})
        for frame in view["frames"].values():
            self.assertEqual(frame["kalman_state"], 1)
            self.assertTrue(frame["above_vwap"])

    def test_the_card_line_names_all_three_states(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows))
        self.assertEqual(reason, "ok")
        self.assertEqual(
            mtf_vwap.summary(view),
            "MTF 5m +1 above VWAP | 15m +1 above VWAP | 1h +1 above VWAP")
        self.assertEqual(mtf_vwap.summary(None), "")
        self.assertEqual(mtf_vwap.summary({"frames": {"5m": {}}}), "")

    def test_the_one_hour_frame_needs_two_completed_hours(self):
        rows = minute_rows(50)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows))
        self.assertIsNone(view)
        self.assertEqual(reason, "mtf_60m_not_ready")

    def test_the_law_reads_the_session_tape_alone(self):
        """Owner order 2026-11-08: the 1 day frame and its file are gone."""
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows))
        self.assertEqual(reason, "ok")
        self.assertNotIn("1d", view["frames"])


class CandidateContractTest(unittest.TestCase):
    def test_without_frames_the_law_refuses_and_names_it(self):
        """The one running law cannot be evaluated without its frames."""
        from tests.kalman_fixture import setup_rows

        rows = setup_rows(scanner, SESSION_OPEN)
        tally: dict = {}
        result = kalman_trend.candidate("OGDC", rows, session_of(rows), tally)
        self.assertIsNone(result)
        self.assertIn("hybrid_frames_not_read", tally)

    def test_when_the_frames_are_read_a_short_session_fails_closed(self):
        from tests.kalman_fixture import setup_rows

        rows = setup_rows(scanner, SESSION_OPEN)
        tally: dict = {}
        result = kalman_trend.candidate("OGDC", rows, session_of(rows), tally,
                                        frames=True)
        self.assertIsNone(result)
        self.assertTrue(any(key.startswith("hybrid_") for key in tally), tally)


if __name__ == "__main__":
    unittest.main()
