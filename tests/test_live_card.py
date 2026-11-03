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

    def test_a_running_tape_names_the_recorders_last_error(self):
        """A tape that cannot reach the venue says why, in the caller's log."""
        self.write(running=True, updated_at=NOW.isoformat(),
                   last_frame_at=None, counters={"messages": 0},
                   last_error="ConnectionError: all feed hosts unreachable")
        alive, detail = live_card.tape_state(NOW)
        self.assertTrue(alive)
        self.assertIn("last error: ConnectionError: all feed hosts "
                      "unreachable", detail)


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


class _Child:
    """A spawned recorder: a pid, and either dead at once or still running."""

    def __init__(self, code: int | None = None) -> None:
        self.pid = 4242
        self._code = code

    def poll(self) -> int | None:
        return self._code


class StartTapeProbeTest(unittest.TestCase):
    """A started child is not a running tape until it survives the start.

    Measured 2026-10-14 on a GitHub Actions runner: the recorder died in
    under a second (its universe file was gitignored) while start_tape
    reported success, so all five cycles of the 30 second loop blamed the
    tape for bars a dead child never wrote.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "feed_capture.log"
        self._real_log = live_card.TAPE_LOG
        live_card.TAPE_LOG = self.log
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        live_card.TAPE_LOG = self._real_log

    def _start(self, child) -> tuple[bool, str]:
        with mock.patch.object(live_card.subprocess, "Popen",
                               return_value=child), \
                mock.patch.object(live_card, "ROOT",
                                  Path(self._dir.name)), \
                mock.patch.object(live_card, "START_PROBE_SECONDS", 0.05):
            return live_card.start_tape()

    def test_a_child_that_dies_at_start_is_a_failed_start(self):
        self.log.write_text(
            "FileNotFoundError: KMIALL universe file not found: "
            "data/legacy_sentinel/data/kmiall_tickers.json\n",
            encoding="utf-8")
        ok, detail = self._start(_Child(code=1))
        self.assertFalse(ok)
        self.assertIn("exited with code 1", detail)
        self.assertIn("FileNotFoundError", detail)

    def test_a_child_that_survives_the_window_is_started(self):
        ok, detail = self._start(_Child(code=None))
        self.assertTrue(ok)
        self.assertIn("broker tape started (pid 4242)", detail)

    def test_the_recorder_runs_unbuffered_so_its_log_is_usable(self):
        """Measured 2026-10-14: the cloud's feed_capture.log came back empty.

        The child's stdout is a file, so Python block buffers it; without -u
        the recorder's own lines never reach logs/feed_capture.log and a
        venue failure cannot be read from the band's artifact.
        """
        child = _Child(code=None)
        with mock.patch.object(live_card.subprocess, "Popen",
                               return_value=child) as popen, \
                mock.patch.object(live_card, "ROOT",
                                  Path(self._dir.name)), \
                mock.patch.object(live_card, "START_PROBE_SECONDS", 0.05):
            live_card.start_tape()
        command = popen.call_args.args[0]
        self.assertEqual(command[1:4], ["-u", "-m", "src.data.feed_capture"])

    def test_probe_watches_until_the_child_exits(self):
        child = _Child(code=None)
        child.poll = mock.Mock(side_effect=[None, None, 1])
        self.assertEqual(live_card._probe_child(child, 0.5), 1)
        self.assertEqual(child.poll.call_count, 3)

    def test_probe_gives_up_after_the_window(self):
        """Still running at the deadline means started, not dead."""
        self.assertIsNone(live_card._probe_child(_Child(code=None), 0.05))


class SplitSummaryTest(unittest.TestCase):
    def rows(self, methods) -> list[dict]:
        return [{"symbol": f"S{i}", "split_method": method}
                for i, method in enumerate(methods)]

    def test_the_framed_card_says_one_law_for_all_leaders(self):
        """Owner order 2026-10-30: the row's own frame is the only source."""
        text = live_card.split_summary({"top_volume": self.rows(
            ["range_position"] * 3)})
        self.assertEqual(
            text,
            "B/S from the row's own published frame, the same law the "
            "search box shows, for all 3 leaders")

    def test_a_legacy_tape_card_is_named_not_claimed_as_measurement(self):
        """If a legacy tape method ever stands on a row again, the sentence
        names the tape rather than calling the card measured."""
        text = live_card.split_summary({"top_volume": self.rows(
            ["measured_tape"] * 3)})
        self.assertIn("split from the session tape", text)
        counted = live_card.split_summary({"top_volume": self.rows(
            ["tape_counts"] * 3)})
        self.assertIn("split from the session tape", counted)
        self.assertNotIn("for all", counted)
        self.assertNotIn("for all 3 leaders measured", counted)

    def test_a_mixed_card_names_both_methods(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["measured_tape", "range_position", "range_position"])})
        self.assertIn("1 of 3 leaders split from the session tape", text)
        self.assertIn("estimated from the row's own frame", text)
        counted = live_card.split_summary({"top_volume": self.rows(
            ["tape_counts", "tape_counts", "range_position"])})
        self.assertIn("2 of 3 leaders split from the session tape", counted)
        self.assertIn("estimated from the row's own frame", counted)

    def test_nothing_available_is_stated_not_hidden(self):
        text = live_card.split_summary({"top_volume": self.rows(
            ["unavailable"] * 3)})
        self.assertIn("no split", text)

    def test_no_leaders_at_all(self):
        self.assertIn("no volume ranking", live_card.split_summary({}))


