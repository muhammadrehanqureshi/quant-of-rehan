"""
Tests for the session keeper's pure decision core (src/watchdog.py).

The keeper is the sole cadence mechanism since v0.16.1 (self-chaining
deleted after three same-day failure modes). Its truth hierarchy is
pinned here:

  * the pass HEARTBEAT (data/heartbeat.json, stamped only by a pass
    that really polled/exited/decided) outranks run metadata - the
    2026-09-16 incident: a SKIPPED pass concludes "success" in
    metadata, which every layer then read as a healthy bot while the
    market sat unpolled for 30+ minutes;
  * metadata is only the fallback before the first heartbeat exists;
  * every rescue still respects the pile-up guard and daily budget.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import watchdog


NOW = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)


def _run(minutes_ago: float, status: str = "completed", conclusion: str = "success"):
    created = NOW - timedelta(minutes=minutes_ago)
    return {
        "id": f"r{minutes_ago}",
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "conclusion": conclusion,
    }


def test_recent_success_is_healthy():
    runs = [_run(5.0)]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("healthy")


def test_stale_success_with_no_recent_activity_dispatches():
    runs = [_run(30.0), _run(45.0)]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("dispatch")


def test_failed_ghost_run_does_not_count_as_healthy():
    # The v0.15.6 killer: a 12-second parse-failure run made the chain
    # think cadence was healthy. Only SUCCESSFUL passes count now.
    runs = [_run(2.0, conclusion="failure"), _run(40.0, conclusion="failure")]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("dispatch")


def test_recent_creation_pauses_rescue():
    # Cadence is behind, but a pass was created 3 minutes ago - it is
    # queued/starting; give it time instead of piling on.
    runs = [_run(30.0), _run(3.0, status="in_progress", conclusion=None)]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("waiting")


def test_no_successes_today_boots_the_chain():
    runs = [_run(90.0, conclusion="failure")]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("dispatch")


def test_daily_cap_blocks_dispatch():
    # 60 runs today, ages 60-119 min: no recent creations, newest
    # success stale, but the day's budget is burned -> capped.
    runs = [_run(60 + i) for i in range(watchdog.DAILY_RUN_BUDGET)]
    verdict = watchdog.decide(runs, NOW)
    assert verdict.startswith("capped")


def test_empty_history_dispatches():
    assert watchdog.decide([], NOW).startswith("dispatch")


def test_budget_constant_is_sane():
    # 60 runs/day is ~2x the normal 24-pass session - a brake, not a leash.
    assert 24 <= watchdog.DAILY_RUN_BUDGET <= 80


# --------------- v0.16.1: the heartbeat outranks metadata ---------------


def test_fresh_heartbeat_is_healthy_even_when_metadata_disagrees():
    # Heartbeat 4 min old (a real pass), metadata's newest success 40
    # min old. Ground truth wins: healthy.
    verdict = watchdog.decide([_run(40.0)], NOW, hb_age_min=4.0)
    assert verdict.startswith("healthy")
    assert "heartbeat" in verdict


def test_stale_heartbeat_beats_fresh_skipped_success_metadata():
    # THE 2026-09-16 INCIDENT, pinned: a skipped pass concluded
    # "success" minutes ago - metadata looks fresh - but the last REAL
    # pass (heartbeat) was 20 min ago. Old code declared "healthy" and
    # the market sat unpolled 30+ min. Now: dispatch.
    # (A run CREATED seconds ago still gets its grace window - that is
    # the separate waiting verdict below.)
    runs = [_run(8.0, conclusion="success"), _run(23.0, conclusion="success")]
    verdict = watchdog.decide(runs, NOW, hb_age_min=20.0)
    assert verdict.startswith("dispatch")


def test_stale_heartbeat_with_recent_creation_waits():
    runs = [_run(3.0, status="in_progress", conclusion=None)]
    verdict = watchdog.decide(runs, NOW, hb_age_min=20.0)
    assert verdict.startswith("waiting")


def test_stale_heartbeat_respects_daily_budget():
    runs = [_run(60 + i) for i in range(watchdog.DAILY_RUN_BUDGET)]
    verdict = watchdog.decide(runs, NOW, hb_age_min=20.0)
    assert verdict.startswith("capped")


def test_heartbeat_boundary():
    # Just inside the 12-min keep window: healthy. Just outside: dispatch.
    inside = watchdog.decide([_run(60.0)], NOW, hb_age_min=11.9)
    outside = watchdog.decide([_run(60.0)], NOW, hb_age_min=12.1)
    assert inside.startswith("healthy")
    assert outside.startswith("dispatch")
