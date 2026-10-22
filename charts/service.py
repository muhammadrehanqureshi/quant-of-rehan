"""Payload assembly: one code path from data to a wire ready chart.

Every consumer of a series (the HTTP API, the SSE snapshot, the runnable
example and the tests) builds its payload here. That is the point: there is
exactly one place where notes, gaps and provenance are attached, so a chart
cannot be honest through one door and quiet through another.

The rules this module implements, in order:

1. Bars come from the store for the session that is running, and from the
   durable archive for a session that is finished. Neither path makes a
   network call while a chart is being drawn, so a slow upstream cannot become
   a slow page.
2. A missing series is an empty payload with a measured sentence, not a row of
   zeroes (SO-3).
3. Gaps are computed against the session law's own expected minutes, so the
   Friday midday break and a holiday are never reported as missing data. For a
   finished session the whole day is expected, not the part of it that had
   already happened.
4. Provenance travels with the bars: which source, which session, which file,
   whether that session is archived, how delayed the source is, how many bars
   were revised, and what the source itself says about its limits.
5. **The chart works at any hour.** When the clock says today is a trading day
   but nothing has been ingested (the recorder is off, the machine was asleep,
   it is the middle of the night before a session), the newest archived
   session that holds this symbol is served instead, and the payload says so in
   one sentence and in its ``session`` block. An empty frame is never dressed
   up as a price, and a real previous session is never hidden behind one.
"""

from __future__ import annotations

from datetime import date, datetime
from itertools import islice

from charts import resolutions as ladder
from charts import sessions
from charts.adapters.base import BarSource
from charts.contract import Bar, ChartPayload, ChartSession, ContractError
from charts.ratelimit import UpstreamError
from charts.store import BarStore, Series


def _stamp(moment) -> str:
    """A session minute as the store's own bar timestamps spell it."""
    return moment.replace(second=0, microsecond=0).isoformat(timespec="seconds")

#: Below this many missing minutes a hole is a print artefact, not a gap: a
#: single absent minute inside a live tape is normal, and calling every one of
#: them a data gap would train a reader to ignore the list.
GAP_FLOOR_MINUTES = 2

#: Resolutions whose buckets are the tape's own minute grid. Everything else
#: is either finer (ticks, where a missing second is not a session gap) or
#: calendar (where a missing day is reported as an absent session, not a
#: stretch of missing minutes).
_MINUTE_RUNGS = ("1m",)


def _expected_for(day: date, resolution: str) -> list[datetime]:
    """The session's expected bucket starts at this resolution."""
    spec = ladder.spec_for(resolution)
    if spec.calendar or spec.subminute:
        return []
    if spec.id in _MINUTE_RUNGS:
        return sessions.session_minutes(day)
    return ladder.expected_bucket_starts(day, resolution)


def _gap_step(resolution: str) -> int:
    spec = ladder.spec_for(resolution)
    return max(1, spec.minutes or 1)


def _build_note(resolution: str) -> str:
    try:
        return ladder.BUILD_NOTES[ladder.normalise(resolution)]
    except (KeyError, ValueError):
        return ""


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


def _current_session(moment: datetime | None) -> date:
    return sessions.law.as_karachi(moment).date()


def _live_source_name(source: BarSource) -> str:
    """The file behind a live series, when the source can name one.

    A chart should be able to say which recording it is drawing, and the tape
    adapter is the only source that can: the portal reads a page and the
    replay source is synthetic, so both honestly report no file.
    """
    namer = getattr(source, "live_capture_name", None)
    if not callable(namer):
        return ""
    try:
        return str(namer() or "")
    except Exception:  # noqa: BLE001 - naming a file may never break a chart
        return ""


