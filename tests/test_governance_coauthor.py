"""SO-7a: no agent attribution on the way to master.

Owner order 2026-11-08: "from now on DON'T INCLUDE YOURSELF as the contributor.
And remove yourself as the contributor from the entire repo and project." The
old co-author rule is withdrawn.

The behaviour is exercised here against a real (throwaway) git repository in a
temporary directory, so "a commit with the old co-author line fails the check"
is observed rather than read out of the code. Nothing here touches the owner's
checkout, GitHub or the network.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAND = ROOT / "scripts" / "land.sh"
GOVERNANCE = ROOT / "GOVERNANCE.md"
WORKFLOW = ROOT / ".github" / "workflows" / "governance-guard.yml"
READ_ME = ROOT / "README.md"

TRAILER = "Co-Authored-By: Codebuff <noreply@codebuff.com>"
GIT = shutil.which("git")


_CHECKER = None


def checker():
    """The shipped checker, loaded by path."""
    global _CHECKER
    if _CHECKER is None:
        spec = importlib.util.spec_from_file_location(
            "check_governance", ROOT / "scripts" / "check_governance.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CHECKER = module
    return _CHECKER


class NoAttributionLawTest(unittest.TestCase):
    """The agent is named nowhere, and the author law around it is untouched."""

    def test_the_checker_bans_every_coauthor(self):
        cg = checker()
        self.assertEqual(cg.BANNED_COAUTHOR, "co-authored-by:")
        self.assertNotIn("co-authored-by:", cg.FORBIDDEN_TRAILERS)
        self.assertFalse(hasattr(cg, "REQUIRED_COAUTHOR"))

    def test_the_landing_script_never_adds_or_accepts_the_line(self):
        text = LAND.read_text(encoding="utf-8")
        self.assertNotIn("COAUTHOR=", text)
        self.assertNotIn('--body "$COAUTHOR"', text)
        self.assertIn("no co-author trailer is allowed", text)
        self.assertIn('git commit -m "$FULL_MESSAGE"', text)

    def test_the_order_is_named_where_the_rules_live(self):
        govern = GOVERNANCE.read_text(encoding="utf-8")
        self.assertIn("SO-7a", govern)
        self.assertIn("No agent attribution", govern)
        self.assertIn("SO-7a", WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("SO-7a", READ_ME.read_text(encoding="utf-8"))
        for text in (govern, READ_ME.read_text(encoding="utf-8"), LAND.read_text(encoding="utf-8")):
            self.assertNotIn(TRAILER, text)

    def test_the_guard_judges_the_prs_own_commits_and_not_githubs_merge(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}",
                      workflow)
        self.assertIn("synthetic test merge commit", workflow)


@unittest.skipUnless(GIT, "git is required to exercise the commit-message check")
class CommitMessageTest(unittest.TestCase):
    """The checker's own behaviour, on real commits in a throwaway repository."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = Path(self._dir.name)
        self.cwd = os.getcwd()
        self.git("init", "-q")
        self.git("config", "user.name", "Mr. Rehan")
        self.git("config", "user.email",
                 "muhammadrehanqureshi@users.noreply.github.com")
        self.git("commit", "-q", "--allow-empty", "-m",
                 "Sandbox: the repository exists")

    def git(self, *args):
        return subprocess.run([GIT, *args], cwd=self.repo, capture_output=True,
                              text=True, check=True)

    def commit(self, message: str) -> None:
        (self.repo / "change.txt").write_text(message, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def errors(self) -> list:
        cg = checker()
        found: list = []
        os.chdir(self.repo)
        self.addCleanup(os.chdir, self.cwd)
        os.environ["GOVERN_COMMIT_RANGE"] = "HEAD~1..HEAD"
        self.addCleanup(os.environ.pop, "GOVERN_COMMIT_RANGE", None)
        cg.check_commit_messages(found)
        return found

    def test_the_old_coauthor_line_is_reported(self):
        self.commit("Sandbox: the old credit\n\n" + TRAILER)
        found = self.errors()
        self.assertTrue(any("[SO-7a]" in e for e in found), found)

    def test_a_plain_owner_commit_passes(self):
        self.commit("Sandbox: the owner's plain change")
        self.assertEqual(self.errors(), [])

    def test_another_co_author_is_reported(self):
        self.commit("Sandbox: someone else's change\n\n"
                    "Co-Authored-By: Someone Else <else@example.com>")
        found = self.errors()
        self.assertTrue(any("[SO-7a]" in e for e in found), found)

    def test_a_generated_by_footer_is_still_reported(self):
        self.commit("Sandbox: a change\n\nGenerated with a robot")
        found = self.errors()
        self.assertTrue(any("banned trailer" in e for e in found), found)

    def test_a_non_owner_author_is_still_reported(self):
        self.git("config", "user.name", "Someone Else")
        self.commit("Sandbox: a change by nobody in particular")
        found = self.errors()
        self.assertTrue(any("[SO-7]" in e and "not authored" in e
                            for e in found), found)


if __name__ == "__main__":
    unittest.main()
