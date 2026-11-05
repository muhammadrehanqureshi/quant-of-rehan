"""The recorder's universe: the tracked KMIALL list, never a guessed one.

The read-only recorder (src/data/feed_capture.py) subscribes to the venue for
the symbols the scanner scans, and it refuses to invent that list (SO-3). Its
universe used to be data/legacy_sentinel/data/kmiall_tickers.json, which is
gitignored under /data/: measured 2026-10-14 on a GitHub Actions runner the
child died with FileNotFoundError before it could write status.json, the
session loop never saw a tape, and five consecutive 30 second cycles faulted
without banking a bar.

These tests pin the fix. The default universe is a tracked file under src/,
it exists on a fresh checkout, it selects exactly the symbols
scripts/intraday_pipeline.load_kmiall scans, and a missing file is still
refused in words rather than replaced with a guess. Everything here is
offline: no socket is opened and no recorder is started.
"""

from __future__ import annotations

import socket
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.intraday_pipeline import load_kmiall  # noqa: E402
from src.data import feed_capture, quote_flow  # noqa: E402


class PublisherRetryCapTest(unittest.TestCase):
    """Owner order 2026-10-30: the phone's numbers must move at the
    broker's own one-second cadence, so one failed quote push may not
    retire the feed for half a minute. The backoff doubles from 1s but
    stops at the 5s cap, and a success handback resets it to the floor."""

    def test_the_retry_cap_is_a_five_second_wall_not_thirty(self):
        self.assertEqual(feed_capture.RelayQuotePublisher.MAX_RETRY_SECONDS,
                         5.0)

    def test_a_hub_that_refuses_with_5xx_gets_thirty_second_retries(self):
        """Owner order 2026-11-05: a hub whose daily budget is spent (its
        5xx answers reset 00:00 UTC) must not have the whole session's
        request budget spent against it every five seconds. The 5-second
        wall stays the cap for data refusals; a 5xx floor moves to 30
        seconds until the relay answers again."""
        self.assertEqual(
            feed_capture.RelayQuotePublisher.REFUSAL_RETRY_SECONDS, 30.0)
        self.assertGreater(feed_capture.RelayQuotePublisher.REFUSAL_RETRY_SECONDS,
                           feed_capture.RelayQuotePublisher.MAX_RETRY_SECONDS)

    def test_a_success_resets_the_floor_below_the_cap(self):
        self.assertLess(feed_capture.RelayQuotePublisher.MIN_PUBLISH_SECONDS,
                        feed_capture.RelayQuotePublisher.MAX_RETRY_SECONDS)

    def test_the_publisher_reuses_one_http_connection(self):
        source = Path(feed_capture.__file__).read_text(encoding="utf-8")
        self.assertIn("session = requests.Session()", source)
        self.assertIn("session.post(", source)


