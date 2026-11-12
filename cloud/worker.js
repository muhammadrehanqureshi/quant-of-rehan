// quant-of-rehan relay, deployed on the Cloudflare edge.
//
// Owner order 2026-10-29: the owner removed his chat account and bot, so
// no chat app is a channel of this system. Notifications travel as
// owner email (src/notify/owner_email.py) from the GitHub Actions jobs, and
// every chat route, binding and send call is removed from this worker.
// What remains here is the app's card, market state, snapshot and status
// surface.
//
// SO-8: the daily open/close schedule here is computed from a fixed UTC+5
// offset (Karachi has had no daylight saving since 1971). It never uses the
// container clock zone and never any other timezone.
//
// SO-5: secrets live in worker bindings only, never in this file, never in
// the repo:
//   RELAY_ADMIN_TOKEN   gates the write routes against strangers
//
// Endpoints:
//   GET  /health        liveness, current Karachi clock, next scheduled event,
//                       and market_open per the owner's session law
//   GET  /market        public: KSE100 points and percentage plus the top
//                       three stocks by current session volume with their
//                       labelled buy/sell split, served from a five minute
//                       cache of the PSX Data Portal
//   POST /market        admin only: store a snapshot built by the local runner
//                       (src/data/market_snapshot.py), which takes precedence
//                       over the edge's own cache for five minutes
//   POST /notify        retired: answers 410. Notifications travel as owner
//                       email from the Actions jobs.
//
// Cron triggers (UTC, set from cloud/). Friday is TWO sessions with
// the exchange's midday break between them, so it has four edges:
//   04:32 Mon-Thu = 09:32 PKT open  | 10:30 Mon-Thu = 15:30 PKT close
//   04:17 Fri     = 09:17 PKT open  | 07:00 Fri     = 12:00 PKT close
//   09:32 Fri     = 14:32 PKT open  | 11:30 Fri     = 16:30 PKT close

const KARACHI_OFFSET_MIN = 5 * 60; // SO-8: UTC+5, fixed forever

// ------------------------------------------------------ the relay's state
//
// Owner report, 2026-10-19: "KV daily limit reached 50% today". Measured
// against that email: the free plan allows about 100,000 KV reads and 1,000
// writes a day, the phone polls once a second while a session is live, and a
// single /health poll read three separate keys, so five or six reads a second
// is roughly half the allowance by early afternoon.
//
// Owner decision, 2026-10-20: no product that mails a quota warning is
// acceptable, so the relay does not use KV at all any more. Every stored value
// (the card, the market snapshot, the session state, pairing codes, the
// research log) lives in the Durable Object the relay already needed for live
// quotes, whose storage is not metered per write the way KV is. KV was also the
// reason the deploy refused to run from 2026-10-19 onwards: its namespace had
// gone, and a binding to a missing namespace fails the whole upload.
//
// The isolate memo stays, because a value that changes on a market edge does
// not need re-reading on every one-second poll. Writes go through the same map,
// so a change is never hidden behind a stale entry.
const KV_MEMO_TTL_MS = 10000;
const kvMemo = new Map();
// Owner order 2026-11-05 (seventh pass, "for the last two days I have been
// hitting limit almost 3 hours before the market closing, make sure
// cloudflare doesn't ever hit it's daily limit"): Workers Free allows
// 100,000 Durable Object requests a day. One phone tick used to cost five
// of them (snapshot, ACK read, ACK write, transition, W/L), so one phone
// and the one-second scanner reached the cap by mid afternoon. Every read
// now shares a short memory of its own and no polled read route writes an
// ACK row: a tick costs one snapshot read at most.
const SNAPSHOT_MEMO_MS = 1000;
const ACK_MEMO_MS = 30000;
const TRANSITION_MEMO_MS = 20000;
const WINLOSS_MEMO_MS = 30000;
let snapshotMemo = { at: 0, value: null };
let ackMemo = { day: "", at: 0, rows: null };
let transitionMemo = { at: 0, value: null };
let winLossMemo = { at: 0, value: null };
// A chart redraw is not a new question: the same symbol, day and limit
// answered within five seconds is served from this isolate's own memory, so a
// desktop repainting a candle cannot spend the Durable Objects request budget
// on every frame.
const HISTORY_MEMO_MS = 5000;
const HISTORY_MEMO_MAX = 32;
let historyMemo = new Map();
const BARS_MEMO_MS = 5000;
let barsMemo = new Map();
const STATE_HUB_NAME = "psx-live-quotes";
// The quote view and the relay's key-value state used to share one Durable
// Object instance. A deployed class change does not restart an instance that
// the one-second feed never lets go idle, so the quote view moved to its own
// instance name on 2026-11-04. The new instance adopts the capture's observed
// full-day pair on its first push; the state hub keeps the existing card,
// signals and ACK rows untouched.
// Owner order 2026-11-07: the OHLC history endpoint adds a table and its
// aggregation to this class, and a deployed class change still does not
// restart an object that the one-second feed never lets go idle. The quote
// view therefore moved to v4 so the new code actually loads. The flow state
// re-seeds from the capture's own measured pair on the first push, exactly
// as it did when v3 was introduced.
const QUOTE_HUB_NAME = "psx-live-quotes-v4";

function stateHub(env) {
  const namespace = env.QUOTE_HUB;
  if (!namespace || typeof namespace.idFromName !== "function") return null;
  return namespace.get(namespace.idFromName(STATE_HUB_NAME));
}

function quoteHub(env) {
  const namespace = env.QUOTE_HUB;
  if (!namespace || typeof namespace.idFromName !== "function") return null;
  return namespace.get(namespace.idFromName(QUOTE_HUB_NAME));
}

async function quoteHubCall(env, path, init) {
  const hub = quoteHub(env);
  if (!hub) return null;
  const response = await hub.fetch("https://quote-hub" + path, init);
  if (!response.ok) throw new Error("quote hub answered " + response.status);
  return response.json();
}

async function quoteHubValue(env, key) {
  try {
    const answer = await quoteHubCall(env,
      "/state?key=" + encodeURIComponent(key));
    return answer && answer.ok ? answer.value : null;
  } catch (_) {
    return null;
  }
}

// A KV binding, when one happens to be present, is only a fallback: the local
// worker harness in tools/worker_check.py has no Durable Object, and a deploy
// that still binds KV must keep answering.
function stateFallback(env) {
  const kv = env.RELAY_KV;
  return kv && typeof kv.get === "function" ? kv : null;
}

async function stateCall(env, path, init) {
  const hub = stateHub(env);
  if (!hub) return null;
  const response = await hub.fetch("https://quote-hub" + path, init);
  if (!response.ok) throw new Error("state store answered " + response.status);
  return response.json();
}

async function relayRead(env, key) {
  try {
    const answer = await stateCall(env, "/state?key=" + encodeURIComponent(key));
    if (answer) return answer.ok ? answer.value : null;
  } catch (error) {
    if (!stateFallback(env)) throw error;
  }
  const kv = stateFallback(env);
  return kv ? kv.get(key) : null;
}

async function relayWrite(env, key, value, options) {
  const ttl = options && Number(options.expirationTtl);
  try {
    const answer = await stateCall(env, "/state", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        key, value, expirationTtl: Number.isFinite(ttl) ? ttl : null,
      }),
    });
    if (answer) return;
  } catch (error) {
    if (!stateFallback(env)) throw error;
  }
  const kv = stateFallback(env);
  if (kv) await kv.put(key, value, options);
}

async function relayDelete(env, key) {
  try {
    const answer = await stateCall(env, "/state?key=" + encodeURIComponent(key),
      { method: "DELETE" });
    if (answer) return;
  } catch (error) {
    if (!stateFallback(env)) throw error;
  }
  const kv = stateFallback(env);
  if (kv) await kv.delete(key);
}

async function relayList(env, prefix, limit) {
  try {
    const answer = await stateCall(env, "/state/list?prefix="
      + encodeURIComponent(prefix) + "&limit=" + limit);
    if (answer) {
      return { keys: answer.keys || [], list_complete: Boolean(answer.list_complete) };
    }
  } catch (error) {
    if (!stateFallback(env)) throw error;
  }
  const kv = stateFallback(env);
  if (!kv) return { keys: [], list_complete: true };
  const listed = await kv.list({ prefix, limit });
  const keys = [];
  for (const item of listed.keys) {
    keys.push({ name: item.name, value: await kv.get(item.name) });
  }
  return { keys, list_complete: Boolean(listed.list_complete) };
}

async function kvGet(env, key, ttlMs = KV_MEMO_TTL_MS) {
  const now = Date.now();
  const hit = kvMemo.get(key);
  if (hit && now - hit.at <= ttlMs) return hit.value;
  const value = await relayRead(env, key);
  kvMemo.set(key, { at: now, value });
  return value;
}

async function kvPut(env, key, value, options) {
  await relayWrite(env, key, value, options);
  kvMemo.set(key, { at: Date.now(), value });
}

async function kvDelete(env, key) {
  await relayDelete(env, key);
  kvMemo.delete(key);
}

// The signal card is the one place the entry stamp is written, and a later
// daily-lock card can be stored without it. Remember the stamp beside the
// card, keyed by the card's own session date, so every read of that day's
// card can put it back even after the phone restarts.
function signalDay(text) {
  const match = String(text || "").match(/\b(\d{4}-\d{2}-\d{2})\b/);
  return match ? match[1] : null;
}

function signalEntryClock(text) {
  const match = String(text || "").match(
    /\bentry\s*time\s*:\s*(\d{1,2}:\d{2}(?::\d{2})?)/i,
  );
  return match ? match[1] : null;
}

function withRememberedEntry(text, entry) {
  if (!text || !entry || signalEntryClock(text)) return text;
  const trimmed = text.replace(/\s+$/, "");
  const stop = /[.!?]$/.test(trimmed) ? "" : ".";
  return `${trimmed}${stop} Entry time: ${entry} PKT.`;
}

// -- Owner order 2026-10-31, extended 2026-11-02: a new home tile,
// "W/L = W/L RATE", reads from TWO authorities the relay already
// stores: the finalized session records the capture pipeline banks
// (RESEARCH:OUTCOME:<date>, POST /research/outcome) and the hit-time
// close ledger the runner banks the moment a stop or target closes the
// paper trade (RESEARCH:CLOSE:<date>, POST /research/close). The field
// is `outcome`, named by src/signals/trade_state.py and
// scripts/intraday_pipeline.py's own run_finalize, and its closed-trade
// values are TARGET_HIT, STOP_HIT, STOP_AMBIGUOUS and
// CLOSED_AT_SESSION_END; NO_CANDIDATE, UNVERIFIABLE and a pending
// record carry no finite net_return and count nothing. The ledgers
// overlap by date, so winLossFromSessions keys by date and the
// finalized record wins. PRL 2026-10-30 is finalized STOP_HIT and
// CNERGY 2026-11-02 closed at its stop, so the answer is 0/2 = 100%.
// The tile asks ONE question, so the relay answers it as ONE object,
// shaped once, in one place:
//   wins   = closed trades whose outcome is TARGET_HIT: the take profit
//            was reached (owner order 2026-11-05: only a TP hit is a W)
//   losses = every other closed trade, however the day itself ended
//   closed = wins + losses (both zero means the rate is not computable)
//   rate_pct = losing share of the CLOSED total, rounded
const TRADE_OUTCOME_LABELS = new Set([
  "TARGET_HIT", "STOP_HIT", "STOP_AMBIGUOUS", "CLOSED_AT_SESSION_END",
]);

function winLossFromSessions(sessions) {
  const byDate = new Map();
  for (const session of sessions) {
    const label = String((session && session.outcome) || "").toUpperCase();
    if (!TRADE_OUTCOME_LABELS.has(label)) continue;
    const net = Number(session.net_return);
    if (!Number.isFinite(net)) continue;
    const day = String((session && (session.date || session.day)) || "");
    const key = day || `${(session && session.symbol) || ""}|${label}|${net}`;
    // Owner order 2026-11-05 (fifth pass, "what signal hit TP that you
    // made it the winner?"): only a call that reached its take profit is
    // a W. Every other closed trade is an L, however the day itself ended.
    byDate.set(key, label === "TARGET_HIT" && net > 0 ? "win" : "loss");
  }
  let wins = 0, losses = 0;
  for (const result of byDate.values()) {
    if (result === "win") wins += 1; else losses += 1;
  }
  return { wins, losses };
}

// The phone re-asks /market every second, so the ledger is read out of a
// 5-minute cache row (RESEARCH:WINLOSS) and only recomputed when that row
// is absent or expired. A cold or failing store never fabricates a rate:
// it answers zeros with a null rate and no closed rows (SO-3).
const WINLOSS_CACHE_SECONDS = 300;

async function winLossSnapshot(env) {
  // Owner order 2026-11-05 (the daily Durable Object budget): the W/L row
  // changes when a trade closes, not every second, so half a minute of
  // memory keeps the per-poll state read off the budget entirely.
  const stamp = Date.now();
  if (winLossMemo.value && stamp - winLossMemo.at < WINLOSS_MEMO_MS) {
    return winLossMemo.value;
  }
  const cached = await relayRead(env, "RESEARCH:WINLOSS");
  if (cached) {
    try {
      const row = JSON.parse(cached);
      const at = Date.parse(String(row.computed_at || ""));
      if (Number.isFinite(at) &&
          Date.now() - at < WINLOSS_CACHE_SECONDS * 1000) {
        winLossMemo = { at: stamp, value: row };
        return row;
      }
    } catch (_) { /* stale row: recompute */ }
  }
  const listed = await relayList(env, "RESEARCH:OUTCOME:", 1000);
  const closed = await relayList(env, "RESEARCH:CLOSE:", 1000);
  const sessions = [];
  for (const source of [closed, listed]) {
    for (const item of source.keys) {
      if (!item.value || typeof item.value !== "string") continue;
      try {
        const row = JSON.parse(item.value);
        if (Array.isArray(row && row.sessions)) sessions.push(...row.sessions);
      } catch (_) { /* unreadable row: never counted */ }
    }
  }
  const { wins, losses } = winLossFromSessions(sessions);
  const total = wins + losses;
  const row = {
    computed_at: new Date().toISOString(),
    wins,
    losses,
    closed: total,
    rate_pct: total > 0 ? Math.round((losses / total) * 100) : null,
  };
  await kvPut(env, "RESEARCH:WINLOSS", JSON.stringify(row),
    { expirationTtl: WINLOSS_CACHE_SECONDS * 2 });
  winLossMemo = { at: Date.now(), value: row };
  return row;
}

// The /market answer grafts the W/L block in, best effort: a research store
// that is cold or mid-refresh never fails the market card; it just leaves
// win_loss out of that one answer so the app falls back to its waiting text.
async function marketWinLoss(env) {
  try {
    return await winLossSnapshot(env);
  } catch (_) {
    return null;
  }
}

const QUOTE_HUB_SOCKET_TAG = "live-quotes";
// Owner's exact condition texts (order of 2026-10-11), mirroring
// src/data/sessions.py. The break sentence is for the exchange's own Friday
// midday break and nothing else.
const CONDITION_BREAK = "Market is on a break right now.";
const CONDITION_CLOSED = "Market is closed right now.";
const MARKET_STATUS_MAX_AGE_MS = 90 * 1000;
const MARKET_OPEN_GRACE_MS = 5 * 60 * 1000;
const MARKET_STATE_KEY = "MARKET:LAST_CONFIRMED_STATE";
// Owner report 2026-10-20 (14:07 PKT): quotes older than half a minute
// read as "numbers frozen" on the phone, so a per-second publisher makes a
// 30 second window honest and a stale row a real degradation signal.
const QUOTE_MAX_AGE_MS = 30 * 1000;
const QUOTE_MAX_SYMBOLS = 600;
const QUOTE_MAX_BODY_BYTES = 256 * 1024;

// PSX trading holidays 2026; mirrors src/data/sessions.py. Refresh yearly.
const PSX_HOLIDAYS_2026 = new Set([
  "2026-02-05", "2026-03-21", "2026-03-23", "2026-05-01", "2026-05-27",
  "2026-05-28", "2026-06-25", "2026-06-26", "2026-08-14", "2026-08-25",
  "2026-11-09", "2026-12-25",
]);

function pad(n) {
  return String(n).padStart(2, "0");
}

// A Date shifted so its UTC fields read as Karachi wall clock.
function karachiView(instantMs) {
  return new Date(instantMs + KARACHI_OFFSET_MIN * 60 * 1000);
}

function dayStamp(d) {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

function hhmm(d) {
  return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

function isTradingDay(k) {
  const wd = k.getUTCDay();
  if (wd === 0 || wd === 6) return false;
  return !PSX_HOLIDAYS_2026.has(dayStamp(k));
}

// Owner's session law (SO-8), mirroring src/data/sessions.py exactly.
// Monday to Thursday is ONE band; Friday is TWO, with the exchange's real
// midday break between them (09:17-12:00 and 14:32-16:30). Before this the
// worker treated Friday as one continuous 09:17-16:30 session, so /health
// answered market_open true at 14:23 while the exchange was shut.
// A parity test (tests/test_session_law_parity.py) fails if this table and
// the Python one ever drift.
const WEEKDAY_BANDS = [[[9, 32], [15, 30]]];
const FRIDAY_BANDS = [[[9, 17], [12, 0]], [[14, 32], [16, 30]]];

function bandsFor(k) {
  if (!isTradingDay(k)) return [];
  return k.getUTCDay() === 5 ? FRIDAY_BANDS : WEEKDAY_BANDS;
}

// The RUNNABLE windows, not the band law. The session loop
// (intraday-session.yml) is one job per window, and its window close is
// 12:30 PKT
// on Mon-Thu, so a loop started at the 09:32 open stops at 12:30 and the
// afternoon had no publisher at all (measured 2026-10-20: /quotes froze
// from 12:30 PKT while the exchange traded). The dispatcher therefore
// needs its own window open edges, one per job the workflow could run.
// marketPhase, /health and the phone texts keep reading bandsFor, whose
// parity with src/data/sessions.py is tested.
// Owner order 2026-10-21: the pre-open and post-market windows are LIVE scan
// windows too (banking broker ticks at one second). Owner order 2026-11-12
// (latest): the first dispatch is 09:00 PKT, on Mon-Thu and Friday, the same
// 09:00 the Windows build names in front of SCANNING; it was 08:55. That
// dispatch and the 14:10 PKT Friday one start the capture, not a pre-market
// trade, while the scanner itself waits for the exchange's published
// pre-open window (Mon-Thu 09:15 to 09:30, Friday 09:00 to 09:15 and 14:15 to
// 14:30). The third window is the quant's scanning window: it opens at 15:32
// (16:32 on Friday) and runs to the feed's last post-close print, 15:49 Monday
// to Thursday and 16:49 on Friday (owner order 2026-11-12). The pre and post
// market volume is captured to the last minute of that window.
const WEEKDAY_WINDOWS = [[[9, 0], [12, 30]], [[12, 30], [15, 30]],
                         [[15, 32], [15, 49]]];

const FRIDAY_WINDOWS = [[[9, 0], [12, 30]], [[14, 10], [16, 30]],
                        [[16, 32], [16, 49]]];

function dispatchWindowsFor(k) {
  if (!isTradingDay(k)) return [];
  return k.getUTCDay() === 5 ? FRIDAY_WINDOWS : WEEKDAY_WINDOWS;
}

function minutesOf(k) {
  return k.getUTCHours() * 60 + k.getUTCMinutes();
}

function hmText(hm) {
  return `${pad(hm[0])}:${pad(hm[1])}`;
}

function bandsText(k) {
  const bands = bandsFor(k);
  if (!bands.length) return "closed (weekend or PSX holiday)";
  return bands.map((b) => `${hmText(b[0])}-${hmText(b[1])}`).join(", ");
}

// Punctual band dispatch (owner audit, 2026-10-19).
//
// GitHub's cron queue delivers schedule events hours late in busy periods:
// measured on this repository on 2026-10-16, the 04:17 UTC band job was
// created at 09:01 UTC and the Friday afternoon job at 14:10 UTC, so every
// band that day was missed and the jobs woke to a shut market. Cloudflare's
// cron triggers already wake at the exact band edges for the open and close
// texts, so the same wake now nudges the GitHub workflow: a workflow_dispatch
// starts in seconds instead of hours, and the scheduled triggers stay as the
// fallback if this token is not configured or GitHub answers with an error.
//
// It is strictly opt-in. With no GH_DISPATCH_TOKEN binding this function does
// nothing and the relay behaves exactly as before. The token is a fine grained
// GitHub PAT with Actions: write on this one repository, set as a Worker
// secret (never in the repo, SO-5). One dispatch per window per day is
// recorded in KV, so a retried cron can never start a second loop for the
// same edge.
const SCAN_WORKFLOW_FILE = "intraday-session.yml";
const SCAN_REPO_DEFAULT = "muhammadrehanqureshi/quant-of-rehan";
const SCAN_DISPATCH_GRACE_MINUTES = 3;
const SCAN_DISPATCH_TIMEOUT_MS = 10000;

/** The runnable window whose open edge this wake is standing on, or null. */
function bandOpenAt(k) {
  const mins = minutesOf(k);
  for (const band of dispatchWindowsFor(k)) {
    const open = band[0][0] * 60 + band[0][1];
    if (mins >= open && mins - open <= SCAN_DISPATCH_GRACE_MINUTES) {
      return band;
    }
  }
  return null;
}

// The pillow under BOTH schedulers. Measured 2026-10-30: GitHub dropped
// every scheduled workflow that day and the Worker's own crons left no
// dispatch note either, so both bands depended on a human dispatch. The app
// polls /signals every few seconds while the owner watches, and the Watcher
// polls in the background, so that poll becomes the third entry point: if a
// band opened in the last ten minutes and nothing has claimed it, one poll
// starts the band. Responses never wait on it (waitUntil), and the claim /
// cooldown keys mean a band is attempted once per ten minutes at most.
const BAND_START_POLL_WINDOW_MINUTES = 10;

async function ensureBandStart(env, now) {
  const k = karachiView(now.getTime());
  const mins = minutesOf(k);
  for (const band of bandsFor(k)) {
    const open = band[0][0] * 60 + band[0][1];
    const close = band[1][0] * 60 + band[1][1];
    if (mins <= open || mins - open > BAND_START_POLL_WINDOW_MINUTES) continue;
    if (mins >= close - 2) continue;
    // The claim key must be the one a cron would write, so a band started by
    // a poll and a band started by the edge can never run twice. The cron
    // names the RUNNABLE window (Mon-Thu 09:00-12:30, 12:30-15:30), which on
    // the morning band opens before the band itself.
    const window = dispatchWindowsFor(k).find((w) => {
      const wOpen = w[0][0] * 60 + w[0][1];
      const wClose = w[1][0] * 60 + w[1][1];
      return wOpen <= open && open < wClose;
    }) || band;
    const claimed = `SCAN:DISPATCH:${dayStamp(k)}:${hmText(window[0])}`;
    if (await relayRead(env, claimed)) {
      return { dispatched: false, reason: "already dispatched" };
    }
    const cooldown = `SCAN:DISPATCH:TRY:${dayStamp(k)}:${hmText(window[0])}`;
    if (await relayRead(env, cooldown)) {
      return { dispatched: false, reason: "cooldown" };
    }
    try {
      await kvPut(env, cooldown, String(now.getTime()),
        { expirationTtl: BAND_START_POLL_WINDOW_MINUTES * 60 });
    } catch (_) {
      // The cooldown is a courtesy; a failed write must not block a band.
    }
    return await dispatchBandScan(env, now, window, "poll");
  }
  // Owner order 2026-11-05 ("always update the signal at the end of the
  // day whether it's winning or losing"): the post-close finalize windows
  // (Mon-Thu 15:32 to 15:49, Friday 16:32 to 16:49) sit OUTSIDE bandsFor,
  // so the pillow above could never start one - the day's paper trade
  // waited on GitHub's cron, and when GitHub drops schedules the day's W
  // or L never lands (GLAXO 2026-11-04 is that defect). These windows get
  // the same pillow as the bands: a poll inside the window claims it with
  // the same key an edge cron writes, so every path names ONE dispatch
  // for the window and the finalize can never run twice.
  const lastBandClose = (() => {
    const bands = bandsFor(k);
    if (!bands.length) return null;
    const last = bands[bands.length - 1][1];
    return last[0] * 60 + last[1];
  })();
  if (lastBandClose !== null) {
    for (const window of dispatchWindowsFor(k)) {
      const open = window[0][0] * 60 + window[0][1];
      if (open < lastBandClose) continue; // a band open edge: handled above
      if (mins <= open || mins - open > BAND_START_POLL_WINDOW_MINUTES) {
        continue;
      }
      const claimed = `SCAN:DISPATCH:${dayStamp(k)}:${hmText(window[0])}`;
      if (await readOrNull(env, claimed)) {
        return { dispatched: false, reason: "already dispatched" };
      }
      const cooldown = `SCAN:DISPATCH:TRY:${dayStamp(k)}:${hmText(window[0])}`;
      if (await readOrNull(env, cooldown)) {
        return { dispatched: false, reason: "cooldown" };
      }
      try {
        await kvPut(env, cooldown, String(now.getTime()),
          { expirationTtl: BAND_START_POLL_WINDOW_MINUTES * 60 });
      } catch (_) {
        // The cooldown is a courtesy; a failed write must not block a band.
      }
      return await dispatchBandScan(env, now, window, "poll");
    }
  }
  return { dispatched: false, reason: "no band open" };
}

// Owner order 2026-11-05: a dispatch never dies on a store read. The
// claim checks must answer on the error path too - a refused read means
// "unclaimed", and the dispatch attempt goes out as if the key were
// free, because a dropped finalize is exactly the defect that left
// GLAXO 2026-11-04 unbilled.
async function readOrNull(env, key) {
  try {
    return await relayRead(env, key);
  } catch (_) {
    return null;
  }
}

async function recordDispatch(env, note) {
  try {
    await kvPut(env, "SCAN:DISPATCH:LAST", JSON.stringify(note),
      { expirationTtl: 7 * 86400 });
  } catch (_) {
    // KV is best effort here: the state of a dispatch must never fail a cron.
  }
}

async function dispatchBandScan(env, now, band = null, source = "cron", options = {}) {
  const k = karachiView(now.getTime());
  band = band || bandOpenAt(k);
  if (!band) return { dispatched: false, reason: "not a band open" };

  const token = String(env.GH_DISPATCH_TOKEN || "").trim();
  if (!token) {
    // Opt-in: without the secret the scheduled trigger is the only path.
    return { dispatched: false, reason: "GH_DISPATCH_TOKEN is not set" };
  }

  const key = `SCAN:DISPATCH:${dayStamp(k)}:${hmText(band[0])}`;
  const seen = await readOrNull(env, key);
  // Once a band is claimed, a second start is refused: that is what stops two
  // loops running the same window. The watchdog is the one caller allowed to
  // force a start, because a claimed band whose capture has died is exactly
  // the case the claim cannot see.
  if (seen && !options.force) {
    return { dispatched: false, reason: "already dispatched" };
  }

  const close = band[1][0] * 60 + band[1][1];
  const seconds = Math.max(60, (close - minutesOf(k)) * 60);
  const repo = String(env.GH_REPO || SCAN_REPO_DEFAULT).trim();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SCAN_DISPATCH_TIMEOUT_MS);
  const note = { at: new Date().toISOString(), band: hmText(band[0]),
    source, repo, seconds, ok: false, status: 0, detail: "" };
  try {
    const response = await fetch(
      `https://api.github.com/repos/${repo}/actions/workflows/`
        + `${SCAN_WORKFLOW_FILE}/dispatches`,
      {
        method: "POST",
        signal: controller.signal,
        headers: {
          authorization: `Bearer ${token}`,
          accept: "application/vnd.github+json",
          "x-github-api-version": "2022-11-28",
          "user-agent": "quant-of-rehan-relay",
        },
        body: JSON.stringify({ ref: "master", inputs: { seconds: String(seconds) } }),
      },
    );
    note.status = response.status;
    note.ok = response.status === 204;
    if (!note.ok) {
      note.detail = (await response.text().catch(() => "")).slice(0, 300);
    }
  } catch (error) {
    note.detail = String((error && error.name) || error).slice(0, 120);
  } finally {
    clearTimeout(timer);
  }

  if (note.ok) {
    // Only a confirmed dispatch claims the band, so a failed attempt leaves
    // the key free for the fallback paths and for an operator retry.
    await kvPut(env, key, note.at, { expirationTtl: 2 * 86400 });
  }
  await recordDispatch(env, note);
  return { dispatched: note.ok, reason: note.ok ? "dispatched" : note.detail,
    status: note.status };
}

// Owner order 2026-11-09: a capture that stops inside an open window must not
// throw the rest of the day into U. Measured on the live relay on 2026-11-06
// (Friday): the hub's newest frame was 12:09 PKT while the exchange traded to
// 16:30, and 148,036,924 of that day's 240,850,912 shares, 61 percent, could
// only be reported as unclassified. The once-per-window claim stops a band
// starting twice; it cannot see a band whose capture has died. This watchdog
// reads the hub's own newest frame and, when it has gone stale inside a live
// window, dispatches the band scan again under a cooldown of its own.
const FEED_WATCHDOG_STALE_MS = 5 * 60 * 1000;
const FEED_WATCHDOG_COOLDOWN_MS = 10 * 60 * 1000;
// A band open is the edge dispatcher's own job. This watchdog runs in the
// same cron wake and the new band has not published a frame yet, so without
// this guard it read yesterday's frame as stale and forced a second loop.
const FEED_WATCHDOG_OPEN_GUARD_MINUTES = 3;
// A dispatch younger than this is still starting. The pre-open auction can
// be quiet, so a stale frame alone is not evidence that the band is dead
// until this grace has passed.
const FEED_WATCHDOG_DISPATCH_GRACE_MS = 10 * 60 * 1000;

// Milliseconds since the newest frame the hub holds was observed, or null when
// the hub holds no stamped frame at all (which counts as stale).
function newestFrameAgeMs(snapshot, now) {
  let newest = 0;
  for (const quote of newestQuoteRows(snapshot && snapshot.quotes).values()) {
    const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
    if (Number.isFinite(at) && at > newest) newest = at;
  }
  if (!newest) return null;
  return Math.max(0, now.getTime() - newest);
}

// A queued run is in flight too. GitHub keeps one pending run per concurrency
// group: a dispatch that lands while the 08:55 band is queued cancels that
// band and replaces it with a later one, which is how a retry storm skips the
// pre-open it was meant to save. Ask GitHub before forcing another loop.
// Only the watchdog calls this, only when the feed is stale, and the caller's
// ten minute cooldown keeps it to one pair of reads per window.
async function bandRunInFlight(env) {
  const token = String(env.GH_DISPATCH_TOKEN || "").trim();
  if (!token) return false;
  const repo = String(env.GH_REPO || SCAN_REPO_DEFAULT).trim();
  for (const status of ("in_progress", "queued")) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), SCAN_DISPATCH_TIMEOUT_MS);
    try {
      const response = await fetch(
        `https://api.github.com/repos/${repo}/actions/workflows/`
          + `${SCAN_WORKFLOW_FILE}/runs?status=${status}&per_page=1`,
        {
          signal: controller.signal,
          headers: {
            authorization: `Bearer ${token}`,
            accept: "application/vnd.github+json",
            "x-github-api-version": "2022-11-28",
            "user-agent": "quant-of-rehan-relay",
          },
        },
      );
      if (!response.ok) continue;
      const answer = await response.json();
      if (Number((answer && answer.total_count) || 0) > 0) return true;
    } catch (_) {
      // A failed read is not evidence that no band is running. The fresh
      // dispatch grace above still covers the ordinary case.
    } finally {
      clearTimeout(timer);
    }
  }
  return false;
}

