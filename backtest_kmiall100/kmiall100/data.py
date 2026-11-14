"""Find, read and clean the OHLCV files. Reads local files only, opens no socket.

Accepted layouts (any mix, file type csv, csv.gz or parquet):

    data/5m/PRL.csv            one folder per timeframe, one file per symbol
    data/5m.parquet            one long file per timeframe with a ``symbol`` column
    data/PRL_5m.csv            flat, timeframe at the end of the name

Timeframe names are normalised: 5m 5min 15m 30m 1h 60m 1d d daily all work.
Columns are matched loosely (time, timestamp, datetime, date; open, high, low,
close, volume or o h l c v). Timestamps are used as given, so keep the whole
data set in one time zone (Karachi time is what the strategies expect, but
nothing here depends on the zone, only on the order and the calendar date).

The index series is the file whose symbol looks like KMIALL (or ``--index``).
It becomes the market regime context for the strategies that need it.

Cleaning follows the repository's own ingestion rules: rows with a missing or
non positive price and untraded rows are dropped, a ragged candle (high below
the body, low above it) is repaired by widening, duplicates are removed, and
every drop is counted in the report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

import numpy as np
import pandas as pd

from .core import ALL_TFS

TF_ALIASES = {
    "5m": "5m", "5": "5m", "5min": "5m", "m5": "5m", "5minute": "5m",
    "15m": "15m", "15": "15m", "15min": "15m", "m15": "15m",
    "30m": "30m", "30": "30m", "30min": "30m", "m30": "30m",
    "1h": "1h", "60m": "1h", "60": "1h", "60min": "1h", "h1": "1h", "1hr": "1h", "hourly": "1h", "h": "1h",
    "1d": "1d", "d": "1d", "day": "1d", "daily": "1d", "1day": "1d", "eod": "1d",
}
EXTS = (".csv", ".csv.gz", ".parquet", ".pq")
TIME_COLS = ("time", "timestamp", "datetime", "date_time", "dt", "date", "ts")
COLMAP = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume", "vol": "volume",
          "openprice": "open", "highprice": "high", "lowprice": "low", "closeprice": "close",
          "last": "close", "ltp": "close", "qty": "volume", "turnover_volume": "volume"}
INDEX_RE = re.compile(r"^(kmi[\s_\-]?all|kmiall)([\s_\-]?index)?$", re.I)


def norm_tf(s: str) -> Optional[str]:
    return TF_ALIASES.get(re.sub(r"[\s_\-]", "", str(s).lower()))


def _strip_ext(name: str) -> Tuple[str, str]:
    low = name.lower()
    for e in sorted(EXTS, key=len, reverse=True):
        if low.endswith(e):
            return name[: -len(e)], e
    return name, ""


@dataclass
class Source:
    tf: str
    symbol: Optional[str]      # None for a long file holding many symbols
    path: Path


@dataclass
class Report:
    rows_in: int = 0
    rows_out: int = 0
    dropped: Dict[str, int] = field(default_factory=dict)
    repaired_ragged: int = 0

    def drop(self, why: str, n: int):
        if n:
            self.dropped[why] = self.dropped.get(why, 0) + int(n)


def discover(root: str | Path) -> List[Source]:
    root = Path(root)
    out: List[Source] = []
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        stem, ext = _strip_ext(p.name)
        if not ext:
            continue
        parent_tf = norm_tf(p.parent.name) if p.parent != root else None
        if parent_tf:                                   # data/5m/PRL.csv
            out.append(Source(parent_tf, stem, p))
            continue
        whole = norm_tf(stem)
        if whole:                                       # data/5m.parquet (long file)
            out.append(Source(whole, None, p))
            continue
        m = re.match(r"^(.*?)[_\-\s](5m|15m|30m|1h|60m|1d|d|daily|5min|15min|30min|60min)$", stem, re.I)
        if m:                                           # data/PRL_5m.csv
            tf = norm_tf(m.group(2))
            if tf:
                out.append(Source(tf, m.group(1), p))
    return out


def _read(path: Path) -> pd.DataFrame:
    name = path.name.lower()
    if name.endswith((".parquet", ".pq")):
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _timestamps(df: pd.DataFrame) -> pd.Series:
    cols = {c.lower().strip(): c for c in df.columns}
    tcol = next((cols[c] for c in TIME_COLS if c in cols), None)
    if tcol is None:
        raise ValueError("no time column among " + ", ".join(df.columns))
    s = df[tcol]
    if "date" in cols and "time" in cols and tcol == cols.get("date"):
        s = df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str)
    elif "date" in cols and "time" in cols:
        s = df[cols["date"]].astype(str) + " " + df[cols["time"]].astype(str)
    if pd.api.types.is_numeric_dtype(s.dtype) and not pd.api.types.is_bool_dtype(s.dtype):
        unit = "ms" if s.iloc[0] > 1e11 else "s"
        t = pd.to_datetime(s, unit=unit, utc=True).dt.tz_convert("Asia/Karachi").dt.tz_localize(None)
    else:
        t = pd.to_datetime(s, errors="coerce", utc=False)
        if getattr(t.dt, "tz", None) is not None:
            t = t.dt.tz_convert("Asia/Karachi").dt.tz_localize(None)
    return t


def clean(df: pd.DataFrame, report: Report) -> pd.DataFrame:
    """Return a frame indexed by timestamp with columns open high low close volume."""
    df = df.rename(columns={c: COLMAP.get(c.lower().strip(), c.lower().strip()) for c in df.columns})
    t = _timestamps(df)
    need = ["open", "high", "low", "close"]
    for c in need:
        if c not in df.columns:
            raise ValueError("missing column " + c)
    if "volume" not in df.columns:
        df["volume"] = 0.0
    out = pd.DataFrame({"ts": t, **{c: pd.to_numeric(df[c], errors="coerce") for c in need + ["volume"]}})
    report.rows_in += len(out)
    bad_t = out["ts"].isna()
    report.drop("bad_time", bad_t.sum())
    out = out[~bad_t]
    px = out[need]
    bad = px.isna().any(axis=1) | (px <= 0).any(axis=1)
    report.drop("bad_or_missing_price", bad.sum())
    out = out[~bad]
    flat0 = (out["volume"].fillna(0) <= 0) & (out["high"] == out["low"]) & (out["open"] == out["close"]) & (out["open"] == out["high"])
    report.drop("untraded_bar", flat0.sum())
    out = out[~flat0]
    hi = out[["open", "high", "low", "close"]].max(axis=1)
    lo = out[["open", "high", "low", "close"]].min(axis=1)
    ragged = (out["high"] < hi) | (out["low"] > lo)
    report.repaired_ragged += int(ragged.sum())
    out["high"], out["low"] = hi, lo
    out["volume"] = out["volume"].fillna(0).clip(lower=0)
    dup = out["ts"].duplicated(keep="last")
    report.drop("duplicate_timestamp", dup.sum())
    out = out[~dup].sort_values("ts").set_index("ts")
    report.rows_out += len(out)
    return out


def load_series(src: Source, only: Optional[set] = None) -> Iterator[Tuple[str, pd.DataFrame, Report]]:
    """Yield (symbol, cleaned frame, report) for a source (one or many symbols)."""
    df = _read(src.path)
    if src.symbol is not None:
        r = Report()
        yield src.symbol, clean(df, r), r
        return
    cols = {c.lower().strip(): c for c in df.columns}
    scol = next((cols[c] for c in ("symbol", "ticker", "scrip", "code", "name") if c in cols), None)
    if scol is None:
        raise ValueError(f"{src.path} is a long file but has no symbol column")
    for sym, g in df.groupby(scol, sort=True):
        if only and str(sym) not in only:
            continue
        r = Report()
        yield str(sym), clean(g.drop(columns=[scol]), r), r


def is_index(sym: str, index_name: Optional[str]) -> bool:
    if index_name:
        return sym.upper() == index_name.upper()
    return bool(INDEX_RE.match(sym.strip()))


def align_index(stock_ts: np.ndarray, idx: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Index bars on the stock's timestamps (the latest index bar at or before each one)."""
    if idx is None or idx.empty:
        return None
    a = idx.reindex(pd.DatetimeIndex(stock_ts), method="ffill")
    if a["close"].isna().mean() > 0.5:
        return None
    return a
