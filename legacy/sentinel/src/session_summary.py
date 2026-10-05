"""
PSX KMIALL BOT
Session summary - the end-of-day report of every call the bot made.

What it reports
---------------
At session close the bot prints (and logs) one compact report:

  * Every ENTER of the day: symbol, entry time/price, target, exit
    time/price, exit reason, P&L in Rs and %.
  * Every STAND_ASIDE of the day, grouped by reason - the day's
    "thinking" made visible: how many cycles were conviction-gated,
    breadth-gated, capped, or warmup.
  * The day's realised P&L and hit rate.

Sources
-------
logs/decisions.jsonl - one line per decide cycle (the calls).
data/portfolio.json   - the executed entries/exits (the fills).

The ledger is append-only JSONL: {"at": ..., "action": ...}. Summaries
are assembled for one trading date at a time.

Usage
-----
    python src/session_summary.py                 # today's summary
    python src/session_summary.py --date 2026-09-07
    python src/session_summary.py --markdown      # compact chat format
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


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_decisions(trading_date: str) -> list[dict]:
    """
    The decide-cycle decisions for one trading date, in order.

    `at` is a UTC ISO timestamp; the PKT-local date selects the day's
    lines. Corrupt lines are skipped, not fatal - the ledger must never
    become unreadable because one cycle wrote a bad row.
    """
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


def load_positions(trading_date: str) -> list[dict]:
    """Portfolio entries opened on the trading date (any status)."""
    portfolio_file = paths.DATA_DIR / "portfolio.json"
    if not portfolio_file.exists():
        return []
    try:
        raw = json.loads(portfolio_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        p for p in raw
        if isinstance(p, dict) and p.get("entry_date") == trading_date
    ]


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------

def _short_reason(reason: str) -> str:
    """Collapse a stand-aside reason into its category."""
    if not reason:
        return "unspecified"
    lower = reason.lower()
    if "warm" in lower or "no current-session data" in lower:
        return "warming up"
    if "entry limit" in lower:
        return "entry cap reached"
    if "conviction" in lower and "score" in lower:
        return "below conviction gate"
    if "thin evidence" in lower:
        return "thin evidence"
    if "breadth" in lower:
        return "weak breadth"
    if "correlated" in lower:
        return "correlation block"
    if "no eligible" in lower:
        return "no eligible candidates"
    if "circuit" in lower:
        return "circuit breaker"
    return reason[:60]


def build_summary(trading_date: str) -> dict:
    """Assemble the day's report from the ledger and the portfolio."""
    decisions = load_decisions(trading_date)
    positions = load_positions(trading_date)

    enters = [d for d in decisions if d.get("action") == "ENTER"]
    asides = [d for d in decisions if d.get("action") == "STAND_ASIDE"]

    # Group the stand-asides by category, keeping counts.
    aside_counts: dict[str, int] = {}
    for d in asides:
        category = _short_reason(str(d.get("reason", "")))
        aside_counts[category] = aside_counts.get(category, 0) + 1

    # Attach each position's decision-time score to the fill.
    by_symbol = {}
    for d in enters:
        symbol = d.get("symbol")
        if symbol:
            by_symbol[symbol] = d

    trades: list[dict] = []
    realised_pnl = 0.0
    wins = 0
    losses = 0
    open_count = 0

    for p in positions:
        symbol = p.get("symbol")
        decision = by_symbol.get(symbol, {})
        entry_at = decision.get("at") or p.get("entry_date")
        pnl = p.get("pnl")
        pnl_pct = p.get("pnl_pct")
        status = p.get("status")

        if status == "CLOSED" and isinstance(pnl, (int, float)):
            realised_pnl += pnl
            if pnl_pct is not None and pnl_pct >= 0:
                wins += 1
            else:
                losses += 1

        if status == "OPEN":
            open_count += 1

        trades.append({
            "symbol": symbol,
            "action": "ENTER",
            "score": decision.get("score"),
            "entry_price": p.get("entry_price"),
            "entry_time": entry_at,
            "target_price": p.get("target_price"),
            "status": status,
            "exit_price": p.get("exit_price"),
            "exit_time": p.get("exit_date"),
            "exit_reason": p.get("exit_reason", ""),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
        })

    return {
        "trading_date": trading_date,
        "cycles": len(decisions),
        "enters": len(enters),
        "stand_asides": len(asides),
        "stand_aside_reasons": aside_counts,
        "trades": trades,
        "realised_pnl": round(realised_pnl, 2),
        "wins": wins,
        "losses": losses,
        "still_open": open_count,
        # Self-learning state as of this close: what the bot has
        # learned from its labeled outcomes so far.
        "lessons": _lessons_snapshot(),
    }


