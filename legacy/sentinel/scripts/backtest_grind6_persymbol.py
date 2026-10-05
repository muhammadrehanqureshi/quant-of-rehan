"""Grind round 6: per-symbol forensics on the ENTIRE KMIALL universe.

The owner's order: backtest each of the KMIALL stocks, not one name.
Every prior grind already ran all 305 symbols pooled; this pass cuts
BY SYMBOL and asks two questions the pooled view cannot answer:

  Q1. Which stocks are chronic lock-continuers vs chronic fakes?
      (per-stock lock-law table: n, wins, net, on the full 175
      sessions, close-bracket resolution, real cost stack)

  Q2. Is symbol-level performance PERSISTENT - does a stock that
      continued yesterday's locks keep continuing? If yes, a
      per-symbol memory filter raises accuracy; if no, it's noise.

  Q3 (only if Q2 says yes): walk-forward per-symbol filter - each
      lock trade judged by the symbol's TRAILING lock record (prior
      trades only, min sample), tested discovery vs validation.

No pooled averages hide behind: every number names its stock.
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"
OUT = ROOT / "data" / "backtest" / "per_symbol_lock_report.json"

COST = 0.848
TP, SL = 2.0, -1.0
LOCK_CHG = 9.9


def load():
    raw = json.loads(CORPUS.read_text())
    out = {}
    for sym, rows in raw.items():
        rows.sort(key=lambda r: r["date"])
        if len(rows) >= 30:
            out[sym] = rows
    return out


def lock_trades(rows):
    """All lock-law trades for one symbol: [(date, outcome, net)]."""
    trades = []
    for i in range(1, len(rows) - 1):
        r, pc = rows[i], rows[i - 1]
        if not r.get("close") or not pc.get("close"):
            continue
        chg = (r["close"] / pc["close"] - 1) * 100
        if chg < LOCK_CHG:
            continue
        nc = rows[i + 1].get("close")
        if not nc:
            continue
        entry = r["close"]
        if nc >= entry * (1 + TP / 100):
            trades.append((r["date"], "TP", TP - COST))
        elif nc <= entry * (1 + SL / 100):
            trades.append((r["date"], "SL", SL - COST))
        else:
            trades.append((r["date"], "time", (nc / entry - 1) * 100 - COST))
    return trades


def main() -> int:
    daily = load()
    all_dates = sorted({r["date"] for rows in daily.values() for r in rows})
    split_date = all_dates[int(len(all_dates) * 2 / 3)]

    per_sym = {}
    for sym, rows in daily.items():
        t = lock_trades(rows)
        if t:
            wins = sum(1 for _, o, _ in t if o == "TP")
            net = sum(n for _, _, n in t)
            per_sym[sym] = {
                "n": len(t),
                "wins": wins,
                "win_pct": wins / len(t) * 100,
                "net": net,
                "dates": [d for d, _, _ in t],
            }

    # ---- Q1: the per-stock table ----
    ranked = sorted(
        per_sym.items(), key=lambda kv: (kv[1]["win_pct"], kv[1]["net"]),
        reverse=True,
    )
    print("=" * 78)
    print(f"GRIND 6 - per-symbol lock law, {len(per_sym)} KMIALL stocks with locks")
    print("=" * 78)
    print("\nTOP 15 (best per-stock lock records, n>=3):")
    for sym, s in ranked:
        if s["n"] < 3:
            continue
        print(
            f"  {sym:8s} n={s['n']:3d} | win {s['win_pct']:5.1f}% | net {s['net']:+6.2f}%"
        )
        if sum(1 for _, x in ranked[: ranked.index((sym, s)) + 1 if (sym, s) in ranked else 0] if x["n"] >= 3) >= 14:
            break
    shown = 0
    print("\nBOTTOM 15 (chronic fakes, n>=3):")
    for sym, s in reversed(ranked):
        if s["n"] < 3:
            continue
        print(
            f"  {sym:8s} n={s['n']:3d} | win {s['win_pct']:5.1f}% | net {s['net']:+6.2f}%"
        )
        shown += 1
        if shown >= 15:
            break

    wrs = [s["win_pct"] for s in per_sym.values() if s["n"] >= 3]
    if wrs:
        print(
            f"\nper-stock win-rate distribution (n>=3): median "
            f"{statistics.median(wrs):.1f}%, spread {min(wrs):.0f}-{max(wrs):.0f}%"
        )

    # ---- Q2: persistence - discovery WR vs validation WR per stock ----
    pairs = []
    for sym, s in per_sym.items():
        d = [1 if o == "TP" else 0 for dt, o, _ in lock_trades(daily[sym]) if dt < split_date]
        v = [1 if o == "TP" else 0 for dt, o, _ in lock_trades(daily[sym]) if dt >= split_date]
        if len(d) >= 3 and len(v) >= 2:
            pairs.append((sym, sum(d) / len(d) * 100, sum(v) / len(v) * 100, len(v)))
    if len(pairs) >= 10:
        disc = [p[1] for p in pairs]
        val = [p[2] for p in pairs]
        mean_d, mean_v = statistics.mean(disc), statistics.mean(val)
        cov = sum((a - mean_d) * (b - mean_v) for _, a, b, _ in pairs)
        sd = statistics.stdev(disc) * statistics.stdev(val) * (len(pairs) - 1)
        corr = cov / sd if sd else 0.0
        # top decile by discovery WR: do they beat the universe in validation?
        pairs.sort(key=lambda p: p[1], reverse=True)
        top = pairs[: max(3, len(pairs) // 5)]
        top_val = [p[2] for p in top]
        rest_val = [p[2] for p in pairs[len(top):]]
        print(f"\nQ2 persistence: {len(pairs)} stocks with >=3 disc & >=2 val trades")
        print(f"  corr(disc WR, val WR) = {corr:+.2f}")
        print(
            f"  top-quintile disc WR -> validation WR "
            f"{statistics.mean(top_val):.1f}% vs rest {statistics.mean(rest_val):.1f}%"
        )
        print(
            f"  (universe val mean {mean_v:.1f}% - a real edge shows as top >> rest)"
        )

    # ---- Q3: walk-forward per-symbol memory filter ----
    print("\nQ3 walk-forward per-symbol memory (trailing record, min 3 prior):")
    with_mem, without_mem = [], []
    for sym, rows in daily.items():
        hist = []  # outcomes so far
        for i in range(1, len(rows) - 1):
            r, pc = rows[i], rows[i - 1]
            if not r.get("close") or not pc.get("close"):
                continue
            chg = (r["close"] / pc["close"] - 1) * 100
            is_lock = chg >= LOCK_CHG
            if is_lock and len(hist) >= 3:
                wr = sum(hist) / len(hist) * 100
                nc = rows[i + 1].get("close")
                if nc:
                    entry = r["close"]
                    if nc >= entry * (1 + TP / 100):
                        o, net = "TP", TP - COST
                    elif nc <= entry * (1 + SL / 100):
                        o, net = "SL", SL - COST
                    else:
                        o, net = "time", (nc / entry - 1) * 100 - COST
                    rec = (o, net, r["date"], wr)
                    if wr >= 50:
                        with_mem.append(rec)
                    else:
                        without_mem.append(rec)
            if is_lock:
                nc = rows[i + 1].get("close")
                if nc:
                    entry = r["close"]
                    hist.append(1 if nc >= entry * (1 + TP / 100) else 0)

    def show(name, ts):
        if not ts:
            print(f"  {name:28s} (no trades)")
            return
        wins = sum(1 for o, _, _, _ in ts if o == "TP")
        net = sum(n for _, n, _, _ in ts)
        disc = [t for t in ts if t[2] < split_date]
        val = [t for t in ts if t[2] >= split_date]

        def wr(x):
            return sum(1 for t in x if t[0] == "TP") / len(x) * 100 if x else 0

        print(
            f"  {name:28s} {len(ts):4d} | win {wins/len(ts)*100:5.1f}% "
            f"(D {wr(disc):5.1f}% / V {wr(val):5.1f}%) | net {net:+7.1f}% "
            f"({net/len(ts):+.2f}/trade)"
        )

    show("trailing WR >= 50%", with_mem)
    show("trailing WR < 50%", without_mem)

    # persist the per-stock table
    OUT.write_text(json.dumps(per_sym, indent=1, sort_keys=True))
    print(f"\nper-stock table written: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
