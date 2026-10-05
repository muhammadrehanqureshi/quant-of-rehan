"""Tier-3 PC-direct emergency pick - decision-core contract.

The tier exists for one scenario: GitHub Actions is completely dead
inside the pick window. Its guarantees, pinned here:

  * arms ONLY inside the disaster window (:24-:30 past the hour,
    Mon-Thu 15:xx, Friday 16:xx) - the on-time tiers own :17-:23;
  * never fires on a weekend;
  * never fires when the pick is already published (any source);
  * never fires without the local Telegram credentials;
  * boundary inclusivity: :24 exactly arms, :31 does not.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eod_emergency_pick import emergency_pick_decision

PKT = timezone(timedelta(hours=5))


def _pkt(h: int, m: int, weekday: int) -> datetime:
    # 2026-09-14 is a Monday; weekday 0=Mon .. 4=Fri.
    return datetime(2026, 9, 14 + weekday, h, m, tzinfo=PKT)


def test_arms_inside_friday_window():
    act, reason = emergency_pick_decision(
        _pkt(16, 27, 4), pick_published_today=False, telegram_ready=True
    )
    assert act and "emergency" in reason


def test_arms_inside_mon_thu_window():
    act, _ = emergency_pick_decision(
        _pkt(15, 27, 0), pick_published_today=False, telegram_ready=True
    )
    assert act


def test_boundary_exact_start_arms():
    act, _ = emergency_pick_decision(
        _pkt(15, 26, 2), pick_published_today=False, telegram_ready=True
    )
    assert act


def test_before_window_stands_down():
    # :24 belongs to the primary/backup tiers, not the emergency tier.
    act, reason = emergency_pick_decision(
        _pkt(15, 24, 2), pick_published_today=False, telegram_ready=True
    )
    assert not act and "before" in reason


def test_after_window_stands_down():
    # :29 is the owner's order minute - nobody arms there, ever.
    act, reason = emergency_pick_decision(
        _pkt(15, 29, 2), pick_published_today=False, telegram_ready=True
    )
    assert not act and "after" in reason


def test_weekend_never_arms():
    act, reason = emergency_pick_decision(
        _pkt(15, 27, 5), pick_published_today=False, telegram_ready=True
    )
    assert not act and reason == "weekend"


def test_published_pick_stands_down():
    act, reason = emergency_pick_decision(
        _pkt(16, 27, 4), pick_published_today=True, telegram_ready=True
    )
    assert not act and "already published" in reason


def test_no_telegram_stands_down():
    act, reason = emergency_pick_decision(
        _pkt(15, 27, 0), pick_published_today=False, telegram_ready=False
    )
    assert not act and "telegram" in reason
