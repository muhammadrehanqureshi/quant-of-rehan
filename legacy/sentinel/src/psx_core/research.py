"""
Shared research core for both PSX bots - labels, costs, barriers, splits.

Every function here is walk-forward safe by construction: nothing in
this module may read a future row to build a present-time value. The
labeling functions are the ONE place where future prices are read, and
they are only ever used for labels (the y), never for features (the X).

Costs (owner-confirmed, 2026-09-30):
    commission 0.15% of traded value per side (min Rs 0.03/share when
    price <= 20 PKR), SST 16% OF THE COMMISSION amount, regulatory
    levies ~0.05% of traded value per side, CGT 15% of the profit.
    These mirror src/exit_frontier.py (the-sentinel) and
    src/eod_bot.side_cost (sentinel-eod) exactly.

Session conventions (psx_core.sessions, both repos):
    Mon-Thu 09:30 open, 15:30 close. Friday leg 1 09:30-12:00,
    leg 2 14:32-16:30. All PKT (UTC+5). The reusable functions here
    take explicit session boundaries so tests never depend on "today".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- The owner's universal exit law (2026-09-21, never changes) ----------
TP_PCT = 2.0
SL_PCT = 1.0

# --- The confirmed cost stack (2026-09-30) --------------------------------
COMMISSION_PCT_FRAC = 0.0015
COMMISSION_PER_SHARE_PKR = 0.03
PRICE_BAND_PKR = 20.0
SST_RATE = 0.16
REGULATORY_LEVY_FRAC = 0.0005
PROFIT_TAX_RATE = 0.15


def side_cost_pkr(price: float) -> float:
    """One side's commission + SST + levies, in PKR per share."""
    if price > PRICE_BAND_PKR:
        commission = COMMISSION_PCT_FRAC * price
    else:
        commission = COMMISSION_PER_SHARE_PKR
    return commission + SST_RATE * commission + REGULATORY_LEVY_FRAC * price


def round_trip_cost_pct(entry_price: float, exit_price: float) -> float:
    """Buy+sell costs as a % of entry value."""
    costs = side_cost_pkr(entry_price) + side_cost_pkr(exit_price)
    return costs / entry_price * 100.0


def net_pnl_pct(entry_price: float, exit_price: float) -> float:
    """Net pnl % after the full cost stack, on a 1-share basis.

    Gross profit pays 15% CGT; losses pay no tax. Matches
    exit_frontier.net_pnl_pct to the paisa (verified in tests).
    """
    gross = exit_price - entry_price
    costs = side_cost_pkr(entry_price) + side_cost_pkr(exit_price)
    tax = PROFIT_TAX_RATE * max(gross, 0.0)
    return (gross - costs - tax) / entry_price * 100.0


def breakeven_win_rate(target_pct: float, stop_pct: float) -> float:
    """Win rate at which TP/SL net expectancy is zero, net of costs.

    Uses the cost at a representative price of 50 PKR (the blend the
    book actually trades) so the number is comparable everywhere.
    """
    rt = round_trip_cost_pct(50.0, 50.0 * (1 - stop_pct / 100.0))
    w_tp = net_pnl_pct(50.0, 50.0 * (1 + target_pct / 100.0))
    w_sl = net_pnl_pct(50.0, 50.0 * (1 - stop_pct / 100.0))
    # p * w_tp + (1-p) * w_sl = 0  ->  p = -w_sl / (w_tp - w_sl)
    return float(-w_sl / (w_tp - w_sl) * 100.0)


# --- Triple-barrier labeling (Bot A) --------------------------------------
@dataclass
class BarrierResult:
    label: int                 # +1 tp, -1 sl, 0 timeout
    exit_price: float
    hit_time: pd.Timestamp | None   # None for timeout
    bars_to_outcome: int
    gross_pct: float           # raw exit price move, % of entry
    net_pct: float             # after the full cost stack


def triple_barrier(
    prices: pd.Series,
    entry_idx: int,
    tp_pct: float = TP_PCT,
    sl_pct: float = SL_PCT,
    max_bars: int = 78,
    check_first: str = "sl",
) -> BarrierResult:
    """Walk forward from entry_idx and find which barrier hits first.

    prices           : intraday price series (5-min bars), entry at
                       prices.iloc[entry_idx]; the walk STARTS at
                       entry_idx + 1 (the bar after entry - no same-bar
                       self-look).
    tp_pct / sl_pct  : barrier distances in % of entry.
    max_bars         : time limit; session-end close is the timeout
                       exit price (force-close convention).
    check_first      : when BOTH barriers sit inside one bar's
                       high-low span, which one to award. "sl" is the
                       adverse-selection convention (conservative,
                       matches exit_frontier/replay): the stop is
                       presumed filled when order is unknowable.

    The entry itself must be realistic: the caller passes the price it
    can actually pay (next-bar or spread-adjusted), never a signal-time
    print it could not have filled.
    """
    if max_bars < 1:
        raise ValueError("max_bars must be >= 1")
    if check_first not in ("sl", "tp"):
        raise ValueError("check_first must be 'sl' or 'tp'")
    if not isinstance(prices, pd.Series):
        prices = pd.Series(prices, dtype=float)
    prices = prices.reset_index(drop=True)
    entry = float(prices.iloc[entry_idx])
    tp = entry * (1 + tp_pct / 100.0)
    sl = entry * (1 - sl_pct / 100.0)
    n = len(prices)

    # Same-bar span (if supplied via a parallel highs/lows frame) is the
    # caller's business; this walk uses close-to-close prints, the only
    # honest bars the collector stores.
    last = min(entry_idx + max_bars, n - 1)
    for i in range(entry_idx + 1, last + 1):
        p = float(prices.iloc[i])
        if p >= tp and p <= sl:  # degenerate flat-zero span; skip
            continue
        if p <= sl:
            return BarrierResult(-1, sl, None if i == entry_idx else i,
                                 i - entry_idx, -sl_pct,
                                 net_pnl_pct(entry, sl))
        if p >= tp:
            return BarrierResult(1, tp, i, i - entry_idx, tp_pct,
                                 net_pnl_pct(entry, tp))
    exit_price = float(prices.iloc[last])
    gross = (exit_price - entry) / entry * 100.0
    return BarrierResult(0, exit_price, None, last - entry_idx, gross,
                         net_pnl_pct(entry, exit_price))


