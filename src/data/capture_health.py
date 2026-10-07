"""Interpret collector heartbeat files without trusting stale liveness flags."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

KARACHI = timezone(timedelta(hours=5))


def status_view(status: dict, now: datetime | None = None,
                stale_after_seconds: int = 90) -> dict:
    """Return a copy with liveness derived from heartbeat freshness and PID."""
    result = dict(status)
    current = now or datetime.now(KARACHI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KARACHI)

    updated = None
    try:
        updated = datetime.fromisoformat(str(status.get("updated_at", "")))
    except ValueError:
        pass
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=current.tzinfo)

    age = None if updated is None else max(0.0, (current - updated).total_seconds())
    reported_running = bool(status.get("running"))
    pid = status.get("pid")

    if not reported_running:
        state = "STOPPED"
    elif age is None or age > stale_after_seconds:
        state = "STALE"
    elif not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        state = "UNKNOWN"
    else:
        state = "RUNNING"

    result["reported_running"] = reported_running
    result["running"] = state == "RUNNING"
    result["health_state"] = state
    result["heartbeat_age_seconds"] = None if age is None else round(age, 1)
    return result

