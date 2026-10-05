"""
pandas helpers shared by the dataset builder, validator and feature engine.

Kept separate from sessions.py so that module stays importable without pandas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import sessions


def add_session_columns(
    df: pd.DataFrame,
    timestamp_column: str = "timestamp",
) -> pd.DataFrame:
    """
    Add `trading_date` and `session_id` to a snapshot-shaped frame.

    Both are derived from the global timestamp axis rather than per symbol,
    because every symbol shares the same snapshot timestamps. Deriving once
    guarantees all symbols agree on where a session starts.

    trading_date
        The Pakistan-local calendar date. Pure timezone arithmetic, so it is
        correct regardless of schedule changes, holidays or Ramadan hours.
        Cumulative counters (volume, trades, value) reset on this boundary.

    session_id
        "<trading_date>#<leg>", where the leg counter increments whenever the
        gap between consecutive distinct snapshot timestamps within one trading
        date exceeds sessions.SESSION_GAP_SECONDS. This is derived from observed
        gaps rather than the published calendar, so a Friday lunch break, an
        unscheduled halt or a Ramadan timetable all split correctly without the
        schedule needing to know about them.

    Group tick-to-tick features (price_change_pct_5s) by session_id.
    Group cumulative-counter deltas (volume, trades) by trading_date.
    """
    if timestamp_column not in df.columns:
        raise KeyError(f"Frame has no {timestamp_column!r} column")

    out = df.copy()
    out[timestamp_column] = pd.to_datetime(
        out[timestamp_column], utc=True, errors="coerce"
    )

    axis = (
        out[timestamp_column]
        .dropna()
        .drop_duplicates()
        .sort_values()
        .reset_index(drop=True)
    )

    if axis.empty:
        out["trading_date"] = pd.Series(dtype="object")
        out["session_id"] = pd.Series(dtype="object")
        return out

    local = axis.dt.tz_convert(sessions.PKT)
    trading_date = local.dt.date.astype(str)

    gap = axis.diff().dt.total_seconds()
    # A new trading date always starts a new leg; within a date, a long gap does.
    new_leg = (trading_date != trading_date.shift(1)) | (
        gap > sessions.SESSION_GAP_SECONDS
    )
    # cumsum within each trading date gives 1, 2, ... for that date's legs.
    leg = new_leg.groupby(trading_date).cumsum().astype(int)

    lookup = pd.DataFrame(
        {
            timestamp_column: axis,
            "trading_date": trading_date,
            "session_id": trading_date + "#" + leg.astype(str),
        }
    )

    out = out.merge(lookup, on=timestamp_column, how="left")
    return out


def session_groupby(df: pd.DataFrame, key: str = "session_id"):
    """Per-symbol, per-session grouping for tick-to-tick features."""
    _require(df, key)
    return df.groupby(["symbol", key], sort=False, observed=True)


def day_groupby(df: pd.DataFrame):
    """Per-symbol, per-trading-day grouping for cumulative-counter deltas."""
    _require(df, "trading_date")
    return df.groupby(["symbol", "trading_date"], sort=False, observed=True)


def _require(df: pd.DataFrame, column: str) -> None:
    if column not in df.columns:
        raise KeyError(
            f"Frame has no {column!r} column. "
            "Call frames.add_session_columns() first."
        )


def safe_divide(
    numerator: pd.Series,
    denominator: pd.Series,
) -> pd.Series:
    """
    Element-wise division that yields NaN instead of inf for a zero divisor.

    Guards every ratio feature so no infinity ever reaches the dataset.
    """
    denominator = denominator.replace(0, np.nan)
    result = numerator / denominator
    return result.replace([np.inf, -np.inf], np.nan)


def coerce_bool(series: pd.Series) -> pd.Series:
    """
    Normalise a possibly object-dtype flag column to a real bool column.

    Rows for unavailable quotes previously omitted flag keys entirely, so
    DataFrame construction produced True/False/NaN object columns. Boolean
    algebra on those happens to work today but is not guaranteed to.
    """
    if series.dtype == bool:
        return series

    mapped = series.map(
        {
            True: True,
            False: False,
            "True": True,
            "False": False,
            "true": True,
            "false": False,
            1: True,
            0: False,
            1.0: True,
            0.0: False,
        }
    )
    return mapped.fillna(False).astype(bool)
