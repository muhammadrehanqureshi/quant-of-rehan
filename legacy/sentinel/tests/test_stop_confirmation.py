"""v2.0.2 stop-confirmation contract (panel-duel backed).

The 85-candidate, 5-session duel (logs/sim_exits_15m.py) showed
2-poll confirmation beats immediate stop exits on every metric at the
real cloud cadence. These tests pin the mechanism:

  * confirmation applies ONLY to stop-family exits (Rule 7 / Rule T);
  * profit-target and time exits fire immediately;
  * recovery above the stop resets the counter;
  * the counter persists across polls (file round-trip);
  * stop_confirmations_required=1 is the exact legacy behavior.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from portfolio import Portfolio


def _book(tmp_path, confirm: int) -> Portfolio:
    return Portfolio(
        portfolio_file=tmp_path / "portfolio.json",
        profit_target_low=2.0,
        profit_target_high=3.0,
        max_holding_days=1,
        max_loss_pct=1.5,
        trailing_stop_pct=0.5,
        trailing_stop_activation_pct=1.0,
        stop_confirmations_required=confirm,
    )


def _open(book: Portfolio, price: float = 100.0):
    book.open_position(
        symbol="TEST",
        entry_price=price,
        entry_date="2026-09-18",
        target_price=price * 1.02,
        entry_ts=datetime(2026, 9, 18, 4, 0, tzinfo=timezone.utc).isoformat(),
    )


def test_stop_waits_two_polls_then_fires(tmp_path):
    book = _book(tmp_path, confirm=2)
    _open(book)
    d = "2026-09-18"

    # Poll 1: below the 1.5% stop -> held for confirmation.
    exits = book.check_exits({"TEST": 98.0}, d)
    assert exits == []
    pos = book.positions[0]
    assert pos.status == "OPEN"
    assert pos.stop_confirm_count == 1

    # Poll 2: still below -> confirmed, closes.
    exits = book.check_exits({"TEST": 98.2}, d)
    assert len(exits) == 1
    assert exits[0].status == "CLOSED"
    assert "Rule 7" in exits[0].exit_reason


def test_recovery_resets_counter(tmp_path):
    book = _book(tmp_path, confirm=2)
    _open(book)
    d = "2026-09-18"

    book.check_exits({"TEST": 98.0}, d)  # below stop: count = 1
    book.check_exits({"TEST": 99.5}, d)  # recovery: count -> 0
    book.check_exits({"TEST": 98.0}, d)  # below again: count = 1
    exits = book.check_exits({"TEST": 98.1}, d)  # second sight: fires
    assert len(exits) == 1


def test_profit_target_fires_immediately(tmp_path):
    book = _book(tmp_path, confirm=2)
    _open(book)
    exits = book.check_exits({"TEST": 102.5}, "2026-09-18")
    assert len(exits) == 1
    assert "Rule 3" in exits[0].exit_reason


def test_counter_persists_across_round_trip(tmp_path):
    f = tmp_path / "portfolio.json"
    book = _book(tmp_path, confirm=2)
    _open(book)
    book.check_exits({"TEST": 98.0}, "2026-09-18")

    reloaded = Portfolio(
        portfolio_file=f,
        max_loss_pct=1.5,
        trailing_stop_pct=0.5,
        trailing_stop_activation_pct=1.0,
        stop_confirmations_required=2,
    )
    pos = reloaded.positions[0]
    assert pos.stop_confirm_count == 1

    exits = reloaded.check_exits({"TEST": 98.1}, "2026-09-18")
    assert len(exits) == 1


def test_confirm_1_is_legacy_immediate(tmp_path):
    book = _book(tmp_path, confirm=1)
    _open(book)
    exits = book.check_exits({"TEST": 98.0}, "2026-09-18")
    assert len(exits) == 1
    assert "Rule 7" in exits[0].exit_reason


def test_trailing_stop_also_confirmed(tmp_path):
    book = _book(tmp_path, confirm=2)
    _open(book, price=100.0)
    d = "2026-09-18"
    # Activate the trail (+1%) and ratchet it.
    book.check_exits({"TEST": 101.2}, d)
    assert book.positions[0].trailing_stop_price is not None
    # First poll below the trailed stop (101.2*0.995 ~= 100.69): held.
    exits = book.check_exits({"TEST": 100.5}, d)
    assert exits == []
    assert book.positions[0].stop_confirm_count == 1
    # Trailing level survives the pending window (must stay armed).
    assert book.positions[0].trailing_stop_price is not None
    # Second poll below: confirmed Rule T exit.
    exits = book.check_exits({"TEST": 100.4}, d)
    assert len(exits) == 1
    assert "Rule T" in exits[0].exit_reason


def test_config_knob_round_trip(tmp_path):
    cfg = json.loads(
        (Path(__file__).resolve().parents[1] / "config.json").read_text()
    )
    assert cfg["stop_confirmations_required"] == 2
