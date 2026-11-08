#!/usr/bin/env python3
"""CLOUD-ONLY three-year daily context for the KMIALL long study.

This is NOT a backtest of the intraday strategies. It answers the two
questions the owner's specification puts beside them, using the only
three-year panel that actually exists in this repository: daily OHLCV.

  1. Liquidity: the 30-day median traded value of every KMIALL name, and
     how much of the universe clears the live 5 million rupee floor.
  2. Target feasibility: if a name is entered at the next day's open, how
     often does +2.00% trade before -1.00% within 1, 5 and 10 sessions?
     The intraday holding law cannot be reconstructed from daily bars, so
     this is a forward-path base rate, not a strategy result.

Daily bars cannot order a high and a low inside the same session. When both
levels are touched on the same day the sample is counted as a stop, the
conservative direction, and the report says so.

Run only in GitHub Actions. The guard refuses any other host.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src import config  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402

TARGET = config.TARGET_PCT
STOP = config.KALMAN_STOP_PCT
HORIZONS = (1, 5, 10)
MAX_HORIZON = max(HORIZONS)


def _atr14(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prior = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prior),
                                           np.abs(low - prior)))
    return pd.Series(tr).ewm(alpha=1.0 / 14.0, adjust=False).mean().to_numpy()


def _percentiles(values: np.ndarray, points=(10, 25, 50, 75, 90)) -> dict:
    values = values[np.isfinite(values)]
    if len(values) == 0:
        return {}
    return {f"p{point}": round(float(np.percentile(values, point)), 6)
            for point in points}


def _summarize(frame: pd.DataFrame, horizon: int) -> dict:
    if frame.empty:
        return {"samples": 0}
    target = ((frame["hit"] == "target") & (frame["day"] <= horizon)).sum()
    stop = ((frame["hit"] == "stop") & (frame["day"] <= horizon)).sum()
    neither = len(frame) - int(target) - int(stop)
    resolved = int(target) + int(stop)
    target_days = frame[(frame["hit"] == "target")
                        & (frame["day"] <= horizon)]["day"]
    return {
        "samples": int(len(frame)),
        "target": int(target),
        "stop": int(stop),
        "neither": int(neither),
        "target_rate_all": round(float(target) / len(frame), 4),
        "target_rate_resolved": (round(float(target) / resolved, 4)
                                 if resolved else None),
        "avg_days_to_target": (round(float(target_days.mean()), 2)
                               if len(target_days) else None),
    }


def _quartile_table(frame: pd.DataFrame, column: str, horizon: int,
                    label: str) -> list[dict]:
    if frame.empty:
        return []
    try:
        buckets = pd.qcut(frame[column], 4, labels=False, duplicates="drop")
    except ValueError:
        return []
    out = []
    for bucket in sorted(buckets.dropna().unique()):
        group = frame[buckets == bucket]
        row = _summarize(group, horizon)
        row.update({
            "quartile": int(bucket) + 1,
            "label": label,
            "median_value": round(float(group[column].median()), 6),
            "min_value": round(float(group[column].min()), 6),
            "max_value": round(float(group[column].max()), 6),
        })
        out.append(row)
    return out


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/backtest_eleven_context.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path,
                        default=Path("data/eod_dataset_10y.csv.gz"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--years", type=int, default=3)
    args = parser.parse_args(argv)

    if not args.dataset.is_file():
        print(f"dataset not found: {args.dataset}. The ten-year panel is "
              "gitignored; build it in Actions rather than inventing it (SO-3).")
        return 1

    from src.backtest.dataset import load_universe

    universe = load_universe()
    frame = pd.read_csv(
        args.dataset,
        usecols=["date", "symbol", "open", "high", "low", "close", "volume"],
    )
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["symbol"].isin(universe)]
    frame = frame.dropna(subset=["date", "open", "high", "low", "close",
                                 "volume"])
    frame = frame[(frame["open"] > 0) & (frame["high"] > 0)
                  & (frame["low"] > 0) & (frame["close"] > 0)
                  & (frame["volume"] > 0)]
    if frame.empty:
        print("No usable KMIALL rows in the panel; nothing is measured (SO-3).")
        return 1
    frame["high"] = frame[["open", "high", "close"]].max(axis=1)
    frame["low"] = frame[["open", "low", "close"]].min(axis=1)
    frame = frame.sort_values(["symbol", "date"])

    end = frame["date"].max()
    start = end - pd.DateOffset(years=args.years) + pd.Timedelta(days=1)
    window = frame[frame["date"] >= start].copy()
    if window.empty:
        print("The requested window holds no rows; nothing is measured (SO-3).")
        return 1

    samples: list[dict] = []
    for symbol, group in window.groupby("symbol", sort=False):
        group = group.sort_values("date")
        if len(group) < 30 + MAX_HORIZON + 2:
            continue
        open_px = group["open"].to_numpy(dtype=float)
        high = group["high"].to_numpy(dtype=float)
        low = group["low"].to_numpy(dtype=float)
        close = group["close"].to_numpy(dtype=float)
        volume = group["volume"].to_numpy(dtype=float)
        atr = _atr14(high, low, close)
        turnover = close * volume
        liquidity = pd.Series(turnover).rolling(30, min_periods=30).median(
        ).to_numpy()
        normalized_atr = atr / np.where(close > 0, close, np.nan)
        for i in range(30, len(group) - MAX_HORIZON - 1):
            entry = float(open_px[i + 1])
            if (not math.isfinite(entry) or entry <= 0
                    or not math.isfinite(liquidity[i])
                    or not math.isfinite(normalized_atr[i])):
                continue
            target = entry * (1.0 + TARGET)
            stop = entry * (1.0 - STOP)
            # An open already beyond a level is not a valid entry sample.
            if entry >= target or entry <= stop:
                continue
            hit = None
            day = None
            for k in range(1, MAX_HORIZON + 1):
                if low[i + k] <= stop and high[i + k] >= target:
                    hit, day = "stop", k
                    break
                if low[i + k] <= stop:
                    hit, day = "stop", k
                    break
                if high[i + k] >= target:
                    hit, day = "target", k
                    break
            samples.append({
                "symbol": symbol,
                "liquidity": float(liquidity[i]),
                "normalized_atr": float(normalized_atr[i]),
                "hit": hit or "neither",
                "day": int(day) if day is not None else 0,
            })

    if not samples:
        print("The daily panel produced no forward samples; nothing is "
              "measured (SO-3).")
        return 1

    table = pd.DataFrame(samples)
    horizons = {str(h): _summarize(table, h) for h in HORIZONS}
    liquidity_values = table["liquidity"].to_numpy(dtype=float)
    atr_values = table["normalized_atr"].to_numpy(dtype=float) * 100.0
    report = {
        "generated": datetime.now(KARACHI).isoformat(),
        "study": "eleven_daily_context_v1",
        "what_this_is": (
            "A three-year daily forward-path base rate and liquidity profile. "
            "It is NOT a backtest of the intraday strategies: daily bars "
            "cannot reconstruct their 5m/15m entries or the intraday order of "
            "the target and the stop."),
        "window": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "years": args.years,
            "sessions": int(window["date"].nunique()),
            "symbols": int(table["symbol"].nunique()),
            "samples": int(len(table)),
        },
        "liquidity": {
            "measure": "30-day median daily traded value (close x volume), PKR",
            "percentiles": _percentiles(liquidity_values),
            "share_above_live_floor": round(
                float((liquidity_values
                       >= config.MIN_SESSION_TRADED_VALUE).mean()), 4),
            "live_floor_pkr": config.MIN_SESSION_TRADED_VALUE,
        },
        "atr": {
            "measure": "14-day ATR as a percent of close",
            "percentiles": _percentiles(atr_values),
        },
        "horizons": horizons,
        "by_liquidity_quartile": _quartile_table(
            table, "liquidity", 5, "30-day median traded value"),
        "by_atr_quartile": _quartile_table(
            table, "normalized_atr", 5, "14-day normalized ATR"),
        "limitations": [
            "This measures a daily forward path, not the 5m/15m intraday "
            "rules. It cannot support a claim that any of the eleven "
            "strategies would have made or lost money over three years.",
            "When a session touches both +2% and -1%, the sample is counted "
            "as a stop because daily bars do not reveal which came first.",
            "Samples overlap: every eligible day is used, so consecutive "
            "forward windows share sessions.",
            "The 5-year/10-year EOD panel is not a tick archive; opening "
            "auction prints and intraday halts are not represented.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"window": report["window"],
                      "horizons": report["horizons"]}, indent=2))
    print(f"report: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
