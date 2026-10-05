"""
Signal DELIVERY (v0.15.6) - the answer to "how do I GET the calls?"

The cloud passes were writing signals into repo files, but files are
not delivery: the owner does not watch a repo like a phone. This module
turns every BUY and every EXIT into an EMAIL by posting it as a comment
on a GitHub issue. The owner watches the issue once; GitHub's own
notification system then emails every comment - no bot mail server, no
cost, nothing extra to run.

Also maintains SIGNALS.md at the repo root: today's calls, newest
first, readable as a plain web page.

Delivery is at-least-once and idempotent: data/notified.json records
what has been sent; a re-run never re-sends.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

NOTIFIED_PATH = ROOT / "data" / "notified.json"
SIGNALS_PATH = ROOT / "SIGNALS.md"
STATUS_PATH = ROOT / "STATUS.md"
DECISIONS_LOG = ROOT / "logs" / "decisions.jsonl"
PORTFOLIO_PATH = ROOT / "data" / "portfolio.json"

ISSUE_TITLE = "📣 The Sentinel - live signals (watch this issue for email alerts)"

# ---------------------------------------------------------------------------
# Telegram (v2.0.1) - the backup delivery channel.
#
# The GitHub-issue email path depends on the Actions run that generated
# the event ALSO running deliver(); the 2026-09-17 incident (the 20:19
# close-out fired after every pass, so the SNGP exit was never emailed)
# proved a single-channel design is fragile. Telegram is:
#   * token-optional: no TELEGRAM_BOT_TOKEN secret -> silently disabled;
#   * idempotent: the same notified.json ledger dedupes both channels;
#   * never fatal: any Telegram failure is logged and swallowed.
# Secrets (owner sets via repo Settings -> Secrets -> Actions):
#   TELEGRAM_BOT_TOKEN - from @BotFather
#   TELEGRAM_CHAT_ID   - the owner's chat id (from getUpdates/getidsbot)
# ---------------------------------------------------------------------------


def _telegram_config() -> tuple[str, str] | None:
    """(token, chat_id) when both secrets exist, else None."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if token and chat_id:
        return token, chat_id
    return None


def send_telegram(message: str) -> bool:
    """Post one message to the owner's chat. False when not configured.

    v0.18.1: RETRIES. 2026-09-18 verification caught real ReadTimeouts
    to api.telegram.org - one silent drop is one lost backup signal.
    3 attempts, short backoff, still never fatal.
    """
    import time

    cfg = _telegram_config()
    if cfg is None:
        return False
    token, chat_id = cfg
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
    ).encode()
    for attempt in range(3):
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return True
                _print(f"telegram: HTTP {resp.status}")
        except Exception as exc:  # noqa: BLE001 - backup channel, never fatal
            _print(f"telegram: attempt {attempt + 1}/3 failed: {exc}")
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return False


