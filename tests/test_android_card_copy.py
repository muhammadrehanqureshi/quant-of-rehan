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

CADENCE = ("Quant will be scanning the market every 30 seconds "
           "when the market is open.")


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
        self.assertIn('sb.append(" (B")', self.main)
        self.assertIn('"  T=%,d)"', self.main)
        self.assertIn('" (T=%,d)"', self.main)
        self.assertNotIn('"  (B', self.main)
        # The bare form the group replaced is gone.
        self.assertNotIn('sb.append(" B")', self.main)

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
        """Owner order 2026-10-15: exact, raw quantities, never a rescaling.

        The buy and sell counts reach the line as the whole numbers the feed
        produced, each formatted straight from its own field. What used to
        reach this line was the tape's flow projected onto the venue's
        session total, which is a rounded estimate rather than the feed's
        number, so nothing here may scale, round or re-derive them.
        """
        self.assertIn('String.format(Locale.US, "%,d", row.buy)', self.main)
        self.assertIn('String.format(Locale.US, "%,d", row.sell)', self.main)
        self.assertNotIn("Math.round(row.buy", self.main)
        self.assertNotIn("Math.round(row.sell", self.main)
        # A row that carries a split but no total keeps its two sides: the
        # quantities are the point of the group, and the totals are optional.
        self.assertIn("if (row.hasVolume()) {", self.main)
        self.assertIn("sb.append(')');", self.main)

    def test_every_arrow_keeps_a_single_space(self):
        self.assertIn('"KSE100  %,.2f %s %,.2f (%.2f%%)"', self.main)
        self.assertNotIn('"KSE100  %,.2f   %s', self.main)
        self.assertIn('"%s %.2f%%"', self.main)
        self.assertNotIn('"   %s %.2f%%"', self.main)
        money = self.main.index('"PKR %,.2f"')
        change = self.main.index('"%s %.2f%%"')
        self.assertIn("sb.append(' ');", self.main[money:change])


if __name__ == "__main__":
    unittest.main()
