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
const STATE_HUB_NAME = "psx-live-quotes";

function stateHub(env) {
  const namespace = env.QUOTE_HUB;
  if (!namespace || typeof namespace.idFromName !== "function") return null;
  return namespace.get(namespace.idFromName(STATE_HUB_NAME));
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

// -- Owner order 2026-10-31: a new home tile, "W/L = W/L RATE",
// reads from ONE authority the relay already stores: the finalized signal
// outcomes the research archive labels (RESEARCH:OUTCOME:<date>). One
// finalized signal (PRL, 2026-10-30) landed net negative, so the answer is
// today 0/1 = 100%. The tile asks ONE question, so the relay answers it as
// ONE object, shaped once, in one place:
//   wins   = finalized trades that landed net POSITIVE
//   losses = finalized trades that landed net zero or negative
//   closed = wins + losses (both zero means the rate is not computable)
//   rate_pct = losing share of the CLOSED total, rounded
// A rate is computed only from CLOSED trades (label in the trade set with
// a finite net_return), never from a pending or partial one (SO-3).
const TRADE_OUTCOME_LABELS = new Set([
  "TP_FIRST", "SL_FIRST", "SL_AMBIG", "TIMEOUT",
]);

function winLossFromSessions(sessions) {
  let wins = 0, losses = 0;
  for (const session of sessions) {
    const label = String((session && session.label) || "").toUpperCase();
    if (!TRADE_OUTCOME_LABELS.has(label)) continue;
    const net = Number(session.net_return);
    if (!Number.isFinite(net)) continue;
    if (net > 0) wins += 1; else losses += 1;
  }
  return { wins, losses };
}

// The phone re-asks /market every second, so the ledger is read out of a
// 5-minute cache row (RESEARCH:WINLOSS) and only recomputed when that row
// is absent or expired. A cold or failing store never fabricates a rate:
// it answers zeros with a null rate and no closed rows (SO-3).
const WINLOSS_CACHE_SECONDS = 300;

async function winLossSnapshot(env) {
  const cached = await relayRead(env, "RESEARCH:WINLOSS");
  if (cached) {
    try {
      const row = JSON.parse(cached);
      const at = Date.parse(String(row.computed_at || ""));
      if (Number.isFinite(at) &&
          Date.now() - at < WINLOSS_CACHE_SECONDS * 1000) {
        return row;
      }
    } catch (_) { /* stale row: recompute */ }
  }
  const listed = await relayList(env, "RESEARCH:OUTCOME:", 1000);
  const sessions = [];
  for (const item of listed.keys) {
    if (!item.value || typeof item.value !== "string") continue;
    try {
      const row = JSON.parse(item.value);
      if (Array.isArray(row && row.sessions)) sessions.push(...row.sessions);
    } catch (_) { /* unreadable row: never counted */ }
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
function quoteHubBinding(env) {
  return env.QUOTE_HUB || null;
}
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
// Owner order 2026-10-21: pre and post market are LIVE scan windows too
// (banking broker ticks at one second), so the morning window opens at
// 08:55 PKT and a third Mon-Thu window covers 15:31 to 15:49 post-close.
const WEEKDAY_WINDOWS = [[[8, 55], [12, 30]], [[12, 30], [15, 30]],
                         [[15, 31], [15, 49]]];

const FRIDAY_WINDOWS = [[[9, 17], [12, 0]], [[14, 32], [16, 30]]];

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
    // names the RUNNABLE window (Mon-Thu 08:55-12:30, 12:30-15:30), which on
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
  return { dispatched: false, reason: "no band open" };
}

async function recordDispatch(env, note) {
  try {
    await kvPut(env, "SCAN:DISPATCH:LAST", JSON.stringify(note),
      { expirationTtl: 7 * 86400 });
  } catch (_) {
    // KV is best effort here: the state of a dispatch must never fail a cron.
  }
}

async function dispatchBandScan(env, now, band = null, source = "cron") {
  const k = karachiView(now.getTime());
  band = band || bandOpenAt(k);
  if (!band) return { dispatched: false, reason: "not a band open" };

  const token = String(env.GH_DISPATCH_TOKEN || "").trim();
  if (!token) {
    // Opt-in: without the secret the scheduled trigger is the only path.
    return { dispatched: false, reason: "GH_DISPATCH_TOKEN is not set" };
  }

  const key = `SCAN:DISPATCH:${dayStamp(k)}:${hmText(band[0])}`;
  const seen = await relayRead(env, key);
  if (seen) return { dispatched: false, reason: "already dispatched" };

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

// Store law (owner order 2026-10-31): a frame enters the quote store
// only when its own tick sits inside its own day's regular bands (with
// the grace the last band-close prints need to land). The post-market
// loop's frames keep their own feed alive but no longer overwrite the
// REGULAR session's number the app answers with.
function frameIsRegularSession(quote) {
  return regularBandIndexOf(quote) !== null && regularBandIndexOf(quote) > 0;
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

const ACK_SYMBOL_RE = /^[A-Z0-9]{1,12}$/;

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
    split_method: row.split_method || "range_position",
    split_source: row.split_source || null,
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
  try {
    const answer = await stateCall(env, "/ack-splits?day="
      + encodeURIComponent(day));
    return answer && answer.ok ? answer.rows : null;
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
  if (Number.isFinite(Number(stored.buy_volume)) &&
      Number.isFinite(Number(stored.sell_volume))) {
    row.buy_volume = Math.round(Number(stored.buy_volume));
    row.sell_volume = Math.round(Number(stored.sell_volume));
    row.split_volume = row.buy_volume + row.sell_volume;
  }
  row.split_method = "range_position";
  row.split_source = stored.split_source
    ? stored.split_source : row.split_source || null;
  row.ack_band = stored.band;
  return row;
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

// The money flow multiplier split of one session's volume. Buying is the
// volume the close's position in the range attributes to buyers, so buy + sell
// is exactly the volume it was given, which is the same total the card prints
// as T. This is a proxy for order flow and every caller labels it as one
// (SO-3). Returns null rather than guessing when the venue's fields are
// missing, contradictory, or describe no session.
function rangePositionSplit(high, low, close, volume) {
  if (![high, low, close, volume].every((v) => Number.isFinite(v))) return null;
  if (high < low || volume <= 0 || close < low || close > high) return null;
  const total = Math.round(volume);
  if (total <= 0) return null;
  const position = high === low ? 0.5 : (close - low) / (high - low);
  const buy = Math.min(Math.max(Math.round(total * position), 0), total);
  return { buy_volume: buy, sell_volume: total - buy, split_volume: total };
}

// Fetch each leader's published range and fill its split, one bounded fetch
// per leader. A symbol that cannot be read keeps nulls and a stated reason.
async function attachSplits(rows) {
  for (const row of rows) {
    const tableVolume = Number.isFinite(row.volume) ? row.volume : null;
    let quote = null;
    try {
      quote = parseSymbolRange(await portalText(PORTAL_COMPANY + row.symbol));
    } catch (e) {
      quote = null;
    }
    if (!quote) {
      row.split_method = "unavailable";
      row.split_source = "no published session range for this symbol";
      continue;
    }
    if (tableVolume !== null && Number.isFinite(quote.volume) &&
        quote.volume < tableVolume) {
      row.split_method = "unavailable";
      row.split_source = "the per-symbol panel reported less volume than " +
        "the ranking table, so its range is stale";
      continue;
    }
    // Decompose the session total the card prints as T, not the panel's own
    // copy of it: buy and sell must add up to that T on the same row, and the
    // panel's copy is fetched seconds later, so it can only be newer.
    const total = Number.isFinite(tableVolume) ? tableVolume : quote.volume;
    const split = rangePositionSplit(quote.high, quote.low, row.price, total);
    if (!split) {
      row.split_method = "unavailable";
      row.split_source = "the published session range is incomplete";
      continue;
    }
    Object.assign(row, split);
    row.split_method = "range_position";
    row.split_source = "B/S estimated from the day's range, not order flow";
  }
  return rows;
}

// The card's one sentence about the split, naming the weakest method used and
// counting any row that carries no split at all.
function splitLabel(rows) {
  const available = rows.filter((r) => Number.isFinite(r.buy_volume));
  if (!available.length) return "B/S unavailable for the leaders right now";
  const measured = available.filter((r) => r.split_method === "measured_tape").length;
  let text = measured === available.length
    ? "B/S measured from the session tape"
    : "B/S estimated from the day's range, not order flow";
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
      // The exchange's own table carries ONE volume column, so the split
      // comes from the symbol's published session range instead, and the
      // method that produced it always travels with the numbers. Null here
      // means "not read yet", never "zero" (SO-3).
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
async function buildMarketSnapshot(now) {
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
    if (!row || typeof row !== "object" || Array.isArray(row) ||
        !/^[A-Z0-9]{1,12}$/.test(String(row.symbol || "")) ||
        !Number.isFinite(row.price) || row.price <= 0 ||
        typeof row.observed_at !== "string" ||
        !Number.isFinite(Date.parse(row.observed_at))) {
      return `quotes[${i}] requires a valid symbol, positive price and timestamp`;
    }
    if (row.source !== "eClear MKT-FEED REG") {
      return `quotes[${i}] has an unsupported source or timestamp`;
    }
    for (const key of ["bid", "ask", "change", "change_pct", "volume", "high", "low"]) {
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
  const snapshot = {
    quotes,
    index: raw.index && typeof raw.index === "object" ? { ...raw.index } : null,
    market_feed: raw.market_feed && typeof raw.market_feed === "object"
      ? { ...raw.market_feed } : null,
    updated_at: raw.updated_at || raw.captured_at || null,
  };
  const now = Date.now();
  snapshot.quotes = snapshot.quotes.map((row) => {
    const age = now - Date.parse(row.observed_at || "");
    return { ...row,
      age_seconds: Number.isFinite(age) ? Math.max(0, Math.round(age / 1000)) : null,
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
  try {
    const namespace = quoteHubBinding(env);
    const id = namespace.idFromName("psx-live-quotes");
    const stub = namespace.get(id);
    const response = await stub.fetch("https://quote-hub/snapshot");
    if (!response.ok) return null;
    const body = await response.json();
    return body && body.ok ? normalizeQuoteSnapshot(body) : null;
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
// and a frame whose range is incomplete says so instead of inheriting the last
// split forever.
function splitFields(split, quote) {
  if (!split) {
    return {
      buy_volume: null,
      sell_volume: null,
      split_volume: null,
      split_method: "unavailable",
      split_source: quote
        ? "the frame's range is incomplete"
        : "no fresh frame for this symbol",
    };
  }
  return {
    buy_volume: split.buy_volume,
    sell_volume: split.sell_volume,
    split_volume: split.split_volume,
    split_method: "range_position",
    split_source: "B/S estimated from the day's range, not order flow",
  };
}

async function applyLiveQuotes(env, snapshot, quotes, now, ackDay) {
  if (!quotes) return refreshMarketFeed(snapshot, now);
  const freshQuotes = quotes.quotes.filter((row) => row.fresh &&
    Number.isFinite(row.price) && row.price > 0);
  if (freshQuotes.length) {
    const liveBySymbol = new Map(freshQuotes.map((row) => [row.symbol, row]));
    const merged = (snapshot.top_volume || []).map((row) => {
      const quote = liveBySymbol.get(row.symbol);
      if (!quote) return { ...row, quote_fresh: false };
      liveBySymbol.delete(row.symbol);
      const volume = quote.volume ?? row.volume;
      const split = rangePositionSplit(quote.high, quote.low, quote.price, volume);
      return {
        ...row,
        price: quote.price,
        volume,
        change_pct: quote.change_pct ?? row.change_pct,
        ...splitFields(split, quote),
        feed_as_of: quote.observed_at,
        feed_age_seconds: quote.age_seconds,
        observed_at: quote.observed_at,
        source_tick_time: quote.source_tick_time,
        quote_fresh: true,
        quote_source: quote.source,
      };
    });
    for (const row of liveBySymbol.values()) {
      if (Number.isFinite(row.volume) && row.volume > 0) {
        merged.push({
          ...row,
          ...splitFields(rangePositionSplit(row.high, row.low, row.price,
            row.volume), row),
          basis: "current session volume (fresh eClear REG quote)",
          quote_fresh: true,
          quote_source: row.source,
        });
      }
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
  } else if (snapshot.top_volume) {
    // Owner order 2026-10-31: with no fresh frames, the card answers from
    // the hub's own LAST PUBLISHED REGULAR-session frames of today, the
    // same frames /stock and /prices answer from, instead of the portal
    // cache's separate copy. One frame, one answer, every surface.
    const todayFrames = (quotes.quotes || []).filter((row) =>
      quoteIsFromToday(row) && Number.isFinite(row.price) && row.price > 0 &&
      Number.isFinite(row.volume) && row.volume > 0);
    if (todayFrames.length) {
      snapshot.top_volume = todayFrames.map((row) => {
        const split = rangePositionSplit(row.high, row.low, row.price,
          row.volume);
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
          observed_at: row.observed_at,
          source_tick_time: row.source_tick_time,
          quote_fresh: Boolean(row.fresh),
          quote_source: row.source,
        };
      })
        .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
        .slice(0, MARKET_TOP_N);
      snapshot.top_volume_basis = snapshot.top_volume.length
        ? `the last published regular-session frames, top ${snapshot.top_volume.length}`
        : snapshot.top_volume_basis;
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
    const frames = snapshot.top_volume
      .map((row) => ackCandidateFrame(row, ackDay))
      .filter(Boolean);
    const storedRows = await ackUpsert(env, frames);
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

async function marketResponseSnapshot(env, now) {
  const k = karachiView(now.getTime());
  const ackDay = isTradingDay(k) ? dayStamp(k) : null;
  let snapshot;
  try {
    snapshot = await marketSnapshot(env, now);
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

// Cached copy, refreshed at most once per five minutes. `force` is used by the
// runner's own push path, never by an app poll.
async function marketSnapshot(env, now) {
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
    } catch (_) {
      // malformed cache: fall through and rebuild
    }
  }
  const fresh = normalizeMarket(await buildMarketSnapshot(now));
  fresh.built_at = now.toISOString();
  fresh.cache_age_seconds = 0;
  await kvPut(env, "MARKET", JSON.stringify(fresh), { expirationTtl: 3600 });
  return fresh;
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
  return {
    ok: true,
    service: "quant-of-rehan-relay",
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
    headers: { "content-type": "application/json", ...extraHeaders },
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
        (path === "/quotes" || path === "/quotes/stream")) {
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
      const namespace = quoteHubBinding(env);
      const hub = namespace.get(namespace.idFromName("psx-live-quotes"));
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

    if (request.method === "GET" && path === "/quotes") {

      const snapshot = await readQuoteSnapshot(env);
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
      const namespace = quoteHubBinding(env);
      const hubId = namespace.idFromName("psx-live-quotes");
      const hub = namespace.get(hubId);
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
        snapshot = await marketResponseSnapshot(env, now);
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
      const quote = quotes.find((q) => q && q.symbol === symbol &&
                                  quoteIsFromToday(q)) || null;
      if (!quote) {
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
        split_method: "unavailable",
        split_source: "the frame's range is incomplete",
        observed_at: quote.observed_at || null,
        source_tick_time: quote.source_tick_time || null,
      };
      const split = rangePositionSplit(quote.high, quote.low,
                                       quote.price, quote.volume);
      if (split) {
        Object.assign(stock, split);
        stock.split_method = "range_position";
        stock.split_source = quote.fresh
          ? "B/S estimated from the day's range, not order flow"
          : "B/S estimated from the symbol's last published frame; the market is closed";
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
          stock.split_source = quote.fresh
            ? "B/S estimated from the day's range, not order flow"
            : "B/S estimated from the symbol's last published frame; the market is closed";
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
      const ackDay = isTradingDay(kNow) ? dayStamp(kNow) : null;
      // Owner order 2026-10-31: every row is the acknowledged frame the
      // card and /stock answer with, so the search's rows, the dropdown
      // rankings and the card hold ONE B/S pair per stock. The stored map
      // is one read; the busiest symbols acknowledge their own rows.
      const storedAll = ackDay ? await ackRowsForDay(env, ackDay) : null;
      const prices = [];
      const rowsBuilt = [];
      for (const quote of (snapshot && snapshot.quotes) || []) {
        if (!quote || !quoteIsFromToday(quote) ||
            !Number.isFinite(quote.price) || quote.price <= 0) continue;
        // The volume dropdowns (owner order 2026-10-23) rank scrips by their
        // published split, so each row carries the same B/S pair the /stock
        // route computes: the day's range is the frame it is split from, and
        // a frame whose range is incomplete ships nulls instead of guessing
        // (SO-3). The exclusion row stays the row: the phone reads a row of
        // five, and indexes beyond three stay null.
        const split = rangePositionSplit(quote.high, quote.low,
                                         quote.price, quote.volume);
        rowsBuilt.push({
          symbol: String(quote.symbol || ""),
          price: quote.price,
          change_pct: Number.isFinite(quote.change_pct) ? quote.change_pct : null,
          volume: Number.isFinite(quote.volume) ? Math.round(quote.volume) : null,
          buy_volume: split ? split.buy_volume : null,
          sell_volume: split ? split.sell_volume : null,
          split_method: split ? "range_position" : "unavailable",
          split_source: split ? "B/S estimated from the day's range, not order flow" : null,
          observed_at: quote.observed_at || null,
          source: quote.source || null,
        });
      }
      if (ackDay && rowsBuilt.length) {
        // The day's busiest symbols acknowledge their rows (bounded: six
        // frames), which is enough for every dropdown ranking the phone
        // prints and for the card's own top three.
        const top = rowsBuilt
          .filter((row) => Number.isFinite(row.volume) && row.volume > 0)
          .sort((a, b) => b.volume - a.volume)
          .slice(0, 6)
          .map((row) => ackCandidateFrame(row, ackDay))
          .filter(Boolean);
        const storedTop = await ackUpsert(env, top);
        if (storedAll === null && storedTop) {
          // no prefix at all, but the upsert answered: use its map
          for (const row of rowsBuilt) applyStoredFrame(row, storedTop[row.symbol]);
        } else if (storedAll || storedTop) {
          for (const row of rowsBuilt) {
            applyStoredFrame(row, (storedAll || {})[row.symbol] ||
              (storedTop || {})[row.symbol] || null);
          }
        }
      }
      for (const row of rowsBuilt) {
        prices.push([
          row.symbol,
          row.price,
          row.change_pct,
          row.buy_volume,
          row.sell_volume,
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
        snapshot = await marketResponseSnapshot(env, now);
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

    if (request.method === "POST" && path === "/research/outcome") {
      const body = await request.json().catch(() => null);
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(String(body.date || "")) ||
          !Array.isArray(body.sessions) || body.sessions.length !== 1) {
        return json({ ok: false, error: "invalid daily outcome" }, 400);
      }
      const key = `RESEARCH:OUTCOME:${body.date}`;
      const existing = await relayRead(env, key);
      if (existing) return json({ ok: true, stored: false, immutable: true });
      await kvPut(env, key, JSON.stringify(body),
        { expirationTtl: 63072000 });
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
      }
      const k = karachiView(now.getTime());
      const next = nextEvent(now);
      const signals = (await kvGet(env, "SIGNALS")) || "";
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

// One SQLite-backed object holds the latest broker frame set. Producer
// requests are coalesced to at most once per second by the cloud capture;
// connected browsers receive server-pushed changes without one DO request per
// client poll. Values are source-timestamped and stale rows remain explicitly
// stale rather than being advanced by the relay clock.
export class QuoteHub {
  constructor(ctx, env) {
    this.ctx = ctx;
    this.env = env;
    this.ready = ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS quote_snapshot (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)",
      );
      // The relay's own key space. It replaced KV on 2026-10-20 so the
      // relay needs no quota-limited product to hold a card.
      ctx.storage.sql.exec(
        "CREATE TABLE IF NOT EXISTS relay_state (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at INTEGER NOT NULL DEFAULT 0)",
      );
    });
  }

  async snapshot() {
    await this.ready;
    const row = this.ctx.storage.sql.exec(
      "SELECT payload FROM quote_snapshot WHERE id = 1",
    ).toArray()[0];
    if (!row) {
      return { ok: true, quotes: [], index: null, market_feed: null,
        updated_at: null, stale: true };
    }
    const snapshot = normalizeQuoteSnapshot(JSON.parse(row.payload));
    return { ok: true, ...snapshot };
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

  async fetch(request) {
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
        const key = `ACK:${parsed.day}:${parsed.band}:${parsed.symbol}`;
        const storedRaw = await this.stateGet(key);
        let previous = null;
        if (storedRaw) {
          try { previous = JSON.parse(storedRaw); } catch (_) { previous = null; }
        }
        if (previous && previous.symbol === parsed.symbol &&
            Math.round(Number(previous.volume) || 0) >= parsed.volume) {
          // Older or equal evidence never moves the acknowledged row.
          rows[parsed.symbol] = previous;
          continue;
        }
        const pair = clampPair(parsed, previous &&
          previous.symbol === parsed.symbol ? previous : null);
        if (!pair) continue;
        const stored = { ...parsed, ...pair };
        await this.statePut(key, JSON.stringify(stored),
          Date.now() + ACK_TTL_SECONDS * 1000);
        rows[parsed.symbol] = stored;
      }
      return json({ ok: true, rows });
    }

    if (url.pathname === "/ack-splits" && request.method === "GET") {
      await this.ready;
      const day = String(url.searchParams.get("day") || "");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) {
        return json({ ok: false, error: "day required" }, 400);
      }
      const listed = await this.stateList(`ACK:${day}:`, 2000);
      const ackRows = {};
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
      return json({ ok: true, rows: ackRows });
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
      let previous = null;
      const row = this.ctx.storage.sql.exec(
        "SELECT payload FROM quote_snapshot WHERE id = 1",
      ).toArray()[0];
      if (row) {
        try { previous = JSON.parse(row.payload); } catch (_) { previous = null; }
      }
      const quotes = new Map((previous && Array.isArray(previous.quotes)
        ? previous.quotes : []).map((quote) => [quote.symbol, quote]));
      // Owner order 2026-10-31: the store serves the REGULAR session's
      // answers. A frame whose own tick sits outside its day's bands (the
      // post-market tail keeps publishing after the close) never enters,
      // so the last frame one symbol answers with is the regular-session
      // close that the card, /stock and /prices all agree on.
      const accepted = body.quotes.filter((quote) =>
        quote && typeof quote.symbol === "string" && quote.symbol &&
        frameIsRegularSession(quote));
      for (const quote of accepted) {
        const old = quotes.get(quote.symbol);
        if (!old || Date.parse(quote.observed_at) >= Date.parse(old.observed_at)) {
          quotes.set(quote.symbol, quote);
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
      };
      const serialized = JSON.stringify(snapshot);
      this.ctx.storage.sql.exec(
        "INSERT INTO quote_snapshot (id, payload) VALUES (1, ?) " +
        "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
        serialized,
      );
      const current = await this.snapshot();
      const answer = { ok: true, stored: true, quotes: accepted.length,
        refused_post_session: body.quotes.length - accepted.length,
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
