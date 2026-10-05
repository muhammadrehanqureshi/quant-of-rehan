"""Grind round 5: inside the 2-8% momentum band, what separates the
next-day winners from the losers?

Band context (grind 4): 2-6% no-lock won 19.5% overall - bad, but the
lock law's periphery (7-9.9%) was never mined separately, and the band
may hide a strong sub-shape. Features (all knowable at the close):
  * vol_ratio: today's volume / 20-day average
  * gap: open vs prior close
  * body: close vs open
  * close_pos: (close - low_proxy) / range_proxy (0..1; low_proxy =
    min(open, close) - the corpus carries no true high/low)
  * streak: consecutive green closes ending today
  * chg bands: 2-3 / 3-4 / 4-5 / 5-6 / 6-7 / 7-9.9
Discipline: discovery = first 2/3 of the 175 sessions, validation =
last 1/3. Only sub-shapes that win in BOTH halves survive.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"

COST = 0.848
TP, SL = 2.0, -1.0


def load():
    raw = json.loads(CORPUS.read_text())
    out = {}
    for sym, rows in raw.items():
        rows.sort(key=lambda r: r["date"])
        if len(rows) >= 30:
            out[sym] = rows
    return out


def resolve(rows, i):
    if i + 1 >= len(rows):
        return None, 0.0
    entry = rows[i]["close"]
    nc = rows[i + 1]["close"]
    if nc >= entry * (1 + TP / 100):
        return "TP", TP - COST
    if nc <= entry * (1 + SL / 100):
        return "SL", SL - COST
    return "time", (nc / entry - 1) * 100 - COST


def streak(rows, i):
    n = 0
    for j in range(i, 0, -1):
        if rows[j]["close"] > rows[j - 1]["close"]:
            n += 1
        else:
            break
    return n


def main() -> int:
    daily = load()
    all_dates = sorted({r["date"] for rows in daily.values() for r in rows})
    split_date = all_dates[int(len(all_dates) * 2 / 3)]

    cells = defaultdict(list)  # feature:value bucket -> [(outcome, net, date)]

    for sym, rows in daily.items():
        # rolling 20-day mean volume
        for i in range(20, len(rows) - 1):
            r, pc = rows[i], rows[i - 1]
            if not r.get("open") or not r.get("close") or not pc.get("close"):
                continue
            chg = (r["close"] / pc["close"] - 1) * 100
            if not (2.0 <= chg < 9.9):
                continue
            outcome, net = resolve(rows, i)
            if outcome is None:
                continue
            d = r["date"]
            avg_v = sum(x.get("volume") or 0 for x in rows[i - 20:i]) / 20
            vr = (r.get("volume") or 0) / avg_v if avg_v else None
            gap = (r["open"] / pc["close"] - 1) * 100
            body = (r["close"] / r["open"] - 1) * 100
            lo = min(r["open"], r["close"])
            hi = max(r["open"], r["close"])
            cpos = (r["close"] - lo) / (hi - lo) if hi > lo else 0.5
            st = streak(rows, i)

            def bucket(name, val, edges):
                if val is None:
                    return
                for e in edges:
                    if val < e:
                        cells[f"{name}<{e}"].append((outcome, net, d))
                        return
                cells[f"{name}>={edges[-1]}"].append((outcome, net, d))

            bucket("vr", vr, [0.5, 1.0, 2.0, 4.0])
            bucket("gap", gap, [0, 1, 2, 4])
            bucket("body", body, [0, 1, 2, 4])
            bucket("cpos", cpos, [0.5, 0.8])
            bucket("streak", st, [1, 2, 3])
            bucket("chg", chg, [3, 4, 5, 6, 7, 8, 9.9])

    print("=" * 78)
    print("GRIND 5 - the 2-8% momentum band, mined. TP+2%/SL-1%, 0.848% RT")
    print("=" * 78)
    survivors = []
    for name in sorted(cells):
        trades = cells[name]
        if len(trades) < 30:
            continue
        disc = [t for t in trades if t[2] < split_date]
        val = [t for t in trades if t[2] >= split_date]
        if not disc or not val:
            continue

        def wr(ts):
            return sum(1 for t in ts if t[0] == "TP") / len(ts) * 100

        def nt(ts):
            return sum(t[1] for t in ts) / len(ts)

        dwr, vwr = wr(disc), wr(val)
        dnet, vnet = nt(disc), nt(val)
        flag = ""
        if dwr >= 35 and vwr >= 35 and dnet > 0 and vnet > 0:
            flag = "  <<< SURVIVOR (both halves positive)"
            survivors.append(name)
        print(
            f"{name:14s} {len(trades):5d} | win {wr(trades):5.1f}% "
            f"(D {dwr:5.1f}% / V {vwr:5.1f}%) "
            f"| net/trade {nt(trades):+.2f} (D {dnet:+.2f} / V {vnet:+.2f}){flag}"
        )

    print()
    if survivors:
        print("survivors:", ", ".join(survivors))
    else:
        print("no sub-shape of the band survives both halves - the ban holds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
