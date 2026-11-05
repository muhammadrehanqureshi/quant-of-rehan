"""The relay must keep the whole-day separation it computes.

The Worker cannot run on this PC (workerd is not installed and the machine is
not a schedule), so these tests read the deployed source and pin the parts the
desk depends on, the same way tests/test_relay_worker_contracts.py pins the
public routes.
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "cloud" / "worker.js"


class WholeDayFlowContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKER.read_text(encoding="utf-8")

    def test_the_hub_owns_a_flow_table(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS quote_flow", self.source)

    def test_the_law_runs_once_per_incoming_row(self):
        self.assertEqual(self.source.count("async advanceFlow(quote)"), 1)
        self.assertIn("await this.advanceFlow(quote)", self.source)

    def test_a_failure_in_the_law_never_breaks_a_push(self):
        start = self.source.index("await this.advanceFlow(quote)")
        block = self.source[start - 400:start + 1600]
        self.assertIn("try {", block)
        self.assertIn("catch (", block)
        self.assertIn("FLOW:LAST_ERROR", block)

    def test_the_pair_is_served_beside_the_total_not_instead_of_it(self):
        self.assertIn("quote.measured_buy", self.source)
        self.assertIn("quote.measured_sell", self.source)
        self.assertIn("quote.flow_baseline", self.source)

    def test_every_increment_is_sided_exactly_once(self):
        self.assertIn("state.buy + state.sell + state.baseline !== total",
                      self.source)
        self.assertIn("state.buy += delta", self.source)
        self.assertIn("state.sell += delta", self.source)

    def test_the_baseline_audit_travels_with_the_measured_pair(self):
        self.assertIn("flow_baseline_at", self.source)
        self.assertIn("flow_first_seen_at", self.source)
        self.assertIn("flow_baseline_reason", self.source)

    def test_the_measured_pair_is_served_before_the_range(self):
        self.assertIn("function measuredFromQuote(quote)", self.source)
        self.assertIn("const measured = measuredFromQuote(quote);", self.source)
        self.assertIn(
            'split_method: measured ? "quote_rule" : "range_position"',
            self.source)

    def test_shares_the_hub_never_saw_stay_unclassified(self):
        """Owner order 2026-11-04: accuracy before a tidy B+S=T.

        A hub that starts after trading has begun must not assign the
        shares it missed to buy or sell. The capture starts before the open
        and sends its own observed pair, which the hub adopts; a genuinely
        late start reports the remainder in flow_baseline.
        """
        self.assertNotIn('bump("baseline_sided")', self.source)
        self.assertIn("function measuredFlowSeed(quote, total)", self.source)
        self.assertIn("const seed = measuredFlowSeed(quote, total);", self.source)
        self.assertIn("baseline: total - buy - sell", self.source)
        self.assertIn("state.buy + state.sell + state.baseline !== total",
                      self.source)

    def test_the_law_never_reads_the_days_change_sign(self):
        law = self.source[self.source.index("async advanceFlow(quote)"):
                          self.source.index("async advanceFlow(quote)") + 6000]
        self.assertNotIn("change_sign", law)
        self.assertNotIn("changeSign", law)


if __name__ == "__main__":
    unittest.main()
