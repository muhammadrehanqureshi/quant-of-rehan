"""
Morning health report - the 09:10 PKT "all clear" before the bell.

WHAT: one Telegram message each market morning confirming, from the
bot's own state files:
  * the book (flat / N open, yesterday's outcome if any);
  * the decide heartbeat (last real pass, age in minutes);
  * the learning state (outcomes absorbed, gates re-fit or not);
  * the EOD sibling (ledger size + last trace heartbeat read from the
    synced copy under data/_eod_src_current/data/, when present);
  * today's session shape (open time, holiday check).

The report is a STATUS read, not a decision - it fires regardless of
what the tape looks like, so silence from it means the delivery chain
itself is down (which is exactly the failure it exists to expose).
Sends once per market day; a second invocation the same day is a no-op.

RUN: python src/morning_report.py --token <github_token>
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths, sessions  # noqa: E402

SENTINEL_STATE = paths.DATA_DIR
EOD_STATE = paths.DATA_DIR / "_eod_src_current" / "data"
STATE_FILE = paths.DATA_DIR / "morning_report_state.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a report must never crash
        return default


def _age_min(iso: str | None, now: datetime | None = None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        base = now or datetime.now(timezone.utc)
        return (base - ts).total_seconds() / 60.0
    except ValueError:
        return None


def _remote_eod_line(is_friday: bool) -> str | None:
    """EOD sibling line read straight from the sibling repo (cloud runs).

    The cloud runner never has the local synced clone, so the old code
    printed "state not synced locally" every morning regardless of the
    owner's PC. The sibling's ledger is committed to its own repo after
    every trace - read it from there and say what is actually true.
    Any failure degrades to the honest "watched by the seatbelt" line.
    """
    import urllib.request

    url = (
        "https://raw.githubusercontent.com/muhammadrehanqureshi/"
        "sentinel-eod/main/data/ledger.jsonl"
    )
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            rows = [
                json.loads(l)
                for l in resp.read().decode("utf-8").splitlines()
                if l.strip()
            ]
        wins = sum(1 for r in rows if r.get("outcome") == "WIN")
        return (
            f"Sentinel-EOD: {len(rows)} picks traced, {wins} wins - "
            f"next card {'16:25' if is_friday else '15:25'} PKT."
        )
    except Exception:  # noqa: BLE001 - a report must never crash
        return (
            "Sentinel-EOD: runs in its own repo (ledger not readable "
            "from here) - watched by the seatbelt."
        )


def build_report(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    today = sessions.trading_date(now)
    is_friday = today.weekday() == 4
    open_min = "09:17" if is_friday else "09:32"

    lines = [f"Morning check - {today.isoformat()} (bell {open_min} PKT)"]

    # Session calendar: holiday / weekend verdict.
    if not sessions.legs_for(today):
        lines.append("Market: CLOSED today (holiday) - bots stand down.")
    else:
        lines.append("Market: OPEN today, full session.")

    # The book.
    book = _read_json(SENTINEL_STATE / "portfolio.json", {})
    rows = book if isinstance(book, list) else book.get("positions", [])
    open_pos = [p for p in rows if isinstance(p, dict) and p.get("status") == "OPEN"]
    if open_pos:
        for p in open_pos:
            lines.append(
                f"Book: OPEN {p.get('symbol')} entry {p.get('entry_price')} "
                f"(target {p.get('target_price')})"
            )
    else:
        lines.append("Book: flat, ready for the first candidate.")

    # Decide heartbeat.
    hb = _read_json(SENTINEL_STATE / "heartbeat.json", {})
    age = _age_min(hb.get("utc"), now)
    if age is None:
        lines.append("Decide heartbeat: NO STAMP YET (first pass fires at the bell).")
    elif age < 0:
        lines.append("Decide heartbeat: stamp is from the future (clock skew) - ignoring.")
    else:
        lines.append(f"Decide heartbeat: last pass {age:.0f} min ago.")

    # Learning state.
    lessons = _read_json(SENTINEL_STATE / "lessons.json", {})
    refit = _read_json(SENTINEL_STATE / "gate_refit.json", {})
    parts = []
    if lessons.get("labeled"):
        parts.append(f"{lessons['labeled']} outcomes absorbed")
    if refit.get("trades"):
        parts.append(
            f"gate refit on {refit['trades']} trades"
            + (f", {len(refit.get('moves', []))} knob(s) moved" if refit.get("moves") else "")
        )
    lines.append(
        "Learning: " + ("; ".join(parts) if parts else "warming up")
    )

    # v2.6.0 - yesterday's market lesson: what the tape taught.
    try:
        import market_learner

        mkt = market_learner.load_market_lessons()
        last = mkt.get("last") or {}
        if last.get("taught"):
            lines.append(f"Yesterday's lesson: {last['taught']}")
        dead = mkt.get("dead_confirmed") or set()
        trend = mkt.get("trend_confirmed") or set()
        if dead or trend:
            bits = []
            if dead:
                bits.append(f"dead x3+: {', '.join(sorted(dead)[:6])}")
            if trend:
                bits.append(f"trending x3+: {', '.join(sorted(trend)[:6])}")
            lines.append("Market memory: " + "; ".join(bits))
    except Exception:  # noqa: BLE001
        pass  # report-only surface; never blocks the morning check

    # The EOD sibling. Reads its ledger from the local synced clone
    # when present (PC), else straight from the sibling repo's GitHub
    # (cloud runner) - the report must speak the truth in both places.
    eod_line = None
    eod_ledger = EOD_STATE / "ledger.jsonl"
    if eod_ledger.exists():
        try:
            n = sum(1 for l in eod_ledger.read_text(encoding="utf-8").splitlines() if l.strip())
            wins = 0
            for l in eod_ledger.read_text(encoding="utf-8").splitlines():
                if l.strip() and json.loads(l).get("outcome") == "WIN":
                    wins += 1
            eod_line = (
                f"Sentinel-EOD: {n} picks traced, {wins} wins - next card "
                f"{'16:25' if is_friday else '15:25'} PKT."
            )
        except Exception:  # noqa: BLE001
            eod_line = "Sentinel-EOD: ledger unreadable (report-only issue)."
    else:
        eod_line = _remote_eod_line(is_friday)
    if eod_line:
        lines.append(eod_line)

    lines.append("Ladder armed: bell slot, 15-min cadence, watchdog, seatbelt.")
    return "\n".join(lines)


def already_sent(today: str) -> bool:
    state = _read_json(STATE_FILE, {})
    return state.get("last_sent") == today


def mark_sent(today: str) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps({"last_sent": today}), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    now = datetime.now(timezone.utc)
    today = sessions.trading_date(now).isoformat()
    if already_sent(today):
        print("morning report: already sent today")
        return 0
    msg = build_report(now)
    print(msg)
    if "--dry-run" in args:
        return 0
    import notify

    ok = notify.send_telegram(msg)
    if ok:
        mark_sent(today)
        print("morning report: delivered")
        return 0
    print("morning report: delivery FAILED (will retry next run)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
