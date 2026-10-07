"""Signal engine v1: FVG / liquidity-sweep / auction layers on daily bars.

Implements the pre-registered definitions of RESEARCH_AUDIT.md sections 5,
6 and 12, with the leakage rules of section 10:

  - every rolling window ENDS at T (no centered windows, no full-sample
    normalization anywhere);
  - regime bands come from an equal-weight KMIALL proxy computed from
    closes up to and including T only;
  - nothing here revises history: features for (symbol, T) depend on rows
    up to T only, verified by tests that truncate the frame.

The v1 live rule is pre-registered combination experiment 5 (the full
stack): regime gate x sweep_low x FVG-retrace, all three required. Other
computed features (BOS, displacement, relvol, premium/discount position,
equal lows, volume acceleration) travel with the signal as context for
later slicing; they are NOT conditions in v1.

Signal payload honesty (GOVERNANCE.md SO-1/SO-3): every signal carries the
the owner's TP and SL percentages from the next session's executable open,
with a three-session holding cap and the data caveats. The engine refuses to emit anything when
its input data is insufficient (see registry.py).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

TP_PCT = 2.0    # owner's law: TP +2.0%
SL_PCT = 1.0    # owner's law: SL -1.0%
MAX_HOLD = 3    # owner's law: 3-session holding cap

# Section 12 regime bands on the equal-weight proxy 20-day return.
REGIME_BANDS = {
    "strong_bull": 0.05,
    "weak_bull": 0.0,
    "weak_bear": -0.05,
}
REGIME_GATE_MIN = 0.0   # v1 gate: bull side only (weak_bull or strong_bull)

FVG_MAX_AGE = 1         # pre-registered: bullish FVG formed at T-1 exactly


@dataclass
class Signal:
    symbol: str
    name: str
    signal_date: str
    close: float
    entry_plan: str
    tp_pct: float
    sl_pct: float
    regime: str
    regime_ret20: float
    sweep_low: bool
    fvg_age: int
    fvg_low: float       # the gap's lower edge (high of T-3 for age 1)
    fvg_mid: float
    fvg_size_pct: float
    relvol: float
    displacement: bool
    bos_up: bool
    clv_position: float  # close position in the prior 20-bar range (0..1)
    equal_lows: bool

    def line(self) -> str:
        return (f"OBSERVE {self.symbol} @close {self.close:g} | "
                f"{self.entry_plan} | TP +{self.tp_pct:g}% from actual entry "
                f"SL -{self.sl_pct:g}% from actual entry | regime {self.regime} "
                f"({self.regime_ret20 * 100:+.1f}%/20d) | sweep_low + "
                f"FVG-retrace(age {self.fvg_age}) | relvol {self.relvol:.2f}x "
                f"| {'BOS ' if self.bos_up else ''}"
                f"{'disp ' if self.displacement else ''}"
                f"clv {self.clv_position:.2f}")

    def dict(self) -> dict:
        return asdict(self)


def kmiall_proxy(df: pd.DataFrame) -> pd.Series:
    """Equal-weight mean close per date across the universe (causal).

    The proxy is the audit's regime basis until a real index history is
    fetched (section 12). It uses only closes up to each date by
    construction: one mean per calendar date.
    """
    return df.groupby("date")["close"].mean()


def regime_of(proxy: pd.Series) -> pd.DataFrame:
    """20-day proxy return bands (section 12), labeled per date."""
    ret20 = proxy / proxy.shift(20) - 1.0
    def label(r: float) -> str:
        if not np.isfinite(r):
            return "unknown"
        if r > REGIME_BANDS["strong_bull"]:
            return "strong_bull"
        if r >= REGIME_BANDS["weak_bull"]:
            return "weak_bull"
        if r >= REGIME_BANDS["weak_bear"]:
            return "weak_bear"
        return "strong_bear"
    return pd.DataFrame({"proxy_ret20": ret20,
                         "regime": ret20.map(label)})


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol causal features at T. Windows END at T (section 10).

    df: long frame [symbol, date, open, high, low, close, volume] sorted by
    (symbol, date). Returns the same frame with feature columns attached.
    """
    df = df.sort_values(["symbol", "date"]).copy()
    g = df.groupby("symbol", sort=False)
    close, low, high, vol, opn = df["close"], df["low"], df["high"], df["volume"], df["open"]

    # --- volume layer (section 5) ---
    vol_med20 = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).median())
    df["relvol"] = vol / vol_med20
    df["vol_accel"] = vol / vol.shift(1)

    # --- price action / SMC set (section 5, operationalized) ---
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["body"] = (close - opn).abs()
    df["body_med20"] = g["body"].transform(lambda s: s.rolling(20, min_periods=20).median())
    df["displacement"] = (df["body"] >= 2.0 * df["body_med20"]) & (close > opn)

    # 20-day high break: close(T) reaches the PRIOR 20-bar high range
    # (high over T-20..T-1; never today's own high)
    prior_high20 = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    df["break20"] = close >= prior_high20

    prior_close_max20 = g["close"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    df["bos_up"] = close > prior_close_max20

    # sweep_low: the 5-bar window T-6..T-2 dips under the prior 10-bar low
    # (T-16..T-6) and close(T) recovers above that swept low.
    recent_low5 = g["low"].transform(lambda s: s.shift(2).rolling(5, min_periods=5).min())
    prior_low10 = g["low"].transform(lambda s: s.shift(6).rolling(10, min_periods=10).min())
    df["swept_low"] = prior_low10
    df["sweep_low"] = (recent_low5 < prior_low10) & (close > prior_low10)

    recent_high5 = g["high"].transform(lambda s: s.shift(2).rolling(5, min_periods=5).max())
    prior_high10 = g["high"].transform(lambda s: s.shift(6).rolling(10, min_periods=10).max())
    df["swept_high"] = prior_high10
    df["sweep_high"] = (recent_high5 > prior_high10) & (close < prior_high10)

    # premium/discount: close(T) inside the PRIOR 20-bar range (T-20..T-1)
    range_hi = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    range_lo = g["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).min())
    df["clv_position"] = (close - range_lo) / (range_hi - range_lo)

    # equal lows: two lows within 0.3% in the last 10 bars: today's low and
    # the minimum of the prior 9 bars sit within 0.3% of each other.
    prev9_min = g["low"].transform(lambda s: s.shift(1).rolling(9, min_periods=9).min())
    df["equal_lows"] = (low / prev9_min - 1.0).abs() <= 0.003

    # --- FVG (section 5): bullish gap formed at T-1: low(T-1) > high(T-3) ---
    lag1_low = g["low"].shift(1)
    lag3_high = g["high"].shift(3)
    lag1_close = g["close"].shift(1)
    df["fvg_bull_age1"] = lag1_low > lag3_high
    df["fvg_low"] = lag3_high            # gap lower edge
    df["fvg_mid"] = (lag1_low + lag3_high) / 2.0
    df["fvg_size_pct"] = (lag1_low - lag3_high) / lag1_close
    df["fvg_retrace"] = df["fvg_bull_age1"] & (low <= df["fvg_mid"])

    # --- Phase 2A research additions (causal; NOT part of the v1 live rule).
    # These columns exist so the trade matrix can carry them for the Group G
    # study. The selection rule above is untouched.
    # lower wick: the lower shadow's share of the bar's own range
    bar_range = high - low
    df["lower_wick"] = np.where(bar_range > 0,
                                (np.minimum(opn, close) - low) / bar_range,
                                np.nan)
    # range expansion: true range above 1.5x the trailing 20-bar median TR
    prev_close = g["close"].shift(1)
    tr = pd.concat([bar_range,
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    tr_med20 = tr.groupby(df["symbol"], sort=False).transform(
        lambda s: s.rolling(20, min_periods=20).median())
    df["range_expansion"] = tr > 1.5 * tr_med20
    # pullback resumption: three consecutive lower closes at T-1..T-3 while
    # close(T) still holds above its own MA20
    c1, c2, c3, c4 = (g["close"].shift(i) for i in (1, 2, 3, 4))
    three_down = (c1 < c2) & (c2 < c3) & (c3 < c4)
    df["pullback_resume"] = three_down & (close > df["ma20"])
    return df


def select_signals(df_feat: pd.DataFrame, proxy_regime: pd.DataFrame) -> list[Signal]:
    """The pre-registered v1 stack: regime gate x sweep_low x FVG-retrace."""
    df_feat = df_feat.drop(columns=["regime", "proxy_ret20"], errors="ignore")
    df_feat = df_feat.join(proxy_regime, on="date")

    gate = (
        (df_feat["proxy_ret20"] >= REGIME_GATE_MIN)
        & df_feat["sweep_low"].fillna(False)
        & df_feat["fvg_retrace"].fillna(False)
    )
    candidates = df_feat.loc[gate]
    signals: list[Signal] = []
    for row in candidates.itertuples(index=False):
        if not np.isfinite(row.close) or row.close <= 0:
            continue
        signals.append(Signal(
            symbol=row.symbol,
            name=getattr(row, "name", "") or "",
            signal_date=str(pd.Timestamp(row.date).date()),
            close=float(row.close),
            entry_plan=f"reference entry: next session open; max hold {MAX_HOLD} sessions",
            tp_pct=TP_PCT,
            sl_pct=SL_PCT,
            regime=row.regime,
            regime_ret20=float(row.proxy_ret20),
            sweep_low=bool(row.sweep_low),
            fvg_age=1,
            fvg_low=float(row.fvg_low),
            fvg_mid=float(row.fvg_mid),
            fvg_size_pct=float(row.fvg_size_pct),
            relvol=float(row.relvol) if np.isfinite(row.relvol) else float("nan"),
            displacement=bool(row.displacement),
            bos_up=bool(row.bos_up),
            clv_position=float(row.clv_position) if np.isfinite(row.clv_position) else float("nan"),
            equal_lows=bool(row.equal_lows),
        ))
    return signals


def run(df: pd.DataFrame) -> tuple[list[Signal], pd.DataFrame]:
    """Full pass: features + regime + selection. Returns (signals, frame)."""
    proxy = kmiall_proxy(df)
    regime = regime_of(proxy)
    feat = add_features(df)
    signals = select_signals(feat, regime)
    return signals, feat


def historical_signals(df: pd.DataFrame) -> list[tuple]:
    """(signal_date, symbol) pairs for EVERY session the v1 stack fired.

    Used by the sanity backtest: the same causal rule evaluated on the
    whole history. Universe membership is today's list (survivorship
    caveat, audit section 8), so results are labeled leaky.
    """
    signals, _ = run(df)
    return [(s.signal_date, s.symbol) for s in signals]

