"""
Sentinel-EOD heartbeat tail (v2.6.3, 2026-10-03).

One helper that every mode function calls as the LAST thing before each
return, so a heartbeat is always stamped by a real run even when the mode
exits early (holiday, weekend, outside window, window-open-only, card
error, corporate-actions skip, gate skip, no-candidate, or the except-block
fallback). Mirrors the-sentinel's v4.4.3 _live_stamp() in run_decide().

source is the mode name the caller passes ("reference" / "pick" / "trace")
so the committed heartbeat carries the mode that produced it.
"""

from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")
HEARTBEAT = Path(__file__).resolve().parents[1] / "data" / "heartbeat.json"


def stamp(source: str) -> None:
    """Record "the EOD runner ran a real cycle in this mode at this instant".

    Best-effort: a heartbeat write must never break a mode that already
    completed its real work. Swallows every exception.
    """
    try:
        from run_eod import save_json  # noqa: E402 - local to this repo
    except Exception:
        return
    try:
        from datetime import datetime as _dt
        save_json(
            HEARTBEAT,
            {
                "utc": _dt.now(ZoneInfo("UTC")).isoformat(),
                "source": source,
            },
        )
    except Exception:  # noqa: BLE001 - never kill a mode for freshness
        pass


def mode_tail(source: str) -> None:
    """Alias for stamp() - named for the pattern: call as the last line
    before every ``return`` inside a mode function."""
    stamp(source)