async function ensureFeedAlive(env, now) {
  const k = karachiView(now.getTime());
  if (!isTradingDay(k)) return { dispatched: false, reason: "not a trading day" };
  const mins = minutesOf(k);
  const open = dispatchWindowsFor(k).filter((w) => {
    const from = w[0][0] * 60 + w[0][1];
    const to = w[1][0] * 60 + w[1][1];
    return mins >= from && mins < to;
  });
  if (!open.length) return { dispatched: false, reason: "no window open" };
  const window = open[open.length - 1];
  const windowOpen = window[0][0] * 60 + window[0][1];
  if (mins - windowOpen <= FEED_WATCHDOG_OPEN_GUARD_MINUTES) {
    return { dispatched: false, reason: "band just opened" };
  }
  // The cooldown is read first so a poll in a live window costs one KV read,
  // not a snapshot read, while nothing is wrong.
  const key = `SCAN:WATCHDOG:${dayStamp(k)}:${hmText(window[0])}`;
  const last = Number((await readOrNull(env, key)) || 0);
  if (last && now.getTime() - last < FEED_WATCHDOG_COOLDOWN_MS) {
    return { dispatched: false, reason: "watchdog cooldown" };
  }
  let snapshot = null;
  try {
    snapshot = await readQuoteSnapshot(env);
  } catch (_) {
    snapshot = null;
  }
  const age = newestFrameAgeMs(snapshot, now);
  if (age !== null && age < FEED_WATCHDOG_STALE_MS) {
    return { dispatched: false, reason: "feed is live",
      age_seconds: Math.round(age / 1000) };
  }
  // A dispatch that is ten minutes old has had time to start its recorder.
  // Do not queue a second loop on top of it; an old dispatch with a stale
  // feed is the case this watchdog exists for.
  const claim = await readOrNull(
    env, `SCAN:DISPATCH:${dayStamp(k)}:${hmText(window[0])}`);
  const claimedAt = Date.parse(String(claim || ""));
  if (Number.isFinite(claimedAt)
      && now.getTime() - claimedAt < FEED_WATCHDOG_DISPATCH_GRACE_MS) {
    return { dispatched: false, reason: "dispatch is fresh" };
  }
  try {
    await kvPut(env, key, String(now.getTime()), { expirationTtl: 6 * 3600 });
  } catch (_) {
    // A failed cooldown write must never withhold the dispatch.
  }
  if (await bandRunInFlight(env)) {
    return { dispatched: false, reason: "a band run is already queued" };
  }
  // The ten minute retry wakes (09:20 and 15:40) are what make a missed
  // pre-open or post-market dispatch recoverable: the watchdog still finds
  // the window open and the zero gate still has time to seed the day.
  const answer = await dispatchBandScan(env, now, window, "watchdog",
    { force: true });
  return { ...answer, age_seconds: age === null ? null : Math.round(age / 1000) };
}

// Which part of the trading day this instant is in. The names are the
// Python MarketPhase names, because the app renders them verbatim.
function marketPhase(nowUtc) {
  const k = karachiView(nowUtc.getTime());
  const bands = bandsFor(k);
  if (!bands.length) return "CLOSED";
  const mins = minutesOf(k);
  const firstOpen = bands[0][0];
  const lastClose = bands[bands.length - 1][1];
  if (mins < firstOpen[0] * 60 + firstOpen[1]) return "PRE_OPEN";
  if (mins >= lastClose[0] * 60 + lastClose[1]) return "POST_CLOSE";
  for (const band of bands) {
    const from = band[0][0] * 60 + band[0][1];
    const to = band[1][0] * 60 + band[1][1];
    if (mins >= from && mins < to) return "OPEN";
  }
  return "BREAK";
}

function liveBand(k) {
  const mins = minutesOf(k);
  for (const band of bandsFor(k)) {
    const from = band[0][0] * 60 + band[0][1];
    const to = band[1][0] * 60 + band[1][1];
    if (mins >= from && mins < to) {
      return { open: hmText(band[0]), close: hmText(band[1]) };
    }
  }
  return null;
}

// Owner's session law (SO-8): is a session live at this instant? A break, a
// weekend, a holiday and the hours before the open are all false.
function marketOpenNow(nowUtc) {
  return marketPhase(nowUtc) === "OPEN";
}

// The owner's three conditions, folded from the same phases the session law
// produces: OPERATIONAL while the exchange trades, BREAK for its own midday
// break, CLOSED for every other shut instant. The app renders the sentence,
// so it never has to build one from a phase name.
function marketCondition(nowUtc) {
  const phase = marketPhase(nowUtc);
  if (phase === "OPEN" || phase === "WARMUP") return "OPERATIONAL";
  if (phase === "BREAK") return "BREAK";
  return "CLOSED";
}

function conditionText(nowUtc) {
  const condition = marketCondition(nowUtc);
  if (condition === "BREAK") return CONDITION_BREAK;
  if (condition === "CLOSED") return CONDITION_CLOSED;
  return "";
}

// The typed status block the app and the verifier both read.
function marketState(nowUtc) {
  const k = karachiView(nowUtc.getTime());
  const phase = marketPhase(nowUtc);
  const next = nextEvent(nowUtc);
  return {
    phase,
    market_open: phase === "OPEN",
    condition: marketCondition(nowUtc),
    condition_text: conditionText(nowUtc),
    date: dayStamp(k),
    as_of: `${dayStamp(k)}T${hhmm(k)}:00+05:00`,
    trading_day: isTradingDay(k),
    live_band: liveBand(k),
    bands: bandsFor(k).map((b) => ({ open: hmText(b[0]), close: hmText(b[1]) })),
    next_event: next.event
      ? {
        event: next.event,
        at_pk: `${dayStamp(karachiView(next.at.getTime()))} ` +
          `${hhmm(karachiView(next.at.getTime()))}`,
      }
      : null,
    timezone: "Asia/Karachi",
  };
}

// ---------------------------------------------------------------- market data
// Owner order 2026-10-09: the app shows the KSE100 index with its points and
// percentage, and the top three stocks by volume, refreshed every five
// minutes. Both come from the PSX Data Portal's own server rendered pages,
// which are public and live during the session. An unreachable portal yields a
// stated gap, never a made up number, and the buy/sell split is labelled with
// the method that produced it (SO-3).
const PORTAL_HOME = "https://dps.psx.com.pk/";
const PORTAL_INDEX = "https://dps.psx.com.pk/indices/"; // + membership name
const PORTAL_COMPANY = "https://dps.psx.com.pk/company/"; // + symbol
const INDEX_NAME = "KSE100";
const MARKET_MEMBERSHIP = "KMIALLSHR";
const MARKET_TOP_N = 3;
const MARKET_TTL_MS = 5 * 60 * 1000;

// Owner order 2026-11-04: show the stocks receiving a large buy or sell.
// The wire is a snapshot cycle with no order id, so the smallest honest
// unit is one relay update: an increase of at least this much value in the
// venue counter, sided by the quote that arrived with it. The label on the
// answer says exactly that; it never claims an individual broker order.
// Owner order 2026-11-04: a big print is at least PKR 10,000,000 spent in a
// SINGLE transaction, buying or selling. It was 1,000,000, which the owner
// read as ordinary size, not a big trade.
const LARGE_PRINT_PKR = 10_000_000;
const LARGE_PRINT_MAX = 200;

// The KMIALL universe the session captures (319 names today). The live
// snapshot only carries symbols that published a frame, so the complete
// answer names the rest as missing instead of shrinking the universe to
// whatever happened to trade. tests/test_flow_endpoint_contract.py fails if
// this list drifts from src/data/universe_kmiall.json.
const KMIALL_UNIVERSE = ["AASM","ABOT","ACPL","ADAMS","AGIL","AGP","AGTL","AHTM","AIRLINK","AKGL","ALNRS","ANL","ANTM","ARCTM","ARPL","ASC","ASHT","ASL","ASTM","ATBA","ATRL","AVN","AWTX","BAFS","BATA","BBFL","BCL","BECO","BERG","BFAGRO","BFBIO","BFMOD","BHAT","BIFO","BIPL","BLUEX","BNL","BNWM","BPL","BRRG","BTL","BUXL","BWHL","CCM","CEPB","CFL","CHAS","CHCC","CLOV","CNERGY","COLG","CPHL","CPPL","CRTM","CSAP","DAAG","DADX","DBSL","DCL","DCR","DFSM","DGKC","DINT","DMC","DNCC","DOL","DSL","DWSM","DYNO","ECOP","EFERT","ELCM","ELSM","EMCO","ENGROH","EPCL","EPQL","EXIDE","FABL","FANM","FASM","FATIMA","FCCL","FCEPL","FCL","FECM","FECTC","FEM","FEROZ","FFC","FFL","FFLM","FHAM","FIBLM","FIL","FIMM","FLYNG","FML","FNBM","FPJM","FPRM","FRCL","FRSM","FTMM","FTSM","FZCM","GADT","GAL","GATI","GATM","GCIL","GCWL","GDL","GEMBCEM","GEMMEL","GEMPACRA","GEMPAPL","GFIL","GGGL","GGL","GHGL","GHNI","GIL","GLAXO","GOC","GTYR","GVGL","GWLC","HAEL","HAFL","HALEON","HATM","HCAR","HINO","HINOON","HPL","HRPL","HTL","HUBC","IBFL","IBLHL","ICCI","ICL","IDRT","IDSM","ILP","IMAGE","INIL","INKL","IPAK","IREIT","ISIL","ISL","ITANZ","ITTEFAQ","JATM","JDMT","JDWS","JSML","JUBS","JVDC","KCL","KEL","KHYT","KOHC","KOHE","KOHTM","KPUS","KSBP","KSTM","KTML","LCI","LEUL","LIVEN","LOADS","LOTCHEM","LPGL","LUCK","MACFL","MACTER","MARI","MEBL","MEHT","MERIT","MFFL","MFL","MIIETF","MIRKS","MLCF","MQTM","MRNS","MSCL","MTL","MUBT","MUGHAL","MWMP","MZNPETF","NATM","NCML","NESTLE","NETSOL","NML","NONS","NRL","NRSL","NSRM","OCTOPUS","OGDC","OLPM","OML","ORM","OTSU","PAEL","PAKD","PAKOXY","PAKQATAR","PIBTL","PICT","PIM","PIOC","PKGS","PMRS","POML","POWER","PPL","PPP","PQGTL","PREMA","PRL","PSEL","PSO","PSYL","PTL","QTECH","QUET","QUICE","RCML","REDCO","REWM","RMPL","RPL","RUBY","RUPL","SANSM","SAPT","SARC","SASML","SAZEW","SCL","SEARL","SEL","SELECT","SERT","SGABL","SGF","SGPL","SGPLR","SHCM","SHDT","SHFA","SHSML","SIEM","SINDM","SITC","SKRS","SLGL","SLM","SMCPL","SML","SNAI","SNGP","SOYASUP","SPEL","SPL","SPSL","SRR","SRVI","SSGC","SSML","SSOM","STCL","STJT","STL","STLR","STML","STYLERS","SUHJ","SURC","SWL","SYM","SYS","SZTM","TATM","TCORP","TELE","TGL","THCCL","TICL","TISL","TOMCL","TOWL","TPLRF1","TREET","TRSM","TSIL","UBDL","UDLI","UDPL","UNITY","UPFL","WAFI","WAHDAT","WAHN","WASL","WAVES","ZAHID","ZAL","ZIL","ZTL"];

// Owner order 2026-11-06: the phone's SEARCH page carries a SECTORS tile.
// The classification is the broker's own scrip master (a sectorName on every
// approved REG scrip), filtered against KMIALL_UNIVERSE, so a scrip outside
// KMIALL never reaches the phone and no sector is invented here (SO-3). The
// master moves only on listing events, so it is held for six hours; an
// unreachable master answers a stated gap, never a guessed list.
const SCRIP_MASTER_URLS = [
  "https://nxg2.eclear.com.pk/pero/ScripServlet",
  "https://nxg1.eclear.com.pk/pero/ScripServlet",
];
const SECTOR_MASTER_TTL_MS = 6 * 60 * 60 * 1000;
let sectorMaster = { at: 0, answer: null };

async function sectorsAnswer() {
  const now = Date.now();
  if (sectorMaster.answer && now - sectorMaster.at < SECTOR_MASTER_TTL_MS) {
    return sectorMaster.answer;
  }
  const wanted = new Set(KMIALL_UNIVERSE);
  let lastError = "no source";
  for (const base of SCRIP_MASTER_URLS) {
    try {
      const response = await fetch(
        `${base}?ScripLoadDateTime=&IsReLoad=1`,
        {
          headers: { "user-agent": "okhttp/4.9.3", accept: "application/json" },
          cf: { cacheTtl: 3600, cacheEverything: true },
        },
      );
      if (!response.ok) {
        lastError = `HTTP ${response.status}`;
        continue;
      }
      const rows = await response.json();
      if (!Array.isArray(rows)) {
        lastError = "not a list";
        continue;
      }
      const bySector = new Map();
      for (const row of rows) {
        if (!row || row.market !== "REG" || row.approved !== "Approved") {
          continue;
        }
        const symbol = String(row.symbol || "").trim().toUpperCase();
        if (!wanted.has(symbol)) continue;
        const sector = String(row.sectorName || "").trim().toUpperCase();
        if (!sector) continue;
        if (!bySector.has(sector)) bySector.set(sector, new Set());
        bySector.get(sector).add(symbol);
      }
      if (bySector.size === 0) {
        lastError = "no KMIALL sectors in the master";
        continue;
      }
      const answer = {
        ok: true,
        source: "eClear ScripServlet sectorName",
        as_of: new Date().toISOString(),
        sectors: [...bySector.entries()]
          .map(([name, symbols]) => ({ name, symbols: [...symbols].sort() }))
          .sort((a, b) => a.name.localeCompare(b.name)),
      };
      sectorMaster = { at: now, answer };
      return answer;
    } catch (err) {
      lastError = String((err && err.message) || err);
    }
  }
  return {
    ok: false,
    source: "eClear ScripServlet sectorName",
    as_of: new Date().toISOString(),
    sectors: [],
    error: `sector master unavailable: ${lastError}`,
  };
}

function largePrintFrom(quote, measured) {
  if (!quote || !measured || !Number.isFinite(measured.delta) ||
      measured.delta <= 0) return null;
  const price = Number(quote.price);
  if (!Number.isFinite(price) || price <= 0) return null;
  const value = Math.round(measured.delta * price);
  if (value < LARGE_PRINT_PKR) return null;
  const at = Date.parse(quote.observed_at || "");
  if (!Number.isFinite(at)) return null;
  return {
    symbol: String(quote.symbol || "").toUpperCase(),
    day: dayStamp(karachiView(at)),
    side: measured.side === "S" ? "S" : "B",
    shares: measured.delta,
    price,
    value_pkr: value,
    at: quote.observed_at,
    tick: quote.source_tick_time || null,
    rule: measured.rule || null,
  };
}

// Owner order 2026-10-26: "show it only if the market is open today".
// Yesterday's frames must not answer a today question. A quote is from
// today when its own stamp carries the SAME Karachi trading day the
// reading instant belongs to - both sides use dayStamp/isTradingDay so a
// weekend roll and a holiday agree by construction (SO-3, SO-8).
function quoteIsFromToday(quote) {
  const at = quote && quote.observed_at ? new Date(quote.observed_at) : null;
  if (!at || Number.isNaN(at.getTime())) return false;
  const kNow = dayStamp(karachiView(Date.now()));
  return dayStamp(karachiView(at.getTime())) === kNow &&
         isTradingDay(karachiView(at.getTime()));
}

// Owner order 2026-10-31, "data has to be same/correct across the entire
// app": the answer to "what did PRL do today" is the REGULAR session's
// numbers, never the post-market tail. Measured on the live relay on
// 2026-10-30 (Friday): the store's last PRL frame carried a 16:46 PKT tick
// with the post-market fill price 96.28, while the exchange's own regular
// session page answered 96.96 with its 25,437,791 total, and the one phone
// asked one question through two routes and saw two different stocks.
// The eClear REG feed keeps publishing after the band close, so the store
// must know which session a frame's own tick belongs to and keep the
// post-market tail out of the store whose rows the app answers from.
// SO-8: the tick is read as Karachi wall clock against bandsFor's own
// table, the same law the phase and the bands already speak.
const REGULAR_SESSION_GRACE_MS = 5 * 60 * 1000;

function tickInstantInDay(karachiDay, tickText, fallbackInstantMs) {
  const at = karachiDay.getTime();
  if (typeof tickText === "string" && /^[0-9]{2}:[0-9]{2}:[0-9]{2}$/.test(tickText)) {
    const parsed = Date.parse(
      `${dayStamp(karachiDay)}T${tickText}+05:00`,
    );
    if (Number.isFinite(parsed)) return parsed;
  }
  return Number.isFinite(fallbackInstantMs) ? fallbackInstantMs : null;
}

// Which regular band of its own Karachi day does this frame's tick
// belong to (1 based), or 0 when the frame names none. Friday has two
// bands, so a frame knows which band its counter belongs to; the bands
// are disjoint, so a tick inside either answers at once.
function regularBandIndexOf(quote) {
  const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
  if (!Number.isFinite(at)) return null;
  const k = karachiView(at);
  const day = dayStamp(k);
  const tickAt = tickInstantInDay(k, quote.source_tick_time, at);
  if (tickAt === null) return null;
  const bands = bandsFor(k);
  for (let i = 0; i < bands.length; i++) {
    const openAt = Date.parse(`${day}T${hmText(bands[i][0])}:00+05:00`);
    const closeAt = Date.parse(`${day}T${hmText(bands[i][1])}:00+05:00`);
    if (tickAt >= openAt && tickAt <= closeAt + REGULAR_SESSION_GRACE_MS) {
      return i + 1;
    }
  }
  return 0;
}

// Store law (owner order 2026-11-06, twelfth pass): a frame enters the
// quote store when its own tick sits inside one of the exchange's real
// trading windows, which now includes the pre-open auction and the
// published Post-Close Session, not only the regular bands. The day's
// B, S and T therefore cover the whole tape from the first pre-open
// print to the last post-close print, and no pre-open or post-close
// volume can fall into the next frame's unclassified baseline. A tail
// after the post-close window is still refused.
const PRE_OPEN_WINDOWS = {
  1: [[9 * 60 + 15, 9 * 60 + 30]],
  2: [[9 * 60 + 15, 9 * 60 + 30]],
  3: [[9 * 60 + 15, 9 * 60 + 30]],
  4: [[9 * 60 + 15, 9 * 60 + 30]],
  5: [[9 * 60, 9 * 60 + 15], [14 * 60 + 15, 14 * 60 + 30]],
};
// Owner order 2026-11-12: the quant scans the post-market from 15:32 to 15:49
// Monday to Thursday and 16:32 to 16:49 on Friday, so the frames it captures
// in that window are accepted and a tail after it is still refused.
const POST_CLOSE_WINDOWS = {
  1: [[15 * 60 + 32, 15 * 60 + 49]],
  2: [[15 * 60 + 32, 15 * 60 + 49]],
  3: [[15 * 60 + 32, 15 * 60 + 49]],
  4: [[15 * 60 + 32, 15 * 60 + 49]],
  5: [[16 * 60 + 32, 16 * 60 + 49]],
};
function frameSessionClock(quote) {
  const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
  if (!Number.isFinite(at)) return null;
  const k = karachiView(at);
  const tickAt = tickInstantInDay(k, quote.source_tick_time, at);
  if (tickAt === null) return null;
  const t = karachiView(tickAt);
  return { weekday: t.getUTCDay(), minute: minutesOf(t) };
}
function minuteInAnyWindow(minute, spans) {
  for (const span of spans || []) {
    if (minute >= span[0] && minute < span[1]) return true;
  }
  return false;
}
function frameIsTradingSession(quote) {
  const band = regularBandIndexOf(quote);
  if (band !== null && band > 0) return true;
  const clock = frameSessionClock(quote);
  if (!clock) return false;
  return minuteInAnyWindow(clock.minute, PRE_OPEN_WINDOWS[clock.weekday]) ||
    minuteInAnyWindow(clock.minute, POST_CLOSE_WINDOWS[clock.weekday]);
}

// One symbol's acknowledged frame for one Karachi day, in relay_state's
// own key space. The acknowledged frame is the newer evidence of the same
// venue counter: per (day, band, symbol), a candidates whose volume
// advances the stored one replaces it, and its split is CLAMPED so the
// printed B and S can only move (owner order 2026-10-31, "how could the
// buying and selling volume decrease? The volume can only increase").
// It is NOT monotone across the Friday midday break on purpose: the
// exchange's own counter is the DAY's cumulative total (measured on the
// live 2026-10-30 store, whose post-break frame still carried the 25.4M
// band-1 total), so the acknowledged frame is keyed day and band together
// and the day's answer is the newest session's rows.
const ACK_TTL_SECONDS = 2 * 86400;
// Owner order 2026-11-03: the ACK mirror is written at most once per live
// symbol per window. The constant is also the gate in /ack-upsert; a
// missing definition there is a ReferenceError, not a throttle.
//
// Owner incident 2026-11-04: the window was 30 seconds, and one row per live
// symbol per 30 seconds is 319 x 720 = 229,680 rows in a six hour session
// against Cloudflare's free plan cap of 100,000 rows written PER ACCOUNT per
// day (00:00 UTC reset). The mirror alone spent the whole day's budget about
// two and a half hours into the band, and every write after that failed: the
// card went empty while the market was open. A window of five minutes is
// 319 x 72 = 22,968 rows, and the reading side still prefers a newer live
// frame over the mirrored one, so no surface waits five minutes for its own
// price. A new Worker would not have helped here: the cap belongs to the
// account, not to the Worker or its Durable Object namespace.
const ACK_WRITE_MIN_MS = 5 * 60 * 1000;
// The hard ceiling for the mirror, so a future change to the window cannot
// quietly spend the day again. Flow's own backup holds 40,000 and the quote
// snapshot is one row per coalesced push, so 25,000 here keeps the whole
// relay inside the free plan's 100,000 rows written a day.
const ACK_ROWS_PER_DAY = 25000;

