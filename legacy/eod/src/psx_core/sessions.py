"""
PSX trading-session calendar and session-boundary derivation.

Why this module exists
----------------------
Thirteen places across the dataset builder and validator performed per-symbol
sequential operations -- pct_change(), diff(), shift(1), expanding() -- grouped
by symbol alone. With a single day of snapshots that is harmless. The moment a
second day exists it silently corrupts data:

  * price_change_pct_5s for the first tick of day 2 becomes the overnight gap,
    labelled as a 5-second move.
  * volume_delta for the first tick of day 2 is (day 2 cumulative) minus
    (day 1 final), a large negative number, so it is flagged as a reset and
    day 2's opening volume is discarded.

Two different groupings are needed, and they are not the same thing:

  * trading_date  -- cumulative counters (volume, trades, value) reset once per
                     trading day and run continuously across the Friday lunch
                     break. Group deltas of cumulative fields by this.
  * session_id    -- one contiguous run of ticks. Friday has two legs separated
                     by ~2.5 hours. Group tick-to-tick features by this.

Schedule (Asia/Karachi, UTC+5, no DST), per
https://psx.com.pk/psx/exchange/general/trading-hours
  Mon-Thu : 09:32-15:30
  Friday  : 09:17-12:00 and 14:32-16:30

Public holidays ARE modelled (v0.20.0): the official PSX holiday
calendar (psx.com.pk -> Exchange -> General -> Calendar Holidays) is
baked into _HOLIDAYS below; legs_for() returns no legs on those dates,
so is_trading_day/is_open/next_open/current_leg all skip them
automatically. UPDATE EACH JANUARY when PSX publishes the new PDF
(the data/psx_holidays.json in this repo mirrors it for the Cloudflare
seatbelt). The Ramadan schedule differs and is published separately
each year -- still handled empirically (a surprise closure produces a
missing session, never wrong data).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

PKT = ZoneInfo("Asia/Karachi")

# Any observed gap at least this long starts a new session leg. Chosen well
# above the 5s poll interval and well below the Friday lunch break.
SESSION_GAP_SECONDS = 900.0

# Official PSX trading holidays (psx.com.pk Calendar Holidays PDF,
# 2026 calendar). Weekend dates included for completeness -- they are
# already non-trading. KEEP IN SYNC WITH data/psx_holidays.json and
# refresh every January from the exchange's published PDF.
_HOLIDAYS: frozenset[str] = frozenset({
    "2026-02-05",  # Kashmir Day (Thu)
    "2026-03-21",  # Eid-ul-Fitr holiday (Sat)
    "2026-03-23",  # Pakistan Day (Mon)
    "2026-05-01",  # Labour Day (Fri)
    "2026-05-27",  # Eid-ul-Adha (Wed)
    "2026-05-28",  # Eid-ul-Adha holiday / Youm-e-Takbeer (Thu)
    "2026-06-25",  # Ashura (Thu)
    "2026-06-26",  # Ashura (Fri)
    "2026-08-14",  # Independence Day (Fri)
    "2026-08-25",  # Eid-e-Miladunabi (Tue)
    "2026-11-09",  # Iqbal Day (Mon)
    "2026-12-25",  # Quaid-e-Azam Day / Christmas (Fri)
})


def is_holiday(day: date) -> bool:
    """True when `day` is an official PSX trading holiday."""
    return day.isoformat() in _HOLIDAYS


@dataclass(frozen=True)
class Leg:
    """One contiguous trading window on a given weekday."""

    index: int
    start: time
    end: time


# Monday=0 ... Sunday=6
_SCHEDULE: dict[int, tuple[Leg, ...]] = {
    0: (Leg(1, time(9, 32), time(15, 30)),),
    1: (Leg(1, time(9, 32), time(15, 30)),),
    2: (Leg(1, time(9, 32), time(15, 30)),),
    3: (Leg(1, time(9, 32), time(15, 30)),),
    4: (
        Leg(1, time(9, 17), time(12, 0)),
        Leg(2, time(14, 32), time(16, 30)),
    ),
    5: (),
    6: (),
}


def to_pkt(moment: datetime) -> datetime:
    """Convert any aware datetime to Pakistan time. Naive input is assumed UTC."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(PKT)


