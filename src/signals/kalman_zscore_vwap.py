"""The Kalman Trend, the 5m/15m/30m VWAP frames and the z-score spread law.

Owner order 2026-11-25 (Karachi): the day trading strategy is this law and no
other. The Kalman Trend and the VWAP on the 5 minute, 15 minute and 30 minute
charts stay and the z-score of the price minus VWAP spread is the mathematical
base. The opening range law that ran before this order is removed, not
disabled.

Owner order 2026-11-26 (Karachi, the latest): the entry is no longer required
to stand closer to the day's low than to the day's high. That gate is removed,
and so is its share of the score. The day's range is still measured and
carried in the view for the card, and a range that cannot be read no longer
refuses a call.

Owner order 2026-11-16 (Karachi): the z-score of the price minus VWAP spread
is a statistical-arbitrage mean-reversion measure, not a z-score of closes.

Owner order 2026-11-19 (Karachi): all three frames stay, at 5, 15 and 30
minutes, and the call must still arrive early in the session. The early call
comes from the shortened 5 minute history (three bars is a 15 minute VWAP line
and three earlier spreads are enough for the z, so the fast frame is ready
seven completed bars in).

Owner order 2026-11-19 (the owner's own arithmetic): a frame never waits for
two of its own candles, so the 30 minute frame votes on its first completed
bar, the one that closes at 10:02 from the 09:32 open (09:47 from Friday's
09:17 open). Two 30 minute bars are an hourly candle and the hourly candle is
not part of this strategy. All session times here are Asia/Karachi, UTC+5
(SO-8); no frame ever reads a forming candle.

The spread is measured, never eyeballed. For one frame, every completed bar
has a spread of its close against the rolling VWAP that was available at that
bar. The current spread is standardised against the mean and standard
deviation of the spreads that came before it. A quiet name therefore needs a
smaller absolute move than a violent one, and the result is a true z-score of
the spread rather than a z-score of the closes.

Entry law:

  * the one minute Kalman trend must be up (the caller owns that clock);
  * the 5 minute frame's Kalman state must be +1, so the fast chart has turned;
  * the 15 minute and 30 minute frames must both have Kalman state +1 and a
    close above their own VWAP, so the slower regime still supports the trade;
  * the 5 minute price-VWAP spread must sit at least ZSCORE_Z_MIN standard
    deviations below its own trailing mean, so the entry buys a measured
    statistical dislocation inside that rising regime;

Exit and risk are the owner's unchanged paper law: entry at the latest
completed close, a fixed -1% stop and a +2% target, three calls a day, each of
which must score above config.MIN_CALL_SCORE out of 100.

The score is a ranking number out of 100, never a probability. The law's own
shape (all three frames aligned and the dislocation at its floor) is worth 62;
the rest is measured: how far past the floor the dislocation is and the reward
against the stop. A minimal legal setup therefore clears
config.MIN_CALL_SCORE without the floor ever refusing the law's own answer.

Nothing here executes, sleeps or touches a network. A missing frame, an
unmeasurable spread or a thin tape fails closed with its reason named (SO-3).
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from statistics import pstdev

from src import config
from src.data.sessions import band_bounds, current_band, open_time
from src.signals import mtf_vwap

#: This reader's own version, carried on every view it returns.
ZSCORE_VERSION = "kalman_zscore_vwap_v2"

#: The strategy label a candidate built from this law carries.
STRATEGY_VERSION = config.ZSCORE_STRATEGY_VERSION


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


def spread_zscore(bars: list, lookback: int) -> dict | None:
    """The current price-VWAP spread in trailing standard deviations.

    Every spread in the series is causal: it uses the rolling VWAP built from
    bars up to that point. The current spread is compared with the spreads
    before it, so the observation is never part of its own mean or sigma.
    """
    if lookback < 1 or len(bars) < lookback + config.ZSCORE_MIN_SPREADS + 1:
        return None
    spreads: list[float] = []
    for end in range(lookback, len(bars) + 1):
        vwap = mtf_vwap.rolling_vwap(bars[:end], lookback)
        if vwap is None:
            continue
        close = float(bars[end - 1].close)
        if not math.isfinite(close) or close <= 0:
            continue
        spread = close - float(vwap)
        if math.isfinite(spread):
            spreads.append(spread)
    if len(spreads) < config.ZSCORE_MIN_SPREADS + 1:
        return None
    current = spreads[-1]
    history = spreads[:-1]
    mean = sum(history) / len(history)
    sigma = pstdev(history)
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    return {
        "z": (current - mean) / sigma,
        "spread": current,
        "mean": mean,
        "sigma": sigma,
        "samples": len(history),
    }


def _frame(bars: list, minutes: int) -> dict | None:
    """One frame's close, VWAP, Kalman state and spread z-score, or None."""
    if len(bars) < config.MTF_MIN_BARS[minutes]:
        return None
    vwap = mtf_vwap.rolling_vwap(bars, config.MTF_VWAP_LOOKBACK[minutes])
    if vwap is None:
        return None
    closes = [bar.close for bar in bars]
    if not all(math.isfinite(c) and c > 0 for c in closes):
        return None
    zview = spread_zscore(bars, config.MTF_VWAP_LOOKBACK[minutes])
    return {
        "minutes": minutes,
        "bars": len(bars),
        "close": closes[-1],
        "vwap": round(vwap, 6),
        "kalman_state": mtf_vwap.kalman_state(bars),
        "above_vwap": bool(closes[-1] > vwap),
        "spread_z": round(zview["z"], 4) if zview else None,
        "spread": round(zview["spread"], 6) if zview else None,
        "spread_mean": round(zview["mean"], 6) if zview else None,
        "spread_sigma": round(zview["sigma"], 6) if zview else None,
        "spread_samples": zview["samples"] if zview else 0,
    }


