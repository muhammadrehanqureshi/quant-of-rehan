"""Order flow from the broker snapshot feed: what the wire supports, labelled.

Measured facts this module obeys (2026-10-23 capture: 127,510 REG rows,
311 symbols, 13,120 MKT-FEED frames; the field map lives in
src/data/feed_capture.py and was verified against 5,064 live rows on
2026-10-12):

  * the feed is a per-symbol SNAPSHOT cycle: 24.0s median between two
    observations of the same symbol, and a genuinely new print reaches the
    bank 9s after the venue's own print clock at the median (p90 21s). It is
    not a trade-by-trade tape: only the LAST print of each window is named,
    so print sizes never add up to the venue's volume movement (measured
    median print fidelity 0.42 on 2026-10-13).
  * it carries best bid and ask WITH their resting sizes, one level only.
    A top-of-book imbalance is measurable; a multi-level ladder, depth
    within a percentage of the touch, or price impact per level is not.
  * it carries the venue's cumulative volume and trade counters and its own
    session average price, so traded value is exact (total x average), and
    the buy/sell side of each window is INFERRED from where the closing
    print traded (at the ask, at the bid) or by the tick rule. No aggressor
    flag exists on the wire; nothing here calls an inferred side a venue
    fact.
  * no order ids, no order additions, modifications or cancellations and no
    sequence numbers exist on this wire, so MBO is unavailable, order
    cancellation ratios cannot be built from it, and gap detection is by
    time and by the venue's own counters rather than by sequence arithmetic.

Every feature returned here names its basis and refuses to produce a number
when its input fields are absent (SO-3). This module is research-only: the
scanner does not import it, and no production signal reads it (owner order:
do not modify production trading logic without demonstrated evidence).

Usage (from repo root):
    python -m src.data.order_flow --date 2026-10-23 --show
    python -m src.data.order_flow --file data/feed_capture/capture_20261023.ndjson
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import tick_volume  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402
from src.data import registry  # noqa: E402  (SO-3: the truth source)

KARACHI_OFFSET = timedelta(hours=5)   # SO-8: Karachi, UTC+5, forever

#: What this feed does and does not carry, as one machine-readable statement.
#: A consumer must read this before claiming anything as order flow.
CAPABILITY = {
    "level_1": {
        "status": "VERIFIED AVAILABLE",
        "fields": ["last", "bid", "ask", "bid_size", "ask_size", "volume",
                   "trades", "open", "high", "low", "close", "average"],
    },
    "level_2_mbp": {
        "status": "NOT AVAILABLE",
        "detail": "top of book only: one best bid and one best ask with "
                  "their resting sizes; no price ladder, no depth levels",
    },
    "level_2_mbo": {
        "status": "NOT AVAILABLE",
        "detail": "no order ids, no new/modify/cancel order messages",
    },
    "time_and_sales": {
        "status": "PARTIALLY AVAILABLE",
        "detail": "the last print of each ~24s snapshot window carries its "
                  "price, size and venue print time; intervening prints are "
                  "not named, so print sizes understate the venue's volume "
                  "movement (median print fidelity 0.42 on 2026-10-13)",
    },
    "aggressor_side": {
        "status": "NOT AVAILABLE",
        "detail": "no side flag exists on the wire; the side of a volume "
                  "window is inferred from the closing print's position at "
                  "the ask or bid, then by the tick rule, and is labelled "
                  "inferred everywhere it is reported",
    },
    "order_events": {
        "status": "NOT AVAILABLE",
        "detail": "no order additions, modifications or cancellations",
    },
    "circuit_limits": {
        "status": "PARTIALLY AVAILABLE",
        "detail": "RUCAP / RLCAP / ADDUCAP frames carry per-symbol cap "
                  "prices; their semantics are inferred from the frame "
                  "names and magnitudes, not documented by the venue",
    },
    "market_breadth": {
        "status": "VERIFIED AVAILABLE",
        "detail": "EXS-FEED index groups carry advancing, declining and "
                  "unchanged counts plus session volume and turnover",
    },
    "sequence_numbers": {
        "status": "NOT AVAILABLE",
        "detail": "frames carry no sequence number; gaps are measured by "
                  "time and by the venue's cumulative counters instead",
    },
    "exchange_timestamps": {
        "status": "PARTIALLY AVAILABLE",
        "detail": "the last print carries a seconds-resolution venue time; "
                  "there is no exchange timestamp on the quote itself",
    },
}

#: Feature -> status. A feature is only ever computed when its status is
#: AVAILABLE or INFERRED_LIMITED, and every number says which one it is.
FEATURE_STATUS = {
    "spread": "AVAILABLE",
    "obi_top1": "AVAILABLE",
    "trade_intensity": "AVAILABLE",
    "traded_value": "AVAILABLE",
    "session_vwap": "AVAILABLE",
    "window_vwap": "AVAILABLE",
    "cvd_inferred": "INFERRED_LIMITED",
    "bid_replenishment": "INFERRED_LIMITED",
    "ask_absorption": "INFERRED_LIMITED",
    "depth_within_band": "NOT AVAILABLE",
    "order_cancellations": "NOT AVAILABLE",
    "price_impact_by_level": "NOT AVAILABLE",
}


def footprint_gate() -> dict:
    """What the registry says about genuine footprint data (SO-3).

    src/data/registry.py is the single source of truth for what this system
    genuinely has. It records footprint and Level-2 order flow as
    UNAVAILABLE, which is exactly what this module must respect: what it
    measures is top of book and inferred trade flow on a snapshot wire,
    never a footprint, so its output is labelled research data and no
    engine may present it as order-book depth.
    """
    source = registry.get("footprint")
    return {
        "key": source.key,
        "availability": source.availability.value,
        "detail": source.detail,
        "this_module": ("top of book and inferred trade flow only; no "
                        "ladder, no order events, no aggressor flag"),
    }


def _num(value) -> float | None:
    """A finite float from a wire string, or None. Never a guess."""
    return tick_volume._num(value)


def _clock(value) -> datetime | None:
    """A capture receipt stamp, zone aware, or None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=now_karachi().tzinfo)
    return stamp


