"""Tests for the console terminal: monotone B/S, poll-delta flow, frames."""

import unittest
from datetime import datetime, timedelta, timezone

from src.desktop import tui

KARACHI = timezone(timedelta(hours=5))
NOW = datetime(2026, 11, 3, 11, 30, tzinfo=KARACHI)


def quote(symbol="PRL", price=86.0, volume=18_173_240, buy=13_874_998,
          sell=4_298_242, change_pct=-1.44, observed=None):
    return {
        "symbol": symbol,
        "price": price,
        "volume": volume,
        "buy_volume": buy,
        "sell_volume": sell,
        "change_pct": change_pct,
        "high": 87.7,
        "low": 82.55,
        "status": "OPEN",
        "observed_at": (observed or NOW).isoformat(),
    }


def desk_with(rows, record=None):
    desk = tui.Desk()
    desk.observe(rows, NOW)
    desk.record = record or {"state": "NO_TRADE"}
    desk.health = {"market_state": {
        "phase": "OPEN", "market_open": True,
        "next_event": {"event": "CLOSE", "at_pk": "2026-11-03T15:30:00"}}}
    desk.market = {"index": {"value": 168290.78, "change": 1726.72,
                             "source": "eClear EXS-FEED"}}
    return desk


def plain_frame(desk, page=0, sort=2, size=(120, 34), now=NOW):
    return [tui.plain(line) for line in
            tui.render(desk, page, sort, size, now)]


class DaySplitTest(unittest.TestCase):
    def test_day_split_comes_from_the_relay_pair(self):
        desk = desk_with([quote()])
        row = desk.flow.rows(now=NOW)[0]
        self.assertEqual(row["buy_volume"], 13_874_998)
        self.assertEqual(row["sell_volume"], 4_298_242)
        self.assertAlmostEqual(row["bought"], 13_874_998 * 86.0)

    def test_day_split_never_falls_when_the_relay_rebalances(self):
        desk = desk_with([quote()])
        desk.observe([quote(price=83.0, volume=19_000_000, buy=12_000_000,
                            sell=7_000_000)], NOW + timedelta(seconds=1))
        row = desk.flow.rows(now=NOW + timedelta(seconds=1))[0]
        self.assertEqual(row["buy_volume"], 13_874_998)
        self.assertEqual(row["sell_volume"], 7_000_000)

    def test_a_row_without_a_split_falls_back_to_the_range_estimate(self):
        row = quote(symbol="SGPL", price=22.49, volume=1_197_880, buy=None,
                    sell=None, change_pct=-2.13)
        row["high"], row["low"] = 24.0, 21.0
        desk = desk_with([row])
        saved = desk.flow.rows(now=NOW)[0]
        self.assertGreater(saved["buy_volume"], 0)
        self.assertEqual(saved["buy_volume"] + saved["sell_volume"],
                         1_197_880)


class SixtySecondFlowTest(unittest.TestCase):
    def test_flow_sides_by_price_move(self):
        desk = tui.Desk()
        desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
        desk.observe([quote(price=86.5, volume=1100, buy=0, sell=0)],
                     NOW + timedelta(seconds=1))
        desk.observe([quote(price=86.0, volume=1250, buy=0, sell=0)],
                     NOW + timedelta(seconds=2))
        row = desk.flow.rows(now=NOW + timedelta(seconds=2))[0]
        self.assertAlmostEqual(row["bought_60"], 100 * 86.5)
        self.assertAlmostEqual(row["sold_60"], 150 * 86.0)
        self.assertEqual(row["shares_60"], 250)

    def test_held_price_keeps_the_last_side(self):
        desk = tui.Desk()
        desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
        desk.observe([quote(price=86.0, volume=1040, buy=0, sell=0)],
                     NOW + timedelta(seconds=1))
        desk.observe([quote(price=86.0, volume=1100, buy=0, sell=0)],
                     NOW + timedelta(seconds=2))
        row = desk.flow.rows(now=NOW + timedelta(seconds=2))[0]
        self.assertEqual(row["sold_60"], 0)
        self.assertAlmostEqual(row["bought_60"], 100 * 86.0)

    def test_backwards_running_volume_is_never_attributed(self):
        desk = tui.Desk()
        desk.observe([quote(price=86.0, volume=5000, buy=0, sell=0)], NOW)
        desk.observe([quote(price=86.0, volume=4000, buy=0, sell=0)],
                     NOW + timedelta(seconds=1))
        row = desk.flow.rows(now=NOW + timedelta(seconds=1))[0]
        self.assertEqual(row["bought_60"], 0)
        self.assertEqual(row["sold_60"], 0)
        self.assertEqual(row["volume"], 5000)

    def test_flow_leaves_the_sixty_second_window(self):
        desk = tui.Desk()
        desk.observe([quote(price=86.0, volume=1000, buy=0, sell=0)], NOW)
        desk.observe([quote(price=87.0, volume=1100, buy=0, sell=0)],
                     NOW + timedelta(seconds=1))
        later = NOW + timedelta(seconds=90)
        desk.observe([quote(price=87.0, volume=1100, buy=0, sell=0)], later)
        row = desk.flow.rows(now=later)[0]
        self.assertEqual(row["bought_60"], 0)


