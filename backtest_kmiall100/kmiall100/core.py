"""Bar containers with cached indicators, session features, higher timeframe
projection, and the small helpers every strategy uses.

Rules this file enforces for every strategy:

* a signal at bar t may use bars 0..t only (``ind.shift`` refuses negative k);
* the trade is entered at the OPEN of bar t+1 (the engine does that, not the strategy);
* higher timeframe values are taken from the previous COMPLETED higher bar, so
  an unfinished hour or day can never leak in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from . import ind
from .ind import shift

np.seterr(invalid="ignore", divide="ignore")   # NaN warm-up bars compare False, quietly

TF_MIN = {"5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 1440}
BPD = {"5m": 75, "15m": 25, "30m": 12, "1h": 6, "1d": 1}
ALL_TFS = ("5m", "15m", "30m", "1h", "1d")
INTRA_TFS = ("5m", "15m", "30m", "1h")


# =============================================================== frames
class Frame:
    """OHLCV arrays plus a cache of indicators computed on demand."""

    def __init__(self, o, h, l, c, v):
        self.o, self.h, self.l, self.c, self.v = (np.array(a, dtype=float) for a in (o, h, l, c, v))
        self.n = len(self.c)
        self._m: Dict[tuple, object] = {}

    # ---- cache plumbing
    def m(self, key: tuple, fn: Callable):
        if key not in self._m:
            self._m[key] = fn()
        return self._m[key]

    def src(self, s):
        return {"o": self.o, "h": self.h, "l": self.l, "c": self.c, "v": self.v}[s] if isinstance(s, str) else s

    # ---- plain series
    def sma(self, n, s="c"):
        return self.m(("sma", n, s), lambda: ind.sma(self.src(s), n))

    def ema(self, n, s="c"):
        return self.m(("ema", n, s), lambda: ind.ema(self.src(s), n))

    def hhv(self, n, s="h"):
        return self.m(("hhv", n, s), lambda: ind.hhv(self.src(s), n))

    def llv(self, n, s="l"):
        return self.m(("llv", n, s), lambda: ind.llv(self.src(s), n))

    def vavg(self, n=20):
        return self.sma(n, "v")

    def tr(self):
        return self.m(("tr",), lambda: ind.tr(self.h, self.l, self.c))

    def atr(self, n=14):
        return self.m(("atr", n), lambda: ind.atr(self.h, self.l, self.c, n))

    def rsi(self, n=14):
        return self.m(("rsi", n), lambda: ind.rsi(self.c, n))

    def roc(self, n):
        return self.m(("roc", n), lambda: ind.roc(self.c, n))

    def zscore(self, n=20):
        return self.m(("z", n), lambda: ind.zscore(self.c, n))

    def macd(self, f=12, s=26, g=9):
        return self.m(("macd", f, s, g), lambda: ind.macd(self.c, f, s, g))

    def bb(self, n=20, k=2.0):
        return self.m(("bb", n, k), lambda: ind.bbands(self.c, n, k))

    def stoch(self, n=14, ks=3, d=3):
        return self.m(("stoch", n, ks, d), lambda: ind.stoch(self.h, self.l, self.c, n, ks, d))

    def willr(self, n=14):
        return self.m(("willr", n), lambda: ind.willr(self.h, self.l, self.c, n))

    def cci(self, n=20):
        return self.m(("cci", n), lambda: ind.cci(self.h, self.l, self.c, n))

    def adx(self, n=14):
        return self.m(("adx", n), lambda: ind.adx(self.h, self.l, self.c, n))

    def aroon(self, n=25):
        return self.m(("aroon", n), lambda: ind.aroon(self.h, self.l, n))

    def vortex(self, n=14):
        return self.m(("vortex", n), lambda: ind.vortex(self.h, self.l, self.c, n))

    def hma(self, n=21):
        return self.m(("hma", n), lambda: ind.hma(self.c, n))

    def linreg(self, n=30):
        return self.m(("linreg", n), lambda: ind.linreg(self.c, n))

    def obv(self):
        return self.m(("obv",), lambda: ind.obv(self.c, self.v))

    def cmf(self, n=20):
        return self.m(("cmf", n), lambda: ind.cmf(self.h, self.l, self.c, self.v, n))

    def adl(self):
        return self.m(("adl",), lambda: ind.adline(self.h, self.l, self.c, self.v))

    def mfi(self, n=14):
        return self.m(("mfi", n), lambda: ind.mfi(self.h, self.l, self.c, self.v, n))

    def force(self, n=13):
        return self.m(("force", n), lambda: ind.force_index(self.c, self.v, n))

    def eom(self, n=14):
        return self.m(("eom", n), lambda: ind.ease_of_movement(self.h, self.l, self.v, n))

    def supertrend(self, n=10, mult=3.0):
        return self.m(("st", n, mult), lambda: ind.supertrend(self.h, self.l, self.c, n, mult))

    def psar(self, af0=0.02, step=0.02, mx=0.2):
        return self.m(("psar", af0, step, mx), lambda: ind.psar(self.h, self.l, af0, step, mx))

    def kalman(self, snr=0.02):
        return self.m(("kalman", snr), lambda: ind.kalman(self.c, snr))

    def heikin(self):
        return self.m(("ha",), lambda: ind.heikin(self.o, self.h, self.l, self.c))

    def streak(self):
        return self.m(("streak",), lambda: ind.streak(self.c))

    def stc(self):
        return self.m(("stc",), lambda: ind.stc(self.c))

    def ich(self):
        return self.m(("ich",), lambda: ind.ichimoku(self.h, self.l, self.c))

    # ---- candle anatomy
    def body(self):
        return self.m(("body",), lambda: np.abs(self.c - self.o))

    def rng(self):
        return self.m(("rng",), lambda: self.h - self.l)

    def lower_wick(self):
        return self.m(("lw",), lambda: np.minimum(self.o, self.c) - self.l)

    def upper_wick(self):
        return self.m(("uw",), lambda: self.h - np.maximum(self.o, self.c))

    def ibs(self):
        def f():
            with np.errstate(divide="ignore", invalid="ignore"):
                r = (self.c - self.l) / (self.h - self.l)
            return np.where(self.h > self.l, r, 0.5)
        return self.m(("ibs",), f)

    def atrp(self, n=14):
        return self.m(("atrp", n), lambda: self.atr(n) / self.c)


# =============================================================== context
class Ctx(Frame):
    """A Frame plus time of day features, the market index, and higher timeframes."""

    def __init__(self, ts, o, h, l, c, v, tf: str, index: Optional[Frame] = None):
        super().__init__(o, h, l, c, v)
        self.ts = np.asarray(ts, dtype="datetime64[ns]")
        self.tf = tf
        self.tfmin = TF_MIN[tf]
        self.ix = index
        self.intraday = tf != "1d"
        d = self.ts.astype("datetime64[D]")
        new = np.r_[True, d[1:] != d[:-1]]
        self.day_id = np.cumsum(new) - 1
        self.day_start = np.flatnonzero(new)
        self.day_end = np.r_[self.day_start[1:] - 1, self.n - 1]
        self.bar_in_day = np.arange(self.n) - self.day_start[self.day_id]
        self.is_eod = np.zeros(self.n, dtype=bool)
        self.is_eod[self.day_end] = True
        days = d.astype("int64")
        self.dow = (days + 3) % 7                      # Monday = 0
        dt = pd.DatetimeIndex(self.ts)
        self.month = dt.month.to_numpy()
        self.dom = dt.day.to_numpy()
        self.bpd = BPD[tf]                                  # nominal bars per session, fixed per timeframe
        self.mins_open = self.bar_in_day * self.tfmin

    # ---- by day helpers (all causal: running values or previous completed days)
    def _day_agg(self, fn):
        return fn

    def day_open(self):
        return self.m(("day_open",), lambda: self.o[self.day_start][self.day_id])

    def day_hi_sofar(self):
        return self.m(("dhi",), lambda: pd.Series(self.h).groupby(self.day_id).cummax().to_numpy())

    def day_lo_sofar(self):
        return self.m(("dlo",), lambda: pd.Series(self.l).groupby(self.day_id).cummin().to_numpy())

    def prev_day(self, which: str):
        """High, low or close of the previous completed trading day (NaN on day one)."""
        def f():
            if which == "h":
                a = np.maximum.reduceat(self.h, self.day_start)
            elif which == "l":
                a = np.minimum.reduceat(self.l, self.day_start)
            else:
                a = self.c[self.day_end]
            prev = np.r_[np.nan, a[:-1]]
            return prev[self.day_id]
        return self.m(("pd", which), f)

    def vwap(self):
        def f():
            tp = (self.h + self.l + self.c) / 3.0
            num = ind.day_cum(tp * self.v, self.day_id)
            den = ind.day_cum(self.v, self.day_id)
            with np.errstate(divide="ignore", invalid="ignore"):
                return np.where(den > 0, num / den, self.c)
        return self.m(("vwap",), f)

    def gap(self):
        """Today's open versus the previous close, known from the first bar of the day."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return self.m(("gap",), lambda: self.day_open() / self.prev_day("c") - 1.0)

    def or_level(self, minutes: int, which: str):
        """Opening range high or low, NaN until the opening range is complete."""
        nb = max(1, int(round(minutes / self.tfmin)))

        def f():
            out = np.full(self.n, np.nan)
            src = self.h if which == "h" else self.l
            red = np.max if which == "h" else np.min
            for s, e in zip(self.day_start, self.day_end):
                if e - s + 1 >= nb:
                    lvl = red(src[s:s + nb])
                    out[s + nb - 1:e + 1] = lvl      # known once the last opening bar has closed
            return out
        return self.m(("or", nb, which), f)

    def or_bars(self, minutes: int) -> int:
        return max(1, int(round(minutes / self.tfmin)))

    def by_day_run(self, x, kind):
        """Running max or min of x inside the day."""
        s = pd.Series(x).groupby(self.day_id)
        return (s.cummax() if kind == "max" else s.cummin()).to_numpy()

    def once_a_day(self, mask):
        """Keep only the first True of each trading day."""
        m = np.asarray(mask, dtype=bool)
        cs = pd.Series(m.astype(int)).groupby(self.day_id).cumsum().to_numpy()
        return m & (cs == 1)

    # ---- higher timeframe: previous completed group only
    def htf(self, kind: str) -> "HTF":
        return self.m(("htf", kind), lambda: HTF(self, kind))