def frame_views(rows: list, session, session_rows: list | None = None
                ) -> tuple[dict | None, str]:
    """The 5, 15 and 30 minute frames, or the first frame that cannot vote.

    *session_rows* is the whole session's one minute tape. All three frames
    are built from it, so the afternoon still has the morning's completed
    bars and the 30 minute frame is not blind after a Friday midday break.
    """
    if current_band(session.as_of) is None:
        return None, "zscore_no_market_band"
    tape = session_rows if session_rows is not None else rows
    day_open = datetime.combine(session.day, time(*open_time(session.day)),
                                tzinfo=session.as_of.tzinfo)
    views: dict[str, dict] = {}
    for minutes in config.MTF_TIMEFRAMES:
        bars = mtf_vwap.completed(tape, minutes, day_open, session.as_of)
        view = _frame(bars, minutes)
        if view is None:
            return None, f"zscore_{minutes}m_not_ready"
        views[f"{minutes}m"] = view
    return views, "ok"


def day_range(tape: list, session) -> dict | None:
    """This session's low and high so far, and where the entry stands.

    Only completed minutes count (a bar's timestamp is its minute's open, so
    the forming minute is never evidence). ``position`` is 0.0 at the day's
    low and 1.0 at its high, which is the number the owner's gate reads.
    """
    day_open = datetime.combine(session.day, time(*open_time(session.day)),
                                tzinfo=session.as_of.tzinfo)
    bars = [bar for bar in tape
            if day_open <= bar.timestamp
            and bar.timestamp + timedelta(minutes=1) <= session.as_of]
    if not bars:
        return None
    try:
        high = max(float(bar.high) for bar in bars)
        low = min(float(bar.low) for bar in bars)
        close = float(bars[-1].close)
    except (AttributeError, TypeError, ValueError):
        return None
    if not (math.isfinite(high) and math.isfinite(low) and math.isfinite(close)):
        return None
    if high <= low or low <= 0:
        return None
    return {
        "high": round(high, 6),
        "low": round(low, 6),
        "close": round(close, 6),
        "position": round((close - low) / (high - low), 6),
        "side": "LOW" if close - low < high - close else "HIGH",
        "bars": len(bars),
    }


