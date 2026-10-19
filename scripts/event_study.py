"""Event study over the full KMIALL panel (research-only, no production change).

Question (owner directive 2026-10-08): what observable condition at time T
predicts a large upward move soon enough to be tradable, before meaningful
adverse movement?

Design:
  - Decision point T = any session where a symbol has >=21 prior sessions and
    a tradable next-session open (T+1). Decision features use bars <= T only.
  - Entry reference = T+1 open (the only executable price). Forward path =
    10 sessions after entry, daily OHLC.
  - Targets: +0.5 +0.75 +1.0 +1.5 +2.0 +3.0 +4.0 % (high >= level).
    Adverse: -0.5 -1.0 % (low <= level). Same-day both-touch counts as
    ADVERSE-first (conservative, consistent with repo convention).
  - Metrics per event: which target hit first vs adverse, MFE/MAE, time (bars)
    to each target, ret by close of bar 1..10.

Outputs data/event_study/ : events.parquet + conditions.json summary.
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "data")
from src.ci.local_only import guard_cloud_backtest  # noqa: E402
OUT = os.path.join(DATA, "event_study")
os.makedirs(OUT, exist_ok=True)

TARGETS = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04]
ADVERSE = [0.005, 0.01]
H = 10  # forward sessions


def load_panel() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(DATA, "eod_history_kmi.csv.gz"), parse_dates=["date"])
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def add_daily_features(df: pd.DataFrame) -> pd.DataFrame:
    """Causal features at T, per symbol. Windows END at T."""
    df = df.copy()
    g = df.groupby("symbol", sort=False)
    df["ret1"] = g["close"].pct_change()
    df["ret5"] = g["close"].pct_change(5)
    df["ret10"] = g["close"].pct_change(10)
    df["ret20"] = g["close"].pct_change(20)
    df["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["hi20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).max())
    df["hi60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).max())
    df["lo20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).min())
    df["vol20"] = g["volume"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["range20"] = (df["hi20"] - df["lo20"]) / df["lo20"]  # compression measure
    df["atr20"] = g.apply(
        lambda x: (
            pd.concat([x["high"] - x["low"], (x["high"] - x["close"].shift()).abs(), (x["low"] - x["close"].shift()).abs()], axis=1)
            .max(axis=1)
            .rolling(20, min_periods=20)
            .mean()
        )
    ).reset_index(level=0, drop=True)
    df["gap1"] = df["open"] / df["close"] - 1.0  # same-day open vs prior close? (assigned after shift below)
    df["gap1"] = g.apply(lambda x: x["open"] / x["close"].shift() - 1.0).reset_index(level=0, drop=True)
    df["gap_ret5"] = g.apply(lambda x: x["open"] / x["close"].shift(5) - 1.0).reset_index(level=0, drop=True)
    return df


def market_features(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional (all-stock) breadth at T: equal-weight mean ret1, adv/dec share."""
    m = df.dropna(subset=["ret1"]).groupby("date")["ret1"].agg(mkt_ret="mean", adv=lambda s: (s > 0).mean()).reset_index()
    m["mkt_ret5"] = m["mkt_ret"].rolling(5).mean()
    m["mkt_vol20"] = m["mkt_ret"].rolling(20).std()
    return m


