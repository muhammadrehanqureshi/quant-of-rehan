"""Durable chart history is local, restart-safe, and symbol isolated."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.contract import Bar, SourceInfo  # noqa: E402
from charts.persistent import PersistentBarStore  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
SOURCE = SourceInfo(id="broker_tape", label="captured broker tape",
                    delay_seconds=0, note="recorded observation")


def bar(minute: int, close: float) -> Bar:
    stamp = datetime(2026, 10, 12, 10, minute, tzinfo=KARACHI)
    return Bar.build(t=stamp, o=close - 0.125, h=close + 0.375,
                     l=close - 0.25, c=close, v=12345.125)


class PersistentBarStoreTest(unittest.TestCase):
    def test_history_and_metadata_survive_restart_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "private" / "history.sqlite3"
            store = PersistentBarStore(database)
            store.register_symbol("ogdc", source="broker_tape", listed=True)
            original = [bar(32, 100.123456789), bar(33, 101.987654321)]
            store.upsert("OGDC", "1m", original, SOURCE,
                         updated_at="2026-10-12T10:34:00+05:00",
                         observed_at="2026-10-12T10:33:48+05:00")
            store.note("OGDC", "1m", "measured source note")
            store.close()

            reopened = PersistentBarStore(database)
            series = reopened.series("ogdc", "1m")
            self.assertIsNotNone(series)
            self.assertEqual(series.bars, original)
            self.assertEqual(series.source, SOURCE)
            self.assertEqual(series.updated_at, "2026-10-12T10:34:00+05:00")
            self.assertEqual(series.observed_at, "2026-10-12T10:33:48+05:00")
            self.assertEqual(series.notes, ["measured source note"])
            self.assertEqual(reopened.symbols(), [
                {"symbol": "OGDC", "source": "broker_tape", "listed": True}])
            reopened.close()

    def test_revision_replaces_existing_minute_without_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            store = PersistentBarStore(database)
            first = bar(32, 100.0)
            revised = bar(32, 100.5)
            self.assertEqual(store.upsert("OGDC", "1m", [first], SOURCE,
                                          updated_at="first"), 1)
            self.assertEqual(store.upsert("OGDC", "1m", [revised], SOURCE,
                                          updated_at="revision"), 0)
            store.close()
            reopened = PersistentBarStore(database)
            series = reopened.series("OGDC", "1m")
            self.assertEqual(series.bars, [revised])
            self.assertEqual(series.revisions, 1)
            reopened.close()

    def test_symbols_and_resolutions_are_isolated_and_clear_is_durable(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "history.sqlite3"
            store = PersistentBarStore(database)
            store.register_symbol("OGDC")
            store.register_symbol("HBL")
            store.upsert("OGDC", "1m", [bar(32, 100.0)], SOURCE,
                         updated_at="one")
            store.upsert("OGDC", "1d", [bar(32, 101.0)], SOURCE,
                         updated_at="two")
            store.upsert("HBL", "1m", [bar(32, 200.0)], SOURCE,
                         updated_at="three")
            self.assertEqual(store.series("OGDC", "1m").bars[0].c, 100.0)
            self.assertEqual(store.series("OGDC", "1d").bars[0].c, 101.0)
            self.assertEqual(store.series("HBL", "1m").bars[0].c, 200.0)
            store.clear()
            store.close()
            reopened = PersistentBarStore(database)
            self.assertEqual(reopened.symbols(), [])
            self.assertIsNone(reopened.series("OGDC", "1m"))
            reopened.close()


if __name__ == "__main__":
    unittest.main()
