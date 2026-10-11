"""Daily-bar reconstruction of the live momentum scanner, plus its forward paths.

The deployed scanner (``src/signals/momentum_scanner.py``) scores 1-minute bars.
This module rebuilds the SAME five weighted component families from DAILY bars,
so the weight vector, the saturating half-credit scales and the entry
thresholds in ``src/config.py`` can be searched across five years of history.

Reproduced as daily analogues
-----------------------------
===============  ==========================================================
momentum         fast return over ``momentum_window`` sessions
acceleration     change in that fast return over the same lookback
relative_volume  volume / trailing ``volume_window`` median
volume_accel     volume / prior session volume
liquidity        traded value, ``close x volume``
===============  ==========================================================

Declared unavailable, never faked
---------------------------------
Everything the live scanner reads from 1-minute bars: distance from the session
high, intraday bar count, intraday range expansion, and the 20 minute warmup.
A daily analogue of those would be a *different quantity*, so the gate below
simply does not use them. Any result from this module is therefore an
indicative daily-bar study of the same component families, not a replication of
the intraday engine.

Causality
---------
Every rolling window ends at and includes bar T, and a signal is decided at the
close of T for an entry at the open of T+1 (``build_path_matrix``). There is no
``shift(-n)`` anywhere in this file, and ``tests/test_backtest_optimize.py``
freezes that by rewriting future bars and asserting past scores do not move.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from src import config

#: Component order used by config.SCORE_WEIGHTS.
COMPONENTS: tuple[str, ...] = (
    "momentum", "acceleration", "relative_volume", "volume_acceleration",
    "liquidity")

FEATURE_COLUMNS: tuple[str, ...] = (
    "momentum_fast", "momentum_accel", "relative_volume", "volume_accel",
    "traded_value")


@dataclass(frozen=True)
class ScannerParams:
    """One point in the entry-rule search space.

    `weights` must cover every name in COMPONENTS; it is normalised to sum to
    1.0 so the resulting score always spans 0..100 regardless of the raw
    vector a search step produced.
    """

    weights: dict[str, float]
    momentum_window: int = config.MOMENTUM_WINDOWS[0]
    volume_window: int = config.VOLUME_WINDOW
    min_score: float = config.MIN_SIGNAL_SCORE
    min_relvol: float = config.MIN_RELATIVE_VOLUME
    min_traded_value: float = config.MIN_SESSION_TRADED_VALUE
    min_price: float = config.MIN_PRICE
    max_extension: float = config.MAX_SESSION_EXTENSION

    def normalised_weights(self) -> dict[str, float]:
        total = float(sum(self.weights.values()))
        if total <= 0:
            raise ValueError("weights must sum to a positive number")
        return {k: float(v) / total for k, v in self.weights.items()}

    def as_dict(self) -> dict:
        return {
            "weights": {k: round(float(v), 6)
                        for k, v in self.normalised_weights().items()},
            "momentum_window": self.momentum_window,
            "volume_window": self.volume_window,
            "min_score": self.min_score,
            "min_relvol": self.min_relvol,
            "min_traded_value": self.min_traded_value,
            "min_price": self.min_price,
            "max_extension": self.max_extension,
        }


def half_credit(value: float | np.ndarray, half: float) -> float | np.ndarray:
    """Saturating score in [0, 1) that earns exactly 0.5 at ``value == half``.

    ``f(x) = x / (x + half)`` for ``x > 0``, else 0. Negative inputs earn
    nothing: a falling price is not partial credit for momentum.
    """
    if half <= 0:
        raise ValueError("half-credit scale must be positive")
    x = np.clip(np.asarray(value, dtype="float64"), 0.0, None)
    return x / (x + float(half))


def add_features(
    frame: pd.DataFrame,
    *,
    momentum_window: int = config.MOMENTUM_WINDOWS[0],
    volume_window: int = config.VOLUME_WINDOW,
) -> pd.DataFrame:
    """Append the five causal features to a cleaned (symbol, date) frame.

    A new frame is returned; the input is not modified. Rows without enough
    history carry NaN, which the gate then refuses.
    """
    needed = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = needed - set(frame.columns)
    if missing:
        raise ValueError(f"frame is missing column(s): {sorted(missing)}")
    if momentum_window < 1 or volume_window < 1:
        raise ValueError("windows must be >= 1")

    out = frame.sort_values(["symbol", "date"], kind="mergesort")
    out = out.reset_index(drop=True)
    grouped = out.groupby("symbol", observed=True)

    # pandas 3 rejects a grouped rolling inside Series.transform (it tries to
    # build a 2-D frame from the window result). Compute the groupby-rolling
    # and re-index it onto the frame's own row index instead of relying on
    # whatever order the grouped result happens to be emitted in.
    trailing_median = (
        grouped["volume"]
        .rolling(volume_window, min_periods=volume_window)
        .median()
        .reset_index(level=0, drop=True)
        .reindex(out.index)
    )

    out["momentum_fast"] = grouped["close"].pct_change(
        momentum_window, fill_method=None)
    # Acceleration is the change in the fast read over the same lookback:
    # momentum_fast(T) - momentum_fast(T - momentum_window).
    out["momentum_accel"] = out.groupby(
        "symbol", observed=True)["momentum_fast"].diff(momentum_window)
    out["relative_volume"] = out["volume"] / trailing_median
    out["volume_accel"] = out["volume"] / grouped["volume"].shift(1)
    out["traded_value"] = out["close"].astype("float64") * out["volume"].astype("float64")
    # Prior close, used only for the extension screen (known at T).
    out["prior_close"] = grouped["close"].shift(1)
    return out


def score_frame(frame: pd.DataFrame, params: ScannerParams) -> pd.Series:
    """Weighted 0..100 score from the five saturating components."""
    weights = params.normalised_weights()
    unknown = set(weights) - set(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown weight key(s): {sorted(unknown)}")

    total = pd.Series(0.0, index=frame.index)
    for name in COMPONENTS:
        weight = float(weights.get(name, 0.0))
        if weight == 0.0:
            continue
        if name == "momentum":
            raw, half = frame["momentum_fast"], config.HALF_CREDIT_MOMENTUM_FAST
        elif name == "acceleration":
            raw, half = frame["momentum_accel"], config.HALF_CREDIT_ACCELERATION
        elif name == "relative_volume":
            # Scored on the EXCESS over 1.0, so an average session earns 0.
            raw = frame["relative_volume"] - 1.0
            half = config.HALF_CREDIT_REL_VOLUME
        elif name == "volume_acceleration":
            raw = frame["volume_accel"] - 1.0
            half = config.HALF_CREDIT_VOLUME_ACCEL
        else:
            raw, half = frame["traded_value"], config.HALF_CREDIT_TRADED_VALUE
        total = total + weight * np.asarray(half_credit(raw.to_numpy(), half),
                                            dtype="float64")
    return pd.Series(total * 100.0, index=frame.index)


def apply_gate(frame: pd.DataFrame, params: ScannerParams,
               score: pd.Series) -> pd.Series:
    """Boolean mask of the bars that would be taken as signals at close T."""
    extension = frame["close"] / frame["prior_close"] - 1.0
    return (
        (score >= params.min_score)
        & (frame["relative_volume"] >= params.min_relvol)
        & (frame["traded_value"] >= params.min_traded_value)
        & (frame["close"] >= params.min_price)
        & (extension <= params.max_extension)
        & frame["momentum_fast"].notna()
        & frame["momentum_accel"].notna()
        & frame["relative_volume"].notna()
        & frame["volume_accel"].notna()
        & frame["prior_close"].notna()
    )


def build_signals(frame: pd.DataFrame,
                  params: ScannerParams) -> tuple[pd.DataFrame, pd.Series]:
    """Return ``(scored_frame, signal_mask)`` for one parameter point."""
    scored = add_features(frame, momentum_window=params.momentum_window,
                          volume_window=params.volume_window)
    score = score_frame(scored, params)
    scored["score"] = score
    return scored, apply_gate(scored, params, score)


def build_path_matrix(scored: pd.DataFrame, signal_mask: pd.Series,
                      horizon: int) -> tuple[pd.DataFrame, int]:
    """Forward OHLC paths for every signal, entry at the NEXT bar's open.

    Returns ``(paths, n_skipped)`` where each row is one signal and each column
    is ``o{i}/h{i}/l{i}/c{i}`` for the i-th bar after the signal bar (i starts
    at 1). A signal whose symbol runs out of bars before ``horizon`` keeps
    whatever bars exist and leaves the rest NaN -- the evaluator treats a
    missing bar as absent rather than inventing a price. A signal with no
    forward bar at all is skipped and counted, because its entry price does not
    exist yet and booking one would be look-ahead.
    """
    if horizon < 1:
        raise ValueError("horizon must be >= 1")

    frame = scored.sort_values(["symbol", "date"], kind="mergesort").reset_index(drop=True)
    positions = frame.groupby("symbol", observed=True).cumcount().to_numpy()
    sizes = frame.groupby("symbol", observed=True)["date"].transform("size").to_numpy()
    rows = np.arange(len(frame))
    raw_mask = signal_mask.reindex(frame.index).fillna(False).to_numpy(dtype=bool)

    has_next = raw_mask & ((positions + 1) < sizes)
    n_skipped = int(raw_mask.sum() - has_next.sum())
    signal_rows = rows[has_next]
    if len(signal_rows) == 0:
        empty = pd.DataFrame(columns=["symbol", "signal_date", "score", "entry"])
        return empty, n_skipped

    out: dict[str, np.ndarray] = {
        "symbol": frame["symbol"].to_numpy()[signal_rows],
        "signal_date": frame["date"].to_numpy()[signal_rows],
        "score": frame["score"].to_numpy(dtype="float64")[signal_rows],
        "prior_close": frame["prior_close"].to_numpy(dtype="float64")[signal_rows],
    }
    # Session ordinal per date, so the evaluator can build a CHRONOLOGICAL
    # equity curve. Without it the drawdown would chain losses in symbol order
    # and misstate the peak-to-trough figure (the engine's own warning).
    ordinals = {d: i for i, d in enumerate(sorted(set(frame["date"].tolist())))}
    date_ord = frame["date"].map(ordinals).to_numpy(dtype="int64")
    out["signal_ord"] = date_ord[signal_rows]
    for name in ("open", "high", "low", "close"):
        values = frame[name].to_numpy(dtype="float64")
        for step in range(1, horizon + 1):
            in_range = (positions[signal_rows] + step) < sizes[signal_rows]
            target = np.where(in_range, signal_rows + step, -1)
            column = np.full(len(signal_rows), np.nan)
            column[in_range] = values[target[in_range]]
            out[f"{name[0]}{step}"] = column
            if name == "close":
                # The exit session ordinal: close shares the bar with the date.
                ord_column = np.full(len(signal_rows), -1, dtype="int64")
                ord_column[in_range] = date_ord[target[in_range]]
                out[f"ord{step}"] = ord_column

    paths = pd.DataFrame(out)
    paths["entry"] = paths["o1"]
    # Drop signals whose entry bar is unusable; the engine does the same.
    usable = paths["entry"].notna() & np.isfinite(paths["entry"]) & (paths["entry"] > 0)
    n_skipped += int((~usable).sum())
    return paths.loc[usable].reset_index(drop=True), n_skipped