def entry_view(symbol: str, rows: list, session,
               session_rows: list | None = None) -> tuple[dict | None, str]:
    """This name's z-score spread entry, or the first gate that refuses it."""
    frames, reason = frame_views(rows, session, session_rows=session_rows)
    if frames is None:
        return None, reason

    fast = frames.get("5m")
    middle = frames.get("15m")
    slow = frames.get("30m")
    if fast is None:
        return None, "zscore_5m_missing"
    if middle is None:
        return None, "zscore_15m_missing"
    if slow is None:
        return None, "zscore_30m_missing"

    if fast.get("kalman_state") != 1:
        return None, "zscore_fast_frame_not_up"
    for key, frame in (("15m", middle), ("30m", slow)):
        if frame.get("kalman_state") != 1:
            return None, f"zscore_{key}_trend_not_up"
        if not frame.get("above_vwap"):
            return None, f"zscore_{key}_below_vwap"

    z = fast.get("spread_z")
    if z is None:
        return None, "zscore_spread_unmeasurable"
    if z > -config.ZSCORE_Z_MIN:
        return None, "zscore_not_stretched_below_mean"

    # Owner order 2026-11-26: the low side of the day's range is not a gate. The
    # range is still measured and carried in the view for the card; a range
    # that cannot be read no longer refuses the entry, and the tape's own last
    # close stands in its place.
    day = day_range(session_rows if session_rows is not None else rows, session)
    close = day["close"] if day is not None else (rows[-1].close if rows else None)

    return {
        "rule": ZSCORE_VERSION,
        "symbol": symbol,
        "side": "LONG",
        "close": round(float(close), 6) if close is not None else None,
        "signal_minutes": config.ZSCORE_SIGNAL_FRAME_MINUTES,
        "z": round(z, 4),
        "z_min": round(config.ZSCORE_Z_MIN, 4),
        "spread": fast.get("spread"),
        "spread_mean": fast.get("spread_mean"),
        "spread_sigma": fast.get("spread_sigma"),
        "spread_samples": fast.get("spread_samples"),
        "day": day,
        "frames": {key: {"close": v["close"], "vwap": v["vwap"],
                         "kalman_state": v["kalman_state"],
                         "above_vwap": v["above_vwap"],
                         "spread_z": v["spread_z"], "bars": v["bars"]}
                   for key, v in frames.items()},
    }, "ok"


def score(view: dict | None, reward_risk: float) -> float:
    """A ranking number for a z-score spread setup, never a probability.

    Owner order 2026-11-25: the law's own shape is 62, the dislocation past
    its floor adds up to 18 and the reward against the stop adds up to 10. The
    low side of the day's range used to add up to 10 more; owner order
    2026-11-26 removed it, so no legal setup can print below 62 and a perfect
    one prints 90. The floor (config.MIN_CALL_SCORE) never refuses the law's
    own answer and the day can still carry the three calls the owner asked for.
    """
    if not isinstance(view, dict):
        return 0.0
    z = abs(float(view.get("z") or 0.0))
    depth = min(18.0, 9.0 * max(0.0, z - config.ZSCORE_Z_MIN))
    reward = min(10.0, 4.0 * max(0.0, reward_risk))
    return round(min(100.0, 62.0 + depth + reward), 2)


def candidate(symbol: str, rows: list, session,
              tally: dict | None = None,
              frames: bool = False) -> dict | None:
    """Return the one legal z-score spread candidate, or None.

    The shared data-honesty gates come first (ETF anonymity, the band clock,
    completed bars, positive prices, a real tape volume, the price and
    turnover floors, freshness, no continuity across a gap, the day's move and
    the measured buy/sell split), then the law itself. ``frames`` says whether
    this deployment reads the three VWAP frames; the law cannot be evaluated
    without them, so a replay without higher timeframe history has no entry
    and names that reason.
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

    if not config.ZSCORE_ENABLED:
        _bump(tally, "zscore_law_disabled")
        return None
    if not (config.MTF_ENABLED and frames):
        _bump(tally, "zscore_frames_not_read")
        return None

    view, reason = entry_view(symbol, rows, session, session_rows=session_rows)
    if view is None:
        _bump(tally, reason)
        return None

    return {
        "symbol": symbol,
        "score": score(view, reward_risk),
        "strategy": STRATEGY_VERSION, "side": "LONG",
        "price": {"last": entry}, "stop_loss": stop, "target": target,
        "risk_pct": risk, "net_reward_risk": reward_risk,
        "setup": {
            "zscore": view,
            "entry_path": "zscore_spread_reversion",
        },
        "volume": {"traded_value_estimate": turnover,
                   "volume_source": "captured bar volume"},
        "day": {"gain_pct": round(day_gain * 100.0, 3),
                "basis": gain_basis, "previous_close": reference},
        "flow": {"buy_volume": int(buy), "sell_volume": int(sell),
                 "buy_sell_ratio": round(buy / sell, 3) if sell else None},
        "last_bar": rows[-1].timestamp.isoformat(), "bars": len(rows),
        "entry_basis": "latest completed close at a measured spread below its "
                       "5m VWAP with the 5m, 15m and 30m Kalman states up; "
                       "paper reference, not a fill",
    }


def summary(view: dict | None) -> str:
    """One ASCII line for the card and the owner email, or empty."""
    if not isinstance(view, dict):
        return ""
    z = view.get("z")
    fast = (view.get("frames") or {}).get("5m") or {}
    vwap = fast.get("vwap")
    if z is None or vwap is None:
        return ""
    line = (f"Z-SPREAD {z:+.2f} sigma versus the 5m VWAP {vwap}, "
            f"with 5m/15m/30m Kalman aligned")
    return line
