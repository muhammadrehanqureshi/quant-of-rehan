#!/usr/bin/env python3
"""Build one year of the five year PSX intraday archive (CLOUD-ONLY).

Owner request 2026-11-13: five years of 5m, 15m, 30m and 1h bars for every
KMIALL scrip, for strategy backtests. The broker's own live servlet cannot
backfill (DATA_SOURCING.md section 4), so the archive is read from the SCS
Trade chart datafeed (src/data/scs_chart.py), which is free, unauthenticated
and carries volume back to 2021-11-15.

This script builds ONE calendar year, because the workflow runs the years as
a matrix: each job is a few minutes, a failed year is retried alone, and the
partitions never need merging.

What it writes, under the gitignored data/history/:

    {tf}/{tf}-{year}.parquet    symbol, ts, open, high, low, close, volume,
                                regular; one row per bar, sorted
    manifest-{year}.json        provenance, per symbol coverage, structural
                                checks and the native bucket agreement

and, unless --skip-r2, uploads both to the private R2 bucket under
history/{year}/. Nothing here is ever committed to the repository.

Data honesty (SO-3): a structurally impossible series is never written; the
symbol is named in the manifest and, if enough symbols fault, the build stops.
Coverage is measured against the exchange calendar, not assumed.

Prices are as traded. No split or bonus adjustment is applied, and the
manifest says so, because inventing one would be worse than naming it.

Run only in GitHub Actions (SO-23): the guard refuses any other host.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src.data import band_state, scs_chart  # noqa: E402
from src.data.sessions import KARACHI, now_karachi, session_bands  # noqa: E402

DEFAULT_OUT = ROOT / "data" / "history"
DEFAULT_UNIVERSE = ROOT / "src" / "data" / "universe_kmiall.json"
DEFAULT_YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
#: The feed's first bar, measured 2026-11-13. Asking for 2021 from January
#: would make the 2021 manifest report coverage against ten dead months.
ARCHIVE_START = date(2021, 11, 13)
WORKERS = 2
MIN_SYMBOL_COVERAGE = 0.50
MAX_FAULT_SHARE = 0.05

_thread_local = threading.local()


def _session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = scs_chart.new_session()
        _thread_local.session = session
    return session


def load_kmiall(path: Path) -> list[str]:
    """Every symbol listed in a KMIALL index, from the universe file.

    The scanner screens the current universe for eligibility; an archive is
    history, so it keeps the whole index membership the file records rather
    than the screen of today. A delisted scrip that traded in 2022 still has
    2022 bars, and a backtest of that year should see them.
    """
    if not path.exists():
        raise SystemExit(f"universe file not found: {path}")
    records = json.loads(path.read_text(encoding="utf-8"))
    symbols = sorted({
        str(r["symbol"]).strip().upper()
        for r in records
        if r.get("symbol")
        and any(str(name).upper().startswith("KMIALL")
                for name in (r.get("listedIn") or []))
    })
    if not symbols:
        raise SystemExit(f"no KMIALL symbols in {path}")
    return symbols


def window_for(year: int, start: str | None, end: str | None) -> tuple[int, int]:
    """Epoch bounds of one year in Karachi time, clipped by explicit dates.

    `end` is inclusive as a date: the archive covers through that whole day,
    so "yesterday" means yesterday's last bar, not midnight at its start.
    """
    first = datetime(year, 1, 1, tzinfo=KARACHI)
    following = datetime(year + 1, 1, 1, tzinfo=KARACHI)
    lo = int(first.timestamp())
    hi = int(following.timestamp())
    if start:
        lo = max(lo, int(datetime.fromisoformat(start).replace(
            tzinfo=KARACHI).timestamp()))
    if end:
        hi = min(hi, int((datetime.fromisoformat(end).replace(tzinfo=KARACHI)
                          + timedelta(days=1)).timestamp()))
    return lo, hi


def compare(derived: scs_chart.Bars, native: scs_chart.Bars) -> dict:
    """How exactly a derived bucket series reproduces the feed's own buckets."""
    out = {"derived_bars": len(derived), "native_bars": len(native),
           "common": 0, "exact": 0, "agreement_pct": None}
    if len(derived) == 0 or len(native) == 0:
        return out
    common, left, right = np.intersect1d(derived.ts, native.ts,
                                         return_indices=True)
    out["common"] = int(common.size)
    if common.size == 0:
        return out
    same = (
        np.isclose(derived.open[left], native.open[right], atol=1e-4)
        & np.isclose(derived.high[left], native.high[right], atol=1e-4)
        & np.isclose(derived.low[left], native.low[right], atol=1e-4)
        & np.isclose(derived.close[left], native.close[right], atol=1e-4)
        & (derived.volume[left] == native.volume[right])
    )
    out["exact"] = int(same.sum())
    out["agreement_pct"] = round(100.0 * out["exact"] / common.size, 3)
    return out


