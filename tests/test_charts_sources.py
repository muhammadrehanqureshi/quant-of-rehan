"""The three sources, each held to its own promises.

No test here touches the network or the owner's real capture directory: the
portal is driven through a fake HTTP session, the tape through a temporary
capture file, and the replay source is deterministic by construction. What is
being checked is the honesty of each adapter:

  * replay is deterministic and its deliberate holes really are holes;
  * the portal claims exactly one resolution and reads the session panel,
    refusing a cleared panel instead of drawing zeroes;
  * the tape refuses to guess a universe, serves minute bars only, and
    exposes the tape's own measured caveats rather than hiding them.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.adapters.portal import PortalSource, parse_company_page  # noqa: E402
from charts.adapters.replay import ReplaySource  # noqa: E402
from charts.adapters.tape import TapeSource  # noqa: E402
from charts.ratelimit import (  # noqa: E402
    CircuitBreaker, TokenBucket, UpstreamError,
)

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY_1100 = datetime(2026, 10, 12, 11, 0, tzinfo=KARACHI)
MONDAY_MARKET_OPEN = datetime(2026, 10, 12, 9, 32, tzinfo=KARACHI)

#: A REG panel shaped exactly like the portal's, captured markup conventions
#: preserved: the label and value pair, the quote__close price, the
#: quote__date stamp.
PORTAL_PAGE = (
    '<div class="tabs__panel active" data-name="REG">'
    '<div class="stats_label">Open</div>'
    '<div class="stats_value">272.10</div>'
    '<div class="stats_label">High</div>'
    '<div class="stats_value">278.00</div>'
    '<div class="stats_label">Low</div>'
    '<div class="stats_value">270.00</div>'
    '<div class="stats_label">Volume</div>'
    '<div class="stats_value">1200000</div>'
    '<div class="stats_label">Total Trades</div>'
    '<div class="stats_value">1234</div>'
    "</div>"
    '<div class="quote__close">Rs.277.50</div>'
    '<div class="quote__date">As of Mon, Oct 12, 2026 11:30 AM</div>'
)

#: A cleared panel: every number zero, which is what the portal publishes
#: when nothing has traded. It is not a bar.
PORTAL_CLEARED = (
    '<div class="tabs__panel active" data-name="REG">'
    '<div class="stats_label">Open</div><div class="stats_value">0.00</div>'
    '<div class="stats_label">High</div><div class="stats_value">0.00</div>'
    '<div class="stats_label">Low</div><div class="stats_value">0.00</div>'
    '<div class="stats_label">Volume</div><div class="stats_value">0</div>'
    "</div>"
)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    """A requests.Session stand-in that returns what the test decided."""

    def __init__(self, *responses) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, timeout=None):
        self.calls += 1
        item = self._responses[min(self.calls - 1, len(self._responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class Timeout(Exception):
    """Named so the adapter's own classification can recognise it."""


def portal(session, *, clock=MONDAY_1100) -> PortalSource:
    return PortalSource(clock=lambda: clock, http=session,
                        bucket=TokenBucket(rate_per_second=1000.0, burst=8),
                        breaker=CircuitBreaker(fail_threshold=5),
                        sleep=lambda seconds: None)


