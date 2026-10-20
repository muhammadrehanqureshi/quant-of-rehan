"""The relay's dispatch token is bound from CI, and never printed.

Owner order 2026-10-20: `cloud/worker.js` dispatches the band scan on
`env.GH_DISPATCH_TOKEN`, and that binding has to exist for the punctual band
opens to work at all. The token is a fine grained PAT with Actions: write on
this repository. SO-5 keeps it out of the repository, the logs and the
messages, which leaves exactly one road: a GitHub secret, piped into wrangler's
stdin on a runner that already holds the Cloudflare credentials.

The assertions below are about that road staying the only one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "bind-relay-dispatch.yml"
WORKER = ROOT / "cloud" / "worker.js"


class BindingWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.worker = WORKER.read_text(encoding="utf-8")

    def test_the_worker_reads_the_binding_it_is_given(self):
        # The name in the workflow and the name the worker reads are one name.
        self.assertIn('env.GH_DISPATCH_TOKEN', self.worker)
        self.assertIn("GH_DISPATCH_TOKEN", self.workflow)
        self.assertIn("intraday-session.yml", self.worker)

    def test_the_value_travels_on_stdin_from_a_secret(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("secrets.GH_DISPATCH_TOKEN", self.workflow)
        self.assertIn("printf '%s' \"$GH_DISPATCH_TOKEN\"", self.workflow)
        self.assertIn("wrangler secret put GH_DISPATCH_TOKEN", self.workflow)
        # A value on the command line would land in the runner's log; stdin
        # does not.
        self.assertNotIn("--body", self.workflow)
        self.assertNotRegex(self.workflow, r"secret put GH_DISPATCH_TOKEN[^\n]*\n\s*\S+\s*$")

    def test_it_never_echoes_or_writes_the_value(self):
        for leak in ('echo "$GH_DISPATCH_TOKEN"',
                     "echo $GH_DISPATCH_TOKEN",
                     'echo "${GH_DISPATCH_TOKEN}"'):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, self.workflow)
        # Only the secret's NAME is ever dumped.
        self.assertIn("wrangler secret list", self.workflow)

    def test_a_successful_upload_is_not_the_evidence(self):
        # The last word is a real dispatch POST, the same call the worker makes.
        self.assertIn("/dispatches", self.workflow)
        self.assertIn('test "$post_code" = "204"', self.workflow)
        self.assertIn("GET intraday-session.yml", self.workflow)

    def test_nothing_cloudflare_is_hardcoded(self):
        self.assertIn("secrets.CLOUDFLARE_API_TOKEN", self.workflow)
        self.assertIn("secrets.CLOUDFLARE_ACCOUNT_ID", self.workflow)
        self.assertIsNone(re.search(r"[0-9a-f]{32}", self.workflow))


if __name__ == "__main__":
    unittest.main()
