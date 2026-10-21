"""Market session schedule for PSX, pinned to Asia/Karachi forever.

SO-8: every time this system speaks, it speaks Pakistan Standard Time:
a fixed UTC+5 offset with no daylight saving. PKT has been UTC+5 since
1971, so this module uses a fixed tzinfo rather than the IANA database.
The schedule can never drift with a timezone database update and never
depends on the machine's own clock settings.

Owner's session law, corrected 2026-10-10 against the exchange's own
published trading hours (psx.com.pk/psx/exchange/general/trading-hours):

    Monday to Thursday:  ONE session   opens 09:32, closes 15:30
    Friday:              TWO sessions  opens 09:17, closes 12:00
                                       opens 14:32, closes 16:30
    PSX holidays:        no session (list below, refreshed yearly)

The Friday midday break is real and the exchange does not trade through
it. Before this correction the law described Friday as one continuous
09:17 to 16:30 session, which made the app claim ONLINE while the
exchange was shut (observed at 14:23 on a Friday, with trading resuming
at 14:32). A session is therefore a set of BANDS, not one window, and
every phase decision in the repository comes from `market_phase` below:
the local runner, the tick script, the Cloudflare relay and the phone
app must all agree about which band, if any, is live.

Phases (`MarketPhase`):

    CLOSED      weekend or a PSX holiday
    PRE_OPEN    a trading day, before the first band of the day
    WARMUP      inside a band, but within its first N minutes
    OPEN        inside a band
    BREAK       between two bands on the same day (Friday 12:00 to 14:32)
    POST_CLOSE  after the last band of the day

Owner's market-state law (2026-10-11), alongside the bands:

The owner asked for one function that answers "which market state is this",
with four states and strict 2-minute gaps, and for the scanner to run ONLY
in the market state. `market_state_at` below is that function; it never
replaces the phases, which the relay, the app and the notification texts
still read:

    PRE_MARKET   a trading day, 09:00 to 09:15, both session shapes
    MARKET       inside a band: Mon-Thu 09:32 to 15:30; Friday 09:17 to
                 12:00 and 14:32 to 16:30
    POST_MARKET  Mon-Thu 15:32 to 15:49; Friday 16:32 to 16:49
    CLOSED       everything else, including the gaps at 15:30-15:32 and
                 16:30-16:32, the Friday midday break and the 09:15-09:32
                 morning gap

Every window is half-open, [start, end), so 15:30:00 itself is no longer the
market and 15:32:00 is already post-market: an instant that sits exactly on
a boundary belongs to the window that starts there, never to the one that
ends there. `is_scan_window` is the one answer to "may the scanner run now":
true in MARKET always, and in PRE_MARKET and POST_MARKET when the owner's
2026-10-21 order (QOR_SCAN_PRE_POST_MARKET, default on) says so: the quant
scans every second through those windows too, on the live broker feed.
The Friday midday break and CLOSED remain sleep windows in every mode.

Owner's condition law (2026-10-11), the owner-facing half of the same clock:

`market_condition_at` folds the six phases into the three conditions the
phone app and the card are allowed to speak about, so no caller ever has to
invent a sentence from a phase name:

    OPERATIONAL  the exchange is trading (phase OPEN or WARMUP)
    BREAK        a trading day between two bands, the exchange's own
                 midday break: Friday 12:00 to 14:32
    CLOSED       everything else: before the first band, after the last
                 one, the weekend, a PSX holiday, and the two minute gap
                 after each close

`condition_text` returns the owner's exact sentence for that condition
("Market is on a break right now." and "Market is closed right now."), and
an empty string while the exchange is trading, because the pill already
says ONLINE.

This module is the only place that may build a market time (SO-8). It
never invents a band: what the exchange publishes is what is encoded
here, and the phone app is never the authority on whether the market is
open, it only renders what the relay answers.

Notification texts are fixed by the owner (SO-9) and live here so every
caller (local runner, Cloudflare worker) uses identical wording.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import Enum

# SO-8: the one and only zone this system may ever use.
KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
KARACHI_UTC_OFFSET_HOURS = 5

# Owner's session law, in Karachi wall-clock time, as bands per weekday.
# Monday to Thursday one band; Friday two, with the exchange's own midday
# break between them.
WEEKDAY_OPEN = (9, 32)    # Mon, Tue, Wed, Thu
WEEKDAY_CLOSE = (15, 30)
FRIDAY_OPEN = (9, 17)
FRIDAY_FIRST_CLOSE = (12, 0)
FRIDAY_SECOND_OPEN = (14, 32)
FRIDAY_CLOSE = (16, 30)

#: A band is ((open_hour, open_minute), (close_hour, close_minute)).
Band = tuple[tuple[int, int], tuple[int, int]]

# Owner's pre-market and post-market windows (2026-10-11). Both session
# shapes share the pre-market window; post-market follows the day's last
# close after the owner's strict 2-minute gap (15:32 and 16:32).
PRE_MARKET_OPEN = (9, 0)
PRE_MARKET_CLOSE = (9, 15)
POST_MARKET_OPEN = (15, 32)
POST_MARKET_CLOSE = (15, 49)
FRIDAY_POST_MARKET_OPEN = (16, 32)
FRIDAY_POST_MARKET_CLOSE = (16, 49)

WEEKDAY_BANDS: tuple[Band, ...] = ((WEEKDAY_OPEN, WEEKDAY_CLOSE),)
FRIDAY_BANDS: tuple[Band, ...] = (
    (FRIDAY_OPEN, FRIDAY_FIRST_CLOSE),
    (FRIDAY_SECOND_OPEN, FRIDAY_CLOSE),
)

# Owner's exact texts (SO-9, reworded by owner order 2026-10-08: name the
# market event first, then the quant state).
# Do not reword, ever.
MSG_MARKET_OPEN = "Market is open. Quant is online now."
MSG_MARKET_CLOSED = "Market is closed. Quant is sleeping now."

# Owner's exact condition texts (order of 2026-10-11). The break sentence is
# for the exchange's own Friday midday break and nothing else: a weekend and
# a holiday are CLOSED, and calling either of them a break would be wrong.
MSG_CONDITION_BREAK = "Market is on a break right now."
MSG_CONDITION_CLOSED = "Market is closed right now."

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


class MarketPhase(str, Enum):
    """Which part of the trading day an instant is in.

    `is_market_open` is true only for OPEN and WARMUP, so a break, a
    weekend, a holiday and the hours before the open are all OFFLINE.
    """

    CLOSED = "CLOSED"
    PRE_OPEN = "PRE_OPEN"
    WARMUP = "WARMUP"
    OPEN = "OPEN"
    BREAK = "BREAK"
    POST_CLOSE = "POST_CLOSE"

    @property
    def is_live(self) -> bool:
        """True only while the exchange is actually trading."""
        return self in (MarketPhase.OPEN, MarketPhase.WARMUP)


class MarketState(str, Enum):
    """The owner's four market states (order of 2026-10-11).

    Windows are half-open, [start, end). PRE_MARKET is 09:00 to 09:15 on
    any trading day, MARKET is every band, POST_MARKET is 15:32 to 15:49
    Monday to Thursday and 16:32 to 16:49 on Friday. Every other instant,
    including the strict 2-minute gaps after each close, is CLOSED.

    MARKET is a scan window always; PRE_MARKET and POST_MARKET are scan
    windows only when SCAN_PRE_POST_MARKET is set (owner order 2026-10-21,
    which supersedes the 2026-10-11 order).
    """

    PRE_MARKET = "PRE_MARKET"
    MARKET = "MARKET"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"

    @property
    def is_scan_window(self) -> bool:
        """MARKET always; the pre and post windows under the 2026-10-21
        order."""
        if self is MarketState.MARKET:
            return True
        return self in (MarketState.PRE_MARKET, MarketState.POST_MARKET) \
            and SCAN_PRE_POST_MARKET


class MarketCondition(str, Enum):
    """The owner's three owner-facing conditions (order of 2026-10-11).

    The phases describe the trading day; these three describe what the
    owner is told. OPERATIONAL is the exchange trading inside a band,
    BREAK is the exchange's own midday break (Friday 12:00 to 14:32), and
    CLOSED is every instant at which the exchange is not trading and not
    on that break: before the first band, after the last one, the weekend,
    a PSX holiday, and the two minute gap after each close.

    The texts are returned by `condition_text`, so no caller has to build a
    sentence from a phase name, and the app and the worker cannot drift.
    """

    OPERATIONAL = "OPERATIONAL"
    BREAK = "BREAK"
    CLOSED = "CLOSED"

    @property
    def is_live(self) -> bool:
        """True only while the exchange is actually trading."""
        return self is MarketCondition.OPERATIONAL


def now_karachi() -> datetime:
    """Current instant in the one true zone."""
    return datetime.now(KARACHI)


def as_karachi(moment: datetime | None = None) -> datetime:
    """Interpret an instant in Karachi time (naive input is local Karachi)."""
    if moment is None:
        return now_karachi()
    if moment.tzinfo is None:
        return moment.replace(tzinfo=KARACHI)
    return moment.astimezone(KARACHI)


def is_trading_day(d: date) -> bool:
    """True for Mon-Fri dates that are not PSX holidays."""
    if d.weekday() >= 5:
        return False
    return d.isoformat() not in PSX_HOLIDAYS_2026


def session_bands(d: date) -> tuple[Band, ...]:
    """The bands the exchange trades on Karachi date d (empty when closed)."""
    if not is_trading_day(d):
        return ()
    return FRIDAY_BANDS if d.weekday() == 4 else WEEKDAY_BANDS


def open_time(d: date) -> tuple[int, int]:
    """(hour, minute) of the FIRST open for Karachi date d.

    Kept for callers that only care when the trading day begins; use
    `session_bands` when the break matters.
    """
    bands = session_bands(d)
    return bands[0][0] if bands else (WEEKDAY_OPEN if d.weekday() != 4
                                      else FRIDAY_OPEN)


def close_time(d: date) -> tuple[int, int]:
    """(hour, minute) of the LAST close for Karachi date d."""
    bands = session_bands(d)
    return bands[-1][1] if bands else (WEEKDAY_CLOSE if d.weekday() != 4
                                       else FRIDAY_CLOSE)


def _at(d: date, hm: tuple[int, int]) -> datetime:
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=KARACHI)


def band_bounds(d: date, band: Band) -> tuple[datetime, datetime]:
    """Open and close instants (Karachi zone) of one band on date d."""
    return _at(d, band[0]), _at(d, band[1])


def session_bounds(d: date) -> tuple[datetime, datetime]:
    """First open and last close (Karachi zone) for trading date d."""
    return _at(d, open_time(d)), _at(d, close_time(d))


def current_band(moment: datetime | None = None) -> Band | None:
    """The band that is live at this instant, or None (break, closed, pre)."""
    k = as_karachi(moment)
    for band in session_bands(k.date()):
        opens, closes = band_bounds(k.date(), band)
        if opens <= k < closes:
            return band
    return None


def market_phase(moment: datetime | None = None, *,
                 warmup_minutes: float = 0.0) -> MarketPhase:
    """Which part of the trading day this instant is in.

    `warmup_minutes` marks the first N minutes of each band as WARMUP, so
    a runner can tell "the session is live" from "the session is live but
    the strategy has not had enough bars yet". A break is never warmup:
    after the Friday midday break the second band gets its own warmup.
    """
    k = as_karachi(moment)
    day = k.date()
    bands = session_bands(day)
    if not bands:
        return MarketPhase.CLOSED
    first_open = _at(day, bands[0][0])
    last_close = _at(day, bands[-1][1])
    if k < first_open:
        return MarketPhase.PRE_OPEN
    if k >= last_close:
        return MarketPhase.POST_CLOSE
    for band in bands:
        opens, closes = band_bounds(day, band)
        if opens <= k < closes:
            if warmup_minutes and k < opens + timedelta(minutes=warmup_minutes):
                return MarketPhase.WARMUP
            return MarketPhase.OPEN
    return MarketPhase.BREAK


def is_market_open(moment: datetime | None = None) -> bool:
    """True only inside a live band, per the owner's law (SO-8).

    The Friday midday break and the whole weekend are closed. This is the
    single answer every caller (runner, relay, app) must render as ONLINE
    or OFFLINE.
    """
    return market_phase(moment).is_live


def pre_market_window(d: date) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The pre-market window for a Karachi date, or None when closed."""
    if not is_trading_day(d):
        return None
    return (PRE_MARKET_OPEN, PRE_MARKET_CLOSE)


