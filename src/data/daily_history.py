"""Daily bars for the 1 day frame of the intraday signal.

The intraday scanner reads one session of one minute tape. That tape cannot
say where the daily chart sits, so the 1 day VWAP and Kalman need a separate
daily history. This module reads the compact file the session workflows
build once per day (scripts/prepare_mtf_daily.py) and hands the scanner only
completed sessions, oldest first.

The file is CSV gzipped with the columns symbol,date,open,high,low,close,
volume. Rows dated today or later are dropped: the current session's day bar
is still forming and is never evidence. A missing or unreadable file is an
empty history, never an invented one.
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src import config

ROOT = Path(__file__).resolve().parents[2]

#: How many completed sessions a symbol may carry into the frame. Twenty are
#: the VWAP's own window; the extra forty feed the Kalman state.
KEEP_DAYS = 120

_CACHE: dict[tuple[str, float, str], dict[str, list["DailyBar"]]] = {}


@dataclass(frozen=True)
class DailyBar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def _number(text) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if value == value else None


def load(path: Path | str | None = None, day: date | None = None) -> dict[str, list[DailyBar]]:
    """Completed daily bars per symbol, oldest first, dated before *day*."""
    target = Path(path) if path is not None else ROOT / config.MTF_DAILY_FILE
    stamp = day or date.today()
    key = (str(target), target.stat().st_mtime if target.is_file() else -1.0,
           stamp.isoformat())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    bars: dict[str, list[DailyBar]] = {}
    if target.is_file():
        try:
            with gzip.open(target, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    symbol = str(row.get("symbol", "")).strip().upper()
                    if not symbol:
                        continue
                    try:
                        moment = date.fromisoformat(str(row.get("date", "")))
                    except ValueError:
                        continue
                    if moment >= stamp:
                        continue
                    values = [_number(row.get(name))
                              for name in ("open", "high", "low", "close", "volume")]
                    if any(value is None for value in values):
                        continue
                    open_, high, low, close, volume = values
                    if (open_ is None or high is None or low is None
                            or close is None or volume is None
                            or min(open_, high, low, close) <= 0
                            or high < max(open_, close) or low > min(open_, close)
                            or high < low or volume < 0):
                        continue
                    bars.setdefault(symbol, []).append(DailyBar(
                        moment, open_, high, low, close, volume))
        except (OSError, EOFError, csv.Error, UnicodeDecodeError):
            bars = {}
    for symbol, rows in bars.items():
        rows.sort(key=lambda bar: bar.day)
        del rows[:-KEEP_DAYS]
    _CACHE.clear()
    _CACHE[key] = bars
    return bars