def _telegram_safe(text: str) -> str:
    """Escape HTML-sensitive chars for parse_mode=HTML messages."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_event_telegram(event: dict) -> bool:
    """Deliver one BUY/EXIT event over Telegram. False when disabled."""
    cfg = _telegram_config()
    if cfg is None:
        return False
    kind = "🟢 BUY" if event["kind"] == "BUY" else "🔴 EXIT"
    body = (
        f"{kind} - The Sentinel\n"
        f"{_telegram_safe(format_event(event))}\n"
        f"<i>{_telegram_safe(one_line(event))}</i>"
    )
    ok = send_telegram(body)
    if ok:
        send_event_whatsapp(kind, event)
    return ok


# ---------------------------------------------------------------------------
# WhatsApp (v4.0.2, owner's order 2026-09-27) - CallMeBot as the SECOND
# backup channel, riding the same dedup ledger and delivery moments as
# Telegram. The API is one GET: a free, personal-use relay that texts
# the owner's own WhatsApp from the number he already activated.
#   * phone-optional: no CALLMEBOT_PHONE + CALLMEBOT_APIKEY -> silently
#     disabled, like Telegram;
#   * never fatal: any failure is logged and swallowed;
#   * plain text only: the free relay renders no HTML, so cards go out
#     as clean text (asterisks still bold in WhatsApp).
# Secrets (owner sets via repo Settings -> Secrets -> Actions):
#   CALLMEBOT_PHONE   - the owner's number with country code, e.g. +923xx
#   CALLMEBOT_APIKEY  - the key the bot texted back at activation
# Rate ceiling: CallMeBot's free relay is for personal use, and the
# bot emits at most ~8 cards a day, far below any sane cap.
# ---------------------------------------------------------------------------


def _whatsapp_config() -> tuple[str, str] | None:
    """(phone, apikey) when both secrets exist, else None."""
    phone = os.environ.get("CALLMEBOT_PHONE", "").strip()
    apikey = os.environ.get("CALLMEBOT_APIKEY", "").strip()
    if phone and apikey:
        return phone, apikey
    return None


def send_whatsapp(message: str) -> bool:
    """Text one message to the owner's WhatsApp via CallMeBot.

    False when not configured. 3 attempts with backoff, mirroring the
    Telegram path - one silent drop is one lost backup signal.
    """
    import time
    import urllib.parse

    cfg = _whatsapp_config()
    if cfg is None:
        return False
    phone, apikey = cfg
    url = (
        "https://api.callmebot.com/whatsapp.php?phone="
        + urllib.parse.quote(phone)
        + "&text="
        + urllib.parse.quote(message, safe="")
        + "&apikey="
        + urllib.parse.quote(apikey)
    )
    for attempt in range(3):
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return True
                _print(f"whatsapp: HTTP {resp.status}")
        except Exception as exc:  # noqa: BLE001 - backup channel, never fatal
            _print(f"whatsapp: attempt {attempt + 1}/3 failed: {exc}")
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return False


def send_event_whatsapp(kind: str, event: dict) -> bool:
    """Deliver one BUY/EXIT event over WhatsApp. False when disabled."""
    cfg = _whatsapp_config()
    if cfg is None:
        return False
    body = (
        f"{kind} - The Sentinel (WhatsApp)\n"
        f"{format_event(event)}\n"
        f"{one_line(event)}"
    )
    return send_whatsapp(body)


def _print(*args: object) -> None:
    print(*args, flush=True)


def enable_utf8_stdout() -> None:
    """Windows consoles default to cp1252; our output uses arrows/emoji."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - best effort, never fatal
        pass


# --------------------------------------------------------------------------
# Event extraction
# --------------------------------------------------------------------------

def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


# Every user-facing timestamp is Karachi time (owner rule, 2026-09-17):
# the owner reads PKT, the market lives in PKT, UTC stays internal.
PKT = ZoneInfo("Asia/Karachi")


def _fmt_pkt(dt: datetime) -> str:
    """Render any aware datetime as 'YYYY-MM-DD HH:MM' in PKT."""
    return dt.astimezone(PKT).strftime("%Y-%m-%d %H:%M")


def _open_book_keys() -> set[str]:
    """(symbol, entry_price) pairs the book legitimately vouches for.

    v3.0.0: ONE vouch only - a position with status OPEN right now.
    The earlier "OPEN at any point today" extension vouched Sep-23's
    zombie: a close-out had already flipped the row to CLOSED, but a
    PC-side pass still saw the pre-close book and re-delivered the
    dead BUY (today-only stopped yesterday's rows, not same-day
    resurrection). An entry made today whose row is somehow not yet
    OPEN is re-deliverable only through the freshest possible truth:
    the GitHub book. It is NOT vouched by a local copy.
    """
    try:
        book = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    keys = set()
    for pos in book if isinstance(book, list) else []:
        if str(pos.get("status", "")).upper() != "OPEN":
            continue
        try:
            keys.add((str(pos.get("symbol")), round(float(pos.get("entry_price")), 4)))
        except (TypeError, ValueError):
            continue
    return keys


