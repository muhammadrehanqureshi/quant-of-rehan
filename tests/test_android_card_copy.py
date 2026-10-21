"""Owner-ordered copy and money-line rules for the phone's market card.

Owner order 2026-10-12: the three volume leaders each read on two lines. The
first line is the rank, the symbol and the volumes; the second is the money
line, "PKR 12.52" followed by the day's change. The owner was seeing the
currency label stranded at the end of the first line with the price wrapped
below it, so the label and the number are now welded together and a narrow
screen cannot split them again. The up and down arrows carry exactly one
space before them on the index line and on every leader line, and the scan
cadence is stated in the owner's own words: "when the market is
open", not "during market open".

Owner order 2026-10-13: the volumes are bracketed as one group. "(" opens at
the B indicator (or at the exchange's total when the relay sent no split) and
")" closes after the T volume, and the ticker keeps exactly one space before
the group.

Owner order 2026-10-13 (third note): that sentence leaves the market card's
foot and stands below the last diamond rule; the fifth note sets the gap
above it to the layout's 12dp, the grid's own unit. The
wording itself is untouched, which is what this file still guards character
for character; tests/test_android_app_ui.py owns where it now stands.

The app has no Java test runner in this repository (it is built with aapt2
and D8, see android/README.md), so these assertions read the two source files
that ship the contract. That is deliberate: the order is about the exact
characters a narrow screen will show, so the check is against the characters
themselves, not against a simulation of the layout.
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
        / "quantofrehan" / "MainActivity.java")
STRINGS = (ROOT / "android" / "app" / "src" / "main" / "res" / "values"
           / "strings.xml")
LAYOUT = (ROOT / "android" / "app" / "src" / "main" / "res" / "layout"
          / "activity_main.xml")

# Owner order 2026-10-21 (v1.8.2): the quant also scans the market's own
# pre-market and post-market windows on the live broker feed, superseding the
# 2026-10-11 watch-only rule; the owner's sentence names them.
CADENCE = ("Quant will be scanning the market every second "
           "when the market is open, "
           "and in the pre-market and post-market windows too.")
DISPLAY_CADENCE = 1000


class FooterContractTest(unittest.TestCase):
    def test_strategy_footer_states_the_one_second_cadence(self):
        """Owner order 2026-10-19: 30 seconds became one second.

        The sentence is the scanner's own cadence again, so it and
        config.SCAN_INTERVAL_SECONDS cannot drift apart: both are one second.
        """
        source = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 1)',
                      source)
        self.assertIn(CADENCE, STRINGS.read_text(encoding="utf-8"))
        self.assertNotIn("every 30 seconds", STRINGS.read_text(encoding="utf-8"))

    def test_market_card_poll_is_one_second_and_separate_from_strategy_scan(self):
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("static final long DISPLAY_REFRESH_MS = FAST_POLL_MS;",
                      watcher)
        self.assertIn("Market market = fetchMarket(c, base);", watcher[
            watcher.index("static void fetchLive("):])
        self.assertIn("? Watcher.FAST_POLL_MS : Watcher.REFRESH_MS", main)
        self.assertIn("this is a display read, not a strategy scan", watcher.lower())
        self.assertIn("five minutes old", watcher.lower())

    def test_settings_hint_is_plain_and_promises_no_poll_cadence(self):
        """Owner order 2026-10-19: no token, no feed jargon, no cadence claim."""
        text = STRINGS.read_text(encoding="utf-8")
        hint = text.split('name="settings_hint">', 1)[1].split("</string>", 1)[0]
        self.assertIn("reads the relay by itself", hint)
        self.assertNotIn("every 30 seconds", hint)
        self.assertNotIn("every second", hint)
        self.assertNotIn("token", hint.lower())

    def test_settings_heading_is_centered_in_its_tile(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        heading = layout.split('android:id="@+id/settings_heading"', 1)[1].split(
            'android:text="@string/label_settings"', 1)[0]
        self.assertIn('android:gravity="center"', heading)
        self.assertIn('android:layout_width="match_parent"', heading)


class CadenceSentenceTest(unittest.TestCase):
    """The owner's sentence, character for character, wherever it stands."""

    def test_the_foot_states_the_cadence_in_the_owner_wording(self):
        self.assertIn(CADENCE, STRINGS.read_text(encoding="utf-8"))

    def test_the_retired_wording_is_gone(self):
        self.assertNotIn("during market open", STRINGS.read_text(encoding="utf-8"))