class CaptureFlowSeedTest(unittest.TestCase):
    """Owner order 2026-11-05: a restarted capture continues the day.

    The 12:30 band starts a new process while the hub already holds the
    morning. Seeding from the relay's same-day pair keeps the day's buy and
    sell moving; a previous day's pair must never become today's baseline.
    """

    ROWS = [{"symbol": "SAZEW", "volume": 270414, "buy_volume": 137493,
             "sell_volume": 109942, "flow_baseline": 22979,
             "split_method": "quote_rule"}]

    def test_a_same_day_pair_is_adopted_whole(self):
        flow = quote_flow.QuoteFlow()
        adopted = feed_capture.seed_day_flow(
            flow, {"ok": True, "day": "2026-11-05", "rows": self.ROWS},
            "2026-11-05")
        self.assertEqual(adopted, 1)
        quote = flow.observe({"symbol": "SAZEW", "price": 1430.0,
                              "bid": 1429.9, "ask": 1430.1,
                              "volume": 270414})
        self.assertEqual(quote["measured_buy"], 137493)
        self.assertEqual(quote["measured_sell"], 109942)
        self.assertEqual(quote["flow_baseline"], 22979)

    def test_an_earlier_days_pair_is_refused(self):
        flow = quote_flow.QuoteFlow()
        adopted = feed_capture.seed_day_flow(
            flow, {"ok": True, "day": "2026-11-04", "rows": self.ROWS},
            "2026-11-05")
        self.assertEqual(adopted, 0)
        self.assertEqual(flow.symbols, {})
        quote = flow.observe({"symbol": "SAZEW", "price": 1430.0,
                              "bid": 1429.9, "ask": 1430.1,
                              "volume": 270414})
        self.assertEqual(quote["measured_buy"], 0)
        self.assertEqual(quote["flow_baseline"], 270414)

    def test_a_refused_answer_seeds_nothing(self):
        flow = quote_flow.QuoteFlow()
        self.assertEqual(feed_capture.seed_day_flow(
            flow, {"ok": False, "day": "2026-11-05", "rows": self.ROWS},
            "2026-11-05"), 0)
        self.assertEqual(flow.symbols, {})

    def test_the_publisher_seeds_before_it_starts_the_push_thread(self):
        source = Path(feed_capture.__file__).read_text(encoding="utf-8")
        init = source[source.index("class RelayQuotePublisher"):]
        init = init[init.index("def __init__"):init.index("def observe")]
        self.assertIn("adopted = self._seed_day_flow()", init)
        self.assertIn("if self._seed_required and adopted == 0", init)
        self.assertIn("self._flow.seed_preopen(", init)
        self.assertLess(init.index("adopted = self._seed_day_flow()"),
                        init.index("self._thread.start()"))

    def test_a_zero_volume_pre_open_row_reaches_the_flow_not_the_app(self):
        update = feed_capture.relay_quote_updates({
            "kind": "MKT-FEED",
            "ts": "2026-11-05T08:55:00+05:00",
            "ticks": [{"market": "REG", "scrip": "KEL", "last": "0",
                       "bid": "6.10", "ask": "6.20", "volume": "0"}],
        })
        self.assertEqual(len(update["quotes"]), 1)
        quote = update["quotes"][0]
        self.assertTrue(quote["flow_only"])
        self.assertEqual(quote["volume"], 0)
        quote = quote_flow.QuoteFlow().observe(quote)
        self.assertEqual(quote["flow_baseline"], 0)
        self.assertEqual(quote["flow_baseline_reason"], "zero_baseline")

    def test_a_nonzero_no_price_row_stays_baseline_not_sided(self):
        flow = quote_flow.QuoteFlow()
        flow.seed_preopen(["KEL"], "2026-11-05T08:55:00+05:00")
        update = feed_capture.relay_quote_updates({
            "kind": "MKT-FEED",
            "ts": "2026-11-05T09:15:00+05:00",
            "ticks": [{"market": "REG", "scrip": "KEL", "last": "",
                       "bid": "6.10", "ask": "6.20",
                       "volume": "7000000"}],
        })
        quote = update["quotes"][0]
        self.assertTrue(quote["flow_only"])
        quote = flow.observe(quote)
        self.assertEqual(quote["flow_baseline"], 7_000_000)
        self.assertEqual(quote["flow_baseline_reason"], "no_price")
        update = feed_capture.relay_quote_updates({
            "kind": "MKT-FEED",
            "ts": "2026-11-05T09:16:00+05:00",
            "ticks": [{"market": "REG", "scrip": "KEL", "last": "6.20",
                       "bid": "6.10", "ask": "6.20",
                       "volume": "7000000"}],
        })
        quote = flow.observe(update["quotes"][0])
        self.assertEqual(quote["buy_volume"], 0)
        self.assertEqual(quote["flow_baseline"], 7_000_000)

    def test_the_publisher_never_publishes_a_flow_only_row(self):
        source = Path(feed_capture.__file__).read_text(encoding="utf-8")
        self.assertIn('if not quote.get("flow_only")]', source)

    def test_the_restart_seed_is_required_once_the_preopen_starts(self):
        tz = feed_capture.KARACHI
        self.assertFalse(feed_capture.session_has_opened(
            datetime(2026, 11, 5, 8, 55, tzinfo=tz)))
        self.assertFalse(feed_capture.session_has_opened(
            datetime(2026, 11, 5, 9, 14, tzinfo=tz)))
        self.assertTrue(feed_capture.session_has_opened(
            datetime(2026, 11, 5, 9, 15, tzinfo=tz)))
        self.assertTrue(feed_capture.session_has_opened(
            datetime(2026, 11, 5, 12, 30, tzinfo=tz)))
        self.assertFalse(feed_capture.session_has_opened(
            datetime(2026, 11, 6, 8, 59, tzinfo=tz)))
        self.assertTrue(feed_capture.session_has_opened(
            datetime(2026, 11, 6, 9, 0, tzinfo=tz)))


class DefaultUniverseTest(unittest.TestCase):
    def test_the_default_universe_is_tracked_not_local_only(self):
        """A fresh checkout must have the file, so it lives under src/."""
        flat = str(feed_capture.UNIVERSE_FILE).replace("\\", "/")
        self.assertTrue(flat.endswith("src/data/universe_kmiall.json"),
                        f"unexpected default universe: {flat}")
        self.assertTrue(feed_capture.UNIVERSE_FILE.is_file())

    def test_the_recorder_subscribes_to_exactly_what_the_scanner_scans(self):
        """Same list, so a tape bar can never mean a different universe."""
        self.assertEqual(set(feed_capture.load_universe()), set(load_kmiall()))

    def test_the_default_universe_is_not_empty(self):
        self.assertGreaterEqual(len(feed_capture.load_universe()), 20)


