"""Outcome labeler: every ranked candidate, not only the traded one.

Owner order (self-improvement mission, item 2): after every close, label all
ranked candidates with what happened next under the mission's own costs
(22.4 bps per side, 10 bps slippage per side, 15 percent CGT on gains) and
the stop-first rule (one bar that touches both levels books the stop, the
pessimistic order).

The labeler is a pure function over a daily OHLCV panel and a table of
candidates, so the same code answers two callers:

  * the cloud's daily labeling step (the finalize job hands over one day's
    ranked table and the panel carries the bars that follow; this is a
    labeling step, not a backtest, so SO-4 does not bar it from the cheap
    cloud path);
  * the search loop (scripts/self_improve.py), which labels whole
    discovery/validation/test slices in one pass.

Nothing here sleeps, waits, or touches the network; a candidate with no
forward bar is labeled as no entry (its entry price does not exist yet) with
an honest reason, never a fabricated price (SO-3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from src.config import COST_SIDE_BPS, CGT_RATE, SLIPPAGE_SIDE_BPS

#: The mission's own cost figure, per side: the repo's fee schedule (22.4 bps)
#: plus the slippage the mission names (10 bps). Every label and every report
#: under these costs carries this exact number in its row.
MISSION_COST_SIDE_BPS = COST_SIDE_BPS + SLIPPAGE_SIDE_BPS

#: The label vocabulary. WIN means the candidate closes net positive after
#: ALL the mission's costs; LOSS means it does not; NO_ENTRY means the
#: candidate had no observable next price to enter at.
LABELS = ("WIN", "LOSS", "NO_ENTRY")


@dataclass(frozen=True)
class LabelParams:
    """One labeler configuration (the exits under which flavors are judged)."""

    tp: float = 0.02          # target above entry, mission grid varies this
    sl: float = 0.01          # stop below entry
    max_hold: int = 10        # bars; timeout at the close of bar max_hold
    cost_side_bps: float = MISSION_COST_SIDE_BPS
    cgt_rate: float = CGT_RATE
    invalid_band: float = 0.60  # same corporate-action screen as the engine

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "sl": self.sl, "max_hold": self.max_hold,
            "cost_side_bps": round(self.cost_side_bps, 4),
            "cgt_rate": self.cgt_rate,
            "round_trip_cost": round(2.0 * self.cost_side_bps / 10000.0, 6),
        }


def net_after_costs(gross: float, params: LabelParams) -> float:
    """The mission's net: round trip costs always on, CGT only on gains."""
    cost = 2.0 * params.cost_side_bps / 10000.0
    net = gross - cost
    if net > 0.0:
        net *= 1.0 - params.cgt_rate
    return net