def _lessons_snapshot() -> dict | None:
    """The engine-readable lessons view, or None when unavailable."""
    try:
        import lessons as lessons_mod
        view = lessons_mod.load_lessons()
        return {
            "blacklisted": sorted(view["blacklisted"]),
            "score_scale": bool(view["score_scale"]),
            "gate_adjustment": view["min_master_score_adjustment"],
        }
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _pkt_time(value: str | None) -> str:
    """UTC ISO string -> HH:MM PKT, or '--:--'."""
    if not value:
        return "--:--"
    try:
        moment = datetime.fromisoformat(str(value))
        return sessions.to_pkt(moment).strftime("%H:%M")
    except ValueError:
        return str(value)[:5]


def render_text(summary: dict) -> str:
    """The full console report."""
    line = "=" * 74
    thin = "-" * 74
    out = [
        line,
        f"SESSION SUMMARY - {summary['trading_date']}",
        line,
        "",
        f"Decide cycles        : {summary['cycles']}",
        f"ENTER signals        : {summary['enters']}",
        f"Stand-asides         : {summary['stand_asides']}",
    ]

    if summary["stand_aside_reasons"]:
        out.append("")
        out.append("STAND-ASIDES BY REASON")
        out.append(thin)
        for reason, count in sorted(
            summary["stand_aside_reasons"].items(),
            key=lambda kv: -kv[1],
        ):
            out.append(f"  {reason:<28} {count:>4}x")

    out.append("")
    out.append("TRADES")
    out.append(thin)
    if not summary["trades"]:
        out.append("  (no entries today)")
    else:
        for t in summary["trades"]:
            status = t["status"] or "?"
            exit_price = (
                f"{t['exit_price']:.2f}" if t["exit_price"] is not None else "-"
            )
            pnl_text = (
                f"{t['pnl']:+.2f} ({t['pnl_pct']:+.2f}%)"
                if t["pnl"] is not None else "open"
            )
            score_text = (
                f" score={t['score']:.4f}" if isinstance(t["score"], float) else ""
            )
            out.append(
                f"  {t['symbol']:<8} {status:<6} "
                f"in={t['entry_price']:.2f}@{_pkt_time(t['entry_time'])} "
                f"out={exit_price} "
                f"pnl={pnl_text}{score_text}"
            )
            if t["exit_reason"]:
                out.append(f"           exit: {t['exit_reason']}")

    out.append("")
    out.append("DAY RESULT")
    out.append(thin)
    out.append(f"  Realised P&L       : Rs. {summary['realised_pnl']:+.2f}")
    out.append(
        f"  Closed trades      : {summary['wins']} wins / "
        f"{summary['losses']} losses"
    )
    if summary["still_open"]:
        out.append(
            f"  Still open         : {summary['still_open']} "
            f"(force-closes at session end)"
        )
    out.append(line)
    return "\n".join(out)


def render_markdown(summary: dict) -> str:
    """The compact chat-update format."""
    out = [f"**DAY SUMMARY - {summary['trading_date']}**", ""]

    for t in summary["trades"]:
        if t["pnl"] is not None:
            verdict = "WIN" if (t["pnl_pct"] or 0) >= 0 else "LOSS"
            out.append(
                f"- `{t['symbol']}` {t['entry_price']:.2f} → "
                f"{t['exit_price']:.2f}  **{verdict}** "
                f"({t['pnl_pct']:+.2f}%)"
            )
        else:
            out.append(
                f"- `{t['symbol']}` in @ {t['entry_price']:.2f}  "
                f"(open - target {t['target_price']:.2f})"
            )

    if not summary["trades"]:
        out.append("- No entries today (gates held all session)")

    out.append("")
    out.append(
        f"Cycles: {summary['cycles']} · Signals: {summary['enters']} · "
        f"Stand-asides: {summary['stand_asides']}"
    )
    out.append(
        f"Realised P&L: **Rs. {summary['realised_pnl']:+.2f}** · "
        f"{summary['wins']}W/{summary['losses']}L"
    )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Summarise one session's decisions and trades.",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Trading date YYYY-MM-DD (default: today PKT).",
    )
    parser.add_argument(
        "--markdown", action="store_true",
        help="Print the compact chat format instead of the full report.",
    )
    args = parser.parse_args(argv)

    if args.date:
        trading_date = args.date
    else:
        trading_date = sessions.trading_date(
            datetime.now(timezone.utc)
        ).isoformat()

    summary = build_summary(trading_date)

    if args.markdown:
        print(render_markdown(summary))
    else:
        print(render_text(summary))

    # Always persist the day's summary alongside the logs.
    out_path = paths.LOGS_DIR / f"session_summary_{trading_date}.json"
    out_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
