"""
PSX KMIALL BOT
Outcomes assembler â€” the calibration dataset builder.

Why this exists
---------------
Tier 3 of the roadmap (IC analysis, measured weights, regime detection)
needs one thing above all: labeled outcomes. Every ENTER the bot ever
made, labeled by what actually happened, appended once per session into
a growing file:

    data/outcomes.jsonl

One record per executed signal:

    {
      "trading_date": "2026-09-07",
      "symbol": "ECOP",
      "entry_time": "2026-09-07T05:00:31+00:00",
      "entry_price": 49.01,
      "score": 0.5908,                  # decision-time master score
      "components": {...},              # z_* evidence snapshot
      "barrier": "profit",              # profit | stop | time | open
      "exit_time": "2026-09-07T05:52:11+00:00",
      "exit_price": 50.14,
      "pnl_pct": 2.3057,
      "label": 1,                      # 1 win, 0 loss, null open
    }

The triple-barrier label is which boundary hit FIRST:
    profit -> price >= entry * (1 + target%)
    stop   -> price <= entry * (1 - stop%)
    time   -> session ended first (force-close)

The labels are derived entirely from the files the bot already writes
(decisions.jsonl + portfolio.json); this module only assembles them,
once, at each session close. No live-path logic touches it â€” a broken
assembler can never break a trading session.

Usage (automatic, via live.py session close):
    from outcomes_assembler import assemble_day
    assemble_day("2026-09-07")

Standalone:
    python src/outcomes_assembler.py                 # today
    python src/outcomes_assembler.py --date 2026-09-07
    python src/outcomes_assembler.py --stats         # running hit-rate
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths, sessions


def _outcomes_file() -> Path:
    """The outcomes ledger path, resolved at call time (test-friendly)."""
    return paths.DATA_DIR / "outcomes.jsonl"


# ---------------------------------------------------------------------------
# Loading the day's raw material
# ---------------------------------------------------------------------------

def load_enter_decisions(trading_date: str) -> list[dict]:
    """ENTER decision records for the date, from the decisions ledger."""
    ledger = paths.LOGS_DIR / "decisions.jsonl"
    if not ledger.exists():
        return []

    out: list[dict] = []
    with ledger.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("action") != "ENTER":
                continue
            at = record.get("at")
            if not at:
                continue
            try:
                moment = datetime.fromisoformat(at)
            except ValueError:
                continue
            if sessions.trading_date(moment).isoformat() == trading_date:
                out.append(record)
    return out


def load_day_positions(trading_date: str) -> dict[str, dict]:
    """{symbol: position} for entries opened on the date."""
    portfolio_file = paths.DATA_DIR / "portfolio.json"
    if not portfolio_file.exists():
        return {}
    try:
        raw = json.loads(portfolio_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        p["symbol"]: p
        for p in raw
        if isinstance(p, dict)
        and p.get("entry_date") == trading_date
        and p.get("symbol")
    }


# ---------------------------------------------------------------------------
# Barrier labeling
# ---------------------------------------------------------------------------

def classify_barrier(position: dict, profit_target_pct: float = 2.0,
                     stop_pct: float = 2.0) -> str:
    """
    Which triple barrier the position hit.

    The exit reason written by portfolio.py names the rule that fired;
    that IS the first-hit barrier (check order inside portfolio.py is
    target -> stop -> time). When no rule reason exists, the close came
    from the session-end force-close: the time barrier.
    """
    reason = str(position.get("exit_reason") or "")
    if "profit target" in reason.lower():
        return "profit"
    if "stop-loss" in reason.lower() or "rule 7" in reason.lower():
        return "stop"
    if "holding period" in reason.lower() or "end of session" in reason.lower():
        return "time"
    if position.get("status") == "OPEN":
        return "open"
    # Unknown reason but closed: time barrier is the honest default for
    # an intraday-only book (nothing carries overnight).
    return "time"


def build_outcome_record(
    trading_date: str,
    decision: dict,
    position: dict,
) -> dict:
    """One labeled outcome row from a decision + its fill."""
    pnl_pct = position.get("pnl_pct")
    barrier = classify_barrier(position)
    label = None
    if barrier != "open" and pnl_pct is not None:
        label = 1 if pnl_pct >= 0 else 0

    metadata = decision.get("metadata") or {}
    return {
        "trading_date": trading_date,
        "symbol": decision.get("symbol"),
        "entry_time": decision.get("at"),
        "entry_price": decision.get("price") or position.get("entry_price"),
        "score": decision.get("score"),
        "score_kind": metadata.get("score_kind"),
        "evidence_count": metadata.get("evidence_count"),
        "barrier": barrier,
        "exit_time": position.get("exit_date"),
        "exit_price": position.get("exit_price"),
        "pnl": position.get("pnl"),
        "pnl_pct": pnl_pct,
        "label": label,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def assemble_day(trading_date: str) -> list[dict]:
    """
    Append the day's labeled outcomes to data/outcomes.jsonl.

    Idempotent: a (date, symbol) pair already present is never written
    twice, so re-running at close (or re-running a backfill) is safe.
    Positions still open are recorded with barrier="open" and no label;
    they are re-assembled on the next call for their date (after the
    force-close has written an exit) â€” the idempotency key must
    therefore treat open rows as stale and replace them.
    """
    decisions = load_enter_decisions(trading_date)
    positions = load_day_positions(trading_date)
    if not decisions:
        return []

    # Load the full current file, minus this date's stale "open" rows â€”
    # those get re-assembled below now that the position has an exit.
    current: list[dict] = []
    if _outcomes_file().exists():
        with _outcomes_file().open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                is_stale = (
                    record.get("trading_date") == trading_date
                    and record.get("barrier") == "open"
                )
                if not is_stale:
                    current.append(record)

    # Finality set: (date, symbol) pairs already carrying a real label.
    existing = {
        (record.get("trading_date"), record.get("symbol"))
        for record in current
    }

    written: list[dict] = []
    for decision in decisions:
        symbol = decision.get("symbol")
        position = positions.get(symbol)
        if position is None:
            continue
        record = build_outcome_record(trading_date, decision, position)

        key = (trading_date, symbol)
        if record["barrier"] == "open":
            # Open rows are refreshed, not duplicated.
            current = [c for c in current
                      if (c.get("trading_date"), c.get("symbol")) != key]
            current.append(record)
            written.append(record)
            continue

        if key in existing:
            continue  # already labeled and final
        current.append(record)
        existing.add(key)
        written.append(record)

    if written:
        _outcomes_file().parent.mkdir(parents=True, exist_ok=True)
        with _outcomes_file().open("w", encoding="utf-8") as f:
            for record in current:
                f.write(json.dumps(record, default=str) + "\n")

    return written


def stats() -> dict:
    """Running calibration stats over every labeled outcome so far."""
    if not _outcomes_file().exists():
        return {"labeled": 0}

    wins = losses = open_positions = 0
    barriers = {"profit": 0, "stop": 0, "time": 0}
    pnl_total = 0.0
    with _outcomes_file().open("r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            barrier = record.get("barrier")
            if barrier == "open":
                open_positions += 1
                continue
            if barrier in barriers:
                barriers[barrier] += 1
            label = record.get("label")
            if label == 1:
                wins += 1
            elif label == 0:
                losses += 1
            if isinstance(record.get("pnl"), (int, float)):
                pnl_total += record["pnl"]

    labeled = wins + losses
    return {
        "labeled": labeled,
        "wins": wins,
        "losses": losses,
        "open": open_positions,
        "hit_rate": round(wins / labeled, 4) if labeled else None,
        "barriers": barriers,
        "total_pnl": round(pnl_total, 2),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Assemble labeled trade outcomes for calibration.",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Trading date YYYY-MM-DD (default: today PKT).",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Print running calibration stats and exit.",
    )
    args = parser.parse_args(argv)

    if args.stats:
        print(json.dumps(stats(), indent=2))
        return 0

    trading_date = args.date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()

    written = assemble_day(trading_date)
    print(f"Outcomes appended : {len(written)} ({trading_date})")
    for record in written:
        print(
            f"  {record['symbol']:<8} barrier={record['barrier']:<7} "
            f"pnl_pct={record['pnl_pct']} label={record['label']}"
        )
    print(json.dumps(stats(), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())