def post_market_window(d: date) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """The post-market window for a Karachi date, or None when closed.

    Friday's window follows its own last close (16:32 to 16:49); every
    other trading day's follows the 15:30 close (15:32 to 15:49).
    """
    if not is_trading_day(d):
        return None
    if d.weekday() == 4:
        return (FRIDAY_POST_MARKET_OPEN, FRIDAY_POST_MARKET_CLOSE)
    return (POST_MARKET_OPEN, POST_MARKET_CLOSE)


def _hm_micros(hm: tuple[int, int]) -> int:
    """A (hour, minute) window edge as microseconds after midnight."""
    return (hm[0] * 60 + hm[1]) * 60 * 1_000_000


def market_state_at(moment: datetime | None = None) -> MarketState:
    """Which of the owner's four states this instant is in (2026-10-11).

    ``moment`` must be a timezone-aware datetime. A naive datetime is
    refused rather than assumed, because the wrong assumption silently
    shifts the session; any aware zone is converted to Karachi first. A
    value that is not a datetime raises TypeError.

    Edges are strict, so an instant that sits exactly on a boundary belongs
    to the window starting there and never to the one ending there: at
    09:15:00 this is CLOSED (pre-market has ended, the market opens at
    09:32), and at 15:30:00 on a Monday to Thursday it is CLOSED until
    post-market starts at 15:32:00.
    """
    if moment is None:
        moment = now_karachi()
    if not isinstance(moment, datetime):
        raise TypeError(
            f"moment must be a datetime, got {type(moment).__name__}")
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(
            "moment must be timezone-aware; a naive datetime is ambiguous "
            "and is refused rather than assumed to be Karachi time")
    k = as_karachi(moment)
    day = k.date()
    if not is_trading_day(day):
        return MarketState.CLOSED
    now_micros = ((k.hour * 60 + k.minute) * 60 + k.second) * 1_000_000 \
        + k.microsecond
    window = pre_market_window(day)
    if window is not None and _hm_micros(window[0]) <= now_micros \
            < _hm_micros(window[1]):
        return MarketState.PRE_MARKET
    for band in session_bands(day):
        if _hm_micros(band[0]) <= now_micros < _hm_micros(band[1]):
            return MarketState.MARKET
    window = post_market_window(day)
    if window is not None and _hm_micros(window[0]) <= now_micros \
            < _hm_micros(window[1]):
        return MarketState.POST_MARKET
    return MarketState.CLOSED


