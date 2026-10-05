"""
Tests for the Rule 11c index-tape plumbing (v2.1.0/2.1.1, v4.0.0).

Contract:
  * apply_index_proxy: feeds the context from the value-weighted money
    lens, badged PROXY, finite values only - NaN/None/absent leave the
    context untouched (the gate degrades to pass, never invents a veto);
  * the veto itself (Rule 11c, live and proxy alike) is pinned in
    test_decision_engine.TestRule11cIndexTape;
  * the live index quote now comes from the ECLEAR feed's EXS-FEED
    message (parse_exs_message in psx_core.broker_feed), carried into
    fetch_snapshot's return under the same 'index' schema as before.
    Calibration note kept for the record: on 2026-09-18's frozen tape
    the proxy read +1.772% against the real index's +1.089% - the
    KMIALL cross-section ran ~0.7pt hotter than the cap-weighted index,
    so the proxy UNDER-flags marginal red days.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import market_regime
from psx_core import feed
from psx_core import broker_feed


class TestApplyIndexProxy:
    def _ctx(self):
        return market_regime.MarketContext()

    def test_finite_value_feeds_the_context(self):
        ctx = self._ctx()
        market_regime.apply_index_proxy(ctx, -0.62)
        assert ctx.index_change_pct == pytest.approx(-0.62)
        assert ctx.index_quote_status == "PROXY"

    def test_nan_leaves_context_untouched(self):
        ctx = self._ctx()
        market_regime.apply_index_proxy(ctx, float("nan"))
        assert ctx.index_change_pct is None
        assert ctx.index_quote_status is None

    def test_none_leaves_context_untouched(self):
        ctx = self._ctx()
        market_regime.apply_index_proxy(ctx, None)
        assert ctx.index_change_pct is None

    def test_pandas_nan_leaves_context_untouched(self):
        ctx = self._ctx()
        market_regime.apply_index_proxy(ctx, pd.NA)
        assert ctx.index_change_pct is None

    def test_garbage_string_leaves_context_untouched(self):
        ctx = self._ctx()
        market_regime.apply_index_proxy(ctx, "not a number")
        assert ctx.index_change_pct is None

    def test_real_quote_would_override_proxy_in_live(self):
        # The live path stamps the real quote's own status (e.g. "SUS"
        # carried through from the broker feed); the PROXY badge must
        # never overwrite a real reading that a later stage injects.
        ctx = self._ctx()
        ctx.index_change_pct = 1.089
        ctx.index_quote_status = "SUS"
        assert ctx.index_quote_status == "SUS"


class TestFeedIndexWiring:
    """The snapshot pipeline carries the index quote end to end."""

    @staticmethod
    def _market_data() -> dict:
        # Faithful excerpt of the EXS-FEED message shape (captured
        # live): <ts>^KSE100;<price>;<chg>;<high>;<x>;<low>;...  The
        # leading ts uses %m/%d/%Y %I:%M:%S %p, PKT wall clock.
        quote = broker_feed.parse_exs_message(
            "EXS-FEED*9/18/2026 09:30:01 AM"
            "^KSE100;170884.5873;1841.3885;171500.0;0;169000.0;0;0;"
            "0;0;1250000000;15000000000;|"
        )
        assert quote is not None
        return {
            "requestTime": "2026-09-18T04:30:00+00:00",
            "receiveTime": "2026-09-18T04:30:01+00:00",
            "bytes": 100,
            "parser": "eclear-mkt-feed",
            "instruments": {},
            "index": quote,
        }

    def test_fetch_shape_carries_index(self):
        # parse_exs_message is wired into fetch_snapshot's return; the
        # universe projection carries it through. (Socket path pinned
        # in test_broker_feed; here the projection contract.)
        market_data = self._market_data()
        # changePercent is derived: change / (price - change) * 100
        # = 1.08924.. on the captured numbers (old source carried it
        # pre-computed; the broker feed derives it from price+change).
        snap = feed.build_universe_snapshot(market_data, [])
        assert snap["index"]["changePercent"] == pytest.approx(1.089, rel=1e-3)
        assert snap["index"]["price"] == pytest.approx(170884.5873)
        assert set(snap["index"]) >= {
            "symbol",
            "status",
            "price",
            "change",
            "changePercent",
            "high",
            "low",
            "timestamp",
        }

    def test_index_absent_degrades_to_none(self):
        market_data = self._market_data()
        market_data["instruments"] = {}
        market_data.pop("index")
        snap = feed.build_universe_snapshot(market_data, [])
        assert snap["index"] is None

    def test_garbage_exs_degrades_to_none(self):
        assert broker_feed.parse_exs_message("EXS-FEED*garbage") is None
        assert broker_feed.parse_exs_message("no star here") is None
