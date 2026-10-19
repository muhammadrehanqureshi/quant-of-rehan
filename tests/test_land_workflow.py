"""The landing workflow: phases, refusals, conflicts and the stubbed publish.

scripts/land.sh is the one path every change takes to master (SO-2, SO-6), so
it is exercised here the way it is used: a real (throwaway) git repository, a
real bare "origin", and a stubbed gh on PATH for the publish phase, which is
the only phase that cannot run offline. The stub speaks the exact subcommands
land.sh calls, and its merge moves the bare remote's master, so the whole
chain (commit, rebase, validate, push, pull request, checks, merge, resync) is
verified end to end. Nothing here touches GitHub, the owner's checkout or the
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

BASH = shutil.which("bash") or shutil.which("bash.exe")
GIT = shutil.which("git")

GOVERNANCE_STUB = (
    "import sys\n"
    'print("GOVERNANCE CHECK PASSED: sandbox stub")\n'
    "sys.exit(0)\n"
)
TEST_STUB = (
    "import unittest\n"
    "\n"
    "class Sanity(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    "        self.assertTrue(True)\n"
)
FAILING_TEST_STUB = (
    "import unittest\n"
    "\n"
    "class Sanity(unittest.TestCase):\n"
    "    def test_ok(self):\n"
    '        self.fail("sandbox failure")\n'
)
WORKER_STUB = "export default {};\n"

#: A gh that answers exactly what land.sh asks and does the merge by moving
#: the bare remote's master. GH_STATE, GH_WORK and GH_BASE come from the test.
GH_STUB = """#!/usr/bin/env bash
state="${GH_STATE:?}"
case "$1 $2" in
  "auth status") exit 0 ;;
  "pr view")
    if [[ "$*" == *"--json number"* ]]; then
      [[ -f "$state/pr_open" ]] || exit 1
      echo 1
      exit 0
    fi
    if [[ "$*" == *"--json mergeable"* ]]; then
      # A test can ask for a few UNKNOWN answers first, which is what GitHub
      # really does while it works out whether a pull request can merge.
      if [[ -f "$state/mergeable_unknown" ]]; then
        left=$(cat "$state/mergeable_unknown")
        if [[ "${left:-0}" -gt 0 ]]; then
          echo "$((left - 1))" > "$state/mergeable_unknown"
          echo UNKNOWN
          exit 0
        fi
        rm -f "$state/mergeable_unknown"
      fi
      echo MERGEABLE
      exit 0
    fi
    if [[ "$*" == *"--json mergeCommit"* ]]; then
      echo 0123456789abcdef0123456789abcdef01234567
      exit 0
    fi
    exit 1 ;;
  "pr create") touch "$state/pr_open"; echo "https://example.invalid/pr/1"; exit 0 ;;
  "pr checks")
    if [[ "$*" == *"--json name"* ]]; then echo governance-guard; exit 0; fi
    exit 0 ;;
  "pr merge")
    git -C "$GH_WORK" push origin "HEAD:refs/heads/${GH_BASE:-master}" >/dev/null 2>&1 || exit 1
    touch "$state/merged"
    exit 0 ;;
