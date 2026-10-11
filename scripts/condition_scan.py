"""Condition scan: P(+X% before -0.5%) conditioned on individual causal features.

Research-only. Tests each condition independently, reports n, base rate,
lift, and chronological persistence (year halves). No production change.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "data", "event_study")
from src.ci.local_only import guard_local_only  # noqa: E402

TGT = "t0.02_first_vs_a05"      # headline: +2% before -0.5%
TGT1 = "t0.01_first_vs_a05"     # secondary: +1% before -0.5%
TGT3 = "t0.03_first_vs_a05"     # right tail: +3% before -0.5%

CONDITIONS = {
    # momentum / relative strength
    "ret1>3%":            lambda e: e["f_ret1"] > 0.03,
    "ret1>5%":            lambda e: e["f_ret1"] > 0.05,
    "ret5>7%":            lambda e: e["f_ret5"] > 0.07,
    "ret20>10%":          lambda e: e["f_ret20"] > 0.10,
    "ret20<0":            lambda e: e["f_ret20"] < 0,
    "rs1>mkt":            lambda e: e["f_ret1"] > e["f_mkt_ret"],
    "gap1>1%":            lambda e: e["f_gap1"] > 0.01,
    "gap1<-1%":           lambda e: e["f_gap1"] < -0.01,
    # structure
    "above_ma20":         lambda e: e["f_above_ma20"] == True,  # noqa: E712
    "below_ma20":         lambda e: e["f_above_ma20"] == False,  # noqa: E712
    "near_hi20(>=97%)":   lambda e: e["f_near_hi20"] >= 0.97,
    "near_hi60(>=95%)":   lambda e: e["f_near_hi60"] >= 0.95,
    "hi20_break(t)":      lambda e: e["f_near_hi20"] >= 1.0,
    "lo20_break(t)":      lambda e: e["f_ret1"] < 0,
    "range20<8%":         lambda e: e["f_range20"] < 0.08,
    "range20<12%":        lambda e: e["f_range20"] < 0.12,
    "atr20<4%":           lambda e: (e["f_atr20"] / e["f_hi20"].replace(0, np.nan)) < 0.04,
    # volume / liquidity
    "relvol>1.5":         lambda e: e["f_relvol"] > 1.5,
    "relvol>2":           lambda e: e["f_relvol"] > 2.0,
    "relvol<0.7":         lambda e: e["f_relvol"] < 0.7,
    "turnover>p75":       lambda e: e["f_turnover"] > e["f_turnover"].quantile(0.75),
    "turnover<p25":       lambda e: e["f_turnover"] < e["f_turnover"].quantile(0.25),
    # market regime
    "mkt_up(t)":          lambda e: e["f_mkt_ret"] > 0,
    "mkt_down(t)":        lambda e: e["f_mkt_ret"] < 0,
    "breadth>60%":        lambda e: e["f_mkt_adv"] > 0.6,
    "breadth<40%":        lambda e: e["f_mkt_adv"] < 0.4,
    "mkt_vol20_hi":       lambda e: e["f_mkt_vol20"] > e["f_mkt_vol20"].quantile(0.75),
}

HALF_CUT = pd.Timestamp("2024-01-01")


def _jdefault(o):
    if isinstance(o, (np.bool_,)): return bool(o)
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.floating,)): return float(o)
    return str(o)


def scan(ev: pd.DataFrame, tgt: str) -> list[dict]:
    rows = []
    base = ev[tgt].mean()
    for name, fn in CONDITIONS.items():
        try:
            mask = fn(ev)
        except Exception:
            continue
        sub = ev[mask]
        if len(sub) < 300:
            continue
        r = {
            "condition": name,
            "n": int(len(sub)),
            "share_pct": round(100 * len(sub) / len(ev), 1),
            "p": round(float(sub[tgt].mean()), 4),
            "base": round(float(base), 4),
            "lift_pp": round(100 * (sub[tgt].mean() - base), 2),
        }
        # persistence across time halves
        d1 = sub[sub["entry_date"] < HALF_CUT][tgt]
        d2 = sub[sub["entry_date"] >= HALF_CUT][tgt]
        r["p_h1"] = round(float(d1.mean()), 4) if len(d1) > 50 else None
        r["p_h2"] = round(float(d2.mean()), 4) if len(d2) > 50 else None
        r["stable"] = (r["p_h1"] is not None and r["p_h2"] is not None
                       and (r["p_h1"] - base) * (r["p_h2"] - base) > 0)
        rows.append(r)
    return sorted(rows, key=lambda r: -r["lift_pp"])


def main() -> int:
    guard_local_only("scripts/condition_scan.py")
    ev = pd.read_parquet(os.path.join(OUT, "events.parquet"))
    ev["entry_date"] = pd.to_datetime(ev["entry_date"])
    for tgt, label in [(TGT1, "+1% before -0.5%"), (TGT, "+2% before -0.5%"), (TGT3, "+3% before -0.5%")]:
        res = scan(ev, tgt)
        print(f"\n===== {label} | base {res[0]['base'] if res else 'n/a'} =====")
        for r in res[:15]:
            print(json.dumps(r, default=_jdefault))
        with open(os.path.join(OUT, f"conditions_{tgt.strip('_first_vs_a05')}.json"), "w") as f:
            json.dump(res, f, indent=2, default=_jdefault)
    return 0


if __name__ == "__main__":
    sys.exit(main())
