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

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.intraday_pipeline import load_kmiall  # noqa: E402
from src.data import feed_capture  # noqa: E402


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


class MissingUniverseTest(unittest.TestCase):
    def test_a_missing_universe_is_refused_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_universe.json"
            with self.assertRaises(FileNotFoundError) as caught:
                feed_capture.load_universe(missing)
        self.assertIn("refusing to subscribe", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
