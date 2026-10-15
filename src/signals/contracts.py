"""The typed contract boundary around the ONE scanner.

Rebuild 2026-10-10. This module adds no strategy. It is the typed, validated
boundary a production caller uses to hold the scanner's inputs and outputs, so
that a bad bar or a contradictory verdict fails loudly at the edge instead of
travelling quietly as a dict.

Why a boundary rather than a second engine: this repository has exactly one
scanner (src/signals/momentum_scanner.py) and exactly one orchestrator
(scripts/intraday_pipeline.py). Anything here that scores a symbol would be the
second competing engine the rebuild removed. So these models are ADAPTERS:
`ScanOutcome.of(result)` copies a real `momentum_scanner.ScanResult` into a
validated object, and `validate_bars` rejects malformed input before the
scanner ever sees it.

Strict typing, with pydantic optional:

  * every model is a typed dataclass with explicit invariants in
    `__post_init__`, so validation is the same code path with or without a
    third-party library;
  * when `pydantic` is importable the same dataclasses are re-decorated with
    `pydantic.dataclasses.dataclass`, which adds coercion and per-field type
    checks. `PYDANTIC_AVAILABLE` reports which mode is live;
  * when pydantic is absent (it is not in requirements.txt), nothing breaks:
    the invariants still run and the API is identical.

Fault taxonomy. String matching on a human-readable reason is how a reason
turns into a retry policy by accident. Every blocked scan maps to a typed
`ScanFault` subclass, and callers branch on the class.

    Data quality     ->  Fault
    no coverage      ->  InsufficientCoverage
    stale feed       ->  StaleFeed
    no volume        ->  VolumeUnavailable
    source error     ->  SourceUnavailable
    outside session  ->  MarketClosed
    killed mid-scan  ->  ScanAborted
    warming up       ->  no fault at all

    A warming-up capture is deliberately NOT in that list: a bar source younger
    than the bars the strategy needs is a countdown, not a failure, and mapping
    it to a fault would put it into a retry-with-backoff policy and a fault
    count. Measured 2026-10-14, that mistake turned 86 warm-up cycles of one
    band into coverage faults and made a healthy tape read as a dead feed.

Usage:

    from src.signals.contracts import ScanOutcome, validate_bars

    # slot is a label chosen by the caller, not a session time built here
    outcome = ScanOutcome.of(result, slot="10:05", as_of=now, universe_size=319)
    if outcome.is_actionable:
        print(outcome.candidate.symbol, outcome.candidate.score)
    fault = outcome.fault()          # None when the scan was clean
"""

from __future__ import annotations

import math
from dataclasses import field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Iterable, Mapping

try:  # optional strict-validation layer
    from pydantic import ValidationError  # noqa: F401  (re-exported for callers)
    from pydantic.dataclasses import dataclass as _pydantic_dataclass

    PYDANTIC_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by the fallback test
    ValidationError = ValueError  # type: ignore[assignment,misc]
    _pydantic_dataclass = None  # type: ignore[assignment]
    PYDANTIC_AVAILABLE = False

from dataclasses import dataclass as _stdlib_dataclass

# SO-8: the session clock is Asia/Karachi (UTC+5) and the pin lives in exactly
# one place, src/data/sessions.py. It is imported here, never re-derived, so a
# captured "09:35" bar cannot be shifted into another hour by a caller whose
# own instant happens to carry a different offset (for example UTC).
from src.data.sessions import KARACHI

MODEL_MODE = "pydantic" if PYDANTIC_AVAILABLE else "dataclass"

# Slack for float comparisons on prices that arrive rounded on the wire.
PRICE_EPSILON = 1e-9

# A bar older than this, relative to the scan instant, is stale for scoring.
DEFAULT_STALENESS_MINUTES = 5.0


def model(cls):
    """Decorate a dataclass, adding pydantic validation when it is available."""
    if _pydantic_dataclass is not None:
        return _pydantic_dataclass(cls)
    return _stdlib_dataclass(cls)


# ------------------------------------------------------------------- enums

