"""Make a small synthetic PSX like data set (random walks, NOT real prices) for tests.

    python tools/make_synthetic.py data_synth --symbols 3 --years 5

Writes data_synth/<tf>/<SYMBOL>.csv for 5m, 15m, 30m, 1h and 1d, plus a KMIALL
index series. Sessions follow PSX: Monday to Thursday 09:15 to 15:30, Friday a
shorter day. Prices have volatility clustering, gaps and a U shaped volume day.
This exists only to prove the code runs and has no look ahead. It carries no edge.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def sessions(years: int, seed: int):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2021-11-01", periods=int(years * 252))
    # a few holidays
    keep = rng.random(len(days)) > 0.03
    return days[keep]


def day_grid(day: pd.Timestamp):
    # Friday is shorter, like the real PSX Friday sessions
    n5 = 75 if day.dayofweek != 4 else 54
    start = day + pd.Timedelta(hours=9, minutes=15)
    return start + pd.to_timedelta(np.arange(n5) * 5, unit="m")


def make_5m(days, seed, base=100.0, mu=0.00002, vol=0.0016, beta_series=None):
    rng = np.random.default_rng(seed)
    ts, o, h, l, c, v = [], [], [], [], [], []
    px = base
    hv = vol
    for d in days:
        grid = day_grid(d)
        gap = rng.normal(0, 0.004)
        px *= 1 + gap
        n = len(grid)
        u = np.linspace(0, 1, n)
        ushape = 1.6 - 1.2 * np.sin(np.pi * u)          # busy at the edges of the day
        for i in range(n):
            hv = 0.97 * hv + 0.03 * vol * (1.0 + 0.5 * abs(rng.normal()))
            r = mu + hv * ushape[i] * rng.normal()
            if beta_series is not None:
                r = 0.6 * beta_series[len(ts)] + 0.8 * r
            op = px
            cl = op * (1 + r)
            hi = max(op, cl) * (1 + abs(rng.normal(0, hv * 0.6)))
            lo = min(op, cl) * (1 - abs(rng.normal(0, hv * 0.6)))
            ts.append(grid[i]); o.append(op); h.append(hi); l.append(lo); c.append(cl)
            v.append(max(1.0, rng.lognormal(10.0, 0.7) * ushape[i] * (1 + 6 * abs(r) / vol)))
            px = cl
    return pd.DataFrame({"time": ts, "open": o, "high": h, "low": l, "close": c, "volume": v})


def resample(df5, tf):
    d = df5.set_index("time")
    if tf == "1d":
        key = d.index.normalize()
    else:
        k = {"15m": 3, "30m": 6, "1h": 12}[tf]
        day = d.index.normalize()
        pos = d.groupby(day).cumcount() // k
        key = pd.MultiIndex.from_arrays([day, pos])
    g = d.groupby(key)
    stamp = d.index.to_series().groupby(key).first()
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum()})
    out["time"] = stamp.to_numpy()
    out = out.reset_index(drop=True)
    return out.sort_values("time")[["time", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--symbols", type=int, default=3)
    ap.add_argument("--years", type=float, default=5)
    a = ap.parse_args()
    out = Path(a.out)
    days = sessions(a.years, 1)
    idx5 = make_5m(days, 99, base=1000.0, vol=0.0009)
    series = {"KMIALL": idx5}
    br = idx5["close"].pct_change().fillna(0).to_numpy()
    names = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH"][: a.symbols]
    for i, s in enumerate(names):
        series[s] = make_5m(days, 10 + i, base=50 + 20 * i, vol=0.0018, beta_series=br)
    for s, df5 in series.items():
        for tf in ("5m", "15m", "30m", "1h", "1d"):
            d = df5 if tf == "5m" else resample(df5, tf)
            p = out / tf
            p.mkdir(parents=True, exist_ok=True)
            d.to_csv(p / f"{s}.csv", index=False, float_format="%.4f")
    print("wrote", out, {tf: len(resample(idx5, tf)) if tf != "5m" else len(idx5) for tf in ("5m", "15m", "30m", "1h", "1d")})


if __name__ == "__main__":
    sys.exit(main())
