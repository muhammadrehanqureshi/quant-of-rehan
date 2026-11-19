"""The one running intraday law: the Kalman Trend, the 5m/15m/30m VWAP frames
and the z-score price-VWAP spread.

Owner order 2026-11-16 (Karachi): the previous hybrid law is removed and the
only strategy is the Kalman Trend with VWAP on the 5 minute, 15 minute and 30
minute charts, whose mathematical base is the z-score of the price minus VWAP
spread (src/signals/kalman_zscore_vwap.py). The fresh one minute flip entry,
the three frame VWAP pullback, the relative strength gate and the hybrid
statistical arbitrage/mean reversion law are withdrawn outright: their
modules and constants are gone, and nothing in this file can build an entry
from them.

What is left is the engine the law needs:

  * the causal level plus slope Kalman over the completed one minute closes,
    whose trend state is the execution clock every entry has always used;
  * every data honesty gate: the ETF refusal, the naive timestamp refusal,
    the band clock, the completed bar rule, the freshness rule, the gap
    restart, the price and turnover floors and the owner's fixed risk plan;
  * one entry: the z-score spread law, measured on the session tape alone.

The owner's TP/SL law is the whole plan: entry at the latest completed close,
stop at the owner's fixed -1% under it, target at his +2%, one call a day
(src/signals/trade_state.py). There is no second strategy, no fallback and no
hidden prior: when the z-score law has no legal entry the scanner answers no
entry, with the refusing gate named (SO-3).

Asia/Karachi, UTC+5. Signal-only: no broker orders (SO-1).
"""
from __future__ import annotations

import math
from datetime import timedelta

from src import config
from src.data.sessions import band_bounds, current_band


def _bump(tally: dict | None, key: str) -> None:
    """Count one rejection reason, when the caller wants the why."""
    if tally is not None:
        tally[key] = tally.get(key, 0) + 1


def filter_series(closes: list[float], q: float, r: float,
                  threshold: float) -> list[dict[str, float]]:
    """Run the causal level+slope Kalman over log closes.

    Returns one record per bar: the posterior level, slope, the trend state
    AFTER that bar (-1, 0, +1 with the hysteresis band) and whether the
    state's move to +1 was the fresh flip of that bar. Level and slope are
    log-price units: exp(level) is the price, exp(slope) the per-minute
    drift. No observation ahead of the bar is ever read.
    """
    level, slope = math.log(closes[0]), 0.0
    p11, p12, p22 = 1.0, 0.0, 1.0
    state = 0
    out = []
    for close in closes:
        # predict: level += slope, slope unchanged; P = F P F' + Q.
        level, slope = level + slope, slope
        p11_old, p12_old, p22_old = p11, p12, p22
        # F = [[1,1],[0,1]] pre-multiplied, plus Q = diag(0, q).
        p11 = p11_old + 2 * p12_old + p22_old
        p22 = p22_old + q
        p12 = p12_old + p22_old
        # update: one scalar observation of the level.
        innovation = math.log(close) - level
        s_den = p11 + r
        k1, k2 = p11 / s_den, p12 / s_den
        level += k1 * innovation
        slope += k2 * innovation
        p11 -= k1 * p11
        p12, p22 = p12 - k1 * p12, p22 - k2 * p12
        # hysteresis: the state only re-crosses through the threshold.
        if slope > threshold:
            new_state = 1
        elif slope < -threshold:
            new_state = -1
        else:
            new_state = state
        flip_up = new_state == 1 and state != 1
        state = new_state
        out.append({"level": level, "slope": slope, "state": state,
                    "flip_up": flip_up})
    return out