class Quality(str, Enum):
    """Whether a scan was allowed to judge the market at all."""

    OK = "OK"
    DATA_BLOCKED = "DATA_BLOCKED"


class Verdict(str, Enum):
    """The scanner's three legal outcomes, plus the administrative ones.

    TRADE and NO_TRADE are market decisions. DATA_BLOCKED is a data failure,
    OUTSIDE_SESSION means the clock, FINALIZED means the day was already
    closed out, and ABORTED means the scan did not finish. Only the first two
    may be reported as a judgement about the market.
    """

    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"
    DATA_BLOCKED = "DATA_BLOCKED"
    OUTSIDE_SESSION = "OUTSIDE_SESSION"
    MONITORING = "MONITORING"
    FINALIZED = "FINALIZED"
    ABORTED = "ABORTED"


#: Trade-state statuses the orchestrator may report once a day is locked.
#: These are not scanner verdicts, and reading them as one would be wrong:
#: the day already HAS its trade, so it is neither NO_TRADE nor a failure.
MONITORING_STATUSES = frozenset({
    "TARGET_MONITORING", "TRADE_ENTERED", "DAILY_LOCKED", "CANDIDATE_FOUND",
    "TRADE_CLOSED", "TARGET_HIT", "SCANNING", "MARKET_OPEN",
})


class Rejection(str, Enum):
    """Why one captured bar row was refused. Counted, never repaired."""

    MALFORMED = "MALFORMED"
    IMPOSSIBLE_OHLC = "IMPOSSIBLE_OHLC"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    NOT_FINITE = "NOT_FINITE"
    FUTURE_BAR = "FUTURE_BAR"
    WRONG_SESSION = "WRONG_SESSION"
    NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"
    NEGATIVE_VOLUME = "NEGATIVE_VOLUME"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"


# ------------------------------------------------------------------- faults

class ScanFault(Exception):
    """Base class for every typed scan failure."""

    #: does retrying the same slot without new data stand a chance?
    retryable = False

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.context = context

    def as_dict(self) -> dict:
        return {"fault": type(self).__name__, "retryable": self.retryable,
                "detail": self.detail, **self.context}


class InsufficientCoverage(ScanFault):
    """Too few universe symbols had usable bars to judge the market."""

    retryable = True


class StaleFeed(ScanFault):
    """Bars exist but the newest one is older than the freshness limit."""

    retryable = True


class VolumeUnavailable(ScanFault):
    """The source cannot supply volume, and the strategy requires it."""

    retryable = False


class SourceUnavailable(ScanFault):
    """The capture source errored, timed out or returned nothing usable."""

    retryable = True


class MarketClosed(ScanFault):
    """A scan was requested outside the configured trading session."""

    retryable = False


class ScanAborted(ScanFault):
    """The scan did not finish. A partial verdict is never reported as one."""

    retryable = True


def as_quality(value: Any) -> Quality:
    """Coerce a status to the enum.

    `str()` on a str-mixin enum member returns 'Quality.OK' on Python 3.11 and
    later, not 'OK', so a naive str-then-upper destroys the value. This handles
    the member, the bare name and the display form.
    """
    if isinstance(value, Quality):
        return value
    text = str(value).strip().upper()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return Quality(text)


def fault_from_quality(quality: "DataQuality") -> ScanFault | None:
    """Map a blocked quality report onto its typed fault, or None when clean.

    A warming-up capture is neither: nothing is broken, the bar source has not
    been alive long enough to hold the bars the strategy needs. Counting it as
    a fault is what made a healthy tape look like a dead feed on 2026-10-14
    (run 38530614304: 86 coverage faults in one band, every cycle warming up).
    """
    if quality.status is Quality.OK:
        return None
    if quality.warming_up:
        return None
    reason = (quality.reason or "").lower()
    context = {
        "coverage": quality.coverage,
        "fresh_coverage": quality.fresh_coverage,
        "symbols_with_bars": quality.symbols_with_bars,
        "symbols_expected": quality.symbols_expected,
        "data_age_minutes": quality.data_age_minutes,
    }
    if "not a psx trading day" in reason:
        return MarketClosed(quality.reason, **context)
    if "coverage 0/" in reason or "no usable current-session bars" in reason:
        return SourceUnavailable(quality.reason, **context)
    if "below the" in reason and "floor" in reason:
        return InsufficientCoverage(quality.reason, **context)
    if "stale" in reason or "minutes old" in reason:
        return StaleFeed(quality.reason, **context)
    if "no volume" in reason or "volume expansion" in reason:
        return VolumeUnavailable(quality.reason, **context)
    if "malformed" in reason or "contradictory" in reason:
        return SourceUnavailable(quality.reason, **context)
    if "universe is empty" in reason:
        return InsufficientCoverage(quality.reason, **context)
    return ScanAborted(quality.reason, **context)


