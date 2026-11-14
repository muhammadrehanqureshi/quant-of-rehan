"""Strategies S001 to S050: trend following, pullbacks in an uptrend, breakouts.

Every function gets the context ``x`` and returns a boolean array: True on the
bar whose CLOSE completes the setup. The engine enters at the next bar's open.
All of them are long only. Plain operators are safe on NaN warm-up bars (they
compare False), and ``sh(a, k)`` is a series k bars ago, never a future bar.
"""

import numpy as np

from . import ind
from .core import (ALL_TFS, INTRA_TFS, E, X, roll_all, roll_any, sh, shb, strat)

F = "Trend following"
P = "Pullback in an uptrend"
B = "Breakout and volatility"


def _sma_atr(x, n=50):
    return x.m(("sma_atr", n), lambda: ind.sma(x.atr(14), n))


# ====================================================================== trend following
@strat("S001", "EMA 9/21 cross in an EMA200 uptrend", F,
       parts=("trigger: EMA9 crosses above EMA21", "filter: close above EMA200"),
       params=dict(f=9, s=21, t=200), grid=[dict(f=5, s=13, t=100), dict(f=12, s=26, t=200)])
def s001(x, f, s, t):
    return X(x.ema(f), x.ema(s)) & (x.c > x.ema(t))


@strat("S002", "EMA 20/50 cross with a strengthening ADX", F,
       parts=("trigger: EMA20 crosses above EMA50", "filter: ADX14 above 20 and rising"),
       params=dict(f=20, s=50, a=20), grid=[dict(f=10, s=30, a=18), dict(f=20, s=50, a=25)])
def s002(x, f, s, a):
    adx = x.adx(14)[0]
    return X(x.ema(f), x.ema(s)) & (adx > a) & (adx > sh(adx))


@strat("S003", "Bounce off EMA21 inside an 8/21/55 EMA stack", F,
       parts=("filter: EMA8 > EMA21 > EMA55", "trigger: low tags EMA21 and the bar closes green above it"),
       params=dict(a=8, b=21, c=55), grid=[dict(a=5, b=13, c=34)])
def s003(x, a, b, c):
    e1, e2, e3 = x.ema(a), x.ema(b), x.ema(c)
    return E((e1 > e2) & (e2 > e3) & (x.l <= e2) & (x.c > e2) & (x.c > x.o))


@strat("S004", "Golden cross SMA50 over SMA200", F, tfs=("1h", "1d"),
       parts=("trigger: SMA50 crosses above SMA200",),
       params=dict(f=50, s=200), grid=[dict(f=20, s=100)])
def s004(x, f, s):
    return X(x.sma(f), x.sma(s))


@strat("S005", "Supertrend 10/3 flips up", F,
       parts=("trigger: Supertrend(10, 3) turns from down to up",),
       params=dict(n=10, m=3.0), grid=[dict(n=7, m=2.0), dict(n=14, m=3.0)])
def s005(x, n, m):
    d = x.supertrend(n, m)[1]
    return (d > 0) & (sh(d) < 0)


@strat("S006", "Supertrend flip confirmed by a rising EMA50", F,
       parts=("trigger: Supertrend flips up", "filter: EMA50 rising and close above it"),
       params=dict(n=10, m=3.0), grid=[dict(n=10, m=2.0)])
def s006(x, n, m):
    d = x.supertrend(n, m)[1]
    e = x.ema(50)
    return (d > 0) & (sh(d) < 0) & (e > sh(e)) & (x.c > e)


@strat("S007", "Donchian 20 breakout on volume", F,
       parts=("trigger: close above the prior 20 bar high", "filter: volume 1.2x its 20 bar average"),
       params=dict(n=20, vm=1.2), grid=[dict(n=10, vm=1.0), dict(n=30, vm=1.5)])
def s007(x, n, vm):
    return E((x.c > sh(x.hhv(n, "h"))) & (x.v > vm * x.vavg(20)))


@strat("S008", "Turtle 55 breakout with expanding ATR", F,
       parts=("trigger: close above the prior 55 bar high", "filter: ATR14 above its 50 bar average"),
       params=dict(n=55), grid=[dict(n=40), dict(n=80)])
def s008(x, n):
    return E((x.c > sh(x.hhv(n, "h"))) & (x.atr(14) > _sma_atr(x)))


@strat("S009", "Ichimoku cloud breakout with Tenkan over Kijun", F,
       parts=("trigger: close crosses above the cloud top", "filter: Tenkan above Kijun"),
       params={}, grid=())
