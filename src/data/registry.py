"""Data-source capability registry: the footprint honesty layer.

Single source of truth for what data this system *genuinely* has. Engines must
consult this registry and refuse to run when their data is UNAVAILABLE.
Fabricating missing data (especially bid/ask / footprint / order flow) is a
governance violation (GOVERNANCE.md SO-3).

Usage in engines::

    from src.data.registry import availability, require

    if availability("footprint") is Availability.UNAVAILABLE:
        print("FOOTPRINT DATA UNAVAILABLE / DEGRADED: footprint engine disabled")
        return None
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict


class Availability(str, Enum):
    AVAILABLE = "AVAILABLE"      # genuine, verified source currently feeding it
    DEGRADED = "DEGRADED"        # partial / delayed / proxy: must be labeled
    UNAVAILABLE = "UNAVAILABLE"  # no genuine source; engine must disable itself


@dataclass(frozen=True)
class DataSource:
    key: str
    description: str
    availability: Availability
    detail: str  # honest status note, surfaced in signals and reports


REGISTRY: Dict[str, DataSource] = {
    "daily_ohlcv": DataSource(
        key="daily_ohlcv",
        description="Daily OHLCV, full PSX market incl. KMIALL universe",
        availability=Availability.AVAILABLE,
        detail="PSX Data Portal / CSOR daily files (free, official). "
               "Backbone of the 5-year local backtest.",
    ),
    "intraday_ohlcv": DataSource(
        key="intraday_ohlcv",
        description="Intraday bars (1m/5m/15m/1h)",
        availability=Availability.DEGRADED,
        detail="No free historical intraday archive for PSX. Bars are only "
               "captured forward by the scheduled GitHub Actions workflow; "
               "each run retains its artifact for 90 days. Historical intraday "
               "backtests are limited to banked data. "
               "UPDATE 2026-10-06: Path A approved by the owner; the read-only "
               "broker feed capture (src/data/feed_capture.py) and 1-minute "
               "OHLC poller (src/data/ohlc_poller.py) now bank genuine bars "
               "daily. Forward-only: no historical claims, DEGRADED until "
               "weeks of banked sessions exist. "
               "UPDATE 2026-10-14: the eClear GetOHLCData servlet that Path A "
               "read serves no bars at all, so the scan path now reads bars "
               "built from the broker tape (src/data/tape_bars.py): open, "
               "high, low and close are the prices the tape carried in that "
               "minute, and volume is the difference of the venue's own "
               "running counter. The servlet capture stays as the fallback "
               "when no tape exists for the day. MEASURED on the 2026-10-13 "
               "KMIALL tape (314 symbols, 56,618 tick rows, 09:52 to 13:47 "
               "Asia/Karachi, the one fixed offset UTC+5 this system speaks, "
               "with a 10:32 to 13:27 outage in it, read to 15:30 PKT so the "
               "whole frozen session is in it): 1-minute bars for 301 of 319 "
               "tracked symbols (94.4%), of which 13,141 of 69,303 bars "
               "(19.0%) carry the previous close across a quiet minute, volume "
               "read from the venue's own counter on 56,209 rows with zero "
               "resets, and zero symbols whose bars disagreed with the venue's "
               "own day high and low. Bar history and freshness are measured "
               "per scan, not assumed.",
    ),
    "session_snapshot": DataSource(
        key="session_snapshot",
        description="One session snapshot per symbol (open, high, low, "
                    "volume, last price) from the PSX Data Portal",
        availability=Availability.DEGRADED,
        detail="The portal's old EOD endpoint answers HTML (and 404) and "
               "/timeseries/int is a 404, both measured 2026-10-14, so there "
               "is no public intraday series to read. Its company page still "
               "carries the REG panel and its own publication stamp. "
               "DEGRADED by delay: the portal states about five minutes, and "
               "the snapshot is one bar per day, never a minute series. The "
               "chart service (charts/adapters/portal.py) serves it as a "
               "single session bar with that delay disclosed in the payload.",
    ),
    "footprint": DataSource(
        key="footprint",
        description="Footprint candles / true bid-ask order flow",
        availability=Availability.UNAVAILABLE,
        detail="FOOTPRINT DATA UNAVAILABLE / DEGRADED: no historical PSX "
               "Level-2 or tick bid/ask data exists in any free source. "
               "Forward capture via the read-only broker feed socket is the "
               "only path. Owner approved Path A on 2026-10-06: the feed "
               "daemon banks genuine ticks daily (data/feed_capture/); a "
               "genuine footprint archive begins accumulating from that date. "
               "No historical footprint exists, so the footprint engine stays "
               "disabled until a real archive is banked AND backtestable.",
    ),
    "market_breadth": DataSource(
        key="market_breadth",
        description="Advancers/decliners, sector behavior, index structure",
        availability=Availability.DEGRADED,
        detail="Derivable from daily OHLCV of the full market today; richer "
               "breadth becomes possible as intraday capture accumulates.",
    ),
    "corporate_actions": DataSource(
        key="corporate_actions",
        description="Dividends, splits, announcements affecting prices",
        availability=Availability.DEGRADED,
        detail="PSX publishes notices; parsing pipeline not yet built. "
               "Until then, event-risk filter uses conservative defaults.",
    ),
}


def get(key: str) -> DataSource:
    """Return the DataSource record for *key* (KeyError if unknown)."""
    return REGISTRY[key]


def availability(key: str) -> Availability:
    """Return the current Availability for *key*."""
    return REGISTRY[key].availability


def require(key: str) -> DataSource:
    """Return the DataSource if genuinely usable, else raise RuntimeError.

    Engines that cannot degrade use this. Engines that can degrade should
    check availability() themselves and label their output.
    """
    ds = REGISTRY[key]
    if ds.availability is Availability.UNAVAILABLE:
        raise RuntimeError(
            f"DATA UNAVAILABLE [{key}]: {ds.detail}"
        )
    return ds


def degraded_keys() -> tuple:
    """Keys that are only DEGRADED: reports must label these."""
    return tuple(k for k, v in REGISTRY.items() if v.availability is Availability.DEGRADED)


def unavailable_keys() -> tuple:
    """Keys that are UNAVAILABLE: engines for these must be disabled."""
    return tuple(k for k, v in REGISTRY.items() if v.availability is Availability.UNAVAILABLE)