# -------------------------------------------------------------------- models

@model
class Bar:
    """One validated minute bar. Construction is the validation."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None

    def __post_init__(self) -> None:
        if not self.symbol or not str(self.symbol).strip():
            raise ValueError("bar has no symbol")
        if self.timestamp.tzinfo is None:
            raise ValueError("bar timestamp must carry a timezone")
        for name in ("open", "high", "low", "close"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name}={value!r} is not a positive finite price")
        if self.high + PRICE_EPSILON < max(self.open, self.close):
            raise ValueError(
                f"impossible OHLC on {self.symbol}: high {self.high} below "
                f"max(open, close)")
        if self.low - PRICE_EPSILON > min(self.open, self.close):
            raise ValueError(
                f"impossible OHLC on {self.symbol}: low {self.low} above "
                f"min(open, close)")
        if self.high + PRICE_EPSILON < self.low:
            raise ValueError(f"impossible OHLC on {self.symbol}: high below low")
        if self.volume is not None:
            volume = float(self.volume)
            if not math.isfinite(volume) or volume < 0:
                raise ValueError(f"volume={self.volume!r} is not finite and >= 0")

    @property
    def range_pct(self) -> float:
        return (self.high - self.low) / self.close if self.close else 0.0

    @property
    def is_flat(self) -> bool:
        """Open == high == low == close: a locked or placeholder print."""
        return (abs(self.high - self.low) <= PRICE_EPSILON
                and abs(self.open - self.close) <= PRICE_EPSILON)

    def is_stale(self, as_of: datetime, minutes: float = DEFAULT_STALENESS_MINUTES) -> bool:
        return (as_of - self.timestamp) > timedelta(minutes=minutes)


@model
class DataQuality:
    """The scanner's measured data verdict, typed."""

    status: Quality
    reason: str
    coverage: float
    fresh_coverage: float
    symbols_expected: int
    symbols_with_bars: int
    newest_bar: datetime | None = None
    oldest_bar: datetime | None = None
    data_age_minutes: float | None = None
    duplicate_bars: int = 0
    malformed_bars: int = 0
    impossible_ohlc: int = 0
    zero_volume_bars: int = 0
    volume_available: bool = False
    resolution: str = "1-minute"
    source: str = ""
    #: Symbols the ranking could actually use (enough bars AND a fresh bar),
    #: the leader slice and how fresh it was, and whether the bar source is
    #: simply younger than the bars it is asked to hold. A warming-up block is
    #: NOT a fault: it is a countdown, and the runner must not retry it into a
    #: dead feed (redesign 2026-10-15).
    rankable_symbols: int = 0
    leader_symbols: int = 0
    leaders_fresh: int = 0
    warming_up: bool = False
    warmup_minutes_remaining: float = 0.0

    def __post_init__(self) -> None:
        if self.symbols_expected < 0 or self.symbols_with_bars < 0:
            raise ValueError("symbol counts cannot be negative")
        if self.symbols_with_bars > self.symbols_expected and self.symbols_expected:
            raise ValueError("more symbols with bars than symbols expected")
        for name in ("coverage", "fresh_coverage"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0 + PRICE_EPSILON:
                raise ValueError(f"{name}={value!r} is not a fraction")

    @property
    def is_blocked(self) -> bool:
        return self.status is Quality.DATA_BLOCKED

    @property
    def is_usable(self) -> bool:
        return self.status is Quality.OK

    def as_dict(self) -> dict:
        return {
            "status": self.status.value, "reason": self.reason,
            "coverage": round(self.coverage, 4),
            "fresh_coverage": round(self.fresh_coverage, 4),
            "symbols_expected": self.symbols_expected,
            "symbols_with_bars": self.symbols_with_bars,
            "data_age_minutes": self.data_age_minutes,
            "volume_available": self.volume_available,
            "malformed_bars": self.malformed_bars,
            "duplicate_bars": self.duplicate_bars,
            "impossible_ohlc": self.impossible_ohlc,
            "resolution": self.resolution, "source": self.source,
            "rankable_symbols": self.rankable_symbols,
            "leader_symbols": self.leader_symbols,
            "leaders_fresh": self.leaders_fresh,
            "warming_up": self.warming_up,
            "warmup_minutes_remaining": self.warmup_minutes_remaining,
        }


@model
class Candidate:
    """One ranked, eligible candidate with the AI prior attached."""

    symbol: str
    score: float
    momentum: str = "UNKNOWN"
    acceleration_label: str = "UNKNOWN"
    volume_label: str = "UNKNOWN"
    entry_price: float | None = None
    ai_probability: float | None = None
    ai_percentile: float | None = None
    ai_active: bool = False
    components: Mapping[str, float] = field(default_factory=dict)
    returns: Mapping[str, float] = field(default_factory=dict)
    # The scanner's volume block deliberately mixes measures with provenance:
    # 'volume_source' is a label such as 'captured bar volume', the rest are
    # numbers. The union below is the honest type; a stricter one would reject
    # a document the scanner is right to produce.
    volume: Mapping[str, float | str | None] = field(default_factory=dict)
    last_bar: datetime | None = None
    bars: int = 0

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("candidate has no symbol")
        if not 0.0 <= float(self.score) <= 100.0:
            raise ValueError(f"score {self.score!r} outside 0..100")
        if self.ai_probability is not None:
            probability = float(self.ai_probability)
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"ai_probability {probability!r} outside 0..1")
        if self.ai_percentile is not None:
            percentile = float(self.ai_percentile)
            if not 0.0 <= percentile <= 1.0:
                raise ValueError(f"ai_percentile {percentile!r} outside 0..1")
        if self.entry_price is not None and float(self.entry_price) <= 0:
            raise ValueError("entry_price must be positive")


