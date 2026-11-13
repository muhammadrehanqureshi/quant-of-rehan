"""Causal feature library for the intraday research engine.

Every feature is computed from the current bar and earlier bars only. A
rolling window is shifted by one bar whenever the feature describes a level
that must be known before the current bar's close, such as a Donchian high.
Volume and VWAP are session cumulative and reset at each Karachi session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_COLUMNS = (
    "ret1", "ret3", "ret6", "ret12",
    "ema20", "ema50", "ema_slope",
    "don_hi20", "don_lo20", "don_hi55", "don_lo55",
    "atr", "atr_pct", "rsi14",
    "vwap", "prev_vwap", "dist_vwap",
    "rel_vol", "vol_med5",
    "bb_mid", "bb_std", "bb_width", "bb_width_med",
    "zscore", "close_pos", "range_pct",
    "or_high", "or_low", "bar_in_band",
    "prior_high", "prior_low", "prev_close",
    "market_ret6", "rs6",
)


def _shift(values: np.ndarray, periods: int) -> np.ndarray:
    out = np.full(values.shape, np.nan, dtype=np.float64)
    if periods <= 0:
        return values.astype(np.float64, copy=True)
    if periods < len(values):
        out[periods:] = values[:-periods]
    return out


def _pct_change(values: np.ndarray, periods: int) -> np.ndarray:
    previous = _shift(values, periods)
    with np.errstate(divide="ignore", invalid="ignore"):
        return values / previous - 1.0


def _ema(values: np.ndarray, span: int) -> np.ndarray:
    series = pd.Series(values, dtype="float64")
    return series.ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def _rolling(values: np.ndarray, window: int, op: str, shift: int = 0) -> np.ndarray:
    series = pd.Series(values, dtype="float64")
    rolled = series.rolling(window, min_periods=window)
    if op == "max":
        result = rolled.max()
    elif op == "min":
        result = rolled.min()
    elif op == "mean":
        result = rolled.mean()
    elif op == "std":
        result = rolled.std(ddof=0)
    elif op == "median":
        result = rolled.median()
    else:
        raise ValueError(f"unsupported rolling op: {op}")
    if shift:
        result = result.shift(shift)
    return result.to_numpy()


def _rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    diff = np.diff(close, prepend=np.nan)
    gain = np.where(diff > 0, diff, 0.0)
    loss = np.where(diff < 0, -diff, 0.0)
    avg_gain = _ema(gain, period)
    avg_loss = _ema(loss, period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[avg_loss == 0] = 100.0
    rsi[(avg_gain == 0) & (avg_loss == 0)] = 50.0
    return rsi


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev_close = _shift(close, 1)
    true_range = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    return _ema(true_range, period)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with the shared feature columns attached.

    The loop is per symbol, which keeps every rolling calculation inside one
    instrument and makes accidental cross-symbol leakage impossible.
    """
    out = df.reset_index(drop=True).copy()
    n = len(out)
    arrays: dict[str, np.ndarray] = {
        name: np.full(n, np.nan, dtype=np.float32) for name in FEATURE_COLUMNS
    }

    for _symbol, g in out.groupby("symbol", sort=False, observed=True):
        idx = g.index.to_numpy()
        ts = g["ts"].to_numpy(dtype=np.int64)
        open_ = g["open"].to_numpy(dtype=np.float64)
        high = g["high"].to_numpy(dtype=np.float64)
        low = g["low"].to_numpy(dtype=np.float64)
        close = g["close"].to_numpy(dtype=np.float64)
        volume = np.nan_to_num(g["volume"].to_numpy(dtype=np.float64), nan=0.0)
        day_ord = g["day_ord"].to_numpy(dtype=np.int64)
        band_key = g["band_key"].to_numpy(dtype=np.int64)

        arrays["ret1"][idx] = _pct_change(close, 1)
        arrays["ret3"][idx] = _pct_change(close, 3)
        arrays["ret6"][idx] = _pct_change(close, 6)
        arrays["ret12"][idx] = _pct_change(close, 12)

        ema20 = _ema(close, 20)
        ema50 = _ema(close, 50)
        arrays["ema20"][idx] = ema20
        arrays["ema50"][idx] = ema50
        arrays["ema_slope"][idx] = ema20 - _shift(ema20, 3)

        arrays["don_hi20"][idx] = _rolling(high, 20, "max", shift=1)
        arrays["don_lo20"][idx] = _rolling(low, 20, "min", shift=1)
        arrays["don_hi55"][idx] = _rolling(high, 55, "max", shift=1)
        arrays["don_lo55"][idx] = _rolling(low, 55, "min", shift=1)

        atr = _atr(high, low, close, 14)
        arrays["atr"][idx] = atr
        with np.errstate(divide="ignore", invalid="ignore"):
            arrays["atr_pct"][idx] = atr / close
        arrays["rsi14"][idx] = _rsi(close, 14)

        # Session VWAP, reset at the Karachi session day, not at the band.
        vwap = np.full(len(g), np.nan, dtype=np.float64)
        for _day, positions in pd.Series(np.arange(len(g))).groupby(day_ord).indices.items():
            pos = np.asarray(positions, dtype=np.int64)
            typical = (high[pos] + low[pos] + close[pos]) / 3.0
            traded = typical * volume[pos]
            cumulative_volume = np.cumsum(volume[pos])
            with np.errstate(divide="ignore", invalid="ignore"):
                vwap[pos] = np.cumsum(traded) / cumulative_volume
            vwap[pos][cumulative_volume <= 0] = np.nan
        arrays["vwap"][idx] = vwap
        prev_vwap = np.full(len(g), np.nan, dtype=np.float64)
        same_day = np.r_[False, day_ord[1:] == day_ord[:-1]]
        prev_vwap[1:] = np.where(same_day[1:], vwap[:-1], np.nan)
        arrays["prev_vwap"][idx] = prev_vwap
        with np.errstate(divide="ignore", invalid="ignore"):
            arrays["dist_vwap"][idx] = close / vwap - 1.0

        vol_med5 = _rolling(volume, 5, "median", shift=1)
        arrays["vol_med5"][idx] = vol_med5
        with np.errstate(divide="ignore", invalid="ignore"):
            arrays["rel_vol"][idx] = volume / vol_med5

        bb_mid = _rolling(close, 20, "mean")
        bb_std = _rolling(close, 20, "std")
        with np.errstate(divide="ignore", invalid="ignore"):
            bb_width = bb_std / bb_mid
        arrays["bb_mid"][idx] = bb_mid
        arrays["bb_std"][idx] = bb_std
        arrays["bb_width"][idx] = bb_width
        arrays["bb_width_med"][idx] = _rolling(bb_width, 100, "median", shift=1)

        with np.errstate(divide="ignore", invalid="ignore"):
            zscore = (close - bb_mid) / bb_std
        arrays["zscore"][idx] = zscore
        with np.errstate(divide="ignore", invalid="ignore"):
            arrays["close_pos"][idx] = (close - low) / (high - low)
            arrays["range_pct"][idx] = (high - low) / close

        # Opening range: the first three usable bars of each band. Invalid
        # bars (pre-open, a bar crossing the close) never count towards the
        # opening range.
        valid = g["valid_bar"].to_numpy(dtype=bool)
        band_series = pd.Series(band_key)
        band_frame = pd.DataFrame({"band_key": band_key, "high": high, "low": low})
        band_frame = band_frame.loc[valid]
        heads = band_frame.groupby("band_key", sort=False).head(3)
        or_high_map = heads.groupby("band_key", sort=False)["high"].max()
        or_low_map = heads.groupby("band_key", sort=False)["low"].min()
        arrays["or_high"][idx] = band_series.map(or_high_map).to_numpy(dtype=np.float32)
        arrays["or_low"][idx] = band_series.map(or_low_map).to_numpy(dtype=np.float32)
        counts = np.full(len(g), -1, dtype=np.int16)
        valid_bands = band_series[valid]
        counts[valid] = valid_bands.groupby(valid_bands).cumcount().to_numpy(dtype=np.int16)
        arrays["bar_in_band"][idx] = counts

        daily = pd.DataFrame({"day": day_ord, "high": high, "low": low})
        daily = daily.groupby("day", sort=False).agg(
            high=("high", "max"), low=("low", "min")
        )
        daily["prior_high"] = daily["high"].shift(1)
        daily["prior_low"] = daily["low"].shift(1)
        arrays["prior_high"][idx] = pd.Series(day_ord).map(daily["prior_high"]).to_numpy()
        arrays["prior_low"][idx] = pd.Series(day_ord).map(daily["prior_low"]).to_numpy()

        arrays["prev_close"][idx] = _shift(close, 1)

    # Cross-sectional market return must be computed after every symbol has
    # its own return. It is the equal-weight mean of the current bar's 6-bar
    # return, so it contains no forward information.
    out["ret6"] = arrays["ret6"]
    out["market_ret6"] = out.groupby("ts", sort=False)["ret6"].transform("mean")
    out["rs6"] = out["ret6"] - out["market_ret6"]

    for name in FEATURE_COLUMNS:
        if name in ("market_ret6", "rs6"):
            continue
        out[name] = arrays[name].astype(np.float32)
    out["market_ret6"] = out["market_ret6"].astype(np.float32)
    out["rs6"] = out["rs6"].astype(np.float32)
    out["bar_in_band"] = out["bar_in_band"].astype(np.int16)
    return out