class ReplayTest(unittest.TestCase):

    def test_the_same_day_produces_the_same_series(self):
        clock = lambda: MONDAY_1100  # noqa: E731 - a one line stub clock
        one = ReplaySource(symbols=["REPLAY1"], clock=clock)
        two = ReplaySource(symbols=["REPLAY1"], clock=clock)
        first = one.history("REPLAY1", "1m", limit=0)
        second = two.history("REPLAY1", "1m", limit=0)
        self.assertGreater(len(first), 50)
        self.assertEqual([bar.as_dict() for bar in first],
                         [bar.as_dict() for bar in second])

    def test_the_series_walks_the_session_minutes_in_order(self):
        clock = lambda: MONDAY_1100  # noqa: E731
        bars = ReplaySource(symbols=["REPLAY1"], clock=clock).history(
            "REPLAY1", "1m", limit=0)
        stamps = [bar.t for bar in bars]
        self.assertEqual(stamps, sorted(stamps))
        self.assertEqual(stamps[0], "2026-10-12T09:32:00+05:00")
        self.assertEqual(stamps[-1], "2026-10-12T11:00:00+05:00")

    def test_a_deliberate_hole_really_is_missing(self):
        clock = lambda: MONDAY_1100  # noqa: E731
        source = ReplaySource(symbols=["REPLAY1"], gaps=(4, 5), clock=clock)
        stamps = {bar.t for bar in source.history("REPLAY1", "1m", limit=0)}
        self.assertNotIn("2026-10-12T09:36:00+05:00", stamps)
        self.assertNotIn("2026-10-12T09:37:00+05:00", stamps)
        self.assertIn("2026-10-12T09:38:00+05:00", stamps)
        self.assertTrue(source.notes("REPLAY1"))

    def test_latest_is_the_whole_session_and_since_filters_it(self):
        clock = lambda: MONDAY_1100  # noqa: E731
        source = ReplaySource(symbols=["REPLAY1"], clock=clock)
        all_bars = source.latest("REPLAY1", "1m")
        self.assertGreater(len(all_bars), 50)
        tail = source.latest("REPLAY1", "1m",
                             since="2026-10-12T10:58:00+05:00")
        self.assertEqual(len(tail), 3)

    def test_before_the_open_it_replays_the_last_trading_day(self):
        """A pre-open clock must not render an empty frame.

        09:00 on the Monday is before its first minute, so the fallback
        walks back to the Friday: the same series the offline demo and this
        suite need at 03:00 as at noon.
        """
        clock = lambda: datetime(2026, 10, 12, 9, 0,    # noqa: E731
                                 tzinfo=KARACHI)
        bars = ReplaySource(symbols=["REPLAY1"], clock=clock).history(
            "REPLAY1", "1m", limit=0)
        self.assertEqual({bar.t[:10] for bar in bars}, {"2026-10-09"})
        self.assertEqual(bars[0].t, "2026-10-09T09:17:00+05:00")
        self.assertEqual(bars[-1].t, "2026-10-09T16:30:00+05:00")
        self.assertEqual(len(bars), 283)  # the Friday, break excluded

    def test_on_a_non_trading_day_it_replays_the_last_trading_day(self):
        clock = lambda: datetime(2026, 10, 11, 12, 0,   # noqa: E731
                                 tzinfo=KARACHI)
        bars = ReplaySource(symbols=["REPLAY1"], clock=clock).history(
            "REPLAY1", "1m", limit=0)
        self.assertEqual({bar.t[:10] for bar in bars}, {"2026-10-09"})

    def test_today_grows_with_the_clock_once_its_session_has_begun(self):
        def at(hour: int, minute: int):
            return lambda: datetime(2026, 10, 12, hour, minute,
                                    tzinfo=KARACHI)

        early = ReplaySource(symbols=["REPLAY1"], clock=at(10, 0)).history(
            "REPLAY1", "1m", limit=0)
        later = ReplaySource(symbols=["REPLAY1"], clock=at(11, 0)).history(
            "REPLAY1", "1m", limit=0)
        self.assertEqual(early[-1].t, "2026-10-12T10:00:00+05:00")
        self.assertEqual(later[-1].t, "2026-10-12T11:00:00+05:00")
        self.assertGreater(len(later), len(early))
        # The later clock extends the same series; it does not reseed it.
        self.assertEqual([bar.as_dict() for bar in later[:len(early)]],
                         [bar.as_dict() for bar in early])

    def test_the_source_says_it_is_synthetic(self):
        source = ReplaySource()
        capabilities = source.capabilities()
        self.assertEqual(capabilities.source.id, "replay")
        self.assertIn("synthetic", capabilities.source.label)
        self.assertEqual(capabilities.resolutions, ("1m",))


