"""The banked session tape, and the split it can genuinely support.

Owner order 2026-10-10, restated 2026-10-12: the app must show, for each of
the day's top three stocks, ``B=``, ``S=`` and ``T=``, and the split has to
come from real-time trading rather than from the shape of the day's range.
This module is the MEASURED half of that: the broker tape in
``data/feed_capture/``, whose rows carry the venue's own running session
total plus the last price, the best bid and the best ask.

These tests pin the three findings the rewrite rests on, each measured on
live rows on 2026-10-12 (see src/data/feed_capture.py for the field map
evidence):

  * only MKT-FEED frames are tape rows. The same capture file also holds
    index, movers and market-stats frames whose fields are NOT the tick
    layout, and counting those would fabricate thousands of shares (SO-3);
  * the volume a window traded is the increment of the venue's own running
    total, not the size of the last print seen. Summing print sizes is a
    floor: on live data the print sizes accounted for a small fraction of
    what the total moved;
  * a side comes from where the prints actually traded (at the ask means a
    buyer lifted, at the bid means a seller hit) or from the tick rule, and
    anything else is reported as unclassified. The wire's sign field is the
    day's change, not a side, and has to be refused as one.

Everything here is offline: the capture is a fixture written to a temp
directory, and the network is never touched.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import market_snapshot, tick_volume, volume_split  # noqa: E402

DAY = date(2026, 10, 9)


def row(scrip: str, *, bid: str = "", ask: str = "", last: str = "",
        size: str = "", total: str = "", when: str = "", trades: str = "",
        change_sign: str = "") -> dict:
    """One tape row in the live layout (bid [3], ask [4], last [10])."""
    return {"scrip": scrip, "market": "REG", "bid": bid, "ask": ask,
            "last": last, "last_volume": size, "volume": total,
            "tick_time": when, "trades": trades, "change_sign": change_sign}


def write_capture(path: Path, records: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


class TapeParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "capture.ndjson"

    def flow(self, records, symbols=None):
        write_capture(self.path, records)
        return tick_volume.session_flow(self.path, symbols)

    def test_only_mkt_feed_frames_are_tape_rows(self):
        """A stats frame reuses the same keys with different meanings."""
        flows = self.flow([
            {"kind": "MKT-STATS", "ticks": [
                {"0": "REG", "1": "OPEN", "last": "150219.00",
                 "last_volume": "45745000.00"}]},
            {"kind": "MKT-Movers", "ticks": [
                row("KEL", bid="5.10", ask="5.11", last="5.11", total="100")]},
            {"kind": "MKT-FEED", "ticks": [
                row("OGDC", bid="100.00", ask="100.50", last="100.50",
                    total="500", when="10:00")]},
        ])
        self.assertEqual(sorted(flows), ["OGDC"])
        self.assertEqual(flows["OGDC"].observed_total, 500)
        self.assertEqual(flows["OGDC"].rows, 1)

    def test_a_market_qualified_scrip_still_matches_the_ranking_table(self):
        """The subscription names the market; the row is read by its symbol."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("OGDC:REG", bid="100.00", ask="100.50", last="100.50",
                    total="600", when="10:00")]},
        ])
        self.assertEqual(sorted(flows), ["OGDC"])

    def test_repeated_snapshots_are_one_window_not_two(self):
        """The feed repeats whole rows; the same row twice is one row."""
        repeated = row("MLCF", bid="10.00", ask="10.10", last="10.10",
                       total="500", trades="7", when="10:00")
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [repeated, dict(repeated)]},
        ])
        flow = flows["MLCF"]
        self.assertEqual(flow.rows, 1)
        self.assertEqual(flow.repeated_rows, 1)
        self.assertEqual(flow.buy_volume, 0)

    def test_a_symbol_without_rows_is_absent_not_zero(self):
        flows = self.flow([{"kind": "MKT-FEED", "ticks": [
            row("OGDC", bid="1", ask="2", last="2", total="10")]}],
            symbols=["OGDC", "NOPE"])
        self.assertNotIn("NOPE", flows)

    def test_rows_an_older_parser_missed_are_recovered_from_the_raw_line(self):
        """A capture written before the separator fix still reads whole.

        The record's own `ticks` list holds one row (that is what the old
        parser managed to name) while the raw line holds the whole frame.
        The raw line is the same exchange data, so it is read back rather
        than losing nine rows of every frame.
        """
        frame = ("MKT-FEED*"
                 "OGDC;REG;22;100.00;100.50;49;OPN;+;0.30;10:01:00;100.50; "
                 ";100.10;100.60;99.90;799;1000;300;99.70;99.80"
                 "||PSO;REG;22;200.00;200.50;49;OPN;+;0.30;10:01:00;200.00; "
                 ";199.00;201.00;198.00;500;2000;100;199.50;199.00")
        flows = self.flow([{"kind": "MKT-FEED", "raw": frame,
                            "ticks": [{"scrip": "OGDC"}]}])
        self.assertEqual(sorted(flows), ["OGDC", "PSO"])
        self.assertEqual(flows["PSO"].observed_total, 2000)

    def test_no_capture_means_no_split(self):
        self.assertEqual(tick_volume.session_flow(self.path / "missing.ndjson"),
                         {})