const ACK_SYMBOL_RE = /^[A-Z0-9]{1,12}$/;

// Owner order 2026-11-03: the ACK store is a mirror, not a second feed. If
// every display poll wrote the mirror, a shopping phone could spend the
// relay's whole Durable Objects day budget. The mirror is written at most
// once per live symbol per 30 seconds; a newer live frame still wins on the
// reading side, so the phone does not open with a stale card or search row.

function clampPair(candidate, previous) {
  const volume = Math.round(candidate.volume);
  if (!Number.isFinite(volume) || volume <= 0) return null;
  let buy = Math.round(candidate.buy_volume);
  let sell = Math.round(candidate.sell_volume);
  if (!Number.isFinite(buy) || !Number.isFinite(sell) ||
      buy < 0 || sell < 0 || buy + sell !== volume) {
    return null;
  }
  if (previous) {
    // Owner order 2026-11-10 (latest): a total below the stored one is not
    // a new print. An older frame or a restarted capture can stand a symbol
    // lower than what is already acknowledged, and following that total
    // down would carry B and S down with it (volume - previous.sell_volume
    // falls below previous.buy_volume, so the floor cap would print a
    // decrease). The acknowledged pair stands instead.
    const prevVolume = Math.round(Number(previous.volume));
    const prevBuy = Math.round(Number(previous.buy_volume));
    const prevSell = Math.round(Number(previous.sell_volume));
    if (Number.isFinite(prevVolume) && Number.isFinite(prevBuy) &&
        Number.isFinite(prevSell) && volume < prevVolume) {
      return { buy: prevBuy, sell: prevSell, volume: prevVolume };
    }
    // Monotone law: B can only stand at or above its own floor, S can
    // only stand at or above its own floor, and the two must still sum
    // to the row's total. buy is bounded by [prevBuy, volume - prevSell].
    buy = Math.min(Math.max(buy, previous.buy_volume),
      volume - previous.sell_volume);
    sell = volume - buy;
  }
  return { buy, sell, volume };
}

function ackCandidateFrame(row, day) {
  if (!day) return null;
  const symbol = String(row.symbol || "").toUpperCase();
  if (!ACK_SYMBOL_RE.test(symbol)) return null;
  const volume = Number(row.volume);
  const buy = Number(row.buy_volume);
  const sell = Number(row.sell_volume);
  if (!Number.isFinite(buy) || !Number.isFinite(sell)) return null;
  if (Math.round(buy) < 0 || Math.round(sell) < 0) return null;
  if (Math.round(buy) + Math.round(sell) !== Math.round(volume)) return null;
  // Only a measured pair may enter the mirror. An old range pair carries no
  // wire evidence and must never be carried forward.
  if (row.split_method !== "quote_rule") return null;
  const band = regularBandIndexOf(row);
  if (band === null || band < 1) return null;
  return {
    symbol,
    day,
    band,
    price: Number.isFinite(Number(row.price)) ? Number(row.price) : null,
    change_pct: Number.isFinite(Number(row.change_pct))
      ? Number(row.change_pct) : null,
    volume: Math.round(volume),
    buy_volume: Math.round(buy),
    sell_volume: Math.round(sell),
    split_method: "quote_rule",
    split_source: row.split_source ||
      "every volume increment sided by the wire's own bid/ask at the poll",
    observed_at: row.observed_at || row.feed_as_of || null,
    source: row.quote_source || row.source || null,
    quote_fresh: Boolean(row.quote_fresh),
  };
}

// The acknowledged rows for one KMIALL trading day, as a map keyed by
// symbol: for each symbol the newest session's acknowledged frame. A
// missing hub (the local worker harness) answers null, and every caller
// falls back to its own paths unchanged.
async function ackRowsForDay(env, day) {
  if (!day) return null;
  // The acknowledged map is a display mirror, not a live tick: half a
  // minute of memory is enough for every ranking on the phone and keeps
  // the read off the Durable Objects request budget (owner order
  // 2026-11-05).
  const stamp = Date.now();
  if (ackMemo.day === day && stamp - ackMemo.at < ACK_MEMO_MS) {
    return ackMemo.rows;
  }
  try {
    const answer = await stateCall(env, "/ack-splits?day="
      + encodeURIComponent(day));
    const rows = answer && answer.ok ? answer.rows : null;
    if (rows) ackMemo = { day, at: Date.now(), rows };
    return rows;
  } catch (_) {
    return null;
  }
}

// Acknowledge display rows and return the stored answer for the symbols
// that were candidates. Any failure degrades to null and the callers keep
// their own rows (SO-3: degrading keeps what was already shown, it never
// invents).
async function ackUpsert(env, frames) {
  if (!frames.length) return null;
  try {
    const answer = await stateCall(env, "/ack-upsert", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ frames }),
    });
    return answer && answer.ok ? answer.rows : null;
  } catch (_) {
    return null;
  }
}

// One display row meets its acknowledged store row. The stored frame IS
// the newer evidence of the same venue counter, so its total wins, and
// its coherent clamped pair rides with it. Nothing is aged forward: a
// stored frame without its own price keeps the candidate's values.
function applyStoredFrame(row, stored) {
  if (!stored || stored.symbol !== row.symbol) return row;
  const rowAt = Date.parse(row.observed_at || "");
  const storedAt = Date.parse(stored.observed_at || "");
  // The ACK store may be throttled, but the reading side is not. A newer
  // live frame is not silently replaced by an older stored frame.
  if (Number.isFinite(rowAt) &&
      (!Number.isFinite(storedAt) || storedAt < rowAt)) return row;
  if (Number.isFinite(Number(stored.volume))) {
    row.volume = Math.round(Number(stored.volume));
    row.split_volume = row.volume;
  }
  if (Number.isFinite(Number(stored.price)) && Number(stored.price) > 0) {
    row.price = Number(stored.price);
  }
  if (Number.isFinite(Number(stored.change_pct))) {
    row.change_pct = Number(stored.change_pct);
  }
  const measuredStored = stored.split_method === "quote_rule";
  if (measuredStored && Number.isFinite(Number(stored.buy_volume)) &&
      Number.isFinite(Number(stored.sell_volume))) {
    row.buy_volume = Math.round(Number(stored.buy_volume));
    row.sell_volume = Math.round(Number(stored.sell_volume));
    row.split_volume = row.buy_volume + row.sell_volume;
    row.split_method = "quote_rule";
    row.split_source = stored.split_source ||
      "every volume increment sided by the wire's own bid/ask at the poll";
  } else if (row.split_method !== "quote_rule") {
    // A stored range is not a measurement. It may update the total, but it
    // never supplies a side; the total stays visible as U.
    row.buy_volume = null;
    row.sell_volume = null;
    row.split_volume = null;
    row.classified_volume = null;
    row.split_method = "unavailable";
    row.split_source =
      "no measured order-flow pair; the total is unclassified";
  }
  if (Number.isFinite(Number(row.volume)) &&
      Number.isFinite(row.buy_volume) && Number.isFinite(row.sell_volume)) {
    row.classified_volume = row.buy_volume + row.sell_volume;
    row.split_volume = row.classified_volume;
    row.unclassified_volume = Math.max(0,
      Math.round(Number(row.volume)) - row.classified_volume);
    row.flow_complete = row.unclassified_volume === 0;
  } else if (row.split_method !== "quote_rule" &&
      Number.isFinite(Number(row.volume))) {
    row.classified_volume = null;
    row.unclassified_volume = Math.max(0, Math.round(Number(row.volume)));
    row.flow_complete = row.unclassified_volume === 0;
  }
  row.ack_band = stored.band;
  return row;
}

// Owner order 2026-11-01 ("make sure that the data is correct always ...
// for the past few days I have been seeing 2 different sets of data for
// stocks, top 3 scrips of volume showed different and search box showed
// different data"): one symbol, ONE frame. The hub can carry more than one
// row for a symbol (a retried push, a frame restored beside a live one), and
// the three reading routes each picked their own: the card took the first
// fresh row it met, /stock took the first row in array order whatever its
// stamp, and /prices walked every row. That is how the same scrip printed
// two prices at once. Every route now asks this one function, which keeps
// the NEWEST frame by its own observed_at for each symbol; ties fall to the
// later row in the snapshot, and a row without a stamp never displaces a
// stamped one.
function newestQuoteRows(quotes) {
  const best = new Map();
  for (const row of Array.isArray(quotes) ? quotes : []) {
    if (!row || typeof row !== "object") continue;
    const symbol = String(row.symbol || "").toUpperCase();
    if (!symbol) continue;
    const prev = best.get(symbol);
    if (!prev) {
      best.set(symbol, row);
      continue;
    }
    const prevAt = Date.parse(prev.observed_at || "");
    const rowAt = Date.parse(row.observed_at || "");
    if (Number.isFinite(rowAt) && (!Number.isFinite(prevAt) || rowAt >= prevAt)) {
      best.set(symbol, row);
    }
  }
  return best;
}

// The change text is printed signed on a falling day ("-5.15") and the
// direction is ALSO carried by the change__text--pos/neg class, so the sign
// comes from the class and the magnitude from the text. The percentage is
// always printed unsigned.
const INDEX_PANEL = /<div class="tabs__panel marketIndices__details"\s+data-name="([A-Z0-9]+)"[^>]*?data-date="([^"]*)"[^>]*?data-close="([-0-9.]+)"[^>]*>.*?<span class="marketIndices__change (change__text--(?:pos|neg))">(?:<i[^>]*><\/i>)?\s*(-?[0-9][0-9,]*\.?[0-9]*)\s*\((-?[0-9][0-9,]*\.?[0-9]*)%\)/gs;
const CONSTITUENT_ROW = /<tr[^>]*>([\s\S]*?)<\/tr>/g;
const TABLE_CELL = /<td([^>]*)>([\s\S]*?)<\/td>/g;

// Short, safe description of a failure: the app shows this verbatim in the
// card's footnote, so it must never leak a token or a URL with credentials.
function describe(e) {
  const name = e && e.name ? e.name : "error";
  const message = e && e.message ? String(e.message) : "";
  return message ? `${name}: ${message}` : name;
}

function num(text) {
  return parseFloat(String(text).replace(/,/g, ""));
}

function parseIndexPanel(html, name) {
  INDEX_PANEL.lastIndex = 0;
  let m;
  while ((m = INDEX_PANEL.exec(html)) !== null) {
    if (m[1] !== name) continue;
    const sign = m[4].endsWith("pos") ? 1 : -1;
    return {
      symbol: name,
      value: num(m[3]),
      change: sign * Math.abs(num(m[5])),
      change_pct: sign * Math.abs(num(m[6])),
      as_of: m[2],
      source: "dps.psx.com.pk index panel",
    };
  }
  return null;
}

function parseConstituents(html) {
  const rows = [];
  CONSTITUENT_ROW.lastIndex = 0;
  let block;
  while ((block = CONSTITUENT_ROW.exec(html)) !== null) {
    const attrs = [];
    const bodies = [];
    TABLE_CELL.lastIndex = 0;
    let cell;
    while ((cell = TABLE_CELL.exec(block[1])) !== null) {
      attrs.push(cell[1]);
      bodies.push(cell[2]);
    }
    if (attrs.length < 9) continue;
    const symbol = /data-order="([A-Z0-9]{2,12})"/.exec(attrs[0]);
    if (!symbol) continue;
    const ordered = (i) => {
      const found = /data-order="([^"]*)"/.exec(attrs[i]);
      if (!found) return null;
      const value = num(found[1]);
      return Number.isFinite(value) ? value : null;
    };
    const signedPercent = (i) => {
      const value = ordered(i);
      if (value === null) return null;
      return attrs[i].includes("change__text--neg") ? -Math.abs(value) : value;
    };
    rows.push({
      symbol: symbol[1],
      current: ordered(3),
      change_pct: signedPercent(5),
      volume: ordered(8),
    });
  }
  return rows;
}

// One <div class="stats_label">NAME</div><div class="stats_value">VALUE</div>
// pair, which is how every number on a company page's panel is published.
const STATS_PAIR = /stats_label">\s*([^<]{1,40}?)\s*<\/div>\s*<div class="stats_value">\s*(.*?)\s*<\/div>/gs;
// The REG panel is the regular equity market. The page also renders FUT, CSF
// and ODL panels plus futures contract blocks with the same label markup, so
// the parse is scoped to REG before any value is read (mirrors
// src/data/market_snapshot.py).
const REG_PANEL_START = /<div[^>]*class="tabs__panel[^"]*"[^>]*data-name="REG"[^>]*>/;
const PANEL_EDGE = /<div[^>]*class="tabs__panel[^"]*"[^>]*data-name="/g;

function regPanel(html) {
  const start = REG_PANEL_START.exec(html);
  if (!start) return "";
  PANEL_EDGE.lastIndex = start.index + start[0].length;
  const edge = PANEL_EDGE.exec(html);
  return html.slice(start.index + start[0].length, edge ? edge.index : html.length);
}

