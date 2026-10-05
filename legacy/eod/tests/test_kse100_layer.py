"""
Tests for the KSE-100 index layer (v2.2.5, v4.0.0).

The broker feed carries the real KSE-100 quote on the same socket as
the ticks (EXS-FEED message, verified live 2026-09-25 against the
psxterminal-era readings: KSE100 price=170884.5873, change=1841.3885).
Both bots now read it:

  * psx_core.broker_feed.parse_exs_message - parses the EXS-FEED form,
    best-effort (None on absent/malformed, never raises);
  * run_eod.kse100_change_pct - prefers the REAL index quote and falls
    back to the value-weighted cross-section proxy on older snapshots.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from psx_core import broker_feed, feed  # noqa: E402
from run_eod import kse100_change_pct  # noqa: E402


class TestExsIndexQuote:
    @staticmethod
    def _exs(extra_groups: str = "") -> str:
        # Faithful capture shape: <ts>^KSE100;<price>;<chg>;<high>;<x>;
        # <low>;... with further $-groups (ALLSHR etc.) after.
        return (
            "EXS-FEED*9/19/2026 09:30:01 AM"
            "^KSE100;170884.5873;1841.3885;171036.7156;0;169399.9898;"
            "0;0;0;0;1250000000;15000000000;|" + extra_groups
        )

    def test_parses_the_live_quote(self):
        q = broker_feed.parse_exs_message(self._exs())
        assert q is not None
        assert q["symbol"] == "KSE100"
        assert q["price"] == pytest.approx(170884.5873)
        # Derived: change / (price - change) * 100.
        assert q["changePercent"] == pytest.approx(1.089, rel=1e-3)
        assert q["high"] == pytest.approx(171036.7156)
        assert q["low"] == pytest.approx(169399.9898)

    def test_first_group_wins_over_later_index_groups(self):
        # The message packs several $-groups; KSE100 is always first.
        q = broker_feed.parse_exs_message(self._exs("$9/19/2026 09:30:01 AM^ALLSHR;105000.0;500.0;|"))
        assert q is not None
        assert q["symbol"] == "KSE100"
        assert q["price"] == pytest.approx(170884.5873)

    def test_absent_index_returns_none(self):
        assert broker_feed.parse_exs_message("<html></html>") is None

    def test_malformed_price_returns_none(self):
        assert broker_feed.parse_exs_message("EXS-FEED*garbage") is None

    def test_universe_snapshot_carries_index(self):
        market_data = {
            "requestTime": "2026-09-20T10:30:00+00:00",
            "receiveTime": "2026-09-20T10:30:01+00:00",
            "bytes": 100,
            "parser": "fast",
            "instruments": {},
            "index": {"symbol": "KSE100", "changePercent": 1.089},
        }
        snap = feed.build_universe_snapshot(market_data, [])
        assert snap["index"] == {"symbol": "KSE100", "changePercent": 1.089}


class TestKse100ChangePct:
    """The reader: real index quote first, cross-section proxy second."""

    def test_real_index_quote_wins(self):
        # The proxy would say +1.0% here; the real quote says -0.62% and
        # MUST win - the pick-time red-tape bar keys off the true index.
        snapshot = {
            "index": {"symbol": "KSE100", "changePercent": -0.62},
            "quotes": {
                "MEBL": {"value": 5.0e6, "changePercent": 0.01},
                "LUCK": {"value": 5.0e6, "changePercent": 0.01},
            },
        }
        assert kse100_change_pct(snapshot) == pytest.approx(-0.62)

    def test_proxy_fallback_without_index(self):
        # Older snapshots carry no index block: the value-weighted
        # cross-section proxy remains the honest estimate.
        snapshot = {
            "quotes": {
                "MEBL": {"value": 8.0e6, "changePercent": 0.02},
                "LUCK": {"value": 2.0e6, "changePercent": -0.01},
            }
        }
        # (8M * 2% + 2M * -1%) / 10M = +1.4%
        assert kse100_change_pct(snapshot) == pytest.approx(1.4)

    def test_none_when_neither_source_exists(self):
        assert kse100_change_pct({}) is None
        assert kse100_change_pct({"quotes": {}}) is None
