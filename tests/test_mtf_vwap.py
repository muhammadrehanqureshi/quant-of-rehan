"""Tests for the 2026-11-03 four frame VWAP plus Kalman law.

The law is pure: completed one minute bars and a daily history in, a frame
agreement or a named refusal out. No network, no tape file and no clock.
"""

from __future__ import annotations

import gzip
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import daily_history  # noqa: E402
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


def daily_rows(count: int = 60, start: float = 80.0,
               step: float = 0.2) -> list:
    bars = []
    price = start
    first = DAY - timedelta(days=count)
    for index in range(count):
        price = round(price + step, 4)
        bars.append(daily_history.DailyBar(
            first + timedelta(days=index), price, round(price + 0.1, 4),
            round(price - 0.1, 4), price, 1_000_000.0))
    return bars


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
    def test_four_frames_that_agree_pass(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows), daily_rows())

        self.assertEqual(reason, "ok")
        self.assertEqual(view["rule"], mtf_vwap.MTF_VERSION)
        self.assertEqual(set(view["frames"]), {"5m", "15m", "60m", "1d"})
        for frame in view["frames"].values():
            self.assertEqual(frame["kalman_state"], 1)
            self.assertTrue(frame["above_vwap"])

    def test_the_card_line_names_all_four_states(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows), daily_rows())
        self.assertEqual(reason, "ok")
        self.assertEqual(
            mtf_vwap.summary(view),
            "MTF 5m +1 above VWAP | 15m +1 above VWAP | "
            "1h +1 above VWAP | 1D +1 above VWAP")
        self.assertEqual(mtf_vwap.summary(None), "")
        self.assertEqual(mtf_vwap.summary({"frames": {"5m": {}}}), "")

    def test_the_one_hour_frame_needs_two_completed_hours(self):
        rows = minute_rows(50)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows), daily_rows())
        self.assertIsNone(view)
        self.assertEqual(reason, "mtf_60m_not_ready")

    def test_no_daily_history_fails_the_day_frame(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows), [])
        self.assertIsNone(view)
        self.assertEqual(reason, "mtf_1440m_not_ready")

    def test_a_falling_daily_chart_refuses_the_signal(self):
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows),
                                         daily_rows(step=-0.2))
        self.assertIsNone(view)
        self.assertEqual(reason, "mtf_1440m_trend_not_up")

    def test_a_daily_bar_for_today_is_never_read(self):
        bars = daily_rows()
        today = daily_history.DailyBar(
            DAY, bars[-1].open, bars[-1].high, bars[-1].low,
            bars[-1].close, bars[-1].volume)
        bars.append(today)
        rows = minute_rows(130)
        view, reason = mtf_vwap.evaluate(rows, session_of(rows), bars)
        self.assertEqual(reason, "ok")
        self.assertEqual(view["frames"]["1d"]["bars"], 60)


class DailyHistoryTest(unittest.TestCase):
    def test_only_completed_sessions_are_loaded(self):
        payload = ("symbol,date,open,high,low,close,volume\n"
                   "AAA,2026-10-05,10,11,9,10.5,100\n"
                   "AAA,2026-10-07,11,12,10,11.5,200\n"
                   "BBB,not-a-date,1,1,1,1,1\n")
        handle = tempfile.NamedTemporaryFile("wb", suffix=".csv.gz",
                                             delete=False)
        handle.close()
        path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        with gzip.open(path, "wt", encoding="utf-8", newline="") as out:
            out.write(payload)

        bars = daily_history.load(path, day=DAY)

        self.assertEqual(list(bars), ["AAA"])
        self.assertEqual(len(bars["AAA"]), 1)
        self.assertEqual(bars["AAA"][0].day, date(2026, 10, 5))


class CandidateContractTest(unittest.TestCase):
    def test_without_daily_context_the_one_minute_law_still_answers(self):
        from tests.kalman_fixture import setup_rows

        rows = setup_rows(scanner, SESSION_OPEN)
        result = kalman_trend.candidate("OGDC", rows, session_of(rows))
        self.assertIsNotNone(result)

    def test_an_empty_daily_list_fails_closed_at_the_frames(self):
        from tests.kalman_fixture import setup_rows

        rows = setup_rows(scanner, SESSION_OPEN)
        tally: dict = {}
        result = kalman_trend.candidate("OGDC", rows, session_of(rows), tally,
                                        daily=[])
        self.assertIsNone(result)
        self.assertTrue(any(key.startswith("mtf_") for key in tally), tally)


if __name__ == "__main__":
    unittest.main()
