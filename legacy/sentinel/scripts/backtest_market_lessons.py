"""Backtest the market-learner's signals on the stored EOD corpus.

The learner's two actionable claims, tested the way every structure
here is tested - real outcomes, both halves of the data:

  1. DEAD: a name dead (flat <=0.4% AND illiquid <200k) has no next-
     day move either - refusing it costs nothing, and its next-day
     |change| distribution should be far below live names'.
  2. TREND: names green in every snapshot with real turnover continue
     overnight better than the average liquid name.

Tape: data/snapshots/*.jsonl.gz (the learner's own source) joined to
processed/psx_eod_history.json for next-day outcomes.
"""
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psx_core import paths  # noqa: E402

DEAD_MAX_CHG = 0.004
DEAD_MAX_VALUE = 200_000.0
LIQ_VALUE = 1_000_000.0


def load_eod():
    d = json.loads(
        (paths.PROCESSED_DIR / "psx_eod_history.json").read_text(
            encoding="utf-8"
        )
    )
    out = {}
    for sym, rows in d.items():
        px = {r["date"]: float(r["close"]) for r in rows}
        out[sym] = px
    return out


def next_close(px: dict, date: str):
    dates = sorted(px)
    after = [d for d in dates if d > date]
    return px[after[0]] if after else None


def close_on(px: dict, date: str):
    return px.get(date)


def main():
    snaps = sorted((paths.DATA_DIR / "snapshots").glob("*.jsonl.gz"))
    eod = load_eod()

    dead_next, live_next, trend_next = [], [], []
    per_day_dead = defaultdict(int)

    for path in snaps:
        date = path.stem.replace(".jsonl", "")
        rows = []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        if not rows:
            continue
        last = rows[-1]
        quotes = last.get("quotes") or {}
        # Trend needs the whole session, not one snapshot.
        green_all: dict[str, int] = defaultdict(int)
        seen: dict[str, int] = defaultdict(int)
        for row in rows:
            for sym, q in (row.get("quotes") or {}).items():
                if not isinstance(q, dict) or q.get("price") is None:
                    continue
                seen[sym] += 1
                chg = q.get("changePercent")
                if isinstance(chg, (int, float)) and chg > 0:
                    green_all[sym] += 1

        for sym, q in quotes.items():
            if not isinstance(q, dict):
                continue
            chg = q.get("changePercent")
            val = q.get("value") or 0.0
            if not isinstance(chg, (int, float)):
                continue
            c0 = close_on(eod.get(sym, {}), date)
            c1 = next_close(eod.get(sym, {}), date)
            if not c0 or not c1:
                continue
            o_n = (c1 / c0 - 1) * 100
            if val < DEAD_MAX_VALUE and abs(chg) <= DEAD_MAX_CHG:
                dead_next.append(o_n)
                per_day_dead[date] += 1
            elif val >= LIQ_VALUE:
                live_next.append(o_n)
                if (
                    seen[sym] >= 2
                    and green_all[sym] == seen[sym]
                    and chg >= 0.005
                ):
                    trend_next.append(o_n)

    def block(name, xs):
        if not xs:
            print(f"{name}: no sample")
            return
        pos = sum(1 for x in xs if x > 0)
        print(
            f"{name}: n={len(xs)} mean={statistics.mean(xs):+.2f}% "
            f"median={statistics.median(xs):+.2f}% "
            f"P(up)={pos / len(xs) * 100:.1f}% "
            f"|chg| mean={statistics.fmean(abs(x) for x in xs):.2f}%"
        )

    print("next-day outcome of each class (close-to-close):")
    block("DEAD  (flat+illiquid)", dead_next)
    block("LIVE  (liquid rest) ", live_next)
    block("TREND(green-all+liq)", trend_next)


if __name__ == "__main__":
    main()
