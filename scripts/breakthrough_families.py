"""Breakthrough 1.0: families 1 and 3, plus the median-only market gate.

Research only. This script does not read the live signal path, does not change
`kalman_trend_flip_v1`, and promotes nothing. It runs on the ten-year KMIALL
daily panel with the locked splits in `src.config`:

    discovery 2016-10-29 .. 2024-06-30
    validation 2024-07-01 .. 2025-12-31
    test      2026-01-01 .. 2026-10-30 (locked)

The registry rows for this family were written before any result existed by
`scripts/preregister_breakthrough.py`. This runner reads the exact grids from
that pre-registration and does not widen them.

Family 1: top 50 names by 60 day median traded value, close within 2, 3 or 5
percent of the 252 day high, volume at least 1.5 times its 20 day average,
entry at the next open, hold 2, 3 or 5 closes, with no bracket or a 2/1
bracket. Family 3: the same top 50, close above the 50 day average, a 3 day
drop of at least 3, 4 or 5 percent, entry at the next open, exit on a 2
percent bounce or after 3 closes. Family 2 applies a market gate to the F1
base and the F3 base.

The panel has no KSE100 series. The brief's fallback is used: the gate is the
median KMIALL stock above its 50 day average, and the two KSE100 legs are
reported as NOT MEASURED rather than invented. That fallback is named in every
row that uses it.

No local execution: `guard_cloud_backtest` refuses this script outside GitHub
Actions, exactly like the other research entry points.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from src import config
from src.ci.local_only import guard_cloud_backtest
from src.research.outcome_labeler import (
    LabelParams,
    MISSION_COST_SIDE_BPS,
    net_after_costs,
)

KARACHI_OFFSET = "+05:00"

F1_PROXIMITY = (2.0, 3.0, 5.0)
F1_HOLDS = (2, 3, 5)
F1_BRACKETS = (None, "2/1")
F3_DROPS = (3.0, 4.0, 5.0)
F3_HOLD = 3
F3_BOUNCE = 0.02

TOP_N = 50
VALUE_LOOKBACK = 60
HIGH_LOOKBACK = 252
VOLUME_LOOKBACK = 20
VOLUME_MULTIPLE = 1.5


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return (round(max(0.0, centre - half), 4),
            round(min(1.0, centre + half), 4))


def day_clustered_lower(trades: pd.DataFrame, resamples: int = 2000,
                        seed: int = 0) -> float | None:
    """Bootstrap the mean net return by SIGNAL DAY, not by trade."""
    if trades.empty:
        return None
    groups = [g["net_ret"].to_numpy(dtype=float)
              for _, g in trades.groupby("signal_date", sort=False)]
    if not groups:
        return None
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(resamples):
        picks = rng.integers(0, len(groups), size=len(groups))
        values = np.concatenate([groups[i] for i in picks])
        means.append(float(values.mean()))
    return round(float(np.percentile(means, 2.5)), 6)


def summarize(trades: pd.DataFrame, *, bracket: bool,
              tp: float, sl: float) -> dict:
    if trades is None or trades.empty:
        return {"n": 0, "note": "no trades"}
    nets = trades["net_ret"].astype(float)
    wins = int((nets > 0).sum())
    n = int(len(nets))
    lo, hi = wilson(wins, n)
    first = pd.to_datetime(trades["signal_date"]).min()
    last = pd.to_datetime(trades["signal_date"]).max()
    months = max(1.0, (last - first).days / 30.4375)
    be = None
    if bracket:
        params = LabelParams(tp=tp, sl=sl)
        win_net = net_after_costs(tp, params)
        loss_net = net_after_costs(-sl, params)
        span = win_net - loss_net
        be = round(-loss_net / span, 4) if span > 0 else 1.0
    return {
        "n": n,
        "wins": wins,
        "losses": n - wins,
        "win_rate": round(wins / n, 4),
        "wilson_95": [lo, hi],
        "break_even_win_rate": be,
        "edge_vs_break_even": (round(wins / n - be, 4)
                               if be is not None else None),
        "net_expectancy": round(float(nets.mean()), 6),
        "median_net": round(float(nets.median()), 6),
        "worst": round(float(nets.min()), 6),
        "p05": round(float(nets.quantile(0.05)), 6),
        "bootstrap_lower_2.5": day_clustered_lower(trades),
        "trades_per_month": round(n / months, 2),
        "first_signal": str(first.date()),
        "last_signal": str(last.date()),
        "days": int(trades["signal_date"].nunique()),
        "cost_side_bps": MISSION_COST_SIDE_BPS,
        "cgt_rate": config.CGT_RATE,
    }


def split_masks(dates: pd.Series) -> dict[str, pd.Series]:
    index = dates.index
    d = pd.to_datetime(dates).reset_index(drop=True)
    masks = {
        "discovery": (d >= pd.Timestamp("2016-10-29")) &
                     (d <= pd.Timestamp(config.SELF_IMPROVE_DISCOVERY_END)),
        "validation": (d >= pd.Timestamp("2024-07-01")) &
                      (d <= pd.Timestamp(config.SELF_IMPROVE_VALIDATION_END)),
        "test": (d >= pd.Timestamp(config.SELF_IMPROVE_TEST_START)) &
                (d <= pd.Timestamp("2026-10-30")),
    }
    return {name: pd.Series(values, index=index)
            for name, values in masks.items()}


def _arrays(group: pd.DataFrame) -> dict:
    g = group.sort_values("date")
    return {
        "dates": pd.to_datetime(g["date"]).to_numpy(),
        "open": g["open"].to_numpy(dtype=float),
        "high": g["high"].to_numpy(dtype=float),
        "low": g["low"].to_numpy(dtype=float),
        "close": g["close"].to_numpy(dtype=float),
        "volume": g["volume"].to_numpy(dtype=float),
        "sma50": g["sma50"].to_numpy(dtype=float),
        "high252": g["high252"].to_numpy(dtype=float),
        "vol20": g["vol20"].to_numpy(dtype=float),
        "value60": g["value60"].to_numpy(dtype=float),
        "rank": g["value_rank"].to_numpy(dtype=float),
        "mkt_gate": g["mkt_gate"].to_numpy(dtype=bool),
    }


def prepare(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    df["traded_value"] = df["close"].astype(float) * df["volume"].astype(float)
    grouped = df.groupby("symbol", observed=True)
    df["value60"] = grouped["traded_value"].transform(
        lambda s: s.rolling(VALUE_LOOKBACK, min_periods=VALUE_LOOKBACK).median())
    df["sma50"] = grouped["close"].transform(
        lambda s: s.rolling(50, min_periods=50).mean())
    df["high252"] = grouped["high"].transform(
        lambda s: s.rolling(HIGH_LOOKBACK, min_periods=HIGH_LOOKBACK).max())
    df["vol20"] = grouped["volume"].transform(
        lambda s: s.rolling(VOLUME_LOOKBACK, min_periods=VOLUME_LOOKBACK).mean())
    # Cross sectional rank per day: 1 is the most liquid name that day.
    df["value_rank"] = df.groupby("date")["value60"].rank(
        method="first", ascending=False)
    # The gate is the median stock's close / SMA50. The panel has no KSE100.
    ratio = df["close"].astype(float) / df["sma50"].astype(float)
    med = ratio.groupby(df["date"]).transform("median")
    df["mkt_gate"] = med > 1.0
    return df


def f1_trades(df: pd.DataFrame, proximity: float, hold: int,
              bracket: str | None) -> pd.DataFrame:
    rows = []
    use_bracket = bracket == "2/1"
    for symbol, group in df.groupby("symbol", observed=True):
        a = _arrays(group)
        n = len(a["dates"])
        if n < max(HIGH_LOOKBACK, VALUE_LOOKBACK) + 2:
            continue
        for i in range(HIGH_LOOKBACK, n - 1):
            if not np.isfinite(a["high252"][i]) or a["high252"][i] <= 0:
                continue
            if (not np.isfinite(a["rank"][i]) or a["rank"][i] > TOP_N or
                    not np.isfinite(a["value60"][i])):
                continue
            if a["close"][i] / a["high252"][i] - 1.0 < -proximity / 100.0:
                continue
            if (not np.isfinite(a["vol20"][i]) or a["vol20"][i] <= 0 or
                    a["volume"][i] < VOLUME_MULTIPLE * a["vol20"][i]):
                continue
            entry = a["open"][i + 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            end = i + 1 + hold
            if end >= n:
                continue
            exit_price = None
            outcome = "time"
            if use_bracket:
                tp = entry * (1.0 + 0.02)
                sl = entry * (1.0 - 0.01)
                for j in range(i + 1, end):
                    high, low, op = a["high"][j], a["low"][j], a["open"][j]
                    if high >= tp and low <= sl:
                        exit_price, outcome = (op if op < sl else sl), "stop"
                        break
                    if low <= sl:
                        exit_price, outcome = (op if op < sl else sl), "stop"
                        break
                    if high >= tp:
                        exit_price, outcome = tp, "target"
                        break
            if exit_price is None:
                exit_price = a["close"][end - 1]
                outcome = "time"
            gross = exit_price / entry - 1.0
            params = LabelParams(tp=0.02 if use_bracket else 0.0,
                                 sl=0.01 if use_bracket else 0.0,
                                 max_hold=hold)
            rows.append({
                "symbol": symbol,
                "signal_date": a["dates"][i],
                "entry_date": a["dates"][i + 1],
                "entry": float(entry),
                "exit": float(exit_price),
                "outcome": outcome,
                "gross_ret": float(gross),
                "net_ret": float(net_after_costs(gross, params)),
                "hold": hold,
                "bracket": bracket or "none",
                "proximity": proximity,
            })
    return pd.DataFrame(rows)


def f3_trades(df: pd.DataFrame, drop_pct: float) -> pd.DataFrame:
    rows = []
    for symbol, group in df.groupby("symbol", observed=True):
        a = _arrays(group)
        n = len(a["dates"])
        if n < 60:
            continue
        close = a["close"]
        drop = np.full(n, np.nan)
        drop[3:] = close[3:] / close[:-3] - 1.0
        for i in range(50, n - 1):
            if not np.isfinite(a["sma50"][i]) or close[i] <= a["sma50"][i]:
                continue
            if not np.isfinite(a["rank"][i]) or a["rank"][i] > TOP_N:
                continue
            if not np.isfinite(drop[i]) or drop[i] > -drop_pct / 100.0:
                continue
            entry = a["open"][i + 1]
            if not np.isfinite(entry) or entry <= 0:
                continue
            end = min(i + 1 + F3_HOLD, n)
            exit_price = close[end - 1]
            outcome = "time"
            for j in range(i + 1, end):
                if close[j] >= entry * (1.0 + F3_BOUNCE):
                    exit_price, outcome = close[j], "bounce"
                    break
            gross = exit_price / entry - 1.0
            rows.append({
                "symbol": symbol,
                "signal_date": a["dates"][i],
                "entry_date": a["dates"][i + 1],
                "entry": float(entry),
                "exit": float(exit_price),
                "outcome": outcome,
                "gross_ret": float(gross),
                "net_ret": float(net_after_costs(gross, LabelParams(
                    tp=0.0, sl=0.0, max_hold=F3_HOLD))),
                "drop_pct": drop_pct,
            })
    return pd.DataFrame(rows)


def run_variant(name: str, family: str, trades: pd.DataFrame, *,
                bracket: bool, tp: float, sl: float,
                params: dict) -> dict:
    masks = split_masks(trades["signal_date"])
    discovery = trades.loc[masks["discovery"]]
    dsum = summarize(discovery, bracket=bracket, tp=tp, sl=sl)
    n = dsum.get("n", 0)
    decision = "KEEP_DISCOVERY"
    if n < config.SELF_IMPROVE_MIN_DISCOVERY_TRADES:
        decision = "KILL_FEW_TRADES"
    elif bracket and dsum["break_even_win_rate"] is not None and \
            dsum["win_rate"] < dsum["break_even_win_rate"]:
        decision = "KILL_NEGATIVE_EDGE"
    elif dsum["net_expectancy"] <= config.SELF_IMPROVE_DISCOVERY_NET_FLOOR:
        decision = "KILL_NO_EXPECTANCY"
    row = {
        "name": name, "family": family, "params": params,
        "discovery": dsum, "decision": decision,
        "validation": None, "test": None,
    }
    if decision != "KEEP_DISCOVERY":
        return row
    validation = trades.loc[masks["validation"]]
    vsum = summarize(validation, bracket=bracket, tp=tp, sl=sl)
    vsum["keep"] = bool(
        vsum["n"] >= config.SELF_IMPROVE_MIN_DISCOVERY_TRADES and
        (vsum["net_expectancy"] or 0) > 0 and
        (not bracket or (
            vsum["break_even_win_rate"] is not None and
            (vsum["win_rate"] or 0) >= vsum["break_even_win_rate"])))
    row["validation"] = vsum
    if vsum["keep"]:
        test = trades.loc[masks["test"]]
        row["test"] = summarize(test, bracket=bracket, tp=tp, sl=sl)
        row["decision"] = "SURVIVED_TO_TEST"
    else:
        row["decision"] = "KILL_VALIDATION"
    return row


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/breakthrough_families.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resamples", type=int, default=2000)
    args = parser.parse_args(argv)

    if not args.dataset.is_file():
        print(f"::error::dataset missing: {args.dataset}", file=sys.stderr)
        return 1
    panel = pd.read_csv(args.dataset, parse_dates=["date"])
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    if not required <= set(panel.columns):
        print(f"::error::dataset columns missing: {sorted(required - set(panel.columns))}",
              file=sys.stderr)
        return 1
    panel = prepare(panel)
    # The module-level default is 2000; the CLI makes the run explicit.
    global day_clustered_lower
    original = day_clustered_lower
    day_clustered_lower = lambda trades, resamples=args.resamples, seed=0: original(
        trades, resamples=resamples, seed=seed)

    variants = []
    f1_cache: dict[tuple[float, int, str | None], pd.DataFrame] = {}
    for proximity in F1_PROXIMITY:
        for hold in F1_HOLDS:
            for bracket in F1_BRACKETS:
                key = (proximity, hold, bracket)
                trades = f1_cache.get(key)
                if trades is None:
                    trades = f1_trades(panel, proximity, hold, bracket)
                    f1_cache[key] = trades
                variants.append(run_variant(
                    f"F1 52w high {proximity:g}pct, hold {hold}, "
                    f"bracket {bracket or 'none'}",
                    "F1", trades, bracket=bracket == "2/1", tp=0.02, sl=0.01,
                    params={"proximity_pct": proximity, "hold_closes": hold,
                            "bracket": bracket or "none",
                            "top_n": TOP_N, "volume_multiple": VOLUME_MULTIPLE}))

    f3_cache: dict[float, pd.DataFrame] = {}
    for drop in F3_DROPS:
        trades = f3_cache.get(drop)
        if trades is None:
            trades = f3_trades(panel, drop)
            f3_cache[drop] = trades
        variants.append(run_variant(
            f"F3 pullback drop {drop:g}pct",
            "F3", trades, bracket=False, tp=0.0, sl=0.0,
            params={"drop_pct": drop, "drop_days": 3,
                    "bounce_pct": F3_BOUNCE * 100, "hold_closes": F3_HOLD,
                    "top_n": TOP_N}))

    # Family 2: the brief's fallback, because this panel has no KSE100.
    gate_note = ("KSE100 legs NOT MEASURED: the daily panel has no index "
                 "series. Gate is the median KMIALL stock above its 50 day "
                 "average, as the brief permits.")
    for base_name, base_trades, bracket, tp, sl in (
        ("F1 base 3pct hold 3 bracket 2/1",
         f1_cache[(3.0, 3, "2/1")], True, 0.02, 0.01),
        ("F3 base drop 4pct", f3_cache[4.0], False, 0.0, 0.0),
    ):
        if base_trades.empty:
            continue
        # The gate is joined by signal date from the panel's daily median.
        gate = (panel[["date", "mkt_gate"]].drop_duplicates("date")
                .set_index("date")["mkt_gate"])
        gated = base_trades.copy()
        gated["signal_date"] = pd.to_datetime(gated["signal_date"])
        gated = gated[gated["signal_date"].map(gate).fillna(False)]
        variants.append(run_variant(
            f"F2 median-only gate on {base_name}", "F2", gated,
            bracket=bracket, tp=tp, sl=sl,
            params={"gate": "median KMIALL close above SMA50",
                    "kse100": "NOT MEASURED", "base": base_name,
                    "note": gate_note}))

    report = {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "dataset_rows": int(len(panel)),
        "symbols": int(panel["symbol"].nunique()),
        "window": [str(panel["date"].min().date()),
                   str(panel["date"].max().date())],
        "splits": {
            "discovery": ["2016-10-29", config.SELF_IMPROVE_DISCOVERY_END],
            "validation": ["2024-07-01", config.SELF_IMPROVE_VALIDATION_END],
            "test": [config.SELF_IMPROVE_TEST_START, "2026-10-30"],
        },
        "cost_side_bps": MISSION_COST_SIDE_BPS,
        "cgt_rate": config.CGT_RATE,
        "min_discovery_trades": config.SELF_IMPROVE_MIN_DISCOVERY_TRADES,
        "kse100": "NOT MEASURED (no index series in the daily panel)",
        "variants": variants,
        "family_5": "BLOCKED: DATA (no dated event calendar)",
        "family_6": "BLOCKED: DATA (no sector field in universe_kmiall.json)",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps({
        "variants": len(variants),
        "survivors": [v["name"] for v in variants
                      if v["decision"] == "SURVIVED_TO_TEST"],
        "out": str(args.out),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
