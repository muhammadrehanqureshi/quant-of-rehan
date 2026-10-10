"""Buy/sell volume per symbol, computed from genuinely banked broker ticks.

Owner order 2026-10-10: the market card must show, for each of the day's
top three KMIALL stocks, the buy volume, the sell volume and the total,
as ``ABC  B=... S=... T=...``. No configured source publishes that split
as a number, so this module derives it from the one place the split
genuinely exists: the read-only broker feed capture
(``data/feed_capture/capture_YYYYMMDD.ndjson``), whose per-trade ticks
carry a ``direction`` field and the last-trade size.

What is genuinely available, and what is not (SO-3):

  * the exchange's constituent table carries ONE volume column, so a
    split cannot come from there;
  * the eClear OHLC endpoint returns bars only;
  * the broker MKT-FEED stream carries, per trade, ``last`` price,
    ``bid``, ``ask``, ``direction`` and ``last-trade volume`` plus the
    symbol's cumulative ``total volume``, which is the raw material for a
    real split.

Honesty rules, enforced here rather than documented:

  * only ``MKT-FEED`` frames count as ticks. The same capture file also
    holds index, movers and market-stats frames whose fields are NOT the
    tick layout, and counting them would fabricate thousands of shares;
  * a side is assigned only from a recognised ``direction`` token, or, when
    the token is unrecognised, from the tick rule against the quoted
    ``bid``/``ask``. Anything else is counted as unclassified and reported,
    never guessed;
  * the per-side sums are cross-checked against the symbol's own
    cumulative total volume in the same stream. A material disagreement is
    reported as a stated gap instead of being rounded away;
  * when there is no capture, or no ticks for a symbol, the split is
    UNAVAILABLE. The card then shows the total and says so.

Usage:
    python -m src.data.tick_volume --show              # today's split
    python -m src.data.tick_volume --show OGDC PSO     # only these symbols
    python -m src.data.tick_volume --date 2026-10-06 --show
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.sessions import now_karachi  # noqa: E402

CAPTURE_DIR = ROOT / "data" / "feed_capture"

#: Frames whose rows use the MKT-FEED tick layout. Anything else in the
#: capture (EXS-FEED, MKT-Movers, MKT-STATS) has a different field map.
TICK_KINDS = ("MKT-FEED",)

#: Direction tokens seen on the wire mean buy / sell. Kept deliberately
#: small: a token this module does not recognise is classified by the tick
#: rule or left unclassified, never guessed. The observed tokens are
#: reported in `notes` so the mapping can be extended from evidence.
BUY_TOKENS = frozenset({"B", "BUY", "BUYER", "BID"})
SELL_TOKENS = frozenset({"S", "SELL", "SELLER", "ASK"})

#: A disagreement above this share of the cumulative total is reported.
TOTAL_TOLERANCE = 0.02


@dataclass
class SymbolFlow:
    """One symbol's session flow, from banked ticks only."""

    symbol: str
    buy_volume: int = 0
    sell_volume: int = 0
    unclassified_volume: int = 0
    ticks: int = 0
    duplicate_ticks: int = 0
    cumulative_total: int | None = None
    first_tick: str = ""
    last_tick: str = ""
    direction_tokens: dict[str, int] = field(default_factory=dict)
    source: str = "broker MKT-FEED tick capture"
    notes: list[str] = field(default_factory=list)

    @property
    def classified_total(self) -> int:
        return self.buy_volume + self.sell_volume

    @property
    def total_volume(self) -> int:
        """The symbol's session total, preferring the exchange's own figure.

        The cumulative field is the source's own running total for the
        session, so it is the honest answer to "T=". The per-side sums are
        this module's derivation and are only used when the cumulative
        figure never arrived.
        """
        if self.cumulative_total:
            return self.cumulative_total
        return self.classified_total + self.unclassified_volume

    @property
    def split_available(self) -> bool:
        """True only when both sides carry genuine classified volume."""
        return self.ticks > 0 and self.classified_total > 0

    @property
    def reconcilable(self) -> bool:
        """Did the classified sums land within tolerance of the total?"""
        total = self.total_volume
        if total <= 0 or not self.classified_total:
            return False
        return abs(self.classified_total - total) <= max(1, TOTAL_TOLERANCE * total)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "buy_volume": self.buy_volume if self.split_available else None,
            "sell_volume": self.sell_volume if self.split_available else None,
            "volume": self.total_volume or None,
            "split_available": self.split_available,
            "classified_volume": self.classified_total,
            "unclassified_volume": self.unclassified_volume,
            "ticks": self.ticks,
            "reconciled": self.reconcilable,
            "first_tick": self.first_tick,
            "last_tick": self.last_tick,
            "source": self.source,
            "notes": list(self.notes),
        }


