"""Regression (2026-10-02): the no-live-candidate Telegram card.

The 2026-10-01 evening card never reached Telegram: the send() call
interpolated {nxt.upper()} - a name defined nowhere in run_eod.py -
and the NameError was swallowed by a silent except. GitHub got the
card, Telegram never did, and the log said nothing. This test pins the
fix three ways: the undefined name is gone from the runner source, the
card text carries the SENTINELS OF REHAN brand, and the wording follows
the v2.2.4 law (only "next market day", never a weekday name).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import run_eod

SRC = Path(run_eod.__file__).read_text(encoding="utf-8")


def test_no_undefined_nxt_in_runner_source():
    # If this trips because a properly defined nxt joined the runner,
    # update this tripwire - the 2026-10-01 incident must not repeat.
    assert "nxt" not in SRC, (
        "run_eod.py references 'nxt' again - the 2026-10-01 silent "
        "NameError that ate the Telegram card"
    )


def test_no_live_card_is_branded():
    assert "SENTINELS OF REHAN | Sentinel-EOD: NO LIVE CANDIDATE" in SRC


def test_no_live_card_names_the_next_market_day_only():
    assert "THE NEXT MARKET DAY</b>" in SRC


def test_telegram_failure_is_loud_not_silent():
    assert "TELEGRAM CARD FAILED (non-fatal)" in SRC