# --- Overnight labeling (Bot B) -------------------------------------------
@dataclass
class OvernightResult:
    symbol: str
    entry_date: str            # the buy day (near-close)
    exit_date: str             # the sell day (next session)
    entry_price: float
    open_price: float
    r5: float                  # % return selling at open+5 min proxy
    r10: float
    r15: float
    hold_to_close: float       # % return selling at exit-day close
    gap_pct: float             # open vs previous close
    weekday: int               # 0=Mon .. 6=Sun of the BUY day
    sessions_held: int         # 1 normally, >1 across weekends/holidays


def overnight_returns(
    next_open: float,
    entry_close: float,
    intraday_first_bars: dict[str, float] | None = None,
) -> dict[str, float]:
    """One overnight hold's returns.

    entry_close : the BUY-day near-close entry price (Bot B's fill).
    next_open   : the next session's opening print.
    intraday_first_bars : optional {"r5": px, "r10": px, "r15": px,
                    "close": px} - real prices at open+5/10/15 minutes
                    and the exit-day close when the bar collector has
                    them. Falls back to the open print (the morning-
                    fade edge concentrates in the first minutes; the
                    open is the honest floor).
    """
    intraday_first_bars = intraday_first_bars or {}
    entry = float(entry_close)
    op = float(next_open)
    gap = (op - entry) / entry * 100.0

    def _ret(px: float) -> float:
        return (px - entry) / entry * 100.0

    r5 = _ret(float(intraday_first_bars.get("r5", op)))
    r10 = _ret(float(intraday_first_bars.get("r10", op)))
    r15 = _ret(float(intraday_first_bars.get("r15", op)))
    close = float(intraday_first_bars.get("close", op))
    return {
        "gap_pct": gap,
        "r5": r5,
        "r10": r10,
        "r15": r15,
        "hold_to_close": _ret(close) if close else r15,
    }


def net_after_overnight(gross_pct: float, entry_price: float) -> float:
    """Gross overnight % -> net after the full round-trip cost stack."""
    exit_price = entry_price * (1 + gross_pct / 100.0)
    return net_pnl_pct(entry_price, exit_price)


# --- Walk-forward splitting ----------------------------------------------
def walk_forward_sessions(
    all_sessions: list[str],
    train_sessions: int = 60,
    test_sessions: int = 5,
    min_train: int = 20,
) -> list[tuple[list[str], list[str]]]:
    """Chronological expanding-window folds. No random splits, ever.

    Each fold trains on the first k sessions and tests the next
    test_sessions block; k grows by test_sessions each fold. A fold
    only exists when it has >= min_train sessions behind it.
    """
    sessions = sorted(all_sessions)
    folds: list[tuple[list[str], list[str]]] = []
    start = min_train
    while start + test_sessions <= len(sessions):
        train = sessions[:start]
        test = sessions[start:start + test_sessions]
        if len(train) >= min(train_sessions, min_train):
            folds.append((train, test))
        start += test_sessions
    return folds


def rank_top1(
    rows: list[dict],
    prob_by_symbol: dict[str, float],
    min_probability: float,
) -> tuple[dict | None, list[dict]]:
    """Rank all eligible rows by model probability; emit at most ONE
    signal - the top rank - and only when it clears the threshold.

    Returns (signal_or_None, full_ranked_list_for_the_log). Replaces
    every threshold-gating scheme: eligibility decides WHO may compete,
    probability decides WHO wins, and "no trade" is a full citizen.
    """
    ranked = sorted(
        (r for r in rows if r.get("symbol") in prob_by_symbol),
        key=lambda r: prob_by_symbol[r["symbol"]],
        reverse=True,
    )
    if not ranked:
        return None, []
    top = ranked[0]
    if prob_by_symbol[top["symbol"]] < min_probability:
        return None, ranked
    return top, ranked


# --- Signal log schema ----------------------------------------------------
@dataclass
class SignalRecord:
    bot: str                   # "sentinel" | "sentinel-eod"
    trading_date: str
    symbol: str
    signal_time_pkt: str
    entry_price: float
    features: dict = field(default_factory=dict)
    rank: int = 1
    probability: float | None = None
    score_components: dict = field(default_factory=dict)
    exit_price: float | None = None
    exit_time_pkt: str | None = None
    exit_reason: str | None = None   # tp|sl|timeout|eod|force|open+5
    gross_pct: float | None = None
    net_pct: float | None = None
    next_session_prices: dict = field(default_factory=dict)  # bot B: open+5/10/15

    def to_dict(self) -> dict:
        return {
            "bot": self.bot,
            "trading_date": self.trading_date,
            "symbol": self.symbol,
            "signal_time_pkt": self.signal_time_pkt,
            "entry_price": self.entry_price,
            "features": self.features,
            "rank": self.rank,
            "probability": self.probability,
            "score_components": self.score_components,
            "exit_price": self.exit_price,
            "exit_time_pkt": self.exit_time_pkt,
            "exit_reason": self.exit_reason,
            "gross_pct": self.gross_pct,
            "net_pct": self.net_pct,
            "next_session_prices": self.next_session_prices,
        }
