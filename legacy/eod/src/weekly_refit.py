"""
Weekly refit - the self-learning loop (v2.2.0, the owner's original ask).

WHAT: reads the ledger, separates winners from losers, and measures
which entry features actually carried the outcome. Emits refit.json:
adjusted weights + a human-readable summary of what the tape taught.

HOW IT DECIDES (no opinions, only evidence):
  * a feature moves only when BOTH buckets hold >= MIN_BUCKET_TRADES
    outcomes. Its evidence = how far each bucket sits from the feature's
    neutral point (no surge = 1.0, flat momentum = 0.0, coin-flip
    book = 0.5). If winners sit farther above neutral than losers, the
    feature is EARNING its weight -> it rises (capped). If it shows up
    in losers (evidence below neutral among wins, or inverted), it
    shrinks to the floor of its range.
  * features without enough data keep their weight untouched - a small
    sample never rewrites the book.
  * weights stay normalized to sum 1.0, and the runner clamps every
    applied weight to a floor, so one lucky feature can never zero
    out the rest.

RUN: python src/weekly_refit.py            (prints the report)
     python src/weekly_refit.py --apply    (writes refit.json; the
     runner applies it at the next pick if present)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LEDGER = REPO_ROOT / "data" / "ledger.jsonl"
REFIT = REPO_ROOT / "data" / "refit.json"
REFIT_HISTORY = REPO_ROOT / "data" / "refit_history.jsonl"

MIN_BUCKET_TRADES = 4   # both buckets need this many for a feature to move
MIN_TOTAL_TRADES = 12   # fewer closed trades than this: no refit at all
MAX_MOVE = 1.6          # a feature's weight can at most 1.6x
MIN_MOVE = 0.625        # ... or at most shrink to 0.625x
WEIGHT_FLOOR = 0.02

# ledger key -> (live weight key, current weight, neutral raw value)
FEATURE_MAP: dict[str, tuple[str, float, float]] = {
    "close_position":    ("close_position",    0.20, 0.5),
    "volume_surge":      ("volume_surge",      0.15, 1.0),   # 1.0 = no surge
    "late_momentum_pct": ("late_momentum",     0.20, 0.0),   # 0 = flat tape
    "day_momentum_pct":  ("day_momentum",      0.05, 0.0),
    "sector_flow":       ("sector_flow",       0.10, 0.5),
    "multi_day":         ("multi_day_momentum", 0.10, 0.5),
    "breakout":          ("breakout_10d",      0.05, 0.5),
    "book_pressure":     ("book_pressure",     0.10, 0.5),
    "aggression":        ("aggression",        0.05, 0.5),
}


def read_ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [
        json.loads(line)
        for line in LEDGER.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def refit(rows: list[dict]) -> dict | None:
    if len(rows) < MIN_TOTAL_TRADES:
        return None  # the tape hasn't spoken enough yet
    weights = {ledger_k: w for ledger_k, (_, w, _) in FEATURE_MAP.items()}
    notes: list[str] = []
    moved = 0
    for ledger_k, (wkey, base_w, neutral) in FEATURE_MAP.items():
        wins, losses = [], []
        for r in rows:
            v = r.get(ledger_k)
            if not isinstance(v, (int, float)):
                continue
            (wins if r.get("outcome") == "WIN" else losses).append(v)
        if len(wins) < MIN_BUCKET_TRADES or len(losses) < MIN_BUCKET_TRADES:
            continue
        w_ev = sum(wins) / len(wins) - neutral
        l_ev = sum(losses) / len(losses) - neutral
        if abs(w_ev) < 1e-9 and abs(l_ev) < 1e-9:
            continue  # both buckets at neutral: the feature says nothing
        if w_ev > 0 and l_ev <= 0:
            # winners show the trait, losers don't: earning its weight
            sep = w_ev / (w_ev + abs(l_ev) + 1e-9)      # 0.5..1
            move = 1.0 + (MAX_MOVE - 1.0) * (2 * sep - 1.0)
        elif w_ev <= 0 and l_ev > 0:
            move = MIN_MOVE                              # trait of losers
        else:
            # both sides above/below neutral: the STRONGER side tells
            sep = w_ev / (w_ev + l_ev) if (w_ev + l_ev) else 0.5
            if sep > 0.5:
                move = 1.0 + (MAX_MOVE - 1.0) * (2 * sep - 1.0) * 0.5
            else:
                move = 1.0 - (1.0 - MIN_MOVE) * (1 - 2 * sep) * 0.5
        move = max(MIN_MOVE, min(MAX_MOVE, move))
        new_w = max(WEIGHT_FLOOR, base_w * move)
        weights[ledger_k] = new_w
        moved += 1
        notes.append(
            f"{ledger_k}: win-mean {sum(wins)/len(wins):.2f} "
            f"vs loss-mean {sum(losses)/len(losses):.2f} "
            f"(neutral {neutral}) -> {base_w:.3f} -> {new_w:.3f}"
        )
    if not moved:
        return None
    total = sum(weights.values())
    # refit.json keys use the SCORER's names (the runner feeds this
    # straight into apply_weight_overrides), so translate here once.
    return {
        "generated": rows[-1].get("closed_at_utc", ""),
        "trades": len(rows),
        "features_moved": moved,
        "notes": notes,
        "weights": {
            FEATURE_MAP[k][0]: round(v / total, 4)
            for k, v in weights.items()
        },
    }


def apply_refit(report: dict) -> None:
    REFIT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    with REFIT_HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report) + "\n")


def main(argv=None) -> int:
    do_apply = "--apply" in (argv if argv is not None else sys.argv[1:])
    rows = read_ledger()
    report = refit(rows)
    if report is None:
        print(
            f"refit: {len(rows)} closed trades - not enough evidence yet "
            f"(needs >= {MIN_TOTAL_TRADES}, with >= {MIN_BUCKET_TRADES} "
            f"per bucket per feature)"
        )
        return 0
    print(
        f"refit: {report['trades']} trades, "
        f"{report['features_moved']} features moved\n"
    )
    for n in report["notes"]:
        print("  " + n)
    print("\nnew weights:", json.dumps(report["weights"]))
    if do_apply:
        apply_refit(report)
        print(f"\nwritten: {REFIT.name} (+ history appended)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