@model
class ScanOutcome:
    """The typed result of one scan pass. Every field is accounted for."""

    as_of: datetime
    slot: str
    verdict: Verdict
    reason: str
    quality: DataQuality | None = None
    candidate: Candidate | None = None
    ranked: tuple[Candidate, ...] = ()
    eligible_count: int = 0
    coverage_text: str = ""
    universe_size: int = 0
    universe_sha256: str | None = None
    scanner_version: str = ""
    ai_active: bool = False
    latency_ms: float | None = None
    delivered: str | None = None

    def __post_init__(self) -> None:
        if self.verdict is Verdict.TRADE and self.candidate is None:
            raise ValueError("a TRADE outcome must carry the candidate it took")
        if self.verdict is not Verdict.TRADE and self.candidate is not None:
            raise ValueError(
                f"a {self.verdict.value} outcome cannot carry an entered candidate")
        if self.eligible_count < 0:
            raise ValueError("eligible_count cannot be negative")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("latency_ms cannot be negative")

    @property
    def is_actionable(self) -> bool:
        return self.verdict is Verdict.TRADE and self.candidate is not None

    @property
    def is_market_decision(self) -> bool:
        """A NO TRADE is a market judgement. A DATA BLOCKED is not."""
        return self.verdict in (Verdict.TRADE, Verdict.NO_TRADE)

    def fault(self) -> ScanFault | None:
        """The typed fault behind a blocked outcome, or None.

        A warming-up capture falls through to None on purpose: the block is a
        countdown, and a fault would put it into a retry-with-backoff policy
        and a fault count, which is what it must not be.
        """
        if self.verdict is Verdict.DATA_BLOCKED:
            if self.quality is not None:
                if self.quality.warming_up:
                    return None
                mapped = fault_from_quality(self.quality)
                if mapped is not None:
                    return mapped
            return SourceUnavailable(self.reason)
        if self.verdict is Verdict.OUTSIDE_SESSION:
            return MarketClosed(self.reason)
        if self.verdict is Verdict.ABORTED:
            return ScanAborted(self.reason)
        return None

    @property
    def is_monitoring(self) -> bool:
        """The day already has its one trade; this cycle only watched it."""
        return self.verdict is Verdict.MONITORING

    def summary(self) -> str:
        head = f"{self.verdict.value} {self.slot} {self.as_of:%Y-%m-%d %H:%M} PKT"
        if self.candidate is not None:
            head += f" {self.candidate.symbol} score {self.candidate.score:.2f}"
        if self.quality is not None:
            head += (f" coverage {self.quality.symbols_with_bars}/"
                     f"{self.quality.symbols_expected}")
        return f"{head}: {self.reason}"

    @staticmethod
    def of(result: Any, *, slot: str, as_of: datetime,
           universe_size: int = 0, universe_sha256: str | None = None,
           scanner_version: str = "", ai_active: bool = False,
           latency_ms: float | None = None) -> "ScanOutcome":
        """Adapt a `momentum_scanner.ScanResult` into the typed contract."""
        raw_status = getattr(result, "status", "")
        verdict = verdict_from_status(raw_status)
        if verdict is None:
            raise ScanAborted(f"unknown scanner verdict {raw_status!r}")

        quality = None
        report = getattr(result, "quality", None)
        if report is not None:
            quality = DataQuality(
                status=as_quality(getattr(report, "status", "OK")),
                reason=str(getattr(report, "reason", "")),
                coverage=float(getattr(report, "coverage", 0.0)),
                fresh_coverage=float(getattr(report, "fresh_coverage", 0.0)),
                symbols_expected=int(getattr(report, "symbols_expected", 0)),
                symbols_with_bars=int(getattr(report, "symbols_with_bars", 0)),
                newest_bar=getattr(report, "newest_bar", None),
                oldest_bar=getattr(report, "oldest_bar", None),
                data_age_minutes=getattr(report, "data_age_minutes", None),
                duplicate_bars=int(getattr(report, "duplicate_bars", 0)),
                malformed_bars=int(getattr(report, "malformed_bars", 0)),
                impossible_ohlc=int(getattr(report, "impossible_ohlc", 0)),
                zero_volume_bars=int(getattr(report, "zero_volume_bars", 0)),
                volume_available=bool(getattr(report, "volume_available", False)),
                resolution=str(getattr(report, "resolution", "1-minute")),
                source=str(getattr(report, "source", "")),
                rankable_symbols=int(getattr(report, "rankable_symbols", 0)),
                leader_symbols=int(getattr(report, "leader_symbols", 0)),
                leaders_fresh=int(getattr(report, "leaders_fresh", 0)),
                warming_up=bool(getattr(report, "warming_up", False)),
                warmup_minutes_remaining=float(
                    getattr(report, "warmup_minutes_remaining", 0.0) or 0.0),
            )

        candidate = None
        raw_candidate = getattr(result, "candidate", None)
        if verdict is Verdict.TRADE and raw_candidate is not None:
            candidate = candidate_from_row(raw_candidate)

        ranked = tuple(candidate_from_row(row)
                       for row in (getattr(result, "ranked", None) or ()))

        return ScanOutcome(
            as_of=as_of, slot=slot, verdict=verdict,
            reason=str(getattr(result, "reason", "")), quality=quality,
            candidate=candidate, ranked=ranked,
            eligible_count=len(ranked),
            coverage_text=str(getattr(result, "coverage_text", "")),
            universe_size=int(universe_size), universe_sha256=universe_sha256,
            scanner_version=scanner_version, ai_active=bool(ai_active),
            latency_ms=latency_ms,
        )


