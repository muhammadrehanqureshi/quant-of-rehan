"""Daily-bar backtest engine for the owner's TP/SL law.

Owner's universal law (from the sentinel's intraday feasibility study):
    TP +2.0% / SL -1.0%, reward:risk 2:1, long-only, signal-only.

Execution model (conservative by construction):
- Signal decided at close of day T -> entry at the OPEN of the next bar
  for that symbol. If no next bar exists, the signal is skipped (no
  look-ahead, ever).
- TP is a limit order: always fills at exactly tp_price, even if price
  gapped above it (conservative — never books a better fill).
- SL fills at sl_price, EXCEPT gap-throughs: if a bar's open is already
  below the stop, the fill is at that open (worse — conservative).
- If both TP and SL are touchable in the same bar, SL wins (pessimistic
  ordering). In close mode "touchable" means the close crossed the level;
  in hl mode it means high/low touched it.
- Max holding: position force-closed at the close of bar `max_hold`.

Cost model (owner's real fee schedule, from the sentinel overnight study):
    commission 0.15%/side + SST 16% of commission + levies 0.05%/side
    => cost_side_bps default 22.4 (0.224% per side).
    CGT 15% applied to positive net per-trade returns (configurable).

DPS timeseries has NO high/low. touch_mode:
    "close" — TP/SL evaluated on closes only (works with DPS data).
    "hl"    — requires high/low columns; sharper but only for future data.
    "auto"  — use hl if columns present, else close. Reports state the mode.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pandas as pd

DEFAULT_COST_SIDE_BPS = 22.4  # 0.15% commission + 16% SST + 0.05% levies
DEFAULT_CGT_RATE = 0.15


@dataclass
class Trade:
    symbol: str
    signal_date: object
    entry_date: object
    entry: float
    exit_date: object
    exit: float
    bars_held: int
    outcome: str          # "TP" | "SL" | "TIMEOUT"
    gross_ret: float
    net_ret: float
    touch_mode: str
    mae: float            # worst adverse excursion vs entry (<= 0)
    mfe: float            # best favorable excursion vs entry (>= 0)


def run_backtest(
    df: pd.DataFrame,
    signals: Iterable[tuple],
    tp: float = 0.02,
    sl: float = 0.01,
    max_hold: int = 3,
    cost_side_bps: float = DEFAULT_COST_SIDE_BPS,
    cgt_rate: float = DEFAULT_CGT_RATE,
    touch_mode: str = "auto",
) -> tuple[pd.DataFrame, dict]:
    """Simulate long trades for every (signal_date, symbol) pair.

    df must be a long frame with columns [symbol, date, open, close] and
    optionally [high, low], sorted by (symbol, date). Signals are decided
    at the close of signal_date; entry is the next bar's open.
    """
    have_hl = {"high", "low"} <= set(df.columns)
    if touch_mode == "auto":
        mode = "hl" if have_hl else "close"
    else:
        mode = touch_mode
        if mode == "hl" and not have_hl:
            raise ValueError("touch_mode='hl' requires high/low columns")

    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    by_symbol = {s: g.reset_index(drop=True) for s, g in df.groupby("symbol", sort=False)}

    trades: list[Trade] = []
    skipped = 0

    for signal_date, symbol in signals:
        g = by_symbol.get(symbol)
        if g is None or g.empty:
            skipped += 1
            continue
        # next bar strictly after the signal date (no look-ahead)
        later = g.index[g["date"] > signal_date]
        if len(later) == 0:
            skipped += 1
            continue
        i0 = later[0]
        n = len(g)
        end = min(i0 + max_hold, n)

        entry = float(g.at[i0, "open"])
        if not math.isfinite(entry) or entry <= 0:
            skipped += 1
            continue
        tp_price = entry * (1.0 + tp)
        sl_price = entry * (1.0 - sl)

        exit_price: Optional[float] = None
        outcome = "TIMEOUT"
        exit_date = None
        exit_idx = end - 1
        mae = 0.0
        mfe = 0.0

        for i in range(i0, end):
            o = float(g.at[i, "open"])
            c = float(g.at[i, "close"])
            if mode == "hl":
                hi = float(g.at[i, "high"])
                lo = float(g.at[i, "low"])
                mae = min(mae, (lo - entry) / entry)
                mfe = max(mfe, (hi - entry) / entry)
            else:
                mae = min(mae, (c - entry) / entry)
                mfe = max(mfe, (c - entry) / entry)

            # stop first — pessimistic ordering, every bar
            stop_hit, tp_hit = False, False
            if mode == "hl":
                stop_hit = lo <= sl_price
                tp_hit = hi >= tp_price
            else:
                stop_hit = c <= sl_price
                tp_hit = c >= tp_price

            if stop_hit:
                if mode == "hl":
                    # gap-through fills at the open (worse), else at sl_price
                    exit_price = o if o < sl_price else sl_price
                else:
                    # close mode: no low is known; the worst KNOWN price is
                    # the close that pierced the stop (a stop-market would
                    # have filled near it or worse). Filling at sl_price
                    # here would be optimistic.
                    exit_price = o if o < sl_price else c
                outcome = "SL"
                exit_idx = i
                break
            if tp_hit:
                # limit order: exact tp fill, never better (conservative)
                exit_price = tp_price
                outcome = "TP"
                exit_idx = i
                break

        if exit_price is None:
            exit_price = float(g.at[exit_idx, "close"])
            exit_date = g.at[exit_idx, "date"]

        bars_held = exit_idx - i0 + 1
        gross = exit_price / entry - 1.0
        costs = 2.0 * cost_side_bps / 1e4
        net = gross - costs
        if net > 0 and cgt_rate > 0:
            net = net * (1.0 - cgt_rate)

        trades.append(Trade(
            symbol=symbol,
            signal_date=signal_date,
            entry_date=g.at[i0, "date"],
            entry=entry,
            exit_date=exit_date if exit_date is not None else g.at[exit_idx, "date"],
            exit=exit_price,
            bars_held=bars_held,
            outcome=outcome,
            gross_ret=gross,
            net_ret=net,
            touch_mode=mode,
            mae=mae,
            mfe=mfe,
        ))

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    summary = summarize(trades_df, skipped=skipped, touch_mode=mode,
                        tp=tp, sl=sl, max_hold=max_hold)
    return trades_df, summary


def summarize(trades_df: pd.DataFrame, *, skipped: int, touch_mode: str,
              tp: float, sl: float, max_hold: int) -> dict:
    n = len(trades_df)
    out = {
        "n_trades": n,
        "n_signals_skipped": skipped,
        "touch_mode": touch_mode,
        "tp": tp, "sl": sl, "max_hold": max_hold,
    }
    if n == 0:
        out["note"] = "NO TRADES — engine validated on zero fills only"
        return out

    net = trades_df["net_ret"]
    wins = net[net > 0]
    losses = net[net <= 0]
    gross_w = trades_df.loc[trades_df["gross_ret"] > 0, "gross_ret"].sum()
    gross_l = -trades_df.loc[trades_df["gross_ret"] <= 0, "gross_ret"].sum()

    equity = (1.0 + net).cumprod()
    peak = equity.cummax()
    out.update({
        "win_rate": float((net > 0).mean()),
        "tp_rate": float((trades_df["outcome"] == "TP").mean()),
        "sl_rate": float((trades_df["outcome"] == "SL").mean()),
        "timeout_rate": float((trades_df["outcome"] == "TIMEOUT").mean()),
        "expectancy_net": float(net.mean()),
        "median_net": float(net.median()),
        "avg_win_net": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_net": float(losses.mean()) if len(losses) else 0.0,
        "median_win_net": float(wins.median()) if len(wins) else 0.0,
        "median_loss_net": float(losses.median()) if len(losses) else 0.0,
        "profit_factor_gross": float(gross_w / gross_l) if gross_l > 0 else float("inf"),
        "max_drawdown": float((1.0 - equity / peak).max()),
        "avg_bars_held": float(trades_df["bars_held"].mean()),
        "mae_p95": float(trades_df["mae"].quantile(0.95)),
        "mfe_p95": float(trades_df["mfe"].quantile(0.95)),
        "n_symbols": int(trades_df["symbol"].nunique()),
    })
    return out
