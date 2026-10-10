"""The buy/sell volume split, and the market card that carries it.

Owner order 2026-10-10: the app must show, for each of the day's top three
KMIALL stocks, ``B=``, ``S=`` and ``T=``. The only genuine source of a
split is the read-only broker tick capture, so these tests pin the two
things that keep it honest:

  * only MKT-FEED frames are ticks. The same capture file also holds index,
    movers and market-stats frames, and counting those would fabricate
    volume (SO-3);
  * an unclassifiable trade is reported as unclassified rather than being
    assigned a side, and the card shows the total with an explicit reason
    when no split exists.

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

from src.data import market_snapshot, tick_volume  # noqa: E402

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


class SplitAttachmentTest(unittest.TestCase):
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
        return [{"symbol": "OGDC", "volume": 1000},
                {"symbol": "PSO", "volume": 900}]

    def test_without_a_capture_the_card_says_why(self):
        rows = self.leaders()
        basis = tick_volume.attach_splits(rows, DAY)
        self.assertIn("no broker tick capture banked", basis)
        for row in rows:
            self.assertIsNone(row["buy_volume"])
            self.assertIsNone(row["sell_volume"])
            self.assertIn("no broker tick capture", row["split_source"])

    def test_with_a_capture_the_leaders_carry_their_split(self):
        write_capture(tick_volume.capture_path(DAY), [
            {"kind": "MKT-FEED", "ticks": [
                tick("OGDC", "B", size="600", total="1000", when="10:01"),
                tick("OGDC", "S", size="400", total="1000", when="10:02"),
            ]},
        ])
        rows = self.leaders()
        basis = tick_volume.attach_splits(rows, DAY)
        self.assertIn("broker tick capture", basis)
        self.assertEqual(rows[0]["buy_volume"], 600)
        self.assertEqual(rows[0]["sell_volume"], 400)
        self.assertEqual(rows[0]["split_total_volume"], 1000)
        # a leader with no ticks says so rather than showing a fake zero
        self.assertIsNone(rows[1]["buy_volume"])
        self.assertIn("no MKT-FEED ticks", rows[1]["split_source"])


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

    def test_the_footnote_states_the_real_membership(self):
        rows = [{"symbol": f"S{index}", "current": 10.0, "change_pct": 0.5,
                 "volume": 1000 - index} for index in range(313)]
        leaders = market_snapshot.volume_leaders(rows)
        basis = (f"current session volume, top {len(leaders)} of "
                 f"{len(rows)} KMIALLSHR members")
        self.assertEqual(basis, "current session volume, top 3 of 313 "
                                "KMIALLSHR members")

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
        # The fixture has no genuine split, so no B=/S= may be rendered for
        # it: showing one would be the fabrication this whole layer refuses.
        self.assertNotIn("B=", result.stdout)
        self.assertIn("split unavailable", result.stdout)
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
