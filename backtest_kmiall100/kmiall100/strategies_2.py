"""Strategies S051 to S100: candlesticks, volume, intraday session, market index,
calendar, and composite or multi timeframe ideas. All long only, all causal."""

import numpy as np
import pandas as pd

from . import ind
from .core import (ALL_TFS, INTRA_TFS, E, X, roll_all, roll_any, sh, shb, strat)

K = "Candlestick pattern"
V = "Volume and money flow"
T = "Intraday session"
I = "Market index and relative strength"
C = "Calendar"
M = "Composite and multi timeframe"


def _bear(x, k=1):
    return sh(x.c, k) < sh(x.o, k)


def _big_body(x, k, f=0.6):
    return sh(x.body(), k) > f * sh(x.rng(), k)


def _engulf(x):
    return _bear(x) & (x.c > x.o) & (x.c >= sh(x.o)) & (x.o <= sh(x.c))


def _htf_kind(x):
    return "W" if x.tf == "1d" else ("D" if x.tfmin >= 60 else "H")


def _no_index(x):
    return np.zeros(x.n, dtype=bool)


# ====================================================================== candlestick patterns
@strat("S051", "Bullish engulfing at a 20 bar low after a decline", K,
       parts=("setup: prior bar within 1 percent of the 20 bar low, close under the close 4 bars before", "trigger: bullish engulfing"),
       params={}, grid=())
def s051(x):
    near = sh(x.l) <= sh(x.llv(20, "l")) * 1.01
    return _engulf(x) & near & (sh(x.c) < sh(x.c, 4))


@strat("S052", "Hammer under the lower Bollinger band", K,
       parts=("trigger: long lower wick (2x the body), small upper wick", "setup: low pierces the lower band (20, 2)"),
       params={}, grid=())
def s052(x):
    lo = x.bb(20, 2.0)[2]
    b = x.body()
    ham = (x.lower_wick() >= 2 * b) & (x.upper_wick() <= 0.5 * b) & (b > 0.1 * x.rng())
    return E(ham & (x.l <= lo))


@strat("S053", "Morning star", K,
       parts=("bar 1: big red body", "bar 2: small body under bar 1 close", "bar 3: green close past the middle of bar 1"),
       params={}, grid=())
def s053(x):
    star_small = sh(x.body()) < 0.3 * sh(x.rng())
    star_low = np.fmax(sh(x.o), sh(x.c)) < sh(x.c, 2)
    mid1 = (sh(x.o, 2) + sh(x.c, 2)) / 2.0
    return _bear(x, 2) & _big_body(x, 2) & star_small & star_low & (x.c > x.o) & (x.c > mid1)


@strat("S054", "Three white soldiers", K,
       parts=("three green bars with rising closes", "each body above 60 percent of its range", "each open inside or at the edge of the prior body"),
       params={}, grid=())
def s054(x):
    def bull(k): return sh(x.c, k) > sh(x.o, k)
    big = [sh(x.body(), k) > 0.6 * sh(x.rng(), k) for k in (0, 1, 2)]
    rising = (x.c > sh(x.c)) & (sh(x.c) > sh(x.c, 2))
    opens = (x.o >= sh(x.o)) & (x.o <= sh(x.c)) & (sh(x.o) >= sh(x.o, 2)) & (sh(x.o) <= sh(x.c, 2))
    return bull(0) & bull(1) & bull(2) & big[0] & big[1] & big[2] & rising & opens


@strat("S055", "Piercing line", K,
       parts=("prior big red bar", "green bar opens under its close and closes above its midpoint but below its open"),
       params={}, grid=())
def s055(x):
    mid = (sh(x.o) + sh(x.c)) / 2.0
    return _bear(x) & _big_body(x, 1) & (x.o <= sh(x.c)) & (x.c > mid) & (x.c < sh(x.o))


@strat("S056", "Tweezer bottom", K,
       parts=("red bar then green bar with matching lows (within 0.1 ATR)",),
       params=dict(t=0.1), grid=[dict(t=0.2)])
def s056(x, t):
    return _bear(x) & (x.c > x.o) & (np.abs(x.l - sh(x.l)) < t * sh(x.atr(14)))


@strat("S057", "Bullish marubozu on volume above EMA50", K,
       parts=("body at least 90 percent of the range, green", "volume above 1.5 times average, close above EMA50"),
       params=dict(vm=1.5), grid=[dict(vm=1.2)])