def newest_archived_day(source: BarSource, symbol: str,
                        before: date | None = None) -> str | None:
    """The newest session the source has bars for this symbol in, or None.

    Asked of the source itself rather than guessed from the clock: a symbol
    that only ever traded last Tuesday must fall back to last Tuesday, and a
    source that cannot list its sessions simply returns None and gets an empty
    chart with a sentence instead of a wrong one.
    """
    lister = getattr(source, "sessions", None)
    if not callable(lister):
        return None
    try:
        rows = lister() or []
    except Exception:  # noqa: BLE001 - a listing may never break a chart
        return None
    for row in rows:
        day = str(row.get("day", ""))
        if not day or (before is not None and day >= before.isoformat()):
            continue
        has = getattr(source, "history", None)
        if not callable(has):
            return day
        try:
            if has(symbol, "1m", limit=1, day=day):
                return day
        except Exception:  # noqa: BLE001 - try the next session
            continue
    return None


def _served_from_archive(source: BarSource, symbol: str, day) -> bool:
    """Did the source read this series from its durable archive?

    Asked of the source, because only the source knows: a finished day it has
    stored is served from the archive, and a session read from a recording
    file is not. A source that cannot answer is treated as live, which is the
    honest reading of a series this service did not store itself.
    """
    ask = getattr(source, "served_from_archive", None)
    if not callable(ask):
        return False
    try:
        return bool(ask(symbol, day=day))
    except Exception:  # noqa: BLE001 - labelling may never break a chart
        return False


def _merged_days_payload(store: BarStore, source: BarSource, symbol: str,
                         resolution: str, *, limit: int, context,
                         moment: datetime | None, today: date,
                         days: int) -> ChartPayload:
    """The newest ``days`` sessions, concatenated into one contiguous chart.

    This is the TradingView habit the owner asked for: an intraday chart that
    keeps more of the market's history than one session. The sessions are the
    source's own list, newest first, so the merge can only ever read sessions
    that exist; each one is read through the same per-session path a named-day
    chart uses, so an archived day contributes exactly the bars and gaps it
    would alone.

    Sessions are packed, not stretched: the hours between one session's close
    and the next open are drawn as a session break, not as elapsed time on a
    clock axis. The payload says so, because a reader who expects 24 hours of
    market deserves to know why Sunday night is missing from the screen.
    """
    lister = getattr(source, "sessions", None)
    if not callable(lister):
        raise ContractError(
            f"source {getattr(source, 'name', source)} serves the running "
            f"session only; it keeps no store to merge several from")
    try:
        rows = lister() or []
    except Exception as exc:  # noqa: BLE001 - a listing failure is a 502 door
        raise ContractError(
            f"the session store could not be listed: {type(exc).__name__}") from exc
    wanted_days = [str(row.get("day", "")) for row in rows]
    wanted_days = [day for day in wanted_days if day][:max(1, int(days))]
    if not wanted_days:
        raise ContractError("the session store holds no day to merge")
    payloads: list[ChartPayload] = []
    for name in wanted_days:
        try:
            payloads.append(_session_payload(
                source, symbol, resolution, day=name, limit=0,
                context=context, moment=moment))
        except ContractError:
            raise
        except Exception as exc:  # noqa: BLE001 - one session may not undo all
            payloads.append(ChartPayload(
                symbol=symbol, resolution=resolution,
                source=source.capabilities().source, market=context,
                as_of=context.as_of, bars=[], gaps=[],
                notes=[f"session {name} could not be read ({type(exc).__name__}), "
                       f"so it is absent from this chart rather than invented"],
                session=ChartSession(day=name, current=False, archived=False,
                                     note="session unread")))
    payloads.reverse()  # oldest first
    bars: list[Bar] = []
    seen: dict[str, Bar] = {}
    held = 0
    empty_days: list[str] = []
    for payload in payloads:
        if not payload.bars:
            empty_days.append(payload.session.day)
            continue
        held += 1
        for bar in payload.bars:
            seen[bar.t] = bar
    bars = [seen[key] for key in sorted(seen)]
    if limit > 0 and len(bars) > limit:
        bars = bars[-limit:]
    gaps: list = []
    for payload in payloads:
        gaps.extend(payload.gaps)
    gaps.sort(key=lambda gap: gap.start)
    notes: list[str] = []
    if held:
        notes.append(
            f"merged {held} session(s) with bars for {symbol} of "
            f"{len(wanted_days)} session(s) requested, from "
            f"{payloads[0].session.day} to {payloads[-1].session.day}")
    if empty_days:
        notes.append(
            f"{len(empty_days)} of these session(s) held no bar for {symbol} "
            f"(holiday or no trades), which is an absence, not a flat zero")
    notes.append(
        "sessions are packed edge to edge: the hours between one session's "
        "close and the next open are a session break on the chart, not "
        "elapsed time")
    newest = payloads[-1]
    if newest.bars:
        notes.append(
            f"the newest candle is the {newest.session.day} session's latest "
            "bar" + (", still forming" if newest.session.current
                     else ", finished"))
    else:
        notes.insert(
            0, f"no bar exists for {symbol} in any of the {len(wanted_days)} "
               f"session(s) read, which is not a price of zero")
    session_day = newest.session.day if newest.bars else wanted_days[0]
    info = getattr(source, "source_info", None)
    source_info = (info(symbol, day=session_day) if callable(info)
                   else source.capabilities().source)
    return ChartPayload(
        symbol=symbol, resolution=resolution, source=source_info,
        market=context, as_of=context.as_of, bars=bars, gaps=gaps,
        notes=notes,
        session=ChartSession(
            day=session_day,
            current=newest.session.current,
            archived=bool(newest.session.archived),
            source=newest.session.source, capture=newest.session.capture,
            built_at=newest.session.built_at,
            volume_available=any(bar.v > 0 for bar in bars),
            note=(f"merged chart over {len(wanted_days)} session(s); newest "
                  f"session {newest.session.day}. {newest.session.note}")))


