"""The Kalman Trend, the 5m/15m VWAP frames and the z-score spread law.

Owner order 2026-11-16 (Karachi): the running intraday strategy is the Kalman
Trend with VWAP on the 5 minute and 15 minute charts, and its mathematical
base is the z-score of the price minus VWAP spread, a statistical-arbitrage
mean-reversion measure.

Owner order 2026-11-19 (Karachi): a call must be possible in the first half
hour of every market session. The 30 minute frame is withdrawn by that order,
because two completed 30 minute bars cannot exist until more than an hour into
a session: it made the owner's time requirement arithmetically impossible.
The law now needs seven completed 5 minute bars (a 15 minute VWAP plus three
earlier spreads), so its first legal call lands thirty-five minutes after the
open, and the 15 minute frame is ready after thirty. The exact clock times
live in the tests and the docs, never as a second clock in the law.

The spread is measured, never eyeballed. For one frame, every completed bar
has a spread of its close against the rolling VWAP that was available at that
bar. The current spread is standardised against the mean and standard
deviation of the spreads that came before it. A quiet name therefore needs a
smaller absolute move than a violent one, and the result is a true z-score of
the spread rather than a z-score of the closes.

Entry law:

  * the one minute Kalman trend must be up (the caller owns that clock);
  * the 5 minute frame's Kalman state must be +1, so the fast chart has turned;
  * the 15 minute frame must have Kalman state +1 and a close above its own
    VWAP, so the slower regime still supports the trade;
  * the 5 minute price-VWAP spread must sit at least ZSCORE_Z_MIN standard
    deviations below its own trailing mean, so the entry buys a measured
    statistical dislocation inside that rising regime.

Exit and risk are the owner's unchanged paper law: entry at the latest
completed close, a fixed -1% stop and a +2% target, one call a day.

Nothing here executes, sleeps or touches a network. A missing frame, an
unmeasurable spread or a thin tape fails closed with its reason named (SO-3).
"""

from __future__ import annotations

import math
from datetime import datetime, time
from statistics import pstdev

from src import config
from src.data.sessions import current_band, open_time
from src.signals import mtf_vwap

#: This reader's own version, carried on every view it returns.
ZSCORE_VERSION = "kalman_zscore_vwap_v1"

#: The strategy label a candidate built from this law carries.
STRATEGY_VERSION = config.ZSCORE_STRATEGY_VERSION


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
    """The 5 and 15 minute frames, or the first frame that cannot vote.

    *session_rows* is the whole session's one minute tape. Both frames are
    built from it, so the afternoon still has the morning's completed bars
    and neither frame is blind after a Friday midday break.
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


def entry_view(symbol: str, rows: list, session,
               session_rows: list | None = None) -> tuple[dict | None, str]:
    """This name's z-score spread entry, or the first gate that refuses it."""
    frames, reason = frame_views(rows, session, session_rows=session_rows)
    if frames is None:
        return None, reason

    fast = frames.get("5m")
    middle = frames.get("15m")
    if fast is None:
        return None, "zscore_5m_missing"
    if middle is None:
        return None, "zscore_15m_missing"

    if fast.get("kalman_state") != 1:
        return None, "zscore_fast_frame_not_up"
    if middle.get("kalman_state") != 1:
        return None, "zscore_15m_trend_not_up"
    if not middle.get("above_vwap"):
        return None, "zscore_15m_below_vwap"

    z = fast.get("spread_z")
    if z is None:
        return None, "zscore_spread_unmeasurable"
    if z > -config.ZSCORE_Z_MIN:
        return None, "zscore_not_stretched_below_mean"

    return {
        "rule": ZSCORE_VERSION,
        "symbol": symbol,
        "side": "LONG",
        "close": round(float(middle["close"]), 6),
        "signal_minutes": config.ZSCORE_SIGNAL_FRAME_MINUTES,
        "z": round(z, 4),
        "z_min": round(config.ZSCORE_Z_MIN, 4),
        "spread": fast.get("spread"),
        "spread_mean": fast.get("spread_mean"),
        "spread_sigma": fast.get("spread_sigma"),
        "spread_samples": fast.get("spread_samples"),
        "frames": {key: {"close": v["close"], "vwap": v["vwap"],
                         "kalman_state": v["kalman_state"],
                         "above_vwap": v["above_vwap"],
                         "spread_z": v["spread_z"], "bars": v["bars"]}
                   for key, v in frames.items()},
    }, "ok"


def score(view: dict | None, reward_risk: float) -> float:
    """A ranking number for a z-score spread setup, never a probability."""
    if not isinstance(view, dict):
        return 0.0
    z = abs(float(view.get("z") or 0.0))
    frames = view.get("frames") or {}
    aligned = sum(1 for key in ("15m",)
                  if (frames.get(key) or {}).get("kalman_state") == 1)
    return round(min(100.0, 50 + min(25.0, 10.0 * z)
                     + min(15.0, 5.0 * reward_risk)
                     + 5.0 * aligned), 2)


def summary(view: dict | None) -> str:
    """One ASCII line for the card and the owner email, or empty."""
    if not isinstance(view, dict):
        return ""
    z = view.get("z")
    fast = (view.get("frames") or {}).get("5m") or {}
    vwap = fast.get("vwap")
    if z is None or vwap is None:
        return ""
    return (f"Z-SPREAD {z:+.2f} sigma versus the 5m VWAP {vwap}, "
            f"with 5m/15m Kalman aligned")
