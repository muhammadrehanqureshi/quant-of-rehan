#!/usr/bin/env python3
"""Verify the five-year PSX intraday archive after a build (CLOUD-ONLY).

The archive is only useful if its five timeframes agree with each other and
with Karachi time. This verifier does not repair or resample the archive; it
reads the partitions and fails when a row is structurally impossible, when a
daily row is not stamped at Karachi midnight, or when the 1D/15m/30m/60m
partitions cannot be reproduced from the 5m partition.

Run only in GitHub Actions (SO-21). The guard refuses any other host.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402

TIMEFRAMES = ("5m", "15m", "30m", "60m", "1D")
SCHEMA = ("symbol", "ts", "open", "high", "low", "close", "volume", "regular")
FIRST_DATE = "2021-11-15"


def _jsonable(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _load(root: Path, year: int, timeframe: str, failures: list[str]):
    path = root / timeframe / f"{timeframe}-{year}.parquet"
    if not path.is_file():
        failures.append(f"{year} {timeframe}: missing partition {path}")
        return None
    frame = pd.read_parquet(path)
    absent = [column for column in SCHEMA if column not in frame.columns]
    if absent:
        failures.append(f"{year} {timeframe}: missing columns {absent}")
        return None
    frame["symbol"] = frame["symbol"].astype(str)
    frame["ts"] = pd.to_numeric(frame["ts"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["regular"] = frame["regular"].fillna(False).astype(bool)
    frame = frame.sort_values(["symbol", "ts"], kind="mergesort").reset_index(drop=True)
    if frame[["ts", "open", "high", "low", "close", "volume"]].isna().any().any():
        failures.append(f"{year} {timeframe}: non-numeric values in a numeric column")
    return frame


def _structural(frame: pd.DataFrame, year: int, timeframe: str,
                failures: list[str]) -> dict:
    out = {}
    out["rows"] = int(len(frame))
    out["symbols"] = int(frame["symbol"].nunique())
    out["duplicates"] = int(frame.duplicated(["symbol", "ts"]).sum())
    bad_high = int((frame["high"] < frame[["open", "close", "low"]].max(axis=1)).sum())
    bad_low = int((frame["low"] > frame[["open", "close", "high"]].min(axis=1)).sum())
    nonpositive = int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
    negative_volume = int((frame["volume"] < 0).sum())
    out.update({
        "duplicate_rows": out["duplicates"],
        "invalid_high_rows": bad_high,
        "invalid_low_rows": bad_low,
        "nonpositive_price_rows": nonpositive,
        "negative_volume_rows": negative_volume,
    })
    if timeframe == "1D":
        midnight = int(((frame["ts"] + 5 * 3600) % 86400 != 0).sum())
        not_regular = int((~frame["regular"]).sum())
        out["not_midnight_pkt_rows"] = midnight
        out["non_regular_rows"] = not_regular
    else:
        seconds = int(timeframe[:-1]) * 60
        off_grid = int((frame["ts"] % seconds != 0).sum())
        out["off_grid_rows"] = off_grid
    for key in ("duplicates", "invalid_high_rows", "invalid_low_rows",
                "nonpositive_price_rows", "negative_volume_rows",
                "not_midnight_pkt_rows", "non_regular_rows", "off_grid_rows"):
        if out.get(key, 0):
            failures.append(f"{year} {timeframe}: {key}={out[key]}")
    return out


def _daily_aggregate(base: pd.DataFrame) -> pd.DataFrame:
    """The expected 1D rows from regular 5m bars, keyed by Karachi session day."""
    frame = base[base["regular"]].copy()
    frame["day"] = ((frame["ts"].astype("int64") + 5 * 3600) // 86400).astype("int64")
    frame = frame.sort_values(["symbol", "ts"], kind="mergesort")
    grouped = frame.groupby(["symbol", "day"], sort=False, observed=True)
    out = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()
    out["ts"] = out["day"] * 86400 - 5 * 3600
    return out


def _resampled_aggregate(base: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    seconds = int(timeframe[:-1]) * 60
    frame = base.copy()
    frame["bucket"] = (frame["ts"].astype("int64") // seconds) * seconds
    grouped = frame.groupby(["symbol", "bucket"], sort=False, observed=True)
    return grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).reset_index()


def _compare(expected: pd.DataFrame, actual: pd.DataFrame, year: int,
             timeframe: str, failures: list[str]) -> dict:
    out = {"expected_rows": int(len(expected)), "actual_rows": int(len(actual)),
           "missing_rows": 0, "extra_rows": 0, "value_mismatches": 0}
    expected = expected.copy()
    actual = actual.copy()
    # Compare on the same identity without requiring the same column order.
    if timeframe == "1D":
        expected["key"] = expected["symbol"].astype(str) + "|" + expected["day"].astype(str)
        actual["key"] = actual["symbol"].astype(str) + "|" + (
            ((actual["ts"].astype("int64") + 5 * 3600) // 86400).astype(str))
    else:
        expected["key"] = expected["symbol"].astype(str) + "|" + expected["bucket"].astype(str)
        actual["key"] = actual["symbol"].astype(str) + "|" + actual["ts"].astype(str)
    e = expected.set_index("key")
    a = actual.set_index("key")
    missing = e.index.difference(a.index)
    extra = a.index.difference(e.index)
    out["missing_rows"] = int(len(missing))
    out["extra_rows"] = int(len(extra))
    common = e.index.intersection(a.index)
    if len(common):
        left = e.loc[common]
        right = a.loc[common]
        close_px = (
            np.isclose(left["open"].to_numpy(float), right["open"].to_numpy(float),
                       atol=1e-3, rtol=1e-5)
            & np.isclose(left["high"].to_numpy(float), right["high"].to_numpy(float),
                         atol=1e-3, rtol=1e-5)
            & np.isclose(left["low"].to_numpy(float), right["low"].to_numpy(float),
                         atol=1e-3, rtol=1e-5)
            & np.isclose(left["close"].to_numpy(float), right["close"].to_numpy(float),
                         atol=1e-3, rtol=1e-5)
        )
        volume = left["volume"].to_numpy("int64") == right["volume"].to_numpy("int64")
        out["value_mismatches"] = int((~close_px | ~volume).sum())
    for key in ("missing_rows", "extra_rows", "value_mismatches"):
        if out[key]:
            failures.append(f"{year} {timeframe}: {key}={out[key]}")
    return out


def verify_year(root: Path, year: int, failures: list[str]) -> dict:
    result: dict = {"year": year, "timeframes": {}}
    frames = {tf: _load(root, year, tf, failures) for tf in TIMEFRAMES}
    manifest_path = root / f"manifest-{year}.json"
    if not manifest_path.is_file():
        failures.append(f"{year}: missing manifest")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result["manifest_ok"] = bool(manifest.get("ok"))
        result["manifest_files"] = sorted((manifest.get("files") or {}).keys())
        if not manifest.get("ok"):
            failures.append(f"{year}: manifest is not ok")
        for tf in TIMEFRAMES:
            if tf not in (manifest.get("files") or {}):
                failures.append(f"{year}: manifest has no {tf} file")

    for tf, frame in frames.items():
        if frame is None:
            continue
        stats = _structural(frame, year, tf, failures)
        result["timeframes"][tf] = stats

    base = frames["5m"]
    if base is None or base.empty:
        failures.append(f"{year}: no 5m rows, cannot verify the other timeframes")
        return result

    first = pd.to_datetime(int(base["ts"].min()), unit="s", utc=True).tz_convert(KARACHI).date()
    last = pd.to_datetime(int(base["ts"].max()), unit="s", utc=True).tz_convert(KARACHI).date()
    result["first_date"] = first.isoformat()
    result["last_date"] = last.isoformat()
    if year == 2021 and first.isoformat() < FIRST_DATE:
        failures.append(f"{year}: first date {first} is before {FIRST_DATE}")

    daily = frames["1D"]
    if daily is not None:
        expected = _daily_aggregate(base)
        result["1D_vs_5m"] = _compare(expected, daily, year, "1D", failures)
        days = pd.to_datetime(daily["ts"].astype("int64"), unit="s", utc=True).dt.tz_convert(KARACHI)
        weekend = int((days.dt.weekday >= 5).sum())
        result["1D_weekend_rows"] = weekend
        if weekend:
            failures.append(f"{year} 1D: {weekend} weekend rows")

    for tf in ("15m", "30m", "60m"):
        frame = frames[tf]
        if frame is None:
            continue
        expected = _resampled_aggregate(base, tf)
        result[f"{tf}_vs_5m"] = _compare(expected, frame, year, tf, failures)
    return result


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/verify_intraday_history.py")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(ROOT / "data" / "history"))
    parser.add_argument("--out", default=str(ROOT / "data" / "research" /
                                             "intraday_history_verification.json"))
    parser.add_argument("--years", default="2021,2022,2023,2024,2025,2026")
    args = parser.parse_args(argv)
    root = Path(args.data)
    years = [int(value) for value in args.years.split(",") if value.strip()]
    failures: list[str] = []
    report = {
        "ok": False,
        "archive_root": str(root),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "timeframes": list(TIMEFRAMES),
        "years": {},
        "failures": failures,
        "note": "The verifier reads all partitions and reproduces 1D/15m/30m/60m "
                "from 5m. It never repairs or fills a bar.",
    }
    for year in years:
        report["years"][str(year)] = verify_year(root, year, failures)
    report["ok"] = not failures
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_jsonable(report), indent=2, sort_keys=True),
                   encoding="utf-8")
    print(json.dumps({
        "ok": report["ok"],
        "out": str(out),
        "years": list(report["years"]),
        "failures": failures[:20],
        "failure_count": len(failures),
    }, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
