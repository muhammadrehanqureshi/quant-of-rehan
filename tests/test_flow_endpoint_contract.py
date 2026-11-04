"""The cloud order-flow answer: complete rows and the PKR 1M large prints.

The Worker cannot run on the owner's PC, so these tests pin the source that
the deployed relay serves. They are the contract the owner's separate desktop
build reads: /flow is a pure read, never an ACK write; every row carries the
full split and its unclassified remainder; a large print is one relay update
of at least PKR 1,000,000, labelled for exactly that limitation.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "cloud" / "worker.js"


class FlowEndpointContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKER.read_text(encoding="utf-8")

    def test_the_public_flow_route_exists_under_both_names(self):
        self.assertIn('path === "/flow" || path === "/orderflow"',
                      self.source)
        self.assertIn("await flowAnswer(env, new Date())", self.source)
        self.assertIn('"access-control-allow-origin": "*"', self.source)

    def test_the_flow_answer_is_a_pure_snapshot_read(self):
        start = self.source.index("async function flowAnswer(env, now)")
        end = self.source.index("async function applyLiveQuotes", start)
        body = self.source[start:end]
        self.assertIn("await readQuoteSnapshot(env)", body)
        self.assertNotIn("ackUpsert", body)
        self.assertNotIn("portalText", body)
        self.assertNotIn("kvPut", body)

    def test_every_row_carries_the_full_flow_and_its_unclassified_part(self):
        for field in ("buy_volume", "sell_volume", "classified_volume",
                      "unclassified_volume", "flow_complete",
                      "buy_share_pct", "sell_share_pct", "bid", "ask",
                      "spread", "observed_at", "fresh"):
            self.assertIn(field + ":", self.source, field)
        self.assertIn("Math.max(0, volume - classified)", self.source)

    def test_the_answer_names_the_day_and_the_missing_symbols(self):
        self.assertIn("counts: {", self.source)
        self.assertIn("missing,", self.source)
        self.assertIn("a symbol with no frame that day", self.source)

    def test_large_prints_are_one_million_rupees_and_labelled_honestly(self):
        self.assertIn("const LARGE_PRINT_PKR = 1_000_000;", self.source)
        self.assertIn("if (value < LARGE_PRINT_PKR) return null;", self.source)
        self.assertIn("one relay update carrying at least PKR 1,000,000",
                      self.source)
        self.assertIn("the broker wire has no individual order id",
                      self.source)
        self.assertIn("large_prints", self.source)
        self.assertIn("large_prints_total", self.source)

    def test_the_large_board_has_both_raw_prints_and_stock_totals(self):
        self.assertIn("largeStatsBySymbol", self.source)
        self.assertIn("large_buy_count", self.source)
        self.assertIn("large_sell_count", self.source)
        self.assertIn("total_value_pkr", self.source)
        self.assertIn("side: print.side === \"S\" ? \"SELL\" : \"BUY\"",
                      self.source)


if __name__ == "__main__":
    unittest.main()