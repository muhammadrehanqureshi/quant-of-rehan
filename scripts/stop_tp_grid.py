#!/usr/bin/env python3
"""Stop/TP expectancy-surface grid on the 5-year KMIALL dataset (GITHUB ACTIONS, SO-21).

Implements RESEARCH_AUDIT.md section 7 exactly:
  stops    = {-0.5, -0.75, -1.0, -1.25, -1.5, -2.0, -2.5, -3.0, -4.0} %
  targets  = {+0.5, +1.0, +1.5, +2.0, +2.5, +3.0} %
  fills    = engine.py semantics unchanged (T close signal, T+1 open entry,
             TP exact even on gap-up, SL stop-or-gap-through at open,
             same-bar SL wins, max_hold 3, print-chain invalid screen)
  costs    = 22.4 bps per side round trip (2 sides) + 15% CGT on winners,
             slippage sensitivity at +0 / +5 / +10 bps per side
  robust   = plateau: a cell qualifies only if at least 3 of its 4 grid
             neighbors have positive net expectancy with overlapping
             bootstrap 95% CIs (1,000 resamples, fixed seed)

Population: ALL placeholder-baseline entries (close>MA20 and volume>20d
median at T, the same 74,654-signal population as the smoke run). This is
the entry-quality ceiling question "where in (stop, target) space does the
ENGINE's law stop losing", NOT a strategy claim. The best-MAE subset
comparison (audit section 13.E.10) runs after the single-variable filters.

Exit outcomes depend only on (tp, sl), never on costs, so each cell's
engine run happens once and the three slippage levels re-cost the same
trades with the engine's own net-return formula.

Outputs (gitignored under /data/):
    data/stop_tp_grid/results.json   full per-cell records
    data/stop_tp_grid/report.md      the expectancy surface, readable

Usage:  python scripts/stop_tp_grid.py [--workers 4]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

from src.backtest.engine import run_backtest, DEFAULT_COST_SIDE_BPS, DEFAULT_CGT_RATE  # noqa: E402

KARACHI = timezone(timedelta(hours=5))  # SO-8

STOPS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0]        # % (positive)
TARGETS = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]                        # % (positive)
SLIPPAGES = [0.0, 5.0, 10.0]                                    # bps per side
N_BOOT = 1000
BOOT_SEED = 20261006
OUT_DIR = ROOT / "data" / "stop_tp_grid"
DATASET = ROOT / "data" / "eod_history_kmi.csv.gz"


def placeholder_signals(df: pd.DataFrame) -> list[tuple]:
    """Same population as scripts/smoke_backtest.py (import-shared logic)."""
    from scripts.smoke_backtest import placeholder_signals as sig_fn
    return sig_fn(df)


def bootstrap_ci(x: np.ndarray, n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> tuple[float, float]:
    """95% percentile bootstrap CI of the mean (fixed seed, deterministic)."""
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    n = len(x)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        means[b] = x[idx].mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def reapply_costs(gross: np.ndarray, cost_side_bps: float,
                  cgt_rate: float = DEFAULT_CGT_RATE) -> np.ndarray:
    """The engine's exact net-return formula, vectorized.

    net = gross - 2 * cost_side_bps / 1e4 ; if net > 0: net *= (1 - CGT).
    """
    net = gross - 2.0 * cost_side_bps / 1e4
    net = np.where(net > 0, net * (1.0 - cgt_rate), net)
    return net


def run_grid(df: pd.DataFrame, signals: list[tuple], workers: int) -> list[dict]:
    """One engine run per (stop, target) cell; slippage re-costs after."""
    cells: list[dict] = []
    total = len(STOPS) * len(TARGETS)
    done = 0
    for sl in STOPS:
        for tp in TARGETS:
            trades, _summary = run_backtest(df, signals, tp=tp / 100.0,
                                            sl=sl / 100.0, max_hold=3)
            gross = trades["gross_ret"].to_numpy(dtype=float)
            invalid = trades["data_invalid"].to_numpy(dtype=bool) \
                if "data_invalid" in trades.columns else np.zeros(len(gross), bool)
            outcomes = trades["outcome"].to_numpy()
            bars = trades["bars_held"].to_numpy(dtype=float)
            rec = {
                "sl_pct": sl, "tp_pct": tp,
                "n_trades": int(len(gross)),
                "n_invalid": int(invalid.sum()),
                "gross_valid": gross[~invalid],
                "outcomes": outcomes[~invalid],
                "bars": float(np.mean(bars[~invalid])) if (~invalid).any() else float("nan"),
                "rate_tp": float((outcomes[~invalid] == "TP").mean()),
                "rate_sl": float((outcomes[~invalid] == "SL").mean()),
                "rate_timeout": float((outcomes[~invalid] == "TIMEOUT").mean()),
            }
            cells.append(rec)
            done += 1
            print(f"[{done:>2}/{total}] sl={sl:>4}% tp={tp:>3}%  "
                  f"n={rec['n_trades']:,} invalid={rec['n_invalid']:,}  "
                  f"TP {rec['rate_tp']:.3f} SL {rec['rate_sl']:.3f} "
                  f"TO {rec['rate_timeout']:.3f}", flush=True)
    return cells


def add_cost_levels(cells: list[dict]) -> None:
    """Bootstrap CI + expectancy per slippage level, in place."""
    for rec in cells:
        rec["costs"] = {}
        for slip in SLIPPAGES:
            net = reapply_costs(rec["gross_valid"], DEFAULT_COST_SIDE_BPS + slip)
            lo, hi = bootstrap_ci(net)
            rec["costs"][f"{slip:.0f}bps"] = {
                "expectancy_net": float(net.mean()),
                "median_net": float(np.median(net)),
                "win_rate": float((net > 0).mean()),
                "ci_lo": lo, "ci_hi": hi,
            }
        del rec["gross_valid"]  # keep the JSON small
        del rec["outcomes"]


def surface_grid(cells: list[dict], slip_key: str) -> tuple[list[list[float | None]], dict]:
    """Expectancy matrix [stop][target] + plateau qualification per cell."""
    lookup = {(r["sl_pct"], r["tp_pct"]): r for r in cells}
    grid: list[list[float | None]] = []
    qual: dict[str, bool] = {}
    for sl in STOPS:
        row: list[float | None] = []
        for tp in TARGETS:
            rec = lookup[(sl, tp)]
            exp = rec["costs"][slip_key]["expectancy_net"]
            row.append(exp)
        grid.append(row)
    for sl in STOPS:
        for tp in TARGETS:
            rec = lookup[(sl, tp)]
            exp = rec["costs"][slip_key]["expectancy_net"]
            ci = (rec["costs"][slip_key]["ci_lo"], rec["costs"][slip_key]["ci_hi"])
            s_i, t_i = STOPS.index(sl), TARGETS.index(tp)
            neighbor_pos = 0
            for ds, dt in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ns, nt = s_i + ds, t_i + dt
                if not (0 <= ns < len(STOPS) and 0 <= nt < len(TARGETS)):
                    continue  # edge cells count only existing neighbors
                nb = lookup[(STOPS[ns], TARGETS[nt])]["costs"][slip_key]
                if nb["expectancy_net"] > 0:
                    overlaps = ci[0] <= nb["ci_hi"] and nb["ci_lo"] <= ci[1]
                    if overlaps:
                        neighbor_pos += 1
            qual[f"sl{sl}_tp{tp}"] = neighbor_pos >= 3
            rec["costs"][slip_key]["qualifying_neighbors"] = neighbor_pos
            rec["costs"][slip_key]["plateau"] = qual[f"sl{sl}_tp{tp}"] and exp > 0
    return grid, qual


def render_report(cells: list[dict], meta: dict) -> str:
    lookup = {(r["sl_pct"], r["tp_pct"]): r for r in cells}
    lines: list[str] = []
    lines.append("# Stop/TP expectancy surface (5-year KMIALL, real costs)")
    lines.append("")
    lines.append(f"Generated: {datetime.now(KARACHI).isoformat(timespec='seconds')} Karachi (SO-8)")
    lines.append(f"Dataset: {meta['dataset']}")
    lines.append(f"Rows: {meta['rows']:,} | symbols: {meta['symbols']} | "
                 f"sessions: {meta['start']} .. {meta['end']}")
    lines.append(f"Population: ALL placeholder-baseline entries, n={meta['signals']:,} "
                 "(close>MA20 & volume>20d median at T; entry T+1 open; NOT a strategy claim)")
    lines.append("Fills: engine.py unchanged (TP exact, SL gap-through at open, "
                 "same-bar SL wins, max_hold 3, print-chain invalid screen).")
    lines.append(f"Costs: {DEFAULT_COST_SIDE_BPS} bps/side round trip + 15% CGT on winners; "
                 "slippage added per side. Invalid prints excluded everywhere.")
    lines.append("")
    for slip in SLIPPAGES:
        key = f"{slip:.0f}bps"
        slip_note = "no slippage" if slip == 0 else f"slippage +{slip:.0f} bps per side"
        lines.append(f"## Net expectancy per trade (%), {slip_note}")
        lines.append("")
        header = "| stop \\ target | " + " | ".join(f"+{t}%" for t in TARGETS) + " |"
        lines.append(header)
        lines.append("|" + "---|" * (len(TARGETS) + 1))
        for sl in STOPS:
            row = [f"-{sl}%"]
            for tp in TARGETS:
                rec = lookup[(sl, tp)]
                c = rec["costs"][key]
                mark = " *" if c.get("plateau") else ""
                row.append(f"{c['expectancy_net'] * 100:+.3f}{mark}")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
        lines.append("(*) plateau cell: positive expectancy AND at least 3 of 4 grid "
                     "neighbors positive with overlapping bootstrap 95% CIs.")
        best = max(
            (r for r in cells if r["costs"][key]["expectancy_net"] == max(
                x["costs"][key]["expectancy_net"] for x in cells)),
            key=lambda r: (r["sl_pct"], r["tp_pct"]))
        pl = [r for r in cells if r["costs"][key].get("plateau")]
        lines.append("")
        if pl:
            lines.append(f"Qualifying plateau cells at {slip_note}: "
                         + ", ".join(f"sl{r['sl_pct']}/tp{r['tp_pct']}" for r in pl))
        else:
            lines.append(f"Qualifying plateau cells at {slip_note}: NONE")
        law = lookup[(1.0, 2.0)]["costs"][key]
        lines.append(f"Law cell (SL -1.0% / TP +2.0%): expectancy "
                     f"{law['expectancy_net'] * 100:+.3f}%/trade, win rate "
                     f"{law['win_rate'] * 100:.1f}%, CI "
                     f"[{law['ci_lo'] * 100:+.3f}, {law['ci_hi'] * 100:+.3f}]%")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/stop_tp_grid.py")
    ap = argparse.ArgumentParser(description="Stop/TP grid (audit section 7)")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    ap.add_argument("--workers", type=int, default=1,
                    help="kept for compatibility; cells run sequentially")
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"dataset missing: {args.dataset}")
        return 1
    df = pd.read_csv(args.dataset, parse_dates=["date"])
    meta = {
        "dataset": str(args.dataset.name),
        "rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "start": str(df["date"].min().date()),
        "end": str(df["date"].max().date()),
        "signals": 0,
    }
    print(f"Loaded {meta['rows']:,} rows, {meta['symbols']} symbols, "
          f"{meta['start']} .. {meta['end']}")

    signals = placeholder_signals(df)
    meta["signals"] = len(signals)
    print(f"Placeholder-baseline signals: {len(signals):,}")

    cells = run_grid(df, signals, args.workers)
    add_cost_levels(cells)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "generated": datetime.now(KARACHI).isoformat(),
        "spec": "RESEARCH_AUDIT.md section 7",
        "meta": meta,
        "stops_pct": STOPS,
        "targets_pct": TARGETS,
        "slippage_bps_per_side": SLIPPAGES,
        "cost_side_bps": DEFAULT_COST_SIDE_BPS,
        "cgt_rate": DEFAULT_CGT_RATE,
        "n_boot": N_BOOT,
        "cells": cells,
    }
    (OUT_DIR / "results.json").write_text(
        json.dumps(results, indent=1, default=str), encoding="utf-8")

    report = render_report(cells, meta)
    (OUT_DIR / "report.md").write_text(report, encoding="utf-8")
    print(f"\nResults -> {OUT_DIR / 'results.json'}")
    print(f"Report  -> {OUT_DIR / 'report.md'}")
    print("\n" + report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
