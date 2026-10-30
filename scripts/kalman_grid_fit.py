"""CLOUD-ONLY Kalman Trend parameter grid fit (owner order 2026-10-30).

The owner chose the parameters by answer 2: grid-fit in GitHub Actions,
never on his PC (the machine law). Input: archived capture files (tape or
poller ndjson), one session more per file. For every parameter triple
(q, r, hysteresis threshold) the script replays the ONE strategy the
system trades - the Kalman Trend's flip entry with the owner's TP/SL law
alone (src/signals/kalman_trend.py) - over every symbol of every session,
with:

  * strictly causal replays: each flip is seen only after its bar closes;
  * the owner's fixed law for every name: +2% target, -1% stop under the
    entry, one call a day (src/config.py is the single source);
  * cost-inclusive accounting (src.config.net_return, CGT applied on
    positive results), the same one the paper engine uses;
  * a fixed chronological 80/20 split: the newest sessions are the
    holdout and NEVER inform the choice. The best triple by TRAIN
    expectancy is the winner; its HOLDOUT row is the honest answer.

Output: --out JSON report (per-triple train and holdout rows, the chosen
triple and its holdout, session provenance). Synthetic fixtures never
count as strategy results (SO-3): with no capture files the script exits 1
instead of inventing a number.

Run only in GitHub Actions (guard below refuses any other host):
    python scripts/kalman_grid_fit.py --input 'data/feed_capture/rec_*.ndjson' \
        --out data/research/kalman_grid.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

from src.data import tape_bars  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals.kalman_trend import filter_series  # noqa: E402

TRAIN_SHARE = 0.8          # chronological split rule of this sweep
#: The sweep box. Small, on purpose: an Actions job, not a supercomputer.
Q_GRID = (1e-8, 1e-7, 1e-6)
R_GRID = (1e-6, 4e-6, 1e-5)
TH_GRID = (0.0, 1e-5, 5e-5)


def replay_symbol(scenario: dict, q: float, r: float, threshold: float) -> list:
    """Every flip trade this symbol made under one parameter triple.

    One trade per upward flip: entry at the flip bar's completed close,
    stop at the owner's fixed -1% under the entry, exit at the target,
    the stop, or the next downward flip close, whichever first. Returns
    net-return rows with their exit reason.
    """
    from src import config

    closes, lows, highs = scenario["closes"], scenario["lows"], scenario["highs"]
    rows: list = []
    flips: list[int] = []
    trace = filter_series(closes, q, r, threshold)
    for index, rec in enumerate(trace):
        if not rec["flip_up"]:
            flips.append(-1)
            continue
        entry = closes[index]
        stop = entry * (1 - config.KALMAN_STOP_PCT)
        target = entry * (1 + config.TARGET_PCT)
        gross = None
        reason = None
        later = index + 1
        while later < len(closes):
            state = trace[later]["state"]
            if highs[later] >= target:
                gross, reason = (target / entry) - 1.0, "target"
                break
            if lows[later] <= stop:
                gross, reason = (stop / entry) - 1.0, "stop"
                break
            if state != 1:
                gross, reason = (closes[later] / entry) - 1.0, "flip_down"
                break
            later += 1
        if gross is None:  # the series ran out before any exit: session close
            gross, reason = (closes[-1] / entry) - 1.0, "session_end"
        rows.append({"gross": gross, "reason": reason,
                     "flip_at": index, "entry": entry})
        flips.append(index)
    # One trade per flip, honest aggregation function applied by caller.
    return rows


def summarize(rows: list) -> dict:
    from src import config

    nets = [config.net_return(row["gross"]) for row in rows]
    nets = [net for net in nets if net is not None]
    if not nets:
        return {"trades": 0}
    return {
        "trades": len(nets),
        "expectancy": round(statistics.mean(nets), 6),
        "median": round(statistics.median(nets), 6),
        "hit_rate": round(sum(1 for net in nets if net > 0) / len(nets), 4),
        "worst": round(min(nets), 6),
    }


def _day_from_path(path: Path):
    """The capture file's own session day (capture_YYYYMMDD.ndjson)."""
    stem = path.stem
    for token in stem.split("_"):
        if token.isdigit() and len(token) == 8:
            return datetime.strptime(token, "%Y%m%d").date()
    return None


def main(argv=None) -> int:
    guard_cloud_backtest("scripts/kalman_grid_fit.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=Path, required=True,
                        help="Capture files, glob ('data/feed_capture/capture_*.ndjson')")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    parent = args.input.parent
    paths = [Path(p) for p in sorted(parent.glob(args.input.name))
             if Path(p).is_file()]
    if not paths:
        print("No capture files found for "
              f"{args.input}. No data, no grid (SO-3): build captures first.")
        return 1

    from scripts.intraday_pipeline import load_kmiall
    universe = set(load_kmiall())
    started = time.perf_counter()
    sessions: dict = {}
    for path in paths:
        day = _day_from_path(path)
        if day is None:
            print(f"{path.name}: no capture_YYYYMMDD day in the name, skipped")
            continue
        end = datetime.combine(day, datetime.max.time(), tzinfo=KARACHI)
        tape = tape_bars.build(path, universe, end, day=day)
        if not tape.bars:
            print(f"{path.name}: no tape bars built, kept out of the grid")
            continue
        session = sessions.setdefault(day, {})
        for symbol, rows in tape.bars.items():
            session[symbol] = {
                "closes": [bar.close for bar in rows],
                "lows": [bar.low for bar in rows],
                "highs": [bar.high for bar in rows],
            }
    if not sessions:
        print("No session rows in the captures; nothing to fit (SO-3).")
        return 1

    ordered = sorted(sessions)
    cut = max(1, int(len(ordered) * TRAIN_SHARE))
    train_days, holdout_days = ordered[:cut], ordered[cut:]
    if not holdout_days:
        print("Need more than one session for a chronological split.")
        return 1

    grid_results, chosen = [], None
    for q in Q_GRID:
        for r in R_GRID:
            for threshold in TH_GRID:
                train_rows: list = []
                for day in train_days:
                    for scenario in sessions[day].values():
                        if len(scenario["closes"]) >= 20:
                            train_rows += replay_symbol(scenario, q, r, threshold)
                train = summarize(train_rows)
                if train.get("trades", 0) < 30:
                    continue  # too thin to trust, read SO-3
                hold_rows = []
                for day in holdout_days:
                    for scenario in sessions[day].values():
                        if len(scenario["closes"]) >= 20:
                            hold_rows += replay_symbol(scenario, q, r, threshold)
                row = {
                    "q": q, "r": r, "threshold": threshold,
                    "train": train, "train_expectancy": train.get("expectancy"),
                    "holdout": summarize(hold_rows),
                }
                grid_results.append(row)
                if chosen is None or (row["train_expectancy"] or -9e9) > \
                        (chosen["train_expectancy"] or -9e9):
                    chosen = row
    report = {
        "generated": datetime.now(KARACHI).isoformat(),
        "strategy": "kalman_trend_flip_v1 (flip entry, +2% TP / -1% SL)",
        "sessions": ordered,
        "split": {"share": TRAIN_SHARE, "train": train_days, "holdout": holdout_days},
        "grid": list(Q_GRID), "r_grid": list(R_GRID), "threshold_grid": list(TH_GRID),
        "rows": grid_results,
        "chosen": chosen,
        "replay_seconds": round(time.perf_counter() - started, 2),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"chosen": chosen, "rows": len(grid_results),
                      "replay_seconds": report["replay_seconds"]}, indent=2))
    return 0