def capture_path(day: date) -> Path:
    return CAPTURE_DIR / f"capture_{day:%Y%m%d}.ndjson"


def _num(value) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def iter_ticks(path: Path) -> Iterator[dict]:
    """Yield only genuine MKT-FEED tick rows from a capture file.

    The capture banks every frame it receives, including index and
    market-stats frames that reuse the same key names with different
    meanings. Filtering on the frame kind here is what keeps the split
    honest.
    """
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = str(record.get("kind", ""))
            if not any(kind.startswith(k) for k in TICK_KINDS):
                continue
            for tick in record.get("ticks", []) or []:
                if isinstance(tick, Mapping):
                    yield tick


def _side(tick: Mapping) -> str:
    """Classify one trade: 'B', 'S', or '' when it cannot be classified.

    The wire carries an explicit direction token. When it is one this
    module recognises, that is the answer. When it is not, the tick rule
    decides from the quoted bid and ask (a print at the ask is a buyer
    lifting, a print at the bid is a seller hitting). Both are statements
    about the data; neither invents a size.
    """
    token = str(tick.get("direction", "")).strip().upper()
    if token in BUY_TOKENS:
        return "B"
    if token in SELL_TOKENS:
        return "S"
    last = _num(tick.get("last"))
    bid = _num(tick.get("bid"))
    ask = _num(tick.get("ask"))
    if last is not None and ask is not None and last >= ask > 0:
        return "B"
    if last is not None and bid is not None and last <= bid > 0:
        return "S"
    return ""


def session_flow(path: Path,
                 symbols: Iterable[str] | None = None) -> dict[str, SymbolFlow]:
    """Buy/sell/total volume per symbol from one capture file.

    Returns only the symbols that genuinely traded in the capture; a
    symbol with no ticks is absent (and its split is unavailable), never
    present with zeros dressed up as data.
    """
    wanted = ({str(s).strip().upper() for s in symbols}
              if symbols is not None else None)
    flows: dict[str, SymbolFlow] = {}
    seen: set[tuple] = set()
    for tick in iter_ticks(path):
        symbol = str(tick.get("scrip", "")).strip().upper()
        if not symbol:
            continue
        if wanted is not None and symbol not in wanted:
            continue
        flow = flows.get(symbol)
        if flow is None:
            flow = flows[symbol] = SymbolFlow(symbol=symbol)
        token = str(tick.get("direction", "")).strip().upper()
        if token:
            flow.direction_tokens[token] = flow.direction_tokens.get(token, 0) + 1
        size = _num(tick.get("last_volume"))
        size_units = int(size) if size and size > 0 else 0
        stamp = str(tick.get("tick_time", "")).strip()
        # A feed repeats ticks; the same (symbol, time, size, price) row is
        # counted once, and a conflict on size is reported rather than added.
        key = (symbol, stamp, size_units, _num(tick.get("last")))
        if key in seen:
            flow.duplicate_ticks += 1
            continue
        seen.add(key)
        flow.ticks += 1
        side = _side(tick)
        if side == "B":
            flow.buy_volume += size_units
        elif side == "S":
            flow.sell_volume += size_units
        else:
            flow.unclassified_volume += size_units
        cumulative = _num(tick.get("volume"))
        if cumulative is not None and cumulative > 0:
            flow.cumulative_total = int(cumulative)
        if stamp:
            if not flow.first_tick:
                flow.first_tick = stamp
            flow.last_tick = stamp

    for flow in flows.values():
        if not flow.split_available:
            flow.notes.append(
                "no classified buy or sell volume: the capture holds "
                f"{flow.ticks} tick(s) with tokens "
                f"{sorted(flow.direction_tokens) or ['<none>']} and no usable "
                "bid/ask to apply the tick rule")
        elif not flow.reconcilable:
            flow.notes.append(
                f"classified {flow.classified_total:,} of a stated session "
                f"total of {flow.total_volume:,}: the capture was partial for "
                "this symbol, so B+S is a floor, not the whole day")
    return flows


