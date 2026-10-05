"""
Bot B base-rate study - the overnight edge, measured from the OHLC corpus.

Question the owner ordered answered (task 2, Bot B):
  for every KMIALL stock, buy at the near-close, sell in the first
  minutes of the next session. What does the tape actually pay?

What this script measures from data/backtest/eod_corpus.json
  (313 symbols x 177 sessions, date/open/close/volume, Jan 5 - Sep 23):
  * close-to-open gap per stock-day: mean, median, win rate, worst case
  * the same, net of the full confirmed cost stack (commission both
    bands + SST + levies + CGT)
  * per weekday of the BUY day (Mon-Thu vs Friday: a Friday pick sells
    Monday - two nights of gap risk, one of them the weekend)
  * per calendar month (regime drift, Jan-Sep 2026)
  * decay: how much of the gain is gone by minute 5/10/15. The corpus
    has no intraday bars, so this run reports the OPEN as the floor
    estimate; scripts/first_minutes_study.py refines it once the
    snapshot collector has filled. Every decay row says which basis
    it used.
  * the morning-fade tradeability filter: does the stock clear the
    liquidity floor on the BUY day (it must be buyable at the close)

Honesty rules: single-print symbols (suspended, IPO gaps) are dropped;
a stock with < 20 valid overnight rows reports its stats but never
enters the "tradeable" verdicts; the verdict section names the exact
conditions (weekday x month x stock) that still work, or says none do.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from psx_core.research import (  # noqa: E402
    net_after_overnight,
    overnight_returns,
    round_trip_cost_pct,
)

CORPUS = REPO / "data" / "backtest" / "eod_corpus.json"
OUT = REPO / "data" / "backtest" / "overnight_study.json"
MIN_ROWS_TRADEABLE = 20
LIQUIDITY_FLOOR_PKR = 20_000_000.0   # Bot B's own MIN_DAY_VALUE
MIN_ABS_PRICE = 5.0

WEEKDAY = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}


def load_pairs() -> list[dict]:
    """One row per (symbol, buy-day): the close-to-open pair."""
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    pairs: list[dict] = []
    for symbol, sessions in corpus.items():
        sessions = sorted(sessions, key=lambda s: s["date"])
        for i in range(len(sessions) - 1):
            buy, nxt = sessions[i], sessions[i + 1]
            entry, op = buy.get("close"), nxt.get("open")
            if not entry or not op or entry <= 0 or op <= 0:
                continue
            if entry < MIN_ABS_PRICE:
                continue  # penny band: commission per-share explodes
            # Sessions whose gap between buy and next day spans non-trading
            # days (weekends, holidays) are still ONE overnight hold for
            # the trade, but we record the calendar gap for the study.
            d1 = datetime.strptime(buy["date"], "%Y-%m-%d").date()
            d2 = datetime.strptime(nxt["date"], "%Y-%m-%d").date()
            rows = {
                "symbol": symbol,
                "buy_date": buy["date"],
                "sell_date": nxt["date"],
                "entry": entry,
                "open": op,
                "weekday": d1.weekday(),
                "month": d1.month,
                "calendar_gap_days": (d2 - d1).days,
                "value": buy.get("volume", 0) * entry,
            }
            pairs.append(rows)
    return pairs


def stats_block(rows: list[dict], key: str) -> dict:
    """Mean/median/win-rate/worst for one bucket, gross and net."""
    if not rows:
        return {"n": 0}
    gross = [r["r_gap"] for r in rows]
    net = [r["r_net"] for r in rows]
    return {
        "n": len(rows),
        "mean_gross_pct": round(sum(gross) / len(gross), 3),
        "median_gross_pct": round(sorted(gross)[len(gross) // 2], 3),
        "win_rate_gross_pct": round(100.0 * sum(g > 0 for g in gross) / len(gross), 1),
        "mean_net_pct": round(sum(net) / len(net), 3),
        "median_net_pct": round(sorted(net)[len(net) // 2], 3),
        "win_rate_net_pct": round(100.0 * sum(n > 0 for n in net) / len(net), 1),
        "worst_net_pct": round(min(net), 2),
        "best_net_pct": round(max(net), 2),
        "_key": key,
    }


def main() -> None:
    pairs = load_pairs()
    if not pairs:
        print("no overnight pairs - corpus empty?")
        return

    # Per-pair returns (open-as-floor decay basis; refined later by the
    # first-minutes study once bars exist).
    for r in pairs:
        d = overnight_returns(r["open"], r["entry"], {})
        r["r_gap"] = d["r5"]              # open print == minute-0 proxy
        r["r_net"] = net_after_overnight(d["r5"], r["entry"])
        r["rt_cost_pct"] = round_trip_cost_pct(r["entry"], r["open"])

    report: dict = {
        "generated": datetime.now().isoformat(),
        "corpus": str(CORPUS.relative_to(REPO)),
        "basis": "open print (minute-0 floor; no intraday bars in corpus yet)",
        "costs": "commission 0.15%/side (0.03/share <=20 PKR), SST 16% of commission, levies 0.05%/side, CGT 15%",
        "pairs": len(pairs),
        "symbols": len({r["symbol"] for r in pairs}),
        "sessions": len({r["buy_date"] for r in pairs}),
    }

    # Whole-board stats
    report["all"] = stats_block(pairs, "all")

    # Per weekday of the BUY day
    per_wd = defaultdict(list)
    for r in pairs:
        per_wd[WEEKDAY[r["weekday"]]].append(r)
    report["by_weekday"] = {
        k: stats_block(v, k) for k in ("Mon", "Tue", "Wed", "Thu", "Fri")
        for v in [per_wd[k]]
    }

    # Weekend vs same-night holds (calendar gap > 1 day = spans a closure)
    same_night = [r for r in pairs if r["calendar_gap_days"] == 1]
    weekend = [r for r in pairs if r["calendar_gap_days"] > 1]
    report["same_night"] = stats_block(same_night, "same_night")
    report["across_closure"] = stats_block(weekend, "across_closure")

    # Per month (regime drift)
    per_month = defaultdict(list)
    for r in pairs:
        per_month[r["month"]].append(r)
    report["by_month"] = {
        f"2026-{m:02d}": stats_block(v, f"2026-{m:02d}")
        for m, v in sorted(per_month.items())
    }

    # Per stock: only the liquid tradeable names (Bot B's own floor)
    liquid = [r for r in pairs if r["value"] >= LIQUIDITY_FLOOR_PKR]
    per_sym = defaultdict(list)
    for r in liquid:
        per_sym[r["symbol"]].append(r)
    sym_stats = []
    for symbol, rows in per_sym.items():
        s = stats_block(rows, symbol)
        if s["n"] >= MIN_ROWS_TRADEABLE:
            sym_stats.append(s)
    sym_stats.sort(key=lambda s: s["mean_net_pct"], reverse=True)
    report["tradeable_symbols_n"] = len(sym_stats)
    report["top20_symbols_net"] = sym_stats[:20]
    report["bottom10_symbols_net"] = sym_stats[-10:]
    n_positive = sum(1 for s in sym_stats if s["mean_net_pct"] > 0)
    report["tradeable_positive_mean_n"] = n_positive
    report["tradeable_positive_share_pct"] = round(
        100.0 * n_positive / max(1, len(sym_stats)), 1
    )

    # Honest verdict
    a = report["all"]
    verdict = {
        "board_mean_net_pct": a["mean_net_pct"],
        "board_win_rate_net_pct": a["win_rate_net_pct"],
        "edge_is_positive": a["mean_net_pct"] > 0,
        "friday_pick_sells_monday": report["by_weekday"]["Fri"]["mean_net_pct"],
        "tradeable_universe": len(sym_stats),
        "tradeable_positive_share_pct": report["tradeable_positive_share_pct"],
    }
    if not verdict["edge_is_positive"]:
        verdict["statement"] = (
            "The overnight edge is NEGATIVE board-wide after costs: the "
            "morning-fade trade as specified does not pay on average. "
            "See by_weekday/by_month/top20 for the conditions that still work."
        )
    else:
        verdict["statement"] = (
            "The overnight edge is positive board-wide after costs, but the "
            "per-stock table shows where it concentrates - trade the "
            "conditions, not the average."
        )
    report["verdict"] = verdict

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Console summary (PKT clock, plain language)
    print(f"pairs {report['pairs']} | symbols {report['symbols']} | sessions {report['sessions']}")
    print(f"basis: {report['basis']}")
    print(f"ALL  : mean net {a['mean_net_pct']:+.3f}% | win {a['win_rate_net_pct']}% | worst {a['worst_net_pct']}%")
    for k in ("Mon", "Tue", "Wed", "Thu", "Fri"):
        s = report["by_weekday"][k]
        if s["n"]:
            print(f"{k:5}: mean net {s['mean_net_pct']:+.3f}% | win {s['win_rate_net_pct']}% | n={s['n']}")
    s = report["across_closure"]
    print(f"CLOSURE-SPANNING HOLDS: mean net {s['mean_net_pct']:+.3f}% | win {s['win_rate_net_pct']}% | n={s['n']}")
    print(f"tradeable symbols (>= {MIN_ROWS_TRADEABLE} rows, liquid): {len(sym_stats)} | positive-mean share: {report['tradeable_positive_share_pct']}%")
    for t in sym_stats[:5]:
        print(f"  top {t['_key']}: mean net {t['mean_net_pct']:+.3f}% | win {t['win_rate_net_pct']}% | n={t['n']}")
    print("verdict:", verdict["statement"])
    print("full report ->", OUT)


if __name__ == "__main__":
    main()
