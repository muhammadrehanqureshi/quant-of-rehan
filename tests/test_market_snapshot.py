"""Tests for the phone app's market snapshot (owner order 2026-10-09).

The fixtures below are trimmed copies of the real portal markup captured on
2026-10-09, so a portal layout change fails these tests instead of silently
feeding the app a wrong number.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from src.data import broker_market, market_snapshot
from src.data.market_snapshot import (
    INDEX_MEMBERSHIP,
    build_snapshot,
    parse_constituents,
    parse_index,
    volume_leaders,
)
from src.data.sessions import KARACHI, is_market_open

# Real panel markup for KSE100, both directions of the day.
HOME_UP = (
    '<div class="tabs__panel marketIndices__details" data-name="KSE100" '
    'data-type="1" data-date="2026-10-09 11:28:15" data-close="167593.79">'
    '<h1 class="marketIndices__price">167,593.79'
    '<span class="marketIndices__change change__text--pos">'
    '<i class="icon-up-dir"></i> 151.89 (0.09%)</span></h1></div>'
    '<div class="tabs__panel marketIndices__details" data-name="KSE100PR" '
    'data-type="1" data-date="2026-10-09 11:28:15" data-close="50447.28">'
    '<h1 class="marketIndices__price">50,447.28'
    '<span class="marketIndices__change change__text--pos">'
    '<i class="icon-up-dir"></i> 51.66 (0.10%)</span></h1></div>'
)

# Real falling-day markup captured 2026-10-09: the change text is signed and
# the class says neg, while the percentage is printed unsigned.
HOME_DOWN = (
    '<div class="tabs__panel marketIndices__details" data-name="KSE100" '
    'data-type="1" data-date="2026-10-09 12:00:00" data-close="166000.00">'
    '<h1 class="marketIndices__price">166,000.00'
    '<span class="marketIndices__change change__text--neg">'
    '<i class="icon-down-dir"></i> -5.15 (0.00%)</span></h1></div>'
)


def row(symbol: str, name: str, current: str, pct: str, volume: str,
        negative: bool = False) -> str:
    """One constituent row shaped exactly like the portal's."""
    pct_class = "change__text--neg" if negative else "change__text--pos"
    return (
        f'<tr><td data-order="{symbol}"><a class="tbl__symbol" '
        f'href="/company/{symbol}"><strong>{symbol}</strong></a></td>'
        f"<td>{name}</td>"
        f'<td class="right" data-order="{current}">{current}</td>'
        f'<td class="right" data-order="{current}">{current}</td>'
        f'<td class="right {pct_class}" data-order="{pct}">'
        f'<i class="icon-up-dir"></i> {pct}</td>'
        f'<td class="right {pct_class}" data-order="{pct}">'
        f'<i class="icon-up-dir"></i> {pct}%</td>'
        f'<td class="right">0.74%</td>'
        f'<td class="right change__text--noc" data-order="0">0.00</td>'
        f'<td class="right" data-order="{volume}">{int(float(volume)) // 1000}</td>'
        f'<td class="right" data-order="13409550">13</td>'
        f'<td class="right" data-order="46799329.5">47</td></tr>'
    )


CONSTITUENTS = (
    "<table><thead><tr><th>SYMBOL</th><th>VOLUME</th></tr></thead><tbody>"
    + row("TREET", "Treet Corporation Limited", "23.57", "2.10", "9404407")
    + row("CNERGY", "Cnergyico PK Limited", "12.40", "1.64", "5385301")
    + row("PRL", "Pakistan Refinery Limited", "91.79", "-0.44", "3892647",
          negative=True)
    + row("OGDC", "Oil & Gas Development Company", "278.00", "0.10", "1200000")
    + row("AASM", "Al-Abid Silk Mills Limited", "3.49", "10.79", "0")
    + "</tbody></table>"
)