# ------------------------------------------------------------------ adapters

def candidate_from_row(row: Mapping[str, Any]) -> Candidate:
    """Build a typed candidate from one scanner ranking row."""
    if not isinstance(row, Mapping):
        raise ScanAborted(f"ranking row is {type(row).__name__}, not a mapping")
    price = row.get("price") or {}
    return Candidate(
        symbol=str(row.get("symbol", "")),
        score=float(row.get("score", 0.0)),
        momentum=str(row.get("momentum", "UNKNOWN")),
        acceleration_label=str(row.get("acceleration_label", "UNKNOWN")),
        volume_label=str(row.get("volume_label", "UNKNOWN")),
        entry_price=(float(price["last"]) if price.get("last") is not None else None),
        ai_probability=(None if row.get("ai_probability") is None
                        else float(row["ai_probability"])),
        ai_percentile=(None if row.get("ai_percentile") is None
                       else float(row["ai_percentile"])),
        ai_active=bool(row.get("ai_active", False)),
        components=dict(row.get("components") or {}),
        returns=dict(row.get("returns") or {}),
        volume=dict(row.get("volume") or {}),
        last_bar=_parse_iso(row.get("last_bar")),
        bars=int(row.get("bars", 0) or 0),
    )


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


# ---------------------------------------------------------------- ingestion

