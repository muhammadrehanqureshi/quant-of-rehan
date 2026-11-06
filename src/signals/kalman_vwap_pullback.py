"""The Kalman Trend pullback entry: agreement first, then a dip near the low.

Owner order 2026-11-06: a second intraday entry beside the fresh one minute
flip (src/signals/kalman_trend.py). When the one minute Kalman Trend is up and
the 5 minute, 15 minute, 1 hour and 1 day VWAP frames all agree
(src/signals/mtf_vwap.py), the alignment itself is not the entry. The entry
waits for the pullback that follows the agreement, takes the resumption, and
does so only while BOTH the pullback's low and the entry price sit in the
lower half of the session's range: strictly nearer the day's low than the
day's high.

The three questions, each answered from completed bars only:

  * pullback: inside the trailing PULLBACK_LOOKBACK_BARS one minute bars of
    the current band, the lowest low is the pullback low, the highest high
    before it is the swing high, and the decline between them must reach
    PULLBACK_MIN_DEPTH_PCT of the swing high. A window whose low is its first
    bar, a rise with no dip at all, or a dip shorter than the floor is
    refused by name.
  * resumption: the first bar after the pullback low whose close clears the
    highest high printed on the pullback leg. That bar is the signal, and it
    must be at most PULLBACK_RESUME_BARS old, so a dip that recovered ten
    bars ago is history rather than an entry.
  * location: the session's own high and low come from every completed bar
    of the day (the whole session, not only the current band), and both the
    pullback low and the entry must be strictly below their midpoint.

The frames are read at the signal bar, which is what the live scan can
measure causally; the pullback is the most recent structure before it. A
reader must not read this as "the frames were already aligned at the swing
high": that would need a full per-bar frame history the scan does not build,
and claiming it without measuring it is exactly what SO-3 forbids.

The owner's law is unchanged: +2% target, -1% stop under the entry, one call
a day, every data-honesty gate, signal-only (SO-1). Nothing here executes,
sleeps or touches a network.
"""

from __future__ import annotations

import math

from src import config

#: The strategy label carried on every candidate, the session state and the
#: delivered message, so a reader can always tell which entry law spoke.
STRATEGY_VERSION = config.PULLBACK_STRATEGY_VERSION


def _window(rows: list, lookback: int) -> list:
    """The trailing bars the pullback is read from."""
    if 0 < lookback < len(rows):
        return list(rows[-lookback:])
    return list(rows)


def detect(rows: list, lookback: int, resume_bars: int,
           min_depth: float) -> tuple[dict | None, str]:
    """Find a completed pullback and its resumption in the trailing bars.

    Returns the measured swing, or a named refusal. Nothing looks ahead: the
    low, the peak and the resumption are all indexed from the window's own
    completed bars and the resumption must already have printed. The dip is
    found FIRST and its swing high second, so a resumption that clears the
    old high cannot erase the dip it came from.
    """
    window = _window(rows, lookback)
    if len(window) < 3:
        return None, "pullback_window_too_short"
    # The pullback low first, the swing high it fell from second. The low may
    # not be the window's first bar, because then no swing high inside the
    # window precedes it.
    trough = min(range(1, len(window)),
                 key=lambda index: (window[index].low, index))
    peak = max(range(trough),
               key=lambda index: (window[index].high, -index))
    peak_high = float(window[peak].high)
    trough_low = float(window[trough].low)
    if not (math.isfinite(peak_high) and math.isfinite(trough_low)
            and peak_high > 0 and trough_low > 0):
        return None, "pullback_unusable_prices"
    if trough_low >= peak_high:
        return None, "pullback_no_dip_yet"
    depth = (peak_high - trough_low) / peak_high
    if depth < min_depth:
        return None, "pullback_too_shallow"
    resumed: int | None = None
    running_high = float(window[trough].high)
    for index in range(trough + 1, len(window)):
        if window[index].close > running_high:
            resumed = index
            break
        running_high = max(running_high, float(window[index].high))
    if resumed is None:
        return None, "pullback_no_resumption"
    bars_since = len(window) - 1 - resumed
    if bars_since > resume_bars:
        return None, "pullback_resumption_stale"
    return {
        "bars_in_window": len(window),
        "peak_at": window[peak].timestamp.isoformat(),
        "peak_high": peak_high,
        "trough_at": window[trough].timestamp.isoformat(),
        "trough_low": trough_low,
        "depth_pct": round(depth, 6),
        "resumed_at": window[resumed].timestamp.isoformat(),
        "resume_bars": bars_since,
    }, "ok"


def entry_view(rows: list, session_rows: list,
               entry: float) -> tuple[dict | None, str]:
    """The pullback plus the owner's location test, or the first refusal.

    *rows* are the current band's completed one minute bars, *session_rows*
    the whole session's completed bars (the day's own range), and *entry* the
    last completed close the signal would use.
    """
    setup, reason = detect(rows, config.PULLBACK_LOOKBACK_BARS,
                           config.PULLBACK_RESUME_BARS,
                           config.PULLBACK_MIN_DEPTH_PCT)
    if setup is None:
        return None, reason
    if not session_rows:
        return None, "pullback_no_session_range"
    day_high = max(float(bar.high) for bar in session_rows)
    day_low = min(float(bar.low) for bar in session_rows)
    if not (math.isfinite(day_high) and math.isfinite(day_low)
            and day_high > day_low and day_low > 0):
        return None, "pullback_no_session_range"
    midpoint = (day_high + day_low) / 2.0
    trough_low = setup["trough_low"]
    if not (trough_low < midpoint and entry < midpoint):
        return None, "pullback_not_near_day_low"
    return {
        **setup,
        "entry": entry,
        "session_high": day_high,
        "session_low": day_low,
        "session_midpoint": round(midpoint, 6),
        "trough_above_day_low_pct": round((trough_low - day_low) / day_low, 6),
        "entry_above_day_low_pct": round((entry - day_low) / day_low, 6),
        "closer_to": "daily low",
    }, "ok"


def score(setup: dict, reward_risk: float) -> float:
    """Rank pullback quality, never a probability of winning (SO-3).

    Depth counts up to twice the strategy's own floor, recovery counts how
    much of the dip the resumption took back, freshness counts the bars since
    that resumption, and the owner's cost-inclusive reward/risk keeps its
    bounded say. The number orders setups; it promises nothing.
    """
    floor = max(config.PULLBACK_MIN_DEPTH_PCT, 1e-9)
    depth = max(0.0, float(setup.get("depth_pct") or 0.0))
    depth_points = 20.0 * min(1.0, depth / (2.0 * floor))
    peak = float(setup.get("peak_high") or 0.0)
    trough = float(setup.get("trough_low") or 0.0)
    entry = float(setup.get("entry") or 0.0)
    recovered = 0.0
    if peak > trough:
        recovered = max(0.0, min(1.0, (entry - trough) / (peak - trough)))
    fresh_points = max(0.0,
                       10.0 - 2.0 * float(setup.get("resume_bars") or 0.0))
    return round(min(100.0, 50.0 + depth_points + 15.0 * recovered
                     + fresh_points
                     + min(15.0, 5.0 * max(0.0, reward_risk))), 2)
