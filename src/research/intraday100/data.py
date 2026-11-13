"""Archive loading and session-band preparation for the intraday research.

The archive stores ``ts`` as UTC epoch seconds. Karachi wall clock is UTC+5,
so the session day and the time of day are derived with a fixed offset and
the session law in :mod:`src.data.sessions`, never with the host timezone.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.sessions import KARACHI, session_bands
from src.research.intraday100 import TIMEFRAME_SECONDS

KARACHI_OFFSET_SECONDS = 5 * 3600
REQUIRED_COLUMNS = ("symbol", "ts", "open", "high", "low", "close", "volume", "regular")


def archive_files(root: str | Path, timeframe: str) -> list[Path]:
    """Every parquet partition for one timeframe, sorted by filename."""
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    base = Path(root) / timeframe
    if not base.is_dir():
        raise FileNotFoundError(f"missing archive directory: {base}")
    files = sorted(base.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files under {base}")
    return files


def load_timeframe(
    root: str | Path,
    timeframe: str,
    years: tuple[int, ...] | None = None,
) -> pd.DataFrame:
    """Load one timeframe into a symbol/time sorted frame.

    The archive is never resampled here. A strategy that needs 15m must be
    scored on the native 15m partition, not on a 5m frame resampled inside
    the runner.
    """
    files = archive_files(root, timeframe)
    frames: list[pd.DataFrame] = []
    for path in files:
        year_text = path.stem.rsplit("-", 1)[-1]
        try:
            year = int(year_text)
        except ValueError:
            year = None
        if years is not None and year not in years:
            continue
        frame = pd.read_parquet(path, columns=list(REQUIRED_COLUMNS))
        frames.append(frame)
    if not frames:
        raise FileNotFoundError(f"no {timeframe} partitions matched years={years}")

    df = pd.concat(frames, ignore_index=True)
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{timeframe} archive missing columns: {missing}")

    df["symbol"] = df["symbol"].astype(str)
    df["ts"] = df["ts"].astype("int64")
    for column in ("open", "high", "low", "close", "volume"):
        df[column] = pd.to_numeric(df[column], errors="coerce").astype("float64")
    df["regular"] = df["regular"].fillna(False).astype(bool)
    df = df.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    return df


def attach_sessions(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Attach day, band and bar-end columns without using local time."""
    if timeframe not in TIMEFRAME_SECONDS:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    seconds = TIMEFRAME_SECONDS[timeframe]
    out = df.copy()

    ts = out["ts"].to_numpy(dtype=np.int64, copy=False)
    # Karachi midnight in epoch seconds, derived with the fixed +5 offset.
    day_ord = ((ts + KARACHI_OFFSET_SECONDS) // 86400) * 86400 - KARACHI_OFFSET_SECONDS
    tod = ts - day_ord
    # Python weekday: Monday=0. 1970-01-01 was a Thursday, so add 3.
    weekday = ((day_ord + KARACHI_OFFSET_SECONDS) // 86400 + 3) % 7

    unique_days = np.unique(day_ord)
    first_open: dict[int, int] = {}
    first_close: dict[int, int] = {}
    second_open: dict[int, int] = {}
    last_close: dict[int, int] = {}
    for day in unique_days:
        date = datetime.fromtimestamp(int(day), tz=KARACHI).date()
        bands = session_bands(date)
        if not bands:
            first_open[int(day)] = -1
            first_close[int(day)] = -1
            second_open[int(day)] = -1
            last_close[int(day)] = -1
            continue
        first_open[int(day)] = bands[0][0][0] * 3600 + bands[0][0][1] * 60
        first_close[int(day)] = bands[0][1][0] * 3600 + bands[0][1][1] * 60
        second_open[int(day)] = (bands[1][0][0] * 3600 + bands[1][0][1] * 60
                                 if len(bands) > 1 else -1)
        last_close[int(day)] = (bands[-1][1][0] * 3600 + bands[-1][1][1] * 60)

    first_open_arr = np.array([first_open[int(d)] for d in day_ord], dtype=np.int64)
    first_close_arr = np.array([first_close[int(d)] for d in day_ord], dtype=np.int64)
    second_open_arr = np.array([second_open[int(d)] for d in day_ord], dtype=np.int64)
    last_close_arr = np.array([last_close[int(d)] for d in day_ord], dtype=np.int64)

    friday = weekday == 4
    in_second = friday & (second_open_arr >= 0) & (tod >= second_open_arr)
    band_id = np.where(in_second, 1, 0)
    band_open = np.where(in_second, second_open_arr, first_open_arr)
    band_close = np.where(in_second, last_close_arr, first_close_arr)

    out["day_ord"] = day_ord.astype(np.int64)
    out["tod"] = tod.astype(np.int64)
    out["weekday"] = weekday.astype(np.int8)
    out["band_id"] = band_id.astype(np.int8)
    out["band_key"] = (day_ord * 2 + band_id).astype(np.int64)
    out["band_end"] = (day_ord + band_close).astype(np.int64)
    out["bar_end"] = (ts + seconds).astype(np.int64)
    out["valid_bar"] = (
        out["regular"].to_numpy(dtype=bool)
        & (band_open >= 0)
        & (tod >= band_open)
        & (out["bar_end"].to_numpy() <= out["band_end"].to_numpy())
    )
    return out


def load_prepared(
    root: str | Path,
    timeframe: str,
    years: tuple[int, ...] | None = None,
    max_rows: int | None = None,
) -> pd.DataFrame:
    """Load and attach sessions, with an explicit smoke-run row cap."""
    df = load_timeframe(root, timeframe, years=years)
    if max_rows is not None:
        df = df.iloc[:max_rows].copy()
    df["timeframe"] = timeframe
    df = attach_sessions(df, timeframe)
    if max_rows is not None:
        # The cap is for a smoke run only. It must not silently leave one
        # symbol's bars without the rest of its session.
        df = df[df["valid_bar"]].copy()
    return df
