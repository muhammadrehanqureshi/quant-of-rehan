"""
Bot A feasibility study - can TP +2% / SL -1% (the owner's universal
law) be reached AT ALL by KMIALL stocks on a normal PSX day?

Method (honest, and its limits are stated):
  * The repo holds 7 sessions of 5-minute snapshots (Sep 17-26), which
    is enough for a NOISE check, not a rate: per stock-day, walk the
    real 5-minute closes from each 5-bar entry point with the true
    triple-barrier walk (research.triple_barrier, adverse-selection
    convention) and count tp/sl/timeout outcomes.
  * The OHLC corpus (313 symbols x 177 sessions) has no intraday bars,
    so for DEPTH it answers the coarser question: on how many
    stock-days does the day's own high/low span show that +2% above
    the OPEN was available before -1% (i.e. (high >= open*1.02) while
    (low > open*0.99), or the day's shape made the target reachable
    before the stop)? An OHLC day cannot order the extremes, so this
    is an UPPER BOUND on reachability and it says nothing about
    timing. It bounds what any selector could achieve.

Both views land in one JSON + a printed verdict. No selection skill
is claimed anywhere here - this is the pool, not the bot.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from psx_core.research import TP_PCT, SL_PCT, triple_barrier  # noqa: E402

SNAPSHOTS = REPO / "data" / "snapshots"
CORPUS = REPO / "data" / "backtest" / "eod_corpus.json"
OUT = REPO / "data" / "backtest" / "intraday_feasibility.json"
LIQUIDITY_FLOOR_PKR = 5_000_000.0    # Bot A's own min_day_value


def intraday_view() -> dict:
    """True 5-minute triple-barrier outcomes on the stored sessions."""
    files = sorted(SNAPSHOTS.glob("*.jsonl.gz"))
    if not files:
        return {"n": 0, "note": "no snapshot sessions stored"}
    outcomes = {"tp": 0, "sl": 0, "timeout": 0}
    by_time: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # hour -> [tp, sl, to]
    per_symbol: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    n_entries = 0
    for f in files:
        series: dict[str, list[tuple[str, float]]] = defaultdict(list)
        with gzip.open(f, "rt") as fh:
            for line in fh:
                row = json.loads(line)
                ts = row.get("generatedAt") or row.get("receiveTime")
                if not ts:
                    continue
                hour_key = ts[11:13]
                for sym, q in (row.get("quotes") or {}).items():
                    px = q.get("price")
                    if px and px > 0:
                        series[sym].append((hour_key, float(px)))
        for sym, points in series.items():
            if len(points) < 20:
                continue
            prices = [p for _, p in points]
            value = None  # liquidity filter applied on the corpus view; here all
            # Entry every 5 bars (25 minutes), walk to session end.
            for entry_idx in range(0, len(prices) - 10, 5):
                r = triple_barrier(
                    prices, entry_idx, tp_pct=TP_PCT, sl_pct=SL_PCT,
                    max_bars=len(prices) - entry_idx - 1,
                    check_first="sl",
                )
                outcomes["tp" if r.label == 1 else "sl" if r.label == -1 else "timeout"] += 1
                by_time[points[entry_idx + 1][0]][
                    0 if r.label == 1 else 1 if r.label == -1 else 2
                ] += 1
                per_symbol[sym][0 if r.label == 1 else 1 if r.label == -1 else 2] += 1
                n_entries += 1
    tp, sl, to = outcomes["tp"], outcomes["sl"], outcomes["timeout"]
    total = max(1, tp + sl + to)
    return {
        "sessions": len(files),
        "n_entries": n_entries,
        "tp_share_pct": round(100.0 * tp / total, 1),
        "sl_share_pct": round(100.0 * sl / total, 1),
        "timeout_share_pct": round(100.0 * to / total, 1),
        "by_entry_hour": {
            h: {"tp_pct": round(100.0 * v[0] / max(1, sum(v)), 1),
                "sl_pct": round(100.0 * v[1] / max(1, sum(v)), 1),
                "n": sum(v)}
            for h, v in sorted(by_time.items())
        },
        "top_reachable_symbols": sorted(
            ((s, round(100.0 * v[0] / max(1, sum(v)), 1), sum(v))
             for s, v in per_symbol.items() if sum(v) >= 10),
            key=lambda t: -t[1],
        )[:15],
    }


def ohlc_upper_bound() -> dict:
    """OHLC span view: was +2% over the OPEN inside the day's range at
    all, and did the day stay above the -1% line? Upper bound only."""
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    n = 0
    tp_in_range = 0
    both_clean = 0
    by_wd = defaultdict(lambda: [0, 0])
    for symbol, sessions in corpus.items():
        for s in sessions:
            op, hi, lo = s.get("open"), s.get("high"), s.get("low")
            if not op or op <= 0 or not s.get("close"):
                continue
            hi = hi if hi is not None else max(op, s["close"])
            lo = lo if lo is not None else min(op, s["close"])
            n += 1
            target_hit = hi >= op * (1 + TP_PCT / 100.0)
            stop_avoided = lo > op * (1 - SL_PCT / 100.0)
            if target_hit:
                tp_in_range += 1
                if stop_avoided:
                    both_clean += 1
            wd = datetime.strptime(s["date"], "%Y-%m-%d").date().weekday()
            by_wd[wd][0] += 1 if (target_hit and stop_avoided) else 0
            by_wd[wd][1] += 1
    WD = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    return {
        "stock_days": n,
        "target_in_range_pct": round(100.0 * tp_in_range / max(1, n), 1),
        "target_clean_pct_upper_bound": round(100.0 * both_clean / max(1, n), 1),
        "by_weekday_clean_pct": {
            WD[k]: {"clean_pct": round(100.0 * v[0] / max(1, v[1]), 1), "n": v[1]}
            for k, v in sorted(by_wd.items())
        },
    }


def main() -> None:
    intra = intraday_view()
    ohlc = ohlc_upper_bound()
    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "law": f"TP +{TP_PCT}% / SL -{SL_PCT}% (owner's universal law)",
        "intraday_5min_view": intra,
        "ohlc_span_upper_bound": ohlc,
    }
    verdict: dict[str, object] = {}
    if intra.get("n_entries"):
        verdict["noise_check"] = (
            f"On the {intra['sessions']} stored sessions, walking every "
            f"{intra['n_entries']} entry point: {intra['tp_share_pct']}% hit TP first, "
            f"{intra['sl_share_pct']}% hit SL first, {intra['timeout_share_pct']}% timed out. "
            "7 sessions is a noise check, not a rate."
        )
    verdict["upper_bound"] = (
        f"On {ohlc['stock_days']} stock-days (Jan-Sep), the +2% target sat inside "
        f"the day's range {ohlc['target_in_range_pct']}% of the time; without the "
        f"stop being touched first (upper bound, no ordering info): "
        f"{ohlc['target_clean_pct_upper_bound']}%."
    )
    verdict["statement"] = (
        "The +2% move EXISTS on a minority of stock-days; the selector's job "
        "is to find those days, not to lift the target. Bot A's TP/SL law "
        "stays; the edge must come from WHEN and WHICH, proven walk-forward."
    )
    report["verdict"] = verdict
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("intraday:", {k: v for k, v in intra.items() if k != "by_entry_hour"})
    print("ohlc upper bound:", {k: v for k, v in ohlc.items() if k != "by_weekday_clean_pct"})
    for k, v in ohlc["by_weekday_clean_pct"].items():
        print(f"  {k}: clean {v['clean_pct']}% (n={v['n']})")
    print("verdict:", verdict["statement"])
    print("full report ->", OUT)


if __name__ == "__main__":
    main()
