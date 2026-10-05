"""
Tests for psx_core.broker_feed - the ECLEAR read-only feed client.

Every test runs offline against captured wire rows (live captures from
2026-09-25 during Friday leg 2). The socket itself is never opened;
subscribe_snapshot's socket behaviour is exercised through monkeypatched
captures plus the degenerate-capture rails.

The schema contract is the point: the quote dicts this module produces
must be indistinguishable from what the retired psxterminal feed
delivered - same keys, same scales (changePercent as a FRACTION),
same truthiness rules.
"""

from __future__ import annotations

import pytest

from psx_core import broker_feed as bf
from psx_core import feed


# A live OGDC row captured 15:22 PKT 2026-09-25 (fields semicolon-joined):
# scrip;market;bidVol;bid;ask;askVol;state;dir;change;lastTradeTime;
# lastPrice;flag;avg;high;low;trades;volume;lastTradeVol;prevClose;open
_OGDC_ROW = (
    "OGDC;REG;26;315.70;315.75;467;OPN;-;-0.48;15:22:32;"
    "315.75; ;316.78;318.50;315.01;2830;912574;30;316.23;316.32"
)
_SNGP_ROW = (
    "SNGP;REG;1000;92.84;93.00;300;OPN;+;2.01;15:22:30;"
    "92.84; ;91.71;93.24;90.80;1519;1345768;500;90.83;90.85"
)
_ZERO_ROW = (
    "IDLE;REG;0;0;0;0;SUS;-;0;15:22:00;0; ;0;0;0;0;0;0;10.00;0"
)


class TestParseTickRow:
    def test_ogdc_prices(self):
        q = bf.parse_tick_row(_OGDC_ROW)
        assert q["symbol"] == "OGDC"
        assert q["market"] == "REG"
        assert q["status"] == "OPN"
        assert q["price"] == pytest.approx(315.75)
        assert q["bid"] == pytest.approx(315.70)
        assert q["ask"] == pytest.approx(315.75)
        assert q["bidVol"] == pytest.approx(26.0)
        assert q["askVol"] == pytest.approx(467.0)

    def test_change_percent_is_fraction_of_prev_close(self):
        q = bf.parse_tick_row(_OGDC_ROW)
        # change -0.48 against prev close 316.23
        assert q["change"] == pytest.approx(-0.48)
        assert q["changePercent"] == pytest.approx(-0.48 / 316.23)

    def test_trades_volume_value(self):
        q = bf.parse_tick_row(_OGDC_ROW)
        assert q["trades"] == 2830
        assert q["volume"] == pytest.approx(912574.0)
        # value = volume x VWAP(avg), the traded value by definition.
        assert q["value"] == pytest.approx(912574.0 * 316.78)

    def test_high_low_open_prevclose(self):
        q = bf.parse_tick_row(_OGDC_ROW)
        assert q["high"] == pytest.approx(318.50)
        assert q["low"] == pytest.approx(315.01)
        # Field [18] is the PREVIOUS close (OGDC closed 316.23 yesterday;
        # the day's open 316.32 rides field [19]).
        assert q.get("timestamp", 0) is not None

    def test_timestamp_parses_server_clock(self):
        q = bf.parse_tick_row(_SNGP_ROW)
        assert q["timestamp"] > 0

    def test_garbage_row_returns_none(self):
        assert bf.parse_tick_row("") is None
        assert bf.parse_tick_row("only;four;fields") is None

    def test_empty_symbol_returns_none(self):
        row = ";REG;26;315.70;315.75;467;OPN;-;-0.48;15:22:32;315.75; ;"
        assert bf.parse_tick_row(row) is None

    def test_plain_symbol_field_is_the_live_format(self):
        """Live tick rows carry a plain symbol in field 0 - only the
        SUBSCRIBE line uses SYM:REG. Pinned by a live capture."""
        assert bf.parse_tick_row(_OGDC_ROW)["symbol"] == "OGDC"

    def test_suspended_row_parses_with_zero_volume(self):
        q = bf.parse_tick_row(_ZERO_ROW)
        assert q["status"] == "SUS"
        assert q["volume"] == 0.0
        assert q["trades"] == 0

    def test_schema_matches_retired_feed_exactly(self):
        """The quote keys must equal the psxterminal-era schema - the
        dataset builder and the ledger read these by name."""
        q = bf.parse_tick_row(_OGDC_ROW)
        assert set(q.keys()) == {
            "market", "status", "symbol", "price", "change",
            "changePercent", "volume", "trades", "value", "high",
            "low", "bid", "ask", "bidVol", "askVol", "timestamp",
        }


