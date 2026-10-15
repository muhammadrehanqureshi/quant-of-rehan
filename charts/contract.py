"""The chart API's canonical contract, defined once.

Every payload the service hands a consumer is built here, and every payload a
consumer reads is validated here, so the browser, the tests and any future
adapter can never disagree about a field name or a unit. The contract is
deliberately dependency free (standard library only) because it is the one
module both the server and the test suite import without side effects.

Two rules carry over from the project's standing orders:

* SO-3, the no-invented-data law: an empty series is ``bars: []`` with a
  measured ``notes`` sentence, never a row of zeros dressed up as data. A
  price is either a real print or absent.
* SO-8, one clock: every timestamp is an ISO 8601 string carrying the
  Karachi offset (+05:00). The service never emits a naive timestamp, and a
  consumer never has to guess a timezone.

Schema changes bump ``SCHEMA_VERSION`` and are additive or breaking by
contract test (see ``tests/test_charts_contract.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

#: Bumped when the shape of a payload changes in a way a consumer must know.
SCHEMA_VERSION = 1

#: The resolutions this service may serve. ``1m`` is the broker tape's own
#: grain; ``1d`` is the PSX portal's published daily bar; ``session`` is the
#: single snapshot bar a session quote yields when nothing finer exists.
RESOLUTION_MINUTE = "1m"
RESOLUTION_DAY = "1d"
RESOLUTION_SESSION = "session"
RESOLUTIONS = (RESOLUTION_MINUTE, RESOLUTION_DAY, RESOLUTION_SESSION)

#: Source identifiers, so a consumer can name where a series came from.
SOURCE_TAPE = "broker_tape"
SOURCE_PORTAL = "psx_portal"
SOURCE_REPLAY = "replay"


class ContractError(ValueError):
    """A payload that does not satisfy the contract, with the reason."""


def _iso(moment: datetime | str) -> str:
    """An ISO 8601 stamp with an offset, or a ContractError.

    A naive datetime is refused rather than assumed to be Karachi: guessing
    a timezone is how a chart silently shows the wrong session.
    """
    if isinstance(moment, str):
        text = moment.strip()
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ContractError(f"timestamp is not ISO 8601: {text!r}") from exc
    else:
        parsed = moment
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(
            f"timestamp carries no offset, so its zone is unknown: {parsed!r}")
    return parsed.isoformat(timespec="seconds")


def _number(value: Any, *, field_name: str, positive: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"{field_name} is not a number: {value!r}") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ContractError(f"{field_name} is not finite: {value!r}")
    if positive and number <= 0:
        raise ContractError(f"{field_name} must be positive: {value!r}")
    return number


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar. Volume may be zero; a price may never be."""

    t: str
    o: float
    h: float
    l: float  # noqa: E741 - the contract's own short names are the point
    c: float
    v: float = 0.0

    def __post_init__(self) -> None:
        if self.h < max(self.o, self.c, self.l):
            raise ContractError(f"high {self.h!r} is below another price")
        if self.l > min(self.o, self.c, self.h):
            raise ContractError(f"low {self.l!r} is above another price")
        if self.v < 0:
            raise ContractError(f"volume is negative: {self.v!r}")

    @classmethod
    def build(cls, *, t: datetime | str, o: Any, h: Any, l: Any,  # noqa: E741
              c: Any, v: Any = 0.0) -> "Bar":
        return cls(
            t=_iso(t),
            o=_number(o, field_name="open", positive=True),
            h=_number(h, field_name="high", positive=True),
            l=_number(l, field_name="low", positive=True),  # noqa: E741
            c=_number(c, field_name="close", positive=True),
            v=max(0.0, _number(v or 0, field_name="volume", positive=False)),
        )

    def as_dict(self) -> dict:
        return {"t": self.t, "o": self.o, "h": self.h, "l": self.l,
                "c": self.c, "v": self.v}


@dataclass(frozen=True)
class Gap:
    """A stretch of expected trading time with no bar, named as a gap."""

    start: str
    end: str
    minutes: int
    reason: str

    def as_dict(self) -> dict:
        return {"start": self.start, "end": self.end,
                "minutes": self.minutes, "reason": self.reason}


