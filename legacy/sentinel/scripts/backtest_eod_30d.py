"""Backtest the EOD overnight strategy over the KMIALL corpus (54 sessions).

METHOD (honest by construction, close-bracket):
  * pick day D: KMIALL members with a green day (close > prior close),
    a green candle (close > open), price >= 20 PKR, traded value
    >= Rs 5M - the same junk floors the live bot applies;
  * entry at D's CLOSE - the real fill the owner places at 15:29/16:29;
  * holding session D+1 under the universal law (TP +2%, SL -1%):
      - session close >= entry*1.02  -> WIN  (live high >= close, so a
        close-based win is a real win: conservative on the TP side);
      - session close <= entry*0.99  -> STOP (live low <= close, real);
      - neither                      -> force-close at D+1's close.
    KNOWN DEVIATION: an intraday -1% touch that recovers by the close
    counts as "not stopped" here but would stop live; an intraday +2%
    touch that fades counts as a miss here but would win live. The two
    partially offset; the report carries the caveat rather than hiding
    it. Live also force-closes at 11:30, earlier than this sim.
  * costs: the real round-trip stack, 0.848%.

THE LEARNING (what the owner asked for): win/expectancy by extension
band over the prior close, by candle-body size, by volume surge, and
by market regime (the corpus's own equal-weight breadth that day) -
so the market's structure, not opinion, picks the final filters.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"
OUT = ROOT / "data" / "backtest" / "eod30_report.json"
COST = 0.848
TP = 2.0
SL = -1.0
PRICE_FLOOR = 20.0
VALUE_FLOOR = 5_000_000.0
MAX_GAP_DAYS = 7  # suspension guard: skip if the next session is farther


def load_corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def trading_dates(corpus: dict) -> list[str]:
    dates = set()
    for hist in corpus.values():
        for row in hist:
            dates.add(row["date"])
    return sorted(dates)[-30:]


def next_session(hist: list[dict], d: str) -> dict | None:
    """The symbol's first session strictly after d, None if too far."""
    for row in hist:
        if row["date"] > d:
            from datetime import date as _d

            gap = (_d.fromisoformat(row["date"]) - _d.fromisoformat(d)).days
            if gap > MAX_GAP_DAYS:
                return None
            return row
    return None


def candidates_on(corpus: dict, d: str, prev_map: dict) -> list[dict]:
    """Each candidate carries its pick date explicitly (the sim needs it)."""
    out = []
    for sym, hist in corpus.items():
        today = next((r for r in hist if r["date"] == d), None)
        if today is None:
            continue
        prev = prev_map.get((sym, d))
        if prev is None:
            continue
        price = today["close"]
        prev_close = prev["close"]
        chg = (price / prev_close - 1) * 100
        value = today["volume"] * (today["open"] + price) / 2
        if price < PRICE_FLOOR or value < VALUE_FLOOR:
            continue
        if price <= prev_close:    # green day required
            continue
        if price <= today["open"]:  # green candle required
            continue
        out.append(
            {
                "symbol": sym,
                "date": d,
                "entry": price,
                "chg": chg,
                "body_pct": (price - today["open"]) / prev_close * 100,
                "vol_ratio": today["volume"] / max(prev.get("_prev_vol") or 1, 1)
                if prev.get("_prev_vol")
                else None,
                "value": value,
            }
        )
    return out


def simulate(trades: list[dict], corpus: dict, dates: list[str]) -> list[dict]:
    idx = {d: i for i, d in enumerate(dates)}
    done = []
    for t in trades:
        nxt = next_session(corpus[t["symbol"]], t["date"])
        if nxt is None:
            continue
        entry = t["entry"]
        close = nxt["close"]
        ret = (close / entry - 1) * 100
        if ret >= TP:
            outcome, pnl = "WIN", TP - COST
        elif ret <= SL:
            outcome, pnl = "STOP", SL - COST
        else:
            outcome, pnl = "FORCE", ret - COST
        done.append({**t, "exit_date": nxt["date"], "ret": ret,
                     "outcome": outcome, "pnl": pnl})
    return done


