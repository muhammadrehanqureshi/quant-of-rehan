"""
PSX KMIALL BOT
Lessons - the self-learning layer.

What "learning" means here
--------------------------
The bot already writes its own report card: every executed signal is
labeled with its triple-barrier outcome in data/outcomes.jsonl (see
outcomes_assembler.py). This module closes the loop:

    outcomes.jsonl  ->  lessons.json  ->  DecisionEngine behaviour

Three lessons, each deliberately small and auditable:

1. Symbol blacklist. A symbol the bot has entered >= min_outcomes times
   with a win rate at or below blacklist_win_rate and an average
   pnl_pct below blacklist_avg_pnl_pct is excluded from future
   candidate pools. Persistent losers are removed from the menu.

2. Score scaling. A linear map fitted from decision-time score to
   realised pnl_pct over all labeled outcomes. The engine applies it
   as score * (1 + slope * (score - center)) so that better-scored
   candidates count for slightly more and overconfident ones for
   less. The slope is clamped to a small range - this nudges the
   ranking, it does not replace the conviction gate.

3. Meta-lesson (regime caution). When the most recent
   tighten_lookback outcomes span at least tighten_min_dates distinct
   trading days inside a tighten_window_days-day lookback and the
   profit rate has fallen to tighten_profit_rate or below, the
   conviction gate tightens by min_gain_for_tightening for the next
   session. The bot trades less in a stretch where its calls stop
   working; the gate relaxes automatically once the window's bad
   stretch ages out.

Honesty rules
-------------
- Nothing is learned before there is evidence: every rule has a
  minimum-outcome guard, and until it is met the lesson simply does
  not apply (it never half-applies).
- Every applied lesson is written to data/lessons.json with the
  counts it was derived from, so any adjustment can be traced back
  to the trades that justified it.
- Learning only happens at session close (wired from live.py), never
  mid-session: today's open trades are not evidence.

Usage (automatic, via live.py session close):
    from lessons import refresh_lessons
    refresh_lessons("2026-09-09")

Standalone:
    python src/lessons.py                # recompute + print
    python src/lessons.py --stats        # engine-readable view
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths, sessions

logger = logging.getLogger("lessons")

# Default learning policy. config.json may override any of these under
# the "learning" key.
DEFAULTS = {
    "enabled": True,
    "min_outcomes_for_blacklist": 4,
    "blacklist_win_rate": 0.25,
    "blacklist_avg_pnl_pct": -0.5,
    # v0.16.5: on mutual-fund dump days, raise the conviction bar by
    # this much (engine adds it to min_master_score).
    "mf_dump_score_bump": 0.03,
    "min_outcomes_for_scale": 10,
    "max_scale_slope": 0.5,
    "tighten_lookback": 15,
    "tighten_min_dates": 4,
    "tighten_window_days": 20,
    "tighten_profit_rate": 0.20,
    "min_gain_for_tightening": 0.03,
}


def _lessons_file() -> Path:
    return paths.DATA_DIR / "lessons.json"


def _policy(config: dict | None = None) -> dict:
    policy = dict(DEFAULTS)
    if config:
        override = config.get("learning", {})
        if isinstance(override, dict):
            policy.update(override)
    return policy


# ---------------------------------------------------------------------------
# Loading outcomes
# ---------------------------------------------------------------------------

def load_labeled_outcomes() -> list[dict]:
    """Every final (non-open) labeled outcome, oldest last."""
    outcomes_file = paths.DATA_DIR / "outcomes.jsonl"
    if not outcomes_file.exists():
        return []
    out: list[dict] = []
    with outcomes_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("barrier") == "open":
                continue  # not evidence yet
            if record.get("label") is None:
                continue
            out.append(record)
    out.sort(key=lambda r: str(r.get("trading_date", "")))
    return out


# ---------------------------------------------------------------------------
# Lesson computation
# ---------------------------------------------------------------------------

def _fit_score_scale(outcomes: list[dict], max_slope: float) -> dict | None:
    """
    OLS slope of pnl_pct on decision-time score, anchored at the
    midpoint of the observed scores. None when too few outcomes or a
    degenerate fit.
    """
    if len(outcomes) < 3:
        return None
    pts = [
        (float(r["score"]), float(r["pnl_pct"]))
        for r in outcomes
        if isinstance(r.get("score"), (int, float))
        and isinstance(r.get("pnl_pct"), (int, float))
    ]
    if len(pts) < 3:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    n = len(pts)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 1e-12:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in pts) / sxx
    # Clamp BEFORE storing: this lesson only nudges the ranking, and an
    # unclamped slope from a few lucky trades could reorder everything.
    slope = max(-max_slope, min(max_slope, slope))
    intercept = mean_y - slope * mean_x
    return {
        "slope": round(slope, 6),
        "intercept": round(intercept, 6),
        "center": round(mean_x, 6),
        "n": n,
        "min_score": round(min(xs), 4),
        "max_score": round(max(xs), 4),
        "clamped_to": max_slope,
    }


def _apply_mf_dump_lesson(lessons: dict, policy: dict) -> None:
    """
    Rule 12c conviction bump (v0.16.5): when the latest flow session
    shows Mutual Funds net-dumping, raise the engine's conviction bar
    for the session. Applied on every compute path - including the
    zero-outcomes early return - because flow data exists regardless
    of whether outcomes have been labeled yet.
    """
    try:
        history = _lessons_file().parent / "foreign_flow_history.jsonl"
        rows = [
            json.loads(line)
            for line in history.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = rows[-1] if rows else None
        mf_net = float(
            ((latest or {}).get("byInvestor") or {})
            .get("Mutual Funds", {})
            .get("net")
            or 0.0
        )
        mf_dump_bump = float(policy.get("mf_dump_score_bump", 0.0))
        if mf_net < 0 and mf_dump_bump > 0:
            lessons["min_master_score_adjustment"] = mf_dump_bump
            lessons["mf_dump"] = {
                "net_usd": mf_net,
                "bump": mf_dump_bump,
            }
    except (OSError, ValueError, json.JSONDecodeError):
        pass


def _apply_lock_memory_lesson(lessons: dict) -> None:
    """Rule 26 escape hatch data (v2.5.0): symbols whose HISTORICAL lock
    continuation is proven (per_symbol_lock_report.json, win >= 70% on
    n >= 8 over 175 sessions) pass Rule 26's dead zone below the normal
    conviction ceiling. Grind 6 measured per-symbol persistence as weak
    walk-forward (corr ~ 0), so this is deliberately narrow: only long,
    strong records qualify, and the refit loop recomputes the list
    every Saturday 21:00 as the corpus grows.

    v2.7.0 self-learning: the LIVE ledger (every labeled real trade,
    src/live_memory.py) is folded into the same table before the lists
    derive - live records have the last word on their symbols, so a
    symbol that starts continuing or failing in the real market moves
    its own list within one session, not at the next Saturday sweep."""
    report = Path(__file__).resolve().parents[1] / "data" / "backtest" / "per_symbol_lock_report.json"
    table: dict = {}
    if report.exists():
        try:
            table = json.loads(report.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            table = {}
    # The live half: real trades merged over the corpus table.
    try:
        import live_memory

        table = live_memory.merge_tables(
            table, live_memory.fold_live(live_memory.load_ledger())
        )
    except Exception:  # noqa: BLE001 - learning must never break refresh
        pass
    if not table:
        return
    proven = {
        sym: {
            "n": s["n"],
            "win_rate": round(s["win_pct"] / 100, 4),
            "net_pct": round(s["net"], 2),
        }
        for sym, s in table.items()
        if s["n"] >= 8 and s["win_pct"] >= 70.0
    }
    if proven:
        lessons["lock_memory_symbols"] = proven
    # The other half of per-symbol memory (grind 6 walk-forward): symbols
    # whose lock continuations chronically FAIL (n >= 3, win < 50%,
    # negative net - GEMMEL 10% over 10, EMCO 14.3% over 7, the 0-for-4
    # cohort). A one-day strong score cannot outvote a record that never
    # pays; these are refused the dead-zone escape entirely.
    banned = {
        sym: {
            "n": s["n"],
            "win_rate": round(s["win_pct"] / 100, 4),
            "net_pct": round(s["net"], 2),
        }
        for sym, s in table.items()
        if s["n"] >= 3 and s["win_pct"] < 50.0 and s["net"] < 0.0
    }
    if banned:
        lessons["lock_banned_symbols"] = banned


def compute_lessons(trading_date: str, config: dict | None = None) -> dict:
    """
    Derive today's lessons from every labeled outcome so far.

    Pure function of the outcomes file + policy: no IO beyond the
    outcomes read. Returns the lessons dict that refresh_lessons
    persists and the engine consumes.
    """
    policy = _policy(config)
    outcomes = load_labeled_outcomes()
    lessons: dict = {
        "trading_date": trading_date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "labeled": len(outcomes),
        "blacklisted": {},
        "score_scale": None,
        "meta": None,
    }
    _apply_mf_dump_lesson(lessons, policy)
    _apply_lock_memory_lesson(lessons)
    if not outcomes:
        return lessons

    # --- 1. Symbol blacklist ---------------------------------------------
    by_symbol: dict[str, list[dict]] = {}
    for r in outcomes:
        symbol = r.get("symbol")
        if symbol:
            by_symbol.setdefault(str(symbol), []).append(r)

    min_n = int(policy["min_outcomes_for_blacklist"])
    for symbol, rows in sorted(by_symbol.items()):
        if len(rows) < min_n:
            continue
        wins = sum(1 for r in rows if r.get("label") == 1)
        win_rate = wins / len(rows)
        pnls = [
            float(r["pnl_pct"]) for r in rows
            if isinstance(r.get("pnl_pct"), (int, float))
        ]
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0.0
        if (
            win_rate <= float(policy["blacklist_win_rate"])
            and avg_pnl < float(policy["blacklist_avg_pnl_pct"])
        ):
            lessons["blacklisted"][symbol] = {
                "n": len(rows),
                "win_rate": round(win_rate, 4),
                "avg_pnl_pct": round(avg_pnl, 4),
            }

    # --- 2. Score scaling --------------------------------------------------
    scale = _fit_score_scale(outcomes, float(policy["max_scale_slope"]))
    if scale and len(outcomes) >= int(policy["min_outcomes_for_scale"]):
        lessons["score_scale"] = scale

    # --- 3. Meta-lesson: tighten after a bad stretch ------------------------
    lookback = int(policy["tighten_lookback"])
    recent = outcomes[-lookback:]
    dates = sorted({str(r.get("trading_date", "")) for r in recent})
    if recent and len(dates) >= int(policy["tighten_min_dates"]):
        newest = max(str(r.get("trading_date", "")) for r in recent)
        try:
            newest_day = datetime.fromisoformat(newest).date()
        except ValueError:
            newest_day = None
        window_start = (
            newest_day - timedelta(days=int(policy["tighten_window_days"]))
            if newest_day else None
        )
        in_window = recent
        if window_start is not None:
            in_window = [
                r for r in recent
                if str(r.get("trading_date", "")) >= window_start.isoformat()
            ]
        wins = sum(1 for r in in_window if r.get("label") == 1)
        profit_rate = wins / len(in_window) if in_window else 1.0
        lessons["meta"] = {
            "window_n": len(in_window),
            "distinct_dates": len(set(
                str(r.get("trading_date", "")) for r in in_window
            )),
            "profit_rate": round(profit_rate, 4),
            "tighten_profit_rate": float(policy["tighten_profit_rate"]),
            "should_tighten": (
                profit_rate <= float(policy["tighten_profit_rate"])
            ),
        }

    return lessons


# ---------------------------------------------------------------------------
# Persistence + engine view
# ---------------------------------------------------------------------------

def refresh_lessons(trading_date: str, config: dict | None = None) -> dict:
    """
    Recompute lessons and persist them. Returns the lessons dict.

    Called once at session close. Idempotent: recomputing for the same
    outcomes simply rewrites the same file.
    """
    policy = _policy(config)
    lessons = compute_lessons(trading_date, config)
    lessons["applied"] = bool(policy.get("enabled", True))
    if lessons["applied"]:
        lessons["applied_at"] = datetime.now(timezone.utc).isoformat()
    _lessons_file().parent.mkdir(parents=True, exist_ok=True)
    _lessons_file().write_text(
        json.dumps(lessons, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return lessons


def load_lessons(config: dict | None = None) -> dict:
    """
    The engine-readable view: what DecisionEngine should apply right now.

    Applies the policy gates a second time at read time, so a stale
    lessons.json never leaks a lesson the current config has disabled.
    Missing file or learning disabled yields the neutral view.
    """
    policy = _policy(config)
    neutral = {
        "blacklisted": set(),
        "score_scale": None,
        "min_master_score_adjustment": 0.0,
        "lock_memory_symbols": set(),
        "lock_banned_symbols": set(),
    }
    if not policy.get("enabled", True):
        return neutral
    lessons_file = _lessons_file()
    if not lessons_file.exists():
        return neutral
    try:
        raw = json.loads(lessons_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return neutral
    if not raw.get("applied", False):
        return neutral

    view = {
        "blacklisted": set(raw.get("blacklisted", {})),
        "score_scale": raw.get("score_scale"),
        "min_master_score_adjustment": 0.0,
        # Rule 26 escape hatch (v2.5.0): proven lock-continuers.
        "lock_memory_symbols": set(raw.get("lock_memory_symbols", {})),
        # v2.5.1: chronic lock-fakes (grind-6 walk-forward, win < 50% on
        # n >= 3 with negative net) are refused the escape hatch.
        "lock_banned_symbols": set(raw.get("lock_banned_symbols", {})),
    }
    meta = raw.get("meta") or {}
    if meta.get("should_tighten"):
        view["min_master_score_adjustment"] += float(
            policy["min_gain_for_tightening"]
        )
    # Rule 12c (v0.16.5): mutual-fund dump days raise the bar too.
    # Both lessons sum; capped so the gate can never become unreachable.
    mf = raw.get("mf_dump") or {}
    if isinstance(mf.get("net_usd"), (int, float)) and mf["net_usd"] < 0:
        view["min_master_score_adjustment"] += float(mf.get("bump") or 0.0)
    view["min_master_score_adjustment"] = round(
        min(view["min_master_score_adjustment"], 0.08), 4
    )
    return view


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Recompute the self-learning lessons from outcomes.",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Trading date YYYY-MM-DD (default: today PKT).",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print the engine-readable view and exit.",
    )
    args = parser.parse_args(argv)

    if args.stats:
        view = load_lessons()
        print(json.dumps({
            "blacklisted": sorted(view["blacklisted"]),
            "score_scale": view["score_scale"],
            "min_master_score_adjustment":
                view["min_master_score_adjustment"],
        }, indent=2))
        return 0

    trading_date = args.date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()
    lessons = refresh_lessons(trading_date)
    print(json.dumps(lessons, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
