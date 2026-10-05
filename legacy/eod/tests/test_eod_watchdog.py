"""
Sentinel-EOD watchdog tests - the rescue contract.

  * decision core: weekend / too-early / already-done / rescue-needed /
    window-closed, for both modes, with weekday-aware targets;
  * mode targets: reference 14:20 / pick 15:26 PKT Mon-Thu,
    15:20 / 16:26 PKT Friday (v2.2.1);
  * grace windows: reference 30 min, pick 2 min (alive through :28 -
    the owner orders at :29);
  * the pick day-guard: a late-arriving pick run must NEVER overwrite
    an already-published book.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from eod_watchdog import mode_target, watchdog_decision  # noqa: E402

PKT = ZoneInfo("Asia/Karachi")


def pkt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=PKT)


# ---------------- mode targets ----------------

def test_reference_targets():
    assert mode_target("reference", 0) == (14, 20)   # Monday
    assert mode_target("reference", 3) == (14, 20)   # Thursday
    assert mode_target("reference", 4) == (15, 20)   # Friday


def test_pick_targets():
    assert mode_target("pick", 0) == (15, 26)
    assert mode_target("pick", 3) == (15, 26)
    assert mode_target("pick", 4) == (16, 26)        # Friday


# ---------------- decision core ----------------

def test_weekend_is_never_rescued():
    d, _ = watchdog_decision(pkt(2026, 9, 19, 16, 0), None, "pick")  # Sat
    assert d == "weekend"
    d, _ = watchdog_decision(pkt(2026, 9, 20, 16, 0), None, "pick")  # Sun
    assert d == "weekend"


def test_too_early_before_target():
    # Wed 15:05 PKT - pick target 15:26 not reached yet (primary :21
    # and backup :24 own the minutes before the rescue window)
    d, t = watchdog_decision(pkt(2026, 9, 16, 15, 5), None, "pick")
    assert d == "too_early" and t == (15, 26)


def test_rescue_needed_when_no_heartbeat():
    # Wed 15:27 PKT - 1 minute past target (:26), nothing landed
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 27), None, "pick")
    assert d == "rescue_needed"


def test_already_done_when_today_pick_heartbeat():
    hb = {
        "utc": "2026-09-16T10:22:00+00:00",   # 15:22 PKT Wed
        "source": "pick",
    }
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 27), hb, "pick")
    assert d == "already_done"


def test_yesterdays_heartbeat_does_not_count():
    hb = {
        "utc": "2026-09-15T10:22:00+00:00",   # Tuesday's pick
        "source": "pick",
    }
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 27), hb, "pick")
    assert d == "rescue_needed"


def test_reference_heartbeat_does_not_satisfy_pick():
    hb = {"utc": "2026-09-16T09:21:00+00:00", "source": "reference"}
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 27), hb, "pick")
    assert d == "rescue_needed"


def test_window_closed_after_grace():
    # grace is 2 min for pick: 15:26 (:26) + 2 = :28 is the last live
    # minute; :29 - the owner's order minute - is closed. A pick
    # delivered :29+ can never be acted on. (Wed 2026-09-16.)
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 28), None, "pick")
    assert d == "rescue_needed"
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 29), None, "pick")
    assert d == "window_closed"


def test_reference_grace_is_30_minutes():
    # Thu 14:50 (20 past target) -> still rescue; 14:51 (31 past) -> closed
    d, _ = watchdog_decision(pkt(2026, 9, 17, 14, 50), None, "reference")
    assert d == "rescue_needed"
    d, _ = watchdog_decision(pkt(2026, 9, 17, 14, 51), None, "reference")
    assert d == "window_closed"


def test_corrupt_heartbeat_is_rescue_not_crash():
    hb = {"utc": "not-a-timestamp", "source": "pick"}
    d, _ = watchdog_decision(pkt(2026, 9, 16, 15, 27), hb, "pick")
    assert d == "rescue_needed"


# ---------------- pick day-guard (integration) ----------------

def test_pick_never_overwrites_todays_book(tmp_path, monkeypatch):
    """A second pick run the same day must keep the first book."""
    import run_eod

    picks_dir = tmp_path / "picks"
    picks_dir.mkdir()
    existing = {
        "pick_date": "2026-09-16",
        "picked_at_pkt": "2026-09-16T15:30:00+05:00",
        "picks": [{"symbol": "FIRST"}],
    }
    (picks_dir / "2026-09-16.json").write_text(
        json.dumps(existing), encoding="utf-8"
    )

    monkeypatch.setattr(run_eod, "PICKS_DIR", picks_dir)

    # Wed 2026-09-16 15:45 PKT - inside the window, book exists
    class FakeNow(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: ANN001
            return pkt(2026, 9, 16, 15, 45)

    monkeypatch.setattr(run_eod, "now_pkt", lambda: pkt(2026, 9, 16, 15, 45))
    monkeypatch.setattr(
        run_eod, "poll_kse100_quotes",
        lambda: (_ for _ in ()).throw(AssertionError("must not re-poll")),
    )

    rc = run_eod.mode_pick(token=None)
    assert rc == 0
    # the first book is untouched
    body = json.loads((picks_dir / "2026-09-16.json").read_text())
    assert body["picks"][0]["symbol"] == "FIRST"