// The session range and volume one symbol's REG panel publishes, or null when
// it publishes no session at all (a closed market clears these fields).
function parseSymbolRange(html) {
  const panel = regPanel(html);
  if (!panel) return null;
  const pairs = {};
  STATS_PAIR.lastIndex = 0;
  let m;
  while ((m = STATS_PAIR.exec(panel)) !== null) {
    const label = m[1].replace(/<[^>]*>/g, "").trim();
    if (!(label in pairs)) pairs[label] = m[2].replace(/<[^>]*>/g, "").trim();
  }
  const value = (name) => {
    const raw = pairs[name];
    if (raw === undefined || raw === "") return null;
    const parsed = parseFloat(String(raw).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
  };
  const quote = { high: value("High"), low: value("Low"), volume: value("Volume") };
  if (!quote.high && !quote.low && !quote.volume) return null;
  return quote;
}

// B/S is never estimated from the day's range. A pair is served only when
// the capture measured every increment at the wire; a frame without one
// ships null B/S and the whole known total as unclassified.

// One answer for a quote's B/S pair. The durable quote store writes the pair
// on every accepted frame, so every route reads that pair instead of
// recomputing a fresh range estimate and getting a different answer. Old rows
// written before the pair was stored fall back to the same range law.
// The measured pair the hub keeps: every increment of the venue's own
// counter sided at the wire and never retracted. When the frame carries it,
// this is the pair every route must serve; the range estimate is only the
// fallback for a frame the hub has not measured yet.
function measuredFromQuote(quote) {
  if (!quote || typeof quote !== "object" || quote.flow_method !== "quote_rule") {
    return null;
  }
  const buy = Math.round(Number(quote.measured_buy));
  const sell = Math.round(Number(quote.measured_sell));
  const baseline = Math.max(0, Math.round(Number(quote.flow_baseline) || 0));
  if (!Number.isFinite(buy) || !Number.isFinite(sell) ||
      buy < 0 || sell < 0) {
    return null;
  }
  return {
    buy_volume: buy,
    sell_volume: sell,
    split_volume: buy + sell,
    flow_baseline: baseline,
    flow_baseline_at: quote.flow_baseline_at || null,
    flow_first_seen_at: quote.flow_first_seen_at || null,
    flow_baseline_reason: quote.flow_baseline_reason || null,
    split_method: "quote_rule",
    split_source:
      "every volume increment sided by the wire's own bid/ask at the poll",
  };
}

function splitFromQuote(quote) {
  if (!quote || typeof quote !== "object") return null;
  // An old stored range pair carries split_method "range_position"; it is
  // not evidence and is never served as B or S.
  if (quote.flow_method !== "quote_rule" &&
      quote.split_method !== "quote_rule") return null;
  const measured = measuredFromQuote(quote);
  if (measured) return measured;
  const volume = Math.round(Number(quote.volume));
  const buy = Math.round(Number(quote.buy_volume));
  const sell = Math.round(Number(quote.sell_volume));
  if (!Number.isFinite(buy) || !Number.isFinite(sell) ||
      buy < 0 || sell < 0) return null;
  if (Number.isFinite(volume) && buy + sell > volume) return null;
  return {
    buy_volume: buy,
    sell_volume: sell,
    split_volume: buy + sell,
    flow_baseline: Number.isFinite(volume) ? volume - buy - sell : null,
    split_method: "quote_rule",
    split_source: quote.split_source ||
      "every volume increment sided by the wire's own bid/ask at the poll",
  };
}

// The capture's own pair, when it carries one. The feed daemon starts before
// the open and sees every frame from the day's first print, so a hub that
// starts later can adopt that observed pair instead of re-baselining the
// shares that were already traded. Only a coherent quote_rule pair is
// accepted; anything else leaves the total unclassified, which is honest.
function measuredFlowSeed(quote, total) {
  if (!quote) return null;
  // The running capture may predate the measured_* names. Its raw pair has
  // carried the same quote_rule separation under buy_volume/sell_volume since
  // the original flow law, so accept that pair too instead of masking it
  // with an all-unclassified baseline.
  const measured = quote.flow_method === "quote_rule";
  if (!measured && quote.split_method !== "quote_rule") return null;
  const buy = Math.round(Number(measured ? quote.measured_buy
    : quote.buy_volume));
  const sell = Math.round(Number(measured ? quote.measured_sell
    : quote.sell_volume));
  if (!Number.isFinite(buy) || !Number.isFinite(sell) ||
      buy < 0 || sell < 0 || buy + sell > total) return null;
  return { buy, sell, baseline: total - buy - sell };
}

// The trading day a quote belongs to. The venue's cumulative counters reset
// once per trading day and run continuously across the Friday lunch break,
// so the afternoon's first frame must still carry the morning's total.
function quoteSessionKey(quote) {
  const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
  if (!Number.isFinite(at)) return null;
  return { day: dayStamp(karachiView(at)) };
}

// The leader table has no order-flow pair. Never fill it from the day's
// range: the total is the only proven number, so it ships as U and B/S
// stay null.
async function attachSplits(rows) {
  for (const row of rows || []) {
    const volume = Number.isFinite(Number(row.volume))
      ? Math.max(0, Math.round(Number(row.volume))) : null;
    row.buy_volume = null;
    row.sell_volume = null;
    row.split_volume = null;
    row.classified_volume = null;
    row.unclassified_volume = volume;
    row.flow_complete = volume === null ? null : volume === 0;
    row.split_method = "unavailable";
    row.split_source = "no measured order-flow pair; the total is unclassified";
  }
  return rows;
}

// The card's one sentence about the split, naming the weakest method used and
// counting any row that carries no split at all.
function splitLabel(rows) {
  const available = (rows || []).filter((r) =>
    r.split_method === "quote_rule" && Number.isFinite(r.buy_volume) &&
    Number.isFinite(r.sell_volume));
  if (!available.length) {
    return "B/S unavailable: the wire has not measured a pair";
  }
  let text = "B/S measured at the wire from the broker feed";
  if (available.length < rows.length) {
    text += ` (${available.length} of ${rows.length})`;
  }
  return text;
}

function topByVolume(rows, limit) {
  return rows
    .filter((r) => r.volume && r.volume > 0)
    .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
    .slice(0, limit)
    .map((r) => ({
      symbol: r.symbol,
      volume: Math.round(r.volume),
      price: r.current,
      // The owner's card shows the day's move per leader, so the parsed
      // percentage is carried instead of being dropped (it was parsed and
      // then discarded, which is why the app had no percentage to show).
      change_pct: r.change_pct,
      // The exchange's own table carries ONE volume column and no aggressor
      // evidence, so B/S stay null and the known total is reported as U.
      // Null here means "not measured", never "zero" (SO-3).
      buy_volume: null,
      sell_volume: null,
      split_method: "unavailable",
      split_source: "split not read yet",
      basis: "current session volume (PSX constituent table)",
    }));
}

async function portalText(url) {
  const r = await fetch(url, {
    headers: {
      "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "accept": "text/html,application/xhtml+xml",
    },
    signal: AbortSignal.timeout(9000),
  });
  if (!r.ok) throw new Error(`portal HTTP ${r.status}`);
  return r.text();
}

// Build a fresh snapshot straight from the portal. A failure in either half
// is reported in `notes` and leaves that half null.
async function buildMarketSnapshot(env, now) {
  const k = karachiView(now.getTime());
  const snapshot = {
    as_of: `${dayStamp(k)}T${hhmm(k)}:00+05:00`,
    date: dayStamp(k),
    timezone: "Asia/Karachi",
    market_open: marketOpenNow(now),
    market_state: marketState(now),
    index: null,
    kmiall_members: 0,
    top_volume: null,
    top_volume_basis: null,
    volume_split_basis: null,
    notes: [],
    market_feed: { status: "UNKNOWN", raw_status: null, as_of: null,
      age_seconds: null, source: "eClear REG market feed", fresh: false },
  };
  try {
    snapshot.index = parseIndexPanel(await portalText(PORTAL_HOME), INDEX_NAME);
    if (!snapshot.index) snapshot.notes.push("index panel not found on the portal home page");
  } catch (e) {
    snapshot.notes.push("index fetch failed: " + describe(e));
  }
  try {
    const rows = parseConstituents(await portalText(PORTAL_INDEX + MARKET_MEMBERSHIP));
    snapshot.kmiall_members = rows.length;
    if (!rows.length) {
      snapshot.notes.push("the index constituent table was empty");
      snapshot.volume_split_basis = "no leaders, so there is no split to report";
    } else {
      await rememberPortalRows(env, now, rows);
      snapshot.top_volume = await attachSplits(topByVolume(rows, MARKET_TOP_N));
      snapshot.top_volume_basis = snapshot.top_volume.length
        ? `current session volume, top ${snapshot.top_volume.length}`
        : "no stock has traded yet this session";
      snapshot.volume_split_basis = splitLabel(snapshot.top_volume);
    }
  } catch (e) {
    snapshot.notes.push("constituents fetch failed: " + describe(e));
    snapshot.top_volume_basis =
      "the index constituent table was unreachable, so the session volume ranking is unavailable";
    snapshot.volume_split_basis =
      "no volume ranking, so the buy/sell split is unavailable";
  }
  return snapshot;
}

// Owner report 2026-11-06: the broker tape went silent at the open, so the
// quote hub held no frame for today and the search, the scanner and the
// sector reveal answered empty while the exchange's own constituent table
// was live. That table is already read for the card's top three; its rows
// are kept here too, so /prices can answer a symbol the hub has not heard
// from today with the exchange's own price, move and session volume instead
// of dropping it. B and S stay null: the portal publishes a total, never a
// measured split, and no split is invented (SO-3).
const PORTAL_ROWS_KEY = "MARKET:ROWS";
const PORTAL_ROWS_MAX_AGE_MS = 15 * 60 * 1000;
let portalRowsMemo = null;

async function rememberPortalRows(env, now, rows) {
  const kept = [];
  for (const row of rows || []) {
    if (!row || typeof row !== "object") continue;
    const symbol = String(row.symbol || "");
    if (!/^[A-Z0-9]{2,12}$/.test(symbol)) continue;
    if (!Number.isFinite(row.current) || row.current <= 0) continue;
    kept.push({
      symbol,
      price: row.current,
      change_pct: Number.isFinite(row.change_pct) ? row.change_pct : null,
      volume: Number.isFinite(row.volume) ? Math.round(row.volume) : null,
    });
  }
  if (!kept.length) return;
  const payload = {
    built_at: now.toISOString(),
    date: dayStamp(karachiView(now.getTime())),
    rows: kept,
  };
  portalRowsMemo = { at: now.getTime(), value: payload };
  try {
    await kvPut(env, PORTAL_ROWS_KEY, JSON.stringify(payload),
      { expirationTtl: 1800 });
  } catch (_) {
    // The isolate's own memo still answers; the next build retries the write.
  }
}

async function portalRowsToday(env, now) {
  const fresh = (value) => {
    if (!value || !Array.isArray(value.rows)) return null;
    if (value.date !== dayStamp(karachiView(now.getTime()))) return null;
    const built = Date.parse(value.built_at || "");
    if (!Number.isFinite(built)) return null;
    if (now.getTime() - built > PORTAL_ROWS_MAX_AGE_MS) return null;
    return value.rows;
  };
  if (portalRowsMemo &&
      now.getTime() - portalRowsMemo.at <= PORTAL_ROWS_MAX_AGE_MS) {
    const remembered = fresh(portalRowsMemo.value);
    if (remembered) return remembered;
  }
  try {
    return fresh(JSON.parse((await kvGet(env, PORTAL_ROWS_KEY)) || "null"));
  } catch (_) {
    return null;
  }
}

// The card's five minute portal build is skipped whenever a runner's pushed
// snapshot keeps the MARKET key fresh, and that pushed snapshot carries only
// the top three. A silent tape then needs the member table on its own, so
// the search route asks for this build directly: one fetch of the exchange's
// own KMIALLSHR table, one shared task, and a two minute floor between
// builds so a one second poll cannot spend the day's write budget.
const PORTAL_ROWS_MIN_GAP_MS = 2 * 60 * 1000;
let portalRowsRefreshInFlight = null;
let portalRowsBuiltAt = 0;

async function refreshPortalRows(env, now) {
  if (portalRowsRefreshInFlight) return portalRowsRefreshInFlight;
  if (now.getTime() - portalRowsBuiltAt < PORTAL_ROWS_MIN_GAP_MS) return null;
  portalRowsBuiltAt = now.getTime();
  portalRowsRefreshInFlight = (async () => {
    try {
      const rows = parseConstituents(
        await portalText(PORTAL_INDEX + MARKET_MEMBERSHIP));
      await rememberPortalRows(env, now, rows);
    } catch (_) {
      // The next poll retries; a failed fetch answers nothing.
    } finally {
      portalRowsRefreshInFlight = null;
    }
  })();
  return portalRowsRefreshInFlight;
}

// The card reads a fixed field set, and a snapshot can come from either
// producer: the edge's own portal build, or the owner's local runner push
// (POST /market). Normalizing on the way out means a partial push can never
// strip `index`, `top_volume`, `notes` or `kmiall_members` from the app's
// contract: a missing field becomes an explicit null instead of a missing key.
function normalizeMarket(raw) {
  const s = (raw && typeof raw === "object" && !Array.isArray(raw)) ? raw : {};
  const index = (s.index && typeof s.index === "object") ? s.index : null;
  const rows = Array.isArray(s.top_volume)
    ? s.top_volume.filter((row) => row && typeof row === "object" &&
                                  typeof row.symbol === "string")
    : null;
  const members = Number.isFinite(Number(s.kmiall_members))
    ? Number(s.kmiall_members) : (rows ? rows.length : 0);
  const marketFeed = (s.market_feed && typeof s.market_feed === "object")
    ? s.market_feed
    : { status: "UNKNOWN", raw_status: null, as_of: null,
        age_seconds: null, source: "eClear REG market feed", fresh: false };
  return { ...s,
    index,
    kmiall_members: members,
    top_volume: rows,
    market_feed: marketFeed,
    top_volume_basis:
      typeof s.top_volume_basis === "string" ? s.top_volume_basis : null,
    notes: Array.isArray(s.notes) ? s.notes : [] };
}

// Market-wide feed status has its own 90 second freshness window, separate
// from the session law and the five-minute card cache. An old OPEN frame must
// not stay visually live after capture has stopped.
function refreshMarketFeed(snapshot, now) {
  const feed = snapshot && snapshot.market_feed;
  if (!snapshot || typeof snapshot !== "object") return snapshot;
  if (!feed || typeof feed !== "object" || !feed.as_of) {
    snapshot.market_feed = { status: "UNKNOWN", raw_status: null,
      as_of: null, age_seconds: null, source: "eClear REG market feed",
      fresh: false };
    return snapshot;
  }
  const stamp = Date.parse(feed.as_of);
  const ageMs = Number.isFinite(stamp) ? now.getTime() - stamp : NaN;
  const age = ageMs / 1000;
  feed.age_seconds = Number.isFinite(age) ? Math.max(0, Math.round(age)) : null;
  feed.fresh = Number.isFinite(ageMs) && ageMs >= -5000 &&
    ageMs <= MARKET_STATUS_MAX_AGE_MS;
  if (!feed.fresh) feed.status = "UNKNOWN";
  return snapshot;
}

function quoteSnapshotShapeError(body) {
  if (!Array.isArray(body.quotes) || body.quotes.length > QUOTE_MAX_SYMBOLS) {
    return `quotes must be an array with at most ${QUOTE_MAX_SYMBOLS} rows`;
  }
  if (body.index !== null && body.index !== undefined &&
      (!body.index || typeof body.index !== "object" || Array.isArray(body.index))) {
    return "index must be an object or null";
  }
  if (body.market_feed !== null && body.market_feed !== undefined &&
      (!body.market_feed || typeof body.market_feed !== "object" ||
       Array.isArray(body.market_feed))) {
    return "market_feed must be an object or null";
  }
  const stamps = [];
  for (const [i, row] of body.quotes.entries()) {
    // Owner order 2026-11-09: one zero-volume baseline is published per
    // symbol per day so the day's first print is sided instead of parked in
    // the unclear remainder. It carries no price by definition, so the
    // positive price rule cannot apply to it; the symbol, the source and the
    // stamp still must. Before this, one baseline rejected the whole batch
    // with a 400 and the feed stayed empty for the rest of the day (owner
    // incident 2026-11-10).
    const baseline = row && row.flow_only === true &&
      Number(row.volume) === 0;
    const priced = row && Number.isFinite(row.price) && row.price > 0;
    if (!row || typeof row !== "object" || Array.isArray(row) ||
        !/^[A-Z0-9]{1,12}$/.test(String(row.symbol || "")) ||
        (!priced && !baseline) ||
        typeof row.observed_at !== "string" ||
        !Number.isFinite(Date.parse(row.observed_at))) {
      return `quotes[${i}] requires a valid symbol, positive price and timestamp`;
    }
    if (row.source !== "eClear MKT-FEED REG") {
      return `quotes[${i}] has an unsupported source or timestamp`;
    }
    for (const key of ["bid", "ask", "bid_size", "ask_size",
      "change", "change_pct", "volume", "high", "low"]) {
      if (row[key] !== null && row[key] !== undefined && !Number.isFinite(row[key])) {
        return `quotes[${i}].${key} must be finite or null`;
      }
    }
    if (typeof row.status !== "string") return `quotes[${i}].status must be text`;
    stamps.push(Date.parse(row.observed_at));
  }
  if (body.index !== null && body.index !== undefined &&
      (!body.index || typeof body.index !== "object" || Array.isArray(body.index) ||
       body.index.symbol !== "KSE100" || !Number.isFinite(body.index.value) ||
       !Number.isFinite(body.index.change) || !Number.isFinite(body.index.change_pct) ||
       !Number.isFinite(Date.parse(String(body.index.as_of || ""))))) {
    return "index must contain the broker KSE100 values and source timestamp";
  }
  if (body.market_feed !== null && body.market_feed !== undefined &&
      (!body.market_feed || typeof body.market_feed !== "object" ||
       Array.isArray(body.market_feed) ||
       !(["OPEN", "HALTED", "CLOSED", "UNKNOWN"].includes(body.market_feed.status)) ||
       !Number.isFinite(Date.parse(String(body.market_feed.as_of || ""))))) {
    return "market_feed must contain a recognized status and source timestamp";
  }
  if (typeof body.captured_at !== "string" ||
      !Number.isFinite(Date.parse(body.captured_at))) {
    return "captured_at must be a valid timestamp";
  }
  return null;
}

function normalizeQuoteSnapshot(raw) {
  const quotes = (Array.isArray(raw.quotes) ? raw.quotes : [])
    .filter((row) => row && typeof row === "object")
    .map((row) => ({ ...row }));
  const largePrints = (Array.isArray(raw.large_prints) ? raw.large_prints : [])
    .filter((row) => row && typeof row === "object" &&
      typeof row.symbol === "string" &&
      (row.side === "B" || row.side === "S") &&
      Number.isFinite(Number(row.value_pkr)))
    .slice(-LARGE_PRINT_MAX)
    .map((row) => ({ ...row }));
  const snapshot = {
    quotes,
    index: raw.index && typeof raw.index === "object" ? { ...raw.index } : null,
    market_feed: raw.market_feed && typeof raw.market_feed === "object"
      ? { ...raw.market_feed } : null,
    updated_at: raw.updated_at || raw.captured_at || null,
    flow_day: typeof raw.flow_day === "string" ? raw.flow_day : null,
    large_prints: largePrints,
    large_prints_total: Number.isFinite(Number(raw.large_prints_total))
      ? Math.max(0, Math.round(Number(raw.large_prints_total)))
      : largePrints.length,
  };
  const now = Date.now();
  snapshot.quotes = snapshot.quotes.map((row) => {
    const observedMs = Date.parse(row.observed_at || "");
    const age = now - observedMs;
    // age_seconds is the age of the FRAME the relay holds: it answers "is the
    // feed pushing right now". tick_age_seconds is the age of the exchange's
    // last print for that symbol: it answers "when did this stock last trade".
    // They are not the same number, and a quiet stock can have an old tick on a
    // fresh frame. A desk build needs both to avoid painting a stale last
    // trade as a stalled relay.
    let tickAge = null;
    if (Number.isFinite(observedMs) &&
        /^[0-9]{2}:[0-9]{2}:[0-9]{2}$/.test(String(row.source_tick_time || ""))) {
      const tickAt = tickInstantInDay(karachiView(observedMs),
        row.source_tick_time, null);
      if (Number.isFinite(tickAt)) tickAge = now - tickAt;
    }
    return { ...row,
      age_seconds: Number.isFinite(age) ? Math.max(0, Math.round(age / 1000)) : null,
      tick_age_seconds: Number.isFinite(tickAge)
        ? Math.max(0, Math.round(tickAge / 1000)) : null,
      fresh: Number.isFinite(age) && age >= -5000 && age <= QUOTE_MAX_AGE_MS,
    };
  });
  snapshot.index = snapshot.index ? {
    ...snapshot.index,
    fresh: Number.isFinite(Date.parse(snapshot.index.as_of || "")) &&
      now - Date.parse(snapshot.index.as_of) >= -5000 &&
      now - Date.parse(snapshot.index.as_of) <= QUOTE_MAX_AGE_MS,
  } : null;
  snapshot.market_feed = snapshot.market_feed ? {
    ...snapshot.market_feed,
    fresh: Number.isFinite(Date.parse(snapshot.market_feed.as_of || "")) &&
      now - Date.parse(snapshot.market_feed.as_of) >= -5000 &&
      now - Date.parse(snapshot.market_feed.as_of) <= QUOTE_MAX_AGE_MS,
  } : null;
  const lastAt = Date.parse(snapshot.updated_at || "");
  const snapshotAge = now - lastAt;
  snapshot.stale = !Number.isFinite(lastAt) || snapshotAge < -5000 ||
    snapshotAge > QUOTE_MAX_AGE_MS;
  return snapshot;
}

async function readQuoteSnapshot(env) {
  // One snapshot read a second serves every route on this isolate, so
  // /market, /prices, /stock and /flow can never each buy their own copy
  // with a Durable Object request (owner order 2026-11-05, the budget).
  const stamp = Date.now();
  if (snapshotMemo.value && stamp - snapshotMemo.at < SNAPSHOT_MEMO_MS) {
    return snapshotMemo.value;
  }
  try {
    const stub = quoteHub(env);
    if (!stub) return null;
    const response = await stub.fetch("https://quote-hub/snapshot");
    if (!response.ok) return null;
    const body = await response.json();
    const value = body && body.ok ? normalizeQuoteSnapshot(body) : null;
    if (value) snapshotMemo = { at: Date.now(), value };
    return value;
  } catch (_) {
    return null;
  }
}

// The B/S pair belongs to the frame it was computed from (owner order
// 2026-10-20).
//
// A pushed card carries a split from the moment it was built. Merging a newer
// total onto that old pair printed a frozen buy and sell beside a moving total,
// which is exactly the "the quantities are not moving" the owner reported on
// 2026-10-20: the venv saw CNERGY's B stuck at 1,208,688 while its T climbed
// past 15,000,000. So every merged row recomputes its split from THIS frame,
// and a frame without a measured pair says so instead of inheriting the last
// split forever.
function splitFields(split, quote) {
  const total = Number(quote && quote.volume);
  if (!split) {
    const unclassified = Number.isFinite(total)
      ? Math.max(0, Math.round(total)) : null;
    return {
      buy_volume: null,
      sell_volume: null,
      split_volume: null,
      classified_volume: null,
      unclassified_volume: unclassified,
      flow_complete: unclassified === null ? null : unclassified === 0,
      flow_baseline: null,
      flow_baseline_at: null,
      flow_first_seen_at: null,
      flow_baseline_reason: null,
      split_method: "unavailable",
      split_source: quote
        ? "no measured order-flow pair; the total is unclassified"
        : "no fresh frame for this symbol",
    };
  }
  const classified = Number(split.buy_volume) + Number(split.sell_volume);
  const unclassified = Number.isFinite(total)
    ? Math.max(0, Math.round(total) - Math.round(classified)) : null;
  return {
    buy_volume: split.buy_volume,
    sell_volume: split.sell_volume,
    split_volume: split.split_volume,
    classified_volume: Math.round(classified),
    unclassified_volume: unclassified,
    flow_complete: unclassified === null ? null : unclassified === 0,
    flow_baseline: Number.isFinite(Number(split.flow_baseline))
      ? Math.max(0, Math.round(Number(split.flow_baseline)))
      : null,
    flow_baseline_at: quote && quote.flow_baseline_at
      ? String(quote.flow_baseline_at) : null,
    flow_first_seen_at: quote && quote.flow_first_seen_at
      ? String(quote.flow_first_seen_at) : null,
    flow_baseline_reason: quote && quote.flow_baseline_reason
      ? String(quote.flow_baseline_reason) : null,
    split_method: "quote_rule",
    split_source: split.split_source ||
      "every volume increment sided by the wire's own bid/ask at the poll",
  };
}

function quoteDay(quote) {
  const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
  return Number.isFinite(at) ? dayStamp(karachiView(at)) : null;
}

function largeStatsBySymbol(prints, day) {
  const stats = new Map();
  for (const print of Array.isArray(prints) ? prints : []) {
    if (!print || print.day !== day) continue;
    const symbol = String(print.symbol || "").toUpperCase();
    if (!symbol) continue;
    const current = stats.get(symbol) || {
      symbol, buy_count: 0, buy_shares: 0, buy_value_pkr: 0,
      sell_count: 0, sell_shares: 0, sell_value_pkr: 0,
      largest_buy_pkr: 0, largest_sell_pkr: 0, last_at: null,
    };
    const shares = Math.max(0, Math.round(Number(print.shares) || 0));
    const value = Math.max(0, Math.round(Number(print.value_pkr) || 0));
    if (print.side === "S") {
      current.sell_count += 1;
      current.sell_shares += shares;
      current.sell_value_pkr += value;
      current.largest_sell_pkr = Math.max(current.largest_sell_pkr, value);
    } else {
      current.buy_count += 1;
      current.buy_shares += shares;
      current.buy_value_pkr += value;
      current.largest_buy_pkr = Math.max(current.largest_buy_pkr, value);
    }
    const at = String(print.at || "");
    if (at && (!current.last_at || at > current.last_at)) current.last_at = at;
    stats.set(symbol, current);
  }
  return stats;
}

// The complete KMIALL order-flow answer. This is a pure read of the durable
// snapshot: no portal fetch, no ACK write, no app poll can spend the day's
// Durable Objects write budget by asking for the whole table.
async function flowAnswer(env, now) {
  const snapshot = await readQuoteSnapshot(env);
  const k = karachiView(now.getTime());
  const tradingToday = isTradingDay(k);
  const today = dayStamp(k);
  if (!snapshot) {
    return {
      ok: true, day: tradingToday ? today : null, as_of: null,
      counts: { universe: 0, included: 0, missing: 0, fresh: 0 },
      totals: { volume: 0, buy: 0, sell: 0, unclassified: 0 },
      rows: [], missing: [],
      large: { threshold_pkr: LARGE_PRINT_PKR, total: 0, shown: 0,
        truncated: false, prints: [], stocks: [] },
      basis: {
        split: "no quote snapshot yet",
        unclassified: "nothing observed yet",
        large: "no quote snapshot yet",
      },
    };
  }
  // On a trading day the answer is today's regular-session frames. Outside
  // a trading day it is the last session the hub holds, never a made-up day.
  const day = tradingToday ? today
    : (snapshot.flow_day || quoteDay((snapshot.quotes || [])[0]) || null);
  const universe = new Set(KMIALL_UNIVERSE);
  const seenSymbols = new Set();
  const allRows = Array.from(newestQuoteRows(snapshot.quotes).values());
  const largePrints = Array.isArray(snapshot.large_prints)
    ? snapshot.large_prints : [];
  const largeStats = largeStatsBySymbol(largePrints, day);
  const rows = [];
  const missing = [];
  let buyTotal = 0;
  let sellTotal = 0;
  let volumeTotal = 0;
  let unclassifiedTotal = 0;
  for (const quote of allRows) {
    const symbol = String(quote && quote.symbol || "").toUpperCase();
    if (symbol) seenSymbols.add(symbol);
    if (!quote || !Number.isFinite(Number(quote.price)) ||
        Number(quote.price) <= 0) continue;
    if (day && quoteDay(quote) !== day) {
      missing.push({
        symbol,
        last_observed_at: quote.observed_at || null,
        last_day: quoteDay(quote),
        reason: "no observed regular-session frame for this day",
      });
      continue;
    }
    const volume = Number.isFinite(Number(quote.volume))
      ? Math.max(0, Math.round(Number(quote.volume))) : null;
    const split = splitFromQuote(quote);
    const buy = split ? Math.max(0, Math.round(Number(split.buy_volume))) : null;
    const sell = split ? Math.max(0, Math.round(Number(split.sell_volume))) : null;
    const classified = buy !== null && sell !== null ? buy + sell : null;
    const unclassified = volume !== null
      ? (classified !== null ? Math.max(0, volume - classified) : volume)
      : null;
    const buyShare = classified && buy !== null
      ? Math.round((10000 * buy) / classified) / 100 : null;
    const sellShare = classified && sell !== null
      ? Math.round((10000 * sell) / classified) / 100 : null;
    const bid = Number.isFinite(Number(quote.bid)) ? Number(quote.bid) : null;
    const ask = Number.isFinite(Number(quote.ask)) ? Number(quote.ask) : null;
    const bidSize = quote.bid_size === null || quote.bid_size === undefined
      ? null
      : (Number.isFinite(Number(quote.bid_size)) ? Number(quote.bid_size) : null);
    const askSize = quote.ask_size === null || quote.ask_size === undefined
      ? null
      : (Number.isFinite(Number(quote.ask_size)) ? Number(quote.ask_size) : null);
    const large = largeStats.get(String(quote.symbol || "").toUpperCase()) || {};
    rows.push({
      symbol: String(quote.symbol || "").toUpperCase(),
      price: Number(quote.price),
      bid,
      ask,
      bid_size: bidSize,
      ask_size: askSize,
      spread: bid !== null && ask !== null && ask >= bid
        ? Math.round((ask - bid) * 10000) / 10000 : null,
      change_pct: Number.isFinite(Number(quote.change_pct))
        ? Number(quote.change_pct) : null,
      high: Number.isFinite(Number(quote.high)) ? Number(quote.high) : null,
      low: Number.isFinite(Number(quote.low)) ? Number(quote.low) : null,
      volume,
      buy_volume: buy,
      sell_volume: sell,
      classified_volume: classified,
      unclassified_volume: unclassified,
      flow_baseline: split && Number.isFinite(Number(split.flow_baseline))
        ? Math.max(0, Math.round(Number(split.flow_baseline))) : null,
      flow_baseline_at: quote.flow_baseline_at || null,
      flow_first_seen_at: quote.flow_first_seen_at || null,
      flow_baseline_reason: quote.flow_baseline_reason || null,
      buy_share_pct: buyShare,
      sell_share_pct: sellShare,
      flow_complete: unclassified === null ? null : unclassified === 0,
      split_method: split ? "quote_rule" : "unavailable",
      split_source: split
        ? (split.split_source ||
           "every volume increment sided by the wire's own bid/ask")
        : "no measured order-flow pair; the total is unclassified",
      observed_at: quote.observed_at || null,
      age_seconds: Number.isFinite(Number(quote.age_seconds))
        ? Math.max(0, Math.round(Number(quote.age_seconds))) : null,
      tick_age_seconds: Number.isFinite(Number(quote.tick_age_seconds))
        ? Math.max(0, Math.round(Number(quote.tick_age_seconds))) : null,
      fresh: Boolean(quote.fresh),
      status: quote.status || null,
      source_tick_time: quote.source_tick_time || null,
      flow_rules: quote.flow_rules && typeof quote.flow_rules === "object"
        ? quote.flow_rules : null,
      large_buy_count: large.buy_count || 0,
      large_buy_shares: large.buy_shares || 0,
      large_buy_value_pkr: large.buy_value_pkr || 0,
      large_sell_count: large.sell_count || 0,
      large_sell_shares: large.sell_shares || 0,
      large_sell_value_pkr: large.sell_value_pkr || 0,
      largest_buy_pkr: large.largest_buy_pkr || 0,
      largest_sell_pkr: large.largest_sell_pkr || 0,
      last_large_at: large.last_at || null,
    });
    if (volume !== null) volumeTotal += volume;
    if (buy !== null) buyTotal += buy;
    if (sell !== null) sellTotal += sell;
    if (unclassified !== null) unclassifiedTotal += unclassified;
  }
  for (const symbol of universe) {
    if (seenSymbols.has(symbol)) continue;
    missing.push({
      symbol,
      last_observed_at: null,
      last_day: null,
      reason: "no quote frame for this day",
    });
  }
  rows.sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol));
  const dayPrints = largePrints
    .filter((print) => print && print.day === day)
    .sort((a, b) => String(b.at || "").localeCompare(String(a.at || "")));
  const prints = dayPrints.map((print) => ({
    symbol: print.symbol,
    side: print.side === "S" ? "SELL" : "BUY",
    shares: Math.round(Number(print.shares) || 0),
    price: Number(print.price),
    value_pkr: Math.round(Number(print.value_pkr) || 0),
    at: print.at || null,
    tick: print.tick || null,
    rule: print.rule || null,
  }));
  const stocks = Array.from(largeStats.values())
    .map((row) => ({ ...row,
      total_value_pkr: row.buy_value_pkr + row.sell_value_pkr,
    }))
    .sort((a, b) => (b.total_value_pkr - a.total_value_pkr) ||
      a.symbol.localeCompare(b.symbol));
  const newest = rows.map((row) => row.observed_at).filter(Boolean).sort().pop();
  return {
    ok: true,
    day,
    as_of: newest || snapshot.updated_at || null,
    counts: {
      universe: universe.size,
      included: rows.length,
      missing: missing.length,
      fresh: rows.filter((row) => row.fresh).length,
    },
    totals: {
      volume: volumeTotal,
      buy: buyTotal,
      sell: sellTotal,
      unclassified: unclassifiedTotal,
    },
    rows,
    missing,
    large: {
      threshold_pkr: LARGE_PRINT_PKR,
      total: Number(snapshot.large_prints_total) || dayPrints.length,
      shown: prints.length,
      truncated: (Number(snapshot.large_prints_total) || dayPrints.length) > prints.length,
      prints,
      stocks,
    },
    basis: {
      split: "quote_rule: every observed increment of the venue counter is sided once by the bid/ask of the frame that carried it; buy and sell never decrease",
      coverage: "regular-session frames for the named Karachi day; a symbol with no frame that day appears in missing, never with an invented number",
      unclassified: "shares traded before the capture or hub first observed the symbol, plus increments the wire did not decide; they are reported separately and never guessed into buy or sell",
      large: "one relay update carrying at least PKR 10,000,000 on one side; the broker wire has no individual order id, so this is a large observed increment, not a claimed order ticket",
    },
  };
}

async function applyLiveQuotes(env, snapshot, quotes, now, ackDay) {
  if (!quotes) return refreshMarketFeed(snapshot, now);
  const freshQuotes = quotes.quotes.filter((row) => row.fresh &&
    Number.isFinite(row.price) && row.price > 0);
  if (freshQuotes.length) {
    // One frame per symbol, the newest the hub holds (owner order
    // 2026-11-01): a retried push can never answer the card with an older
    // price than /stock and /prices read for the same scrip.
    const liveBySymbol = newestQuoteRows(freshQuotes);
    // The card answers the live ranking as one set. A cached portal leader
    // must not sit beside fresh quote rows: when the base card is a few
    // minutes old, that produced the visible twenty second lag (fresh prices
    // moving while one leader stayed on its old stamp). If a symbol has no
    // fresh quote it is not a current leader and waits for its next frame.
    const merged = [];
    for (const quote of liveBySymbol.values()) {
      if (!Number.isFinite(quote.volume) || quote.volume <= 0) continue;
      const volume = quote.volume;
      const split = splitFromQuote(quote);
      merged.push({
        ...quote,
        volume,
        ...splitFields(split, quote),
        feed_as_of: quote.observed_at,
        feed_age_seconds: quote.age_seconds,
        feed_tick_age_seconds: quote.tick_age_seconds,
        observed_at: quote.observed_at,
        source_tick_time: quote.source_tick_time,
        quote_fresh: true,
        quote_source: quote.source,
        basis: "current session volume (fresh eClear REG quote)",
      });
    }
    // The card's as_of is the clock a reader sees, so it is the newest frame
    // in this answer, never the build time of the pushed body: a body built
    // five minutes ago sitting behind a two second old quote stamped the
    // screen 10:20:00 while its numbers were current (owner order 2026-10-20).
    const newest = freshQuotes.map((row) => row.observed_at)
      .filter((at) => typeof at === "string" && at)
      .sort()
      .pop();
    const stamp = (quotes.index && quotes.index.fresh && quotes.index.as_of)
      || newest || quotes.updated_at;
    if (stamp) snapshot.as_of = stamp;
    snapshot.top_volume = merged
      .filter((row) => Number.isFinite(row.volume) && row.volume > 0)
      .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
      .slice(0, MARKET_TOP_N);
    snapshot.top_volume_basis = snapshot.top_volume.length
      ? `current session volume, top ${snapshot.top_volume.length} from fresh REG feed`
      : snapshot.top_volume_basis;
    snapshot.volume_split_basis = splitLabel(snapshot.top_volume || []);
    // Every displayed value has now come from a live frame, so the older
    // portal cache must not mark the answer stale.
    snapshot.stale = false;
  } else if (snapshot.top_volume) {
    // Owner order 2026-10-31: with no fresh frames, the card answers from
    // the hub's own LAST PUBLISHED REGULAR-session frames of today, the
    // same frames /stock and /prices answer from, instead of the portal
    // cache's separate copy. One frame, one answer, every surface.
    const todayFrames = Array.from(newestQuoteRows(quotes.quotes).values())
      .filter((row) =>
      quoteIsFromToday(row) && Number.isFinite(row.price) && row.price > 0 &&
      Number.isFinite(row.volume) && row.volume > 0);
    if (todayFrames.length) {
      snapshot.top_volume = todayFrames.map((row) => {
        const split = splitFromQuote(row);
        return {
          symbol: row.symbol,
          volume: Math.round(row.volume),
          price: row.price,
          change_pct: Number.isFinite(row.change_pct) ? row.change_pct : null,
          ...splitFields(split, row),
          basis: row.fresh
            ? "current session volume (fresh eClear REG quote)"
            : "the symbol's last published regular-session frame",
          feed_as_of: row.observed_at,
          feed_age_seconds: row.age_seconds,
          feed_tick_age_seconds: row.tick_age_seconds,
          observed_at: row.observed_at,
          source_tick_time: row.source_tick_time,
          tick_age_seconds: row.tick_age_seconds,
          quote_fresh: Boolean(row.fresh),
          quote_source: row.source,
        };
      })
        .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
        .slice(0, MARKET_TOP_N);
      snapshot.top_volume_basis = snapshot.top_volume.length
        ? `the last published regular-session frames, top ${snapshot.top_volume.length}`
        : snapshot.top_volume_basis;
      snapshot.volume_split_basis = splitLabel(snapshot.top_volume || []);
    }
  }
  if (quotes.index && quotes.index.fresh) {
    snapshot.index = quotes.index;
  }
  if (quotes.market_feed && quotes.market_feed.fresh) {
    snapshot.market_feed = quotes.market_feed;
  }
  snapshot.quote_snapshot_updated_at = quotes.updated_at;
  snapshot.quote_snapshot_stale = quotes.stale;
  // The acknowledged store: the card's own top rows are candidates, and
  // every answered row then reads the SAME stored pair /stock reads, so
  // the two surfaces can never disagree and the printed B and S only
  // move as the day's own volume grows (owner order 2026-10-31).
  if (snapshot.top_volume && snapshot.top_volume.length && ackDay) {
    // Read only (owner order 2026-11-05, the daily Durable Object budget):
    // a display poll applies the day's acknowledged rows and never writes
    // one, so a phone tick cannot spend the mirror's write budget.
    const storedRows = await ackRowsForDay(env, ackDay);
    if (storedRows) {
      snapshot.top_volume = snapshot.top_volume.map(
          (row) => applyStoredFrame(row, storedRows[row.symbol]))
        .filter((row) => Number.isFinite(row.volume) && row.volume > 0)
        .sort((a, b) => (b.volume - a.volume) ||
          a.symbol.localeCompare(b.symbol))
        .slice(0, MARKET_TOP_N);
    }
  }
  return refreshMarketFeed(snapshot, now);
}

