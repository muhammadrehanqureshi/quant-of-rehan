"""Tests for the local spark (Task-Scheduler cadence rescuer).

Only the pure decision core is tested - network I/O is excluded by
design (the module keeps it in main()).
"""
from __future__ import annotations

from datetime import datetime

import pytest

from spark import pick_guard_decision, should_dispatch


def _dt(h: int, m: int, weekday: int = 2) -> datetime:  # 2 = Wednesday
    # 2026-09-16 is a Wednesday; shift days from there to hit Mon/Sat.
    from datetime import timedelta

    base = datetime(2026, 9, 16, h, m)
    return base + timedelta(days=weekday - 2)


def test_weekend_never_sparks():
    dispatch, reason = should_dispatch(60.0, _dt(11, 0, weekday=5), None)
    assert not dispatch
    assert reason == "weekend"


def test_before_session_never_sparks():
    dispatch, reason = should_dispatch(60.0, _dt(8, 0), None)
    assert not dispatch
    assert reason == "before session"


def test_after_session_never_sparks():
    dispatch, reason = should_dispatch(60.0, _dt(16, 0), None)
    assert not dispatch
    assert reason == "after session"


def test_fresh_heartbeat_no_dispatch():
    dispatch, reason = should_dispatch(5.0, _dt(11, 0), None)
    assert not dispatch
    assert "fresh" in reason


def test_stale_heartbeat_dispatches():
    dispatch, reason = should_dispatch(17.0, _dt(11, 0), None)
    assert dispatch
    assert "stale" in reason


def test_unreadable_heartbeat_dispatches():
    """Fail-safe: if the heartbeat can't be read, assume the bot is down."""
    dispatch, reason = should_dispatch(None, _dt(11, 0), None)
    assert dispatch
    assert "unreadable" in reason


def test_spark_pileup_guard():
    """Two sparks 5 min apart: the second must hold off."""
    dispatch, reason = should_dispatch(17.0, _dt(11, 5), last_spark_min=5.0)
    assert not dispatch
    assert "guard" in reason


def test_spark_guard_expires():
    dispatch, reason = should_dispatch(17.0, _dt(11, 30), last_spark_min=30.0)
    assert dispatch


# ---- Guard 2: Sentinel-EOD trace rescue (2026-09-17) -----------------

def _trace_fixtures(now_local, pick_date="2026-09-16"):
    tracker = {
        "pick_date": pick_date,
        "open": [{"symbol": "SGPL", "entry_price": 30.0}],
    }
    return tracker


def test_trace_guard_weekend():
    from datetime import datetime
    import spark
    sat = datetime(2026, 9, 19, 10, 0)
    assert spark.trace_guard_decision(sat, _trace_fixtures(sat), None)[0] is False


def test_trace_guard_outside_window():
    from datetime import datetime
    import spark
    early = datetime(2026, 9, 17, 9, 0)   # before 09:35
    late = datetime(2026, 9, 17, 12, 0)   # after 11:50
    assert spark.trace_guard_decision(early, _trace_fixtures(early), None)[0] is False
    assert spark.trace_guard_decision(late, _trace_fixtures(late), None)[0] is False


def test_trace_guard_no_book():
    from datetime import datetime
    import spark
    now = datetime(2026, 9, 17, 10, 0)
    assert spark.trace_guard_decision(now, {"open": []}, None)[0] is False


def test_trace_guard_today_picks_not_traced_today():
    from datetime import datetime
    import spark
    now = datetime(2026, 9, 17, 10, 0)
    tracker = _trace_fixtures(now, pick_date="2026-09-17")
    assert spark.trace_guard_decision(now, tracker, None)[0] is False


def test_trace_guard_rescues_stale():
    from datetime import datetime, timezone, timedelta
    import spark
    now = datetime(2026, 9, 17, 10, 0)
    stale_hb = {"utc": (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(),
                "source": "trace"}
    dispatch, reason = spark.trace_guard_decision(now, _trace_fixtures(now), stale_hb)
    assert dispatch is True and "rescue" in reason


def test_trace_guard_skips_fresh():
    from datetime import datetime, timezone, timedelta
    import spark
    now = datetime(2026, 9, 17, 10, 0)
    fresh_hb = {"utc": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
                "source": "trace"}
    dispatch, reason = spark.trace_guard_decision(now, _trace_fixtures(now), fresh_hb)
    assert dispatch is False and "fresh" in reason


def test_trace_guard_wrong_source_does_not_count():
    from datetime import datetime, timezone, timedelta
    import spark
    now = datetime(2026, 9, 17, 10, 0)
    pick_hb = {"utc": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
               "source": "pick"}   # pick stamp != trace stamp
    dispatch, _ = spark.trace_guard_decision(now, _trace_fixtures(now), pick_hb)
    assert dispatch is True


# ---- Guard 3: the EOD evening-pick contract (15:20/16:20 PKT) ---------


def test_pick_guard_rescues_when_missing_on_friday():
    """Friday 16:14, no pick published: rescue fires immediately."""
    now = datetime(2026, 9, 18, 16, 14)  # Friday
    dispatch, reason = pick_guard_decision(
        now, {"pick_date": "2026-09-17"}, {"posted": []}
    )
    assert dispatch is True
    assert "16:13" in reason


def test_pick_guard_rescues_on_mon_thu_window():
    now = datetime(2026, 9, 21, 15, 14)  # Monday
    dispatch, _ = pick_guard_decision(now, {"pick_date": "2026-09-18"}, {})
    assert dispatch is True


def test_pick_guard_respects_published_pick():
    now = datetime(2026, 9, 18, 16, 14)  # Friday
    dispatch, reason = pick_guard_decision(
        now, {"pick_date": "2026-09-18"}, {"posted": ["pick:2026-09-18"]}
    )
    assert dispatch is False and "already published" in reason


def test_pick_guard_before_window_and_weekend():
    fri_early = datetime(2026, 9, 18, 16, 5)
    assert pick_guard_decision(fri_early, {"pick_date": "2026-09-17"}, {})[0] is False
    sat = datetime(2026, 9, 19, 16, 14)
    assert pick_guard_decision(sat, {"pick_date": "2026-09-18"}, {})[0] is False