def label_candidates(panel: pd.DataFrame,
                     candidates: pd.DataFrame,
                     params: LabelParams = LabelParams()) -> pd.DataFrame:
    """Label every candidate row under the mission's exits.

    panel: long OHLCV frame [symbol, date, open, high, low, close, volume].
    candidates: rows with at least [symbol, signal_date]; optional a score
    column rides through to the labels. The exit law is the engine's own:
    entry at the next bar's open after the signal date (never the signal
    bar's own print), stop-first on any bar that touches both levels, a
    stop whose open already gapped through fills at that open, a target
    fills AT its price even when the bar gapped past it, and a timeout at
    the close of bar ``max_hold``.
    """
    have_hl = {"high", "low"} <= set(panel.columns)
    by_symbol = {s: g.sort_values("date").reset_index(drop=True)
                 for s, g in panel.groupby("symbol", observed=True)}
    labels: list[dict] = []
    for row in candidates.itertuples(index=False):
        symbol = str(getattr(row, "symbol", ""))
        signal_date = getattr(row, "signal_date")
        label: dict = {
            "symbol": symbol, "signal_date": signal_date,
            "entry_basis": "next_open",
        }
        if "score" in candidates.columns:
            label["score"] = getattr(row, "score")
        group = by_symbol.get(symbol)
        if group is None or group.empty:
            label.update({"label": "NO_ENTRY", "reason": "symbol absent"})
            labels.append(label)
            continue
        later = group.index[group["date"] > signal_date]
        if len(later) == 0:
            label.update({"label": "NO_ENTRY", "reason": "no next bar"})
            labels.append(label)
            continue
        i0 = int(later[0])
        n = len(group)
        entry = float(group.at[i0, "open"])
        if not math.isfinite(entry) or entry <= 0:
            label.update({"label": "NO_ENTRY", "reason": "entry unreadable"})
            labels.append(label)
            continue
        tp_price = entry * (1.0 + params.tp)
        sl_price = entry * (1.0 - params.sl)
        end = min(i0 + params.max_hold, n)
        outcome, exit_price, exit_date, exit_idx, mae, mfe = (
            "TIMEOUT", None, None, None, 0.0, 0.0)
        for i in range(i0, end):
            high = float(group.at[i, "high"]) if have_hl else float(group.at[i, "close"])
            low = float(group.at[i, "low"]) if have_hl else float(group.at[i, "close"])
            mae = min(mae, low / entry - 1.0)
            mfe = max(mfe, high / entry - 1.0)
            touched_sl = low <= sl_price
            touched_tp = high >= tp_price
            if touched_sl and touched_tp:
                # Stop first, always: the pessimistic order is the law.
                exit_price = sl_price
                outcome, exit_date, exit_idx = "SL", group.at[i, "date"], i
                break
            if touched_tp:
                # The target is a limit: it books its own price even when
                # the bar gapped past it (never a better fill).
                exit_price = tp_price
                outcome, exit_date, exit_idx = "TP", group.at[i, "date"], i
                break
            if touched_sl:
                # Gap-through: a bar that OPENS below the stop fills at
                # that open (worse), like the engine does.
                open_price = float(group.at[i, "open"]) if have_hl else \
                    float(group.at[i, "close"])
                exit_price = open_price if open_price < sl_price else sl_price
                outcome, exit_date, exit_idx = "SL", group.at[i, "date"], i
                break
        if exit_price is None:
            exit_price = float(group.at[min(end, n) - 1, "close"])
            exit_date = group.at[min(end, n) - 1, "date"]
        gross = exit_price / entry - 1.0
        net = net_after_costs(gross, params)
        invalid = abs(gross) > params.invalid_band
        label.update({
            "entry": round(entry, 6), "exit": round(exit_price, 6),
            "exit_date": str(exit_date), "outcome": outcome,
            "gross_ret": round(gross, 6), "net_ret": round(net, 6),
            "label": "WIN" if net > 0 else "LOSS",
            "bars_held": (int(exit_idx - i0 + 1)
                         if exit_idx is not None else params.max_hold),
            "mae": round(mae, 6), "mfe": round(mfe, 6),
            "data_invalid": bool(invalid),
            "cost_side_bps": params.cost_side_bps,
        })
        labels.append(label)
    return pd.DataFrame(labels)


def label_summary(labels: pd.DataFrame) -> dict:
    """The mission's own scorecard for one labeled table (SO-3: counts, not
    impressions, and the no-entry bucket is named, never hidden)."""
    if labels is None or labels.empty:
        return {"n": 0}
    invalid = (labels["data_invalid"].astype(bool)
               if "data_invalid" in labels.columns
               else pd.Series(False, index=labels.index))
    # The scorecard's n counts CLOSED PAPER TRADES only (the rows the
    # engine actually entered, WIN or LOSS, cheap data excluded): a
    # NO_ENTRY row is a named gap in the accounting, not a session, so
    # it must not stand inside n or inside an average of returns it
    # does not carry (SO-3; caught by the all-NO_ENTRY KeyError).
    label = (labels["label"].astype(str) if "label" in labels.columns
             else pd.Series("", index=labels.index))
    trades = labels.loc[(label == "WIN") | (label == "LOSS")]
    valid = trades.loc[~invalid.reindex(trades.index, fill_value=False)]
    n = int(len(valid))
    wins = int((valid["label"] == "WIN").sum()) if n else 0
    losses = int((valid["label"] == "LOSS").sum()) if n else 0
    no_entry = int((label == "NO_ENTRY").sum())
    summary: dict = {
        "n": n, "wins": wins, "losses": losses, "no_entry": no_entry,
        "win_rate": round(wins / n, 4) if n else None,
        "net_expectancy": (round(float(valid["net_ret"].mean()), 6)
                           if n else None),
        "cost_side_bps": float(valid["cost_side_bps"].iloc[0])
        if n and "cost_side_bps" in valid else MISSION_COST_SIDE_BPS,
    }
    if n:
        rng = np.random.default_rng(0)
        boots = np.array([valid["net_ret"].sample(n, replace=True,
                                                 random_state=int(rng.integers(1 << 31)))
                          .mean() for _ in range(1000)])
        summary["bootstrap_lower_2.5"] = round(float(np.percentile(boots, 2.5)), 6)
    return summary
