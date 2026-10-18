#!/usr/bin/env python3
"""Intraday bars built from the broker tape, not from a servlet.

Owner order 2026-10-14: the scanner must stop depending on the eClear OHLC
servlet. That servlet is dead: it answers and serves no bars, so every
scheduled scan reported DATA BLOCKED with a coverage of 0/319 while the tape
this system already subscribes to was carrying the whole market. This module
is the bar path that replaces it. The same read-only MKT-FEED capture that
feeds the buy/sell split and the phone's card is now the bar source.

One bar is one minute (config.BAR_SECONDS, the grid config.BAR_RESOLUTION
names):

    open/high/low/close   the prices the tape carried inside that minute
    volume                the venue's own running volume counter, differenced
                          across the minute. Never a proxy, never estimated
    prints                how many rows in that minute carried a fresh print
                          rather than the previous state repeated
    carried               True when the minute held no row at all, so the
                          previous close stands in for it

Why a carried bar is not fabrication: the feed reports its state per symbol,
not a print per trade, so a quiet minute is itself a market fact (no trade
happened, the price is where the last one left it, the running counter did
not move). The fill is bounded, and the bound is the honesty: it runs only
while the tape was genuinely watching, meaning between two observations no
further apart than config.TAPE_CARRY_MAX_GAP_SECONDS, so an outage or a
stopped capture leaves a hole in the series instead of a flat invented line.
Nothing is ever written after the last observation of a symbol, and every
carried bar is counted and reported.

Measured on the real 2026-10-13 KMIALL tape (data/feed_capture, 44.6 MB, 314
symbols, 56,618 tick rows, covering 09:52 to 13:47 Asia/Karachi, which is the
one fixed offset UTC+5 this system speaks, SO-8): the feed observes a symbol
about every 30 seconds (median gap 30.0s, p90 150s), so 1-minute buckets are
dense and the carry fill only ever closes a jittery minute.

What this module never does, per GOVERNANCE.md SO-3:

  * it never invents a price, a volume or a timestamp. A row with no usable
    price is counted as priceless, a running counter that goes backwards is
    counted as a reset and contributes no volume, and a row that simply
    repeats the previous one is counted once;
  * it never hides what the tape could not see. Volume that traded before the
    tape first observed a symbol is reported as that symbol's opening counter
    value, never spread across bars it did not come from, and a symbol whose
    first bar sits after the session open is named, because for that symbol
    this series does not contain the day's open.

The read-only law of src/data/feed_capture.py is untouched: this module only
reads a capture file that already exists on disk.

Usage::

    python -m src.data.tape_bars --date 2026-10-13 --show
    python -m src.data.tape_bars --check-coverage --symbols-file src/data/universe_kmiall.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import tick_volume  # noqa: E402
from src.data.ohlc_poller import LOW_COVERAGE_FLAG as _POLLER_FLAG  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI,
    is_trading_day,
    open_time,
)

#: The label that travels with every bar built here, into the quality report
#: and the observation, so no reader has to guess which source spoke (SO-3).
SOURCE = ("broker MKT-FEED tape (prints for open, high, low and close; "
          "the venue's running volume counter for volume)")

CAPTURE_DIR = ROOT / "data" / "feed_capture"

#: The capture-health channel, deliberately the SAME file the servlet pass has
#: always written: scripts/ops_alert.py --capture-health turns it into one
#: deduped alert and clears it, and one channel means a thin tape can never
#: hide behind a healthy servlet or the other way round. Imported from its
#: original owner rather than typed a second time, so the two can never drift.
LOW_COVERAGE_FLAG = _POLLER_FLAG


def capture_path(day: date) -> Path:
    """The tape this path reads for *day* (one file per Karachi day)."""
    return tick_volume.capture_path(day)


def _number(value) -> float | None:
    """A wire field as a number, or None when it carries no number at all."""
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _moment(row: Mapping, day: date) -> datetime | None:
    """When the tape held this row: its arrival stamp, else its print clock.

    The arrival stamp is the honest clock for a bar. The print clock is the
    time of the symbol's last trade, which on a quiet name can be hours old,
    and the row in hand is a genuine observation now: it is what the venue's
    own counter is measured against.
    """
    arrived = str(row.get("capture_ts") or "").strip()
    if arrived:
        try:
            moment = datetime.fromisoformat(arrived)
        except ValueError:
            moment = None
        if moment is not None:
            return (moment.astimezone(KARACHI) if moment.tzinfo
                    else moment.replace(tzinfo=KARACHI))
    printed = str(row.get("tick_time") or "").strip()
    for pattern in ("%H:%M:%S", "%H:%M"):
        try:
            clock = datetime.strptime(printed, pattern).time()
        except ValueError:
            continue
        return datetime.combine(day, clock, tzinfo=KARACHI)
    return None


def _repeats(row: Mapping, previous: Mapping | None) -> bool:
    """Is this row the previous row of the same symbol, sent again?"""
    if previous is None:
        return False
    return (
        str(row.get("tick_time", "")) == str(previous.get("tick_time", ""))
        and all(_number(row.get(key)) == _number(previous.get(key))
                for key in ("volume", "trades", "last"))
    )


def _is_new_print(row: Mapping, previous: Mapping | None) -> bool:
    """Did this row carry a print the tape had not already given us?"""
    if previous is None:
        return True
    return (str(row.get("tick_time", "")) != str(previous.get("tick_time", ""))
            or _number(row.get("last")) != _number(previous.get("last")))


@dataclass(frozen=True)
class TapeBar:
    """One minute of one symbol, as the tape saw it."""

    timestamp: datetime   # the minute's own start, on the Karachi clock (UTC+5)
    open: float
    high: float
    low: float
    close: float
    volume: float
    prints: int = 0
    carried: bool = False


@dataclass
class TapeBars:
    """Every bar one tape file holds, with what it cost to read and what it
    could not see. Counts are measured; nothing here is estimated."""

    day: date
    bars: dict[str, list[TapeBar]] = field(default_factory=dict)
    #: Last genuine arrival time seen per symbol, including quiet-book snapshots.
    observed_at: dict[str, datetime] = field(default_factory=dict)
    path: Path | None = None
    rows_seen: int = 0
    rows_rejected: int = 0
    repeated_rows: int = 0
    priceless_rows: int = 0
    counter_rows: int = 0
    counter_gaps: int = 0
    counter_resets: int = 0
    priced_bars: int = 0
    carried_bars: int = 0
    #: Symbols whose series holds a hole wider than the carry bound: an outage
    #: or a stopped tape, left as a hole rather than filled with a flat line.
    hole_symbols: tuple[str, ...] = ()
    #: Shares the venue's counter already carried when the tape first observed
    #: the symbol. Reported per symbol; never spread across bars.
    pre_tape_volume: dict[str, int] = field(default_factory=dict)
    #: Symbols whose first bar is later than the session open, so their first
    #: bar is not the day's open.
    started_after_open: tuple[str, ...] = ()
    #: The earliest observation the tape held, and how it compares with the
    #: session open. A capture that starts after the open cannot contain the
    #: day's open for anybody, which is worth saying once, plainly.
    first_observation: datetime | None = None
    #: Self-check against the venue's own day extremes (fields 13 and 14 of
    #: the tick row): a bar may not exceed the high or undercut the low the
    #: venue itself reports for the day. A count above zero means the parse or
    #: the wire is wrong, so it is reported rather than swallowed.
    venue_extreme_violations: int = 0
    source: str = SOURCE
    notes: list[str] = field(default_factory=list)

    @property
    def symbols_with_bars(self) -> int:
        return len(self.bars)

    @property
    def volume_available(self) -> bool:
        """True only when the tape carried the venue's counter and moved it.

        The strategy needs volume expansion, and the counter is the only
        genuine volume in this capture. A tape that never carried it is a
        blocked scan, not a price-only scan.
        """
        if self.counter_rows <= 0:
            return False
        return any(bar.volume > 0 for rows in self.bars.values()
                   for bar in rows)

    def as_dict(self) -> dict:
        total = self.priced_bars + self.carried_bars
        return {
            "source": self.source,
            "day": self.day.isoformat(),
            "capture": str(self.path) if self.path else None,
            "symbols_with_bars": self.symbols_with_bars,
            "bars": total,
            "priced_bars": self.priced_bars,
            "carried_bars": self.carried_bars,
            "carried_share": round(self.carried_bars / total, 4) if total else 0.0,
            "rows_seen": self.rows_seen,
            "rows_rejected": self.rows_rejected,
            "repeated_rows": self.repeated_rows,
            "priceless_rows": self.priceless_rows,
            "counter_rows": self.counter_rows,
            "counter_gaps": self.counter_gaps,
            "counter_resets": self.counter_resets,
            "volume_available": self.volume_available,
            "pre_tape_volume_symbols": len(self.pre_tape_volume),
            "pre_tape_volume_total": sum(self.pre_tape_volume.values()),
            "first_observation": (self.first_observation.isoformat()
                                  if self.first_observation else None),
            "started_after_open": list(self.started_after_open[:20]),
            "started_after_open_count": len(self.started_after_open),
            "venue_extreme_violations": self.venue_extreme_violations,
            "hole_symbols": list(self.hole_symbols[:20]),
            "hole_symbol_count": len(self.hole_symbols),
            "notes": list(self.notes),
        }


def build(path: Path, symbols: Iterable[str], as_of: datetime,
          day: date | None = None) -> TapeBars:
    """Build one session of bars from one tape capture file.

    Rows are read in arrival order per symbol (src/data/tick_volume.iter_ticks
    already filters to genuine MKT-FEED rows and recovers rows banked before
    the row separator was fixed). Every bar is dated by its own minute, on the
    Karachi clock (SO-8), and a bar that starts at or after *as_of* is never
    written, exactly like the capture loader's own rule.
    """
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=KARACHI)
    session_day = day or as_of.date()
    universe = {str(symbol).strip().upper() for symbol in symbols}
    tape = TapeBars(day=session_day, path=path)
    if not is_trading_day(session_day):
        tape.notes.append(f"{session_day.isoformat()} is not a PSX trading day")
        return tape
    if not path.is_file():
        tape.notes.append(f"no tape capture on disk: {path}")
        return tape

    minutes: dict[str, dict[datetime, dict]] = {}
    previous: dict[str, Mapping] = {}
    venue_high: dict[str, float] = {}
    venue_low: dict[str, float] = {}
    for row in tick_volume.iter_ticks(path):
        symbol = str(row.get("scrip", "")).split(":", 1)[0].strip().upper()
        if not symbol or symbol not in universe:
            continue
        moment = _moment(row, session_day)
        if moment is None:
            tape.rows_rejected += 1
            continue
        if moment.date() != session_day or moment >= as_of:
            continue
        observed = tape.observed_at.get(symbol)
        if observed is None or moment > observed:
            tape.observed_at[symbol] = moment
        prior = previous.get(symbol)
        if _repeats(row, prior):
            # The feed re-sends a whole snapshot when only the book moved. It
            # is still a genuine observation of that symbol, so it belongs in
            # the minute (the scanner's freshness gate is about the tape
            # watching, not about the price moving); it simply carries no new
            # volume, because its counter did not move.
            tape.repeated_rows += 1
        tape.rows_seen += 1

        total = _number(row.get("volume"))
        delta = 0.0
        if total is not None and total > 0:
            tape.counter_rows += 1
            prior_total = _number(prior.get("volume")) if prior else None
            if prior is None:
                # Everything traded before the tape saw this symbol: the
                # counter's own opening value for it. Reported, not spread.
                tape.pre_tape_volume[symbol] = int(total)
            elif prior_total is None:
                tape.counter_gaps += 1
            elif total >= prior_total:
                delta = float(int(total) - int(prior_total))
            else:
                # A running total cannot go backwards: report it instead of
                # reading a fall as negative volume.
                tape.counter_resets += 1

        if tape.first_observation is None or moment < tape.first_observation:
            tape.first_observation = moment
        day_high = _number(row.get("high"))
        day_low = _number(row.get("low"))
        if day_high is not None and day_high > 0:
            venue_high[symbol] = max(venue_high.get(symbol, day_high), day_high)
        if day_low is not None and day_low > 0:
            venue_low[symbol] = min(venue_low.get(symbol, day_low), day_low)

        price = _number(row.get("last"))
        previous[symbol] = row
        if price is None or price <= 0:
            tape.priceless_rows += 1
            continue

        minute = moment.replace(second=0, microsecond=0)
        bucket = minutes.setdefault(symbol, {}).get(minute)
        if bucket is None:
            minutes[symbol][minute] = {
                "open": price, "high": price, "low": price, "close": price,
                "volume": delta,
                "prints": 1 if _is_new_print(row, prior) else 0,
            }
        else:
            bucket["high"] = max(bucket["high"], price)
            bucket["low"] = min(bucket["low"], price)
            bucket["close"] = price
            bucket["volume"] += delta
            if _is_new_print(row, prior):
                bucket["prints"] += 1
        tape.priced_bars += 1

    session_start = datetime.combine(session_day, time(*open_time(session_day)),
                                     tzinfo=KARACHI)
    started_late: list[str] = []
    holed: list[str] = []
    for symbol, buckets in minutes.items():
        ordered = sorted(buckets)
        if ordered[0] > session_start:
            started_late.append(symbol)
        rows: list[TapeBar] = []
        for index, minute in enumerate(ordered):
            data = buckets[minute]
            rows.append(TapeBar(minute, data["open"], data["high"], data["low"],
                                data["close"], data["volume"], data["prints"]))
            following = ordered[index + 1] if index + 1 < len(ordered) else None
            if following is None:
                continue
            gap = (following - minute).total_seconds()
            if gap <= config.BAR_SECONDS:
                continue
            if gap > config.TAPE_CARRY_MAX_GAP_SECONDS:
                # An outage or a stopped tape: the series keeps its hole so a
                # flat invented line can never stand in for one.
                if symbol not in holed:
                    holed.append(symbol)
                continue
            fill = minute + timedelta(seconds=config.BAR_SECONDS)
            close = data["close"]
            while fill < following:
                rows.append(TapeBar(fill, close, close, close, close, 0.0, 0,
                                    carried=True))
                tape.carried_bars += 1
                fill += timedelta(seconds=config.BAR_SECONDS)
        tape.bars[symbol] = rows

    for symbol, rows in tape.bars.items():
        high = venue_high.get(symbol)
        low = venue_low.get(symbol)
        if high is None and low is None:
            continue
        for bar in rows:
            if high is not None and bar.high > high + 1e-6:
                tape.venue_extreme_violations += 1
                break
            if low is not None and bar.low < low - 1e-6:
                tape.venue_extreme_violations += 1
                break

    tape.started_after_open = tuple(sorted(started_late))
    tape.hole_symbols = tuple(sorted(holed))
    _note(tape)
    return tape


def _note(tape: TapeBars) -> None:
    """Write down what the tape could not see, in the record's own words."""
    if tape.counter_rows == 0:
        tape.notes.append(
            "the capture carried no venue volume counter on any row, so this "
            "tape cannot support a volume-based scan"
        )
    if tape.counter_gaps:
        tape.notes.append(
            f"{tape.counter_gaps} row(s) carried no running total after a row "
            f"that did, so no volume window could be measured across them"
        )
    if tape.counter_resets:
        tape.notes.append(
            f"{tape.counter_resets} row(s) saw the venue's running total go "
            f"backwards and contributed no volume"
        )
    if tape.priceless_rows:
        tape.notes.append(
            f"{tape.priceless_rows} row(s) carried no usable price and were "
            f"counted, not guessed"
        )
    total = tape.priced_bars + tape.carried_bars
    if tape.carried_bars:
        tape.notes.append(
            f"{tape.carried_bars} of {total} bars ({tape.carried_bars / total:.1%}) "
            f"carry the previous price because that symbol had no row in the "
            f"minute: a quiet minute, bounded to gaps of at most "
            f"{config.TAPE_CARRY_MAX_GAP_SECONDS / 60:.0f} minutes of live tape"
        )
    if tape.pre_tape_volume:
        tape.notes.append(
            f"{len(tape.pre_tape_volume)} symbol(s) had already traded before "
            f"the tape first observed them; that volume is reported as their "
            f"opening counter value and never spread across bars"
        )
    if tape.first_observation is not None:
        tape.notes.append(
            f"the tape's first observation is {tape.first_observation:%H:%M} "
            f"Karachi, {len(tape.started_after_open)} of "
            f"{tape.symbols_with_bars} symbol(s) start after the session open, "
            f"so this series is what the tape saw, not the whole day"
        )
    if tape.venue_extreme_violations:
        tape.notes.append(
            f"{tape.venue_extreme_violations} symbol(s) hold a bar above the "
            f"venue's own day high or below its day low: the bar path and the "
            f"wire disagree about those prints"
        )
    if tape.hole_symbols:
        tape.notes.append(
            f"{len(tape.hole_symbols)} symbol(s) hold a hole wider than "
            f"{config.TAPE_CARRY_MAX_GAP_SECONDS / 60:.0f} minutes of live tape; "
            f"the hole is kept so no flat line stands in for a stopped capture"
        )


