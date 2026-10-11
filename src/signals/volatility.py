"""Volatility regime and market edge cases, measured on real intraday bars.

Rebuild 2026-10-10. The scanner's score is a momentum-and-volume reading. It
already decays late moves multiplicatively, but it has no idea whether the
session it is looking at is calm, violent or broken, and a 4-minute loop has to
survive all three. This module adds that reading, and nothing else:

  * a REGIME, from the session's own average true range as a share of price,
    bucketed into config thresholds (calm / normal / elevated / extreme);
  * EDGE CASES that make a name untradable or a reading meaningless, detected
    from the bars themselves: limit-locked prints, flat bars, zero-range
    sessions, thin samples, a stale last bar, gap opens, and violent intraday
    swings;
  * an optional TARGET MULTIPLIER so the owner can widen or narrow the +2%
    target by regime, OFF by default so the live strategy is unchanged until
    the owner turns it on;
  * an optional VETO for the objectively untradable cases, also OFF by default.

It never scores, ranks or picks anything: `momentum_scanner` remains the only
thing that does. Every function takes bars and returns a typed assessment, so
the loop can log what regime it saw and why it refused a name.

Usage:

    from src.signals.volatility import assess, Regime

    reading = assess("OGDC", bars, as_of=as_of)
    reading.regime            # Regime.ELEVATED
    reading.atr_pct           # 0.0187
    reading.edge_cases        # (EdgeCase.GAP_UP,)
    reading.is_untradable     # False
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from statistics import median, pstdev
from typing import Sequence

from src import config
from src.signals.contracts import Bar, InsufficientCoverage, ScanFault

# A reading below this many bars is reported as UNKNOWN rather than guessed.
MIN_BARS_FOR_VOLATILITY = 10


class Regime(str, Enum):
    CALM = "CALM"
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


class EdgeCase(str, Enum):
    """Conditions that change what a reading means, or whether a trade exists."""

    LIMIT_LOCKED = "LIMIT_LOCKED"        # flat print with no volume: cannot enter
    FLAT_BARS = "FLAT_BARS"              # repeated identical bars
    ZERO_RANGE = "ZERO_RANGE"            # the whole session has one price
    THIN_SAMPLE = "THIN_SAMPLE"          # too few bars to say anything
    STALE_LAST_BAR = "STALE_LAST_BAR"    # the newest bar is behind the scan
    GAP_UP = "GAP_UP"                    # opened far above the previous close
    GAP_DOWN = "GAP_DOWN"
    EXTREME_SWING = "EXTREME_SWING"      # intraday high-to-low beyond the limit
    MISSING_VOLUME = "MISSING_VOLUME"    # volume absent on some bars


#: Cases where a real order could not have been filled at the printed price.
UNTRADABLE = frozenset({EdgeCase.LIMIT_LOCKED})


@dataclass(frozen=True)
class VolatilityAssessment:
    symbol: str
    regime: Regime
    atr_pct: float | None
    realized_vol: float | None
    gap_pct: float | None
    swing_pct: float | None
    bars: int
    edge_cases: tuple[EdgeCase, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_untradable(self) -> bool:
        return any(case in UNTRADABLE for case in self.edge_cases)

    @property
    def target_multiplier(self) -> float:
        """Regime-scaled multiplier for the +2% target.

        Returns exactly 1.0 unless the owner enables volatility-aware targets,
        so the live rule cannot change by accident.
        """
        if not config.VOLATILITY_AWARE_TARGETS:
            return 1.0
        return float(config.TARGET_MULTIPLIER_BY_REGIME.get(self.regime.value, 1.0))

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "regime": self.regime.value,
            "atr_pct": None if self.atr_pct is None else round(self.atr_pct, 6),
            "realized_vol": (None if self.realized_vol is None
                             else round(self.realized_vol, 6)),
            "gap_pct": None if self.gap_pct is None else round(self.gap_pct, 6),
            "swing_pct": None if self.swing_pct is None else round(self.swing_pct, 6),
            "bars": self.bars,
            "edge_cases": [case.value for case in self.edge_cases],
            "notes": list(self.notes),
        }


# ------------------------------------------------------------------ measures

def true_ranges(bars: Sequence[Bar]) -> list[float]:
    """Wilder true range per bar, anchored on the previous close."""
    ranges: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            ranges.append(bar.high - bar.low)
            continue
        prior_close = bars[index - 1].close
        ranges.append(max(bar.high - bar.low,
                          abs(bar.high - prior_close),
                          abs(bar.low - prior_close)))
    return ranges


def average_true_range_pct(bars: Sequence[Bar]) -> float | None:
    """Mean true range as a share of the last close."""
    if not bars or bars[-1].close <= 0:
        return None
    ranges = true_ranges(bars)
    if not ranges:
        return None
    return (sum(ranges) / len(ranges)) / bars[-1].close


def realized_volatility(bars: Sequence[Bar]) -> float | None:
    """Standard deviation of per-bar simple returns, same units as a return."""
    closes = [bar.close for bar in bars]
    if len(closes) < 3:
        return None
    returns = [closes[i] / closes[i - 1] - 1.0
               for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(returns) < 2:
        return None
    return pstdev(returns)


def classify(atr_pct: float | None) -> Regime:
    """Bucket an ATR reading against the configured thresholds."""
    if atr_pct is None or not math.isfinite(atr_pct):
        return Regime.UNKNOWN
    if atr_pct <= config.ATR_CALM_PCT:
        return Regime.CALM
    if atr_pct <= config.ATR_ELEVATED_PCT:
        return Regime.NORMAL
    if atr_pct <= config.ATR_EXTREME_PCT:
        return Regime.ELEVATED
    return Regime.EXTREME


# --------------------------------------------------------------- edge cases

def detect_edge_cases(bars: Sequence[Bar], as_of: datetime,
                      previous_close: float | None = None,
                      staleness_minutes: float | None = None) -> tuple[EdgeCase, ...]:
    """Every condition in the bars that changes the reading or the trade."""
    found: list[EdgeCase] = []
    if len(bars) < MIN_BARS_FOR_VOLATILITY:
        found.append(EdgeCase.THIN_SAMPLE)
    if not bars:
        return tuple(found)

    limit = staleness_minutes if staleness_minutes is not None \
        else config.STALENESS_MINUTES
    if (as_of - bars[-1].timestamp).total_seconds() / 60.0 > limit:
        found.append(EdgeCase.STALE_LAST_BAR)

    if all(bar.is_flat for bar in bars):
        found.append(EdgeCase.ZERO_RANGE)
        if all((bar.volume or 0.0) == 0.0 for bar in bars):
            found.append(EdgeCase.LIMIT_LOCKED)

    flat_run = 0
    for bar in bars:
        flat_run = flat_run + 1 if bar.is_flat else 0
        if flat_run >= 5:
            if EdgeCase.FLAT_BARS not in found:
                found.append(EdgeCase.FLAT_BARS)
            break

    if any(bar.volume is None for bar in bars):
        found.append(EdgeCase.MISSING_VOLUME)

    session_open = bars[0].open
    if previous_close and previous_close > 0:
        gap = session_open / previous_close - 1.0
        if gap >= config.MAX_GAP_PCT:
            found.append(EdgeCase.GAP_UP)
        elif gap <= -config.MAX_GAP_PCT:
            found.append(EdgeCase.GAP_DOWN)

    high = max(bar.high for bar in bars)
    low = min(bar.low for bar in bars)
    if low > 0 and (high - low) / low >= config.MAX_INTRADAY_SWING_PCT:
        found.append(EdgeCase.EXTREME_SWING)

    return tuple(found)


def assess(symbol: str, bars: Sequence[Bar], as_of: datetime,
           previous_close: float | None = None) -> VolatilityAssessment:
    """Measure one symbol's regime and edge cases from its session bars."""
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    atr_pct = average_true_range_pct(ordered)
    realized = realized_volatility(ordered)
    gap_pct = None
    if ordered and previous_close and previous_close > 0:
        gap_pct = ordered[0].open / previous_close - 1.0
    swing = None
    if ordered:
        high = max(bar.high for bar in ordered)
        low = min(bar.low for bar in ordered)
        swing = (high - low) / low if low > 0 else None

    edge_cases = detect_edge_cases(ordered, as_of, previous_close)
    # A reading from fewer than MIN_BARS_FOR_VOLATILITY bars is reported as
    # UNKNOWN rather than guessed, exactly as this module's contract states.
    # Classifying a two or three bar sample produced a confident-looking
    # regime (ELEVATED on three bars) that contradicted the documented law.
    regime = (classify(atr_pct) if len(ordered) >= MIN_BARS_FOR_VOLATILITY
              else Regime.UNKNOWN)
    notes: list[str] = []
    if regime is Regime.EXTREME:
        notes.append("session volatility is extreme for this universe; a late "
                     "entry here pays the widest spread of the day")
    elif regime is Regime.CALM:
        notes.append("session volatility is calm; momentum breakouts are more "
                     "likely to be noise")

    return VolatilityAssessment(
        symbol=str(symbol).strip().upper(), regime=regime,
        atr_pct=atr_pct, realized_vol=realized, gap_pct=gap_pct, swing_pct=swing,
        bars=len(ordered), edge_cases=edge_cases, notes=tuple(notes),
    )


def hard_block_fault(reading: VolatilityAssessment) -> ScanFault | None:
    """The fault for a name that could not have been traded, when enforced.

    Returns None unless `VOLATILITY_VETO_ENABLED` is on, so the default
    behaviour of the live scanner is unchanged.
    """
    if not config.VOLATILITY_VETO_ENABLED:
        return None
    if EdgeCase.LIMIT_LOCKED in reading.edge_cases:
        return InsufficientCoverage(
            f"{reading.symbol} is limit locked: the session printed one price "
            f"with no volume, so no order could fill at the printed price",
            symbol=reading.symbol)
    if EdgeCase.MISSING_VOLUME in reading.edge_cases:
        return InsufficientCoverage(
            f"{reading.symbol} has bars with no volume; the strategy requires "
            f"volume expansion", symbol=reading.symbol)
    return None
