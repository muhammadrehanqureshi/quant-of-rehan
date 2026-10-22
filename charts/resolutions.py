"""The timeframe ladder: one place that knows every chart resolution.

The tape records ticks, the bar builder turns them into one-minute bars, and
the durable archive stores minutes. Everything coarser than a minute is a
*fold* of those minutes by the exchange's own OHLC rules, and everything finer
than a minute is built directly from the capture's tick rows. Keeping that
knowledge in one module is what stops the HTTP surface, the adapters and the
UI from each inventing a slightly different five-minute candle.

Two rules are enforced here rather than left to callers:

* **Session alignment.** Intraday buckets start at the open of the band they
  belong to, not at midnight. A Friday has two bands, so a 30-minute bar in
  the second band is anchored at 14:32, not at a clock edge inherited from
  the morning. The midday break is never folded into a candle.
* **No invention.** A fold only ever consumes real bars. A bucket with no
  constituent bar simply does not exist; the payload builder turns that
  absence into a measured gap or a note, never into a zero candle.

Calendar resolutions (``1D``, ``1W``, ``1M``) group by the Karachi date, the
ISO week and the calendar month. Their timestamps are the first real bar in
each group, because that is the only stamp the data itself supports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import sessions as law  # noqa: E402

from charts.contract import Bar  # noqa: E402

#: Canonical ids, finest first. This is the order the UI offers.
RESOLUTION_IDS: tuple[str, ...] = (
    "1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h", "4h",
    "1D", "1W", "1M",
)

#: Old names a deployment may still ask for. They resolve to a canonical id.
ALIASES: dict[str, str] = {
    "1d": "1D",
    "1w": "1W",
    "1mo": "1M",
    "1month": "1M",
    "1hour": "1h",
    "1hr": "1h",
    "60m": "1h",
    "240m": "4h",
    "session": "1D",
    "day": "1D",
    "daily": "1D",
    "week": "1W",
    "weekly": "1W",
    "month": "1M",
    "monthly": "1M",
    "second": "1s",
    "10s": "10s",
    "1min": "1m",
    "minute": "1m",
}

#: Minutes per intraday resolution. Calendar resolutions are absent on purpose.
_INTRADAY_MINUTES: dict[str, int] = {
    "1s": 0,
    "10s": 0,
    "1m": 1,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}

_INTRADAY_SECONDS: dict[str, int] = {
    "1s": 1,
    "10s": 10,
    "1m": 60,
    "5m": 300,
    "10m": 600,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
}


@dataclass(frozen=True)
class ResolutionSpec:
    """One rung of the ladder, with everything a reader needs to label it."""

    id: str
    label: str
    kind: str            # second | minute | hour | day | week | month
    seconds: int | None  # bucket width for intraday rungs, None for calendar
    minutes: int | None
    source: str          # tick | minute | calendar

    @property
    def intraday(self) -> bool:
        return self.seconds is not None

    @property
    def calendar(self) -> bool:
        return self.seconds is None

    @property
    def subminute(self) -> bool:
        return self.id in ("1s", "10s")

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "kind": self.kind,
                "seconds": self.seconds, "minutes": self.minutes,
                "source": self.source}


SPECS: dict[str, ResolutionSpec] = {
    "1s": ResolutionSpec("1s", "1 second", "second", 1, None, "tick"),
    "10s": ResolutionSpec("10s", "10 seconds", "second", 10, None, "tick"),
    "1m": ResolutionSpec("1m", "1 minute", "minute", 60, 1, "minute"),
    "5m": ResolutionSpec("5m", "5 minutes", "minute", 300, 5, "minute"),
    "10m": ResolutionSpec("10m", "10 minutes", "minute", 600, 10, "minute"),
    "15m": ResolutionSpec("15m", "15 minutes", "minute", 900, 15, "minute"),
    "30m": ResolutionSpec("30m", "30 minutes", "minute", 1800, 30, "minute"),
    "1h": ResolutionSpec("1h", "1 hour", "hour", 3600, 60, "minute"),
    "4h": ResolutionSpec("4h", "4 hours", "hour", 14400, 240, "minute"),
    "1D": ResolutionSpec("1D", "1 day", "day", None, None, "calendar"),
    "1W": ResolutionSpec("1W", "1 week", "week", None, None, "calendar"),
    "1M": ResolutionSpec("1M", "1 month", "month", None, None, "calendar"),
}

#: What each rung is built from, said in one sentence for a payload note.
BUILD_NOTES: dict[str, str] = {
    "1s": "1-second bars are built from the capture's own tick rows, so they "
          "exist while that session's recording file is on disk",
    "10s": "10-second bars are built from the capture's own tick rows, so they "
           "exist while that session's recording file is on disk",
    "1m": "1-minute bars are the broker tape's own grain: open, high, low and "
          "close are the prints in that minute",
    "5m": "5-minute bars are folded from the session's 1-minute tape bars, band "
          "aligned and never across the Friday break",
    "10m": "10-minute bars are folded from the session's 1-minute tape bars",
    "15m": "15-minute bars are folded from the session's 1-minute tape bars",
    "30m": "30-minute bars are folded from the session's 1-minute tape bars",
    "1h": "1-hour bars are folded from the session's 1-minute tape bars",
    "4h": "4-hour bars are folded from the session's 1-minute tape bars; a "
          "short PSX session may hold only one or two of them",
    "1D": "daily bars are one trading session each, folded from that session's "
          "minute bars",
    "1W": "weekly bars group trading sessions by ISO week, folded from their "
          "minute bars",
    "1M": "monthly bars group trading sessions by calendar month, folded from "
          "their minute bars",
}


def normalise(resolution: str) -> str:
    """The canonical id for a requested resolution, or a ValueError."""
    text = str(resolution or "").strip()
    if not text:
        raise ValueError("a resolution is required")
    if text in SPECS:
        return text
    alias = ALIASES.get(text)
    if alias is not None and alias in SPECS:
        return alias
    # Case-insensitive aliases ("1d", "1D", "1w"...), while keeping "1m"
    # distinct from a hypothetical "1M".
    lowered = text.lower()
    for candidate in RESOLUTION_IDS:
        if candidate.lower() == lowered and candidate not in ("1m", "1M"):
            return candidate
    raise ValueError(
        f"unknown resolution {text!r}; this service serves "
        f"{', '.join(RESOLUTION_IDS)}")


def spec_for(resolution: str) -> ResolutionSpec:
    return SPECS[normalise(resolution)]


def is_intraday(resolution: str) -> bool:
    return spec_for(resolution).intraday


def is_second(resolution: str) -> bool:
    return spec_for(resolution).subminute


def seconds_of(resolution: str) -> int | None:
    return spec_for(resolution).seconds


def minutes_of(resolution: str) -> int | None:
    return spec_for(resolution).minutes


def steps_per_minute(resolution: str) -> int | None:
    """How many buckets of this rung fit in a minute (1s -> 60)."""
    seconds = seconds_of(resolution)
    if seconds is None or seconds >= 60:
        return None
    return 60 // seconds if 60 % seconds == 0 else None


# --------------------------------------------------------------- calendar keys


def _local(moment: datetime) -> datetime:
    return law.as_karachi(moment)


def _bar_time(bar: Bar) -> datetime:
    return datetime.fromisoformat(bar.t)


def band_for(moment: datetime) -> tuple[datetime, datetime] | None:
    """The session band containing `moment`, or None outside trading time.

    The law's own bands are half-open, ``[open, close)``, so a bar stamped at
    the close belongs to no band and is not folded into the session.
    """
    local = _local(moment)
    for band in law.session_bands(local.date()):
        opened, closed = law.band_bounds(local.date(), band)
        if opened <= local < closed:
            return opened, closed
    return None


def in_session(moment: datetime) -> bool:
    return band_for(moment) is not None


def bucket_start(moment: datetime, resolution: str) -> datetime | None:
    """The start of this moment's bucket, session-band aligned.

    Returns None when the moment is outside every band. This is the only
    bucketing rule in the service: a candle can never straddle a band edge.
    """
    spec = spec_for(resolution)
    local = _local(moment)
    if spec.intraday:
        band = band_for(local)
        if band is None:
            return None
        opened = band[0]
        width = timedelta(seconds=spec.seconds or 0)
        offset = local - opened
        steps = int(offset.total_seconds() // width.total_seconds())
        return opened + width * steps
    # Calendar rungs are labelled by the first bar in the group. Their key is
    # computed separately; the bar's own stamp is the honest label.
    return local


def calendar_key(moment: datetime, resolution: str) -> tuple:
    local = _local(moment)
    spec = spec_for(resolution)
    if spec.id == "1D":
        return (local.date().isoformat(),)
    if spec.id == "1W":
        iso = local.isocalendar()
        return (iso.year, iso.week)
    if spec.id == "1M":
        return (local.year, local.month)
    raise ValueError(f"{resolution} is not a calendar resolution")


def _merge(group: list[Bar], *, start: datetime | None = None) -> Bar:
    """Fold bars into one OHLCV row, using the exchange's own rules."""
    first = group[0]
    last = group[-1]
    opened = start or _bar_time(first)
    return Bar.build(
        t=opened,
        o=first.o,
        h=max(bar.h for bar in group),
        l=min(bar.l for bar in group),
        c=last.c,
        v=sum(bar.v for bar in group),
    )


