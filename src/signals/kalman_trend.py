"""The causal level plus slope Kalman, kept for the research scripts only.

Owner order 2026-11-25 (Karachi) put the Kalman Trend back into the day
trading law: the running strategy is the Kalman Trend with the 5, 15 and 30
minute VWAP lines and the z-score of the price minus VWAP spread
(src/signals/kalman_zscore_vwap.py), and every live entry reads the frame
states this filter produces.

What remains here is the filter itself. ``scripts/kalman_grid_fit.py`` and
``scripts/backtest_eleven_intraday.py`` still replay it as historical
research, and ``src/signals/mtf_vwap.py`` keeps its frame state helper for the
same historical record, so the maths has one implementation and no second
copy. Nothing in this module decides a trade.

Nothing here executes, sleeps or touches a network.
"""

from __future__ import annotations

import math


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
