"""The PC safety guard, the metrics, and one full run on tiny data."""

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _env(**extra):
    e = {k: v for k, v in os.environ.items() if k not in ("GITHUB_ACTIONS", "KMIALL_CLOUD", "KMIALL_ALLOW_LOCAL")}
    e.update(extra)
    e["PYTHONPATH"] = str(ROOT)
    return e


def test_runner_refuses_to_start_on_a_normal_pc(synth_dir, tmp_path):
    r = subprocess.run([sys.executable, "-m", "kmiall100.run", "--data", str(synth_dir), "--out", str(tmp_path / "o")],
                       env=_env(), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 3
    assert "REFUSED" in r.stderr and not (tmp_path / "o").exists()


def test_a_cloud_flag_on_the_command_line_does_not_exist(synth_dir, tmp_path):
    r = subprocess.run([sys.executable, "-m", "kmiall100.run", "--data", str(synth_dir), "--out", str(tmp_path / "o"),
                        "--allow-local"], env=_env(), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode != 0 and not (tmp_path / "o" / "summary.csv").exists()


def test_end_to_end_small_run(synth_dir, tmp_path):
    out = tmp_path / "res"
    r = subprocess.run([sys.executable, "-m", "kmiall100.run", "--data", str(synth_dir), "--out", str(out),
                        "--tfs", "30m,1d", "--strategies", "S001,S017,S035,S091,S079", "--min-trades", "10", "--grid"],
                       env=_env(GITHUB_ACTIONS="true"), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr[-800:]
    s = pd.read_csv(out / "summary.csv")
    assert set(s["id"]) == {"S001", "S017", "S035", "S091", "S079"}
    assert set(s["profile"]) == {"law", "atr", "trail"}
    assert (s["n"] > 0).all() and s["exp_net"].notna().all()
    meta = json.loads((out / "meta.json").read_text())
    assert meta["errors"] == 0 and meta["partial"] is False and "1d" in meta["index_found"]
    assert not (out / "errors.txt").read_text().strip()


def test_shards_split_the_strategies_without_overlap():
    sys.path.insert(0, str(ROOT))
    os.environ["KMIALL_CLOUD"] = "1"
    from kmiall100 import run
    parts = [set(run.pick_strategies("", (i, 7))) for i in range(7)]
    assert sum(len(p) for p in parts) == 100 and len(set().union(*parts)) == 100


def test_local_override_runs_one_core_at_lowest_priority(synth_dir, tmp_path):
    out = tmp_path / "loc"
    r = subprocess.run([sys.executable, "-m", "kmiall100.run", "--data", str(synth_dir), "--out", str(out),
                        "--tfs", "1d", "--strategies", "S001", "--min-trades", "5", "--profiles", "law"],
                       env=_env(KMIALL_ALLOW_LOCAL="1"), capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "mode=local" in r.stdout


def test_metrics_basic_numbers():
    sys.path.insert(0, str(ROOT))
    from kmiall100 import metrics as M
    n = 400
    ts = (np.datetime64("2022-01-03") + np.arange(n).astype("timedelta64[D]")).astype("datetime64[ns]").astype("int64")
    net = np.where(np.arange(n) % 2 == 0, 0.02, -0.01)
    r = M.summarize(ts, np.zeros(n, dtype=np.int16), net, np.where(net > 0, 0, 1).astype(np.int8), np.full(n, 3), 400, 100)
    assert abs(r["win_rate"] - 50.0) < 1e-9 and abs(r["exp_net"] - 0.5) < 1e-9
    assert abs(r["profit_factor"] - 2.0) < 1e-9 and abs(r["payoff"] - 2.0) < 1e-9
    assert abs(r["be_win_rate"] - 100 / 3) < 1e-6
    assert r["tp_rate"] == 50.0 and r["sl_rate"] == 50.0
    assert r["daily_n"] == 400 and abs(r["days_signal_pct"] - 100.0) < 1e-9
    assert r["passes"] == 1


def test_metrics_noise_does_not_pass():
    sys.path.insert(0, str(ROOT))
    from kmiall100 import metrics as M
    rng = np.random.default_rng(3)
    n = 3000
    ts = (np.datetime64("2021-01-04") + np.arange(n).astype("timedelta64[h]") * 7).astype("datetime64[ns]").astype("int64")
    net = rng.normal(0.0, 0.015, n)
    r = M.summarize(ts, np.zeros(n, dtype=np.int16), net, np.zeros(n, dtype=np.int8), np.ones(n), 900, 100)
    assert r["passes"] == 0