def aggregate(bars: Iterable[Bar], resolution: str) -> list[Bar]:
    """Fold a sorted minute (or tick) series into `resolution`.

    The input is expected to be ascending and unique by timestamp. A bar
    outside the session bands is dropped rather than folded, because it is not
    exchange time. A calendar fold groups every session in the series.
    """
    spec = spec_for(resolution)
    rows = [bar for bar in bars if in_session(_bar_time(bar))]
    if not rows:
        return []
    if spec.intraday and spec.id == "1m":
        return rows
    if spec.intraday:
        folded: list[Bar] = []
        current_key: object = object()
        group: list[Bar] = []
        start: datetime | None = None
        for bar in rows:
            moment = _bar_time(bar)
            key = bucket_start(moment, spec.id)
            if key is None:
                continue
            if not group or key != current_key:
                if group:
                    folded.append(_merge(group, start=start))
                current_key = key
                start = key
                group = [bar]
            else:
                group.append(bar)
        if group:
            folded.append(_merge(group, start=start))
        return folded
    # Calendar rungs.
    groups: list[list[Bar]] = []
    keys: list[tuple] = []
    for bar in rows:
        key = calendar_key(_bar_time(bar), spec.id)
        if keys and keys[-1] == key:
            groups[-1].append(bar)
        else:
            keys.append(key)
            groups.append([bar])
    return [_merge(group) for group in groups]


