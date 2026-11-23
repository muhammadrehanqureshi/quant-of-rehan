"""The opening range with the 5m, 15m and 30m VWAP lines, scored out of 100.

Owner order 2026-11-23 (Karachi): the day trading strategy is the opening
range with the VWAP on the 5 minute, 15 minute and 30 minute charts. The
Kalman Trend and the z-score price-VWAP spread are removed outright: no
Kalman state is read here, and no spread is standardised. The day still
carries at most three calls (config.MAX_TRADES_PER_DAY), and every call
carries a score out of 100.

The law, in order:

  * the opening range is the first OPENING_RANGE_MINUTES completed one minute
    bars of the session, and every one of those minutes must be present, so a
    gap is a hole rather than a padded range;
  * the latest completed one minute bar must close above that range's high,
    by no more than OPENING_RANGE_MAX_EXTENSION times the range's own height,
    so a name already far past the range is a chase and is refused;
  * the 5, 15 and 30 minute frames must each have a completed bar whose close
    sits above that frame's own rolling VWAP.

The score is a ranking number out of 100, never a probability. The law's own
shape (a formed range, a held breakout and all three frames above VWAP) is
worth 50; the rest is measured: how far above its VWAP each frame sits, how
far the breakout has cleared the range, and the breakout bar's volume against
the range's own average volume. A minimal legal setup therefore clears
config.MIN_CALL_SCORE without the floor ever refusing the law's own answer.

Entry, stop and target are the owner's unchanged paper plan: entry at the
latest completed close, a fixed -1% stop and a +2% target. Nothing here
executes, sleeps or touches a network. A missing frame, an unformed range or
a thin tape fails closed with its own reason named (SO-3).

Asia/Karachi, UTC+5 (SO-8). Signal-only: no broker orders (SO-1).
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta

from src import config
from src.data.sessions import band_bounds, current_band, open_time
from src.signals import mtf_vwap

#: This law's own reader version, carried on every view it returns.
READER_VERSION = "opening_range_vwap_v1"

#: The strategy label a candidate built from this law carries.
STRATEGY_VERSION = config.OPENING_RANGE_STRATEGY_VERSION


def _bump(tally: dict | None, key: str) -> None:
    """Count one rejection reason, when the caller wants the why."""
    if tally is not None:
        tally[key] = tally.get(key, 0) + 1


def day_gain_pct(session, symbol: str,
                 entry: float) -> tuple[float | None, str, float | None]:
    """The pick's day move, from the venue's own reference when it exists.

    Owner order 2026-11-19 (Karachi): the pick may not already be more than
    MAX_DAY_GAIN_PCT up on the day. A move measured from the session's own
    first bar would call a name that gapped up at the open flat, which is
    exactly the pick this gate exists to stop, so the tape's ``close`` field
    (the venue's previous close) is the reference. Only a source that carries
    no previous close at all falls back to the session's first bar, and the
    basis travels with the number so a reader sees which was used.

    Returns (gain as a fraction, basis, the reference price or None).
    """
    previous = (getattr(session, "previous_close", None) or {}).get(symbol)
    if previous is not None and previous > 0:
        return entry / previous - 1.0, "venue_previous_close", previous
    rows = (getattr(session, "bars", None) or {}).get(symbol)
    if rows and rows[0].open and rows[0].open > 0:
        return entry / rows[0].open - 1.0, "session_first_bar", None
    return None, "unmeasurable", None


def opening_range(rows: list, session_open: datetime,
                  as_of: datetime) -> dict | None:
    """The session's first completed bars, or None when the range is not whole.

    Every one of the first OPENING_RANGE_MINUTES minutes must be present and
    consecutive: a capture that started late or slept through a minute has no
    opening range rather than a narrower invented one.
    """
    need = config.OPENING_RANGE_MINUTES
    window = [bar for bar in rows
              if session_open <= bar.timestamp
              and bar.timestamp < session_open + timedelta(minutes=need)]
    if len(window) != need:
        return None
    start = session_open
    for position, bar in enumerate(sorted(window, key=lambda b: b.timestamp)):
        if bar.timestamp != start + timedelta(minutes=position):
            return None
    if as_of < session_open + timedelta(minutes=need):
        return None
    ordered = sorted(window, key=lambda b: b.timestamp)
    high = max(float(bar.high) for bar in ordered)
    low = min(float(bar.low) for bar in ordered)
    volume = sum(float(bar.volume) for bar in ordered
                 if bar.volume is not None and math.isfinite(bar.volume))
    if not (math.isfinite(high) and math.isfinite(low) and high > low > 0):
        return None
    return {
        "minutes": need,
        "open_time": session_open.isoformat(),
        "close_time": (session_open + timedelta(minutes=need)).isoformat(),
        "high": round(high, 6),
        "low": round(low, 6),
        "height": round(high - low, 6),
        "volume": volume,
        "bars": need,
    }


def _frame_view(bars: list, minutes: int) -> tuple[dict | None, str]:
    """One frame's close and its own rolling VWAP, or a named refusal."""
    if len(bars) < config.MTF_MIN_BARS[minutes]:
        return None, f"opening_range_{minutes}m_not_ready"
    vwap = mtf_vwap.rolling_vwap(bars, config.MTF_VWAP_LOOKBACK[minutes])
    if vwap is None:
        return None, f"opening_range_{minutes}m_vwap_unavailable"
    close = float(bars[-1].close)
    if not (math.isfinite(close) and close > 0):
        return None, f"opening_range_{minutes}m_close_unavailable"
    return {
        "minutes": minutes,
        "bars": len(bars),
        "close": round(close, 6),
        "vwap": round(vwap, 6),
        "above_vwap": bool(close > vwap),
    }, "ok"


def entry_view(symbol: str, rows: list, session,
               session_rows: list | None = None) -> tuple[dict | None, str]:
    """This name's opening range breakout, or the first gate that refuses it.

    ``session_rows`` is the whole session's one minute tape, so the morning's
    range is still read in the Friday afternoon band. All frames are built
    from completed bars only.
    """
    if current_band(session.as_of) is None:
        return None, "opening_range_no_market_band"
    tape = session_rows if session_rows is not None else rows
    session_open = datetime.combine(session.day, time(*open_time(session.day)),
                                    tzinfo=session.as_of.tzinfo)
    rng = opening_range(tape, session_open, session.as_of)
    if rng is None:
        return None, "opening_range_not_formed"
    completed = [bar for bar in tape
                 if session_open <= bar.timestamp
                 and bar.timestamp + timedelta(minutes=1) <= session.as_of]
    if not completed:
        return None, "opening_range_no_completed_bar"
    last = max(completed, key=lambda bar: bar.timestamp)
    close = float(last.close)
    high = float(rng["high"])
    if not (math.isfinite(close) and close > 0):
        return None, "opening_range_close_unavailable"
    if close <= high:
        return None, "opening_range_not_broken"
    extension = (close - high) / float(rng["height"])
    if extension > config.OPENING_RANGE_MAX_EXTENSION:
        return None, "opening_range_too_far_past"

    frames: dict[str, dict] = {}
    for minutes in config.MTF_TIMEFRAMES:
        bars = mtf_vwap.completed(tape, minutes, session_open, session.as_of)
        view, reason = _frame_view(bars, minutes)
        if view is None:
            return None, reason
        if not view["above_vwap"]:
            return None, f"opening_range_{minutes}m_below_vwap"
        frames[f"{minutes}m"] = view

    return {
        "rule": READER_VERSION,
        "symbol": symbol,
        "side": "LONG",
        "close": round(close, 6),
        "opening_range": rng,
        "range_high": rng["high"],
        "range_low": rng["low"],
        "range_height": rng["height"],
        "extension": round(extension, 4),
        "breakout_volume": float(last.volume or 0.0),
        "breakout_time": last.timestamp.isoformat(),
        "frames": frames,
    }, "ok"


def score(view: dict | None) -> float:
    """A ranking number out of 100 for the opening range setup.

    The law's own shape is 50 points. The remaining 50 are measured: 20 for
    how far the three frames sit above their own VWAP (each measured against
    the range's height), 15 for how far the breakout has cleared the range
    high (capped at one range height, which is also the anti-chase cap's own
    unit), and 15 for the breakout bar's volume against the range's average
    volume (capped at twice the average). Never a probability.
    """
    if not isinstance(view, dict):
        return 0.0
    height = float(view.get("range_height") or 0.0)
    if not (math.isfinite(height) and height > 0):
        return 0.0
    frames = view.get("frames") or {}
    distances = []
    for key in ("5m", "15m", "30m"):
        frame = frames.get(key) or {}
        close = float(frame.get("close") or 0.0)
        vwap = float(frame.get("vwap") or 0.0)
        if not (math.isfinite(close) and math.isfinite(vwap) and vwap > 0):
            return 0.0
        distances.append(min(1.0, max(0.0, (close - vwap) / height)))
    strength = sum(distances) / len(distances)
    clear = min(1.0, max(0.0, float(view.get("extension") or 0.0)))
    rng = view.get("opening_range") or {}
    range_bars = max(int(rng.get("bars") or 0), 1)
    average = float(rng.get("volume") or 0.0) / range_bars
    breakout = float(view.get("breakout_volume") or 0.0)
    ratio = breakout / average if average > 0 else 0.0
    volume = min(1.0, max(0.0, ratio / 2.0))
    return round(min(100.0, 50.0 + 20.0 * strength + 15.0 * clear
                     + 15.0 * volume), 2)


def candidate(symbol: str, rows: list, session,
              tally: dict | None = None,
              frames: bool = False) -> dict | None:
    """Return the one legal opening range candidate, or None.

    The shared data-honesty gates come first (ETF anonymity, the band clock,
    completed bars, positive prices, a real tape volume, the price and
    turnover floors, freshness, no continuity across a gap, the day's move and
    the measured buy/sell split), then the opening range law. ``frames`` says
    whether this deployment reads the three VWAP frames; the law cannot be
    evaluated without them, so a replay without higher timeframe history has
    no entry and names that reason.
    """
    if config.is_etf_symbol(symbol) or session.as_of.tzinfo is None:
        _bump(tally, "etf_or_naive_tz")
        return None
    session_rows = list(rows)
    band = current_band(session.as_of)
    if band is None:
        _bump(tally, "no_market_band")
        return None
    opens, closes = band_bounds(session.day, band)
    if session.as_of >= closes - timedelta(
            minutes=config.KALMAN_LAST_ENTRY_MINUTES):
        _bump(tally, "near_band_close")
        return None
    # Bar timestamps denote minute OPEN, so an in-progress minute is never
    # evidence, even when the scan runs at HH:MM:30.
    rows = [bar for bar in rows if opens <= bar.timestamp
            and bar.timestamp + timedelta(minutes=1) <= session.as_of]
    if len(rows) < config.MIN_BARS_PER_SYMBOL:
        _bump(tally, "bars_under_strategy_minimum")
        return None
    if session.as_of - (rows[-1].timestamp + timedelta(minutes=1)) > timedelta(
            seconds=config.KALMAN_MAX_SIGNAL_AGE_SECONDS):
        _bump(tally, "stale_print")
        return None
    gap_start = 0
    for index, bar in enumerate(rows):
        values = (bar.open, bar.high, bar.low, bar.close)
        if (not all(math.isfinite(value) and value > 0 for value in values)
                or bar.high < max(bar.open, bar.close)
                or bar.low > min(bar.open, bar.close)
                or bar.high < bar.low or bar.volume is None
                or not math.isfinite(bar.volume) or bar.volume < 0):
            _bump(tally, "impossible_row")
            return None
        if index and bar.timestamp - rows[index - 1].timestamp != timedelta(minutes=1):
            gap_start = index
    rows = rows[gap_start:]
    if len(rows) < config.MIN_BARS_PER_SYMBOL or rows[-1].close < config.MIN_PRICE:
        _bump(tally, "too_short_after_gap_or_penny")
        return None
    turnover = sum(bar.close * bar.volume for bar in rows)
    if turnover < config.MIN_SESSION_TRADED_VALUE:
        _bump(tally, "under_min_session_traded_value")
        return None

    day_gain, gain_basis, reference = day_gain_pct(session, symbol,
                                                   rows[-1].close)
    if day_gain is None:
        _bump(tally, "day_gain_unmeasurable")
        return None
    if day_gain > config.MAX_DAY_GAIN_PCT:
        _bump(tally, "day_gain_over_max")
        return None
    buy = (getattr(session, "buy_volume", None) or {}).get(symbol)
    sell = (getattr(session, "sell_volume", None) or {}).get(symbol)
    if buy is None or sell is None or buy + sell <= 0:
        _bump(tally, "buy_sell_split_unavailable")
        return None
    if buy < config.MIN_BUY_SELL_RATIO * sell:
        _bump(tally, "buyers_not_dominant")
        return None

    entry = rows[-1].close
    stop = round(entry * (1 - config.KALMAN_STOP_PCT), 4)
    if entry <= stop or entry <= 0:
        _bump(tally, "stop_not_below_entry")
        return None
    target = round(entry * (1 + config.TARGET_PCT), 4)
    risk = (entry - stop) / entry
    if risk > config.KALMAN_MAX_RISK_PCT:
        _bump(tally, "risk_outside_band")
        return None
    net_reward = config.TARGET_PCT - config.round_trip_cost()
    reward_risk = net_reward / (risk + config.round_trip_cost())

    if not config.OPENING_RANGE_ENABLED:
        _bump(tally, "opening_range_law_disabled")
        return None
    if not (config.MTF_ENABLED and frames):
        _bump(tally, "opening_range_frames_not_read")
        return None

    view, reason = entry_view(symbol, rows, session, session_rows=session_rows)
    if view is None:
        _bump(tally, reason)
        return None

    return {
        "symbol": symbol,
        "score": score(view),
        "strategy": STRATEGY_VERSION, "side": "LONG",
        "price": {"last": entry}, "stop_loss": stop, "target": target,
        "risk_pct": risk, "net_reward_risk": reward_risk,
        "setup": {
            "opening_range": view,
            "entry_path": "opening_range_breakout",
        },
        "volume": {"traded_value_estimate": turnover,
                   "volume_source": "captured bar volume"},
        "day": {"gain_pct": round(day_gain * 100.0, 3),
                "basis": gain_basis, "previous_close": reference},
        "flow": {"buy_volume": int(buy), "sell_volume": int(sell),
                 "buy_sell_ratio": round(buy / sell, 3) if sell else None},
        "last_bar": rows[-1].timestamp.isoformat(), "bars": len(rows),
        "entry_basis": "latest completed close above the opening range high "
                       "with the 5m, 15m and 30m closes above their own VWAP "
                       "and the breakout inside the range's own chase cap; "
                       "paper reference, not a fill",
    }


def summary(view: dict | None) -> str:
    """One ASCII line for the card and the owner email, or empty."""
    if not isinstance(view, dict):
        return ""
    rng = view.get("opening_range") or {}
    frames = view.get("frames") or {}
    high, low = rng.get("high"), rng.get("low")
    if high is None or low is None or len(frames) != 3:
        return ""
    extension = float(view.get("extension") or 0.0)
    return (f"OPENING RANGE {low:.2f}-{high:.2f}, 5m/15m/30m above VWAP, "
            f"breakout {extension:.2f}x the range")
