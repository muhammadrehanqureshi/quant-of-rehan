"""Indicator library: plain numpy and pandas, one value per bar, no look-ahead.

Every function here uses only bars at or before the bar it reports. The only way
to look at an earlier bar is ``shift(x, k)`` with k >= 0, and negative k is
refused outright, so a future bar cannot leak into a signal by accident.
Warm-up bars are NaN, and any comparison with NaN is False.

The few recursive indicators (Supertrend, Parabolic SAR, Kalman, Heikin Ashi,
Schaff, streaks) are plain loops. They are compiled with numba when it is
installed (the GitHub workflow installs it) and run as ordinary Python when it
is not, with identical results.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

try:  # optional speed up
    from numba import njit
    HAVE_NUMBA = True
except Exception:  # pragma: no cover
    HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda f: f

NAN = np.nan


# ---------------------------------------------------------------- basics
def shift(x: np.ndarray, k: int = 1) -> np.ndarray:
    """Value k bars ago. k must be >= 0, so a signal can never see the future."""
    if k < 0:
        raise ValueError("negative shift would look into the future")
    out = np.full(x.shape, np.nan)
    if k == 0:
        out[:] = x
    elif k < len(x):
        out[k:] = x[:-k]
    return out


def _s(x):
    return pd.Series(x)


def sma(x, n):
    return _s(x).rolling(n, min_periods=n).mean().to_numpy(copy=True)


def rstd(x, n):
    return _s(x).rolling(n, min_periods=n).std(ddof=0).to_numpy(copy=True)


def hhv(x, n):
    return _s(x).rolling(n, min_periods=n).max().to_numpy(copy=True)


def llv(x, n):
    return _s(x).rolling(n, min_periods=n).min().to_numpy(copy=True)


def rsum(x, n):
    return _s(x).rolling(n, min_periods=n).sum().to_numpy(copy=True)


def ema(x, n):
    return _s(x).ewm(span=n, adjust=False, min_periods=n).mean().to_numpy(copy=True)


def wilder(x, n):
    return _s(x).ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean().to_numpy(copy=True)


def ffill(x):
    return _s(x).ffill().to_numpy(copy=True)


def roc(c, n):
    return c / shift(c, n) - 1.0


def zscore(c, n):
    sd = rstd(c, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return (c - sma(c, n)) / sd


def _win(x, n):
    """Trailing windows (len(x) rows, n columns), NaN padded at the start."""
    out = np.full((len(x), n), np.nan)
    if len(x) >= n:
        out[n - 1:] = sliding_window_view(x, n)
    return out


def pct_rank(x, n):
    """Share of the previous n-1 values below the current one, 0..100."""
    w = _win(x, n)
    with np.errstate(invalid="ignore"):
        return 100.0 * np.sum(w[:, :-1] < w[:, -1:], axis=1) / (n - 1) + 0 * w[:, -1]


# ------------------------------------------------------------ range, volatility
def tr(h, l, c):
    pc = shift(c)
    r = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    r[0] = h[0] - l[0]
    return r


def atr(h, l, c, n):
    return wilder(tr(h, l, c), n)


def bbands(c, n=20, k=2.0):
    mid = sma(c, n)
    sd = rstd(c, n)
    return mid, mid + k * sd, mid - k * sd


# ------------------------------------------------------------ momentum
def rsi(c, n=14):
    d = np.r_[0.0, np.diff(c)]
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru, rd = wilder(up, n), wilder(dn, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + ru / rd)
    out = np.where((rd == 0) & (ru > 0), 100.0, out)
    return out


def macd(c, f=12, s=26, g=9):
    line = ema(c, f) - ema(c, s)
    sig = ema(line, g)
    return line, sig, line - sig


def stoch(h, l, c, n=14, ks=3, d=3):
    hh, ll = hhv(h, n), llv(l, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = 100.0 * (c - ll) / (hh - ll)
    k = sma(raw, ks)
    return k, sma(k, d)


def willr(h, l, c, n=14):
    hh, ll = hhv(h, n), llv(l, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return -100.0 * (hh - c) / (hh - ll)


def mad(x, n):
    w = _win(x, n)
    return np.mean(np.abs(w - w.mean(axis=1, keepdims=True)), axis=1)


def cci(h, l, c, n=20):
    tp = (h + l + c) / 3.0
    with np.errstate(divide="ignore", invalid="ignore"):
        return (tp - sma(tp, n)) / (0.015 * mad(tp, n))


def adx(h, l, c, n=14):
    up = np.nan_to_num(h - shift(h))
    dn = np.nan_to_num(shift(l) - l)
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    mdm = np.where((dn > up) & (dn > 0), dn, 0.0)
    a = wilder(tr(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100.0 * wilder(pdm, n) / a
        mdi = 100.0 * wilder(mdm, n) / a
        dx = 100.0 * np.abs(pdi - mdi) / (pdi + mdi)
    out = wilder(np.nan_to_num(dx), n)
    out[: 2 * n] = np.nan
    return out, pdi, mdi


def aroon(h, l, n=25):
    wh, wl = _win(h, n + 1), _win(l, n + 1)
    with np.errstate(invalid="ignore"):
        since_h = np.argmax(wh[:, ::-1], axis=1)
        since_l = np.argmin(wl[:, ::-1], axis=1)
    ok = ~np.isnan(wh[:, 0])
    up = np.where(ok, 100.0 * (n - since_h) / n, np.nan)
    dn = np.where(ok, 100.0 * (n - since_l) / n, np.nan)
    return up, dn


def vortex(h, l, c, n=14):
    vmp = np.abs(h - shift(l))
    vmm = np.abs(l - shift(h))
    t = rsum(tr(h, l, c), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return rsum(vmp, n) / t, rsum(vmm, n) / t


def wma(x, n):
    w = _win(x, n)
    wt = np.arange(1, n + 1, dtype=float)
    return (w @ wt) / wt.sum()


def hma(c, n=21):
    half = max(2, n // 2)
    root = max(2, int(round(np.sqrt(n))))
    return wma(2.0 * wma(c, half) - wma(c, n), root)


def linreg(c, n=30):
    """Slope per bar, R squared and the fitted value at the current bar."""
    w = _win(c, n)
    xc = np.arange(n, dtype=float) - (n - 1) / 2.0
    sxx = float(xc @ xc)
    ym = w.mean(axis=1)
    slope = (w @ xc) / sxx
    ssy = np.sum((w - ym[:, None]) ** 2, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = slope * slope * sxx / ssy
    end = ym + slope * (n - 1) / 2.0
    return slope, r2, end


# ------------------------------------------------------------ volume
def obv(c, v):
    d = np.r_[0.0, np.sign(np.diff(c))]
    return np.cumsum(d * v)


def mfm(h, l, c):
    with np.errstate(divide="ignore", invalid="ignore"):
        m = ((c - l) - (h - c)) / (h - l)
    return np.where(h > l, m, 0.0)


def cmf(h, l, c, v, n=20):
    with np.errstate(divide="ignore", invalid="ignore"):
        return rsum(mfm(h, l, c) * v, n) / rsum(v, n)


def adline(h, l, c, v):
    return np.cumsum(mfm(h, l, c) * v)


def mfi(h, l, c, v, n=14):
    tp = (h + l + c) / 3.0
    raw = tp * v
    d = np.r_[0.0, np.diff(tp)]
    pos = rsum(np.where(d > 0, raw, 0.0), n)
    neg = rsum(np.where(d < 0, raw, 0.0), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + pos / neg)
    return np.where((neg == 0) & (pos > 0), 100.0, out)


def force_index(c, v, n=13):
    return ema(np.r_[0.0, np.diff(c)] * v, n)


def ease_of_movement(h, l, v, n=14):
    mid = (h + l) / 2.0
    dist = mid - shift(mid)
    with np.errstate(divide="ignore", invalid="ignore"):
        box = (v / (h - l))
        e = dist / box
    e = np.where(np.isfinite(e), e, 0.0)
    return sma(e, n)


def day_cum(x, day_id):
    """Cumulative sum that restarts every trading day."""
    s = pd.Series(x).groupby(day_id).cumsum().to_numpy(copy=True)
    return s


# ------------------------------------------------------------ recursive indicators
@njit(cache=True)
def _supertrend(h, l, c, a, mult):
    n = len(c)
    line = np.full(n, np.nan)
    dirn = np.zeros(n)
    fu = np.nan
    fl = np.nan
    d = 1.0
    started = False
    for i in range(n):
        if np.isnan(a[i]):
            continue
        mid = (h[i] + l[i]) / 2.0
        bu = mid + mult * a[i]
        bl = mid - mult * a[i]
        if not started:
            fu, fl, d = bu, bl, 1.0
            started = True
        else:
            fu = bu if (bu < fu or c[i - 1] > fu) else fu
            fl = bl if (bl > fl or c[i - 1] < fl) else fl
            if d > 0 and c[i] < fl:
                d = -1.0
            elif d < 0 and c[i] > fu:
                d = 1.0
        line[i] = fl if d > 0 else fu
        dirn[i] = d
    return line, dirn


def supertrend(h, l, c, n=10, mult=3.0):
    return _supertrend(h, l, c, atr(h, l, c, n), mult)


@njit(cache=True)
def _psar(h, l, af0, step, afmax):
    n = len(h)
    sar = np.full(n, np.nan)
    dirn = np.zeros(n)
    if n < 3:
        return sar, dirn
    up = True
    ep = h[0]
    s = l[0]
    af = af0
    sar[0], dirn[0] = s, 1.0
    for i in range(1, n):
        s = s + af * (ep - s)
        if up:
            s = min(s, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < s:
                up = False
                s = ep
                ep = l[i]
                af = af0
            elif h[i] > ep:
                ep = h[i]
                af = min(af + step, afmax)
        else:
            s = max(s, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > s:
                up = True
                s = ep
                ep = h[i]
                af = af0
            elif l[i] < ep:
                ep = l[i]
                af = min(af + step, afmax)
        sar[i] = s
        dirn[i] = 1.0 if up else -1.0
    return sar, dirn


def psar(h, l, af0=0.02, step=0.02, afmax=0.2):
    return _psar(h, l, af0, step, afmax)


@njit(cache=True)
def _kalman(logp, snr, vol_alpha):
    """Local linear trend filter on log price. State is [level, slope]."""
    n = len(logp)
    lvl = np.full(n, np.nan)
    slp = np.full(n, np.nan)
    if n < 3:
        return lvl, slp
    x0, x1 = logp[0], 0.0
    p00, p01, p11 = 1e-6, 0.0, 1e-8
    r = 1e-6
    for i in range(1, n):
        ret = logp[i] - logp[i - 1]
        r = (1.0 - vol_alpha) * r + vol_alpha * ret * ret + 1e-12
        q = snr * r
        # predict
        px0 = x0 + x1
        px1 = x1
        pp00 = p00 + 2.0 * p01 + p11 + q / 3.0
        pp01 = p01 + p11 + q / 2.0
        pp11 = p11 + q
        # update with the new price
        s = pp00 + r
        k0 = pp00 / s
        k1 = pp01 / s
        innov = logp[i] - px0
        x0 = px0 + k0 * innov
        x1 = px1 + k1 * innov
        p00 = (1.0 - k0) * pp00
        p01 = (1.0 - k0) * pp01
        p11 = pp11 - k1 * pp01
        lvl[i] = x0
        slp[i] = x1
    return lvl, slp


def kalman(c, snr=0.02, vol_alpha=0.05):
    lvl, slp = _kalman(np.log(c), snr, vol_alpha)
    return np.exp(lvl), slp


@njit(cache=True)
def _heikin(o, h, l, c):
    n = len(c)
    ho = np.empty(n)
    hc = (o + h + l + c) / 4.0
    ho[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2.0
    hh = np.maximum(h, np.maximum(ho, hc))
    hl = np.minimum(l, np.minimum(ho, hc))
    return ho, hh, hl, hc


def heikin(o, h, l, c):
    return _heikin(o, h, l, c)


@njit(cache=True)
def _streak(c):
    n = len(c)
    s = np.zeros(n)
    for i in range(1, n):
        if c[i] > c[i - 1]:
            s[i] = s[i - 1] + 1.0 if s[i - 1] > 0 else 1.0
        elif c[i] < c[i - 1]:
            s[i] = s[i - 1] - 1.0 if s[i - 1] < 0 else -1.0
    return s


def streak(c):
    return _streak(c)


@njit(cache=True)
def _stc_core(m, cyc, fac):
    n = len(m)
    out = np.full(n, np.nan)
    f1 = np.full(n, np.nan)
    pf = np.full(n, np.nan)
    f2 = np.full(n, np.nan)
    pff = np.full(n, np.nan)
    for i in range(n):
        if i < cyc - 1 or np.isnan(m[i]):
            continue
        lo = m[i]
        hi = m[i]
        ok = True
        for j in range(i - cyc + 1, i + 1):
            if np.isnan(m[j]):
                ok = False
                break
            lo = min(lo, m[j])
            hi = max(hi, m[j])
        if not ok:
            continue
        rng = hi - lo
        if rng > 0:
            f1[i] = (m[i] - lo) / rng * 100.0
        else:
            f1[i] = f1[i - 1] if i > 0 and not np.isnan(f1[i - 1]) else 0.0
        pf[i] = f1[i] if (i == 0 or np.isnan(pf[i - 1])) else pf[i - 1] + fac * (f1[i] - pf[i - 1])
        if i < 2 * cyc - 2:
            continue
        lo2 = pf[i]
        hi2 = pf[i]
        ok2 = True
        for j in range(i - cyc + 1, i + 1):
            if np.isnan(pf[j]):
                ok2 = False
                break
            lo2 = min(lo2, pf[j])
            hi2 = max(hi2, pf[j])
        if not ok2:
            continue
        rng2 = hi2 - lo2
        if rng2 > 0:
            f2[i] = (pf[i] - lo2) / rng2 * 100.0
        else:
            f2[i] = f2[i - 1] if i > 0 and not np.isnan(f2[i - 1]) else 0.0
        pff[i] = f2[i] if (i == 0 or np.isnan(pff[i - 1])) else pff[i - 1] + fac * (f2[i] - pff[i - 1])
        out[i] = pff[i]
    return out


def stc(c, fast=23, slow=50, cyc=10, fac=0.5):
    m = ema(c, fast) - ema(c, slow)
    return _stc_core(m, cyc, fac)


def ichimoku(h, l, c, t=9, k=26, b=52):
    ten = (hhv(h, t) + llv(l, t)) / 2.0
    kij = (hhv(h, k) + llv(l, k)) / 2.0
    sa = shift((ten + kij) / 2.0, k)
    sb = shift((hhv(h, b) + llv(l, b)) / 2.0, k)
    return ten, kij, sa, sb
