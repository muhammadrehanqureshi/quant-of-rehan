"""Mean-reversion (RSI snapback) strategy for the KMIALL universe.

Sober statement (SO-3): the owner target of a 90% round-trip win rate on
intraday or 3-4 day KMIALL positions is not reachable with fixed bracket
stops on tradable data. A 90 percent win rate demands a target-to-stop
ratio of at least roughly 9:1 for a merely break-even edge after costs
(cheap wins are refuted by rare large losses at exactly that scale); a
9:1 ratio reachable on daily bars sits at the exchange's own price-band
tails, which src/backtest/engine.py correctly refuses to book as trades
(corporate-action screen). The honest objective this module optimises
instead: the HIGHEST win rate that still leaves positive net expectancy
after LEVEL_1 trading costs and capital-gains tax, with per-trade loss
capped by a real stop rather than by the exchange band.

The core signal is the short-horizon snapback (Connors-style RSI(2)
mean reversion), adapted to PSX microstructure with strict gates:

1. RSI(2) oversold extreme (Wilder smoothing, computed on the close).
2. Trend filter: close above its SMA(200) on the signal day. Oversold
   inside a downtrend is a value trap on PSX, where individual names can
   drift on thin volume for months before turning.
3. Relative-volume gate: today's volume must not collapse below 0.5x
   the trailing 5-day median that EXCLUDES today (fully causal, and it
   reads today on its own). A dead-tape downdraft at a few percent of
   normal volume is most often one stale print in a no-bid session; the
   re-entrant crowd the snapback needs is simply not there.
4. Session traded value gate (close x volume) at the same cap every
   other declared strategy uses, so reported fills are plausible fills.
5. Price floor at MIN_PRICE so tick/band behaviour stays sane.

Causality: every feature is computed from bars at or before the signal
date, and the engine enters at the open of the NEXT session, the same
entry law src/backtest/daily_strategy.py (the deployed scanner analogue)
uses. Nothing here can peek a day ahead; tests/test_backtest_mean_reversion.py
locks that with a no-future-leak fixture.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from src import config


def compute_rsi_wilder(close: pd.Series, window: int) -> pd.Series:
    """Wilder RSI on a close series; NaN for the first `window` bars."""
    if window < 1:
        raise ValueError("rsi window must be >= 1")
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window,
                        adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window,
                        adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def compute_atr_wilder(high: pd.Series, low: pd.Series,
                       close: pd.Series, window: int) -> pd.Series:
    """Wilder ATR on a session's true range; NaN for the first `window` bars."""
    if window < 1:
        raise ValueError("atr window must be >= 1")
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / window, min_periods=window,
                  adjust=False).mean()


@dataclass(frozen=True)
class MeanRevParams:
    """Every number here is a risk parameter, not decoration.

    take_profit / stop_loss / max_hold feed src/backtest/engine.run_backtest
    directly; the exit law is: take the +take_profit snapback, cap any
    single loss at -stop_loss, force out at max_hold sessions if neither
    side of the bracket touches the entry.
    """
    rsi_window: int = 2
    rsi_entry: float = 10.0
    trend_window: int = 200
    relvol_window: int = 5
    min_relvol: float = 0.5
    min_price: float = config.MIN_PRICE
    min_traded_value: float = config.MIN_SESSION_TRADED_VALUE
    take_profit: float = 0.01
    stop_loss: float = 0.03
    max_hold: int = 4

    def as_dict(self) -> dict:
        return asdict(self)

    def validate(self) -> None:
        if not 1 <= self.rsi_window <= 30:
            raise ValueError("rsi_window must be in [1, 30]")
        if not 0 < self.rsi_entry < 50:
            raise ValueError("rsi_entry must be in (0, 50)")
        if self.trend_window < 10:
            raise ValueError("trend_window must be >= 10")
        if self.relvol_window < 2:
            raise ValueError("relvol_window must be >= 2")
        if not 0 <= self.min_relvol <= 5:
            raise ValueError("min_relvol must be in [0, 5]")
        if self.min_price <= 0:
            raise ValueError("min_price must be positive")
        if self.min_traded_value <= 0:
            raise ValueError("min_traded_value must be positive")
        if not 0 < self.take_profit < 0.2:
            raise ValueError("take_profit must be a fraction in (0, 0.2)")
        if not 0 < self.stop_loss < 0.5:
            raise ValueError("stop_loss must be a fraction in (0, 0.5)")
        if not 0 < self.max_hold <= 30:
            raise ValueError("max_hold must be in (0, 30]")
        if self.stop_loss < self.take_profit:
            raise ValueError(
                "stop_loss must be at least take_profit: a fixed-bracket "
                "exit earns its high win rate when banks_a_win has a "
                "SMALLER price distance than risks_a_loss, so the "
                "break-even bar p_be = sl/(sl+tp) sits above 50%")