def _session_payload(source: BarSource, symbol: str, resolution: str, *,
                     day: str, limit: int, context, moment: datetime | None,
                     ) -> ChartPayload:
    """One named session, read from the source's own store for that day."""
    day_date = date.fromisoformat(day)
    spec = ladder.spec_for(resolution)
    bars = list(source.history(symbol, resolution, limit=limit or 1500,
                               day=day_date))
    expected = _expected_for(day_date, resolution)
    step = _gap_step(resolution)
    gap_floor = max(GAP_FLOOR_MINUTES, step)
    gaps = ([gap for gap in BarStore.gaps(bars, expected, step_minutes=step)
             if gap.minutes >= gap_floor] if bars and expected else [])
    notes = list(_source_notes(source, symbol, day=day_date))
    build_note = _build_note(resolution)
    if build_note:
        notes.append(build_note)
    if bars:
        if expected:
            first = bars[0].t
            window = [bucket for bucket in expected if _stamp(bucket) >= first]
            late_start = len(expected) - len(window)
            notes.append(f"{len(bars)} bar(s) held against {len(expected)} "
                         f"expected {spec.label} bucket(s) in a finished "
                         f"session")
            if late_start and not spec.calendar:
                notes.append(
                    f"this series starts at {bars[0].t[11:16]} Karachi, "
                    f"{late_start} bucket(s) after the session opened; the "
                    f"earlier buckets are not in it")
        elif spec.calendar:
            notes.append(f"{len(bars)} {spec.label} bar(s) folded from the "
                         f"sessions this service holds for {symbol}")
        else:
            notes.append(f"{len(bars)} {spec.label} bar(s) built from the "
                         f"capture's own tick rows; missing seconds are absent "
                         f"ticks, not a measured session gap")
    else:
        if spec.subminute:
            notes.append(
                f"no {spec.label} bars exist for {symbol} on {day}: the "
                f"durable archive keeps minute bars, and second bars can only "
                f"be built while that session's capture file is on disk")
        elif spec.calendar:
            notes.append(
                f"no {spec.label} bar exists for {symbol} in the sessions "
                f"this service holds, which is not the same as a price of "
                f"zero")
        else:
            notes.append(
                f"no {resolution} bar exists for {symbol} on {day}: the "
                f"session is stored and this symbol printed nothing in it, "
                f"which is not the same as a price of zero")
    summary = getattr(source, "archive_summary", lambda _day: None)(day)
    capture = None
    built_at = ""
    volume_available = any(bar.v > 0 for bar in bars)
    if summary is not None:
        capture = summary.capture
        built_at = summary.built_at
        volume_available = volume_available or summary.volume_available
    info = getattr(source, "source_info", None)
    source_info = (info(symbol, day=day_date) if callable(info)
                   else source.capabilities().source)
    archived = _served_from_archive(source, symbol, day_date)
    current = day == _current_session(moment).isoformat()
    # The recording behind this series is named either by the archive's own
    # manifest (a stored session) or by the source's live capture (a session
    # read from the file the recorder is still writing).
    file_name = (capture or {}).get("name", "") or _live_source_name(source)
    if archived:
        note = (f"this is the archived {day} session, so nothing in it is a "
                f"live price")
    elif current:
        note = (f"this is today's {day} session read from its recording file"
                + (f" ({file_name})" if file_name else "")
                + ", so the newest candle may still be forming")
    else:
        note = (f"this is the finished {day} session, read from its recording "
                f"file" + (f" ({file_name})" if file_name else "")
                + ", so nothing in it is a live price")
    return ChartPayload(
        symbol=symbol, resolution=resolution, source=source_info,
        market=context, as_of=context.as_of, bars=bars, gaps=gaps, notes=notes,
        session=ChartSession(
            day=day, current=current, archived=archived,
            source=file_name, capture=capture,
            built_at=built_at, volume_available=volume_available,
            note=note))