def day_gain_pct(session, symbol: str,
                 entry: float) -> tuple[float | None, str, float | None]:
    """The pick's day move, from the venue's own reference when it exists.

    Owner order 2026-11-19 (Karachi): the pick may not already be more than
    MAX_DAY_GAIN_PCT up on the day. A move measured from the session's own
    first bar would call a name that gapped up at the open flat, which is
    exactly the pick this gate exists to stop, so the tape's `close` field
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


def candidate(symbol: str, rows: list, session,
              tally: dict | None = None,
              frames: bool = False) -> dict | None:
    """Return the one legal candidate of the running law, or None.

    Same call shape the scanner and its tests always used. Every gate below is
    the data honesty the whole system shares (ETF anonymity, the band clock,
    completed bars, positive prices, a real tape volume, the price and
    turnover floors, freshness, no continuity across a gap) plus the owner's
    fixed +2% / -1% plan. The STRATEGY is the z-score spread law and only it.

    `frames` says whether this deployment reads the 5 minute, 15 minute and 30
    minute VWAP frames (src/signals/mtf_vwap.py). The law cannot be evaluated
    without them, so a deployment that is not reading them (a replay or a
    unit fixture with no higher timeframe history) has no entry at all and
    names that reason; the live pipeline passes the deployment flag.
    """
    if config.is_etf_symbol(symbol) or session.as_of.tzinfo is None:
        _bump(tally, "etf_or_naive_tz")
        return None
    # Keep the whole session for the 30 minute frame before the current
    # band's own rows are trimmed below: a Friday afternoon band must still
    # see the morning's completed bars across the exchange's midday break.
    mtf_rows = list(rows)
    band = current_band(session.as_of)
    if band is None:
        _bump(tally, "no_market_band")
        return None
    opens, closes = band_bounds(session.day, band)
    if session.as_of >= closes - timedelta(
            minutes=config.KALMAN_LAST_ENTRY_MINUTES):
        _bump(tally, "near_band_close")
        return None
    # Bar timestamps denote minute OPEN, not close. An in-progress minute is
    # never evidence, even when the scan runs at HH:MM:30.
    rows = [b for b in rows if opens <= b.timestamp
            and b.timestamp + timedelta(minutes=1) <= session.as_of]
    if len(rows) < config.MIN_BARS_PER_SYMBOL:
        _bump(tally, "bars_under_strategy_minimum")
        return None
    if session.as_of - (rows[-1].timestamp + timedelta(minutes=1)) > timedelta(
            seconds=config.KALMAN_MAX_SIGNAL_AGE_SECONDS):
        _bump(tally, "stale_print")
        return None
    gap_start = 0
    for i, b in enumerate(rows):
        values = (b.open, b.high, b.low, b.close)
        if (not all(math.isfinite(v) and v > 0 for v in values)
                or b.high < max(b.open, b.close) or b.low > min(b.open, b.close)
                or b.high < b.low or b.volume is None
                or not math.isfinite(b.volume) or b.volume < 0):
            _bump(tally, "impossible_row")
            return None
        # No fabricated continuity across missing prints or the break.
        if i and b.timestamp - rows[i - 1].timestamp != timedelta(minutes=1):
            gap_start = i
    rows = rows[gap_start:]
    if len(rows) < config.MIN_BARS_PER_SYMBOL or rows[-1].close < config.MIN_PRICE:
        _bump(tally, "too_short_after_gap_or_penny")
        return None
    turnover = sum(b.close * b.volume for b in rows)
    if turnover < config.MIN_SESSION_TRADED_VALUE:
        _bump(tally, "under_min_session_traded_value")
        return None

    # Owner order 2026-11-19 (Karachi): a pick may not already be more than
    # MAX_DAY_GAIN_PCT up on the day, and its measured buyers must be at
    # least MIN_BUY_SELL_RATIO times its measured sellers. Both read the facts
    # the tape pass measured (src/data/tape_bars.py), and a source that
    # cannot answer either question fails closed and names it: an unmeasured
    # pick is exactly what these two gates exist to stop (SO-3).
    day_gain, gain_basis, reference = day_gain_pct(session, symbol, rows[-1].close)
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

    closes_series = [b.close for b in rows]
    trace = filter_series(closes_series, config.KALMAN_Q,
                          config.KALMAN_R, config.KALMAN_FLIP_THRESHOLD)
    last = rows[-1]
    entry = last.close
    # The owner's fixed -1% stop under the entry, the same number for every
    # name, and the +2% target measured from that same entry (owner answer
    # 2026-10-30: 2% TP / -1% SL, one call a day).
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

    # The one entry law. The frames are required: a replay or a unit fixture
    # with no higher timeframe history fails closed with its reason named
    # rather than running a law it cannot evaluate (SO-3).
    if not config.ZSCORE_ENABLED:
        _bump(tally, "zscore_law_disabled")
        return None
    if not (config.MTF_ENABLED and frames):
        _bump(tally, "zscore_frames_not_read")
        return None
    if trace[-1]["state"] != 1:
        _bump(tally, "zscore_trend_not_up")
        return None

    from src.signals import kalman_zscore_vwap as zscore

    setup, reason = zscore.entry_view(symbol, rows, session,
                                      session_rows=mtf_rows)
    if setup is None:
        _bump(tally, reason)
        return None

    return {
        "symbol": symbol,
        "score": zscore.score(setup, reward_risk),
        "strategy": zscore.STRATEGY_VERSION, "side": "LONG",
        "price": {"last": entry}, "stop_loss": stop, "target": target,
        "risk_pct": risk, "net_reward_risk": reward_risk,
        "setup": {
            "zscore": setup,
            "entry_path": "zscore_spread",
            "slope_per_minute_log": trace[-1]["slope"],
            "hysteresis_log_per_minute": config.KALMAN_FLIP_THRESHOLD,
            "process_noise_q": config.KALMAN_Q,
            "observation_noise_r": config.KALMAN_R,
            "mtf": {"rule": "vwap_mtf_v4", "frames": setup.get("frames")},
        },
        "volume": {"traded_value_estimate": turnover,
                   "volume_source": "captured bar volume"},
        "day": {"gain_pct": round(day_gain * 100.0, 3),
                "basis": gain_basis, "previous_close": reference},
        "flow": {"buy_volume": int(buy), "sell_volume": int(sell),
                 "buy_sell_ratio": round(buy / sell, 3) if sell else None},
        "last_bar": last.timestamp.isoformat(), "bars": len(rows),
        "entry_basis": "latest completed close after the 5 minute price-VWAP "
                       "spread fell by the configured z score below its own "
                       "trailing mean, with 5m, 15m and 30m Kalman states up "
                       "and the slower frames above VWAP, inside a day move of "
                       "at most 2% and a measured buy/sell split of at least "
                       "2:1; paper reference, not a fill",
    }
