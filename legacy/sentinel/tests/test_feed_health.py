"""
Tests for the v0.20.4 feed-health gate (cloud_bot).

The contract:
  * a healthy synthetic snapshot passes;
  * every garbage signature is refused with a human-readable reason -
    coverage collapse, all-flat quotes (closed/stale page), too few
    live-priced instruments, stale receiveTime, missing stamp;
  * the Telegram alert fires ONCE per failure class per session
    (anti-spam) and never raises;
  * the alert file round-trips and prunes old sessions.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import psx_core.paths as paths
import cloud_bot


_MISSING = object()


def _snap(
    *,
    n=500,
    live=500,
    universe=530,
    stamp=_MISSING,
) -> dict:
    now = datetime.now(timezone.utc)
    snap = {
        "quotes": {
            f"S{i}": {
                "price": 10.0 + i,
                "volume": 1000.0 if i < live else 0.0,
                "high": 10.5,
            }
            for i in range(n)
        },
        "universeCount": universe,
    }
    if stamp is not _MISSING:
        snap["receiveTime"] = stamp
    else:
        snap["receiveTime"] = now.isoformat()
    return snap


@pytest.fixture
def alert_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cloud_bot, "_ALERT_FILE", tmp_path / "feed_alerts.json"
    )
    return tmp_path / "feed_alerts.json"


class TestFeedHealthGate:
    def test_healthy_snapshot_passes(self):
        ok, why = cloud_bot._feed_health(_snap())
        assert ok is True
        assert why == ""

    def test_coverage_collapse_refused(self):
        ok, why = cloud_bot._feed_health(_snap(n=100, universe=530))
        assert ok is False
        assert "coverage collapsed" in why

    def test_all_flat_quotes_refused(self):
        ok, why = cloud_bot._feed_health(_snap(live=0))
        assert ok is False
        assert "live-priced" in why

    def test_too_few_live_quotes_refused(self):
        ok, why = cloud_bot._feed_health(_snap(live=5))
        assert ok is False
        assert "live-priced" in why

    def test_stale_stamp_refused(self):
        old = (
            datetime.now(timezone.utc) - timedelta(minutes=45)
        ).isoformat()
        ok, why = cloud_bot._feed_health(_snap(stamp=old))
        assert ok is False
        assert "min old" in why

    def test_missing_stamp_refused(self):
        snap = _snap()
        del snap["receiveTime"]
        ok, why = cloud_bot._feed_health(snap)
        assert ok is False
        assert "receiveTime" in why

    def test_timezone_naive_stamp_accepted(self):
        """The feed has produced naive stamps historically - they must
        be read as UTC, not crash the gate."""
        naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        ok, _ = cloud_bot._feed_health(_snap(stamp=naive))
        assert ok is True


class TestFeedAlert:
    def test_alert_fires_once_per_class_per_session(
        self, alert_file, monkeypatch
    ):
        sent: list[str] = []
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: sent.append(msg) or True
        )
        cloud_bot._alert_feed("coverage collapsed: 1/530 quotes")
        cloud_bot._alert_feed("coverage collapsed: 2/530 quotes")
        cloud_bot._alert_feed("only 0 live-priced instruments")
        assert len(sent) == 2  # one per distinct class, not per pass
        state = json.loads(alert_file.read_text(encoding="utf-8"))
        assert len(state) == 1  # today's session key
        assert len(next(iter(state.values()))) == 2

    def test_alert_never_raises(self, alert_file, monkeypatch):
        def boom(msg):
            raise RuntimeError("telegram down")

        monkeypatch.setattr("notify.send_telegram", boom)
        cloud_bot._alert_feed("feed stamp 45 min old")  # must not raise
        # the class is still recorded so the failure stays reported-once
        state = json.loads(alert_file.read_text(encoding="utf-8"))
        assert len(next(iter(state.values()))) == 1

    def test_alert_file_prunes_old_sessions(self, alert_file, monkeypatch):
        monkeypatch.setattr(
            "notify.send_telegram", lambda msg: True
        )
        old_day = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).strftime("%Y-%m-%d")
        alert_file.write_text(
            json.dumps({old_day: ["old-class"]}), encoding="utf-8"
        )
        cloud_bot._alert_feed("fresh failure")
        state = json.loads(alert_file.read_text(encoding="utf-8"))
        assert old_day not in state
