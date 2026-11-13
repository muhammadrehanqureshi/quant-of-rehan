"""Five year PSX intraday archive reader: the SCS Trade chart datafeed.

Owner request 2026-11-13: five years of 5m, 15m, 30m and 1h bars for every
KMIALL scrip, for strategy backtests.

Measured 2026-11-13, read only, no key and no login:

    GET https://chart.scstrade.com/history
        ?symbol=OGDC&resolution=5&from=1636761600&to=1794000000
    {"t":[...], "o":[...], "h":[...], "l":[...], "c":[...], "v":[...],
     "s":"ok"}

The first bar is 2021-11-15 and bars carry the venue's own traded volume. The
feed offers 1, 5, 15, 30, 60, 120, 180, 240, D and W resolutions; this module
reads 5 as the base and derives 15, 30 and 60 as clock aligned buckets. The
builder checks those against the feed's own native buckets on a sample and
records the agreement in its manifest.

This is the datafeed behind the chart page the owner named,
https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx. It is
NOT the eClear GetOHLCData servlet, which serves the current session only and
was measured dead in DATA_SOURCING.md section 4.

What the bars contain, measured on the real payload: the feed includes the
pre-open auction bars (from 09:15) and the post-close session bars (to 15:45
Monday to Thursday, 16:45 Friday), so every bar is labelled with `regular`,
true only inside the exchange's own trading bands (src/data/sessions.py). A
backtest filters on that column; the archive keeps the auction bars rather
than throwing evidence away.

Prices are the venue's as-traded prices: no split or bonus adjustment is
applied here, and the manifest says so. A backtester must handle corporate
actions from the exchange notices; this module never invents an adjustment.

Every stamp is Asia/Karachi, the fixed UTC+5 zone (SO-8); the feed's own
`timezone` field says Asia/Ashkhabad, a charting label it uses for every PSX
scrip, so it is ignored rather than trusted.

Rights (DATA_SOURCING.md section 5): the feed is free and unauthenticated,
and the archive is for the owner's own research. It is never committed to the
repository and never redistributed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

import numpy as np
import pandas as pd
import requests

from src.data.sessions import KARACHI, band_bounds, session_bands

BASE_URL = "https://chart.scstrade.com"
HISTORY_PATH = "/history"
SYMBOLS_PATH = "/symbols"
SEARCH_PATH = "/search"
CHART_PAGE = "https://www.scstrade.com/TechnicalAnalysis/TA_RealTimeCharting.aspx"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0 Safari/537.36"
)

#: The base resolution the archive stores. Every other timeframe is derived
#: from it, so one download serves all four.
BASE_RESOLUTION = 5
RESAMPLED = (15, 30, 60)

#: Polite pacing: one request at a time per worker, this long between them.
PACING_SECONDS = 0.35
TIMEOUT_SECONDS = 45.0
RETRIES = 4
BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)

#: A window that long is split in half when the answer does not cover it,
#: which is how a server side cap is worked around without guessing one.
MIN_SPLIT_SPAN_DAYS = 20

#: How close to the requested edges an answer must reach to count as complete,
#: capped as a fraction of the window so a short window is not fooled by a
#: fixed number of days that reaches back past its own start.
COVERAGE_TOLERANCE_DAYS = 10

#: The first bar the feed holds, measured on 2026-11-13. An archive that asks
#: for earlier years would report coverage against days the source never had.
FIRST_BAR_DATE = "2021-11-15"

#: Columns every stored frame carries.
FRAME_COLUMNS = ("symbol", "ts", "open", "high", "low", "close", "volume",
                 "regular")


class FeedError(RuntimeError):
    """The feed answered something this reader refuses to interpret."""


@dataclass(frozen=True)
class Bars:
    """One symbol's bars, oldest first, as parallel arrays."""

    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    status: str = "ok"
    requests_made: int = 1

    def __len__(self) -> int:
        return int(self.ts.size)

    @staticmethod
    def empty(status: str = "no_data", requests_made: int = 1) -> "Bars":
        i = np.zeros(0, dtype=np.int64)
        f = np.zeros(0, dtype=np.float64)
        return Bars(i.copy(), f.copy(), f.copy(), f.copy(), f.copy(),
                    i.copy(), status, requests_made)

    def frame(self, symbol: str) -> pd.DataFrame:
        """The stored rows: epoch seconds, prices, volume and the session flag."""
        return pd.DataFrame({
            "symbol": np.full(len(self), symbol, dtype=object),
            "ts": self.ts.astype(np.int64),
            "open": self.open.astype(np.float32),
            "high": self.high.astype(np.float32),
            "low": self.low.astype(np.float32),
            "close": self.close.astype(np.float32),
            "volume": self.volume.astype(np.int64),
            "regular": regular_mask(self.ts),
        })


