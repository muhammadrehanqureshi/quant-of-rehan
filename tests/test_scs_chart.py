"""Offline checks for the SCS Trade chart reader and the archive builder.

No network: every answer comes from a fake session that serves a synthetic
series with the same payload shape the feed was measured to send on
2026-11-13. The builder's window and universe helpers are checked too.

The suite runs under unittest (the governance job does not install pytest),
so every test is a method on a TestCase.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from scripts import build_intraday_history as builder
from src.data import scs_chart
from src.data.sessions import KARACHI


def _series(day: str, minutes: int, count: int, price: float = 100.0,
            volume: int = 500) -> tuple[np.ndarray, ...]:
    start = datetime.fromisoformat(f"{day}T09:30:00").replace(tzinfo=KARACHI)
    ts = np.array([int((start + timedelta(minutes=minutes * i)).timestamp())
                   for i in range(count)], dtype=np.int64)
    op = np.full(count, price, dtype=np.float64)
    hi = op + 1.0
    lo = op - 1.0
    cl = op + 0.5
    vol = np.full(count, volume, dtype=np.int64)
    return ts, op, hi, lo, cl, vol


def _bars(day: str = "2026-11-02", minutes: int = 5, count: int = 12,
          price: float = 100.0) -> scs_chart.Bars:
    return scs_chart.Bars(*_series(day, minutes, count, price))


class _Answer:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self.text = json.dumps(payload)
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _CappedSession:
    """Serves at most `cap` bars from `from`, the shape of a server side cap."""

    def __init__(self, ts, op, hi, lo, cl, vol, cap: int) -> None:
        self.arrays = (ts, op, hi, lo, cl, vol)
        self.cap = cap
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        ts, op, hi, lo, cl, vol = self.arrays
        keep = (ts >= int(params["from"])) & (ts <= int(params["to"]))
        idx = np.flatnonzero(keep)[:self.cap]
        return _Answer({
            "t": ts[idx].tolist(), "o": op[idx].tolist(),
            "h": hi[idx].tolist(), "l": lo[idx].tolist(),
            "c": cl[idx].tolist(), "v": vol[idx].tolist(), "s": "ok",
        })


class ResampleTest(unittest.TestCase):
    def test_resample_builds_clock_aligned_buckets(self):
        bars = _bars(count=12)  # 09:30 to 10:25, 5m
        out = scs_chart.resample(bars, 15)
        self.assertEqual(len(out), 4)
        self.assertEqual(int(out.ts[0]), int(bars.ts[0]))
        self.assertAlmostEqual(float(out.open[0]), 100.0, places=6)
        self.assertAlmostEqual(float(out.close[0]), 100.5, places=6)
        self.assertAlmostEqual(float(out.high[0]), 101.0, places=6)
        self.assertAlmostEqual(float(out.low[0]), 99.0, places=6)
        self.assertEqual(int(out.volume[0]), 3 * 500)

    def test_resample_of_the_base_is_the_base(self):
        bars = _bars()
        same = scs_chart.resample(bars, 5)
        self.assertTrue(np.array_equal(same.ts, bars.ts))
        self.assertTrue(np.array_equal(same.volume, bars.volume))

    def test_resample_does_not_cross_the_friday_break(self):
        # Friday 2026-11-06: bands 09:17-12:00 and 14:32-16:30.
        morning = _bars("2026-11-06", count=30, price=100.0)  # 09:30 to 11:55
        raw = _bars("2026-11-06", count=12, price=200.0)
        shift = int(timedelta(hours=5, minutes=2).total_seconds())
        afternoon = scs_chart.Bars(raw.ts + shift, raw.open, raw.high, raw.low,
                                   raw.close, raw.volume)
        bars = scs_chart.Bars(
            np.concatenate([morning.ts, afternoon.ts]),
            np.concatenate([morning.open, afternoon.open]),
            np.concatenate([morning.high, afternoon.high]),
            np.concatenate([morning.low, afternoon.low]),
            np.concatenate([morning.close, afternoon.close]),
            np.concatenate([morning.volume, afternoon.volume]),
        )
        out = scs_chart.resample(bars, 60)
        # Clock aligned buckets: 09:00, 10:00, 11:00 in the morning and
        # 14:00, 15:00 after the break. No bucket spans the break.
        self.assertEqual(len(out), 5)
        self.assertAlmostEqual(float(out.open[-2]), 200.0, places=6)
        self.assertEqual(int(out.volume[-2]), 6 * 500)
        self.assertEqual(int(out.volume[2]), 12 * 500)


class DailyTest(unittest.TestCase):
    def test_daily_uses_the_karachi_session_date(self):
        bars = _bars("2026-11-02", count=12)
        out = scs_chart.daily(bars)
        self.assertEqual(len(out), 1)
        midnight = datetime(2026, 11, 2, tzinfo=KARACHI)
        self.assertEqual(int(out.ts[0]), int(midnight.timestamp()))
        self.assertAlmostEqual(float(out.open[0]), 100.0, places=6)
        self.assertAlmostEqual(float(out.high[0]), 101.0, places=6)
        self.assertAlmostEqual(float(out.low[0]), 99.0, places=6)
        self.assertAlmostEqual(float(out.close[0]), 100.5, places=6)
        self.assertEqual(int(out.volume[0]), 12 * 500)
        frame = out.frame("TEST", np.ones(len(out), dtype=bool))
        self.assertTrue(bool(frame["regular"].all()))

    def test_daily_keeps_two_sessions_apart(self):
        first = _bars("2026-11-02", count=12)
        second = _bars("2026-11-03", count=6, price=200.0)
        bars = scs_chart.Bars(
            np.concatenate([first.ts, second.ts]),
            np.concatenate([first.open, second.open]),
            np.concatenate([first.high, second.high]),
            np.concatenate([first.low, second.low]),
            np.concatenate([first.close, second.close]),
            np.concatenate([first.volume, second.volume]),
        )
        out = scs_chart.daily(bars)
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(float(out.open[1]), 200.0, places=6)
        self.assertEqual(int(out.volume[1]), 6 * 500)

    def test_daily_validation_rejects_a_non_midnight_stamp(self):
        bars = _bars(count=12)
        out = scs_chart.daily(bars)
        shifted = scs_chart.Bars(out.ts + 300, out.open, out.high, out.low,
                                 out.close, out.volume)
        self.assertEqual(scs_chart.validate_daily(shifted)["not_midnight_pkt"], 1)
        self.assertEqual(scs_chart.problems_daily(shifted),
                         ["not_midnight_pkt=1"])

    def test_daily_comparison_keys_on_the_karachi_date(self):
        out = scs_chart.daily(_bars(count=12))
        native_ts = np.array([
            int(datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp())
        ], dtype=np.int64)
        native = scs_chart.Bars(native_ts, out.open, out.high, out.low,
                                out.close, out.volume)
        compared = scs_chart.compare_daily(out, native)
        self.assertEqual(compared["common"], 1)
        self.assertEqual(compared["exact"], 1)
        self.assertEqual(compared["agreement_pct"], 100.0)


class SessionFlagTest(unittest.TestCase):
    def test_regular_mask_excludes_auction_and_post_close(self):
        monday = datetime(2026, 11, 2, tzinfo=KARACHI)
        ts = np.array([
            int(monday.replace(hour=9, minute=20).timestamp()),
            int(monday.replace(hour=9, minute=35).timestamp()),
            int(monday.replace(hour=15, minute=30).timestamp()),
            int(monday.replace(hour=15, minute=40).timestamp()),
        ], dtype=np.int64)
        self.assertEqual(scs_chart.regular_mask(ts).tolist(),
                         [False, True, False, False])

    def test_regular_mask_respects_the_friday_break(self):
        friday = datetime(2026, 11, 6, tzinfo=KARACHI)
        ts = np.array([
            int(friday.replace(hour=11, minute=55).timestamp()),
            int(friday.replace(hour=12, minute=30).timestamp()),
            int(friday.replace(hour=14, minute=40).timestamp()),
        ], dtype=np.int64)
        self.assertEqual(scs_chart.regular_mask(ts).tolist(),
                         [True, False, True])


class ValidateTest(unittest.TestCase):
    def test_validate_flags_an_impossible_bar(self):
        bars = _bars(count=3)
        high = bars.high.copy()
        high[1] = bars.low[1] - 5.0
        broken = scs_chart.Bars(bars.ts, bars.open, high, bars.low,
                                bars.close, bars.volume)
        self.assertEqual(scs_chart.validate(broken)["impossible_ohlc"], 1)
        self.assertEqual(scs_chart.problems(broken), ["impossible_ohlc=1"])
        self.assertEqual(scs_chart.problems(bars), [])

    def test_merge_dedupes_and_keeps_the_later_answer(self):
        first = _bars(count=4)
        second = _bars(count=4, price=150.0)
        merged = scs_chart.merge(first, second)
        self.assertEqual(len(merged), 4)
        self.assertAlmostEqual(float(merged.open[0]), 150.0, places=6)
        self.assertEqual(merged.requests_made, 2)


class FetchTest(unittest.TestCase):
    def test_fetch_window_splits_a_capped_answer_until_it_is_covered(self):
        days = [_bars(f"2026-11-{day:02d}", count=72) for day in range(1, 9)]
        bars = scs_chart.Bars(
            np.concatenate([b.ts for b in days]),
            np.concatenate([b.open for b in days]),
            np.concatenate([b.high for b in days]),
            np.concatenate([b.low for b in days]),
            np.concatenate([b.close for b in days]),
            np.concatenate([b.volume for b in days]),
        )
        session = _CappedSession(bars.ts, bars.open, bars.high, bars.low,
                                 bars.close, bars.volume, cap=200)
        out = scs_chart.fetch_window(session, "TEST", 5, int(bars.ts[0]),
                                     int(bars.ts[-1]) + 1, min_split_days=2)
        self.assertGreater(session.calls, 2)
        self.assertEqual(len(out), len(bars))
        self.assertTrue(np.array_equal(out.ts, bars.ts))

    def test_fetch_bars_rejects_mismatched_arrays(self):
        class _Bad:
            status_code = 200
            text = "{}"

            def json(self):
                return {"t": [1, 2], "o": [1.0], "h": [1.0], "l": [1.0],
                        "c": [1.0], "v": [1.0], "s": "ok"}

        class _Session:
            def get(self, url, params=None, timeout=None):
                return _Bad()

        with self.assertRaises(scs_chart.FeedError):
            scs_chart.fetch_bars(_Session(), "BAD", 5, 0, 100)


class BuilderTest(unittest.TestCase):
    def test_window_for_clips_a_year_to_yesterday(self):
        start, end = builder.window_for(2026, None, "2026-11-12")
        self.assertEqual(
            datetime.fromtimestamp(start, tz=KARACHI).date().isoformat(),
            "2026-01-01")
        self.assertEqual(
            datetime.fromtimestamp(end, tz=KARACHI).date().isoformat(),
            "2026-11-13")

    def test_load_kmiall_keeps_every_index_member(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "universe.json"
            path.write_text(json.dumps([
                {"symbol": "OGDC", "listedIn": ["KMIALLSHR", "ALLSHR"]},
                {"symbol": "PIBTL", "listedIn": ["KMIALL"]},
                {"symbol": "NOPE", "listedIn": ["ALLSHR"]},
            ]), encoding="utf-8")
            self.assertEqual(builder.load_kmiall(path), ["OGDC", "PIBTL"])


if __name__ == "__main__":
    unittest.main()