@model
class IngestionReport:
    """What the ingestion boundary accepted, and why it refused the rest."""

    accepted: int = 0
    rejected: int = 0
    by_reason: Mapping[str, int] = field(default_factory=dict)
    newest_bar: datetime | None = None
    oldest_bar: datetime | None = None
    symbols: int = 0

    @property
    def rejection_share(self) -> float:
        total = self.accepted + self.rejected
        return self.rejected / total if total else 0.0

    def raises(self, max_share: float) -> ScanFault | None:
        """A feed that is mostly garbage is a source fault, not a data gap."""
        if self.rejection_share > max_share:
            return SourceUnavailable(
                f"{self.rejected} of {self.accepted + self.rejected} bar rows "
                f"were refused ({self.rejection_share:.1%}), above the "
                f"{max_share:.1%} limit", by_reason=dict(self.by_reason))
        return None


def validate_bar_rows(rows: Iterable[Mapping[str, Any]], *, session_day: date,
                      as_of: datetime, universe: Iterable[str] | None = None,
                      symbol_key: str = "symbol", bars_key: str = "bars",
                      time_key: str = "t", max_share: float = 0.01,
                      ) -> tuple[dict[str, list[Bar]], IngestionReport]:
    """Validate captured rows into typed bars, counting every refusal.

    This is the edge where a market feed turns into numbers, so it is the edge
    where bad numbers must die. Nothing is repaired, interpolated or dropped
    silently: every refused row is counted against a typed reason, and a feed
    that is mostly refusals is reported as a source fault rather than a data
    gap.

    Returns the accepted bars by symbol and an `IngestionReport`.
    """
    allowed = ({str(s).strip().upper() for s in universe}
               if universe is not None else None)
    accepted: dict[str, list[Bar]] = {}
    counts: dict[str, int] = {}
    seen: dict[str, dict[datetime, tuple]] = {}
    total = 0

    def reject(reason: Rejection) -> None:
        counts[reason.value] = counts.get(reason.value, 0) + 1

    for row in rows:
        total += 1
        if not isinstance(row, Mapping):
            reject(Rejection.MALFORMED)
            continue
        symbol = str(row.get(symbol_key, "")).strip().upper()
        if not symbol:
            reject(Rejection.MALFORMED)
            continue
        if allowed is not None and symbol not in allowed:
            continue  # not a refusal: simply outside the requested universe
        for item in row.get(bars_key) or ():
            total += 1
            if not isinstance(item, Mapping):
                reject(Rejection.MALFORMED)
                continue
            try:
                stamp = _bar_timestamp(item.get(time_key), session_day, as_of)
            except (TypeError, ValueError):
                reject(Rejection.MALFORMED)
                continue
            if stamp.tzinfo is None:
                reject(Rejection.NAIVE_TIMESTAMP)
                continue
            if stamp.date() != session_day:
                reject(Rejection.WRONG_SESSION)
                continue
            if stamp >= as_of:
                reject(Rejection.FUTURE_BAR)
                continue
            try:
                values = [float(item[k]) for k in ("o", "h", "l", "c")]
            except (KeyError, TypeError, ValueError):
                reject(Rejection.MALFORMED)
                continue
            if not all(math.isfinite(v) for v in values):
                reject(Rejection.NOT_FINITE)
                continue
            if not all(v > 0 for v in values):
                reject(Rejection.NON_POSITIVE_PRICE)
                continue
            volume = item.get("v", item.get("volume"))
            if volume is not None:
                try:
                    volume = float(volume)
                except (TypeError, ValueError):
                    volume = None
                else:
                    if not math.isfinite(volume) or volume < 0:
                        reject(Rejection.NEGATIVE_VOLUME)
                        continue
            try:
                bar = Bar(symbol=symbol, timestamp=stamp, open=values[0],
                          high=values[1], low=values[2], close=values[3],
                          volume=volume)
            except ValueError:
                reject(Rejection.IMPOSSIBLE_OHLC)
                continue
            fingerprint = (bar.open, bar.high, bar.low, bar.close, bar.volume)
            by_time = seen.setdefault(symbol, {})
            prior = by_time.get(stamp)
            if prior is not None:
                if prior != fingerprint:
                    reject(Rejection.DUPLICATE_CONFLICT)
                continue
            by_time[stamp] = fingerprint
            accepted.setdefault(symbol, []).append(bar)

    newest = oldest = None
    for bars in accepted.values():
        bars.sort(key=lambda bar: bar.timestamp)
        newest = max(newest, bars[-1].timestamp) if newest else bars[-1].timestamp
        oldest = min(oldest, bars[0].timestamp) if oldest else bars[0].timestamp

    report = IngestionReport(
        accepted=sum(len(bars) for bars in accepted.values()),
        rejected=sum(counts.values()),
        by_reason=counts, newest_bar=newest, oldest_bar=oldest,
        symbols=len(accepted),
    )
    fault = report.raises(max_share)
    if fault is not None:
        raise fault
    return accepted, report


