"""Shared fixtures: small synthetic PSX like series. Random walks only, no edge."""

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KMIALL_CLOUD", "1")        # the tests run in CI, the guard has its own test


def _load_tool():
    spec = importlib.util.spec_from_file_location("make_synthetic", ROOT / "tools" / "make_synthetic.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def synth_dir(tmp_path_factory):
    """Two stocks and the index, 2 years, written as data/<tf>/<SYMBOL>.csv."""
    tool = _load_tool()
    out = tmp_path_factory.mktemp("synth")
    days = tool.sessions(2, 1)
    idx5 = tool.make_5m(days, 99, base=1000.0, vol=0.0009)
    series = {"KMIALL": idx5}
    br = idx5["close"].pct_change().fillna(0).to_numpy()
    for i, s in enumerate(["AAA", "BBB"]):
        series[s] = tool.make_5m(days, 10 + i, base=50 + 20 * i, vol=0.0018, beta_series=br)
    for s, df5 in series.items():
        for tf in ("5m", "15m", "30m", "1h", "1d"):
            d = df5 if tf == "5m" else tool.resample(df5, tf)
            p = out / tf
            p.mkdir(parents=True, exist_ok=True)
            d.to_csv(p / f"{s}.csv", index=False, float_format="%.4f")
    return out


@pytest.fixture(scope="session")
def frames(synth_dir):
    """{tf: (stock arrays dict, index arrays dict)} read through the real loader."""
    from kmiall100 import data as D
    res = {}
    for tf in ("5m", "15m", "30m", "1h", "1d"):
        got = {}
        for src in D.discover(synth_dir):
            if src.tf != tf:
                continue
            for sym, df, _ in D.load_series(src, None):
                got[sym] = df
        res[tf] = got
    return res