async function marketResponseSnapshot(env, now, ctx) {
  const k = karachiView(now.getTime());
  const ackDay = isTradingDay(k) ? dayStamp(k) : null;
  let snapshot;
  try {
    snapshot = await marketSnapshot(env, now, ctx);
  } catch (e) {
    const fallback = await kvGet(env, "MARKET");
    if (!fallback) throw e;
    snapshot = normalizeMarket(JSON.parse(fallback));
    snapshot.stale = true;
    snapshot.market_open = marketOpenNow(now);
    snapshot.market_state = marketState(now);
  }
  return applyLiveQuotes(env, snapshot, await readQuoteSnapshot(env), now,
    ackDay);
}

async function trackMarketTransitions(env, snapshot, now, ctx) {
  // Owner order 2026-11-05 (the daily Durable Object budget): a transition
  // is an edge, not a per-second fact, so one answer serves twenty seconds
  // of one-second polls instead of one state read and write per poll.
  const stamp = Date.now();
  if (transitionMemo.value && stamp - transitionMemo.at < TRANSITION_MEMO_MS) {
    return transitionMemo.value;
  }
  const value = await computeMarketTransitions(env, snapshot, now, ctx);
  transitionMemo = { at: stamp, value };
  return value;
}

async function computeMarketTransitions(env, snapshot, now, ctx) {
  const edge = marketState(now);
  if (!edge.trading_day) {
    return { state: null, evidence: "outside_trading_day", delivered: false };
  }

  // The scheduled session law decides Friday's break and the final close.
  // Within an open band, only a fresh REG market-wide broker status can
  // confirm OPEN or HALTED; missing/stale frames and per-symbol SUS flags
  // never become a market-wide transition.
  let state = null;
  let evidence = "session_schedule";
  if (edge.condition === "BREAK") {
    state = "BREAK";
  } else if (edge.phase === "POST_CLOSE") {
    state = "CLOSED";
  } else if (edge.market_open) {
    const feed = refreshMarketFeed({ market_feed: snapshot && snapshot.market_feed }, now)
      .market_feed;
    if (!feed.fresh || (feed.status !== "OPEN" && feed.status !== "HALTED")) {
      return { state: null, evidence: "no_fresh_market_wide_feed", delivered: false };
    }
    state = feed.status;
    evidence = "fresh_broker_market_status";
  } else if (edge.phase === "PRE_OPEN") {
    // The scheduled close wake can arrive just after the edge. Emit CLOSED
    // only when a session close occurred within the grace interval; this avoids
    // morning greetings and duplicate Friday break notices.
    const todaysBands = edge.bands || [];
    const lastBand = todaysBands[todaysBands.length - 1];
    const closeAt = lastBand
      ? Date.parse(`${edge.date}T${lastBand.close}:00+05:00`) : NaN;
    const sessionJustClosed = Number.isFinite(closeAt) &&
      now.getTime() >= closeAt && now.getTime() - closeAt <= MARKET_OPEN_GRACE_MS;
    if (!sessionJustClosed) {
      return { state: null, evidence: "no_session_transition", delivered: false };
    }
    state = "CLOSED";
  } else {
    return { state: null, evidence: "no_session_transition", delivered: false };
  }  const day = edge.date;
  const identity = `${day}:${state}`;
  let previous = null;
  const raw = await kvGet(env, MARKET_STATE_KEY);
  try {
    previous = raw ? JSON.parse(raw) : null;
  } catch (_) {
    previous = null;
  }
  if (previous && previous.identity === identity) {
    return { state, evidence, delivered: false, duplicate: true };
  }

  const oldState = previous && previous.state;
  const oldDay = previous && typeof previous.identity === "string"
    ? previous.identity.slice(0, 10) : "";
  const bandOpen = edge.live_band && edge.live_band.open;
  const openAt = bandOpen ? Date.parse(`${day}T${bandOpen}:00+05:00`) : NaN;
  const withinOpeningGrace = Number.isFinite(openAt) &&
    now.getTime() >= openAt && now.getTime() - openAt <= MARKET_OPEN_GRACE_MS;
  const shouldNotify = (state === "BREAK" || state === "CLOSED"
    ? oldState !== state || (!previous && evidence === "session_schedule" &&
      (state === "BREAK" ||
       (Number.isFinite(openAt) && now.getTime() - openAt <= MARKET_OPEN_GRACE_MS)))
    : state === "HALTED"
      // Owner order 2026-10-20 (third note): a halt is drawn on the card but
      // is not one of the four notification events.
      ? false
      : oldState === "HALTED" || oldState === "BREAK" || oldState === "CLOSED" ||
        (oldDay !== "" && oldDay !== day) || (!previous && withinOpeningGrace));
  if (!shouldNotify) {
    // Seed a baseline when first observing OPEN after the opening grace. This
    // prevents a later app launch from replaying a greeting hours late.
    if (state === "OPEN") {
      await kvPut(env, MARKET_STATE_KEY, JSON.stringify({
        state, identity, confirmed_at_ms: now.getTime(), evidence,
      }), { expirationTtl: 604800 });
    }
    return { state, evidence, delivered: false, baseline: true };
  }
  // Owner order 2026-10-29: no chat send exists any more. Owner order
  // 2026-10-31: the market open/close/break emails are retired entirely,
  // so a transition records only its confirmed state and delivers
  // nothing anywhere.
  await kvPut(env, MARKET_STATE_KEY, JSON.stringify({
    state, identity, confirmed_at_ms: now.getTime(), evidence,
  }), { expirationTtl: 604800 });
  return { state, evidence, delivered: false, retired: "email" };
}

// A pushed snapshot must carry the two fields the card renders, so an agent
// that pushes a partial body is told so instead of blanking the app.
function snapshotShapeError(body) {
  if (!("index" in body)) return "snapshot is missing index";
  if (!(body.index === null || (typeof body.index === "object" &&
                                !Array.isArray(body.index)))) {
    return "index must be an object or null";
  }
  if (!("top_volume" in body)) return "snapshot is missing top_volume";
  if (!(body.top_volume === null || Array.isArray(body.top_volume))) {
    return "top_volume must be an array or null";
  }
  return null;
}

// The portal snapshot is rebuilt behind the response, never in front of it.
// The portal fetches can each spend nine seconds waiting for an exchange site
// that is slow or unreachable. Doing that synchronously when the five minute
// cache expires made an app poll arrive almost twenty seconds late. The cached
// copy is answered at once; the next build is a single shared background task.
let marketRefreshInFlight = null;

async function refreshMarketSnapshot(env, now) {
  if (marketRefreshInFlight) return marketRefreshInFlight;
  marketRefreshInFlight = (async () => {
    try {
      const fresh = normalizeMarket(await buildMarketSnapshot(env, now));
      fresh.built_at = now.toISOString();
      fresh.cache_age_seconds = 0;
      await kvPut(env, "MARKET", JSON.stringify(fresh), { expirationTtl: 3600 });
      return fresh;
    } catch (_) {
      return null;
    } finally {
      marketRefreshInFlight = null;
    }
  })();
  return marketRefreshInFlight;
}

// A cold cache still answers immediately. Live quote rows from the durable hub
// fill the card while this portal ranking rebuilds in the background.
function blankMarketSnapshot(now) {
  const k = karachiView(now.getTime());
  return {
    as_of: `${dayStamp(k)}T${hhmm(k)}:00+05:00`,
    date: dayStamp(k),
    timezone: "Asia/Karachi",
    market_open: marketOpenNow(now),
    market_state: marketState(now),
    index: null,
    kmiall_members: 0,
    top_volume: null,
    top_volume_basis: "the ranking is rebuilding from the exchange portal; live quotes are served from the broker feed",
    volume_split_basis: "no portal ranking yet",
    notes: ["the ranking is rebuilding from the exchange portal"],
    market_feed: { status: "UNKNOWN", raw_status: null, as_of: null,
      age_seconds: null, source: "eClear REG market feed", fresh: false },
  };
}

async function marketSnapshot(env, now, ctx) {
  const cachedRaw = await kvGet(env, "MARKET");
  if (cachedRaw) {
    try {
      const cached = JSON.parse(cachedRaw);
      const built = Date.parse(cached.built_at || "");
      if (Number.isFinite(built) && now.getTime() - built < MARKET_TTL_MS) {
        cached.market_open = marketOpenNow(now); // always current
        cached.market_state = marketState(now);  // phase, break, next edge
        cached.cache_age_seconds = Math.round((now.getTime() - built) / 1000);
        // A pushed snapshot lives in this key too, so normalize whatever
        // came back before the app sees it.
        return normalizeMarket(cached);
      }
      cached.market_open = marketOpenNow(now);
      cached.market_state = marketState(now);
      cached.cache_age_seconds = Number.isFinite(built)
        ? Math.round((now.getTime() - built) / 1000) : null;
      cached.stale = true;
      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(refreshMarketSnapshot(env, now));
      }
      return normalizeMarket(cached);
    } catch (_) {
      // malformed cache: schedule a rebuild and answer from live quotes now
    }
  }
  if (ctx && typeof ctx.waitUntil === "function") {
    ctx.waitUntil(refreshMarketSnapshot(env, now));
  }
  return normalizeMarket(blankMarketSnapshot(now));
}

function pktInstant(k, hm) {
  return new Date(`${dayStamp(k)}T${pad(hm[0])}:${pad(hm[1])}:00+05:00`);
}

// Band aware: a Friday has FOUR edges (two opens, two closes), so the break
// shows as a CLOSE at 12:00 and an OPEN at 14:32 rather than one long day.
function nextEvent(nowUtc) {
  for (let offset = 0; offset < 10; offset++) {
    const probe = karachiView(nowUtc.getTime() + offset * 86400000);
    for (const band of bandsFor(probe)) {
      const o = pktInstant(probe, band[0]);
      const c = pktInstant(probe, band[1]);
      if (o.getTime() > nowUtc.getTime()) return { event: "OPEN", at: o };
      if (c.getTime() > nowUtc.getTime()) return { event: "CLOSE", at: c };
    }
  }
  return { event: null, at: null };
}

function adminOk(request, env) {
  const got = request.headers.get("x-admin-token") || "";
  return env.RELAY_ADMIN_TOKEN && got === env.RELAY_ADMIN_TOKEN;
}