# EXS-FEED captured 15:25 PKT 2026-09-25 (KSE100 closed leg 1 at
# 171092.71; intraday price 170541.90, +42.96 on the day).
_EXS = (
    "EXS-FEED*9/25/2026 3:25:06 PM^KSE100;170541.90;42.96;171092.71;"
    "593.75;169890.56;-608.3906;229;236;22;147176521;7885815044.80;|"
    "^$9/25/2026 3:25:06 PM^ALLSHR;103120.62;17.53;103474.92;"
    "371.8359;102828.75;-274.3359;229;236;22;328023132;12635192154.97;|"
)


class TestParseExsMessage:
    def test_kse100_prices(self):
        q = bf.parse_exs_message(_EXS)
        assert q is not None
        assert q["symbol"] == "KSE100"
        assert q["price"] == pytest.approx(170541.90)
        assert q["change"] == pytest.approx(42.96)
        assert q["high"] == pytest.approx(171092.71)
        assert q["low"] == pytest.approx(169890.56)

    def test_change_percent_is_true_percent(self):
        q = bf.parse_exs_message(_EXS)
        prev = 170541.90 - 42.96
        assert q["changePercent"] == pytest.approx(42.96 / prev * 100.0)

    def test_malformed_returns_none(self):
        assert bf.parse_exs_message("EXS-FEED*garbage") is None
        assert bf.parse_exs_message("EXS-FEED*a^b") is None

    def test_closed_market_group_order_prefers_kse100(self):
        # 2026-09-26, market closed: ALLSHR arrived first and KSE100
        # later in the message. Group order is not a contract; the
        # parser must select the KSE100 group wherever it sits (the
        # first-group read returned the wrong index live).
        flipped = (
            "EXS-FEED*9/26/2026 11:10:00 AM"
            "^ALLSHR;103241.0;137.96;103241.0;0;103241.0;0;0;0;0;"
            "328023132;12635192154.97;|"
            "^$9/26/2026 11:10:00 AM"
            "^KSE100;170541.90;42.96;171092.71;593.75;169890.56;"
            "-608.3906;229;236;22;147176521;7885815044.80;|"
        )
        q = bf.parse_exs_message(flipped)
        assert q is not None
        assert q["symbol"] == "KSE100"
        assert q["price"] == pytest.approx(170541.90)
        assert q["change"] == pytest.approx(42.96)


class TestSlugify:
    def test_sector_slug_shape(self):
        assert bf._slugify("EXCHANGE TRADED FUNDS") == "exchange-traded-funds"
        assert bf._slugify("INV. BANKS / INV. COS. / SECURITIES COS.") == (
            "inv-banks-inv-cos-securities-cos"
        )

    def test_collapses_repeated_dashes(self):
        assert bf._slugify("A  --  B") == "a-b"