def _print_clock(row: Mapping, arrived: datetime | None) -> datetime | None:
    """The venue's own print time, anchored to the snapshot's own date."""
    if arrived is None:
        return None
    text = str(row.get("tick_time", "")).strip()
    try:
        stamp = datetime.strptime(text, "%H:%M:%S")
    except ValueError:
        return None
    return arrived.replace(hour=stamp.hour, minute=stamp.minute,
                           second=stamp.second, microsecond=0)


def flow_snapshots(path: Path,
                   symbols: Iterable[str] | None = None) -> Iterator[dict]:
    """One normalized snapshot per genuinely new observation, in order.

    Consecutive rows with the same running total, trade count, last price
    and print clock are one observation echoed again (measured: 89.8% of
    the 2026-10-23 rows repeat their predecessor), so only the first of the
    run is yielded. Nothing else is dropped: every field keeps the value the
    wire sent, or None.
    """
    wanted = ({str(s).strip().upper() for s in symbols}
              if symbols is not None else None)
    previous: dict[str, tuple] = {}
    for row in tick_volume.iter_ticks(path):
        symbol = str(row.get("scrip", "")).strip().upper().split(":", 1)[0]
        if not symbol:
            continue
        if wanted is not None and symbol not in wanted:
            continue
        if str(row.get("market", "")).strip().upper() != "REG":
            continue
        arrived = _clock(row.get("capture_ts"))
        identity = (_num(row.get("volume")), _num(row.get("trades")),
                    str(row.get("last", "")).strip(),
                    str(row.get("tick_time", "")).strip())
        if previous.get(symbol) == identity:
            continue
        previous[symbol] = identity
        yield {
            "symbol": symbol,
            "capture_ts": arrived.isoformat() if arrived else None,
            "print_ts": (_print_clock(row, arrived).isoformat()
                         if _print_clock(row, arrived) else None),
            "status": str(row.get("status", "")).strip().upper() or None,
            "bid": _num(row.get("bid")),
            "ask": _num(row.get("ask")),
            "bid_size": _num(row.get("bid_size")),
            "ask_size": _num(row.get("ask_size")),
            "last": _num(row.get("last")),
            "last_volume": _num(row.get("last_volume")),
            "trades": _num(row.get("trades")),
            "volume": _num(row.get("volume")),
            "average": _num(row.get("avg")),
            "open": _num(row.get("open")),
            "high": _num(row.get("high")),
            "low": _num(row.get("low")),
            "close": _num(row.get("close")),
        }


