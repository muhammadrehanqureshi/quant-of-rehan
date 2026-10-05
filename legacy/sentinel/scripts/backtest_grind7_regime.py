"""Grind 7: condition the lock law on session regime.

Everything so far measured the lock law averaged across ALL sessions.
The market's own state - index up vs down, breadth strong vs weak,
volatility high vs calm - plausibly changes how often a locked close
continues. This script measures the law cell by cell against the
PREVIOUS session's regime features (knowable before the pick is made,
so the conditioning is deployable, not descriptive):

  regime cells (measured on the PRIOR session):
    * KMIALL cross-sectional mean day-change (the tape's color)
    * breadth proxy: share of names closing green
    * dispersion: cross-sectional stdev of day-change (chop vs trend)

  outcome: the standard close-bracket sim (TP +2% / SL -1%, both cost
  tiers) of the NEXT session's lock continuation.

Honesty rules: every cell needs >= 30 trades in BOTH discovery
(first 60%) and validation (last 40%) to be reported as an
adjustment; a cell that fails either half is reported as "no
evidence" and the engine keeps the unconditional rate.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

COST_PCT = 0.848
TP = 2.0
SL = -1.0
LOCK_MIN = 9.9
MIN_TRADES = 30


def load_corpus() -> dict[str, list[dict]]:
    """symbol -> [{date, close, high, low, chg}] across the corpus.

    The committed corpus (data/backtest/eod_corpus.json) carries
    open/close/volume only - chg/high/low are derived here (close to
    close change; high/low are unavailable at this granularity, so
    the bracket outcome uses the OPENING-gap + close convention: a
    lock entry is bought at the lock close, the next session's close
    decides, with the open gap credited first - an opening gap beyond
    the target books as a win at the target, beyond the stop books at
    the stop, otherwise close-to-close decides).
    """
    corpus_path = ROOT / "data" / "backtest" / "eod_corpus.json"
    raw = json.loads(corpus_path.read_text(encoding="utf-8"))
    out: dict[str, list[dict]] = {}
    for sym, rows in raw.items():
        rows = sorted(rows, key=lambda r: r["date"])
        fixed = []
        for i, r in enumerate(rows):
            prev_close = rows[i - 1]["close"] if i else r["open"]
            chg = (r["close"] / prev_close - 1) * 100
            fixed.append({
                "date": r["date"],
                "close": r["close"],
                "open": r["open"],
                "chg": chg,
            })
        out[sym] = fixed
    return out


def main() -> int:
    corpus = load_corpus()
    dates = sorted({d["date"] for rows in corpus.values() for d in rows})
    print(f"symbols: {len(corpus)}  sessions: {len(dates)}  ({dates[0]} .. {dates[-1]})")

    # index per date: mean change, breadth, dispersion
    by_date: dict[str, list[float]] = defaultdict(list)
    for sym, rows in corpus.items():
        for r in rows:
            chg = r.get("chg")
            if chg is not None:
                by_date[r["date"]].append(chg)
    regime = {}
    for d, chgs in by_date.items():
        green = sum(1 for c in chgs if c > 0)
        regime[d] = {
            "mean": statistics.fmean(chgs),
            "breadth": green / len(chgs),
            "disp": statistics.pstdev(chgs),
        }

    # lock events: symbol locked on date D -> outcome from D->D+1 bars
    trades = []
    for sym, rows in corpus.items():
        rows = sorted(rows, key=lambda r: r["date"])
        for i in range(len(rows) - 1):
            d0, d1 = rows[i], rows[i + 1]
            if (d0.get("chg") or 0) < LOCK_MIN:
                continue
            prev_regime = regime.get(rows[i - 1]["date"]) if i >= 1 else None
            entry = d0["close"]
            # daily-bar convention (no intraday extremes at this
            # granularity): opening gap books first, close decides the
            # rest; adverse rule for the in-between band.
            gap = (d1["open"] / entry - 1) * 100
            if gap >= TP:
                win, net = True, TP - COST_PCT
            elif gap <= SL:
                win, net = False, SL - COST_PCT
            else:
                cc = (d1["close"] / entry - 1) * 100
                if cc >= TP:
                    win, net = True, TP - COST_PCT
                elif cc <= SL:
                    win, net = False, SL - COST_PCT
                else:
                    win = cc - COST_PCT > 0
                    net = cc - COST_PCT
            trades.append({
                "date": d1["date"],
                "symbol": sym,
                "win": win,
                "net": net,
                "regime": prev_regime,
            })

    print(f"lock trades: {len(trades)}")
    half = int(len(dates) * 0.6)
    disc_end = dates[half] if half < len(dates) else dates[-1]

    def cell_stats(key_fn, label):
        cells: dict = defaultdict(list)
        for t in trades:
            if t["regime"] is None:
                continue
            cells[key_fn(t["regime"])].append(t)
        print(f"\n== {label} ==")
        for key, ts in sorted(cells.items()):
            if len(ts) < MIN_TRADES:
                continue
            disc = [t for t in ts if t["date"] <= disc_end]
            val = [t for t in ts if t["date"] > disc_end]
            if len(disc) < MIN_TRADES or len(val) < MIN_TRADES:
                print(f"  {key:28s} n={len(ts):5d}  win {sum(t['win'] for t in ts)/len(ts)*100:5.1f}%  "
                      f"(disc n={len(disc)}, val n={len(val)} - <{MIN_TRADES} in a half: no evidence)")
                continue
            dw = sum(t["win"] for t in disc) / len(disc) * 100
            vw = sum(t["win"] for t in val) / len(val) * 100
            net = sum(t["net"] for t in ts)
            print(f"  {key:28s} n={len(ts):5d}  win {dw:5.1f}%/{vw:5.1f}% (D/V)  net {net:+7.1f}%")
        if not cells:
            print("  (no cells)")

    cell_stats(lambda r: f"tape mean {'>0' if r['mean'] > 0 else '<=0'}", "prior-session tape color")
    cell_stats(
        lambda r: f"breadth {'>=50%' if r['breadth'] >= 0.5 else '<50%'}",
        "prior-session breadth",
    )
    cell_stats(
        lambda r: f"disp {'<2%' if r['disp'] < 2.0 else '>=2%'}",
        "prior-session dispersion (chop vs trend)",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
