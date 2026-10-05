"""Does the LOCK law (v2.3.0) break the intraday book?

The EOD corpus law says locked closes continue overnight (52.7-73.3%).
The intraday Sentinel hard-bans >=8% chases (Rule 25: 6.9% intraday
win). Both can be true - different QUESTIONS:
  * intraday: buy DURING day D after it is already +8% -> chases a
    spent intraday move into profit-taking;
  * overnight: buy at D's CLOSE after the lock sealed -> holds the
    proven momentum through the night.

This script proves the boundary on data: simulate buying prior-day
locked names AT THE NEXT OPEN (the intraday bot's realistic entry)
vs buying them at the prior CLOSE (the EOD's entry). If the open-entry
is still bad, Rule 25 and the lock law are complementary, not
contradictory - and the intraday book should NOT hunt locks at the
open; its edge must come from somewhere else (measured next).
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
PRICE_FLOOR = 20.0
VALUE_FLOOR = 5_000_000.0
MAX_GAP_DAYS = 7


def trading_dates(corpus: dict) -> list[str]:
    dates = set()
    for hist in corpus.values():
        for row in hist:
            dates.add(row["date"])
    return sorted(dates)[-30:]


def next_session(hist: list[dict], d: str) -> dict | None:
    from datetime import date as _d

    for row in hist:
        if row["date"] > d:
            gap = (_d.fromisoformat(row["date"]) - _d.fromisoformat(d)).days
            if gap > MAX_GAP_DAYS:
                return None
            return row
    return None


def sim(entries: list[dict], label: str) -> None:
    wins = stops = forces = 0
    pnls = []
    for e in entries:
        ret = (e["exit_close"] / e["entry"] - 1) * 100
        if ret >= TP:
            wins += 1
            pnls.append(TP - COST)
        elif ret <= SL:
            stops += 1
            pnls.append(SL - COST)
        else:
            forces += 1
            pnls.append(ret - COST)
    n = len(entries)
    if not n:
        print(f"{label:<42} n=0")
        return
    print(f"{label:<42} n={n:>3}  win {100*wins/n:5.1f}%  stop {100*stops/n:5.1f}%  "
          f"force {100*forces/n:5.1f}%  avg net {sum(pnls)/n:+.2f}%")


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dates = trading_dates(corpus)
    prev_of: dict[tuple[str, str], dict] = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_of[(sym, hist[i]["date"])] = hist[i - 1]

    at_close = []   # EOD entry: pick-day close -> next close bracket
    at_open = []    # intraday-style entry: next-day open -> next-day close
    by_lock = defaultdict(lambda: ([], []))

    for d in dates:
        for sym, hist in corpus.items():
            today = next((r for r in hist if r["date"] == d), None)
            prev = prev_of.get((sym, d))
            if today is None or prev is None or prev["close"] <= 0:
                continue
            ext = (today["close"] / prev["close"] - 1) * 100
            if ext < 9.9:
                continue
            value = today["volume"] * (today["open"] + today["close"]) / 2
            if today["close"] < PRICE_FLOOR or value >= 500_000_000:
                continue
            nxt = next_session(hist, d)
            if nxt is None:
                continue
            at_close.append({"entry": today["close"], "exit_close": nxt["close"]})
            if nxt["open"] and nxt["open"] > 0:
                at_open.append({"entry": nxt["open"], "exit_close": nxt["close"]})
            ls = 1
            i = hist.index(today) - 1
            while i > 0 and hist[i]["close"] > 0 and hist[i - 1]["close"] > 0 and \
                    (hist[i]["close"] / hist[i - 1]["close"] - 1) * 100 >= 9.9:
                ls += 1
                i -= 1
            band = "2nd lock" if ls == 2 else ("3+ locks" if ls >= 3 else "1st lock")
            by_lock[band][0].append({"entry": today["close"], "exit_close": nxt["close"]})
            if nxt["open"] and nxt["open"] > 0:
                by_lock[band][1].append({"entry": nxt["open"], "exit_close": nxt["close"]})

    print(f"locked closes (>=9.9%, <500M, >=20 PKR), 30 sessions\n")
    sim(at_close, "BUY AT PICK-DAY CLOSE (the EOD trade)")
    sim(at_open, "BUY AT NEXT-DAY OPEN (the intraday chase)")
    print()
    for band in ("1st lock", "2nd lock", "3+ locks"):
        cl, op = by_lock[band]
        sim(cl, f"  {band} - at close")
        sim(op, f"  {band} - at open")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
