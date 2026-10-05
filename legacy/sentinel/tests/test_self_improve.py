"""
Tests for the self-improvement trigger (v0.12.3).

Contract:
  * counts valid labeled trades in the outcomes ledger;
  * stays dormant below MIN_LABELS and below STEP new-labels-since-last;
  * a successful dispatch is remembered in the marker (idempotent);
  * a failed dispatch leaves the marker untouched (retries next close);
  * without GITHUB_TOKEN/GITHUB_REPOSITORY it defers, never raises.
"""

from __future__ import annotations

import json

import pytest

import self_improve as si

from psx_core import paths


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    return data


def _write_labels(data, n: int) -> None:
    lines = [
        json.dumps({
            "trading_date": f"2026-09-{i % 28 + 1:02d}",
            "symbol": f"S{i:03d}",
            "entry_time": f"2026-09-{i % 28 + 1:02d}T05:0{i % 10}:00Z",
            "label": i % 2,
        })
        for i in range(n)
    ]
    (data / "outcomes.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def test_count_labels_counts_valid_rows(isolated):
    _write_labels(isolated, 7)
    (isolated / "outcomes.jsonl").open("a", encoding="utf-8").write(
        "{broken json\n"
    )
    assert si.count_labels() == 7


def test_dormant_below_first_threshold(isolated):
    _write_labels(isolated, si.MIN_LABELS - 1)
    fire, why = si.should_trigger()
    assert not fire
    assert "first sweep threshold" in why


def test_fires_at_threshold(isolated):
    _write_labels(isolated, si.MIN_LABELS)
    fire, _ = si.should_trigger()
    assert fire


def test_does_not_refire_below_step(isolated):
    _write_labels(isolated, si.MIN_LABELS)
    (isolated / si.MARKER).write_text(
        json.dumps({"labels": si.MIN_LABELS}), encoding="utf-8"
    )
    fire, why = si.should_trigger()
    assert not fire
    assert "new labels" in why


def test_refires_after_step_new_labels(isolated):
    _write_labels(isolated, si.MIN_LABELS + si.STEP)
    (isolated / si.MARKER).write_text(
        json.dumps({"labels": si.MIN_LABELS}), encoding="utf-8"
    )
    fire, _ = si.should_trigger()
    assert fire


def test_dispatch_without_token_defers(isolated):
    ok, msg = si.dispatch_workflow()
    assert not ok
    assert "no GITHUB_TOKEN" in msg


def test_maybe_trigger_marker_only_on_success(isolated, monkeypatch):
    _write_labels(isolated, si.MIN_LABELS)
    # Failing dispatch -> marker untouched, no exception.
    monkeypatch.setattr(
        si, "dispatch_workflow", lambda: (False, "HTTP 403")
    )
    fired, msg = si.maybe_trigger()
    assert not fired
    assert "deferred" in msg
    assert not (isolated / si.MARKER).exists()
    # Successful dispatch -> marker written with the label count.
    monkeypatch.setattr(
        si, "dispatch_workflow", lambda: (True, "dispatched")
    )
    fired, msg = si.maybe_trigger()
    assert fired
    marker = json.loads(
        (isolated / si.MARKER).read_text(encoding="utf-8")
    )
    assert marker["labels"] == si.MIN_LABELS
    # And it must not fire again immediately.
    fired2, _ = si.maybe_trigger()
    assert not fired2


def test_closer_wires_the_step(isolated, monkeypatch):
    # The cloud closer must include the self-improve step without
    # breaking when it defers (no token in the test env).
    import cloud_close_session as ccs

    from psx_core import sessions
    monkeypatch.setattr(sessions, "is_open", lambda now: False)
    for name in ("close_intraday_book", "update_baselines",
                 "refresh_regime_inputs", "label_outcomes"):
        monkeypatch.setattr(ccs, name, lambda *a, **k: None)
    assert ccs.main(["--force"]) == 0