def build_symbol(symbol: str, start: int, end: int, resolutions: list[int],
                 native_check: bool) -> dict:
    """Fetch one symbol for the window, validate it and resample it."""
    session = _session()
    result = {"symbol": symbol, "status": "ok", "frames": {},
              "checks": {}, "coverage": {}, "native": {}, "faults": [],
              "requests": 0}
    try:
        bars = scs_chart.fetch_window(session, symbol, scs_chart.BASE_RESOLUTION,
                                      start, end)
    except scs_chart.FeedError as exc:
        result["status"] = "failed"
        result["faults"].append(f"fetch: {exc}")
        return result
    result["requests"] = bars.requests_made
    if bars.status in ("not_found", "no_data", "empty_window") or len(bars) == 0:
        result["status"] = "no_data"
        return result
    if bars.status != "ok":
        result["status"] = "failed"
        result["faults"].append(f"status {bars.status}")
        return result
    result["checks"] = scs_chart.validate(bars)
    fault_list = scs_chart.problems(bars)
    if fault_list:
        # A series with an impossible bar is never written: SO-3.
        result["status"] = "faulted"
        result["faults"].extend(fault_list)
        return result
    result["coverage"] = scs_chart.coverage(bars, start, end)
    for resolution in resolutions:
        series = bars if resolution == scs_chart.BASE_RESOLUTION else \
            scs_chart.resample(bars, resolution)
        result["frames"][f"{resolution}m"] = series.frame(symbol)
        if native_check and resolution != scs_chart.BASE_RESOLUTION:
            try:
                native = scs_chart.fetch_window(session, symbol, resolution,
                                                start, end)
                result["native"][f"{resolution}m"] = compare(series, native)
            except scs_chart.FeedError as exc:
                result["native"][f"{resolution}m"] = {"error": str(exc)[:160]}
    return result


def write_parquet(frames: list[pd.DataFrame], path: Path) -> dict:
    """Write one timeframe partition, symbols sorted and categorical."""
    if not frames:
        return {"rows": 0, "bytes": 0, "path": None}
    table = pd.concat(frames, ignore_index=True)
    table["symbol"] = table["symbol"].astype("category")
    table = table.sort_values(["symbol", "ts"], kind="stable")
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(path, index=False, compression="zstd")
    try:
        shown = str(path.relative_to(ROOT))
    except ValueError:
        shown = str(path)
    return {"rows": int(len(table)), "bytes": int(path.stat().st_size),
            "path": shown.replace("\\", "/")}


