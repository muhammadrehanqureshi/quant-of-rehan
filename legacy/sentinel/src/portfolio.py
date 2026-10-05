"""
PSX KMIALL BOT
Portfolio tracker - position management, P&L, and rule enforcement.

What this does
--------------
Tracks open and closed positions, computes unrealised and realised P&L,
and enforces exit rules that the decision engine cannot enforce on its own:

  Rule 3 - profit target (1%-4%)
  Rule 6 - maximum 3-trading-day holding period

The tracker does not talk to any broker. It is a bookkeeping layer that
records what the decision engine decided and marks positions as closed
when exit conditions are met. The broker integration sits on top of this.

Storage
-------
Positions are persisted to data/portfolio.json as a list of JSON objects.
One file, append-safe via atomic write. The tracker reloads from disk on
every instantiation, so it is safe to use from short-lived scripts.

Usage
-----
    from psx_core import paths
    paths.bootstrap_import_path()

    from portfolio import Portfolio, Position

    portfolio = Portfolio()

    # Record an entry.
    portfolio.open_position(
        symbol="EFERT",
        entry_price=100.0,
        entry_date="2026-09-02",
        target_price=103.0,
    )

    # Check exit conditions against current prices.
    exits = portfolio.check_exits(current_prices={"EFERT": 104.5}, current_date="2026-09-02")

    # Persist.
    portfolio.save()
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from psx_core import paths


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

@dataclass
class Position:
    """One open or closed position."""

    symbol: str
    entry_price: float
    entry_date: str  # YYYY-MM-DD
    target_price: float
    status: str = "OPEN"  # OPEN | CLOSED
    exit_price: float | None = None
    exit_date: str | None = None
    # Wall-clock exit instant (UTC ISO, v2.0.1): the delivery ledger
    # keys on it and the status email shows it. Positions closed
    # before v2.0.1 lack it; every new close stamps it.
    exit_ts: str | None = None
    # v2.0.2 stop-confirmation state: consecutive polls with price at
    # or below the stop. Reset whenever price recovers above it.
    stop_confirm_count: int = 0
    exit_reason: str = ""
    pnl: float | None = None
    pnl_pct: float | None = None
    # v0.16.5: the same trade NET of Mr. Rehan's real cost stack
    # (commission per price band, SST, levies, 15% CGT). The gross
    # figure above is kept for comparability with the replay/sweep.
    pnl_net_pct: float | None = None
    trading_days_held: int = 0
    trailing_stop_price: float | None = None
    # Wall-clock entry instant (UTC ISO) for the stale-trade timeout.
    # Positions created before v0.9.0 lack it; the stale rule skips
    # them rather than guessing an age.
    entry_ts: str | None = None
    # v2.1.0 entry context - what the engine knew at pick time, stored
    # so the ledger can finally be studied feature-by-outcome. Rows
    # from before v2.1.0 carry None and the analyses skip them.
    entry_score: float | None = None
    entry_change_pct: float | None = None  # % above prior close at entry
    entry_breadth_pct: float | None = None
    # v0.20.3 touch attribution: the DAY HIGH on the entry poll. The
    # feed's high field spans the whole session, so a later poll's
    # high only proves a POST-ENTRY touch if it EXCEEDS this seed (a
    # genuinely new print) - or when the poll lands in a fresh session
    # (EOD overnight holds), where the whole day is post-entry. STL
    # 2026-09-18: day-high 24.40 at entry, target 24.28 - without the
    # seed the rule would have claimed a touch that pre-dated us.
    high_at_entry: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Position:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Portfolio:
    """
    Tracks positions and enforces exit rules.

    Parameters
    ----------
    portfolio_file : Path or None
        Where to persist. Default: data/portfolio.json.
    profit_target_low : float
        Minimum profit target % (rule 3).
    profit_target_high : float
        Maximum profit target % (rule 3).
    max_holding_days : int
        Maximum trading-day holding period (rule 6).
    """

    def __init__(
        self,
        portfolio_file: Path | None = None,
        profit_target_low: float = 2.0,
        profit_target_high: float = 3.0,
        max_holding_days: int = 1,
        capital: float = 1_000_000,
        position_size_pct: float = 10.0,
        max_loss_pct: float = 2.0,
        trailing_stop_pct: float = 0.5,
        trailing_stop_activation_pct: float = 1.0,
        stale_trade_minutes: float = 0.0,
        stale_trade_min_gain_pct: float = 0.2,
        stop_confirmations_required: int = 1,
    ) -> None:
        # AIRTIGHT (v2.1.1): a default-constructed Portfolio inside the
        # test suite once opened the LIVE book and appended TEST rows to
        # production data (found 2026-09-18: three TEST positions in the
        # owner's real ledger). Under pytest, the default now resolves
        # to a throwaway path instead of the production book - tests
        # must either pass an explicit path or hit the sandbox, never
        # the owner's real trade history.
        if portfolio_file is not None:
            self.portfolio_file = portfolio_file
        elif "PYTEST_CURRENT_TEST" in os.environ:
            self.portfolio_file = paths.DATA_DIR / "portfolio.test-sandbox.json"
        else:
            self.portfolio_file = paths.DATA_DIR / "portfolio.json"
        self.profit_target_low = profit_target_low
        self.profit_target_high = profit_target_high
        self.max_holding_days = max_holding_days
        self.capital = capital
        self.position_size_pct = position_size_pct
        # Rule 7: hard stop-loss. Independent of the profit target so a
        # tight 2% target does not silently widen risk to 3%.
        self.max_loss_pct = max_loss_pct
        # v2.0.2: consecutive-poll stop confirmation. The panel duel
        # (85 candidates, 5 sessions, logs/sim_exits_15m.py): 2-pass
        # confirmation beat immediate exits on every metric - win
        # 25.7->33.8%, avg net -1.40->-1.37, worst session -57.8->-55.3
        # - because single-poll trips on thin-name bid/ask bounce.
        # 1 = off (immediate), the ship value is config-driven.
        self.stop_confirmations_required = max(1, int(stop_confirmations_required))
        # Trailing stop: once the position is in profit by
        # trailing_stop_activation_pct, the stop loss trails the
        # price up by trailing_stop_pct. Trend-following exit -
        # let winners run, lock in gains when the trend reverses.
        self.trailing_stop_pct = trailing_stop_pct
        self.trailing_stop_activation_pct = trailing_stop_activation_pct
        # Stale-trade timeout (v0.9.0, exit-frontier study): this bot's
        # picks pop early or fade - the measured frontier showed a
        # 45-minute stale exit converts slow bleeds into scratches and
        # lifts the ledger from -1.26%/trade to roughly breakeven
        # without touching a single entry. 0 disables the rule.
        self.stale_trade_minutes = stale_trade_minutes
        self.stale_trade_min_gain_pct = stale_trade_min_gain_pct
        self.positions: list[Position] = []
        self._load()

    # -- Persistence --------------------------------------------------------

    def _load(self) -> None:
        if not self.portfolio_file.exists():
            self.positions = []
            return
        try:
            raw = json.loads(self.portfolio_file.read_text(encoding="utf-8"))
            self.positions = [Position.from_dict(p) for p in raw]
        except (json.JSONDecodeError, KeyError, TypeError):
            self.positions = []

    def save(self) -> None:
        self.portfolio_file.parent.mkdir(parents=True, exist_ok=True)
        data = [p.to_dict() for p in self.positions]
        self.portfolio_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # -- Open positions ------------------------------------------------------

    @property
    def open_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "OPEN"]

    @property
    def closed_positions(self) -> list[Position]:
        return [p for p in self.positions if p.status == "CLOSED"]

    @property
    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.open_positions}

    def losing_exits_today(self, current_date: str) -> int:
        """
        How many positions exited at a loss on this trading date.

        The daily-loss circuit breaker's input: repeated losing exits
        within one session mean the tape is not what the entry filters
        believed, and further entries that day compound the mistake.
        """
        return sum(
            1
            for p in self.closed_positions
            if p.exit_date == current_date and (p.pnl or 0.0) < 0
        )

    def open_position(
        self,
        symbol: str,
        entry_price: float,
        entry_date: str,
        target_price: float,
        entry_ts: str | None = None,
        entry_score: float | None = None,
        entry_change_pct: float | None = None,
        entry_breadth_pct: float | None = None,
        high_at_entry: float | None = None,
    ) -> Position:
        """
        Record a new position. The decision engine calls this when it
        decides to ENTER.

        ``entry_ts`` is the UTC instant of the entry decision; the
        stale-trade timeout measures holding time from it.
        """
        position = Position(
            symbol=symbol,
            entry_price=entry_price,
            entry_date=entry_date,
            target_price=target_price,
            # v2.0.2: the trail must be EARNED, not pre-armed. It used
            # to initialize at entry*(1-trail%) - inert under the old
            # enforcement quirk, but a live -0.5% stop once the armed
            # level is enforced at every price. It arms when the
            # position first gains trailing_stop_activation_pct.
            trailing_stop_price=None,
            entry_ts=entry_ts or datetime.now(timezone.utc).isoformat(),
            entry_score=entry_score,
            entry_change_pct=entry_change_pct,
            entry_breadth_pct=entry_breadth_pct,
            high_at_entry=high_at_entry,
        )
        self.positions.append(position)
        self.save()
        return position

    # -- Exit logic ---------------------------------------------------------

    def check_exits(
        self,
        current_prices: dict[str, float],
        current_date: str,
        now: datetime | None = None,
        high_prices: dict[str, float] | None = None,
    ) -> list[Position]:
        """
        Check all open positions against current prices and dates.
        Returns the list of positions that were closed in this call.

        Exit conditions (checked in order):
          0. TOUCH (v0.20.3): the session high reached the target at a
             moment the 15-minute polls never saw - and the touch is
             ATTRIBUTABLE to post-entry time (a new day-high beyond
             the entry-poll seed, or a fresh session). Closes AT the
             target (a resting limit order fills on the touch).
          1. Price >= target_price (rule 3: profit target)
          2. Price <= entry_price * (1 - max_loss_pct/100) (rule 7:
             hard stop-loss, from config max_loss_pct) - quoted price
             only, with 2-poll confirmation. A stop TOUCH that
             recovered between polls is deliberately NOT claimed:
             the owner trades manually from signals, so only sustained
             quoted weakness would have taken him out.
          3. Trading days held >= max_holding_days (rule 6)
        """
        exits: list[Position] = []
        dirty = False  # confirmation counters must persist across polls

        for position in self.open_positions:
            current_price = current_prices.get(position.symbol)
            if current_price is None:
                continue

            # Update trading days held.
            position.trading_days_held = self._count_trading_days(
                position.entry_date, current_date
            )

            # v0.20.3 Rule 3-touch. Attribution: a poll in a FRESH
            # session (entry on an earlier day) owns the whole day's
            # high; a same-session poll must see a high BEYOND the
            # entry-poll seed to prove the print happened while we
            # held. Missing seed -> same-session touches unverifiable
            # -> not claimed (the record never invents fills).
            new_high = (high_prices or {}).get(position.symbol)
            fresh_session = position.entry_date != current_date
            attributable = fresh_session or (
                position.high_at_entry is not None
                and position.target_price > position.high_at_entry
            )
            # Ambiguity guard (v0.20.3): if THIS poll quotes at/below
            # the stop level, the blind window behind the touch also
            # contained a stop print - the order of the two prints is
            # unknowable at 15-minute sight. We never book an optimistic
            # win we can't prove: fall through to the stop family, whose
            # 2-poll confirmation owns the verdict.
            stop_level = position.entry_price * (
                1.0 - self.max_loss_pct / 100.0
            )
            ambiguous_touch = current_price <= stop_level
            if (
                position.target_price
                and attributable
                and not ambiguous_touch
                and isinstance(new_high, (int, float))
                and new_high >= position.target_price
            ):
                self._close_position(
                    position,
                    position.target_price,
                    current_date,
                    (
                        f"Rule 3-touch: target filled on a touch "
                        f"(session high {new_high:.2f} >= target "
                        f"{position.target_price:.2f}; poll price "
                        f"{current_price:.2f})"
                    ),
                )
                exits.append(position)
                continue

            exit_reason = self._check_exit_conditions(
                position, current_price, current_date, now=now
            )

            # v2.0.2: consecutive-poll stop confirmation. Stop-family
            # reasons (bid/ask bounce is the enemy - the panel duel
            # says 2-pass confirmation beats immediate exits) must
            # hold across N polls; profit/time exits close at once.
            # Recovery above the stop resets the counter.
            if (
                exit_reason
                and self.stop_confirmations_required > 1
                and (exit_reason.startswith("Rule 7:") or exit_reason.startswith("Rule T:"))
            ):
                position.stop_confirm_count += 1
                dirty = True
                if position.stop_confirm_count < self.stop_confirmations_required:
                    continue  # first sight - wait for the next poll
            elif not exit_reason:
                if position.stop_confirm_count:
                    dirty = True
                position.stop_confirm_count = 0

            if exit_reason:
                position.stop_confirm_count = 0
                self._close_position(position, current_price, current_date, exit_reason)
                exits.append(position)

        if exits or dirty:
            self.save()

        return exits

    def force_close(
        self,
        symbol: str,
        exit_price: float,
        exit_date: str,
        reason: str = "Manual close",
    ) -> Position | None:
        """Force-close a position (e.g. end-of-day cleanup)."""
        for position in self.open_positions:
            if position.symbol == symbol:
                self._close_position(position, exit_price, exit_date, reason)
                self.save()
                return position
        return None

    def _check_exit_conditions(
        self,
        position: Position,
        current_price: float,
        current_date: str,
        now: datetime | None = None,
    ) -> str | None:
        """Return the exit reason, or None if no exit is triggered.

        Trailing stop (PSX trend-following): once the position is
        in profit by trailing_stop_activation_pct, the stop loss
        trails the price up by trailing_stop_pct. This lets winners
        run while locking in gains when the trend reverses.
        """
        # Rule 3: profit target hit.
        if position.target_price and current_price >= position.target_price:
            return (
                f"Rule 3: profit target reached "
                f"({current_price:.2f} >= {position.target_price:.2f})"
            )

        # Trailing stop: trend-following exit.
        # Activate once the position gains trailing_stop_activation_pct.
        pnl_pct = (current_price / position.entry_price - 1.0) * 100.0
        if pnl_pct >= self.trailing_stop_activation_pct:
            # Trail the stop loss up as the price rises.
            new_stop = current_price * (1.0 - self.trailing_stop_pct / 100.0)
            if position.trailing_stop_price is None:
                position.trailing_stop_price = new_stop
            else:
                # Only move the stop up, never down.
                position.trailing_stop_price = max(
                    position.trailing_stop_price, new_stop
                )

        # v2.0.2 fix (caught by the confirmation tests): an armed trail
        # is enforced at EVERY price level. Previously the check only
        # ran while pnl >= activation, so a drop through the armed
        # level below +1% silently rode the position down to the hard
        # stop - the "locked" profit was not locked.
        if position.trailing_stop_price is not None:
            # If the hard stop is higher than the trailing stop, use it.
            hard_stop = position.entry_price * (
                1.0 - self.max_loss_pct / 100.0
            )
            effective_stop = max(position.trailing_stop_price, hard_stop)
            if current_price <= effective_stop:
                reason = f"Rule T: trailing stop triggered "
                f"({current_price:.2f} <= {effective_stop:.2f}, "
                f"trailing {self.trailing_stop_pct:.1f}%)"
                # v2.0.2: the stop level itself stays armed while the
                # confirmation window runs; _close_position nulls it.
                return reason

        # Rule 7: hard stop-loss (max_loss_pct from config, default 2%).
        stop_price = position.entry_price * (1.0 - self.max_loss_pct / 100.0)
        if current_price <= stop_price:
            return (
                f"Rule 7: stop-loss triggered "
                f"({current_price:.2f} <= {stop_price:.2f}, "
                f"-{self.max_loss_pct:.1f}%)"
            )

        # Rule S: stale-trade timeout (v0.9.0, exit-frontier study).
        # A position that has gone nowhere after the timeout window is
        # harvesting decay, not edge: exit at market and recycle the
        # slot. Skipped when disabled (0), or when the entry instant is
        # unknown (pre-v0.9.0 positions).
        if self.stale_trade_minutes > 0 and position.entry_ts:
            ref = now or datetime.now(timezone.utc)
            try:
                entered = datetime.fromisoformat(position.entry_ts)
                if entered.tzinfo is None:
                    entered = entered.replace(tzinfo=timezone.utc)
                minutes_held = (ref - entered).total_seconds() / 60.0
            except (ValueError, TypeError):
                minutes_held = None
            if (
                minutes_held is not None
                and minutes_held >= self.stale_trade_minutes
                and pnl_pct < self.stale_trade_min_gain_pct
            ):
                return (
                    f"Rule S: stale trade timeout "
                    f"({minutes_held:.0f} min held, "
                    f"{pnl_pct:+.2f}% < "
                    f"{self.stale_trade_min_gain_pct:.1f}% gate)"
                )

        # Rule 6: holding period exceeded - ONLY when the session is
        # actually over (v0.18.0). The 44-trade forensics: 31 of 44
        # trades died on max-hold with 1 win (3%) because the gate ran
        # at every poll - a position opened at 10:00 was force-closed
        # at the very next midnight pass, converting time-in-market
        # into losses. Same-day EOD closes won 7x more than max-hold
        # closes, so the book now closes INTRAday and holds only
        # through the close->open window when the exit checker is
        # asleep.
        from psx_core import sessions as _sessions
        try:
            session_open = _sessions.is_open(now or datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001 - unknown clock: default open
            session_open = True
        days = self._count_trading_days(position.entry_date, current_date)
        if not session_open and days >= self.max_holding_days:
            return (
                f"Rule 6: maximum holding period reached "
                f"({days} days >= {self.max_holding_days})"
            )

        return None

    def _close_position(
        self,
        position: Position,
        exit_price: float,
        exit_date: str,
        reason: str,
    ) -> None:
        position.status = "CLOSED"
        # Wall-clock exit instant: the delivery ledger keys on it, so a
        # missing stamp can collide two same-symbol exits (and the
        # status email shows "when" as -). Stamped on every close.
        if not position.exit_ts:
            position.exit_ts = datetime.now(timezone.utc).isoformat()
        position.exit_price = exit_price
        position.exit_date = exit_date
        position.exit_reason = reason
        position.pnl = round(exit_price - position.entry_price, 4)
        if position.entry_price > 0:
            position.pnl_pct = round(
                (exit_price / position.entry_price - 1.0) * 100.0, 4
            )
            try:
                import exit_frontier

                position.pnl_net_pct = round(
                    exit_frontier.net_pnl_pct(
                        position.entry_price, exit_price
                    ),
                    4,
                )
            except Exception:  # noqa: BLE001 - gross is still recorded
                position.pnl_net_pct = None
        position.trailing_stop_price = None

    @staticmethod
    def _count_trading_days(entry_date: str, current_date: str) -> int:
        """
        Count the number of calendar days between two dates.
        True PSX trading-day counting would exclude weekends and holidays,
        but with only calendar dates available this is a reasonable
        approximation. The decision engine's rule 6 threshold accounts
        for this.
        """
        try:
            d1 = date.fromisoformat(entry_date)
            d2 = date.fromisoformat(current_date)
            return (d2 - d1).days
        except (ValueError, TypeError):
            return 0

    # -- Reporting ----------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Portfolio summary for logging and reports."""
        open_pnl = sum(
            (p.exit_price or p.entry_price) - p.entry_price
            for p in self.open_positions
        )
        closed_pnl = sum(
            p.pnl for p in self.closed_positions if p.pnl is not None
        )
        return {
            "open_positions": len(self.open_positions),
            "closed_positions": len(self.closed_positions),
            "open_symbols": sorted(self.open_symbols),
            "open_unrealised_pnl": round(open_pnl, 2),
            "closed_realised_pnl": round(closed_pnl, 2),
            "total_pnl": round(open_pnl + closed_pnl, 2),
        }

    def trade_log(self) -> list[dict[str, Any]]:
        """All closed trades as a list of dicts, newest first."""
        return [
            p.to_dict()
            for p in sorted(
                self.closed_positions,
                key=lambda p: p.exit_date or "",
                reverse=True,
            )
        ]
