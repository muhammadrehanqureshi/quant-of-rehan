"""Signal-only Telegram notifier for quant-of-rehan.

Delivery channel for owner notifications (SO-1: signal-only: this module
sends messages, never trades). Token source of truth:

    1. explicit `token` argument (tests only)
    2. env var  TELEGRAM_BOT_TOKEN
    3. local <repo>/.env  (gitignored; KEY=VALUE lines)

The canonical token lives in the owner's Desktop credentials.txt and is
mirrored into .env by the owner/QUANT: never hardcoded, never committed,
never logged in full. The sentinel's old bot token is retired and must not
be reused anywhere.

Network reality (observed 2026-10-05): api.telegram.org can be blocked or
throttled by the local ISP. send_message therefore fails CLOSED: on
transport failure it returns False after retries and the caller must keep
the signal locally: no signal is ever lost silently, none is fabricated.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://api.telegram.org"
REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
DEFAULT_RETRIES = 3
RETRY_PAUSE_S = 2.0


def load_bot_token() -> Optional[str]:
    """Resolve the bot token: env var first, then the gitignored .env file.

    Returns None when unset: callers decide how loud to be. The value is
    never printed, logged, or embedded in exceptions.
    """
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tok:
        return tok
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == "TELEGRAM_BOT_TOKEN" and v.strip():
                return v.strip()
    return None


def mask_token(token: str) -> str:
    """Safe identification form for logs: bot-id + last 3 of the hash."""
    if ":" not in token:
        return "***"
    bot_id, _, secret = token.partition(":")
    tail = secret[-3:] if len(secret) >= 3 else "***"
    return f"{bot_id}:***{tail}"


def send_message(text: str, *, token: Optional[str] = None,
                 chat_id: Optional[str] = None,
                 retries: int = DEFAULT_RETRIES,
                 pause_s: float = RETRY_PAUSE_S,
                 timeout_s: float = 30.0) -> bool:
    """Send `text` to the owner chat. Returns True only on Telegram's ok.

    chat_id resolution: explicit arg, then TELEGRAM_CHAT_ID env, then
    TELEGRAM_CHAT_ID in .env. Transport failures return False (fail
    closed): callers must treat the signal as undelivered, not lost.
    """
    tok = token or load_bot_token()
    if not tok:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set (env or .env)")
    cid = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not cid and ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and line.split("=", 1)[0].strip() == "TELEGRAM_CHAT_ID":
                cid = line.split("=", 1)[1].strip()
                break
    if not cid:
        raise RuntimeError("TELEGRAM_CHAT_ID not set (env or .env)")

    url = f"{API_BASE}/bot{tok}/sendMessage"
    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json={"chat_id": cid, "text": text,
                                         "parse_mode": "HTML"},
                              timeout=timeout_s)
            if r.status_code == 200 and r.json().get("ok"):
                return True
            last_err = f"HTTP {r.status_code}: {r.json().get('description', '')[:80]}"
        except requests.RequestException as e:
            last_err = type(e).__name__
        if attempt < retries:
            time.sleep(pause_s * attempt)
    # Fail closed, never leak the token into error text.
    print(f"telegram: delivery FAILED after {retries} attempts "
          f"(token {mask_token(tok)}): {last_err}")
    return False
