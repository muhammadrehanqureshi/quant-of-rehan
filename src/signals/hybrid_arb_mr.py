"""The hybrid statistical arbitrage and mean reversion law.

Owner order 2026-11-12 (Karachi): a new intraday strategy joins the book,
the Kalman Trend with the VWAP on the 5 minute, 15 minute and 1 hour charts
AND a hybrid statistical arbitrage and mean reversion model.

It is a third entry law inside the ONE scanner (src/signals/kalman_trend.py),
never a second engine. The entry asks for three measured facts at once:

  * the price is stretched BELOW the 15 minute frame's VWAP by at least
    HYBRID_Z_MIN standard deviations of that frame's own closes, so a quiet
    tape needs a smaller move than a violent one and the stretch is measured,
    never eyeballed;
  * the 5 minute frame has turned up (its Kalman state is +1): the fast chart
    already agrees with the reversion, which is the Kalman Trend ingredient;
  * the name is LAGGING the equal-weight market leg the scan measured by at
    least HYBRID_LAG_MIN_PCT, which is the cheap side of the pair. Chasing a
    leader is never this law.

The one minute Kalman state is checked by the caller, which owns the execution
clock: a reversion entry needs the one minute trend up, exactly like the other
two laws. Entry, stop and target are the owner's fixed paper numbers taken
from the caller's entry price, so all three laws share one risk plan.

Nothing here executes, sleeps or touches a network. A missing frame, a thin
name or an unmeasured market fails closed with its reason named (SO-3).
"""

from __future__ import annotations

import math
from datetime import datetime, time
from statistics import pstdev

from src import config
from src.data.sessions import band_bounds, current_band, open_time
from src.signals import mtf_vwap

#: This reader's own version, carried on every view it returns.
HYBRID_VERSION = "hybrid_sa_mr_v1"

#: The strategy label a candidate built from this law carries.
STRATEGY_VERSION = config.HYBRID_STRATEGY_VERSION


def _frame(bars: list, minutes: int) -> dict | None:
    """One frame's close, VWAP and Kalman state, or None when it cannot vote."""
    if len(bars) < config.MTF_MIN_BARS[minutes]:
        return None
    vwap = mtf_vwap.rolling_vwap(bars, config.MTF_VWAP_LOOKBACK[minutes])
    if vwap is None:
        return None
    closes = [bar.close for bar in bars]
    if not all(math.isfinite(c) and c > 0 for c in closes):
        return None
    return {
        "minutes": minutes,
        "bars": len(bars),
        "close": closes[-1],
        "vwap": round(vwap, 6),
        "kalman_state": mtf_vwap.kalman_state(bars),
        "above_vwap": bool(closes[-1] > vwap),
        "closes": closes,
    }


def frame_views(rows: list, session, hourly_rows: list | None = None
                ) -> tuple[dict | None, str]:
    """The three frames this law reads, or the first frame that cannot vote.

    *hourly_rows* is the whole session's one minute tape, so the 1 hour frame
    still carries the morning block after a Friday midday break. The 5 and 15
    minute frames stay on the current band, the same split mtf_vwap keeps.
    """
    band = current_band(session.as_of)
    if band is None:
        return None, "hybrid_no_market_band"
    session_open, _session_close = band_bounds(session.day, band)
    day_open = datetime.combine(session.day, time(*open_time(session.day)),
                                tzinfo=session.as_of.tzinfo)
    views: dict[str, dict] = {}
    for minutes in (5, 15):
        view = _frame(mtf_vwap.completed(rows, minutes, session_open,
                                         session.as_of), minutes)
        if view is None:
            return None, f"hybrid_{minutes}m_not_ready"
        views[f"{minutes}m"] = view
    hour_bars = mtf_vwap.completed(hourly_rows if hourly_rows is not None
                                   else rows, 60, day_open, session.as_of)
    view = _frame(hour_bars, 60)
    if view is None:
        return None, "hybrid_60m_not_ready"
    views["60m"] = view
    return views, "ok"


