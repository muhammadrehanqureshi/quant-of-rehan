#!/usr/bin/env python3
"""LOCAL-ONLY 5-year EOD history builder from PSX Daily Downloads (SO-4).

Walks weekdays in [start, end], fetches each session's mkt_summary file
(see src/data/psx_daily_downloads.py: full OHLCV WITH high/low), and
writes a long-frame CSV. CHECKPOINTED: rows flush to a `.partial.csv`
every --flush-every sessions, so an interrupted crawl loses at most the
last few sessions: just re-run to resume.

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
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/eod_history.csv.gz")
    ap.add_argument("--pause", type=float, default=REQUEST_PAUSE)
    ap.add_argument("--flush-every", type=int, default=25,
                    help="checkpoint rows to the partial file every N sessions")
    args = ap.parse_args(argv)

    # SO-4 with the SO-10 carve-out (owner approval, 2026-10-07): CI never
    # crawls the 5-year history, but the cloud signal job may fetch a small
    # trailing window for the day's bars.
    if os.environ.get("GITHUB_ACTIONS"):
        d0 = datetime.strptime(str(args.start), "%Y-%m-%d")
        d1 = datetime.strptime(str(args.end), "%Y-%m-%d")
        if (d1 - d0).days > 45:
            print("REFUSING on CI: full-history crawls stay LOCAL ONLY (SO-4); "
                  "the cloud signal job may fetch only a small trailing "
                  "window (SO-10).")
            return 1

    # Append-mode checkpoint file: a killed crawl loses at most the last
    # --flush-every sessions, not the whole run (lesson from the first
    # 5-year attempt: write-only-at-end lost 30+ minutes to a restart).
    partial = args.out.with_suffix(".partial.csv")

    want = iter_weekdays(args.start, args.end)
    print(f"LOCAL-ONLY PSX EOD crawl: {len(want)} weekdays "
          f"{args.start} .. {args.end} (holidays just 404)\n"
          f"pause={args.pause}s  out={args.out}  flush_every={args.flush_every}")

    have: set[str] = set()
    for src in (args.out, partial):
        if src.is_file():
            old = pd.read_csv(src, usecols=["date"])
            have |= set(old["date"].unique())
            print(f"resume source {src.name}: "
                  f"{old['date'].nunique()} sessions")
    if have:
        print(f"resuming: {len(have)} sessions already on disk")

    todo = [d for d in want if d.isoformat() not in have]
    print(f"to fetch: {len(todo)} sessions")

    fetched, no_session, bad = 0, 0, []
    buf: list[dict] = []
    new_rows_total = 0
    partial.parent.mkdir(parents=True, exist_ok=True)

    def flush() -> None:
        """Append buffered rows to the partial checkpoint file."""
        if not buf:
            return
        pd.DataFrame(buf)[["date", "symbol", "name", "open", "high",
                           "low", "close", "volume", "rate2"]].to_csv(
            partial, mode="a", header=not partial.is_file(), index=False)
        buf.clear()

    for i, d in enumerate(todo, 1):
        rows, info = fetch_mkt_summary(d, pause=args.pause)
        if info["status"] == "ok":
            buf.extend(rows)
            fetched += 1
            new_rows_total += len(rows)
        elif info["status"] == "no_session":
            no_session += 1
        else:
            bad.append(info)
            print(f"  !! {d}: {info.get('status')} {info.get('error', '')}",
                  flush=True)
        if i % args.flush_every == 0:
            flush()
        if i % 60 == 0:
            print(f"  ...{i}/{len(todo)} fetched={fetched} "
                  f"no_session={no_session} bad={len(bad)} "
                  f"rows={new_rows_total:,}", flush=True)
    flush()

    if new_rows_total == 0:
        print("Nothing new fetched.")
        return 0

    old = pd.read_csv(args.out) if args.out.is_file() else None
    add = pd.read_csv(partial) if partial.is_file() else None
    parts = [p for p in (old, add) if p is not None]
    df = pd.concat(parts, ignore_index=True)
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