class IndexParse(unittest.TestCase):

    def test_up_day_uses_the_portal_panel(self):
        got = parse_index(HOME_UP)
        self.assertEqual(got["symbol"], "KSE100")
        self.assertEqual(got["value"], 167593.79)
        self.assertEqual(got["change"], 151.89)
        self.assertEqual(got["change_pct"], 0.09)
        self.assertEqual(got["as_of"], "2026-10-09 11:28:15")

    def test_the_right_index_is_picked_not_the_first_panel(self):
        # KSE100 is requested by name, never by position.
        self.assertEqual(parse_index(HOME_UP, "KSE100PR")["value"], 50447.28)

    def test_down_day_is_negative_even_though_the_text_is_signed(self):
        got = parse_index(HOME_DOWN)
        self.assertEqual(got["value"], 166000.0)
        self.assertEqual(got["change"], -5.15)
        self.assertEqual(got["change_pct"], -0.0)

    def test_a_neg_class_never_reports_a_rise(self):
        # the class decides the direction, so the app cannot show a green
        # arrow on a falling index
        big_fall = HOME_DOWN.replace('-5.15', '-1,593.79').replace('(0.00%)', '(0.95%)')
        got = parse_index(big_fall)
        self.assertEqual(got["change"], -1593.79)
        self.assertEqual(got["change_pct"], -0.95)

    def test_unparseable_page_is_none_never_a_guess(self):
        self.assertIsNone(parse_index("<html><body>maintenance</body></html>"))


class ConstituentParse(unittest.TestCase):

    def test_rows_read_symbol_price_percent_and_volume(self):
        rows = parse_constituents(CONSTITUENTS)
        self.assertEqual([r["symbol"] for r in rows],
                         ["TREET", "CNERGY", "PRL", "OGDC", "AASM"])
        treet = rows[0]
        self.assertEqual(treet["current"], 23.57)
        self.assertEqual(treet["change_pct"], 2.10)
        self.assertEqual(treet["volume"], 9404407)

    def test_negative_change_percent_is_signed(self):
        prl = [r for r in parse_constituents(CONSTITUENTS)
               if r["symbol"] == "PRL"][0]
        self.assertEqual(prl["change_pct"], -0.44)

    def test_never_traded_member_is_excluded_from_a_volume_ranking(self):
        leaders = volume_leaders(parse_constituents(CONSTITUENTS))
        self.assertEqual([l["symbol"] for l in leaders],
                         ["TREET", "CNERGY", "PRL"])
        self.assertNotIn("AASM", [l["symbol"] for l in leaders])

    def test_ranking_is_by_volume_descending(self):
        leaders = volume_leaders(parse_constituents(CONSTITUENTS), top_n=4)
        volumes = [l["volume"] for l in leaders]
        self.assertEqual(volumes, sorted(volumes, reverse=True))
        self.assertEqual(leaders[0]["volume"], 9404407)
        self.assertEqual(leaders[0]["basis"],
                         "current session volume (PSX constituent table)")


