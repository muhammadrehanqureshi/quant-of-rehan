"""Buy and sell volume, separated at the wire by one strict law.

The broker feed is a per-symbol snapshot cycle, not a trade tape (see
src/data/feed_capture.py for the measured field map): a row carries the best
bid [3], best ask [4], last traded price [10] and the venue's own running
session total [16]. There is no aggressor flag anywhere in the twenty fields.

So the only honest way to separate buying from selling is to side every
increment of the venue's own counter by the quote that was standing when it
arrived, and to keep that decision forever. This module is that law, and it
has one invariant that no other producer in this repository has:

    buy_volume + sell_volume == volume - baseline, exactly, always

Every increment of the counter is attributed to exactly one side. Nothing is
dropped, nothing is re-attributed later, and nothing is estimated from the
day's range. The rules, in order, first match wins:

  1. last >= ask (ask > 0)              -> BUY   (lifted the offer)
  2. last <= bid (bid > 0)              -> SELL  (hit the bid)
  3. bid < last < ask, last vs midpoint -> BUY above the mid, SELL below
  4. last moved up from the previous row -> BUY, down -> SELL
  5. otherwise                          -> the symbol's last decided side
                                           (counted, never hidden)

Rule 5 is the only place where a side is carried rather than decided, and
the row reports how many increments were carried, so the desk can say so.
The day's change sign (field [7]) is deliberately never consulted: it is the
sign of the change, not the side of a trade, and using it is what produced
the wrong buy and sell numbers this module replaces.

A running total that falls is a day reset or a bad row, never a sale: the
symbol is re-baselined and the fall is not attributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

METHOD_QUOTE_RULE = "quote_rule"
SOURCE_QUOTE_RULE = (
    "every volume increment sided by the wire's own bid/ask at the poll")

#: Rule names, used for the per-symbol counters the desk can display.
RULE_ASK = "at_ask"
RULE_BID = "at_bid"
RULE_ABOVE_MID = "above_mid"
RULE_BELOW_MID = "below_mid"
RULE_UP = "tick_up"
RULE_DOWN = "tick_down"
RULE_CARRIED = "carried"
RULE_RESET = "reset"


def _number(value) -> float | None:
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


@dataclass
class SymbolFlow:
    """One symbol's running, never-retracted side separation."""

    symbol: str
    baseline: int = 0
    buy: int = 0
    sell: int = 0
    rules: dict = field(default_factory=dict)
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    side: str | None = None

    def observe(self, price, bid, ask, volume) -> None:
        last = _number(price)
        best_bid = _number(bid)
        best_ask = _number(ask)
        total = _number(volume)
        previous_price = self.last_price
        self.last_price = last if last is not None else self.last_price
        self.bid = best_bid if best_bid and best_bid > 0 else self.bid
        self.ask = best_ask if best_ask and best_ask > 0 else self.ask
        if last is None or total is None or total < 0:
            return
        total = int(total)
        if self.volume is None:
            # The first running total this process sees is the baseline: the
            # shares traded before it were never observed and are not ours to
            # side. From here on every increment is attributed.
            self.volume = total
            self.baseline = total
            return
        delta = total - self.volume
        if delta < 0:
            self._count(RULE_RESET)
            self.volume = total
            self.baseline += total
            return
        if delta == 0:
            return
        rule, side = self._side(last, previous_price)
        if side == "B":
            self.buy += delta
        else:
            self.sell += delta
        self._count(rule)
        self.side = side
        self.volume = total

    def _side(self, last: float, previous_price: float | None):
        if self.ask and self.ask > 0 and last >= self.ask:
            return RULE_ASK, "B"
        if self.bid and self.bid > 0 and last <= self.bid:
            return RULE_BID, "S"
        if (self.bid and self.ask and 0 < self.bid < self.ask):
            mid = (self.bid + self.ask) / 2.0
            if last > mid:
                return RULE_ABOVE_MID, "B"
            if last < mid:
                return RULE_BELOW_MID, "S"
        if previous_price is not None and last > previous_price:
            return RULE_UP, "B"
        if previous_price is not None and last < previous_price:
            return RULE_DOWN, "S"
        return RULE_CARRIED, (self.side or "B")

    def _count(self, rule: str) -> None:
        self.rules[rule] = self.rules.get(rule, 0) + 1

    def payload(self) -> dict:
        return {
            "buy_volume": int(self.buy),
            "sell_volume": int(self.sell),
            "split_volume": int(self.buy + self.sell),
            "split_method": METHOD_QUOTE_RULE,
            "split_source": SOURCE_QUOTE_RULE,
            "flow_baseline": int(self.baseline),
            "flow_rules": dict(sorted(self.rules.items())),
        }


class QuoteFlow:
    """Every symbol's strict separation, fed one observed row at a time."""

    def __init__(self) -> None:
        self.symbols: dict[str, SymbolFlow] = {}

    def observe(self, quote: dict) -> dict:
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            return quote
        flow = self.symbols.get(symbol)
        if flow is None:
            flow = self.symbols[symbol] = SymbolFlow(symbol)
        flow.observe(quote.get("price"), quote.get("bid"), quote.get("ask"),
                     quote.get("volume"))
        quote.update(flow.payload())
        return quote

    def observe_many(self, quotes) -> list:
        return [self.observe(quote) for quote in quotes or []
                if isinstance(quote, dict)]

    def seed(self, rows) -> int:
        """Adopt the relay's own day pair so a restarted capture continues.

        The cloud starts a capture process per cycle. Without a seed each
        process would re-baseline at the current total and the day's pair
        would restart from zero, which the relay's clamp would then have to
        paper over. A row whose stored method is quote_rule carries the
        wire-sided pair from the day so far, so it is adopted exactly; any
        other row seeds the total only, as an unattributed baseline that is
        counted but never sided.
        """
        adopted = 0
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                volume = int(float(str(row.get("volume")).replace(",", "")))
            except (TypeError, ValueError):
                continue
            flow = SymbolFlow(symbol)
            flow.volume = volume
            flow.baseline = volume
            if row.get("split_method") == METHOD_QUOTE_RULE:
                try:
                    buy = int(float(row.get("buy_volume")))
                    sell = int(float(row.get("sell_volume")))
                except (TypeError, ValueError):
                    buy = sell = -1
                if buy >= 0 and sell >= 0 and buy + sell == volume:
                    flow.buy, flow.sell = buy, sell
                    flow.baseline = 0
                    adopted += 1
            self.symbols[symbol] = flow
        return adopted
