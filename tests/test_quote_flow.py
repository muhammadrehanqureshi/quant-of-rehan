"""The strict law: every increment of the venue's counter, sided once."""

import unittest

from src.data import quote_flow


def row(price, bid, ask, volume, symbol="PRL"):
    return {"symbol": symbol, "price": price, "bid": bid, "ask": ask,
            "volume": volume}


class QuoteFlowTest(unittest.TestCase):
    def setUp(self):
        self.flow = quote_flow.QuoteFlow()

    def test_the_first_total_is_a_baseline_not_a_trade(self):
        quote = self.flow.observe(row(86.0, 85.9, 86.0, 1000))
        self.assertEqual(quote["buy_volume"], 0)
        self.assertEqual(quote["sell_volume"], 0)
        self.assertEqual(quote["flow_baseline"], 1000)
        self.assertEqual(quote["split_method"], "quote_rule")

    def test_a_print_at_the_ask_is_buying(self):
        self.flow.observe(row(86.0, 85.9, 86.0, 1000))
        quote = self.flow.observe(row(86.0, 85.9, 86.0, 1400))
        self.assertEqual(quote["buy_volume"], 400)
        self.assertEqual(quote["sell_volume"], 0)

    def test_a_print_at_the_bid_is_selling(self):
        self.flow.observe(row(86.0, 85.9, 86.0, 1000))
        quote = self.flow.observe(row(85.9, 85.9, 86.0, 1250))
        self.assertEqual(quote["buy_volume"], 0)
        self.assertEqual(quote["sell_volume"], 250)

    def test_inside_the_spread_the_midpoint_decides(self):
        self.flow.observe(row(86.0, 85.0, 87.0, 1000))
        up = self.flow.observe(row(86.8, 85.0, 87.0, 1100))
        self.assertEqual(up["buy_volume"], 100)
        down = self.flow.observe(row(85.6, 85.0, 87.0, 1300))
        self.assertEqual(down["sell_volume"], 200)

    def test_without_a_book_the_tick_rule_decides(self):
        self.flow.observe(row(86.0, None, None, 1000))
        up = self.flow.observe(row(86.5, None, None, 1010))
        down = self.flow.observe(row(86.2, None, None, 1050))
        self.assertEqual(up["buy_volume"], 10)
        self.assertEqual(down["sell_volume"], 40)

    def test_an_undecidable_increment_is_carried_and_counted(self):
        self.flow.observe(row(86.0, None, None, 1000))
        quote = self.flow.observe(row(86.0, None, None, 1030))
        self.assertEqual(quote["flow_rules"].get("carried"), 1)
        self.assertEqual(quote["buy_volume"] + quote["sell_volume"], 30)

    def test_a_falling_total_is_a_reset_never_a_sale(self):
        self.flow.observe(row(86.0, 85.9, 86.0, 1000))
        self.flow.observe(row(86.0, 85.9, 86.0, 1400))
        quote = self.flow.observe(row(86.0, 85.9, 86.0, 100))
        self.assertEqual(quote["sell_volume"], 0)
        self.assertEqual(quote["flow_rules"].get("reset"), 1)
        after = self.flow.observe(row(86.0, 85.9, 86.0, 250))
        self.assertEqual(after["buy_volume"], 400 + 150)

    def test_every_observed_share_is_attributed_exactly_once(self):
        book = [(86.0, 85.9, 86.0, 1000),
                (86.0, 85.9, 86.0, 1300),
                (85.9, 85.8, 86.0, 1700),
                (86.5, 86.4, 86.5, 2000),
                (86.3, 86.0, 86.6, 2600)]
        last = None
        for price, bid, ask, volume in book:
            last = self.flow.observe(row(price, bid, ask, volume))
        self.assertEqual(last["buy_volume"] + last["sell_volume"],
                         2600 - last["flow_baseline"])
        self.assertEqual(last["buy_volume"] + last["sell_volume"],
                         1600)

    def test_seed_continues_a_measured_day_and_ignores_an_estimate(self):
        seeded = quote_flow.QuoteFlow()
        adopted = seeded.seed([
            {"symbol": "PRL", "volume": 1000, "buy_volume": 700,
             "sell_volume": 300, "split_method": "quote_rule"},
            {"symbol": "CNERGY", "volume": 500, "buy_volume": 100,
             "sell_volume": 400, "split_method": "range_position"},
        ])
        self.assertEqual(adopted, 1)
        quote = seeded.observe(row(86.0, 85.9, 86.0, 1100))
        self.assertEqual(quote["buy_volume"], 800)
        self.assertEqual(quote["sell_volume"], 300)
        other = seeded.observe(row(12.0, 11.9, 12.0, 520, symbol="CNERGY"))
        self.assertEqual(other["buy_volume"], 20)
        self.assertEqual(other["flow_baseline"], 500)

    def test_seed_adopts_a_pair_with_its_own_baseline(self):
        seeded = quote_flow.QuoteFlow()
        adopted = seeded.seed([
            {"symbol": "OGDC", "volume": 1000, "buy_volume": 600,
             "sell_volume": 150, "flow_baseline": 250,
             "split_method": "quote_rule"},
        ])
        self.assertEqual(adopted, 1)
        quote = seeded.observe(row(86.0, 85.9, 86.0, 1100))
        self.assertEqual(quote["buy_volume"], 700)
        self.assertEqual(quote["sell_volume"], 150)
        self.assertEqual(quote["flow_baseline"], 250)
        self.assertEqual(quote["buy_volume"] + quote["sell_volume"]
                         + quote["flow_baseline"], 1100)


if __name__ == "__main__":
    unittest.main()
