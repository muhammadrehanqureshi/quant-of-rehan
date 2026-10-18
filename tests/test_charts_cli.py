"""Command-line wiring for the chart store's persistence policy."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts import app  # noqa: E402
from charts.persistent import PersistentBarStore  # noqa: E402
from charts.store import BarStore  # noqa: E402


class StoreSelectionTest(unittest.TestCase):
    def test_real_sources_default_to_private_local_history(self):
        args = app.build_parser().parse_args(["--source", "tape"])
        store = app._store_for(args)
        try:
            self.assertIsInstance(store, PersistentBarStore)
            self.assertEqual(Path(store.database), app.DEFAULT_HISTORY_DATABASE)
            self.assertTrue(app.DEFAULT_HISTORY_DATABASE.parent.is_dir())
        finally:
            store.close()
            app.DEFAULT_HISTORY_DATABASE.unlink(missing_ok=True)
            app.DEFAULT_HISTORY_DATABASE.with_name(
                app.DEFAULT_HISTORY_DATABASE.name + "-wal").unlink(missing_ok=True)
            app.DEFAULT_HISTORY_DATABASE.with_name(
                app.DEFAULT_HISTORY_DATABASE.name + "-shm").unlink(missing_ok=True)

    def test_replay_defaults_to_memory_and_never_persists_demo_bars(self):
        args = app.build_parser().parse_args(["--source", "replay"])
        self.assertIsInstance(app._store_for(args), BarStore)
        self.assertNotIsInstance(app._store_for(args), PersistentBarStore)

    def test_an_explicit_path_can_persist_replay_for_a_deliberate_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "replay.sqlite3"
            args = app.build_parser().parse_args([
                "--source", "replay", "--database", str(database)])
            store = app._store_for(args)
            try:
                self.assertIsInstance(store, PersistentBarStore)
                self.assertEqual(Path(store.database), database)
            finally:
                store.close()

    def test_memory_database_remains_available_for_any_source(self):
        args = app.build_parser().parse_args([
            "--source", "tape", "--database", ":memory:"])
        store = app._store_for(args)
        try:
            self.assertIsInstance(store, PersistentBarStore)
            self.assertEqual(store.database, ":memory:")
        finally:
            store.close()

    def test_default_history_path_is_rooted_inside_runtime_data(self):
        self.assertEqual(
            app.DEFAULT_HISTORY_DATABASE,
            ROOT / "data" / "charts" / "history.sqlite3")
        self.assertEqual(
            app.build_parser().parse_args([]).database, "")


if __name__ == "__main__":
    unittest.main()