def legs_for(day: date) -> tuple[Leg, ...]:
    if is_holiday(day):
        return ()
    return _SCHEDULE.get(day.weekday(), ())


def is_trading_day(day: date) -> bool:
    return bool(legs_for(day))


def next_trading_day(day: date) -> date:
    """The next day with a session, strictly after `day`.

    Skips weekends AND official PSX holidays (v0.20.1). Used by the
    dividend-runway doctrine: "will I still be holding when the
    ex-drop lands?" is a question about the next SESSION, not the
    next calendar day.
    """
    probe = day + timedelta(days=1)
    for _ in range(30):  # 30 days > any holiday cluster
        if is_trading_day(probe):
            return probe
        probe += timedelta(days=1)
    return probe  # unreachable in practice; keeps types honest


def session_over_for(moment: datetime) -> bool:
    """True only when the WHOLE session is done for `moment`'s day:
    a trading day, and the local time at/after the LAST leg's end.

    The between-legs gap (Friday 12:00-14:32) is NOT session-over -
    the close card must never fire there (2026-09-25 incident: it did).
    """
    local = to_pkt(moment)
    legs = legs_for(local.date())
    if not legs:
        return False
    return local.time() >= legs[-1].end


def current_leg(moment: datetime) -> Leg | None:
    """Return the trading leg containing `moment`, or None if closed."""
    local = to_pkt(moment)
    for leg in legs_for(local.date()):
        if leg.start <= local.time() < leg.end:
            return leg
    return None


def is_open(moment: datetime) -> bool:
    return current_leg(moment) is not None


def trading_date(moment: datetime) -> date:
    """
    The PSX trading date a moment belongs to.

    Always the Pakistan-local calendar date: a full session (04:17-11:30 UTC)
    never crosses a UTC midnight, so this is unambiguous.
    """
    return to_pkt(moment).date()


def next_resumption(moment: datetime) -> datetime | None:
    """
    The start of the next trading leg TODAY strictly after `moment`, or
    None when no further leg starts today.

    The distinction matters to the live runner: Friday's 12:00-14:32
    lunch gap is an INTRA-DAY break - positions stay open, bookkeeping
    must not run (it would force-close at lunch prices and label
    outcomes hours early). After the day's final leg the session is
    truly closed and end-of-day bookkeeping belongs.
    """
    local = to_pkt(moment)
    for leg in legs_for(local.date()):
        candidate = datetime.combine(local.date(), leg.start, tzinfo=PKT)
        if candidate > local:
            return candidate
    return None


def next_open(moment: datetime) -> datetime:
    """
    The next instant the market opens at or after `moment`.

    Used by the collector to sleep until the next session instead of polling a
    closed market for hours and writing thousands of identical stale snapshots.
    """
    local = to_pkt(moment)

    for day_offset in range(0, 8):
        day = local.date() + timedelta(days=day_offset)

        for leg in legs_for(day):
            candidate = datetime.combine(day, leg.start, tzinfo=PKT)
            if candidate >= local:
                return candidate

    raise RuntimeError(f"No trading session found within 8 days of {local}")


def leg_end(moment: datetime) -> datetime | None:
    """The close of the leg containing `moment`, or None if closed."""
    leg = current_leg(moment)
    if leg is None:
        return None
    local = to_pkt(moment)
    return datetime.combine(local.date(), leg.end, tzinfo=PKT)


def session_id(moment: datetime) -> str:
    """
    Stable identifier for the contiguous trading window, e.g. "2026-09-04#1".

    Timestamps outside any scheduled leg are bucketed as "#0" so they remain
    groupable and visibly distinct rather than being merged into a real session.
    """
    local = to_pkt(moment)
    leg = current_leg(moment)
    index = leg.index if leg is not None else 0
    return f"{local.date().isoformat()}#{index}"
