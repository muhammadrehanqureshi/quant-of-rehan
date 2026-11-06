"""The cloud order-flow answer: complete rows and the PKR 10M large prints.

The Worker cannot run on the owner's PC, so these tests pin the source that
the deployed relay serves. They are the contract the owner's separate desktop
build reads: /flow is a pure read, never an ACK write; every row carries the
full split and its unclassified remainder; a large print is one relay update
of at least PKR 10,000,000, labelled for exactly that limitation.
"""

import json
import re
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

    def test_the_quote_view_runs_on_its_own_fresh_hub_instance(self):
        """A deployed class change does not restart a never-idle object.

        The feed pushes every second, so the old quote object would keep its
        pre-deploy class forever. The quote view therefore has its own
        instance name; the state hub keeps the card, signals and ACK rows.
        """
        self.assertIn('const QUOTE_HUB_NAME = "psx-live-quotes-v3";',
                      self.source)
        self.assertIn("namespace.idFromName(QUOTE_HUB_NAME)", self.source)
        self.assertIn("const stub = quoteHub(env);", self.source)
        self.assertIn("const hub = quoteHub(env);", self.source)
        self.assertIn('const STATE_HUB_NAME = "psx-live-quotes";', self.source)

    def test_a_running_old_capture_can_still_seed_the_new_hub(self):
        """The capture process survives a deploy; its raw pair stays valid."""
        start = self.source.index("function measuredFlowSeed(quote, total)")
        body = self.source[start:start + 1400]
        self.assertIn('quote.split_method !== "quote_rule"', body)
        self.assertIn("quote.buy_volume", body)
        self.assertIn("quote.sell_volume", body)

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
                      "unclassified_volume", "flow_baseline_at",
                      "flow_first_seen_at", "flow_baseline_reason",
                      "flow_complete",
                      "buy_share_pct", "sell_share_pct", "bid", "ask",
                      "bid_size", "ask_size",
                      "spread", "observed_at", "age_seconds",
                      "tick_age_seconds", "fresh"):
            self.assertIn(field + ":", self.source, field)
        self.assertIn("Math.max(0, volume - classified)", self.source)

    def test_a_row_without_a_measured_pair_reports_the_total_as_unclassified(self):
        start = self.source.index("async function flowAnswer(env, now)")
        end = self.source.index("async function applyLiveQuotes", start)
        body = self.source[start:end]
        self.assertIn(
            "? (classified !== null ? Math.max(0, volume - classified) : volume)",
            body)
        self.assertIn('split_method: split ? "quote_rule" : "unavailable"',
                      body)

    def test_the_answer_names_the_day_and_the_missing_symbols(self):
        self.assertIn("counts: {", self.source)
        self.assertIn("missing,", self.source)
        self.assertIn("a symbol with no frame that day", self.source)

    def test_the_universe_is_the_full_kmiall_file(self):
        start = self.source.index("const KMIALL_UNIVERSE = [")
        end = self.source.index("];", start)
        embedded = set(re.findall(r'"([A-Z0-9]+)"', self.source[start:end]))
        rows = json.loads((ROOT / "src" / "data" / "universe_kmiall.json")
                          .read_text(encoding="utf-8"))
        expected = {str(row["symbol"]).strip().upper() for row in rows
                    if row.get("symbol")}
        self.assertEqual(embedded, expected)
        self.assertIn("counts: {\n      universe: universe.size,", self.source)

    def test_large_prints_are_ten_million_rupees_and_labelled_honestly(self):
        # Owner order 2026-11-04: a big print is at least PKR 10,000,000 in a
        # single transaction, up from 1,000,000, and the basis the relay
        # serves says the same number the constant does.
        self.assertIn("const LARGE_PRINT_PKR = 10_000_000;", self.source)
        self.assertIn("if (value < LARGE_PRINT_PKR) return null;", self.source)
        self.assertIn("one relay update carrying at least PKR 10,000,000",
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