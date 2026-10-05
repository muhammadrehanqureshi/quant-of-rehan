"""
Gate refit - the ledger tunes the entry doctrine, not a human.

WHAT: reads the closed-trade book, buckets each entry-context feature
(entry score, entry premium over the prior close, breadth at entry,
opening zone) by outcome, and when the evidence is thick enough
(BUCKET_MIN trades on BOTH sides) moves the corresponding config knob
one step at a time. Every move is written to data/refit_history.jsonl
with the counts that justified it, and data/gate_refit.json carries
the current verdict for the STATUS page. Nothing moves on thin
evidence: a small sample never rewrites the book.

RUN: python src/gate_refit.py            (evaluate, no writes)
     python src/gate_refit.py --apply    (evaluate + write moves)

Called with --apply by the cloud close-out after the lessons refresh.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths  # noqa: E402

# A feature only moves when both buckets hold at least this many
# closed trades. Anything thinner stays untouched.
BUCKET_MIN = 20
# One evaluation step per feature, in the direction the ledger votes.
# Knobs map to config.json keys (with a config_moved marker persisted
# so the close-out can report exactly what changed).
STEPS = {
    "min_master_score": 0.02,       # conviction gate
    "max_entry_off_low_pct": 0.25,  # chase cap
    "hard_min_breadth_pct": 1.0,    # breadth floor
}
# Hard clamps - the ledger can tune a knob, never weld it shut.
CLAMPS = {
    "min_master_score": (0.50, 0.75),
    "max_entry_off_low_pct": (2.0, 4.0),
    "hard_min_breadth_pct": (35.0, 50.0),
}

CONFIG = paths.PROJECT_ROOT / "config.json"
GATE_REFIT = paths.DATA_DIR / "gate_refit.json"
GATE_HISTORY = paths.DATA_DIR / "refit_history.jsonl"


def _load_book() -> list[dict]:
    book_file = paths.DATA_DIR / "portfolio.json"
    if not book_file.exists():
        return []
    try:
        raw = json.loads(book_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    rows = raw if isinstance(raw, list) else raw.get("positions", [])
    return [
        r for r in rows
        if isinstance(r, dict)
        and r.get("status") == "CLOSED"
        and isinstance(r.get("pnl"), (int, float))
    ]


def _bucket_stats(rows: list[dict], key: str) -> dict:
    """Mean of `key` per outcome bucket, with counts. Rows missing the
    key (older book entries) simply don't count for that feature."""
    wins = [r[key] for r in rows if key in r and r.get("pnl", 0) > 0]
    losses = [r[key] for r in rows if key in r and r.get("pnl", 0) <= 0]
    out = {}
    for name, bucket in (("wins", wins), ("losses", losses)):
        vals = [v for v in bucket if isinstance(v, (int, float))]
        out[name] = {
            "n": len(vals),
            "mean": round(sum(vals) / len(vals), 4) if vals else None,
        }
    return out


def evaluate(config: dict | None = None) -> dict:
    """The evidence table + the moves the evidence votes for."""
    cfg = config or json.loads(CONFIG.read_text(encoding="utf-8"))
    rows = _load_book()
    verdict: dict = {
        "trades": len(rows),
        "bucket_min": BUCKET_MIN,
        "moves": [],
        "features": {},
    }
    if len(rows) < 2 * BUCKET_MIN:
        verdict["note"] = (
            f"thin sample: {len(rows)} closed trades, "
            f"{2 * BUCKET_MIN} needed before any knob moves"
        )
        return verdict

    for key, step in STEPS.items():
        stats = _bucket_stats(rows, key)
        verdict["features"][key] = stats
        w, l = stats.get("wins", {}), stats.get("losses", {})
        if w.get("n", 0) < BUCKET_MIN or l.get("n", 0) < BUCKET_MIN:
            continue
        w_mean, l_mean = w.get("mean"), l.get("mean")
        if w_mean is None or l_mean is None:
            continue
        current = cfg.get(key)
        if not isinstance(current, (int, float)):
            continue
        lo, hi = CLAMPS[key]
        # Winners' mean vs losers' mean votes the knob's direction:
        # winners clearing a higher bar -> raise it; winners sitting
        # lower than losers -> the bar is filtering the wrong trades.
        if w_mean > l_mean and current < hi:
            new = min(hi, round(current + step, 4))
        elif w_mean < l_mean and current > lo:
            new = max(lo, round(current - step, 4))
        else:
            continue
        if new != current:
            verdict["moves"].append({
                "key": key,
                "from": current,
                "to": new,
                "win_mean": w_mean,
                "loss_mean": l_mean,
                "wins": w["n"],
                "losses": l["n"],
            })
    return verdict


def apply() -> dict:
    """Evaluate, write the moves into config.json, persist the audit."""
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    verdict = evaluate(cfg)
    if verdict["moves"]:
        for mv in verdict["moves"]:
            cfg[mv["key"]] = mv["to"]
        CONFIG.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        verdict["applied_at"] = _utcnow()
        GATE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with GATE_HISTORY.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(verdict) + "\n")
    GATE_REFIT.write_text(
        json.dumps(verdict, indent=1), encoding="utf-8"
    )
    return verdict


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    if "--apply" in (argv or sys.argv[1:]):
        v = apply()
        for mv in v.get("moves", []):
            print(f"moved {mv['key']}: {mv['from']} -> {mv['to']} "
                  f"(win {mv['win_mean']} vs loss {mv['loss_mean']})")
        if not v.get("moves"):
            print(v.get("note", "no knob earned a move"))
    else:
        v = evaluate()
        print(json.dumps(v, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
