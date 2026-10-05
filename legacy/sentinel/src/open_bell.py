"""
The Sentinel - the open bell (v3.1.0).

WHY: the owner should learn that the session started from the bot
itself, not from silence. The 2026-09-24 morning showed the failure
mode: GitHub's cron swallowed the 09:10 report and the owner sat
wondering whether the machine was alive while it stood aside all
session. One short card per trading leg - "market is OPEN, I am
watching" - closes that gap on every normal day and makes an
abnormally quiet morning instantly legible (no card = no healthy pass
since the open = the cadence is down; the seatbelt alarm layer owns
that case).

LAW: the card says the bot is ALIVE, never that the market is good.
It carries no signal content, so it can never be confused with the
one call per day. Delivery is Telegram-direct (the same channel as
the feed alert); the dedup state lives in data/open_bell.json and is
keyed by (trading date, leg index), so Friday's two legs each get
their own card and a retried pass never double-sends. State is only
recorded after a confirmed send: a failed send is retried by the next
pass of the same leg.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psx_core.paths as paths
import psx_core.sessions as sessions

STATE_FILE = paths.DATA_DIR / "open_bell.json"
BOOK_FILE = paths.DATA_DIR / "portfolio.json"
CONFIG_FILE = paths.PROJECT_ROOT / "config.json"

# Keep a week of session keys; the file can never grow unbounded.
_KEEP_DAYS = 7


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict, today: date) -> None:
    cutoff = (today - timedelta(days=_KEEP_DAYS)).isoformat()
    pruned = {day: legs for day, legs in state.items() if day >= cutoff and "-" in day}
    pruned[today.isoformat()] = sorted(set(pruned.get(today.isoformat(), [])))
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(pruned, indent=1), encoding="utf-8")


def _book_line() -> str:
    """One line about the book. Reads only; a bad file is not fatal."""
    try:
        book = json.loads(BOOK_FILE.read_text(encoding="utf-8"))
        open_n = sum(
            1 for p in book if isinstance(p, dict) and p.get("status") == "OPEN"
        )
        if open_n:
            return f"Book: {open_n} open position(s) - exits are guarded."
        return "Book: flat, ready for the first candidate."
    except (OSError, json.JSONDecodeError):
        return "Book: state unreadable (exits still guarded)."


def _kill_switch_off() -> bool:
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return cfg.get("open_bell_enabled", True) is False
    except (OSError, json.JSONDecodeError):
        return False


def announce_open(now: datetime | None = None) -> tuple[bool, str]:
    """Send the open-bell card once per trading leg.

    Returns (sent, note) for the caller's log. Never raises: a bell
    failure must not kill the pass's real duties. Skips cleanly on
    weekends, PSX holidays, closed hours, when the kill-switch
    (open_bell_enabled) is off, and when this leg already got its card.
    """
    try:
        moment = now if now is not None else datetime.now(timezone.utc)
        local = sessions.to_pkt(moment)
        today = local.date()

        if _kill_switch_off():
            return False, "kill-switch off (open_bell_enabled=false) - silent"
        if not sessions.is_trading_day(today):
            return False, f"no session on {today.isoformat()} - silent"
        leg = sessions.current_leg(moment)
        if leg is None:
            return False, "market not open right now - silent"

        state = _load_state()
        today_key = today.isoformat()
        if leg.index in state.get(today_key, []):
            return False, f"leg {leg.index} already announced - silent"

        import notify

        msg = (
            "🛰️ <b>SENTINELS OF REHAN | The Sentinel is online, market is OPEN.</b>\n"
            f"Leg {leg.index} of {today_key}, "
            f"{leg.start.strftime('%H:%M')}-{leg.end.strftime('%H:%M')} PKT.\n"
            f"{_book_line()}\n"
            "Watching the full KMIALL universe every pass. "
            "One call/day max - TP +2%, SL -1%."
        )
        if not notify.send_telegram(msg):
            return False, "telegram refused - will retry next pass"

        state.setdefault(today_key, []).append(leg.index)
        _save_state(state, today)
        return True, f"sent (leg {leg.index}, {today_key})"
    except Exception as exc:  # noqa: BLE001 - the bell must never kill a pass
        return False, f"failed (non-fatal): {exc}"
