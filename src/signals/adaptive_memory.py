"""The quant's own memory of its closed trades (owner order 2026-10-31).

Owner, verbatim: "So you need to have a ML engine/concept that will be self
learning. Like an actual pro trader. Learn from your mistakes. Be with the
market. Don't go against the market."

This module is that engine, and it is honest about what "learning" can
mean on the evidence this system genuinely has (SO-3). It reads the ONE
session history the pipeline already banks
(src/research/session_history.py: local forward state plus the relay's
two-year research archive), finds every CLOSED trade in it, and learns
three pro-trader laws from the outcomes:

  1. TIME OF DAY. A pro does not put the same size into every hour. The
     memory files each closed trade by the minutes since its own band
     opened, keeps a recency-weighted expectancy per hour bucket, and
     refuses a fresh entry in a bucket whose own recent record is a
     measured loser (default: at least 3 closed trades averaging worse
     than the floor in src/config.py).
  2. REPEATED MISTAKES. The trade that started this file: PRL's first
     Kalman Trend call, the day the strategy went live, stopped out. A
     pro does not re-take the exact same setup that just failed twice.
     The memory keeps each symbol's consecutive stop-out streak and
     refuses that symbol while the streak stands. One good session
     clears it.
  3. THE MARKET'S OWN DIRECTION. "Be with the market": an entry into a
     falling tape is a bet against the day's own direction. The broad
     selloff veto the scanner already carries stays; the memory adds
     the stricter floor for a CONFIRMED entry (config.py names it), so
     the scanner ranks and delivers what it sees, but the paper entry
     only opens while the market's median is at or above the floor.

Every veto it returns NAMES what it learned. Nothing is invented: a
bucket with fewer trades than the minimum, or a history the loader
could not read, produces no veto at all and says so. The history is
never written here; the research archive is the one durable store, so
the memory is recomputed from outcomes on every runner and no learning
state can drift away from the evidence it claims to rest on.

SO-8: entry times are Karachi wall clock from the session's own
records, resolved through src/data/sessions.py helpers only.

Usage:
    python -m src.signals.adaptive_memory --show
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import band_bounds, session_bands  # noqa: E402

try:
    from src.research import session_history  # noqa: E402
except Exception:  # pragma: no cover - the loader is import guarded
    session_history = None

#: The outcome labels that ARE closed trades, in the gate's own vocabulary
#: (src/research/session_history.LABEL_BY_OUTCOME). UNVERIFIED is NOT one:
#: a session that could not be valued teaches nothing.
TRADE_LABELS = ("TP_FIRST", "SL_FIRST", "SL_AMBIG", "TIMEOUT")
STOP_LABELS = ("SL_FIRST", "SL_AMBIG")
WIN_LABELS = ("TP_FIRST",)

#: Unfiled entries (a record with no entry stamp) sit in their own named
#: bucket; they are counted, never hidden, and their name says exactly
#: what the record does not carry (the hour itself).
UNFILED_BUCKET = "no entry stamp"


@dataclass(frozen=True)
class BucketTip:
    """One hour bucket's measured record. Nothing here is a guess."""

    label: str
    trades: int
    stops: int
    wins: int
    expectancy_net: float | None

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "trades": self.trades,
            "stops": self.stops,
            "wins": self.wins,
            "expectancy_net": self.expectancy_net,
        }