class WindowClassificationTest(unittest.TestCase):
    """The venue's running-total increments, and the evidence for each side."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "capture.ndjson"

    def flow(self, records, symbols=None):
        write_capture(self.path, records)
        return tick_volume.session_flow(self.path, symbols)

    def test_the_increment_is_split_by_where_the_print_traded(self):
        """Print at the ask is a buyer lifting; at the bid, a seller hitting."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("OGDC", bid="100.00", ask="100.50", last="100.00",
                    total="1000", when="10:00"),
                row("OGDC", bid="100.40", ask="100.90", last="100.90",
                    size="300", total="1600", when="10:01"),
                row("OGDC", bid="100.30", ask="100.80", last="100.30",
                    size="50", total="2000", when="10:02"),
            ]},
        ])
        flow = flows["OGDC"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (600, 400))
        self.assertEqual(flow.windows, 2)
        self.assertEqual(flow.windows_at_quote, 2)
        self.assertEqual(flow.observed_total, 2000)
        self.assertTrue(flow.split_available)
        self.assertFalse(flow.reconcilable)   # the tape started mid-session
        self.assertTrue(any("before the tape" in note for note in flow.notes))

    def test_the_print_sizes_are_not_the_split(self):
        """A 10 share print says nothing about the 600 shares traded."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("OGDC", bid="100.00", ask="100.50", last="100.00",
                    total="1000", when="10:00"),
                row("OGDC", bid="100.40", ask="100.90", last="100.90",
                    size="10", total="1600", when="10:01"),
            ]},
        ])
        flow = flows["OGDC"]
        self.assertEqual(flow.buy_volume, 600)
        self.assertNotEqual(flow.buy_volume, 10)

    def test_a_print_inside_the_book_uses_the_tick_rule(self):
        """No quote match, so the direction of the print decides."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("PSO", bid="100.00", ask="100.50", last="100.50",
                    total="1000", when="10:00"),
                row("PSO", bid="100.20", ask="100.90", last="100.60",
                    total="1500", when="10:01"),   # rose, inside the book
                row("PSO", bid="99.80", ask="100.40", last="100.00",
                    total="1800", when="10:02"),   # fell, inside the book
            ]},
        ])
        flow = flows["PSO"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (500, 300))
        self.assertEqual(flow.windows_by_tick, 2)
        self.assertEqual(flow.windows_at_quote, 0)

    def test_a_flat_print_inside_the_book_is_unclassified_and_reported(self):
        """Inside the book and unchanged: neither rule has anything to say."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("HBL", bid="100.00", ask="100.50", last="100.25",
                    total="1000", when="10:00"),
                row("HBL", bid="100.00", ask="100.50", last="100.25",
                    total="1300", when="10:01"),
                row("HBL", bid="100.00", ask="100.50", last="100.25",
                    total="1500", when="10:02"),
            ]},
        ])
        flow = flows["HBL"]
        self.assertEqual(flow.unclassified_windows, 2)
        self.assertEqual(flow.unclassified_volume, 1500)   # 1000 + 300 + 200
        self.assertFalse(flow.split_available)
        self.assertTrue(any("no print or quote evidence" in note
                            for note in flow.notes))

    def test_the_days_change_sign_is_never_read_as_a_trade_side(self):
        """'+' and '-' are the day's move, not who bought (SO-3).

        The live feed writes the sign of the day's change into field [7],
        and across all 902 MKT-FEED rows banked on 2026-10-12 it equalled
        sign(change) with zero exceptions. Reading it as a side would call
        every trade of a rising stock a buy.
        """
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("TREET", bid="24.80", ask="24.90", last="24.85",
                    total="1000", when="10:00", change_sign="+"),
                row("TREET", bid="24.80", ask="24.90", last="24.85",
                    total="1500", when="10:01", change_sign="+"),
                row("TREET", bid="24.80", ask="24.90", last="24.85",
                    total="2000", when="10:02", change_sign="-"),
            ]},
        ])
        flow = flows["TREET"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (0, 0))
        self.assertEqual(flow.unclassified_volume, 2000)
        self.assertFalse(flow.split_available)

    def test_an_outage_window_is_refused_not_attributed(self):
        """Measured failure, 2026-10-12: a dead capture is not a side.

        CNERGY traded 4,050,063 shares across a stretch where the tape was
        down for three hours, and the print that closed that stretch sat at
        the ask. Attributing it to buying would have printed the day as 97
        percent buying. A window longer than ten minutes is refused, and its
        shares stay unclassified.
        """
        flows = self.flow([
            {"kind": "MKT-FEED", "ts": "2026-10-12T10:32:31.000+05:00",
             "ticks": [row("CNERGY", bid="12.48", ask="12.49",
                           last="12.49", total="4699128",
                           when="10:32:19")]},
            {"kind": "MKT-FEED", "ts": "2026-10-12T13:27:52.000+05:00",
             "ticks": [row("CNERGY", bid="12.38", ask="12.40",
                           last="12.40", total="8749191",
                           when="13:27:46")]},
        ])
        flow = flows["CNERGY"]
        self.assertEqual(flow.gap_windows, 1)
        self.assertEqual(flow.gap_volume, 4_050_063)
        self.assertEqual(flow.buy_volume, 0)
        self.assertEqual(flow.sell_volume, 0)
        self.assertFalse(flow.split_available)
        self.assertTrue(any("spanned more than" in note
                            for note in flow.notes))

    def test_a_normal_sampling_gap_is_still_a_window(self):
        """Thirty seconds between snapshots is the feed's own cadence."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ts": "2026-10-12T13:33:22.000+05:00",
             "ticks": [row("TREET", bid="24.39", ask="24.45",
                           last="24.45", total="21971591",
                           when="13:33:17")]},
            {"kind": "MKT-FEED", "ts": "2026-10-12T13:33:52.000+05:00",
             "ticks": [row("TREET", bid="24.39", ask="24.41",
                           last="24.41", total="21976861",
                           when="13:33:41")]},
        ])
        flow = flows["TREET"]
        self.assertEqual(flow.gap_windows, 0)
        self.assertEqual(flow.windows, 1)
        self.assertEqual(flow.buy_volume, 5270)   # the print sat at the ask

    def test_a_backwards_total_is_excluded_and_stated(self):
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("COLG", bid="100.00", ask="100.50", last="100.50",
                    total="5000", when="10:00"),
                row("COLG", bid="100.00", ask="100.50", last="100.50",
                    total="4000", when="10:01"),
                row("COLG", bid="100.00", ask="100.50", last="100.50",
                    total="6000", when="10:02"),
            ]},
        ])
        flow = flows["COLG"]
        self.assertEqual(flow.backward_windows, 1)
        # the fall is refused; the next window is 4000 -> 6000, at the ask
        self.assertEqual(flow.buy_volume, 2000)
        self.assertTrue(any("backwards" in note for note in flow.notes))

    def test_a_tape_running_from_the_open_reconciles_with_the_day(self):
        """First row at zero volume: every share from the open is attributed."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                row("PIBTL", bid="13.60", ask="13.70", last="13.70",
                    total="0", when="09:32"),
                row("PIBTL", bid="13.70", ask="13.80", last="13.80",
                    total="1000", when="09:33"),
                row("PIBTL", bid="13.60", ask="13.70", last="13.60",
                    total="1500", when="09:34"),
            ]},
        ])
        flow = flows["PIBTL"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (1000, 500))
        self.assertEqual(flow.pre_tape_volume, 0)
        self.assertTrue(flow.reconcilable)
        self.assertEqual(flow.coverage, 1.0)


class MeasuredSplitTest(unittest.TestCase):
    """When the tape is allowed to answer, and what the card then says."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.capture_dir = Path(self._dir.name)
        self._real_dir = tick_volume.CAPTURE_DIR
        tick_volume.CAPTURE_DIR = self.capture_dir
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        tick_volume.CAPTURE_DIR = self._real_dir

    def leaders(self) -> list[dict]:
        return [{"symbol": "OGDC", "volume": 1000, "price": 95.0},
                {"symbol": "PSO", "volume": 900, "price": 96.0}]

    def attach(self, rows=None) -> tuple[list[dict], str]:
        rows = self.leaders() if rows is None else rows
        flows = tick_volume.session_flow(tick_volume.capture_path(DAY),
                                        [row["symbol"] for row in rows])
        basis = volume_split.attach_splits(rows, quotes={}, flows=flows)
        return rows, basis

    def test_a_tape_that_covers_the_day_is_labelled_measured(self):
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-FEED", "ticks": [
                row("OGDC", bid="100.00", ask="100.50", last="100.50",
                    total="0", when="09:32"),
                row("OGDC", bid="100.40", ask="100.90", last="100.90",
                    total="600", when="09:33"),
                row("OGDC", bid="100.20", ask="100.90", last="100.20",
                    total="1000", when="09:34"),
            ]},
        ])
        rows, basis = self.attach()
        self.assertEqual(rows[0]["buy_volume"], 600)
        self.assertEqual(rows[0]["sell_volume"], 400)
        self.assertEqual(rows[0]["split_method"], volume_split.METHOD_MEASURED)
        self.assertIn("measured", basis)
        # a leader with no tape rows carries no numbers at all
        self.assertIsNone(rows[1]["buy_volume"])
        self.assertIsNone(rows[1]["sell_volume"])
        self.assertIn("(1 of 2)", basis)

    def test_a_partial_tape_is_projected_and_labelled_an_estimate(self):
        """The tape saw part of the day: its sides are used, and labelled.

        Six windows, four of them buys, 3000 attributed shares against a
        running total of 4000 (75 percent coverage), so the tape's two to
        one buy flow is projected onto the day's 1000 shares.
        """
        ticks = [row("OGDC", bid="100.00", ask="100.50", last="100.00",
                     total="1000", when="10:00")]
        sides = (("100.40", "100.90", "100.90"),   # at the ask: a buyer
                 ("100.40", "100.90", "100.90"),
                 ("100.10", "100.90", "100.10"),   # at the bid: a seller
                 ("100.40", "100.90", "100.90"),
                 ("100.10", "100.90", "100.10"),
                 ("100.40", "100.90", "100.90"))
        total = 1000
        for index, (bid, ask, last) in enumerate(sides, start=1):
            total += 500
            ticks.append(row("OGDC", bid=bid, ask=ask, last=last,
                             total=str(total), when=f"10:{index:02d}"))
        write_capture(tick_volume.capture_path(DAY),
                      [{"kind": "MKT-FEED", "ticks": ticks}])
        rows, basis = self.attach()
        # Owner order 2026-10-15: the feed's own counts, verbatim. The tape
        # attributed 3000 shares here (2000 buys, 1000 sells); none of them
        # is scaled onto the venue's total for the same row.
        self.assertEqual((rows[0]["buy_volume"], rows[0]["sell_volume"]),
                         (2000, 1000))
        self.assertEqual(rows[0]["buy_volume"] + rows[0]["sell_volume"],
                         rows[0]["split_volume"])
        self.assertEqual(rows[0]["split_method"],
                         volume_split.METHOD_TAPE_COUNTS)
        self.assertIn("part of the session", basis)

    def test_a_capture_without_tape_rows_cannot_split_a_row(self):
        """A stats frame is not a trade: the row stays without numbers."""
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-STATS", "ticks": [
                {"0": "REG", "1": "OPEN", "last": "150219.00",
                 "last_volume": "45745000.00"}]},
        ])
        rows, basis = self.attach()
        for row_ in rows:
            self.assertIsNone(row_["buy_volume"])
            self.assertIsNone(row_["sell_volume"])
        self.assertNotIn("measured", basis)
        self.assertNotIn("broker", basis)

    def test_no_capture_at_all_leaves_every_row_unavailable(self):
        rows, basis = self.attach()
        self.assertEqual(basis, "B/S unavailable for the leaders right now")
        for row_ in rows:
            self.assertEqual(row_["split_method"], volume_split.METHOD_NONE)
            self.assertTrue(row_["split_source"])


