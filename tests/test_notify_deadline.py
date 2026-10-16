"""The relay's Telegram call is bounded, and the senders' budgets agree with it.

Owner defect found 2026-10-16 while verifying the notification path end to
end against the live relay: ``POST /notify`` answered ``{"ok": true}`` but took
**42.2 seconds**. Everything that calls the relay gives up sooner than that
(``scripts/intraday_pipeline.py`` and ``scripts/ops_alert.py`` use a 30 second
timeout, as does the daily push), and a client that has already timed out
cannot tell a refusal from a slow yes: the message lands on the phone and the
sender records a failure. The worker's own Telegram call is therefore bounded,
so the honest answer arrives inside every client's budget.

These are source-level assertions because the worker runs on Cloudflare's
runtime, not in this suite; the behavioural half is the measured 42.2s against
the live edge recorded in the audit, and ``tools/worker_check.py`` remains the
tool that exercises a deployed worker with real credentials.
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

#: The worker's own deadline, and the client timeout it must fit inside.
WORKER_DEADLINE_MS = 10_000
CLIENT_TIMEOUT_S = 30


class TelegramCallDeadlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = WORKER.read_text(encoding="utf-8")

    def test_the_telegram_call_carries_a_deadline(self):
        self.assertIn("const TELEGRAM_TIMEOUT_MS = 10000;", self.worker)
        self.assertIn("AbortSignal.timeout(TELEGRAM_TIMEOUT_MS)", self.worker)

    def test_a_timed_out_send_is_reported_and_not_swallowed(self):
        """The route turns the miss into a 502 carrying the reason."""
        self.assertIn("return { ok: false,", self.worker)
        self.assertIn("telegram did not answer within", self.worker)
        # and /notify still surfaces whatever tgCall said
        self.assertIn('error: sent.description || "telegram refused"',
                      self.worker)

    def test_the_deadline_fits_inside_every_client_timeout(self):
        """A worker deadline longer than a caller's budget is the bug again."""
        self.assertLess(WORKER_DEADLINE_MS, CLIENT_TIMEOUT_S * 1000)
        for path in (PIPELINE, OPS_ALERT):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"timeout=(\d+)", source):
                with self.subTest(path=path.name, timeout=match.group(1)):
                    self.assertGreaterEqual(
                        int(match.group(1)) * 1000, WORKER_DEADLINE_MS,
                        f"{path.name} gives up before the worker's own "
                        f"Telegram deadline, so a slow delivery is "
                        f"indistinguishable from a refusal")


if __name__ == "__main__":
    unittest.main()
