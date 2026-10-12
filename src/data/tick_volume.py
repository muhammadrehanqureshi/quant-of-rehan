"""Buy/sell volume per symbol, measured from the broker's real-time tape.

Owner order 2026-10-10, restated 2026-10-12: the market card must show, for
each of the day's top three KMIALL stocks, the buy volume, the sell volume and
the total. No configured source publishes that split as a number, so this
module derives it from the one place the volume genuinely exists: the
per-symbol snapshots the broker's read-only feed banks in
``data/feed_capture/capture_YYYYMMDD.ndjson``.

WHAT THE TAPE IS, measured on 5064 live rows on 2026-10-12 (and the reason
this module was rebuilt):

  * Every row carries the symbol's own running session total (field [16]),
    the cumulative trade count (field [15]), the last traded price (field
    [10]), the best bid and ask (fields [3] and [4]) and the size of that
    last print (field [17]).
  * The volume genuinely traded between two snapshots is the increment of
    field [16]: measured against the venue's own numbers, TREET's total
    advanced 8,879,754 shares over the observed window while the sizes of
    the last prints in those same rows add up to a small fraction of that.
    Summing print sizes therefore produced a floor, never a day, which is
    why the card could not show a measured split at all.
  * Each row's last price sat exactly at the ask on 2184 rows and exactly at
    the bid on 1122 of the 5064, so the side of the print that closed a
    window is directly observable: the buyer lifted the offer, or the seller
    hit the bid.
  * The field an earlier reading called a trade side is not one. Field [7]
    carries the sign of the day's change: across all 902 MKT-FEED rows
    banked on the day it equalled sign(field [8]) with zero exceptions, and
    23 of 314 symbols changed its value during the session as the day's move
    crossed zero. 'B' and 'S' tokens are therefore gone from this module:
    no side token exists on this wire, and reading the sign as one would
    classify every trade of a rising stock as a buy.

HOW THE SPLIT IS MEASURED (per symbol, rows in arrival order):

  1. The window between two rows held ``total_now - total_previous`` shares.
     That difference is the venue's own counter, so every share the tape saw
     is in exactly one window. A window longer than MAX_WINDOW_SECONDS of
     tape is an outage, not a sample, so it is refused and reported instead
     of being attributed to one side (measured failure, see that constant).
     A capture written before the row separator was fixed is re-read from
     its raw line, so those frames contribute whole rather than one row.
  2. The window's side comes from evidence about the prints, in this order:
     the closing print's own position (at the ask means a buyer, at the bid
     means a seller), then the tick rule against the previous row's last
     price (a higher print means buying pressure, a lower one selling).
     A window with none of that evidence is counted as unclassified and
     reported, never guessed. Nothing here reads a size as a side, and no
     token is trusted over a price.
  3. The volume traded before the tape first saw the symbol is its first
     row's running total. It is reported as unclassified, so the totals stay
     arithmetically complete: classified + unclassified is exactly the
     symbol's running total, and a partial tape can never be dressed up as
     a whole day.

src/data/volume_split.py turns these flows into the card's numbers: it uses
them directly when the tape covered the day (reconcilable), projects their
proportion onto the venue's own total when it did not, and says which of the
two it did. This module owns the measurement; that one owns the label.

Usage:
    python -m src.data.tick_volume --show              # today's split
    python -m src.data.tick_volume --show OGDC PSO     # only these symbols
    python -m src.data.tick_volume --date 2026-10-06 --show

All timestamps are Karachi time (SO-8): the zone is already imported from
src/data/sessions.py, which pins Asia/Karachi at the fixed UTC+5 offset, and
this module never builds a session time of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.sessions import now_karachi  # noqa: E402  (SO-8: the one zone)

CAPTURE_DIR = ROOT / "data" / "feed_capture"

#: Frames whose rows use the MKT-FEED tick layout. Anything else in the
#: capture (EXS-FEED, MKT-Movers, MKT-STATS) has a different field map.
TICK_KINDS = ("MKT-FEED",)

#: A disagreement above this share of the running total is reported, and the
#: split is refused as a whole-day answer above it (see `reconcilable`).
TOTAL_TOLERANCE = 0.02

#: The longest interval between two observations of one symbol that may be
#: attributed to a single side. This bound exists because of a measured
#: failure: on 2026-10-12 the capture stopped between 10:32 and 13:27, and the
#: 4,050,063 shares CNERGY traded across that dead three hours were one
#: "window" whose closing print sat at the ask, which would have printed the
#: day as 97 percent buying. A window that long is not a sample of the flow,
#: it is an outage, so it is refused and reported instead of classified. The
#: feed observes a symbol every 30 seconds or so when it is running.
MAX_WINDOW_SECONDS = 600.0


@dataclass
class SymbolFlow:
    """One symbol's session flow, from banked tape rows only."""

    symbol: str
    buy_volume: int = 0
    sell_volume: int = 0
    #: Volume the tape saw but could not attribute (windows with no price or
    #: quote evidence, plus everything traded before the tape started).
    unclassified_volume: int = 0
    #: The running total in the first row the tape saw for this symbol: the
    #: volume traded before the capture existed. Reported, never absorbed.
    pre_tape_volume: int = 0
    rows: int = 0
    windows: int = 0
    windows_at_quote: int = 0
    windows_by_tick: int = 0
    unclassified_windows: int = 0
    repeated_rows: int = 0
    backward_windows: int = 0
    #: Windows that spanned more than MAX_WINDOW_SECONDS of tape: an outage,
    #: never a side. Their volume is counted as unclassified.
    gap_windows: int = 0
    gap_volume: int = 0
    #: The venue's cumulative total in the last row seen (its own figure).
    observed_total: int = 0
    first_tick: str = ""
    last_tick: str = ""
    source: str = "broker MKT-FEED tape"
    notes: list[str] = field(default_factory=list)

    @property
    def classified_total(self) -> int:
        return self.buy_volume + self.sell_volume

    @property
    def total_volume(self) -> int:
        """The symbol's running total, preferring the venue's own figure.

        The cumulative field is the source's own counter for the session, so
        it is the honest answer to "T=". The classified sums are this
        module's attribution of that same counter.
        """
        if self.observed_total:
            return self.observed_total
        return self.classified_total + self.unclassified_volume

    @property
    def split_available(self) -> bool:
        """True only when the tape attributed volume to a side."""
        return self.classified_total > 0

    @property
    def coverage(self) -> float:
        """Share of the symbol's running total the tape attributed."""
        total = self.total_volume
        return 0.0 if total <= 0 else self.classified_total / total

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
            "pre_tape_volume": self.pre_tape_volume,
            "coverage": round(self.coverage, 4),
            "rows": self.rows,
            "windows": self.windows,
            "windows_at_quote": self.windows_at_quote,
            "windows_by_tick": self.windows_by_tick,
            "unclassified_windows": self.unclassified_windows,
            "gap_windows": self.gap_windows,
            "gap_volume": self.gap_volume,
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
    """Yield only genuine MKT-FEED tape rows from a capture file.

    The capture banks every frame it receives, including index and
    market-stats frames that reuse the same key names with different
    meanings. Filtering on the frame kind here is what keeps the split
    honest.
    """
    if not path.is_file():
        return
    from src.data.feed_capture import parse_message  # local: no cycle at import

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
            ticks = record.get("ticks", []) or []
            # A capture written before the row separator was fixed banked one
            # row per frame and left the rest of the payload in the raw line.
            # The raw line is the same genuine exchange data, so reading it
            # back here recovers those rows instead of silently measuring a
            # tenth of the tape. If the re-parse yields nothing, the stored
            # rows are used as they were banked.
            raw = str(record.get("raw", ""))
            if raw:
                try:
                    reparsed = parse_message(raw) or {}
                except Exception:  # noqa: BLE001 - the banked row still counts
                    reparsed = {}
                recovered = [t for t in reparsed.get("ticks", []) or []
                             if isinstance(t, Mapping)]
                if recovered:
                    ticks = recovered
            # When the snapshot arrived. It is the honest clock for a window:
            # tick_time is the time of the last print, which on a quiet
            # symbol can be hours old while the snapshot itself is fresh.
            arrived = str(record.get("ts", ""))
            for tick in ticks:
                if isinstance(tick, Mapping):
                    if arrived and "capture_ts" not in tick:
                        try:
                            tick["capture_ts"] = arrived
                        except TypeError:
                            continue
                    yield tick