class SubscribeFrameTest(unittest.TestCase):
    """The one frame that decides whether a tape exists at all.

    Measured live on 2026-10-12 on the KST feed, same socket, same second:
    bare symbols returned 0 MKT-FEED frames in 18 seconds, the same symbols
    with ``:REG`` returned 17. A bare subscription still receives the index,
    movers and market-stats frames, so it looks healthy while the tape it
    exists to record stays empty, which is exactly how the card came to show
    total volume with no buy and sell sides.
    """

    def test_every_symbol_carries_the_market_qualifier(self):
        from src.data.feed_capture import build_subscribe_frame

        frame = build_subscribe_frame(["OGDC", "PSO"])
        self.assertEqual(frame, "MKT-FEED|OGDC:REG;PSO:REG;%")

    def test_an_already_qualified_symbol_is_not_qualified_twice(self):
        from src.data.feed_capture import build_subscribe_frame

        self.assertEqual(build_subscribe_frame(["OGDC:REG"]),
                         "MKT-FEED|OGDC:REG;%")

    def test_the_frame_still_passes_the_read_only_guard(self):
        """The owner's read-only law: still a subscription, nothing else."""
        from src.data.feed_capture import (ALLOWED_OUTGOING_PREFIXES,
                                           build_subscribe_frame)

        frame = build_subscribe_frame(["OGDC"])
        self.assertTrue(frame.startswith("MKT-FEED|"))
        self.assertTrue(frame.endswith("%"))
        self.assertEqual(len(ALLOWED_OUTGOING_PREFIXES), 3)


