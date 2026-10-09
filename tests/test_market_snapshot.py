"""Tests for the phone app's market snapshot (owner order 2026-10-09).

The fixtures below are trimmed copies of the real portal markup captured on
2026-10-09, so a portal layout change fails these tests instead of silently
feeding the app a wrong number.
"""

from __future__ import annotations

import unittest
from datetime import datetime

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
                         "current session volume (PSX KMIALLSHR constituents)")


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

    def test_membership_name_is_the_index_the_strategy_trades(self):
        self.assertEqual(INDEX_MEMBERSHIP, "KMIALLSHR")


if __name__ == "__main__":
    unittest.main()