def summarise(rows: list[dict], window: tuple[int, int], year: int,
              resolutions: list[int]) -> dict:
    """The manifest: what was asked, what arrived, what it cost and what is odd."""
    start, end = window
    with_bars = [r for r in rows if r["status"] == "ok"]
    coverage = [r["coverage"].get("session_coverage_pct", 0.0) for r in with_bars]
    shares = sorted(coverage)
    checks = {}
    for r in rows:
        for key, value in (r["checks"] or {}).items():
            checks[key] = checks.get(key, 0) + int(value)
    trading_days = 0
    d = datetime.fromtimestamp(start, tz=KARACHI).date()
    last = datetime.fromtimestamp(end, tz=KARACHI).date()
    while d <= last:
        if session_bands(d):
            trading_days += 1
        d = date.fromordinal(d.toordinal() + 1)
    native = {}
    for r in with_bars:
        for tf, info in r["native"].items():
            bucket = native.setdefault(tf, {"symbols": 0, "compared": 0,
                                            "exact": 0, "per_symbol": []})
            if info.get("agreement_pct") is not None:
                bucket["symbols"] += 1
                bucket["compared"] += int(info.get("common") or 0)
                bucket["exact"] += int(info.get("exact") or 0)
                bucket["per_symbol"].append({"symbol": r["symbol"],
                                             "pct": info["agreement_pct"]})
    for tf, info in native.items():
        info["agreement_pct"] = (round(100.0 * info["exact"] / info["compared"], 3)
                                 if info["compared"] else None)
        info["per_symbol"] = info["per_symbol"][:10]
    return {
        "source": {
            "name": "SCS Trade chart datafeed",
            "endpoint": scs_chart.BASE_URL + scs_chart.HISTORY_PATH,
            "chart_page": scs_chart.CHART_PAGE,
            "auth": "none",
            "base_resolution": "5m",
            "derived_resolutions": [f"{r}m" for r in resolutions
                                    if r != scs_chart.BASE_RESOLUTION],
            "prices": "as traded, no split or bonus adjustment",
            "first_bar_measured": scs_chart.FIRST_BAR_DATE,
            "sessions": "regular flag marks the exchange's trading bands; "
                        "pre-open and post-close bars are kept",
        },
        "generated_at": now_karachi().isoformat(timespec="seconds"),
        "year": year,
        "window_pkt": {
            "start": datetime.fromtimestamp(start, tz=KARACHI).isoformat(),
            "end": datetime.fromtimestamp(end, tz=KARACHI).isoformat(),
        },
        "trading_days_in_window": trading_days,
        "coverage_basis": "weekdays minus the local 2026 PSX holiday list; "
                          "earlier-year holidays are not in that list, so a "
                          "coverage figure is conservative",
        "symbols": {
            "requested": len(rows),
            "with_bars": len(with_bars),
            "no_data": [r["symbol"] for r in rows if r["status"] == "no_data"],
            "faulted": [{"symbol": r["symbol"], "faults": r["faults"]}
                        for r in rows if r["status"] in ("faulted", "failed")],
        },
        "coverage_pct": {
            "min": round(shares[0], 2) if shares else None,
            "median": round(float(np.median(shares)), 2) if shares else None,
            "max": round(shares[-1], 2) if shares else None,
            "below_50": sum(1 for s in shares if s < 50.0),
        },
        "checks": checks,
        "native_check": native,
        "requests": sum(int(r["requests"]) for r in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="build one year of the five year PSX intraday archive")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--start", default=None, help="ISO date, optional")
    parser.add_argument("--end", default=None, help="ISO date, inclusive")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--symbols", default=str(DEFAULT_UNIVERSE))
    parser.add_argument("--limit", type=int, default=0,
                        help="first N symbols, for a probe")
    parser.add_argument("--resolutions", default="5,15,30,60")
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument("--check-native", type=int, default=3,
                        help="compare derived buckets on the first N symbols")
    parser.add_argument("--skip-r2", action="store_true")
    parser.add_argument("--r2-prefix", default="history")
    args = parser.parse_args(argv)

    guard_cloud_backtest("scripts/build_intraday_history.py")

    resolutions = sorted({int(part) for part in args.resolutions.split(",")
                          if part.strip()})
    if scs_chart.BASE_RESOLUTION not in resolutions:
        resolutions = [scs_chart.BASE_RESOLUTION] + resolutions
    window = window_for(args.year, args.start, args.end)
    if args.year <= 2021:
        window = (max(window[0], int(datetime(ARCHIVE_START.year,
                                              ARCHIVE_START.month,
                                              ARCHIVE_START.day,
                                              tzinfo=KARACHI).timestamp())),
                  window[1])
    if window[1] <= window[0]:
        raise SystemExit(f"empty window for {args.year}: {window}")
    out_dir = Path(args.out)
    symbols = load_kmiall(Path(args.symbols))
    if args.limit:
        symbols = symbols[:args.limit]
    started = time.time()
    print(json.dumps({
        "year": args.year, "symbols": len(symbols),
        "window": [datetime.fromtimestamp(window[0], tz=KARACHI).isoformat(),
                   datetime.fromtimestamp(window[1], tz=KARACHI).isoformat()],
        "resolutions": resolutions, "workers": args.workers}), flush=True)

    rows: list[dict] = []
    check_native_for = set(symbols[:max(0, args.check_native)])
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {
            pool.submit(build_symbol, symbol, window[0], window[1], resolutions,
                        symbol in check_native_for): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                row = future.result()
            except Exception as exc:  # noqa: BLE001 - a named failure, not a crash
                row = {"symbol": symbol, "status": "failed",
                       "faults": [f"{type(exc).__name__}: {exc}"],
                       "frames": {}, "checks": {}, "coverage": {},
                       "native": {}, "requests": 0}
            rows.append(row)
            done += 1
            if done % 20 == 0 or done == len(symbols):
                good = sum(1 for r in rows if r["status"] == "ok")
                print(f"[{done}/{len(symbols)}] with_bars={good}",
                      flush=True)

    rows.sort(key=lambda r: r["symbol"])
    manifest = summarise(rows, window, args.year, resolutions)
    manifest["elapsed_seconds"] = round(time.time() - started, 1)
    faulted = len(manifest["symbols"]["faulted"])
    if len(rows) and faulted / len(rows) > MAX_FAULT_SHARE:
        manifest["ok"] = False
        manifest["reason"] = (f"{faulted} of {len(rows)} symbols faulted, "
                              f"above the {MAX_FAULT_SHARE:.0%} limit")
        print(json.dumps(manifest, indent=2), flush=True)
        return 3

    written = {}
    for resolution in resolutions:
        tf = f"{resolution}m"
        frames = [r["frames"][tf] for r in rows if tf in r["frames"]]
        written[tf] = write_parquet(frames, out_dir / tf / f"{tf}-{args.year}.parquet")
    manifest["files"] = written
    manifest["ok"] = manifest["symbols"]["with_bars"] > 0
    if not manifest["ok"]:
        manifest["reason"] = "no symbol returned a usable series"
    manifest_path = out_dir / f"manifest-{args.year}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if not args.skip_r2 and manifest["ok"]:
        ensured = band_state.ensure_bucket()
        uploads = []
        if ensured.get("ok"):
            for tf, info in written.items():
                if not info["path"]:
                    continue
                key = f"{args.r2_prefix}/{args.year}/{tf}/{tf}-{args.year}.parquet"
                uploads.append(band_state.put_object(
                    key, (ROOT / info["path"]).read_bytes(),
                    "application/vnd.apache.parquet"))
            uploads.append(band_state.put_object(
                f"{args.r2_prefix}/{args.year}/manifest-{args.year}.json",
                json.dumps(manifest, indent=2).encode("utf-8"),
                "application/json"))
        manifest["r2"] = {
            "bucket_ready": bool(ensured.get("ok")),
            "reason": ensured.get("reason"),
            "uploads": [{"key": u.get("key"), "ok": u.get("ok"),
                         "reason": u.get("reason")} for u in uploads],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(json.dumps({k: manifest[k] for k in
                      ("year", "ok", "symbols", "coverage_pct", "checks",
                       "files", "r2", "elapsed_seconds")
                      if k in manifest}, indent=2), flush=True)
    return 0 if manifest["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
