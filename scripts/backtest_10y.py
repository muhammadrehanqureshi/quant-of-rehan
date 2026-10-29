"""Ten-year, whole-universe EOD backtest of the daily scanner analogue.

SO-21: this run belongs on GitHub Actions minutes, never the owner's PC;
the entry point is guarded with guard_cloud_backtest and refuses locally.

Pipeline:

1. Load the ten-year panel built by scripts/build_backtest_dataset.py
   (mkt_summary archive, OHLCV, one row per symbol per session).
2. Score every session of every symbol with the SAME five component
   families and weights the deployed scanner uses
   (src/backtest/daily_strategy.py - the declared daily analogue), decide
   signals at close T, enter at the open of T+1.
3. Simulate every signal with src/backtest/engine.py: target, stop and
   timeout exits, round-trip costs, capital-gains tax on winners, and the
   corporate-action screen that refuses to book band-breaking prints.
4. Report per-year plus full-period statistics honestly (SO-3): counts,
   win rate, expectancy, profit factor, chronological equity and drawdown.

Signals are decided on the dataset the engine is given; nothing is
interpolated, nothing forward-filled, no year skipped silently. The report
carries the dataset summary next to the results so coverage is never
implied beyond what the crawl actually fetched.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.ci.local_only import guard_cloud_backtest

import pandas as pd

from src import config
from src.backtest.daily_strategy import ScannerParams, build_signals
from src.backtest.engine import run_backtest


def _per_year(trades: pd.DataFrame) -> dict:
    """Exit-year grouped view: counts, win rate, expectancy, PF."""
    valid = trades.loc[~trades["data_invalid"].astype(bool)].copy()
    if valid.empty:
        return {}
    valid["year"] = pd.to_datetime(valid["exit_date"]).dt.year.astype(int)
    out: dict[str, dict] = {}
    for year, rows in valid.groupby("year"):
        net = rows["net_ret"]
        gross_w = float(rows.loc[rows["gross_ret"] > 0, "gross_ret"].sum())
        gross_l = -float(rows.loc[rows["gross_ret"] <= 0, "gross_ret"].sum())
        out[str(int(year))] = {
            "trades": int(len(rows)),
            "win_rate": round(float((net > 0).mean()), 4),
            "expectancy_net": round(float(net.mean()), 6),
            "profit_factor_gross": (round(gross_w / gross_l, 4)
                                    if gross_l > 0 else "inf"),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/backtest_10y.py")
    ap = argparse.ArgumentParser(
        description="Ten-year EOD backtest of the scanner's component rules")
    ap.add_argument("--dataset", type=Path, default=Path("data/eod_dataset_10y.csv.gz"))
    ap.add_argument("--out", type=Path, default=Path("data/backtest_10y_report.json"))
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"::error::{args.dataset} is missing. Dispatch with "
              "task=both (or build-dataset) first; this job never invents "
              "data (SO-3).")
        return 1

    df = pd.read_csv(args.dataset, parse_dates=["date"])
    need = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = need - set(df.columns)
    if missing:
        print(f"::error::dataset missing column(s): {sorted(missing)}")
        return 1

    params = ScannerParams(weights=dict(config.SCORE_WEIGHTS))
    scored, mask = build_signals(df, params)
    n_signals = int(mask.sum())

    signals = list(zip(scored.loc[mask, "date"], scored.loc[mask, "symbol"]))
    trades_df, summary = run_backtest(df, signals, touch_mode="hl")

    summary["n_gate_signals"] = n_signals
    summary["per_year"] = _per_year(trades_df) if len(trades_df) else {}
    summary["params"] = params.as_dict()
    summary["gate_config"] = {
        "target_pct": config.TARGET_PCT * 100.0,
        "min_relvol": params.min_relvol,
        "min_traded_value": params.min_traded_value,
        "min_price": params.min_price,
        "max_extension": params.max_extension,
    }

    side = {
        # Side-file of scripts/build_backtest_dataset.py, written by the
        # same run that produced the dataset: the coverage the panel
        # actually has, next to the results that claim it (SO-3).
        "dataset_summary": None,
    }
    summary_path = args.dataset.with_suffix("").with_suffix(".summary")
    if summary_path.is_file():
        summary["dataset_summary"] = json.loads(summary_path.read_text("utf-8"))
    if trades_df is not None and len(trades_df):
        trades_path = args.out.with_name(args.out.stem + "_trades.csv")
        trades_df.to_csv(trades_path, index=False)
        summary["trades_file"] = trades_path.name

    args.out.write_text(json.dumps(summary, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