def top_of_book_imbalance(bid_size, ask_size) -> float | None:
    """(bid - ask) / (bid + ask) at the touch, or None without both sizes."""
    b, a = _num(bid_size), _num(ask_size)
    if b is None or a is None or b < 0 or a < 0 or (b + a) <= 0:
        return None
    return (b - a) / (b + a)


@dataclass
class SymbolOrderFlow:
    """One symbol's measured flow, every number with its basis."""

    symbol: str
    snapshots: int = 0
    windows: int = 0
    quote_windows: int = 0          # windows whose quote came from venue fields
    gap_windows: int = 0
    unclassified_windows: int = 0
    volume_delta: int = 0
    trades_delta: int = 0
    buy_volume: int = 0             # INFERRED side
    sell_volume: int = 0            # INFERRED side
    unclassified_volume: int = 0
    value_delta: float = 0.0        # venue average price identity
    window_vwaps: list[float] = field(default_factory=list)
    spreads: list[float] = field(default_factory=list)
    spread_bps: list[float] = field(default_factory=list)
    obi_latest: float | None = None
    obi_values: list[float] = field(default_factory=list)
    obi_median: float | None = None
    print_lag_seconds: list[float] = field(default_factory=list)
    bid_replenish_events: int = 0
    bid_consumed_events: int = 0
    ask_absorption_events: int = 0
    ask_consumed_events: int = 0
    session_vwap: float | None = None
    first_capture_ts: str | None = None
    last_capture_ts: str | None = None
    suspended_snapshots: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def cvd(self) -> int | None:
        """Inferred cumulative volume delta (buy minus sell)."""
        if not (self.buy_volume or self.sell_volume):
            return None
        return self.buy_volume - self.sell_volume

    def as_dict(self) -> dict:
        obis = self.obi_median
        return {
            "symbol": self.symbol,
            "snapshots": self.snapshots,
            "windows": self.windows,
            "volume_delta": self.volume_delta,
            "trades_delta": self.trades_delta,
            "traded_value": (round(self.value_delta, 2)
                             if self.volume_delta else None),
            "buy_volume_inferred": (self.buy_volume
                                    if self.buy_volume or self.sell_volume
                                    else None),
            "sell_volume_inferred": (self.sell_volume
                                     if self.buy_volume or self.sell_volume
                                     else None),
            "unclassified_volume": self.unclassified_volume,
            "cvd_inferred": self.cvd,
            "session_vwap": self.session_vwap,
            "window_vwap_median": (round(statistics.median(self.window_vwaps), 4)
                                   if self.window_vwaps else None),
            "spread": (round(statistics.median(self.spreads), 4)
                       if self.spreads else None),
            "spread_bps": (round(statistics.median(self.spread_bps), 2)
                           if self.spread_bps else None),
            "obi_top1": self.obi_latest,
            "obi_top1_median": (round(obis, 4) if obis is not None else None),
            "feed_print_lag_seconds": (round(statistics.median(
                self.print_lag_seconds), 1) if self.print_lag_seconds else None),
            "bid_replenishment_rate": (
                round(self.bid_replenish_events / self.bid_consumed_events, 4)
                if self.bid_consumed_events else None),
            "ask_absorption_rate": (
                round(self.ask_absorption_events / self.ask_consumed_events, 4)
                if self.ask_consumed_events else None),
            "suspended_snapshots": self.suspended_snapshots,
            "first_capture_ts": self.first_capture_ts,
            "last_capture_ts": self.last_capture_ts,
            "basis": {
                "spread": FEATURE_STATUS["spread"],
                "obi_top1": FEATURE_STATUS["obi_top1"],
                "cvd_inferred": FEATURE_STATUS["cvd_inferred"],
                "bid_replenishment": FEATURE_STATUS["bid_replenishment"],
                "ask_absorption": FEATURE_STATUS["ask_absorption"],
                "session_vwap": "AVAILABLE (venue average price field)",
            },
            "notes": list(self.notes),
        }


