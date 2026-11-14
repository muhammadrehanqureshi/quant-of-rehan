#!/usr/bin/env python3
"""Prepare the five year archive for the kmiall100 cloud backtest.

The archive stores one parquet file per timeframe per year under::

    data/history/5m/5m-2021.parquet

The backtest kit reads one long parquet per timeframe (``5m.parquet`` with a
``symbol`` column), so this joins the yearly partitions and filters out bars
outside the exchange's regular session when the archive carries that flag.
No strategy is run here, and no number is invented: a missing year fails the
job instead of quietly shortening the test.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

EXPECTED_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
COLUMNS = ("symbol", "ts", "open", "high", "low", "close", "volume")


def prepare(history: Path, out: Path, tfs: list[str]) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    report: dict[str, dict] = {}
    for tf in tfs:
        folder = history / tf
        paths = sorted(folder.glob(f"{tf}-*.parquet"))
        years = sorted(int(p.stem.split("-")[-1]) for p in paths)
        missing = [y for y in EXPECTED_YEARS if y not in years]
        if missing:
            raise SystemExit(
                f"{tf} archive is missing years {missing}; present: {years}")

        parts = []
        for path in paths:
            frame = pd.read_parquet(path)
            absent = [c for c in COLUMNS if c not in frame.columns]
            if absent:
                raise SystemExit(f"{path} is missing columns {absent}")
            if "regular" in frame.columns:
                frame = frame[frame["regular"].astype(bool)]
            parts.append(frame[list(COLUMNS)])

        table = pd.concat(parts, ignore_index=True)
        table["symbol"] = table["symbol"].astype(str).str.upper()
        table = table.sort_values(["symbol", "ts"], kind="mergesort")
        table = table.drop_duplicates(["symbol", "ts"], keep="last")

        target = out / f"{tf}.parquet"
        table.to_parquet(target, index=False)
        report[tf] = {
            "rows": int(len(table)),
            "symbols": int(table["symbol"].nunique()),
            "years": years,
            "path": str(target),
        }
        print(f"{tf}: {len(table):,} regular-session rows, "
              f"{report[tf]['symbols']} symbols -> {target}", flush=True)

    (out / "manifest.json").write_text(
        json.dumps({"source": str(history), "timeframes": report}, indent=2) + "\n",
        encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history", default="data/history")
    ap.add_argument("--out", default="data/kmiall100")
    ap.add_argument("--tfs", default="5m,15m,30m")
    args = ap.parse_args()
    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    if not tfs:
        raise SystemExit("no timeframes requested")
    prepare(Path(args.history), Path(args.out), tfs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