class PortalTest(unittest.TestCase):

    def test_the_session_panel_becomes_one_session_bar(self):
        source = portal(FakeSession(FakeResponse(200, PORTAL_PAGE)))
        bars = source.history("OGDC", "session")
        self.assertEqual(len(bars), 1)
        bar = bars[0]
        self.assertEqual(bar.t, "2026-10-12T09:32:00+05:00")
        self.assertEqual((bar.o, bar.h, bar.l, bar.c), (272.10, 278.0,
                                                        270.0, 277.5))
        self.assertEqual(bar.v, 1200000.0)

    def test_the_portal_stamp_travels_with_the_snapshot(self):
        source = portal(FakeSession(FakeResponse(200, PORTAL_PAGE)))
        snapshot = source.snapshot("OGDC")
        self.assertEqual(snapshot.as_of_note, "Mon, Oct 12, 2026 11:30 AM")
        lines = source.notes(snapshot)
        self.assertTrue(any("Mon, Oct 12, 2026" in line for line in lines))
        self.assertTrue(any("delay" in line for line in lines))

    def test_a_cleared_panel_is_a_named_failure_not_a_zero_bar(self):
        source = portal(FakeSession(FakeResponse(200, PORTAL_CLEARED)))
        with self.assertRaises(UpstreamError) as caught:
            source.history("OGDC", "session")
        self.assertEqual(caught.exception.category, UpstreamError.EMPTY_ACK)

    def test_minute_bars_are_refused_with_the_reason(self):
        source = portal(FakeSession(FakeResponse(200, PORTAL_PAGE)))
        with self.assertRaises(UpstreamError) as caught:
            source.history("OGDC", "1m")
        self.assertEqual(caught.exception.category, UpstreamError.SCHEMA_CHANGE)

    def test_a_429_is_retried_once_and_then_succeeds(self):
        session = FakeSession(FakeResponse(429), FakeResponse(200, PORTAL_PAGE))
        source = portal(session)
        snapshot = source.snapshot("OGDC")
        self.assertEqual(session.calls, 2)
        self.assertEqual(snapshot.last, 277.5)
        self.assertTrue(any("retries" in line for line in source.notes(
            snapshot)))

    def test_a_404_is_not_retried(self):
        session = FakeSession(FakeResponse(404))
        source = portal(session)
        with self.assertRaises(UpstreamError) as caught:
            source.snapshot("NOSUCH")
        self.assertEqual(caught.exception.category, UpstreamError.HTTP_ERROR)
        self.assertEqual(caught.exception.status, 404)
        self.assertEqual(session.calls, 1)

    def test_a_timeout_is_classified_and_retried(self):
        session = FakeSession(Timeout("read timed out"),
                              FakeResponse(200, PORTAL_PAGE))
        source = portal(session)
        source.snapshot("OGDC")
        self.assertEqual(session.calls, 2)

    def test_a_connection_error_ends_as_a_named_failure(self):
        session = FakeSession(ConnectionResetError("connection reset"))
        source = portal(session)
        with self.assertRaises(UpstreamError) as caught:
            source.snapshot("OGDC")
        self.assertEqual(caught.exception.category, UpstreamError.CONNECTION)

    def test_the_portal_only_ever_claims_the_session_resolution(self):
        source = portal(FakeSession(FakeResponse(200, PORTAL_PAGE)))
        capabilities = source.capabilities()
        self.assertEqual(capabilities.resolutions, ("session",))
        self.assertEqual(capabilities.source.delay_seconds, 300)

    def test_parsing_is_scoped_to_the_reg_panel(self):
        html = (PORTAL_PAGE
                + '<div class="tabs__panel" data-name="FUT">'
                  '<div class="stats_label">High</div>'
                  '<div class="stats_value">999.00</div></div>')
        snapshot = parse_company_page(html, "OGDC")
        self.assertEqual(snapshot.quote["high"], 278.0)


def tick(symbol: str, price, volume, at: datetime,
         tick_time: str | None = None, high=None, low=None) -> dict:
    row = {"scrip": f"{symbol}:REG", "last": str(price),
           "volume": None if volume is None else str(volume),
           "tick_time": tick_time or f"{at:%H:%M:%S}"}
    if high is not None:
        row["high"] = str(high)
    if low is not None:
        row["low"] = str(low)
    return row


def frame(at: datetime, *rows: dict) -> dict:
    return {"kind": "MKT-FEED*x", "ts": at.isoformat(), "ticks": list(rows)}