def _apply_window(flow: SymbolOrderFlow, current: Mapping,
                  previous: Mapping) -> None:
    """Measure one window between two observations of one symbol."""
    total = _num(current.get("volume"))
    before_total = _num(previous.get("volume"))
    if total is None or before_total is None:
        return
    delta = int(total) - int(before_total)
    if delta < 0:
        flow.notes.append("the running total moved backwards; window ignored")
        return
    if delta == 0:
        return
    flow.windows += 1
    flow.volume_delta += delta
    trades_now = _num(current.get("trades"))
    trades_before = _num(previous.get("trades"))
    if trades_now is not None and trades_before is not None:
        flow.trades_delta += max(0, int(trades_now) - int(trades_before))
    # Traded value from the venue's own session average: sum(total*avg)
    # differences are exact for a volume weighted average, so a window's
    # value and VWAP need no estimated price.
    avg_now = _num(current.get("average"))
    avg_before = _num(previous.get("average"))
    if (avg_now is not None and avg_before is not None
            and total > 0 and before_total > 0):
        value = total * avg_now - before_total * avg_before
        if value > 0:
            flow.value_delta += value
            flow.window_vwaps.append(value / delta)
    earlier = _clock(previous.get("capture_ts"))
    later = _clock(current.get("capture_ts"))
    gap = (later - earlier).total_seconds() if earlier and later else None
    if gap is None or gap > tick_volume.MAX_WINDOW_SECONDS:
        flow.gap_windows += 1
        flow.unclassified_volume += delta
        return
    side, _how = tick_volume._trade_side(current, previous)
    if side == "B":
        flow.buy_volume += delta
    elif side == "S":
        flow.sell_volume += delta
    else:
        flow.unclassified_windows += 1
        flow.unclassified_volume += delta
        return
    # Quote reaction, at snapshot cadence only (median 24s), so these are
    # pressure proxies, never per-order facts. Replenishment: after selling
    # hit the bid, did the resting bid size return to its pre-window size?
    # Absorption: after buying lifted the ask, did the resting ask shrink
    # while the price refused to fall?
    size_before = _num(previous.get("bid_size"))
    size_now = _num(current.get("bid_size"))
    last_before = _num(previous.get("last"))
    last_now = _num(current.get("last"))
    if side == "S" and size_before is not None and size_now is not None:
        flow.bid_consumed_events += 1
        if size_now >= size_before:
            flow.bid_replenish_events += 1
    ask_before = _num(previous.get("ask_size"))
    ask_now = _num(current.get("ask_size"))
    if side == "B" and ask_before is not None and ask_now is not None:
        flow.ask_consumed_events += 1
        if (ask_now < ask_before
                and last_before is not None and last_now is not None
                and last_now >= last_before):
            flow.ask_absorption_events += 1


