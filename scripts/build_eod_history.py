#!/usr/bin/env python3
"""LOCAL-ONLY 5-year EOD history builder from PSX Daily Downloads (SO-4).

Walks weekdays in [start, end], fetches each session's mkt_summary file
(see src/data/psx_daily_downloads.py — full OHLCV WITH high/low), and
appends to a long-frame CSV (+ .gz). Resumable: already-present session
dates are skipped, so an interrupted crawl can just be re-run.

    python scripts/build_eod_history.py --start 2021-10-04 --end 2026-10-02

~1,240 sessions x ~20KB. Never run in CI; never commit the dataset.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.psx_daily_downloads import (  # noqa: E402
    REQUEST_PAUSE,
    fetch_mkt_summary,
    iter_weekdays,
)


def main(argv: list[str] | None = None) -> int:
    if os.environ.get("GITHUB_ACTIONS"):
        print("REFUSING: dataset fetches are LOCAL ONLY (SO-4).")
        return 1

    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/eod_history.csv.gz")
    ap.add_argument("--pause", type=float, default=REQUEST_PAUSE)
    args = ap.parse_args(argv)

    want = iter_weekdays(args.start, args.end)
    print(f"LOCAL-ONLY PSX EOD crawl: {len(want)} weekdays "
          f"{args.start} .. {args.end} (holidays just 404)\n"
          f"pause={args.pause}s  out={args.out}")

    have: set[str] = set()
    if args.out.is_file():
        old = pd.read_csv(args.out)
        have = set(old["date"].unique())
        print(f"resuming: {len(have)} sessions already present")

    todo = [d for d in want if d.isoformat() not in have]
    print(f"to fetch: {len(todo)} sessions")

    frames = [] if not have else []
    fetched, no_session, bad = 0, 0, []
    buf: list[dict] = []
    for i, d in enumerate(todo, 1):
        rows, info = fetch_mkt_summary(d, pause=args.pause)
        if info["status"] == "ok":
            buf.extend(rows)
            fetched += 1
        elif info["status"] == "no_session":
            no_session += 1
        else:
            bad.append(info)
            print(f"  !! {d}: {info.get('status')} {info.get('error', '')}")
        if buf and i % 60 == 0:
            print(f"  ...{i}/{len(todo)} fetched={fetched} "
                  f"no_session={no_session} bad={len(bad)} "
                  f"rows={len(buf):,}")

    if not buf:
        print("Nothing new fetched.")
        return 0

    new = pd.DataFrame(buf)[["date", "symbol", "name", "open", "high",
                             "low", "close", "volume", "rate2"]]
    old = pd.read_csv(args.out) if args.out.is_file() else None
    df = pd.concat([old, new], ignore_index=True) if old is not None else new
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)

    coverage = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "range": [args.start, args.end],
        "sessions_fetched": fetched,
        "sessions_no_data_404": no_session,
        "sessions_bad": len(bad),
        "bad": bad[:50],
        "total_rows": int(len(df)),
        "total_sessions": int(df["date"].nunique()),
        "symbols": int(df["symbol"].nunique()),
        "start": str(df["date"].min()),
        "end": str(df["date"].max()),
    }
    cov_path = args.out.with_suffix(".coverage.json")
    cov_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")
    print(json.dumps(coverage, indent=2)[:600])
    print(f"\nDataset -> {args.out}\nCoverage -> {cov_path}")
    return 0 if len(bad) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