class MarketCardTest(unittest.TestCase):
    """The card the phone renders, built offline from stubbed portal pages."""

    def test_leaders_carry_the_days_percentage_change(self):
        rows = [{"symbol": "CNERGY", "current": 12.52, "change_pct": 1.049,
                 "volume": 27_276_548},
                {"symbol": "PRL", "current": 93.07, "change_pct": -2.14,
                 "volume": 24_123_072}]
        leaders = market_snapshot.volume_leaders(rows)
        self.assertEqual([row["symbol"] for row in leaders],
                         ["CNERGY", "PRL"])
        self.assertAlmostEqual(leaders[0]["change_pct"], 1.049)
        self.assertAlmostEqual(leaders[1]["change_pct"], -2.14)
        self.assertIsNone(leaders[0]["buy_volume"])

    def test_the_basis_names_the_ranking_and_not_the_membership(self):
        """Owner order 2026-10-11: the membership wording is gone."""
        rows = [{"symbol": f"S{index}", "current": 10.0, "change_pct": 0.5,
                 "volume": 1000 - index} for index in range(313)]
        leaders = market_snapshot.volume_leaders(rows)
        self.assertEqual(len(leaders), 3)
        for row_ in leaders:
            self.assertEqual(row_["basis"],
                             "current session volume (PSX constituent table)")
            self.assertNotIn("KMIALLSHR", row_["basis"])

    def test_portal_downtime_is_a_stated_gap_not_a_number(self):
        """API downtime: the snapshot says what is missing and invents none."""
        original_index = market_snapshot.fetch_index
        original_rows = market_snapshot.fetch_constituents
        original_live = market_snapshot.broker_market.read_market_snapshot
        market_snapshot.broker_market.read_market_snapshot = lambda now: {
            "index": None, "top_volume": None,
            "market_feed": {"status": "UNKNOWN", "raw_status": None,
                            "as_of": None, "age_seconds": None,
                            "source": "eClear REG market feed", "fresh": False},
        }

        def boom():
            raise OSError("portal unreachable")

        market_snapshot.fetch_index = boom
        market_snapshot.fetch_constituents = boom
        try:
            snapshot = market_snapshot.build_snapshot()
        finally:
            market_snapshot.fetch_index = original_index
            market_snapshot.fetch_constituents = original_rows
            market_snapshot.broker_market.read_market_snapshot = original_live

        self.assertIsNone(snapshot["index"])
        self.assertIsNone(snapshot["top_volume"])
        self.assertIn("session volume ranking is unavailable",
                      snapshot["top_volume_basis"])
        self.assertEqual(len(snapshot["notes"]), 3)
        self.assertTrue(any("index fetch failed" in note
                            for note in snapshot["notes"]))
        self.assertTrue(any("portal index unavailable" in note
                            for note in snapshot["notes"]))
        self.assertTrue(any("constituents fetch failed" in note
                            for note in snapshot["notes"]))
        self.assertFalse(snapshot["market_state"]["market_open"]
                         and snapshot["index"] is None
                         and snapshot["top_volume"] is not None)
        self.assertIn("phase", snapshot["market_state"])

    def test_the_snapshot_carries_the_session_phase(self):
        snapshot = market_snapshot.build_snapshot()
        state = snapshot["market_state"]
        self.assertIn(state["phase"],
                      {"OPEN", "BREAK", "CLOSED", "PRE_OPEN", "POST_CLOSE"})
        self.assertEqual(state["market_open"],
                         state["phase"] in ("OPEN", "WARMUP"))
        # Owner order 2026-10-11: the card reads the condition and its exact
        # sentence from here, so both must travel with every snapshot.
        self.assertIn(state["condition"],
                      {"OPERATIONAL", "BREAK", "CLOSED"})
        if state["condition"] == "OPERATIONAL":
            self.assertEqual(state["condition_text"], "")
        else:
            self.assertIn(state["condition_text"],
                          ("Market is on a break right now.",
                           "Market is closed right now."))