class PublishCardTest(unittest.TestCase):
    def setUp(self) -> None:
        # Each test starts with no pushed card: the throttle ledger is per
        # process and the test process is shared across these classes.
        live_card.CARD_PUSH_STATE["signature"] = None
        live_card.CARD_PUSH_STATE["epoch"] = 0.0

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
        self.assertIn("split from the session tape", result["split"])

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
        self.assertIn("the same law the search box shows", result["split"])


class RunOnceTest(unittest.TestCase):
    def setUp(self) -> None:
        live_card.CARD_PUSH_STATE["signature"] = None
        live_card.CARD_PUSH_STATE["epoch"] = 0.0

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


class CardPushThrottleTest(unittest.TestCase):
    """Owner order 2026-11-03: the card push never burns the request cap.

    On 2026-11-02 Cloudflare emailed the daily request limit to the owner
    twice: the Workers free plan grants 100,000 requests a day and alerts
    at 80% and 100%, and a day with overlapping loop runners pushed the
    card once a second, about 21,600 requests per loop per session. The
    edge serves a pushed card for five minutes, so these laws are pinned:

      * the first card of a fresh process is always pushed;
      * a card whose content matches the last push is never sent again,
        and clock labels alone are not card content;
      * a changed card is sent at most once per minute, and the tick log
        says the pushed card stands;
      * a refused push never claims an interval: the next cycle retries
        immediately instead of waiting out the throttle.
    """

    def snapshot(self, volume: int = 10, as_of: str = "11:00:00") -> dict:
        return {
            "as_of": f"2026-10-12T{as_of}+05:00",
            "top_volume": [{"symbol": "OGDC", "volume": volume,
                            "split_method": "range_position"}],
        }

    def reset(self) -> None:
        live_card.CARD_PUSH_STATE["signature"] = None
        live_card.CARD_PUSH_STATE["epoch"] = 0.0

    def setUp(self) -> None:
        self.reset()

    def tearDown(self) -> None:
        self.reset()

    def test_the_first_card_of_a_fresh_process_is_pushed(self):
        calls: list[dict] = []

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return {"ok": True}

        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot()),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            result = live_card.publish_card(NOW)
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)
        self.assertIn("card published to the relay", result["detail"])

    def test_an_identical_card_is_never_pushed_twice(self):
        calls: list[dict] = []

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return {"ok": True}

        with mock.patch.object(market_snapshot, "build_snapshot",
                               return_value=self.snapshot()),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            live_card.publish_card(NOW)
            later = NOW + timedelta(seconds=120)
            again = live_card.publish_card(later)
        self.assertTrue(again["ok"])
        self.assertEqual(len(calls), 1)
        self.assertIn("card unchanged since the last push", again["detail"])

    def test_clock_labels_alone_are_not_card_content(self):
        calls: list[dict] = []

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return {"ok": True}

        builds = iter([self.snapshot(as_of="11:00:00"),
                       self.snapshot(as_of="11:00:01")])
        with mock.patch.object(market_snapshot, "build_snapshot",
                               side_effect=lambda: next(builds)),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            live_card.publish_card(NOW)
            later = NOW + timedelta(seconds=2)
            again = live_card.publish_card(later)
        self.assertEqual(len(calls), 1)
        self.assertIn("card unchanged since the last push", again["detail"])

    def test_a_changed_card_inside_the_interval_waits(self):
        calls: list[dict] = []

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return {"ok": True}

        builds = iter([self.snapshot(volume=10), self.snapshot(volume=11)])
        with mock.patch.object(market_snapshot, "build_snapshot",
                               side_effect=lambda: next(builds)),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            live_card.publish_card(NOW)
            later = NOW + timedelta(seconds=5)
            again = live_card.publish_card(later)
        self.assertTrue(again["ok"])
        self.assertEqual(len(calls), 1)
        self.assertIn("push interval", again["detail"])

    def test_a_changed_card_after_the_interval_pushes(self):
        calls: list[dict] = []

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return {"ok": True}

        builds = iter([self.snapshot(volume=10), self.snapshot(volume=11)])
        with mock.patch.object(market_snapshot, "build_snapshot",
                               side_effect=lambda: next(builds)),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            live_card.publish_card(NOW)
            later = NOW + timedelta(
                seconds=live_card.CARD_PUSH_MIN_INTERVAL_SECONDS + 1)
            again = live_card.publish_card(later)
        self.assertEqual(len(calls), 2)
        self.assertIn("card published to the relay", again["detail"])

    def test_a_refused_push_never_opens_the_interval(self):
        calls: list[dict] = []
        answers = iter([{"ok": False, "error": "no KV"},
                        {"ok": True}])

        def push(snapshot: dict) -> dict:
            calls.append(snapshot)
            return next(answers)

        builds = iter([self.snapshot(volume=10), self.snapshot(volume=11)])
        with mock.patch.object(market_snapshot, "build_snapshot",
                               side_effect=lambda: next(builds)),                 mock.patch.object(market_snapshot, "push_snapshot", push):
            refused = live_card.publish_card(NOW)
            later = NOW + timedelta(seconds=5)
            retry = live_card.publish_card(later)
        self.assertFalse(refused["ok"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(retry["ok"])
        self.assertIn("card published to the relay", retry["detail"])


if __name__ == "__main__":
    unittest.main()
