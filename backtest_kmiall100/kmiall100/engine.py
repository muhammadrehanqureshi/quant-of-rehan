"""Long only trade simulator. Conservative on every ambiguous point.

Execution model
---------------
* The signal is known at the CLOSE of bar t. The order fills at the OPEN of bar
  t+1, plus slippage. A signal on the last bar is dropped. A next bar with zero
  volume is not tradable, so that signal is dropped too.
* Take profit is a limit order and fills exactly at its price, never better,
  even when price gaps over it.
* The stop fills at its price, or at the open when the bar opens already below
  it (a gap through the stop is worse and is booked as such).
* If one bar touches both the stop and the target, the stop wins.
* A trailing stop (when used) trails the highest high of the COMPLETED bars,
  so a bar cannot raise the stop and hit it in the same candle.
* Intraday data is flat by the last bar of the trading day unless the strategy
  is marked overnight. The time stop closes at the close of the last allowed bar.
* One position per symbol at a time: signals that arrive while a trade is open
  are ignored.
* Costs follow the repository law: 0.224 percent per side (commission, SST,
  levies) plus slippage per side, and 15 percent capital gains tax on a positive
  trade. They are applied to every trade in ``net_return``.

All of the work is in ``simulate``, a plain loop that numba compiles when it is
available (about 100 times faster, same answer).
"""

from __future__ import annotations

import numpy as np

from .ind import njit

OUT_TP, OUT_SL, OUT_TIME, OUT_EOD, OUT_SIG, OUT_GAP = 0, 1, 2, 3, 4, 5
OUT_NAMES = ["TP", "SL", "TIME", "EOD", "SIGNAL", "GAP_SL"]

COST_SIDE = 0.00224     # 22.4 bps per side, the repository's COST_SIDE_BPS
SLIP_SIDE = 0.0010      # 10 bps per side, the repository's SLIPPAGE_SIDE_BPS
CGT = 0.15


@njit(cache=True)
def simulate(o, h, l, c, v, eod, sig_idx, tp_f, sl_f, trail_f, max_hold, flat_eod, exit_sig, use_exit, slip):
    """Returns arrays: sig bar, entry bar, exit bar, entry px, exit px, outcome, mae, mfe."""
    n = len(c)
    m = len(sig_idx)
    r_sig = np.empty(m, dtype=np.int64)
    r_en = np.empty(m, dtype=np.int64)
    r_ex = np.empty(m, dtype=np.int64)
    r_epx = np.empty(m)
    r_xpx = np.empty(m)
    r_out = np.empty(m, dtype=np.int64)
    r_mae = np.empty(m)
    r_mfe = np.empty(m)
    k = 0
    free_from = 0                      # a signal at bar i is allowed when i >= free_from
    for q in range(m):
        i = sig_idx[q]
        if i < free_from:
            continue
        e = i + 1
        if e >= n:
            continue
        if v[e] <= 0.0:
            continue
        ep = o[e] * (1.0 + slip)
        tp = ep * (1.0 + tp_f[q])
        sl = ep * (1.0 - sl_f[q])
        tr = trail_f[q]
        hh = ep
        last = min(e + max_hold - 1, n - 1)
        xpx = c[last]
        xbar = last
        out = OUT_TIME
        mae = 0.0
        mfe = 0.0
        j = e
        while j <= last:
            stop = sl
            if tr > 0.0:
                ts_ = hh * (1.0 - tr)
                if ts_ > stop:
                    stop = ts_
            if j > e and o[j] <= stop:                   # gapped through the stop
                xpx, xbar, out = o[j], j, OUT_GAP
                break
            if l[j] <= stop:
                xpx, xbar, out = stop, j, OUT_SL
                break
            if h[j] >= tp:
                xpx, xbar, out = tp, j, OUT_TP
                break
            if h[j] / ep - 1.0 > mfe:
                mfe = h[j] / ep - 1.0
            if l[j] / ep - 1.0 < mae:
                mae = l[j] / ep - 1.0
            if h[j] > hh:
                hh = h[j]
            if flat_eod and eod[j]:
                xpx, xbar, out = c[j], j, OUT_EOD
                break
            if use_exit and exit_sig[j]:
                if j + 1 <= last:
                    xpx, xbar, out = o[j + 1] * (1.0 - slip), j + 1, OUT_SIG
                else:
                    xpx, xbar, out = c[j], j, OUT_SIG
                break
            j += 1
        if out != OUT_TP and out != OUT_SIG:      # the limit order fills clean, everything else pays slippage
            xpx = xpx * (1.0 - slip)
        r_sig[k], r_en[k], r_ex[k] = i, e, xbar
        r_epx[k], r_xpx[k], r_out[k] = ep, xpx, out
        r_mae[k], r_mfe[k] = mae, mfe
        k += 1
        free_from = xbar               # next signal may fire on the exit bar's close or later
    return r_sig[:k], r_en[:k], r_ex[:k], r_epx[:k], r_xpx[:k], r_out[:k], r_mae[:k], r_mfe[:k]


def net_returns(entry_px, exit_px, cost_side=COST_SIDE, cgt=CGT):
    """Gross and net trade returns. Slippage is already inside the prices."""
    gross = exit_px / entry_px - 1.0
    net = gross - 2.0 * cost_side
    net = np.where(net > 0.0, net * (1.0 - cgt), net)
    return gross, net


def jump_mask(c, band=0.35, pad=60):
    """Bars near a price jump bigger than any PSX circuit band (unadjusted split or bad print)."""
    r = np.abs(c[1:] / c[:-1] - 1.0)
    bad = np.zeros(len(c), dtype=bool)
    idx = np.flatnonzero(r > band) + 1
    for k in idx:
        bad[max(0, k - pad): k + pad] = True
    return bad
