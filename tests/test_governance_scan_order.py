"""SO-20: the governance check that keeps the tape ahead of the scanner.

The check is new, so it gets its own test: an enforcement that cannot fail is
documentation, and this one exists because a real defect reached the cloud.
Measured 2026-10-14 on a GitHub Actions runner, a 45 minute band ran 88 cycles
without one usable ranking while the recorder's universe file was a gitignored
local path, and no check objected. These tests pin the objections: the tracked
universe, the start probe, and the loop's order (tape first, servlet only for a
day with no tape at all).

Everything here is offline and reads nothing outside a temporary tree.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_governance as governance  # noqa: E402

RECORDER = "src/data/feed_capture.py"
TAPE = "src/data/live_card.py"
LOOP = "scripts/scan_loop.py"

GOOD_RECORDER = (
    'UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"\n'
    'raise FileNotFoundError("refusing to subscribe to an invented list")\n'
)
GOOD_TAPE = (
    "START_PROBE_SECONDS = 2.0\n"
    "def _probe_child(child, timeout):\n"
    "    return None\n"
    'raise RuntimeError("the broker tape exited with code 1 at start")\n'
)
GOOD_LOOP = (
    "    def _capture(self) -> bool:\n"
    "        alive, note = live_card.ensure_tape(moment)\n"
    "        if alive:\n"
    "            return self._tape_capture(moment, alive, note)\n"
    "        return self._poller_capture(moment)\n"
)
BAD_LOOP = (
    "    def _capture(self) -> bool:\n"
    "        if tape_bars.capture_path(moment.date()).is_file():\n"
    "            return self._tape_capture(moment)\n"
    "        note = 'no tape'\n"
    "        return self._poller_capture(moment)\n"
    "        alive, note = live_card.ensure_tape(moment)\n"
)


class TapeBeforeScannerCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tree = Path(self._dir.name)
        self._real_root = governance.ROOT
        governance.ROOT = self.tree
        self.addCleanup(self._restore_root)
        self.good()

    def _restore_root(self) -> None:
        governance.ROOT = self._real_root

    def write(self, rel: str, text: str) -> None:
        path = self.tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def good(self) -> None:
        self.write(RECORDER, GOOD_RECORDER)
        self.write(TAPE, GOOD_TAPE)
        self.write(LOOP, GOOD_LOOP)

    def errors(self) -> list:
        found: list = []
        governance.check_tape_before_scanner(found)
        return [e for e in found if e.startswith("[SO-20]")]

    def test_a_clean_tree_is_quiet(self):
        self.assertEqual(self.errors(), [])

    def test_a_local_only_universe_is_refused(self):
        self.write(RECORDER, "UNIVERSE_FILE = ROOT / 'data' / 'legacy' / 'x.json'\n")
        errors = self.errors()
        self.assertTrue(errors)
        self.assertIn("universe_kmiall", " ".join(errors))

    def test_a_recorder_that_cannot_refuse_an_invented_universe_is_flagged(self):
        self.write(RECORDER,
                   'UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"\n')
        self.assertIn("refusing to subscribe", " ".join(self.errors()))

    def test_a_tape_without_a_start_probe_is_flagged(self):
        self.write(TAPE, "def start_tape():\n    return True, 'started'\n")
        errors = " ".join(self.errors())
        self.assertIn("probe", errors.lower())

    def test_a_loop_that_picks_the_servlet_before_the_recorder_is_flagged(self):
        self.write(LOOP, BAD_LOOP)
        self.assertIn("servlet", " ".join(self.errors()))

    def test_a_missing_file_is_flagged_rather_than_skipped(self):
        (self.tree / LOOP).unlink()
        self.assertIn("is missing", " ".join(self.errors()))


if __name__ == "__main__":
    unittest.main()