def _bar_timestamp(value: Any, session_day: date, as_of: datetime) -> datetime:
    """Accept 'HH:MM', 'HH:MM:SS' or a full ISO instant; anything else is bad.

    Wall-clock times are read as Karachi wall-clock times (SO-8), because that
    is what the captured feed writes. An ISO instant may carry its own offset
    and is trusted as written; a naive one is stamped Karachi rather than the
    caller's offset, so a UTC-scoped caller cannot shift every bar by hours.
    """
    if value is None:
        raise ValueError("missing bar time")
    if as_of.tzinfo is None:
        raise ValueError("the scan instant must carry a timezone")
    text = str(value).strip()
    if len(text) == 4 and text[1] == ":":
        text = "0" + text
    if "T" in text or " " in text:
        stamp = datetime.fromisoformat(text)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=KARACHI)
        return stamp
    parts = [int(part) for part in text.split(":")]
    while len(parts) < 3:
        parts.append(0)
    return datetime(session_day.year, session_day.month, session_day.day,
                    parts[0], parts[1], parts[2], tzinfo=KARACHI)


def verdict_from_status(status: Any) -> Verdict | None:
    """Map any status string the orchestrator can emit onto a verdict.

    Returns None for a status that is neither a scanner verdict nor a known
    trade state, so a caller can treat it as an aborted scan rather than
    silently filing a new state under an old name.
    """
    text = str(status).strip().upper()
    if "." in text:                      # an enum's display form
        text = text.rsplit(".", 1)[-1]
    try:
        return Verdict(text)
    except ValueError:
        pass
    if text in MONITORING_STATUSES:
        return Verdict.MONITORING
    return None


