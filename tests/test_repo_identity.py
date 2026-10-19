"""The helper the landing flow uses to know which repository it is in.

Two public repositories share this machine. ``.repo-identity`` names the one
this checkout belongs to, and origin must agree; a wrong answer here either
refuses every legitimate landing or accepts the wrong repository, so every
shape of remote is covered.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from repo_identity import repository_name  # noqa: E402

SCRIPT = ROOT / "scripts" / "repo_identity.py"


class RepositoryNameTest(unittest.TestCase):

    def test_an_https_remote(self):
        self.assertEqual(
            repository_name("https://github.com/muhammadrehanqureshi/"
                            "quant-of-rehan.git"),
            "quant-of-rehan")

    def test_an_https_remote_without_the_suffix(self):
        self.assertEqual(
            repository_name("https://github.com/muhammadrehanqureshi/"
                            "charts-of-rehan"),
            "charts-of-rehan")

    def test_an_scp_style_ssh_remote(self):
        self.assertEqual(
            repository_name("git@github.com:muhammadrehanqureshi/"
                            "quant-of-rehan.git"),
            "quant-of-rehan")

    def test_a_posix_local_remote(self):
        self.assertEqual(repository_name("/tmp/sandbox/remote.git"), "remote")

    def test_a_windows_local_remote_prints_backslashes(self):
        url = "C:\\Users\\rehan\\AppData\\Local\\Temp\\abc\\remote.git"
        self.assertEqual(repository_name(url), "remote")

    def test_a_trailing_separator_is_ignored(self):
        self.assertEqual(
            repository_name("https://github.com/owner/quant-of-rehan.git/"),
            "quant-of-rehan")

    def test_an_empty_url_has_no_name(self):
        self.assertEqual(repository_name(""), "")
        self.assertEqual(repository_name("   "), "")

    def test_the_command_prints_the_name_and_nothing_else(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT),
             "https://github.com/owner/charts-of-rehan.git"],
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), "charts-of-rehan")
        self.assertEqual(result.stderr, "")

    def test_the_command_refuses_to_guess_without_an_argument(self):
        result = subprocess.run([sys.executable, str(SCRIPT)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


if __name__ == "__main__":
    unittest.main()
