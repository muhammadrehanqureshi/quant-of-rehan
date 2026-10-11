"""Offline tests for the sleep gate, including the weekend-to-open transition.

The deliverable this suite proves: the gate is IDLE across a weekend and across
every non-trading hour, and becomes ACTIVE at exactly the 09:32 open, without
ever consulting the network while it is asleep.

Every test is deterministic and offline. The portal is always mocked, so the
suite cannot depend on whether PSX happens to be trading today.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import session_gate as gate  # noqa: E402
from src.data.market_probe import (  # noqa: E402
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_UNKNOWN,
    MarketProbe,
)
from src.data.sessions import KARACHI  # noqa: E402


def at_karachi(year, month, day, hour, minute, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=KARACHI)


def fake_probe(status: str, raw_state: str | None = None,
               note: str = "mocked probe") -> MarketProbe:
    return MarketProbe(status=status, raw_state=raw_state, segment="REG",
                       url="https://dps.psx.example/",
                       checked_at="2026-10-12T10:00:00+05:00",
                       latency_ms=4, note=note)


# 2026-10-05 Mon, 10-09 Fri, 10-10 Sat, 10-11 Sun, 10-12 Mon.
SATURDAY = at_karachi(2026, 10, 10, 11, 52)
SUNDAY = at_karachi(2026, 10, 11, 11, 0)
MONDAY_MID_SESSION = at_karachi(2026, 10, 12, 11, 0)
FRIDAY_MID_SESSION = at_karachi(2026, 10, 9, 10, 0)


class TestIdleStates(unittest.TestCase):
    """Nothing that runs while the exchange is shut may touch the network."""

    def assert_sleeps_without_network(self, moment, expect_in_reason):
        with mock.patch("urllib.request.urlopen") as opened:
            decision = gate.session_gate(moment)
        self.assertFalse(decision.should_run)
        self.assertEqual(decision.probe_status, gate.PROBE_DISABLED)
        self.assertFalse(opened.called,
                         "an idle fire must not open a socket at all")
        self.assertIn(expect_in_reason, decision.reason)

    def test_saturday_is_idle(self):
        self.assert_sleeps_without_network(SATURDAY, "not a PSX trading day")

    def test_sunday_is_idle(self):
        self.assert_sleeps_without_network(SUNDAY, "not a PSX trading day")

    def test_psx_holiday_is_idle_even_though_it_is_a_friday(self):
        # 2026-08-14 is on the published PSX holiday list and is a Friday.
        self.assert_sleeps_without_network(
            at_karachi(2026, 8, 14, 11, 0), "not a PSX trading day")

    def test_pre_market_is_idle_and_never_scanned(self):
        # Owner order 2026-10-11: 09:00-09:15 is the pre-market window, and
        # the quant never scans in it.
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 12, 9, 0), "PRE_MARKET")

    def test_between_pre_market_and_the_open_is_idle(self):
        # 09:15-09:32 belongs to neither window.
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 12, 9, 20), "PRE_OPEN")

    def test_friday_midday_break_is_idle(self):
        # Friday is two bands; 13:00 PKT is inside the exchange's break.
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 9, 13, 0), "BREAK")

    def test_post_market_is_idle_and_never_scanned(self):
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 12, 15, 45), "POST_MARKET")

    def test_the_two_minute_gap_after_the_close_is_idle(self):
        # 15:30-15:32 is the owner's strict gap: no window owns it.
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 12, 15, 31), "POST_CLOSE")

    def test_friday_post_market_is_idle(self):
        self.assert_sleeps_without_network(
            at_karachi(2026, 10, 9, 16, 40), "POST_MARKET")

    def test_idle_decisions_report_the_next_edge(self):
        decision = gate.session_gate(SATURDAY)
        self.assertIsNotNone(decision.next_event)
        self.assertIn("PKT", decision.next_event)


class TestOwnerScanWindowOrder(unittest.TestCase):
    """Owner order 2026-10-11: scan only in MARKET, never pre or post market.

    The windows are checked independently of the band law, so a future band
    change cannot quietly re-enable scanning in them.
    """

    def test_pre_market_scan_is_refused_and_names_the_order(self):
        decision = gate.session_gate(at_karachi(2026, 10, 12, 9, 5))
        self.assertFalse(decision.should_run)
        self.assertIn("PRE_MARKET", decision.reason)
        self.assertIn("never scanned", decision.reason)
        self.assertIn("2026-10-11", decision.reason)

    def test_post_market_scan_is_refused_and_names_the_order(self):
        for moment in (at_karachi(2026, 10, 12, 15, 40),
                       at_karachi(2026, 10, 9, 16, 40)):
            decision = gate.session_gate(moment)
            self.assertFalse(decision.should_run, moment)
            self.assertIn("POST_MARKET", decision.reason)
            self.assertIn("never scanned", decision.reason)

    def test_finalize_is_allowed_in_the_post_market_window(self):
        # The finalize crons fire at 15:47 and 16:47 PKT, inside the
        # post-market window. A finalize values the closed session and is
        # not a scan, so the owner's order does not block it.
        decision = gate.session_gate(at_karachi(2026, 10, 12, 15, 47),
                                     purpose=gate.PURPOSE_FINALIZE)
        self.assertTrue(decision.should_run)
        self.assertIn("post-market window", decision.reason)

    def test_the_cadence_is_four_minutes(self):
        from src import config
        self.assertEqual(config.TICK_INTERVAL_MINUTES, 4)


class TestActiveStates(unittest.TestCase):
    def test_open_probe_runs_verified(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")):
            decision = gate.session_gate(MONDAY_MID_SESSION)
        self.assertTrue(decision.should_run)
        self.assertTrue(decision.verified)
        self.assertTrue(decision.law_open)
        self.assertEqual(decision.probe_status, STATUS_OPEN)

    def test_probe_is_only_consulted_while_a_band_is_live(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")) as probe:
            gate.session_gate(MONDAY_MID_SESSION)
            gate.session_gate(SATURDAY)
            gate.session_gate(at_karachi(2026, 10, 12, 9, 0))
        self.assertEqual(probe.call_count, 1,
                         "the probe must not run outside a live band")

    def test_warmup_window_counts_as_live(self):
        # TICK_WARMUP_MINUTES is 20, so 09:40 is inside the warmup band.
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")):
            decision = gate.session_gate(at_karachi(2026, 10, 12, 9, 40))
        self.assertTrue(decision.law_open)
        self.assertIn(decision.phase, ("WARMUP", "OPEN"))


class TestProbeOnlySubtractsConfidence(unittest.TestCase):
    def test_portal_reporting_shut_stops_the_scan(self):
        """An unexpected closure must not be scanned as if it were trading."""
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_CLOSED,
                                                       "Suspended")):
            decision = gate.session_gate(MONDAY_MID_SESSION)
        self.assertFalse(decision.should_run)
        self.assertTrue(decision.verified)
        self.assertIn("exchange shut", decision.reason)
        self.assertEqual(decision.probe_state, "Suspended")

    def test_unreadable_portal_still_runs_on_the_law(self):
        """A blocked portal must never silence a session the law calls live."""
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_UNKNOWN, None,
                                                       note="portal unreachable")):
            decision = gate.session_gate(MONDAY_MID_SESSION)
        self.assertTrue(decision.should_run)
        self.assertFalse(decision.verified)
        self.assertIn("session law decides", decision.reason)

    def test_probe_disabled_uses_the_law_alone(self):
        with mock.patch("urllib.request.urlopen") as opened:
            decision = gate.session_gate(MONDAY_MID_SESSION, probe=False)
        self.assertTrue(decision.should_run)
        self.assertFalse(decision.verified)
        self.assertEqual(decision.probe_status, gate.PROBE_DISABLED)
        self.assertFalse(opened.called)

    def test_a_dead_network_is_a_real_unverified_run(self):
        """End to end with the socket genuinely broken."""
        import urllib.error
        with mock.patch("urllib.request.urlopen",
                        side_effect=urllib.error.URLError("dns")):
            decision = gate.session_gate(MONDAY_MID_SESSION)
        self.assertTrue(decision.should_run)
        self.assertFalse(decision.verified)
        self.assertEqual(decision.probe_status, STATUS_UNKNOWN)


class TestProbeFlagComesFromConfig(unittest.TestCase):
    """PSX_PROBE_ENABLED is the operator's escape hatch, so it must be read."""

    def test_probe_on_by_default_consults_the_portal(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")) as probe:
            gate.session_gate(MONDAY_MID_SESSION)
        self.assertEqual(probe.call_count, 1)

    def test_disabling_the_probe_in_config_stops_the_network_call(self):
        with mock.patch.object(gate.config, "PSX_PROBE_ENABLED", False):
            with mock.patch("urllib.request.urlopen") as opened:
                decision = gate.session_gate(MONDAY_MID_SESSION)
        self.assertTrue(decision.should_run, "the law alone decides")
        self.assertFalse(decision.verified)
        self.assertEqual(decision.probe_status, gate.PROBE_DISABLED)
        self.assertFalse(opened.called)

    def test_an_explicit_probe_argument_overrides_config(self):
        with mock.patch.object(gate.config, "PSX_PROBE_ENABLED", False):
            with mock.patch.object(gate, "probe_market_state",
                                   return_value=fake_probe(STATUS_OPEN,
                                                           "Open")) as probe:
                gate.session_gate(MONDAY_MID_SESSION, probe=True)
        self.assertEqual(probe.call_count, 1)


class TestForce(unittest.TestCase):
    def test_force_runs_on_a_weekend(self):
        with mock.patch("urllib.request.urlopen") as opened:
            decision = gate.session_gate(SATURDAY, force=True)
        self.assertTrue(decision.should_run)
        self.assertTrue(decision.forced)
        self.assertFalse(opened.called)


class TestWeekendToOpenTransition(unittest.TestCase):
    """The idle/active flip the request asks for, asserted minute by minute."""

    TIMELINE = (
        # (instant, expected should_run)
        (at_karachi(2026, 10, 10, 9, 0), False),    # Saturday, before hours
        (at_karachi(2026, 10, 10, 11, 52), False),  # Saturday, mid session
        (at_karachi(2026, 10, 10, 16, 0), False),   # Saturday, after hours
        (at_karachi(2026, 10, 11, 10, 0), False),   # Sunday
        (at_karachi(2026, 10, 11, 15, 0), False),   # Sunday
        (at_karachi(2026, 10, 12, 9, 0), False),    # Monday pre-open
        (at_karachi(2026, 10, 12, 9, 31), False),   # one minute before open
        (at_karachi(2026, 10, 12, 9, 32), True),    # THE 09:32 OPEN
        (at_karachi(2026, 10, 12, 10, 0), True),    # inside the session
        (at_karachi(2026, 10, 12, 15, 29), True),   # one minute before close
        (at_karachi(2026, 10, 12, 15, 30), False),  # the 15:30 close
        (at_karachi(2026, 10, 12, 20, 0), False),   # Monday evening
    )

    def test_state_flips_exactly_at_the_open_and_the_close(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")) as probe:
            for moment, expected in self.TIMELINE:
                with self.subTest(at=moment.isoformat()):
                    decision = gate.session_gate(moment)
                    self.assertEqual(decision.should_run, expected,
                                     decision.reason)
        self.assertEqual(probe.call_count,
                         sum(1 for _, expected in self.TIMELINE if expected),
                         "the probe must be consulted exactly on the live slots")

    def test_saturday_and_monday_open_disagree(self):
        """Same wall-clock time, different verdict: the weekend is the difference."""
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")):
            idle = gate.session_gate(at_karachi(2026, 10, 10, 10, 0))
            active = gate.session_gate(at_karachi(2026, 10, 12, 10, 0))
        self.assertFalse(idle.should_run)
        self.assertTrue(active.should_run)
        self.assertEqual(idle.phase, "CLOSED")
        self.assertFalse(idle.trading_day)
        self.assertTrue(active.trading_day)

    def test_friday_afternoon_band_reopens_after_the_break(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")):
            before = gate.session_gate(at_karachi(2026, 10, 9, 13, 0))
            after = gate.session_gate(at_karachi(2026, 10, 9, 14, 32))
        self.assertFalse(before.should_run, "inside the Friday break")
        self.assertTrue(after.should_run, "Friday session two is live")


class TestFinalizePurpose(unittest.TestCase):
    """A finalize is about a session that has ENDED, so it sleeps until then.

    The finalize crons fire at 15:47 and 16:47 PKT, outside every band. Gating
    them on "is a band live" would silently delete the daily outcome.
    """

    def test_finalize_waits_until_after_the_close(self):
        with mock.patch("urllib.request.urlopen") as opened:
            decision = gate.session_gate(at_karachi(2026, 10, 12, 14, 0),
                                         purpose=gate.PURPOSE_FINALIZE)
        self.assertFalse(decision.should_run)
        self.assertIn("has not closed yet", decision.reason)
        self.assertFalse(opened.called)

    def test_finalize_runs_after_the_close(self):
        with mock.patch("urllib.request.urlopen") as opened:
            decision = gate.session_gate(at_karachi(2026, 10, 12, 15, 47),
                                         purpose=gate.PURPOSE_FINALIZE)
        self.assertTrue(decision.should_run)
        self.assertEqual(decision.phase, "POST_CLOSE")
        self.assertFalse(opened.called,
                         "a finalize reads captured bars, not the portal")

    def test_friday_finalize_runs_after_the_later_close(self):
        decision = gate.session_gate(at_karachi(2026, 10, 9, 16, 47),
                                     purpose=gate.PURPOSE_FINALIZE)
        self.assertTrue(decision.should_run)

    def test_friday_finalize_waits_through_the_break(self):
        decision = gate.session_gate(at_karachi(2026, 10, 9, 13, 0),
                                     purpose=gate.PURPOSE_FINALIZE)
        self.assertFalse(decision.should_run)
        self.assertEqual(decision.phase, "BREAK")

    def test_finalize_still_sleeps_on_a_weekend(self):
        decision = gate.session_gate(SATURDAY,
                                     purpose=gate.PURPOSE_FINALIZE)
        self.assertFalse(decision.should_run)
        self.assertIn("not a PSX trading day", decision.reason)


class TestSchedulePlan(unittest.TestCase):
    """The cron -> work mapping lives in Python so it can be tested at all."""

    WORKFLOW = (Path(__file__).resolve().parents[1] / ".github" / "workflows"
                / "intraday-capture.yml")

    def test_workflow_crons_all_have_a_plan(self):
        import re
        crons = re.findall(r'^\s*-\s*cron:\s*"([^"]+)"',
                           self.WORKFLOW.read_text(encoding="utf-8"), re.M)
        self.assertEqual(len(crons), 7, "the workflow should still declare 7 crons")
        for cron in crons:
            with self.subTest(cron=cron):
                self.assertIn(gate.normalise_schedule(cron), gate.SCHEDULE_PLAN)

    def test_plan_has_no_crons_the_workflow_does_not_declare(self):
        import re
        declared = {gate.normalise_schedule(c) for c in re.findall(
            r'^\s*-\s*cron:\s*"([^"]+)"',
            self.WORKFLOW.read_text(encoding="utf-8"), re.M)}
        self.assertEqual(declared, set(gate.SCHEDULE_PLAN))

    def test_scan_schedules_carry_their_slot(self):
        for cron, slot in (("7 5 * * 1-5", "10:00"),
                           ("37 6 * * 1-5", "11:30"),
                           ("7 8 * * 1-4", "13:00"),
                           ("37 9 * * 1-5", "14:30"),
                           ("7 11 * * 5", "16:00")):
            with self.subTest(cron=cron):
                self.assertEqual(gate.plan_for(cron),
                                 (gate.PURPOSE_SCAN, slot))

    def test_the_two_post_close_crons_are_the_only_finalizes(self):
        finalizes = [cron for cron, (purpose, _) in gate.SCHEDULE_PLAN.items()
                     if purpose == gate.PURPOSE_FINALIZE]
        self.assertEqual(sorted(finalizes), ["47 10 * * 1-4", "47 11 * * 5"])

    def test_plan_lookup_tolerates_extra_whitespace(self):
        self.assertEqual(gate.plan_for("  47   10   *  *  1-4 "),
                         (gate.PURPOSE_FINALIZE, None))

    def test_an_unknown_cron_defaults_to_a_plain_scan(self):
        self.assertEqual(gate.plan_for("0 0 * * *"),
                         (gate.PURPOSE_SCAN, None))


class TestCiContract(unittest.TestCase):
    """The workflow reads should_run, so the emitted contract is tested."""

    def test_emit_writes_a_parseable_should_run(self):
        decision = gate.session_gate(SATURDAY)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            summary = Path(tmp) / "summary"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out),
                                              "GITHUB_STEP_SUMMARY": str(summary)}):
                gate._emit(decision, verbose=True)
            lines = out.read_text(encoding="utf-8").splitlines()
            keys = dict(line.split("=", 1) for line in lines if "=" in line)
            self.assertEqual(keys["should_run"], "false")
            self.assertEqual(keys["verified"], "false")
            self.assertNotIn("\n", keys["reason"])
            self.assertIn("Session gate: SLEEP", summary.read_text(encoding="utf-8"))

    def test_emit_reports_a_run_for_a_live_band(self):
        with mock.patch.object(gate, "probe_market_state",
                               return_value=fake_probe(STATUS_OPEN, "Open")):
            decision = gate.session_gate(MONDAY_MID_SESSION)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out),
                                              "GITHUB_STEP_SUMMARY": ""}):
                gate._emit(decision)
            keys = dict(line.split("=", 1)
                        for line in out.read_text(encoding="utf-8").splitlines()
                        if "=" in line)
        self.assertEqual(keys["should_run"], "true")
        self.assertEqual(keys["verified"], "true")

    def test_emit_publishes_the_scan_slot_and_purpose(self):
        decision = gate.session_gate(MONDAY_MID_SESSION, probe=False,
                                     slot="11:30")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out),
                                              "GITHUB_STEP_SUMMARY": ""}):
                gate._emit(decision)
            keys = dict(line.split("=", 1)
                        for line in out.read_text(encoding="utf-8").splitlines()
                        if "=" in line)
        self.assertEqual(keys["should_run"], "true")
        self.assertEqual(keys["purpose"], "scan")
        self.assertEqual(keys["slot"], "11:30")

    def test_emit_publishes_an_empty_slot_for_a_finalize(self):
        decision = gate.session_gate(at_karachi(2026, 10, 12, 15, 47),
                                     purpose=gate.PURPOSE_FINALIZE)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output"
            with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(out),
                                              "GITHUB_STEP_SUMMARY": ""}):
                gate._emit(decision)
            keys = dict(line.split("=", 1)
                        for line in out.read_text(encoding="utf-8").splitlines()
                        if "=" in line)
        self.assertEqual(keys["should_run"], "true")
        self.assertEqual(keys["purpose"], "finalize")
        self.assertEqual(keys["slot"], "")

    def test_one_line_flattens_newlines(self):
        self.assertEqual(gate._one_line("a\nb\r\nc"), "a b c")

    def test_cli_exits_zero_while_asleep(self):
        # A sleeping day is a correct day, so a scheduled run must stay green.
        idle = gate.session_gate(SATURDAY)
        self.assertFalse(idle.should_run)
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": "",
                                          "GITHUB_STEP_SUMMARY": ""}):
            with mock.patch.object(gate, "session_gate", return_value=idle):
                self.assertEqual(gate.main(["--check", "--no-probe"]), 0)


if __name__ == "__main__":
    unittest.main()