# Owner order 2026-10-21: scan the pre-market and post-market windows too,
# on the live broker feed, with the exchange's own session bands unchanged.
# Defaults ON; a future order flips it off and the law above snaps back to
# MARKET alone.
SCAN_PRE_POST_MARKET = True


def is_scan_window(moment: datetime | None = None) -> bool:
    """May the scanner run at this instant?

    True always in MARKET. True in PRE_MARKET and POST_MARKET when
    SCAN_PRE_POST_MARKET is set (owner order 2026-10-21, which supersedes
    the 2026-10-11 order that barred those windows).
    """
    state = market_state_at(moment)
    if state is MarketState.MARKET:
        return True
    if state in (MarketState.PRE_MARKET, MarketState.POST_MARKET):
        return SCAN_PRE_POST_MARKET
    return False


def market_condition_at(moment: datetime | None = None) -> MarketCondition:
    """Which of the owner's three conditions this instant is in.

    A single fold of `market_phase`, so the condition can never disagree
    with the session bands: WARMUP and OPEN are OPERATIONAL, the Friday
    midday break is BREAK, and every other phase is CLOSED. The morning
    gap (09:15 to 09:32) and the two minute gap after a close are CLOSED,
    because the exchange is not trading in either.
    """
    phase = market_phase(moment)
    if phase.is_live:
        return MarketCondition.OPERATIONAL
    if phase is MarketPhase.BREAK:
        return MarketCondition.BREAK
    return MarketCondition.CLOSED