def s009(x):
    ten, kij, sa, sb = x.ich()
    return X(x.c, np.fmax(sa, sb)) & (ten > kij)


@strat("S010", "Parabolic SAR flips up with ADX above 20", F,
       parts=("trigger: PSAR turns from above price to below", "filter: ADX14 above 20"),
       params=dict(a=20), grid=[dict(a=15), dict(a=25)])
def s010(x, a):
    d = x.psar()[1]
    return (d > 0) & (sh(d) < 0) & (x.adx(14)[0] > a)


@strat("S011", "MACD signal cross above zero in an EMA100 uptrend", F,
       parts=("trigger: MACD line crosses above signal", "filter: MACD above zero and close above EMA100"),
       params=dict(f=12, s=26, g=9, t=100), grid=[dict(f=8, s=21, g=5, t=50)])
def s011(x, f, s, g, t):
    line, sig, _ = x.macd(f, s, g)
    return X(line, sig) & (line > 0) & (x.c > x.ema(t))


@strat("S012", "MACD histogram turns up in an uptrend", F,
       parts=("trigger: histogram stops falling while still below zero", "filter: close above EMA100"),
       params=dict(t=100), grid=[dict(t=50)])
def s012(x, t):
    hist = x.macd()[2]
    return (hist > sh(hist)) & (sh(hist) <= sh(hist, 2)) & (hist < 0) & (x.c > x.ema(t))


@strat("S013", "Aroon 25 up line crosses the down line", F,
       parts=("trigger: Aroon up crosses above Aroon down", "filter: Aroon up above 70"),
       params=dict(n=25, lv=70), grid=[dict(n=14, lv=70), dict(n=50, lv=60)])
def s013(x, n, lv):
    up, dn = x.aroon(n)
    return X(up, dn) & (up > lv)


@strat("S014", "Vortex 14 cross with trend strength", F,
       parts=("trigger: VI+ crosses above VI-", "filter: ADX14 above 18"),
       params=dict(n=14, a=18), grid=[dict(n=21, a=20)])
def s014(x, n, a):
    vp, vm = x.vortex(n)
    return X(vp, vm) & (x.adx(14)[0] > a)


@strat("S015", "Hull MA 21 turns up", F,
       parts=("trigger: HMA slope flips from down to up", "filter: close above the HMA"),
       params=dict(n=21), grid=[dict(n=14), dict(n=34)])
def s015(x, n):
    h = x.hma(n)
    return (h > sh(h)) & (sh(h) <= sh(h, 2)) & (x.c > h)


@strat("S016", "Clean regression uptrend starts", F,
       parts=("state: 30 bar regression slope positive with R squared above 0.6", "filter: close above the fitted line"),
       params=dict(n=30, r2=0.6), grid=[dict(n=20, r2=0.5), dict(n=50, r2=0.7)])
def s016(x, n, r2):
    sl, r, end = x.linreg(n)
    return E((sl > 0) & (r > r2) & (x.c > end))


# ====================================================================== pullbacks in an uptrend
@strat("S017", "Connors RSI(2) below 10 above SMA200", P,
       parts=("trigger: RSI2 below 10", "filter: close above SMA200"),
       params=dict(n=2, th=10), grid=[dict(n=2, th=5), dict(n=3, th=15)])
def s017(x, n, th):
    return E((x.rsi(n) < th) & (x.c > x.sma(200)))


@strat("S018", "RSI14 recovers through 40 inside an EMA50 over EMA200 trend", P,
       parts=("trigger: RSI14 crosses above 40", "filter: EMA50 above EMA200"),
       params=dict(th=40), grid=[dict(th=35), dict(th=45)])
def s018(x, th):
    return X(x.rsi(14), th) & (x.ema(50) > x.ema(200))


@strat("S019", "Bollinger lower band reclaim in an uptrend", P,
       parts=("trigger: close crosses back above the lower band (20, 2)", "filter: close above SMA100"),
       params=dict(n=20, k=2.0), grid=[dict(n=20, k=2.5), dict(n=14, k=2.0)])
def s019(x, n, k):
    return X(x.c, x.bb(n, k)[2]) & (x.c > x.sma(100))


@strat("S020", "Keltner lower channel reclaim", P,
       parts=("trigger: close crosses back above EMA20 minus 2 ATR10", "filter: close above EMA200"),
       params=dict(m=2.0), grid=[dict(m=1.5), dict(m=2.5)])
def s020(x, m):
    return X(x.c, x.ema(20) - m * x.atr(10)) & (x.c > x.ema(200))


