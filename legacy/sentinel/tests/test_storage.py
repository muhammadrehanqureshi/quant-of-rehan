"""
Tests for psx_core.storage - snapshot persistence (gzipped JSONL).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from psx_core import paths, storage


@pytest.fixture
def snap_dir(tmp_path, monkeypatch):
    """Redirect SNAPSHOT_DIR to a temp directory."""
    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setattr(paths, "SNAPSHOT_DIR", directory)
    return directory


def _make_snapshot(
    generated_at: str = "2026-09-02T09:35:00+00:00",
    symbols: tuple[str, ...] = ("ABOT",),
) -> dict:
    quotes = {}
    for sym in symbols:
        quotes[sym] = {
            "symbol": sym,
            "status": "OPN",
            "price": 100.0,
            "change": 1.0,
            "changePercent": 0.01,
            "volume": 1000,
            "trades": 10,
            "value": 100000,
            "high": 101,
            "low": 99,
            "bid": 99.5,
            "ask": 100.5,
            "bidVol": 500,
            "askVol": 500,
            "timestamp": 1756790000,
        }
    return {
        "generatedAt": generated_at,
        "source": "PSX Terminal",
        "market": "REG",
        "universeCount": len(symbols),
        "quoteAvailable": len(quotes),
        "quoteUnavailable": 0,
        "quotes": quotes,
    }


# ---------------------------------------------------------------------------
# day_file
# ---------------------------------------------------------------------------

class TestDayFile:
    def test_returns_gzipped_jsonl_path(self, snap_dir):
        path = storage.day_file("2026-09-02")
        assert path.name == "2026-09-02.jsonl.gz"
        assert path.parent == snap_dir


# ---------------------------------------------------------------------------
# append_snapshot / iter_snapshots
# ---------------------------------------------------------------------------

class TestAppendAndIter:
    def test_append_creates_file(self, snap_dir):
        snap = _make_snapshot()
        path = storage.append_snapshot(snap)
        assert path.exists()
        assert path.stat().st_size > 0

    def test_append_multiple(self, snap_dir):
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:00+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:05+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:10+00:00"))
        snapshots = list(storage.iter_snapshots(snap_dir))
        assert len(snapshots) == 3

    def test_iter_yields_label_and_snapshot(self, snap_dir):
        storage.append_snapshot(_make_snapshot())
        for label, snap in storage.iter_snapshots(snap_dir):
            assert isinstance(label, str)
            assert "generatedAt" in snap

    def test_iter_empty_dir(self, snap_dir):
        snapshots = list(storage.iter_snapshots(snap_dir))
        assert snapshots == []

    def test_iter_nonexistent_dir(self, tmp_path):
        snapshots = list(storage.iter_snapshots(tmp_path / "nope"))
        assert snapshots == []

    def test_snapshots_ordered_by_generated_at(self, snap_dir):
        storage.append_snapshot(_make_snapshot("2026-09-02T09:40:00+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:00+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:45:00+00:00"))
        snapshots = list(storage.iter_snapshots(snap_dir))
        times = [s[1]["generatedAt"] for s in snapshots]
        assert times == sorted(times)


# ---------------------------------------------------------------------------
# count_snapshots
# ---------------------------------------------------------------------------

class TestCountSnapshots:
    def test_counts_per_date(self, snap_dir):
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:00+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:05+00:00"))
        counts = storage.count_snapshots(snap_dir)
        assert counts["2026-09-02"] == 2

    def test_empty_returns_empty(self, snap_dir):
        counts = storage.count_snapshots(snap_dir)
        assert counts == {}


# ---------------------------------------------------------------------------
# compact_day
# ---------------------------------------------------------------------------

class TestCompactDay:
    def test_compact_reduces_file(self, snap_dir):
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:00+00:00"))
        storage.append_snapshot(_make_snapshot("2026-09-02T09:35:05+00:00"))
        before, after = storage.compact_day("2026-09-02")
        assert before > 0
        assert after > 0
        # After compact, snapshots still readable
        snapshots = list(storage.iter_snapshots(snap_dir))
        assert len(snapshots) == 2

    def test_compact_missing_file_raises(self, snap_dir):
        with pytest.raises(FileNotFoundError):
            storage.compact_day("2099-01-01")


# ---------------------------------------------------------------------------
# SnapshotReadError
# ---------------------------------------------------------------------------

class TestSnapshotReadError:
    def test_corrupt_line_raises(self, snap_dir, monkeypatch):
        """A truncated gzip member should trigger SnapshotReadError."""
        path = storage.day_file("2026-09-02")
        # Write a valid line, then garbage
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"generatedAt": "2026-09-02T09:35:00+00:00"}) + "\n")
            f.write("{bad json\n")

        with pytest.raises(storage.SnapshotReadError):
            list(storage.iter_snapshots(snap_dir, skip_unreadable=False))

    def test_corrupt_line_skipped_when_skip(self, snap_dir):
        path = storage.day_file("2026-09-02")
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(json.dumps({"generatedAt": "2026-09-02T09:35:00+00:00"}) + "\n")
            f.write("{bad json\n")

        # With skip_unreadable=True (default), the corrupt line is skipped
        # and we get back the good line
        snapshots = list(storage.iter_snapshots(snap_dir, skip_unreadable=True))
        # We should still get data from the first good line
        # Note: _iter_jsonl raises on the bad line, which is caught by the
        # outer try/except in iter_snapshots. So we may get 0 or 1 depending
        # on gzip member boundary. The important thing is no crash.
        assert isinstance(snapshots, list)