def s057(x, vm):
    return E((x.body() >= 0.9 * x.rng()) & (x.c > x.o) & (x.v > vm * x.vavg(20)) & (x.c > x.ema(50)))


@strat("S058", "Bullish harami after weakness", K,
       parts=("prior big red bar", "small green bar inside its body", "RSI14 below 40 on the prior bar"),
       params=dict(r=40), grid=[dict(r=50)])
def s058(x, r):
    inside = (x.c > x.o) & (x.o > sh(x.c)) & (x.c < sh(x.o)) & (x.body() < 0.5 * sh(x.body()))
    return _bear(x) & _big_body(x, 1) & inside & (sh(x.rsi(14)) < r)


@strat("S059", "Dragonfly doji at a 20 bar low", K,
       parts=("tiny body, long lower wick, almost no upper wick", "low at or under the prior 20 bar low"),
       params={}, grid=())
def s059(x):
    r = x.rng()
    shape = (x.body() < 0.1 * r) & (x.lower_wick() > 0.6 * r) & (x.upper_wick() < 0.1 * r)
    return E(shape & (x.l <= sh(x.llv(20, "l")) * 1.002))


@strat("S060", "Rising three methods", K,
       parts=("big green bar", "three small bars inside its range", "green close above its high"),
       params={}, grid=())
def s060(x):
    inside = np.ones(x.n, dtype=bool)
    for k in (1, 2, 3):
        inside &= (sh(x.h, k) <= sh(x.h, 4)) & (sh(x.l, k) >= sh(x.l, 4))
    first = (sh(x.c, 4) > sh(x.o, 4)) & _big_body(x, 4)
    return first & inside & (x.c > x.o) & (x.c > sh(x.h, 4))


# ====================================================================== volume and money flow
@strat("S061", "OBV leads a 10 bar closing high", V,
       parts=("trigger: OBV above its prior 20 bar high", "confirm: close above the prior 10 bar closing high"),
       params={}, grid=())
def s061(x):
    o = x.obv()
    return E((o > sh(ind.hhv(o, 20))) & (x.c > sh(x.hhv(10, "c"))))


@strat("S062", "Chaikin money flow crosses 0.1 above EMA50", V,
       parts=("trigger: CMF20 crosses above 0.1 and is rising", "filter: close above EMA50"),
       params=dict(lv=0.1), grid=[dict(lv=0.05), dict(lv=0.15)])
def s062(x, lv):
    c = x.cmf(20)
    return X(c, lv) & (c > sh(c)) & (x.c > x.ema(50))


@strat("S063", "Three bar accumulation run", V,
       parts=("three higher closes", "three rising volumes", "close above EMA20"),
       params={}, grid=())
def s063(x):
    up = (x.c > sh(x.c)) & (sh(x.c) > sh(x.c, 2)) & (sh(x.c, 2) > sh(x.c, 3))
    vol = (x.v > sh(x.v)) & (sh(x.v) > sh(x.v, 2))
    return E(up & vol & (x.c > x.ema(20)))


@strat("S064", "VWAP reclaim on strong volume", V, tfs=INTRA_TFS,
       parts=("trigger: close crosses above the day VWAP", "filter: volume 1.5 times average, not in the first 3 bars"),
       params=dict(vm=1.5), grid=[dict(vm=1.2), dict(vm=2.0)])
def s064(x, vm):
    return X(x.c, x.vwap()) & (x.v > vm * x.vavg(20)) & (x.bar_in_day >= 3)


@strat("S065", "Accumulation distribution divergence at a new low", V,
       parts=("setup: close makes a new 20 bar low while the A/D line holds above its own 20 bar low", "trigger: green bar"),
       params={}, grid=())
def s065(x):
    a = x.adl()
    return E((x.c < sh(x.llv(20, "c"))) & (a > sh(ind.llv(a, 20))) & (x.c > x.o))


@strat("S066", "Volume dry up then expansion", V,
       parts=("setup: 3 bars under half the average volume", "trigger: green bar on 2 times volume closing higher"),
       params=dict(dry=0.5, ex=2.0), grid=[dict(dry=0.6, ex=1.5)])
def s066(x, dry, ex):
    quiet = x.v < dry * sh(x.vavg(20))
    return shb(roll_all(quiet, 3)) & (x.v > ex * sh(x.vavg(20))) & (x.c > x.o) & (x.c > sh(x.c))