@strat("S021", "Z-score snap back from minus 2", P,
       parts=("trigger: yesterday z(20) below -2 and z turns up", "filter: close above SMA200"),
       params=dict(n=20, z=-2.0), grid=[dict(n=20, z=-1.5), dict(n=30, z=-2.5)])
def s021(x, n, z):
    zs = x.zscore(n)
    return (sh(zs) < z) & (zs > sh(zs)) & (x.c > x.sma(200))


@strat("S022", "Stochastic oversold cross in an uptrend", P,
       parts=("trigger: %K crosses above %D from below 20", "filter: close above EMA100"),
       params=dict(lv=20), grid=[dict(lv=25), dict(lv=15)])
def s022(x, lv):
    k, d = x.stoch(14, 3, 3)
    return X(k, d) & (sh(k) < lv) & (x.c > x.ema(100))


@strat("S023", "Williams %R leaves oversold in an uptrend", P,
       parts=("trigger: %R(14) crosses above -80", "filter: EMA50 above EMA200"),
       params=dict(lv=-80), grid=[dict(lv=-90)])
def s023(x, lv):
    return X(x.willr(14), lv) & (x.ema(50) > x.ema(200))


@strat("S024", "CCI recovers through minus 100 in an uptrend", P,
       parts=("trigger: CCI20 crosses above -100", "filter: EMA50 above EMA200"),
       params=dict(lv=-100), grid=[dict(lv=-150)])
def s024(x, lv):
    return X(x.cci(20), lv) & (x.ema(50) > x.ema(200))


@strat("S025", "Internal bar strength washout above SMA200", P,
       parts=("trigger: close in the bottom 20 percent of the bar range", "filter: close above SMA200"),
       params=dict(th=0.2), grid=[dict(th=0.1), dict(th=0.3)])
def s025(x, th):
    return E((x.ibs() < th) & (x.c > x.sma(200)))


@strat("S026", "Three down closes then a green bar in an uptrend", P,
       parts=("setup: three consecutive lower closes", "trigger: next bar closes green", "filter: close above EMA200"),
       params=dict(t=200), grid=[dict(t=100)])
def s026(x, t):
    down3 = (sh(x.c) < sh(x.c, 2)) & (sh(x.c, 2) < sh(x.c, 3)) & (sh(x.c, 3) < sh(x.c, 4))
    return down3 & (x.c > x.o) & (x.c > x.ema(t))


@strat("S027", "VWAP dip and reclaim on high volume", P, tfs=INTRA_TFS,
       parts=("setup: price dipped 0.5 ATR below the day VWAP in the last 6 bars", "trigger: close crosses back above VWAP"),
       params=dict(d=0.5), grid=[dict(d=0.3), dict(d=0.8)])
def s027(x, d):
    dev = (x.c - x.vwap()) / x.atr(14)
    return X(x.c, x.vwap()) & (ind.llv(dev, 6) < -d) & (x.bar_in_day >= 6)


@strat("S028", "Fibonacci 50 to 61.8 percent pullback bounce", P,
       parts=("setup: 40 bar up leg wider than 2 ATR", "trigger: bullish bar closing in the 50 to 61.8 percent retracement zone"),
       params=dict(n=40), grid=[dict(n=30), dict(n=60)])
def s028(x, n):
    hh, ll = x.hhv(n, "h"), x.llv(n, "l")
    rng = hh - ll
    ret = (hh - x.c) / rng
    au, ad = x.aroon(n)
    return E((ret >= 0.5) & (ret <= 0.618) & (au > ad) & (x.c > x.o) & (rng > 2 * x.atr(14)))


@strat("S029", "Gap down that reverses above the first bar high", P, tfs=INTRA_TFS,
       parts=("setup: gap down more than 1 percent", "trigger: close above the day open and above the first bar high"),
       params=dict(g=-0.01), grid=[dict(g=-0.005), dict(g=-0.02)])
def s029(x, g):
    first_hi = x.or_level(x.tfmin, "h")
    return x.once_a_day((x.gap() < g) & (x.c > x.day_open()) & (x.c > first_hi))


@strat("S030", "MFI leaves oversold in an uptrend", P,
       parts=("trigger: MFI14 crosses above 20", "filter: close above EMA100"),
       params=dict(lv=20), grid=[dict(lv=30)])
def s030(x, lv):
    return X(x.mfi(14), lv) & (x.c > x.ema(100))


@strat("S031", "EMA20 tag followed by a bullish engulfing bar", P,
       parts=("setup: previous bar tagged EMA20 in an EMA20 > EMA50 trend", "trigger: bullish engulfing"),
       params={}, grid=())
