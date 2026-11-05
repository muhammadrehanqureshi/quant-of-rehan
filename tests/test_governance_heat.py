"""SO-23: the heat order, pinned in the docs a session reads first.

Owner order 2026-11-05: the machine sat above 75 C while a session was
working, and he ordered that it never be hammered again. SO-21 keeps the
project's workloads in the cloud; SO-23 keeps the agent's own checks
there too, so its only local actions are file edits and the git/gh
commands. This test holds both halves of that pin: the shipped documents
carry his words, and the governance check fails a pull request that
removes them.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_governance as governance  # noqa: E402

ORDER = "Don't ever hammer my PC at all ever"


class HeatOrderInTheDocsTest(unittest.TestCase):
    def test_the_shipped_docs_carry_the_heat_order(self):
        gov = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn(ORDER, gov)
        self.assertIn(ORDER, agents)
        self.assertIn("SO-23", gov)
        self.assertIn("The heat order: zero local compute", agents)
        # The law itself: edits, git and gh, and every check in CI.
        flat_gov = " ".join(gov.split()).lower()
        self.assertIn("the agent's own session runs no local computation",
                      flat_gov)
        self.assertIn("the agent's only local actions are file edits and the "
                      "`git` and `gh` commands", flat_gov)


class HeatOrderPinTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tree = Path(self._dir.name)
        self._root = governance.ROOT
        governance.ROOT = self.tree
        self.addCleanup(self._restore_root)

    def _restore_root(self) -> None:
        governance.ROOT = self._root

    def write(self, rel: str, text: str) -> None:
        (self.tree / rel).write_text(text, encoding="utf-8")

    def errors(self) -> list:
        found: list = []
        governance.check_governance_doc(found)
        return found

    def test_docs_with_every_required_line_pass(self):
        self.write("GOVERNANCE.md",
                   "\n".join(governance.REQUIRED_GOVERNANCE_SNIPPETS))
        self.write("AGENTS.md",
                   "\n".join(governance.REQUIRED_AGENTS_SNIPPETS))
        self.assertEqual(self.errors(), [])

    def test_a_governance_doc_without_the_order_fails(self):
        gov_text = "\n".join(governance.REQUIRED_GOVERNANCE_SNIPPETS)
        self.write("GOVERNANCE.md", gov_text.replace(ORDER, ""))
        self.write("AGENTS.md",
                   "\n".join(governance.REQUIRED_AGENTS_SNIPPETS))
        errors = self.errors()
        self.assertTrue(any("GOVERNANCE.md" in e for e in errors))

    def test_an_agents_doc_without_the_order_fails(self):
        self.write("GOVERNANCE.md",
                   "\n".join(governance.REQUIRED_GOVERNANCE_SNIPPETS))
        agents_text = "\n".join(governance.REQUIRED_AGENTS_SNIPPETS)
        self.write("AGENTS.md", agents_text.replace(ORDER, ""))
        errors = self.errors()
        self.assertTrue(any("AGENTS.md" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
