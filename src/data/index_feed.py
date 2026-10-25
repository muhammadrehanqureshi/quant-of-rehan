#!/usr/bin/env python3
"""The exchange's own index levels, read from the capture's EXS-FEED frames.

Owner correction 2026-10-20: the chart showed "KSE100" as an equal-weight
proxy rebased to 1000, and the owner was right to call it wrong. The broker's
read-only recorder banks every frame it receives, including the index frames
(``EXS-FEED*``) that carry the real published levels: on 2026-10-16 the KSE100
frame read ``KSE100;166231.18;45.02;166599.29;413.125;165956.51;...`` , the
real level, the day's change against the previous close, the session high and
low, and the totals. This module turns those frames into bars.

Every stamp is read on the exchange's own clock, Asia/Karachi (UTC+5), never
in whatever zone the host machine happens to be in.

What one EXS-FEED frame carries, measured on the real captures (2026-10-12,
10-13, 10-14, 10-16, 10-18 , every file banks the same layout):

    stamp            ``10/16/2026 10:05:34 AM`` Karachi, per index group
    fields[0]        index name (KSE100, KSE30, KMI30, BKTI, ALLSHR)
    fields[1]        the index value
    fields[2]        day change vs the previous close
    fields[3]        session high so far (absolute level)
    fields[5]        session low so far (absolute level)
    fields[6..8]     advances / declines / unchanged
    fields[10]       session volume so far (shares)
    fields[11]       session traded value so far (PKR)

Bars are built at the minute a frame arrived in, the same honest clock
``tape_bars`` uses (the arrival stamp, never a carried print clock). within a
minute, open is the first value seen, close the last, and high/low span the
values seen in that minute; the session's running extremes are reported in
the session note rather than forged into a single minute.

``ALLSHR`` is the exchange's own all-shares index, which this service serves
as ``KMIALLSHR`` , the name the card and the watchlist already used. The
level is authoritative; the mental model "all shares" is unchanged.

Previous closes, the base of the day's change, are read from the frame
itself (``value - change``), so each session's first bar can also serve as
the previous close for cross-session chaining.

Nothing here writes, subscribes or asks the network: it reads banked
captures, and an index the capture never saw returns no bars rather than an
invented level (SO-3).
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import date, datetime
from pathlib import Path

from src.data.sessions import KARACHI

#: The names the wire uses and the chart serves, wire -> series name.
EXS_INDEX_NAMES: dict[str, str] = {
    "KSE100": "KSE100",     # the exchange's own large-cap index
    "ALLSHR": "KMIALLSHR",  # the exchange's all-shares index
}

#: Field positions inside one EXS-FEED group, measured (see module doc).
_FIELD_VALUE = 1
_FIELD_CHANGE = 2
_FIELD_HIGH = 3
_FIELD_LOW = 5
_FIELD_VOLUME = 10
_FIELD_VALUE_TRADED = 11

_STAMP_FORMAT = "%m/%d/%Y %I:%M:%S %p"


def _f(text) -> float | None:
    """One wire number, tolerant of trailing separators and blank fields."""
    cleaned = str(text or "").strip().replace(",", "")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def _stamp_to_karachi(stamp_text: str, day: date) -> datetime | None:
    """The group's own stamp, in this system's one fixed clock (SO-8)."""
    try:
        naive = datetime.strptime(stamp_text.strip(), _STAMP_FORMAT)
    except ValueError:
        return None
    local = datetime.combine(day, naive.time(), tzinfo=KARACHI)
    return local


def iter_index_quotes(path: Path, day: date) -> Iterator[dict]:
    """Yield one record per index group per EXS-FEED frame, arrival ordered.

    A record carries: ``name`` (the served name, e.g. KMIALLSHR),
    ``moment`` (arrival, Karachi), ``value``, ``high``, ``low``, ``change``,
    ``previous`` (value - change), ``volume`` and ``value_traded``. A field
    the wire left blank stays None; a stamp the wire malformed drops the
    record and the caller sees a shorter series, never a shifted one.
    """
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or "EXS-FEED" not in line[:64]:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            raw = str(record.get("raw", "") or "")
            if not raw.startswith("EXS-FEED*"):
                continue
            arrived = str(record.get("ts", "") or "")
            arrival: datetime | None = None
            if arrived:
                try:
                    parsed = datetime.fromisoformat(arrived)
                except ValueError:
                    parsed = None
                if parsed is not None:
                    arrival = (parsed.astimezone(KARACHI) if parsed.tzinfo
                               else parsed.replace(tzinfo=KARACHI))
            for group in raw.split("*", 1)[1].split("$"):
                parts = group.split("^", 1)
                if len(parts) < 2:
                    continue
                fields = parts[1].split(";")
                wire_name = fields[0].strip().upper() if fields else ""
                name = EXS_INDEX_NAMES.get(wire_name)
                if name is None:
                    continue
                value = _f(fields[_FIELD_VALUE] if len(fields) > _FIELD_VALUE else None)
                if value is None:
                    continue
                # The group's own stamp is the index's clock; the record's
                # arrival `ts` is the bank time and is identical for every
                # group banked in one frame, so using it alone would merge
                # distinct index minutes into whichever minute arrived.
                moment = _stamp_to_karachi(parts[0], day)
                if moment is None:
                    moment = arrival
                if moment is None:
                    continue
                change = _f(fields[_FIELD_CHANGE]
                            if len(fields) > _FIELD_CHANGE else None)
                previous = value - change if change is not None else None
                yield {
                    "name": name,
                    "moment": moment,
                    "value": value,
                    "high": _f(fields[_FIELD_HIGH]
                               if len(fields) > _FIELD_HIGH else None),
                    "low": _f(fields[_FIELD_LOW]
                               if len(fields) > _FIELD_LOW else None),
                    "change": change,
                    "previous": previous,
                    "volume": _f(fields[_FIELD_VOLUME]
                                 if len(fields) > _FIELD_VOLUME else None),
                    "value_traded": _f(
                        fields[_FIELD_VALUE_TRADED]
                        if len(fields) > _FIELD_VALUE_TRADED else None),
                }


def minute_bars(path: Path, day: date, name: str) -> list[dict]:
    """The index's minute bars from one capture, ascending and unique.

    Open is the first value seen in the minute, close the last, high/low span
    the values the recorder banked in that minute (running session extremes
    are reported by the caller's notes, not folded into minutes). A minute
    the capture did not watch is simply absent , no carry, no invention.
    """
    wanted = name.strip().upper()
    buckets: dict[datetime, dict] = {}
    for quote in iter_index_quotes(path, day):
        if quote["name"] != wanted:
            continue
        start = quote["moment"].replace(second=0, microsecond=0)
        value = quote["value"]
        bucket = buckets.get(start)
        if bucket is None:
            buckets[start] = {
                "o": value, "h": value, "l": value, "c": value,
                "v": 0.0,
                "high": quote["high"] or value,
                "low": quote["low"] or value,
            }
        else:
            bucket["h"] = max(bucket["h"], value)
            bucket["l"] = min(bucket["l"], value)
            bucket["c"] = value
        if quote["volume"] is not None:
            buckets[start]["v"] = quote["volume"]  # session running total
        if quote["high"] is not None:
            buckets[start]["high"] = max(buckets[start]["high"],
                                         quote["high"])
        if quote["low"] is not None:
            buckets[start]["low"] = min(buckets[start]["low"],
                                        quote["low"])
    return [buckets[start] | {"t": start}
            for start in sorted(buckets)]
