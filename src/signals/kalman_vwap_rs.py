"""The relative strength leg of the owner's latest intraday strategy.

Owner order 2026-11-09 (Karachi): the newest intraday law is the Kalman
Trend with VWAP on the 5 minute, 15 minute and 1 hour charts AND relative
strength, and it remains the running strategy until the owner changes it
again. The two entry paths stay exactly as they were
(src/signals/kalman_trend.py, src/signals/mtf_vwap.py,
src/signals/kalman_vwap_pullback.py); this module adds the third ingredient:
the name being called must also be outperforming the market it trades in.

Measured from the session tape alone, causally:

  * the symbol's own move is its last completed close against the open of
    its first completed bar, the same session return market_context reads;
  * the market leg is the EQUAL-WEIGHT MEAN of that same move across every
    symbol the capture holds. It is the captured cross-section, never the
    official KMIALLSHR level and never a daily file: the owner's 2026-11-08
    order withdrew the daily history, so a 20 session RS cannot be measured
    here and is not claimed;
  * relative strength is the difference, and the gate wants it strictly
    positive: the owner asked for a name that is strong relative to the
    market, not one that merely drifts with it.

Nothing here sleeps, executes or touches a network. A market too thin to
measure fails closed with its reason named (SO-3).
"""

from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from statistics import mean

from src import config
from src.data.sessions import open_time

#: The reader's own version, carried on every relative strength view.
RS_VERSION = "rs_session_v1"

#: The strategy label of the law this leg belongs to.
STRATEGY_VERSION = config.RS_STRATEGY_VERSION


def session_open_of(session) -> datetime:
    """The session's own open time in the session's own timezone (SO-8)."""
    return datetime.combine(session.day, time(*open_time(session.day)),
                            tzinfo=session.as_of.tzinfo)


def session_return(rows: list, session_open: datetime,
                   as_of: datetime) -> float | None:
    """The symbol's move from its first completed open to its last close.

    A forming minute is never read, so the number is the same one a scan
    could have printed at `as_of`. None rather than a guess when the rows
    hold no completed bar or an unusable price.
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
    """The equal-weight mean session return of the captured universe.

    Measured once per scan and handed to every name, so one scan never
    compares two names against two different markets. Fewer than
    RS_MIN_MARKET_SYMBOLS measured names is not a market view, and it says
    so instead of returning a number built from a handful of prints.
    """
    session_open = session_open_of(session)
    returns: dict[str, float] = {}
    for symbol, rows in (session.bars or {}).items():
        value = session_return(rows, session_open, session.as_of)
        if value is None:
            continue
        returns[symbol] = value
    if len(returns) < config.RS_MIN_MARKET_SYMBOLS:
        return None, "rs_market_too_thin"
    return {
        "rule": RS_VERSION,
        "mean_return": mean(returns.values()),
        "symbols": len(returns),
        "proxy": "equal-weight mean of the captured universe, "
                 "not the KMIALLSHR index",
        "as_of": session.as_of.isoformat(),
    }, "ok"


def entry_view(symbol: str, rows: list, session,
               market: dict | None) -> tuple[dict | None, str]:
    """This name's relative strength against the scan's own market leg."""
    if not isinstance(market, dict):
        return None, "rs_market_unavailable"
    market_leg = market.get("mean_return")
    if market_leg is None or not math.isfinite(float(market_leg)):
        return None, "rs_market_unavailable"
    own = session_return(rows, session_open_of(session), session.as_of)
    if own is None:
        return None, "rs_no_session_return"
    excess = own - float(market_leg)
    if not (excess > config.RS_MIN_RELATIVE_PCT):
        return None, "rs_not_positive"
    return {
        "rule": RS_VERSION,
        "symbol": symbol,
        "symbol_return": round(own, 6),
        "market_return": round(float(market_leg), 6),
        "relative_strength": round(excess, 6),
        "market_symbols": market.get("symbols"),
        "min_relative_pct": round(config.RS_MIN_RELATIVE_PCT * 100, 4),
    }, "ok"


def summary(view: dict | None) -> str:
    """One ASCII line for the card and the owner email, or empty."""
    if not isinstance(view, dict):
        return ""
    excess = view.get("relative_strength")
    market_leg = view.get("market_return")
    if excess is None or market_leg is None:
        return ""
    return (f"RS {excess * 100:+.2f} pp vs market {market_leg * 100:+.2f}% "
            f"(equal weight of {view.get('market_symbols') or 0} names)")
