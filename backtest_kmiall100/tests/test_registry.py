"""The catalogue itself: 100 distinct, well formed, working strategies."""

import pathlib

import numpy as np
import pytest

from kmiall100 import data as D
from kmiall100.core import ALL_TFS, Ctx, Frame, REGISTRY
from kmiall100.strategies import REGISTRY as _R  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]
FAMILIES = {"Trend following", "Pullback in an uptrend", "Breakout and volatility", "Candlestick pattern",
            "Volume and money flow", "Intraday session", "Market index and relative strength", "Calendar",
            "Composite and multi timeframe"}


def test_exactly_100_ids_in_order():
    assert sorted(REGISTRY) == [f"S{i:03d}" for i in range(1, 101)]


def test_names_unique_and_documented():
    names = [s.name for s in REGISTRY.values()]
    assert len(set(names)) == 100
    for s in REGISTRY.values():
        assert s.parts, s.id                                   # every strategy lists its building blocks
        assert s.family in FAMILIES, (s.id, s.family)
        assert set(s.tfs) <= set(ALL_TFS), s.id
        for g in s.grid:
            assert set(g) <= set(s.params), (s.id, g)
        if s.hold:
            assert set(s.hold) <= set(ALL_TFS), s.id


def test_family_sizes():
    from collections import Counter
    c = Counter(s.family for s in REGISTRY.values())
    assert sum(c.values()) == 100 and set(c) == FAMILIES
    assert c["Trend following"] == 16 and c["Pullback in an uptrend"] == 18 and c["Breakout and volatility"] == 16


def _ctx(frames, tf, sym="AAA", with_index=True):
    df = frames[tf][sym]
    ts = df.index.to_numpy(dtype="datetime64[ns]")
    ix = None
    if with_index:
        a = D.align_index(ts, frames[tf]["KMIALL"])
        ix = Frame(a["open"], a["high"], a["low"], a["close"], a["volume"])
    return Ctx(ts, df["open"], df["high"], df["low"], df["close"], df["volume"], tf, ix)


@pytest.mark.parametrize("tf", ALL_TFS)
def test_all_strategies_run_and_return_boolean_arrays(frames, tf):
    x = _ctx(frames, tf)
    for sid, s in REGISTRY.items():
        if tf not in s.tfs:
            continue
        for p in [s.params] + [dict(s.params, **g) for g in s.grid]:
            sig = s.fn(x, **p)
            sig = np.asarray(sig)
            assert sig.dtype == bool and sig.shape == (x.n,), (sid, tf, p)


@pytest.mark.parametrize("tf", ["15m", "1d"])
def test_index_strategies_skip_quietly_when_there_is_no_index(frames, tf):
    x = _ctx(frames, tf, with_index=False)
    for sid, s in REGISTRY.items():
        if s.needs_index and tf in s.tfs:
            sig = np.asarray(s.fn(x, **s.params))
            assert sig.shape == (x.n,) and not sig.any(), sid


def test_no_strategy_is_dead_and_none_are_copies(frames):
    """Each one signals somewhere, and no two give the same signal array on the same data."""
    seen = {}
    dead = []
    for sid, s in REGISTRY.items():
        total = 0
        for tf in s.tfs:
            for sym in ("AAA", "BBB"):
                x = _ctx(frames, tf, sym)
                total += int(np.asarray(s.fn(x, **s.params)).sum())
        if total < 5:
            dead.append((sid, total))
    assert not dead, dead
    for tf in ("30m", "1d"):
        x = _ctx(frames, tf, "AAA")
        for sid, s in REGISTRY.items():
            if tf not in s.tfs:
                continue
            sig = np.asarray(s.fn(x, **s.params))
            if sig.sum() < 5:
                continue
            key = sig.tobytes()
            assert key not in seen or seen[key][0] != tf, f"{sid} duplicates {seen[key][1]} on {tf}"
            seen[key] = (tf, sid)


def test_no_em_or_en_dash_anywhere_in_the_kit():
    bad = []
    dashes = (chr(0x2014), chr(0x2013))
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in {".py", ".md", ".yml", ".yaml", ".txt", ".csv", ".json"} and ".git" not in p.parts \
                and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts:
            t = p.read_text(errors="ignore")
            if any(d in t for d in dashes):
                bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad
