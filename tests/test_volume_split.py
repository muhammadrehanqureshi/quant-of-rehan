"""How the buy and sell volumes are calculated, and when they are refused.

Owner order 2026-10-11: the card must carry, for each of the day's top three
stocks, the buy volume, the sell volume and the total, and the legacy wording
about index membership and a broker capture must be gone. The owner also
asked for a test that demonstrates the calculation itself, so the first class
below is that demonstration, worked by hand.

The rules these tests hold the module to (SO-3, footprint honesty law):

  * buy + sell is EXACTLY the session volume, for every produced split;
  * the estimate is a labelled proxy, never presented as order flow;
  * a measured split is used only when it reconciles with the venue's own
    cumulative total, so a partial capture is never printed as the day;
  * missing, stale or contradictory inputs produce no numbers and a reason.

Everything here is offline: the ranking rows are literals, the session range
is a literal, and the tape is a fixture in a temp directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import market_snapshot, tick_volume, volume_split  # noqa: E402


class SplitCalculationTest(unittest.TestCase):
    """The calculation, stated once and then worked through."""

    def test_the_owners_worked_example(self):
        """position = (close - low) / (high - low), buy = volume x position.

        Range 99.00 to 101.50, close 101.00, volume 1,000,000:
        position 0.8, so 800,000 shares are attributed to buying and the
        remaining 200,000 to selling. It is an estimate from the day's
        range, and the label says so.
        """
        split = volume_split.range_position_split(101.5, 99.0, 101.0, 1_000_000)
        self.assertIsNotNone(split)
        self.assertEqual(split.buy, 800_000)
        self.assertEqual(split.sell, 200_000)
        self.assertEqual(split.buy + split.sell, split.volume)
        self.assertAlmostEqual(split.fraction, 0.8)
        self.assertEqual(split.method, volume_split.METHOD_RANGE)
        self.assertIn("estimated", volume_split.METHOD_LABELS[split.method])

    def test_a_close_at_the_high_attributes_everything_to_buying(self):
        split = volume_split.range_position_split(100.0, 90.0, 100.0, 1_000)
        self.assertEqual((split.buy, split.sell), (1_000, 0))

    def test_a_close_at_the_low_attributes_everything_to_selling(self):
        split = volume_split.range_position_split(100.0, 90.0, 90.0, 1_000)
        self.assertEqual((split.buy, split.sell), (0, 1_000))

    def test_a_close_at_the_midpoint_splits_the_session_evenly(self):
        split = volume_split.range_position_split(100.0, 90.0, 95.0, 1_000)
        self.assertEqual((split.buy, split.sell), (500, 500))

    def test_the_sum_is_exact_across_a_sweep_of_inputs(self):
        """The invariant that makes the card's T= true by construction."""
        for high in (100.0, 100.01, 1234.5):
            for low in (90.0, 99.99, 100.0):
                if low > high:
                    continue
                for close in (low, (low + high) / 2, high):
                    for volume in (1, 3, 999, 1_000_001, 27_276_548):
                        split = volume_split.range_position_split(
                            high, low, close, volume)
                        self.assertIsNotNone(split, (high, low, close, volume))
                        self.assertEqual(split.buy + split.sell, split.volume)
                        self.assertGreaterEqual(split.buy, 0)
                        self.assertGreaterEqual(split.sell, 0)
                        self.assertEqual(split.volume, volume)

    def test_the_share_count_rounds_half_up_like_the_relay(self):
        """Python and the worker's Math.round must never differ by a share.

        An odd total with the close exactly mid-range is the one case where a
        half-even rule would answer one share below the relay's.
        """
        split = volume_split.range_position_split(10, 0, 5, 1_001)
        self.assertEqual(split.buy, 501)
        self.assertEqual(split.sell, 500)

    def test_a_single_price_session_is_even_and_says_so(self):
        split = volume_split.range_position_split(100.0, 100.0, 100.0, 1_000)
        self.assertEqual((split.buy, split.sell), (500, 500))
        self.assertIn("single price", split.note)

    def test_a_volume_string_with_separators_is_read(self):
        """The portal publishes 1,792,926 and 27,276,548, commas included."""
        split = volume_split.range_position_split("100.00", "90.00", "95.00",
                                                 "1,792,926")
        self.assertEqual(split.volume, 1_792_926)
        self.assertEqual(split.buy + split.sell, 1_792_926)

    def test_impossible_inputs_produce_no_numbers(self):
        cases = {
            "low above high": (90.0, 100.0, 95.0, 1_000),
            "no volume at all": (100.0, 90.0, 95.0, 0),
            "negative volume": (100.0, 90.0, 95.0, -5),
            "the last price above the range": (100.0, 90.0, 100.5, 1_000),
            "the last price below the range": (100.0, 90.0, 89.5, 1_000),
            "a missing high": (None, 90.0, 95.0, 1_000),
            "a missing close": (100.0, 90.0, None, 1_000),
            "a missing volume": (100.0, 90.0, 95.0, None),
            "a word where a number belongs": (100.0, 90.0, 95.0, "many"),
        }
        for label, (high, low, close, volume) in cases.items():
            with self.subTest(label=label):
                self.assertIsNone(
                    volume_split.range_position_split(high, low, close, volume))


