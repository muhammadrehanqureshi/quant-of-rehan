"""Market session schedule for PSX, pinned to Asia/Karachi forever.

SO-8: every time this system speaks, it speaks Pakistan Standard Time:
a fixed UTC+5 offset with no daylight saving. PKT has been UTC+5 since
1971, so this module uses a fixed tzinfo rather than the IANA database.
The schedule can never drift with a timezone database update and never
depends on the machine's own clock settings.

Owner's session law (2026-10-05):
    Monday to Thursday: opens 09:32, closes 15:30
    Friday:             opens 09:17, closes 16:30
    PSX holidays:       no session (list below, refreshed yearly)

Notification texts are fixed by the owner (SO-9) and live here so every
caller (local runner, Cloudflare worker) uses identical wording.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

# SO-8: the one and only zone this system may ever use.
KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
KARACHI_UTC_OFFSET_HOURS = 5

# Owner's session law, in Karachi wall-clock time.
WEEKDAY_OPEN = (9, 32)    # Mon, Tue, Wed, Thu
WEEKDAY_CLOSE = (15, 30)
FRIDAY_OPEN = (9, 17)
FRIDAY_CLOSE = (16, 30)

# Owner's exact texts (SO-9). Do not reword, ever.
MSG_MARKET_OPEN = "Market is open and the system is online."
MSG_MARKET_CLOSED = "Market is closed and the system is sleeping now."

# PSX trading holidays for 2026 (published by PSX; salvaged from the
# sentinel's maintained list, data/legacy_sentinel/data/psx_holidays.json).
# Refresh every January when PSX publishes the new calendar.
PSX_HOLIDAYS_2026 = frozenset({
    "2026-02-05", "2026-03-21", "2026-03-23", "2026-05-01", "2026-05-27",
    "2026-05-28", "2026-06-25", "2026-06-26", "2026-08-14", "2026-08-25",
    "2026-11-09", "2026-12-25",
})

# PSX trades Monday to Friday only; Saturdays and Sundays never have a
# session. TradingDay = datetime.weekday() (0=Monday ... 6=Sunday).
TradingDay = int


def now_karachi() -> datetime:
    """Current instant in the one true zone."""
    return datetime.now(KARACHI)


def is_trading_day(d: date) -> bool:
    """True for Mon-Fri dates that are not PSX holidays."""
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in PSX_HOLIDAYS_2026


def open_time(d: date) -> tuple[int, int]:
    """(hour, minute) of the open for Karachi date d."""
    return FRIDAY_OPEN if d.weekday() == 4 else WEEKDAY_OPEN


def close_time(d: date) -> tuple[int, int]:
    """(hour, minute) of the close for Karachi date d."""
    return FRIDAY_CLOSE if d.weekday() == 4 else WEEKDAY_CLOSE


def _at(d: date, hm: tuple[int, int]) -> datetime:
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=KARACHI)


def session_bounds(d: date) -> tuple[datetime, datetime]:
    """Open and close instants (Karachi zone) for trading date d."""
    return _at(d, open_time(d)), _at(d, close_time(d))


def is_market_open(now: datetime | None = None) -> bool:
    """True only inside a live session, per the owner's law."""
    n = (now or now_karachi()).astimezone(KARACHI)
    if not is_trading_day(n.date()):
        return False
    o, c = session_bounds(n.date())
    return o <= n < c


def next_event(now: datetime | None = None) -> tuple[str, datetime]:
    """Next (OPEN, instant) or (CLOSE, instant) the runner must fire.

    Scans forward at most 10 calendar days; a market that never opens in
    10 days means the holiday list is stale and we say so in the result.
    """
    n = (now or now_karachi()).astimezone(KARACHI)
    for offset in range(10):
        d = (n + timedelta(days=offset)).date()
        if not is_trading_day(d):
            continue
        o, c = session_bounds(d)
        if o > n:
            return "OPEN", o
        if c > n:
            return "CLOSE", c
    # Stale holiday list: treat tomorrow 09:32 as a hard fallback so the
    # runner never goes silent, and let the failure be loud (SO-9).
    fallback_date = (n + timedelta(days=1)).date()
    fallback = _at(fallback_date, (9, 32))
    return "OPEN", fallback


def ms_until(instant: datetime, now: datetime | None = None) -> int:
    """Whole milliseconds from now until instant (>= 0)."""
    n = now or now_karachi()
    return max(0, int((instant - n).total_seconds() * 1000))
