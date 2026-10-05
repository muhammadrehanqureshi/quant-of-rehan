"""
Tests for the portfolio tracker - position management, P&L, and exit rules.
"""

from __future__ import annotations

import json

import pytest

from portfolio import Portfolio, Position
from psx_core import paths


@pytest.fixture
def portfolio_dir(tmp_path, monkeypatch):
    """Redirect data dir to a temp directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data_dir)
    return data_dir


@pytest.fixture
def portfolio(portfolio_dir):
    return Portfolio(portfolio_file=portfolio_dir / "portfolio.json")


# ---------------------------------------------------------------------------
# Position dataclass
# ---------------------------------------------------------------------------

class TestPosition:
    def test_to_dict(self):
        p = Position(symbol="ABOT", entry_price=100.0, entry_date="2026-09-02", target_price=103.0)
        d = p.to_dict()
        assert d["symbol"] == "ABOT"
        assert d["entry_price"] == 100.0
        assert d["status"] == "OPEN"

    def test_from_dict(self):
        d = {
            "symbol": "ABOT",
            "entry_price": 100.0,
            "entry_date": "2026-09-02",
            "target_price": 103.0,
            "status": "OPEN",
        }
        p = Position.from_dict(d)
        assert p.symbol == "ABOT"
        assert p.entry_price == 100.0


# ---------------------------------------------------------------------------
# Portfolio - open / close
# ---------------------------------------------------------------------------

class TestPortfolioOpen:
    def test_open_position(self, portfolio):
        pos = portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        assert pos.status == "OPEN"
        assert pos.symbol == "ABOT"
        assert len(portfolio.open_positions) == 1

    def test_persists_to_disk(self, portfolio_dir):
        p = Portfolio(portfolio_file=portfolio_dir / "portfolio.json")
        p.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        p.save()

        p2 = Portfolio(portfolio_file=portfolio_dir / "portfolio.json")
        assert len(p2.open_positions) == 1
        assert p2.open_positions[0].symbol == "ABOT"

    def test_open_symbols(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        portfolio.open_position("MEBL", 200.0, "2026-09-02", 208.0)
        assert portfolio.open_symbols == {"ABOT", "MEBL"}


class TestPortfolioClose:
    def test_force_close(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        pos = portfolio.force_close("ABOT", 105.0, "2026-09-03", "Manual")
        assert pos.status == "CLOSED"
        assert pos.exit_price == 105.0
        assert pos.pnl == 5.0
        assert pos.pnl_pct == 5.0

    def test_force_close_nonexistent_returns_none(self, portfolio):
        result = portfolio.force_close("NOPE", 100.0, "2026-09-02")
        assert result is None


# ---------------------------------------------------------------------------
# Exit conditions
# ---------------------------------------------------------------------------

class TestExitConditions:
    def test_profit_target_hit(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        exits = portfolio.check_exits({"ABOT": 103.5}, "2026-09-02")
        assert len(exits) == 1
        assert "Rule 3" in exits[0].exit_reason
        assert exits[0].pnl == 3.5

    def test_stop_loss_hit(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        # Rule 7 stop at max_loss_pct=2%: stop = 100 * (1 - 2/100) = 98.0
        exits = portfolio.check_exits({"ABOT": 95.0}, "2026-09-02")
        assert len(exits) == 1
        assert "Rule 7" in exits[0].exit_reason
        assert exits[0].pnl == -5.0

    def test_stop_loss_exactly_at_boundary(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        # 98.0 == stop price, <= triggers the stop.
        exits = portfolio.check_exits({"ABOT": 98.0}, "2026-09-02")
        assert len(exits) == 1
        assert "Rule 7" in exits[0].exit_reason

    def test_stop_loss_independent_of_profit_target(self, tmp_path):
        # Tight target (1%) with default 2% stop: price at 98.9 is above
        # the stop but below target - no exit. Proves the stop no longer
        # widens to the profit-target magnitude.
        p = Portfolio(
            portfolio_file=tmp_path / "pf.json",
            profit_target_low=1.0,
            profit_target_high=1.0,
            max_loss_pct=2.0,
        )
        p.open_position("ABOT", 100.0, "2026-09-02", 101.0)
        exits = p.check_exits({"ABOT": 98.9}, "2026-09-02")
        assert len(exits) == 0

    def test_holding_period_exceeded(self, portfolio, monkeypatch):
        import psx_core.sessions as sessions

        # v0.18.0: Rule 6 (max-hold) fires ONLY when the session is
        # over - intraday polls must never force-close a fresh
        # position (31 of 44 ledger losses were daytime max-hold
        # closes). The close-out clock is mocked to after-hours.
        monkeypatch.setattr(sessions, "is_open", lambda now: False)
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 110.0)
        # 3 days later, price hasn't hit target or stop
        exits = portfolio.check_exits({"ABOT": 101.0}, "2026-09-05")
        assert len(exits) == 1
        assert "Rule 6" in exits[0].exit_reason

    def test_no_exit_within_parameters(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        # Same day - no exit should trigger (1 day = max, so need 0 days).
        exits = portfolio.check_exits({"ABOT": 101.0}, "2026-09-02")
        assert len(exits) == 0

    def test_missing_price_no_exit(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        exits = portfolio.check_exits({}, "2026-09-03")
        assert len(exits) == 0

    def test_multiple_positions_checked(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        portfolio.open_position("MEBL", 200.0, "2026-09-02", 208.0)
        # ABOT hits target, MEBL does not
        exits = portfolio.check_exits({"ABOT": 104.0, "MEBL": 201.0}, "2026-09-02")
        assert len(exits) == 1
        assert exits[0].symbol == "ABOT"

    def test_exit_pnl_percentage(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 104.0)
        exits = portfolio.check_exits({"ABOT": 104.0}, "2026-09-02")
        assert exits[0].pnl_pct == pytest.approx(4.0)

    def test_exit_pnl_negative(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 110.0)
        exits = portfolio.check_exits({"ABOT": 96.0}, "2026-09-02")
        assert exits[0].pnl == pytest.approx(-4.0)


# ---------------------------------------------------------------------------
# Trading days counting
# ---------------------------------------------------------------------------

class TestTradingDays:
    def test_same_day(self):
        assert Portfolio._count_trading_days("2026-09-02", "2026-09-02") == 0

    def test_three_days(self):
        assert Portfolio._count_trading_days("2026-09-02", "2026-09-05") == 3

    def test_invalid_date(self):
        assert Portfolio._count_trading_days("bad", "2026-09-02") == 0


# ---------------------------------------------------------------------------
# Summary and trade log
# ---------------------------------------------------------------------------

class TestSummary:
    def test_empty_portfolio(self, portfolio):
        s = portfolio.summary()
        assert s["open_positions"] == 0
        assert s["closed_positions"] == 0
        assert s["total_pnl"] == 0

    def test_with_positions(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        portfolio.open_position("MEBL", 200.0, "2026-09-02", 208.0)
        portfolio.force_close("ABOT", 105.0, "2026-09-03", "target")
        s = portfolio.summary()
        assert s["open_positions"] == 1
        assert s["closed_positions"] == 1
        assert s["open_symbols"] == ["MEBL"]
        assert s["closed_realised_pnl"] == 5.0

    def test_trade_log(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        portfolio.force_close("ABOT", 105.0, "2026-09-03", "target")
        log = portfolio.trade_log()
        assert len(log) == 1
        assert log[0]["symbol"] == "ABOT"


# ---------------------------------------------------------------------------
# Persistence edge cases
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_load_nonexistent_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        p = Portfolio(portfolio_file=tmp_path / "nope.json")
        assert p.positions == []

    def test_load_corrupt_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        path = tmp_path / "portfolio.json"
        path.write_text("not json!!!", encoding="utf-8")
        p = Portfolio(portfolio_file=path)
        assert p.positions == []

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        path = tmp_path / "sub" / "portfolio.json"
        p = Portfolio(portfolio_file=path)
        p.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        assert path.exists()


# ---------------------------------------------------------------------------
# Daily-loss circuit breaker input
# ---------------------------------------------------------------------------

class TestLosingExitsToday:
    def test_counts_only_same_day_losses(self, portfolio):
        portfolio.open_position("ABOT", 100.0, "2026-09-02", 103.0)
        portfolio.open_position("MEBL", 200.0, "2026-09-02", 206.0)
        portfolio.open_position("OGDC", 300.0, "2026-09-03", 306.0)
        portfolio.force_close("ABOT", 98.0, "2026-09-02", "Stop")   # loss, today
        portfolio.force_close("MEBL", 204.0, "2026-09-02", "Trailing")  # win, today
        portfolio.force_close("OGDC", 294.0, "2026-09-03", "Stop")  # loss, yesterday...
        assert portfolio.losing_exits_today("2026-09-02") == 1
        assert portfolio.losing_exits_today("2026-09-03") == 1

    def test_no_closed_positions_is_zero(self, portfolio):
        assert portfolio.losing_exits_today("2026-09-02") == 0


# ---------------------------------------------------------------------------
# Rule S: stale-trade timeout (v0.9.0, exit-frontier study)
# ---------------------------------------------------------------------------


def _stale_book(tmp_path, minutes=45.0, gate=0.2):
    from portfolio import Portfolio

    return Portfolio(
        portfolio_file=tmp_path / "stale.json",
        stale_trade_minutes=minutes,
        stale_trade_min_gain_pct=gate,
    )


def _open_at(book, entry_ts):
    book.open_position(
        symbol="STC",
        entry_price=100.0,
        entry_date="2026-09-14",
        target_price=100.5,
        entry_ts=entry_ts,
    )


def test_stale_timeout_exits_flat_trade_after_window(tmp_path):
    from datetime import datetime, timedelta, timezone

    book = _stale_book(tmp_path)
    entry = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    _open_at(book, entry.isoformat())
    exits = book.check_exits(
        {"STC": 100.1},
        "2026-09-14",
        now=entry + timedelta(minutes=46),
    )
    assert len(exits) == 1
    assert exits[0].exit_reason.startswith("Rule S")
    assert exits[0].pnl_pct == 0.1


def test_stale_timeout_spares_mover(tmp_path):
    from datetime import datetime, timedelta, timezone

    book = _stale_book(tmp_path)
    entry = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    _open_at(book, entry.isoformat())
    exits = book.check_exits(
        {"STC": 100.3},  # +0.3% > 0.2% gate, below the +0.5% target
        "2026-09-14",
        now=entry + timedelta(minutes=46),
    )
    assert exits == []


def test_stale_timeout_does_not_fire_before_window(tmp_path):
    from datetime import datetime, timedelta, timezone

    book = _stale_book(tmp_path)
    entry = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
    _open_at(book, entry.isoformat())
    exits = book.check_exits(
        {"STC": 100.1},
        "2026-09-14",
        now=entry + timedelta(minutes=10),
    )
    assert exits == []


def test_stale_disabled_when_zero_or_missing_ts(tmp_path):
    from datetime import datetime, timedelta, timezone

    entry = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)

    book = _stale_book(tmp_path, minutes=0)
    _open_at(book, entry.isoformat())
    assert book.check_exits(
        {"STC": 100.1}, "2026-09-14", now=entry + timedelta(minutes=90)
    ) == []

    book2 = _stale_book(tmp_path)
    # A pre-v0.9.0 persisted position has no entry_ts; build it directly
    # (open_position would auto-stamp one).
    from portfolio import Position

    book2.positions.append(
        Position(
            symbol="OLD",
            entry_price=100.0,
            entry_date="2026-09-14",
            target_price=100.5,
        )
    )
    assert book2.check_exits(
        {"OLD": 100.1}, "2026-09-14", now=entry + timedelta(minutes=90)
    ) == []


# ---------------------------------------------------------------------------
# v0.20.3 - touch-based take-profit (the STL 2026-09-18 lesson)
# ---------------------------------------------------------------------------


class TestTouchExits:
    def test_touch_after_entry_fills_the_target(self, portfolio):
        """Target 102, entered when the day-high was 100.5. At the next
        poll the price is back to 101 but the feed's day-high now says
        102.4 - the target PRINTED while we held. A resting limit order
        would have filled at 102.0."""
        pos = portfolio.open_position(
            "STL", 100.0, "2026-09-18", 102.0, high_at_entry=100.5
        )
        exits = portfolio.check_exits(
            {"STL": 101.0}, "2026-09-18", high_prices={"STL": 102.4}
        )
        assert len(exits) == 1
        assert exits[0].exit_price == 102.0  # the limit fill, not the poll
        assert "Rule 3-touch" in exits[0].exit_reason
        assert pos.status == "CLOSED"

    def test_touch_that_predates_entry_is_never_claimed(self, portfolio):
        """THE STL CASE, verbatim: bought 23.80 with the day-high
        already 24.40 - above our 24.28 target. The high has not moved
        since, so the seed blocks the claim: the spike belonged to the
        move we chased, not the trade we made."""
        portfolio.open_position(
            "STL", 23.80, "2026-09-18", 24.28, high_at_entry=24.40
        )
        exits = portfolio.check_exits(
            {"STL": 23.80}, "2026-09-18", high_prices={"STL": 24.40}
        )
        assert exits == []

    def test_unseeded_same_session_touch_is_not_claimed(self, portfolio):
        """No seed recorded (legacy row): a same-session high cannot be
        attributed to post-entry time - the record refuses to invent a
        fill it cannot prove."""
        portfolio.open_position("OLD", 100.0, "2026-09-18", 102.0)
        exits = portfolio.check_exits(
            {"OLD": 101.0}, "2026-09-18", high_prices={"OLD": 102.6}
        )
        assert exits == []

    def test_fresh_session_touch_is_fully_attributable(self, portfolio):
        """EOD-style overnight hold: entered Sep 17, now Sep 18 - the
        whole session is post-entry time, so the day-high alone
        proves the touch."""
        portfolio.open_position("HOLD", 100.0, "2026-09-17", 102.0)
        exits = portfolio.check_exits(
            {"HOLD": 101.0}, "2026-09-18", high_prices={"HOLD": 102.1}
        )
        assert len(exits) == 1
        assert exits[0].exit_price == 102.0

    def test_poll_price_hit_beats_touch_logic(self, portfolio):
        """The ordinary Rule 3 path is untouched: poll price itself at
        the target still closes at the target with the classic reason."""
        portfolio.open_position("P", 100.0, "2026-09-18", 102.0)
        exits = portfolio.check_exits(
            {"P": 102.0}, "2026-09-18", high_prices={"P": 102.0}
        )
        assert len(exits) == 1
        assert "Rule 3:" in exits[0].exit_reason
        assert "touch" not in exits[0].exit_reason

    def test_stop_poll_beats_touch_no_optimistic_fill(self, portfolio):
        """Ambiguity guard: the poll QUOTES at the stop level while the
        session high says the target also printed. The order of those
        two prints inside the blind window is unknowable - the book
        must not book a win it can't prove. The stop family owns the
        verdict: a Rule 7 LOSS, never the 102.0 touch fill."""
        portfolio.open_position(
            "AMB", 100.0, "2026-09-18", 102.0, high_at_entry=100.5
        )
        exits = portfolio.check_exits(
            {"AMB": 98.0},  # 98.0 == stop (2% of 100) -> ambiguous window
            "2026-09-18",
            high_prices={"AMB": 102.4},
        )
        assert len(exits) == 1
        assert exits[0].exit_price == 98.0  # the loss, not the 102 fill
        assert "Rule 7" in exits[0].exit_reason

    def test_two_poll_stop_confirmed_ambiguity_never_books_touch_win(
        self, portfolio_dir
    ):
        """Live confirmation setting (2 polls): the ambiguous first poll
        arms the counter - no exit at all - and the confirming second
        poll closes as the Rule 7 loss."""
        book = Portfolio(
            portfolio_file=portfolio_dir / "p2.json",
            stop_confirmations_required=2,
        )
        book.open_position(
            "AMB", 100.0, "2026-09-18", 102.0, high_at_entry=100.5
        )
        assert book.check_exits(
            {"AMB": 98.0}, "2026-09-18", high_prices={"AMB": 102.4}
        ) == []  # counter armed, no optimistic touch win
        exits = book.check_exits(
            {"AMB": 97.9}, "2026-09-18", high_prices={"AMB": 102.4}
        )
        assert len(exits) == 1
        assert exits[0].exit_price < 100.0
        assert "Rule 7" in exits[0].exit_reason