def expected_bucket_starts(day: date, resolution: str) -> list[datetime]:
    """Every bucket the session law expects for one day, at this resolution.

    Used for gap measurement on intraday rungs. A bucket is expected when any
    part of it falls inside a band. A day the law calls closed has none.
    """
    spec = spec_for(resolution)
    if spec.calendar:
        return []
    starts: list[datetime] = []
    for band in law.session_bands(day):
        opened, closed = law.band_bounds(day, band)
        cursor = opened
        while cursor < closed:
            starts.append(cursor)
            cursor += timedelta(seconds=spec.seconds or 60)
    return starts


def expected_minutes_for(day: date) -> list[datetime]:
    """The law's own minute grid for a day, re-exported for callers."""
    return [moment for band in law.session_bands(day)
            for moment in _minutes(day, band)]


def _minutes(day: date, band) -> list[datetime]:
    opened, closed = law.band_bounds(day, band)
    cursor = opened
    rows: list[datetime] = []
    while cursor < closed:
        rows.append(cursor)
        cursor += timedelta(minutes=1)
    return rows


def label(resolution: str) -> str:
    try:
        return spec_for(resolution).label
    except ValueError:
        return str(resolution)


def all_specs() -> Sequence[dict]:
    return [SPECS[item].as_dict() for item in RESOLUTION_IDS]
