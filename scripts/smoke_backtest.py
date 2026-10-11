#!/usr/bin/env python3
"""LOCAL-ONLY smoke backtest (SO-4: never run in GitHub Actions).

Validates the engine end-to-end on the real 5-year KMIALL dataset using a
PLACEHOLDER BASELINE entry rule: explicitly NOT the strategy. Purpose:
prove plumbing, produce first honest numbers for the ENGINE, not a claim
about any edge. The real signal engine (FVG/liquidity/auction layers)
comes after this pipeline is proven and walk-forwarded.

Usage (from repo root, on the owner's PC):
    python scripts/smoke_backtest.py [--dataset data/eod_dataset.csv.gz]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_local_only  # noqa: E402

from src.backtest.engine import run_backtest  # noqa: E402
from src.data.corpus import load_corpus  # noqa: E402


def placeholder_signals(df: pd.DataFrame) -> list[tuple]:
    """PLACEHOLDER BASELINE: trend+participation filter, decided at close T.

    Uses only information up to and including T (rolling windows end at T);
    the engine then enters at T+1's open. This is plumbing validation, not
    an edge claim.
    """
    df = df.sort_values(["symbol", "date"]).copy()
    ma20 = df.groupby("symbol")["close"].transform(
        lambda s: s.rolling(20, min_periods=20).mean()
    )
    vol_med = df.groupby("symbol")["volume"].transform(
        lambda s: s.rolling(20, min_periods=20).median()
    )
    ok = (df["close"] > ma20) & (df["volume"] > vol_med)
    sig = df.loc[ok, ["date", "symbol"]]
    return list(sig.itertuples(index=False, name=None))


def main(argv: list[str] | None = None) -> int:
    guard_local_only("scripts/smoke_backtest.py")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, default=None,
                    help="Long-frame dataset (data/eod_dataset.csv.gz)")
    ap.add_argument("--corpus", type=Path, default=None,
                    help="Sentinel's eod_corpus.json (fallback source)")
    ap.add_argument("--out", type=Path, default=ROOT / "data/backtest_smoke.json")
    args = ap.parse_args(argv)

    if args.dataset and args.dataset.is_file():
        df = pd.read_csv(args.dataset, parse_dates=["date"])
        source = f"dataset {args.dataset}"
    elif args.corpus and args.corpus.is_file():
        df, info = load_corpus(args.corpus)
        source = f"corpus {args.corpus}"
        print(f"Corpus: {info}")
    else:
        print("No data. Build a dataset (python -m src.data.psx_eod --universe ...) "
              "or pass --corpus <path to the sentinel's eod_corpus.json>")
        return 1
    print(f"Loaded {len(df):,} rows, {df['symbol'].nunique()} symbols, "
          f"{df['date'].min().date()} .. {df['date'].max().date()} [{source}]")

    sigs = placeholder_signals(df)
    print(f"PLACEHOLDER-BASELINE signals (not a strategy): {len(sigs):,}")

    trades, summary = run_backtest(df, sigs)
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "engine": "daily-bar TP/SL engine (conservative fills)",
        "data": {"rows": int(len(df)), "symbols": int(df["symbol"].nunique()),
                 "start": str(df["date"].min().date()),
                 "end": str(df["date"].max().date())},
        "signal_rule": "PLACEHOLDER-BASELINE: close>MA20 and volume>rolling-median, at close T; entry T+1 open",
        "summary": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print(json.dumps(summary, indent=2, default=str))
    print(f"\nReport -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
