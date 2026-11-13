"""Ten pre-registered pilot architectures, one or two per research family.

The pilot is deliberately small. It validates the data path, the causal
execution law, the cost model and the runtime before the full catalog is
allowed to spend cloud minutes. The full 100 catalog will reuse the same
engine and the same exit-rule contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from src.research.intraday100.engine import ExitRule


@dataclass(frozen=True)
class PilotStrategy:
    strategy_id: str
    name: str
    family: str
    hypothesis: str
    timeframe: str
    mask: Callable[[pd.DataFrame], pd.Series]
    score: Callable[[pd.DataFrame], pd.Series]
    rule: ExitRule
    weaknesses: str


def _pilot_strategies() -> list[PilotStrategy]:
    return [
        PilotStrategy(
            strategy_id="P01",
            name="EMA trend with Donchian breakout",
            family="A trend following",
            hypothesis=(
                "A stock already in a rising medium-term state that closes above "
                "its prior 20-bar high is more likely to continue than to revert."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["ema20"] > d["ema50"])
                & (d["ema_slope"] > 0)
                & (d["close"] > d["don_hi20"])
                & d["atr_pct"].between(0.002, 0.030)
                & (d["rsi14"] < 75)
                & (d["rel_vol"] > 1.2)
            ),
            score=lambda d: d["rs6"],
            rule=ExitRule(target_atr=1.8, stop_atr=1.0, max_hold_bars=12),
            weaknesses="Late entries after a fast breakout; whipsaw in a flat market.",
        ),
        PilotStrategy(
            strategy_id="P02",
            name="Opening range breakout",
            family="F market structure",
            hypothesis=(
                "The first three bars establish a reference range; a close above "
                "that range with above-normal volume attracts continuation buying."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["bar_in_band"] >= 3)
                & (d["close"] > d["or_high"])
                & (d["close"] > d["vwap"])
                & (d["rel_vol"] > 1.5)
                & (d["atr_pct"] > 0.002)
                & (d["rsi14"] < 80)
            ),
            score=lambda d: d["rel_vol"],
            rule=ExitRule(target_atr=2.0, stop_atr=1.0, max_hold_bars=9),
            weaknesses="Opening ranges are noisy on gap days and low-liquidity names.",
        ),
        PilotStrategy(
            strategy_id="P03",
            name="VWAP z-score reversion",
            family="C mean reversion",
            hypothesis=(
                "An intraday dislocation far below the session VWAP in a stock "
                "above its slower average tends to snap back toward VWAP."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["zscore"] < -2.0)
                & (d["close"] > d["ema50"])
                & (d["rsi14"] < 35)
                & (d["rel_vol"] > 1.0)
                & (d["close"] > d["prior_low"])
            ),
            score=lambda d: -d["zscore"],
            rule=ExitRule(target_atr=1.0, stop_atr=0.8, max_hold_bars=6),
            weaknesses="Catches falling knives when the trend has actually changed.",
        ),
        PilotStrategy(
            strategy_id="P04",
            name="VWAP reclaim with volume",
            family="D volume and liquidity",
            hypothesis=(
                "A close back above VWAP after trading below it, confirmed by "
                "volume expansion, marks a change in intraday control."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["close"] > d["vwap"])
                & (d["prev_close"] <= d["prev_vwap"])
                & (d["rel_vol"] > 1.5)
                & (d["ema20"] > d["ema50"])
                & (d["atr_pct"] > 0.001)
            ),
            score=lambda d: d["rel_vol"],
            rule=ExitRule(target_atr=1.5, stop_atr=1.0, max_hold_bars=9),
            weaknesses="False reclaims in a declining stock; VWAP is an estimate.",
        ),
        PilotStrategy(
            strategy_id="P05",
            name="Volatility squeeze breakout",
            family="E volatility",
            hypothesis=(
                "When the recent Bollinger width is compressed, a close through "
                "the prior Donchian high releases stored volatility."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["bb_width"] < d["bb_width_med"])
                & (d["close"] > d["don_hi20"])
                & (d["atr_pct"] < 0.020)
                & (d["rel_vol"] > 1.2)
                & (d["rsi14"] < 75)
            ),
            score=lambda d: d["rel_vol"],
            rule=ExitRule(target_atr=2.0, stop_atr=0.9, max_hold_bars=12),
            weaknesses="Squeeze definitions are unstable across liquidity buckets.",
        ),
        PilotStrategy(
            strategy_id="P06",
            name="Prior session high reclaim",
            family="F market structure",
            hypothesis=(
                "A close above the previous session's high is a visible "
                "participation level; holding above it invites continuation."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["close"] > d["prior_high"])
                & (d["close"] > d["vwap"])
                & (d["rel_vol"] > 1.2)
                & (d["ema20"] > d["ema50"])
                & (d["atr_pct"] > 0.001)
            ),
            score=lambda d: d["rs6"],
            rule=ExitRule(target_atr=1.5, stop_atr=1.0, max_hold_bars=12),
            weaknesses="Prior highs are widely watched and can be false breakouts.",
        ),
        PilotStrategy(
            strategy_id="P07",
            name="Trend-filtered residual reversion",
            family="G statistical",
            hypothesis=(
                "A negative residual against a rising slower trend is a "
                "short-horizon liquidity concession rather than a new trend."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["zscore"] < -1.5)
                & (d["ema_slope"] > 0)
                & (d["rsi14"] < 45)
                & (d["rel_vol"] > 1.2)
                & (d["close"] < d["vwap"])
            ),
            score=lambda d: -d["zscore"],
            rule=ExitRule(target_atr=1.0, stop_atr=0.7, max_hold_bars=6),
            weaknesses="Residual is not a true cointegration residual; regime breaks hurt.",
        ),
        PilotStrategy(
            strategy_id="P08",
            name="Positive statistical momentum",
            family="B momentum",
            hypothesis=(
                "A positive standardized price deviation inside an aligned "
                "uptrend reflects persistent demand rather than overextension."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["close"] > d["ema20"])
                & (d["ema20"] > d["ema50"])
                & (d["zscore"] > 0.5)
                & (d["rsi14"].between(50, 75))
                & (d["rel_vol"] > 1.2)
                & (d["atr_pct"] > 0.001)
            ),
            score=lambda d: d["rs6"],
            rule=ExitRule(target_atr=1.5, stop_atr=1.0, max_hold_bars=8),
            weaknesses="Momentum crashes; the standardized score can stay high too long.",
        ),
        PilotStrategy(
            strategy_id="P09",
            name="Trend, volume and volatility agreement",
            family="I hybrid",
            hypothesis=(
                "A breakout is more reliable when trend alignment, unusual "
                "volume and a moderate volatility state agree."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["ema20"] > d["ema50"])
                & (d["close"] > d["don_hi20"])
                & (d["rel_vol"] > 2.0)
                & d["atr_pct"].between(0.002, 0.025)
                & (d["rsi14"] < 80)
            ),
            score=lambda d: d["rel_vol"] * d["rs6"].clip(-0.05, 0.05),
            rule=ExitRule(target_atr=2.0, stop_atr=1.0, max_hold_bars=12),
            weaknesses="Rare signal, so the sample may be thin on illiquid names.",
        ),
        PilotStrategy(
            strategy_id="P10",
            name="Reversion inside a positive regime",
            family="I hybrid",
            hypothesis=(
                "Mean reversion works better when the slower regime is positive; "
                "the trade is a pullback, not a reversal."
            ),
            timeframe="5m",
            mask=lambda d: (
                (d["zscore"] < -1.5)
                & (d["ema_slope"] > 0)
                & (d["rsi14"] < 40)
                & (d["rel_vol"] > 1.2)
                & (d["close"] > d["vwap"] * 0.99)
            ),
            score=lambda d: -d["zscore"],
            rule=ExitRule(target_atr=1.0, stop_atr=0.8, max_hold_bars=6),
            weaknesses="The VWAP tolerance is a parameter choice, not a law.",
        ),
    ]


PILOT_STRATEGIES = _pilot_strategies()
