#!/usr/bin/env python3
"""Replay a taped session through the REAL scanner, slot by slot.

This is the replay harness the owner asked for (2026-10-15, "UNITY's 13
October ground truth, the 20-session red/green recall audit, and the
cycle-by-cycle replay"). It runs the same code a live scan runs
(scanner.load_session -> assess_quality -> select_one via
scripts.intraday_pipeline.run_scan) against a historical tape with each slot
bound to its replayed as_of, so a past day's verdicts, coverage and ranked
candidates are replayed rather than remembered.

For a --focus symbol the report also carries that symbol's own ledger from
the tape: the counted buy/sell flow (src/data/tick_volume), and the
session's own direction from the tape's bars (last close vs first open).

Ground-truth honesty (SO-3): four real session tapes exist (Oct 6, 12, 13,
14). A 20-session red/green recall review cannot be fabricated from nothing;
this script is run per accumulating session until twenty are on disk, and
each run appends to data/forward/replay_YYYYMMDD.json.

Owner-approval law (SO-4): a replay is a backtest and stays on the PC, run
when the owner asks, never on a schedule (src/ci/local_only.py).

Usage:
    python scripts/replay_audit.py --day 2026-10-13 --focus UNITY
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: The official per-slot cadence (intraday_pipeline's own choices list).
SLOTS = ("10:00", "11:30", "13:00", "14:30", "16:00")


def replay_day(day: date, focus: str | None = None) -> dict:
    from scripts import intraday_pipeline as pipeline
    from scripts.intraday_pipeline import load_kmiall, resolve_capture
    from src.data.sessions import session_window_text

    tape = resolve_capture(day)
    if not tape.is_file():
        raise SystemExit(f"no capture for {day.isoformat()}: {tape}")
    symbols = load_kmiall()

    report: dict = {"day": day.isoformat(), "window": session_window_text(day),
                    "tape": str(tape), "universe": len(symbols),
                    "slots": [], "focus": None}

    for slot in SLOTS:
        if not pipeline.session_legal(pipeline.scheduled_as_of(slot, day)):
            report["slots"].append({"slot": slot, "verdict": "SKIPPED",
                                    "reason": "not a scan window"})
            continue
        payload = pipeline.run_scan(slot, capture=tape, day=day)
        candidate = payload.get("candidate") or {}
        ranked = payload.get("ranked_top") or []
        row = {"slot": slot,
               "reason": (payload.get("reason") or "")[:140],
               "verdict": payload.get("status"),
               "candidate": {"symbol": candidate.get("symbol"),
                             "score": candidate.get("score")},
               "coverage": (payload.get("data_quality") or {}).get("coverage")}
        if focus:
            hit = next((r for r in ranked
                        if r.get("symbol") == focus.upper()), None)
            row[f"{focus.lower()}_top_score"] = hit and hit.get("score")
            row[f"{focus.lower()}_in_top"] = hit is not None
        report["slots"].append(row)

    if focus:
        report["focus"] = focus_ledger(tape, focus, day)
    return report


def focus_ledger(tape: Path, symbol: str, day: date) -> dict:
    """One symbol's own day, straight from the tape's own prints and bars."""
    from src.data import tape_bars, tick_volume

    flow = tick_volume.session_flow(tape, [symbol]).get(symbol)
    if flow is None:
        return {"symbol": symbol,
                "ground_truth": "this symbol produced no tape windows today"}

    from scripts.intraday_pipeline import scheduled_as_of
    as_of = scheduled_as_of("16:00", day)
    bars = tape_bars.build(tape, [symbol], as_of)
    rows = bars.bars.get(symbol) or []
    open_px = rows[0].open if rows else None
    last_px = rows[-1].close if rows else None
    direction = ("GREEN" if (open_px is not None and last_px > open_px)
                 else "RED" if (open_px is not None and last_px < open_px)
                 else "FLAT" if open_px is not None else None)
    basis = None if direction is None else (
        "the tape's own bars: last bar close vs first bar open")
    return {
        "symbol": symbol,
        "windows": flow.windows,
        "tape_buy_volume": flow.buy_volume,
        "tape_sell_volume": flow.sell_volume,
        "tape_observed_total": flow.observed_total,
        "pre_tape_volume": flow.pre_tape_volume,
        "coveraged_bars": len(rows),
        "open_from_bars": open_px,
        "last_close_from_bars": last_px,
        "ground_truth_direction": direction,
        "ground_truth_basis": basis,
        "first_tick": flow.first_tick,
        "last_tick": flow.last_tick,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="replay a taped day slot by slot")
    parser.add_argument("--day", required=True)
    parser.add_argument("--focus", default=None)
    args = parser.parse_args(argv)
    report = replay_day(date.fromisoformat(args.day), args.focus)
    print(json.dumps(report, indent=2, default=str))
    out = ROOT / "data" / "forward" / f"replay_{args.day.replace('-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
