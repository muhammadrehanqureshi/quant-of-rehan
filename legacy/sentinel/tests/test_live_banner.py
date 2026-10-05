"""
THE SENTINEL
Tests for the live runner's startup banner.

The banner is the first thing on the console after launch - the thing
that tells the operator the process actually started, instead of a
silent blinking cursor during warm-up. These tests pin:

  * the time-of-day greeting (PKT clock, not machine clock)
  * the market-status line (open / pre-open / next session)
  * the banner's core content (name, cap, decide cadence)

Nothing here touches the network or writes outside a tmp dir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from entry_gate import EntryGate
from live import (
    _greeting,
    _market_status_line,
    _startup_banner,
)


# PKT is UTC+5, no DST. Helper: a UTC datetime whose PKT wall-clock is
# (hour:minute) on the given 2026 date.
def _pkt_on(day: str, hour: int, minute: int = 0) -> datetime:
    year, month, daynum = (int(x) for x in day.split("-"))
    return datetime(
        year, month, daynum, hour - 5, minute, tzinfo=timezone.utc
    )


MONDAY = "2026-09-07"   # a Monday (trading day, leg 1)
FRIDAY = "2026-09-11"   # Friday: legs 09:17-12:00 and 14:32-16:30
SATURDAY = "2026-09-12"  # weekend


def test_greeting_morning() -> None:
    assert _greeting(_pkt_on(MONDAY, 10)) == "Good morning, Mr. Rehan."


def test_greeting_afternoon() -> None:
    assert _greeting(_pkt_on(MONDAY, 14)) == "Good afternoon, Mr. Rehan."


def test_greeting_evening() -> None:
    assert _greeting(_pkt_on(MONDAY, 19)) == "Good evening, Mr. Rehan."


def test_market_status_open_monday() -> None:
    line = _market_status_line(_pkt_on(MONDAY, 10))
    assert "Market is OPEN" in line
    assert "(leg 1)" in line


def test_market_status_friday_second_leg() -> None:
    line = _market_status_line(_pkt_on(FRIDAY, 15))
    assert "Market is OPEN" in line
    assert "(leg 2)" in line


def test_market_status_preopen_same_day() -> None:
    line = _market_status_line(_pkt_on(MONDAY, 9))
    assert "Market is CLOSED - pre-open" in line
    assert "09:32" in line


def test_market_status_weekend_next_session() -> None:
    line = _market_status_line(_pkt_on(SATURDAY, 12))
    assert "Market is CLOSED" in line
    assert "Mon" in line and "2026-09-14" in line


def test_market_status_ignore_schedule_qualifies() -> None:
    line = _market_status_line(_pkt_on(SATURDAY, 12), ignore_schedule=True)
    assert "(--ignore-schedule)" in line


def _banner_logger() -> logging.Logger:
    return logging.getLogger("test-live-banner")


def test_banner_greets_and_names_project(tmp_path, capsys) -> None:
    gate = EntryGate(path=tmp_path / "entry_gate.json")
    _startup_banner(
        _banner_logger(),
        gate,
        _pkt_on(MONDAY, 10),
    )
    out = capsys.readouterr().out
    assert "Good morning, Mr. Rehan." in out
    assert "The Sentinel is online" in out
    # The console carries the greeting, the cap, and the promise that
    # only BUY/EXIT calls follow - nothing else.
    assert "Entries capped at 1/day (0 used)" in out
    assert "BUY and EXIT calls" in out


def test_banner_reports_entries_used(tmp_path, capsys) -> None:
    gate = EntryGate(path=tmp_path / "entry_gate.json")
    gate.record_entry(MONDAY)  # one entry already today
    _startup_banner(_banner_logger(), gate, _pkt_on(MONDAY, 10))
    out = capsys.readouterr().out
    assert "Entries capped at 1/day (1 used)" in out


def test_banner_carries_no_gate_config_chatter(tmp_path, capsys) -> None:
    # Operational detail (trend filters, strong-horse thresholds) goes
    # to the log file, never the console.
    gate = EntryGate(path=tmp_path / "entry_gate.json")
    _startup_banner(_banner_logger(), gate, _pkt_on(MONDAY, 10))
    out = capsys.readouterr().out
    assert "Kalman" not in out
    assert "Strong-horse" not in out
    assert "self-learning" not in out


def test_is_chatter_suppresses_repetitive_reasons() -> None:
    from live import _is_chatter

    # Repeating cycle chatter: suppressed.
    assert _is_chatter("Entry limit reached (3/3) for today")
    assert _is_chatter("Warming up: no current-session rows yet")
    assert _is_chatter("No eligible candidates after filtering")
    assert _is_chatter("Rule 13: 25 min since open - standing aside")
    # Real decisions the user can act on: shown once.
    assert not _is_chatter(
        "Below conviction gate: best score 0.5154 < 0.55"
    )
    assert not _is_chatter(
        "Rule 11: KSE-100 below its 20-session average - downtrend"
    )