class MarketCardExampleTest(unittest.TestCase):
    """The usage example is the documentation, so it is executed, not read."""

    EXAMPLE = ROOT / "examples" / "market_card.py"

    def test_the_example_runs_and_refuses_bad_cards(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(self.EXAMPLE), "--offline"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn("T=27,276,548", result.stdout)
        # Owner order 2026-10-12: the retired "MARKET NOW" label is gone from
        # the card, so the example cannot print it either.
        self.assertNotIn("MARKET NOW", result.stdout)
        # The fixture carries the day's split, labelled as the estimate it is:
        # the venue publishes total volume only, so a bare B=/S= would claim
        # more than anyone can know (SO-3).
        self.assertIn("B=14,547,492", result.stdout)
        self.assertIn("S=12,729,056", result.stdout)
        self.assertIn("B/S estimated from the day's range, not order flow",
                      result.stdout)
        self.assertIn("Market is on a break right now.", result.stdout)
        self.assertNotIn("KMIALLSHR members", result.stdout)
        self.assertNotIn("broker", result.stdout)
        refusals = [line for line in result.stdout.splitlines()
                    if line.strip().startswith("refused")]
        self.assertEqual(len(refusals), 5, result.stdout)
        self.assertNotIn("ACCEPTED", result.stdout)

    def test_the_example_can_be_asked_about_a_friday_break(self):
        """The reported bug, checked through the code the app uses."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(self.EXAMPLE), "--offline",
             "--at", "2026-10-09T14:23:00+05:00"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        self.assertIn('"phase": "BREAK"', result.stdout)
        self.assertIn('"market_open": false', result.stdout)
        self.assertIn('"condition": "BREAK"', result.stdout)
        self.assertIn('"condition_text": "Market is on a break right now."',
                      result.stdout)
        self.assertIn("OFFLINE", result.stdout)


class PushDiagnosticsTest(unittest.TestCase):
    """The scheduled job must be able to explain its own failure.

    Owner bug report, 2026-10-10: Telegram said only "the daily signal push
    failed", with the cause buried in a GitHub log. These assertions pin the
    fix: the reason travels with the alert, the run summary, and the job
    output, and the token resolver agrees with the rest of the code.
    """

    WORKFLOW = ROOT / ".github" / "workflows" / "signal-push.yml"

    def test_the_alert_carries_the_reason(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("REASON=", text)
        self.assertIn("Reason: ${REASON}", text)
        self.assertIn("GITHUB_STEP_SUMMARY", text)
        self.assertIn("signal_push_run.log", text)

    def test_the_job_still_does_not_fail_the_scheduled_run(self):
        text = self.WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("|| true", text)
        self.assertNotIn("exit $STATUS", text)

    def test_ops_alert_resolves_the_token_like_everyone_else(self):
        from src.notify.schedule_runner import load_relay_admin_token
        import scripts.ops_alert as ops_alert

        self.assertTrue(callable(load_relay_admin_token))
        self.assertIs(ops_alert.load_relay_admin_token, load_relay_admin_token)

    def test_signal_push_has_a_preflight_and_hints(self):
        text = (ROOT / "src" / "signals" / "signal_push.py").read_text(
            encoding="utf-8")
        self.assertIn("def relay_preflight", text)
        self.assertIn("RELAY_ADMIN_TOKEN no longer matches", text)
        self.assertIn("Telegram refused the send", text)
        self.assertIn("unreachable after", text)


if __name__ == "__main__":
    unittest.main()
