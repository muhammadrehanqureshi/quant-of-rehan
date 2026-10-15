"""The bar store: upsert semantics, revisions, and measured gaps.

Two of these tests carry a rule that the rest of the service depends on:

  * the minute still forming is *replaced*, never appended twice, and the
    replacement is counted as a revision so the payload can say so;
  * a gap is a stretch of expected session minutes with no bar, where the
    expected minutes come from the session law. A closed market, a break and
    a holiday therefore produce no gap at all, which is the difference
    between an honest chart and one that cries wolf every Friday.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts import sessions  # noqa: E402
from charts.contract import Bar, ContractError, SourceInfo  # noqa: E402
from charts.store import BarStore  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY = datetime(2026, 10, 12, 10, 32, tzinfo=KARACHI)
SOURCE = SourceInfo(id="test", label="test source")


def bar(minute: datetime, close: float = 100.0, volume: float = 1.0) -> Bar:
    return Bar.build(t=minute, o=close - 0.5, h=close + 1, l=close - 1.5,
                     c=close, v=volume)


class UpsertTest(unittest.TestCase):

    def setUp(self) -> None:
        self.store = BarStore()

    def test_a_new_minute_is_appended_in_order(self):
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE,
                          updated_at="2026-10-12T10:32:00+05:00")
        self.store.upsert("OGDC", "1m", [bar(MONDAY - timedelta(minutes=1))],
                          SOURCE, updated_at="2026-10-12T10:32:00+05:00")
        series = self.store.series("OGDC", "1m")
        self.assertIsNotNone(series)
        self.assertEqual([row.t for row in series.bars],
                         ["2026-10-12T10:31:00+05:00",
                          "2026-10-12T10:32:00+05:00"])

    def test_the_forming_minute_is_replaced_and_counted(self):
        stored = self.store.upsert("OGDC", "1m", [bar(MONDAY, 100.0)], SOURCE,
                                   updated_at="one")
        again = self.store.upsert("OGDC", "1m", [bar(MONDAY, 101.0)], SOURCE,
                                  updated_at="two")
        self.assertEqual(stored, 1)
        self.assertEqual(again, 0)
        series = self.store.series("OGDC", "1m")
        self.assertEqual(len(series.bars), 1)
        self.assertEqual(series.bars[0].c, 101.0)
        self.assertEqual(series.revisions, 1)
        self.assertEqual(series.updated_at, "two")

    def test_an_identical_republish_is_not_a_revision(self):
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="b")
        self.assertEqual(self.store.series("OGDC", "1m").revisions, 0)

    def test_an_empty_upsert_still_creates_the_series(self):
        self.store.upsert("OGDC", "1m", [], SOURCE, updated_at="a")
        series = self.store.series("OGDC", "1m")
        self.assertIsNotNone(series)
        self.assertEqual(series.bars, [])

    def test_the_returned_series_is_a_copy(self):
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        got = self.store.series("OGDC", "1m")
        got.bars.clear()
        got.notes.append("written by a caller")
        self.assertEqual(len(self.store.series("OGDC", "1m").bars), 1)
        self.assertEqual(self.store.series("OGDC", "1m").notes, [])

    def test_two_resolutions_of_one_symbol_do_not_share_bars(self):
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        self.store.upsert("OGDC", "session", [bar(MONDAY)], SOURCE,
                          updated_at="a")
        self.assertEqual(len(self.store.series("OGDC", "1m").bars), 1)
        self.assertEqual(len(self.store.series("OGDC", "session").bars), 1)


class SymbolsTest(unittest.TestCase):

    def setUp(self) -> None:
        self.store = BarStore()

    def test_registration_is_case_insensitive_and_keeps_facts(self):
        self.store.register_symbol("ogdc", source="tape", listed=True)
        self.store.register_symbol("OGDC", sector="oil")
        rows = self.store.symbols()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "OGDC")
        self.assertEqual(rows[0]["sector"], "oil")
        self.assertTrue(self.store.has_symbol("ogdc"))

    def test_an_empty_symbol_is_refused(self):
        with self.assertRaises(ContractError):
            self.store.register_symbol("   ")

    def test_snapshot_returns_the_tail(self):
        rows = [bar(MONDAY + timedelta(minutes=step)) for step in range(5)]
        self.store.upsert("OGDC", "1m", rows, SOURCE, updated_at="a")
        self.assertEqual(len(self.store.snapshot("OGDC", "1m", 2)), 2)
        self.assertEqual(self.store.snapshot("OGDC", "1m", None), rows)

    def test_latest_resolution_prefers_the_finest_that_has_bars(self):
        self.store.upsert("OGDC", "1d", [bar(MONDAY)], SOURCE, updated_at="a")
        self.assertEqual(self.store.latest_resolution("OGDC"), "1d")
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        self.assertEqual(self.store.latest_resolution("OGDC"), "1m")
        self.assertIsNone(self.store.latest_resolution("NOTHING"))

    def test_a_note_is_recorded_once(self):
        self.store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        self.store.note("OGDC", "1m", "TIMEOUT: the source did not answer")
        self.store.note("OGDC", "1m", "TIMEOUT: the source did not answer")
        self.store.note("NOTHING", "1m", "ignored on purpose")
        self.assertEqual(self.store.series("OGDC", "1m").notes,
                         ["TIMEOUT: the source did not answer"])


class GapTest(unittest.TestCase):

    def test_a_single_missing_minute_is_one_gap(self):
        expected = [MONDAY + timedelta(minutes=step) for step in range(4)]
        bars = [bar(expected[0]), bar(expected[1]), bar(expected[3])]
        gaps = BarStore.gaps(bars, expected)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].start, "2026-10-12T10:34:00+05:00")
        self.assertEqual(gaps[0].end, "2026-10-12T10:34:00+05:00")
        self.assertEqual(gaps[0].minutes, 1)

    def test_a_run_of_missing_minutes_is_merged(self):
        expected = [MONDAY + timedelta(minutes=step) for step in range(6)]
        bars = [bar(expected[0]), bar(expected[5])]
        gaps = BarStore.gaps(bars, expected)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].minutes, 4)

    def test_minutes_the_law_did_not_expect_are_not_gaps(self):
        # The session law's own minute list is the only thing a gap is
        # measured against: the Friday break is simply not in it, so a
        # series that prints nothing between 12:00 and 14:32 is not a chart
        # full of missing data.
        friday = datetime(2026, 10, 9, 9, 32, tzinfo=KARACHI)
        expected = sessions.expected_minutes(friday.replace(hour=17))
        first_close = friday.replace(hour=12, minute=0)
        second_open = friday.replace(hour=14, minute=32)
        self.assertIn(first_close, expected)
        self.assertIn(second_open, expected)
        in_break = [moment for moment in expected
                    if first_close < moment < second_open]
        self.assertEqual(in_break, [])
        # Two bands of 164 and 119 minutes: a full Friday, minus the break.
        self.assertEqual(len(expected), 283)

    def test_a_holiday_has_no_expected_minutes_at_all(self):
        holiday = datetime(2026, 8, 14, 11, 0, tzinfo=KARACHI)
        self.assertFalse(sessions.law.is_trading_day(holiday.date()))
        self.assertEqual(sessions.expected_minutes(holiday), [])

    def test_an_empty_series_against_expected_minutes_is_one_gap(self):
        expected = [MONDAY + timedelta(minutes=step) for step in range(3)]
        gaps = BarStore.gaps([], expected)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0].minutes, 3)
        # With no expected minutes at all there is nothing to be missing.
        self.assertEqual(BarStore.gaps([], []), [])

    def test_clear_removes_everything(self):
        store = BarStore()
        store.register_symbol("OGDC")
        store.upsert("OGDC", "1m", [bar(MONDAY)], SOURCE, updated_at="a")
        store.clear()
        self.assertEqual(store.symbols(), [])
        self.assertIsNone(store.series("OGDC", "1m"))


if __name__ == "__main__":
    unittest.main()
