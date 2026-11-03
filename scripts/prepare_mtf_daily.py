#!/usr/bin/env python3
"""Build the daily history the intraday 1 day frame reads.

The session workflows restore this file from the Actions cache. On a miss
they run this script once, then save the file under the day's key. It walks
the most recent weekdays backwards from yesterday, fetches the PSX
mkt_summary file for each, keeps the KMIALL symbols and writes a compact
gzipped CSV.

A 404 is a non-session day (weekend, holiday, archive gap), counted and
skipped, never filled. If fewer than the forty sessions the daily Kalman
needs come back, the script refuses to write a thin file: the live signal
would otherwise be blocked by a history that only looks present.

GITHUB ACTIONS only (SO-21). The crawl is polite, paced by
src/data/psx_daily_downloads.py, and never runs on the owner's PC.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.psx_daily_downloads import fetch_mkt_summary  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

MIN_SESSIONS = 40
UNIVERSE = ROOT / "src" / "data" / "universe_kmiall.json"


def _universe(path: Path) -> set[str]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row["symbol"]).strip().upper()
        for row in records
        if row.get("symbol") and "KMIALLSHR" in (row.get("listedIn") or [])
    }


def _weekdays_back(end: date, count: int) -> list[date]:
    days: list[date] = []
    cursor = end
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return days


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="daily history for the 1d frame")
    parser.add_argument("--sessions", type=int, default=60,
                        help="completed sessions to keep (default 60)")
    parser.add_argument("--lookback-days", type=int, default=120,
                        help="weekday slots to walk at most (default 120)")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data" / "mtf_daily.csv.gz")
    parser.add_argument("--universe", type=Path, default=UNIVERSE)
    args = parser.parse_args(argv)

    if args.sessions < MIN_SESSIONS:
        print(f"refusing fewer than {MIN_SESSIONS} sessions", file=sys.stderr)
        return 2

    symbols = _universe(args.universe)
    yesterday = now_karachi().date() - timedelta(days=1)
    slots = _weekdays_back(yesterday, args.lookback_days)
    rows: list[dict] = []
    found = 0
    missing = 0
    for day in slots:
        if found >= args.sessions:
            break
        records, info = fetch_mkt_summary(day, pause=0.2)
        if records is None:
            missing += 1
            continue
        found += 1
        for row in records:
            symbol = str(row.get("symbol", "")).strip().upper()
            if symbol not in symbols:
                continue
            rows.append({
                "symbol": symbol,
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
            })

    if found < MIN_SESSIONS:
        print(f"::error::only {found} sessions returned; {MIN_SESSIONS} needed. "
              f"{missing} slots were non-session or unreadable. No file written.",
              file=sys.stderr)
        return 3
    if not rows:
        print("::error::no KMIALL rows in the fetched sessions", file=sys.stderr)
        return 4

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["symbol", "date", "open", "high", "low",
                                "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)
    dates = sorted({row["date"] for row in rows})
    print(json.dumps({
        "out": str(args.out),
        "sessions": found,
        "slots_missing": missing,
        "symbols": len({row["symbol"] for row in rows}),
        "rows": len(rows),
        "first_date": dates[0],
        "last_date": dates[-1],
    }, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
