"""Policy-level test: refine the one-pick-per-day rule with the miner's
findings and measure it under the same close-bracket sim.

Baseline (v2.2.7 as shipped): best >=8% candidate by extension/value.
Refined: LOCKED closes only (>=9.9%), two vetoes the data condemned
(>=500M traded value = the distribution trap; open-gap 5-8% = the
failed-gap zone), then rank by momentum quality:
  lock_streak==2 bonus, green-streak>=3 bonus, held-gap 2-5% bonus.
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


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    dates = trading_dates(corpus)

    prev_of: dict[tuple[str, str], dict] = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_of[(sym, hist[i]["date"])] = hist[i - 1]

    def green_streak(sym: str, d: str) -> int:
        hist = corpus[sym]
        idx = next((i for i, r in enumerate(hist) if r["date"] == d), None)
        n = 0
        if idx:
            i = idx
            while i > 0 and hist[i]["close"] > hist[i - 1]["close"] > 0:
                n += 1
                i -= 1
        return n

    def lock_streak(sym: str, d: str) -> int:
        hist = corpus[sym]
        idx = next((i for i, r in enumerate(hist) if r["date"] == d), None)
        n = 0
        if idx:
            i = idx
            while i > 0 and hist[i - 1]["close"] > 0 and \
                    (hist[i]["close"] / hist[i - 1]["close"] - 1) * 100 >= 9.9:
                n += 1
                i -= 1
        return n

    regime = {}
    for d in dates:
        chgs = []
        for sym, hist in corpus.items():
            i = next((k for k, r in enumerate(hist) if r["date"] == d), None)
            if i and i > 0 and hist[i - 1]["close"] > 0:
                chgs.append((hist[i]["close"] / hist[i - 1]["close"] - 1) * 100)
        regime[d] = statistics.mean(chgs) if chgs else 0.0

    def build(mode: str):
        picks = []
        for d in dates:
            cands = []
            for sym, hist in corpus.items():
                today = next((r for r in hist if r["date"] == d), None)
                prev = prev_of.get((sym, d))
                if today is None or prev is None or prev["close"] <= 0:
                    continue
                ext = (today["close"] / prev["close"] - 1) * 100
                value = today["volume"] * (today["open"] + today["close"]) / 2
                if today["close"] < PRICE_FLOOR or value < VALUE_FLOOR:
                    continue
                if today["close"] <= prev["close"] or today["close"] <= today["open"]:
                    continue
                if mode == "baseline":
                    if ext < 8.0:
                        continue
                else:  # refined
                    if ext < 9.9:      # locked-at-close only
                        continue
                    if value >= 500e6:  # distribution trap
                        continue
                    og = (today["open"] / prev["close"] - 1) * 100
                    if 5.0 <= og < 8.0:  # failed-gap zone
                        continue
                cands.append({"sym": sym, "ext": ext, "value": value,
                              "entry": today["close"], "date": d,
                              "gap": (today["open"] / prev["close"] - 1) * 100,
                              "ls": lock_streak(sym, d),
                              "gs": green_streak(sym, d)})
            if not cands:
                continue
            if mode == "baseline":
                cands.sort(key=lambda c: (-c["ext"], -c["value"]))
            else:
                def score(c):
                    s = 0.0
                    if c["ls"] == 2:
                        s += 3.0
                    elif c["ls"] >= 3:
                        s += 1.5
                    if c["gs"] >= 3:
                        s += 2.0
                    if 2.0 <= c["gap"] < 5.0:
                        s += 1.5
                    return s
                cands.sort(key=lambda c: (-score(c), -c["ext"], -c["value"]))
            top = cands[0]
            nxt = next_session(corpus[top["sym"]], d)
            if nxt is None:
                continue
            ret = (nxt["close"] / top["entry"] - 1) * 100
            if ret >= TP:
                outcome, pnl = "WIN", TP - COST
            elif ret <= SL:
                outcome, pnl = "STOP", SL - COST
            else:
                outcome, pnl = "FORCE", ret - COST
            picks.append({**top, "outcome": outcome, "pnl": pnl,
                          "tape": regime[d]})
        return picks

    for mode in ("baseline", "refined"):
        picks = build(mode)
        n = len(picks)
        wins = sum(1 for p in picks if p["outcome"] == "WIN")
        stops = sum(1 for p in picks if p["outcome"] == "STOP")
        forces = sum(1 for p in picks if p["outcome"] == "FORCE")
        avg = sum(p["pnl"] for p in picks) / n if n else 0.0
        print(f"{mode:>8}: n={n}  WIN {wins} ({100*wins/n:.1f}%)  STOP {stops}  "
              f"FORCE {forces}  avg {avg:+.3f}%  total {sum(p['pnl'] for p in picks):+.2f}%")
        if mode == "refined":
            # regime split - the one question left
            for lab, pred in [("red-tape days", lambda p: p["tape"] < -0.3),
                              ("green-tape days", lambda p: p["tape"] > 0.3),
                              ("flat days", lambda p: -0.3 <= p["tape"] <= 0.3)]:
                sub = [p for p in picks if pred(p)]
                if sub:
                    w = sum(1 for p in sub if p["outcome"] == "WIN")
                    a = sum(p["pnl"] for p in sub) / len(sub)
                    print(f"          {lab:<16} n={len(sub)}  WIN {100*w/len(sub):.0f}%  avg {a:+.2f}%")
            print()
            for p in picks:
                print(f"  {p['date']} {p['sym']:6s} ext {p['ext']:4.1f}% ls{p['ls']} gs{p['gs']} "
                      f"gap {p['gap']:4.1f}% -> {p['outcome']:5s} {p['pnl']:+6.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
