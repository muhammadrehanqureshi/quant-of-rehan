#!/usr/bin/env python3
"""How the market status and the stock card are fetched, validated, rendered.

This is the usage example for the phone card: it answers the two questions
the app answers, using the same modules the app's data comes from.

    1. WHAT STATE IS THE MARKET IN?  src/data/sessions.py knows, as bands:
       Monday to Thursday one session, Friday two with the exchange's midday
       break, weekends and holidays closed. `market_state()` returns the phase
       (CLOSED, PRE_OPEN, WARMUP, OPEN, BREAK, POST_CLOSE), the live band and
       the next band edge. The app renders that answer; it never builds a
       market time of its own, which is why a phone in another timezone, or a
       PC whose clock has drifted, cannot disagree with the exchange.

    2. WHAT IS THE MARKET DOING?  src/data/market_snapshot.py reads the PSX
       Data Portal's own pages for the KSE100 index and the KMIALLSHR volume
       leaders, and src/data/tick_volume.py adds a genuine buy/sell split when
       a broker tick capture exists for the session.

Every field is validated before it is rendered: a snapshot with a missing
index, a negative volume, a percentage that is not a number, a split that is
half present, or an unknown phase is refused with the reason, because a card
that prints a wrong number is worse than a card that prints none.

Usage:
    python examples/market_card.py                # live: read the portal
    python examples/market_card.py --offline      # validate a fixture, no network
    python examples/market_card.py --at 2026-10-09T14:23   # phase at an instant
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    KARACHI, market_state, session_window_text,
)


class CardError(ValueError):
    """A card that cannot be trusted is refused, never rendered."""


@dataclass(frozen=True)
class Leader:
    symbol: str
    volume: int
    price: float | None
    change_pct: float | None
    buy: int | None
    sell: int | None

    @property
    def has_split(self) -> bool:
        return self.buy is not None and self.sell is not None

    def line(self) -> str:
        parts = [self.symbol]
        if self.has_split:
            parts.append(f"B={self.buy:,}")
            parts.append(f"S={self.sell:,}")
            parts.append(f"T={self.volume:,}")
        else:
            parts.append(f"T={self.volume:,}")
        if self.price is not None:
            parts.append(f"Rs {self.price:,.2f}")
        if self.change_pct is not None:
            arrow = "up" if self.change_pct >= 0 else "down"
            parts.append(f"{arrow} {abs(self.change_pct):.2f}%")
        return "   ".join(parts)


@dataclass(frozen=True)
class Card:
    phase: str
    open_now: bool
    window: str
    index_value: float | None
    index_pct: float | None
    members: int | None
    leaders: tuple[Leader, ...]
    split_basis: str
    notes: tuple[str, ...]

    @property
    def is_live(self) -> bool:
        return self.open_now

    def render(self) -> str:
        lines = [f"MARKET NOW   {self.phase}   {self.window}"]
        if self.index_value is None:
            lines.append("KSE100  not available right now")
        else:
            sign = "+" if (self.index_pct or 0) >= 0 else "-"
            lines.append(f"KSE100  {self.index_value:,.2f}   "
                         f"{sign}{abs(self.index_pct or 0):.2f}%")
        if not self.leaders:
            lines.append("no volume leaders to show")
        for position, leader in enumerate(self.leaders, start=1):
            lines.append(f"{position}. {leader.line()}")
        if self.members:
            lines.append(f"   volume: top {len(self.leaders)} of "
                         f"{self.members} KMIALLSHR members")
        if not self.is_live:
            lines.append("   OFFLINE: no session is live at this instant")
        if self.split_basis:
            lines.append(f"   {self.split_basis}")
        for note in self.notes:
            lines.append(f"   note: {note}")
        return "\n".join(lines)


def _number(value: Any, field: str, *, low: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CardError(f"{field} is not a number: {value!r}") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise CardError(f"{field} is not finite: {value!r}")
    if low is not None and number < low:
        raise CardError(f"{field} is below {low}: {number}")
    return number


def _count(value: Any, field: str, *, low: int = 0) -> int | None:
    number = _number(value, field)
    if number is None:
        return None
    if number != int(number):
        raise CardError(f"{field} is not a whole number: {value!r}")
    if int(number) < low:
        raise CardError(f"{field} is below {low}: {value!r}")
    return int(number)


def validate_leader(row: Any) -> Leader:
    """Validate one leader row. Every refusal names the field it refused."""
    if not isinstance(row, dict):
        raise CardError(f"leader row is {type(row).__name__}, not an object")
    symbol = str(row.get("symbol", "")).strip().upper()
    if not symbol:
        raise CardError("leader row has no symbol")
    volume = _count(row.get("volume"), f"{symbol}.volume", low=0)
    if volume is None:
        raise CardError(f"{symbol} has no volume, so it cannot be ranked")
    buy = _count(row.get("buy_volume"), f"{symbol}.buy_volume", low=0)
    sell = _count(row.get("sell_volume"), f"{symbol}.sell_volume", low=0)
    if (buy is None) != (sell is None):
        # Half a split is not a split: it would print one side as zero.
        raise CardError(f"{symbol} carries only one side of the split")
    if buy is not None and sell is not None and buy + sell > volume * 2:
        raise CardError(f"{symbol} split {buy}+{sell} dwarfs its total {volume}")
    return Leader(
        symbol=symbol, volume=volume,
        price=_number(row.get("price"), f"{symbol}.price", low=0.0),
        change_pct=_number(row.get("change_pct"), f"{symbol}.change_pct"),
        buy=buy, sell=sell,
    )


def validate_card(snapshot: Any) -> Card:
    """Validate a relay or local snapshot into a card that may be rendered."""
    if not isinstance(snapshot, dict):
        raise CardError(f"snapshot is {type(snapshot).__name__}, not an object")
    state = snapshot.get("market_state")
    if not isinstance(state, dict):
        # The relay's older shape: fall back to the boolean, but say so by
        # leaving the phase empty rather than inventing one.
        phase = "OPEN" if snapshot.get("market_open") else ""
    else:
        phase = str(state.get("phase", ""))
        if phase not in ("CLOSED", "PRE_OPEN", "WARMUP", "OPEN", "BREAK",
                         "POST_CLOSE"):
            raise CardError(f"unknown market phase: {phase!r}")
    index = snapshot.get("index") or {}
    leaders = tuple(validate_leader(row)
                    for row in (snapshot.get("top_volume") or ()))
    seen = {leader.symbol for leader in leaders}
    if len(seen) != len(leaders):
        raise CardError("the same symbol appears twice in the leaders")
    return Card(
        phase=phase or "UNKNOWN",
        open_now=bool(snapshot.get("market_open")),
        window=session_window_text(datetime.now(KARACHI).date()),
        index_value=_number(index.get("value"), "index.value", low=0.0),
        index_pct=_number(index.get("change_pct"), "index.change_pct"),
        members=_count(snapshot.get("kmiall_members"), "kmiall_members", low=0),
        leaders=leaders,
        split_basis=str(snapshot.get("volume_split_basis", "") or ""),
        notes=tuple(str(note) for note in (snapshot.get("notes") or ())),
    )


OFFLINE_FIXTURE: dict = {
    "market_open": False,
    "market_state": {"phase": "BREAK", "market_open": False,
                     "trading_day": True,
                     "next_event": {"event": "OPEN",
                                    "at_pk": "2026-10-09 14:32"}},
    "index": {"value": 167089.27, "change_pct": -0.21,
              "as_of": "2026-10-09 16:50:00"},
    "kmiall_members": 313,
    "top_volume": [
        {"symbol": "CNERGY", "volume": 27276548, "price": 12.52,
         "change_pct": 1.049, "buy_volume": None, "sell_volume": None},
        {"symbol": "PRL", "volume": 24123072, "price": 93.07,
         "change_pct": -2.14, "buy_volume": None, "sell_volume": None},
        {"symbol": "TREET", "volume": 22903682, "price": 41.1,
         "change_pct": 0.51, "buy_volume": None, "sell_volume": None},
    ],
    "top_volume_basis": "current session volume, top 3 of 313 KMIALLSHR members",
    "volume_split_basis": ("buy/sell split unavailable: no broker tick capture "
                           "banked for 2026-10-09"),
    "notes": [],
}

BAD_FIXTURES: list[tuple[str, dict]] = [
    ("a negative volume", {**OFFLINE_FIXTURE, "top_volume": [
        {"symbol": "X", "volume": -5}]}),
    ("a percentage that is not a number", {**OFFLINE_FIXTURE, "top_volume": [
        {"symbol": "X", "volume": 10, "change_pct": "up"}]}),
    ("half a split", {**OFFLINE_FIXTURE, "top_volume": [
        {"symbol": "X", "volume": 10, "buy_volume": 5}]}),
    ("an unknown phase", {**OFFLINE_FIXTURE,
                          "market_state": {"phase": "LUNCH"}}),
    ("a duplicated leader", {**OFFLINE_FIXTURE, "top_volume": [
        {"symbol": "X", "volume": 10}, {"symbol": "X", "volume": 9}]}),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fetch, validate and render the card")
    parser.add_argument("--offline", action="store_true",
                        help="validate the built-in fixtures, touch no network")
    parser.add_argument("--at", default=None,
                        help="ISO instant for the phase instead of now")
    args = parser.parse_args(argv)

    # 1. the market state, from the one session law
    moment = datetime.fromisoformat(args.at) if args.at else None
    state = market_state(moment)
    print("market state:")
    print(json.dumps(state, indent=2))

    # 2. the stock data
    if args.offline:
        snapshot = OFFLINE_FIXTURE
        print("\noffline: validating the built-in fixture instead of the portal")
    else:
        from src.data import market_snapshot

        snapshot = market_snapshot.build_snapshot()

    card = validate_card(snapshot)
    print("\n" + card.render())

    if args.offline:
        print("\nrefusals (a card is only as good as what it rejects):")
        for label, broken in BAD_FIXTURES:
            try:
                validate_card(broken)
            except CardError as exc:
                print(f"  refused {label}: {exc}")
            else:
                print(f"  ACCEPTED {label}: that is a bug")
                return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
