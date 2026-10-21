"""One answer to "what may the scanner do at this instant" (rebuild 2026-10-11).

The local 4-minute tick (scripts/kmiall_tick.py) and the supervised loop
(scripts/scan_loop.py) drive the same orchestrator, and each used to carry its
own copy of the pause table plus its own `phase_of`/`slot_of`. Two copies of
the rule that decides whether the exchange is tradeable is one copy too many:
the Friday midday break and the owner's pre-market and post-market never-scan
order each had to be added twice, and a fix in one place could leave the other
scanning a shut market.

This module is that one place. It owns the slot label, the phase, the state and
the three way decision (scan, finalize, wait), and it owns nothing else: no
network, no state file, no orchestrator, no clock of its own. Both callers keep
their own guards (the tick its slot guard and lock, the loop its backoff) and
both stay trivially testable with an injected instant.

The session law itself remains in src/data/sessions.py, which is the only
authority on PSX hours (SO-8); this module only labels it and decides what a
fire is for. Every instant it labels is Asia/Karachi wall clock, UTC+5, because
it builds no time of its own: it hands the caller's instant to sessions.py and
reports what the law says.

Decision order, first match wins (the owner's orders, 2026-10-11):

    PRE_MARKET   wait   the pre-market window is never scanned
    CLOSED       wait   weekend, PSX holiday, or outside every band
    PRE_OPEN     wait   before the first band of the day
    WARMUP       wait   inside a band, but the strategy has too few bars
    BREAK        wait   the Friday midday break
    OPEN         scan   inside a band, in MARKET
    POST_MARKET  finalize  the session has closed (never a scan)
    POST_CLOSE   finalize  the session has closed (never a scan)
"""

from __future__ import annotations

from datetime import datetime

from src import config
from src.data.sessions import (
    MarketState,
    is_scan_window,
    market_phase,
    market_state_at,
    session_window_text,
)

# Phase names as strings, mirroring MarketPhase in src/data/sessions.py. Kept
# as module constants because both callers' logs and tests read them.
PHASE_CLOSED = "CLOSED"
PHASE_PRE_OPEN = "PRE_OPEN"
PHASE_WARMUP = "WARMUP"
PHASE_OPEN = "OPEN"
PHASE_BREAK = "BREAK"
PHASE_POST_CLOSE = "POST_CLOSE"

# The three things a scheduled or supervised fire may do.
ACTION_SCAN = "scan"
ACTION_FINALIZE = "finalize"
ACTION_WAIT = "wait"

#: The owner's market states, as the strings the callers log and test.
STATE_MARKET = MarketState.MARKET.value
STATE_PRE_MARKET = MarketState.PRE_MARKET.value
STATE_POST_MARKET = MarketState.POST_MARKET.value


