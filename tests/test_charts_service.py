"""The shared payload builder, which every door into the API goes through.

The tests pin the sentences that keep a chart honest:

  * an empty series explains itself instead of drawing zeroes (SO-3);
  * a series that starts mid-session says so and does not report the whole
    morning as one enormous gap;
  * a delayed source says it is delayed;
  * the gap list ignores single missing minutes but keeps real holes;
  * ``limit`` trims the tail, which is the part a live chart reads.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts import service  # noqa: E402
from charts.adapters.base import Capabilities  # noqa: E402
from charts.contract import (  # noqa: E402
    Bar, MarketContext, SourceInfo,
)
from charts.store import BarStore  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
FIRST = datetime(2026, 10, 12, 9, 35, tzinfo=KARACHI)
SOURCE = SourceInfo(id="tape", label="the tape")


class StubSource:
    """The smallest source the builder needs: capabilities only."""

    name = "stub"

    def __init__(self, *, delay_seconds: int = 0) -> None:
        self._source = SourceInfo(id="stub", label="a stub source",
                                  delay_seconds=delay_seconds)

    def capabilities(self) -> Capabilities:
        return Capabilities(source=self._source, resolutions=("1m",),
                            live=True)


def bar(minute: datetime, close: float = 100.0) -> Bar:
    return Bar.build(t=minute, o=close - 0.5, h=close + 1, l=close - 1.5,
                     c=close, v=5)


def context(*, trading_day: bool = True) -> MarketContext:
    return MarketContext(phase="OPEN", state="MARKET", trading_day=trading_day,
                         timezone="Asia/Karachi", band=None, next_event=None,
                         as_of="2026-10-12T10:00:00+05:00")


def builder_fixture(minutes: int, *, trading_day: bool = True):
    """Patch the two session calls the builder makes, for a fixed day."""
    expected = [datetime(2026, 10, 12, 9, 32, tzinfo=KARACHI)
                + timedelta(minutes=step) for step in range(minutes)]
    return (
        mock.patch.object(service.sessions, "expected_minutes",
                          return_value=expected),
        mock.patch.object(service.sessions, "market_context",
                          return_value=context(trading_day=trading_day)),
    )


class EmptySeriesTest(unittest.TestCase):

    def test_nothing_ingested_is_explained_not_zeroed(self):
        expected, market = builder_fixture(30)
        with expected, market:
            payload = service.build_payload(BarStore(), StubSource(), "OGDC",
                                            "1m")
        self.assertEqual(payload.bars, [])
        self.assertEqual(payload.gaps, [])
        self.assertTrue(any("not the same as a price of zero" in note
                            for note in payload.notes))
        self.assertEqual(payload.symbol, "OGDC")

    def test_a_known_but_silent_symbol_says_so(self):
        store = BarStore()
        store.upsert("OGDC", "1m", [], SOURCE, updated_at="2026-10-12T10:00:00+05:00")
        expected, market = builder_fixture(30)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertEqual(payload.bars, [])
        self.assertEqual(payload.gaps, [])
        self.assertTrue(any("published no bar for it this session" in note
                            for note in payload.notes))


class LateStartTest(unittest.TestCase):

    def test_a_late_start_is_named_and_is_not_a_morning_long_gap(self):
        store = BarStore()
        rows = [bar(FIRST + timedelta(minutes=step)) for step in range(6)]
        store.upsert("OGDC", "1m", rows, SOURCE, updated_at="now")
        # Expected minutes run to the newest bar: the session opened at
        # 09:32, the series begins at 09:35, and nothing after it is missing.
        expected, market = builder_fixture(9)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertEqual(len(payload.bars), 6)
        self.assertEqual(payload.gaps, [])
        self.assertTrue(any("starts at 09:35" in note and "3 session minute"
                            in note for note in payload.notes))

    def test_a_hole_after_the_start_is_still_a_gap(self):
        store = BarStore()
        rows = [bar(FIRST + timedelta(minutes=step)) for step in range(6)
                if step not in (2, 3)]
        store.upsert("OGDC", "1m", rows, SOURCE, updated_at="now")
        expected, market = builder_fixture(9)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertEqual(len(payload.gaps), 1)
        self.assertEqual(payload.gaps[0].minutes, 2)

    def test_one_missing_minute_is_below_the_gap_floor(self):
        store = BarStore()
        rows = [bar(FIRST + timedelta(minutes=step)) for step in range(6)
                if step != 2]
        store.upsert("OGDC", "1m", rows, SOURCE, updated_at="now")
        expected, market = builder_fixture(9)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertEqual(payload.gaps, [])


class ProvenanceTest(unittest.TestCase):

    def test_a_delayed_source_says_it_is_delayed(self):
        store = BarStore()
        store.upsert("OGDC", "1m", [bar(FIRST)], SOURCE, updated_at="now")
        expected, market = builder_fixture(4)
        with expected, market:
            payload = service.build_payload(store, StubSource(delay_seconds=300),
                                            "OGDC", "1m")
        self.assertTrue(any("about 5 minute(s)" in note
                            for note in payload.notes))

    def test_revisions_are_disclosed(self):
        store = BarStore()
        store.upsert("OGDC", "1m", [bar(FIRST, 100.0)], SOURCE, updated_at="a")
        store.upsert("OGDC", "1m", [bar(FIRST, 101.0)], SOURCE, updated_at="b")
        expected, market = builder_fixture(4)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertTrue(any("1 bar(s) were revised" in note
                            for note in payload.notes))

    def test_the_payload_reports_the_series_source_not_the_default(self):
        store = BarStore()
        other = SourceInfo(id="broker_tape", label="the venue tape")
        store.upsert("OGDC", "1m", [bar(FIRST)], other, updated_at="now")
        expected, market = builder_fixture(4)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m")
        self.assertEqual(payload.source.id, "broker_tape")


class LimitTest(unittest.TestCase):

    def test_limit_keeps_the_newest_bars(self):
        store = BarStore()
        rows = [bar(FIRST + timedelta(minutes=step)) for step in range(10)]
        store.upsert("OGDC", "1m", rows, SOURCE, updated_at="now")
        expected, market = builder_fixture(13)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m",
                                            limit=3)
        self.assertEqual([row.t for row in payload.bars],
                         ["2026-10-12T09:42:00+05:00",
                          "2026-10-12T09:43:00+05:00",
                          "2026-10-12T09:44:00+05:00"])

    def test_a_zero_limit_keeps_everything(self):
        store = BarStore()
        rows = [bar(FIRST + timedelta(minutes=step)) for step in range(4)]
        store.upsert("OGDC", "1m", rows, SOURCE, updated_at="now")
        expected, market = builder_fixture(7)
        with expected, market:
            payload = service.build_payload(store, StubSource(), "OGDC", "1m",
                                            limit=0)
        self.assertEqual(len(payload.bars), 4)


if __name__ == "__main__":
    unittest.main()
