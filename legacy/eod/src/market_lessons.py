"""Market-lessons sync for Sentinel-EOD (v2.4.0).

The Sentinel's close-out teaches one lesson per session from the full
KMIALL tape (breadth, money leaders, trending names, dead names,
investor flows - see the Sentinel's src/market_learner.py). This
module mirrors that rolling store here, exactly like the per-symbol
lock memory does, so the evening pick also learns what the market has
been doing every day.

Consumed by run_eod.py:
  * market_dead  - dead 3+ sessions running: refused as evening picks
    (a dead tape has no overnight fuel either);
  * market_trend - trending 3+ sessions running: modest rank context
    in the card (data, not a bonus that overrides the gates);
  * last lesson  - the "market context" line on the card.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

STORE_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "market_lessons.json"
)

SENTINEL_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "muhammadrehanqureshi/the-sentinel/master/"
    "data/market_lessons.json"
)

# Pick-side tuning. Dead means dead: no overnight thesis in a flat,
# illiquid tape. Trending context is capped small - the scorer's own
# evidence (lock memory, quality gates) outranks a tape anecdote.
DEAD_MIN_STREAK = 3
TREND_MIN_STREAK = 3
TREND_RANK_BONUS = 0.03   # +3% rank, capped
STALE_DAYS = 10


def refresh_store(token: str | None = None, timeout: float = 15.0) -> bool:
    """Best-effort sync of the rolling market lessons from the Sentinel
    repo. Returns True when a fresh copy was written. Never raises: a
    failed refresh leaves the committed copy in place (offline-safe).
    """
    try:
        req = urllib.request.Request(SENTINEL_RAW_URL)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict) or not parsed.get("days"):
            return False
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STORE_PATH.write_text(json.dumps(parsed), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def load_market_lessons(path: Path | None = None) -> dict:
    """The consumer view. Missing/stale/corrupt store degrades to an
    empty lesson - learning must never break a pick run."""
    path = path or STORE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"dead": set(), "trending": set(), "last": None}
    if not isinstance(raw, dict):
        return {"dead": set(), "trending": set(), "last": None}

    dead_streak = raw.get("dead_streak") or {}
    trend_streak = raw.get("trend_streak") or {}
    return {
        "dead": {
            s for s, n in dead_streak.items()
            if isinstance(n, (int, float)) and n >= DEAD_MIN_STREAK
        },
        "trending": {
            s for s, n in trend_streak.items()
            if isinstance(n, (int, float)) and n >= TREND_MIN_STREAK
        },
        "last": (raw.get("days") or {}).get(raw.get("last_date") or ""),
    }


def memory_factor(symbol: str, lessons: dict) -> float | None:
    """Rank multiplier for an evening pick. Refusal is signalled by
    0.0; untouched symbols get None."""
    if not lessons:
        return None
    if symbol in (lessons.get("dead") or set()):
        return 0.0
    if symbol in (lessons.get("trending") or set()):
        return 1.0 + TREND_RANK_BONUS
    return None


def context_line(lessons: dict) -> str | None:
    """One line of market context for the card, from the last lesson."""
    last = (lessons or {}).get("last") or {}
    taught = last.get("taught")
    return taught or None
