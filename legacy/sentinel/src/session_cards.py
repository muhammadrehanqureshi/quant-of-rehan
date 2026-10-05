"""
Session lifecycle cards (v3.4.0): the owner's standing order.

  * MARKET OPEN  -> one card on GitHub (primary, the signals issue =
    an email) AND Telegram (backup) when the session starts.
  * MARKET CLOSED -> one card on both channels when the session ends,
    including the sentinel's day summary: wins, losses, realised P&L,
    and a sleep note until the next market day.
  * Every time on every card is PKT. Mon-Thu and Friday wording differ
    (Friday has two legs and the weekend follows).

Design: state file data/session_cards.json keyed by
(date, kind, leg/phase); state recorded only after a confirmed send on
at least one channel, so a dead pass retries without double-sending.
Never fatal - a card failure must not kill the pass that delivers it.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import psx_core.sessions as sessions

CARDS_PATH = Path("data") / "session_cards.json"


def _load_state() -> dict:
    try:
        return json.loads(CARDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    CARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARDS_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def _kill_switch_off() -> bool:
    try:
        cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        return not bool(cfg.get("session_cards_enabled", True))
    except Exception:  # noqa: BLE001 - default is ON
        return False


def _already_sent(state: dict, key: str) -> bool:
    return key in state.get("sent", [])


def _mark_sent(state: dict, key: str) -> None:
    state.setdefault("sent", []).append(key)
    state["sent"] = state["sent"][-400:]
    _save_state(state)


def _github_comment(body: str) -> bool:
    """Primary channel: a comment on the signals issue = owner email."""
    import os

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo or not token:
        return False
    try:
        import notify

        issue_no = notify.ensure_issue(repo, token)
        if issue_no is None:
            return False
        owner = repo.split("/")[0] if "/" in repo else ""
        mention = f"@{owner} " if owner else ""
        status, _ = notify._api(
            f"https://api.github.com/repos/{repo}/issues/{issue_no}/comments",
            token,
            {"body": mention + body},
        )
        return status in (200, 201)
    except Exception:  # noqa: BLE001 - card must never kill a pass
        return False


def _telegram(body: str) -> bool:
    try:
        import notify

        return notify.send_telegram(body)
    except Exception:  # noqa: BLE001
        return False


def _send_both(body: str) -> bool:
    """GitHub primary first; Telegram backup rides along and covers
    the failure case. True once at least one channel confirms."""
    gh = _github_comment(body)
    tg = _telegram(body)
    return gh or tg


def _next_day_line(today: date) -> str:
    nxt = sessions.next_trading_day(today)
    return f"Next market day: <b>{nxt.strftime('%a %d %b %Y')}</b>."


def _legs_line(today: date) -> str:
    legs = sessions.legs_for(today)
    spans = ", ".join(
        f"leg {leg.index} {leg.start.strftime('%H:%M')}-"
        f"{leg.end.strftime('%H:%M')}"
        for leg in legs
    )
    return spans or "closed"


def _summary_block(trading_date: str) -> str:
    """The sentinel's day summary: wins/losses/realised P&L."""
    try:
        import session_summary

        s = session_summary.build_summary(trading_date)
    except Exception:  # noqa: BLE001 - a summary failure is cosmetic
        return ""
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    pnl = s.get("realised_pnl", 0.0)
    trades = s.get("trades") or []
    total = wins + losses
    if total == 0:
        return (
            "\n<b>Day summary:</b> no trades today - the engine stood "
            "aside all session. Book untouched."
        )
    arrow = "\U0001F4C8" if pnl >= 0 else "\U0001F4C9"
    lines = [
        f"\n<b>Day summary:</b> {total} trade(s) - {wins} win(s), "
        f"{losses} loss(es), realised P&L {pnl:+.2f} PKT {arrow}."
    ]
    for t in trades[:5]:
        sym = t.get("symbol", "?")
        pct = t.get("pnl_pct")
        if pct is None:
            continue
        mark = "+" if pct >= 0 else "-"
        lines.append(f"  {mark} {sym} {pct:+.2f}%")
    return "\n".join(lines)