class LeaderLineTest(unittest.TestCase):
    """Two lines per leader, a bracketed volume group, one space per arrow."""

    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_price_is_welded_to_its_currency_label(self):
        self.assertIn('"PKR %,.2f"', self.main)
        self.assertNotIn("Rs %,.2f", self.main)

    def test_the_volume_group_is_bracketed_and_keeps_one_space(self):
        # "(" opens at B, ")" closes after T, and the ticker keeps exactly one
        # space before the group: the three fields read as one block.
        self.assertIn('sb.append(" (B=");', self.main)
        self.assertIn('sb.append("  S=");', self.main)
        self.assertIn('"  T=%,d)"', self.main)
        self.assertIn('" (T=%,d)"', self.main)
        self.assertNotIn('"  (B', self.main)
        # The bare form the group replaced is gone, and so is the side without
        # its "=" (owner order 2026-10-20, third note).
        self.assertNotIn('sb.append(" B")', self.main)
        self.assertNotIn('sb.append(" (B")', self.main)
        self.assertNotIn('sb.append("  S")', self.main)

    def test_the_money_line_opens_after_the_volumes(self):
        volumes = self.main.index('"  T=%,d)"')
        money = self.main.index('"PKR %,.2f"')
        self.assertLess(volumes, money)
        self.assertIn("sb.append('\\n');", self.main[volumes:money])

    def test_a_price_less_row_still_opens_the_money_line(self):
        # The edge case the layout must not lose: the relay can report a
        # change without a price, and the change must not hang off the
        # volumes line.
        self.assertIn("if (row.price != null || row.changePct != null) {",
                      self.main)

    def test_the_quantity_fields_print_the_feeds_own_numbers(self):
        """Render only exact non-negative broker share counts; never round."""
        self.assertIn('String.format(Locale.US, "%,d", row.buy)', self.main)
        self.assertIn('String.format(Locale.US, "%,d", row.sell)', self.main)
        self.assertNotIn("Math.round(row.buy", self.main)
        self.assertNotIn("Math.round(row.sell", self.main)
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        parser = watcher[watcher.index("private static Long integerOrNull("):]
        parser = parser[:parser.index("private static String readBounded")]
        self.assertIn("longValueExact()", parser)
        self.assertIn("return value < 0 ? null : value;", parser)
        self.assertNotIn("Math.round(value)", parser)
        # Owner order 2026-10-20 (third note): no estimate tag and no tilde
        # mark survives on the phone. The quantities are the numbers, and the
        # relay's own split_source still names the method in its JSON (SO-3).
        self.assertNotIn('sb.append("  EST");', self.main)
        self.assertNotIn("estimatedSplit", self.main)
        # A row that carries a split but no total keeps both sides.
        self.assertIn("if (row.hasVolume()) {", self.main)
        self.assertIn("sb.append(')');", self.main)

    def test_the_feed_status_line_is_retired_and_the_index_has_no_clock(self):
        """Owner orders 2026-10-19 and 2026-10-20 (third note).

        The "feed unconfirmed" narration is gone, and so is the broker stamp
        that replaced it: the owner read the clock after the percentage as part
        of the index and asked for it to leave the tile. The line is the index
        and its move, nothing after the closing bracket, and no reader for a
        stamp survives in the console.
        """
        strings = STRINGS.read_text(encoding="utf-8")
        layout = LAYOUT.read_text(encoding="utf-8")
        for name in ("market_feed_unknown", "market_feed_open",
                     "market_feed_halted", "market_feed_closed"):
            with self.subTest(resource=name):
                self.assertNotIn(f'name="{name}"', strings)
        self.assertNotIn("unconfirmed", strings.lower())
        self.assertNotIn('android:id="@+id/market_feed_status"', layout)
        self.assertNotIn("renderMarketFeedStatus", self.main)
        self.assertNotIn("brokerClock", self.main)
        self.assertNotIn("brokerClock", strings)

    def test_every_arrow_keeps_a_single_space(self):
        # The index line ends at the closing bracket (owner order 2026-10-20,
        # third note) and keeps exactly one space before the arrow.
        self.assertIn('"KSE100  %,.2f %s %,.2f (%.2f%%)"', self.main)
        self.assertNotIn('"KSE100  %,.2f   %s', self.main)
        self.assertNotIn('"KSE100  %,.2f %s %,.2f (%.2f%%)%s"', self.main)
        self.assertIn('"%s %.2f%%"', self.main)
        self.assertNotIn('"   %s %.2f%%"', self.main)
        money = self.main.index('"PKR %,.2f"')
        change = self.main.index('"%s %.2f%%"')
        self.assertIn("sb.append(' ');", self.main[money:change])


if __name__ == "__main__":
    unittest.main()