class TapeTest(unittest.TestCase):
    """The tape adapter, driven through a temporary capture file."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="charts-tape-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.capture = self.tmp / "capture_20261012.ndjson"
        self.universe = self.tmp / "universe.json"
        self.universe.write_text(json.dumps(["OGDC"]), encoding="utf-8")

    def write_tape(self, records: list[dict]) -> None:
        self.capture.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n",
            encoding="utf-8")

    def source(self, clock=MONDAY_1100) -> TapeSource:
        return TapeSource(clock=lambda: clock, universe_path=self.universe)

    def test_minute_prints_become_one_bar_per_minute(self):
        minute = MONDAY_MARKET_OPEN + timedelta(minutes=1)
        self.write_tape([
            frame(minute, tick("OGDC", 100.0, 1000, minute, "09:33:05",
                               high=101.0, low=99.0)),
            frame(minute + timedelta(seconds=30),
                  tick("OGDC", 101.5, 1600, minute, "09:33:35",
                       high=101.0, low=99.0)),
        ])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            bars = self.source().history("OGDC", "1m")
        self.assertEqual(len(bars), 1)
        # High and low are the prints' own range. The row's high/low fields
        # are the venue's day extremes, used for the builder's self check.
        self.assertEqual((bars[0].o, bars[0].h, bars[0].l, bars[0].c),
                         (100.0, 101.5, 100.0, 101.5))

    def test_the_tape_serves_minute_bars_only(self):
        self.write_tape([])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            with self.assertRaises(UpstreamError) as caught:
                self.source().history("OGDC", "1d")
        self.assertEqual(caught.exception.category, UpstreamError.SCHEMA_CHANGE)

    def test_a_missing_universe_is_refused_in_words(self):
        self.universe.write_text("[]", encoding="utf-8")
        self.write_tape([])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            with self.assertRaises(UpstreamError) as caught:
                self.source().history("OGDC", "1m")
        self.assertEqual(caught.exception.category, UpstreamError.EMPTY_ACK)
        self.assertIn("universe", caught.exception.detail)

    def test_a_missing_capture_is_a_named_failure(self):
        self.capture.unlink(missing_ok=True)
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            with self.assertRaises(UpstreamError) as caught:
                self.source().history("OGDC", "1m")
        self.assertEqual(caught.exception.category, UpstreamError.EMPTY_ACK)
        self.assertIn("2026-10-12", caught.exception.detail)

    def test_a_symbol_with_no_prints_has_an_empty_series(self):
        minute = MONDAY_MARKET_OPEN + timedelta(minutes=1)
        self.write_tape([frame(minute, tick("OGDC", 100.0, 1000, minute))])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            bars = self.source().history("SILENT", "1m")
        self.assertEqual(bars, [])

    def test_the_tape_notes_name_its_own_caveats(self):
        minute = MONDAY_MARKET_OPEN + timedelta(minutes=5)
        self.write_tape([
            frame(minute, tick("OGDC", 100.0, 5000, minute, "09:37:00")),
            frame(minute + timedelta(seconds=30),
                  tick("OGDC", 100.5, 6200, minute, "09:37:30")),
        ])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            source = self.source()
            source.history("OGDC", "1m")  # fills the day cache
            lines = source.notes("OGDC")
        self.assertTrue(any("after the session opened" in line
                            for line in lines))
        self.assertTrue(any("before the tape first saw" in line
                            for line in lines))

    def test_catalog_carries_the_universe_it_reads_against(self):
        minute = MONDAY_MARKET_OPEN + timedelta(minutes=1)
        self.write_tape([frame(minute, tick("OGDC", 50.0, 100, minute))])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            rows = {row["symbol"]: row for row in self.source().catalog()}
        self.assertTrue(rows["OGDC"]["listed"])
        self.assertEqual(rows["OGDC"]["source"], "broker_tape")

    def test_session_effect_reports_the_tape_or_says_why_not(self):
        self.write_tape([])
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            effect = self.source().session_effect()
        self.assertTrue(effect["available"])
        self.assertEqual(effect["path"], self.capture.name)

        self.capture.unlink()
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            missing = self.source().session_effect()
        self.assertFalse(missing["available"])
        self.assertIn("no broker tape", missing["detail"])


if __name__ == "__main__":
    unittest.main()
