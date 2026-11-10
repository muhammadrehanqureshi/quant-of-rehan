"""The zero baseline must pass the relay's quote shape law (owner 2026-11-10).

The order of 2026-11-09 seeds one zero-volume baseline per symbol per day so
the day's first print is sided instead of parked in the unclear remainder.
That row carries no price by definition, and the relay's shape check demanded
a positive one, so it answered 400 for the whole batch, the publisher queued
the same row again, and every later push was refused behind it: the card read
NO FEED from 09:40 while the tape itself was delivering thousands of ticks.

These checks are on the two laws that made that impossible to see and possible
to happen: the shape check now accepts a baseline, and a 400 never requeues a
row that carries no price.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QuoteShapeLawTest(unittest.TestCase):
    def test_a_zero_volume_baseline_passes_the_shape_check(self):
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        start = worker.index("function quoteSnapshotShapeError")
        body = worker[start:worker.index("function normalizeQuoteSnapshot")]
        self.assertIn("const baseline = row && row.flow_only === true", body,
                      "the shape check must know a zero baseline")
        self.assertIn("(!priced && !baseline)", body,
                      "a baseline may carry no price; a priced row still must")
        self.assertIn("Number(row.volume) === 0", body,
                      "only a zero volume row is a baseline")

    def test_the_shape_error_still_names_the_rule(self):
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        self.assertIn(
            "requires a valid symbol, positive price and timestamp", worker,
            "the refusal message the runner prints must stay recognisable")


class RefusedBaselineIsNotRetriedTest(unittest.TestCase):
    def test_a_400_drops_the_rows_that_carry_no_price(self):
        source = (ROOT / "src" / "data" / "feed_capture.py").read_text(
            encoding="utf-8")
        start = source.index("class RelayQuotePublisher")
        body = source[start:source.index("def close(self)")]
        self.assertIn("if status == 400:", body)
        self.assertIn("if q.get(\"flow_only\")", body,
                      "the queued baselines are purged on a 400")
        self.assertIn("self._pending_quotes.pop(doomed, None)", body)
        self.assertIn("if status == 400 and row.get(\"flow_only\")", body,
                      "a refused baseline is never queued for another try")


if __name__ == "__main__":
    unittest.main()
