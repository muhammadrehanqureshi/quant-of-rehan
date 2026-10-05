"""
PSX KMIALL BOT
Classical technical-indicator layer (v3.2.0, the whitelist law).

The owner's whitelist: ATR, Price Channel, EMA, RSI, MACD, Volume,
VWAP. Of these, this layer computes RSI (with its humped position
score) and the EMA stack alignment; VWAP and volume live in the
tier-1 feature engine. ATR, Price Channel and MACD are NOT yet
implemented anywhere: the owner's doctrine is one change at a time,
so they arrive only when ordered - no speculative code.

RETIRED (v3.1.1/v3.2.0, owner's orders) and deleted from this layer:
Bollinger %B, the Lo-MacKinlay variance ratio, and the volume/price
divergence measure. Their former consumers emit schema-compatibility
columns (all NaN) in the feature builder.

All functions are pure numpy/pandas. Session-scoped windows are the
caller's responsibility (the feature builder feeds one
(trading_date, symbol) window at a time, never across the overnight
gap).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# RSI (Wilder)
# ---------------------------------------------------------------------------

def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    Wilder's RSI, series-in/series-out (last valid value = the state).

    Flat prices (zero average gain AND zero average loss) return 50.0
    - neutral is the honest read, not an error. A pure one-way rise
    with no down ticks returns 100.0.
    """
    p = pd.Series(prices, dtype=float)
    delta = p.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    out = pd.Series(np.nan, index=p.index, dtype=float)
    both = avg_gain.notna() & avg_loss.notna()

    rising = both & (avg_loss == 0) & (avg_gain > 0)
    flat = both & (avg_loss == 0) & (avg_gain == 0)
    normal = both & (avg_loss > 0)

    rs = avg_gain / avg_loss.where(avg_loss > 0)
    out[normal] = 100.0 - 100.0 / (1.0 + rs[normal])
    out[rising] = 100.0
    out[flat] = 50.0
    return out


def rsi_position_score(rsi_values: pd.Series) -> pd.Series:
    """
    Humped RSI map for the master blend: 0.85 inside the healthy
    50-65 band (up but not exhausted), linear falloff to 0 at 25 and
    at 80. Deliberately NOT monotone - a long book does not want the
    maximum RSI, it wants the pullback-in-uptrend zone. The plateau
    sits at 0.85 (not 1.0) so a mid-band stock does not out-boost the
    0.5-neutral centre the master blend's other components assume.
    """
    r = pd.Series(rsi_values, dtype=float)
    score = pd.Series(0.0, index=r.index, dtype=float)

    rising_zone = (r >= 50) & (r <= 65)
    below = (r < 50) & r.notna()
    above = (r > 65) & r.notna()

    score[rising_zone] = 0.85
    # Below the band: 0 at RSI 25, 1 at 50 - still-recovering uptrends
    # score partially rather than nothing.
    score[below] = ((r[below] - 25.0) / 25.0).clip(lower=0.0, upper=1.0)
    # Above the band: exhaustion ramp - 1.0 at 65, 0.0 at 80.
    score[above] = ((80.0 - r[above]) / 15.0).clip(lower=0.0, upper=1.0)
    return score.where(r.notna())


# ---------------------------------------------------------------------------
# EMA stack alignment
# ---------------------------------------------------------------------------

def ema_alignment_score(
    prices: pd.Series, fast: int = 9, slow: int = 20
) -> float:
    """
    Final-state stack test over the window: 1.0 if price > EMA(fast)
    > EMA(slow), 0.0 if price < EMA(fast) < EMA(slow), 0.5 otherwise.
    """
    p = pd.Series(prices, dtype=float).dropna()
    if len(p) < slow:
        return float("nan")
    ef = p.ewm(span=fast, adjust=False).mean().iloc[-1]
    es = p.ewm(span=slow, adjust=False).mean().iloc[-1]
    last = p.iloc[-1]
    if last > ef > es:
        return 1.0
    if last < ef < es:
        return 0.0
    return 0.5
