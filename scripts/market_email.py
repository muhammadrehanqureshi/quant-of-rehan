"""The market event emails (owner order 2026-10-22, exact wording).

Runs inside GitHub Actions from .github/workflows/market-email.yml, one
job per event. Every comment the job writes is an email on the owner's
GitHub connected address, posted on the watched owner email issue by
src/notify/owner_email.py, whose comment ledger makes each event exactly
once per Karachi day however late or however double a fire arrives.

The wording is the owner's own, and is never edited on the way through:

- open and closed are the owner's 2026-10-08 sentences, fixed in
  src/data/sessions.py (MSG_MARKET_OPEN, MSG_MARKET_CLOSED) and quoted
  here from that law, never retyped.
- break is the phone notification's 2026-10-11 sentence, mirrored from
  cloud/worker.js's MSG_MARKET_BREAK and the app's strings.xml.
- pre and post are the owner's sentences booked 2026-10-22; post follows
  the same shape he typed for pre. Both name the window, which never
  changes the exchange state (owner order 2026-10-21).

The job's decision is the session law (SO-8): the script recomputes the
Karachi instant itself, refuses a weekend or a window the event does not
belong to, and then lets the comment ledger decide whether the email
still has to go out. Nothing waits, nothing fabricates.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    MSG_MARKET_CLOSED,
    MSG_MARKET_OPEN,
    MarketPhase,
    MarketState,
    PRE_MARKET_OPEN,
    as_karachi,
    band_bounds,
    market_phase,
    market_state_at,
    now_karachi,
    post_market_window,
    session_bands,
)
from src.notify import owner_email  # noqa: E402
from src.notify.market_watch import ledger_key  # noqa: E402 - the shared key law

# Owner's exact sentences (SO-9). Do not reword, ever.
EVENT_TEXTS = {
    "pre": "The market is pre-opened. Quant is online now.",
    "open": MSG_MARKET_OPEN,
    "break": "Market is on a break. Quant is sleeping until the market reopens.",
    "close": MSG_MARKET_CLOSED,
    "post": "The market is post-opened. Quant is online now.",
}

EVENTS = tuple(EVENT_TEXTS)


def due(event: str, moment=None) -> bool:
    """True when this instant is inside the window the event names.

    The window check is the session law itself, not a clock guess: the
    cron names the minute, the law names the truth, and a late fire that
    lands inside its window still emails (the ledger keeps it exactly
    once), while a fire that lands outside it stops without writing a
    comment.
    """
    k = as_karachi(moment)
    if not session_bands(k.date()):
        # No session today (weekend or PSX holiday): no event is due.
        return False
    if event == "pre":
        return market_state_at(k) is MarketState.PRE_MARKET
    if event == "open":
        return market_phase(k) in (MarketPhase.WARMUP, MarketPhase.OPEN)
    if event == "break":
        return market_phase(k) is MarketPhase.BREAK
    if event == "close":
        return market_phase(k) is MarketPhase.POST_CLOSE
    if event == "post":
        return market_state_at(k) is MarketState.POST_MARKET
    return False


def event_roadmap(day: date) -> list[tuple[str, str, datetime]]:
    """The day's events in order, each with (event, label, fire_at PKT).

    This is the session law again, in the shape catch_up walks: the
    pre-market opening, each band's open (the second band labelled
    reopen), the midday break between two bands, the last close and the
    post-market opening that follows it. derived only from the band
    table and the two fixed windows, never from a clock.
    """
    bands = session_bands(day)
    if not bands:
        return []
    open_h, open_m = PRE_MARKET_OPEN
    # A naive wall-time in the law's alone zone (SO-8).
    at = lambda hour, minute: as_karachi(
        datetime(day.year, day.month, day.day, hour, minute))
    roadmap = [("pre", "", at(open_h, open_m))]
    for index, band in enumerate(bands, start=1):
        opens, closes = band_bounds(day, band)
        label = "" if index == 1 else "reopen"
        roadmap.append(("open", label, opens))
        if len(bands) > 1 and index == 1:
            roadmap.append(("break", "", closes))
    last_open, last_close = band_bounds(day, bands[-1])
    roadmap.append(("close", "", last_close))
    window = post_market_window(day)
    if window is not None:
        p_open = window[0]
        roadmap.append(("post", "", at(*p_open)))
    return roadmap


# How long after an event's own minute a catch-up fire may still email
# it. GitHub's queue is owed nothing; this window absorbs the minutes to
# a quarter hour of lateness, beyond which the email is stale and the
# band loop's own passenger (market_watch) is the tolerant path anyway
# (it attempts the phase it finds inside the whole band).
CATCH_UP_GRACE_MINUTES = 15.0


def catch_up(moment: datetime | None = None, sender=None,
             today_markers=None) -> list[str]:
    """Email every event whose minute passed within the grace and is
    still missing from the ledger. Returns the markers that landed.

    This is the backstop for a GitHub cron that fires late or never: a
    catch-up fire walks the day's roadmap, sends what is due inside the
    grace window and is not already on today's ledger, and skips
    everything else with a printed reason. The ledger keeps each event
    exactly once across this path, the band loop's passenger and the
    per-event cron jobs.
    """
    if sender is None:
        def sender(event: str, label: str, day: str) -> bool:
            return bool(owner_email.send(
                EVENT_TEXTS[event], ledger_key(event, label, day)))
    if today_markers is None:
        today_markers = owner_email.sent_markers
    k = as_karachi(moment) if moment is not None else now_karachi()
    day = k.date()
    try:
        sent = set(today_markers())
    except Exception as exc:  # noqa: BLE001 - never raise into the fire
        print(f"catch-up: today's ledger unreadable: "
              f"{type(exc).__name__}: {exc}; sending nothing")
        return []
    grace = timedelta(minutes=CATCH_UP_GRACE_MINUTES)
    mailed: list[str] = []
    for event, label, fire_at in event_roadmap(day):
        if fire_at > k:
            continue  # still to come; its own cron or loop edge owns it
        if not (fire_at <= k and k < fire_at + grace):
            continue  # too stale for a backstop
        key = ledger_key(event, label, day.isoformat())
        if key in sent or key in mailed:
            print(f"catch-up: {key} already delivered this day")
            continue
        try:
            if sender(event, label, day.isoformat()):
                mailed.append(key)
            else:
                print(f"catch-up: {key} refused by the ledger; not resent")
        except Exception as exc:  # noqa: BLE001 - never raise into the fire
            print(f"catch-up: {key} failed: {type(exc).__name__}: {exc}; "
                  "a later fire may still catch it inside the grace")
    if not mailed:
        print(f"catch-up: nothing due inside the grace at "
              f"{k:%Y-%m-%d %H:%M:%S} PKT")
    return mailed


def fire(event: str, label: str = "", moment=None) -> bool:
    """Email the event when it is due. True only when a comment landed.

    `label` distinguishes two fires of the same event on one day: the
    Friday reopen (the second band's open at 14:32) writes
    ``market-open:<date>:reopen`` while the morning open writes
    ``market-open:<date>``, so both go out and neither is hidden by the
    other.
    """
    if event not in EVENTS:
        raise SystemExit(f"unknown event: {event}")
    now = as_karachi(moment) if moment is not None else now_karachi()
    if not due(event, now):
        print(f"{event}: not due at {now:%Y-%m-%d %H:%M:%S} PKT; no email")
        return False
    key = f"market-{event}:{now.date().isoformat()}"
    if label:
        key = f"{key}:{label.strip()}"
    return owner_email.send(EVENT_TEXTS[event], key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="owner's market event email")
    parser.add_argument("--event", choices=EVENTS,
                        help="one event; each cron's own job owns its minute")
    parser.add_argument("--key", default="",
                        help="distinguishes two fires of one event per day "
                             "(the Friday reopen) in the dedup ledger")
    parser.add_argument("--catch-up", action="store_true",
                        help="walk today's roadmap and send whatever is due "
                             "inside the grace and missing from the ledger "
                             "(the backstop when GitHub's queue runs late)")
    args = parser.parse_args(argv)
    if args.catch_up:
        catch_up()
        return 0
    if not args.event:
        parser.error("--event or --catch-up is required")
    fire(args.event, args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
