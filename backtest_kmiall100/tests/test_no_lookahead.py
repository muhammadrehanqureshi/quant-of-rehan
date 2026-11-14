"""No strategy may use a bar that has not closed yet.

The method is a blackout test. Compute a strategy's signals on the real series.
Then pick a bar k, black out EVERYTHING after k (prices, volumes and the index
become NaN, the calendar stays), recompute, and demand identical signals for
every bar up to and including k. If a value at bar k had peeked at a later bar
(a negative shift, a day high that includes the rest of the day, an unfinished
higher timeframe bar, a centred window, an index value from a later bar) the
blacked out run cannot reproduce it and the test fails.

Cut points are chosen where the strategy actually signalled (a leak is visible
there) plus a few arbitrary bars in the second half of the series. Planted leaks
prove the check has teeth.
"""

import numpy as np
import pytest

from kmiall100 import data as D
from kmiall100 import ind
from kmiall100.core import Ctx, Frame, REGISTRY
from kmiall100.strategies import REGISTRY as _R  # noqa: F401

IDS = sorted(REGISTRY)
TFS = ["5m", "15m", "30m", "1h", "1d"]


def build(tf, df, idx_df, blackout_after=None):
    ts = df.index.to_numpy(dtype="datetime64[ns]")
    arr = {k: df[k].to_numpy(float).copy() for k in ("open", "high", "low", "close", "volume")}
    ix = None
    if idx_df is not None:
        a = D.align_index(ts, idx_df)
        ia = {k: a[k].to_numpy(float).copy() for k in ("open", "high", "low", "close", "volume")}
        if blackout_after is not None:
            for v in ia.values():
                v[blackout_after + 1:] = np.nan
        ix = Frame(ia["open"], ia["high"], ia["low"], ia["close"], ia["volume"])
    if blackout_after is not None:
        for v in arr.values():
            v[blackout_after + 1:] = np.nan
    return Ctx(ts, arr["open"], arr["high"], arr["low"], arr["close"], arr["volume"], tf, ix)


def pick_cuts(sig, x, n_mid=4):
    """Cuts where the strategy signalled (a leak shows there) plus mid session cuts on several days."""
    n = x.n
    lo = n // 2
    hits = np.flatnonzero(sig[lo: n - 5]) + lo
    cuts = []
    if len(hits):
        for q in (0.2, 0.5, 0.8):
            cuts.append(int(hits[int(q * (len(hits) - 1))]))
    days = len(x.day_start)
    fr = np.linspace(0.55, 0.95, n_mid)
    for q, f in zip(fr, np.linspace(0.3, 0.75, n_mid)):
        d = int(days * q)
        s0, e0 = x.day_start[d], x.day_end[d]
        cuts.append(int(s0 + max(0, int((e0 - s0) * f))))
    return sorted(set(cuts))


def violations(fn, tf, stock, idx, params=None, n_mid=4):
    full = build(tf, stock, idx)
    sig = np.asarray(fn(full, **(params or {})), dtype=bool)
    assert sig.shape == (full.n,)
    bad = []
    for k in pick_cuts(sig, full, n_mid):
        part = build(tf, stock, idx, blackout_after=k)
        sp = np.asarray(fn(part, **(params or {})), dtype=bool)
        if not np.array_equal(sp[: k + 1], sig[: k + 1]):
            d = np.flatnonzero(sp[: k + 1] != sig[: k + 1])
            bad.append((k, int(d[0]), len(d)))
    return bad


@pytest.mark.parametrize("tf", TFS)
def test_every_strategy_is_causal(frames, tf):
    stock, idx = frames[tf]["AAA"], frames[tf]["KMIALL"]
    bad = []
    for sid in IDS:
        s = REGISTRY[sid]
        if tf not in s.tfs:
            continue
        v = violations(s.fn, tf, stock, idx, s.params)
        if v:
            bad.append(f"{sid}: cut/first_diff/count {v[:3]}")
    assert not bad, "look ahead in: " + "; ".join(bad[:12])


@pytest.mark.parametrize("tf", ["15m", "1d"])
def test_grid_variants_are_causal_too(frames, tf):
    stock, idx = frames[tf]["BBB"], frames[tf]["KMIALL"]
    bad = []
    for sid in IDS:
        s = REGISTRY[sid]
        if tf not in s.tfs:
            continue
        for g in s.grid:
            v = violations(s.fn, tf, stock, idx, dict(s.params, **g))
            if v:
                bad.append(f"{sid} {g}: {v[:2]}")
    assert not bad, "look ahead in variants: " + "; ".join(bad[:12])


def test_negative_shift_is_refused():
    with pytest.raises(ValueError):
        ind.shift(np.arange(5.0), -1)


def test_planted_leaks_are_caught(frames):
    """Prove the check has teeth: deliberately leaky signals must all fail it."""
    stock, idx = frames["15m"]["AAA"], frames["15m"]["KMIALL"]

    def next_bar_up(x):                       # peeks one bar ahead
        return np.r_[x.c[1:] > x.c[:-1], False]

    def full_day_high(x):                     # the whole day's high is only known at the end of the day
        hi = np.fmax.reduceat(x.h, x.day_start)[x.day_id]
        return x.c >= hi * 0.996

    def centred_average(x):                   # a centred window uses future bars
        c = np.convolve(x.c, np.ones(5) / 5, mode="same")
        return x.c > c

    def tomorrows_close(x):                   # next trading day's close
        nxt = np.r_[x.c[x.day_end][1:], np.nan][x.day_id]
        return nxt > x.c * 1.002

    for fn in (next_bar_up, full_day_high, centred_average, tomorrows_close):
        assert violations(fn, "15m", stock, idx, n_mid=10), fn.__name__


def test_a_clean_signal_passes_the_same_check(frames):
    stock, idx = frames["15m"]["AAA"], frames["15m"]["KMIALL"]
    assert not violations(lambda x: x.c > x.ema(20), "15m", stock, idx)


def test_higher_timeframe_values_come_from_the_previous_group(frames):
    full = build("30m", frames["30m"]["AAA"], None)
    htf = full.htf("D")
    daily_close = htf.f.c
    proj = htf.at(daily_close)
    d = full.day_id
    for g in (5, 50, 120):                    # on day g the projected close is the close of day g - 1
        rows = np.flatnonzero(d == g)
        assert np.allclose(proj[rows], daily_close[g - 1])
    assert np.isnan(proj[np.flatnonzero(d == 0)]).all()


def test_index_alignment_never_looks_forward(frames):
    st = frames["15m"]["AAA"]
    ix = frames["15m"]["KMIALL"]
    a = D.align_index(st.index.to_numpy(dtype="datetime64[ns]"), ix)
    pos = ix.index.get_indexer(a.index, method="ffill")
    assert (ix.index[pos] <= a.index).all()


FORBIDDEN = ("shift(-", "np.roll", "reduceat", "bfill", ".iloc", "diff(-", "pct_change(-", "[::-1]", "center=True",
             "np.convolve", "arr[1:]", "[1:] >", "[:-1] <")


def test_static_scan_finds_no_future_peeking_idioms():
    """Second line of defence next to the blackout test: the strategy files may not use idioms that look ahead."""
    import pathlib
    here = pathlib.Path(__file__).resolve().parents[1] / "kmiall100"
    bad = []
    for name in ("strategies_1.py", "strategies_2.py"):
        for no, line in enumerate((here / name).read_text().splitlines(), 1):
            code = line.split("#")[0]
            for tok in FORBIDDEN:
                if tok in code:
                    bad.append(f"{name}:{no}: {tok}")
    assert not bad, bad
