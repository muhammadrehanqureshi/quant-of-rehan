"""The banked session tape, and the measured split it can produce.

Owner order 2026-10-10: the app must show, for each of the day's top three
stocks, ``B=``, ``S=`` and ``T=``. This module is one of the two sources
src/data/volume_split.py uses, and the only MEASURED one: the per-trade
tape, with a side carried by each trade. The split a card shows is measured
when this tape covers the symbol and reconciles with the venue's own
cumulative total, and otherwise an explicitly labelled estimate, so these
tests pin the two things that keep the measured path honest:

  * only MKT-FEED frames are ticks. The same capture file also holds index,
    movers and market-stats frames whose fields are NOT the tick layout, and
    counting those would fabricate thousands of shares (SO-3);
  * an unclassifiable trade is reported as unclassified rather than being
    given a side, and a partial capture is never printed as the whole day.

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


def tick(scrip: str, direction: str = "", last: str = "100.0",
         bid: str = "", ask: str = "", size: str = "0",
         total: str = "", when: str = "10:01") -> dict:
    return {"scrip": scrip, "market": "REG", "last": last, "bid": bid,
            "ask": ask, "direction": direction, "last_volume": size,
            "volume": total, "tick_time": when}


def write_capture(path: Path, records: list[dict]) -> Path:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


class TickParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "capture.ndjson"

    def flow(self, records, symbols=None):
        write_capture(self.path, records)
        return tick_volume.session_flow(self.path, symbols)

    def test_only_mkt_feed_frames_count_as_ticks(self):
        """A stats frame reuses the same keys with different meanings."""
        flows = self.flow([
            {"kind": "MKT-STATS", "ticks": [
                {"0": "REG", "1": "OPEN", "last": "150219.00",
                 "direction": "17799.00", "last_volume": "45745000.00"}]},
            {"kind": "MKT-Movers", "ticks": [tick("KEL", "B", size="100")]},
            {"kind": "MKT-FEED", "ticks": [tick("OGDC", "B", size="500")]},
        ])
        self.assertEqual(sorted(flows), ["OGDC"])
        self.assertEqual(flows["OGDC"].buy_volume, 500)
        self.assertEqual(flows["OGDC"].ticks, 1)

    def test_direction_tokens_split_buy_and_sell(self):
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                tick("OGDC", "B", size="300", total="1000", when="10:01"),
                tick("OGDC", "S", size="200", total="1000", when="10:02"),
                tick("OGDC", "B", size="500", total="1000", when="10:03"),
            ]},
        ])
        flow = flows["OGDC"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (800, 200))
        self.assertEqual(flow.total_volume, 1000)   # the source's own total
        self.assertTrue(flow.split_available)
        self.assertTrue(flow.reconcilable)

    def test_an_unknown_token_uses_the_tick_rule(self):
        """No recognised side token, so bid/ask decides, never a guess."""
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                tick("PSO", "", last="100.5", ask="100.5", size="400",
                     when="10:01"),          # printed at the ask: a buyer
                tick("PSO", "?", last="99.5", bid="99.5", size="100",
                     when="10:02"),          # printed at the bid: a seller
            ]},
        ])
        flow = flows["PSO"]
        self.assertEqual((flow.buy_volume, flow.sell_volume), (400, 100))
        self.assertEqual(sorted(flow.direction_tokens), ["?"])

    def test_a_trade_with_no_side_evidence_is_unclassified(self):
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [
                tick("HBL", "Z", size="250", when="10:01"),
                tick("HBL", "B", size="750", total="1000", when="10:02"),
            ]},
        ])
        flow = flows["HBL"]
        self.assertEqual(flow.buy_volume, 750)
        self.assertEqual(flow.sell_volume, 0)
        self.assertEqual(flow.unclassified_volume, 250)
        self.assertEqual(flow.total_volume, 1000)
        self.assertFalse(flow.reconcilable)
        self.assertTrue(any("classified" in note for note in flow.notes))

    def test_repeated_ticks_are_counted_once(self):
        repeated = tick("MLCF", "B", size="100", when="10:01")
        flows = self.flow([
            {"kind": "MKT-FEED", "ticks": [repeated, dict(repeated)]},
        ])
        flow = flows["MLCF"]
        self.assertEqual(flow.buy_volume, 100)
        self.assertEqual(flow.duplicate_ticks, 1)

    def test_a_symbol_without_ticks_is_absent_not_zero(self):
        flows = self.flow([{"kind": "MKT-FEED",
                            "ticks": [tick("OGDC", "B", size="10")]}],
                          symbols=["OGDC", "NOPE"])
        self.assertNotIn("NOPE", flows)

    def test_no_capture_means_no_split(self):
        self.assertEqual(tick_volume.session_flow(self.path / "missing.ndjson"),
                         {})


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

    def test_a_reconciled_tape_is_used_and_labelled_measured(self):
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-FEED", "ticks": [
                tick("OGDC", "B", size="600", total="1000", when="10:01"),
                tick("OGDC", "S", size="400", total="1000", when="10:02"),
            ]},
        ])
        rows, basis = self.attach()
        self.assertEqual(rows[0]["buy_volume"], 600)
        self.assertEqual(rows[0]["sell_volume"], 400)
        self.assertEqual(rows[0]["split_method"], volume_split.METHOD_MEASURED)
        self.assertIn("measured", basis)
        # a leader the tape never covered carries no numbers at all
        self.assertIsNone(rows[1]["buy_volume"])
        self.assertIsNone(rows[1]["sell_volume"])
        self.assertIn("no published session range", rows[1]["split_source"])
        self.assertIn("(1 of 2)", basis)

    def test_a_partial_capture_is_not_printed_as_the_whole_day(self):
        """Classified 400 of a stated 1000: a floor, not the day."""
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-FEED", "ticks": [
                tick("OGDC", "B", size="400", total="1000", when="10:01"),
            ]},
        ])
        rows, basis = self.attach()
        self.assertIsNone(rows[0]["buy_volume"])
        self.assertEqual(rows[0]["split_method"], volume_split.METHOD_NONE)
        self.assertIn("no published session range", rows[0]["split_source"])

    def test_a_capture_without_ticks_cannot_split_a_row(self):
        """A stats frame is not a trade: the row stays without numbers."""
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-STATS", "ticks": [
                {"0": "REG", "1": "OPEN", "last": "150219.00",
                 "direction": "17799.00", "last_volume": "45745000.00"}]},
        ])
        rows, basis = self.attach()
        for row in rows:
            self.assertIsNone(row["buy_volume"])
            self.assertIsNone(row["sell_volume"])
        self.assertNotIn("measured", basis)
        self.assertNotIn("broker", basis)

    def test_no_capture_at_all_leaves_every_row_unavailable(self):
        rows, basis = self.attach()
        self.assertEqual(basis, "B/S unavailable for the leaders right now")
        for row in rows:
            self.assertEqual(row["split_method"], volume_split.METHOD_NONE)
            self.assertTrue(row["split_source"])


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
        for row in leaders:
            self.assertEqual(row["basis"],
                             "current session volume (PSX constituent table)")
            self.assertNotIn("KMIALLSHR", row["basis"])

    def test_portal_downtime_is_a_stated_gap_not_a_number(self):
        """API downtime: the snapshot says what is missing and invents none."""
        original_index = market_snapshot.fetch_index
        original_rows = market_snapshot.fetch_constituents

        def boom():
            raise OSError("portal unreachable")

        market_snapshot.fetch_index = boom
        market_snapshot.fetch_constituents = boom
        try:
            snapshot = market_snapshot.build_snapshot()
        finally:
            market_snapshot.fetch_index = original_index
            market_snapshot.fetch_constituents = original_rows

        self.assertIsNone(snapshot["index"])
        self.assertIsNone(snapshot["top_volume"])
        self.assertIn("session volume ranking is unavailable",
                      snapshot["top_volume_basis"])
        self.assertEqual(len(snapshot["notes"]), 2)
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
        self.assertIn("MARKET NOW", result.stdout)
        self.assertIn("T=27,276,548", result.stdout)
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
