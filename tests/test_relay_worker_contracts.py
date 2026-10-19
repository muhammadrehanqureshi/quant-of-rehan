"""Contract tests for the Cloudflare relay (cloud/worker.js).

The relay is the one component that cannot be exercised from this machine: a
Worker runs on Cloudflare's runtime (workerd), there is no local node, and this
PC is not allowed to be a schedule. So these tests read the deployed source and
pin the parts of the contract that the Python callers and the phone app depend
on, in the same spirit as tests/test_android_app_ui.py reading the app's XML.

Each assertion below stands for a defect that was measured on 2026-10-16, not a
style preference:

  * /status did not exist (a GET answered {"error": "not found"}) while the
    owner's interface list for the app names /status, /market and /signals;
  * the research routes validated the slot as HH:MM, and SO-13's 30 second loop
    labels its slots HH:MM:SS, so every observation the loop sent was answered
    400 "invalid observation" and never archived (GET /research/observations
    returned 0 rows for 2026-10-13, 2026-10-15 and 2026-10-16);
  * /notify waited for Telegram inside the request, and Telegram took 42.2
    seconds to answer, so every send was recorded as a failure;
  * the ops dedupe key was written BEFORE the send, so a failed alert was
    suppressed by its own attempt and never retried.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORKER = ROOT / "cloud" / "worker.js"


class RelayWorkerContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKER.read_text(encoding="utf-8")

    # ---------------------------------------------------------------- /status

    def test_status_and_health_are_one_answer(self):
        """The app's documented /status must exist and agree with /health."""
        self.assertIn("path === \"/health\" || path === \"/status\"", self.source,
                      "/status is not served beside /health")
        self.assertIn("return json(await healthPayload(env));", self.source)
        self.assertEqual(self.source.count("async function healthPayload(env)"), 1,
                         "the two names must come from one function, not two")

    def test_health_reports_the_last_telegram_outcome(self):
        """Acceptance and delivery are different facts, and both are reported."""
        self.assertIn('env.RELAY_KV.get("DELIVERY:LAST")', self.source,
                      "the relay does not record what Telegram answered")
        self.assertIn("last_delivery: lastDelivery", self.source,
                      "the recorded outcome never reaches a client")

    # ------------------------------------------------------- research routes

    def test_the_research_slot_accepts_seconds(self):
        """HH:MM:SS is a slot the 30 second loop legitimately produces."""
        # Built from chr(92) so this assertion cannot drift with the escaping
        # of the file it reads: the worker carries one backslash, as a JS
        # regex literal must.
        bs = chr(92)
        minutes = bs + "d{2}"
        slot_regex = "/^" + minutes + ":" + minutes + "(:" + minutes + ")?$/"
        self.assertEqual(self.source.count(slot_regex), 2,
                         "both /research/observation and /research/claim must "
                         "accept the minute and the seconds slot")

    # ------------------------------------------------------------ /notify

    def test_notify_does_not_wait_for_telegram(self):
        """A send nobody waits for runs in the background and is recorded."""
        self.assertIn("ctx.waitUntil(sendAndRecord(env, paired, text, \"ops\", alertKey))",
                      self.source)
        self.assertIn("ctx.waitUntil(sendAndRecord(env, paired, text, \"signals\", null))",
                      self.source)
        self.assertIn("async fetch(request, env, ctx)", self.source,
                      "the handler cannot defer work without ctx")
        self.assertIn('json({ ok: true, accepted: true, delivery: "pending" })',
                      self.source,
                      "an accepted message must not claim a completed delivery")

    def test_the_background_send_outlasts_telegram(self):
        """The background budget is the one that has to hold a slow answer."""
        bs = chr(92)
        digits = "(" + bs + "d+)"
        sync_budget = int(re.search("TELEGRAM_TIMEOUT_MS = " + digits + ";",
                                    self.source).group(1))
        async_budget = int(re.search("TELEGRAM_SEND_TIMEOUT_MS = " + digits + ";",
                                     self.source).group(1))
        self.assertGreater(async_budget, sync_budget)
        # Telegram's own answer took 42.2 seconds on 2026-10-16, and the client
        # budget in the Python senders is 30 seconds, so the background send
        # gets more than Telegram needed on the day it was measured.
        self.assertGreater(async_budget, 42200)
        self.assertIn("AbortSignal.timeout(timeoutMs || TELEGRAM_TIMEOUT_MS)",
                      self.source,
                      "the per-call budget is not wired into the fetch")

    def test_a_failed_alert_is_not_deduped_away(self):
        """The ops key is written after a successful send, never before."""
        route = self.source.index('if (kind === "ops")')
        body = self.source[route:route + 1400]
        self.assertIn("const seen = await env.RELAY_KV.get(alertKey);", body)
        self.assertIn("if (seen) return json({ ok: true, deduped: true",
                      body)
        self.assertNotIn('await env.RELAY_KV.put(alertKey, "1"', body,
                         "the route still suppresses an alert it never sent")
        sender = self.source.index("async function sendAndRecord(")
        tail = self.source[sender:sender + 1600]
        self.assertIn("if (sent.ok && dedupeKey)", tail,
                      "the dedupe key must depend on Telegram's own answer")

    # --------------------------------------------------------- market alerts

    def test_market_messages_are_exact_and_separate_states(self):
        for state, message in (
            ("OPEN", "Market is open. Quant is online now."),
            ("CLOSED", "Market is closed. Quant is sleeping now."),
            ("BREAK", "Market is on a break. Quant is sleeping until the market reopens."),
            ("HALTED", "Market is halted now. Quant is sleeping until the market reopens."),
        ):
            with self.subTest(state=state):
                self.assertIn(f'if (state === "{state}") return {"MSG_MARKET_" + state};',
                              self.source)
                self.assertIn(f'const MSG_MARKET_{state} = "{message}";', self.source)

    def test_market_transition_requires_fresh_market_wide_reg_evidence(self):
        self.assertIn("const MARKET_STATUS_MAX_AGE_MS = 90 * 1000;", self.source)
        self.assertIn('evidence = "fresh_broker_market_status";', self.source)
        self.assertIn('"no_fresh_market_wide_feed"', self.source)
        self.assertIn('feed.status !== "OPEN" && feed.status !== "HALTED"', self.source)
        self.assertIn('snapshot && snapshot.market_feed', self.source)
        # A symbol-level suspension must not be elevated to a global halt.
        self.assertIn("// never become a market-wide transition.", self.source)

    def test_live_quote_hub_has_bounded_validation_and_a_public_read_contract(self):
        self.assertIn('const QUOTE_MAX_SYMBOLS = 600;', self.source)
        self.assertIn('const QUOTE_MAX_BODY_BYTES = 256 * 1024;', self.source)
        self.assertIn('path === "/quotes/stream"', self.source)
        self.assertIn('path === "/quotes"', self.source)
        self.assertIn('name = "QUOTE_HUB"',
                      (ROOT / "cloud" / "wrangler.toml").read_text(encoding="utf-8"))
        self.assertIn('export class QuoteHub', self.source)
        self.assertIn('ctx.storage.sql.exec', self.source)
        self.assertIn('access-control-allow-origin": "*"', self.source)
        self.assertIn('cache-control": "no-store"', self.source)
        self.assertIn('typeof body.captured_at !== "string"', self.source)
        self.assertIn('const stamps = [];', self.source)

    def test_broker_feed_push_evaluates_market_transitions_without_phone_polling(self):
        route = self.source[self.source.index('if (request.method === "POST" && path === "/quotes")'):]
        route = route[:route.index('if (request.method === "GET" && path === "/dashboard")')]
        self.assertIn("await trackMarketTransitions(env,", route)
        self.assertIn("{ market_feed: result.market_feed }, new Date(), ctx)", route)
        self.assertIn('return json({ ...result, market_transition: transition }', route)
        hub = self.source[self.source.index('export class QuoteHub'):]
        self.assertIn('market_feed: current.market_feed', hub)

    def test_market_transition_dedupes_and_retries_failed_delivery(self):
        self.assertIn('const MARKET_PENDING_KEY = "MARKET:NOTIFICATION_PENDING";',
                      self.source)
        self.assertIn('const MARKET_STATE_KEY = "MARKET:LAST_CONFIRMED_STATE";',
                      self.source)
        self.assertIn("retry_after_ms = Date.now() + MARKET_TRANSITION_RETRY_MS", self.source)
        self.assertIn("current.identity !== identity", self.source)
        self.assertIn("retryPending ||", self.source)
        self.assertIn("ctx.waitUntil(deliverMarketTransition", self.source)

    def test_friday_break_and_reopen_follow_the_session_boundaries(self):
        self.assertIn('edge.condition === "BREAK"', self.source)
        self.assertIn('edge.phase === "POST_CLOSE"', self.source)
        self.assertIn('edge.phase === "PRE_OPEN"', self.source)
        self.assertIn("const sessionJustClosed = Number.isFinite(closeAt)", self.source)
        self.assertIn("now.getTime() - closeAt <= MARKET_OPEN_GRACE_MS", self.source)
        self.assertIn('state = "CLOSED";', self.source)
        self.assertIn("const MARKET_OPEN_GRACE_MS = 5 * 60 * 1000;", self.source)
        self.assertIn("now.getTime() - openAt <= MARKET_OPEN_GRACE_MS", self.source)
        self.assertIn("async scheduled(controller, env, ctx)", self.source)
        self.assertIn("await trackMarketTransitions(env, snapshot, now, ctx);", self.source)
        # Scheduled notifications have no direct hard-coded Telegram call.
        scheduled = self.source[self.source.index("async scheduled(controller, env, ctx)"):]
        self.assertNotIn('tgCall(env, "sendMessage"', scheduled)

    def test_session_edges_and_broker_halt_are_not_scanner_schedule_changes(self):
        for text in ("09:32", "15:30", "09:17", "12:00", "14:32", "16:30"):
            with self.subTest(edge=text):
                self.assertIn(text, self.source)
        workflow = (ROOT / ".github" / "workflows" / "intraday-session.yml").read_text(
            encoding="utf-8")
        self.assertIn("30 seconds", workflow)
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 30)',
                      (ROOT / "src" / "config.py").read_text(encoding="utf-8"))

    def test_durable_object_deploy_paths_declare_the_same_class(self):
        config = (ROOT / "cloud" / "wrangler.toml").read_text(encoding="utf-8")
        upload = (ROOT / "cloud" / "pair.py").read_text(encoding="utf-8")
        self.assertIn('name = "QUOTE_HUB"', config)
        self.assertIn('class_name = "QuoteHub"', config)
        self.assertIn('[exports.QuoteHub]', config)
        self.assertIn('"name": "QUOTE_HUB"', upload)
        self.assertIn('"class_name": "QuoteHub"', upload)
        self.assertIn('"QuoteHub": {"type": "durable-object", "storage": "sqlite"}',
                      upload)

    # --------------------------------------------------- unchanged contracts

    def test_the_admin_gate_and_the_card_routes_survive(self):
        """A refactor of /notify must not open the write routes."""
        for route in ('path === "/research/observation"', 'path === "/research/claim"',
                      'path === "/notify"', 'path === "/signals"'):
            with self.subTest(route=route):
                self.assertIn(route, self.source)
        self.assertIn("function adminOk(request, env)", self.source)
        self.assertIn('path.startsWith("/research/") && !adminOk(request, env)',
                      self.source)


if __name__ == "__main__":
    unittest.main()
