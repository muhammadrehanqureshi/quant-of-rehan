"""Multi-timeframe VWAP and Kalman confirmation for the intraday signal.

Owner order 2026-11-03: VWAP joins the Kalman Trend, and the intraday signal
is read on the 5 minute, 15 minute, 1 hour and 1 day charts. The one minute
tape stays the execution clock: it is where the fresh flip and the entry
price come from. The four higher timeframes are the regime the flip must
agree with.

Each frame is built only from completed bars, so nothing here looks at a
forming candle:

  * 5m, 15m and 1h are strict session-aligned aggregations of the one minute
    bars. A bucket with a missing minute is a hole, never a padded bar.
  * 1D is the symbol's daily history, supplied by the caller from
    src/data/daily_history.py. Today's forming day is never included.

For every frame the close must sit above that frame's rolling VWAP and the
Kalman state on that frame's closes must be +1. The VWAP is volume weighted
typical price over the last N completed bars of the frame, so it is a real
per-chart line rather than one session number copied four times. A frame
with no volume, no VWAP or too little history fails closed and its reason is
returned, never guessed.

Nothing in this module executes, sleeps or touches a network.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from src import config
from src.data.sessions import band_bounds, current_band, open_time
from src.signals.kalman_trend import filter_series

MTF_VERSION = "vwap_mtf_v1"

#: The four frames the owner named, in minutes. 1440 is handled separately
#: because a day bar is not a strict multiple of the session's 1 minute bars.
TIMEFRAMES = config.MTF_TIMEFRAMES

#: VWAP lookbacks, in completed bars of each frame. Twelve 5m bars is one
#: hour, twelve 1h bars is a day and a half, twenty daily bars is one month.
VWAP_LOOKBACK = config.MTF_VWAP_LOOKBACK

#: The minimum completed bars a frame needs before it can vote. The 1D frame
#: needs the same forty bars the one minute filter uses to settle.
MIN_BARS = config.MTF_MIN_BARS


@dataclass(frozen=True)
class Frame:
    """One completed higher-timeframe bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def completed(rows: list, minutes: int, session_open: datetime,
              as_of: datetime) -> list[Frame]:
    """Aggregate 1 minute bars into completed, session-aligned *minutes* bars.

    A bucket is emitted only when it holds exactly `minutes` consecutive one
    minute bars, so a gap is a hole in the higher timeframe rather than a bar
    carrying a fabricated open or close. `as_of` is exclusive.
    """
    if minutes <= 1:
        raise ValueError("minutes must be greater than one")
    buckets: dict[int, list] = {}
    for bar in rows:
        if bar.timestamp < session_open:
            continue
        if bar.timestamp + timedelta(minutes=1) > as_of:
            continue
        offset = int((bar.timestamp - session_open).total_seconds() // 60)
        if offset < 0:
            continue
        buckets.setdefault(offset // minutes, []).append(bar)

    out: list[Frame] = []
    for index in sorted(buckets):
        group = sorted(buckets[index], key=lambda bar: bar.timestamp)
        if len(group) != minutes:
            continue
        start = group[0].timestamp
        if any(bar.timestamp != start + timedelta(minutes=position)
               for position, bar in enumerate(group)):
            continue
        if any(bar.volume is None or not math.isfinite(bar.volume)
               or bar.volume < 0 for bar in group):
            continue
        out.append(Frame(
            timestamp=start,
            open=group[0].open,
            high=max(bar.high for bar in group),
            low=min(bar.low for bar in group),
            close=group[-1].close,
            volume=sum(float(bar.volume) for bar in group),
        ))
    return out


def rolling_vwap(bars: list[Frame], lookback: int) -> float | None:
    """Volume weighted typical price over the last *lookback* bars.

    Bars with no volume contribute nothing; a window with no volume at all
    has no VWAP and returns None rather than a price-only proxy.
    """
    window = bars[-lookback:] if lookback > 0 else bars
    traded = 0.0
    value = 0.0
    for bar in window:
        volume = bar.volume
        if volume is None or not math.isfinite(volume) or volume <= 0:
            continue
        typical = (bar.high + bar.low + bar.close) / 3.0
        if not math.isfinite(typical) or typical <= 0:
            continue
        traded += volume
        value += typical * volume
    if traded <= 0:
        return None
    return value / traded


def kalman_state(bars: list[Frame]) -> int | None:
    """The Kalman state on this frame's completed closes, or None."""
    closes = [bar.close for bar in bars]
    if len(closes) < 2:
        return None
    if any(not math.isfinite(close) or close <= 0 for close in closes):
        return None
    trace = filter_series(closes, config.KALMAN_Q, config.KALMAN_R,
                          config.KALMAN_FLIP_THRESHOLD)
    return trace[-1]["state"]


def _view(bars: list[Frame], minutes: int) -> tuple[dict | None, str]:
    """The frame's answer: close, VWAP, state and whether it agrees."""
    need = MIN_BARS[minutes]
    if len(bars) < need:
        return None, f"mtf_{minutes}m_not_ready"
    vwap = rolling_vwap(bars, VWAP_LOOKBACK[minutes])
    state = kalman_state(bars)
    last = bars[-1]
    view = {
        "minutes": minutes,
        "bars": len(bars),
        "close": last.close,
        "vwap": round(vwap, 6) if vwap is not None else None,
        "kalman_state": state,
        "above_vwap": bool(vwap is not None and last.close > vwap),
        "as_of": last.timestamp.isoformat(),
    }
    if vwap is None:
        return view, f"mtf_{minutes}m_vwap_unavailable"
    if state is None:
        return view, f"mtf_{minutes}m_kalman_unavailable"
    if state != 1:
        return view, f"mtf_{minutes}m_trend_not_up"
    if last.close <= vwap:
        return view, f"mtf_{minutes}m_below_vwap"
    return view, "ok"


def evaluate(rows: list, session, daily: list,
             hourly_rows: list | None = None) -> tuple[dict | None, str]:
    """Read the four frames and return the agreement, or the first refusal.

    *daily* is the symbol's completed daily bars, oldest first, with the
    current session excluded. It must be supplied: the caller decides
    whether the one day frame is available at all.

    *hourly_rows* is the whole session's one minute tape, so the 1 hour bars
    still carry the morning block after a Friday midday break. The 5 and 15
    minute frames stay on the current band; when the tape is not supplied
    they use the same rows as the faster frames.
    """
    band = current_band(session.as_of)
    if band is None:
        return None, "mtf_no_market_band"
    session_open, _session_close = band_bounds(session.day, band)
    day_open = datetime.combine(session.day, time(*open_time(session.day)),
                                tzinfo=session.as_of.tzinfo)

    frames: dict[str, dict] = {}
    for minutes in (5, 15):
        bars = completed(rows, minutes, session_open, session.as_of)
        view, reason = _view(bars, minutes)
        if view is None:
            return None, reason
        frames[f"{minutes}m"] = view
        if reason != "ok":
            return None, reason

    hour_bars = completed(hourly_rows if hourly_rows is not None else rows,
                          60, day_open, session.as_of)
    view, reason = _view(hour_bars, 60)
    if view is None:
        return None, reason
    frames["60m"] = view
    if reason != "ok":
        return None, reason

    daily_bars = [
        Frame(timestamp=bar.day, open=bar.open, high=bar.high, low=bar.low,
              close=bar.close, volume=bar.volume)
        for bar in daily
        if bar.close > 0 and bar.day < session.day
    ]
    view, reason = _view(daily_bars, 1440)
    if view is None:
        return None, reason
    frames["1d"] = view
    if reason != "ok":
        return None, reason

    return {
        "rule": MTF_VERSION,
        "frames": frames,
        "entry_clock": "1m flip and last completed 1m close",
    }, "ok"


def summary(view: dict | None) -> str:
    """One ASCII line naming all four frame states, or empty when incomplete.

    The line is the display contract for the cloud card and the owner email.
    It never invents a frame: a missing frame returns empty rather than a
    partial claim, because a reader must not see three states and assume the
    fourth agreed.
    """
    frames = (view or {}).get("frames") or {}
    parts = []
    for key, label in (("5m", "5m"), ("15m", "15m"),
                       ("60m", "1h"), ("1d", "1D")):
        frame = frames.get(key)
        if not isinstance(frame, dict):
            return ""
        state = frame.get("kalman_state")
        state_text = f"{state:+d}" if isinstance(state, int) else "?"
        side = "above VWAP" if frame.get("above_vwap") else "below VWAP"
        parts.append(f"{label} {state_text} {side}")
    return "MTF " + " | ".join(parts)