def s031(x):
    e20, e50 = x.ema(20), x.ema(50)
    engulf = (sh(x.c) < sh(x.o)) & (x.c > x.o) & (x.c >= sh(x.o)) & (x.o <= sh(x.c))
    return engulf & (sh(x.l) <= sh(e20) * 1.002) & (e20 > e50)


@strat("S032", "RSI5 washout on rising volume", P,
       parts=("trigger: RSI5 below 20 with volume above the previous bar", "filter: close above EMA100"),
       params=dict(th=20), grid=[dict(th=10), dict(th=30)])
def s032(x, th):
    return E((x.rsi(5) < th) & (x.c > x.ema(100)) & (x.v > sh(x.v)))


@strat("S033", "Shallow ATR pullback in an EMA50 uptrend", P,
       parts=("setup: close 1 to 2 ATR under the 20 bar high with ATR5 below ATR14", "trigger: green bar above EMA50"),
       params=dict(lo=1.0, hi=2.0), grid=[dict(lo=0.8, hi=1.6)])
def s033(x, lo, hi):
    depth = (sh(x.hhv(20, "h")) - x.c) / x.atr(14)
    return E((depth >= lo) & (depth <= hi) & (x.c > x.ema(50)) & (x.c > x.o) & (x.atr(5) < x.atr(14)))


@strat("S034", "Two bar reversal at the lower Bollinger band", P,
       parts=("setup: red bar tagged the lower band", "trigger: green bar closing above the red bar high"),
       params={}, grid=())
def s034(x):
    lo = x.bb(20, 2.0)[2]
    return (sh(x.l) <= sh(lo)) & (sh(x.c) < sh(x.o)) & (x.c > sh(x.h)) & (x.c > x.o)


# ====================================================================== breakouts and volatility
@strat("S035", "Bollinger squeeze release upwards", B,
       parts=("setup: band width within 10 percent of its 120 bar minimum in the last 5 bars", "trigger: close above the upper band"),
       params=dict(n=20), grid=[dict(n=30)])
def s035(x, n):
    mid, up, lo = x.bb(n, 2.0)
    bw = (up - lo) / mid
    sq = bw <= 1.1 * ind.llv(bw, 120)
    return E(shb(roll_any(sq, 5)) & (x.c > up))


@strat("S036", "NR7 narrow range breakout", B,
       parts=("setup: previous bar had the narrowest range of 7", "trigger: close above that bar high"),
       params=dict(n=7), grid=[dict(n=4), dict(n=10)])
def s036(x, n):
    r = x.rng()
    nr = r <= ind.llv(r, n)
    return shb(nr) & (x.c > sh(x.h))


@strat("S037", "Inside bar breakout above the mother bar", B,
       parts=("setup: previous bar inside the bar before it", "trigger: close above the mother bar high", "filter: EMA20 rising"),
       params={}, grid=())
def s037(x):
    ib = (x.h < sh(x.h)) & (x.l > sh(x.l))
    e = x.ema(20)
    return shb(ib) & (x.c > sh(x.h, 2)) & (e > sh(e))


@strat("S038", "ATR expansion bar closing near its high", B,
       parts=("trigger: true range above 1.5 times the prior ATR14", "filter: close in the top quarter of the bar and above EMA20"),
       params=dict(m=1.5), grid=[dict(m=1.2), dict(m=2.0)])
def s038(x, m):
    return (x.tr() > m * sh(x.atr(14))) & (x.ibs() > 0.75) & (x.c > x.ema(20))


@strat("S039", "Opening range breakout, 30 minutes", B, tfs=INTRA_TFS,
       parts=("trigger: first close above the 30 minute opening range high", "filter: volume above its 20 bar average"),
       params=dict(mins=30), grid=[dict(mins=15), dict(mins=45)])
def s039(x, mins):
    return x.once_a_day((x.c > x.or_level(mins, "h")) & (x.v > x.vavg(20)) & (x.bar_in_day >= x.or_bars(mins)))


@strat("S040", "Opening range breakout, 60 minutes, with VWAP and a flat or up open", B, tfs=INTRA_TFS,
       parts=("trigger: first close above the 60 minute opening range high", "filter: close above VWAP, gap not negative"),
       params=dict(mins=60), grid=[dict(mins=90)])
def s040(x, mins):
    return x.once_a_day((x.c > x.or_level(mins, "h")) & (x.c > x.vwap()) & (x.gap() >= 0) & (x.bar_in_day >= x.or_bars(mins)))


