"""Live per-symbol lock memory - self-learning from real trades.

The v2.5 memory lists come from the backtest corpus alone. This module
is the missing half of self-learning: the LIVE ledger (every labeled
outcome in data/outcomes.jsonl) folds into the same per-symbol
records, so a symbol that starts continuing (or failing) in the real
market shifts its own record within one session - no Saturday sweep
required.

Record shape per symbol (stored in data/backtest/live_lock_records.json):

    {"n": int, "wins": int, "net": float, "last_date": str,
     "src": "live"}

The engine's read side is unchanged: lessons.py merges these live
records INTO the corpus table (live has the last word - it is real
money) before the proven/banned lists are derived. The corpus stays
the 180-day statistical base; the live ledger keeps the lists honest
as the market drifts.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "backtest" / "live_lock_records.json"
LEDGER = ROOT / "data" / "outcomes.jsonl"

# Same law as the corpus: TP +2 / SL -1, cost stack folded in by the
# outcome labeler (pnl_pct is already net).
WIN_LABEL = "tp"


def load_ledger(path: Path | None = None) -> list[dict]:
    path = path or LEDGER
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def fold_live(rows: list[dict]) -> dict[str, dict]:
    """Per-symbol records from the live ledger (lock-family entries
    only - the bot's own trades under the current law)."""
    recs: dict[str, dict] = {}
    for r in rows:
        sym = r.get("symbol")
        if not sym:
            continue
        pnl = r.get("pnl_pct")
        if pnl is None:
            continue
        rec = recs.setdefault(
            sym, {"n": 0, "wins": 0, "net": 0.0, "last_date": "", "src": "live"}
        )
        rec["n"] += 1
        if str(r.get("barrier") or "").lower() == WIN_LABEL or pnl > 0:
            rec["wins"] += 1
        rec["net"] += float(pnl)
        d = str(r.get("trading_date") or "")
        if d > rec["last_date"]:
            rec["last_date"] = d
    for rec in recs.values():
        rec["net"] = round(rec["net"], 2)
    return recs


def merge_tables(corpus: dict, live: dict) -> dict:
    """The lessons-read view: corpus base, live records overriding the
    same symbol (real money outranks simulation). Both are returned
    under the grind-6 schema the proven/banned derivation expects:
    {sym: {"n", "win_pct", "net"}}."""
    merged = {
        sym: {
            "n": int(s.get("n") or 0),
            "win_pct": float(s.get("win_pct") or 0.0),
            "net": float(s.get("net") or 0.0),
        }
        for sym, s in (corpus or {}).items()
    }
    for sym, rec in (live or {}).items():
        n = rec.get("n") or 0
        if n <= 0:
            continue
        merged[sym] = {
            "n": int(merged.get(sym, {}).get("n", 0)) + int(n),
            "win_pct": round(
                (
                    merged.get(sym, {}).get("win_pct", 0.0)
                    * merged.get(sym, {}).get("n", 0)
                    + (rec["wins"] / n * 100.0) * n
                )
                / (merged.get(sym, {}).get("n", 0) + n),
                2,
            )
            if merged.get(sym)
            else round(rec["wins"] / n * 100.0, 2),
            "net": round(
                merged.get(sym, {}).get("net", 0.0) + rec.get("net", 0.0),
                2,
            ),
        }
    return merged


def update(trading_date: str | None = None) -> dict:
    """Fold the current ledger into the live records and persist.
    Idempotent: the ledger is append-only, so recomputing rewrites the
    same records."""
    recs = fold_live(load_ledger())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "updated": trading_date or "",
                "records": recs,
            },
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return recs
