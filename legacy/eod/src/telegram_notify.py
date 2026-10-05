"""Telegram backup channel for Sentinel-EOD (v2.0.1).

The GitHub-issue email path dies whenever the Actions slots that carry
it are dropped or delayed (2026-09-17: the owner got no 15:20 pick at
all). Telegram is the second, independent pipe:

  * enabled only when BOTH secrets exist: TELEGRAM_BOT_TOKEN and
    TELEGRAM_CHAT_ID (repo Settings -> Secrets -> Actions);
  * a silent no-op without them - nothing else changes;
  * never fatal, never blocks the picks.
"""
from __future__ import annotations

import os

import requests


def _config() -> tuple[str, str] | None:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    if token and chat_id:
        return token, chat_id
    return None


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send(message: str) -> bool:
    """Post one message. False (silently) when unconfigured or failed.

    v2.0.3: RETRIES. 2026-09-18 verification caught real ReadTimeouts
    to api.telegram.org on this route - a single attempt silently
    drops the backup exactly when it is needed. 3 attempts, short
    backoff; never fatal, never blocks the picks.
    """
    import time

    cfg = _config()
    if cfg is None:
        return False
    token, chat_id = cfg
    for attempt in range(3):
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"},
                timeout=15,
            )
            if resp.ok:
                _send_whatsapp(_plain(message))
                return True
        except Exception:  # noqa: BLE001 - backup channel, never fatal
            pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return False


# ---------------------------------------------------------------------------
# WhatsApp (v2.5.0, owner's order 2026-09-27) - CallMeBot as a SECOND
# backup channel, riding every send() this module already makes, so the
# picks, outcomes and ops alerts land on the owner's WhatsApp too.
# The API is one GET to the free personal-use relay:
#   https://api.callmebot.com/whatsapp.php?phone=..&text=..&apikey=..
#   * phone-optional: no CALLMEBOT_PHONE + CALLMEBOT_APIKEY -> silently
#     disabled, like Telegram;
#   * never fatal, never blocks the picks;
#   * plain text only (the free relay renders no HTML): tags stripped,
#     asterisks kept for WhatsApp bold.
# Secrets (owner sets via repo Settings -> Secrets -> Actions):
#   CALLMEBOT_PHONE   - the owner's number with country code, e.g. +923xx
#   CALLMEBOT_APIKEY  - the key the bot texted back at activation
# ---------------------------------------------------------------------------


def _whatsapp_config() -> tuple[str, str] | None:
    phone = (os.environ.get("CALLMEBOT_PHONE") or "").strip()
    apikey = (os.environ.get("CALLMEBOT_APIKEY") or "").strip()
    if phone and apikey:
        return phone, apikey
    return None


def _plain(text: str) -> str:
    """HTML to plain text: the free CallMeBot relay renders no HTML."""
    for tag in ("<b>", "</b>", "<i>", "</i>"):
        text = text.replace(tag, "")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text


def _send_whatsapp(message: str) -> bool:
    """Text one message to the owner's WhatsApp via CallMeBot.

    False when not configured. 3 attempts with backoff, mirroring the
    Telegram path; any failure is swallowed - never fatal.
    """
    import time

    import requests

    cfg = _whatsapp_config()
    if cfg is None:
        return False
    phone, apikey = cfg
    for attempt in range(3):
        try:
            resp = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": phone, "text": message, "apikey": apikey},
                timeout=15,
            )
            if resp.ok:
                return True
        except Exception:  # noqa: BLE001 - backup channel, never fatal
            pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return False


def build_pick_text(
    today: str,
    picks: list[dict],
    market_regime: float | None = None,
) -> str:
    """Compose the evening pick card.

    v2.2.4 wording (owner's order, 2026-09-19): the trade happens on
    the NEXT MARKET DAY - never "tomorrow" (a Friday's tomorrow is a
    closed Saturday) and never a concrete day name (the bot cannot
    know PSX public holidays, so "(Monday)" could be a lie).
    """
    lines = [
        f"🌙 <b>SENTINELS OF REHAN | Sentinel-EOD - picks for {today}</b>",
        "Buy at/near the close. Next market day: sell at +2.0%, stop -1.0%, "
        "force-close 11:30 PKT.",
    ]
    if any(p.get("degraded") for p in picks):
        lines.insert(
            1,
            "⚠ DEGRADED MODE - final-hour evidence unavailable; day-change "
            "shape substituted. Weaker evidence, treat sizes accordingly.",
        )
    if market_regime is not None:
        lines.insert(2, f"Market at analysis: KSE-100 {market_regime:+.2f}%")
    lines.append("")
    for i, p in enumerate(picks, 1):
        flag = f"\n   {_escape(p['streak_flag'])}" if p.get("streak_flag") else ""
        ev = (                f"\n   last-hr {p['late_momentum_pct']:+.2f}%"
            + (f" | vpvr {p['vpvr']:.2f}" if p.get("vpvr") is not None else "")
            + (f" | book {p['book_pressure']:.2f}" if p.get("book_pressure") is not None else "")
            + (f" | tape {p['aggression']:.2f}" if p.get("aggression") is not None else "")
            + (f" | streak {p['multi_day']:.2f}" if p.get("multi_day") is not None else "")
            + (
                f" | earnings EPS {p['fresh_results']['eps']:+.2f}"
                if p.get("fresh_results")
                else ""
            )
            + (
                f" | div-runway {p['dividend_runway']} sess"
                if p.get("dividend_runway") is not None
                else ""
            )
            + (
                f" | locks {p['lock_days']}x, green run {p['green_streak']}d"
                if p.get("lock_days") is not None
                else ""
            )
        )
        lines.append(
            f"{i}. <b>{_escape(p['symbol'])}</b> - entry ~{p['entry_price']:.2f} "
            f"(score {p['score']:.3f}){ev}{flag}"
        )
    return "\n".join(lines)


def send_pick(
    today: str,
    picks: list[dict],
    market_regime: float | None = None,
) -> bool:
    """The evening pick card - buy at the close."""
    if not picks or _config() is None:
        return False
    return send(build_pick_text(today, picks, market_regime))


def send_outcomes(today: str, outcomes: list[dict]) -> bool:
    """The morning outcome card - what each pick did."""
    if not outcomes or _config() is None:
        return False
    lines = [f"🌤 <b>SENTINELS OF REHAN | Sentinel-EOD - morning outcomes ({today})</b>", ""]
    for o in outcomes:
        lines.append(
            f"{_escape(o['symbol'])}: {o['outcome']} at {o['exit_price']:.2f} "
            f"({o['net_return_pct']:+.2f}% net)"
        )
    return send("\n".join(lines))