def slot_of(moment: datetime, interval_minutes: float | None = None,
            interval_seconds: float | None = None) -> str:
    """The scan slot a moment belongs to, floored to the cadence.

    The slot label is what the once-per-slot guard is keyed on, so it must
    stay stable for every fire inside the same interval.

    A whole-minute cadence keeps the minute label the local 4 minute tick has
    always used (10:07 -> 10:04, 10:59 -> 10:56). A sub-minute cadence -- the
    cloud session loop's 30 seconds (owner order 2026-10-14, SO-13) -- labels
    the second as well (10:07:29 -> 10:07:00, 10:07:31 -> 10:07:30), because a
    30 second runner that reported only the minute would guard away 29 of its
    30 slots and scan once a minute while claiming every 30 seconds.
    """
    if interval_seconds is not None:
        step = max(1.0, float(interval_seconds))
        if step >= 60 and step % 60 == 0:
            return slot_of(moment, step / 60.0)
        # Any other cadence is floored on its own grid, so the label is stable
        # for every fire inside one slot whatever the interval is.
        elapsed = moment.hour * 3600 + moment.minute * 60 + moment.second
        floored = int(elapsed // step) * int(step)
        return (f"{floored // 3600:02d}:{(floored % 3600) // 60:02d}:"
                f"{floored % 60:02d}")
    step = max(1, int(interval_minutes
                      if interval_minutes is not None
                      else config.TICK_INTERVAL_MINUTES))
    minute = (moment.minute // step) * step
    return f"{moment.hour:02d}:{minute:02d}"


def phase_of(moment: datetime, warmup_minutes: float | None = None) -> str:
    """Which part of the trading day this instant is in.

    Delegates to src/data/sessions.py, the one session law (SO-8). The warmup
    is the first N minutes of each band, so a runner can tell "the session is
    live" from "the session is live but the strategy has not had enough bars".
    """
    warmup = (config.TICK_WARMUP_MINUTES if warmup_minutes is None
              else warmup_minutes)
    return market_phase(moment, warmup_minutes=warmup).value


def state_of(moment: datetime) -> str:
    """Which of the owner's four market states this instant is in."""
    return market_state_at(moment).value


def decide(moment: datetime,
           warmup_minutes: float | None = None) -> tuple[str, str]:
    """What a fire at this instant should do, as (action, reason).

    Pure and clock free, so the whole decision table is testable without
    sleeping and without a network. `action` is one of ACTION_SCAN,
    ACTION_FINALIZE or ACTION_WAIT; `reason` is a full sentence fragment
    suitable for a log line, and it names the state or phase that decided.
    """
    warmup = (config.TICK_WARMUP_MINUTES if warmup_minutes is None
              else warmup_minutes)
    phase = phase_of(moment, warmup)
    state = state_of(moment)
    window = session_window_text(moment.date())

    # Owner order 2026-10-21 (superseding 2026-10-11): pre-market IS a
    # scan window, on the live broker feed, every second.
    if state == STATE_PRE_MARKET:
        if is_scan_window(moment):
            return ACTION_SCAN, (f"{STATE_PRE_MARKET}: pre-market scanning is "
                                 f"on (owner order 2026-10-21), live broker feed")
        return ACTION_WAIT, (f"{STATE_PRE_MARKET}: the pre-market window is "
                             f"never scanned (owner order 2026-10-11)")

    if phase == PHASE_CLOSED:
        return ACTION_WAIT, (f"{PHASE_CLOSED}: not a PSX trading day "
                             f"(weekend or PSX holiday)")

    if phase == PHASE_PRE_OPEN:
        return ACTION_WAIT, (f"{PHASE_PRE_OPEN}: before the session open "
                             f"(today {window})")

    if phase == PHASE_WARMUP:
        return ACTION_WAIT, (f"{PHASE_WARMUP}: inside the first {warmup:g} "
                             f"minutes after the open; not enough bars yet")

    if phase == PHASE_BREAK:
        return ACTION_WAIT, (f"{PHASE_BREAK}: the exchange is in its midday "
                             f"break (today {window})")

    if phase == PHASE_OPEN:
        if state != STATE_MARKET:
            # Defensive: the band law and the state law are both in
            # src/data/sessions.py, and only MARKET may be scanned.
            return ACTION_WAIT, (f"{state}: outside the scan window "
                                 f"(owner order 2026-10-11)")
        return ACTION_SCAN, f"{PHASE_OPEN}: inside the session (today {window})"

    if state == STATE_POST_MARKET:
        # Owner order 2026-10-21 (superseding 2026-10-11): post-market IS
        # a scan window too. Finalize remains the scheduled finalize's job
        # and stays strictly after the close; the loop outside a band
        # neither scans nor finalizes.

        if is_scan_window(moment):
            return ACTION_SCAN, (f"{STATE_POST_MARKET}: post-market scanning is "
                                 f"on (owner order 2026-10-21), live broker feed")
        return ACTION_FINALIZE, (f"{STATE_POST_MARKET}: the session has "
                                 f"closed; post-market is finalize-only")

    return ACTION_FINALIZE, f"{PHASE_POST_CLOSE}: the session has closed"