def build_events(df: pd.DataFrame) -> pd.DataFrame:
    # next session's open (executable entry reference)
    g = df.groupby("symbol", sort=False)
    df["n_open"] = g["open"].shift(-1)
    df["n_date"] = g["date"].shift(-1)
    df["sess_idx"] = g.cumcount()
    df["n_sess_idx"] = df["sess_idx"] + 1
    df["n_close"] = g["close"].shift(-1)

    mkt = market_features(df)
    df = df.merge(mkt, on="date", how="left")

    rows = []
    for sym, x in df.groupby("symbol", sort=False):
        x = x.reset_index(drop=True)
        arr = {c: x[c].to_numpy() for c in
               ["date", "n_open", "n_date", "open", "high", "low", "close", "n_close", "sess_idx"]}
        n = len(x)
        for i in range(21, n - 1):  # need >=21 prior sessions; entry bar exists
            eo = arr["n_open"][i]
            if not np.isfinite(eo) or eo <= 0:
                continue
            entry_i = i + 1
            hi = arr["high"][entry_i: min(entry_i + H, n)].astype(float)
            lo = arr["low"][entry_i: min(entry_i + H, n)].astype(float)
            cl = arr["close"][entry_i: min(entry_i + H, n)].astype(float)
            if len(hi) == 0:
                continue
            # first-touch per target within horizon
            t_hit = {}
            for t in TARGETS:
                lv = eo * (1 + t)
                hit = np.where(hi >= lv)[0]
                t_hit[t] = int(hit[0]) if len(hit) else None
            a_hit = {}
            for a in ADVERSE:
                lv = eo * (1 - a)
                hit = np.where(lo <= lv)[0]
                a_hit[a] = int(hit[0]) if len(hit) else None
            mfe = float((hi.max() / eo) - 1.0)
            mae = float((lo.min() / eo) - 1.0)
            row = dict(
                symbol=sym,
                signal_date=arr["date"][i],
                entry_date=arr["n_date"][i],
                entry_price=eo,
                mfe=mfe, mae=mae,
            )
            for t in TARGETS:
                row[f"t{t}"] = t_hit[t]
            for a in ADVERSE:
                row[f"a{a}"] = a_hit[a]
            for t in TARGETS:
                a0 = a_hit[ADVERSE[0]]
                th = t_hit[t]
                # adverse-first comparison using -0.5% adverse and same-bar=adverse
                if th is None:
                    row[f"t{t}_first_vs_a05"] = False
                elif a0 is None or th < a0:
                    row[f"t{t}_first_vs_a05"] = True
                else:
                    row[f"t{t}_first_vs_a05"] = False
            for j in range(min(len(cl), 10)):
                row[f"ret_c{j+1}"] = float(cl[j] / eo - 1.0)
            # causal features at T
            for c in ["ret1", "ret5", "ret10", "ret20", "gap1", "gap_ret5",
                      "range20", "atr20", "vol20", "hi20", "hi60", "lo20"]:
                v = x[c].iloc[i] if c in x.columns else np.nan
                row[f"f_{c}"] = float(v) if np.isfinite(v) else None
            row["f_above_ma20"] = bool(arr["close"][i] > x["ma20"].iloc[i]) if np.isfinite(x["ma20"].iloc[i]) else None
            row["f_near_hi20"] = float(arr["close"][i] / x["hi20"].iloc[i]) if np.isfinite(x["hi20"].iloc[i]) else None
            row["f_near_hi60"] = float(arr["close"][i] / x["hi60"].iloc[i]) if np.isfinite(x["hi60"].iloc[i]) else None
            row["f_relvol"] = float(x["volume"].iloc[i] / x["vol20"].iloc[i]) if np.isfinite(x["vol20"].iloc[i]) and x["vol20"].iloc[i] > 0 else None
            row["f_turnover"] = float(arr["close"][i] * x["volume"].iloc[i])
            row["f_mkt_ret"] = float(x["mkt_ret"].iloc[i]) if np.isfinite(x["mkt_ret"].iloc[i]) else None
            row["f_mkt_adv"] = float(x["adv"].iloc[i]) if np.isfinite(x["adv"].iloc[i]) else None
            rows.append(row)
    ev = pd.DataFrame(rows)
    return ev


def summarize(ev: pd.DataFrame) -> dict:
    out = {}
    valid = ev[~ev["mae"].isna()]
    out["n_events"] = int(len(valid))
    out["n_symbols"] = int(valid["symbol"].nunique())
    for t in TARGETS:
        col = f"t{t}_first_vs_a05"
        if col in valid:
            out[f"p_t{t}_before_a05"] = round(float(valid[col].mean()), 4)
    # unconditional forward returns
    for j in [1, 2, 3, 5, 10]:
        c = f"ret_c{j}"
        if c in valid:
            s = valid[c].dropna()
            out[f"ret_c{j}_mean"] = round(float(s.mean()), 5)
            out[f"ret_c{j}_p90"] = round(float(s.quantile(0.9)), 5)
            out[f"ret_c{j}_p95"] = round(float(s.quantile(0.95)), 5)
    out["mfe_p50"] = round(float(valid["mfe"].quantile(0.5)), 5)
    out["mfe_p90"] = round(float(valid["mfe"].quantile(0.9)), 5)
    out["mfe_p95"] = round(float(valid["mfe"].quantile(0.95)), 5)
    out["mae_p50"] = round(float(valid["mae"].quantile(0.5)), 5)
    out["mae_p05"] = round(float(valid["mae"].quantile(0.05)), 5)
    return out


def main() -> int:
    guard_cloud_backtest("scripts/event_study.py")
    df = load_panel()
    print("panel rows", len(df), "symbols", df["symbol"].nunique())
    df = add_daily_features(df)
    ev = build_events(df)
    ev.to_parquet(os.path.join(OUT, "events.parquet"), index=False)
    summ = summarize(ev)
    with open(os.path.join(OUT, "event_summary.json"), "w") as f:
        json.dump(summ, f, indent=2)
    print(json.dumps(summ, indent=2))
    print("events written:", os.path.join(OUT, "events.parquet"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
