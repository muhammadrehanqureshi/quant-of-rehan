"""Positive control: a series with a built in upward drift must make the gates pass.

Without this a pipeline that can never say yes would look just like an honest one that found nothing.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def test_drift_is_found_and_flat_noise_is_not(tmp_path):
    spec = importlib.util.spec_from_file_location("ms", ROOT / "tools" / "make_synthetic.py")
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    days = ms.sessions(3, 1)
    idx = ms.make_5m(days, 99, base=1000.0, vol=0.0009)
    br = idx["close"].pct_change().fillna(0).to_numpy()
    sets = {"drift": 0.00035, "flat": 0.0}
    result = {}
    for name, mu in sets.items():
        series = {"KMIALL": idx}
        for i, s in enumerate(["AAA", "BBB", "CCC"]):
            series[s] = ms.make_5m(days, 10 + i, base=50 + 20 * i, vol=0.0018, mu=mu, beta_series=br)
        data = tmp_path / name
        for s, df5 in series.items():
            for tf in ("1h", "1d"):
                d = ms.resample(df5, tf)
                (data / tf).mkdir(parents=True, exist_ok=True)
                d.to_csv(data / tf / f"{s}.csv", index=False, float_format="%.4f")
        env = dict(os.environ, GITHUB_ACTIONS="true", PYTHONPATH=str(ROOT))
        r = subprocess.run([sys.executable, "-m", "kmiall100.run", "--data", str(data), "--out", str(tmp_path / (name + "_res")),
                            "--tfs", "1h,1d", "--strategies", "S001,S005,S012,S017,S035,S047,S091,S098",
                            "--profiles", "atr,trail", "--min-trades", "30"],
                           env=env, capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, r.stderr[-500:]
        result[name] = pd.read_csv(tmp_path / (name + "_res") / "summary.csv")
    assert result["drift"]["passes"].sum() >= 5
    assert result["flat"]["passes"].sum() == 0
