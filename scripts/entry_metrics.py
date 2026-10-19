#!/usr/bin/env python3
"""Entry metrics study on the 5-year KMIALL dataset (GITHUB ACTIONS, SO-21).

Measures the owner's research table for every next-bar-open entry, with no
TP/SL truncation (pure data, so stop and target placement can be judged):

  MAE / MFE            worst low / best high vs entry open, within the 3-bar
                       hold window (the law's max hold) and within bar 1
  time to +0.5/1/2%    first bar whose high reaches entry*(1+x), bars 1..3
  entry returns        open(i0) to close(i0+k) for k = 1,2,3,5,10
                       (k=1 same session, k=2 next session close, k=3 the
                       law's timeout exit, k=5 short-term edge)
  overnight gap        bar1 close to bar2 open (informational)

Two populations: ALL clean entries and the placeholder-baseline entries.
Print-chain corrupted windows (10x recon artifacts) are excluded and
counted (SO-3). Costs and CGT are NOT applied: this is gross data research.

Output: data/entry_metrics_report.json and a console summary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

DATASET = ROOT / "data" / "eod_history_kmi.csv.gz"
OUT = ROOT / "data" / "entry_metrics_report.json"
BAND = 0.60          # PSX circuit band; adjacent prints beyond it are fake
HOLD = 3             # the law's max hold
TARGETS = (0.005, 0.01, 0.02)
HORIZONS = (1, 2, 3, 5, 10)
PCTS = (1, 5, 10, 25, 50, 75, 90, 95, 99)


def load() -> pd.DataFrame:
    df = pd.read_csv(DATASET)
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Row-level print-chain cleanliness and next-bar helpers, per symbol."""
    g = df.groupby("symbol", sort=False)
    prev_close = g["close"].shift(1)
    oc = (df["close"] / df["open"].replace(0, np.nan) - 1).abs()
    po = (df["open"] / prev_close.replace(0, np.nan) - 1).abs()
    pc = (df["close"] / prev_close.replace(0, np.nan) - 1).abs()
    row_clean = (df["open"] > 0) & (df["close"] > 0) & oc.le(BAND) & po.le(BAND) & pc.le(BAND)
    df["row_clean"] = row_clean.fillna(False)
    df["prev_close"] = prev_close
    return df


def window_clean(df: pd.DataFrame, span: int) -> pd.Series:
    """True when rows i-1 .. i+span-1 are all clean (entry window intact)."""
    g = df.groupby("symbol", sort=False)["row_clean"]
    acc = g.shift(0).astype(bool)
    for k in range(1, span):
        acc &= g.shift(-k).fillna(False).astype(bool)
    prev_ok = g.shift(1).fillna(False).astype(bool)  # prior close for chain
    return acc & prev_ok


def shifted(df: pd.DataFrame, col: str, k: int) -> pd.Series:
    return df.groupby("symbol", sort=False)[col].shift(-k)


