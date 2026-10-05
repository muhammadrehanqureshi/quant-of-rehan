"""Grind round 4: entry-shape forensics on 175 sessions x 305 symbols.

QUESTION (owner's order): why did the trade lose, and what entry shapes
does the data forgive? Tested under the fixed law (-1% SL, +2% TP,
0.848% round trip), conservative tie-break (stop wins ties).

Entry families, all knowable at decision time:
  A. green-open continuation: prior close up, day opens green,
     enter at the open (what PPL was: +0.79% day, open near prior close)
  B. flat-open drift-up: opens flat (|open/pc-1|<0.3%), first push
     +1% by 10:30-equivalent fraction of the day (daily approx:
     open flat, close > open, enter close - the daily approximation
     of the intraday reclaim)
  C. red-to-green flip: prior close red, today closes green above
     prior close
  D. gap-and-hold: gaps 1-3% and closes above the gap
  E. yesterday-red-today-lock: control (the shipped lock law)
  F. consecutive-green-day-2/3 (fresh green streak, NOT locked,
     extension 2-6%): the 'momentum without lock' band
Every family reports discovery (first 2/3 of sessions) vs validation
(last 1/3) with wins/nets, plus the same split by month.
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
    daily = {}
    for sym, rows in raw.items():
        rows.sort(key=lambda r: r["date"])
        daily[sym] = rows
    return daily


def next_day_outcome(rows, i):
    """Next session: which barrier first. Uses close only (corpus has
    open/close/volume). TP if next close >= entry*1.02, SL if next
    close <= entry*0.99; neither -> 'time' (hold to that close,
    pnl = close/entry-1). The corpus has no intraday path - the
    close-bracket is the honest resolution and matches the 30-day
    method used to fit the lock law."""
    if i + 1 >= len(rows):
        return None, 0.0
    entry = rows[i]["close"]
    nc = rows[i + 1]["close"]
    if nc >= entry * 1.02:
        return "TP", TP - COST
    if nc <= entry * 0.99:
        return "SL", SL - COST
    return "time", (nc / entry - 1) * 100 - COST


def band_stats(trades, label):
    if not trades:
        return f"{label:26s}  (none)"
    n = len(trades)
    wins = sum(1 for t in trades if t[0] == "TP")
    net = sum(t[1] for t in trades)
    return (
        f"{label:26s} {n:5d} | win {wins/n*100:5.1f}% | net {net:+8.1f}% "
        f"({net/n:+.2f}/trade)"
    )


def main() -> int:
    daily = load()
    all_dates = sorted({r["date"] for rows in daily.values() for r in rows})
    split_idx = int(len(all_dates) * 2 / 3)
    split_date = all_dates[split_idx]

    fams = defaultdict(list)  # family -> [(outcome, net, date)]
    for sym, rows in daily.items():
        if len(rows) < 30:
            continue
        for i in range(1, len(rows) - 1):
            today, pc = rows[i], rows[i - 1]
            if not today.get("open") or not today.get("close") or not pc.get("close"):
                continue
            o, c, pclose = today["open"], today["close"], today.get("prev_close")
            chg = (c / pclose - 1) * 100 if pclose else (c / pc["close"] - 1) * 100
            gap = (o / pc["close"] - 1) * 100
            body = (c / o - 1) * 100
            outcome, net = next_day_outcome(rows, i)
            if outcome is None:
                continue
            d = today["date"]

            # A. green-open continuation (PPL's family)
            if 0 < chg < 2 and 0 <= gap < 1 and body > 0:
                fams["A green-open 0-2%"].append((outcome, net, d))
            # B. flat-open drift-up
            if abs(gap) < 0.3 and body > 1.0 and 0 < chg < 3:
                fams["B flat-open drift-up"].append((outcome, net, d))
            # C. red-to-green flip
            if pc["close"] < rows[i - 2]["close"] if i >= 2 else False:
                pass
            if i >= 2 and rows[i - 2]["close"] > pc["close"] and chg > 0 and body > 0:
                fams["C red-to-green flip"].append((outcome, net, d))
            # D. gap-and-hold 1-3%
            if 1 <= gap <= 3 and c > o and chg > gap:
                fams["D gap-and-hold 1-3%"].append((outcome, net, d))
            # F. momentum-without-lock 2-6% (not locked)
            if 2 <= chg < 6:
                fams["F momentum 2-6% no-lock"].append((outcome, net, d))
            # E. control: locked close
            if chg >= 9.9:
                fams["E LOCK control (>=9.9%)"].append((outcome, net, d))

    print("=" * 78)
    print("GRIND 4 - entry-shape forensics, 175 sessions x 305 symbols")
    print("law TP+2%/SL-1%, costs 0.848% RT, close-bracket resolution")
    print("=" * 78)
    for name in sorted(fams):
        trades = fams[name]
        disc = [t for t in trades if t[2] < split_date]
        val = [t for t in trades if t[2] >= split_date]
        print(band_stats(trades, name))
        print(band_stats(disc, "  discovery"))
        print(band_stats(val, "  validation"))

    # PPL specifically: what happens after a 0-2% green day with a
    # green open, by month - the seasonality of the failure
    ppl = fams["A green-open 0-2%"]
    months = defaultdict(list)
    for outcome, net, d in ppl:
        months[d[:7]].append((outcome, net))
    print()
    print("A-family by month (PPL's family):")
    for m in sorted(months):
        ts = months[m]
        wins = sum(1 for o, _ in ts if o == "TP")
        net = sum(n for _, n in ts)
        print(f"  {m}  {len(ts):4d} | win {wins/len(ts)*100:5.1f}% | net {net:+7.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
