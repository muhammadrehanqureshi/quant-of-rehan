"""One cost schedule, one definition of net return.

Defect this guards: the rebuilt paper cycle recorded ``net_return = gross_return``
(no execution cost model was wired in), while the frozen research gate charged
22.4 bps per side plus slippage and CGT. Two definitions of "net" would collide
the moment the paper cycle fed the gate. Now the schedule lives once, in
src/config.py, and the frozen gate reads it from there, so the arithmetic is
guaranteed identical.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.research import forward_validation as fv  # noqa: E402


class CostModelTest(unittest.TestCase):
    def test_frozen_gate_and_config_share_one_schedule(self):
        self.assertEqual(fv.COST_SIDE_BPS, config.COST_SIDE_BPS)
        self.assertEqual(fv.SLIPPAGE_SIDE_BPS, config.SLIPPAGE_SIDE_BPS)
        self.assertEqual(fv.CGT_RATE, config.CGT_RATE)

    def test_round_trip_cost_charges_both_sides(self):
        expected = 2.0 * (config.COST_SIDE_BPS + config.SLIPPAGE_SIDE_BPS) / 10000.0
        self.assertAlmostEqual(config.round_trip_cost(), expected, places=12)

    def test_net_return_charges_costs_then_cgt_on_a_winner(self):
        gross = 0.02
        expected = round((gross - config.round_trip_cost()) * (1.0 - config.CGT_RATE), 6)
        self.assertEqual(config.net_return(gross), expected)
        self.assertLess(config.net_return(gross), gross)

    def test_net_return_leaves_a_loser_without_cgt(self):
        gross = -0.01
        self.assertEqual(config.net_return(gross),
                         round(gross - config.round_trip_cost(), 6))

    def test_net_return_of_none_stays_none(self):
        self.assertIsNone(config.net_return(None))

    def test_paper_net_matches_the_frozen_labeler_arithmetic(self):
        """The two paths must compute a net return the same way, value for value."""
        gross = 0.015
        label_net = gross - 2.0 * (fv.COST_SIDE_BPS + fv.SLIPPAGE_SIDE_BPS) / 10000.0
        if label_net > 0:
            label_net *= 1.0 - fv.CGT_RATE
        self.assertAlmostEqual(config.net_return(gross), round(label_net, 6), places=6)


if __name__ == "__main__":
    unittest.main()
