"""SO-22: the governance check that keeps a session from idling.

Owner order 2026-10-21: a session spent 14:30 to 15:30 sleeping until the
market closed, and he named that wait as the offence. The order is now law
in GOVERNANCE.md and AGENTS.md, and this check is its objection: a wait in
the tooling a session drives is pacing while it is short, and it is idling
the moment it is aimed at a market clock or stretched past the ceiling. The
cloud daemons (`src/data/session_gate.py` and the scan scheduler) still wait
for a session by design, which is why this check reads only `scripts/` and
`.github/workflows/`.

Everything here is offline and reads nothing outside a temporary tree,
except one test that reads the shipped tooling as it stands.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_governance as governance  # noqa: E402

LANDING = "scripts/land.sh"
RELAY_DEPLOY = ".github/workflows/deploy-relay.yml"
SPINNER = "scripts/wait_for_close.sh"


class IdleWaitRuleTest(unittest.TestCase):
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
        # The landing tool's own bounded pacing, and a relay deploy that
        # retries a propagation Check: both are waits that end quickly.
        self.write(LANDING, "for attempt in 1 2 3; do\n    sleep 10\ndone\n")
        self.write(
            RELAY_DEPLOY,
            "for i in 1 2 3; do\n  status=$(curl -s -o /dev/null -w '%{http_code}' $URL)\n  [ \"$status\" = 200 ] && break\n  sleep 10\ndone\n",
        )

    def errors(self) -> list:
        found: list = []
        governance.check_no_idle_waits(found)
        return [e for e in found if e.startswith("[SO-22]")]

    def test_short_pacing_anywhere_is_quiet(self):
        self.assertEqual(self.errors(), [])

    def test_a_retry_backoff_in_a_script_is_quiet(self):
        self.write(
            "scripts/notify.py",
            "for attempt in range(3):\n    time.sleep(2.0 * attempt)\n",
        )
        self.assertEqual(self.errors(), [])

    def test_a_wait_aimed_at_the_close_is_refused(self):
        self.write(
            SPINNER,
            "left=$(( $(close_minutes) - $(now_minutes) ))\n"
            "if [ \"$left\" -gt 0 ]; then\n    sleep \"$left\"\nfi\n",
        )
        errors = self.errors()
        self.assertTrue(errors)
        self.assertIn("market clock", " ".join(errors))

    def test_a_python_wait_named_after_a_session_moment_is_refused(self):
        self.write(
            "scripts/finalize.py",
            "import time\n"
            "def main():\n"
            "    time.sleep(seconds_until_close())\n",
        )
        self.assertIn("market clock", " ".join(self.errors()))

    def test_a_long_sleep_in_a_shell_script_is_refused(self):
        self.write(SPINNER, "sleep 900\n")
        errors = self.errors()
        self.assertTrue(errors)
        self.assertIn("900", " ".join(errors))

    def test_a_long_sleep_in_a_python_script_is_refused(self):
        self.write("scripts/spin.py", "import time\ntime.sleep(600)\n")
        self.assertIn("600", " ".join(self.errors()))

    def test_a_long_powershell_sleep_is_refused(self):
        self.write("scripts/spin.ps1", "Start-Sleep -Seconds 1200\n")
        self.assertIn("1200", " ".join(self.errors()))

    def test_the_ceiling_itself_is_pacing(self):
        self.write(SPINNER, "sleep 30\n")
        self.assertEqual(self.errors(), [])

    def test_one_second_past_the_ceiling_is_idling(self):
        self.write(SPINNER, "sleep 31\n")
        self.assertTrue(self.errors())

    def test_a_comment_about_sleeping_is_not_a_wait(self):
        self.write(
            SPINNER,
            "#!/usr/bin/env bash\n"
            "# never sleep until the close; the cloud waits for it\n",
        )
        self.assertEqual(self.errors(), [])

    def test_the_cloud_daemons_are_out_of_scope(self):
        # session_gate and the scan scheduler hold a session's wait on the far
        # side of the PC, so a wait named after the close is their job.
        self.write(
            "src/data/session_gate.py",
            "def gate(now):\n    time.sleep(seconds_until_close(now))\n",
        )
        self.assertEqual(self.errors(), [])


class ShippedLawTest(unittest.TestCase):
    """The order has to be written where a session reads it, and honoured."""

    def test_the_real_tooling_holds_no_clock_wait(self):
        found: list = []
        governance.check_no_idle_waits(found)
        self.assertEqual([e for e in found if e.startswith("[SO-22]")], [])

    @staticmethod
    def flat(name: str) -> str:
        # Markdown is wrapped by hand, so a phrase can straddle a line break.
        return " ".join((ROOT / name).read_text(encoding="utf-8").split())

    def test_the_governance_file_carries_the_order(self):
        text = self.flat("GOVERNANCE.md")
        self.assertIn("SO-22", text)
        self.assertIn("Don't ever sleep, do the work what I tell you", text)
        self.assertIn("the agent never sleeps", text.lower())

    def test_agents_md_carries_the_order_in_his_words(self):
        text = self.flat("AGENTS.md")
        self.assertIn("The no-idling rule", text)
        self.assertIn("Don't ever sleep, do the work what I tell you", text)
        self.assertIn("gh pr checks --watch", text)

    def test_the_ceiling_is_thirty_seconds(self):
        self.assertEqual(governance.MAX_PACING_SECONDS, 30)

    def test_the_landing_tool_stays_inside_its_ceiling(self):
        text = (ROOT / "scripts" / "land.sh").read_text(encoding="utf-8")
        waits = [
            int(m.group(1))
            for m in governance.LITERAL_WAIT.finditer(text)
            if m.group(1)
        ]
        self.assertTrue(waits, "land.sh is expected to poll GitHub's answers")
        self.assertLessEqual(max(waits), governance.MAX_PACING_SECONDS)


if __name__ == "__main__":
    unittest.main()