@dataclass
class AdaptiveMemory:
    """The measured memory of the system's own closed trades."""

    buckets: dict[str, BucketTip] = field(default_factory=dict)
    symbol_streaks: dict[str, int] = field(default_factory=dict)
    honest_notes: list[str] = field(default_factory=list)
    trades_read: int = 0
    days_read: int = 0

    # ------------------------------------------------------------------ load

    @classmethod
    def from_rows(cls, rows: Iterable[Mapping]) -> "AdaptiveMemory":
        """Build the memory from the gate's own session rows.

        The rows are whatever session_history.session_rows() produced, in
        any order. Each row is one trading day's newest record; a day with
        no closed trade contributes nothing, and a row that is not a trade
        is skipped with no note (it is not a failure, it is not a trade).
        """
        trades: list[dict] = []
        days = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = str(row.get("date") or "").strip()
            if not day:
                continue
            days.add(day)
            label = str(row.get("label") or "").upper()
            if label not in TRADE_LABELS:
                continue
            net = row.get("net_return")
            if not isinstance(net, (int, float)) or isinstance(net, bool) \
                    or not math.isfinite(float(net)):
                continue
            symbol = str((row.get("candidate") or {}).get("symbol")
                         or row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            entry_time = row.get("entry_time")
            stamp = None
            if isinstance(entry_time, str) and entry_time.strip():
                try:
                    stamp = datetime.fromisoformat(entry_time.strip())
                except ValueError:
                    stamp = None
            trades.append({
                "date": stamp.date().isoformat() if stamp else day,
                "day": day,
                "symbol": symbol,
                "label": label,
                "net": float(net),
                "entry": stamp,
            })
        trades.sort(key=lambda trade: (trade.get("day") or "",
                                       trade.get("date") or ""))
        memory = cls()
        memory.trades_read = len(trades)
        memory.days_read = len(days)
        if not trades:
            memory.honest_notes.append(
                "no closed trade in the history yet; the memory cannot "
                "veto anything it has not measured")
            return memory

        # The time ledger: bucket by minutes since that entry's own band
        # opened, weighted by recency (config.py's own decay).
        by_bucket: dict[str, list[dict]] = {}
        newest_day = trades[-1]["day"]
        if config.ADAPTIVE_DECAY_PER_DAY < 1.0:
            def day_weight(day: str) -> float:
                try:
                    in_between = (datetime.fromisoformat(newest_day)
                                  - datetime.fromisoformat(day)).days
                except ValueError:
                    in_between = 0
                return config.ADAPTIVE_DECAY_PER_DAY ** max(0, in_between)
        else:
            def day_weight(_day: str) -> float:
                return 1.0
        day_weights = {day: day_weight(day) for day in
                       {trade["day"] for trade in trades}}
        for trade in trades:
            weight = day_weights.get(trade["day"], 1.0)
            bucket = bucket_label(trade["entry"]) if trade["entry"] \
                else UNFILED_BUCKET
            by_bucket.setdefault(bucket, []).append({**trade, "weight": weight})
        for name, rows in sorted(by_bucket.items()):
            weight_sum = sum(row["weight"] for row in rows)
            expectancy = (sum(row["net"] * row["weight"] for row in rows)
                          / weight_sum) if weight_sum > 0 else None
            memory.buckets[name] = BucketTip(
                label=name,
                trades=len(rows),
                stops=sum(1 for row in rows if row["label"] in STOP_LABELS),
                wins=sum(1 for row in rows if row["label"] in WIN_LABELS),
                expectancy_net=None if expectancy is None
                else round(expectancy, 6),
            )

        # The symbol ledger: each symbol's consecutive stop-out streak,
        # newest trade first (config.py's own streak length).
        by_symbol: dict[str, list[dict]] = {}
        for trade in trades:
            by_symbol.setdefault(trade["symbol"], []).append(trade)
        for symbol, symbol_trades in by_symbol.items():
            streak = 0
            for trade in sorted(symbol_trades, key=lambda row: row["day"],
                                reverse=True):
                if trade["label"] in STOP_LABELS:
                    streak += 1
                    continue
                break
            if streak:
                memory.symbol_streaks[symbol] = streak
        return memory

    @classmethod
    def load(cls, extra: list[dict] | None = None,
             note_sink: dict | None = None) -> "AdaptiveMemory":
        """The runner's memory: the history that genuinely exists.

        `extra` is the session being finalized right now (src/research/
        session_history.session_rows takes the same argument). The loader
        refuses to raise: an unreadable archive is a stated gap, and a
        stated gap vetoes nothing (SO-3).
        """
        report: dict = {}
        rows = load_history_rows(note_sink=report)
        if note_sink is not None:
            note_sink.update(report)
        if extra:
            rows = list(rows)
            rows.extend(extra)
        return cls.from_rows(rows)

    # ----------------------------------------------------------------- exit

    def entry_veto(self, symbol: str, entry_at: datetime | None) -> str | None:
        """The learned refusal for one fresh entry, or None when it stands.

        Each law speaks only for the evidence behind it. A law with less
        than its own minimum behind it is silent for exactly that reason.
        """
        symbol = str(symbol or "").strip().upper()
        bucket_name = bucket_label(entry_at) if entry_at else UNFILED_BUCKET
        tip = self.buckets.get(bucket_name)
        if tip is not None \
                and tip.trades >= config.ADAPTIVE_MIN_BUCKET_TRADES \
                and tip.expectancy_net is not None \
                and tip.expectancy_net <= config.ADAPTIVE_MIN_BUCKET_NET:
            return (f"{bucket_name}: the last {tip.trades} closed entries "
                    f"in that hour averaged {tip.expectancy_net:+.2%} net "
                    f"({tip.stops} stop, {tip.wins} target); the quant stands "
                    f"down there until the record improves")
        streak = self.symbol_streaks.get(symbol, 0)
        if streak >= config.ADAPTIVE_SYMBOL_STOP_STREAK:
            return (f"{symbol}: its last {streak} entries each hit the stop "
                    f"(owner order 2026-10-31, learn from your mistakes); the "
                    f"quant refuses the same failed setup until one whole "
                    f"session closes inside its range")
        return None

    def market_veto(self, median_return: float | None) -> str | None:
        """The "be with the market" law for a CONFIRMED entry.

        The broad selloff veto already lives in the scanner's own strict
        law; this is the memory's stricter floor: an entry into any falling
        tape is a bet against the day's own direction, and the quant does
        not take it. The rank table is untouched, so the owner still sees
        what the scanner saw (as a call watch, the way 2026-10-29 ordered).
        """
        if median_return is not None \
                and median_return < config.ADAPTIVE_MARKET_TREND_FLOOR:
            return (f"the market's own median is {median_return:+.2%}; the "
                    f"quant does not enter against the market's direction")
        return None

    def as_dict(self) -> dict:
        """The whole measured memory, for the outcome record and the CLI."""
        return {
            "trades_read": self.trades_read,
            "days_read": self.days_read,
            "buckets": {name: tip.as_dict() for name, tip
                        in sorted(self.buckets.items())},
            "symbol_stop_streaks": dict(sorted(
                self.symbol_streaks.items(), key=lambda pair: -pair[1])),
            "notes": list(self.honest_notes),
            "law": {
                "min_bucket_trades": config.ADAPTIVE_MIN_BUCKET_TRADES,
                "min_bucket_net": config.ADAPTIVE_MIN_BUCKET_NET,
                "symbol_stop_streak": config.ADAPTIVE_SYMBOL_STOP_STREAK,
                "market_trend_floor": config.ADAPTIVE_MARKET_TREND_FLOOR,
                "decay_per_day": config.ADAPTIVE_DECAY_PER_DAY,
            },
        }


# The runner's own cache: the history is read once, then refreshed at
# most this often, so the one-second loop never pays a relay read per
# scan and a fresh runner re-learns from the archive at band start.
_CACHE_ROWS: list[dict] | None = None
_CACHE_AT = 0.0


def load_cached(extra: list[dict] | None = None,
                note_sink: dict | None = None) -> "AdaptiveMemory":
    """The memory the runner keeps, refreshed at most every TTL seconds.

    `extra` is the session being finalized right now; it rides the cached
    rows so the finalize can count today's own outcome before the archive
    even answers. Never raises; an unreadable history is a stated gap that
    vetoes nothing (SO-3).
    """
    import time
    global _CACHE_ROWS, _CACHE_AT
    fresh = (_CACHE_ROWS is not None
             and time.monotonic() - _CACHE_AT
             < config.ADAPTIVE_REFRESH_SECONDS)
    if not fresh:
        _CACHE_ROWS = load_history_rows(note_sink=note_sink)
        _CACHE_AT = time.monotonic()
    if extra:
        rows = list(_CACHE_ROWS or [])
        rows.extend(extra)
        return AdaptiveMemory.from_rows(rows)
    return AdaptiveMemory.from_rows(_CACHE_ROWS or [])


def load_history_rows(note_sink: dict | None = None) -> list[dict]:
    """session_rows, refused to raise; empty list with a note on failure."""
    report: dict = {}
    if session_history is None:
        report["error"] = "history loader unavailable"
        if note_sink is not None:
            note_sink.update(report)
        return []
    try:
        rows = session_history.session_rows(report=report)
    except Exception as exc:  # noqa: BLE001 - a stated gap, not a crash
        report["error"] = f"history unreadable: {type(exc).__name__}: {exc}"
        rows = []
    if note_sink is not None:
        note_sink.update(report)
    return rows


def bucket_label(entry_at: datetime) -> str:
    """Which hour bucket one entry stamp belongs to (SO-8).

    The minutes are measured from that day's own FIRST band open, so a
    Monday entry and a Friday entry are filed on the same law; the bands
    themselves come from src/data/sessions.py, never from a local clock.
    An entry outside every band files itself and says so.
    """
    day = entry_at.date()
    try:
        bands = session_bands(day)
        if not bands:
            return UNFILED_BUCKET
        interested_open, interested_close = band_bounds(day, bands[0])
        tz = entry_at.tzinfo or interested_open.tzinfo
        minutes_in = (entry_at
                      - datetime.combine(day, interested_open.timetz(), tzinfo=tz)
                      ).total_seconds() // 60
        span_minutes = max(1, int((interested_close - interested_open)
                                  .total_seconds() // 60))
    except Exception:  # pragma: no cover - the session law is import guarded
        return UNFILED_BUCKET
    if minutes_in < 0 or minutes_in > span_minutes:
        return UNFILED_BUCKET
    fractions = config.ADAPTIVE_BUCKET_FRACTIONS
    names = config.ADAPTIVE_BUCKET_NAMES
    for index, fraction in enumerate(fractions):
        if minutes_in < round(span_minutes * fraction):
            return names[index] if index < len(names) else f"bracket {index + 1}"
    return names[-1] if names else UNFILED_BUCKET


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="The quant's measured memory of its own closed trades")
    parser.add_argument("--show", action="store_true",
                        help="print the whole measured memory")
    args = parser.parse_args(argv)

    memory = AdaptiveMemory.load()
    print(json.dumps(memory.as_dict(), indent=2, allow_nan=False))
    if not args.show:
        return 0
    print()
    for name, tip in sorted(memory.buckets.items()):
        expectancy = ("none measured" if tip.expectancy_net is None
                      else f"{tip.expectancy_net:+.2%} net")
        print(f"- {name}: {tip.trades} trade(s) "
              f"({tip.stops} stop, {tip.wins} target), {expectancy}")
    if not memory.buckets:
        print("- no closed trade measured yet; nothing is vetoed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