def _source_notes(source: BarSource, symbol: str, *, day=None) -> list[str]:
    """The source's own caveats for a symbol, when it can report them."""
    if day is None:
        reporter = getattr(source, "notes", None)
        if not callable(reporter):
            return []
        try:
            return list(reporter(symbol))
        except TypeError:
            return []
    reporter = getattr(source, "notes", None)
    if not callable(reporter):
        return []
    try:
        return list(reporter(symbol, day=day))
    except TypeError:
        try:
            return list(reporter(symbol))
        except Exception:  # noqa: BLE001
            return []
    except Exception:  # noqa: BLE001
        return []


def _live_multi_payload(store: BarStore, source: BarSource, symbol: str,
                        resolution: str, *, limit: int, context,
                        moment: datetime | None, today: date) -> ChartPayload:
    """A live payload for any rung other than the store's own minute grain.

    The store only ever holds the tape's minute bars. Everything else is asked
    of the source, which folds minutes (or builds seconds from ticks) for the
    session the clock calls today. A source that cannot answer produces an
    empty series with the source's own sentence, never an invented candle.
    """
    spec = ladder.spec_for(resolution)
    bars: list[Bar] = []
    failure = ""
    fallback_day: str | None = None
    history = getattr(source, "history", None)
    if not callable(history):
        failure = (f"source {getattr(source, 'name', source)} cannot serve "
                   f"{spec.label} bars")
    else:
        try:
            bars = list(history(symbol, resolution,
                                limit=limit or 1500))
        except UpstreamError as exc:
            failure = exc.detail
        except Exception as exc:  # noqa: BLE001 - named, never silent
            failure = f"{type(exc).__name__}: {exc}"
        if not bars:
            # The 24/7 rule applies to every rung, not just minutes. A live
            # 5-minute chart at 02:00 would otherwise be an empty frame while
            # the archive holds the whole previous session.
            fallback = newest_archived_day(source, symbol, before=today)
            if fallback:
                try:
                    rows = list(history(symbol, resolution,
                                        limit=limit or 1500,
                                        day=date.fromisoformat(fallback)))
                except Exception:  # noqa: BLE001 - reported below
                    rows = []
                if rows:
                    bars = rows
                    fallback_day = fallback
                    failure = ""
    if limit > 0 and len(bars) > limit:
        bars = bars[-limit:]

    notes = list(_source_notes(source, symbol,
                               day=(date.fromisoformat(fallback_day)
                                    if fallback_day else None)))
    build_note = _build_note(resolution)
    if build_note:
        notes.append(build_note)
    if fallback_day:
        notes.insert(
            0, f"today ({today.isoformat()}) has no bar for {symbol} yet, so "
               f"this is the newest stored session, {fallback_day}; the "
               f"newest candle is that session's last price, not a live one")
    if failure:
        notes.insert(0, failure)
    if bars:
        notes.append(f"{len(bars)} {spec.label} bar(s) on this chart")
        if spec.calendar:
            notes.append(
                f"these {spec.label} bars end at the {bars[-1].t[:10]} "
                f"session; a calendar chart is built from every session this "
                f"service holds")
        if bars[-1].t[:10] != context.as_of[:10]:
            notes.append(
                f"these bars end on the {bars[-1].t[:10]} session, not "
                f"today: the newest candle is that session's close, not a "
                f"live price")
    else:
        notes.append(
            f"no {spec.label} bar exists for {symbol} yet: nothing has been "
            f"ingested at this resolution, which is not the same as a price "
            f"of zero")

    expected: list[datetime] = []
    gap_day = date.fromisoformat(fallback_day) if fallback_day else today
    if not spec.calendar and not spec.subminute:
        expected = [bucket for bucket in
                    ladder.expected_bucket_starts(gap_day, resolution)
                    if fallback_day is not None
                    or bucket <= sessions.law.as_karachi(moment)]
    gaps = []
    if bars and expected and bars[-1].t[:10] == gap_day.isoformat():
        first = bars[0].t
        window = [bucket for bucket in expected if _stamp(bucket) >= first]
        step = _gap_step(resolution)
        gaps = [gap for gap in
                BarStore.gaps(bars, window, step_minutes=step)
                if gap.minutes >= max(GAP_FLOOR_MINUTES, step)]
    delayed = source.capabilities().source.delay_seconds
    if delayed:
        notes.append(
            f"this source publishes with a delay of about "
            f"{delayed // 60} minute(s), so the newest bar is not the "
            f"newest trade")

    session_day = bars[-1].t[:10] if bars else (fallback_day or
                                                today.isoformat())
    info = getattr(source, "source_info", None)
    day_date = date.fromisoformat(session_day)
    source_info = (info(symbol, day=day_date) if callable(info)
                   else source.capabilities().source)
    archived = (fallback_day is not None
                or _served_from_archive(source, symbol, day_date))
    volume_available = any(bar.v > 0 for bar in bars)
    note = ""
    if fallback_day:
        note = (f"fallback to the newest stored session ({fallback_day}) "
                f"because {today.isoformat()} holds no bar for {symbol}")
    elif archived:
        note = (f"this is the archived {session_day} session, so nothing "
                f"in it is a live price")
    return ChartPayload(
        symbol=symbol, resolution=spec.id, source=source_info,
        market=context, as_of=context.as_of, bars=bars, gaps=gaps,
        notes=notes,
        session=ChartSession(
            day=session_day,
            current=session_day == today.isoformat(),
            archived=archived, source=_live_source_name(source),
            note=note,
            volume_available=volume_available))