def new_session() -> requests.Session:
    """A browser shaped session, the shape the chart page itself sends."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": CHART_PAGE,
    })
    return s


def _request_json(session: requests.Session, path: str, params: dict,
                  timeout: float = TIMEOUT_SECONDS) -> object | None:
    """One GET, retried on transport, 429 and 5xx. Never returns HTML."""
    url = BASE_URL + path
    last = ""
    for attempt in range(RETRIES):
        try:
            answer = session.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            if answer.status_code == 404:
                return None
            if answer.status_code == 200:
                try:
                    return answer.json()
                except ValueError:
                    last = f"answer was not JSON: {answer.text[:120]!r}"
            elif answer.status_code == 429 or 500 <= answer.status_code < 600:
                last = f"HTTP {answer.status_code}"
            else:
                raise FeedError(
                    f"{path} HTTP {answer.status_code}: {answer.text[:160]}")
        if attempt + 1 < RETRIES:
            time.sleep(BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)])
    raise FeedError(f"{path} failed after {RETRIES} attempts: {last}")


def symbol_info(session: requests.Session, symbol: str,
                timeout: float = TIMEOUT_SECONDS) -> dict | None:
    """The feed's own description of a scrip, or None when it does not know it."""
    payload = _request_json(session, SYMBOLS_PATH, {"symbol": symbol}, timeout)
    return payload if isinstance(payload, dict) else None


def fetch_bars(session: requests.Session, symbol: str, resolution: int,
               start: int, end: int,
               timeout: float = TIMEOUT_SECONDS) -> Bars:
    """Every bar the feed holds for one symbol, resolution and window."""
    payload = _request_json(session, HISTORY_PATH, {
        "symbol": symbol,
        "resolution": str(int(resolution)),
        "from": int(start),
        "to": int(end),
    }, timeout)
    if payload is None:
        return Bars.empty("not_found")
    if not isinstance(payload, dict):
        raise FeedError(f"{symbol} {resolution}: answer is not an object")
    status = str(payload.get("s") or "")
    if status == "no_data":
        return Bars.empty("no_data")
    if status != "ok":
        raise FeedError(f"{symbol} {resolution}: status {status!r}")
    try:
        ts = np.asarray(payload["t"], dtype=np.int64)
        op = np.asarray(payload["o"], dtype=np.float64)
        hi = np.asarray(payload["h"], dtype=np.float64)
        lo = np.asarray(payload["l"], dtype=np.float64)
        cl = np.asarray(payload["c"], dtype=np.float64)
        vol = np.asarray(payload["v"], dtype=np.float64)
    except (KeyError, TypeError, ValueError) as exc:
        raise FeedError(f"{symbol} {resolution}: malformed arrays ({exc})")
    if not (ts.size == op.size == hi.size == lo.size == cl.size == vol.size):
        raise FeedError(
            f"{symbol} {resolution}: array lengths differ "
            f"({ts.size},{op.size},{hi.size},{lo.size},{cl.size},{vol.size})")
    keep = (ts >= int(start)) & (ts <= int(end))
    ts, op, hi, lo, cl, vol = ts[keep], op[keep], hi[keep], lo[keep], cl[keep], vol[keep]
    if ts.size == 0:
        return Bars.empty("empty_window")
    order = np.argsort(ts, kind="stable")
    return Bars(ts[order], op[order], hi[order], lo[order], cl[order],
                np.rint(vol[order]).astype(np.int64), "ok", 1)