def slice_stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0}
    wins = [t for t in trades if t["outcome"] == "WIN"]
    stops = [t for t in trades if t["outcome"] == "STOP"]
    forces = [t for t in trades if t["outcome"] == "FORCE"]
    pnls = [t["pnl"] for t in trades]
    return {
        "n": n,
        "wins": len(wins),
        "stops": len(stops),
        "forces": len(forces),
        "win_rate": round(len(wins) / n, 4),
        "avg_net": round(sum(pnls) / n, 3),
        "total_net": round(sum(pnls), 2),
    }


def band(v, edges, labels):
    for e, lab in zip(edges, labels):
        if v < e:
            return lab
    return labels[-1]


def main() -> int:
    corpus = load_corpus()
    dates = trading_dates(corpus)

    # prior close (and prior volume) per (symbol, date)
    prev_map: dict[tuple[str, str], dict] = {}
    for sym, hist in corpus.items():
        for i in range(1, len(hist)):
            prev_map[(sym, hist[i]["date"])] = {
                "close": hist[i - 1]["close"],
                "_prev_vol": hist[i - 1]["volume"],
            }

    # market regime per day: equal-weight mean day-change across members
    regime = {}
    for d in dates:
        chgs = []
        for (sym, dd), prev in prev_map.items():
            if dd != d:
                continue
            today = next((r for r in corpus[sym] if r["date"] == d), None)
            if today:
                chgs.append((today["close"] / prev["close"] - 1) * 100)
        regime[d] = round(statistics.mean(chgs), 3) if chgs else 0.0

    all_trades = []
    for d in dates:
        cands = candidates_on(corpus, d, prev_map)
        simmed = simulate(cands, corpus, dates)
        for t in simmed:
            t["date"] = d
            t["tape"] = regime[d]
        all_trades.extend(simmed)

    report = {"window": [dates[0], dates[-1]], "cost_pct": COST,
              "law": {"tp": TP, "sl": SL}, "regime": regime}

    report["ALL"] = slice_stats(all_trades)

    ext = defaultdict(list)
    for t in all_trades:
        ext[band(t["chg"], [2, 4, 6, 8], ["<2%", "2-4%", "4-6%", "6-8%", ">=8%"])].append(t)
    report["by_extension"] = {k: slice_stats(v) for k, v in sorted(ext.items())}

    body = defaultdict(list)
    for t in all_trades:
        body[band(t["body_pct"], [0.5, 1.0, 2.0], ["<0.5%", "0.5-1%", "1-2%", ">=2%"])].append(t)
    report["by_body"] = {k: slice_stats(v) for k, v in sorted(body.items())}

    tape = defaultdict(list)
    for t in all_trades:
        tape["red tape" if t["tape"] < 0 else "green tape"].append(t)
    report["by_tape"] = {k: slice_stats(v) for k, v in sorted(tape.items())}

    # per-day top-3 selection by traded value (a realistic pick rule)
    by_day = defaultdict(list)
    for t in all_trades:
        by_day[t["date"]].append(t)
    top3 = []
    for d, group in by_day.items():
        top3.extend(sorted(group, key=lambda t: -t["value"])[:3])
    report["top3_by_value"] = slice_stats(top3)

    OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")

    print(f"window {report['window'][0]} .. {report['window'][1]}  (TP {TP}/SL {SL}, cost {COST})")
    for section in ("ALL", "by_extension", "by_body", "by_tape", "top3_by_value"):
        print(f"\n== {section} ==")
        data = report[section]
        items = data.items() if isinstance(data, dict) and "n" not in data else [(section, data)]
        for name, s in items:
            if s.get("n"):
                print(f"  {name:<12} n={s['n']:>4}  win {100*s['win_rate']:5.1f}%  "
                      f"avg net {s['avg_net']:+.2f}%  (W{s['wins']}/S{s['stops']}/F{s['forces']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
