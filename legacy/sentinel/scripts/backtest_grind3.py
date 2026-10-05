"""The grind, round 3: confluence features on the lock class.

New features joined to the corpus (all knowable at 15:29):
  * sector heat  - share of the symbol's sector (EOD sector_map.json)
    that closed green on the pick day (0..1); a lock inside a sector
    where everything is green is a sector move, not a one-off;
  * vol_ratio    - pick-day volume / prior-day volume (distribution
    trap refined: is the >=500M veto just a vol_ratio proxy?);
  * tape         - equal-weight market change on the pick day.

Questions, each with the discovery/validation split:
  Q1 does sector heat separate winners?
  Q2 is the 500M veto a vol_ratio effect?
  Q3 does a red-tape veto (tape <= -1%) add anything?
  Q4 best COMBINED policy vs v2.3.1.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
EOD_SECTORS = HERE.parent / "Sentinel-EOD" / "data" / "sector_map.json"
CORPUS = HERE / "data" / "backtest" / "eod_corpus.json"
COST = 0.848
TP = 2.0
SL = -1.0
LOCK = 9.9
DISTRIBUTION = 500_000_000.0


def next_session(hist, d):
    from datetime import date as _d

    for row in hist:
        if row["date"] > d:
            gap = (_d.fromisoformat(row["date"]) - _d.fromisoformat(d)).days
            if gap > 7:
                return None
            return row
    return None


def all_dates(corpus):
    dates = set()
    for hist in corpus.values():
        for row in hist:
            dates.add(row["date"])
    return sorted(dates)


def main():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    sectors = json.loads(EOD_SECTORS.read_text(encoding="utf-8")).get("symbolToSector", {})
    dates = all_dates(corpus)[-30:]

    prev_of = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_of[(sym, hist[i]["date"])] = hist[i - 1]

    # market tape per day
    tape = {}
    for d in dates:
        chgs = []
        for sym, hist in corpus.items():
            i = next((k for k, r in enumerate(hist) if r["date"] == d), None)
            if i and i > 0 and hist[i - 1]["close"] > 0:
                chgs.append((hist[i]["close"] / hist[i - 1]["close"] - 1) * 100)
        tape[d] = statistics.mean(chgs) if chgs else 0.0

    rows = []
    for j, d in enumerate(dates[:-1]):
        nd = dates[j + 1]
        # sector health: green share per sector today
        day_changes = {}
        for sym, hist in corpus.items():
            i = next((k for k, r in enumerate(hist) if r["date"] == d), None)
            if i and i > 0 and hist[i - 1]["close"] > 0:
                day_changes[sym] = (hist[i]["close"] / hist[i - 1]["close"] - 1) * 100
        sec_green = defaultdict(list)
        for sym, c in day_changes.items():
            s = sectors.get(sym)
            if s:
                sec_green[s].append(c)
        for sym, hist in corpus.items():
            today = next((r for r in hist if r["date"] == d), None)
            prev = prev_of.get((sym, d))
            if today is None or prev is None or prev["close"] <= 0:
                continue
            ext = (today["close"] / prev["close"] - 1) * 100
            if ext < LOCK:
                continue
            value = today["volume"] * (today["open"] + today["close"]) / 2
            if today["close"] < 20 or value < 5_000_000 or value >= DISTRIBUTION:
                continue
            i = hist.index(today)
            lock_days = 1
            while i > 1 and hist[i - 1]["close"] > 0 and hist[i - 2]["close"] > 0 and \
                    (hist[i - 1]["close"] / hist[i - 2]["close"] - 1) * 100 >= LOCK:
                lock_days += 1
                i -= 1
            pr_vol = prev["volume"]
            vol_ratio = (today["volume"] / pr_vol) if pr_vol else None
            sec = sectors.get(sym)
            peers = sec_green.get(sec, [])
            heat = (sum(1 for c in peers if c > 0) / len(peers)) if peers else None
            nxt = next_session(hist, d)
            if nxt is None:
                continue
            ret = (nxt["close"] / today["close"] - 1) * 100
            pnl = TP - COST if ret >= TP else (SL - COST if ret <= SL else ret - COST)
            rows.append({"sym": sym, "date": d, "pnl": pnl, "ext": ext,
                         "lock_days": lock_days, "vol_ratio": vol_ratio,
                         "heat": heat, "tape": tape[d]})

    disc = [r for r in rows if r["date"] <= "2026-09-04"]
    val = [r for r in rows if r["date"] >= "2026-09-07"]

    def q1(sub, label):
        print(f"-- Q1 sector heat [{label}] --")
        for lo, hi, name in [(None, 0.5, "<0.5 (cold/one-off)"),
                             (0.5, 0.8, "0.5-0.8"),
                             (0.8, None, ">=0.8 (sector-wide move)")]:
            g = [r for r in sub if r["heat"] is not None and
                 (lo is None or r["heat"] >= lo) and (hi is None or r["heat"] < hi)]
            if g:
                w = sum(1 for r in g if r["pnl"] > 0.5)
                print(f"  {name:<26} n={len(g):>3}  win {100*w/len(g):5.1f}%  avg {sum(r['pnl'] for r in g)/len(g):+.2f}%")
        nh = [r for r in sub if r["heat"] is None]
        if nh:
            w = sum(1 for r in nh if r["pnl"] > 0.5)
            print(f"  {'no sector data':<26} n={len(nh):>3}  win {100*w/len(nh):5.1f}%  avg {sum(r['pnl'] for r in nh)/len(nh):+.2f}%")

    def q2(sub, label):
        print(f"-- Q2 vol_ratio [{label}] --")
        for lo, hi, name in [(None, 1.5, "<1.5 (quiet lock)"),
                             (1.5, 3.0, "1.5-3"),
                             (3.0, 6.0, "3-6"),
                             (6.0, None, ">=6 (blow-off volume)")]:
            g = [r for r in sub if r["vol_ratio"] is not None and
                 (lo is None or r["vol_ratio"] >= lo) and (hi is None or r["vol_ratio"] < hi)]
            if g:
                w = sum(1 for r in g if r["pnl"] > 0.5)
                print(f"  {name:<26} n={len(g):>3}  win {100*w/len(g):5.1f}%  avg {sum(r['pnl'] for r in g)/len(g):+.2f}%")

    def q3(sub, label):
        print(f"-- Q3 red-tape veto [{label}] --")
        for name, pred in [("tape <= -1%", lambda r: r["tape"] <= -1.0),
                           ("tape > -1%", lambda r: r["tape"] > -1.0)]:
            g = [r for r in sub if pred(r)]
            if g:
                w = sum(1 for r in g if r["pnl"] > 0.5)
                print(f"  {name:<26} n={len(g):>3}  win {100*w/len(g):5.1f}%  avg {sum(r['pnl'] for r in g)/len(g):+.2f}%")

    def pick_best(sub, label, red_bonus=0.0):
        # v2.3.1 rank: 2nd lock 3.0, 3+ 1.5, ext/value tiebreak
        by_date = defaultdict(list)
        for r in sub:
            by_date[r["date"]].append(r)
        picks = []
        for d, g in sorted(by_date.items()):
            def key(r):
                base = 3.0 if r["lock_days"] == 2 else (1.5 if r["lock_days"] >= 3 else 0.0)
                bonus = red_bonus if r.get("tape", 0.0) <= -1.0 else 0.0
                return -(base + bonus)
            g = sorted(g, key=lambda r: (key(r), -r["ext"]))
            picks.append(g[0])
        n = len(picks)
        w = sum(1 for r in picks if r["pnl"] > 0.5)
        print(f"-- v2.3.1 [{label}]: n={n} win {100*w/n:.1f}% avg {sum(r['pnl'] for r in picks)/n:+.2f}%")
        if red_bonus:
            picks2 = []
            for d, g in sorted(by_date.items()):
                g2 = sorted(g, key=lambda r: (
                    -((3.0 if r["lock_days"] == 2 else (1.5 if r["lock_days"] >= 3 else 0.0)) + (0.5 if r.get("tape", 0.0) <= -1.0 else 0.0)),
                    -r["ext"]))
                picks2.append(g2[0])
            w2 = sum(1 for r in picks2 if r["pnl"] > 0.5)
            print(f"   +red-tape bonus 0.5: n={len(picks2)} win {100*w2/len(picks2):.1f}% avg {sum(r['pnl'] for r in picks2)/len(picks2):+.2f}%")

    for sub, label in [(disc, "DISCOVERY"), (val, "VALIDATION")]:
        q1(sub, label)
        q2(sub, label)
        q3(sub, label)
        pick_best(sub, label, red_bonus=0.5)
        print()


if __name__ == "__main__":
    main()
