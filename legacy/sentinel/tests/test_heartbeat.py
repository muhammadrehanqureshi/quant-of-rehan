"""
Tests for the pass heartbeat (src/heartbeat.py).

The heartbeat is the keeper's ground truth about cadence: it is
stamped only by a pass that actually polled the feed, checked exits
and decided - never by a skipped/duplicate run. Round-trip, tolerance
of a missing/corrupt file, and monotonic overwrite are pinned here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import heartbeat


NOW = datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc)


def test_stamp_then_read_age_roundtrip(tmp_path):
    path = tmp_path / "hb.json"
    heartbeat.stamp(path=path, now=NOW)
    age = heartbeat.read_age(path=path, now=NOW + timedelta(minutes=7))
    assert age is not None
    assert abs(age - 7.0) < 0.01


def test_read_age_missing_file_is_none(tmp_path):
    assert heartbeat.read_age(path=tmp_path / "nope.json", now=NOW) is None


def test_read_age_corrupt_file_is_none(tmp_path):
    path = tmp_path / "hb.json"
    path.write_text("{not json", encoding="utf-8")
    assert heartbeat.read_age(path=path, now=NOW) is None


def test_read_age_naive_timestamp_treated_as_utc(tmp_path):
    path = tmp_path / "hb.json"
    naive = NOW.replace(tzinfo=None).isoformat()
    path.write_text(f'{{"utc": "{naive}", "source": "t"}}', encoding="utf-8")
    age = heartbeat.read_age(path=path, now=NOW + timedelta(minutes=2))
    assert age is not None and abs(age - 2.0) < 0.01


def test_stamp_overwrites_with_newest(tmp_path):
    path = tmp_path / "hb.json"
    heartbeat.stamp(path=path, now=NOW - timedelta(minutes=30))
    heartbeat.stamp(path=path, now=NOW)
    age = heartbeat.read_age(path=path, now=NOW + timedelta(minutes=1))
    assert age is not None and age < 2.0
