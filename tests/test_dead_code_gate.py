"""The dead-code audit runs on every pull request.

`scripts/dead_code_audit.py` existed since 2026-10-10 and was never wired into
the suite, so nothing stopped an unused import or an unreferenced module from
accumulating. Owner order 2026-10-20 asks for the dead code to be gone, and a
one-time sweep is not a gate: this test is, so the next one fails in the pull
request that adds it.

The audit is static parsing (ast and regex) over the source corpus, not an
execution of the project, so it costs a second and cannot reach the network or
a data file.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "dead_code_audit.py"


class DeadCodeGateTest(unittest.TestCase):
    def test_the_audit_reports_nothing(self):
        result = subprocess.run(
            [sys.executable, str(AUDIT), "--quiet"],
            cwd=ROOT, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(
            result.returncode, 0,
            "the dead-code audit found something; read its output, decide "
            "whether the hit is reachable, and remove it in this pull request\n"
            + result.stdout + result.stderr,
        )

    def test_the_audit_covers_the_live_source_roots(self):
        text = AUDIT.read_text(encoding="utf-8")
        self.assertIn('SOURCE_ROOTS = ("src", "scripts")', text)
        self.assertIn('CORPUS_ROOTS = ("src", "scripts", "tests", "cloud"', text)


if __name__ == "__main__":
    unittest.main()
