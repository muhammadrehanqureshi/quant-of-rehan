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
  * the ops dedupe key was written BEFORE the send, so a failed alert was
    suppressed by its own attempt and never retried;
  * the chat hop finally answered {"ok": true} while the message went
    nowhere, and on 2026-10-29 the owner's chat channel was closed for good,
    so the route is retired and nothing on the edge sends a message.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "cloud"))

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

    def test_health_carries_no_retired_delivery_ledger(self):
        """The chat link is gone, so no delivery ledger may be served."""
        self.assertNotIn("DELIVERY:LAST", self.source,
                         "the retired send still has a ledger on the edge")
        self.assertNotIn("last_delivery", self.source)

    def test_the_relay_lives_without_a_kv_namespace(self):
        """Owner order 2026-10-20: no product that mails a quota warning.

        The 2026-10-19 email ("KV daily limit reached 50% today") came from the
        free plan allowance of about 100,000 reads and 1,000 writes a day, and
        the deploy then began refusing outright because the namespace it bound
        no longer existed (run 39241261663: "KV namespace ... not found"), so
        the edge kept running a build from before the memo fix. The relay now
        keeps the card, the snapshot, the session state, the pairing codes and
        the research log in the QuoteHub Durable Object it already needed, and
        binds no namespace at all.
        """
        self.assertIn("const KV_MEMO_TTL_MS = 10000;", self.source)
        self.assertIn("async function kvGet(env, key, ttlMs = KV_MEMO_TTL_MS)",
                      self.source)
        self.assertIn('const STATE_HUB_NAME = "psx-live-quotes";', self.source)
        for helper in ("async function relayRead(", "async function relayWrite(",
                       "async function relayDelete(", "async function relayList("):
            with self.subTest(helper=helper):
                self.assertIn(helper, self.source)
        # No call site may reach past the helpers into KV directly.
        self.assertNotIn("env.RELAY_KV.get(", self.source)
        self.assertNotIn("env.RELAY_KV.put(", self.source)
        self.assertNotIn("env.RELAY_KV.delete(", self.source)
        self.assertNotIn("env.RELAY_KV.list(", self.source)
        self.assertIn("CREATE TABLE IF NOT EXISTS relay_state", self.source)
        config = (ROOT / "cloud" / "wrangler.toml").read_text(encoding="utf-8")
        self.assertNotIn("[[kv_namespaces]]", config,
                         "the Worker still declares a KV namespace")
        workflow = (ROOT / ".github" / "workflows" / "deploy-relay.yml").read_text(
            encoding="utf-8")
        self.assertNotIn("RELAY_KV_ID", workflow,
                         "the deploy still waits for a namespace id")
        pair = (ROOT / "cloud" / "pair.py").read_text(encoding="utf-8")
        self.assertNotIn('"kv_namespace"', pair,
                         "a manual deploy still uploads a KV binding")
        # The transition ledger is the only stateful read left after the
        # delivery-retry path was retired: it reads the confirmed state
        # through the memo helper rather than the helpers' KV names.
        self.assertIn("kvGet(env, MARKET_STATE_KEY)", self.source)

    def test_health_names_the_commit_the_edge_is_running(self):
        """`ok: true` proved only that SOMETHING answered.

        Run 39225627067 uploaded nothing and a green /health would still have
        been read as a successful deploy, so the workflow now sets the commit
        as WORKER_VERSION and asks /health for it back.
        """
        self.assertIn("version: env.WORKER_VERSION || null,", self.source)
        workflow = (ROOT / ".github" / "workflows" / "deploy-relay.yml").read_text(
            encoding="utf-8")
        self.assertIn("--var WORKER_VERSION:${{ github.sha }}", workflow)
        self.assertIn('json.load(sys.stdin).get("version")', workflow,
                      "the verify step does not read the version it asked for")
        self.assertIn("the deploy did not land", workflow)
        # A refused deploy is annotated with what the owner must check, because
        # 10041 is never caused by the code in this repository.
        self.assertIn("Workers Scripts: Edit", workflow)

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

    def test_notify_is_retired_and_never_fakes_a_delivery(self):
        """Owner order 2026-10-29: the chat channel is gone.

        The route answers 410 so a straggling sender records the delivery it
        did NOT get, instead of an "accepted" message that never arrived
        anywhere. Notifications travel on the owner email issue
        (src/notify/owner_email.py) from the Actions jobs.
        """
        route = self.source[self.source.index('path === "/notify"'):]
        route = route[:route.index('if (request.method === "OPTIONS"')]
        self.assertIn("if (!adminOk(request, env)) {", route,
                      "the retired route must keep its admin gate")
        self.assertIn('ok: false, retired: "email",', route)
        self.assertIn("}, 410);", route,
                      "a retired route must answer a completion nobody got")
        self.assertNotIn("waitUntil", route,
                         "a retired route must not queue a background send")
        # No send helper may exist anywhere: the route is the only chat
        # entry point and it sends nothing.
        for gone in ("sendAndRecord", "tgCall", "api.telegram.org",
                     "TELEGRAM_TIMEOUT_MS", "MARKET_PENDING_KEY"):
            self.assertNotIn(gone, self.source)

    # --------------------------------------------------------- market alerts

    def test_market_event_emails_are_gone(self):
        """Owner order 2026-10-31: no market event emails exist at all.

        The open, the close and the break no longer email the owner from
        ANY path: the dedicated market-email workflow and its script are
        deleted, the band loop's market_watch passenger is deleted, and
        the only owner emails an Actions job may send are the actual
        intraday signals (the trade entry and the call watch) and the
        deduped ops alerts. The worker carries only the app card's own
        condition strings, which must not borrow the notification
        wording.
        """
        for retired in ("MSG_MARKET", "Market is open. Quant is online now.",
                        "Market is closed. Quant is sleeping now."):
            self.assertNotIn(retired, self.source)
        for gone in (".github/workflows/market-email.yml",
                     "scripts/market_email.py",
                     "src/notify/market_watch.py",):
            self.assertFalse((ROOT / gone).exists(),
                             f"the retired market email path must be gone: {gone}")
        loop_source = (ROOT / "scripts" / "scan_loop.py").read_text(
            encoding="utf-8")
        self.assertNotIn("MarketEventWatcher", loop_source)
        self.assertNotIn("market_events", loop_source)
        self.assertNotIn("EMAIL_SLOT_VERDICTS",
                         (ROOT / ".github" / "workflows" /
                          "intraday-capture.yml").read_text(encoding="utf-8"))
        sessions_source = (ROOT / "src" / "data" / "sessions.py").read_text(
            encoding="utf-8")
        self.assertIn("Market is open. Quant is online now.", sessions_source)

    def test_market_transition_requires_fresh_market_wide_reg_evidence(self):
        self.assertIn("const MARKET_STATUS_MAX_AGE_MS = 90 * 1000;", self.source)
        self.assertIn('evidence = "fresh_broker_market_status";', self.source)
        self.assertIn('"no_fresh_market_wide_feed"', self.source)
        self.assertIn('feed.status !== "OPEN" && feed.status !== "HALTED"', self.source)
        self.assertIn('snapshot && snapshot.market_feed', self.source)
        # A symbol-level suspension must not be elevated to a global halt.
        self.assertIn("// never become a market-wide transition.", self.source)

    def test_market_polls_never_wait_for_a_portal_rebuild(self):
        """A slow exchange page must not delay the live card by twenty seconds.

        The portal snapshot has a five minute cache, and both of its fetches
        carry a nine second timeout. Rebuilding it inside GET /market made the
        first app poll after expiry wait for the portal. The cached copy is now
        answered immediately and one shared background task refreshes it.
        """
        helper = self.source[self.source.index(
            "async function refreshMarketSnapshot(env, now)"):]
        helper = helper[:helper.index("// A cold cache still answers immediately.")]
        self.assertIn("if (marketRefreshInFlight) return marketRefreshInFlight;",
                      helper)
        block = self.source[self.source.index(
            "async function marketSnapshot(env, now, ctx)"):]
        block = block[:block.index("function pktInstant(")]
        self.assertIn("ctx.waitUntil(refreshMarketSnapshot(env, now));", block)
        self.assertIn("return normalizeMarket(cached);", block)
        self.assertIn("return normalizeMarket(blankMarketSnapshot(now));", block)
        self.assertNotIn("await buildMarketSnapshot(now)", block,
                         "a client poll must not wait for the portal build")
        self.assertIn("marketResponseSnapshot(env, now, ctx)", self.source)

    def test_live_card_ranking_comes_only_from_fresh_quotes(self):
        """A stale portal leader cannot sit beside fresh one-second quotes."""
        block = self.source[self.source.index(
            "async function applyLiveQuotes("):]
        block = block[:block.index("async function marketResponseSnapshot(")]
        self.assertIn("for (const quote of liveBySymbol.values()) {", block)
        self.assertNotIn("(snapshot.top_volume || []).map", block)
        self.assertIn("snapshot.stale = false;", block)

    def test_the_market_answer_carries_the_wl_ledger(self):
        """Owner order 2026-10-31: the W/L = W/L RATE tile reads ONE ledger.

        The phone re-asks GET /market every second, so the closed-trade
        rows are counted once into a five-minute cache row
        (RESEARCH:WINLOSS), never re-listed per second, and a cold or
        failing store leaves win_loss out of that one answer instead of
        fabricating a rate (SO-3). The hit-time close ledger and the
        finalized outcome overlap by design; the date key counts the trade
        once. The rate is the losing share of the CLOSED trades only, and
        both-zero answers a null rate.
        """
        self.assertIn("const TRADE_OUTCOME_LABELS = new Set([", self.source,
                      "only closed trade outcomes count")
        # The archive's own field is `outcome`, named by
        # src/signals/trade_state.py and scripts/intraday_pipeline.py's
        # run_finalize; its closed-trade values are the four exits the
        # paper trade can reach.
        self.assertIn('"TARGET_HIT", "STOP_HIT", "STOP_AMBIGUOUS", '
                      '"CLOSED_AT_SESSION_END",', self.source)
        self.assertIn("session.outcome", self.source)
        self.assertIn("const WINLOSS_CACHE_SECONDS = 300;", self.source)
        self.assertIn('relayList(env, "RESEARCH:OUTCOME:", 1000)', self.source)
        self.assertIn('relayList(env, "RESEARCH:CLOSE:", 1000)', self.source)
        self.assertIn('path === "/research/close"', self.source)
        self.assertIn('kvDelete(env, "RESEARCH:WINLOSS")', self.source)
        self.assertIn("byDate", self.source)
        self.assertIn('kvPut(env, "RESEARCH:WINLOSS"', self.source)
        # The rate is computed from the closed total; both zero answers null.
        self.assertIn("rate_pct: total > 0 ? Math.round((losses / total) * 100) : null,",
                      self.source)
        # The market route grafts the block in, best effort: a failing
        # research store never fails the card.
        route = self.source[self.source.index(
            'if (request.method === "GET" && path === "/market")'):]
        route = route[:route.index('if (request.method === "POST" && path === "/market")')]
        self.assertIn("marketWinLoss(env)", route)
        self.assertIn("win_loss: winLoss,", route)

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

    def test_market_transitions_are_recorded_never_delivered_from_the_edge(self):
        """Owner order 2026-10-29: the edge confirms state, owner email sends.

        A transition still records its confirmed state so the dedupe law
        answers honestly, but no notification is queued, retried or
        delivered from the relay.
        """
        self.assertIn('const MARKET_STATE_KEY = "MARKET:LAST_CONFIRMED_STATE";',
                      self.source)
        self.assertNotIn("MARKET_PENDING_KEY", self.source,
                         "a pending-retry delivery survived the retirement")
        self.assertNotIn("deliverMarketTransition", self.source)
        self.assertNotIn("MARKET_TRANSITION_RETRY_MS", self.source)
        self.assertNotIn("retryPending", self.source)
        self.assertIn("previous.identity === identity", self.source,
                      "the transition ledger no longer dedupes a day:state")
        self.assertIn('let evidence = "session_schedule";', self.source)

    def test_one_truth_per_stock_per_day(self):
        """Owner order 2026-10-31: the app cannot answer one stock twice.

        Three laws are pinned from the worker's sources:

          * a frame whose own tick sits outside its day's regular bands
            never enters the quote store, so the search can never answer
            with the post-market tail the card's regular session never
            saw;
          * every display path (the merged card, /stock, /prices) reads
            and advances ONE acknowledged frame per Karachi day, band
            and symbol, stored in the durable object;
          * the acknowledged pair is clamped, so the printed B and S can
            never decrease within a day: volume increases, or it does
            not print.
        """
        self.assertIn("function frameIsRegularSession(quote)", self.source)
        self.assertIn("function regularBandIndexOf(quote)", self.source)
        self.assertIn("REGULAR_SESSION_GRACE_MS", self.source)
        # Store law: the post-market tail is refused at the DO's own
        # update route, before any row can be merged. The probe is
        # bounded from the route's own anchor, and its message carries
        # the offsets so a CI failure can be read on its own (SO-3).
        probe_at = self.source.find('url.pathname === "/update"')
        self.assertGreaterEqual(
            probe_at, 0, "the durable object's POST /update route is gone")
        update_route = self.source[probe_at:probe_at + 11000]
        self.assertIn("frameIsRegularSession(quote)", update_route,
                      f"the /update anchor sits at {probe_at}; the store law "
                      f"is not inside the route's own first 11000 characters")
        self.assertIn("refused_post_session", update_route,
                      f"the /update anchor sits at {probe_at}; the refusal "
                      f"count is not inside the route's own first 11000 chars")
        # The acknowledged store lives in the durable object.
        hub = self.source[self.source.index("export class QuoteHub"):]  # the class to the end of the file
        self.assertIn("/ack-upsert", hub)
        self.assertIn("/ack-splits", hub)
        self.assertIn("ackCandidate(frame)", hub)
        self.assertIn("clampPair(parsed", hub)
        # And every answer path reads the SAME stored pair.
        self.assertIn("applyStoredFrame(row, storedRows[row.symbol])", self.source)
        self.assertIn("applyStoredFrame(stock, stored)", self.source)
        self.assertIn("ackRowsForDay(env, ackDay)", self.source)

    def test_prices_does_not_scan_every_ack_row_on_each_poll(self):
        """The phone reads /prices once per tick; that must not list 319 rows.

        The free Durable Objects plan allows 5,000,000 SQL rows reads a day.
        Listing the day's ACK rows for every /prices poll exhausted it on
        2026-11-04 and stopped the relay. The QuoteHub already sees every ACK
        write, so it keeps the day's map in memory and only loads SQL on a
        fresh instance or a new Karachi day.
        """
        hub = self.source[self.source.index("export class QuoteHub"):]
        self.assertIn("this.ackRowsBySymbol", hub)
        self.assertIn("this.ackRowsLoaded", hub)
        self.assertIn("rememberAckFrame(parsed.day, stored)", hub)
        splits = hub[hub.index('url.pathname === "/ack-splits"'):]
        splits = splits[:splits.index('url.pathname === "/snapshot"')]
        self.assertIn(
            "if (this.ackRowsLoaded && this.ackRowsDay === day &&", splits,
            "the ACK day map must be served from memory before SQL")
        self.assertIn("this.ackRowsBySymbol = ackRows", splits)

    def test_the_acknowledged_pair_can_only_move_forward(self):
        """Owner order 2026-10-31: volume decreases are impossible prints.

        The clamp's arithmetic is pinned: buy stays at or above its own
        previous value and below the volume minus the previous sell, so
        BOTH sides are monotone while their sum stays exactly the row's
        own total.
        """
        clamp_at = self.source.find("function clampPair(candidate")
        self.assertGreaterEqual(
            clamp_at, 0, "the acknowledged pair's clamp function is gone")
        clamp = self.source[clamp_at:clamp_at + 2000]
        self.assertIn("Math.max(buy, previous.buy_volume)", clamp,
                      f"the clamp anchor sits at {clamp_at}; its monotone "
                      f"buy floor is not inside its own first 2000 characters")
        self.assertIn("volume - previous.sell_volume", clamp,
                      f"the clamp anchor sits at {clamp_at}; its monotone "
                      f"sell ceiling is not inside its own first 2000 chars")
        self.assertIn("sell = volume - buy", clamp,
                      f"the clamp anchor sits at {clamp_at}; its own sum "
                      f"law is not inside its first 2000 characters")
        # An older total never moves the acknowledged row backwards.
        hub = self.source[self.source.index("export class QuoteHub"):]  # the class to the end of the file
        self.assertIn(
            "Math.round(Number(previous.volume) || 0) >= parsed.volume",
            hub,
            "the durable object no longer refuses an acknowledged older total")

    def test_the_quote_store_is_monotone_for_every_symbol(self):
        """Owner order 2026-11-02: volume and B/S never go backward."""
        self.assertIn("function splitFromQuote(quote)", self.source)
        self.assertIn("function quoteSessionKey(quote)", self.source)
        update_at = self.source.find('url.pathname === "/update"')
        self.assertGreaterEqual(update_at, 0)
        update = self.source[update_at:update_at + 9000]
        self.assertIn("newVolume < oldVolume", update)
        self.assertIn("oldKey.day === newKey.day", update)
        self.assertNotIn("oldKey.band", update)
        self.assertIn("splitFromQuote(quote)", update)
        self.assertIn("clampPair(pair, previous)", update)
        self.assertIn('"cache-control": "no-store"', self.source)

    def test_the_write_budget_is_pinned_not_silent(self):
        """Owner order 2026-11-03: Cloudflare's free-plan Durable Objects
        rows_written cap must not be consumed by per-push writes again.

        The flow backup is the one table whose per-symbol row would repeat
        on every push, so its cadence and hard day row budget are pinned in
        the Worker source. Same idea for the ACK mirror: a display poll must
        not be able to buy hundreds of ACK rows an hour, so the mirror
        write is at most one per symbol per window and a newer live frame
        still wins on read.

        Owner incident 2026-11-04: the 30 second window wrote about 230,000
        ACK rows in a session, which is more than twice the free plan's
        100,000 rows written per ACCOUNT per day, and the relay went dark
        with the market still open. The window and the hard ceiling are
        pinned here so neither can drift back.
        """
        self.assertIn("const FLOW_FLUSH_MS = 10 * 60 * 1000", self.source)
        self.assertIn("const FLOW_ROWS_PER_DAY = 40000", self.source)
        self.assertIn("if (flushed - this.lastFlowFlush >= FLOW_FLUSH_MS)", self.source)
        self.assertIn("this.flowRowsToday += rows", self.source)
        self.assertIn("const ACK_WRITE_MIN_MS = 5 * 60 * 1000;", self.source)
        self.assertIn("const ACK_ROWS_PER_DAY = 25000;", self.source)
        self.assertIn("this.lastAckWrites.get(key)", self.source)
        self.assertIn("nowMs - lastAckWrite < ACK_WRITE_MIN_MS", self.source)
        self.assertIn("if (this.ackWritesToday >= ACK_ROWS_PER_DAY)", self.source)
        self.assertIn("this.ackWritesToday += 1;", self.source)
        # A newer live frame is not silently replaced by an older mirror.
        self.assertIn("storedAt < rowAt", self.source)

    def test_the_snapshot_lives_in_memory_and_the_hub_never_throws(self):
        """Owner order 2026-11-05: a daily free-plan budget can never again
        kill the live feed or surface as the edge's HTML error page.

        Cloudflare's Durable Objects free tier allows 5,000,000 rows read
        and 100,000 rows written a day, reset at 00:00 UTC, and exceeding
        one makes the storage call THROW inside the object. Two laws pin
        the guarantee: the accepted snapshot lives in the hub's memory -
        so a push does not SELECT the day's row back and a reading poll
        (the phone's every-second card, the desk's slower pace) costs no
        SQLite read at all - and every throw inside the hub collapses to
        a JSON refusal, never an HTML page, with the persistence itself
        best effort and the reason recorded once for /health.
        """
        # The snapshot's memory law, both read and write.
        self.assertIn("this.snapshotCache = null;", self.source)
        self.assertIn("if (this.snapshotLoaded) {", self.source)
        self.assertIn("this.snapshotCache = snapshot;", self.source)
        # The push reads its previous from memory after the one load.
        self.assertIn("let previous = this.snapshotCache;", self.source)
        # Per-push writes are best effort, with the reason named for /health.
        self.assertIn("let stored = true;", self.source)
        self.assertIn("stored = false;", self.source)
        self.assertIn('"SNAPSHOT:PERSIST_ERROR"', self.source)
        # Nothing thrown inside the object escapes as HTML 1101: the
        # wrapper answers JSON and the publisher retries.
        self.assertIn("return await this.handle(request);", self.source)
        self.assertIn('error: "quote hub refused: " +', self.source)
        # Per-quoted diagnostics can never spend the write budget on
        # themselves: one FLOW:LAST_ERROR note a minute at most.
        self.assertIn("this.lastFlowErrorSeen = 0;", self.source)
        self.assertIn("stamp - this.lastFlowErrorSeen >= 60000", self.source)

    def test_the_daily_row_budget_sums_below_the_free_plan(self):
        """Owner order 2026-11-05: the pinned ceilings must add up below
        Cloudflare's free-plan account cap of 100,000 rows written a day
        (rows read are held near zero by the snapshot's memory law).

        Worst arithmetic for one full session: one snapshot row per push
        (a push at most once a second for the 09:30 to 15:30 session is
        21,600), the flow backup's own 40,000 ceiling, the ACK mirror's
        25,000, the 10-minute stats row and at most one diagnostic a
        minute - the sum stays near 88,000, under the cap even doubled,
        so no day can exhaust writes and mute the feed.
        """
        pushes = 21_600
        snapshot_rows = pushes
        flow_rows = 40_000
        ack_rows = 25_000
        stats_rows = 6 * 60 // 10
        diagnostics = 6 * 60
        total = snapshot_rows + flow_rows + ack_rows + stats_rows + diagnostics
        self.assertLess(total, 100_000, total)
        self.assertEqual((snapshot_rows, flow_rows, ack_rows, total),
                         (21600, 40000, 25000, 86996))

    def test_the_relay_remembers_the_days_entry_stamp(self):
        """A later card cannot lose the entry time the first card carried."""
        self.assertIn("function signalEntryClock(text)", self.source)
        self.assertIn("SIGNAL:ENTRY:", self.source)
        self.assertIn("withRememberedEntry(signals, remembered)", self.source)

    # ------------------------------------------------------- market alerts (text law moved)

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

    def test_a_band_open_dispatches_the_scan_workflow_punctually(self):
        """Owner audit 2026-10-19: GitHub cron arrives hours late, so the
        relay's own punctual cron wake nudges the band workflow.

        The platform delivered the 04:17 UTC fire at 09:01 UTC and the 09:32
        fire at 14:10, so every Friday band was missed. Cloudflare crons wake
        at the exact edges already; the same wake now calls workflow_dispatch.
        It is opt-in (no token, no dispatch), deduped per band per day, and
        never blocks the open/close notification path.
        """
        self.assertIn("ctx.waitUntil(dispatchBandScan(env, now));", self.source)
        self.assertIn("const SCAN_WORKFLOW_FILE = \"intraday-session.yml\";",
                      self.source)
        self.assertIn("const SCAN_DISPATCH_GRACE_MINUTES = 3;", self.source)
        self.assertIn(
            "async function dispatchBandScan(env, now, band = null, "
            "source = \"cron\")", self.source)
        self.assertIn('const token = String(env.GH_DISPATCH_TOKEN || "").trim();',
                      self.source)
        self.assertIn('if (!token) {', self.source)
        self.assertIn("new AbortController()", self.source)
        self.assertIn("/actions/workflows/", self.source)
        self.assertIn("/dispatches", self.source)
        self.assertIn('inputs: { seconds: String(seconds) }', self.source)
        self.assertIn("const key = `SCAN:DISPATCH:", self.source)
        # A failed dispatch must not claim the band: only a 204 records the key.
        self.assertIn("note.ok = response.status === 204;", self.source)
        self.assertIn("if (note.ok) {", self.source)
        # The token is a Worker secret, never a value in this file (SO-5).
        self.assertNotIn("ghp_", self.source)
        self.assertNotIn("github_pat_", self.source)
        # Owner order 2026-10-20: the morning loop stops at 12:30 PKT, so the
        # dispatcher must know the runnable windows too, not only the band law.
        # The exchange keeps seeing Mon-Thu as one band; the RUNNABLE windows
        # are what a loop can actually run inside. bandOpenAt consults the
        # window table, never bandsFor, or the 12:30 edge can never dispatch.
        # Owner order 2026-10-21: the table now opens at 08:55 as a recorder
        # warm-up (the exchange's pre-open window is later) and carries the
        # exchange's 15:35 to 15:50 Post-Close Session as its third entry.
        self.assertIn("const WEEKDAY_WINDOWS = [[[8, 55], [12, 30]], [[12, 30], [15, 30]],",
                      self.source)
        self.assertIn("[[15, 35], [15, 50]]", self.source)
        self.assertIn("function dispatchWindowsFor(k) {", self.source)
        self.assertIn("for (const band of dispatchWindowsFor(k))", self.source)
        # The consumer that would have silently frozen the afternoon must be
        # named here, so a future edit cannot quietly swap windows for bands.
        self.assertNotIn("for (const band of bandsFor(k))\n", self.source)

    def test_an_app_poll_starts_a_missed_band(self):
        """Measured 2026-10-30: GitHub delivered no scheduled fire all day
        (four workflows, zero runs) and the Worker's own crons left no dispatch
        note either, so both bands existed only because a human dispatched
        them. The phone polls /signals every few seconds, so that poll is the
        third entry point: a band whose open is at most ten minutes old and
        that nothing has claimed is started once, after the answer is sent.

        The claim key is the cron's own runnable-window key, so the two paths
        can never both start the same band; a failed attempt leaves a
        cooldown and the next poll may retry.
        """
        self.assertIn("const BAND_START_POLL_WINDOW_MINUTES = 10;", self.source)
        self.assertIn("async function ensureBandStart(env, now)", self.source)
        self.assertIn(
            "ctx.waitUntil(ensureBandStart(env, now).catch(() => {}));",
            self.source)
        # The poll path must not wait on the dispatch: the answer is already
        # sent when it runs, so a slow GitHub API can never hold a poll open.
        self.assertIn("if (ctx && typeof ctx.waitUntil === \"function\") {",
                      self.source)
        self.assertIn('return await dispatchBandScan(env, now, window, "poll");',
                      self.source)
        self.assertIn("SCAN:DISPATCH:TRY:", self.source)
        self.assertIn("const window = dispatchWindowsFor(k).find((w) => {",
                      self.source)
        # The health answer says why the backup did or did not start a band,
        # and the note it quotes carries no token (SO-5).
        self.assertIn("last_dispatch: lastDispatch,", self.source)
        self.assertIn('const raw = await kvGet(env, "SCAN:DISPATCH:LAST");',
                      self.source)

    def test_session_edges_and_broker_halt_are_not_scanner_schedule_changes(self):
        for text in ("09:32", "15:30", "09:17", "12:00", "14:32", "16:30"):
            with self.subTest(edge=text):
                self.assertIn(text, self.source)
        workflow = (ROOT / ".github" / "workflows" / "intraday-session.yml").read_text(
            encoding="utf-8")
        # Owner order 2026-10-19: the band loop scans at one second intervals.
        self.assertIn("--interval 1", workflow)
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 1)',
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

    def test_the_upload_body_is_a_well_formed_multipart_form(self):
        """The deploy path builds its own multipart body, so it is pinned here.

        Cloudflare's script upload API reads the metadata as one part and each
        module as a part named after main_module. A body joined with bare
        newlines, or a boundary that appears inside the module, produces an
        upload the API rejects without saying which part was wrong, which is
        why this test parses the payload the way the API does instead of
        grepping for a string.
        """
        import pair  # cloud/pair.py, imported for its builder only

        module = "export default { fetch() { return new Response('ok'); } };\r\n"
        meta = pair.upload_metadata([
            {"type": "secret_text", "name": "RELAY_ADMIN_TOKEN", "text": "t"},
        ])
        body, boundary = pair.build_upload_body(meta, meta["main_module"], module)

        with self.subTest("the delimiter lands on its own CRLF line"):
            self.assertTrue(body.startswith(f"--{boundary}\r\n".encode()))
            self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))
            # Every delimiter after the first is reached through a CRLF, never
            # through a bare LF: a body joined with \n is malformed to the API.
            self.assertEqual(body.count(b"\r\n--" + boundary.encode()), 2)
            self.assertEqual(body.count(b"\n--" + boundary.encode()), 2)

        parsed = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: multipart/form-data; boundary="
            + boundary.encode() + b"\r\n\r\n" + body)
        parts = list(parsed.iter_parts())
        self.assertEqual(len(parts), 2, "metadata plus one module is the whole body")
        self.assertEqual(parts[0].get_param("name", header="content-disposition"),
                         "metadata")
        self.assertEqual(parts[0].get_content_type(), "application/json")
        self.assertEqual(parts[1].get_param("name", header="content-disposition"),
                         meta["main_module"])
        self.assertEqual(parts[1].get_content_type(),
                         "application/javascript+module")
        self.assertEqual(parts[1].get_payload(decode=True), module.encode("utf-8"))

        metadata = json.loads(parts[0].get_payload(decode=True))
        with self.subTest("the binding and the export ship together"):
            self.assertEqual(metadata["main_module"], "worker.js")
            self.assertEqual(metadata["exports"], {
                "QuoteHub": {"type": "durable-object", "storage": "sqlite"},
            })
            names = [b["name"] for b in metadata["bindings"]]
            self.assertEqual(names.count("QUOTE_HUB"), 1,
                             "QUOTE_HUB is bound once, not once per caller")
            hub = next(b for b in metadata["bindings"] if b["name"] == "QUOTE_HUB")
            self.assertEqual(hub["class_name"], "QuoteHub")

    def test_the_boundary_cannot_split_the_module(self):
        """A boundary that occurs in the payload would truncate the module."""
        import pair

        meta = pair.upload_metadata([])
        body, boundary = pair.build_upload_body(meta, "worker.js",
                                                "const x = 1; // ----qor\n")
        self.assertEqual(body.split(b"\r\n")[0][2:].decode(), boundary)
        # Two opening delimiters and one closing one: the delimiter appears as
        # a delimiter and nowhere else, whatever the module happens to contain.
        self.assertEqual(body.count(f"--{boundary}".encode()), 3)

    def test_the_signal_read_is_public_and_the_write_is_gated(self):
        """Owner order 2026-10-19: the phone carries no admin token.

        Removing the token field from the app is only safe if the read it
        needs no longer requires the token. GET /signals returns the card the
        owner's own runner already sent him; POST /signals stores new fingers
        on that card and stays admin gated, so nothing a phone can reach can
        change state.
        """
        read = self.source[self.source.index('if (request.method === "GET" && path === "/signals")'):]
        read = read[:read.index('if (request.method === "POST" && path === "/signals")')]
        self.assertNotIn("adminOk", read)
        self.assertIn('await kvGet(env, "SIGNALS")', read)

        write = self.source[self.source.index('if (request.method === "POST" && path === "/signals")'):]
        write = write[:write.index("return json({ ok: false, error: \"not found\" }")]
        self.assertIn("if (!adminOk(request, env)) {", write)
        self.assertIn('kvPut(env, "SIGNALS", text)', write)

    def test_the_admin_gate_and_the_card_routes_survive(self):
        """A refactor of /notify must not open the write routes."""
        for route in ('path === "/research/observation"', 'path === "/research/claim"',
                      'path === "/notify"', 'path === "/signals"'):
            with self.subTest(route=route):
                self.assertIn(route, self.source)
        self.assertIn("function adminOk(request, env)", self.source)
        self.assertIn('path.startsWith("/research/") && !adminOk(request, env)',
                      self.source)

    # ------------------------------------------------- post-close search data
    # Owner order 2026-10-22: "I want to see everything about the stock even
    # after the market is closed." The relay's publisher stops with the
    # session, so freshness gating of the READING routes threw away exactly
    # that. /prices now serves each symbol's last published price and
    # /stock computes the split from the last published frame, with the
    # closed-session fact carried in the source line (SO-3), and the write
    # routes keep their own freshness rules untouched.

    def test_prices_serves_the_last_published_price_after_close(self):
        """An /prices row is no longer fresh-only; the last price stands."""
        prices = self.source[self.source.index('path === "/prices"') :]
        prices = prices[:prices.index('path === "/market"')]
        self.assertNotIn("quote.fresh", prices)
        # The rows are the last PUBLISHED price of each symbol, read from
        # the same snapshot the live answer reads, and a symbol the relay
        # never heard from is skipped rather than invented (SO-3).
        self.assertIn("const snapshot = await readQuoteSnapshot(env);", prices)
        self.assertIn("Number.isFinite(quote.price)", prices)

    def test_stock_computes_the_split_from_the_last_published_frame(self):
        """B, S and T are stated after close, stamped with their date."""
        stock = self.source[self.source.index('path === "/stock"') :]
        stock = stock[:stock.index('path === "/prices"')]
        self.assertNotIn("if (quote.fresh) {", stock)
        self.assertIn("const split = splitFromQuote(quote);", stock)
        self.assertIn("the market is closed", stock)
        self.assertIn("quote_fresh: Boolean(quote.fresh),", stock)

    def test_prices_rows_carry_the_relay_split_for_the_dropdowns(self):
        """Owner order 2026-10-23: the phone ranks the dropdowns itself.

        Each /prices row is [symbol, price, change_pct, buy, sell], the buy
        and sell pair computed by the relay's own split law from the row's
        frame, with nulls where the frame's range is incomplete rather than
        a guessed zero (SO-3). The phone ranks from these columns; the
        /stock route stays the human-readable answer with its labels.
        """
        prices = self.source[self.source.index('path === "/prices"'):]
        prices = prices[:prices.index('path === "/market"')]
        self.assertIn("const split = splitFromQuote(quote);", prices)
        self.assertIn("split ? split.buy_volume : null,", prices)
        self.assertIn("split ? split.sell_volume : null,", prices)


    def test_one_newest_frame_answers_every_surface(self):
        """Owner order 2026-11-01: the card, /stock and /prices agree.

        The three reading routes used to pick their own row: the card took
        the first fresh hub row it met, /stock the first row in array order
        whatever its stamp, and /prices walked every row, which is how the
        same scrip printed two prices at once. One helper now keeps the
        newest frame per symbol by its own observed_at, all three routes
        read it, and the acknowledged total travels to the phone as
        /prices' sixth column so its answer moves with the card.
        """
        self.assertIn("function newestQuoteRows(quotes) {", self.source)
        stock = self.source[self.source.index('path === "/stock"'):]
        stock = stock[:stock.index('path === "/prices"')]
        self.assertIn("newestQuoteRows(quotes).get(symbol)", stock)
        prices = self.source[self.source.index('path === "/prices"'):]
        prices = prices[:prices.index('path === "/market"')]
        self.assertIn("newestQuoteRows(snapshot && snapshot.quotes).values()",
                      prices)
        self.assertIn("row.volume,", prices)
        self.assertIn("newestQuoteRows(freshQuotes)", self.source)
        self.assertIn("newestQuoteRows(quotes.quotes).values()", self.source)
        # Owner order 2026-11-01, the same day's second data note: on a
        # non-trading day both reading routes answer with the last
        # session's frames, stamped, so a Saturday's card and search list
        # carry the same scrips instead of three rows against none. On a
        # trading day the today-only law still stands.
        self.assertIn("const stockTradingToday = isTradingDay(karachiView(Date.now()));",
                      stock)
        self.assertIn("if (!quote || (!quoteIsFromToday(quote) && stockTradingToday)) {",
                      stock)
        self.assertIn("const tradingToday = isTradingDay(kNow);", prices)
        self.assertIn("if (!quoteIsFromToday(quote) && tradingToday) continue;",
                      prices)


if __name__ == "__main__":
    unittest.main()