def _github_book_keys(repo: str, token: str) -> tuple[set[str], bool]:
    """((symbol, entry_price) pairs OPEN in the committed GitHub book, reachable?).

    The repo's portfolio.json is the bot's source of truth: every real
    pass commits its book within a minute. A local copy (OneDrive sync
    lag, a half-finished close) can be minutes stale in EITHER
    direction, so delivery-side vouches are answered from the repo
    itself when it answers at all. Unreadable = (empty, False) - the
    caller falls back to the local copy, never to silence.
    """
    import base64

    if not (repo and token):
        return set(), False
    url = (
        f"https://api.github.com/repos/{repo}/contents/"
        "data/portfolio.json?ref=master"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.load(resp)
        book = json.loads(base64.b64decode(payload["content"]))
    except Exception:  # noqa: BLE001 - never fatal, never a vouch
        return set(), False
    keys = set()
    for pos in book if isinstance(book, list) else []:
        if str(pos.get("status", "")).upper() != "OPEN":
            continue
        try:
            keys.add((str(pos.get("symbol")), round(float(pos.get("entry_price")), 4)))
        except (TypeError, ValueError):
            continue
    return keys, True


def collect_events(
    repo: str = "", token: str = ""
) -> list[dict]:
    """All ENTER decisions + all closed positions, as deliverable events.

    v3.0.0 zombie law, three independent seals on every BUY:
      1. TODAY ONLY - a BUY row from any earlier trading day is dead,
         whatever any book says (the Sep-23 09:19 UTC card carried the
         Sep-15 entry while both books showed it CLOSED).
      2. LIVE-OPEN VOUCH - the position must be status OPEN right now
         in the book this delivery trusts.
      3. STALENESS SEAL - the existing 20-minute age cap stays.
    """
    events: list[dict] = []
    repo = repo or os.environ.get("GITHUB_REPOSITORY", "")
    token = token or os.environ.get("GITHUB_TOKEN", "")
    open_keys = _open_book_keys()
    gh_keys, gh_ok = _github_book_keys(repo, token)
    # The committed GitHub book outranks the local copy whenever it
    # answers: it is what every other pass sees. The local file only
    # speaks when GitHub is unreachable (offline fallback).
    vouch_keys = gh_keys if gh_ok else open_keys
    today = datetime.now(timezone.utc).astimezone(PKT).date().isoformat()

    if DECISIONS_LOG.exists():
        for line in DECISIONS_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("action") == "ENTER":
                # A BUY card without a price and a target is garbage by
                # construction (the Sep-21 zombie: target 0.0, conviction
                # 0.000, quantity 0). Such a row must never reach the
                # owner's phone - skip it here, at the source.
                try:
                    ok_price = float(row.get("price") or 0) > 0
                    ok_tgt = float(row.get("profit_target_price") or 0) > 0
                except (TypeError, ValueError):
                    ok_price = ok_tgt = False
                if not (ok_price and ok_tgt):
                    continue
                # The book-truth gate (Sep-22 zombie kill): a BUY event
                # exists ONLY if the book still holds this position OPEN
                # at this entry price. Every real call opens a book row
                # in the same pass; a row without one is a relic of a
                # crashed/rolled-back write and must never reach the
                # owner's phone.
                try:
                    entry_key = (
                        str(row.get("symbol")),
                        round(float(row.get("price")), 4),
                    )
                except (TypeError, ValueError):
                    continue
                # Seal 1: today only. Yesterday's rows never vouch.
                row_ts = _parse_ts(row.get("timestamp") or row.get("at"))
                if row_ts.astimezone(PKT).date().isoformat() != today:
                    continue
                # Seal 2: the trusted book must hold the position
                # OPEN right now (GitHub-committed truth first, local
                # copy only as the offline fallback).
                if entry_key not in vouch_keys:
                    continue
                events.append(
                    {
                        "key": f"buy:{row.get('timestamp') or row.get('at')}:{row.get('symbol')}",
                        "kind": "BUY",
                        "ts": row_ts,
                        "fields": row,
                    }
                )

    if PORTFOLIO_PATH.exists():
        try:
            book = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            book = []
        for pos in book:
            if pos.get("status") == "CLOSED" and pos.get("exit_date"):
                events.append(
                    {
                        "key": (
                            f"exit:{pos.get('symbol')}:"
                            f"{pos.get('exit_date')}:{pos.get('exit_ts') or pos.get('exit_price')}"
                        ),
                        "kind": "EXIT",
                        "ts": _parse_ts(pos.get("exit_ts")),
                        "fields": pos,
                    }
                )

    events.sort(key=lambda e: e["ts"])
    return events


# --------------------------------------------------------------------------
# Dedup ledger
# --------------------------------------------------------------------------

def _load_notified() -> dict:
    if NOTIFIED_PATH.exists():
        try:
            return json.loads(NOTIFIED_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_notified(state: dict) -> None:
    NOTIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFIED_PATH.write_text(
        json.dumps(state, indent=1, sort_keys=True), encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Signal formatting
# --------------------------------------------------------------------------

def _fmt_buy(fields: dict) -> str:
    sym = fields.get("symbol", "?")
    price = fields.get("price", 0.0)
    tgt = fields.get("profit_target_price", 0.0)
    pct = fields.get("profit_target_pct", 0.0)
    qty = fields.get("quantity", 0)
    score = fields.get("score", 0.0)
    # Owner's law (2026-09-25): every time on every card is PKT. The
    # Sep-25 04:46 UTC card forced this - parse the stored UTC stamp
    # and render Pakistan time, never raw UTC.
    raw_when = str(fields.get("timestamp") or fields.get("at") or "")
    when = _fmt_pkt(_parse_ts(raw_when)) if raw_when else ""
    return (
        f"**🟢 SENTINELS OF REHAN | BUY {sym}**\n\n"
        f"| | |\n|---|---|\n"
        f"| Entry | **{price}** |\n"
        f"| Target | **{tgt}** (+{pct:.1f}% - session exit) |\n"
        # ONE stop loss - the owner's universal law: -1.0%, nothing
        # else. The old line advertised a -1.5% trailing stop on top of
        # the hard stop (a v0.x relic); the trailing machinery in
        # portfolio.py arms at +1% gain and trails at 0.5% - it never
        # widens the stop - but the CARD must not show two numbers.
        f"| Stop | **-1.0% hard** (trails up after +1% gain) |\n"
        f"| Quantity ref | {qty} |\n"
        f"| Conviction | {score:.3f} |\n"
        f"| Time | {when} PKT |\n\n"
        f"Trade manually in your broker terminal. This is a signal, not an order."
    )


def _fmt_exit(fields: dict) -> str:
    sym = fields.get("symbol", "?")
    entry = fields.get("entry_price", 0.0)
    px = fields.get("exit_price", 0.0)
    pnl_pct = fields.get("pnl_pct", 0.0)
    reason = str(fields.get("exit_reason", ""))
    # exit_date is a PKT calendar date already (sessions.trading_date);
    # prefer the precise exit_ts when present, rendered in PKT.
    when = str(fields.get("exit_date") or "")
    exit_ts = str(fields.get("exit_ts") or "")
    if exit_ts:
        when = _fmt_pkt(_parse_ts(exit_ts))
    arrow = "✅" if (pnl_pct or 0.0) > 0 else "🔻"
    return (
        f"**{arrow} SENTINELS OF REHAN | EXIT {sym} @ {px}**\n\n"
        f"| | |\n|---|---|\n"
        f"| Entry | {entry} |\n"
        f"| Exit | **{px}** |\n"
        f"| Result | **{pnl_pct:+.2f}%** |\n"
        f"| Reason | {reason} |\n"
        f"| Time | {when} PKT |\n\n"
        f"Close this position in your broker terminal if still held."
    )


def format_event(event: dict) -> str:
    if event["kind"] == "BUY":
        return _fmt_buy(event["fields"])
    return _fmt_exit(event["fields"])


def one_line(event: dict) -> str:
    f = event["fields"]
    if event["kind"] == "BUY":
        return (
            f"BUY {f.get('symbol')} @ {f.get('price')} → target "
            f"{f.get('profit_target_price')} (+{f.get('profit_target_pct', 0):.1f}%)"
        )
    return (
        f"EXIT {f.get('symbol')} @ {f.get('exit_price')} "
        f"({f.get('pnl_pct', 0):+.2f}%)"
    )


# --------------------------------------------------------------------------
# SIGNALS.md
# --------------------------------------------------------------------------

def _flow_headline() -> str | None:
    """
    Rule 12c (v0.16.2): one-line pump/dump read for SIGNALS.md from the
    latest stored session in data/foreign_flow_history.jsonl. NCCPL
    publishes after the close, so the last row is always the freshest
    flow that exists. Returns None (silently) when unavailable - a
    rendering helper must never break signal delivery.
    """
    try:
        history_path = ROOT / "data" / "foreign_flow_history.jsonl"
        rows = [
            json.loads(line)
            for line in history_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not rows:
            return None
        latest = rows[-1]
        by_inv = latest.get("byInvestor") or {}
        nets = [
            (name, float(v.get("net") or 0.0))
            for name, v in by_inv.items()
            if isinstance(v, dict)
        ]
        if len(nets) < 2:
            return None
        buyer, b_net = max(nets, key=lambda nv: nv[1])
        seller, s_net = min(nets, key=lambda nv: nv[1])

        def _fmt(x: float) -> str:
            return f"{x / 1e6:+.1f}M"

        # "...dumping WHAT": the top sector per leader from the stored
        # investor x sector matrix (absent -> no clause, never fatal).
        matrix = latest.get("matrix") or {}

        def _top_sector(investor: str, want_max: bool) -> str:
            cells = [
                (sector, float(net))
                for sector, net in (matrix.get(investor) or {}).items()
                if isinstance(net, (int, float))
            ]
            if not cells:
                return ""
            sector, _ = (
                max(cells, key=lambda nv: nv[1])
                if want_max
                else min(cells, key=lambda nv: nv[1])
            )
            return f" in {sector}"

        return (
            f"**Who's pumping / dumping** (last completed session "
            f"{latest.get('date', '?')}): 🐂 {buyer} "
            f"{_fmt(b_net)}{_top_sector(buyer, True)} · 🐻 "
            f"{seller} {_fmt(s_net)}{_top_sector(seller, False)}"
        )
    except Exception:  # noqa: BLE001 - display only, never fatal
        return None


def render_status_md(now: datetime | None = None) -> str:
    """
    STATUS.md (v0.16.4): the one-glance answer to "is the bot working?"
    Regenerated on every pass, committed to the repo, readable like any
    web page: liveness (heartbeat age), the latest decision and why,
    the open book, and the ledger's running win rate. Every read is
    defensive - a missing file becomes a dash, never an exception.
    """
    now = now or datetime.now(timezone.utc)
    lines = ["# 🛰️ The Sentinel - status", ""]

    # Liveness: heartbeat age (stamped only by a real pass).
    hb_age = None
    try:
        rec = json.loads(
            (ROOT / "data" / "heartbeat.json").read_text(encoding="utf-8")
        )
        stamped = datetime.fromisoformat(str(rec["utc"]))
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        hb_age = (now - stamped).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        pass
    if hb_age is None:
        lines += ["**Liveness:** ⚠️ no heartbeat recorded yet", ""]
    elif hb_age <= 20:
        lines += [
            f"**Liveness:** ✅ alive - last real pass {hb_age:.0f} min ago",
            "",
        ]
    else:
        lines += [
            f"**Liveness:** 🔴 stale - last real pass {hb_age:.0f} min "
            "ago (the keeper should rescue within minutes)",
            "",
        ]

    # Latest decision.
    try:
        decs = [
            json.loads(line)
            for line in (ROOT / "logs" / "decisions.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        latest = decs[-1] if decs else None
        if latest:
            try:
                ts_dt = datetime.fromisoformat(
                    str(latest.get("timestamp", ""))
                )
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                ts = _fmt_pkt(ts_dt)
            except ValueError:
                ts = str(latest.get("timestamp", ""))[:16].replace("T", " ")
            lines += [
                "**Latest decision:** "
                f"`{latest.get('action', '?')}` at {ts} PKT - "
                f"{str(latest.get('reason', ''))[:160]}",
                "",
            ]
    except Exception:  # noqa: BLE001
        pass

    # The open book.
    try:
        book = json.loads(
            (ROOT / "data" / "portfolio.json").read_text(encoding="utf-8")
        )
        if isinstance(book, dict):
            book = book.get("positions") or book.get("trades") or []
        open_pos = [
            p for p in book if isinstance(p, dict)
            and str(p.get("status", "")).upper() == "OPEN"
        ]
        if open_pos:
            lines += ["**Open trades:**", "", "| Symbol | Entry | Target | Stop |", "|---|---|---|---|"]
            for p in open_pos:
                lines.append(
                    f"| {p.get('symbol', '?')} | {p.get('entry_price', '?')} "
                    f"| {p.get('target_price', '-')} "
                    f"| {p.get('trailing_stop_price', '-')} |"
                )
            lines.append("")
        else:
            lines += ["**Open trades:** none - book is flat", ""]
    except Exception:  # noqa: BLE001
        pass

    # Ledger running stats.
    try:
        book = json.loads(
            (ROOT / "data" / "portfolio.json").read_text(encoding="utf-8")
        )
        if isinstance(book, dict):
            book = book.get("positions") or book.get("trades") or []
        closed = [
            p for p in book if isinstance(p, dict) and p.get("status") != "open"
        ]
        rets = [
            float(p["pnl_pct"])
            for p in closed
            if isinstance(p.get("pnl_pct"), (int, float))
        ]
        if rets:
            wins = [r for r in rets if r > 0]
            losses = [r for r in rets if r <= 0]
            lines += [
                f"**Ledger:** {len(rets)} closed · win rate "
                f"{100 * len(wins) / len(rets):.0f}% · avg win "
                f"{sum(wins) / len(wins):+.2f}% · avg loss "
                f"{sum(losses) / len(losses):+.2f}%",
                "",
            ]
            # The learning trajectory (v0.21.0): the book's last few
            # calls against its all-time record - the visible slope of
            # the self-improvement loop. Flat until 5 outcomes exist.
            recent = rets[-5:]
            if len(rets) >= 5:
                r_wins = sum(1 for r in recent if r > 0)
                trend = (
                    "improving" if 100 * r_wins / len(recent)
                    > 100 * len(wins) / len(rets)
                    else ("holding" if r_wins * len(rets) == len(wins) * len(recent) else "slipping")
                )
                lines.append(
                    f"**Trajectory:** last {len(recent)} calls "
                    f"{r_wins}W-{len(recent) - r_wins}L "
                    f"({100 * r_wins / len(recent):.0f}%) vs all-time "
                    f"{100 * len(wins) / len(rets):.0f}% - {trend}"
                )
    except Exception:  # noqa: BLE001
        pass

    # What the lessons layer actually changed (v0.21.0): the ledger's
    # own evidence, applied back into the engine - visible, auditable.
    try:
        import json as _json

        lessons = _json.loads(
            (ROOT / "data" / "lessons.json").read_text(encoding="utf-8")
        )
        n_labeled = int(lessons.get("labeled") or 0)
        if n_labeled:
            n_black = len(lessons.get("blacklisted") or [])
            scale = lessons.get("score_scale") or {}
            slope = scale.get("slope")
            meta = lessons.get("meta") or {}
            active = bool(meta.get("tightened")) if isinstance(meta, dict) else False
            parts = [f"{n_labeled} outcomes absorbed"]
            if n_black:
                parts.append(f"{n_black} symbol(s) benched")
            if isinstance(slope, (int, float)) and slope:
                parts.append(f"score calibration {slope:+.2f}")
            parts.append("regime caution ON" if active else "regime caution standby")
            lines += [f"**Learning:** {', '.join(parts)}", ""]
    except Exception:  # noqa: BLE001
        pass

    flow_line = _flow_headline()
    if flow_line:
        lines += [flow_line, ""]

    lines += [
        f"_Regenerated {_fmt_pkt(now)} PKT on every "
        "pass. Today's calls live in "
        "[SIGNALS.md](SIGNALS.md)._",
        "",
    ]
    return "\n".join(lines)


def render_signals_md(events: list[dict], delivered: dict) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        "# 📣 The Sentinel - signal log",
        "",
        f"_Page regenerated {_fmt_pkt(now)} PKT. "
        "Newest first. Every BUY/EXIT below was also emailed via the "
        "[signals issue](../../issues) once._",
        "",
    ]
    flow_line = _flow_headline()
    if flow_line:
        lines += [flow_line, ""]
    todays = [
        e
        for e in events
        if e["ts"].astimezone(PKT).date() == now.astimezone(PKT).date()
    ]
    if not todays:
        lines += ["_No signals yet today. The bot is watching._", ""]
        return "\n".join(lines)
    lines += ["| Time (PKT) | Signal | Detail |", "|---|---|---|"]
    for e in reversed(todays):
        flag = "📧" if delivered.get(e["key"]) else "·"
        lines.append(
            f"| {_fmt_pkt(e['ts'])} {flag} | **{e['kind']}** "
            f"| {one_line(e)} |"
        )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# GitHub issue delivery
# --------------------------------------------------------------------------

def _api(url: str, token: str, payload: dict | None, method: str = "POST"):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github+json")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        return exc.code, None


def ensure_issue(repo: str, token: str) -> int | None:
    """Find or create the signals issue; return its number."""
    status, data = _api(
        f"https://api.github.com/repos/{repo}/issues?state=open&per_page=50",
        token,
        None,
        method="GET",
    )
    if status == 200 and data:
        for issue in data:
            if issue.get("title", "").startswith("📣 The Sentinel"):
                return issue["number"]
    status, data = _api(
        f"https://api.github.com/repos/{repo}/issues",
        token,
        {"title": ISSUE_TITLE, "body": (
            "You will receive an email for every BUY and EXIT this bot "
            "issues, delivered as comments on this issue.\n\n"
            "**One-time setup (do it now):** open this issue and click "
            "**Subscribe** (right side). Then check your GitHub settings → "
            "Notifications → Watching: make sure email notifications are on.\n\n"
            "_Comments below are posted by the bot itself._"
        )},
    )
    if status in (200, 201) and data:
        return data["number"]
    return None


# Signals older than this are never delivered. A failed delivery must
# NOT queue a card for days: the Sep-15 KEL BUY (dedup key lost in a
# same-minute book reset) sat 'forever pending' for 6 days and burst
# onto the owner's phone Sep 21 as a stale zombie card. Signals live in
# the minute they fire; after SIGNAL_MAX_AGE_MINUTES they are dead and
# the position state (data/portfolio.json) remains the only truth.
SIGNAL_MAX_AGE_MINUTES = 20


def _drop_stale_pending(
    events: list[dict], notified: dict, now: datetime | None = None
) -> tuple[list[dict], int]:
    """Seal long-dead pending events so they can never deliver.

    BUY signals seal after SIGNAL_MAX_AGE_MINUTES: a late entry card is
    dangerous (the price has moved; acting on it loses money). EXIT
    cards stay deliverable through their own trading day - the owner
    may still hold the position - and seal once that day is over.
    Sealed events are marked 'expired-stale' in the dedup ledger;
    re-sealing is idempotent.
    """
    now = now or datetime.now(timezone.utc)
    today_pkt = now.astimezone(PKT).date().isoformat()
    cutoff = timedelta(minutes=SIGNAL_MAX_AGE_MINUTES)
    stale: list[dict] = []
    for e in events:
        if notified.get(e["key"]):
            continue
        if e["kind"] == "BUY":
            dead = (now - e["ts"]) > cutoff
        else:  # EXIT: fresh while its own trading day lives
            exit_date = str(e["fields"].get("exit_date") or "")
            dead = bool(exit_date) and exit_date != today_pkt
        if dead:
            stale.append(e)
    for e in stale:
        notified[e["key"]] = "expired-stale"
    return [e for e in events if not notified.get(e["key"])], len(stale)


def deliver(repo: str, token: str, dry_run: bool = False) -> dict:
    """Deliver all undelivered events; returns a summary."""
    enable_utf8_stdout()
    events = collect_events(repo, token)
    notified = _load_notified()
    pending, n_stale = _drop_stale_pending(events, notified)
    if n_stale:
        _save_notified(notified)
        _print(
            f"notify: sealed {n_stale} stale pending event(s) "
            f"(> {SIGNAL_MAX_AGE_MINUTES} min old - never delivered)"
        )

    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNALS_PATH.write_text(
        render_signals_md(events, notified), encoding="utf-8"
    )
    STATUS_PATH.write_text(render_status_md(), encoding="utf-8")

    summary = {"pending": len(pending), "sent": 0, "issue": None}
    if not pending:
        _print("notify: nothing new to deliver.")
        return summary
    if not (repo and token) or dry_run:
        _print(f"notify: {len(pending)} event(s) pending, no credentials - listing:")
        for e in pending:
            _print("  -", one_line(e))
        return summary

    issue_no = ensure_issue(repo, token)
    if issue_no is None:
        # The issue path is dead but Telegram may still work - deliver
        # every pending event over the backup channel.
        _print("notify: could not find/create the signals issue.")
        for e in pending:
            if send_event_telegram(e):
                notified[e["key"]] = datetime.now(timezone.utc).isoformat()
                # Marked Telegram-only so the catch-up pass delivers the
                # primary email once GitHub recovers.
                notified[e["key"] + ":tg-only"] = datetime.now(
                    timezone.utc
                ).isoformat()
                summary["sent"] += 1
                _print(f"notify: sent via telegram {one_line(e)}")
        _save_notified(notified)
        return summary
    summary["issue"] = issue_no

    for e in pending:
        # @mention the owner: GitHub emails mentions even when the
        # account-wide notification setting is "participating only".
        owner = repo.split("/")[0] if repo and "/" in repo else ""
        mention = f"@{owner} " if owner else ""
        status, _ = _api(
            f"https://api.github.com/repos/{repo}/issues/{issue_no}/comments",
            token,
            {"body": mention + format_event(e)},
        )
        if status in (200, 201):
            notified[e["key"]] = datetime.now(timezone.utc).isoformat()
            summary["sent"] += 1
            _print(f"notify: sent {one_line(e)}")
            # Backup channel: same dedup ledger, never fatal.
            send_event_telegram(e)
        else:
            _print(f"notify: FAILED ({status}) {one_line(e)}")
            # Email path failed - try Telegram alone so the signal still
            # reaches the owner. Only marked sent if Telegram delivers.
            if send_event_telegram(e):
                notified[e["key"]] = datetime.now(timezone.utc).isoformat()
                # Telegram-only marker: the catch-up pass below retries
                # the primary email when GitHub comes back.
                notified[e["key"] + ":tg-only"] = datetime.now(
                    timezone.utc
                ).isoformat()
                summary["sent"] += 1

    # Catch-up (v0.18.1): anything delivered Telegram-only during a
    # GitHub outage gets its primary email retried now that GitHub is
    # answering again. The owner's standing order: GitHub primary,
    # Telegram backup - a rescued signal is not a finished delivery.
    if repo and token and issue_no:
        for e in events:
            if (
                notified.get(e["key"])
                and notified.get(e["key"] + ":tg-only")
                and not notified.get(e["key"] + ":gh")
            ):
                owner = repo.split("/")[0] if "/" in repo else ""
                mention = f"@{owner} " if owner else ""
                gh_status, _ = _api(
                    f"https://api.github.com/repos/{repo}/issues/{issue_no}/comments",
                    token,
                    {"body": mention + format_event(e)},
                )
                if gh_status in (200, 201):
                    notified[e["key"] + ":gh"] = datetime.now(
                        timezone.utc
                    ).isoformat()
                    notified.pop(e["key"] + ":tg-only", None)
                    summary["sent"] += 1
                    _print(
                        f"notify: catch-up email delivered {one_line(e)}"
                    )

    _save_notified(notified)
    return summary


if __name__ == "__main__":
    # Actions entrypoint: deliver using the workflow's env.
    enable_utf8_stdout()
    if "--telegram-test" in sys.argv:
        # Wiring check: sends one card to the owner's chat. With no
        # secrets set this prints the honest status and exits 0 -
        # useful as a workflow step BEFORE the owner finishes setup.
        if _telegram_config() is None:
            _print(
                "telegram: NOT configured - set TELEGRAM_BOT_TOKEN and "
                "TELEGRAM_CHAT_ID repo secrets"
            )
        else:
            ok = send_telegram(
                "✅ <b>The Sentinel - Telegram linked.</b> "
                "Backup channel active: every BUY/EXIT will also "
                "arrive here. (GitHub email remains the primary.)"
            )
            _print("telegram: test", "sent" if ok else "FAILED")
        if _whatsapp_config() is None:
            _print(
                "whatsapp: NOT configured - set CALLMEBOT_PHONE and "
                "CALLMEBOT_APIKEY repo secrets"
            )
        else:
            ok = send_whatsapp(
                "*The Sentinel - WhatsApp linked.* "
                "Backup channel active: every BUY/EXIT will also "
                "arrive here. (GitHub email remains the primary.)"
            )
            _print("whatsapp: test", "sent" if ok else "FAILED")
        sys.exit(0)
    summary = deliver(
        os.environ.get("GITHUB_REPOSITORY", ""),
        os.environ.get("GITHUB_TOKEN", ""),
    )
    _print("notify summary:", summary)
