"""Loader for the sentinel's local EOD corpus (engine smoke-testing data).

Corpus format (built by the sentinel's scripts/build_eod_corpus.py on
2026-09-24, before the DPS portal redesign removed the 5-year endpoint):
    {symbol: [{"date": "YYYY-MM-DD", "open": float, "close": float,
               "volume": float}, ...]}
Covers 305 KMIALL symbols, 177 sessions, 2026-01-05 .. 2026-09-23.
No high/low (DPS never provided it) -> backtests run in close mode.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_corpus(path: Path) -> tuple[pd.DataFrame, dict]:
    """Return (long DataFrame [symbol, date, open, close, volume], info dict).

    Empty symbols are skipped and counted — never silently (SO-3).
    """
    if not path.is_file():
        raise FileNotFoundError(f"Corpus not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    frames = []
    empty = 0
    for symbol, rows in raw.items():
        if not rows:
            empty += 1
            continue
        frames.append(pd.DataFrame(rows).assign(symbol=symbol))
    if not frames:
        raise ValueError(f"Corpus {path} contains no usable rows")
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    info = {
        "symbols_total": len(raw),
        "symbols_with_data": len(frames),
        "symbols_empty": empty,
        "sessions": int(df["date"].nunique()),
        "rows": int(len(df)),
        "start": str(df["date"].min().date()),
        "end": str(df["date"].max().date()),
    }
    return df, info
