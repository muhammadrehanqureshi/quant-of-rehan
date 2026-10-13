"""SO-7a: the agent is the owner's co-author, hardcoded on the way to master.

Owner order 2026-10-13: "I want you to be my co author until further notice,
you need to hardcode this for all the PRs and merging into the master branch
from now on." GOVERNANCE.md records it as SO-7a, scripts/land.sh appends the
line to every commit, pull request body and merge, and
scripts/check_governance.py requires it.

The behaviour is exercised here against a real (throwaway) git repository in a
temporary directory, so "a commit without the line fails the check" is
observed rather than read out of the code, and the one string is pinned to
every place that has to agree on it: the checker, the landing script and the
governance document. Nothing here touches the owner's checkout, GitHub or the
network.
"""

from __future__ import annotations

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


def checker():
    import check_governance as cg
    return cg


class CoAuthorLawTest(unittest.TestCase):
    """One line, one spelling, and the author law around it untouched."""

    def test_the_line_is_the_same_in_the_checker_the_script_and_the_docs(self):
        cg = checker()
        self.assertEqual(cg.REQUIRED_COAUTHOR.lower(), TRAILER.lower())
        self.assertIn(TRAILER, LAND.read_text(encoding="utf-8"))
        self.assertIn(TRAILER, GOVERNANCE.read_text(encoding="utf-8"))
        # The owner is still the author of every commit (SO-7).
        self.assertIn(cg.OWNER_NAME, LAND.read_text(encoding="utf-8"))
        self.assertIn(cg.OWNER_EMAIL, LAND.read_text(encoding="utf-8"))

    def test_every_other_attribution_stays_banned(self):
        cg = checker()
        self.assertNotIn("co-authored-by:", cg.FORBIDDEN_TRAILERS)
        for banned in ("generated with", "generated-by:", "signed-off-by:"):
            with self.subTest(banned=banned):
                self.assertIn(banned, cg.FORBIDDEN_TRAILERS)

    def test_the_landing_script_puts_the_line_on_the_commit_pr_and_merge(self):
        text = LAND.read_text(encoding="utf-8")
        self.assertIn(f'COAUTHOR="{TRAILER}"', text)
        self.assertIn(
            'FULL_MESSAGE=$(printf \'%s\\n\\n%s\\n\' "$MESSAGE" "$COAUTHOR")', text)
        self.assertIn('git commit -m "$FULL_MESSAGE"', text)
        self.assertIn('--body "$FULL_MESSAGE"', text)
        self.assertIn('gh pr merge "$pr" "${merge_args[@]}" --body "$COAUTHOR"',
                      text)
        # A message that already carries the line is refused, so the script
        # stays the only writer of it.
        self.assertIn("the co-author line is appended by land.sh itself", text)

    def test_the_order_is_named_where_the_rules_live(self):
        self.assertIn("SO-7a", GOVERNANCE.read_text(encoding="utf-8"))
        self.assertIn("SO-7a", WORKFLOW.read_text(encoding="utf-8"))
        self.assertIn("SO-7a", READ_ME.read_text(encoding="utf-8"))


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

    def test_a_commit_without_the_line_is_reported(self):
        self.commit("Sandbox: a change without the co-author line")
        found = self.errors()
        self.assertTrue(any("[SO-7a]" in e and "missing" in e for e in found),
                        found)

    def test_a_commit_with_the_line_passes(self):
        self.commit("Sandbox: the owner's change\n\n" + TRAILER)
        self.assertEqual(self.errors(), [])

    def test_another_co_author_is_reported(self):
        self.commit("Sandbox: someone else's change\n\n"
                    "Co-Authored-By: Someone Else <else@example.com>")
        found = self.errors()
        self.assertTrue(any("[SO-7a]" in e for e in found), found)

    def test_the_line_twice_is_reported(self):
        self.commit("Sandbox: a doubled change\n\n" + TRAILER + "\n" + TRAILER)
        found = self.errors()
        self.assertTrue(any("times" in e for e in found), found)

    def test_a_generated_by_footer_is_still_reported(self):
        self.commit("Sandbox: a change\n\n" + TRAILER
                    + "\nGenerated with a robot")
        found = self.errors()
        self.assertTrue(any("banned trailer" in e for e in found), found)

    def test_a_non_owner_author_is_still_reported(self):
        self.git("config", "user.name", "Someone Else")
        self.commit("Sandbox: a change by nobody in particular\n\n" + TRAILER)
        found = self.errors()
        self.assertTrue(any("[SO-7]" in e and "not authored" in e
                            for e in found), found)


if __name__ == "__main__":
    unittest.main()
