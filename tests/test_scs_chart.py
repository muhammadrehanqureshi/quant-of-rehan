"""Offline checks for the SCS Trade chart reader and the archive builder.

No network: every answer comes from a fake session that serves a synthetic
series with the same payload shape the feed was measured to send on
2026-11-13. The builder's window and universe helpers are checked too.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

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


def test_resample_builds_clock_aligned_buckets():
    bars = _bars(count=12)  # 09:30 to 10:25, 5m
    out = scs_chart.resample(bars, 15)
    assert len(out) == 4
    assert int(out.ts[0]) == int(bars.ts[0])
    assert out.open[0] == pytest.approx(100.0)
    assert out.close[0] == pytest.approx(100.5)
    assert out.high[0] == pytest.approx(101.0)
    assert out.low[0] == pytest.approx(99.0)
    assert int(out.volume[0]) == 3 * 500


def test_resample_of_the_base_is_the_base():
    bars = _bars()
    same = scs_chart.resample(bars, 5)
    assert np.array_equal(same.ts, bars.ts)
    assert np.array_equal(same.volume, bars.volume)


def test_resample_does_not_cross_the_friday_break():
    # Friday 2026-11-06: bands 09:17-12:00 and 14:32-16:30.
    morning = _bars("2026-11-06", count=30, price=100.0)  # 09:30 to 11:55
    afternoon = _bars("2026-11-06", count=12, price=200.0)
    afternoon.ts += int(timedelta(hours=5, minutes=2).total_seconds())
    bars = scs_chart.Bars(
        np.concatenate([morning.ts, afternoon.ts]),
        np.concatenate([morning.open, afternoon.open]),
        np.concatenate([morning.high, afternoon.high]),
        np.concatenate([morning.low, afternoon.low]),
        np.concatenate([morning.close, afternoon.close]),
        np.concatenate([morning.volume, afternoon.volume]),
    )
    out = scs_chart.resample(bars, 60)
    # Buckets are clock aligned: 09:00, 10:00, 11:00 in the morning and
    # 14:00, 15:00 after the break. The 11:00 bucket holds only morning bars
    # and the 14:00 bucket only afternoon ones, so no bucket spans the break.
    assert len(out) == 5
    assert out.open[-2] == pytest.approx(200.0)
    assert out.volume[-2] == 6 * 500
    assert out.volume[2] == 12 * 500


def test_regular_mask_excludes_auction_and_post_close():
    monday = datetime(2026, 11, 2, tzinfo=KARACHI)
    ts = np.array([
        int((monday.replace(hour=9, minute=20)).timestamp()),
        int((monday.replace(hour=9, minute=35)).timestamp()),
        int((monday.replace(hour=15, minute=30)).timestamp()),
        int((monday.replace(hour=15, minute=40)).timestamp()),
    ], dtype=np.int64)
    assert scs_chart.regular_mask(ts).tolist() == [False, True, False, False]


def test_regular_mask_respects_the_friday_break():
    friday = datetime(2026, 11, 6, tzinfo=KARACHI)
    ts = np.array([
        int(friday.replace(hour=11, minute=55).timestamp()),
        int(friday.replace(hour=12, minute=30).timestamp()),
        int(friday.replace(hour=14, minute=40).timestamp()),
    ], dtype=np.int64)
    assert scs_chart.regular_mask(ts).tolist() == [True, False, True]


def test_validate_flags_an_impossible_bar():
    bars = _bars(count=3)
    high = bars.high.copy()
    high[1] = bars.low[1] - 5.0
    broken = scs_chart.Bars(bars.ts, bars.open, high, bars.low, bars.close,
                            bars.volume)
    assert scs_chart.validate(broken)["impossible_ohlc"] == 1
    assert scs_chart.problems(broken) == ["impossible_ohlc=1"]
    assert scs_chart.problems(bars) == []


def test_merge_dedupes_and_keeps_the_later_answer():
    first = _bars(count=4)
    second = _bars(count=4, price=150.0)
    merged = scs_chart.merge(first, second)
    assert len(merged) == 4
    assert merged.open[0] == pytest.approx(150.0)
    assert merged.requests_made == 2


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
        payload = {
            "t": ts[idx].tolist(), "o": op[idx].tolist(),
            "h": hi[idx].tolist(), "l": lo[idx].tolist(),
            "c": cl[idx].tolist(), "v": vol[idx].tolist(), "s": "ok",
        }
        return _Answer(payload)


def test_fetch_window_splits_a_capped_answer_until_it_is_covered():
    frame = []
    for day in range(1, 9):
        frame.append(_bars(f"2026-11-{day:02d}", count=72))
    bars = scs_chart.Bars(
        np.concatenate([b.ts for b in frame]),
        np.concatenate([b.open for b in frame]),
        np.concatenate([b.high for b in frame]),
        np.concatenate([b.low for b in frame]),
        np.concatenate([b.close for b in frame]),
        np.concatenate([b.volume for b in frame]),
    )
    session = _CappedSession(bars.ts, bars.open, bars.high, bars.low,
                             bars.close, bars.volume, cap=200)
    out = scs_chart.fetch_window(session, "TEST", 5, int(bars.ts[0]),
                                 int(bars.ts[-1]) + 1, min_split_days=2)
    assert session.calls > 2
    assert len(out) == len(bars)
    assert np.array_equal(out.ts, bars.ts)


def test_fetch_bars_rejects_mismatched_arrays():
    class _Bad:
        status_code = 200
        text = "{}"

        def json(self):
            return {"t": [1, 2], "o": [1.0], "h": [1.0], "l": [1.0],
                    "c": [1.0], "v": [1.0], "s": "ok"}

    class _Session:
        def get(self, url, params=None, timeout=None):
            return _Bad()

    with pytest.raises(scs_chart.FeedError):
        scs_chart.fetch_bars(_Session(), "BAD", 5, 0, 100)


def test_window_for_clips_a_year_to_yesterday():
    start, end = builder.window_for(2026, None, "2026-11-12")
    assert datetime.fromtimestamp(start, tz=KARACHI).date().isoformat() == "2026-01-01"
    assert datetime.fromtimestamp(end, tz=KARACHI).date().isoformat() == "2026-11-13"


def test_load_kmiall_keeps_every_index_member(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps([
        {"symbol": "OGDC", "listedIn": ["KMIALLSHR", "ALLSHR"]},
        {"symbol": "PIBTL", "listedIn": ["KMIALL"]},
        {"symbol": "NOPE", "listedIn": ["ALLSHR"]},
    ]), encoding="utf-8")
    assert builder.load_kmiall(path) == ["OGDC", "PIBTL"]
