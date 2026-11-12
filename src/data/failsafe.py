"""The session failsafe: the scan that never waits for one cron fire.

Owner order 2026-11-11: "I want you to introduce a fail safe for Quant of Rehan.
So the Quant of Rehan can possibly never be down and always scan the pre and
post market."

The bands already have a primary loop (intraday-session.yml), per-slot backstop
scans (intraday-capture.yml) and the relay's own watchdog. What none of those
can see is a GitHub schedule event that never arrives, or a band that is running
but whose feed never came up: GitHub reports such a job green while it pushes
nothing. This module answers exactly one question for the failsafe workflow,
without opening a socket, so the decision is testable on a fixed clock:

    given the instant, the relay's /health answer and its /flow answer, should
    another band be dispatched, and does the owner need an email?

The law:

* outside a PSX trading day or a scan window nothing is dispatched, so a
  mistimed fire costs nothing;
* the capture opens with the exchange's own pre-open (09:15 Monday to Thursday,
  09:00 on Friday, owner order 2026-11-12), which the session law already calls
  a scan window, so no lead time before it is a window of its own;
* a relay that did not answer at all is the one case that also alerts, because
  no scan can publish while the relay is down;
* a feed whose newest frame is older than STALE_SECONDS inside a window is
  dispatched again, since a running band that pushes nothing is dead;
* a healthy feed dispatches nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from src.data.sessions import (
    is_trading_day,
    market_state_at,
)

# A feed this old inside a scan window is dead. The band pushes every frame it
# receives, at the broker's own cadence, so four minutes of silence is a dead
# capture and never a quiet symbol.
STALE_SECONDS = 240.0

# SO-8: the clock here is Asia/Karachi (UTC+5), and every window edge is
# imported from src/data/sessions.py, the one place the pin lives.
# Owner order 2026-11-12 (latest): the recorder starts with the exchange's own
# pre-open, 09:15 Monday to Thursday and 09:00 on Friday, so there is no lead
# window before it for a warmer-up band to cover.

# How long a dispatched band runs. Long enough for the pre-open window and for
# the post-market window, and the loop's own pause table stops it scanning the
# moment the window closes.
DISPATCH_SECONDS = 1800


@dataclass(frozen=True)
class Decision:
    """What the failsafe should do, and the sentence that says why."""

    dispatch: bool
    reason: str
    alert: bool


def flow_age_seconds(moment: datetime, health: Mapping[str, Any] | None,
                     flow: Mapping[str, Any] | None) -> float | None:
    """How old the relay's newest frame is, from its own stamps.

    The relay's `market_feed.age_seconds` is the age it measured itself, so it
    is preferred. `/flow`'s `as_of` is the fallback: it is stamped by the relay
    from the frame it holds, so it answers the same question one step later.
    None means the answer carried no time at all, which cannot prove a feed is
    alive.
    """
    feed = (health or {}).get("market_feed") or {}
    age = feed.get("age_seconds")
    if isinstance(age, (int, float)) and age >= 0:
        return float(age)
    stamp = (flow or {}).get("as_of")
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        return None
    return max(0.0, (moment - then).total_seconds())


def capture_warmup(moment: datetime) -> bool:
    """False at every moment: the recorder starts with the pre-open itself.

    Owner order 2026-11-12 (latest): the capture begins at 09:15 Monday to
    Thursday and at 09:00 on Friday, the exchange's own pre-open, so no minute
    before it is a warm-up any more. The session law already treats those
    pre-open windows as scan windows, which is what decide() reads.
    """
    return False


def decide(moment: datetime, health: Mapping[str, Any] | None,
           flow: Mapping[str, Any] | None) -> Decision:
    """Should a band be dispatched again, and is the owner to be emailed?"""
    if moment.tzinfo is None:
        raise ValueError("the failsafe needs an aware instant, not a naive one")
    if not is_trading_day(moment.date()):
        return Decision(False, "not a PSX trading day", False)
    state = market_state_at(moment)
    warmup = capture_warmup(moment)
    if not state.is_scan_window and not warmup:
        return Decision(False, "outside every scan window "
                               f"({state.value})", False)
    where = state.value if state.is_scan_window else "capture warm-up"
    if health is None:
        return Decision(True, "the relay did not answer /health", True)
    if flow is None:
        return Decision(True, "the relay did not answer /flow", False)
    age = flow_age_seconds(moment, health, flow)
    if age is None:
        return Decision(
            True,
            "the relay named no frame time, so the feed cannot be shown alive",
            False,
        )
    if age > STALE_SECONDS:
        return Decision(
            True,
            f"the newest frame is {age:.0f} s old inside {where}",
            False,
        )
    return Decision(False, f"the feed is {age:.0f} s old inside {where}",
                    False)