def symbol_flow(path: Path,
                symbols: Iterable[str] | None = None) -> dict[str, SymbolOrderFlow]:
    """Every measured flow in one capture file, keyed by symbol."""
    flows: dict[str, SymbolOrderFlow] = {}
    previous: dict[str, Mapping] = {}
    for snapshot in flow_snapshots(path, symbols):
        symbol = snapshot["symbol"]
        flow = flows.get(symbol)
        if flow is None:
            flow = flows[symbol] = SymbolOrderFlow(symbol=symbol)
        flow.snapshots += 1
        if flow.first_capture_ts is None:
            flow.first_capture_ts = snapshot.get("capture_ts")
        flow.last_capture_ts = snapshot.get("capture_ts")
        if str(snapshot.get("status") or "") == "SUS":
            flow.suspended_snapshots += 1
        bid, ask = snapshot.get("bid"), snapshot.get("ask")
        last = snapshot.get("last")
        if bid is not None and ask is not None and ask > 0 and bid > 0 and ask >= bid:
            spread = ask - bid
            flow.spreads.append(spread)
            mid = (ask + bid) / 2.0
            if mid > 0:
                flow.spread_bps.append(spread / mid * 10000.0)
        obi = top_of_book_imbalance(snapshot.get("bid_size"),
                                    snapshot.get("ask_size"))
        if obi is not None:
            flow.obi_latest = round(obi, 4)
            flow.obi_values.append(obi)
        avg = snapshot.get("average")
        if avg is not None and avg > 0:
            flow.session_vwap = avg
        print_ts = _clock(snapshot.get("print_ts"))
        arrived = _clock(snapshot.get("capture_ts"))
        before = previous.get(symbol)
        if before is not None:
            previous_print = _clock(before.get("print_ts"))
            if (print_ts is not None and arrived is not None
                    and previous_print is not None and print_ts > previous_print):
                lag = (arrived - print_ts).total_seconds()
                if 0 <= lag <= 300:
                    flow.print_lag_seconds.append(lag)
            _apply_window(flow, snapshot, before)
        previous[symbol] = snapshot
    for flow in flows.values():
        if flow.obi_values:
            flow.obi_median = statistics.median(flow.obi_values)
        if flow.gap_windows:
            flow.notes.append(
                f"{flow.gap_windows} window(s) spanned more than "
                f"{tick_volume.MAX_WINDOW_SECONDS / 60:.0f} minutes and are "
                "unclassified")
        if flow.unclassified_windows:
            flow.notes.append(
                f"{flow.unclassified_windows} window(s) had no print or "
                "quote evidence and are unclassified")
        if flow.unclassified_volume:
            flow.notes.append(
                f"{flow.unclassified_volume:,} shares are unclassified")
        flow.notes.append(
            "buy/sell sides are inferred (print at the ask or bid, then the "
            "tick rule); the wire carries no aggressor flag")
        if flow.bid_consumed_events:
            flow.notes.append(
                "bid replenishment and ask absorption are snapshot cadence "
                "proxies, not per-order events")
    return flows


def summarise(flows: Mapping[str, SymbolOrderFlow]) -> dict:
    """Aggregate availability and quality across the flows measured."""
    rows = list(flows.values())
    traded = sum(flow.volume_delta for flow in rows)
    classified = sum(flow.buy_volume + flow.sell_volume for flow in rows)
    return {
        "capability": CAPABILITY,
        "feature_status": FEATURE_STATUS,
        "registry": footprint_gate(),
        "symbols": len(rows),
        "windows": sum(flow.windows for flow in rows),
        "volume_traded": traded,
        "classified_volume": classified,
        "inferred_share": (round(classified / traded, 4) if traded else None),
        "note": ("sides are inferred, not venue supplied; MBP depth, MBO "
                 "order events and per-level impact are not on this wire"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--date", default=None, help="YYYY-MM-DD")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--top", type=int, default=15)
    args = parser.parse_args(argv)

    path = args.file
    if path is None:
        day = (date.fromisoformat(args.date) if args.date
               else now_karachi().date())
        path = tick_volume.capture_path(day)
    if not path or not path.is_file():
        print(f"no capture file at {path}", file=sys.stderr)
        return 2

    flows = symbol_flow(path)
    if not flows:
        print(f"{path.name} holds no REG MKT-FEED rows", file=sys.stderr)
        return 1
    summary = summarise(flows)
    print(json.dumps(summary, indent=1))
    rows = sorted(flows.values(), key=lambda f: -f.volume_delta)
    if args.show:
        print(json.dumps([flow.as_dict() for flow in rows[:args.top]], indent=2))
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"file": path.name, "summary": summary,
             "symbols": [flow.as_dict() for flow in rows]}, indent=1),
            encoding="utf-8")
        print(f"report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