class SplitSourceHierarchyTest(unittest.TestCase):
    """Measured tape first, labelled estimate second, nothing third."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.capture_dir = Path(self._dir.name)
        self._real_dir = tick_volume.CAPTURE_DIR
        tick_volume.CAPTURE_DIR = self.capture_dir
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        tick_volume.CAPTURE_DIR = self._real_dir

    def flow(self, symbol: str, records: list[dict]) -> dict:
        """Write a capture and read the symbol's flow out of it."""
        from datetime import date

        path = tick_volume.capture_path(date(2026, 10, 9))
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        return tick_volume.session_flow(path, [symbol])

    def test_a_reconciled_tape_beats_the_estimate(self):
        """The tape ran from the open, so its own numbers are the split."""
        flows = self.flow("OGDC", [{"kind": "MKT-FEED", "ticks": [
            {"scrip": "OGDC", "bid": "100.00", "ask": "100.50",
             "last": "100.50", "volume": "0", "tick_time": "09:32"},
            {"scrip": "OGDC", "bid": "100.40", "ask": "100.90",
             "last": "100.90", "volume": "600", "tick_time": "09:33"},
            {"scrip": "OGDC", "bid": "100.20", "ask": "100.80",
             "last": "100.20", "volume": "1000", "tick_time": "09:34"},
        ]}])
        row = {"symbol": "OGDC", "volume": 1000, "price": 95.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 1000}
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows=flows)
        self.assertEqual(reason, "")
        self.assertEqual((split.buy, split.sell), (600, 400))
        self.assertEqual(split.method, volume_split.METHOD_MEASURED)
        self.assertIn("measured", volume_split.METHOD_LABELS[split.method])

    def test_a_partial_tape_carries_the_feeds_own_counts_verbatim(self):
        """3000 attributed shares, 2000 of them buys, printed as they are.

        Owner order 2026-10-15: the quantity fields show the exact numbers
        the broker feed produced, so the tape's own integers ride through
        unchanged. Nothing is scaled onto the venue's session total (1000
        here), which is why B + S is 3000 and not that total, and the note
        carries what the counts cover.
        """
        ticks = [{"scrip": "OGDC", "bid": "100.00", "ask": "100.50",
                  "last": "100.00", "volume": "1000", "tick_time": "10:00"}]
        side_prices = ([("100.40", "100.90", "100.90"),   # at the ask
                        ("100.40", "100.90", "100.90"),
                        ("100.10", "100.90", "100.10"),   # at the bid
                        ("100.40", "100.90", "100.90"),
                        ("100.10", "100.90", "100.10"),
                        ("100.40", "100.90", "100.90")])
        total = 1000
        for index, (bid, ask, last) in enumerate(side_prices, start=1):
            total += 500
            ticks.append({"scrip": "OGDC", "bid": bid, "ask": ask,
                          "last": last, "volume": str(total),
                          "tick_time": f"10:{index:02d}"})
        flows = self.flow("OGDC", [{"kind": "MKT-FEED", "ticks": ticks}])
        row = {"symbol": "OGDC", "volume": 1000, "price": 100.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 1000}
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows=flows)
        self.assertEqual(reason, "")
        self.assertEqual(split.method, volume_split.METHOD_TAPE_COUNTS)
        self.assertEqual((split.buy, split.sell), (2000, 1000))
        self.assertEqual(split.buy + split.sell, split.volume)
        # The venue's own total for the same symbol is NOT the tape's window,
        # and the card prints both: T= stays the exchange's figure.
        self.assertNotEqual(split.volume, 1000)
        self.assertIn("3,000", split.note)
        self.assertIn("4,000", split.note)
        label = volume_split.METHOD_LABELS[split.method]
        self.assertIn("session's own trade tape", label)
        self.assertIn("part of the session", label)

    def test_a_too_thin_tape_slice_is_refused_and_the_range_answers(self):
        """A slice this small is one window's direction, not the day's flow.

        Measured 2026-10-12: a mid-session capture covered 0.1 percent of
        SLGL's day, and one window's direction would have printed as 100
        percent buying. Below the floor the labelled range estimate answers
        instead.
        """
        flows = self.flow("OGDC", [{"kind": "MKT-FEED", "ticks": [
            {"scrip": "OGDC", "bid": "100.00", "ask": "100.50",
             "last": "100.00", "volume": "10000", "tick_time": "10:00"},
            {"scrip": "OGDC", "bid": "100.40", "ask": "100.90",
             "last": "100.90", "volume": "10050", "tick_time": "10:01"},
        ]}])
        row = {"symbol": "OGDC", "volume": 10000, "price": 100.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 10000}
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows=flows)
        self.assertEqual(reason, "")
        self.assertEqual(split.method, volume_split.METHOD_RANGE)

    def test_a_thin_tape_slice_with_no_range_is_refused_outright(self):
        flows = self.flow("OGDC", [{"kind": "MKT-FEED", "ticks": [
            {"scrip": "OGDC", "bid": "100.00", "ask": "100.50",
             "last": "100.00", "volume": "10000", "tick_time": "10:00"},
            {"scrip": "OGDC", "bid": "100.40", "ask": "100.90",
             "last": "100.90", "volume": "10050", "tick_time": "10:01"},
        ]}])
        row = {"symbol": "OGDC", "volume": 10000, "price": 100.0}
        split, reason = volume_split.split_for(row, quotes={}, flows=flows)
        self.assertIsNone(split)
        self.assertIn("no published session range", reason)

    def test_no_tape_counts_falls_back_to_the_range_estimate(self):
        """No tape at all: the day's range answers, and says so."""
        flows = self.flow("OGDC", [{"kind": "MKT-FEED", "ticks": [
            {"scrip": "OGDC", "bid": "100.00", "ask": "100.50",
             "last": "100.00", "volume": "1000", "tick_time": "10:00"},
        ]}])
        row = {"symbol": "OGDC", "volume": 1000, "price": 100.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 1000}
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows=flows)
        self.assertEqual(reason, "")
        self.assertEqual(split.method, volume_split.METHOD_RANGE)
        self.assertEqual((split.buy, split.sell), (1000, 0))

    def test_no_tape_and_no_range_is_unavailable_with_a_reason(self):
        row = {"symbol": "OGDC", "volume": 1000, "price": 95.0}
        split, reason = volume_split.split_for(row, quotes={}, flows={})
        self.assertIsNone(split)
        self.assertIn("no published session range", reason)

    def test_a_stale_panel_is_refused(self):
        row = {"symbol": "OGDC", "volume": 1000, "price": 95.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 900}   # 900 < 1000
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows={})
        self.assertIsNone(split)
        self.assertIn("stale", reason)

    def test_a_price_outside_the_range_is_refused(self):
        row = {"symbol": "OGDC", "volume": 1000, "price": 101.0}
        quote = {"high": 100.0, "low": 90.0, "volume": 1000}
        split, reason = volume_split.split_for(row, quotes={"OGDC": quote},
                                               flows={})
        self.assertIsNone(split)
        self.assertIn("outside the published range", reason)

    def test_the_labels_never_claim_more_than_they_know(self):
        for label in (volume_split.METHOD_LABELS[volume_split.METHOD_RANGE],):
            self.assertIn("estimated", label)
            self.assertIn("not order flow", label)
        # The tape's counts are the feed's own numbers, so the label claims
        # the feed and the window it covered: it may not say "estimated"
        # (they are not an estimate) and it may not imply the whole session.
        counted = volume_split.METHOD_LABELS[volume_split.METHOD_TAPE_COUNTS]
        self.assertIn("session's own trade tape", counted)
        self.assertIn("part of the session", counted)
        self.assertNotIn("estimated", counted)
        self.assertIn("measured",
                      volume_split.METHOD_LABELS[volume_split.METHOD_MEASURED])
        for label in volume_split.METHOD_LABELS.values():
            self.assertNotIn("broker", label)
            self.assertNotIn("KMIALLSHR", label)