def condition_text(moment: datetime | None = None) -> str:
    """The owner's exact sentence for this instant, or '' while trading.

    Nothing is returned while the exchange is trading: the app's pill
    already says ONLINE, and a second sentence would only repeat it.
    """
    condition = market_condition_at(moment)
    if condition is MarketCondition.BREAK:
        return MSG_CONDITION_BREAK
    if condition is MarketCondition.CLOSED:
        return MSG_CONDITION_CLOSED
    return ""


def market_state(moment: datetime | None = None) -> dict:
    """The typed, serialisable answer the relay and the app both consume.

    Returns the phase, the live band (if any), and the next band edge, so
    a UI can say "OFFLINE, break until 14:32" without re-deriving the law.
    """
    k = as_karachi(moment)
    phase = market_phase(k)
    band = current_band(k)
    event, at = next_event(k)
    live_band = (None if band is None
                 else {"open": _hm(band[0]), "close": _hm(band[1])})
    condition = market_condition_at(k)
    return {
        "phase": phase.value,
        "market_open": phase.is_live,
        "condition": condition.value,
        "condition_text": condition_text(k),
        "as_of": k.isoformat(timespec="seconds"),
        "date": k.date().isoformat(),
        "trading_day": is_trading_day(k.date()),
        "live_band": live_band,
        "bands": [{"open": _hm(b[0]), "close": _hm(b[1])}
                  for b in session_bands(k.date())],
        "next_event": (None if event is None else
                       {"event": event,
                        "at_pk": at.strftime("%Y-%m-%d %H:%M")}),
        "timezone": "Asia/Karachi",
    }


