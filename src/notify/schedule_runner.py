"""Email notifications to the owner, exactly once per event per day.

Intraday schedulers just want a message body to claim for delivery and
a boolean back. This module is the shared seam for that: it prints one
clear line per attempt, returns whether the send landed, and never
changes the caller's wording (SO-3: text travels as given).

The channel is the owner's Gmail through GitHub's own notification mail
(owner order 2026-10-22, after the chat channel was retired): each
notification is a comment on the watched "Quant of Rehan - owner email"
issue, and GitHub emails the owner the moment the comment lands. Nothing
on this machine talks to a mail server.

The exactly-once ledger lives in GitHub, not on a PC: one marker line
per event per day, for example ``market-open:2026-10-22``. A marker
already committed on the issue means the notification went out and the
call is a no-op; late arrivals and catch-up backstops therefore cannot
double-fire. If the send raised, the state is unknown, the marker was
never proven committed, and the next fire simply claims it again -
fail-closed toward exactly one send, not zero.

The relay URL and RELAY_ADMIN_TOKEN resolvers stay in this module because
they are the one resolver the whole notification path shares (the scan
pipeline, the card push, the research log); the retired chat hop is gone,
so delivery itself needs neither.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from src.notify.owner_email import (  # noqa: E402,F401
    ENV_DOCS_ISSUE as OWNER_EMAIL_ISSUE_ENV,
    owner_email_issue,
    send as send_owner_email,
)

ENV_FILE = REPO_ROOT / ".env"
RELAY_URL_FILE = REPO_ROOT / "data" / "relay_url.txt"
NOTIFY_LOG = REPO_ROOT / "data" / "notify_log.jsonl"

_EMAIL_ISSUE_CACHE: str | None = None

MARKER_RE = re.compile(r"[a-z0-9_-]+:\d{4}-\d{2}-\d{2}")



def load_relay_url() -> str:
    """Resolve the worker relay URL, or fail closed.

    Order: the RELAY_URL environment variable, then data/relay_url.txt
    (gitignored, written by cloud/pair.py and scripts/signal_daily.py),
    with a trailing slash stripped so the resolved value is joinable.

    Still fail closed with nothing configured: the card push, the research
    log and the daily push all need the deployed worker's URL, and a
    delivery must never travel to a guessed address. The owner email is a
    different transport and never reads this.
    """
    configured = os.environ.get("RELAY_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    if RELAY_URL_FILE.is_file():
        url = RELAY_URL_FILE.read_text(encoding="utf-8").strip()
        if url:
            return url.rstrip("/")
    raise RuntimeError(
        "no relay URL configured: set RELAY_URL or write "
        "data/relay_url.txt with the deployed worker's URL "
        "(see cloud/README.md)"
    )


def load_relay_admin_token() -> str:
    """RELAY_ADMIN_TOKEN: the environment, then the repo .env, or fail.

    One resolver for the whole notification path. Owner bug report,
    2026-10-10: the daily-push failure alert was the one thing that could
    explain a failure, and it read the environment only, so on the owner's
    PC it quietly printed "relay admin token is missing" and sent nothing
    while every other module happily found the token in .env. Resolved per
    call, never cached: a caller that fixes its environment mid-process
    may cure itself, and tests patch ENV_FILE per test. The token is never
    printed, logged or embedded in an exception (SO-5).
    """
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


def _resolve_email_issue() -> str | None:
    """The watched issue's number; None when it is unreachable.

    OWNER_EMAIL_ISSUE pins it for the whole job (no per-call look-up,
    no second API list). Without the pin, the owner_email module does a
    the repo's own title search, which is correct but costs one API
    call, so the first resolution is cached - after that, only when the
    module's own connective test would find the same issue twice.
    """
    global _EMAIL_ISSUE_CACHE
    named = os.environ.get(OWNER_EMAIL_ISSUE_ENV, "").strip()
    if named:
        _EMAIL_ISSUE_CACHE = named
        return named
    if _EMAIL_ISSUE_CACHE is not None:
        return _EMAIL_ISSUE_CACHE
    try:
        _EMAIL_ISSUE_CACHE = owner_email_issue()
        return _EMAIL_ISSUE_CACHE
    except Exception as exc:  # the ledger being unreachable is degraded
        print(f"owner email: watched issue unreachable: {exc}", flush=True)
        return None


def deliver(text: str, event_key: str = "") -> bool:
    """Email the owner one notification, exactly once.

    ``event_key`` is the daily dedup key (``market-open``); this module
    turns it into the full marker (``market-open:2026-10-22``). When the
    key is empty no claim can be formed, so text alone is ambiguous
    between fires: the call is a no-op, never an extra mail.

    Returns True when this call landed the send, False when it is a no
    fire, and False (with a reason in the logs) when the transport is
    unreachable - never mixed text, never hidden state.
    """
    marker = _marker(event_key)
    if marker is None:
        print("owner email: no event key, no send", flush=True)
        return False

    issue = _resolve_email_issue()
    if issue is None:
        return False
    try:
        sent = send_owner_email(text, marker)
    except Exception as exc:
        print(f"owner email: {event_key}: send failed: {exc}", flush=True)
        return False
    if not sent:
        print(f"owner email: '{marker}' already delivered; not resent",
              flush=True)
        return False
    _log(marker, issue)
    return True


def _marker(event_key: str) -> str | None:
    """The full daily marker; None whenever the key is not a claim."""
    text = event_key.strip()
    if not text or "\n" in text or len(text.split()) != 1:
        return None
    if re.fullmatch(MARKER_RE, text):
        return text
    if ":" in text:
        return None  # something else has a colon: refuse, never guess
    return f"{text}:{_today()}"


def _today() -> str:
    """The Karachi date (SO-8): the day the notification claims."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=5)))
    return now.strftime("%Y-%m-%d")


def _log(marker: str, issue: str) -> None:
    """One line in the job log and one line in the gitignored ledger."""
    line = f"EMAIL DELIVERED {marker} issue={issue}"
    print(line, flush=True)
    try:
        NOTIFY_LOG.parent.mkdir(parents=True, exist_ok=True)
        with NOTIFY_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass  # the ledger is best-effort; the send itself already landed