class _FakeSocket:
    """A socket that hands back queued frames and then goes silent.

    Silence is `socket.timeout`, which is what the real read loop sees when a
    venue stops pushing without closing the connection: heartbeats keep being
    sent, nothing comes back.
    """

    def __init__(self, frames: list[bytes]) -> None:
        self.frames = list(frames)
        self.sent: list[bytes] = []
        self.closed = False

    def settimeout(self, _seconds):  # noqa: D401 - socket API
        return None

    def recv(self, _size):
        if self.frames:
            return self.frames.pop(0)
        raise socket.timeout()

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def close(self) -> None:
        self.closed = True


class StallWatchdogTest(unittest.TestCase):
    """A venue that stops pushing must not become a tape that ages out.

    Measured 2026-10-16 inside the live Friday band: two fresh connections
    were each answered with ONE full universe sweep (32 MKT-FEED frames, 315
    rows) and then nothing; one stall ran five consecutive minutes before the
    sweeps came back. Re-sending the subscription did not restore the stream,
    but a new connection is answered with a fresh sweep every time. Before
    this watchdog the recorder sat on the dead push while its heartbeat kept
    status.json looking healthy, and every later scan read stale leaders.
    """

    BANNER = b"Welcome*%"
    SWEEP = (b"MKT-FEED*SAZEW;REG;310;1533.20;1534.95;36;OPN;-;-8.18;"
             b"10:05:39;1533.20; ;1538.68;1549.00;1;22400;1;1535.00;%")

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        capture_dir = Path(self._dir.name)
        for name in ("CAPTURE_DIR", "STATUS_PATH"):
            original = getattr(feed_capture, name)
            replacement = (capture_dir if name == "CAPTURE_DIR"
                           else capture_dir / "status.json")
            patcher = mock.patch.object(feed_capture, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        # No real backoff sleep: the escalation itself is already covered by
        # the loop's own tests, and a 2s sleep per reconnect would make this
        # test slow enough to be skipped by hand.
        sleeper = mock.patch.object(feed_capture.time, "sleep", lambda *_: None)
        sleeper.start()
        self.addCleanup(sleeper.stop)

    def run_session(self, frames: list[bytes], duration: float = 0.4,
                    limit: float = 0.05):
        # The stall limit is the config's, so the test drives the same value
        # production reads rather than a private copy of it.
        stall = mock.patch.object(feed_capture.config, "TICK_STALL_SECONDS",
                                 limit)
        stall.start()
        made: list[_FakeSocket] = []

        def connect():
            sock = _FakeSocket(frames)
            made.append(sock)
            return sock

        patcher = mock.patch.object(feed_capture.CaptureSession, "_connect",
                                    staticmethod(connect))
        patcher.start()
        try:
            session = feed_capture.CaptureSession(["SAZEW"], duration=duration)
            session.run()
        finally:
            patcher.stop()
            stall.stop()
        return session, made

    def test_the_stall_limit_is_five_seconds(self):
        # Owner report 2026-11-04: the old 20 second wait showed up as 14 to
        # 15 seconds of lag on the desk before the fresh sweep arrived.
        self.assertEqual(feed_capture.config.TICK_STALL_SECONDS, 5.0)

    def test_a_silent_venue_reconnects_and_names_the_stall(self):
        session, made = self.run_session([self.BANNER, self.SWEEP])
        self.assertGreaterEqual(session.counters["ticks"], 1,
                                "the sweep that did arrive was not banked")
        self.assertGreaterEqual(session.counters["errors"], 1)
        self.assertIn("pushed no market data", session.last_error or "")
        self.assertGreaterEqual(session.counters["reconnects"], 1)
        self.assertGreater(len(made), 1, "the socket was never re-opened")
        self.assertTrue(all(sock.closed for sock in made),
                        "a stalled socket was left open")

    def test_a_venue_that_keeps_pushing_is_never_reconnected(self):
        # A limit far longer than this run: the point is that a venue which
        # keeps pushing is never treated as stalled, however fast the frames
        # are drained.
        frames = ([self.BANNER] + [self.SWEEP] * 4000)
        session, made = self.run_session(frames, duration=0.3, limit=30.0)
        self.assertEqual(session.counters["errors"], 0)
        self.assertEqual(session.counters["reconnects"], 0)
        self.assertEqual(len(made), 1)
        self.assertGreater(session.counters["ticks"], 0)


class MissingUniverseTest(unittest.TestCase):
    def test_a_missing_universe_is_refused_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_universe.json"
            with self.assertRaises(FileNotFoundError) as caught:
                feed_capture.load_universe(missing)
        self.assertIn("refusing to subscribe", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