@strat("S041", "Previous day high breakout above VWAP", B, tfs=INTRA_TFS,
       parts=("trigger: close crosses above yesterday's high", "filter: close above VWAP"),
       params={}, grid=())
def s041(x):
    return x.once_a_day(X(x.c, x.prev_day("h")) & (x.c > x.vwap()))


@strat("S042", "Gap up that holds its open", B, tfs=INTRA_TFS,
       parts=("setup: gap up above 1 percent, never traded 0.5 percent under the open", "trigger: first close after 15 minutes above open and VWAP"),
       params=dict(g=0.01), grid=[dict(g=0.005), dict(g=0.02)])
def s042(x, g):
    nb = max(2, x.or_bars(15))
    ok = (x.gap() > g) & (x.c > x.day_open()) & (x.c > x.vwap()) & (x.day_lo_sofar() >= x.day_open() * 0.995)
    return x.once_a_day(ok & (x.bar_in_day >= nb))


@strat("S043", "Volume spike breakout", B,
       parts=("trigger: close above the prior 20 bar high", "filter: volume above 3 times its average"),
       params=dict(vm=3.0, n=20), grid=[dict(vm=2.0, n=20), dict(vm=4.0, n=30)])
def s043(x, vm, n):
    return E((x.v > vm * sh(x.vavg(20))) & (x.c > sh(x.hhv(n, "h"))))


@strat("S044", "One year closing high", B, tfs=("1h", "1d"),
       parts=("trigger: close above the highest close of the last 250 sessions",),
       params=dict(days=250), grid=[dict(days=120)])
def s044(x, days):
    return E(x.c > sh(x.hhv(days * x.bpd, "c")))


@strat("S045", "Range expansion day closing above the prior high", B,
       parts=("trigger: range above 2 times its 20 bar average, green, close above the prior high",),
       params=dict(m=2.0), grid=[dict(m=1.5)])
def s045(x, m):
    avg = x.m(("rgavg", 20), lambda: ind.sma(x.rng(), 20))
    return (x.rng() > m * sh(avg)) & (x.c > x.o) & (x.c > sh(x.h))


@strat("S046", "Volatility contraction pattern breakout", B,
       parts=("setup: ATR5 under 0.8 times ATR50 for 3 bars", "trigger: close above the prior 10 bar high"),
       params=dict(r=0.8, k=3), grid=[dict(r=0.7, k=3), dict(r=0.9, k=3)])
def s046(x, r, k):
    contraction = x.atr(5) / x.atr(50) < r
    return E(shb(roll_all(contraction, k)) & (x.c > sh(x.hhv(10, "h"))))


@strat("S047", "Break of the last confirmed swing high", B,
       parts=("setup: pivot high confirmed after 3 lower bars", "trigger: close crosses above the pivot", "filter: close above EMA50"),
       params={}, grid=())
def s047(x):
    piv_val = sh(x.h, 3)
    is_piv = piv_val >= ind.hhv(x.h, 7)
    level = ind.ffill(np.where(is_piv, piv_val, np.nan))
    return X(x.c, sh(level)) & (x.c > x.ema(50))


@strat("S048", "Keltner channel breakout with ADX and volume", B,
       parts=("trigger: close above EMA20 plus 2 ATR10", "filter: ADX14 above 20 and rising, volume above average"),
       params=dict(m=2.0), grid=[dict(m=1.5), dict(m=2.5)])
def s048(x, m):
    adx = x.adx(14)[0]
    return E((x.c > x.ema(20) + m * x.atr(10)) & (adx > 20) & (adx > sh(adx)) & (x.v > x.vavg(20)))


@strat("S049", "Darvas style tight box breakout", B,
       parts=("setup: prior 20 bar box under 6 ATR tall", "trigger: close above the box top on 1.2 times volume"),
       params=dict(h=6.0), grid=[dict(h=4.0), dict(h=8.0)])
def s049(x, h):
    top, bot = sh(x.hhv(20, "h")), sh(x.llv(20, "l"))
    return E(((top - bot) < h * sh(x.atr(14))) & (x.c > top) & (x.v > 1.2 * x.vavg(20)))


@strat("S050", "Five bar high breakout in an EMA20 uptrend", B, tfs=("1h", "1d"),
       parts=("trigger: close above the prior 5 bar high", "filter: close above EMA20 and volume above average"),
       params=dict(n=5), grid=[dict(n=3), dict(n=8)])
def s050(x, n):
    return E((x.c > sh(x.hhv(n, "h"))) & (x.c > x.ema(20)) & (x.v > x.vavg(20)))
