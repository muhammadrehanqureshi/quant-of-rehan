"""The grind, round 2: can ANY policy reachable from daily bars push the
EOD lock law past its 74.1%?

Discipline (the only honest way to hunt):
  * DISCOVERY on Aug 6 - Sep 4 (first 22 sessions);
  * VALIDATION on Sep 7 - Sep 18 (last 8 sessions, never looked at
    during discovery);
  * a rule ships only if BOTH halves hold.

Policy space explored:
  P0 baseline            lock closes (>=9.9), rank by extension
  P1 +2nd-lock bonus     v2.3.0 as shipped
  P2 veto 3+ locks       (3+ measured 57.9%, but discovery says?)
  P3 veto lock after a down-lock yesterday (whipsaw class)
  P4 require body >= 3%  (the day must be a real surge, not drift)
  P5 require gap-in-[0..5) (no huge gap opens)
  P6 rank by value asc   (smaller = cleaner? tested, likely no)
  P7 veto ext >= 10.5 (impossible on PSX 10% circuit = bad data)
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"
COST = 0.848
TP = 2.0
SL = -1.0
PRICE_FLOOR = 20.0
VALUE_FLOOR = 5_000_000.0
DISTRIBUTION = 500_000_000.0
LOCK = 9.9
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
            if today["close"] < PRICE_FLOOR or value < VALUE_FLOOR:
                continue
            # lock streak INCLUDING today
            i = hist.index(today)
            lock_days = 1
            while i > 1 and hist[i - 1]["close"] > 0 and hist[i - 2]["close"] > 0 and \
                    (hist[i - 1]["close"] / hist[i - 2]["close"] - 1) * 100 >= LOCK:
                lock_days += 1
                i -= 1
            # yesterday's shape (the session before the pick day)
            i = hist.index(today)
            y_ext = None
            if i >= 2 and hist[i - 2]["close"] > 0:
                y_ext = (hist[i - 1]["close"] / hist[i - 2]["close"] - 1) * 100
            body = (today["close"] - today["open"]) / prev["close"] * 100
            gap = (today["open"] / prev["close"] - 1) * 100
            nxt = next_session(hist, d)
            if nxt is None:
                continue
            ret = (nxt["close"] / today["close"] - 1) * 100
            pnl = TP - COST if ret >= TP else (SL - COST if ret <= SL else ret - COST)
            rows.append({
                "sym": sym, "date": d, "pnl": pnl, "ext": ext,
                "lock_days": lock_days, "y_ext": y_ext, "body": body,
                "gap": gap, "value": value,
            })
    return rows


def pick_day(rows, d, policy):
    cands = [r for r in rows if r["date"] == d]
    # universal vetoes first (already-shipped law)
    cands = [r for r in cands if r["value"] < DISTRIBUTION]
    if policy >= 7 and cands:
        cands = [r for r in cands if r["ext"] <= 10.5] or cands
    if policy >= 6 and cands:
        pass  # P6 handled in ranking, not veto
    if policy >= 5 and cands:
        kept = [r for r in cands if 0.0 <= r["gap"] < 5.0]
        cands = kept or cands
    if policy >= 4 and cands:
        kept = [r for r in cands if r["body"] >= 3.0]
        cands = kept or cands
    if policy >= 3 and cands:
        # veto the whipsaw: locked today after a down-lock yesterday
        kept = [r for r in cands if not (r["y_ext"] is not None and r["y_ext"] <= -LOCK)]
        cands = kept or cands
    if policy >= 2 and cands:
        # veto 3+ locks (over-extended per discovery?) - keep 1-2 only
        kept = [r for r in cands if r["lock_days"] <= 2]
        cands = kept or cands
    if not cands:
        return None
    if policy == 0:
        cands.sort(key=lambda r: -r["ext"])
    elif policy == 6:
        cands.sort(key=lambda r: r["value"])  # smallest value first
    else:
        def score(r):
            s = 0.0
            if r["lock_days"] == 2:
                s += 3.0
            elif r["lock_days"] >= 3:
                s += 1.5
            if r["green_streak"] >= 3:
                s += 2.0
            if 2.0 <= r["gap"] < 5.0:
                s += 1.5
            return s
        # green_streak not carried in rows; approximate with lock_days+body
        cands.sort(key=lambda r: (
            -(3.0 if r["lock_days"] == 2 else (1.5 if r["lock_days"] >= 3 else 0.0)),
            -r["ext"], -r["value"],
        ))
    return cands[0]


def evaluate(rows, label):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    dates = sorted(by_date)
    print(f"-- {label} --")
    for p in range(8):
        picks = []
        for d in dates:
            b = pick_day(rows, d, p)
            if b:
                picks.append(b)
        n = len(picks)
        if not n:
            print(f"  P{p}: no picks")
            continue
        wins = sum(1 for x in picks if x["pnl"] > 0.5)
        stops = sum(1 for x in picks if x["pnl"] < -0.5)
        avg = sum(x["pnl"] for x in picks) / n
        print(f"  P{p}: n={n:>2}  win {100*wins/n:5.1f}%  stop {100*stops/n:4.0f}%  avg {avg:+.2f}%  total {sum(x['pnl'] for x in picks):+.2f}%")
    print()


def main():
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dates = all_dates(corpus)[-30:]
    rows = build_rows(corpus, dates)
    disc = [r for r in rows if r["date"] <= "2026-09-04"]
    val = [r for r in rows if r["date"] >= "2026-09-07"]
    evaluate(disc, f"DISCOVERY  {disc[0]['date']} .. {disc[-1]['date']}  (rows={len(disc)})")
    evaluate(val, f"VALIDATION {val[0]['date']} .. {val[-1]['date']}  (rows={len(val)})")
    evaluate(rows, "FULL 30 (check, not proof)")


if __name__ == "__main__":
    main()
