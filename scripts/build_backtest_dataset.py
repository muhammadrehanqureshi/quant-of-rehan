"""Build the ten-year KMIALL EOD dataset from the mkt_summary archive.

SO-21: this crawl runs on GitHub Actions minutes, never on the owner's PC;
the entry point is guarded with guard_cloud_backtest and refuses locally.

Source: https://dps.psx.com.pk/download/mkt_summary/{YYYY-MM-DD}.Z - one
fixed-format `closing11.lis` per session date. A 404 is a non-session day,
never an error. The archive starts where the 2026-09 redesign left it and
reaches back years (gzip bodies for older sessions); the crawl walks every
weekday and records which dates actually returned a session, missing dates
are a measured 404 count, never filled (SO-3).

Output: data/eod_dataset_10y.csv.gz, columns symbol,date,open,high,low,
close,volume - the full OHLCV the old five-year timeseries endpoint never
had. The dataset is gitignored (data/ root) and travels between runs only
as a workflow artifact.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import zipfile
from datetime import date as date_cls, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

import requests

BASE = "https://dps.psx.com.pk"
MKT_SUMMARY_URL = BASE + "/download/mkt_summary/{date}.Z"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": BASE + "/downloads",
}
REQUEST_PAUSE = 0.20   # polite crawl: ~2600 weekdays over ten years
RETRIES = 3

# How much of the weekday slots may 404 before the crawl refuses to hand
# the runner a panel that is too shallow to call a ten-year proof (SO-3:
# coverage is reported, never implied). If the archive itself is shallower
# than ten years the job fails LOUDLY with the measured gap in the log,
# instead of shipping a backtest that pretends it had history it did not.
MISSING_PCT_FLOOR = 25.0


def parse_closing_lis(text: str) -> list[dict]:
    """Parse `closing11.lis` content into per-symbol row dicts.

    Format: 02OCT2026|OGDC|0820|Oil & Gas Dev|OPEN|HIGH|LOW|CLOSE|VOLUME|rate2|||
    Malformed lines are skipped, never invented. The OHLCV floats are
    guarded: a row without a real number in every OHLCV slot is dropped.
    """
    rows: list[dict] = []
    for line in text.splitlines():
        fields = line.split("|")
        if len(fields) < 9:
            continue
        try:
            session = datetime.strptime(fields[0].strip(), "%d%b%Y").date()
            symbol = fields[1].strip().upper()
            if not symbol:
                continue
            open_ = float(fields[4])
            high = float(fields[5])
            low = float(fields[6])
            close = float(fields[7])
            volume = float(fields[8])
        except (ValueError, IndexError):
            continue
        if close <= 0:
            continue
        rows.append({"date": session, "symbol": symbol, "open": open_,
                     "high": high, "low": low, "close": close,
                     "volume": volume})
    return rows


def _payload(http: requests.Session, session: date_cls) -> list[dict]:
    """One mkt_summary fetch: a list of rows, [] on a clean non-session day,
    None on a transport failure."""
    url = MKT_SUMMARY_URL.format(date=session.isoformat())
    body: bytes | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = http.get(url, timeout=30.0)
            if resp.status_code == 404:
                return []
            if resp.status_code == 200:
                body = resp.content
                break
        except requests.RequestException:
            pass
        if attempt < RETRIES:
            time.sleep(1.5 * attempt)
    if body is None:
        return None
    if body[:2] == b"PK":
        return parse_closing_lis(zipfile.ZipFile(io.BytesIO(body))
                                 .read("closing11.lis").decode("utf-8",
                                                               "replace"))
    return parse_closing_lis(gzip.decompress(body).decode("utf-8", "replace"))


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/build_backtest_dataset.py")
    ap = argparse.ArgumentParser(
        description="Ten-year PSX EOD crawl (mkt_summary archive)")
    ap.add_argument("--universe", type=Path,
                    default=Path("src/data/universe_kmiall.json"))
    ap.add_argument("--start", default="2016-11-01",
                    help="ISO date of the first weekday crawled")
    ap.add_argument("--end", help="ISO date, default: today")
    ap.add_argument("--out", type=Path, default=Path("data/eod_dataset_10y.csv.gz"))
    ap.add_argument("--cache-dir", type=Path, default=Path("data/mkt_cache"))
    args = ap.parse_args(argv)

    import pandas as pd
    universe = sorted({r["symbol"] for r in
                       json.loads(args.universe.read_text(encoding="utf-8"))})
    print(f"Universe: {len(universe)} KMIALL symbols")
    d0 = date_cls.fromisoformat(args.start)
    d1 = date_cls.fromisoformat(args.end) if args.end else date_cls.today()
    days = [d0 + timedelta(days=i) for i in range((d1 - d0).days + 1)]
    weekdays = [d for d in days if d.weekday() < 5]
    print(f"Crawl window: {d0} .. {d1}: {len(weekdays)} weekdays")

    http = requests.Session()
    http.headers.update(HEADERS)
    cache_dir = args.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "mkt_sessions.json"
    cache: dict = json.loads(cache_file.read_text("utf-8")) if cache_file.is_file() else {}

    rows: list[dict] = []
    missing = []          # weekdays the archive returned 404
    failed = []           # weekdays that errored after retries
    for i, day in enumerate(weekdays):
        key = day.isoformat()
        status = cache.get(key, {}).get("status")
        if status is not None:
            if status == "ok":
                rows.extend(cache[key]["rows"])
            elif status == "missing":
                missing.append(key)
            else:
                failed.append(key)
            continue
        result = _payload(http, day)
        if result is None:
            failed.append(key)
            cache[key] = {"status": "failed"}
        elif not result:
            missing.append(key)
            cache[key] = {"status": "missing"}
        else:
            rows.extend(result)
            # Keep every session's raw rows in one side file so the main
            # run passes over the cache as intact data instead of parsing
            # archives again.
            cache[key] = {"status": "ok", "rows": result}
        if (i + 1) % 250 == 0:
            cache_file.write_text(json.dumps(cache), encoding="utf-8")
            print(f"  {i + 1}/{len(weekdays)} weekdays done", flush=True)
        time.sleep(REQUEST_PAUSE)
    cache_file.write_text(json.dumps(cache), encoding="utf-8")

    rows = [r for r in rows if r["symbol"] in universe]
    if not rows:
        print("::error::No rows in the KMIALL universe; refusing to write an empty dataset (SO-3)")
        return 1
    missing_pct = round(100.0 * len(missing) / max(len(weekdays), 1), 2)
    if missing_pct > MISSING_PCT_FLOOR:
        print(f"::error::Archive missing {missing_pct}% of weekday slots (> {MISSING_PCT_FLOOR}%); "
              "the panel never claims coverage it never had (SO-3)")
        return 1
    df = pd.DataFrame(rows).sort_values(["symbol", "date"]).reset_index(drop=True)
    df.to_csv(args.out, index=False)
    summary = {
        "universe_size": len(universe),
        "weekdays": len(weekdays),
        "sessions": len(weekdays) - len(missing) - len(failed),
        "missing": missing,
        "failed": failed,
        "missing_pct": missing_pct,
        "rows": int(len(df)),
        "symbols_with_data": int(df["symbol"].nunique()),
        "window": [d0.isoformat(), d1.isoformat()],
    }
    args.out.with_suffix("").with_suffix(".summary").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
