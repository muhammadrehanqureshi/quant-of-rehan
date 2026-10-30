"""The retired chat route must never fake a delivery, and every sender's
own budget must still outlast the relay's answer.

Owner defect found 2026-10-16 while verifying the notification path end to
end against the live relay: ``POST /notify`` answered ``{"ok": true}`` but
took **42.2 seconds**, because the send ran inside the request on a slow
chat API. A sender that has already timed out cannot tell a refusal from a
slow yes, so the message was recorded as a failure while it still landed.

Owner order 2026-10-29 closed the chat channel for good, which retires the
whole hop, not just its deadline:

  * ``POST /notify`` answers 410 ``retired: "email"`` and sends nothing;
    a straggling sender records the delivery it did NOT get;
  * nothing on the edge defers a background send with ``ctx.waitUntil``
    any more: there is nothing left to send;
  * the notification channel is the owner email issue
    (src/notify/owner_email.py) from the Actions jobs, deduped per marker
    in the comment ledger.

These are source-level assertions because the worker runs on Cloudflare's
runtime, not in this suite; ``tools/worker_check.py`` remains the tool that
exercises a deployed worker with real credentials.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKER = ROOT / "cloud" / "worker.js"
PIPELINE = ROOT / "scripts" / "intraday_pipeline.py"
OPS_ALERT = ROOT / "scripts" / "ops_alert.py"

#: The tightest answer any caller of the relay waits on. The senders give
#: up at 30 seconds, and a retired 410 must land well inside that.
CLIENT_TIMEOUT_S = 30
MIN_ACCEPTABLE_TIMEOUT_S = 10


class RetiredChatRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = WORKER.read_text(encoding="utf-8")

    def test_the_retired_route_never_claims_a_delivery(self):
        """The 2026-10-16 defect is closed at the root: the route answers
        a refusal, never an acceptance for a message nobody received."""
        self.assertIn('ok: false, retired: "email",', self.worker)
        self.assertIn("}, 410);", self.worker)
        self.assertNotIn("accepted: true", self.worker)
        self.assertNotIn('delivery: "pending"', self.worker)

    def test_no_send_exists_anywhere_on_the_edge(self):
        """The deferral helpers are gone, not merely unused."""
        self.assertNotIn("sendAndRecord", self.worker)
        self.assertNotIn("api.telegram.org", self.worker)
        self.assertNotIn("TELEGRAM_", self.worker)

    def test_the_senders_still_carry_a_patient_budget(self):
        """Whatever the relay answers (410 on the retired route, a stored
        card on the live ones), a caller gives up later, never sooner."""
        for path in (PIPELINE, OPS_ALERT):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"timeout=(\d+)", source):
                with self.subTest(path=path.name, timeout=match.group(1)):
                    self.assertGreaterEqual(
                        int(match.group(1)), MIN_ACCEPTABLE_TIMEOUT_S,
                        f"{path.name} gives up inside the relay's slowness")
        self.assertLess(MIN_ACCEPTABLE_TIMEOUT_S, CLIENT_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