def _clock(text) -> datetime | None:
    """Parse a capture timestamp, or a bare time of day, for gap checks.

    A real capture writes a full ISO stamp on every record. A hand-built row
    may carry only a time of day, so that is accepted too, on a fixed dummy
    date: rows written in one style compare correctly with each other, and a
    mix of styles simply fails the gap check and is unclassified.
    """
    text = str(text or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            moment = datetime.strptime(text, pattern)
        except ValueError:
            continue
        return moment.replace(year=2000, month=1, day=1)
    return None


def _window_gap(row: Mapping, previous: Mapping) -> float | None:
    """Seconds between two observations, or None when a clock is missing."""
    now = _clock(row.get("capture_ts") or row.get("tick_time"))
    before = _clock(previous.get("capture_ts") or previous.get("tick_time"))
    if now is None or before is None:
        return None
    return (now - before).total_seconds()


def _trade_side(row: Mapping, previous: Mapping | None) -> tuple[str, str]:
    """Classify one snapshot window: ('B'|'S'|'', how it was decided).

    The evidence is about the venue's own prints, strongest first:

      * QUOTE: the closing print traded at the ask (a buyer lifted the
        offer) or at the bid (a seller hit the bid). Only an exact match
        counts: a book that is inverted or a print that sits outside it
        says nothing, and is not used.
      * TICK: the last price moved up or down against the previous row's
        last price. This is the standard tick rule, applied to the shares
        the running total moved in the window.

    A window with neither is unclassified. No field is ever read as a side
    token: field [7] is the day's change sign (see the module docstring).
    """
    last = _num(row.get("last"))
    bid = _num(row.get("bid"))
    ask = _num(row.get("ask"))
    if bid is not None and ask is not None and bid > ask:
        bid = ask = None   # an inverted book is not evidence
    if last is not None and ask is not None and ask > 0 and last == ask:
        return "B", "quote: print at the ask"
    if last is not None and bid is not None and bid > 0 and last == bid:
        return "S", "quote: print at the bid"
    previous_last = _num(previous.get("last")) if previous is not None else None
    if last is not None and previous_last is not None:
        if last > previous_last:
            return "B", "tick rule: the print rose"
        if last < previous_last:
            return "S", "tick rule: the print fell"
    return "", ""


def session_flow(path: Path,
                 symbols: Iterable[str] | None = None) -> dict[str, SymbolFlow]:
    """Buy/sell/total volume per symbol from one capture file.

    Returns only the symbols the tape genuinely saw; a symbol with no rows
    is absent (and its split is unavailable), never present with zeros
    dressed up as data. Within a symbol, rows are walked in arrival order
    and each pair of rows contributes one window: the increment of the
    venue's own running total, attributed to a side by the print evidence
    (see _trade_side). Everything before the first row, and every window
    with no evidence, is counted as unclassified rather than guessed.
    """
    wanted = ({str(s).strip().upper() for s in symbols}
              if symbols is not None else None)
    flows: dict[str, SymbolFlow] = {}
    previous_row: dict[str, Mapping] = {}
    for tick in iter_ticks(path):
        symbol = str(tick.get("scrip", "")).strip().upper()
        # A subscription names the market (SYM:REG) and the feed echoes the
        # market in its own field, but a hand-built row may still carry the
        # suffix on the scrip, so it is stripped rather than left to miss the
        # ranking table's bare symbol.
        symbol = symbol.split(":", 1)[0]
        if not symbol:
            continue
        if wanted is not None and symbol not in wanted:
            continue
        flow = flows.get(symbol)
        if flow is None:
            flow = flows[symbol] = SymbolFlow(symbol=symbol)
        stamp = str(tick.get("tick_time", "")).strip()
        if stamp:
            if not flow.first_tick:
                flow.first_tick = stamp
            flow.last_tick = stamp
        total = _num(tick.get("volume"))
        previous = previous_row.get(symbol)
        # A feed repeats whole snapshots; the same row twice is one row.
        if previous is not None and all(
                _num(tick.get(key)) == _num(previous.get(key))
                for key in ("volume", "trades", "last")
        ) and str(tick.get("tick_time", "")) == str(previous.get("tick_time", "")):
            flow.repeated_rows += 1
            continue
        flow.rows += 1
        if total is None or total <= 0:
            # No running total on this row: it carries no window of its own
            # but is still the evidence the next row's window is measured
            # against, so it becomes the previous row.
            previous_row[symbol] = tick
            continue
        if previous is None:
            # The first row's total is everything traded before the tape saw
            # this symbol. Reported, never spread across the two sides. A
            # tape that starts before the first trade sees a zero here and
            # then attributes every share from the open.
            flow.pre_tape_volume = int(total)
            flow.unclassified_volume += int(total)
            flow.observed_total = int(total)
            previous_row[symbol] = tick
            continue
        previous_total = _num(previous.get("volume"))
        flow.observed_total = int(total)
        if previous_total is None:
            previous_row[symbol] = tick
            continue
        delta = int(total) - int(previous_total)
        if delta > 0:
            flow.windows += 1
            gap = _window_gap(tick, previous)
            side, how = "", ""
            if gap is None or gap > MAX_WINDOW_SECONDS:
                # The tape was not watching for too long to call this flow.
                # An outage is not a side, and the shares stay unclassified.
                flow.gap_windows += 1
                flow.gap_volume += delta
            else:
                side, how = _trade_side(tick, previous)
            if side == "B":
                flow.buy_volume += delta
            elif side == "S":
                flow.sell_volume += delta
            else:
                flow.unclassified_volume += delta
                flow.unclassified_windows += 1
            if how.startswith("quote"):
                flow.windows_at_quote += 1
            elif how.startswith("tick"):
                flow.windows_by_tick += 1
        elif delta < 0:
            # A running total that went backwards cannot be split: report it
            # rather than turning the fall into a side's volume.
            flow.backward_windows += 1
        previous_row[symbol] = tick

    for flow in flows.values():
        if flow.gap_windows:
            flow.notes.append(
                f"{flow.gap_windows} window(s) spanned more than "
                f"{MAX_WINDOW_SECONDS / 60:.0f} minutes of tape, so the "
                f"{flow.gap_volume:,} shares in them are unclassified rather "
                f"than attributed to one side")
        if flow.pre_tape_volume:
            flow.notes.append(
                f"{flow.pre_tape_volume:,} shares traded before the tape "
                f"first saw this symbol are unclassified")
        if flow.unclassified_windows:
            flow.notes.append(
                f"{flow.unclassified_windows} window(s) carried no print or "
                f"quote evidence and are unclassified")
        if flow.backward_windows:
            flow.notes.append(
                f"{flow.backward_windows} window(s) saw the running total go "
                f"backwards and are excluded")
        if not flow.split_available:
            flow.notes.append(
                "no side could be attributed: the tape holds "
                f"{flow.rows} row(s) for this symbol")
        elif not flow.reconcilable:
            flow.notes.append(
                f"classified {flow.classified_total:,} of a stated session "
                f"total of {flow.total_volume:,}: the capture did not cover "
                "the whole day for this symbol")
    return flows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="buy/sell/total volume from the banked broker tape")
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
    print(f"\n{len(rows)} symbol(s) with tape rows; a split is available for "
          f"{sum(1 for f in flows.values() if f.split_available)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
