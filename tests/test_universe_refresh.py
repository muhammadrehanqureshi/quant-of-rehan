"""Universe drift checker: pure diff and snapshot resolution, no network.

The live side of the check needs the PSX portal, which a unit test must never
call. The live fetch is therefore exercised by the CLI by hand; here we pin the
parts that decide correctness: how the tracked snapshot resolves, and how the
name-by-name diff behaves in both directions.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.universe_refresh as universe  # noqa: E402


class UniverseDriftTest(unittest.TestCase):
    def test_tracked_snapshot_resolves_the_shariah_kmiall_list(self):
        symbols = universe.tracked_symbols()
        self.assertGreater(len(symbols), 100)
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertTrue(all(s == s.upper() for s in symbols))

    def test_diff_reports_both_directions(self):
        report = universe.diff(["AAA", "BBB", "CCC"], ["BBB", "CCC", "DDD"])
        self.assertFalse(report["in_sync"])
        self.assertEqual(report["tracked_count"], 3)
        self.assertEqual(report["live_count"], 3)
        self.assertEqual(report["overlap"], 2)
        self.assertEqual(report["missing_from_live"], ["AAA"])
        self.assertEqual(report["missing_from_tracked"], ["DDD"])

    def test_diff_is_case_insensitive_and_ignores_blanks(self):
        report = universe.diff(["aaa", " BBB ", ""], ["AAA", "bbb"])
        self.assertTrue(report["in_sync"])

    def test_check_reports_a_fetch_failure_rather_than_in_sync(self):
        """An unreachable portal is a failure, never a clean bill of health."""
        with patch.object(universe, "live_symbols", side_effect=OSError("portal down")):
            report = universe.check()
        self.assertFalse(report["ok"])
        self.assertIn("OSError", report["error"])
        self.assertGreater(report["tracked_count"], 100)


if __name__ == "__main__":
    unittest.main()