def coverage(tape: TapeBars, universe_size: int) -> float:
    """Share of the universe this tape holds a bar for."""
    return tape.symbols_with_bars / max(universe_size, 1)


def write_low_coverage_flag(tape: TapeBars, universe_size: int,
                            cause: str) -> Path | None:
    """Leave the capture-health flag behind when the tape is too thin.

    The flag is the same channel scripts/ops_alert.py already turns into one
    deduped alert per day, so a degraded tape is REPORTED to the owner rather
    than passed off as a quiet market. Its payload carries the source, which
    is what lets the alert say what still ran and what did not.
    """
    if coverage(tape, universe_size) >= config.MIN_COVERAGE_PCT:
        return None
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    LOW_COVERAGE_FLAG.write_text(json.dumps({
        "captured_at": datetime.now(KARACHI).isoformat(),
        "coverage": coverage(tape, universe_size),
        "symbols_ok": tape.symbols_with_bars,
        "universe": universe_size,
        "source": tape.source,
        "cause": cause,
        "counters": tape.as_dict(),
    }, indent=1), encoding="utf-8")
    return LOW_COVERAGE_FLAG


def write_bars(tape: TapeBars, target: Path) -> Path:
    """Write the bars this session built, one per line, for the archive.

    The raw tape is tens of megabytes a session, so what is kept is what the
    scan actually read: symbol, minute, OHLC, volume, prints and whether the
    minute was carried. Nothing else is added.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for symbol in sorted(tape.bars):
            for bar in tape.bars[symbol]:
                handle.write(json.dumps({
                    "symbol": symbol,
                    "ts": bar.timestamp.isoformat(),
                    "o": bar.open, "h": bar.high, "l": bar.low, "c": bar.close,
                    "v": bar.volume, "prints": bar.prints,
                    "carried": bar.carried,
                    "source": tape.source,
                }, ensure_ascii=False) + "\n")
    return target


def _load_symbols(path: Path) -> list[str]:
    records = json.loads(path.read_text(encoding="utf-8"))
    return sorted({
        str(row["symbol"]).strip().upper() for row in records
        if row.get("symbol") and "KMIALLSHR" in (row.get("listedIn") or [])
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="1-minute bars from the banked broker tape")
    parser.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--as-of", default=None,
                        help="ISO instant to read up to (default: now)")
    parser.add_argument("--symbols-file", type=Path,
                        default=ROOT / "src" / "data" / "universe_kmiall.json")
    parser.add_argument("--show", action="store_true",
                        help="print the measured summary")
    parser.add_argument("--check-coverage", action="store_true",
                        help="measure the tape and raise the health flag if thin")
    parser.add_argument("--write-bars", type=Path, default=None,
                        help="also write the built bars to this ndjson path")
    args = parser.parse_args(argv)

    from src.data.sessions import now_karachi

    moment = (datetime.fromisoformat(args.as_of) if args.as_of
              else now_karachi())
    day = (date.fromisoformat(args.date) if args.date else moment.date())
    symbols = _load_symbols(args.symbols_file)
    tape = build(capture_path(day), symbols, moment, day=day)
    if args.write_bars is not None:
        print(f"bars written: {write_bars(tape, args.write_bars)}")

    if args.check_coverage:
        flag = write_low_coverage_flag(
            tape, len(symbols),
            cause=(f"the tape held bars for {tape.symbols_with_bars} of "
                   f"{len(symbols)} KMIALL symbols at "
                   f"{moment:%Y-%m-%d %H:%M} PKT"),
        )
        print(json.dumps(tape.as_dict(), indent=1, allow_nan=False))
        print(f"low coverage flag: {flag}" if flag else "coverage ok")
        return 0

    print(json.dumps(tape.as_dict(), indent=1, allow_nan=False))
    if args.show:
        for symbol in sorted(tape.bars)[:10]:
            rows = tape.bars[symbol]
            print(f"\n{symbol}: {len(rows)} bars, last {rows[-1].timestamp:%H:%M} "
                  f"close {rows[-1].close} volume {rows[-1].volume:.0f} "
                  f"prints {rows[-1].prints}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
