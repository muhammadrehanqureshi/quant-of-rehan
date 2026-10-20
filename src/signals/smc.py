"""Price-action ICT/SMC hypotheses, not claims about institutional orders.

All timestamps are Asia/Karachi (UTC+5). A pivot is usable only after its
right-hand bars close. A gap requires three consecutive completed minutes;
its retracement must be a later bar. No retrospective limit fill is assumed:
the signal's entry reference is the latest completed close, not the gap low.
"""
from __future__ import annotations

import math
from datetime import timedelta
from statistics import median

from src import config
from src.data.sessions import band_bounds, current_band


def confirmed_swings(rows: list, end: int, high: bool) -> list[int]:
    """Pivots confirmed strictly before index end (including both right bars)."""
    width = config.SMC_SWING_BARS
    out = []
    for i in range(width, end - width):
        value = rows[i].high if high else rows[i].low
        neighbors = [rows[j].high if high else rows[j].low
                     for j in range(i - width, i + width + 1) if j != i]
        if all(value > v if high else value < v for v in neighbors):
            out.append(i)
    return out


def candidate(symbol: str, rows: list, session) -> dict | None:
    """Return only a fresh, confirmed bullish retest, with all evidence attached."""
    if config.is_etf_symbol(symbol) or session.as_of.tzinfo is None:
        return None
    band = current_band(session.as_of)
    if band is None:
        return None
    opens, closes = band_bounds(session.day, band)
    if session.as_of >= closes - timedelta(minutes=config.SMC_LAST_ENTRY_MINUTES):
        return None
    # Bar timestamps denote minute OPEN, not close. An in-progress minute is
    # never evidence, even when the scan runs at HH:MM:30.
    rows = [b for b in rows if opens <= b.timestamp
            and b.timestamp + timedelta(minutes=1) <= session.as_of]
    if len(rows) < config.MIN_BARS_PER_SYMBOL:
        return None
    if session.as_of - (rows[-1].timestamp + timedelta(minutes=1)) > timedelta(
            seconds=config.SMC_MAX_SIGNAL_AGE_SECONDS):
        return None
    gap_start = 0
    for i, b in enumerate(rows):
        values = (b.open, b.high, b.low, b.close)
        if (not all(math.isfinite(v) and v > 0 for v in values)
                or b.high < max(b.open, b.close) or b.low > min(b.open, b.close)
                or b.high < b.low or b.volume is None
                or not math.isfinite(b.volume) or b.volume < 0):
            return None
        # No fabricated continuity across missing prints or the Friday break.
        if i and b.timestamp - rows[i - 1].timestamp != timedelta(minutes=1):
            gap_start = i
    rows = rows[gap_start:]
    if len(rows) < config.MIN_BARS_PER_SYMBOL or rows[-1].close < config.MIN_PRICE:
        return None
    turnover = sum(b.close * b.volume for b in rows)
    if turnover < config.MIN_SESSION_TRADED_VALUE:
        return None
    n = len(rows)
    last = rows[-1]
    tick = config.SMC_TICK_SIZE
    all_lows = confirmed_swings(rows, n, high=False)
    all_highs = confirmed_swings(rows, n, high=True)
    for sweep in range(max(config.SMC_ATR_BARS + 2, n - config.SMC_SETUP_BARS), n - 3):
        lows = [i for i in all_lows if i + config.SMC_SWING_BARS < sweep]
        highs = [i for i in all_highs if i + config.SMC_SWING_BARS < sweep]
        if not lows or not highs:
            continue
        low_index, high_index = lows[-1], highs[-1]
        level, structure = rows[low_index].low, rows[high_index].high
        swept = rows[sweep]
        # The level must still be untouched when swept, not a replay of an
        # already consumed pool. The structure threshold is frozen at sweep.
        if any(b.low <= level for b in rows[low_index + 1:sweep]):
            continue
        if not (swept.low <= level - tick + 1e-9 and swept.close > level):
            continue
        for shift in range(sweep + 1, min(sweep + config.SMC_SHIFT_BARS + 1, n - 2)):
            displacement = rows[shift]
            prior = rows[shift - config.SMC_ATR_BARS:shift]
            true_ranges = [max(b.high - b.low,
                               abs(b.high - rows[shift - len(prior) + i - 1].close),
                               abs(b.low - rows[shift - len(prior) + i - 1].close))
                           for i, b in enumerate(prior)]
            atr = sum(true_ranges) / len(true_ranges)
            body = displacement.close - displacement.open
            size = displacement.high - displacement.low
            if (atr <= 0 or body < config.SMC_DISPLACEMENT_ATR * atr
                    or size <= 0 or displacement.close <= structure
                    or displacement.close < displacement.low + config.SMC_DISPLACEMENT_CLOSE_FRACTION * size):
                continue
            # A bullish order block is the last down candle preceding the
            # displacement. It is a price zone, not evidence of institutional orders.
            down = [b for b in rows[sweep:shift] if b.close < b.open]
            if not down:
                continue
            order_block = down[-1]
            gap_low, gap_high = rows[shift - 1].high, rows[shift + 1].low
            if gap_high - gap_low < max(tick, last.close * config.SMC_MIN_GAP_PCT):
                continue
            gap_known = shift + 1
            if n - 1 <= gap_known or n - 1 - gap_known > config.SMC_RETEST_BARS:
                continue
            # Only the first retest may signal. Earlier mitigation, invalidation
            # or a target already reached invalidates this setup permanently.
            if any(b.low <= gap_high for b in rows[gap_known + 1:-1]):
                continue
            stop = round(swept.low - tick, 4)
            if any(b.low <= stop for b in rows[sweep + 1:]):
                continue
            midpoint = (gap_low + gap_high) / 2
            if not (last.low <= gap_high and last.high >= gap_low
                    and last.close > midpoint and last.close > last.open
                    and last.close <= gap_high * (1 + config.SMC_MAX_CHASE_PCT)):
                continue
            entry = last.close
            target = round(entry * (1 + config.TARGET_PCT), 4)
            risk = (entry - stop) / entry
            if not config.SMC_MIN_RISK_PCT <= risk <= config.SMC_MAX_RISK_PCT:
                continue
            net_reward = config.TARGET_PCT - config.round_trip_cost()
            reward_risk = net_reward / (risk + config.round_trip_cost())
            if reward_risk < config.SMC_MIN_NET_RR:
                continue
            range_high = max(b.high for b in rows[max(0, sweep - config.SMC_DEALING_RANGE_BARS):sweep])
            range_low = min(b.low for b in rows[max(0, sweep - config.SMC_DEALING_RANGE_BARS):sweep + 1])
            equilibrium = (range_high + range_low) / 2
            if entry > equilibrium:
                continue
            overhead = [rows[i].high for i in highs if rows[i].high > entry
                        and not any(b.high >= rows[i].high for b in rows[i + 1:])]
            ceiling = min(overhead) if overhead else None
            if ceiling is None or ceiling < target + entry * config.round_trip_cost():
                continue
            if any(b.high >= target for b in rows[gap_known + 1:-1]):
                continue
            prior_volume = median(b.volume for b in prior)
            relative_volume = displacement.volume / prior_volume if prior_volume > 0 else 0
            if relative_volume < config.SMC_MIN_DISPLACEMENT_VOLUME:
                continue
            # Ranking measures setup quality, never a probability of winning.
            score = min(100.0, 50 + min(20, 10 * body / atr)
                        + min(15, 5 * relative_volume) + min(15, 5 * reward_risk))
            return {
                "symbol": symbol, "score": round(score, 2),
                "strategy": config.SCANNER_VERSION, "side": "LONG",
                "price": {"last": entry}, "stop_loss": stop, "target": target,
                "risk_pct": risk, "net_reward_risk": reward_risk,
                "setup": {
                    "liquidity_level": level, "sweep_low": swept.low,
                    "sweep_at": swept.timestamp.isoformat(),
                    "structure_level": structure,
                    "shift_at": displacement.timestamp.isoformat(),
                    "displacement_atr": body / atr,
                    "order_block_low": order_block.low,
                    "order_block_high": order_block.high,
                    "fvg_low": gap_low, "fvg_high": gap_high,
                    "fvg_known_at": (rows[gap_known].timestamp + timedelta(minutes=1)).isoformat(),
                    "retest_at": last.timestamp.isoformat(),
                    "equilibrium": equilibrium, "overhead_liquidity": ceiling,
                },
                "volume": {"relative": relative_volume,
                           "traded_value_estimate": turnover,
                           "volume_source": "captured bar volume"},
                "last_bar": last.timestamp.isoformat(), "bars": len(rows),
                "entry_basis": "latest completed retest close; paper reference, not a fill",
            }
    return None
