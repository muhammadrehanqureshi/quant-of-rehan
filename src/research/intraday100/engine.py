"""Causal one-trade-per-day intraday simulator.

The simulation law:

* a signal is observed only when its bar closes;
* the entry is the next bar's open, and that bar must be in the same PSX
  session band;
* a stop is checked before a target on the same bar;
* a position is closed by the band close at the latest, so nothing is held
  through the Friday break or overnight;
* at most one trade is opened on any Karachi session day.

The portfolio uses a fixed PKR 10,000,000 baseline and PKR 1,000,000
(10 percent) of notional per trade. There is no compounding and no
overlapping position, so the same capital is never spent twice.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.data.sessions import KARACHI
from src.research.intraday100 import CGT_RATE, COST_SIDE_BPS, SPREAD_SIDE_BPS


@dataclass(frozen=True)
class ExitRule:
    target_atr: float = 1.5
    stop_atr: float = 1.0
    max_hold_bars: int = 12
    # A target below the round-trip cost is not a trade; it is a guaranteed
    # net loss. These floors are deliberately above the 0.748 percent
    # baseline cost, and the gap and liquidity screens below are mandatory.
    target_min: float = 0.015
    target_max: float = 0.040
    stop_min: float = 0.008
    stop_max: float = 0.020


def _exit_pct(value: float, low: float, high: float) -> float:
    if not np.isfinite(value):
        return np.nan
    return float(min(high, max(low, value)))


def simulate_strategy(
    df: pd.DataFrame,
    mask: pd.Series | np.ndarray,
    score: pd.Series | np.ndarray,
    strategy_id: str,
    rule: ExitRule,
    *,
    capital: float = 10_000_000.0,
    trade_fraction: float = 0.10,
    cost_side_bps: float = COST_SIDE_BPS,
    spread_side_bps: float = SPREAD_SIDE_BPS,
    bar_seconds: int = 300,
    min_turnover_pkr: float = 1_000_000.0,
    max_open_gap: float = 0.15,
) -> pd.DataFrame:
    """Simulate one strategy and return its trade ledger."""
    signal = np.asarray(mask, dtype=bool)
    if signal.shape[0] != len(df):
        raise ValueError("signal mask is not aligned with the bar frame")
    scores = np.asarray(score, dtype=np.float64)
    if scores.shape[0] != len(df):
        raise ValueError("score is not aligned with the bar frame")
    scores = np.nan_to_num(scores, nan=-np.inf, posinf=np.inf, neginf=-np.inf)

    valid = df["valid_bar"].to_numpy(dtype=bool) & signal
    if not valid.any():
        return pd.DataFrame()

    symbols = df["symbol"].to_numpy()
    ts = df["ts"].to_numpy(dtype=np.int64)
    open_ = df["open"].to_numpy(dtype=np.float64)
    high = df["high"].to_numpy(dtype=np.float64)
    low = df["low"].to_numpy(dtype=np.float64)
    close = df["close"].to_numpy(dtype=np.float64)
    band_key = df["band_key"].to_numpy(dtype=np.int64)
    band_end = df["band_end"].to_numpy(dtype=np.int64)
    day_ord = df["day_ord"].to_numpy(dtype=np.int64)
    atr_pct = df["atr_pct"].to_numpy(dtype=np.float64)
    volume = df["volume"].to_numpy(dtype=np.float64)
    median_turnover = df["median_turnover20"].to_numpy(dtype=np.float64)
    prev_close = df["prev_close"].to_numpy(dtype=np.float64)

    positions = np.flatnonzero(valid)
    candidates = pd.DataFrame({
        "pos": positions,
        "symbol": symbols[positions],
        "ts": ts[positions],
        "day": day_ord[positions],
        "score": scores[positions],
    })
    candidates = candidates.replace([np.inf, -np.inf], np.nan).dropna(subset=["score"])
    if candidates.empty:
        return pd.DataFrame()

    # One pass over the frame, not one scan of the whole frame per symbol.
    grouped_positions = df.groupby("symbol", sort=False).indices
    symbol_positions = {
        str(symbol): np.asarray(positions, dtype=np.int64)
        for symbol, positions in grouped_positions.items()
    }

    round_trip_cost = 2.0 * (cost_side_bps + spread_side_bps) / 10_000.0
    records: list[dict[str, Any]] = []

    for day, day_frame in candidates.groupby("day", sort=True):
        # The first signal of the day is the only one that may be acted on.
        # At one timestamp, the strategy's own ranking chooses one symbol.
        day_frame = day_frame.sort_values(["ts", "score"], ascending=[True, False])
        day_frame = day_frame.drop_duplicates("ts", keep="first")
        for row in day_frame.itertuples(index=False):
            i = int(row.pos)
            symbol = str(row.symbol)
            symbol_index = symbol_positions[symbol]
            next_at = int(np.searchsorted(symbol_index, i, side="right"))
            if next_at >= len(symbol_index):
                continue
            j = int(symbol_index[next_at])
            if band_key[j] != band_key[i]:
                continue
            if ts[j] + bar_seconds > band_end[j]:
                continue
            if not np.isfinite(open_[j]) or open_[j] <= 0 or not np.isfinite(atr_pct[i]):
                continue
            # Liquidity and unadjusted-gap screens. Both use information
            # observable at the signal close or at the entry open, never the
            # entry bar's completed volume.
            if volume[i] <= 0 or not np.isfinite(median_turnover[i]):
                continue
            if median_turnover[i] < min_turnover_pkr:
                continue
            if (np.isfinite(prev_close[j]) and prev_close[j] > 0
                    and abs(open_[j] / prev_close[j] - 1.0) > max_open_gap):
                continue

            entry = float(open_[j])
            target_pct = _exit_pct(rule.target_atr * float(atr_pct[i]),
                                   rule.target_min, rule.target_max)
            stop_pct = _exit_pct(rule.stop_atr * float(atr_pct[i]),
                                 rule.stop_min, rule.stop_max)
            if not np.isfinite(target_pct) or not np.isfinite(stop_pct):
                continue
            target = entry * (1.0 + target_pct)
            stop = entry * (1.0 - stop_pct)

            exit_price: float | None = None
            exit_reason = ""
            exit_pos = j
            last_pos = j
            for k in range(j, len(df)):
                if (symbols[k] != symbol
                        or band_key[k] != band_key[j]
                        or ts[k] + bar_seconds > band_end[j]):
                    break
                last_pos = k
                if k == j:
                    if low[k] <= stop:
                        exit_price, exit_reason, exit_pos = stop, "stop", k
                        break
                    if high[k] >= target:
                        exit_price, exit_reason, exit_pos = target, "target", k
                        break
                else:
                    if open_[k] <= stop:
                        exit_price, exit_reason, exit_pos = float(open_[k]), "stop", k
                        break
                    if open_[k] >= target:
                        exit_price, exit_reason, exit_pos = target, "target", k
                        break
                    if low[k] <= stop:
                        exit_price, exit_reason, exit_pos = stop, "stop", k
                        break
                    if high[k] >= target:
                        exit_price, exit_reason, exit_pos = target, "target", k
                        break
                if k - j + 1 >= rule.max_hold_bars:
                    exit_price, exit_reason, exit_pos = float(close[k]), "max_hold", k
                    break

            if exit_price is None:
                exit_price, exit_reason, exit_pos = float(close[last_pos]), "session", last_pos
            if not np.isfinite(exit_price):
                continue

            gross = exit_price / entry - 1.0
            net_before_tax = gross - round_trip_cost
            tax = CGT_RATE * net_before_tax if net_before_tax > 0 else 0.0
            net = net_before_tax - tax
            pnl = capital * trade_fraction * net
            records.append({
                "strategy_id": strategy_id,
                "symbol": symbol,
                "signal_ts": int(ts[i]),
                "entry_ts": int(ts[j]),
                "exit_ts": int(ts[exit_pos]),
                "entry_price": entry,
                "exit_price": float(exit_price),
                "gross_return": float(gross),
                "net_return": float(net),
                "pnl_pkr": float(pnl),
                "notional_pkr": float(capital * trade_fraction),
                "target_pct": float(target_pct),
                "stop_pct": float(stop_pct),
                "exit_reason": exit_reason,
                "hold_bars": int(exit_pos - j + 1),
                "atr_pct": float(atr_pct[i]),
                "score": float(row.score),
                "entry_year": datetime.fromtimestamp(int(ts[j]), tz=KARACHI).year,
            })
            break

    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values("entry_ts").reset_index(drop=True)


def _breakdown(trades: pd.DataFrame, key: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for value, frame in trades.groupby(key, sort=True):
        rows.append({
            key: str(value),
            "trades": int(len(frame)),
            "net_pnl_pkr": float(frame["pnl_pkr"].sum()),
            "expectancy_pct": float(frame["net_return"].mean() * 100.0),
            "win_rate_pct": float((frame["net_return"] > 0).mean() * 100.0),
        })
    return rows


def summarize_trades(
    trades: pd.DataFrame,
    strategy_id: str,
    *,
    capital: float = 10_000_000.0,
    trade_fraction: float = 0.10,
) -> dict[str, Any]:
    """All required performance measures for one strategy ledger."""
    if trades is None or trades.empty:
        return {
            "strategy_id": strategy_id,
            "trades": 0,
            "status": "no_trades",
            "capital_pkr": capital,
            "notional_per_trade_pkr": capital * trade_fraction,
        }

    t = trades.sort_values("exit_ts").copy()
    pnl = t["pnl_pkr"].to_numpy(dtype=np.float64)
    net = t["net_return"].to_numpy(dtype=np.float64)
    wins = net[net > 0]
    losses = net[net < 0]
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float(pnl[pnl < 0].sum())
    equity = capital + np.cumsum(pnl)
    running_max = np.maximum.accumulate(np.r_[capital, equity])
    drawdown = (np.r_[capital, equity] - running_max) / running_max
    max_dd = float(drawdown.min())
    daily = t.assign(day=pd.to_datetime(t["exit_ts"], unit="s", utc=True)
                     .dt.tz_convert(KARACHI).dt.date)
    daily_pnl = daily.groupby("day")["pnl_pkr"].sum()
    daily_ret = daily_pnl / capital
    daily_std = float(daily_ret.std(ddof=1)) if len(daily_ret) > 1 else 0.0
    downside = daily_ret[daily_ret < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sharpe = float(daily_ret.mean() / daily_std * np.sqrt(252)) if daily_std > 0 else 0.0
    sortino = float(daily_ret.mean() / downside_std * np.sqrt(252)) if downside_std > 0 else 0.0
    total_return = float(pnl.sum() / capital)
    max_dd_abs = abs(max_dd)
    calmar = float(total_return / max_dd_abs) if max_dd_abs > 0 else 0.0

    return {
        "strategy_id": strategy_id,
        "status": "ok",
        "capital_pkr": float(capital),
        "notional_per_trade_pkr": float(capital * trade_fraction),
        "trades": int(len(t)),
        "symbols": int(t["symbol"].nunique()),
        "gross_profit_pkr": gross_profit,
        "gross_loss_pkr": gross_loss,
        "net_profit_pkr": float(pnl.sum()),
        "net_return_pct": total_return * 100.0,
        "profit_factor": (gross_profit / abs(gross_loss)) if gross_loss < 0 else None,
        "expectancy_pct": float(net.mean() * 100.0),
        "avg_win_pct": float(wins.mean() * 100.0) if wins.size else 0.0,
        "avg_loss_pct": float(losses.mean() * 100.0) if losses.size else 0.0,
        "avg_reward_risk": (float(wins.mean() / abs(losses.mean()))
                            if wins.size and losses.size else None),
        "win_rate_pct": float((net > 0).mean() * 100.0),
        "loss_rate_pct": float((net < 0).mean() * 100.0),
        "avg_hold_bars": float(t["hold_bars"].mean()),
        "max_drawdown_pct": max_dd * 100.0,
        "max_daily_drawdown_pct": float(daily_ret.min() * 100.0),
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "worst_trade_pct": float(net.min() * 100.0),
        "longest_losing_streak": _losing_streak(net),
        "target_exit_rate_pct": float((t["exit_reason"] == "target").mean() * 100.0),
        "stop_exit_rate_pct": float((t["exit_reason"] == "stop").mean() * 100.0),
        "time_exit_rate_pct": float(t["exit_reason"].isin(["max_hold", "session"]).mean() * 100.0),
        "trades_per_year": _trades_per_year(t),
        "yearly": _breakdown(t, "entry_year"),
        "by_symbol": _breakdown(t, "symbol"),
        "exit_mix": {str(k): int(v) for k, v in t["exit_reason"].value_counts().items()},
    }


def _losing_streak(net: np.ndarray) -> int:
    longest = 0
    current = 0
    for value in net:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _trades_per_year(trades: pd.DataFrame) -> float:
    years = trades["entry_year"].nunique()
    return float(len(trades) / years) if years else 0.0