def announce_open(now: datetime | None = None) -> tuple[bool, str]:
    """Market-open card, once per trading leg. Never raises."""
    try:
        if _kill_switch_off():
            return False, "kill-switch off (session_cards_enabled=false)"
        moment = now if now is not None else datetime.now(timezone.utc)
        local = sessions.to_pkt(moment)
        today = local.date()
        if not sessions.is_trading_day(today):
            return False, f"no session on {today.isoformat()} - silent"
        leg = sessions.current_leg(moment)
        if leg is None:
            return False, "market not open right now - silent"

        key = f"open:{today.isoformat()}:{leg.index}"
        state = _load_state()
        if _already_sent(state, key):
            return False, f"{key} already sent - silent"

        is_friday = today.weekday() == 4
        flavor = (
            "Friday session - two legs, weekend follows the close."
            if is_friday
            else "Mon-Thu full session."
        )
        tail = _next_day_line(today) if is_friday else ""
        body = (
            "<b>SENTINELS OF REHAN | MARKET OPEN - The Sentinel is running.</b>\n\n"
            f"Date: {today.strftime('%a %d %b %Y')}\n"
            f"Session: {_legs_line(today)} PKT\n"
            f"Phase: leg {leg.index} of "
            f"{len(sessions.legs_for(today))} ({flavor})\n"
            f"Local time: {local.strftime('%H:%M')} PKT\n\n"
            "Watching the full KMIALL universe every pass. "
            "One call/day max - TP +2%, SL -1%.\n"
            f"{tail}"
        )
        if not _send_both(body):
            return False, f"{key}: both channels refused - will retry"
        _mark_sent(state, key)
        return True, f"sent ({key})"
    except Exception as exc:  # noqa: BLE001
        return False, f"failed (non-fatal): {exc}"


def announce_close(now: datetime | None = None) -> tuple[bool, str]:
    """Market-closed card with the day summary, once per day. The
    close-out workflow calls this after the book is closed. Never
    raises; silent on non-trading days."""
    try:
        if _kill_switch_off():
            return False, "kill-switch off (session_cards_enabled=false)"
        moment = now if now is not None else datetime.now(timezone.utc)
        local = sessions.to_pkt(moment)
        today = local.date()
        if not sessions.is_trading_day(today):
            return False, f"no session on {today.isoformat()} - silent"
        # The card says "market closed" - it must never fire while any
        # leg is open OR while the day still has a leg coming (the
        # 2026-09-25 12:49 incident on the EOD side: Friday's between-
        # legs gap passed the old current_leg() guard). Gate: the WHOLE
        # session is over.
        if not sessions.session_over_for(moment):
            return False, "session not fully over - close card waits"

        key = f"close:{today.isoformat()}"
        state = _load_state()
        if _already_sent(state, key):
            return False, f"{key} already sent - silent"

        # v4.4.4 (2026-10-03): the MARKET CLOSED card must report the
        # SCHEDULED market close time for the day, not the close-out script's
        # run time. GitHub's cron can dispatch the close-out hours late (the
        # seatbelt's own Guard P/E documents 6.5-hour-late cards at 22:09 PKT
        # on 2026-10-01) - when that happens "Closed at: {now}"` would tell
        # the owner the market closed hours late, which is false. The market
        # close is a fixed schedule fact: the last leg's end time in PKT.
        # Mondays-Thursdays close 15:30 PKT; Fridays close 16:30 PKT (leg 2).
        last_leg = sessions.legs_for(today)[-1]
        market_closed_at = datetime.combine(
            today, last_leg.end, tzinfo=sessions.PKT
        ).astimezone(timezone.utc)
        local_close = sessions.to_pkt(market_closed_at)
        is_friday = today.weekday() == 4
        sleep_line = (
            "Both bots are sleeping until Monday's open (weekend)."
            if is_friday
            else "Both bots are sleeping until the next market day's open."
        )
        body = (
            "<b>SENTINELS OF REHAN | MARKET CLOSED - session over.</b>\n\n"
            f"Date: {today.strftime('%a %d %b %Y')}\n"
            f"Session: {_legs_line(today)} PKT\n"
            f"Closed at: {local_close.strftime('%H:%M')} PKT\n"
            "Next open: "
            f"{sessions.next_trading_day(today).strftime('%a %d %b')}\n"
            + _summary_block(today.isoformat())
            + f"\n\n{sleep_line} Notifications resume at the next market open."
        )
        if not _send_both(body):
            return False, f"{key}: both channels refused - will retry"
        _mark_sent(state, key)
        return True, f"sent ({key})"
    except Exception as exc:  # noqa: BLE001
        return False, f"failed (non-fatal): {exc}"