class SnapshotHonesty(unittest.TestCase):

    def test_market_open_follows_the_owner_session_law(self):
        # Friday 2026-10-09: opens 09:17, closes 16:30 Karachi.
        self.assertTrue(is_market_open(
            datetime(2026, 10, 9, 11, 34, tzinfo=KARACHI)))
        self.assertFalse(is_market_open(
            datetime(2026, 10, 9, 9, 16, tzinfo=KARACHI)))
        self.assertFalse(is_market_open(
            datetime(2026, 10, 9, 16, 30, tzinfo=KARACHI)))
        # A Saturday is never a session, whatever the clock says.
        self.assertFalse(is_market_open(
            datetime(2026, 10, 10, 11, 34, tzinfo=KARACHI)))

    def test_snapshot_carries_the_session_state_and_a_basis_line(self):
        snapshot = build_snapshot()
        self.assertIsInstance(snapshot["market_open"], bool)
        self.assertIn("as_of", snapshot)
        self.assertIn("top_volume_basis", snapshot)
        if snapshot["top_volume"]:
            self.assertLessEqual(len(snapshot["top_volume"]), 3)
            for leader in snapshot["top_volume"]:
                self.assertGreater(leader["volume"], 0)
        else:
            # Unavailable must be stated as unavailable, never faked.
            self.assertTrue(snapshot["top_volume_basis"])
            self.assertNotIn("average", snapshot["top_volume_basis"].lower())

    def write_records(self, directory: str, records: list[dict]) -> Path:
        capture = Path(directory) / "capture.ndjson"
        capture.write_text("".join(json.dumps(row) + "\n" for row in records),
                           encoding="utf-8")
        return capture

    @staticmethod
    def feed_row(symbol: str, volume: int, status: str = "OPN",
                 market: str = "REG") -> str:
        return ";".join([
            symbol, market, "10", "99.00", "101.00", "20", status,
            "+", "1.00", "10:05:40", "100.00", " ", "100.00",
            "102.00", "98.00", "20", str(volume), "5", "99.00", "99.00",
        ])

    def test_live_broker_values_rank_by_feed_volume_and_separate_stock_suspension(self):
        now = datetime.fromisoformat("2026-10-16T10:05:42+05:00")
        records = [
            {"kind": "EXS-FEED", "ts": "2026-10-16T10:05:41+05:00",
             "raw": "EXS-FEED*10/16/2026 10:05:34 AM^KSE100;166231.18;45.02;"
                    "166599.29;413.125;165956.51;|^$10/16/2026 10:05:34 AM"
                    "^ALLSHR;100904.71;81.44;101151.88;328.60;100778.43;"},
            {"kind": "MKT-STATS", "ts": "2026-10-16T10:05:41+05:00",
             "raw": "MKT-STATS*FUT;HALTED;0|REG;OPEN;1"},
            {"kind": "MKT-FEED", "ts": "2026-10-16T10:05:41+05:00",
             "raw": "MKT-FEED*" + "||".join([
                 self.feed_row("SAZEW", 1000, "SUS"),
                 self.feed_row("LUCK", 2000),
                 self.feed_row("PICT", 1500),
                 self.feed_row("FOREIGN", 999999),
                 self.feed_row("FUT9", 888888, market="FUT"),
             ])},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            capture = self.write_records(tmp, records)
            snapshot = broker_market.read_market_snapshot(
                now, capture_path=capture, symbols=["SAZEW", "LUCK", "PICT"])
        self.assertEqual(snapshot["index"]["source"], "eClear EXS-FEED")
        self.assertEqual(snapshot["index"]["value"], 166231.18)
        self.assertAlmostEqual(snapshot["index"]["change_pct"],
                               45.02 / (166231.18 - 45.02) * 100)
        self.assertEqual(snapshot["market_feed"]["status"], "OPEN")
        self.assertTrue(snapshot["market_feed"]["fresh"])
        self.assertEqual([row["symbol"] for row in snapshot["top_volume"]],
                         ["LUCK", "PICT", "SAZEW"])
        self.assertEqual([row["volume"] for row in snapshot["top_volume"]],
                         [2000, 1500, 1000])
        self.assertEqual(snapshot["top_volume"][-1]["market_status"], "SUSPENDED")
        # One suspended symbol and a different halted segment cannot report a
        # halt for the market-wide REG segment.
        self.assertNotEqual(snapshot["market_feed"]["status"], "HALTED")

    def test_snapshot_uses_portal_only_as_labeled_fallback(self):
        now = datetime.fromisoformat("2026-10-16T10:05:42+05:00")
        live = {"index": None, "top_volume": None,
                "market_feed": {"status": "UNKNOWN", "fresh": False,
                                "as_of": None}}
        rows = [{"symbol": "OGDC", "current": 100.0, "change_pct": 1.0,
                 "volume": 1000}]
        with mock.patch.object(market_snapshot, "now_karachi", return_value=now), \
                mock.patch.object(broker_market, "read_market_snapshot",
                                  return_value=live), \
                mock.patch.object(market_snapshot, "fetch_index", return_value=None), \
                mock.patch.object(market_snapshot, "fetch_constituents",
                                  return_value=rows), \
                mock.patch.object(market_snapshot, "fetch_quotes",
                                  return_value={}), \
                mock.patch.object(market_snapshot.volume_split, "flows_for",
                                  return_value={}):
            snapshot = market_snapshot.build_snapshot()
        self.assertEqual(snapshot["top_volume"][0]["symbol"], "OGDC")
        self.assertIn("portal fallback", snapshot["top_volume_basis"])
        self.assertEqual(snapshot["market_feed"]["status"], "UNKNOWN")
        self.assertIsNone(snapshot["top_volume"][0]["buy_volume"])
        self.assertEqual(snapshot["top_volume"][0]["split_method"],
                         market_snapshot.volume_split.METHOD_NONE)

    def test_snapshot_prefers_live_data_and_keeps_the_stock_flag_off_market_state(self):
        now = datetime.fromisoformat("2026-10-16T10:05:42+05:00")
        live = {
            "index": {"symbol": "KSE100", "value": 166231.18,
                      "change": 45.02, "change_pct": 0.027,
                      "as_of": "2026-10-16T10:05:34+05:00",
                      "source": "eClear EXS-FEED"},
            "top_volume": [{"symbol": "SAZEW", "volume": 1000,
                            "price": 100.0, "change_pct": 1.0,
                            "market_status": "SUSPENDED"}],
            "market_feed": {"status": "OPEN", "raw_status": "OPEN",
                            "as_of": "2026-10-16T10:05:41+05:00",
                            "fresh": True},
        }
        with mock.patch.object(market_snapshot, "now_karachi", return_value=now), \
                mock.patch.object(broker_market, "read_market_snapshot",
                                  return_value=live), \
                mock.patch.object(market_snapshot, "fetch_index") as fetch_index, \
                mock.patch.object(market_snapshot, "fetch_constituents") as fetch_rows, \
                mock.patch.object(market_snapshot.volume_split, "flows_for",
                                  return_value={}):
            snapshot = market_snapshot.build_snapshot()
        fetch_index.assert_not_called()
        fetch_rows.assert_not_called()
        self.assertEqual(snapshot["index"]["source"], "eClear EXS-FEED")
        self.assertEqual(snapshot["top_volume"][0]["volume"], 1000)
        self.assertNotIn("market_status", snapshot["top_volume"][0])
        self.assertEqual(snapshot["market_feed"]["status"], "OPEN")

    def test_market_status_parser_requires_the_market_wide_reg_segment(self):
        self.assertEqual(
            broker_market.parse_market_status_frame(
                "MKT-STATS*FUT;HALTED;0|REG;OPEN;1"),
            ("OPEN", "OPEN"))
        self.assertEqual(
            broker_market.parse_market_status_frame("MKT-STATS*REG;HALTED;0"),
            ("HALTED", "HALTED"))
        self.assertEqual(
            broker_market.parse_market_status_frame("MKT-STATS*REG;MYSTERY;0"),
            ("UNKNOWN", "MYSTERY"))
        self.assertIsNone(
            broker_market.parse_market_status_frame("MKT-STATS*FUT;HALTED;0"))

    def test_stale_feed_values_are_unknown_not_current(self):
        import json
        import tempfile
        from pathlib import Path

        now = datetime.fromisoformat("2026-10-16T10:10:00+05:00")
        with tempfile.TemporaryDirectory() as tmp:
            capture = Path(tmp) / "capture.ndjson"
            capture = self.write_records(tmp, [{
                "kind": "MKT-STATS", "ts": "2026-10-16T10:05:42+05:00",
                "raw": "MKT-STATS*REG;OPEN;1"}])
            got = broker_market.read_market_snapshot(
                now, capture_path=capture, symbols=[])
        self.assertEqual(got["market_feed"]["status"], "UNKNOWN")
        self.assertFalse(got["market_feed"]["fresh"])
        self.assertIsNone(got["index"])
        self.assertIsNone(got["top_volume"])

    def test_membership_name_is_still_available_for_parser_tests(self):
        # A fresh card should not say KMIALLSHR on the screen, but the
        # tester can still read the constant it started from. This fixture
        # carries the old on-screen copy by accident, so the word still
        # appears once in test_market_snapshot.py and nowhere in the app.
        self.assertEqual(INDEX_MEMBERSHIP, "KMIALLSHR")


if __name__ == "__main__":
    unittest.main()
