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
#: v2 added the ``session`` block: which trading day a series belongs to,
#: whether that day is the one the clock calls today, whether the bars came
#: from the durable archive, and which file answered. A chart that can show a
#: finished session has to say which session it is showing.
#: v3 (2026-10-20) added the full timeframe ladder (``1s`` through ``1M``) and
#: the computed index proxies ``KSE100`` and ``KMIALLSHR``. The session block
#: and the bar shape are unchanged; an old consumer keeps reading a v2 series.
SCHEMA_VERSION = 3

#: The resolutions this service may serve, finest first. ``1m`` is the broker
#: tape's own grain; sub-minute rungs are built from tick rows; coarser
#: intraday rungs are folds of the tape's minutes; ``1D``/``1W``/``1M`` group
#: trading sessions. ``1d`` and ``session`` remain accepted aliases.
RESOLUTION_MINUTE = "1m"
RESOLUTION_DAY = "1D"
RESOLUTION_SESSION = "session"
RESOLUTIONS = (
    "1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h", "4h",
    "1D", "1W", "1M",
    # Accepted spellings a pre-v3 caller may still send.
    "1d", "session",
)

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


@dataclass(frozen=True)
class ChartSession:
    """Which session a series belongs to, and where those bars came from.

    A charting service that can draw a finished session has to label it: a
    reader looking at Friday's candles on a Sunday must not be able to mistake
    them for a live market, and a research pass must be able to prove which
    file the bars were read from.
    """

    day: str
    current: bool = True
    archived: bool = False
    source: str = ""
    capture: dict | None = None
    built_at: str = ""
    note: str = ""
    #: Whether this session's source reported a volume counter at all. A pane
    #: of flat zero columns is a lie about a source with no volume, so the
    #: chart asks rather than assumes.
    volume_available: bool = False

    def as_dict(self) -> dict:
        return {"day": self.day, "current": self.current,
                "archived": self.archived, "source": self.source,
                "capture": self.capture, "built_at": self.built_at,
                "note": self.note,
                "volume_available": self.volume_available}


def parse_session(raw: Any) -> "ChartSession":
    """Read a session block, tolerating a payload that predates v2."""
    if not isinstance(raw, Mapping):
        return ChartSession(day="")
    capture = raw.get("capture")
    return ChartSession(
        day=str(raw.get("day", "")),
        current=bool(raw.get("current", True)),
        archived=bool(raw.get("archived", False)),
        source=str(raw.get("source", "")),
        capture=dict(capture) if isinstance(capture, Mapping) else None,
        built_at=str(raw.get("built_at", "")),
        note=str(raw.get("note", "")),
        volume_available=bool(raw.get("volume_available", False)),
    )


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
    observed_at: str = ""
    session: ChartSession = field(default_factory=lambda: ChartSession(day=""))
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
            "session": self.session.as_dict(),
            "bars": [bar.as_dict() for bar in self.bars],
            "bar_count": len(self.bars),
            "gaps": [gap.as_dict() for gap in self.gaps],
            "notes": list(self.notes),
            "observed_at": self.observed_at or self.as_of,
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
                session=parse_session(raw.get("session")),
                notes=[str(note) for note in raw.get("notes", [])],
                observed_at=str(raw.get("observed_at", raw.get("as_of", ""))),
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
