"""
Session-opens memory for the morning-fade engine.

The exit ladder and the overnight-history feature both need the NEXT
SESSION'S OPENING PRINT per pick. The morning trace polls from
09:35 PKT; this module records, per trading date, each symbol's first
price seen that day - the closest honest proxy for the official open
that the poll cadence gives (the PSX open auction print lands at
09:30:01; our first stored print is 09:35, at most one slot late, and
the card states the basis).

Storage: data/session_opens.json
    {"sessions": {"2026-09-30": {"PSO": {"open": 100.8,
                                         "ts": "...Z"}},
                  ...}}
    last 15 sessions kept. Idempotent per day: the first print of a
    session wins, later polls never overwrite it.
"""
from __future__ import annotations


def record_session_open(
    state: dict,
    trading_date: str,
    quotes: dict[str, dict],
    keep_sessions: int = 15,
) -> tuple[dict, bool]:
    """Fold one morning poll into the opens memory.

    Returns (state, wrote). The first poll of the day writes every
    symbol's price; later polls only fill symbols still missing.
    """
    sessions = state.setdefault("sessions", {})
    day = sessions.setdefault(trading_date, {})
    wrote = False
    for sym, q in (quotes or {}).items():
        if not q:
            continue
        price = q.get("price")
        if not price or price <= 0:
            continue
        if sym in day:
            continue  # first print of the session wins - idempotent
        day[sym] = {
            "open": price,
            "ts": q.get("timestamp"),
        }
        wrote = True
    # Retention: keep the last N sessions.
    for old in sorted(sessions.keys())[:-keep_sessions]:
        sessions.pop(old, None)
    return state, wrote


def open_of(state: dict, trading_date: str, symbol: str) -> float | None:
    """The recorded open print for one symbol on one date, or None."""
    return ((state.get("sessions") or {}).get(trading_date) or {}).get(symbol, {}).get("open")