esac
exit 1
"""


@unittest.skipUnless(BASH and GIT, "git and bash are required for the landing workflow")
class LandingWorkflowTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)
        self.remote = self.root / "remote.git"
        self.work = self.root / "work"
        self.state = self.root / "state"
        self.state.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        stub = self.bin / "gh"
        stub.write_text(GH_STUB, encoding="utf-8", newline="\n")
        self.run_bash(f'chmod +x "{stub}"')

        self.git("init", "--bare", str(self.remote))
        self.git("clone", str(self.remote), str(self.work))
        self.git("-C", str(self.work), "config", "user.name", "Mr. Rehan")
        self.git("-C", str(self.work), "config", "user.email",
                 "muhammadrehanqureshi@users.noreply.github.com")
        (self.work / "scripts").mkdir()
        (self.work / "tests").mkdir()
        (self.work / "cloud").mkdir()
        (self.work / ".repo-identity").write_text("remote", encoding="utf-8")
        (self.work / "scripts" / "check_governance.py").write_text(
            GOVERNANCE_STUB, encoding="utf-8", newline="\n")
        (self.work / "tests" / "test_ok.py").write_text(
            TEST_STUB, encoding="utf-8", newline="\n")
        (self.work / "cloud" / "worker.js").write_text(
            WORKER_STUB, encoding="utf-8", newline="\n")
        (self.work / "scripts" / "land.sh").write_bytes(LAND.read_bytes())
        # land.sh asks this helper which repository origin names.
        (self.work / "scripts" / "repo_identity.py").write_bytes(
            (ROOT / "scripts" / "repo_identity.py").read_bytes())
        self.git("-C", str(self.work), "add", "-A")
        self.git("-C", str(self.work), "commit", "-qm",
                 "Sandbox: bootstrap the landing workflow")
        self.git("-C", str(self.work), "branch", "-M", "master")
        self.git("-C", str(self.work), "push", "-qu", "origin", "master")
        self.git("-C", str(self.work), "checkout", "-qb", "local/sandbox-land")

    # ------------------------------------------------------------- helpers
    def git(self, *args, cwd=None):
        result = subprocess.run([GIT, *args], cwd=cwd, capture_output=True,
                                text=True, check=True)
        return result.stdout

    def run_bash(self, command, env=None):
        return subprocess.run([BASH, "-c", command], capture_output=True,
                              text=True, env=env, check=True)

    def land(self, *args, expect=0):
        env = dict(os.environ)
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        env["GH_STATE"] = str(self.state)
        env["GH_WORK"] = str(self.work)
        env["GH_BASE"] = "master"
        result = subprocess.run([BASH, "scripts/land.sh", *args],
                                cwd=self.work, capture_output=True, text=True,
                                env=env)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result

    def write(self, name, text):
        (self.work / name).write_text(text, encoding="utf-8", newline="\n")

    def remote_branches(self):
        return self.git("-C", str(self.remote), "branch", "--list")

    # --------------------------------------------------------------- tests
    def test_the_happy_path_lands_the_branch_through_the_stubbed_publish(self):
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m",
                           "Sandbox: land through the stubbed publish phase")
        self.assertIn("merged PR #1", result.stdout)
        self.assertTrue((self.state / "merged").is_file())
        log = self.git("-C", str(self.remote), "log", "--oneline", "master")
        self.assertIn("Sandbox: land through the stubbed publish phase", log)
        head = self.git("-C", str(self.work), "rev-parse",
                        "--abbrev-ref", "HEAD").strip()
        self.assertEqual(head, "master", "the checkout ends on the base branch")

    def test_it_waits_out_an_unknown_mergeable_state(self):
        # GitHub answers UNKNOWN while it computes mergeability, and the
        # first attempt at this aborted a pull request whose checks were
        # already green. Three UNKNOWN replies must be waited out, not
        # mistaken for a conflict.
        (self.state / "mergeable_unknown").write_text("3", encoding="utf-8")
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m",
                           "Sandbox: an unknown mergeable state is waited out")
        self.assertIn("still reports UNKNOWN", result.stdout)
        self.assertIn("merged PR #1", result.stdout)
        self.assertTrue((self.state / "merged").is_file())

    def test_a_dry_run_changes_nothing(self):
        before = self.git("-C", str(self.remote), "rev-parse", "master").strip()
        result = self.land("--dry-run", "-m", "Sandbox: dry run preview")
        self.assertIn("nothing will be staged", result.stdout)
        after = self.git("-C", str(self.remote), "rev-parse", "master").strip()
        self.assertEqual(before, after)
        self.assertNotIn("sandbox-land", self.remote_branches())

    def test_a_banned_message_is_refused_before_anything_is_staged(self):
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m", "Sandbox: a title\n\nGenerated with a robot",
                           expect=1)
        self.assertIn("banned trailer", result.stderr)
        self.assertEqual(self.git("-C", str(self.work), "status",
                                  "--porcelain").strip(), "?? README.md")
        self.assertNotIn("sandbox-land", self.remote_branches())

    def test_failing_tests_abort_before_publish(self):
        self.write("tests/test_ok.py", FAILING_TEST_STUB)
        result = self.land("-y", "-m", "Sandbox: failing validation must abort",
                           "--until", "validate", expect=1)
        self.assertNotIn("merged PR", result.stdout)
        self.assertNotIn("sandbox-land", self.remote_branches())

    def test_a_rebase_conflict_aborts_and_leaves_the_branch_alone(self):
        other = self.root / "other"
        self.git("clone", "-q", str(self.remote), str(other))
        self.git("-C", str(other), "config", "user.name", "Mr. Rehan")
        self.git("-C", str(other), "config", "user.email",
                 "muhammadrehanqureshi@users.noreply.github.com")
        (other / "README.md").write_text("master moved\n", encoding="utf-8")
        self.git("-C", str(other), "add", "-A")
        self.git("-C", str(other), "commit", "-qm", "Sandbox: master moves on")
        self.git("-C", str(other), "push", "-q", "origin", "master")
        self.write("README.md", "branch edit\n")
        result = self.land("-y", "-m", "Sandbox: conflicting change must abort",
                           "--until", "validate", expect=1)
        self.assertIn("rebase conflict", result.stderr)
        self.assertFalse((self.work / ".git" / "rebase-merge").exists())
        self.assertFalse((self.work / ".git" / "rebase-apply").exists())
        self.assertEqual(self.git("-C", str(self.work), "status",
                                  "--porcelain").strip(), "")
        subject = self.git("-C", str(self.work), "log", "-1", "--format=%s")
        self.assertIn("conflicting change must abort", subject)

    def test_a_rerun_after_a_hand_resolved_conflict_skips_the_commit_phase(self):
        # The documented resume: the conflict was resolved by hand, so the
        # branch already carries the commit and the tree is clean.
        self.write("README.md", "resolved\n")
        self.git("-C", str(self.work), "add", "-A")
        self.git("-C", str(self.work), "commit", "-qm", "Sandbox: resolved by hand")
        result = self.land("-y", "-m", "Sandbox: resume after a conflict",
                           "--until", "validate")
        self.assertIn("nothing new to commit", result.stdout)

    def test_it_refuses_a_checkout_that_declares_another_repository(self):
        # The failure this guards: a copy of this flow run from the other
        # project tree would publish that work into this public repository.
        (self.work / ".repo-identity").write_text(
            "charts-of-rehan", encoding="utf-8")
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m", "Sandbox: the wrong repository must abort",
                           expect=1)
        self.assertIn("refusing to land into the wrong repository", result.stderr)
        # Nothing was committed: the new file is still untracked.
        self.assertIn("?? README.md",
                      self.git("-C", str(self.work), "status", "--porcelain"))
        self.assertNotIn("sandbox-land", self.remote_branches())

    def test_it_refuses_a_checkout_that_declares_no_identity(self):
        (self.work / ".repo-identity").unlink()
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m", "Sandbox: a missing identity must abort",
                           expect=1)
        self.assertIn(".repo-identity", result.stderr)
        self.assertNotIn("sandbox-land", self.remote_branches())

    def test_it_refuses_to_land_on_the_base_branch_itself(self):
        self.git("-C", str(self.work), "checkout", "-q", "master")
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m", "Sandbox: must refuse this", expect=1)
        self.assertIn("refusing to land on master", result.stderr)

    def test_it_refuses_a_non_owner_identity(self):
        self.git("-C", str(self.work), "config", "user.name", "Someone Else")
        self.write("README.md", "readme\n")
        result = self.land("-y", "-m", "Sandbox: must refuse this", expect=1)
        self.assertIn("SO-7 requires the owner identity", result.stderr)


if __name__ == "__main__":
    unittest.main()