def _hm(hm: tuple[int, int]) -> str:
    return f"{hm[0]:02d}:{hm[1]:02d}"


def next_event(moment: datetime | None = None) -> tuple[str, datetime] | tuple[None, None]:
    """Next ("OPEN", band start) or ("CLOSE", band end) the relay fires.

    With the Friday break there are four edges on a Friday: two opens and
    two closes. Scans forward at most 10 calendar days; a market that
    never opens in 10 days means the holiday list is stale and we say so
    in the result rather than guessing a date.
    """
    k = as_karachi(moment)
    for offset in range(10):
        d = (k + timedelta(days=offset)).date()
        for band in session_bands(d):
            opens, closes = band_bounds(d, band)
            if opens > k:
                return "OPEN", opens
            if closes > k:
                return "CLOSE", closes
    # Stale holiday list: treat tomorrow's scheduled open as a hard
    # fallback so the runner never goes silent, and let the failure be
    # loud (SO-9). Friday opens at 09:17, everything else at 09:32.
    fallback_date = (k + timedelta(days=1)).date()
    fallback = _at(fallback_date, open_time(fallback_date))
    return "OPEN", fallback


def next_open(moment: datetime | None = None) -> datetime:
    """The next band start after this instant (used by the runners)."""
    k = as_karachi(moment)
    for offset in range(11):
        d = (k + timedelta(days=offset)).date()
        for band in session_bands(d):
            opens, _ = band_bounds(d, band)
            if opens > k:
                return opens
    return _at((k + timedelta(days=1)).date(), open_time((k + timedelta(days=1)).date()))


def session_window_text(d: date) -> str:
    """Human window text for a date, break included: "09:17-12:00, 14:32-16:30"."""
    bands = session_bands(d)
    if not bands:
        return "closed (weekend or PSX holiday)"
    return ", ".join(f"{_hm(band[0])}-{_hm(band[1])}" for band in bands)


def ms_until(instant: datetime, now: datetime | None = None) -> int:
    """Whole milliseconds from now until instant (>= 0)."""
    n = now or now_karachi()
    return max(0, int((instant - n).total_seconds() * 1000))