def study(df: pd.DataFrame, entry_mask: pd.Series, label: str) -> dict:
    """Compute the owner's table for the entry rows selected by mask."""
    d = df.loc[entry_mask].copy()
    n_total = int(len(d))
    if n_total == 0:
        return {"label": label, "n_entries": 0}

    entry = d["open"]
    out: dict = {"label": label, "n_entries": n_total}

    # returns: entry open to close k bars ahead
    for k in HORIZONS:
        c = shifted(df, "close", k).loc[d.index]
        r = (c / entry - 1).where(c > 0)
        out[f"entry_to_close_bar{k}"] = describe(r.dropna())

    # overnight gap: bar1 close to bar2 open (informational)
    c1 = shifted(df, "close", 1).loc[d.index]
    o2 = shifted(df, "open", 2).loc[d.index]
    gap = (o2 / c1 - 1).where((c1 > 0) & (o2 > 0))
    out["overnight_gap_bar1_close_to_bar2_open"] = describe(gap.dropna())

    # MAE / MFE within 1 and within HOLD bars (lows/highs vs entry open).
    # Grouped shifts only: a symbol-block end must never borrow the next
    # symbol's bar. Rows with a missing bar inside the window are NaN and
    # therefore excluded, keeping MAE/MFE window lengths honest.
    low_m = df["low"].where(df["low"] > 0)
    high_m = df["high"].where(df["high"] > 0)
    gsym = df.groupby("symbol", sort=False)
    mae1 = (low_m / entry - 1).loc[d.index]
    mfe1 = (high_m / entry - 1).loc[d.index]

    # Window extremes per bar offset j (j=0 is the entry bar itself), all
    # symbol-grouped so block ends yield NaN instead of a neighbor's bar.
    lo_j = {}
    hi_j = {}
    for j in range(HOLD):
        lo_j[j] = gsym["low"].shift(-j).loc[d.index]
        hi_j[j] = gsym["high"].shift(-j).loc[d.index]
        lo_j[j] = lo_j[j].where(lo_j[j] > 0)
        hi_j[j] = hi_j[j].where(hi_j[j] > 0)

    def extremes(span: int) -> tuple[pd.Series, pd.Series, pd.Series]:
        """(min low, max high, all-bars-present mask) over bars 0..span-1.
        pandas min/max skip NaN, so partially present windows still get an
        extreme; the ok mask then drops them from reported stats."""
        lo = lo_j[0].copy()
        hi = hi_j[0].copy()
        ok = lo.notna() & hi.notna()
        for j in range(1, span):
            lo = pd.concat([lo, lo_j[j]], axis=1).min(axis=1)
            hi = pd.concat([hi, hi_j[j]], axis=1).max(axis=1)
            ok &= lo_j[j].notna() & hi_j[j].notna()
        return lo, hi, ok

    lo3, hi3, ok3 = extremes(HOLD)
    out["mae_within_1_bar"] = describe(mae1.dropna())
    out["mfe_within_1_bar"] = describe(mfe1.dropna())
    out["mae_within_3_bars"] = describe((lo3 / entry - 1)[ok3].dropna())
    out["mfe_within_3_bars"] = describe((hi3 / entry - 1)[ok3].dropna())

    # stop/TP touch rates within the hold window (complete windows only)
    mae3 = lo3 / entry - 1
    mfe3 = hi3 / entry - 1
    out["touch_rates_within_3_bars"] = {
        "mae_le_-1pct": float((mae3[ok3] <= -0.01).mean()),
        "mae_le_-2pct": float((mae3[ok3] <= -0.02).mean()),
        "mfe_ge_+0.5pct": float((mfe3[ok3] >= 0.005).mean()),
        "mfe_ge_+1pct": float((mfe3[ok3] >= 0.01).mean()),
        "mfe_ge_+2pct": float((mfe3[ok3] >= 0.02).mean()),
    }

    # time to target: first bar j (1..HOLD) whose high reaches entry*(1+x).
    # hi_j indexes bar offsets 0..HOLD-1, so bar number = j+1. Only entries
    # whose high_j exists count toward the reach rate.
    tt = {}
    for t in TARGETS:
        reach = pd.Series(False, index=d.index)
        bars = pd.Series(np.nan, index=d.index)
        for j in range(HOLD):
            hit = (hi_j[j] >= entry * (1 + t)) & ~reach
            bars = bars.where(~hit, float(j + 1))
            reach = reach | hit.fillna(False)
        known = pd.Series(True, index=d.index)
        for j in range(HOLD):
            known &= hi_j[j].notna()
        tt[f"+{t*100:g}pct"] = {
            "reached_within_3_bars": float(reach[known].mean()),
            "median_bars_when_reached": float(bars.dropna().median()) if reach.any() else None,
        }
    out["time_to_target"] = tt
    return out


def describe(s: pd.Series) -> dict:
    q = s.quantile([p / 100 for p in PCTS])
    return {
        "mean": float(s.mean()),
        **{f"p{p}": float(q[p / 100]) for p in PCTS},
    }


def baseline_mask(df: pd.DataFrame) -> pd.Series:
    """Entries of the placeholder baseline (close>MA20 and volume>rolling
    median at the signal row); the entry row is the symbol's next row."""
    g = df.groupby("symbol", sort=False)
    ma20 = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    vmed = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).median())
    sig = ((df["close"] > ma20) & (df["volume"] > vmed)).fillna(False)
    # shift inside each symbol so a signal never maps across symbols
    return sig.groupby(df["symbol"], sort=False).shift(1).fillna(False).astype(bool)


def main() -> int:
    guard_cloud_backtest("scripts/entry_metrics.py")
    df = load()
    df = add_flags(df)
    wc3 = window_clean(df, HOLD)
    base = baseline_mask(df)

    base_mask = base & wc3
    all_mask = wc3
    excluded = int((~wc3).sum())
    print(f"entries considered (clean 3-bar windows, prev row clean): "
          f"{int(all_mask.sum()):,}  | excluded corrupted windows: {excluded:,}")

    report = {
        "dataset": str(DATASET.name),
        "rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "definition_note": (
            "entry = open of bar 1 (the session after the signal); returns are "
            "gross, no costs; MAE/MFE use lows/highs vs entry open within the "
            "stated window; corrupted print windows excluded"
        ),
    }
    report["all_clean_entries"] = study(df, all_mask, "all clean entries")
    report["placeholder_baseline_entries"] = study(df, base_mask, "placeholder baseline entries")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # console summary: the owner's table, headline numbers
    for pop in ("all_clean_entries", "placeholder_baseline_entries"):
        r = report[pop]
        print(f"\n=== {r['label']} (n={r['n_entries']:,}) ===")
        for key in [f"entry_to_close_bar{k}" for k in HORIZONS] + [
                "mae_within_1_bar", "mfe_within_1_bar",
                "mae_within_3_bars", "mfe_within_3_bars",
                "overnight_gap_bar1_close_to_bar2_open"]:
            d = r[key]
            print(f"{key:38s} p25={d['p25']:+.4f} p50={d['p50']:+.4f} "
                  f"p75={d['p75']:+.4f} p95={d['p95']:+.4f} mean={d['mean']:+.4f}")
        print("touch rates:", json.dumps(r["touch_rates_within_3_bars"]))
        for t, v in r["time_to_target"].items():
            print(f"time to {t}: reached {v['reached_within_3_bars']:.3f} "
                  f"| median bars {v['median_bars_when_reached']}")
    print(f"\nfull report -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