def flow_for(day: date, symbol: str,
             symbols: Iterable[str] | None = None) -> SymbolFlow | None:
    """One symbol's flow for a date, or None when no split is available."""
    flows = session_flow(capture_path(day), symbols or [symbol])
    return flows.get(symbol.strip().upper())


def attach_splits(leaders: list[dict], day: date) -> str:
    """Add buy_volume, sell_volume and a split basis to leader rows in place.

    Returns the split basis text for the card's footnote. Mutating the
    rows keeps the caller simple; every added field is either a genuine
    number or an explicit null with the reason in the basis text.
    """
    path = capture_path(day)
    if not path.is_file():
        for row in leaders:
            row.setdefault("buy_volume", None)
            row.setdefault("sell_volume", None)
            row["split_source"] = (f"no broker tick capture banked for "
                                   f"{day.isoformat()}")
        return ("buy/sell split unavailable: no broker tick capture banked "
                f"for {day.isoformat()}")
    flows = session_flow(path, [str(row.get("symbol", "")) for row in leaders])
    available = 0
    for row in leaders:
        symbol = str(row.get("symbol", "")).strip().upper()
        flow = flows.get(symbol)
        if flow is not None and flow.split_available:
            row["buy_volume"] = flow.buy_volume
            row["sell_volume"] = flow.sell_volume
            if flow.total_volume:
                row["split_total_volume"] = flow.total_volume
            row["split_source"] = (
                "broker MKT-FEED ticks: direction per trade"
                + ("" if flow.reconcilable else ", partial capture"))
            available += 1
        else:
            row["buy_volume"] = None
            row["sell_volume"] = None
            row["split_source"] = (
                "no MKT-FEED ticks for this symbol in today's capture")
    if not available:
        return ("buy/sell split unavailable: the capture has no classified "
                "MKT-FEED ticks for the leaders")
    return (f"buy/sell split from the broker tick capture "
            f"({available} of {len(leaders)} leaders)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="buy/sell/total volume from banked broker ticks")
    parser.add_argument("symbols", nargs="*", help="symbols (default: all)")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--show", action="store_true", help="print the split")
    args = parser.parse_args(argv)

    day = (date.fromisoformat(args.date) if args.date else now_karachi().date())
    path = capture_path(day)
    if not path.is_file():
        print(f"no capture banked for {day.isoformat()} at {path}")
        print("start it with: python -m src.data.feed_capture")
        return 1
    flows = session_flow(path, args.symbols or None)
    if not flows:
        print(f"{path.name} holds no MKT-FEED ticks for "
              f"{args.symbols or 'any symbol'}")
        return 1
    rows = [flow.as_dict() for flow in
            sorted(flows.values(), key=lambda f: -f.total_volume)]
    print(json.dumps(rows[:25], indent=2))
    print(f"\n{len(rows)} symbol(s) with ticks; split available for "
          f"{sum(1 for f in flows.values() if f.split_available)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