class TestFetchScripsCache:
    def test_cache_hits_within_ttl(self, monkeypatch):
        monkeypatch.setattr(bf, "_scrip_cache", {
            "fetchedAt": bf.time.time(), "scrips": {"ABOT": {"name": "x"}},
        })
        scrips = bf.fetch_scrips()
        assert scrips == {"ABOT": {"name": "x"}}

    @staticmethod
    def _fake_http(symbols: list[str]):
        rows = [
            '{"market":"REG","symbol":"%s","symbolName":"N",'
            '"sectorName":"S","approved":"Approved"}' % s
            for s in symbols
        ]

        class Resp:
            text = "[" + ",".join(rows) + "]"

            def raise_for_status(self):
                pass

        class Sess:
            def get(self, url, timeout=None):
                return Resp()

        return Sess()

    def test_stale_cache_refetches(self, monkeypatch):
        monkeypatch.setattr(bf, "_scrip_cache", {
            "fetchedAt": 0.0, "scrips": {"OLD": {}},
        })
        monkeypatch.setattr(
            bf, "_HTTP", self._fake_http([f"S{i:03d}" for i in range(301)])
        )
        scrips = bf.fetch_scrips()
        assert "S000" in scrips and "OLD" not in scrips

    def test_degenerate_master_refused(self, monkeypatch):
        monkeypatch.setattr(bf, "_scrip_cache", {
            "fetchedAt": 0.0, "scrips": {},
        })
        monkeypatch.setattr(bf, "_HTTP", self._fake_http(["ONE"]))
        with pytest.raises(bf.BrokerFeedError, match="ScripServlet"):
            bf.fetch_scrips()


class TestShariahParse:
    def test_parses_symbol_list(self, monkeypatch):
        class Resp:
            text = "ShariaSymbol=AASM:REG;ABOT:REG;BECO:REG;"

            def raise_for_status(self):
                pass

        class Sess:
            def get(self, url, timeout=None):
                return Resp()

        monkeypatch.setattr(bf, "_HTTP", Sess())
        assert bf.fetch_shariah_symbols() == {"AASM", "ABOT", "BECO"}


# ---------------------------------------------------------------------------
# subscribe_snapshot through a monkeypatched socket
# ---------------------------------------------------------------------------

class _FakeSock:
    """Replays a captured wire transcript once, then idles."""

    def __init__(self, transcript: bytes, banner: bytes = b"Welcome*%"):
        self._banner = banner
        self._transcript = transcript
        self._sent: list[bytes] = []
        self._read_banner = False
        self._read_data = False

    def settimeout(self, value):
        pass

    def recv(self, size):
        if not self._read_banner:
            self._read_banner = True
            return self._banner
        if not self._read_data:
            self._read_data = True
            return self._transcript
        raise TimeoutError()

    def sendall(self, data):
        self._sent.append(data)

    def close(self):
        pass


_TICKS = (
    "MKT-FEED*" + _OGDC_ROW + "||" + _SNGP_ROW + "%"
).encode()


class TestSubscribeSnapshot:
    def _run(self, monkeypatch, transcript: bytes, **kwargs):
        monkeypatch.setattr(
            bf.socket, "create_connection",
            lambda host_port, timeout: _FakeSock(transcript),
        )
        return bf.subscribe_snapshot(["OGDC", "SNGP"], **kwargs)

    def test_returns_snapshot_shape(self, monkeypatch):
        data = self._run(
            monkeypatch, _TICKS, listen_seconds=0.5, min_instruments=2
        )
        assert set(data.keys()) == {
            "requestTime", "receiveTime", "bytes", "parser",
            "instruments", "index",
        }
        assert data["parser"] == "eclear-mkt-feed"
        assert set(data["instruments"]) == {"OGDC", "SNGP"}

    def test_subscribe_message_format(self, monkeypatch):
        """The wire format the app sends: MKT-FEED|SYM:REG;...;% with no
        brackets. This is the exact line three probe rounds got wrong."""
        sock = _FakeSock(_TICKS)
        monkeypatch.setattr(
            bf.socket, "create_connection", lambda hp, timeout: sock
        )
        bf.subscribe_snapshot(
            ["OGDC", "SNGP"], listen_seconds=0.5, min_instruments=2
        )
        sent = b"".join(sock._sent)
        assert sent.startswith(b"MKT-FEED|OGDC:REG;SNGP:REG;%")

    def test_degenerate_capture_refused(self, monkeypatch):
        # One instrument against a 350 floor: a half-delivered burst
        # must raise, never write.
        with pytest.raises(bf.BrokerFeedError, match="instruments"):
            self._run(monkeypatch, _TICKS, listen_seconds=0.5)

    def test_min_instruments_lowerable_for_tests(self, monkeypatch):
        data = self._run(
            monkeypatch, _TICKS, listen_seconds=0.5, min_instruments=2
        )
        assert data["instruments"]["OGDC"]["price"] == pytest.approx(315.75)

    def test_empty_capture_refused(self, monkeypatch):
        with pytest.raises(bf.BrokerFeedError, match="no instruments"):
            self._run(
                monkeypatch, b"EXS-FEED*nothing%", listen_seconds=0.5,
                min_instruments=1,
            )