REQUIRED_FEATURE_COLUMNS = ("rsi", "sma_trend", "rel_volume", "traded_value")


def mean_reversion_features(
    frame: pd.DataFrame,
    params: MeanRevParams,
) -> pd.DataFrame:
    """Per-row decision features on the (symbol, date) long panel.

    frame needs columns [symbol, date, open, high, low, close, volume].
    Adds rsi, sma_trend, rel_volume (today's volume over the prior
    relvol_window median, today excluded) and traded_value.
    """
    params.validate()
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"frame missing column(s): {sorted(missing)}")

    parts: list[pd.DataFrame] = []
    for symbol, grp in frame.sort_values(
            ["symbol", "date"], kind="mergesort").groupby(
            "symbol", sort=False):
        close = grp["close"].astype(float)
        volume = grp["volume"].astype(float)
        part = grp.copy()
        part["rsi"] = compute_rsi_wilder(close, params.rsi_window).to_numpy()
        part["sma_trend"] = close.rolling(
            params.trend_window,
            min_periods=params.trend_window).mean().to_numpy()
        prior_med = (volume.rolling(params.relvol_window,
                                    min_periods=params.relvol_window)
                     .median().shift(1))
        with np.errstate(invalid="ignore", divide="ignore"):
            part["rel_volume"] = np.where(
                prior_med > 0, volume.astype(float) / prior_med, np.nan)
        part["traded_value"] = close.abs() * volume.abs()
        parts.append(part)
    return pd.concat(parts, ignore_index=True)


def gate_mask(frame_with_features: pd.DataFrame,
              params: MeanRevParams) -> pd.Series:
    """True where every mean-reversion gate holds; NaN rows are False."""
    missing = set(REQUIRED_FEATURE_COLUMNS) - set(frame_with_features.columns)
    if missing:
        raise ValueError(
            f"frame missing feature column(s): {sorted(missing)}")
    rsi = pd.to_numeric(frame_with_features["rsi"], errors="coerce")
    sma = pd.to_numeric(frame_with_features["sma_trend"], errors="coerce")
    close = pd.to_numeric(frame_with_features["close"], errors="coerce")
    relvol = pd.to_numeric(frame_with_features["rel_volume"], errors="coerce")
    traded = pd.to_numeric(frame_with_features["traded_value"], errors="coerce")
    return (
        rsi.notna() & sma.notna() & close.notna() & relvol.notna()
        & traded.notna()
        & (rsi < params.rsi_entry)
        & (close > sma)
        & (relvol >= params.min_relvol)
        & (traded >= params.min_traded_value)
        & (close >= params.min_price)
    )


def build_signals(frame: pd.DataFrame,
                  params: MeanRevParams) -> list[tuple]:
    """Engine-ready (signal_date, symbol) pairs.

    The signal is decided at the close of the signal session using only
    data at or before it; src/backtest/engine.run_backtest then enters at
    the NEXT session's open. Every NaN in a decision column vetoes the
    bar; nothing is interpolated or forward-filled (SO-3).
    """
    enriched = mean_reversion_features(frame, params)
    mask = gate_mask(enriched, params)
    hits = enriched.loc[mask, ["date", "symbol"]]
    return list(zip(hits["date"].tolist(), hits["symbol"].tolist()))
