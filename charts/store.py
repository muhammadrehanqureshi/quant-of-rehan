"""The in-memory bar store: upsert, revision counting, and gap detection.

One series is one symbol at one resolution. The store is deliberately small
and lock guarded, because it is written by the ingestion thread and read by
several HTTP worker threads at once, and a half-applied upsert has to be
impossible rather than unlikely.

Two behaviours matter more than they look:

* **Upsert, not append.** The current minute's bar is revised while the
  exchange prints, so a fresh row replaces the row with the same timestamp
  instead of duplicating it. The store counts those revisions, which is how
  the API can say ``revised`` for a symbol whose last bar just changed.
* **Gaps are measured, never assumed.** A missing minute inside the session
  is a gap; a missing minute inside the Friday midday break is not, because
  the expected minute list comes from the session law. A symbol that has
  printed nothing at all yet is not a one-bar chart with zeros, it is an
  empty series with a stated reason.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from charts.contract import Bar, ContractError, Gap, SourceInfo


@dataclass
class Series:
    """One symbol at one resolution, with its provenance."""

    symbol: str
    resolution: str
    source: SourceInfo
    bars: list[Bar] = field(default_factory=list)
    #: How many times a bar's values were replaced after first appearing.
    revisions: int = 0
    #: The Karachi stamp of the last successful upsert.
    updated_at: str = ""
    #: The upstream source observation time, not when this server was polled.
    observed_at: str = ""
    #: Free-form measured notes, carried into the payload.
    notes: list[str] = field(default_factory=list)

    @property
    def last(self) -> Bar | None:
        return self.bars[-1] if self.bars else None


class BarStore:
    """Thread safe storage for every series the service currently holds."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._series: dict[tuple[str, str], Series] = {}
        self._symbols: dict[str, dict] = {}

    # ------------------------------------------------------------- symbols
    def register_symbol(self, symbol: str, **facts) -> None:
        """Record a symbol the service can serve, with whatever is known."""
        key = symbol.strip().upper()
        if not key:
            raise ContractError("a symbol cannot be empty")
        with self._lock:
            entry = self._symbols.setdefault(key, {"symbol": key})
            entry.update({k: v for k, v in facts.items() if v is not None})

    def symbols(self) -> list[dict]:
        with self._lock:
            return [dict(row) for row in sorted(self._symbols.values(),
                                                key=lambda r: r["symbol"])]

    def has_symbol(self, symbol: str) -> bool:
        with self._lock:
            return symbol.strip().upper() in self._symbols

    # -------------------------------------------------------------- bars
    def upsert(self, symbol: str, resolution: str, bars: Iterable[Bar],
               source: SourceInfo, *, updated_at: str,
               observed_at: str = "") -> int:
        """Merge bars into a series, returning how many rows were new.

        A bar whose timestamp already exists replaces it and counts as a
        revision; a bar with a new timestamp is appended in order. Replacing
        rather than duplicating is what keeps the current minute honest.
        """
        key = (symbol.strip().upper(), resolution)
        appended = 0
        with self._lock:
            series = self._series.get(key)
            if series is None:
                series = Series(symbol=key, resolution=resolution,
                                source=source)
                self._series[key] = series
            known = {bar.t: bar for bar in series.bars}
            for bar in bars:
                existing = known.get(bar.t)
                if existing is None:
                    known[bar.t] = bar
                    appended += 1
                elif existing != bar:
                    known[bar.t] = bar
                    series.revisions += 1
            series.bars = sorted(known.values(), key=lambda b: b.t)
            series.source = source
            series.updated_at = updated_at
            series.observed_at = observed_at or updated_at
        return appended

    def series(self, symbol: str, resolution: str) -> Series | None:
        with self._lock:
            found = self._series.get((symbol.strip().upper(), resolution))
            if found is None:
                return None
            # A shallow copy: the payload builder must not hold the lock.
            return Series(symbol=found.symbol, resolution=found.resolution,
                          source=found.source, bars=list(found.bars),
                          revisions=found.revisions,
                          updated_at=found.updated_at,
                          observed_at=found.observed_at,
                          notes=list(found.notes))

    def snapshot(self, symbol: str, resolution: str,
                 limit: int | None = None) -> list[Bar]:
        found = self.series(symbol, resolution)
        if found is None:
            return []
        return found.bars[-limit:] if limit else found.bars

    def latest_resolution(self, symbol: str) -> str | None:
        """The finest resolution with data for a symbol, or None."""
        order = {"1m": 0, "session": 1, "1d": 2}
        with self._lock:
            keys = [key for key in self._series
                    if key[0] == symbol.strip().upper() and self._series[key].bars]
        if not keys:
            return None
        return sorted((key[1] for key in keys), key=lambda r: order.get(r, 9))[0]

    def note(self, symbol: str, resolution: str, line: str) -> None:
        with self._lock:
            found = self._series.get((symbol.strip().upper(), resolution))
            if found is not None and line not in found.notes:
                found.notes.append(line)

    # -------------------------------------------------------------- gaps
    @staticmethod
    def gaps(bars: Iterable[Bar], expected: Iterable[datetime], *,
             reason: str = "no bar was printed in this minute",
             step_minutes: int = 1) -> list[Gap]:
        """Contiguous stretches of expected buckets with no bar.

        `expected` is the session law's own bucket list for the day up to
        now, so a break or a holiday produces no gap at all. `step_minutes`
        is the width of one expected bucket: one minute for the tape's own
        grain, five for a five-minute chart, and so on. The comparison is
        done on timestamps truncated to the minute, which is the grain of
        both sides.
        """
        step = max(1, int(step_minutes))
        step_seconds = step * 60
        def stamp(moment: datetime) -> str:
            return moment.replace(second=0, microsecond=0).isoformat(
                timespec="seconds")

        have = {bar.t for bar in bars}
        missing = [moment for moment in expected if stamp(moment) not in have]
        if not missing:
            return []
        missing.sort()
        gaps: list[Gap] = []
        run_start = missing[0]
        previous = missing[0]
        for moment in missing[1:]:
            if (moment - previous).total_seconds() <= step_seconds:
                previous = moment
                continue
            gaps.append(Gap(start=run_start.isoformat(timespec="seconds"),
                            end=previous.isoformat(timespec="seconds"),
                            minutes=int((previous - run_start).total_seconds()
                                        // step_seconds) * step + step,
                            reason=reason))
            run_start = previous = moment
        gaps.append(Gap(start=run_start.isoformat(timespec="seconds"),
                        end=previous.isoformat(timespec="seconds"),
                        minutes=int((previous - run_start).total_seconds()
                                    // step_seconds) * step + step,
                        reason=reason))
        return gaps

    def clear(self) -> None:
        with self._lock:
            self._series.clear()
            self._symbols.clear()