@strat("S067", "MFI crosses 50 above EMA20", V,
       parts=("trigger: MFI14 crosses above 50", "filter: close above EMA20"),
       params=dict(lv=50), grid=[dict(lv=60)])
def s067(x, lv):
    return X(x.mfi(14), lv) & (x.c > x.ema(20))


@strat("S068", "Force index crosses zero in an EMA20 over EMA50 trend", V,
       parts=("trigger: force index(13) crosses above zero", "filter: EMA20 above EMA50"),
       params={}, grid=())
def s068(x):
    return X(x.force(13), 0.0) & (x.ema(20) > x.ema(50))


@strat("S069", "Ease of movement turns positive above EMA50", V,
       parts=("trigger: EOM14 crosses above zero", "filter: close above EMA50"),
       params={}, grid=())
def s069(x):
    return X(x.eom(14), 0.0) & (x.c > x.ema(50))


@strat("S070", "Selling climax reversal", V,
       parts=("setup: volume above 3 times average, RSI14 under 30 in the last 3 bars", "trigger: green bar closing in the upper half"),
       params=dict(vm=3.0), grid=[dict(vm=2.0)])
def s070(x, vm):
    return E((x.v > vm * sh(x.vavg(20))) & (x.ibs() > 0.5) & roll_any(x.rsi(14) < 30, 3) & (x.c > x.o))


# ====================================================================== intraday session (bars counted from the open)
@strat("S071", "Opening drive continuation", T, tfs=INTRA_TFS,
       parts=("setup: up more than 0.5 percent from the open after 30 minutes", "trigger: first such close above VWAP on above average volume"),
       params=dict(r=0.005), grid=[dict(r=0.003), dict(r=0.01)])
def s071(x, r):
    nb = x.or_bars(30)
    ok = (x.c / x.day_open() - 1 > r) & (x.c > x.vwap()) & (x.v > x.vavg(20)) & (x.bar_in_day >= nb)
    return x.once_a_day(ok)


@strat("S072", "Gap up VWAP dip then reclaim", T, tfs=INTRA_TFS,
       parts=("setup: gap up above 0.5 percent, price traded under VWAP", "trigger: first close back above VWAP"),
       params=dict(g=0.005), grid=[dict(g=0.0), dict(g=0.01)])
def s072(x, g):
    dipped = x.by_day_run(np.where(x.c < x.vwap(), 1.0, 0.0), "max") > 0
    return x.once_a_day((x.gap() > g) & X(x.c, x.vwap()) & shb(dipped))


@strat("S073", "Midday compression breakout", T, tfs=("5m", "15m", "30m"),
       parts=("setup: prior hour range under 2.5 ATR", "trigger: close above the prior hour high between minute 90 and 300"),
       params=dict(m=2.5), grid=[dict(m=2.0), dict(m=3.0)])