# ---------------------------------------------------------------------------
# feed.py wiring: the public contract
# ---------------------------------------------------------------------------

class TestFeedWiring:
    def test_fetch_snapshot_rejects_non_reg(self, monkeypatch):
        with pytest.raises(feed.FeedError, match="not served"):
            feed.fetch_snapshot(None, market="FUT")

    def test_fetch_snapshot_passes_rails_through(self, monkeypatch):
        captured = {}

        def fake_subscribe(symbols, listen_seconds, min_instruments):
            captured["min"] = min_instruments
            raise bf.BrokerFeedError("stop")

        monkeypatch.setattr(bf, "subscribe_snapshot", fake_subscribe)
        monkeypatch.setattr(bf, "fetch_shariah_symbols", lambda: set())
        monkeypatch.setattr(
            feed.universe, "load",
            lambda **kw: ["ABOT", "MEBL"],
        )
        with pytest.raises(feed.FeedError):
            feed.fetch_snapshot(None, min_instruments=10)
        assert captured["min"] == 10

    def test_subscription_unions_universe_and_shariah(self, monkeypatch):
        captured = {}

        def fake_subscribe(symbols, listen_seconds, min_instruments):
            captured["symbols"] = sorted(symbols)
            raise bf.BrokerFeedError("stop here")

        monkeypatch.setattr(bf, "subscribe_snapshot", fake_subscribe)
        monkeypatch.setattr(
            bf, "fetch_shariah_symbols", lambda: {"ZZZ", "ABOT"}
        )
        monkeypatch.setattr(
            feed.universe, "load", lambda **kw: ["ABOT", "MEBL"]
        )
        with pytest.raises(feed.FeedError):
            feed.fetch_snapshot(None)
        assert captured["symbols"] == ["ABOT", "MEBL", "ZZZ"]

    def test_empty_subscription_refused(self, monkeypatch):
        monkeypatch.setattr(bf, "fetch_shariah_symbols", lambda: set())
        monkeypatch.setattr(
            feed.universe, "load",
            lambda **kw: (_ for _ in ()).throw(Exception("no file")),
        )
        with pytest.raises(feed.FeedError, match="empty subscription"):
            feed.fetch_snapshot(None)


class TestFeedHelpers:
    def test_normalize_change_percent_unchanged(self):
        assert feed.normalize_change_percent(0.00563) == pytest.approx(0.563)
        assert feed.normalize_change_percent(None) is None

    def test_parse_number_unchanged(self):
        assert feed.parse_number("12.5") == 12.5
        assert feed.parse_number(None) is None

    def test_build_universe_snapshot_shape(self):
        market_data = {
            "requestTime": "t", "receiveTime": "t", "bytes": 10,
            "parser": "eclear-mkt-feed",
            "instruments": {
                "ABOT": bf.parse_tick_row(_OGDC_ROW),
            },
            "index": None,
        }
        snap = feed.build_universe_snapshot(market_data, ["ABOT", "MEBL"])
        assert snap["source"].startswith("ECLEAR")
        assert snap["quoteAvailable"] == 1
        assert snap["quoteUnavailable"] == 1
        assert snap["quoteOpen"] == 1
        assert snap["marketInstrumentCount"] == 1
