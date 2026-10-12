"""The live session's two jobs: a running trade tape, and a published card.

Owner order 2026-10-12: the phone's card must carry the day's top three KMIALL
stocks with buy and sell volumes split from real-time trades. The split has one
genuine source, the broker's per-trade tape, and that tape exists only while
src/data/feed_capture.py runs for the session; the card reaches the phone only
because the snapshot is pushed to the relay. This module owns both halves, so
these tests pin the decisions that make them real:

  * liveness is read from the recorder's own heartbeat, so a killed capture is
    restarted rather than assumed alive;
  * a running tape is never restarted (a second capture would double-bank the
    same trades);
  * nothing here raises: a card or a tape that cannot be delivered is reported
    in words, because the caller is a scan tick whose verdict must not depend
    on the phone's card;
  * the split sentence says which leaders were measured and which were
    estimated, so the tick log never claims a proxy is order flow (SO-3).

Everything here is offline: the recorder's status file is a fixture, and the
relay is never contacted.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import live_card, market_snapshot  # noqa: E402

NOW = datetime.fromisoformat("2026-10-12T11:00:00+05:00")


class TapeStateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.status = Path(self._dir.name) / "status.json"
        self._real = live_card.STATUS_PATH
        live_card.STATUS_PATH = self.status
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        live_card.STATUS_PATH = self._real

    def write(self, **fields) -> None:
        self.status.write_text(json.dumps(fields), encoding="utf-8")

    def test_no_status_file_means_no_tape(self):
        alive, detail = live_card.tape_state(NOW)
        self.assertFalse(alive)
        self.assertIn("no broker tape is running", detail)

    def test_a_finished_run_is_not_a_running_tape(self):
        self.write(running=False, updated_at=NOW.isoformat())
        alive, detail = live_card.tape_state(NOW)
        self.assertFalse(alive)
        self.assertIn("ended", detail)

    def test_a_stale_heartbeat_is_not_a_running_tape(self):
        """A killed recorder leaves running=true and an old heartbeat behind."""
        stale = NOW - timedelta(seconds=live_card.TAPE_STALE_SECONDS + 1)
        self.write(running=True, updated_at=stale.isoformat(), counters={})
        alive, detail = live_card.tape_state(NOW)
        self.assertFalse(alive)
        self.assertIn("stopped reporting", detail)

    def test_a_fresh_heartbeat_is_a_live_tape(self):
        self.write(running=True, updated_at=NOW.isoformat(),
                   last_frame_at="2026-10-12T11:00:00.500+05:00",
                   counters={"messages": 42, "ticks": 900})
        alive, detail = live_card.tape_state(NOW)
        self.assertTrue(alive)
        self.assertIn("42 messages", detail)


class EnsureTapeTest(unittest.TestCase):
    def test_a_live_tape_is_never_started_twice(self):
        with mock.patch.object(live_card, "tape_state",
                               return_value=(True, "alive")), \
                mock.patch.object(live_card, "start_tape") as start:
            ok, detail = live_card.ensure_tape(NOW)
        start.assert_not_called()
        self.assertTrue(ok)
        self.assertEqual(detail, "alive")

    def test_a_dead_tape_is_restarted_with_the_reason(self):
        with mock.patch.object(live_card, "tape_state",
                               return_value=(False, "no tape")), \
                mock.patch.object(live_card, "start_tape",
                                  return_value=(True, "started pid 7")):
            ok, detail = live_card.ensure_tape(NOW)
        self.assertTrue(ok)
        self.assertIn("no tape", detail)
        self.assertIn("started pid 7", detail)

    def test_a_tape_that_cannot_start_says_so(self):
        with mock.patch.object(live_card, "tape_state",
                               return_value=(False, "no tape")), \
                mock.patch.object(live_card, "start_tape",
                                  return_value=(False, "python is missing")):
            ok, detail = live_card.ensure_tape(NOW)
        self.assertFalse(ok)
        self.assertIn("python is missing", detail)


class SplitSummaryTest(unittest.TestCase):
    def rows(self, methods) -> list[dict]:
        return [{"symbol": f"S{i}", "split_method": method}
                for i, method in enumerate(methods)]

    def test_all_measured(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["measured_tape"] * 3)})
        self.assertEqual(text, "B/S measured from the session tape for all 3 leaders")

    def test_all_tape_flow_says_projected_and_labelled(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["tape_flow"] * 3)})
        self.assertIn("tape's real-time prints", text)
        self.assertIn("estimate", text)

    def test_a_mixed_card_names_both_methods(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["measured_tape", "range_position", "range_position"])})
        self.assertIn("1 of 3 leaders split from the session tape", text)
        self.assertIn("estimated from the day's range", text)

    def test_nothing_available_is_stated_not_hidden(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["unavailable"] * 3)})
        self.assertIn("no split", text)

    def test_no_leaders_at_all(self):
        self.assertIn("no volume ranking", live_card.split_summary({}))


class PublishCardTest(unittest.TestCase):
    def snapshot(self, methods) -> dict:
        return {"top_volume": [{"symbol": "OGDC", "split_method": method}
                               for method in methods]}

    def test_a_dry_run_builds_and_never_pushes(self):
        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot(["measured_tape"])), \
                mock.patch.object(market_snapshot, "push_snapshot") as push:
            result = live_card.publish_card(NOW, dry_run=True)
        push.assert_not_called()
        self.assertTrue(result["ok"])
        self.assertIn("dry run", result["detail"])

    def test_a_published_card_reports_what_it_measured(self):
        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot(["measured_tape"])), \
                mock.patch.object(market_snapshot, "push_snapshot",
                                  return_value={"ok": True}):
            result = live_card.publish_card(NOW)
        self.assertTrue(result["ok"])
        self.assertIn("measured from the session tape", result["split"])

    def test_a_refusing_relay_is_reported_not_raised(self):
        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot(["measured_tape"])), \
                mock.patch.object(market_snapshot, "push_snapshot",
                                  return_value={"ok": False, "error": "no KV"}):
            result = live_card.publish_card(NOW)
        self.assertFalse(result["ok"])
        self.assertIn("no KV", result["detail"])

    def test_a_build_failure_is_reported_not_raised(self):
        def boom():
            raise RuntimeError("portal is down")

        with mock.patch.object(market_snapshot, "build_snapshot", boom):
            result = live_card.publish_card(NOW)
        self.assertFalse(result["ok"])
        self.assertIn("portal is down", result["detail"])

    def test_a_missing_credential_is_reported_not_raised(self):
        """The push fails closed with SystemExit; the tick must survive it."""
        def no_token(_snapshot):
            raise SystemExit("RELAY_ADMIN_TOKEN missing (env and .env)")

        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot(["range_position"])), \
                mock.patch.object(market_snapshot, "push_snapshot", no_token):
            result = live_card.publish_card(NOW)
        self.assertFalse(result["ok"])
        self.assertIn("RELAY_ADMIN_TOKEN missing", result["detail"])
        self.assertIn("estimated from the day's range", result["split"])


class RunOnceTest(unittest.TestCase):
    def test_both_halves_appear_in_one_log_line(self):
        """One line for the tick log, naming the tape and the card."""
        with mock.patch.object(live_card, "tape_state",
                               return_value=(True, "broker tape alive")), \
                mock.patch.object(market_snapshot, "build_snapshot",
                                  return_value={"top_volume": []}), \
                mock.patch.object(market_snapshot, "push_snapshot",
                                  return_value={"ok": True}):
            result = live_card.run_once(NOW, manage_tape=False)
        self.assertTrue(result["ok"])
        self.assertIn("tape: broker tape alive", result["detail"])
        self.assertIn("card: card published to the relay", result["detail"])
        self.assertIn("no volume ranking", result["split"])

    def test_a_dead_tape_does_not_stop_the_card(self):
        with mock.patch.object(live_card, "ensure_tape",
                               return_value=(False, "no tape and none started")), \
                mock.patch.object(market_snapshot, "build_snapshot",
                                  return_value={"top_volume": []}), \
                mock.patch.object(market_snapshot, "push_snapshot",
                                  return_value={"ok": True}):
            result = live_card.run_once(NOW)
        self.assertFalse(result["tape_ok"])
        self.assertTrue(result["card_ok"])
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
