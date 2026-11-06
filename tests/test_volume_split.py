"""Strict B/S contract for the card's leaders.

A leader row carries B and S only when the relay's measured quote_rule pair
is already on it. No range, tape or price move is consulted. Without that
pair, B and S are null and the whole total is U.
"""

import unittest

from src.data import volume_split


class AttachSplitsTest(unittest.TestCase):
    def row(self, **overrides):
        row = {"symbol": "OGDC", "volume": 1000, "price": 100.0}
        row.update(overrides)
        return row

    def test_no_measured_pair_is_unclear_without_any_estimate(self):
        row = self.row(buy_volume=None, sell_volume=None,
                       high=110.0, low=90.0)
        basis = volume_split.attach_splits([row])
        self.assertIsNone(row["buy_volume"])
        self.assertIsNone(row["sell_volume"])
        self.assertEqual(row["unclassified_volume"], 1000)
        self.assertEqual(row["split_method"], volume_split.METHOD_NONE)
        self.assertIn("no measured order-flow pair", row["split_source"])
        self.assertEqual(
            basis, "B/S unavailable: the wire has not measured a pair")

    def test_a_range_pair_is_never_trusted(self):
        row = self.row(buy_volume=800, sell_volume=200,
                       split_method=volume_split.METHOD_RANGE)
        volume_split.attach_splits([row])
        self.assertIsNone(row["buy_volume"])
        self.assertIsNone(row["sell_volume"])
        self.assertEqual(row["unclassified_volume"], 1000)

    def test_a_tape_pair_is_never_trusted_on_the_card(self):
        row = self.row(buy_volume=600, sell_volume=300,
                       split_method=volume_split.METHOD_TAPE_COUNTS)
        volume_split.attach_splits([row])
        self.assertIsNone(row["buy_volume"])
        self.assertIsNone(row["sell_volume"])
        self.assertEqual(row["unclassified_volume"], 1000)

    def test_measured_wire_pair_is_copied_and_u_is_the_rest(self):
        row = self.row(buy_volume=600, sell_volume=300,
                       split_method=volume_split.METHOD_WIRE)
        basis = volume_split.attach_splits([row])
        self.assertEqual((row["buy_volume"], row["sell_volume"]), (600, 300))
        self.assertEqual(row["classified_volume"], 900)
        self.assertEqual(row["unclassified_volume"], 100)
        self.assertFalse(row["flow_complete"])
        self.assertEqual(row["split_method"], volume_split.METHOD_WIRE)
        self.assertIn("measured at the wire", row["split_source"])
        self.assertIn("measured at the wire", basis)

    def test_measured_pair_that_reconciles_is_complete(self):
        row = self.row(buy_volume=600, sell_volume=400,
                       split_method=volume_split.METHOD_WIRE)
        volume_split.attach_splits([row])
        self.assertEqual(row["unclassified_volume"], 0)
        self.assertTrue(row["flow_complete"])

    def test_measured_pair_larger_than_the_total_is_refused(self):
        row = self.row(buy_volume=900, sell_volume=200,
                       split_method=volume_split.METHOD_WIRE)
        volume_split.attach_splits([row])
        self.assertIsNone(row["buy_volume"])
        self.assertIsNone(row["sell_volume"])
        self.assertEqual(row["unclassified_volume"], 1000)

    def test_negative_measured_pair_is_refused(self):
        row = self.row(buy_volume=-1, sell_volume=100,
                       split_method=volume_split.METHOD_WIRE)
        volume_split.attach_splits([row])
        self.assertIsNone(row["buy_volume"])
        self.assertIsNone(row["sell_volume"])
        self.assertEqual(row["unclassified_volume"], 1000)


class SplitForTest(unittest.TestCase):
    def test_split_for_requires_the_wire_tag(self):
        row = {"symbol": "OGDC", "volume": 1000,
               "buy_volume": 600, "sell_volume": 300}
        split, reason = volume_split.split_for(row)
        self.assertIsNone(split)
        self.assertIn("no measured order-flow pair", reason)

    def test_split_for_accepts_the_measured_pair(self):
        row = {"symbol": "OGDC", "volume": 1000,
               "buy_volume": 600, "sell_volume": 300,
               "split_method": volume_split.METHOD_WIRE}
        split, reason = volume_split.split_for(row)
        self.assertEqual(reason, "")
        self.assertEqual((split.buy, split.sell), (600, 300))
        self.assertEqual(split.method, volume_split.METHOD_WIRE)


if __name__ == "__main__":
    unittest.main()
