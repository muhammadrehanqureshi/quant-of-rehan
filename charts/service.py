"""Payload assembly: one code path from a store to a wire ready chart.

Every consumer of a series (the HTTP API, the SSE snapshot, the runnable
example and the tests) builds its payload here. That is the point: there is
exactly one place where notes, gaps and provenance are attached, so a chart
cannot be honest through one door and quiet through another.

The rules this function implements, in order:

1. Bars come from the store, never from a fresh upstream call, so a slow
   source cannot become a slow page.
2. A missing series is an empty payload with a measured sentence, not a row
   of zeroes (SO-3).
3. Gaps are computed against the session law's own expected minutes, so the
   Friday midday break and a holiday are never reported as missing data.
4. Provenance travels with the bars: which source, how delayed it is, how
   many bars were revised, and what the source itself says about its limits.
"""

from __future__ import annotations

from datetime import datetime
from itertools import islice

from charts import sessions
from charts.adapters.base import BarSource
from charts.contract import ChartPayload, SourceInfo
from charts.store import BarStore, Series


def _stamp(moment) -> str:
    """A session minute as the store's own bar timestamps spell it."""
    return moment.replace(second=0, microsecond=0).isoformat(timespec="seconds")

#: Below this many missing minutes a hole is a print artefact, not a gap: a
#: single absent minute inside a live tape is normal, and calling every one of
#: them a data gap would train a reader to ignore the list.
GAP_FLOOR_MINUTES = 2


def series_notes(series: Series | None, *, expected_minutes: int,
                 bars: int) -> list[str]:
    lines: list[str] = []
    if series is not None:
        lines.extend(series.notes)
        if series.revisions:
            lines.append(f"{series.revisions} bar(s) were revised after they "
                         f"first appeared, which is normal for the minute "
                         f"still forming")
        if series.updated_at:
            lines.append(f"last updated {series.updated_at}")
    if bars and expected_minutes:
        lines.append(f"{bars} bar(s) held against {expected_minutes} expected "
                     f"session minute(s)")
    return lines


def build_payload(store: BarStore, source: BarSource, symbol: str,
                  resolution: str, *, limit: int = 1500,
                  moment: datetime | None = None) -> ChartPayload:
    """One symbol's chart payload, ready for the wire.

    ``limit`` keeps a long session from shipping thousands of bars to a
    screen that can show a few hundred candles: the tail is the part a live
    chart reads, and the full series stays in the store for history.

    ``moment`` is the session moment the payload describes, for the market
    context and the expected minutes the gaps are measured against. The
    default is the Karachi now, which is what a live service wants; a caller
    rendering a series that was ingested for another moment (a fixed replay
    clock, the offline demo) passes its own clock so the bars and the
    context describe the same session instead of two different days.
    """
    symbol = symbol.strip().upper()
    context = sessions.market_context(moment)
    series = store.series(symbol, resolution)
    bars = list(series.bars) if series else []
    if limit > 0 and len(bars) > limit:
        bars = bars[-limit:]
    expected = sessions.expected_minutes(moment)
    # A series that begins mid-session is not a series with a morning long
    # gap: it is a series that begins mid-session. Gaps are only counted from
    # the first bar onward, and the late start gets its own sentence instead,
    # because the two are different facts about the day.
    window = expected
    late_start = 0
    if bars:
        first = bars[0].t
        window = [moment for moment in expected if _stamp(moment) >= first]
        late_start = len(expected) - len(window)
    # Gaps are only meaningful against bars that exist: with nothing at all
    # there is no series to be missing minutes from, and a list of 300
    # "gaps" would bury the one sentence that actually explains the chart.
    gaps = ([gap for gap in BarStore.gaps(bars, window)
             if gap.minutes >= GAP_FLOOR_MINUTES] if bars else [])
    if series is None:
        notes = [f"no {resolution} series exists yet for {symbol}: nothing "
                 f"has been ingested, which is not the same as a price of "
                 f"zero"]
    else:
        notes = series_notes(series, expected_minutes=len(expected),
                             bars=len(bars))
        if not bars and context.trading_day:
            notes.append(
                f"{symbol} is a known symbol but the source has published "
                f"no bar for it this session yet; it will appear when it "
                f"prints rather than being drawn as zero")
        if late_start:
            notes.append(
                f"this series starts at {bars[0].t[11:16]} Karachi, "
                f"{late_start} session minute(s) after the session opened; "
                f"the earlier minutes are not in it")
        # A series can belong to another day than the market context: at
        # 09:00 the tape is still yesterday's, and the offline replay
        # deliberately serves the last session rather than an empty frame.
        # Without this sentence a reader would take that day's close for
        # today's price, which is precisely the mistake the notes exist to
        # prevent.
        if bars and bars[-1].t[:10] != context.as_of[:10]:
            notes.append(
                f"these bars are the {bars[-1].t[:10]} session, and today "
                f"has no bar in this series yet: the newest candle is that "
                f"day's last price, not today's")
        delayed = source.capabilities().source.delay_seconds
        if delayed:
            notes.append(
                f"this source publishes with a delay of about "
                f"{delayed // 60} minute(s), so the newest bar is not the "
                f"newest trade")
    return ChartPayload(symbol=symbol, resolution=resolution,
                        source=(series.source if series else
                                source.capabilities().source),
                        market=context, as_of=context.as_of, bars=bars,
                        gaps=gaps, notes=notes)


def build_many(store: BarStore, source: BarSource, symbols: list[str],
               resolution: str, *, limit: int = 1500,
               moment: datetime | None = None) -> dict[str, dict]:
    """Payloads for several symbols, keyed by symbol."""
    return {symbol: build_payload(store, source, symbol, resolution,
                                  limit=limit, moment=moment).as_dict()
            for symbol in islice(symbols, 0, 200)}
