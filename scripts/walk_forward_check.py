"""Walk-forward + net expectancy for the two conditions that survived the scan.

Research-only. Conditions: turnover<p25 (low liquidity) and gap1<-1%
(gap-down next open). Splits: discovery <=2023-12-31, validation
2024-01-01..2025-06-30, OOS >=2025-07-01. Net applies repo cost model
(22.4 bps/side + 15% CGT on winners) to a +2%-before--0.5% exit within
10 sessions, timeout at close of bar 10.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "event_study")
COST_SIDE = 0.00224
CGT = 0.15
H = 10

SPLITS = {
    "discovery": (None, "2023-12-31"),
    "validation": ("2024-01-01", "2025-06-30"),
    "oos": ("2025-07-01", None),
}


def trade_outcome(ev_sub: pd.DataFrame) -> pd.DataFrame:
    """Simulate: entry at open; if +2% hits before -0.5% -> TP; if -0.5% first -> exit at -0.5%;
    timeout -> close of bar 10. Uses first-touch bars recorded in the event study."""
    e = ev_sub.copy()
    tp_bar = e["t0.02"]
    a_bar = e["a0.005"]
    gross = []
    outcome = []
    for tp, ad, last_c in zip(tp_bar, a_bar, e["ret_c10"]):
        if tp is not None and (ad is None or tp < ad):
            gross.append(0.02)
            outcome.append("tp")
        elif ad is not None:
            gross.append(-0.005)
            outcome.append("adverse")
        elif np.isfinite(last_c):
            gross.append(float(last_c))
            outcome.append("timeout")
        else:
            gross.append(np.nan)
            outcome.append("unknown")
    e["gross"] = gross
    e["outcome"] = outcome
    g = e["gross"]
    e["net"] = g - 2 * COST_SIDE - CGT * np.maximum(g - 2 * COST_SIDE, 0)
    return e


def stats(e: pd.DataFrame) -> dict:
    e = e.dropna(subset=["net"])
    if len(e) == 0:
        return {"n": 0}
    return {
        "n": int(len(e)),
        "net_mean_pct": round(float(e["net"].mean()) * 100, 3),
        "net_win_pct": round(float((e["net"] > 0).mean()) * 100, 2),
        "tp_pct": round(float((e["outcome"] == "tp").mean()) * 100, 2),
        "adverse_pct": round(float((e["outcome"] == "adverse").mean()) * 100, 2),
        "timeout_pct": round(float((e["outcome"] == "timeout").mean()) * 100, 2),
        "gross_mean_pct": round(float(e["gross"].mean()) * 100, 3),
        "median_net_pct": round(float(e["net"].median()) * 100, 3),
        "mfe_p50_pct": round(float(e["mfe"].quantile(0.5)) * 100, 2),
        "mae_p50_pct": round(float(e["mae"].quantile(0.5)) * 100, 2),
    }


def main() -> int:
    ev = pd.read_parquet(os.path.join(OUT, "events.parquet"))
    ev["entry_date"] = pd.to_datetime(ev["entry_date"])
    conds = {
        "ALL": lambda e: pd.Series(True, index=e.index),
        "turnover<p25": lambda e: e["f_turnover"] < e["f_turnover"].quantile(0.25),
        "gap1<-1%": lambda e: e["f_gap1"] < -0.01,
        "gap1<-1% & turnover<p50": lambda e: (e["f_gap1"] < -0.01) & (e["f_turnover"] < e["f_turnover"].quantile(0.5)),
    }
    report = {}
    for name, fn in conds.items():
        sub = trade_outcome(ev[fn(ev)])
        report[name] = {}
        for sp, (lo, hi) in SPLITS.items():
            m = pd.Series(True, index=sub.index)
            if lo:
                m &= sub["entry_date"] >= pd.Timestamp(lo)
            if hi:
                m &= sub["entry_date"] <= pd.Timestamp(hi)
            report[name][sp] = stats(sub[m])
        # slippage sensitivity on full sample
        full = trade_outcome(ev[fn(ev)])
        sens = {}
        for slip in [0, 0.0005, 0.001]:
            g = full["gross"]
            net = g - 2 * (COST_SIDE + slip) - CGT * np.maximum(g - 2 * (COST_SIDE + slip), 0)
            sens[f"slip{slip*1e4:.0f}bps"] = round(float(net.mean()) * 100, 3)
        report[name]["slippage_sensitivity"] = sens
    print(json.dumps(report, indent=2))
    with open(os.path.join(OUT, "walk_forward_check.json"), "w") as f:
        json.dump(report, f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