class SplitFootnoteTest(unittest.TestCase):
    """One sentence, naming the weakest method that produced a number."""

    def rows(self, methods):
        return [{"symbol": f"S{i}", "volume": 100,
                 "buy_volume": None if method is None else 60,
                 "sell_volume": None if method is None else 40,
                 "split_method": method or volume_split.METHOD_NONE}
                for i, method in enumerate(methods)]

    def test_all_estimated_says_estimated(self):
        text = volume_split.summarise(self.rows([volume_split.METHOD_RANGE] * 3))
        self.assertEqual(text, volume_split.METHOD_LABELS[
            volume_split.METHOD_RANGE])

    def test_tape_counts_name_the_tape_not_the_range(self):
        text = volume_split.summarise(
            self.rows([volume_split.METHOD_TAPE_COUNTS] * 2))
        self.assertEqual(text, volume_split.METHOD_LABELS[
            volume_split.METHOD_TAPE_COUNTS])

    def test_a_mixed_line_names_the_weakest_method(self):
        """One range row makes the whole line the range label: it is read
        on the same card, so it may not sound stronger than its weakest
        number."""
        text = volume_split.summarise(self.rows([volume_split.METHOD_MEASURED,
                                                 volume_split.METHOD_RANGE]))
        self.assertIn("day's range", text)
        mixed = volume_split.summarise(self.rows([volume_split.METHOD_MEASURED,
                                                  volume_split.METHOD_TAPE_COUNTS]))
        self.assertIn("trade tape", mixed)

    def test_all_measured_says_measured(self):
        text = volume_split.summarise(
            self.rows([volume_split.METHOD_MEASURED] * 2))
        self.assertIn("measured", text)

    def test_a_row_without_a_split_is_counted_not_hidden(self):
        text = volume_split.summarise(self.rows([volume_split.METHOD_RANGE,
                                                 None, volume_split.METHOD_RANGE]))
        self.assertIn("(2 of 3)", text)

    def test_nothing_available_says_so(self):
        self.assertEqual(volume_split.summarise(self.rows([None, None])),
                         "B/S unavailable for the leaders right now")


