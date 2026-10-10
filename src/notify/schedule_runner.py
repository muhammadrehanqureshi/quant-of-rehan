"""Local scheduler for the owner's two daily notifications (SO-9).

Runs on the owner's PC only (SO-4: never in Actions). It sleeps until the
next schedule event computed by src/data/sessions.py (Karachi pinned),
then delivers the owner's exact text through the quant-of-rehan Cloudflare
Worker relay. Direct calls to api.telegram.org from this machine are
forbidden (Telegram is blocked inside Pakistan; SO-9).

Delivery is honest by construction: every attempt is journaled to
data/notify_log.jsonl and retried on the next loop pass if the relay could
not be reached. The runner never invents a success.

Usage (owner's PC, from the repo root):
    python -m src.notify.schedule_runner
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    MSG_MARKET_CLOSED,
    MSG_MARKET_OPEN,
    KARACHI,
    next_event,
    now_karachi,
)

RELAY_URL_FILE = ROOT / "data" / "relay_url.txt"
ENV_FILE = ROOT / ".env"
NOTIFY_LOG = ROOT / "data" / "notify_log.jsonl"
MAX_DELAY_MS = 10 * 60 * 1000   # wake at least every 10 min to re-check
RETRY_AFTER_FAIL_S = 120        # retry a failed send after 2 minutes


def load_relay_url() -> str:
    """Read the worker relay URL from data/relay_url.txt (gitignored)."""
    if RELAY_URL_FILE.is_file():
        url = RELAY_URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url.rstrip("/")
    raise RuntimeError(
        "data/relay_url.txt missing: deploy the worker and paste its URL "
        "(see cloud/README.md)"
    )


def load_relay_admin_token() -> str:
    """Resolve RELAY_ADMIN_TOKEN: environment first, then the repo .env.

    One resolver for the whole notification path. Owner bug report,
    2026-10-10: the daily-push failure alert was the one thing that could
    explain a failure, and it read the environment only, so on the owner's
    PC it quietly printed "relay admin token is missing" and sent nothing
    while every other module happily found the token in .env. The token is
    never printed, logged or embedded in an exception (SO-5).
    """
    import os

    token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    if token:
        return token
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == "RELAY_ADMIN_TOKEN" and value.strip():
                return value.strip()
    raise RuntimeError(
        "RELAY_ADMIN_TOKEN missing (set the environment variable or add it "
        "to the gitignored repo .env)"
    )


def send_via_relay(url: str, text: str, kind: str,
                   timeout_s: float = 30.0) -> bool:
    """POST one message to the worker relay. True only on relay ok."""
    import requests

    payload = {"kind": kind, "text": text}
    try:
        r = requests.post(url + "/notify", json=payload, timeout=timeout_s)
        if r.status_code == 200:
            body = r.json()
            return bool(body.get("ok"))
        print(f"relay {url}: HTTP {r.status_code}: {r.text[:120]}")
        return False
    except requests.RequestException as e:
        print(f"relay unreachable ({type(e).__name__}); will retry")
        return False


def journal(event: str, kind: str, text: str, ok: bool, detail: str) -> None:
    """Append one delivery record. Local data only, never committed."""
    NOTIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "ts": now_karachi().isoformat(timespec="seconds"),
        "event": event,
        "kind": kind,
        "ok": ok,
        "detail": detail,
    }
    with NOTIFY_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def deliver(event: str, kind: str, text: str) -> bool:
    """One delivery attempt with journaling. Never raises, never fakes."""
    try:
        url = load_relay_url()
    except RuntimeError as e:
        journal(event, kind, text, False, str(e))
        print(f"[{now_karachi():%Y-%m-%d %H:%M:%S}] {event}: {e}")
        return False
    ok = send_via_relay(url, text, kind)
    detail = "delivered" if ok else "relay refused or unreachable"
    journal(event, kind, text, ok, detail)
    stamp = now_karachi().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{stamp}] {event}: {'sent' if ok else 'FAILED'} ({detail})")
    return ok


def run_forever(poll_interval_s: float = 30.0) -> None:
    """Fire OPEN at the open instant and CLOSE at the close instant.

    Exactly-once per event per Karachi day: the fired set keeps
    (event, date) keys in memory. If the PC was off at the moment, the
    event is simply missed for that day (honest: no fake catch-up sends).
    """
    fired: set[tuple[str, str]] = set()
    print(f"schedule runner up at {now_karachi():%Y-%m-%d %H:%M:%S} "
          f"(Asia/Karachi, UTC+5, SO-8)")
    while True:
        now = now_karachi()
        event, when = next_event(now)
        key = (event, when.date().isoformat())
        if key not in fired and now >= when:
            text = MSG_MARKET_OPEN if event == "OPEN" else MSG_MARKET_CLOSED
            ok = deliver(event, kind="open" if event == "OPEN" else "close",
                         text=text)
            if ok:
                fired.add(key)
            else:
                # stay un-fired so the loop retries after the backoff
                time.sleep(RETRY_AFTER_FAIL_S)
                continue
        delay = min(ms_until(when, now), MAX_DELAY_MS)
        time.sleep(max(delay / 1000.0, poll_interval_s))


if __name__ == "__main__":
    try:
        run_forever()
    except KeyboardInterrupt:
        print("schedule runner stopped by owner")
        sys.exit(0)
