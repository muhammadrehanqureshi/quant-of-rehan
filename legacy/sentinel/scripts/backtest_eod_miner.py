"""Intra-class miner: within the >=8% lock class, what feature separates
the next-day WIN from the STOP? All features computed from pick-day data
only (no look-ahead). Outcome: close-bracket TP2/SL1 on the next session.

Candidate features (all knowable at 15:29 when the order is placed):
  ext         extension over prior close (%)
  locked      day closed AT the upper lock (ext >= 9.9)
  value       traded value (PKR)
  vol_ratio   volume / prior-day volume
  open_gap    (open / prior close - 1) * 100  (gap-up that held vs grind)
  body        (close - open) / prior close * 100
  streak      consecutive green days ending on the pick day
  lock_streak consecutive >=9.9% lock days ending on the pick day
  tape        market regime that day (equal-weight mean member change)
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
    dset = set(dates)

    # ordered history per symbol + prior-row lookup
    hist_by = corpus
    prev_of: dict[tuple[str, str], dict] = {}
    for sym, hist in hist_by.items():
        for i in range(1, len(hist)):
            prev_of[(sym, hist[i]["date"])] = hist[i - 1]

    # streaks: consecutive green / lock days ending at (sym, d)
    def green_streak(sym: str, d: str) -> int:
        hist = hist_by[sym]
        idx = next((i for i, r in enumerate(hist) if r["date"] == d), None)
        if idx is None:
            return 0
        n = 0
        i = idx
        while i > 0:
            cur, prev = hist[i], hist[i - 1]
            if cur["close"] > prev["close"] > 0:
                n += 1
                i -= 1
            else:
                break
        return n

    def lock_streak(sym: str, d: str) -> int:
        hist = hist_by[sym]
        idx = next((i for i, r in enumerate(hist) if r["date"] == d), None)
        if idx is None:
            return 0
        n = 0
        i = idx
        while i > 0:
            cur, prev = hist[i], hist[i - 1]
            if prev["close"] > 0 and (cur["close"] / prev["close"] - 1) * 100 >= 9.9:
                n += 1
                i -= 1
            else:
                break
        return n

    # market regime per day
    regime = {}
    for d in dates:
        chgs = []
        for sym, hist in hist_by.items():
            i = next((k for k, r in enumerate(hist) if r["date"] == d), None)
            if i and i > 0:
                pc = hist[i - 1]["close"]
                if pc > 0:
                    chgs.append((hist[i]["close"] / pc - 1) * 100)
        regime[d] = statistics.mean(chgs) if chgs else 0.0

    rows = []
    for d in dates:
        for sym, hist in hist_by.items():
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
            if ext < 8.0:
                continue
            nxt = next_session(hist, d)
            if nxt is None:
                continue
            ret = (nxt["close"] / today["close"] - 1) * 100
            if ret >= TP:
                outcome, pnl = "WIN", TP - COST
            elif ret <= SL:
                outcome, pnl = "STOP", SL - COST
            else:
                outcome, pnl = "FORCE", ret - COST
            pr_vol = prev["volume"] if prev["volume"] else None
            rows.append({
                "sym": sym, "date": d, "outcome": outcome, "pnl": pnl,
                "ext": ext,
                "locked": ext >= 9.9,
                "value": value,
                "vol_ratio": (today["volume"] / pr_vol) if pr_vol else None,
                "open_gap": (today["open"] / prev["close"] - 1) * 100,
                "body": (today["close"] - today["open"]) / prev["close"] * 100,
                "streak": green_streak(sym, d),
                "lock_streak": lock_streak(sym, d),
                "tape": regime[d],
            })

    wins = [r for r in rows if r["outcome"] == "WIN"]
    print(f"class rows: {len(rows)}  (WIN {len(wins)}, "
          f"STOP {sum(1 for r in rows if r['outcome']=='STOP')}, "
          f"FORCE {sum(1 for r in rows if r['outcome']=='FORCE')})  "
          f"class avg net {sum(r['pnl'] for r in rows)/len(rows):+.2f}%\n")

    def report(name: str, key, buckets: list[tuple[str, object]]):
        print(f"-- {name} --")
        for label, pred in buckets:
            sub = [r for r in rows if pred(r)]
            if not sub:
                continue
            w = sum(1 for r in sub if r["outcome"] == "WIN")
            s = sum(1 for r in sub if r["outcome"] == "STOP")
            avg = sum(r["pnl"] for r in sub) / len(sub)
            print(f"  {label:<22} n={len(sub):>3}  WIN {100*w/len(sub):5.1f}%  STOP {100*s/len(sub):5.1f}%  avg {avg:+.2f}%")
        print()

    report("lock at close (ext>=9.9) vs strong-not-locked",
           "locked",
           [("LOCKED at close", lambda r: r["locked"]),
            ("8.0-9.9% strong", lambda r: not r["locked"])])

    report("lock_streak (consecutive lock days)",
           "lock_streak",
           [("first lock day (1)", lambda r: r["lock_streak"] == 1),
            ("2 lock days", lambda r: r["lock_streak"] == 2),
            ("3+ lock days", lambda r: r["lock_streak"] >= 3)])

    report("green streak ending today",
           "streak",
           [("1-2 days", lambda r: r["streak"] <= 2),
            ("3-4 days", lambda r: 3 <= r["streak"] <= 4),
            ("5+ days", lambda r: r["streak"] >= 5)])

    report("open_gap (how the day started)",
           "open_gap",
           [("flat/slight (<2%)", lambda r: r["open_gap"] < 2),
            ("gap 2-5%", lambda r: 2 <= r["open_gap"] < 5),
            ("gap 5-8%", lambda r: 5 <= r["open_gap"] < 8),
            ("gap >=8%", lambda r: r["open_gap"] >= 8)])

    report("body (close vs open over prior close)",
           "body",
           [("small (<3%)", lambda r: r["body"] < 3),
            ("3-6%", lambda r: 3 <= r["body"] < 6),
            (">=6% huge body", lambda r: r["body"] >= 6)])

    vr = [r for r in rows if r["vol_ratio"]]
    if vr:
        vals = sorted(x["vol_ratio"] for x in vr)
        med = vals[len(vals) // 2]
        print(f"-- vol_ratio (median {med:.2f}) --")
        for label, pred in [("below median", lambda r: r["vol_ratio"] and r["vol_ratio"] < med),
                            ("at/above median", lambda r: r["vol_ratio"] and r["vol_ratio"] >= med)]:
            sub = [r for r in vr if pred(r)]
            if sub:
                w = sum(1 for r in sub if r["outcome"] == "WIN")
                avg = sum(r["pnl"] for r in sub) / len(sub)
                print(f"  {label:<22} n={len(sub):>3}  WIN {100*w/len(sub):5.1f}%  avg {avg:+.2f}%")
        print()

    report("market tape on pick day",
           "tape",
           [("red tape (<-0.3%)", lambda r: r["tape"] < -0.3),
            ("flat tape", lambda r: -0.3 <= r["tape"] <= 0.3),
            ("green tape (>+0.3%)", lambda r: r["tape"] > 0.3)])

    report("traded value",
           "value",
           [("<20M", lambda r: r["value"] < 20e6),
            ("20-100M", lambda r: 20e6 <= r["value"] < 100e6),
            ("100-500M", lambda r: 100e6 <= r["value"] < 500e6),
            (">=500M", lambda r: r["value"] >= 500e6)])

    # the two-way combos that matter
    print("-- combos --")
    combos = [
        ("LOCKED + lock_streak>=2", lambda r: r["locked"] and r["lock_streak"] >= 2),
        ("LOCKED + first lock", lambda r: r["locked"] and r["lock_streak"] == 1),
        ("LOCKED + green tape", lambda r: r["locked"] and r["tape"] > 0.3),
        ("LOCKED + red tape", lambda r: r["locked"] and r["tape"] < -0.3),
        ("LOCKED + body>=3", lambda r: r["locked"] and r["body"] >= 3),
        ("LOCKED + body<3", lambda r: r["locked"] and r["body"] < 3),
        ("LOCKED + gap<2", lambda r: r["locked"] and r["open_gap"] < 2),
        ("LOCKED + gap>=2", lambda r: r["locked"] and r["open_gap"] >= 2),
        ("LOCKED + vol>=500M", lambda r: r["locked"] and r["value"] >= 500e6),
        ("LOCKED + streak<=2", lambda r: r["locked"] and r["streak"] <= 2),
        ("LOCKED + streak>=3", lambda r: r["locked"] and r["streak"] >= 3),
    ]
    for label, pred in combos:
        sub = [r for r in rows if pred(r)]
        if not sub:
            continue
        w = sum(1 for r in sub if r["outcome"] == "WIN")
        s = sum(1 for r in sub if r["outcome"] == "STOP")
        avg = sum(r["pnl"] for r in sub) / len(sub)
        print(f"  {label:<26} n={len(sub):>3}  WIN {100*w/len(sub):5.1f}%  STOP {100*s/len(sub):5.1f}%  avg {avg:+.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
