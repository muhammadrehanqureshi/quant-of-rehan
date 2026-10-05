"""
The pass heartbeat (v0.16.1) - the one freshness signal the keeper trusts.

The bug this closes (2026-09-16, 10:33 PKT): a pass that SKIPPED itself
as a duplicate still concludes "success" in GitHub's run metadata, and
every cadence layer (chain and watchdog alike) counted that as proof of
a healthy bot. One skip near the head of the chain ended the loop, and
the market went unpolled for 30+ minutes while the metadata said
everything was fine.

This file is written only by a pass that actually polled the feed,
checked exits and decided. The keeper (src/watchdog.py) reads its age
first and only falls back to run metadata when no heartbeat exists
yet. Metadata can say "success" for a pass that did nothing; this
timestamp cannot.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEARTBEAT_PATH = ROOT / "data" / "heartbeat.json"


def stamp(
    path: Path | None = None, now: datetime | None = None, source: str = "cloud_bot"
) -> dict:
    """Record 'a real pass ran at this instant'. Returns what was written."""
    now = now or datetime.now(timezone.utc)
    record = {"utc": now.isoformat(), "source": source}
    path = path or HEARTBEAT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=1) + "\n", encoding="utf-8"
    )
    return record


def read_age(
    path: Path | None = None, now: datetime | None = None
) -> float | None:
    """Minutes since the last real pass, or None if unreadable/absent."""
    path = path or HEARTBEAT_PATH
    now = now or datetime.now(timezone.utc)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        stamped = datetime.fromisoformat(str(record["utc"]))
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        return (now - stamped).total_seconds() / 60.0
    except (OSError, ValueError, KeyError, TypeError):
        return None
