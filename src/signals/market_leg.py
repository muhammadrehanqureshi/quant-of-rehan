"""The market leg the one running law reads.

Owner order 2026-11-12 (Karachi): the relative strength strategy
(`kalman_vwap_rs_v3`) is withdrawn with every other previous strategy, and the
only strategy is the Kalman Trend with the three VWAP frames and the hybrid
statistical arbitrage and mean reversion model. What survives from that module
is not a strategy and never opens a trade on its own: it is the one number the
hybrid law needs to know which side of the pair is cheap.

Measured from the session tape alone, causally:

  * the symbol's own move is its last completed close against the open of its
    first completed bar;
  * the market leg is the EQUAL WEIGHT MEAN of that same move across every
    symbol the capture holds. It is the captured cross section, never the
    official KMIALLSHR level and never a daily file: the owner's 2026-11-08
    order withdrew the daily history, so a 20 session measure cannot be made
    here and is not claimed.

Nothing here sleeps, executes or touches a network. A market too thin to
measure fails closed with its reason named (SO-3).
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from statistics import mean

from src import config
from src.data.sessions import open_time

#: The reader's own version, carried on every market leg it returns.
MARKET_LEG_VERSION = "market_leg_equal_weight_v1"


def session_open_of(session) -> datetime:
    """The session's own open time in the session's own timezone (SO-8)."""
    return datetime.combine(session.day, time(*open_time(session.day)),
                            tzinfo=session.as_of.tzinfo)


def session_return(rows: list, session_open: datetime,
                   as_of: datetime) -> float | None:
    """The symbol's move from its first completed open to its last close.

    A forming minute is never read, so the number is the same one a scan could
    have printed at `as_of`. None rather than a guess when the rows hold no
    completed bar or an unusable price.
    """
    completed = [bar for bar in rows
                 if session_open <= bar.timestamp
                 and bar.timestamp + timedelta(minutes=1) <= as_of]
    if not completed:
        return None
    first_open = float(completed[0].open)
    last_close = float(completed[-1].close)
    if not (math.isfinite(first_open) and math.isfinite(last_close)
            and first_open > 0 and last_close > 0):
        return None
    return last_close / first_open - 1.0


def market_return(session) -> tuple[dict | None, str]:
    """The equal weight mean session return of the captured universe.

    Measured once per scan and handed to every name, so one scan never
    compares two names against two different markets. Fewer than
    MARKET_LEG_MIN_SYMBOLS measured names is not a market view, and it says so
    instead of returning a number built from a handful of prints.
    """
    session_open = session_open_of(session)
    returns: dict[str, float] = {}
    for symbol, rows in (session.bars or {}).items():
        value = session_return(rows, session_open, session.as_of)
        if value is None:
            continue
        returns[symbol] = value
    if len(returns) < config.MARKET_LEG_MIN_SYMBOLS:
        return None, "market_leg_too_thin"
    return {
        "rule": MARKET_LEG_VERSION,
        "mean_return": mean(returns.values()),
        "symbols": len(returns),
        "proxy": "equal-weight mean of the captured universe, "
                 "not the KMIALLSHR index",
        "as_of": session.as_of.isoformat(),
    }, "ok"