def merge(first: Bars, second: Bars) -> Bars:
    """Union of two overlapping answers; the later answer wins a duplicate."""
    if len(first) == 0:
        return second
    if len(second) == 0:
        return first
    frame = pd.DataFrame({
        "ts": np.concatenate([first.ts, second.ts]),
        "open": np.concatenate([first.open, second.open]),
        "high": np.concatenate([first.high, second.high]),
        "low": np.concatenate([first.low, second.low]),
        "close": np.concatenate([first.close, second.close]),
        "volume": np.concatenate([first.volume, second.volume]),
    })
    frame = frame.sort_values("ts").drop_duplicates("ts", keep="last")
    return Bars(
        frame["ts"].to_numpy(dtype=np.int64),
        frame["open"].to_numpy(dtype=np.float64),
        frame["high"].to_numpy(dtype=np.float64),
        frame["low"].to_numpy(dtype=np.float64),
        frame["close"].to_numpy(dtype=np.float64),
        frame["volume"].to_numpy(dtype=np.int64),
        "ok",
        int(first.requests_made + second.requests_made),
    )


def fetch_window(session: requests.Session, symbol: str, resolution: int,
                 start: int, end: int,
                 on_fetch: Callable[[str, int, int, int, int], None] | None = None,
                 min_split_days: int = MIN_SPLIT_SPAN_DAYS) -> Bars:
    """A whole window, split in halves when one answer cannot cover it.

    The feed has a server side cap, measured by asking for five years at once:
    the answer was complete at the start of the range and short at the end.
    Rather than guess the cap, an answer that does not reach the requested
    edges is split and fetched again, so any cap the server applies is worked
    around with the fewest requests that actually cover the window.
    """
    start, end = int(start), int(end)
    if end <= start:
        return Bars.empty("empty_range", 0)
    bars = fetch_bars(session, symbol, resolution, start, end)
    if on_fetch is not None:
        on_fetch(symbol, resolution, start, end, len(bars))
    if bars.status != "ok":
        # no_data, not_found and an empty_window are the feed's own answers
        # about this range; splitting one cannot produce bars it does not hold.
        return bars
    span = end - start
    tolerance = min(COVERAGE_TOLERANCE_DAYS * 86400,
                    max(86400, span // 8))
    if len(bars) > 0:
        reached_start = bars.ts[0] <= start + tolerance
        reached_end = bars.ts[-1] >= end - tolerance
        if reached_start and reached_end:
            return bars
    if span <= min_split_days * 86400:
        return bars
    mid = start + span // 2
    left = fetch_window(session, symbol, resolution, start, mid, on_fetch,
                        min_split_days)
    time.sleep(PACING_SECONDS)
    right = fetch_window(session, symbol, resolution, mid, end, on_fetch,
                         min_split_days)
    return merge(left, right)


def resample(bars: Bars, minutes: int) -> Bars:
    """Clock aligned OHLCV buckets built from the base series.

    Karachi is a whole number of hours from UTC, so a UTC clock boundary is
    also a Karachi clock boundary: 15, 30 and 60 minute buckets land on the
    same instants the feed's own native buckets use (checked by the builder).
    A bucket is open at its first bar's open, closes at its last bar's close,
    highs and lows are the extremes, and volume is the sum.
    """
    if minutes <= 0 or len(bars) == 0:
        return bars
    step = int(minutes) * 60
    bucket = (bars.ts // step) * step
    edges = np.flatnonzero(np.r_[True, bucket[1:] != bucket[:-1]])
    last = np.r_[edges[1:] - 1, len(bars) - 1]
    out = Bars(
        bucket[edges].astype(np.int64),
        bars.open[edges].astype(np.float64),
        np.maximum.reduceat(bars.high, edges).astype(np.float64),
        np.minimum.reduceat(bars.low, edges).astype(np.float64),
        bars.close[last].astype(np.float64),
        np.add.reduceat(bars.volume, edges).astype(np.int64),
        "ok",
        bars.requests_made,
    )
    return out


def regular_mask(ts: np.ndarray) -> np.ndarray:
    """True for bars inside the exchange's own trading bands.

    The feed carries the pre-open auction and the post-close session; this is
    the one column that lets a backtest use the regular session alone without
    re-deriving the calendar.
    """
    out = np.zeros(ts.size, dtype=bool)
    if ts.size == 0:
        return out
    days = np.array([datetime.fromtimestamp(int(t), tz=KARACHI).date().toordinal()
                     for t in ts])
    for ordinal in np.unique(days):
        d = date.fromordinal(int(ordinal))
        bands = session_bands(d)
        if not bands:
            continue
        idx = days == ordinal
        for band in bands:
            opens, closes = band_bounds(d, band)
            out[idx] |= (ts[idx] >= int(opens.timestamp())) & \
                        (ts[idx] < int(closes.timestamp()))
    return out


def validate(bars: Bars) -> dict:
    """Structural checks. Counts only: nothing is dropped or repaired here.

    The build fails closed on an impossible bar rather than writing a series a
    backtest would trust; a bar with a zero volume or a quiet minute is not a
    fault and is kept.
    """
    issues = {
        "bars": len(bars),
        "duplicate_ts": 0,
        "impossible_ohlc": 0,
        "non_positive_price": 0,
        "negative_volume": 0,
        "off_grid": 0,
    }
    if len(bars) == 0:
        return issues
    issues["duplicate_ts"] = int(np.sum(np.diff(bars.ts) == 0))
    high_ok = (bars.high >= np.maximum.reduce([bars.open, bars.close, bars.low]))
    low_ok = (bars.low <= np.minimum.reduce([bars.open, bars.close, bars.high]))
    issues["impossible_ohlc"] = int(np.sum(~(high_ok & low_ok)))
    issues["non_positive_price"] = int(np.sum(
        (bars.open <= 0) | (bars.high <= 0) | (bars.low <= 0) | (bars.close <= 0)))
    issues["negative_volume"] = int(np.sum(bars.volume < 0))
    issues["off_grid"] = int(np.sum(bars.ts % 300 != 0))
    return issues


def problems(bars: Bars) -> list[str]:
    """Human readable faults, empty when the series is structurally sound."""
    found = validate(bars)
    out = []
    for key in ("duplicate_ts", "impossible_ohlc", "non_positive_price",
                "negative_volume", "off_grid"):
        if found[key]:
            out.append(f"{key}={found[key]}")
    return out


def coverage(bars: Bars, start: int, end: int) -> dict:
    """How much of a window the series really covers, in sessions and bars."""
    if len(bars) == 0:
        return {"bars": 0, "sessions": 0, "first": None, "last": None,
                "trading_days": 0, "session_coverage_pct": 0.0}
    days = sorted({datetime.fromtimestamp(int(t), tz=KARACHI).date()
                   for t in bars.ts})
    first_day = datetime.fromtimestamp(int(start), tz=KARACHI).date()
    last_day = datetime.fromtimestamp(int(end), tz=KARACHI).date()
    trading = 0
    d = first_day
    while d <= last_day:
        if session_bands(d):
            trading += 1
        d = date.fromordinal(d.toordinal() + 1)
    return {
        "bars": len(bars),
        "sessions": len(days),
        "first": days[0].isoformat(),
        "last": days[-1].isoformat(),
        "trading_days": trading,
        "session_coverage_pct": round(100.0 * len(days) / trading, 2)
        if trading else 0.0,
    }


@dataclass
class FetchLog:
    """Counters a builder prints: requests made and how each window answered."""

    requests: int = 0
    empty_windows: int = 0
    splits: int = 0
    failures: list[str] = field(default_factory=list)

    def note(self, symbol: str, resolution: int, start: int, end: int,
             bars: int) -> None:
        self.requests += 1
        if bars == 0:
            self.empty_windows += 1
