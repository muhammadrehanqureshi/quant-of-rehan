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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    MSG_MARKET_CLOSED,
    MSG_MARKET_OPEN,
    MarketPhase,
    MarketState,
    as_karachi,
    market_phase,
    market_state_at,
    now_karachi,
    session_bands,
)
from src.notify import owner_email  # noqa: E402

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
    parser.add_argument("--event", required=True, choices=EVENTS)
    parser.add_argument("--key", default="",
                        help="distinguishes two fires of one event per day "
                             "(the Friday reopen) in the dedup ledger")
    args = parser.parse_args(argv)
    fire(args.event, args.key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
