"""Turn a pile of trades into the numbers that decide whether a strategy lives.

Everything here is computed on NET trade returns (after costs, slippage and the
15 percent capital gains tax on winners), in percent of the entry price.

Besides the usual win rate and expectancy it reports what matters for QoR's own
rule, one winning signal a day with +2 percent target and -1 percent stop:

* ``daily_*``: take only the FIRST signal of each trading day across the whole
  universe (what a "one call a day" bot would actually have sent) and score that;
* ``days_signal_pct``: the share of trading days that had at least one signal;
* an in sample versus out of sample split (first 60 percent of the calendar span
  against the last 40 percent), the share of calendar years that were positive,
  and a t statistic of the mean net return.

With 100 strategies on 5 timeframes and 3 exits there are 1,500 tests, and the
best of 1,500 random tests looks good by luck. ``t_stat >= 3`` is the hurdle
that survives that, and ``rank_score`` (the weaker of the two halves) is what
the leaderboard sorts by.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np

FIELDS = ["n", "symbols", "win_rate", "be_win_rate", "avg_win", "avg_loss", "payoff", "exp_net", "profit_factor",
          "t_stat", "sum_net", "max_dd", "avg_bars", "tp_rate", "sl_rate", "time_rate", "trades_per_day",
          "is_n", "is_exp", "is_t", "oos_n", "oos_exp", "oos_t", "years", "years_pos", "rank_score",
          "days_signal_pct", "daily_n", "daily_win_rate", "daily_exp", "daily_tp_rate", "passes"]


def wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return float("nan")
    p = wins / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d


def _t(x: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    sd = x.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float(x.mean() / (sd / math.sqrt(len(x))))


def summarize(ts: np.ndarray, sym: np.ndarray, net: np.ndarray, outcome: np.ndarray, bars: np.ndarray,
              n_trading_days: int, min_trades: int = 100) -> Dict[str, float]:
    """ts: entry time int64 ns, net: fractional net return per trade."""
    out: Dict[str, float] = {k: float("nan") for k in FIELDS}
    n = len(net)
    out["n"] = n
    out["passes"] = 0
    if n == 0:
        return out
    order = np.argsort(ts, kind="stable")
    ts, sym, net, outcome, bars = ts[order], sym[order], net[order], outcome[order], bars[order]
    pct = net * 100.0
    win = net > 0
    wins, losses = pct[win], -pct[~win]
    out["symbols"] = len(np.unique(sym))
    out["win_rate"] = float(win.mean() * 100)
    out["avg_win"] = float(wins.mean()) if len(wins) else 0.0
    out["avg_loss"] = float(losses.mean()) if len(losses) else 0.0
    out["payoff"] = out["avg_win"] / out["avg_loss"] if out["avg_loss"] > 0 else float("nan")
    out["be_win_rate"] = float(out["avg_loss"] / (out["avg_win"] + out["avg_loss"]) * 100) if (out["avg_win"] + out["avg_loss"]) > 0 else float("nan")
    out["exp_net"] = float(pct.mean())
    out["profit_factor"] = float(wins.sum() / losses.sum()) if losses.sum() > 0 else float("inf")
    out["t_stat"] = _t(pct)
    out["sum_net"] = float(pct.sum())
    eq = np.cumsum(pct)
    out["max_dd"] = float((np.maximum.accumulate(eq) - eq).max()) if n else 0.0
    out["avg_bars"] = float(bars.mean())
    out["tp_rate"] = float((outcome == 0).mean() * 100)
    out["sl_rate"] = float(((outcome == 1) | (outcome == 5)).mean() * 100)
    out["time_rate"] = float(((outcome == 2) | (outcome == 3) | (outcome == 4)).mean() * 100)
    out["trades_per_day"] = float(n / max(1, n_trading_days))
    # calendar split
    t0, t1 = ts[0], ts[-1]
    cut = t0 + int((t1 - t0) * 0.6)
    a, b = pct[ts <= cut], pct[ts > cut]
    out["is_n"], out["oos_n"] = len(a), len(b)
    out["is_exp"] = float(a.mean()) if len(a) else float("nan")
    out["oos_exp"] = float(b.mean()) if len(b) else float("nan")
    out["is_t"], out["oos_t"] = _t(a), _t(b)
    yr = ts.astype("datetime64[ns]").astype("datetime64[Y]").astype(int) + 1970
    ys = [y for y in np.unique(yr) if (yr == y).sum() >= 20]
    out["years"] = len(ys)
    out["years_pos"] = float(np.mean([pct[yr == y].mean() > 0 for y in ys])) if ys else float("nan")
    lo = min(out["is_t"], out["oos_t"])
    out["rank_score"] = float(lo) if not math.isnan(lo) else float("-inf")
    # one signal a day: first trade of each trading day, across all symbols
    day = ts.astype("datetime64[ns]").astype("datetime64[D]").astype(int)
    _, first = np.unique(day, return_index=True)
    dn = pct[first]
    out["daily_n"] = len(dn)
    out["days_signal_pct"] = float(len(dn) / max(1, n_trading_days) * 100)
    out["daily_win_rate"] = float((dn > 0).mean() * 100)
    out["daily_exp"] = float(dn.mean())
    out["daily_tp_rate"] = float((outcome[first] == 0).mean() * 100)
    ok = (n >= min_trades and out["exp_net"] > 0 and out["oos_exp"] > 0 and out["is_exp"] > 0
          and out["years_pos"] >= 0.6 and out["t_stat"] >= 3.0)
    out["passes"] = int(ok)
    return out
