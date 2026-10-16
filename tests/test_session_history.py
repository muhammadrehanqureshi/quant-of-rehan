"""The session evidence the production gate reads, and how it is labelled.

Owner defect 2026-10-16: scripts/intraday_pipeline.py called
``evaluate_gate([])``, so the gate never saw a single session and
``sessions_collected`` was pinned at 0 for ever. src/research/session_history.py
is the input that was missing, and these tests hold the two properties that
make it worth having:

  * a session with verified data IS counted, so the 120-session window can
    actually advance;
  * a session with blocked, unreadable or unconfirmed data is NOT counted, and
    the lost sessions are named rather than silently absorbed. Feeding the gate
    more rows must never buy progress a session did not earn.

Everything here runs against a temporary forward directory and a stubbed
relay, so no test reads the owner's real records or opens a socket.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.research import forward_validation, session_history  # noqa: E402
from src.signals import trade_state  # noqa: E402

CONFIRMATIONS = {
    "data_rights_confirmed": True,
    "data_latency_confirmed": True,
    "universe_confirmed": True,
}


def verified_quality(**overrides) -> dict:
    """A QualityReport payload in which every law the scanner checks passed."""
    quality = {
        "status": "OK",
        "reason": "coverage, freshness, history, structure and volume present",
        "coverage": 0.97,
        "fresh_coverage": 0.95,
        "symbols_expected": 317,
        "symbols_with_bars": 308,
        "symbols_missing": [],
        "rankable_symbols": 300,
        "leaders_fresh": 20,
        "leader_symbols": 20,
        "volume_available": True,
    }
    quality.update(overrides)
    return quality


def session_record(day: str, **overrides) -> dict:
    """One stored session, in the shape scripts/intraday_pipeline.py writes."""
    record = {
        "date": day,
        "trades_taken": 1,
        "trade_status": "DAILY_LOCKED",
        "symbol": "FCCL",
        "entry_price": 51.95,
        "entry_time": f"{day}T11:30:00+05:00",
        "target_price": 52.989,
        "target_hit": True,
        "exit_price": 53.0,
        "return_pct": 0.0202,
        "gross_return": 0.02,
        "net_return": config.net_return(0.02),
        "minutes_held": 45,
        "outcome": "TARGET_HIT",
        "data_quality": verified_quality(),
        "data_confirmations": dict(CONFIRMATIONS),
        "scanner_version": config.SCANNER_VERSION,
        "universe_size": 317,
    }
    record.update(overrides)
    return record


class SessionHistoryTest(unittest.TestCase):
    """What the loader emits, and what the gate can do with it."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        (self.root / "data" / "forward").mkdir(parents=True, exist_ok=True)

        root_patcher = patch.object(trade_state, "ROOT", self.root)
        root_patcher.start()
        self.addCleanup(root_patcher.stop)

        relay_patcher = patch.object(
            session_history, "_relay_records",
            lambda timeout_s=20.0: ([], "stubbed in this test"))
        relay_patcher.start()
        self.addCleanup(relay_patcher.stop)

    def write_outcome(self, *records: dict) -> None:
        payload = {
            "date": records[-1]["date"],
            "scanner_version": config.SCANNER_VERSION,
            "outcomes_by_rule": {config.SCANNER_VERSION: records[-1]},
            "data_quality": records[-1].get("data_quality") or {},
            "storage_status": "relay+local",
        }
        (self.root / "data" / "forward" / "daily_outcome.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8")

    def write_journal(self, *records: dict) -> None:
        path = self.root / "data" / "forward" / "session_journal.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def test_a_verified_session_is_counted_and_moves_the_gate(self):
        """The whole point: a good session advances the 120-session window."""
        self.write_outcome(session_record("2026-10-13"))

        report: dict = {}
        rows = session_history.session_rows(report=report)
        self.assertEqual(report["sessions_loaded"], 1)
        self.assertEqual(report["sessions_verified"], 1)
        self.assertEqual(rows[0]["data_quality"]["quality"], "verified")
        self.assertTrue(rows[0]["data_quality"]["production_data_ready"])

        gate = forward_validation.evaluate_gate(rows)
        self.assertEqual(gate["sessions_collected"], 1)
        self.assertEqual(gate["sessions_required"], 120)
        self.assertEqual(gate["status"], "RESEARCH_RUNNING")
        # and it is still locked: one session of 120 buys nothing
        self.assertFalse(gate["live_signal_enabled"])

    def test_a_blocked_session_is_unverified_and_spends_no_session(self):
        """A DATA_BLOCKED day is evidence of a bad feed, not of a strategy."""
        record = session_record(
            "2026-10-14", symbol=None, outcome="NO_CANDIDATE",
            gross_return=None, net_return=None, minutes_held=None,
            data_quality={"status": "DATA_BLOCKED",
                          "reason": "KMIALL coverage 0/317 (0.0%)",
                          "coverage": 0.0})
        self.write_outcome(record)

        report: dict = {}
        rows = session_history.session_rows(report=report)
        self.assertEqual(report["sessions_loaded"], 1)
        self.assertEqual(report["sessions_verified"], 0)
        self.assertEqual(rows[0]["data_quality"]["quality"], "unverified")
        self.assertFalse(rows[0]["data_quality"]["production_data_ready"])

        gate = forward_validation.evaluate_gate(rows)
        self.assertEqual(gate["sessions_collected"], 0)
        self.assertEqual(gate["status"], "RESEARCH_INSUFFICIENT_DATA")
        self.assertFalse(gate["live_signal_enabled"])

    def test_production_data_ready_needs_all_three_confirmations(self):
        """The owner's own confirmations, read and never assumed."""
        for missing in ("data_rights_confirmed", "data_latency_confirmed",
                        "universe_confirmed"):
            with self.subTest(missing=missing):
                confirmations = dict(CONFIRMATIONS)
                confirmations.pop(missing)
                self.write_outcome(session_record(
                    "2026-10-13", data_confirmations=confirmations))
                row = session_history.session_rows()[0]
                self.assertEqual(row["data_quality"]["quality"], "verified")
                self.assertFalse(
                    row["data_quality"]["production_data_ready"],
                    f"{missing} was absent and production_data_ready said true")

    def test_config_confirmations_are_read_from_the_environment(self):
        with patch.dict("os.environ", {
                "KMIALL_DATA_RIGHTS_CONFIRMED": "true",
                "KMIALL_DATA_LATENCY_CONFIRMED": "true",
                "KMIALL_UNIVERSE_CONFIRMED": "true"}):
            self.assertTrue(config.production_data_ready())
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(config.production_data_ready())

    def test_the_label_maps_the_live_scanners_own_outcome(self):
        """TARGET_HIT is the +2% target touched; it is the gate's TP_FIRST."""
        self.write_outcome(session_record("2026-10-13", outcome="TARGET_HIT"))
        self.write_journal(session_record(
            "2026-10-14", outcome="CLOSED_AT_SESSION_END", target_hit=False,
            symbol="CNERGY", net_return=-0.004, gross_return=-0.003))
        rows = session_history.session_rows()
        labels = {row["date"]: row["label"] for row in rows}
        self.assertEqual(labels["2026-10-13"], "TP_FIRST")
        self.assertEqual(labels["2026-10-14"], "TIMEOUT")
        for row in rows:
            self.assertEqual(row["candidate"]["symbol"], row["symbol"])

    def test_a_no_candidate_day_contributes_no_trade(self):
        """A quiet day is a session, not a trade: it must not enter _metrics."""
        self.write_outcome(session_record(
            "2026-10-13", symbol=None, outcome="NO_CANDIDATE",
            gross_return=None, net_return=None, minutes_held=None,
            target_hit=False))
        row = session_history.session_rows()[0]
        self.assertIsNone(row["candidate"])
        self.assertIsNone(row["net_return"])
        metrics = forward_validation._metrics(
            forward_validation._rule_rows([row], config.SCANNER_VERSION))
        self.assertEqual(metrics["trades"], 0)

    def test_a_row_is_scored_under_its_own_scanner_version(self):
        """A momentum outcome can never be counted as an opening-range one."""
        self.write_outcome(session_record("2026-10-13"))
        row = session_history.session_rows()[0]
        self.assertEqual(forward_validation._own_rule(row), config.SCANNER_VERSION)

        live = forward_validation._metrics(forward_validation._rule_rows(
            [row], config.SCANNER_VERSION))
        self.assertEqual(live["trades"], 1)
        # The frozen opening-range cohort has its own label; this row is not it.
        for frozen in forward_validation.CANDIDATE_RULES:
            other = forward_validation._metrics(
                forward_validation._rule_rows([row], frozen))
            self.assertEqual(other["trades"], 0,
                             f"a live row was counted as {frozen}")

    def test_the_live_rule_is_registered_beside_the_frozen_library(self):
        self.assertIn(config.SCANNER_VERSION, forward_validation.REGISTERED_RULES)
        for frozen in forward_validation.CANDIDATE_RULES:
            self.assertIn(frozen, forward_validation.REGISTERED_RULES)

    def test_a_relay_failure_is_reported_and_never_fatal(self):
        """A runner with no relay still gets its local evidence scored."""
        self.write_outcome(session_record("2026-10-13"))
        unavailable = ([], "relay answered HTTP 503")
        with patch.object(session_history, "_relay_records",
                          lambda timeout_s=20.0: unavailable):
            report: dict = {}
            rows = session_history.session_rows(report=report)
        self.assertEqual(len(rows), 1)
        self.assertTrue(any(src.startswith("relay(") for src in report["sources"]),
                        "the relay's failure was not named in the report")
        self.assertEqual(report["sessions_verified"], 1)

    def test_records_without_a_date_are_dropped_and_reported(self):
        self.write_journal(session_record("2026-10-13"), {"symbol": "FCCL"})
        report: dict = {}
        rows = session_history.session_rows(report=report)
        self.assertEqual(len(rows), 1)
        self.assertEqual(report["sessions_dropped"],
                         ["record with no date"])

    def test_the_session_being_finalized_outranks_the_stored_copy(self):
        """A date is emitted once, from the newest source for that date."""
        self.write_journal(session_record("2026-10-13", symbol="OLD"))
        rows = session_history.session_rows(
            extra=[session_record("2026-10-13", symbol="NEW")])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "NEW")

    def test_the_gate_keeps_scoring_without_a_daily_outcome_file(self):
        """A fresh runner has no local file at all; that is not an error."""
        rows = session_history.session_rows()
        self.assertEqual(rows, [])
        gate = forward_validation.evaluate_gate(rows)
        self.assertEqual(gate["status"], "RESEARCH_INSUFFICIENT_DATA")
        self.assertEqual(gate["sessions_collected"], 0)


class FinalizeFeedsTheGateTest(unittest.TestCase):
    """The defect itself: the pipeline must not ask the gate an empty question."""

    def test_run_finalize_does_not_call_evaluate_gate_with_an_empty_list(self):
        """Audited at the call site, because the bug WAS the call site.

        The parse, not a substring search: the fix's own comment quotes the
        old bug, so a text match would be satisfied by the explanation rather
        than by the code. Paired with the behavioural coverage in
        tests/test_pipeline_paper_cycle.py, whose full cycle asserts that the
        finished gate reports the session it just scored.
        """
        source = (ROOT / "scripts" / "intraday_pipeline.py").read_text(
            encoding="utf-8")
        calls = [node for node in ast.walk(ast.parse(source))
                 if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "evaluate_gate"]
        self.assertTrue(calls, "run_finalize no longer asks the gate at all")
        for call in calls:
            self.assertEqual(len(call.args), 1)
            argument = call.args[0]
            self.assertFalse(
                isinstance(argument, ast.List) and not argument.elts,
                "evaluate_gate was handed a literal empty list")
            self.assertIn("session_history", ast.unparse(argument))


if __name__ == "__main__":
    unittest.main()
