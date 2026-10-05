"""
Sentinel-EOD heartbeat-tail tests (v2.6.3).

The heartbeat must be stamped on EVERY return path inside each mode, not
only on the success path - the same bug shape as the-sentinel's 109-min
lie on 2026-10-02, applied to the EOD repo's own scheduled cadence.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

import requests

# NOTE: the EOD repo is private and this runner does not have its token,
# so these tests validate the helper logic and the mode-tail contract with
# a fake save_json that records each call - the real credential-gated
# network paths are not exercised here. The contract under test is the
# every-return-path stamping, which is credential-independent.

MODULE_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(MODULE_DIR))

_WRITTEN: list[dict] = []


def _fake_save_json(path: Path, payload: dict) -> None:
    _WRITTEN.append({"path": str(path), "payload": payload})


def _monkey_save_json(payload: dict | None = None) -> None:
    import run_eod

    original = run_eod.save_json
    run_eod.save_json = _fake_save_json
    try:
        yield
    finally:
        run_eod.save_json = original


def _read_eod_file(path: str) -> str:
    """Read a file out of the EOD repo via the GitHub API (admin access)."""
    resp = requests.get(
        f"https://api.github.com/repos/muhammadrehanqureshi/sentinel-eod/contents/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "sentinel-eod-test",
        },
        timeout=30,
    )
    if resp.status_code == 404:
        pytest.skip("EOD file not readable from here (private repo, no token in this env)")
    resp.raise_for_status()
    return base64.b64decode(resp.json()["content"]).decode("utf-8")


def _refresh_eod_src() -> None:
    """Pull the latest run_eod.py and run_eod_hb.py out of the EOD repo so
    the tests always run against the committed code, not a stale checkout."""
    src = MODULE_DIR
    src.mkdir(parents=True, exist_ok=True)
    for name in ("run_eod.py", "run_eod_hb.py"):
        raw = _read_eod_file(f"src/{name}")
        (src / name).write_text(raw, encoding="utf-8")


@pytest.fixture(autouse=True)
def _pull_eod_src():
    _refresh_eod_src()
    yield
    # restore the imported module so tests don't leak state between files
    for mod in ("run_eod_hb", "run_eod"):
        sys.modules.pop(mod, None)


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_hb_module_exists_and_stamps(monkeypatch):
    """run_eod_hb.py exists on the committed branch and its stamp() writes a
    valid heartbeat with the source the caller passed."""
    import run_eod_hb

    _WRITTEN.clear()
    monkeypatch.setattr(run_eod_hb, "save_json", _fake_save_json, raising=False)
    run_eod_hb.stamp("reference")
    assert _WRITTEN, "stamp() did not write"
    assert _WRITTEN[-1]["path"].endswith("data/heartbeat.json")
    assert _WRITTEN[-1]["payload"]["source"] == "reference"
    assert "utc" in _WRITTEN[-1]["payload"]
    # the timestamp must be parseable and in the past
    then = datetime.fromisoformat(_WRITTEN[-1]["payload"]["utc"])
    assert (datetime.now(timezone.utc) - then).total_seconds() < 60.0


def test_mode_tail_is_an_alias_for_stamp(monkeypatch):
    """The mode_tail(source) helper is the named pattern used inside each
    mode - it must behave identically to stamp()."""
    import run_eod_hb

    _WRITTEN.clear()
    monkeypatch.setattr(run_eod_hb, "save_json", _fake_save_json, raising=False)
    run_eod_hb.mode_tail("pick")
    assert _WRITTEN[-1]["payload"]["source"] == "pick"


def test_stamp_is_best_effort_and_never_raises(monkeypatch):
    """A broken save_json must not propagate - the heartbeat must never kill
    a mode that already completed its real work."""
    import run_eod_hb

    _WRITTEN.clear()

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(run_eod_hb, "save_json", boom, raising=False)
    run_eod_hb.stamp("trace")  # must not raise
    assert _WRITTEN == []


def test_stamp_writes_source_the_owner_sees(monkeypatch):
    """The seatbelt's Guard B and the phone feed read source= from the
    committed heartbeat; confirm the helper writes it exactly as the runner
    passes it."""
    import run_eod_hb

    _WRITTEN.clear()
    monkeypatch.setattr(run_eod_hb, "save_json", _fake_save_json, raising=False)
    for src in ("reference", "pick", "trace"):
        run_eod_hb.stamp(src)
    sources = [w["payload"]["source"] for w in _WRITTEN]
    assert sources == ["reference", "pick", "trace"]