def stretch(closes: list, vwap: float | None) -> float | None:
    """How far below (or above) the mean the last close sits, in sigmas.

    The unit is the frame's own dispersion, so the same number means the same
    thing on a quiet scrip and on a violent one. Fewer than three closes, a
    missing VWAP or a frame that never moved cannot be measured and answer
    None rather than a zero (SO-3: a missing number is not a number).
    """
    if vwap is None or len(closes) < 3:
        return None
    if not all(math.isfinite(c) and c > 0 for c in closes):
        return None
    sd = pstdev(closes)
    if not math.isfinite(sd) or sd <= 0:
        return None
    return (closes[-1] - float(vwap)) / sd


def entry_view(symbol: str, rows: list, session, market: dict | None,
               hourly_rows: list | None = None) -> tuple[dict | None, str]:
    """This name's reversion view, or the first gate that refuses it."""
    frames, reason = frame_views(rows, session, hourly_rows=hourly_rows)
    if frames is None:
        return None, reason
    if not isinstance(market, dict):
        return None, "hybrid_market_unavailable"
    market_leg = market.get("mean_return")
    if market_leg is None or not math.isfinite(float(market_leg)):
        return None, "hybrid_market_unavailable"

    mean_frame = frames.get(f"{config.HYBRID_MEAN_FRAME_MINUTES}m")
    fast_frame = frames.get(f"{config.HYBRID_FAST_FRAME_MINUTES}m")
    if mean_frame is None:
        return None, "hybrid_mean_frame_missing"
    if fast_frame is None:
        return None, "hybrid_fast_frame_missing"

    z = stretch(mean_frame.get("closes") or [], mean_frame.get("vwap"))
    if z is None:
        return None, "hybrid_stretch_unmeasurable"
    if z > -config.HYBRID_Z_MIN:
        return None, "hybrid_not_stretched_below_mean"
    if fast_frame.get("kalman_state") != 1:
        return None, "hybrid_fast_frame_not_up"

    own = _session_return(rows, session)
    if own is None:
        return None, "hybrid_no_session_return"
    excess = own - float(market_leg)
    if excess > -config.HYBRID_LAG_MIN_PCT:
        return None, "hybrid_not_lagging_market"

    return {
        "rule": HYBRID_VERSION,
        "symbol": symbol,
        "side": "LONG",
        "close": round(float(mean_frame["close"]), 6),
        "mean_minutes": config.HYBRID_MEAN_FRAME_MINUTES,
        "mean_vwap": mean_frame["vwap"],
        "z": round(z, 4),
        "z_min": round(config.HYBRID_Z_MIN, 4),
        "fast_minutes": config.HYBRID_FAST_FRAME_MINUTES,
        "fast_state": fast_frame.get("kalman_state"),
        "frames": {key: {"close": v["close"], "vwap": v["vwap"],
                         "kalman_state": v["kalman_state"],
                         "above_vwap": v["above_vwap"],
                         "bars": v["bars"]} for key, v in frames.items()},
        "symbol_return": round(own, 6),
        "market_return": round(float(market_leg), 6),
        "relative_strength": round(excess, 6),
        "lag_min_pct": round(config.HYBRID_LAG_MIN_PCT * 100, 4),
        "market_symbols": market.get("symbols"),
    }, "ok"


def _session_return(rows: list, session) -> float | None:
    """The name's own move over its completed bars, causally."""
    from src.signals.kalman_vwap_rs import session_return, session_open_of

    return session_return(rows, session_open_of(session), session.as_of)


def score(view: dict | None, reward_risk: float) -> float:
    """A ranking number for a reversion setup, never a probability (SO-3)."""
    if not isinstance(view, dict):
        return 0.0
    z = abs(float(view.get("z") or 0.0))
    state = ((view.get("frames") or {}).get("15m") or {}).get("kalman_state")
    return round(min(100.0, 50 + min(25.0, 10.0 * z)
                     + min(15.0, 5.0 * reward_risk)
                     + (10.0 if state == 1 else 0.0)), 2)


def summary(view: dict | None) -> str:
    """One ASCII line for the card and the owner email, or empty."""
    if not isinstance(view, dict):
        return ""
    z = view.get("z")
    vwap = view.get("mean_vwap")
    if z is None or vwap is None:
        return ""
    return (f"HYBRID {z:+.2f} sigma below the {view.get('mean_minutes')}m "
            f"VWAP {vwap}, lagging the market by "
            f"{(view.get('relative_strength') or 0.0) * 100:+.2f} pp")