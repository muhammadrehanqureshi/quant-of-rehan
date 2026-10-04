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
DEFAULT_INVALID_BAND = 0.60   # adjacent-print |move| (open-vs-prior-close,
                              # close-vs-open, close-vs-prior-close) beyond
                              # ANY PSX circuit band; near-certain unadjusted
                              # corporate action (e.g. 10:1 par
                              # reconstruction) or corrupt column —
                              # data-invalid


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
    data_invalid: bool = False  # unadjusted corp action / corrupt print


def run_backtest(
    df: pd.DataFrame,
    signals: Iterable[tuple],
    tp: float = 0.02,
    sl: float = 0.01,
    max_hold: int = 3,
    cost_side_bps: float = DEFAULT_COST_SIDE_BPS,
    cgt_rate: float = DEFAULT_CGT_RATE,
    touch_mode: str = "auto",
    invalid_band: float = DEFAULT_INVALID_BAND,
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

        # prior print for the data-quality screen: the bar before entry
        # (normally the signal-day close) starts the print chain
        prev_print: Optional[float] = None
        if i0 > 0:
            pc = float(g.at[i0 - 1, "close"])
            if math.isfinite(pc) and pc > 0:
                prev_print = pc
        worst_bar_ret = 0.0

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

            # worst SINGLE-BAR print-to-print move while held: overnight
            # (open vs prior close), intra-session (close vs open) and the
            # session total (close vs prior close). A chain of two legal
            # max-band prints cannot occur on real PSX data (bands anchor
            # to the same base price), so the direct close-vs-prior-close
            # term is checked too.
            start_ref = prev_print
            for p in (o, c):
                if prev_print is not None and math.isfinite(p) and p > 0:
                    worst_bar_ret = max(worst_bar_ret, abs(p / prev_print - 1.0))
                prev_print = p if math.isfinite(p) and p > 0 else None
            if start_ref is not None and math.isfinite(c) and c > 0:
                worst_bar_ret = max(worst_bar_ret, abs(c / start_ref - 1.0))

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

        # Data-quality screen: any adjacent-print move beyond any PSX
        # circuit band is not a tradable loss/gain — it is an unadjusted
        # corporate action (10:1 par reconstruction, e.g. an open column
        # left 10x the close column) or a corrupt print. Worst single
        # print pair, NOT a per-bar average: a slow -90% bleed spread over
        # 3 bars of legal prints is a REAL (untradeable-in-hindsight but
        # genuine) loss and must be booked; only band-breaking prints are
        # fake. Flag it, keep it in the record for audit, exclude it from
        # metrics (SO-3: never book fake data as results).
        data_invalid = worst_bar_ret > invalid_band or not math.isfinite(gross)

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
            net_ret=0.0 if data_invalid else net,
            touch_mode=mode,
            mae=mae,
            mfe=mfe,
            data_invalid=data_invalid,
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

    if "data_invalid" in trades_df.columns:
        invalid_mask = trades_df["data_invalid"].astype(bool)
        out["n_data_invalid"] = int(invalid_mask.sum())
        valid = trades_df.loc[~invalid_mask]
    else:
        invalid_mask = pd.Series(False, index=trades_df.index)
        valid = trades_df
    if len(valid) == 0:
        out["note"] = "ALL TRADES DATA-INVALID — no metrics without honest data"
        return out

    net = valid["net_ret"]
    wins = net[net > 0]
    losses = net[net <= 0]
    gross_w = valid.loc[valid["gross_ret"] > 0, "gross_ret"].sum()
    gross_l = -valid.loc[valid["gross_ret"] <= 0, "gross_ret"].sum()

    # Equity curve must be CHRONOLOGICAL. Trades arrive symbol-ordered;
    # compounding that order chains losses across unrelated symbols and
    # fakes a 100% drawdown. Realized-equity convention: mark each trade
    # at its exit_date, start capital 1.0 in front so an early losing
    # streak is not invisible to the drawdown.
    chrono = valid.sort_values("exit_date", kind="mergesort")
    eq = (1.0 + chrono["net_ret"]).cumprod().reset_index(drop=True)
    equity = pd.concat([pd.Series([1.0]), eq], ignore_index=True)
    peak = equity.cummax()
    out.update({
        "win_rate": float((net > 0).mean()),
        "tp_rate": float((valid["outcome"] == "TP").mean()),
        "sl_rate": float((valid["outcome"] == "SL").mean()),
        "timeout_rate": float((valid["outcome"] == "TIMEOUT").mean()),
        "expectancy_net": float(net.mean()),
        "median_net": float(net.median()),
        "avg_win_net": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_net": float(losses.mean()) if len(losses) else 0.0,
        "median_win_net": float(wins.median()) if len(wins) else 0.0,
        "median_loss_net": float(losses.median()) if len(losses) else 0.0,
        "profit_factor_gross": float(gross_w / gross_l) if gross_l > 0 else float("inf"),
        "final_equity": float(equity.iloc[-1]),   # interpret drawdown 1.0:
                                                  # a deeply negative baseline
                                                  # compounds to ~0 honestly
        "max_drawdown": float((1.0 - equity / peak).max()),
        "avg_bars_held": float(valid["bars_held"].mean()),
        "mae_p95": float(valid["mae"].quantile(0.95)),
        "mfe_p95": float(valid["mfe"].quantile(0.95)),
        "n_symbols": int(valid["symbol"].nunique()),
    })
    return out