@dataclass(frozen=True)
class SourceInfo:
    """Where a series came from, and what it costs to trust it."""

    id: str
    label: str
    #: Publication delay of the upstream in seconds (0 for the local tape).
    delay_seconds: int = 0
    #: What the source itself claims to be, in its own words.
    note: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "label": self.label,
                "delay_seconds": self.delay_seconds, "note": self.note}


@dataclass(frozen=True)
class MarketContext:
    """The session facts a chart needs, all of them server resolved.

    The browser never derives a session from its own clock, so a phone, a
    laptop and a cloud runner can never disagree about whether the exchange
    is trading (the same law the phone app follows).
    """

    phase: str
    state: str
    trading_day: bool
    timezone: str
    band: dict | None = None
    next_event: dict | None = None
    as_of: str = ""

    def as_dict(self) -> dict:
        return {"phase": self.phase, "state": self.state,
                "trading_day": self.trading_day, "timezone": self.timezone,
                "band": self.band, "next_event": self.next_event,
                "as_of": self.as_of}


@dataclass
class ChartPayload:
    """One symbol's series plus everything needed to read it honestly."""

    symbol: str
    resolution: str
    source: SourceInfo
    market: MarketContext
    as_of: str
    bars: list[Bar] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.resolution not in RESOLUTIONS:
            raise ContractError(f"unknown resolution: {self.resolution!r}")
        stamps = [bar.t for bar in self.bars]
        if stamps != sorted(stamps):
            raise ContractError("bars are not in ascending time order")
        if len(set(stamps)) != len(stamps):
            raise ContractError("two bars share one timestamp")

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "symbol": self.symbol,
            "resolution": self.resolution,
            "source": self.source.as_dict(),
            "market": self.market.as_dict(),
            "bars": [bar.as_dict() for bar in self.bars],
            "bar_count": len(self.bars),
            "gaps": [gap.as_dict() for gap in self.gaps],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ChartPayload":
        """Parse and validate a payload, raising ContractError on any doubt."""
        try:
            bars = [
                Bar(t=str(row["t"]),
                    o=float(row["o"]), h=float(row["h"]),
                    l=float(row["l"]), c=float(row["c"]),  # noqa: E741
                    v=float(row.get("v", 0.0)))
                for row in raw.get("bars", [])
            ]
            gaps = [
                Gap(start=str(row["start"]), end=str(row["end"]),
                    minutes=int(row["minutes"]),
                    reason=str(row.get("reason", "")))
                for row in raw.get("gaps", [])
            ]
            source = raw.get("source") or {}
            market = raw.get("market") or {}
            return cls(
                symbol=str(raw["symbol"]),
                resolution=str(raw.get("resolution", RESOLUTION_MINUTE)),
                source=SourceInfo(id=str(source.get("id", "")),
                                  label=str(source.get("label", "")),
                                  delay_seconds=int(source.get(
                                      "delay_seconds", 0)),
                                  note=str(source.get("note", ""))),
                market=MarketContext(
                    phase=str(market.get("phase", "UNKNOWN")),
                    state=str(market.get("state", "UNKNOWN")),
                    trading_day=bool(market.get("trading_day", False)),
                    timezone=str(market.get("timezone", "")),
                    band=market.get("band"),
                    next_event=market.get("next_event"),
                    as_of=str(market.get("as_of", ""))),
                as_of=str(raw.get("as_of", "")),
                bars=bars,
                gaps=gaps,
                notes=[str(note) for note in raw.get("notes", [])],
                schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
            )
        except KeyError as exc:
            raise ContractError(f"payload is missing field {exc}") from exc
        except (TypeError, ValueError) as exc:
            raise ContractError(f"payload is malformed: {exc}") from exc


def bars_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[Bar]:
    """Build bars from a bar-like iterable, dropping nothing silently.

    Raises on the first row that cannot be a bar: a chart that quietly skips
    a malformed row is a chart that lies about the day.
    """
    built = [Bar.build(t=row["ts"], o=row["open"], h=row["high"],
                       l=row["low"], c=row["close"], v=row.get("volume", 0.0))
             for row in rows]
    built.sort(key=lambda bar: bar.t)
    previous = None
    for bar in built:
        if bar.t == previous:
            raise ContractError(f"two bars share one timestamp: {bar.t}")
        previous = bar.t
    return built