def s073(x, m):
    k = max(2, 60 // x.tfmin)
    top, bot = sh(x.hhv(k, "h")), sh(x.llv(k, "l"))
    win = (x.mins_open >= 90) & (x.mins_open <= 300)
    return x.once_a_day(win & ((top - bot) < m * sh(x.atr(14))) & (x.c > top) & (x.v > 1.2 * x.vavg(20)))


@strat("S074", "Late session strength held overnight", T, tfs=INTRA_TFS, overnight=True,
       hold=dict(zip(("5m", "15m", "30m", "1h"), (120, 40, 22, 12))),
       parts=("setup: after minute 240, close in the top 20 percent of the day range, up 0.5 percent, above VWAP", "exit: TP, SL or the next session"),
       params=dict(r=0.005), grid=[dict(r=0.01)])
def s074(x, r):
    rng = x.day_hi_sofar() - x.day_lo_sofar()
    ok = (x.mins_open >= 240) & (x.c > x.vwap()) & (rng > 0) & (x.c >= x.day_lo_sofar() + 0.8 * rng) & (x.c / x.day_open() - 1 > r)
    return x.once_a_day(ok)


@strat("S075", "Yesterday close reclaim after a morning dip", T, tfs=INTRA_TFS,
       parts=("setup: traded more than 1 percent under yesterday's close", "trigger: first close back above it"),
       params=dict(d=0.01), grid=[dict(d=0.005), dict(d=0.02)])
def s075(x, d):
    pc = x.prev_day("c")
    dipped = x.by_day_run(np.where(x.c < pc * (1 - d), 1.0, 0.0), "max") > 0
    return x.once_a_day(X(x.c, pc) & shb(dipped))


@strat("S076", "Day open reclaim on volume", T, tfs=INTRA_TFS,
       parts=("setup: traded 0.5 percent under the day open", "trigger: first close back above the open on above average volume"),
       params=dict(d=0.005), grid=[dict(d=0.003), dict(d=0.01)])
def s076(x, d):
    do = x.day_open()
    dipped = x.by_day_run(np.where(x.c < do * (1 - d), 1.0, 0.0), "max") > 0
    return x.once_a_day(X(x.c, do) & shb(dipped) & (x.v > x.vavg(20)))


@strat("S077", "Strong yesterday plus opening range break", T, tfs=INTRA_TFS,
       parts=("setup: yesterday closed in the top quarter of its range", "trigger: first close above today's 30 minute opening range high"),
       params={}, grid=())
def s077(x):
    pc, pl, ph = x.prev_day("c"), x.prev_day("l"), x.prev_day("h")
    strong = pc >= pl + 0.75 * (ph - pl)
    return x.once_a_day(strong & (x.c > x.or_level(30, "h")) & (x.bar_in_day >= x.or_bars(30)))


@strat("S078", "Failed opening range breakdown (bear trap)", T, tfs=INTRA_TFS,
       parts=("setup: close under the 30 minute opening range low within the last 3 bars", "trigger: green close back above that low"),
       params={}, grid=())
def s078(x):
    olow = x.or_level(30, "l")
    brk = x.c < olow
    recent = roll_any(shb(brk), 3)
    return x.once_a_day(recent & (x.c > olow) & (x.c > x.o))


# ====================================================================== market index and relative strength
@strat("S079", "Relative strength breakout while the index trends up", I, needs_index=True,
       parts=("market: KMIALL above its EMA50", "stock: outperforming the index over 20 bars and rising", "trigger: close above the prior 20 bar high"),
       params=dict(n=20), grid=[dict(n=10)])
def s079(x, n):
    if x.ix is None:
        return _no_index(x)
    ix = x.ix
    rel = (x.c / sh(x.c, n)) / (ix.c / sh(ix.c, n))
    return E((rel > 1) & (rel > sh(rel)) & (ix.c > ix.ema(50)) & (x.c > sh(x.hhv(n, "h"))))


@strat("S080", "Index oversold bounce, strong stock", I, needs_index=True,
       parts=("market: KMIALL RSI2 under 10", "stock: close above its SMA200"),
       params=dict(th=10), grid=[dict(th=5), dict(th=15)])
def s080(x, th):
    if x.ix is None:
        return _no_index(x)
    return E((x.ix.rsi(2) < th) & (x.c > x.sma(200)))


@strat("S081", "Stock rises on volume while the index falls", I, needs_index=True,
       parts=("market: index bar down", "stock: up 0.3 percent on 1.2 times volume above EMA20"),
       params=dict(r=0.003), grid=[dict(r=0.002), dict(r=0.005)])
def s081(x, r):
    if x.ix is None:
        return _no_index(x)
    return E((x.ix.c < sh(x.ix.c)) & (x.c > sh(x.c) * (1 + r)) & (x.v > 1.2 * x.vavg(20)) & (x.c > x.ema(20)))


@strat("S082", "Relative strength line at a 60 bar high", I, needs_index=True,
       parts=("stock to index ratio above its prior 60 bar high", "market: KMIALL above its EMA50"),
       params=dict(n=60), grid=[dict(n=30)])
def s082(x, n):
    if x.ix is None:
        return _no_index(x)
    rs = x.c / x.ix.c
    return E((rs > sh(ind.hhv(rs, n))) & (x.ix.c > x.ix.ema(50)))


@strat("S083", "Excess return over the index in ATR units", I, needs_index=True,
       parts=("10 bar return minus the index return above 2 ATR units and rising", "close above EMA20"),
       params=dict(z=2.0), grid=[dict(z=1.5), dict(z=3.0)])
def s083(x, z):
    if x.ix is None:
        return _no_index(x)
    zz = (x.roc(10) - x.ix.roc(10)) / (x.atrp(14) * np.sqrt(10))
    return E((zz > z) & (zz > sh(zz)) & (x.c > x.ema(20)))


@strat("S084", "Strong stock buys an index pullback", I, needs_index=True,
       parts=("market: KMIALL under EMA20 but above EMA100", "stock: above EMA20, green, relative strength rising"),
       params={}, grid=())
def s084(x):
    if x.ix is None:
        return _no_index(x)
    ix = x.ix
    rs = x.c / ix.c
    return E((ix.c < ix.ema(20)) & (ix.c > ix.ema(100)) & (x.c > x.ema(20)) & (x.c > sh(x.c)) & (rs > sh(rs, 5)))


@strat("S085", "Follow an index 20 bar breakout", I, needs_index=True,
       parts=("market: KMIALL closes above its prior 20 bar high", "stock: above EMA20 and up on the bar"),
       params=dict(n=20), grid=[dict(n=10)])
def s085(x, n):
    if x.ix is None:
        return _no_index(x)
    return E((x.ix.c > sh(x.ix.hhv(n, "c"))) & (x.c > x.ema(20)) & (x.c > sh(x.c)))


@strat("S086", "EMA20 pullback in a calm index regime", I, needs_index=True,
       parts=("market: KMIALL ATR% under its 100 bar average", "stock: EMA20 > EMA50, low tags EMA20, green close above it"),
       params={}, grid=())
def s086(x):
    if x.ix is None:
        return _no_index(x)
    ap = x.ix.atrp(14)
    calm = ap < x.ix.m(("sma_atrp", 100), lambda: ind.sma(ap, 100))
    e20 = x.ema(20)
    return E(calm & (e20 > x.ema(50)) & (x.l <= e20 * 1.001) & (x.c > e20) & (x.c > x.o))


# ====================================================================== calendar (daily bars)
@strat("S087", "Turn of the month window above EMA50", C, tfs=("1d",), hold=dict({"1d": 3}),
       parts=("window: calendar day 28 onwards or the first 3 trading days of a month", "filter: close above EMA50"),
       params={}, grid=())
def s087(x):
    mkey = x.ts.astype("datetime64[M]").astype("int64")
    k = pd.Series(np.arange(x.n)).groupby(mkey).cumcount().to_numpy()
    return E(((x.dom >= 28) | (k < 3)) & (x.c > x.ema(50)))


@strat("S088", "Quarter end window dressing", C, tfs=("1d",), hold=dict({"1d": 3}),
       parts=("window: March, June, September or December from day 26", "filter: close above EMA20 and 20 day return positive"),
       params={}, grid=())
def s088(x):
    q = np.isin(x.month, (3, 6, 9, 12)) & (x.dom >= 26)
    return E(q & (x.c > x.ema(20)) & (x.roc(20) > 0))


@strat("S089", "Thursday close drift into Friday", C, tfs=("1d",), hold=dict({"1d": 1}),
       parts=("setup: Thursday green close above EMA20", "exit: Friday"),
       params={}, grid=())
def s089(x):
    return (x.dow == 3) & (x.c > x.ema(20)) & (x.c > x.o)


@strat("S090", "Monday reversal after a weak Friday", C, tfs=("1d",), hold=dict({"1d": 3}),
       parts=("setup: Friday fell more than 1.5 percent", "trigger: Monday closes green"),
       params=dict(d=-0.015), grid=[dict(d=-0.01), dict(d=-0.025)])
def s090(x, d):
    return (x.dow == 0) & (sh(x.roc(1)) < d) & (x.c > x.o)


# ====================================================================== composite and multi timeframe
@strat("S091", "Kalman trend flip (analogue of the current QoR baseline)", M,
       parts=("filter: local linear trend Kalman filter on log price", "trigger: slope crosses above a small positive threshold"),
       params=dict(snr=0.02, hy=0.05), grid=[dict(snr=0.005, hy=0.05), dict(snr=0.05, hy=0.1)],
       note="Baseline. QoR's live Kalman flip lost all three of its first signals, so this is the bar to beat.")
def s091(x, snr, hy):
    lvl, slp = x.kalman(snr)
    thr = hy * x.atrp(14)
    return (slp > thr) & (sh(slp) <= sh(thr)) & (x.c > lvl)


@strat("S092", "Kalman flip with volume and VWAP or EMA20", M,
       parts=("trigger: Kalman slope positive and rising, close above the filter", "filter: volume above average, above VWAP (intraday) or EMA20 (daily)"),
       params=dict(snr=0.02), grid=[dict(snr=0.005)])
def s092(x, snr):
    lvl, slp = x.kalman(snr)
    ref = x.vwap() if x.intraday else x.ema(20)
    return E((slp > 0) & (slp > sh(slp)) & (x.c > lvl) & (x.v > x.vavg(20)) & (x.c > ref))


@strat("S093", "Heikin Ashi: three green bars with no lower wick", M,
       parts=("setup: red Heikin Ashi bar", "trigger: three green Heikin Ashi bars with no lower shadow"),
       params={}, grid=())
def s093(x):
    ho, hh, hl, hc = x.heikin()
    green = hc > ho
    flat = (ho - hl) <= 0.05 * (hh - hl + 1e-12)
    g = green & flat
    return E(g & shb(g) & shb(g, 2) & shb(hc < ho, 3))


@strat("S094", "Elder triple screen", M,
       parts=("slow screen: higher timeframe MACD histogram rising", "fast screen: Stochastic %K crosses %D from under 30"),
       params=dict(lv=30), grid=[dict(lv=40)])
def s094(x, lv):
    hf = x.htf(_htf_kind(x))
    hist = hf.f.macd()[2]
    slow = hf.at((hist > ind.shift(hist)).astype(float)) > 0
    k, d = x.stoch(14, 3, 3)
    return slow & X(k, d) & (sh(k) < lv)


@strat("S095", "Squeeze release with rising momentum", M,
       parts=("setup: Bollinger bands inside Keltner channel, then released", "trigger: momentum above zero and rising"),
       params={}, grid=())
def s095(x):
    mid, up, lo = x.bb(20, 2.0)
    kcu, kcl = x.ema(20) + 1.5 * x.atr(20), x.ema(20) - 1.5 * x.atr(20)
    sq = (lo > kcl) & (up < kcu)
    val = x.c - ((x.hhv(20, "h") + x.llv(20, "l")) / 2.0 + x.sma(20)) / 2.0
    mom = ind.linreg(val, 20)[2]
    release = shb(sq) & ~sq
    return E(roll_any(release, 3) & (mom > 0) & (mom > sh(mom)) & ~sq)


@strat("S096", "ConnorsRSI washout above SMA200", M,
       parts=("composite: RSI3, RSI2 of the up/down streak, 100 bar percent rank of the 1 bar return", "trigger: average under 10", "filter: close above SMA200"),
       params=dict(th=10), grid=[dict(th=5), dict(th=15)])
def s096(x, th):
    pr = ind.pct_rank(x.roc(1), 100)
    crsi = (x.rsi(3) + ind.rsi(x.streak(), 2) + pr) / 3.0
    return E((crsi < th) & (x.c > x.sma(200)))


@strat("S097", "Schaff trend cycle crosses 25", M,
       parts=("trigger: STC(23, 50, 10) crosses above 25", "filter: close above EMA100"),
       params=dict(lv=25), grid=[dict(lv=10)])
def s097(x, lv):
    return X(x.stc(), lv) & (x.c > x.ema(100))


@strat("S098", "Three of four vote: trend, momentum, volume, RSI band", M,
       parts=("votes: EMA20 > EMA50, 10 bar return > 0, volume above average, RSI14 between 50 and 70", "trigger: votes reach 3"),
       params=dict(k=3), grid=[dict(k=4)])
def s098(x, k):
    votes = ((x.ema(20) > x.ema(50)).astype(int) + (x.roc(10) > 0).astype(int)
             + (x.v > x.vavg(20)).astype(int) + ((x.rsi(14) > 50) & (x.rsi(14) < 70)).astype(int))
    return E(votes >= k)


@strat("S099", "Higher timeframe uptrend, RSI5 pullback recovery", M,
       parts=("filter: higher timeframe EMA20 above EMA50", "trigger: RSI5 crosses back above 30"),
       params=dict(lv=30), grid=[dict(lv=20), dict(lv=40)])
def s099(x, lv):
    hf = x.htf(_htf_kind(x))
    up = hf.at((hf.f.ema(20) > hf.f.ema(50)).astype(float)) > 0
    return up & X(x.rsi(5), lv)


@strat("S100", "Higher timeframe uptrend plus Donchian 20 breakout", M,
       parts=("filter: higher timeframe EMA20 above EMA50", "trigger: close above the prior 20 bar high on 1.2 times volume"),
       params=dict(n=20), grid=[dict(n=10), dict(n=30)])
def s100(x, n):
    hf = x.htf(_htf_kind(x))
    up = hf.at((hf.f.ema(20) > hf.f.ema(50)).astype(float)) > 0
    return E(up & (x.c > sh(x.hhv(n, "h"))) & (x.v > 1.2 * x.vavg(20)))
