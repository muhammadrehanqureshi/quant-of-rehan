"""Robust local ingestion for the 5-year PSX EOD dataset.

SO-4: backtesting runs on the owner's PC and nowhere else. Nothing in this
module opens a socket -- it reads one local file and returns a cleaned frame
plus a report that accounts for every row it dropped or repaired, and why.

The dataset is a long frame with columns ``[date, symbol, open, high, low,
close, volume]``; any extra column is ignored. Cleaned output is sorted by
``(symbol, date)`` and restricted to the KMIALL universe, because the strategy
trades KMIALL only (``config.KMIALL_ONLY``).

What the file actually contains (measured 2026-10-10 on the shipped dataset)
--------------------------------------------------------------------------
The raw file holds 4,545 symbols, but only 319 are KMIALL: the rest are other
boards and delisted names, and they are removed FIRST so the quality counters
below describe the universe that is actually traded rather than the whole file.

Inside KMIALL, three real defects appear, and they are not the same defect:

``zero_volume``        1,635 rows print ``open=high=low=volume=0`` with a
                       carried-forward ``close``. These are untraded sessions
                       (halts, suspensions), not corrupt data. Dropped.
``missing_open``       1,791 rows print ``open=0`` while high/low/close are
                       valid AND volume is non-zero. The stock genuinely
                       traded, so the open cell is defective. Dropped, because
                       a bar whose open is unknown cannot be entered at.
``ragged_envelope``    ~8,400 rows have ``high`` below ``max(open, close)`` or
                       ``low`` above ``min(open, close)``. These are REPAIRED
                       rather than dropped, by widening to
                       ``high = max(open, high, close)`` and
                       ``low = min(open, low, close)``. Widening is the
                       conservative direction: a wider envelope can only add
                       stop-outs, and the engine resolves a same-bar TP+SL in
                       favour of the stop. Dropping 3% of the history would
                       throw away more than the defect costs.

Every drop and every repair is a NAMED counter on ``IngestionReport``, so an
ingestion surprise shows up in the report instead of quietly shrinking the
sample.

Usage::

    from src.backtest.dataset import load_eod_history
    frame, report = load_eod_history("data/eod_history.csv.gz")
    print(report.as_dict())
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

#: Columns the strategy needs. Anything else in the file is ignored.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "date", "symbol", "open", "high", "low", "close", "volume")

PRICE_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close")
NUMERIC_COLUMNS: tuple[str, ...] = PRICE_COLUMNS + ("volume",)

DEFAULT_DATASET = "data/eod_history.csv.gz"
DEFAULT_UNIVERSE = "src/data/universe_kmiall.json"
DEFAULT_MIN_BARS = 20


@dataclass
class IngestionReport:
    """Every row in, every row out, a counter per drop reason, a repair count."""

    source: str = ""
    universe_source: str = ""
    rows_in: int = 0
    rows_out: int = 0
    symbols_in: int = 0
    symbols_out: int = 0
    sessions: int = 0
    first_date: str | None = None
    last_date: str | None = None
    min_bars_per_symbol: int = DEFAULT_MIN_BARS
    dropped_missing_date: int = 0
    dropped_bad_date: int = 0
    dropped_null_value: int = 0
    dropped_untraded_bar: int = 0
    dropped_nonpositive_price: int = 0
    dropped_duplicate: int = 0
    dropped_outside_universe: int = 0
    dropped_short_history: int = 0
    repaired_ragged_envelope: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def dropped_total(self) -> int:
        return self.rows_in - self.rows_out

    @property
    def retention(self) -> float:
        """Share of input rows that survived cleaning (1.0 when input was empty)."""
        return 1.0 if self.rows_in == 0 else self.rows_out / self.rows_in

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["dropped_total"] = self.dropped_total
        payload["retention"] = round(self.retention, 6)
        return payload


def load_universe(path: str | Path = DEFAULT_UNIVERSE) -> set[str]:
    """KMIALL member symbols.

    The file is a list of objects with a ``symbol`` key (the shape the universe
    refresh writes). A bare list of strings is also accepted.
    """
    resolved = Path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"universe file not found: {resolved}")
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"universe file must contain a list, got {type(raw).__name__}")
    symbols: set[str] = set()
    for entry in raw:
        if isinstance(entry, str):
            symbols.add(entry.strip().upper())
        elif isinstance(entry, dict) and "symbol" in entry:
            symbols.add(str(entry["symbol"]).strip().upper())
        else:
            raise ValueError(f"unusable universe entry: {entry!r}")
    symbols.discard("")
    if not symbols:
        raise ValueError(f"universe file {resolved} contained no symbols")
    return symbols


def load_eod_history(
    path: str | Path = DEFAULT_DATASET,
    *,
    universe_path: str | Path | None = DEFAULT_UNIVERSE,
    min_bars: int = DEFAULT_MIN_BARS,
) -> tuple[pd.DataFrame, IngestionReport]:
    """Read, validate, clean and repair the local EOD dataset.

    Returns ``(frame, report)``. The frame is sorted by ``(symbol, date)`` with
    a datetime ``date`` column and float prices. ``universe_path=None`` skips
    the KMIALL filter (useful for tests and for ad-hoc corpora).

    Raises:
        FileNotFoundError: the dataset is missing.
        ValueError: the file lacks required columns, or the universe is empty.
    """
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"dataset not found: {source}")

    report = IngestionReport(source=str(source),
                             min_bars_per_symbol=int(min_bars))
    frame = pd.read_csv(source)

    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(
            f"{source} is missing required column(s): {', '.join(missing)}; "
            f"found: {', '.join(map(str, frame.columns))}")
    frame = frame.loc[:, list(REQUIRED_COLUMNS)].copy()
    report.rows_in = int(len(frame))
    if frame.empty:
        report.notes.append("dataset contained no rows")
        return frame, report

    frame["symbol"] = frame["symbol"].astype("string").str.strip().str.upper()
    report.symbols_in = int(frame["symbol"].nunique())

    # --- universe FIRST ----------------------------------------------------
    # The file carries every board; filtering here means every quality counter
    # below describes the universe actually traded, and it makes the rest of
    # the cleaning an order of magnitude cheaper.
    if universe_path is None:
        report.universe_source = "(none: whole file)"
    else:
        symbols = load_universe(universe_path)
        report.universe_source = str(universe_path)
        inside = frame["symbol"].isin(symbols)
        report.dropped_outside_universe = int((~inside).sum())
        frame = frame.loc[inside]
        if frame.empty:
            report.notes.append("no row belonged to the universe")
            return frame, report

    # --- dates -------------------------------------------------------------
    raw_dates = pd.to_datetime(frame["date"], errors="coerce")
    tz = getattr(raw_dates.dt, "tz", None)
    if tz is not None:
        raw_dates = raw_dates.dt.tz_localize(None)
    unparsed = raw_dates.isna()
    as_text = frame["date"].astype("string").str.strip()
    blank = frame["date"].isna() | (as_text == "")
    # A present-but-unparseable date is a different defect from an empty cell.
    report.dropped_bad_date = int((unparsed & ~blank).sum())
    report.dropped_missing_date = int((unparsed & blank).sum())
    frame["date"] = raw_dates
    frame = frame.loc[~unparsed]
    if frame.empty:
        report.notes.append("every surviving row had an unusable date")
        return frame, report

    # --- numeric coercion --------------------------------------------------
    for column in NUMERIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    null_mask = frame[list(NUMERIC_COLUMNS)].isna().any(axis=1)
    # inf survives to_numeric and poisons every downstream ratio.
    for column in NUMERIC_COLUMNS:
        null_mask |= ~frame[column].map(math.isfinite)
    report.dropped_null_value = int(null_mask.sum())
    frame = frame.loc[~null_mask]

    # --- untraded sessions -------------------------------------------------
    # Volume is the arbiter: no volume means no tradable bar, whatever the
    # price columns carry forward.
    untraded = frame["volume"] <= 0
    report.dropped_untraded_bar = int(untraded.sum())
    frame = frame.loc[~untraded]

    # --- defective price cells --------------------------------------------
    bad_price = (frame[list(PRICE_COLUMNS)] <= 0).any(axis=1)
    report.dropped_nonpositive_price = int(bad_price.sum())
    frame = frame.loc[~bad_price]
    if frame.empty:
        report.notes.append("no tradable bar survived the price screens")
        return frame, report

    # --- duplicates --------------------------------------------------------
    n_before = len(frame)
    frame = frame.drop_duplicates(subset=["symbol", "date"], keep="first")
    report.dropped_duplicate = int(n_before - len(frame))

    # --- ragged envelope: repair, do not drop ------------------------------
    high = frame[["open", "high", "close"]].max(axis=1)
    low = frame[["open", "low", "close"]].min(axis=1)
    ragged = (frame["high"] != high) | (frame["low"] != low)
    report.repaired_ragged_envelope = int(ragged.sum())
    if report.repaired_ragged_envelope:
        frame["high"] = high
        frame["low"] = low
        report.notes.append(
            f"widened {report.repaired_ragged_envelope} ragged bar(s) to their "
            f"open/close envelope (conservative: only adds stop-outs)")

    # --- per-symbol history length ----------------------------------------
    counts = frame.groupby("symbol", observed=True)["date"].transform("size")
    short = counts < int(min_bars)
    report.dropped_short_history = int(short.sum())
    frame = frame.loc[~short]

    if frame.empty:
        report.notes.append("every row was filtered out; nothing to backtest")
        report.rows_out = 0
        return frame, report

    frame = frame.sort_values(["symbol", "date"], kind="mergesort")
    frame = frame.reset_index(drop=True)
    report.rows_out = int(len(frame))
    report.symbols_out = int(frame["symbol"].nunique())
    report.sessions = int(frame["date"].nunique())
    report.first_date = frame["date"].min().date().isoformat()
    report.last_date = frame["date"].max().date().isoformat()

    lost = report.symbols_in - report.symbols_out
    if lost:
        report.notes.append(
            f"{lost} symbol(s) left the sample (out of universe, short "
            f"history, or fully invalid)")
    return frame, report