class SnapshotIntegrationTest(unittest.TestCase):
    """The card the relay serves, built offline from stubbed portal answers."""

    ROWS = [{"symbol": f"S{index}", "current": 10.0 + index,
             "change_pct": 0.5, "volume": 1_000_000 - index * 1000}
            for index in range(313)]

    def snapshot(self, quotes):
        originals = (market_snapshot.fetch_index,
                     market_snapshot.fetch_constituents,
                     market_snapshot.fetch_quotes,
                     volume_split.flows_for,
                     market_snapshot.broker_market.read_market_snapshot)
        market_snapshot.fetch_index = lambda: {"symbol": "KSE100",
                                               "value": 1.0, "change": 0.0,
                                               "change_pct": 0.0,
                                               "as_of": "2026-10-09 15:30:00"}
        market_snapshot.fetch_constituents = lambda: list(self.ROWS)
        market_snapshot.fetch_quotes = lambda symbols: dict(quotes)
        volume_split.flows_for = lambda day, symbols: {}
        market_snapshot.broker_market.read_market_snapshot = lambda now: {
            "index": None, "top_volume": None,
            "market_feed": {"status": "UNKNOWN", "raw_status": None,
                            "as_of": None, "age_seconds": None,
                            "source": "eClear REG market feed", "fresh": False},
        }

        def restore():
            (market_snapshot.fetch_index,
             market_snapshot.fetch_constituents,
             market_snapshot.fetch_quotes,
             volume_split.flows_for,
             market_snapshot.broker_market.read_market_snapshot) = originals

        self.addCleanup(restore)
        return market_snapshot.build_snapshot()

    def test_the_leaders_carry_a_labelled_split(self):
        # The panel's volume is fetched after the ranking table, so it can
        # only be equal to or newer than the table's own figure.
        quotes = {f"S{index}": {"high": 12.0, "low": 9.0, "volume": 1_000_000}
                  for index in range(3)}
        snapshot = self.snapshot(quotes)
        leaders = snapshot["top_volume"]
        self.assertEqual([row["symbol"] for row in leaders],
                         ["S0", "S1", "S2"])
        for row in leaders:
            self.assertEqual(row["split_method"], volume_split.METHOD_RANGE)
            self.assertEqual(row["buy_volume"] + row["sell_volume"],
                             row["volume"])
        self.assertEqual(snapshot["volume_split_basis"],
                         volume_split.METHOD_LABELS[
                             volume_split.METHOD_RANGE])
        self.assertEqual(snapshot["top_volume_basis"],
                         "current session volume, top 3 (portal fallback)")

    def test_the_card_carries_no_legacy_wording(self):
        quotes = {f"S{index}": {"high": 12.0, "low": 9.0, "volume": 1_000_000}
                  for index in range(3)}
        snapshot = self.snapshot(quotes)
        rendered = " ".join([
            str(snapshot["top_volume_basis"]),
            str(snapshot["volume_split_basis"]),
            *[str(row.get("basis", "")) for row in snapshot["top_volume"]],
            *[str(note) for note in snapshot["notes"]],
        ])
        self.assertNotIn("KMIALLSHR members", rendered)
        self.assertNotIn("broker", rendered)
        self.assertNotIn("tick capture", rendered)

    def test_a_missing_range_produces_no_split_and_a_reason(self):
        snapshot = self.snapshot({})
        for row in snapshot["top_volume"]:
            self.assertIsNone(row["buy_volume"])
            self.assertIsNone(row["sell_volume"])
            self.assertEqual(row["split_method"], volume_split.METHOD_NONE)
            self.assertTrue(row["split_source"])
        self.assertEqual(snapshot["volume_split_basis"],
                         "B/S unavailable for the leaders right now")


class WorkedExampleTest(unittest.TestCase):
    """The demonstration the owner asked for, executed rather than read."""

    def test_the_module_prints_the_calculation_line_by_line(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.data.volume_split"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("position = (close - low) / (high - low) = 0.8000",
                      result.stdout)
        self.assertIn("buy  = round(1000000 x 0.8000) = 800,000", result.stdout)
        self.assertIn("sell = 1000000 - 800,000 = 200,000", result.stdout)
        self.assertIn("buy + sell = 1,000,000 = volume, exactly", result.stdout)
        self.assertIn("estimated from the day's range", result.stdout)

    def test_the_module_answers_for_given_fields(self):
        result = subprocess.run(
            [sys.executable, "-m", "src.data.volume_split", "--high", "10",
             "--low", "8", "--close", "9", "--volume", "500"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("buy  = round(500 x 0.5000) = 250", result.stdout)
        self.assertIn("sell = 500 - 250 = 250", result.stdout)


if __name__ == "__main__":
    unittest.main()
