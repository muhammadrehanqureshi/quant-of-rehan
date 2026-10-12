"""Owner-ordered copy and money-line rules for the phone's market card.

Owner order 2026-10-12: the three volume leaders each read on two lines. The
first line is the rank, the symbol and the volumes; the second is the money
line, "PKR 12.52" followed by the day's change. The owner was seeing the
currency label stranded at the end of the first line with the price wrapped
below it, so the label and the number are now welded together and a narrow
screen cannot split them again. The up and down arrows carry exactly one
space before them on the index line and on every leader line, and the card's
foot states the scan cadence in the owner's own words: "when the market is
open", not "during market open".

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

CADENCE = ("Quant will be scanning the market every 4 minutes "
           "when the market is open.")


class FootSentenceTest(unittest.TestCase):
    """The card's foot carries the owner's sentence, character for character."""

    def test_the_foot_states_the_cadence_in_the_owner_wording(self):
        self.assertIn(CADENCE, STRINGS.read_text(encoding="utf-8"))

    def test_the_retired_wording_is_gone(self):
        self.assertNotIn("during market open", STRINGS.read_text(encoding="utf-8"))


class LeaderLineTest(unittest.TestCase):
    """Two lines per leader, and one space before every arrow."""

    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")

    def test_one_space_separates_the_ticker_from_its_buy_volume(self):
        """Owner order 2026-10-12 (third note): the double space is gone.

        Three spaces sat between the ticker and its buy volume, which read as
        a double space on the phone. One space replaces it, in both branches
        (a split row and a volume only row). The two spaces that separate the
        volume fields stay: they are what groups B, S and T apart.
        """
        self.assertIn('sb.append(" B")', self.main)
        self.assertNotIn('"   B"', self.main)
        self.assertNotIn('"   T=', self.main)

    def test_the_price_is_welded_to_its_currency_label(self):
        self.assertIn('"PKR %,.2f"', self.main)
        self.assertNotIn("Rs %,.2f", self.main)

    def test_the_money_line_opens_after_the_volumes(self):
        volumes = self.main.index('"  T=%,d"')
        money = self.main.index('"PKR %,.2f"')
        self.assertLess(volumes, money)
        self.assertIn("sb.append('\\n');", self.main[volumes:money])

    def test_a_price_less_row_still_opens_the_money_line(self):
        # The edge case the layout must not lose: the relay can report a
        # change without a price, and the change must not hang off the
        # volumes line.
        self.assertIn("if (row.price != null || row.changePct != null) {",
                      self.main)

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
