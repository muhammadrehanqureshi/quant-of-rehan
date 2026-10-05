"""
Tests for psx_core.feed - the market-feed contract.

v4.0.0: the feed is the ECLEAR broker (see psx_core.broker_feed for the
wire tests). This file pins the CONTRACT the rest of the bot holds:
quote schema, changePercent scale, universe projection, and the
FeedError rails (a degraded capture must never reach disk).
All offline; no network.
"""

from __future__ import annotations

import pytest

from psx_core import feed


def _quote(symbol: str = "ABOT", status: str = "OPN") -> dict:
    return {
        "market": "REG",
        "status": status,
        "symbol": symbol,
        "price": 100.5,
        "change": 1.5,
        "changePercent": 0.015,
        "volume": 1000.0,
        "trades": 50,
        "value": 100500.0,
        "high": 102.0,
        "low": 99.0,
        "bid": 100.4,
        "ask": 100.6,
        "bidVol": 200.0,
        "askVol": 150.0,
        "timestamp": 1756790000,
    }


# ---------------------------------------------------------------------------
# parse_number / parse_int (public helpers, kept for downstream imports)
# ---------------------------------------------------------------------------

class TestParseNumber:
    def test_none_returns_none(self):
        assert feed.parse_number(None) is None

    def test_null_string_returns_none(self):
        assert feed.parse_number("null") is None

    def test_nan_string_returns_none(self):
        assert feed.parse_number("NaN") is None

    def test_valid_number(self):
        assert feed.parse_number("12.5") == 12.5

    def test_non_finite_returns_none(self):
        assert feed.parse_number(float("inf")) is None

    def test_non_string_non_number_returns_none(self):
        assert feed.parse_number([1, 2]) is None


class TestParseInt:
    def test_none_returns_none(self):
        assert feed.parse_int(None) is None

    def test_valid_int(self):
        assert feed.parse_int("100") == 100

    def test_float_string_truncated(self):
        assert feed.parse_int("3.7") == 3


# ---------------------------------------------------------------------------
# normalize_change_percent - the scale contract
# ---------------------------------------------------------------------------

class TestNormalizeChangePercent:
    def test_none_returns_none(self):
        assert feed.normalize_change_percent(None) is None

    def test_zero_stays_zero(self):
        assert feed.normalize_change_percent(0.0) == 0.0

    def test_fraction_scaled_to_percent(self):
        assert feed.normalize_change_percent(0.00563) == pytest.approx(0.563)

    def test_negative_fraction(self):
        assert feed.normalize_change_percent(-0.01) == pytest.approx(-1.0)

    def test_max_circuit_breaker(self):
        assert feed.normalize_change_percent(0.1) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# build_universe_snapshot - the projection every consumer reads
# ---------------------------------------------------------------------------

class TestBuildUniverseSnapshot:
    def _make_market_data(self, symbols):
        return {
            "requestTime": "2026-09-25T10:00:00+00:00",
            "receiveTime": "2026-09-25T10:00:01+00:00",
            "bytes": 10000,
            "parser": "eclear-mkt-feed",
            "instruments": {s: _quote(s) for s in symbols},
            "index": {"symbol": "KSE100", "changePercent": 0.03},
        }

    def test_all_symbols_available(self):
        snap = feed.build_universe_snapshot(
            self._make_market_data(["ABOT", "MEBL"]), ["ABOT", "MEBL"]
        )
        assert snap["quoteAvailable"] == 2
        assert snap["quoteUnavailable"] == 0
        assert snap["universeCount"] == 2

    def test_missing_symbol_unavailable(self):
        snap = feed.build_universe_snapshot(
            self._make_market_data(["ABOT"]), ["ABOT", "MEBL"]
        )
        assert snap["quoteAvailable"] == 1
        assert "MEBL" in snap["quoteUnavailableSymbols"]

    def test_suspended_symbol_counted(self):
        market_data = self._make_market_data(["ABOT"])
        market_data["instruments"]["ABOT"]["status"] = "SUS"
        snap = feed.build_universe_snapshot(market_data, ["ABOT"])
        assert snap["quoteOpen"] == 0
        assert snap["quoteSuspended"] == 1

    def test_source_names_the_broker(self):
        snap = feed.build_universe_snapshot(
            self._make_market_data(["ABOT"]), ["ABOT"]
        )
        assert snap["source"] == "ECLEAR broker feed (read-only)"
        assert snap["parser"] == "eclear-mkt-feed"
        assert snap["market"] == "REG"

    def test_index_rides_through(self):
        snap = feed.build_universe_snapshot(
            self._make_market_data(["ABOT"]), ["ABOT"]
        )
        assert snap["index"]["symbol"] == "KSE100"

    def test_quote_schema_is_complete(self):
        snap = feed.build_universe_snapshot(
            self._make_market_data(["ABOT"]), ["ABOT"]
        )
        quote = snap["quotes"]["ABOT"]
        assert set(quote.keys()) == {
            "market", "status", "symbol", "price", "change",
            "changePercent", "volume", "trades", "value", "high",
            "low", "bid", "ask", "bidVol", "askVol", "timestamp",
        }


# ---------------------------------------------------------------------------
# fetch_snapshot - the rails
# ---------------------------------------------------------------------------

class TestFetchSnapshot:
    def test_rejects_non_reg_markets(self):
        with pytest.raises(feed.FeedError, match="not served"):
            feed.fetch_snapshot(None, market="FUT")

    def test_degenerate_capture_raises(self, monkeypatch):
        monkeypatch.setattr(feed.broker_feed, "fetch_shariah_symbols",
                            lambda: set())
        monkeypatch.setattr(feed.universe, "load",
                            lambda **kw: ["ABOT"])

        def tiny_snapshot(symbols, listen_seconds, min_instruments):
            return {
                "requestTime": "t", "receiveTime": "t", "bytes": 1,
                "parser": "eclear-mkt-feed",
                "instruments": {"ABOT": _quote()},
                "index": None,
            }

        monkeypatch.setattr(feed.broker_feed, "subscribe_snapshot",
                            tiny_snapshot)
        with pytest.raises(feed.FeedError, match="instruments"):
            feed.fetch_snapshot(None, min_instruments=350)

    def test_broker_error_wraps_as_feed_error(self, monkeypatch):
        monkeypatch.setattr(feed.broker_feed, "fetch_shariah_symbols",
                            lambda: set())
        monkeypatch.setattr(feed.universe, "load",
                            lambda **kw: ["ABOT"])

        def boom(symbols, listen_seconds, min_instruments):
            raise feed.broker_feed.BrokerFeedError("socket dead")

        monkeypatch.setattr(feed.broker_feed, "subscribe_snapshot", boom)
        with pytest.raises(feed.FeedError, match="socket dead"):
            feed.fetch_snapshot(None)

    def test_min_instruments_default_is_railed(self):
        # 200: lower than the psxterminal-era 350 because the broker
        # serves the shariah world (~350 names), not the whole market,
        # but high enough that a half-delivered burst never writes.
        assert feed.MIN_EXPECTED_INSTRUMENTS == 200