def build_payload(store: BarStore, source: BarSource, symbol: str,
                  resolution: str, *, limit: int = 1500,
                  moment: datetime | None = None,
                  day: date | str | None = None, days: int = 0) -> ChartPayload:
    """One symbol's chart payload, ready for the wire.

    ``limit`` keeps a long session from shipping thousands of bars to a screen
    that can show a few hundred candles: the tail is the part a live chart
    reads, and the full series is on disk (live series in the store, finished
    sessions in the archive).

    ``moment`` is the session moment the payload describes, for the market
    context and the expected minutes the gaps are measured against. The
    default is the Karachi now, which is what a live service wants; a caller
    rendering a series that was ingested for another moment (a fixed replay
    clock, the offline demo) passes its own clock so the bars and the context
    describe the same session instead of two different days.

    ``day`` asks for one specific session by name. Without it, the payload
    describes the session the clock calls today, and falls back to the newest
    archived session that holds this symbol when today has nothing to show.

    ``days`` bigger than one (and no ``day`` named) asks for the newest
    sessions merged into one contiguous intraday chart. A calendar rung
    ignores it: its whole point is that the bars already span the sessions.
    """
    symbol = symbol.strip().upper()
    try:
        canonical = ladder.normalise(resolution)
    except ValueError as exc:
        raise ContractError(str(exc)) from exc
    resolution = canonical
    context = sessions.market_context(moment)
    today = _current_session(moment)
    wanted = day.isoformat() if isinstance(day, date) else (
        str(day).strip() if day else None)
    if wanted:
        # A caller that names a session gets that session, including today: a
        # chart that says "2026-10-16" must show 2026-10-16 rather than
        # whichever series the live store happens to hold. Only a source with
        # a session store can answer, so anything else is the caller's 400.
        if not callable(getattr(source, "sessions", None)):
            raise ContractError(
                f"source {getattr(source, 'name', source)} serves the running "
                f"session only; it keeps no store to read {wanted} from")
        return _session_payload(source, symbol, resolution, day=wanted,
                                limit=limit, context=context, moment=moment)

    spec = ladder.spec_for(resolution)
    if days > 1 and not spec.calendar:
        return _merged_days_payload(store, source, symbol, resolution,
                                    limit=limit, context=context,
                                    moment=moment, today=today, days=days)

    if resolution != "1m":
        return _live_multi_payload(store, source, symbol, resolution,
                                   limit=limit, context=context,
                                   moment=moment, today=today)

    series = store.series(symbol, resolution)
    bars = list(series.bars) if series else []
    if limit > 0 and len(bars) > limit:
        bars = bars[-limit:]

    if not bars:
        # Nothing has been ingested for today. Before showing an empty frame,
        # ask whether a finished session holds this symbol: a chart service
        # that only works during exchange hours is a chart service that is
        # useless when the owner actually has time to look at it.
        fallback = newest_archived_day(source, symbol, before=today)
        if fallback:
            payload = _session_payload(source, symbol, resolution,
                                       day=fallback, limit=limit,
                                       context=context, moment=moment)
            payload.notes.insert(
                0, f"today ({today.isoformat()}) has no bar for {symbol} yet, "
                   f"so this is the newest stored session, "
                   f"{fallback}; the newest candle is that session's last "
                   f"price, not a live one")
            payload.session = ChartSession(
                day=payload.session.day, current=False, archived=True,
                source=payload.session.source, capture=payload.session.capture,
                built_at=payload.session.built_at,
                volume_available=payload.session.volume_available,
                note=f"fallback to the newest stored session ({fallback}) "
                     f"because {today.isoformat()} holds no bar for {symbol}")
            return payload

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
                f"day's close, not today's price")
        delayed = source.capabilities().source.delay_seconds
        if delayed:
            notes.append(
                f"this source publishes with a delay of about "
                f"{delayed // 60} minute(s), so the newest bar is not the "
                f"newest trade")
    observed_at = ""
    if series is not None:
        observed_at = series.observed_at
        observation_reader = getattr(source, "observation_at", None)
        if callable(observation_reader):
            observed_at = observation_reader(symbol) or observed_at
        if observed_at:
            notes.append(f"last broker observation {observed_at}")
    session_day = (bars[-1].t[:10] if bars else
                   (series.updated_at[:10] if series and series.updated_at
                    else today.isoformat()))
    return ChartPayload(symbol=symbol, resolution=resolution,
                        source=(series.source if series else
                                source.capabilities().source),
                        market=context, as_of=context.as_of, bars=bars,
                        gaps=gaps, notes=notes,
                        observed_at=observed_at or context.as_of,
                        session=ChartSession(
                            day=session_day,
                            current=session_day == today.isoformat(),
                            archived=False, source=_live_source_name(source),
                            note="",
                            volume_available=any(bar.v > 0 for bar in bars)))


def build_many(store: BarStore, source: BarSource, symbols: list[str],
               resolution: str, *, limit: int = 1500,
               moment: datetime | None = None) -> dict[str, dict]:
    """Payloads for several symbols, keyed by symbol."""
    return {symbol: build_payload(store, source, symbol, resolution,
                                  limit=limit, moment=moment).as_dict()
            for symbol in islice(symbols, 0, 200)}
