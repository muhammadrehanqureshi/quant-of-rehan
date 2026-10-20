"""A slow Telegram call must never be mistaken for a refusal on the phone.

Owner defect found 2026-10-16 while verifying the notification path end to end
against the live relay: ``POST /notify`` answered ``{"ok": true}`` but took
**42.2 seconds**, while every sender gives up sooner (``intraday_pipeline.py``
and ``ops_alert.py`` use a 30 second timeout, as does the daily push). A sender
that has already timed out cannot tell a refusal from a slow yes, so the
message lands on the phone and the sender records a failure.

The first fix bounded the caller-side call at 10 seconds. Measured again on
2026-10-16 11:47 PKT, that turned every send into a reported failure: /notify
and /updates both answered ``telegram did not answer within 10s
(TimeoutError)``. So the send moved off the request path altogether:

  * ``/notify`` accepts the message, answers immediately, and defers the
    Telegram call with ``ctx.waitUntil`` (the scan cycle cannot be held for 42
    seconds, and a client budget cannot decide whether a message was sent);
  * the deferred send carries its own, longer deadline, above Telegram's
    measured answer time;
  * its outcome is written to KV and reported by ``/status`` as
    ``last_delivery``, so "the relay accepted it" and "Telegram delivered it"
    stay two different facts (the owner asked for exactly that separation).

These are source-level assertions because the worker runs on Cloudflare's
runtime, not in this suite; ``tools/worker_check.py`` remains the tool that
exercises a deployed worker with real credentials, and the live measurements
above are the behavioural half.
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

#: The deadline for a call somebody is waiting on, and the client budget it
#: must fit inside. The background budget is separate and deliberately larger.
WORKER_DEADLINE_MS = 10_000
CLIENT_TIMEOUT_S = 30
#: Measured 2026-10-16: Telegram's own answer to sendMessage took 42.2s.
MEASURED_TELEGRAM_ANSWER_MS = 42_200


class TelegramCallDeadlineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = WORKER.read_text(encoding="utf-8")

    def test_the_interactive_telegram_call_still_carries_a_deadline(self):
        self.assertIn("const TELEGRAM_TIMEOUT_MS = 10000;", self.worker)
        self.assertIn("AbortSignal.timeout(timeoutMs || TELEGRAM_TIMEOUT_MS)",
                      self.worker)

    def test_the_background_send_outlasts_telegram(self):
        match = re.search(r"TELEGRAM_SEND_TIMEOUT_MS = (\d+);", self.worker)
        self.assertIsNotNone(match, "the deferred send has no budget of its own")
        self.assertGreater(int(match.group(1)), MEASURED_TELEGRAM_ANSWER_MS)
        self.assertIn("TELEGRAM_SEND_TIMEOUT_MS)", self.worker,
                      "the deferred send does not use its own budget")

    def test_notify_does_not_wait_for_telegram(self):
        self.assertIn('json({ ok: true, accepted: true, delivery: "pending" })',
                      self.worker,
                      "the route still claims a completed delivery")
        self.assertIn("ctx.waitUntil(sendAndRecord(env, paired, text, \"signals\", null))",
                      self.worker)
        # Owner order 2026-10-20 (third note): the ops kind sends nothing, so
        # only the signal send is deferred now.
        self.assertNotIn("ctx.waitUntil(sendAndRecord(env, paired, text, \"ops\", alertKey))",
                         self.worker)
        self.assertIn("async fetch(request, env, ctx)", self.worker)

    def test_the_telegram_answer_is_recorded_and_not_swallowed(self):
        """A timeout or a refusal becomes a recorded outcome, not a silence."""
        self.assertIn("telegram did not answer within", self.worker)
        self.assertIn('kvPut(env, "DELIVERY:LAST"', self.worker)
        self.assertIn("ok: Boolean(sent.ok)", self.worker)
        self.assertIn("last_delivery: lastDelivery", self.worker,
                      "the recorded outcome never reaches the app")

    def test_the_acceptance_answer_fits_inside_every_client_timeout(self):
        """What a caller waits for is the acceptance, and that stays short."""
        self.assertLess(WORKER_DEADLINE_MS, CLIENT_TIMEOUT_S * 1000)
        for path in (PIPELINE, OPS_ALERT):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"timeout=(\d+)", source):
                with self.subTest(path=path.name, timeout=match.group(1)):
                    self.assertGreaterEqual(
                        int(match.group(1)) * 1000, WORKER_DEADLINE_MS,
                        f"{path.name} gives up before the relay can answer")


if __name__ == "__main__":
    unittest.main()