async function healthPayload(env) {
  const now = new Date();
  const k = karachiView(now.getTime());
  const next = nextEvent(now);
  let marketFeed = null;
  try {
    const cachedMarket = await kvGet(env, "MARKET");
    if (cachedMarket) {
      const parsed = JSON.parse(cachedMarket);
      marketFeed = parsed.market_feed || null;
    }
  } catch (_) {
    marketFeed = null;
  }
  // The punctual band dispatch is a backup path that fails SILENTLY by
  // design: a bad or read-only token answers 401/403 inside a cron and no
  // workflow is created, so a dead dispatch looks exactly like a scheduler
  // that never fired (measured 2026-10-30, both Friday wakes left no run).
  // The note was already recorded; put it on /health so the owner, the app
  // and an agent can see WHY the backup did not start a band. Safe fields
  // only: the record holds no token.
  let lastDispatch = null;
  try {
    const raw = await kvGet(env, "SCAN:DISPATCH:LAST");
    if (raw) {
      const note = JSON.parse(raw);
      lastDispatch = {
        at: note.at || null,
        band: note.band || null,
        source: note.source || "cron",
        ok: Boolean(note.ok),
        status: note.status || 0,
        detail: String(note.detail || "").slice(0, 200),
      };
    }
  } catch (_) {
    lastDispatch = null;
  }
  let flowError = null;
  try {
    const rawFlowError = await quoteHubValue(env, "FLOW:LAST_ERROR");
    if (rawFlowError) flowError = JSON.parse(rawFlowError);
  } catch (_) {
    flowError = null;
  }
  let flowBudget = null;
  try {
    const rawFlowBudget = await quoteHubValue(env, "FLOW:STATS");
    if (rawFlowBudget) flowBudget = JSON.parse(rawFlowBudget);
  } catch (_) {
    flowBudget = null;
  }
  // Owner order 2026-11-05: when the day's rows-written budget or any
  // storage error makes the hub hold the snapshot in memory alone, the
  // card keeps answering fresh numbers and /health says why, so a
  // degraded-but-alive day can never look like a healthy one (SO-3).
  let snapshotPersistError = null;
  try {
    const rawPersistError = await quoteHubValue(env, "SNAPSHOT:PERSIST_ERROR");
    if (rawPersistError) snapshotPersistError = JSON.parse(rawPersistError);
  } catch (_) {
    snapshotPersistError = null;
  }
  return {
    ok: true,
    service: "quant-of-rehan-relay",
    flow_last_error: flowError,
    flow_budget: flowBudget,
    snapshot_persist_error: snapshotPersistError,
    // The commit this script was built from. The deploy workflow sets it from
    // GITHUB_SHA and then asks /health for it, so a deploy that uploaded
    // nothing (or uploaded to another account) cannot pass as a success.
    // Empty when the worker was uploaded outside CI.
    version: env.WORKER_VERSION || null,
    karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
    // The app shows ONLINE only while a session is live, so the state is
    // answered by the same session law the notifications use (SO-8).
    // `market_state.phase` is the authoritative word (OPEN, BREAK, CLOSED,
    // PRE_OPEN, POST_CLOSE); `market_open` is kept for older clients and is
    // exactly `phase === "OPEN"`.
    market_open: marketOpenNow(now),
    market_state: marketState(now),
    // Separately sourced from a fresh REG market-wide MKT-STATS frame in the
    // latest card push; null/unknown never means the session clock is halted.
    market_feed: refreshMarketFeed({ market_feed: marketFeed }, now).market_feed,
    last_dispatch: lastDispatch,
    next_event: next.event
      ? { event: next.event, at_pk: `${dayStamp(karachiView(next.at.getTime()))} ${hhmm(karachiView(next.at.getTime()))}` }
      : null,
  };
}function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "content-type": "application/json",
      "cache-control": "no-store", ...extraHeaders },
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;

    // /health and /status are the same answer under two names. The owner's
    // interface list for the phone app names /status, /market and /signals;
    // /status did not exist (a GET answered {"error":"not found"}), so a
    // client built to that list had nothing to read. Served from one function
    // so the two names cannot drift apart.
    if (request.method === "GET" &&
        (path === "/health" || path === "/status")) {
      return json(await healthPayload(env));
    }

    if (request.method === "POST" && path === "/notify") {
      // Owner order 2026-10-29: the chat channel is retired (the owner's
      // account and bot no longer exist). The route answers 410 so a
      // straggling sender records the delivery it did NOT get, instead of an
      // "accepted" message that never arrived anywhere. Every notification
      // now travels on the owner email channel (src/notify/owner_email.py)
      // from the Actions jobs, which dedupe per marker in the issue ledger.
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      return json({
        ok: false, retired: "email",
        error: "notifications are carried by the owner email issue from the Actions jobs; this route sends nothing",
      }, 410);
    }

    if (request.method === "OPTIONS" &&
        (path === "/quotes" || path === "/quotes/stream" ||
         path === "/history" || path === "/bars" ||
         path === "/flow" || path === "/orderflow")) {
      return new Response(null, { status: 204, headers: {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "content-type",
        "access-control-max-age": "86400",
      } });
    }

    if (request.method === "GET" && path === "/quotes/stream") {
      if (url.searchParams.has("symbol")) {
        const requested = String(url.searchParams.get("symbol") || "").toUpperCase();
        if (!/^[A-Z0-9]{1,12}$/.test(requested)) {
          return json({ ok: false, error: "invalid symbol" }, 400);
        }
      }
      const hub = quoteHub(env);
      if (!hub) return json({ ok: false, error: "quote hub not configured" }, 503);
      const response = await hub.fetch(new Request("https://quote-hub/stream", request));
      if (response.status === 101) return response;
      return new Response(response.body, {
        status: response.status,
        headers: {
          ...Object.fromEntries(response.headers),
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        },
      });
    }

    if (request.method === "GET" &&
        (path === "/flow" || path === "/orderflow")) {
      // Owner order 2026-11-04: the complete KMIALL order flow and the
      // large-print board live on the relay. The owner's own desktop build
      // reads this answer; the phone does not need a new screen. This is a
      // pure read of the durable snapshot, so polling it can never spend
      // the Durable Objects write budget.
      return json(await flowAnswer(env, new Date()), 200, {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      });
    }

    if (request.method === "GET" && path === "/history") {
      // Owner order 2026-11-07: the owner's desktop build draws a full-day
      // candlestick chart per scrip, and its own sample buffer holds only
      // about five minutes. This route serves the relay's minute bars, built
      // inside the quote hub from the accepted one-second feed. It is a pure
      // read: no store write happens here, and an empty day is answered as
      // empty with a reason rather than filled with invented prices (SO-3).
      const resolution = String(url.searchParams.get("resolution") || "1m");
      const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      const day = String(url.searchParams.get("day") || "");
      if (resolution !== "1m") {
        return json({ ok: false, error: "resolution must be 1m" }, 400, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      if (symbol && !/^[A-Z0-9]{1,12}$/.test(symbol)) {
        return json({ ok: false, error: "invalid symbol" }, 400, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      if (day && !/^\d{4}-\d{2}-\d{2}$/.test(day)) {
        return json({ ok: false, error: "day must be YYYY-MM-DD" }, 400, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      const askedRaw = url.searchParams.get("limit");
      const asked = askedRaw === null ? NaN : Number(askedRaw);
      const limit = Number.isFinite(asked)
        ? Math.max(1, Math.min(HISTORY_MAX_BARS, Math.round(asked)))
        : HISTORY_DEFAULT_BARS;
      // A chart redraw is not a new question. This isolate answers the same
      // symbol, day and limit from its own memory for five seconds, so a
      // desktop repainting a candle cannot spend a Durable Object request a
      // frame (owner order 2026-11-05, the budget).
      const cacheKey = `${symbol}|${day}|${limit}|${resolution}`;
      const stamp = Date.now();
      const memo = historyMemo.get(cacheKey);
      if (memo && stamp - memo.at < HISTORY_MEMO_MS) {
        return json(memo.body, 200, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      const hub = quoteHub(env);
      if (!hub) {
        return json({ ok: false, error: "quote hub not configured" }, 503, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      const query = new URLSearchParams({ resolution, limit: String(limit) });
      if (symbol) query.set("symbol", symbol);
      if (day) query.set("day", day);
      const answer = await hub.fetch("https://quote-hub/history?" + query.toString());
      const body = await answer.json().catch(() => ({
        ok: false, error: "quote hub answered invalid JSON",
      }));
      if (answer.ok && body && body.ok) {
        if (historyMemo.size >= HISTORY_MEMO_MAX) historyMemo.clear();
        historyMemo.set(cacheKey, { at: stamp, body });
      }
      return json(body, answer.ok ? 200 : answer.status, {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      });
    }

    if (request.method === "GET" && path === "/bars") {
      // Owner order 2026-11-07: the desktop draws KSE100, KMIALLSHR and every
      // KMIALL scrip on ten frames. This route is the one chart answer; it is
      // public and read-only, and the hub does every aggregation so a repaint
      // can never cost one Durable Object request per candle.
      const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      const tf = String(url.searchParams.get("tf") || "1m");
      const headers = {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      };
      if (!symbol || !/^[A-Z0-9]{1,12}$/.test(symbol)) {
        return json({ ok: false, error: "invalid symbol" }, 400, headers);
      }
      if (!BAR_TFS.includes(tf)) {
        return json({ ok: false, error: "tf must be one of " + BAR_TFS.join(", "),
          supported: BAR_TFS }, 400, headers);
      }
      const askedDays = Number(url.searchParams.get("days"));
      const days = Number.isFinite(askedDays)
        ? Math.max(1, Math.min(BARS_MAX_DAYS, Math.round(askedDays)))
        : BARS_MAX_DAYS;
      const askedLimit = Number(url.searchParams.get("limit"));
      const limit = Number.isFinite(askedLimit)
        ? Math.max(1, Math.min(BARS_MAX, Math.round(askedLimit)))
        : BARS_DEFAULT;
      const key = `${symbol}|${tf}|${days}|${limit}`;
      const stamp = Date.now();
      const memo = barsMemo.get(key);
      if (memo && stamp - memo.at < BARS_MEMO_MS) {
        return json(memo.body, 200, headers);
      }
      const hub = quoteHub(env);
      if (!hub) return json({ ok: false, error: "quote hub not configured" }, 503, headers);
      const answer = await hub.fetch("https://quote-hub/bars?" + new URLSearchParams({
        symbol, tf, days: String(days), limit: String(limit),
      }).toString());
      const body = await answer.json().catch(() => ({
        ok: false, error: "quote hub answered invalid JSON",
      }));
      if (answer.ok && body && body.ok) {
        if (barsMemo.size >= 64) barsMemo.clear();
        barsMemo.set(key, { at: stamp, body });
      }
      return json(body, answer.ok ? 200 : answer.status, headers);
    }

    if (request.method === "GET" && path === "/sectors") {
      // Every KMIALL scrip's sector, grouped and filtered on the relay: the
      // phone never receives a scrip outside the universe (2026-11-06).
      return json(await sectorsAnswer(), 200, {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      });
    }

    if (request.method === "GET" && path === "/quotes") {

      const snapshot = await readQuoteSnapshot(env);
      if (snapshot) {
        // This is the whole-feed view a phone can poll without the card. It
        // must carry the same buy/sell pair the card serves, not just the raw
        // quote, or a reader of this route alone sees no order flow at all.
        snapshot.quotes = (Array.isArray(snapshot.quotes) ? snapshot.quotes : [])
          .map((row) => ({
            ...row,
            ...splitFields(splitFromQuote(row), row),
          }));
      }
      const symbol = String(url.searchParams.get("symbol") || "").trim().toUpperCase();
      if (snapshot && symbol) {
        snapshot.quotes = snapshot.quotes.filter((row) => row.symbol === symbol);
      }
      return json({ ok: true,
        ...(snapshot || { quotes: [], index: null, market_feed: null,
          updated_at: null, stale: true }),
        source: "eClear broker feed" }, 200, {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      });
    }

    if (request.method === "POST" && path === "/quotes") {

      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const rawBody = await request.text();
      if (new TextEncoder().encode(rawBody).byteLength > QUOTE_MAX_BODY_BYTES) {
        return json({ ok: false, error: "quote update exceeds size limit" }, 413);
      }
      let body = null;
      try { body = JSON.parse(rawBody); } catch (_) { body = null; }
      if (!body || typeof body !== "object" || Array.isArray(body)) {
        return json({ ok: false, error: "invalid quote update" }, 400);
      }
      const shapeError = quoteSnapshotShapeError(body);
      if (shapeError) return json({ ok: false, error: shapeError }, 400);
      const hub = quoteHub(env);
      if (!hub) return json({ ok: false, error: "quote hub not configured" }, 503);
      const response = await hub.fetch("https://quote-hub/update", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) {
        return json(result, response.status, {
          "access-control-allow-origin": "*",
          "cache-control": "no-store",
        });
      }
      // The cloud capture is the always-on observer, unlike a phone poll that
      // may stop when the app is backgrounded. Let each accepted broker push
      // evaluate the transition from the fresh market-wide status it stored.
      const transition = await trackMarketTransitions(env,
        { market_feed: result.market_feed }, new Date(), ctx);
      return json({ ...result, market_transition: transition }, response.status, {
        "access-control-allow-origin": "*",
        "cache-control": "no-store",
      });
    }

    if (request.method === "GET" && path === "/dashboard") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const now = new Date();
      let snapshot;
      try {
        snapshot = await marketResponseSnapshot(env, now, ctx);
      } catch (_) {
        snapshot = { index: null, top_volume: null, market_feed: null,
          notes: ["market data unavailable"], market_open: marketOpenNow(now),
          market_state: marketState(now) };
      }
      const health = await healthPayload(env);
      const k = karachiView(now.getTime());
      return json({ ...health,
        karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        signals: (await kvGet(env, "SIGNALS")) || "",
        market: snapshot });
    }

    if (request.method === "GET" && path === "/stock") {
      // Owner order 2026-10-20: the phone's search asks for ONE symbol's
      // B, S and T. The split is computed HERE, by the same law the card
      // uses, so two readers of one question cannot disagree, and the method
      // that produced it travels with the numbers (SO-3). No portal fetch: the
      // live frame already carries the published high and low. Owner order
      // 2026-10-22: freshness no longer refuses the answer. After close the
      // publisher stops, so a fresh-only split left the pinned scrip with its
      // total alone and the owner asked to see EVERYTHING after close. The
      // split is now computed from the symbol's LAST PUBLISHED frame, which
      // is the same frame the card still shows; the frame's own stamp stays
      // in quote_as_of, freshness stays in quote_fresh, and the source line
      // names a closed session, so the numbers never claim to be live (SO-3).
      // Owner order 2026-10-26 ("it shows the CHNGM data from yesterday, it
      // should only show it if the market is open today"): the yesterday's
      // session frame is NOT today's data. A frame stamped from a previous
      // Karachi trading day is refused just like a never-seen symbol (SO-3).
      const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      if (!/^[A-Z0-9]{1,12}$/.test(symbol)) {
        return json({ ok: false, error: "invalid symbol" }, 400);
      }
      const snapshot = await readQuoteSnapshot(env);
      const quotes = snapshot && Array.isArray(snapshot.quotes) ? snapshot.quotes : [];
      const quote = newestQuoteRows(quotes).get(symbol) || null;
      // Owner order 2026-11-01: on a non-trading day the last session's
      // frame IS the answer - the card already shows those scrips - and
      // refusing it here left the search box empty while the top three
      // printed Friday's numbers, the two datasets the owner reported.
      // On a trading day the 2026-10-26 law stands: today's frames only.
      const stockTradingToday = isTradingDay(karachiView(Date.now()));
      if (!quote || (!quoteIsFromToday(quote) && stockTradingToday)) {
        return json({ ok: false, error: "symbol not in the live snapshot" }, 404);
      }
      const stock = {
        symbol,
        volume: Number.isFinite(quote.volume) ? Math.round(quote.volume) : null,
        price: Number.isFinite(quote.price) ? quote.price : null,
        change_pct: Number.isFinite(quote.change_pct) ? quote.change_pct : null,
        quote_as_of: quote.observed_at || null,
        quote_fresh: Boolean(quote.fresh),
        buy_volume: null,
        sell_volume: null,
        classified_volume: null,
        unclassified_volume: Number.isFinite(Number(quote.volume))
          ? Math.max(0, Math.round(Number(quote.volume))) : null,
        flow_complete: Number.isFinite(Number(quote.volume))
          ? Math.max(0, Math.round(Number(quote.volume))) === 0 : null,
        split_method: "unavailable",
        split_source: "no measured order-flow pair; the total is unclassified",
        observed_at: quote.observed_at || null,
        source_tick_time: quote.source_tick_time || null,
      };
      const split = splitFromQuote(quote);
      if (split) {
        Object.assign(stock, split);
        const classified = Math.round(Number(split.buy_volume) +
          Number(split.sell_volume));
        const unclassified = Number.isFinite(Number(stock.volume))
          ? Math.max(0, Math.round(Number(stock.volume)) - classified) : null;
        stock.classified_volume = classified;
        stock.unclassified_volume = unclassified;
        stock.flow_complete = unclassified === null
          ? null : unclassified === 0;
        stock.split_method = "quote_rule";
        stock.split_source = split.split_source || quote.split_source ||
          "every volume increment sided by the wire's own bid/ask";
      }
      // Owner order 2026-10-31: the answer also reads and advances the
      // SAME acknowledged frame every surface reads, so the search's B, S
      // and T can never disagree with the card's row for this symbol, and
      // the pair only moves as the day's own volume grows. A stored frame
      // with newer evidence (the card's portal row) answers as itself.
      const kNow = karachiView(Date.now());
      const ackDay = isTradingDay(kNow) ? dayStamp(kNow) : null;
      const frame = ackCandidateFrame(stock, ackDay);
      if (frame) {
        const storedRows = await ackUpsert(env, [frame]);
        const stored = storedRows ? storedRows[symbol] : null;
        if (stored) {
          applyStoredFrame(stock, stored);
          if (stored.observed_at) stock.quote_as_of = stored.observed_at;
        }
      }
      return json({ ok: true, stock });
    }

    if (request.method === "GET" && path === "/prices") {
      // Owner order 2026-10-20 (second note): the phone's search rows show a
      // price and a move, so this returns the whole KMIALL map in one compact
      // answer. Owner order 2026-10-22: freshness no longer gates the row.
      // After close the publisher stops, so a fresh-only map erased every
      // price from the list just as the owner went searching. The rows are
      // the LAST PUBLISHED price of each symbol, from TODAY'S session only;
      // nothing is invented for a symbol the relay has not heard from, and
      // nothing is aged forward, while /stock labels a closed session in its
      // own source line (SO-3). Owner order 2026-10-26: yesterday's frames
      // are not in the list either - the card cannot fill with the last
      // session's prices before today's publisher has spoken. Both laws
      // measure the same thing: the quote's own stamp against the Karachi
      // trading day in progress (SO-8), so a pre-open list is honestly
      // empty and the first published bar of the new session fills it.
      const snapshot = await readQuoteSnapshot(env);
      const kNow = karachiView(Date.now());
      const tradingToday = isTradingDay(kNow);
      const ackDay = tradingToday ? dayStamp(kNow) : null;
      // Owner order 2026-10-31: every row is the acknowledged frame the
      // card and /stock answer with, so the search's rows, the dropdown
      // rankings and the card hold ONE B/S pair per stock. The stored map
      // is one read; the busiest symbols acknowledge their own rows.
      const storedAll = ackDay ? await ackRowsForDay(env, ackDay) : null;
      const prices = [];
      const rowsBuilt = [];
      for (const quote of newestQuoteRows(snapshot && snapshot.quotes).values()) {
        if (!quote || !Number.isFinite(quote.price) || quote.price <= 0) continue;
        // Owner order 2026-11-01: on a non-trading day every surface answers
        // with the last session's frames, stamped by their own observed_at,
        // so a Saturday's search list and the card's top three carry the
        // same scrips. On a trading day the 2026-10-26 law stands:
        // yesterday's frames are not today's list.
        if (!quoteIsFromToday(quote) && tradingToday) continue;
        // The volume dropdowns (owner order 2026-10-23) rank scrips by their
        // measured split, so each row carries the same B/S pair the /stock
        // route computes. A frame without a measured pair ships null B/S and
        // the total as U instead of guessing (SO-3). The row is nine long
        // now: the acknowledged total rides beside the pair, the seventh
        // field is the unclear remainder, and the eighth and ninth are the
        // day's high and low.
        const split = splitFromQuote(quote);
        rowsBuilt.push({
          symbol: String(quote.symbol || ""),
          price: quote.price,
          change_pct: Number.isFinite(quote.change_pct) ? quote.change_pct : null,
          volume: Number.isFinite(quote.volume) ? Math.round(quote.volume) : null,
          // Owner order 2026-11-07: the phone's search row carries the day's
          // own high and low beside the price, so both ride the compact row.
          high: Number.isFinite(quote.high) && quote.high > 0 ? quote.high : null,
          low: Number.isFinite(quote.low) && quote.low > 0 ? quote.low : null,
          buy_volume: split ? split.buy_volume : null,
          sell_volume: split ? split.sell_volume : null,
          split_method: split ? "quote_rule" : "unavailable",
          split_source: split
            ? (split.split_source || quote.split_source ||
               "every volume increment sided by the wire's own bid/ask")
            : "no measured order-flow pair; the total is unclassified",
          observed_at: quote.observed_at || null,
          source: quote.source || null,
        });
      }
      if (tradingToday) {
        // Owner report 2026-11-06: the tape was silent and every search row
        // vanished with it, while the exchange's own table carried today's
        // price and volume. A symbol the hub has not answered for today is
        // filled from that table, with no measured pair, so the list, the
        // scanner and the sector reveal show the real session instead of
        // nothing. A hub frame always wins, and nothing is invented (SO-3).
        const held = new Set(rowsBuilt.map((row) => row.symbol));
        const portalNow = new Date();
        const portalRows = await portalRowsToday(env, portalNow);
        if (!portalRows && ctx && typeof ctx.waitUntil === "function") {
          // The card's own portal build can be suppressed by a fresh runner
          // push, so the member table is rebuilt here, behind the poll.
          ctx.waitUntil(refreshPortalRows(env, portalNow));
        }
        for (const row of portalRows || []) {
          if (held.has(row.symbol)) continue;
          rowsBuilt.push({
            symbol: row.symbol,
            price: row.price,
            change_pct: row.change_pct,
            volume: row.volume,
            high: Number.isFinite(row.high) && row.high > 0 ? row.high : null,
            low: Number.isFinite(row.low) && row.low > 0 ? row.low : null,
            buy_volume: null,
            sell_volume: null,
            split_method: "unavailable",
            split_source: "the exchange's table publishes a total, not a measured pair",
            observed_at: null,
            source: "dps.psx.com.pk KMIALLSHR",
          });
        }
      }
      if (ackDay && rowsBuilt.length && storedAll) {
        // Read only (owner order 2026-11-05, the daily Durable Object
        // budget): the acknowledged map is applied, never rewritten by a
        // poll, so one phone tick costs one snapshot read at most.
        for (const row of rowsBuilt) {
          applyStoredFrame(row, storedAll[row.symbol] || null);
        }
      }
      for (const row of rowsBuilt) {
        prices.push([
          row.symbol,
          row.price,
          row.change_pct,
          row.buy_volume,
          row.sell_volume,
          // Owner order 2026-11-01 ("I am not seeing the volume moving in
          // real time in my app"): the acknowledged total rides with the
          // pair, so the search answer and the selected line print the
          // same moving counter the card's row carries.
          row.volume,
          // The unclear remainder rides as the seventh field (owner order
          // 2026-11-05, eighth pass): the phone prints it as U and never
          // folds it into a side.
          row.volume != null
            ? (row.buy_volume != null && row.sell_volume != null
              ? Math.max(0, Math.round(row.volume)
                - Math.round(row.buy_volume)
                - Math.round(row.sell_volume))
              : Math.round(row.volume))
            : null,
          // The day's high and low are the eighth and ninth fields (owner
          // order 2026-11-07): the search row prints H and L from them.
          row.high,
          row.low,
        ]);
      }
      return json({ ok: true, prices });
    }

    if (request.method === "GET" && path === "/market") {
      // Companion app card (public: exchange data, no secrets). The portal
      // snapshot remains cached, while the one-second broker snapshot is read
      // from the durable quote hub and freshness-checked at response time.
      const now = new Date();
      let snapshot;
      try {
        snapshot = await marketResponseSnapshot(env, now, ctx);
      } catch (_) {
        return json({ ok: false, error: "market data unavailable",
          market_open: marketOpenNow(now), market_state: marketState(now) }, 503);
      }
      const k = karachiView(now.getTime());
      const edgeState = marketState(now);
      const transitions = await trackMarketTransitions(env, snapshot, now, ctx);
      const winLoss = await marketWinLoss(env);
      return json({ ok: true, karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        ...snapshot,
        win_loss: winLoss,
        market_transition: transitions,
        // The relay is the authority on the SESSION, so its own phase is
        // applied last and wins over a snapshot pushed by the owner's PC.
        // The pushed snapshot owns the market DATA (index, leaders, split);
        // the edge owns whether the exchange is open, because the edge's
        // clock is the world's and the PC's may not be (measured drift on
        // 2026-10-10). Otherwise a stale local push could report ONLINE
        // during the Friday break.
        market_open: edgeState.market_open,
        market_state: edgeState });
    }

    if (request.method === "POST" && path === "/market") {
      // Local runner push (src/data/market_snapshot.py --push), admin gated.
      // It takes precedence over the edge's own cache for five minutes.
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object" || Array.isArray(body)) {
        return json({ ok: false, error: "invalid snapshot" }, 400);
      }
      const shapeError = snapshotShapeError(body);
      if (shapeError) {
        return json({ ok: false, error: shapeError }, 400);
      }
      body.source = body.source || "local runner";
      const now = new Date();
      body.built_at = now.toISOString();
      await kvPut(env, "MARKET", JSON.stringify(body), { expirationTtl: 3600 });
      const transitions = await trackMarketTransitions(env, body, now, ctx);
      return json({ ok: true, stored: true, market_transition: transitions });
    }

    if (path.startsWith("/research/") && !adminOk(request, env)) {
      return json({ ok: false, error: "admin token required" }, 403);
    }

    if (request.method === "POST" && path === "/research/observation") {
      const body = await request.json().catch(() => null);
      // The slot is a clock label, and the cadence changed under this route:
      // SO-13's 30 second loop labels its slots HH:MM:SS (11:34:00) while the
      // local 4 minute tick labels them HH:MM (11:34). The route used to
      // accept only HH:MM, so from 2026-10-14 every observation the loop sent
      // was answered 400 "invalid observation" and silently never archived.
      // Both forms are the same clock now, so both are accepted.
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(String(body.date || "")) ||
          !/^\d{2}:\d{2}(:\d{2})?$/.test(String(body.slot || "")) ||
          !body.snapshot || typeof body.snapshot !== "object") {
        return json({ ok: false, error: "invalid observation" }, 400);
      }
      const key = `RESEARCH:OBS:${body.date}:${body.slot.replace(":", "")}`;
      const existing = await relayRead(env, key);
      if (existing) return json({ ok: true, key, stored: false, immutable: true });
      await kvPut(env, key, JSON.stringify(body), { expirationTtl: 63072000 });
      return json({ ok: true, key, stored: true });
    }

    if (request.method === "GET" && path === "/research/observations") {
      const date = url.searchParams.get("date") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        return json({ ok: false, error: "date required" }, 400);
      }
      const listed = await relayList(env, `RESEARCH:OBS:${date}:`, 100);
      const observations = [];
      for (const item of listed.keys) {
        if (item.value) observations.push(JSON.parse(item.value));
      }
      observations.sort((a, b) => a.slot.localeCompare(b.slot));
      return json({ ok: true, observations });
    }

    if (request.method === "POST" && path === "/research/close") {
      // The hit-time close ledger: the runner banks this the moment a stop
      // or target closes the paper trade, so W/L does not wait for the
      // post-close finalize. The full RESEARCH:OUTCOME record still posts
      // later; the W/L reader merges both by date and counts the trade once.
      const body = await request.json().catch(() => null);
      const date = String((body && body.date) || "");
      const sessions = body && body.sessions;
      const session = Array.isArray(sessions) && sessions.length === 1
        ? sessions[0] : null;
      const outcome = String((session && session.outcome) || "").toUpperCase();
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(date) || !session ||
          !TRADE_OUTCOME_LABELS.has(outcome) ||
          String(session.date || "") !== date ||
          !Number.isFinite(Number(session.net_return))) {
        return json({ ok: false, error: "invalid closed trade" }, 400);
      }
      const key = `RESEARCH:CLOSE:${date}`;
      const existing = await relayRead(env, key);
      if (existing) {
        await kvDelete(env, "RESEARCH:WINLOSS");
        return json({ ok: true, stored: false, immutable: true });
      }
      await kvPut(env, key, JSON.stringify(body),
        { expirationTtl: 63072000 });
      await kvDelete(env, "RESEARCH:WINLOSS");
      return json({ ok: true, stored: true });
    }

    if (request.method === "POST" && path === "/research/outcome") {
      const body = await request.json().catch(() => null);
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(String(body.date || "")) ||
          !Array.isArray(body.sessions) || body.sessions.length !== 1) {
        return json({ ok: false, error: "invalid daily outcome" }, 400);
      }
      const key = `RESEARCH:OUTCOME:${body.date}`;
      const existing = await relayRead(env, key);
      if (existing) {
        // Owner order 2026-11-05 ("always update the signal at the end of
        // the day whether it's winning or losing"): a day whose FIRST
        // attempt carried no countable trade (an UNVERIFIABLE finalize,
        // GLAXO 2026-11-04) may be replaced by the day's CLOSED record.
        // A record that already counts is immutable: the day is banked
        // once, and no later run can relabel it.
        let countable = false;
        try {
          const prior = JSON.parse(existing);
          const priorSession = Array.isArray(prior && prior.sessions)
            ? prior.sessions[0] : null;
          const priorLabel = String((priorSession && priorSession.outcome) || "")
            .toUpperCase();
          countable = TRADE_OUTCOME_LABELS.has(priorLabel) &&
            Number.isFinite(Number(priorSession && priorSession.net_return));
        } catch (_) { countable = false; }
        const nextSession = body.sessions[0];
        const nextLabel = String((nextSession && nextSession.outcome) || "")
          .toUpperCase();
        const upgrade = TRADE_OUTCOME_LABELS.has(nextLabel) &&
          Number.isFinite(Number(nextSession && nextSession.net_return));
        if (countable || !upgrade) {
          await kvDelete(env, "RESEARCH:WINLOSS");
          return json({ ok: true, stored: false, immutable: true });
        }
      }
      await kvPut(env, key, JSON.stringify(body),
        { expirationTtl: 63072000 });
      await kvDelete(env, "RESEARCH:WINLOSS");
      return json({ ok: true, stored: true });
    }

    if (request.method === "GET" && path === "/research/history") {
      const listed = await relayList(env, "RESEARCH:OUTCOME:", 1000);
      const sessions = [];
      for (const item of listed.keys) {
        const value = item.value;
        if (!value) continue;
        try {
          const row = JSON.parse(value);
          if (Array.isArray(row.sessions)) sessions.push(...row.sessions);
        } catch (_) {
          // Ignore a malformed stored row; the research gate will remain closed.
        }
      }
      sessions.sort((a, b) => a.date.localeCompare(b.date));
      return json({ ok: true, sessions, complete: Boolean(listed.list_complete) });
    }

    if (request.method === "POST" && path === "/research/claim") {
      const body = await request.json().catch(() => null);
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(String(body.date || "")) ||
          !/^\d{2}:\d{2}(:\d{2})?$/.test(String(body.slot || ""))) {
        return json({ ok: false, error: "invalid signal claim" }, 400);
      }
      const key = `RESEARCH:SENT:${body.date}`;
      if (await relayRead(env, key)) return json({ ok: true, claimed: false });
      await kvPut(env, key, String(body.slot), { expirationTtl: 86400 });
      return json({ ok: true, claimed: true });
    }

    if (request.method === "GET" && path === "/research/gate") {
      const value = await relayRead(env, "RESEARCH:PRODUCTION_GATE");
      return json({ ok: true, gate: value ? JSON.parse(value) : null });
    }

    if (request.method === "POST" && path === "/research/gate") {
      const body = await request.json().catch(() => null);
      if (!body || typeof body.eligible !== "boolean" ||
          typeof body.status !== "string" || !body.rule_version) {
        return json({ ok: false, error: "invalid gate record" }, 400);
      }
      await kvPut(env, "RESEARCH:PRODUCTION_GATE", JSON.stringify(body));
      return json({ ok: true });
    }


    if (request.method === "GET" && path === "/signals") {
      // Companion app poll. Owner order 2026-10-19 retired the token field
      // from the phone, so this read is public: it returns what the owner's
      // own runner already sent his phone, and the write route below stays
      // admin gated. Nothing here can change state.
      const now = new Date();
      // A poll is also a wake-up: this is what starts a band when both the
      // GitHub schedule and the Worker cron failed to. It runs after the
      // answer is sent, so a poll can never wait on, or fail because of, a
      // dispatch attempt.
      if (ctx && typeof ctx.waitUntil === "function") {
        ctx.waitUntil(ensureBandStart(env, now).catch(() => {}));
        // Owner order 2026-11-09: the same poll also watches the feed, so a
        // capture that died mid-band is started again before the close.
        ctx.waitUntil(ensureFeedAlive(env, now).catch(() => {}));
      }
      const k = karachiView(now.getTime());
      const next = nextEvent(now);
      let signals = (await kvGet(env, "SIGNALS")) || "";
      if (signals && !signalEntryClock(signals)) {
        const day = signalDay(signals);
        const remembered = day ? await kvGet(env, `SIGNAL:ENTRY:${day}`) : null;
        if (remembered) signals = withRememberedEntry(signals, remembered);
      }
      return json({
        ok: true,
        signals,
        karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        next_event: next.event
          ? { event: next.event, at_pk: `${dayStamp(karachiView(next.at.getTime()))} ${hhmm(karachiView(next.at.getTime()))}` }
          : null,
      });
    }

    if (request.method === "POST" && path === "/signals") {
      // Local runner pushes fresh signal lines here (admin gated).
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const body = await request.json().catch(() => ({}));
      const text = String(body.signals || "").slice(0, 4000);
      await kvPut(env, "SIGNALS", text);
      const day = signalDay(text);
      const entry = signalEntryClock(text);
      if (day && entry) {
        await kvPut(env, `SIGNAL:ENTRY:${day}`, entry,
          { expirationTtl: 2 * 86400 });
      }
      return json({ ok: true, stored: text.length });
    }

    return json({ ok: false, error: "not found" }, 404);
  },

  // Cron handler: the edge's job is DISPATCH and CARD STATE, not sending.
  // Since owner order 2026-10-29 the owner's texts travel by owner email on
  // GitHub, sent from the Actions jobs; this wake dispatches the band workflow
  // and keeps the app card's market state current.
  async scheduled(controller, env, ctx) {
    const now = new Date();
    const k = karachiView(now.getTime());
    if (!bandsFor(k).length) return;

    // The punctual path for the scanner (owner audit 2026-10-19): this same
    // wake that sends the open text also dispatches the band workflow, so a
    // late GitHub cron is no longer the only thing standing between the owner
    // and a scanned band. No token, no dispatch: the scheduled triggers stay
    // the fallback.
    ctx.waitUntil(dispatchBandScan(env, now));
    // Owner order 2026-11-09: the cron is the clock that does not depend on a
    // phone being open, so it also watches that the band it started is still
    // being fed, and starts the band again when the hub's frames go stale.
    ctx.waitUntil(ensureFeedAlive(env, now).catch(() => {}));

    // Cron is an edge wake-up, not a substitute for a feed observation.
    // Reuse the latest broker snapshot when fresh; break/close transitions are
    // still derived from the shared Karachi session law if the feed has ended.
    let snapshot = null;
    try {
      const raw = await kvGet(env, "MARKET");
      snapshot = raw ? JSON.parse(raw) : null;
    } catch (_) {
      snapshot = null;
    }
    await trackMarketTransitions(env, snapshot, now, ctx);
  },
};

const FLOW_FLUSH_MS = 10 * 60 * 1000;
const FLOW_ROWS_PER_DAY = 40000;

// Owner order 2026-11-07: the desktop needs a whole session of minute bars,
// not the five minutes its own sample buffer holds. The free Durable Objects
// plan allows 100,000 rows written a day for the whole account, so the store
// is one row per MINUTE carrying every symbol, never one row per symbol per
// minute (which would be about 115,000 rows a session on its own). A session
// is at most 360 minutes, a row is written when its minute closes, and the
// retention prune runs once a day, so the ceiling below is a measured bound
// and the arithmetic in tests/test_relay_worker_contracts.py stays under the
// free plan's cap.
const BAR_ROWS_PER_DAY = 1000;
const BAR_RETENTION_DAYS = 45;
const HISTORY_DEFAULT_BARS = 500;
const HISTORY_MAX_BARS = 1000;

// Owner order 2026-11-07: the owner's charts cover KSE100, KMIALLSHR and every
// KMIALLSHR scrip on ten frames, with a rolling year where the data exists.
// ONE: the broker feed samples one symbol every 30 to 90 seconds, so a stored
// one or five second bar would pretend to a detail the wire never had; those
// two frames are built on the desktop from its own live samples and are
// labelled live-only. TWO: from one minute up the relay stores one row per
// (frame, day, bucket) carrying every symbol, five rows a closed minute, so a
// session writes about 1,900 rows and a chart read is bounded by its limit
// rather than by the year. THREE: one minute bars are kept 45 days; five
// minutes 180; everything longer a full 365 days.
const BAR_TFS = ["1s", "5s", "1m", "5m", "15m", "30m", "1h", "1D", "1W", "1M"];
const BAR_TF_MINUTES = { "5m": 5, "15m": 15, "30m": 30, "1h": 60 };
const BAR_ROLL_TFS = ["5m", "15m", "30m", "1h", "1D"];
const BAR_TF_RETENTION = { "1m": 45, "5m": 180, "15m": 365, "30m": 365,
  "1h": 365, "1D": 365, "1W": 365, "1M": 365 };
const BARS_DEFAULT = 400;
const BARS_MAX = 2000;
const BARS_MAX_DAYS = 365;
const BAR_ROLL_ROWS_PER_DAY = 3000;

// One SQLite-backed object holds the latest broker frame set. Producer
// requests are coalesced to at most once per second by the cloud capture;
// connected browsers receive server-pushed changes without one DO request per
// client poll. Values are source-timestamped and stale rows remain explicitly
// stale rather than being advanced by the relay clock.
export class QuoteHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    // Owner order 2026-11-05: the free plan's Durable Objects daily
    // budgets (5,000,000 rows read and 100,000 rows written a day, reset
    // 00:00 UTC) must never again be able to kill the live feed. Two
    // laws hold this. ONE: the quote snapshot lives in this hub's memory
    // between loads, so a push does not SELECT the day's row back and a
    // reading poll never touches SQLite at all - the session's reads
    // drop from six figures a day to a few thousand, and the dedicated
    // phone and desk clients can read for a century of sessions inside
    // the cap. TWO: even when persistence itself refuses (any budget,
    // any error), the handler still answers JSON with the memory-held
    // snapshot, so a throw can never again surface as the edge's HTML
    // error page and mute the feed until midnight UTC.
    // Flow state is authoritative in memory between flushes. Persisting it
    // on every push cost one SQL row per symbol per push and exhausted the
    // Durable Objects daily write budget; five minutes is 312 rows at a
    // time, not 312 rows every second.
    this.flowStates = null;
    this.lastFlowFlush = 0;
    // Owner order 2026-11-05: the memory-read law. The last accepted
    // snapshot lives here between loads, so the POST /update handler
    // stops SELECTing the day's row back on every push and no reading
    // poll (the phone's one-a-second card and the desk's slower pace)
    // ever costs a SQLite row read. A fresh instance loads the row once;
    // from then on every read answer comes from memory.
    this.snapshotCache = null;
    this.snapshotLoaded = false;
    // Per-push error notes are rate limited to one a minute, so a
    // repeating per-symbol error can never spend the day's rows-written
    // budget on diagnostics itself.
    this.lastFlowErrorSeen = 0;
    this.lastAckWrites = new Map();
    // The mirror's own day ledger, so ACK_ROWS_PER_DAY is a measured ceiling
    // and not a promise. It is in-memory like the flow counters: an instance
    // that restarts re-counts from zero, which can only make it stricter.
    this.ackWritesDay = "";
    this.ackWritesToday = 0;
    // /prices is polled by the phone once per foreground tick. Listing its
    // acknowledged rows from SQL on every read spent the free Durable Objects
    // rows-read budget (5,000,000/day) and stopped the relay on 2026-11-04.
    // This object already owns every ACK write, so it keeps the current day's
    // map in memory and falls back to one SQL list only when a fresh instance
    // starts or the Karachi day changes.
    this.ackRowsDay = "";
    this.ackRowsBySymbol = null;
    this.ackRowsLoaded = false;
    this.flowRowsDay = "";
    this.flowRowsToday = 0;
    this.flowStatsLoaded = false;
    // Minute bars (owner order 2026-11-07). Only the CURRENT minute is held
    // here; closed minutes are already rows. The day cache holds the one day
    // a chart is being read for, so paging a session costs one SQL read and
    // every later read of that day costs none.
    this.barForming = null;
    this.barVolumes = null;
    this.barsDayCache = { day: "", rows: null };
    this.barRowsDay = "";
    this.barRowsToday = 0;
    this.barPruneDay = "";
    this.barWriteError = null;
    // Owner order 2026-11-07: the ten frame chart store. The rollups are
    // held for the day in memory between writes; these fields make the
    // budget ledger explicit instead of accidental.
    this.barRolls = null;
    this.barRollsDay = "";
    this.barRollRowsDay = "";
    this.barRollRowsToday = 0;
    this.barRollPruneDay = "";
    this.barRollWriteError = null;
    this.ready = ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)",
      );
      // The relay's own key space. It replaced KV on 2026-10-20 so the
      // relay needs no quota-limited product to hold a card.
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS relay_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at INTEGER NOT NULL DEFAULT 0)",
      );
      // Owner order 2026-11-03: the day's order flow, sided at the hub. The
      // capture pushes snapshots; this object sees every push for the whole
      // session and survives restarts, so it is the one place a pair can
      // cover the day from its first print. The law is the one
      // src/data/quote_flow.py documents and tests.
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_flow (symbol TEXT PRIMARY KEY, day TEXT NOT NULL, volume INTEGER NOT NULL, buy INTEGER NOT NULL, sell INTEGER NOT NULL, baseline INTEGER NOT NULL, bid REAL NOT NULL DEFAULT 0, ask REAL NOT NULL DEFAULT 0, last REAL NOT NULL DEFAULT 0, side TEXT NOT NULL DEFAULT '', rules TEXT NOT NULL DEFAULT '{}', updated_at INTEGER NOT NULL DEFAULT 0)",
      );
      // Owner order 2026-11-07: one row per Karachi minute, its payload a
      // symbol -> OHLCV map. Bundling every symbol into the minute row is
      // what keeps a session near 360 written rows instead of one row per
      // symbol per minute, which would be about 115,000 on its own.
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_bars (day TEXT NOT NULL, minute INTEGER NOT NULL, payload TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, minute))",
      );
      this.ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_bars_tf (tf TEXT NOT NULL, day TEXT NOT NULL, bucket INTEGER NOT NULL, payload TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tf, day, bucket))",
      );
    });
  }

  // Every increment of the venue's own running total, sided once, for the
  // whole day. Rules, first match wins: last at or above the ask buys; at or
  // below the bid sells; inside the spread the midpoint decides; otherwise
  // the tick decides; otherwise no side is known and the increment stays in
  // the unclassified baseline. The day's change sign is never consulted: it
  // is the sign of the change, not the side of a trade. A falling total is
  // stale evidence and is refused, never turned into a sale. The pre-baseline
  // counter is unclassified too; no share is ever guessed into a side.
  async advanceFlow(quote) {
    await this.ready;
    // An instance that was already running before the flow table shipped
    // never re-ran the constructor, so the table is created here too. The
    // statement is idempotent and the table is tiny.
    this.ctx.storage.sql.exec(
      "CREATE TABLE IF NOT EXISTS quote_flow (symbol TEXT PRIMARY KEY, day TEXT NOT NULL, volume INTEGER NOT NULL, buy INTEGER NOT NULL, sell INTEGER NOT NULL, baseline INTEGER NOT NULL, bid REAL NOT NULL DEFAULT 0, ask REAL NOT NULL DEFAULT 0, last REAL NOT NULL DEFAULT 0, side TEXT NOT NULL DEFAULT '', rules TEXT NOT NULL DEFAULT '{}', updated_at INTEGER NOT NULL DEFAULT 0)",
    );
    const symbol = String((quote && quote.symbol) || "").toUpperCase();
    const at = Date.parse(quote && quote.observed_at ? quote.observed_at : "");
    const total = Math.round(Number(quote && quote.volume));
    if (!/^[A-Z0-9]{1,12}$/.test(symbol)) return null;
    if (!Number.isFinite(at) || !Number.isFinite(total) || total < 0) return null;
    const day = dayStamp(karachiView(at));
    await this.loadFlowStats();
    const price = Number(quote.price);
    const bid = Number(quote.bid);
    const ask = Number(quote.ask);
    if (!this.flowStates) this.loadFlowStates();
    const stored = this.flowStates[symbol];
    let state;
    if (stored && String(stored.day) === day) {
      let rules = {};
      try { rules = JSON.parse(String(stored.rules || "{}")) || {}; }
      catch (_) { rules = {}; }
      state = { day, volume: Number(stored.volume), buy: Number(stored.buy),
        sell: Number(stored.sell), baseline: Number(stored.baseline),
        bid: Number(stored.bid) || 0, ask: Number(stored.ask) || 0,
        last: Number(stored.last) || 0, side: String(stored.side || ""),
        rules };
    } else {
      // A fresh day, or a hub that has no stored state for this day. Adopt
      // the capture's observed pair when the frame carries it; otherwise
      // every share already traded is unclassified. It is never assigned to
      // one side, because that would manufacture a buy or a sell the wire
      // never showed us.
      const seed = measuredFlowSeed(quote, total);
      state = seed
        ? { day, volume: total, buy: seed.buy, sell: seed.sell,
            baseline: seed.baseline, bid: 0, ask: 0, last: 0, side: "",
            rules: {} }
        : { day, volume: total, buy: 0, sell: 0, baseline: total,
            bid: 0, ask: 0, last: 0, side: "", rules: {} };
    }
    const previousLast = state.last;
    if (Number.isFinite(price) && price > 0) state.last = price;
    if (Number.isFinite(bid) && bid > 0) state.bid = bid;
    if (Number.isFinite(ask) && ask > 0) state.ask = ask;
    const bump = (rule) => { state.rules[rule] = (state.rules[rule] || 0) + 1; };
    // Shares the hub did not see stay in state.baseline. They are reported
    // as unclassified and are never sided by a guess. On a normal session
    // the capture starts before the open and the seed is zero, so there is
    // nothing to hide; after a genuine late start the number is visible.
    let attributed = 0;
    let attributedRule = null;
    let attributedSide = null;
    if (total < state.volume) {
      bump("stale_total");
      return null;
    } else {
      const delta = total - state.volume;
      if (delta > 0) {
        let rule = null;
        let side = null;
        if (state.ask > 0 && state.last >= state.ask) {
          rule = "at_ask"; side = "B";
        } else if (state.bid > 0 && state.last <= state.bid) {
          rule = "at_bid"; side = "S";
        } else if (state.bid > 0 && state.ask > state.bid) {
          const mid = (state.bid + state.ask) / 2;
          if (state.last > mid) { rule = "above_mid"; side = "B"; }
          else if (state.last < mid) { rule = "below_mid"; side = "S"; }
        }
        if (!side && Number.isFinite(previousLast) && previousLast > 0) {
          if (state.last > previousLast) { rule = "tick_up"; side = "B"; }
          else if (state.last < previousLast) { rule = "tick_down"; side = "S"; }
        }
        if (side === "B") state.buy += delta;
        else if (side === "S") state.sell += delta;
        else {
          // No evidence decides this increment. It stays in the baseline,
          // which is served as U, and never carries the previous side.
          rule = "unclassified";
          state.baseline += delta;
          state.side = "";
        }
        if (side) {
          state.side = side;
          attributed = delta;
          attributedSide = side;
        }
        attributedRule = rule;
        bump(rule);
      }
      state.volume = total;
    }
    this.flowStates[symbol] = state;
    const flushed = Date.now();
    if (flushed - this.lastFlowFlush >= FLOW_FLUSH_MS) {
      if (this.flowRowsDay !== day) {
        this.flowRowsDay = day;
        this.flowRowsToday = 0;
      }
      const rows = Object.keys(this.flowStates).length;
      if (this.flowRowsToday + rows <= FLOW_ROWS_PER_DAY &&
          this.persistFlowStates()) {
        this.flowRowsToday += rows;
      }
      this.lastFlowFlush = flushed;
      try {
        await this.statePut("FLOW:STATS", JSON.stringify({
          day: this.flowRowsDay,
          rows_written_today: this.flowRowsToday,
          row_budget: FLOW_ROWS_PER_DAY,
          flush_minutes: FLOW_FLUSH_MS / 60000,
          symbols: rows,
          last_flush: new Date(flushed).toISOString(),
          exhausted: this.flowRowsToday >= FLOW_ROWS_PER_DAY,
        }), 0);
      } catch (_) { /* stats are best effort */ }
    }
    if (state.buy + state.sell + state.baseline !== total) return null;
    return { buy_volume: state.buy, sell_volume: state.sell,
      baseline: state.baseline, total, delta: attributed,
      side: attributedSide, rule: attributedRule, rules: state.rules };
  }

  async loadFlowStats() {
    if (this.flowStatsLoaded) return;
    this.flowStatsLoaded = true;
    try {
      const raw = await this.stateGet("FLOW:STATS");
      if (!raw) return;
      const stats = JSON.parse(raw);
      this.flowRowsDay = String(stats.day || "");
      this.flowRowsToday = Math.max(0, Number(stats.rows_written_today) || 0);
    } catch (_) { /* first run has no stats yet */ }
  }

  loadFlowStates() {
    const states = {};
    try {
      const rows = this.ctx.storage.sql.exec(
        "SELECT symbol, day, volume, buy, sell, baseline, bid, ask, last, side, rules FROM quote_flow",
      ).toArray();
      for (const row of rows) {
        let rules = {};
        try { rules = JSON.parse(String(row.rules || "{}")) || {}; }
        catch (_) { rules = {}; }
        states[String(row.symbol)] = {
          day: String(row.day), volume: Number(row.volume),
          buy: Number(row.buy), sell: Number(row.sell),
          baseline: Number(row.baseline),
          bid: Number(row.bid) || 0, ask: Number(row.ask) || 0,
          last: Number(row.last) || 0, side: String(row.side || ""), rules,
        };
      }
    } catch (_) { /* a first run has no rows; the next flush creates them */ }
    this.flowStates = states;
  }

  persistFlowStates() {
    const states = this.flowStates || {};
    try {
      for (const symbol of Object.keys(states)) {
        const state = states[symbol];
        this.ctx.storage.sql.exec(
          "INSERT INTO quote_flow (symbol, day, volume, buy, sell, baseline, bid, ask, last, side, rules, updated_at) " +
          "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) " +
          "ON CONFLICT(symbol) DO UPDATE SET day = excluded.day, volume = excluded.volume, " +
          "buy = excluded.buy, sell = excluded.sell, baseline = excluded.baseline, " +
          "bid = excluded.bid, ask = excluded.ask, last = excluded.last, " +
          "side = excluded.side, rules = excluded.rules, updated_at = excluded.updated_at",
          symbol, state.day, state.volume, state.buy, state.sell, state.baseline,
          state.bid, state.ask, state.last, state.side,
          JSON.stringify(state.rules), Date.now(),
        );
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  // ------------------------------------------------------------- minute bars
  //
  // Owner order 2026-11-07: the owner's desktop build draws a full-day
  // candlestick chart per scrip, and its own sample buffer holds only about
  // five minutes. A bar is built here from the frames this object already
  // accepts, never from a separate feed, so a bar exists only where the relay
  // actually saw a print (SO-3). The open is the first price seen in the
  // minute, the high and low are the extremes of the prices seen, the close is
  // the last one, and the volume is the measured increase of the venue's own
  // cumulative day total across that minute. It is a relay bar, not an
  // exchange bar, and /history says so in its own notes.

  ensureBarTable() {
    try {
      this.ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_bars (day TEXT NOT NULL, minute INTEGER NOT NULL, payload TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, minute))",
      );
      this.ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_bars_tf (tf TEXT NOT NULL, day TEXT NOT NULL, bucket INTEGER NOT NULL, payload TEXT NOT NULL, updated_at INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (tf, day, bucket))",
      );
    } catch (_) { /* the write that follows records the refusal */ }
  }

  barSlot(observedAt) {
    const at = Date.parse(observedAt || "");
    if (!Number.isFinite(at)) return null;
    const k = karachiView(at);
    return { day: dayStamp(k), minute: minutesOf(k) };
  }

  // Persist the forming minute as ONE row carrying every symbol. Best effort:
  // a storage refusal keeps the bar in memory and is noted for /history, never
  // thrown, so a spent write budget can never mute the feed.
  flushFormingBar() {
    const forming = this.barForming;
    if (!forming) return false;
    this.barForming = null;
    const symbols = forming.symbols || {};
    const names = Object.keys(symbols);
    if (!names.length) return false;
    if (this.barRowsDay !== forming.day) {
      this.barRowsDay = forming.day;
      this.barRowsToday = 0;
    }
    if (this.barRowsToday >= BAR_ROWS_PER_DAY) return false;
    const payload = {};
    for (const name of names) {
      const bar = symbols[name];
      const first = Number.isFinite(bar.first) ? bar.first : null;
      const last = Number.isFinite(bar.last) ? bar.last : null;
      payload[name] = { o: bar.o, h: bar.h, l: bar.l, c: bar.c,
        v: first !== null && last !== null ? Math.max(0, last - first) : 0 };
    }
    this.ensureBarTable();
    try {
      this.ctx.storage.sql.exec(
        "INSERT INTO quote_bars (day, minute, payload, updated_at) VALUES (?, ?, ?, ?) " +
        "ON CONFLICT(day, minute) DO UPDATE SET payload = excluded.payload, " +
        "updated_at = excluded.updated_at",
        forming.day, forming.minute, JSON.stringify(payload), Date.now(),
      );
      this.barRowsToday += 1;
      this.barWriteError = null;
      if (this.barsDayCache.day === forming.day && this.barsDayCache.rows) {
        this.barsDayCache.rows.set(forming.minute, payload);
      }
      this.pruneBars(forming.day);
      this.rollBars(forming.day, forming.minute, payload);
      return true;
    } catch (error) {
      this.barWriteError = {
        at: new Date().toISOString(),
        message: String((error && error.message) || error).slice(0, 200),
      };
      return false;
    }
  }

  // At most one retention pass a day, on the first row written for a new day.
  // Whole days outside the window are deleted, and their rows are counted
  // against the same day ceiling so the free-plan arithmetic stays honest.
  pruneBars(today) {
    if (this.barPruneDay === today) return;
    this.barPruneDay = today;
    const start = Date.parse(today + "T00:00:00+05:00");
    if (!Number.isFinite(start)) return;
    const cutoff = dayStamp(karachiView(start - BAR_RETENTION_DAYS * 86400000));
    try {
      const stale = this.ctx.storage.sql.exec(
        "SELECT COUNT(*) AS rows FROM quote_bars WHERE day < ?", cutoff,
      ).toArray()[0];
      const count = Math.max(0, Number(stale && stale.rows) || 0);
      if (!count) return;
      if (this.barRowsToday + count > BAR_ROWS_PER_DAY) return;
      this.ctx.storage.sql.exec("DELETE FROM quote_bars WHERE day < ?", cutoff);
      this.barRowsToday += count;
      if (this.barsDayCache.day && this.barsDayCache.day < cutoff) {
        this.barsDayCache = { day: "", rows: null };
      }
    } catch (_) { /* the next day retries; a stale day is not invented */ }
  }

  accumulateBar(quote) {
    const slot = this.barSlot(quote && quote.observed_at);
    if (!slot) return;
    const price = Number(quote.price);
    if (!Number.isFinite(price) || price <= 0) return;
    const symbol = String(quote.symbol || "").toUpperCase();
    if (!/^[A-Z0-9]{1,12}$/.test(symbol)) return;
    const total = Math.round(Number(quote.volume));
    const volume = Number.isFinite(total) ? total : null;
    if (!this.barForming || this.barForming.day !== slot.day ||
        this.barForming.minute !== slot.minute) {
      // The previous minute is complete. Write it once, then start the new
      // one: a session is about 360 minutes, so about 360 rows.
      this.flushFormingBar();
      this.barForming = { day: slot.day, minute: slot.minute, symbols: {} };
    }
    if (!this.barVolumes || this.barVolumes.day !== slot.day) {
      this.barVolumes = { day: slot.day, totals: {} };
    }
    const before = Number.isFinite(this.barVolumes.totals[symbol])
      ? this.barVolumes.totals[symbol] : null;
    const book = this.barForming.symbols;
    const held = book[symbol];
    if (!held) {
      // `first` is the cumulative total that stood before this minute, so the
      // increment between the previous minute's last frame and this one is
      // counted here instead of being lost at the boundary.
      book[symbol] = { o: price, h: price, l: price, c: price,
        first: before !== null && volume !== null && before <= volume ? before : volume,
        last: volume };
    } else {
      if (price > held.h) held.h = price;
      if (price < held.l) held.l = price;
      held.c = price;
      if (volume !== null && (held.last === null || volume >= held.last)) {
        held.last = volume;
      }
    }
    if (volume !== null) this.barVolumes.totals[symbol] = volume;
  }

  async loadBarsDay(day) {
    if (this.barsDayCache.day === day && this.barsDayCache.rows) {
      return this.barsDayCache.rows;
    }
    const rows = new Map();
    this.ensureBarTable();
    try {
      for (const row of this.ctx.storage.sql.exec(
        "SELECT minute, payload FROM quote_bars WHERE day = ? ORDER BY minute",
        day,
      ).toArray()) {
        let parsed = null;
        try { parsed = JSON.parse(row.payload); } catch (_) { parsed = null; }
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          rows.set(Number(row.minute), parsed);
        }
      }
    } catch (_) { /* an unreadable store answers empty, never invented */ }
    this.barsDayCache = { day, rows };
    return rows;
  }

  // The minute's start as an ISO 8601 stamp carrying the Karachi offset
  // (SO-8). The stored minute is already Karachi wall clock, so the stamp is
  // the day and the clock, never a UTC conversion the reader must undo.
  barStamp(day, minute) {
    return `${day}T${this.barClock(minute)}:00+05:00`;
  }

  barClock(minute) {
    return `${pad(Math.floor(minute / 60))}:${pad(minute % 60)}`;
  }

  // A wall clock stamp for as_of, always with the Karachi offset (SO-8).
  karachiStamp(instantMs) {
    const k = karachiView(instantMs);
    return `${dayStamp(k)}T${pad(k.getUTCHours())}:` +
      `${pad(k.getUTCMinutes())}:${pad(k.getUTCSeconds())}+05:00`;
  }

  // One closed minute becomes five rollup rows (5m, 15m, 30m, 1h, 1D), each
  // carrying every symbol. The day's buckets are cached here, so a minute's
  // merge is memory work plus one INSERT per frame. A refused write leaves
  // the minute bars intact and records the reason for the answer, never
  // throws into the feed.
  rollBars(day, minute, payload) {
    if (!payload || typeof payload !== "object") return;
    if (this.barRollsDay !== day) {
      this.barRollsDay = day;
      this.barRolls = new Map();
    }
    if (!this.barRolls) this.barRolls = new Map();
    if (this.barRollRowsDay !== day) {
      this.barRollRowsDay = day;
      this.barRollRowsToday = 0;
    }
    for (const tf of BAR_ROLL_TFS) {
      if (this.barRollRowsToday >= BAR_ROLL_ROWS_PER_DAY) break;
      const bucket = tf === "1D" ? 0
        : Math.floor(minute / BAR_TF_MINUTES[tf]) * BAR_TF_MINUTES[tf];
      const key = tf + "|" + day + "|" + bucket;
      let book = this.barRolls.get(key);
      if (!book) {
        book = {};
        try {
          const row = this.ctx.storage.sql.exec(
            "SELECT payload FROM quote_bars_tf WHERE tf = ? AND day = ? AND bucket = ?",
            tf, day, bucket,
          ).toArray()[0];
          if (row) {
            try { book = JSON.parse(row.payload) || {}; } catch (_) { book = {}; }
          }
        } catch (_) { book = {}; }
      }
      for (const name of Object.keys(payload)) {
        const bar = payload[name];
        if (!bar || !Number.isFinite(Number(bar.o))) continue;
        const held = book[name];
        if (!held) {
          book[name] = { o: bar.o, h: bar.h, l: bar.l, c: bar.c,
            v: Math.max(0, Number(bar.v) || 0) };
        } else {
          if (bar.h > held.h) held.h = bar.h;
          if (bar.l < held.l) held.l = bar.l;
          held.c = bar.c;
          held.v = Math.max(0, Number(held.v) || 0) +
            Math.max(0, Number(bar.v) || 0);
        }
      }
      this.barRolls.set(key, book);
      try {
        this.ctx.storage.sql.exec(
          "INSERT INTO quote_bars_tf (tf, day, bucket, payload, updated_at) VALUES (?, ?, ?, ?, ?) " +
          "ON CONFLICT(tf, day, bucket) DO UPDATE SET payload = excluded.payload, " +
          "updated_at = excluded.updated_at",
          tf, day, bucket, JSON.stringify(book), Date.now(),
        );
        this.barRollRowsToday += 1;
        this.barRollWriteError = null;
      } catch (error) {
        this.barRollWriteError = {
          at: new Date().toISOString(),
          message: String((error && error.message) || error).slice(0, 200),
        };
      }
    }
    this.pruneBarRolls(day);
  }

  pruneBarRolls(today) {
    if (this.barRollPruneDay === today) return;
    this.barRollPruneDay = today;
    const start = Date.parse(today + "T00:00:00+05:00");
    if (!Number.isFinite(start)) return;
    for (const tf of BAR_ROLL_TFS) {
      const keep = BAR_TF_RETENTION[tf] || 365;
      const cutoff = dayStamp(karachiView(start - keep * 86400000));
      try {
        const stale = this.ctx.storage.sql.exec(
          "SELECT COUNT(*) AS rows FROM quote_bars_tf WHERE tf = ? AND day < ?",
          tf, cutoff,
        ).toArray()[0];
        const count = Math.max(0, Number(stale && stale.rows) || 0);
        if (!count) continue;
        if (this.barRollRowsToday + count > BAR_ROLL_ROWS_PER_DAY) continue;
        this.ctx.storage.sql.exec(
          "DELETE FROM quote_bars_tf WHERE tf = ? AND day < ?", tf, cutoff,
        );
        this.barRollRowsToday += count;
      } catch (_) { /* the next day retries */ }
    }
  }

  // Every frame the desk can draw, for one symbol, newest first in the store
  // but returned oldest first for the chart. A read is bounded by `limit`
  // rows, never by the year, so a 365 day chart costs a few hundred reads.
  // The forming minute is folded into the newest bar, so a live chart ticks
  // with the same data the session is writing.
  async barsAnswer(url) {
    await this.ready;
    const tf = String(url.searchParams.get("tf") || "1m");
    const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
    if (!BAR_TFS.includes(tf)) {
      return { ok: false, error: "tf must be one of " + BAR_TFS.join(", "),
        supported: BAR_TFS };
    }
    if (!symbol) return { ok: false, error: "symbol required" };
    if (!/^[A-Z0-9]{1,12}$/.test(symbol)) return { ok: false, error: "invalid symbol" };
    if (tf === "1s" || tf === "5s") {
      return {
        ok: true, symbol, tf, bars: [], bar_count: 0,
        retention_days: 0, retention: "live session only",
        source: "desktop live quote buffer",
        notes: [
          "one and five second candles are built on the desktop from the live quote stream",
          "the broker feed samples one symbol every 30 to 90 seconds, so the relay cannot store a true second bar for a year",
        ],
      };
    }
    const askedDays = Number(url.searchParams.get("days"));
    const days = Number.isFinite(askedDays)
      ? Math.max(1, Math.min(BARS_MAX_DAYS, Math.round(askedDays)))
      : BARS_MAX_DAYS;
    const askedLimit = Number(url.searchParams.get("limit"));
    const limit = Number.isFinite(askedLimit)
      ? Math.max(1, Math.min(BARS_MAX, Math.round(askedLimit)))
      : BARS_DEFAULT;
    const cutoff = dayStamp(karachiView(Date.now() - days * 86400000));
    this.ensureBarTable();
    const notes = [];
    let bars = [];
    if (tf === "1m") {
      const rows = this.ctx.storage.sql.exec(
        "SELECT day, minute, payload FROM quote_bars WHERE day >= ? " +
        "ORDER BY day DESC, minute DESC LIMIT ?", cutoff, limit,
      ).toArray();
      for (const row of rows.reverse()) {
        let book = null;
        try { book = JSON.parse(row.payload); } catch (_) { book = null; }
        const bar = book && book[symbol];
        if (!bar || !Number.isFinite(Number(bar.o))) continue;
        bars.push({ t: this.barStamp(String(row.day), Number(row.minute)),
          o: Number(bar.o), h: Number(bar.h), l: Number(bar.l),
          c: Number(bar.c), v: Math.max(0, Number(bar.v) || 0) });
      }
    } else if (tf === "5m" || tf === "15m" || tf === "30m" ||
               tf === "1h" || tf === "1D") {
      const rows = this.ctx.storage.sql.exec(
        "SELECT day, bucket, payload FROM quote_bars_tf WHERE tf = ? AND day >= ? " +
        "ORDER BY day DESC, bucket DESC LIMIT ?", tf, cutoff, limit,
      ).toArray();
      for (const row of rows.reverse()) {
        let book = null;
        try { book = JSON.parse(row.payload); } catch (_) { book = null; }
        const bar = book && book[symbol];
        if (!bar || !Number.isFinite(Number(bar.o))) continue;
        bars.push({ t: this.barStamp(String(row.day), Number(row.bucket)),
          o: Number(bar.o), h: Number(bar.h), l: Number(bar.l),
          c: Number(bar.c), v: Math.max(0, Number(bar.v) || 0) });
      }
    } else {
      const rows = this.ctx.storage.sql.exec(
        "SELECT day, payload FROM quote_bars_tf WHERE tf = '1D' AND day >= ? " +
        "ORDER BY day ASC", cutoff,
      ).toArray();
      const groups = new Map();
      for (const row of rows) {
        const day = String(row.day);
        let key = day;
        if (tf === "1W") {
          const at = new Date(day + "T00:00:00Z");
          if (!Number.isFinite(at.getTime())) continue;
          const dow = (at.getUTCDay() + 6) % 7;
          key = new Date(at.getTime() - dow * 86400000).toISOString().slice(0, 10);
        } else {
          key = day.slice(0, 7) + "-01";
        }
        let book = null;
        try { book = JSON.parse(row.payload); } catch (_) { book = null; }
        const bar = book && book[symbol];
        if (!bar || !Number.isFinite(Number(bar.o))) continue;
        const held = groups.get(key);
        if (!held) {
          groups.set(key, { t: key + "T00:00:00+05:00", o: Number(bar.o),
            h: Number(bar.h), l: Number(bar.l), c: Number(bar.c),
            v: Math.max(0, Number(bar.v) || 0) });
        } else {
          if (Number(bar.h) > held.h) held.h = Number(bar.h);
          if (Number(bar.l) < held.l) held.l = Number(bar.l);
          held.c = Number(bar.c);
          held.v += Math.max(0, Number(bar.v) || 0);
        }
      }
      bars = Array.from(groups.values()).sort((a, b) => a.t.localeCompare(b.t));
    }
    // The forming minute is not in SQL yet. Fold it into the newest bar so a
    // chart ticks while the minute is still open, and never invent a bucket.
    if (this.barForming && this.barForming.day >= cutoff) {
      const forming = this.barForming;
      const bar = forming.symbols[symbol];
      if (bar) {
        let t = this.barStamp(forming.day, forming.minute);
        if (tf === "5m" || tf === "15m" || tf === "30m" || tf === "1h") {
          t = this.barStamp(forming.day,
            Math.floor(forming.minute / BAR_TF_MINUTES[tf]) * BAR_TF_MINUTES[tf]);
        } else if (tf === "1D" || tf === "1W" || tf === "1M") {
          t = forming.day + "T00:00:00+05:00";
        }
        let target = null;
        for (let i = bars.length - 1; i >= 0 && i >= bars.length - 2; i--) {
          if (bars[i] && (bars[i].t === t ||
              ((tf === "1W" || tf === "1M") &&
               bars[i].t.slice(0, 7) === t.slice(0, 7)))) {
            target = bars[i];
            break;
          }
        }
        if (target) {
          if (Number(bar.h) > target.h) target.h = Number(bar.h);
          if (Number(bar.l) < target.l) target.l = Number(bar.l);
          target.c = Number(bar.c);
        } else if (tf !== "1W" && tf !== "1M") {
          bars.push({ t, o: Number(bar.o), h: Number(bar.h), l: Number(bar.l),
            c: Number(bar.c), v: 0 });
        }
      }
    }
    bars.sort((a, b) => a.t.localeCompare(b.t));
    const newest = bars.slice(-limit);
    if (!newest.length) {
      notes.push("no stored " + tf + " bars for " + symbol + " in this range");
      notes.push("the relay began storing bars on 2026-11-07; a day with no session has no bar");
    }
    if (this.barRollWriteError) {
      notes.push("a rollup write was refused at " + this.barRollWriteError.at +
        "; the reason is " + this.barRollWriteError.message);
    }
    return {
      ok: true, symbol, tf, days, bars: newest, bar_count: newest.length,
      first: newest.length ? newest[0].t : null,
      last: newest.length ? newest[newest.length - 1].t : null,
      retention_days: BAR_TF_RETENTION[tf] || 0,
      source: tf === "1m"
        ? "relay minute bars built from accepted broker quote frames"
        : "relay " + tf + " bars rolled up from its minute bars",
      notes,
    };
  }

  async historyAnswer(url) {
    await this.ready;
    const resolution = String(url.searchParams.get("resolution") || "1m");
    if (resolution !== "1m") {
      return { ok: false, error: "resolution must be 1m" };
    }
    const askedDay = String(url.searchParams.get("day") || "");
    const day = /^\d{4}-\d{2}-\d{2}$/.test(askedDay)
      ? askedDay : dayStamp(karachiView(Date.now()));
    const askedLimitRaw = url.searchParams.get("limit");
    const askedLimit = askedLimitRaw === null ? NaN : Number(askedLimitRaw);
    const limit = Number.isFinite(askedLimit)
      ? Math.max(1, Math.min(HISTORY_MAX_BARS, Math.round(askedLimit)))
      : HISTORY_DEFAULT_BARS;
    const symbol = String(url.searchParams.get("symbol") || "").toUpperCase();
    if (!symbol) {
      // No symbol asks for coverage: which days the relay actually holds, so
      // a chart can say "nothing stored" with a reason instead of drawing an
      // empty frame that looks like a flat market (SO-3).
      let days = [];
      this.ensureBarTable();
      try {
        days = this.ctx.storage.sql.exec(
          "SELECT day, COUNT(*) AS minutes, MIN(minute) AS first_minute, " +
          "MAX(minute) AS last_minute FROM quote_bars GROUP BY day " +
          "ORDER BY day DESC",
        ).toArray().map((row) => ({
          day: String(row.day),
          minutes: Math.max(0, Number(row.minutes) || 0),
          first: this.barClock(Math.max(0, Number(row.first_minute) || 0)),
          last: this.barClock(Math.max(0, Number(row.last_minute) || 0)),
        }));
      } catch (_) { days = []; }
      return {
        ok: true,
        resolution: "1m",
        retention_days: BAR_RETENTION_DAYS,
        source: "relay minute bars built from accepted one-second quote frames",
        days,
        notes: [
          "no symbol was asked, so this answer is coverage only",
          "the relay keeps at most " + BAR_RETENTION_DAYS + " days of minute bars",
        ],
      };
    }
    if (!/^[A-Z0-9]{1,12}$/.test(symbol)) {
      return { ok: false, error: "invalid symbol" };
    }
    const merged = new Map(await this.loadBarsDay(day));
    let formingMinute = null;
    if (this.barForming && this.barForming.day === day) {
      formingMinute = this.barForming.minute;
      const live = {};
      for (const name of Object.keys(this.barForming.symbols)) {
        const bar = this.barForming.symbols[name];
        const first = Number.isFinite(bar.first) ? bar.first : null;
        const last = Number.isFinite(bar.last) ? bar.last : null;
        live[name] = { o: bar.o, h: bar.h, l: bar.l, c: bar.c,
          v: first !== null && last !== null ? Math.max(0, last - first) : 0 };
      }
      merged.set(formingMinute,
        { ...(merged.get(formingMinute) || {}), ...live });
    }
    const all = [];
    for (const minute of Array.from(merged.keys()).sort((a, b) => a - b)) {
      const bar = merged.get(minute)[symbol];
      if (!bar || !Number.isFinite(Number(bar.o))) continue;
      all.push({
        t: this.barStamp(day, minute),
        minute: this.barClock(minute),
        o: Number(bar.o), h: Number(bar.h), l: Number(bar.l),
        c: Number(bar.c), v: Math.max(0, Number(bar.v) || 0),
      });
    }
    const bars = all.slice(-limit);
    const notes = [
      "built by the relay from accepted one-second quote frames, not from an exchange OHLC feed",
      "a minute's volume is the observed increase of the venue's cumulative day total between the first and last frame accepted in that minute",
      "times are ISO 8601 with the Karachi offset (+05:00)",
    ];
    if (!bars.length) {
      notes.push("no stored minute bars for this symbol and day; nothing is filled in");
      notes.push("the relay began storing bars on 2026-11-07 and keeps at most " +
        BAR_RETENTION_DAYS + " days");
    } else if (formingMinute !== null &&
               bars[bars.length - 1].minute === this.barClock(formingMinute)) {
      notes.push("the last bar is the minute still forming and can change until it closes");
    }
    if (this.barWriteError) {
      notes.push("a bar write was refused at " + this.barWriteError.at +
        "; the reason is " + this.barWriteError.message);
    }
    if (all.length > bars.length) {
      notes.push("limit returned the newest " + bars.length + " of " +
        all.length + " bars");
    }
    return {
      ok: true,
      symbol,
      day,
      resolution: "1m",
      source: "eClear broker feed, aggregated to minute bars inside the relay",
      bars,
      bar_count: bars.length,
      first_minute: bars.length ? bars[0].minute : null,
      last_minute: bars.length ? bars[bars.length - 1].minute : null,
      forming: formingMinute !== null && bars.length > 0 &&
        bars[bars.length - 1].minute === this.barClock(formingMinute),
      as_of: this.karachiStamp(Date.now()),
      retention_days: BAR_RETENTION_DAYS,
      notes,
    };
  }

  async snapshot() {
    await this.ready;
    // Owner order 2026-11-05: served from memory once loaded, so the
    // phone's every-second card read never costs a SQLite row read. The
    // cache is loaded by this one guarded read; after that the DO's own
    // reads are free for the life of the instance.
    if (this.snapshotLoaded) {
      if (this.snapshotCache) return { ok: true, ...this.snapshotCache };
      return { ok: false, quotes: [], index: null, market_feed: null,
        updated_at: null, stale: true };
    }
    try {
      const row = this.ctx.storage.sql.exec(
        "SELECT payload FROM quote_snapshot WHERE id = 1",
      ).toArray()[0];
      this.snapshotLoaded = true;
      if (!row) return { ok: true, quotes: [], index: null, market_feed: null,
        updated_at: null, stale: true };
      let parsed = null;
      try { parsed = JSON.parse(row.payload); } catch (_) { parsed = null; }
      if (!parsed) {
        return { ok: true, quotes: [], index: null, market_feed: null,
          updated_at: null, stale: true };
      }
      this.snapshotCache = parsed;
      return { ok: true, ...parsed };
    } catch (_) {
      // A storage read refused (a daily free-plan budget, reset 00:00
      // UTC, or any storage error). Answer stale-and-empty rather than
      // throwing: the caller's own catch turns this into JSON, never
      // into the edge's HTML error page.
      return { ok: false, quotes: [], index: null, market_feed: null,
        updated_at: null, stale: true };
    }
  }

  async stateGet(key) {
    await this.ready;
    const row = this.ctx.storage.sql.exec(
      "SELECT value, expires_at FROM relay_state WHERE key = ?", key,
    ).toArray()[0];
    if (!row) return null;
    if (Number(row.expires_at) > 0 && Number(row.expires_at) <= Date.now()) {
      this.stateDelete(key);
      return null;
    }
    return row.value;
  }

  async statePut(key, value, expiresAt) {
    await this.ready;
    this.ctx.storage.sql.exec(
      "INSERT INTO relay_state (key, value, expires_at) VALUES (?, ?, ?) "
      + "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
      + "expires_at = excluded.expires_at",
      key, value, expiresAt || 0,
    );
  }

  async stateDelete(key) {
    await this.ready;
    this.ctx.storage.sql.exec("DELETE FROM relay_state WHERE key = ?", key);
  }

  async stateList(prefix, limit) {
    await this.ready;
    const rows = this.ctx.storage.sql.exec(
      "SELECT key, value FROM relay_state WHERE substr(key, 1, ?) = ? "
      + "AND (expires_at = 0 OR expires_at > ?) ORDER BY key LIMIT ?",
      prefix.length, prefix, Date.now(), limit,
    ).toArray();
    return { ok: true,
      keys: rows.map((row) => ({ name: row.key, value: row.value })),
      list_complete: rows.length < limit };
  }

  // One acknowledged-frame candidate, validated. Anything malformed or
  // incoherent is refused, never normalised into a guess (SO-3).
  ackCandidate(frame) {
    if (!frame || typeof frame !== "object") return null;
    const symbol = String(frame.symbol || "").toUpperCase();
    const day = String(frame.day || "");
    const band = Number(frame.band);
    const volume = Math.round(Number(frame.volume));
    const buy = Math.round(Number(frame.buy_volume));
    const sell = Math.round(Number(frame.sell_volume));
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
    if (!/^[A-Z0-9]{1,12}$/.test(symbol)) return null;
    if (!Number.isInteger(band) || band < 1 || band > 4) return null;
    if (!Number.isFinite(volume) || volume <= 0) return null;
    if (!Number.isFinite(buy) || !Number.isFinite(sell) ||
        buy < 0 || sell < 0 || buy + sell !== volume) return null;
    return { ...frame, symbol, day, band, volume,
      buy_volume: buy, sell_volume: sell };
  }

  rememberAckFrame(day, frame) {
    if (!frame || !this.ackRowsLoaded || this.ackRowsDay !== day ||
        !this.ackRowsBySymbol) return;
    const known = this.ackRowsBySymbol[frame.symbol];
    if (!known || Number(frame.band) >= Number(known.band)) {
      this.ackRowsBySymbol[frame.symbol] = frame;
    }
  }

  // Owner order 2026-11-05: nothing this object does may ever surface as
  // the edge's HTML 1101 page again. Every throw inside the hub collapses
  // to a JSON refusal the publisher retries and the phone survives; columns
  // or limits reset at 00:00 UTC and the memory-held snapshot keeps the
  // answers moving meanwhile.
  async fetch(request) {
    try {
      return await this.handle(request);
    } catch (error) {
      try {
        await this.statePut("FLOW:LAST_ERROR", JSON.stringify({
          at: new Date().toISOString(),
          message: String((error && error.message) || error).slice(0, 200),
        }), Date.now() + 86400 * 1000);
      } catch (_) { /* diagnostics never break a refusal */ }
      return json({
        ok: false,
        error: "quote hub refused: " +
          String((error && error.message) || error).slice(0, 160),
      }, 503);
    }
  }

  async handle(request) {
    const url = new URL(request.url);
    // The relay's key value store, served by this object instead of KV.
    if (url.pathname === "/state") {
      if (request.method === "GET") {
        const key = String(url.searchParams.get("key") || "");
        if (!key) return json({ ok: false, error: "key required" }, 400);
        return json({ ok: true, value: await this.stateGet(key) });
      }
      if (request.method === "PUT") {
        const body = await request.json().catch(() => null);
        if (!body || typeof body.key !== "string" || !body.key ||
            typeof body.value !== "string") {
          return json({ ok: false, error: "key and value required" }, 400);
        }
        const ttl = Number(body.expirationTtl);
        await this.statePut(body.key, body.value,
          Number.isFinite(ttl) && ttl > 0 ? Date.now() + ttl * 1000 : 0);
        return json({ ok: true });
      }
      if (request.method === "DELETE") {
        const key = String(url.searchParams.get("key") || "");
        if (!key) return json({ ok: false, error: "key required" }, 400);
        await this.stateDelete(key);
        return json({ ok: true });
      }
      return json({ ok: false, error: "method not allowed" }, 405);
    }
    if (url.pathname === "/state/list" && request.method === "GET") {
      const prefix = String(url.searchParams.get("prefix") || "");
      const asked = Number(url.searchParams.get("limit"));
      const limit = Math.max(1, Math.min(1000, Number.isFinite(asked) ? asked : 100));
      return json(await this.stateList(prefix, limit));
    }
    // The acknowledged-frame store (owner order 2026-10-31): per
    // (Karachi day, regular-session band, symbol), the newer evidence of
    // the same venue counter, with its split clamped so the printed B and
    // S can only move as the day's volume grows. Keys live in this
    // object's own relay_state table under the ACK: prefix, two day TTL.
    if (url.pathname === "/ack-upsert" && request.method === "POST") {
      await this.ready;
      const body = await request.json().catch(() => null);
      if (!body || !Array.isArray(body.frames) || !body.frames.length ||
          body.frames.length > 20) {
        return json({ ok: false, error: "frames array (max 20) required" }, 400);
      }
      const rows = {};
      for (const frame of body.frames) {
        const parsed = this.ackCandidate(frame);
        if (!parsed) continue;
        const nowMs = Date.now();
        if (this.ackWritesDay !== parsed.day) {
          this.ackWritesDay = parsed.day;
          this.ackWritesToday = 0;
        }
        const key = `ACK:${parsed.day}:${parsed.band}:${parsed.symbol}`;
        const cachedPrevious = (this.ackRowsLoaded &&
          this.ackRowsDay === parsed.day && this.ackRowsBySymbol)
          ? (this.ackRowsBySymbol[parsed.symbol] || null) : null;
        const storedRaw = cachedPrevious ? null : await this.stateGet(key);
        let previous = cachedPrevious;
        if (!previous && storedRaw) {
          try { previous = JSON.parse(storedRaw); } catch (_) { previous = null; }
        }
        const lastAckWrite = this.lastAckWrites.get(key) || 0;
        // The mirror write is time budgeted. If the ACK row already exists
        // and was written inside the window, it is returned unchanged even
        // when the newer candidate has grown; the reading routes then use
        // applyStoredFrame's newer-frame rule, so no surface is left stale.
        if (previous && previous.symbol === parsed.symbol &&
            nowMs - lastAckWrite < ACK_WRITE_MIN_MS) {
          rows[parsed.symbol] = previous;
          this.rememberAckFrame(parsed.day, previous);
          continue;
        }
        if (previous && previous.symbol === parsed.symbol &&
            Math.round(Number(previous.volume) || 0) >= parsed.volume) {
          // Older or equal evidence never moves the acknowledged row.
          rows[parsed.symbol] = previous;
          this.rememberAckFrame(parsed.day, previous);
          continue;
        }
        if (this.ackWritesToday >= ACK_ROWS_PER_DAY) {
          // The day's mirror budget is spent. The mirror stops writing and
          // the reading side keeps its own live frame, so the card is not
          // served a stale row and the day's remaining writes stay with the
          // snapshot the app actually reads.
          if (previous && previous.symbol === parsed.symbol) {
            rows[parsed.symbol] = previous;
            this.rememberAckFrame(parsed.day, previous);
          }
          continue;
        }
        const pair = clampPair(parsed, previous &&
          previous.symbol === parsed.symbol ? previous : null);
        if (!pair) continue;
        const stored = { ...parsed, ...pair };
        await this.statePut(key, JSON.stringify(stored),
          nowMs + ACK_TTL_SECONDS * 1000);
        this.ackWritesToday += 1;
        this.lastAckWrites.set(key, nowMs);
        rows[parsed.symbol] = stored;
        this.rememberAckFrame(parsed.day, stored);
      }
      return json({ ok: true, rows });
    }

    if (url.pathname === "/ack-splits" && request.method === "GET") {
      await this.ready;
      const day = String(url.searchParams.get("day") || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
        return json({ ok: false, error: "day required" }, 400);
      }
      let ackRows;
      if (this.ackRowsLoaded && this.ackRowsDay === day &&
          this.ackRowsBySymbol) {
        ackRows = this.ackRowsBySymbol;
      } else {
        const listed = await this.stateList(`ACK:${day}:`, 2000);
        ackRows = {};
        for (const item of listed.keys || []) {
          let frame = null;
          try { frame = JSON.parse(item.value); } catch (_) { frame = null; }
          const symbolFromKey = item.name.slice(1 + item.name.lastIndexOf(":"));
          if (!frame || frame.symbol !== symbolFromKey) continue;
          const band = Number(frame.band) || 0;
          const known = ackRows[frame.symbol];
          if (!known || band >= Number(known.band || 0)) {
            ackRows[frame.symbol] = frame;
          }
        }
        this.ackRowsDay = day;
        this.ackRowsBySymbol = ackRows;
        this.ackRowsLoaded = true;
      }
      return json({ ok: true, rows: ackRows });
    }

    if (request.method === "GET" && url.pathname === "/history") {
      const answer = await this.historyAnswer(url);
      return json(answer, answer && answer.ok ? 200 : 400);
    }
    if (request.method === "GET" && url.pathname === "/bars") {
      const answer = await this.barsAnswer(url);
      return json(answer, answer && answer.ok ? 200 : 400);
    }
    if (request.method === "GET" && url.pathname === "/snapshot") {
      return json(await this.snapshot());
    }
    if (request.method === "GET" && url.pathname === "/stream") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
        return json({ ok: false, error: "websocket upgrade required" }, 426);
      }
      const selectedSymbol = String(url.searchParams.get("symbol") || "").toUpperCase();
      if (selectedSymbol && !/^[A-Z0-9]{1,12}$/.test(selectedSymbol)) {
        return json({ ok: false, error: "invalid symbol" }, 400);
      }
      const pair = new WebSocketPair();
      const client = pair[0];
      const server = pair[1];
      const tags = [QUOTE_HUB_SOCKET_TAG];
      if (selectedSymbol) tags.push(`symbol:${selectedSymbol}`);
      this.ctx.acceptWebSocket(server, tags);
      const snapshot = await this.snapshot();
      server.send(JSON.stringify({ event: "snapshot", ...snapshot,
        quotes: selectedSymbol
          ? snapshot.quotes.filter((quote) => quote.symbol === selectedSymbol)
          : snapshot.quotes }));
      return new Response(null, { status: 101, webSocket: client });
    }
    if (request.method === "POST" && url.pathname === "/update") {
      await this.ready;
      const body = await request.json().catch(() => null);
      if (!body || typeof body !== "object" || !Array.isArray(body.quotes)) {
        return json({ ok: false, error: "invalid quote update" }, 400);
      }
      // Owner order 2026-11-05: the previous snapshot comes from memory.
      // One guarded read loads it on a fresh instance; after that a push
      // never SELECTs the day's row back, so a whole session's pushes
      // cost at most one row read. If even the one load is refused, the
      // push is answered with a refusal the publisher retries, never
      // with a blank overwrite of a snapshot this object cannot read.
      let previous = this.snapshotCache;
      if (!this.snapshotLoaded) {
        let row = null;
        try {
          row = this.ctx.storage.sql.exec(
            "SELECT payload FROM quote_snapshot WHERE id = 1",
          ).toArray()[0];
          this.snapshotLoaded = true;
          if (row) {
            try { previous = JSON.parse(row.payload); }
            catch (_) { previous = null; }
          }
        } catch (_) {
          return json({ ok: false, error: "snapshot row unavailable" }, 503);
        }
      }
      // While this push is being assembled the previous snapshot stays in
      // memory: a reading poll that lands mid-push must keep seeing the
      // last accepted snapshot, never a blank.
    const flowDay = dayStamp(karachiView(Date.now()));
    let largePrints = previous && previous.flow_day === flowDay &&
      Array.isArray(previous.large_prints)
      ? previous.large_prints.slice() : [];
    let largePrintsTotal = previous && previous.flow_day === flowDay &&
      Number.isFinite(Number(previous.large_prints_total))
      ? Math.max(0, Number(previous.large_prints_total))
      : largePrints.length;
      const quotes = new Map((previous && Array.isArray(previous.quotes)
        ? previous.quotes : []).map((quote) => [quote.symbol, quote]));
      // Owner order 2026-10-31: the store serves the REGULAR session's
      // answers. A frame whose own tick sits outside its day's bands (the
      // post-market tail keeps publishing after the close) never enters,
      // so the last frame one symbol answers with is the regular-session
      // close that the card, /stock and /prices all agree on.
      const accepted = body.quotes.filter((quote) =>
        quote && typeof quote.symbol === "string" && quote.symbol &&
        frameIsTradingSession(quote));
      for (const quote of accepted) {
        const old = quotes.get(quote.symbol);
        if (old && !(Date.parse(quote.observed_at) >= Date.parse(old.observed_at))) {
          continue;
        }
        const oldKey = old ? quoteSessionKey(old) : null;
        const newKey = quoteSessionKey(quote);
        const oldVolume = Math.round(Number(old && old.volume));
        const newVolume = Math.round(Number(quote.volume));
        if (old && oldKey && newKey &&
            oldKey.day === newKey.day &&
            Number.isFinite(oldVolume) && Number.isFinite(newVolume) &&
            newVolume < oldVolume) {
          // Cumulative volume can never move backwards inside one trading
          // day. Keep the higher frame; the next real print carries a total
          // at or above it.
          continue;
        }
        // The hub's own whole-day separation rides beside the pair, under
        // its own names, so no consumer that requires buy + sell to equal
        // the total is ever handed a pair that does not. The desk reads
        // these fields and says how many shares preceded its baseline. A
        // throw here never breaks the push.
        try {
          const measured = await this.advanceFlow(quote);
          if (measured) {
            quote.measured_buy = measured.buy_volume;
            quote.measured_sell = measured.sell_volume;
            quote.flow_baseline = measured.baseline;
            quote.flow_method = "quote_rule";
            quote.flow_source = "whole-day measured at the hub: every volume increment sided by the wire's own bid/ask";
            quote.flow_rules = measured.rules || {};
            const large = largePrintFrom(quote, measured);
            if (large && large.day === flowDay) {
              largePrints.push(large);
              largePrintsTotal += 1;
            }
          }
        } catch (error) {
          // The range pair still answers. The reason is kept for /health so
          // a silent failure can never hide for long - at most one note a
          // minute, so diagnostics can never spend the day's own written
          // rows budget diagnosing itself.
          const stamp = Date.now();
          if (stamp - this.lastFlowErrorSeen >= 60000) {
            this.lastFlowErrorSeen = stamp;
            try {
              await this.statePut("FLOW:LAST_ERROR", JSON.stringify({
                at: new Date().toISOString(),
                message: String((error && error.message) || error).slice(0, 200),
              }), Date.now() + 86400 * 1000);
            } catch (ignored) { /* diagnostics never break a push */ }
          }
        }
        // The same accepted frame feeds the minute bar. Only a frame the
        // session law already accepted can shape a candle, so no post-close
        // print can extend a day's last bar (SO-3).
        this.accumulateBar(quote);
        const split = splitFromQuote(quote);
        if (split) {
          let pair = { volume: split.split_volume,
                       buy_volume: split.buy_volume,
                       sell_volume: split.sell_volume };
          const previous = old ? splitFromQuote(old) : null;
          if (previous && oldKey && newKey &&
              oldKey.day === newKey.day) {
            const clamped = clampPair(pair, previous);
            if (clamped) {
              pair = { volume: clamped.volume, buy_volume: clamped.buy,
                       sell_volume: clamped.sell };
            }
          }
          // splitFromQuote returns only a measured pair. An old range row
          // never reaches this branch, so the declared method is always the
          // wire measurement rather than an estimate.
          quote.buy_volume = pair.buy_volume;
          quote.sell_volume = pair.sell_volume;
          quote.split_volume = pair.volume;
          quote.split_method = "quote_rule";
          quote.split_source = split.split_source || quote.split_source ||
            "every volume increment sided by the wire's own bid/ask at the poll";
        } else {
          quote.buy_volume = null;
          quote.sell_volume = null;
          quote.split_volume = null;
          quote.split_method = "unavailable";
          quote.split_source =
            "no measured order-flow pair; the total is unclassified";
        }
        quotes.set(quote.symbol, quote);
      }
      // The broker's own KSE100 frame is a chart symbol too. It rides the same
      // minute store and every rollup, under its own name, so the index has
      // the same ten frames as a scrip. No KMIALLSHR level is invented: the
      // wire does not publish one and the exchange page carries only its
      // constituents.
      if (body.index && Number.isFinite(Number(body.index.value)) &&
          Number(body.index.value) > 0) {
        const indexAt = Date.parse(String(body.index.as_of || ""));
        if (Number.isFinite(indexAt) && isTradingDay(karachiView(indexAt))) {
          this.accumulateBar({ symbol: "KSE100", price: Number(body.index.value),
            observed_at: body.index.as_of, volume: 0 });
        }
      }
      const newer = (current, incoming, stamp) => {
        if (!incoming) return current || null;
        return !current || Date.parse(incoming[stamp]) >= Date.parse(current[stamp])
          ? incoming : current;
      };
      const snapshot = {
        quotes: Array.from(quotes.values()).sort((a, b) =>
          Date.parse(a.observed_at) - Date.parse(b.observed_at)).slice(-QUOTE_MAX_SYMBOLS),
        index: newer(previous && previous.index, body.index, "as_of"),
        market_feed: newer(previous && previous.market_feed,
                           body.market_feed, "as_of"),
        updated_at: (() => {
          const previousAt = Date.parse(previous && previous.updated_at || "");
          const incomingAt = Date.parse(body.captured_at);
          const latestAt = Math.max(
            Number.isFinite(previousAt) ? previousAt : 0,
            Number.isFinite(incomingAt) ? incomingAt : 0,
          );
          return latestAt ? new Date(latestAt).toISOString() : null;
        })(),
        flow_day: flowDay,
        large_prints: largePrints.slice(-LARGE_PRINT_MAX),
        large_prints_total: largePrintsTotal,
      };
      const serialized = JSON.stringify(snapshot);
      // Owner order 2026-11-05: the memory law again. The pushed
      // snapshot is authoritative in this object's memory BEFORE it is
      // persisted, and the persistence is best effort: if the day's
      // rows-written budget or any storage error refuses the write, the
      // push is still answered ok with the memory-held snapshot, the
      // phone and the desk keep reading fresh numbers, and the reason
      // is recorded once for /health (SO-3: a silent failure is never
      // allowed to hide).
      let stored = true;
      try {
        this.ctx.storage.sql.exec(
          "INSERT INTO quote_snapshot (id, payload) VALUES (1, ?) " +
          "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
          serialized,
        );
      } catch (error) {
        stored = false;
        try {
          await this.statePut("SNAPSHOT:PERSIST_ERROR", JSON.stringify({
            at: new Date().toISOString(),
            message: String((error && error.message) || error).slice(0, 200),
          }), Date.now() + 86400 * 1000);
        } catch (_) { /* diagnostics never break a push */ }
      }
      this.snapshotCache = snapshot;
      const current = { ok: true, ...snapshot };
      const answer = { ok: true, stored, quotes: accepted.length,
        refused_outside_session: body.quotes.length - accepted.length,
        updated_at: snapshot.updated_at, market_feed: current.market_feed };
      for (const socket of this.ctx.getWebSockets(QUOTE_HUB_SOCKET_TAG)) {
        const tags = this.ctx.getTags(socket);
        const selected = tags.find((tag) => tag.startsWith("symbol:"));
        const filtered = selected
          ? current.quotes.filter((quote) =>
            quote.symbol === selected.slice("symbol:".length))
          : current.quotes;
        const event = JSON.stringify({ event: "quotes", ...current,
          quotes: filtered });
        try { socket.send(event); } catch (_) { /* closed socket */ }
      }
      return json(answer);
    }
    return json({ ok: false, error: "not found" }, 404);
  }

  webSocketMessage(_socket, _message) {
    // The feed is a one-way server-pushed view; clients do not send commands.
  }

  webSocketClose(_socket, _code, _reason, _wasClean) {}

  webSocketError(_socket, _error) {}
}
