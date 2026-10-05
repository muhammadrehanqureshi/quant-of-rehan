"""The grind on the 90-session corpus (2026-05-07 .. 2026-09-18).

The question the owner is asking: does the lock law hold through 90
sessions, and does the deeper sample reveal a BETTER policy that the
30-day window was too small to prove?

Discipline, unchanged:
  * DISCOVERY: May-July (first ~60 sessions of the window)
  * VALIDATION: August-September (last ~30, incl. the rout)
  * a rule ships only if BOTH hold
Plus a month-by-month stability read of every candidate rule.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"
COST = 0.848
TP = 2.0
SL = -1.0
LOCK = 9.9
PRICE_FLOOR = 20.0
VALUE_FLOOR = 5_000_000.0
DISTRIBUTION = 500_000_000.0
MAX_GAP_DAYS = 7


def all_dates(corpus):
    dates = set()
    for hist in corpus.values():
        for row in hist:
            dates.add(row["date"])
    return sorted(dates)


def next_session(hist, d):
    from datetime import date as _d

    for row in hist:
        if row["date"] > d:
            gap = (_d.fromisoformat(row["date"]) - _d.fromisoformat(d)).days
            if gap > MAX_GAP_DAYS:
                return None
            return row
    return None


def build_rows(corpus, dates):
    prev_of = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_of[(sym, hist[i]["date"])] = hist[i - 1]
    rows = []
    for j, d in enumerate(dates[:-1]):
        nd = dates[j + 1]
        for sym, hist in corpus.items():
            today = next((r for r in hist if r["date"] == d), None)
            prev = prev_of.get((sym, d))
            if today is None or prev is None or prev["close"] <= 0:
                continue
            ext = (today["close"] / prev["close"] - 1) * 100
            if ext < LOCK:
                continue
            value = today["volume"] * (today["open"] + today["close"]) / 2
            if today["close"] < PRICE_FLOOR or value < VALUE_FLOOR or value >= DISTRIBUTION:
                continue
            i = hist.index(today)
            lock_days = 1
            while i > 1 and hist[i - 1]["close"] > 0 and hist[i - 2]["close"] > 0 and \
                    (hist[i - 1]["close"] / hist[i - 2]["close"] - 1) * 100 >= LOCK:
                lock_days += 1
                i -= 1
            gap = (today["open"] / prev["close"] - 1) * 100
            body = (today["close"] - today["open"]) / prev["close"] * 100
            pr_vol = prev["volume"]
            vol_ratio = (today["volume"] / pr_vol) if pr_vol else None
            nxt = next_session(hist, d)
            if nxt is None:
                continue
            ret = (nxt["close"] / today["close"] - 1) * 100
            pnl = TP - COST if ret >= TP else (SL - COST if ret <= SL else ret - COST)
            rows.append({"sym": sym, "date": d, "pnl": pnl, "ext": ext,
                         "lock_days": lock_days, "gap": gap, "body": body,
                         "vol_ratio": vol_ratio, "value": value,
                         "month": d[:7]})
    return rows


def stats(g):
    n = len(g)
    if not n:
        return None
    w = sum(1 for r in g if r["pnl"] > 0.5)
    s = sum(1 for r in g if r["pnl"] < -0.5)
    return {"n": n, "win": 100 * w / n, "stop": 100 * s / n,
            "avg": sum(r["pnl"] for r in g) / n, "total": sum(r["pnl"] for r in g)}


def pick_daily(rows, month_key=None):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    picks = []
    for d, g in sorted(by_date.items()):
        if month_key and d[:7] != month_key:
            continue
        g2 = sorted(g, key=lambda r: (
            -(3.0 if r["lock_days"] == 2 else (1.5 if r["lock_days"] >= 3 else 0.0)),
            -r["ext"]))
        picks.append(g2[0])
    return picks


def main():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dates = all_dates(corpus)[-90:]
    rows = build_rows(corpus, dates)
    disc = [r for r in rows if r["date"] < "2026-08-01"]
    val = [r for r in rows if r["date"] >= "2026-08-01"]
    print(f"rows: {len(rows)}  (discovery {len(disc)}, validation {len(val)})\n")

    # class average, monthly
    print("== lock-class cohort, by month ==")
    bym = defaultdict(list)
    for r in rows:
        bym[r["month"]].append(r)
    for m in sorted(bym):
        s = stats(bym[m])
        print(f"  {m}: n={s['n']:>3}  win {s['win']:5.1f}%  avg {s['avg']:+.2f}%")

    # policy picks, by month
    print("\n== v2.3.1 rank-1 policy, by month ==")
    picks = pick_daily(rows)
    pby = defaultdict(list)
    for p in picks:
        pby[p["month"]].append(p)
    tot_w = tot_n = 0
    tot_pnl = 0.0
    for m in sorted(pby):
        s = stats(pby[m])
        tot_w += sum(1 for r in pby[m] if r["pnl"] > 0.5)
        tot_n += len(pby[m])
        tot_pnl += s["total"]
        print(f"  {m}: n={s['n']:>2}  win {s['win']:5.1f}%  avg {s['avg']:+.2f}%  total {s['total']:+.2f}%")
    print(f"  ALL: n={tot_n}  win {100*tot_w/tot_n:.1f}%  total {tot_pnl:+.2f}%")

    # discovery/validation for the policy and for new candidate rules
    print("\n== policy on the split ==")
    for label, sub in (("DISCOVERY", disc), ("VALIDATION", val)):
        p = pick_daily(sub)
        if p:
            s = stats(p)
            print(f"  {label}: n={s['n']}  win {s['win']:.1f}%  avg {s['avg']:+.2f}%")

    print("\n== new candidate slices (need BOTH halves) ==")
    for name, pred in [
        ("2nd-lock only", lambda r: r["lock_days"] == 2),
        ("3+ locks", lambda r: r["lock_days"] >= 3),
        ("first lock", lambda r: r["lock_days"] == 1),
        ("vol_ratio < 1.5", lambda r: r["vol_ratio"] and r["vol_ratio"] < 1.5),
        ("gap in [0,5)", lambda r: 0.0 <= r["gap"] < 5.0),
        ("body >= 3%", lambda r: r["body"] >= 3.0),
        ("small value <50M", lambda r: r["value"] < 50e6),
        ("50-150M", lambda r: 50e6 <= r["value"] < 150e6),
    ]:
        d1, v1 = stats([r for r in disc if pred(r)]), stats([r for r in val if pred(r)])
        if d1 and v1:
            verdict = "HOLDS" if (d1["avg"] > -0.2 and v1["avg"] > -0.2) else "fails"
            print(f"  {name:<18} D: n={d1['n']:>3} {d1['win']:5.1f}% {d1['avg']:+.2f} | "
                  f"V: n={v1['n']:>3} {v1['win']:5.1f}% {v1['avg']:+.2f}  -> {verdict}")


if __name__ == "__main__":
    main()
