"""Backtest the EXACT live EOD policy (v2.2.7) over the 30-day corpus.

Policy: one pick per day (the owner's law) - the single best >=8%
extension candidate (green day, green candle, >=20 PKR, >=5M traded
value), bought at that day's close (the real 15:29/16:29 fill).

Honest close-bracket sim (no intraday high/low exists in DPS history):
  * D+1 close >= entry*1.02 -> WIN (+2.0)
  * D+1 close <= entry*0.99 -> STOP (-1.0)
  * else                    -> force-close at D+1 close
Costs 0.848% round trip. Same method as eod30_report.json, so the
class-average rows there are the direct baseline for rank-1 here.

Also prints the top-3 each day to show how sensitive rank-1 is.
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


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dates = trading_dates(corpus)

    prev_close: dict[tuple[str, str], dict] = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_close[(sym, hist[i]["date"])] = {
                "close": hist[i - 1]["close"],
                "vol": hist[i - 1]["volume"],
            }

    picks = []
    no_cand_days = []
    for d in dates:
        cands = []
        for sym, hist in corpus.items():
            today = next((r for r in hist if r["date"] == d), None)
            prev = prev_close.get((sym, d))
            if today is None or prev is None or prev["close"] <= 0:
                continue
            ext = (today["close"] / prev["close"] - 1) * 100
            value = today["volume"] * (today["open"] + today["close"]) / 2
            if today["close"] < PRICE_FLOOR or value < VALUE_FLOOR:
                continue
            if today["close"] <= prev["close"] or today["close"] <= today["open"]:
                continue
            if ext < 8.0:
                continue
            cands.append({"sym": sym, "ext": ext, "value": value,
                          "entry": today["close"], "date": d})
        if not cands:
            no_cand_days.append(d)
            continue
        # rank: strongest extension first (momentum-lock quality), value tiebreak
        cands.sort(key=lambda c: (-c["ext"], -c["value"]))
        for rank, c in enumerate(cands[:3], 1):
            nxt = next_session(corpus[c["sym"]], d)
            if nxt is None:
                continue
            ret = (nxt["close"] / c["entry"] - 1) * 100
            if ret >= TP:
                outcome, pnl = "WIN", TP - COST
            elif ret <= SL:
                outcome, pnl = "STOP", SL - COST
            else:
                outcome, pnl = "FORCE", ret - COST
            picks.append({**c, "rank": rank, "exit_date": nxt["date"],
                          "ret": round(ret, 2), "outcome": outcome,
                          "pnl": round(pnl, 3)})

    r1 = [p for p in picks if p["rank"] == 1]
    print(f"window {dates[0]} .. {dates[-1]}  (TP {TP}/SL {SL}, cost {COST})")
    print(f"sessions: {len(dates)}, rank-1 picks: {len(r1)}, "
          f"no-candidate days: {len(no_cand_days)} -> {no_cand_days}")
    if r1:
        wins = [p for p in r1 if p["outcome"] == "WIN"]
        stops = [p for p in r1 if p["outcome"] == "STOP"]
        forces = [p for p in r1 if p["outcome"] == "FORCE"]
        avg = sum(p["pnl"] for p in r1) / len(r1)
        print(f"rank-1: n={len(r1)}  WIN {len(wins)} ({100*len(wins)/len(r1):.1f}%)  "
              f"STOP {len(stops)}  FORCE {len(forces)}")
        print(f"avg net per pick: {avg:+.3f}%   total net: {sum(p['pnl'] for p in r1):+.2f}%")
        print()
        for p in r1:
            alts = [f"{q['sym']}({q['ret']:+.1f})" for q in picks
                    if q["date"] == p["date"] and q["rank"] > 1]
            print(f"  {p['date']} {p['sym']:6s} ext {p['ext']:5.1f}% -> {p['outcome']:5s} "
                  f"net {p['pnl']:+6.2f}%   alts: {', '.join(alts) if alts else '-'}")
        # rank sensitivity: what if picks 2 or 3 were taken instead
        for rk in (2, 3):
            sub = [p for p in picks if p["rank"] == rk]
            if sub:
                w = sum(1 for p in sub if p["outcome"] == "WIN")
                a = sum(p["pnl"] for p in sub) / len(sub)
                print(f"rank-{rk} would-be: n={len(sub)} win {100*w/len(sub):.0f}% avg net {a:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
