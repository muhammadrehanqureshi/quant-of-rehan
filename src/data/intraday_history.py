"""Reader for the five year PSX intraday archive.

Built by scripts/build_intraday_history.py from the SCS Trade chart datafeed
(src/data/scs_chart.py) into the gitignored data/history/ tree, one parquet
partition per timeframe per year:

    data/history/5m/5m-2024.parquet
    data/history/15m/15m-2024.parquet
    data/history/30m/30m-2024.parquet
    data/history/60m/60m-2024.parquet
    data/history/manifest-2024.json

Columns: symbol, ts (epoch seconds, UTC), open, high, low, close, volume and
`regular`, true only inside the exchange's trading bands. Karachi is
Asia/Karachi, a fixed UTC+5, so the local stamp is `ts + 5h`;
`karachi_index` builds it.

A backtest filters `regular` when it wants the trading session alone. The
archive keeps the pre-open and post-close bars, because throwing evidence
away is worse than a flag.

This reader never returns data it does not have: a missing year is a named
FileNotFoundError, not an empty frame that a strategy would silently train on
(SO-3). Prices are as traded, with no split or bonus adjustment.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_ROOT = ROOT / "data" / "history"
TIMEFRAMES = ("5m", "15m", "30m", "60m")
SCHEMA = ("symbol", "ts", "open", "high", "low", "close", "volume", "regular")
PKT_OFFSET_SECONDS = 5 * 3600


def available(timeframe: str, root: Path = ARCHIVE_ROOT) -> dict[int, Path]:
    """The years actually on disk for a timeframe, oldest first."""
    if timeframe not in TIMEFRAMES:
        raise ValueError(f"timeframe must be one of {TIMEFRAMES}, got {timeframe!r}")
    folder = Path(root) / timeframe
    if not folder.is_dir():
        return {}
    years = {}
    for path in sorted(folder.glob(f"{timeframe}-*.parquet")):
        stem = path.stem.split("-")[-1]
        if stem.isdigit():
            years[int(stem)] = path
    return dict(sorted(years.items()))


def manifest(year: int, root: Path = ARCHIVE_ROOT) -> dict:
    """The builder's own record for a year: provenance, coverage, checks."""
    path = Path(root) / f"manifest-{year}.json"
    if not path.is_file():
        raise FileNotFoundError(
            f"no archive manifest for {year} at {path}; run the intraday-history "
            f"workflow for that year first (the archive is gitignored)")
    return json.loads(path.read_text(encoding="utf-8"))


def _epoch(value: str | date | datetime | int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, date):
        moment = datetime(value.year, value.month, value.day)
    else:
        moment = datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        return int(moment.timestamp()) - PKT_OFFSET_SECONDS
    return int(moment.timestamp())


def load(timeframe: str, years: list[int] | None = None,
         symbols: list[str] | None = None, start=None, end=None,
         regular_only: bool = False, root: Path = ARCHIVE_ROOT) -> pd.DataFrame:
    """Read the archive, filtered to the window, symbols and session asked for.

    `start` and `end` are inclusive dates in Karachi time (or epoch seconds).
    Years absent from disk raise instead of being skipped: a five year study
    that silently ran on three years is the failure this reader exists to
    prevent.
    """
    on_disk = available(timeframe, root)
    if not on_disk:
        raise FileNotFoundError(
            f"no {timeframe} partitions under {Path(root) / timeframe}; run the "
            f"intraday-history workflow first (the archive is gitignored)")
    wanted = sorted(on_disk) if years is None else sorted(set(years))
    missing = [y for y in wanted if y not in on_disk]
    if missing:
        raise FileNotFoundError(
            f"{timeframe} archive has no partition for {missing}; present: "
            f"{sorted(on_disk)}")
    parts = []
    for year in wanted:
        frame = pd.read_parquet(on_disk[year])
        absent = [c for c in SCHEMA if c not in frame.columns]
        if absent:
            raise ValueError(f"{on_disk[year]} is missing columns {absent}")
        parts.append(frame)
    table = pd.concat(parts, ignore_index=True)
    if symbols:
        wanted_symbols = {s.strip().upper() for s in symbols}
        table = table[table["symbol"].astype(str).isin(wanted_symbols)]
    if start is not None:
        table = table[table["ts"] >= _epoch(start)]
    if end is not None:
        table = table[table["ts"] < _epoch(end) + 86400]
    if regular_only:
        table = table[table["regular"]]
    return table.reset_index(drop=True)


def karachi_index(frame: pd.DataFrame) -> pd.DatetimeIndex:
    """The bars' Karachi wall-clock stamps, from epoch seconds and fixed UTC+5."""
    return pd.to_datetime(frame["ts"].astype("int64") + PKT_OFFSET_SECONDS,
                          unit="s")


def sessions(frame: pd.DataFrame) -> pd.Series:
    """Bars per Karachi date, for a quick coverage look before a study."""
    stamps = karachi_index(frame)
    return stamps.dt.date.value_counts().sort_index()