class HTF:
    """Aggregate bars into hours, days or weeks and project them back, one group late."""

    def __init__(self, c: Ctx, kind: str):
        if kind == "H":
            k = max(1, 60 // c.tfmin)
            key = c.day_id * 1000 + c.bar_in_day // k
        elif kind == "D":
            key = c.day_id
        elif kind == "W":
            days = c.ts.astype("datetime64[D]").astype("int64")
            key = (days + 3) // 7
        else:
            raise ValueError(kind)
        change = np.r_[True, key[1:] != key[:-1]]
        self.gid = np.cumsum(change) - 1
        st = np.flatnonzero(change)
        en = np.r_[st[1:] - 1, c.n - 1]
        self.f = Frame(c.o[st], np.maximum.reduceat(c.h, st), np.minimum.reduceat(c.l, st), c.c[en],
                       np.add.reduceat(c.v, st))
        self.n = c.n

    def at(self, arr_h) -> np.ndarray:
        """Project an array computed on the higher bars onto the base bars (previous group)."""
        prev = self.gid - 1
        out = np.full(self.n, np.nan)
        ok = prev >= 0
        out[ok] = np.asarray(arr_h, dtype=float)[prev[ok]]
        return out


# =============================================================== signal helpers
def X(a, b):
    """a crosses above b on this bar."""
    a = np.asarray(a, dtype=float)
    b = a * 0 + b if np.isscalar(b) else np.asarray(b, dtype=float)
    with np.errstate(invalid="ignore"):
        return (a > b) & (shift(a) <= shift(b))


def E(mask):
    """First True of each run: turns a state into an event."""
    m = np.asarray(mask, dtype=bool)
    p = np.r_[False, m[:-1]]
    return m & ~p


def sh(x, k=1):
    return shift(np.asarray(x, dtype=float), k)


def gt(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a) > np.asarray(b)


def lt(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a) < np.asarray(b)


def ge(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a) >= np.asarray(b)


def le(a, b):
    with np.errstate(invalid="ignore"):
        return np.asarray(a) <= np.asarray(b)


def shb(mask, k=1):
    """A boolean series k bars ago."""
    m = np.asarray(mask, dtype=bool)
    out = np.zeros(len(m), dtype=bool)
    if k < len(m):
        out[k:] = m[:-k] if k else m
    return out


def roll_any(mask, n):
    """True if mask was True at any of the last n bars (including this one)."""
    return pd.Series(np.asarray(mask, dtype=float)).rolling(n, min_periods=1).max().to_numpy() > 0


def roll_all(mask, n):
    return pd.Series(np.asarray(mask, dtype=float)).rolling(n, min_periods=n).min().to_numpy() > 0


# =============================================================== registry
@dataclass
class Strat:
    id: str
    name: str
    family: str
    fn: Callable
    tfs: Tuple[str, ...]
    parts: Tuple[str, ...]
    params: dict
    grid: Tuple[dict, ...]
    overnight: bool = False
    needs_index: bool = False
    hold: Optional[dict] = None
    note: str = ""


REGISTRY: Dict[str, Strat] = {}


def strat(sid, name, family, tfs=ALL_TFS, parts=(), params=None, grid=(), overnight=False,
          needs_index=False, hold=None, note=""):
    def deco(fn):
        assert sid not in REGISTRY, sid
        REGISTRY[sid] = Strat(sid, name, family, fn, tuple(tfs), tuple(parts), dict(params or {}),
                              tuple(grid), overnight, needs_index, hold, note)
        return fn
    return deco