class FrameTest(unittest.TestCase):
    def test_top_three_are_the_volume_leaders(self):
        rows = [quote(symbol="PRL", volume=18_173_240),
                quote(symbol="CNERGY", volume=37_942_931),
                quote(symbol="CLOV", volume=6_014_787),
                quote(symbol="MLCF", volume=3_761_121)]
        frame = "\n".join(plain_frame(desk_with(rows)))
        self.assertLess(frame.index("CNERGY"), frame.index("PRL"))
        self.assertLess(frame.index("PRL"), frame.index("CLOV"))
        self.assertNotIn("MLCF", frame)

    def test_home_shows_the_relay_split_and_the_recorded_signal(self):
        desk = desk_with([quote()], record={
            "state": "NO_TRADE_TODAY",
            "recorded_at": "2026-11-03T10:10:00"})
        frame = "\n".join(plain_frame(desk))
        self.assertIn("PRL", frame)
        self.assertIn("13,874,998", frame)
        self.assertIn("4,298,242", frame)
        self.assertIn("NO_TRADE_TODAY", frame)
        self.assertIn("record written 10:10", frame)

    def test_scanner_waits_for_a_second_poll(self):
        frame = "\n".join(plain_frame(desk_with([quote()]), page=1))
        for name in tui.SORTS:
            self.assertIn(name, frame)
        self.assertIn("no executed buying in the last 60 s yet", frame)

    def test_scanner_ranks_the_sixty_second_buyers_after_a_poll(self):
        desk = desk_with([quote(price=86.0, volume=18_173_240)])
        desk.observe([quote(price=86.5, volume=18_180_000)],
                     NOW + timedelta(seconds=1))
        frame = "\n".join(plain_frame(desk, page=1,
                                     now=NOW + timedelta(seconds=1)))
        self.assertIn("PRL", frame)
        self.assertIn("BOUGHT PKR 585K", frame)
        self.assertIn("SOLD PKR 0", frame)
        self.assertIn("6.76K shares", frame)

    def test_order_flow_page_lists_the_day_pair(self):
        frame = "\n".join(plain_frame(desk_with([quote()]), page=2))
        self.assertIn("ORDER FLOW", frame)
        self.assertIn("13,874,998", frame)

    def test_signals_page_states_the_record_and_its_age(self):
        desk = desk_with([quote()], record={
            "state": "NO_TRADE_TODAY",
            "recorded_at": "2026-11-03T10:10:00"})
        frame = "\n".join(plain_frame(desk, page=3))
        self.assertIn("NO_TRADE_TODAY", frame)
        self.assertIn("record written", frame)

    def test_health_and_settings_pages_render(self):
        desk = desk_with([quote()])
        health = "\n".join(plain_frame(desk, page=4))
        settings = "\n".join(plain_frame(desk, page=5))
        self.assertIn("RELAY AND FEED", health)
        self.assertIn("rows", health)
        self.assertIn("fresh", health)
        self.assertIn("SETTINGS", settings)
        self.assertIn("QOR_RELAY", settings)

    def test_every_frame_keeps_the_terminal_size(self):
        desk = desk_with([quote()])
        for page in range(len(tui.PAGES)):
            lines = plain_frame(desk, page=page, size=(110, 32))
            self.assertEqual(len(lines), 32)
            for line in lines:
                self.assertLessEqual(len(line), 110, line)

    def test_colour_is_ansi_and_plain_strips_it(self):
        desk = desk_with([quote()])
        coloured = tui.render(desk, 0, 2, (120, 34), NOW)
        self.assertTrue(any("\x1b[" in line for line in coloured))
        self.assertIsNone(tui.ANSI.search(tui.plain("\n".join(coloured))))

    def test_missing_quotes_still_render(self):
        lines = plain_frame(tui.Desk())
        self.assertIn("QUANT CORE", "\n".join(lines))
        self.assertEqual(len(lines), 34)

    def test_the_core_ring_animates(self):
        desk = desk_with([quote()])
        first = plain_frame(desk, page=1, now=NOW)
        later = plain_frame(desk, page=1,
                            now=NOW + timedelta(seconds=3))
        self.assertNotEqual(first[3:14], later[3:14])

    def test_the_split_basis_names_the_registry_verdict(self):
        self.assertIn("UNAVAILABLE", tui.split_basis())


if __name__ == "__main__":
    unittest.main()
