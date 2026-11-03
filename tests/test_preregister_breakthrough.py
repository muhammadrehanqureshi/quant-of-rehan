"""The Breakthrough 1.0 pre-registration must stay a fixed family.

The registry is gitignored, so the durable statement of the family is
`reports/2026-11-03-breakthrough-1.0.md` plus this script. This test pins the
part that must not drift: exactly 30 variants, each a distinct hypothesis,
distributed 18 / 1 / 2 / 3 / 6 across families 1, 1b, 2, 3 and 4, and no row
carrying a result. A later edit that quietly widens a grid fails here before
it can reach a run.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "preregister_breakthrough.py"


def load_rows() -> list[dict]:
    spec = importlib.util.spec_from_file_location("preregister_breakthrough", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rows()


class PreregistrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = load_rows()

    def test_the_family_has_thirty_distinct_variants(self) -> None:
        self.assertEqual(len(self.rows), 30)
        hypotheses = [row["hypothesis"] for row in self.rows]
        self.assertEqual(len(set(hypotheses)), 30)

    def test_each_family_carries_its_registered_count(self) -> None:
        def count(prefix: str) -> int:
            return sum(1 for row in self.rows
                       if row["hypothesis"].startswith(prefix))

        self.assertEqual(count("F1 "), 18)
        self.assertEqual(count("F1b "), 1)
        self.assertEqual(count("F2 "), 2)
        self.assertEqual(count("F3 "), 3)
        self.assertEqual(count("F4 "), 6)
        self.assertEqual(count("F5"), 0)
        self.assertEqual(count("F6"), 0)

    def test_no_row_carries_a_result_or_an_open_parameter(self) -> None:
        for row in self.rows:
            self.assertNotIn("results", row)
            self.assertIsInstance(row["params"], dict)
            self.assertTrue(row["params"])
            self.assertNotIn(None, row["params"].values())


if __name__ == "__main__":
    unittest.main()
