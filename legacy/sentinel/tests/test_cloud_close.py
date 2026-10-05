"""
Tests for the cloud session-closer.

The closer's contract:
  * it refuses to close the book while the market is marked open
    (unless --force) - a mid-session close would price exits early;
  * exit pricing comes from a universe-projected feed poll, so an
    open position always closes at a real last price (never silently
    flat because the projection was empty);
  * every bookkeeping step is isolated: one failing step must not
    stop the next (the desktop close-out's standing rule).

All network and clock access is mocked; paths land in tmp_path.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import cloud_close_session as ccs

from psx_core import paths


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(paths, "DATA_DIR", data)
    return SimpleNamespace(data=data)


def _fake_snapshot(symbols):
    return {
        "quotes": {
            s: {"symbol": s, "price": 10.0 + i, "volume": 1000.0 + i,
                "trades": 10.0 + i, "status": "OPN"}
            for i, s in enumerate(symbols)
        }
    }


class TestMarketOpenGuard:
    def test_refuses_while_open(self, isolated, monkeypatch):
        from psx_core import sessions
        monkeypatch.setattr(sessions, "is_open", lambda now: True)
        rc = ccs.main(["--force"])  # --force overrides, must NOT refuse
        assert rc == 0

        called = {"n": 0}
        monkeypatch.setattr(
            ccs, "close_intraday_book",
            lambda d: called.update(n=called["n"] + 1),
        )
        # Without --force the guard fires before any bookkeeping.
        rc2 = ccs.main([])
        assert rc2 == 1
        assert called["n"] == 0


class TestExitPricing:
    def test_price_map_uses_universe_projection(self, isolated, monkeypatch):
        seen = {}

        def fake_build(market_data, symbols, market):
            seen["symbols"] = list(symbols)
            return _fake_snapshot(symbols[:3])

        monkeypatch.setattr(ccs.feed, "fetch_snapshot", lambda http, timeout: {})
        monkeypatch.setattr(ccs.feed, "build_universe_snapshot", fake_build)
        monkeypatch.setattr(
            ccs, "_universe", lambda: ["OGDC", "LUCK", "ENGRO", "FFC"]
        )
        prices = ccs._closing_price_map()
        # The projection received the full universe, not an empty list
        # (the empty-projection bug closed every position flat).
        assert seen["symbols"] == ["OGDC", "LUCK", "ENGRO", "FFC"]
        assert prices == {"OGDC": 10.0, "LUCK": 11.0, "ENGRO": 12.0}

    def test_feed_failure_returns_empty_map(self, isolated, monkeypatch):
        # v4.0.0: the feed is the broker socket; a failure surfaces as
        # feed.FeedError from fetch_snapshot. Patch at that boundary -
        # no network in unit tests.
        def boom(*a, **k):
            raise ccs.feed.FeedError("feed down")

        monkeypatch.setattr(ccs.feed, "fetch_snapshot", boom)
        assert ccs._closing_price_map() == {}


class TestStepIsolation:
    def test_failing_step_does_not_stop_the_next(self, isolated, monkeypatch):
        order = []
        monkeypatch.setattr(ccs, "close_intraday_book",
                            lambda d: order.append("close"))
        monkeypatch.setattr(ccs, "update_baselines",
                            lambda d: (_ for _ in ()).throw(RuntimeError("x")))
        monkeypatch.setattr(ccs, "refresh_regime_inputs",
                            lambda: order.append("regime"))
        monkeypatch.setattr(ccs, "label_outcomes",
                            lambda d: order.append("label"))
        rc = ccs.main(["--force"])
        assert rc == 0
        # close ran, baselines blew up, regime and label still ran.
        assert order == ["close", "regime", "label"]
