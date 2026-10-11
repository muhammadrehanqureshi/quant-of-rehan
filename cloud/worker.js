// quant-of-rehan Telegram relay, deployed on the Cloudflare edge.
//
// Why this exists (SO-9): Telegram is blocked for direct connections inside
// Pakistan, so the owner's PC never calls api.telegram.org. This worker runs
// on Cloudflare's network outside that block and forwards to Telegram. The
// owner reads messages on his phone over his VPN, exactly as he always has.
//
// SO-8: the daily open/close schedule here is computed from a fixed UTC+5
// offset (Karachi has had no daylight saving since 1971). It never uses the
// container clock zone and never any other timezone.
//
// SO-5: secrets live in worker bindings only (set by cloud/pair.py from the
// owner's PC), never in this file, never in the repo:
//   TELEGRAM_BOT_TOKEN  the new quant-of-rehan bot token
//   RELAY_ADMIN_TOKEN   gates /pair and /notify against strangers
//   PAIRED_CHAT_ID      the owner's chat, set by the pairing script
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
//   POST /pair/start    admin only: find the chat that just messaged the bot,
//                       store a pairing code in KV and send the code to it
//   POST /pair/confirm  admin only: {code} -> sets the paired chat id
//   POST /notify        admin only: {text, kind} forwarded to the paired chat
//   GET  /updates       admin only: raw getUpdates proxy for local debugging
//
// Cron triggers (UTC, set by cloud/pair.py). Friday is TWO sessions with
// the exchange's midday break between them, so it has four edges:
//   04:32 Mon-Thu = 09:32 PKT open  | 10:30 Mon-Thu = 15:30 PKT close
//   04:17 Fri     = 09:17 PKT open  | 07:00 Fri     = 12:00 PKT close
//   09:32 Fri     = 14:32 PKT open  | 11:30 Fri     = 16:30 PKT close

const KARACHI_OFFSET_MIN = 5 * 60; // SO-8: UTC+5, fixed forever

// Owner order 2026-10-08: name the market event first, then the quant
// state (SO-9).
const MSG_OPEN = "Market is open. Quant is online now.";
const MSG_CLOSED = "Market is closed. Quant is sleeping now.";

// Owner's exact condition texts (order of 2026-10-11), mirroring
// src/data/sessions.py. The break sentence is for the exchange's own Friday
// midday break and nothing else.
const CONDITION_BREAK = "Market is on a break right now.";
const CONDITION_CLOSED = "Market is closed right now.";

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
  return { ...s,
    index,
    kmiall_members: members,
    top_volume: rows,
    top_volume_basis:
      typeof s.top_volume_basis === "string" ? s.top_volume_basis : null,
    notes: Array.isArray(s.notes) ? s.notes : [] };
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
  const cachedRaw = await env.RELAY_KV.get("MARKET");
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
  await env.RELAY_KV.put("MARKET", JSON.stringify(fresh), { expirationTtl: 3600 });
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

async function latestChat(env) {
  const updates = await tgCall(env, "getUpdates", { limit: 50 });
  if (!updates.ok) return { error: updates.description || "getUpdates refused" };
  let best = null;
  for (const u of updates.result || []) {
    const m = u.message || u.channel_post || {};
    if (!m.chat || m.chat.id === undefined) continue;
    if (!best || (m.date || 0) > (best.date || 0)) best = m;
  }
  if (!best) return { error: "no chat has messaged this bot recently" };
  return { chat: best.chat, date: best.date || 0 };
}

async function tgCall(env, method, params) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(params),
  });
  return r.json().catch(() => ({}));
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj, null, 2), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;

    if (request.method === "GET" && path === "/health") {
      const now = new Date();
      const k = karachiView(now.getTime());
      const next = nextEvent(now);
      return json({
        ok: true,
        service: "quant-of-rehan-relay",
        karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        // The app shows ONLINE only while a session is live, so the state is
        // answered by the same session law the notifications use (SO-8).
        // `market_state.phase` is the authoritative word (OPEN, BREAK,
        // CLOSED, PRE_OPEN, POST_CLOSE); `market_open` is kept for older
        // clients and is exactly `phase === "OPEN"`.
        market_open: marketOpenNow(now),
        market_state: marketState(now),
        paired: Boolean((await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID),
        next_event: next.event
          ? { event: next.event, at_pk: `${dayStamp(karachiView(next.at.getTime()))} ${hhmm(karachiView(next.at.getTime()))}` }
          : null,
      });
    }

    if (request.method === "POST" && path === "/pair/start") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const found = await latestChat(env);
      if (found.error) {
        return json({ ok: false, error: found.error }, 404);
      }
      const code = String(Math.floor(1000 + Math.random() * 9000));
      await env.RELAY_KV.put("PENDING_CODE", code, { expirationTtl: 3600 });
      await env.RELAY_KV.put("PENDING_CHAT", String(found.chat.id), { expirationTtl: 3600 });
      const name = found.chat.title || found.chat.username || found.chat.first_name || "";
      await tgCall(env, "sendMessage", {
        chat_id: found.chat.id,
        text: `Pairing code for quant-of-rehan: ${code}\nIf you did not request this, ignore it.`,
      });
      return json({ ok: true, chat_kind: found.chat.type, chat_name: name });
    }

    if (request.method === "POST" && path === "/pair/confirm") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const body = await request.json().catch(() => ({}));
      const code = String(body.code || "").trim();
      const pending = (await env.RELAY_KV.get("PENDING_CODE")) || "";
      const chat = (await env.RELAY_KV.get("PENDING_CHAT")) || "";
      if (!pending || !chat) {
        return json({ ok: false, error: "no pending pairing; run pair/start" }, 409);
      }
      if (code !== pending) {
        return json({ ok: false, error: "wrong code" }, 403);
      }
      await env.RELAY_KV.put("PAIRED_CHAT_ID", chat);
      await env.RELAY_KV.delete("PENDING_CODE");
      await env.RELAY_KV.delete("PENDING_CHAT");
      await tgCall(env, "sendMessage", {
        chat_id: chat,
        text: "quant-of-rehan relay paired with this chat. Daily open and close notifications and trading signals will arrive here.",
      });
      return json({ ok: true, paired_chat: chat });
    }

    if (request.method === "POST" && path === "/notify") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const paired = (await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID;
      if (!paired) {
        return json({ ok: false, error: "not paired; run cloud/pair.py start then confirm" }, 409);
      }
      const body = await request.json().catch(() => ({}));
      const text = String(body.text || "");
      const kind = String(body.kind || "signals");
      if (!text) {
        return json({ ok: false, error: "empty text" }, 400);
      }
      // Owner order 2026-10-08: scheduled ops alerts (capture degraded,
      // push retry pending) must cost at most ONE Telegram message per day
      // per distinct text. kind "ops" dedupes on (UTC date, text); signal
      // traffic (kind "signals") is deduped upstream by the push journal.
      if (kind === "ops") {
        const day = new Date().toISOString().slice(0, 10);
        let digest = "";
        try {
          digest = await crypto.subtle.digest("SHA-256",
              new TextEncoder().encode(text));
          digest = Array.from(new Uint8Array(digest)).slice(0, 8)
              .map((b) => b.toString(16).padStart(2, "0")).join("");
        } catch (e) {
          digest = String(text.length);
        }
        const alertKey = `ALERT:${day}:${digest}`;
        const seen = await env.RELAY_KV.get(alertKey);
        if (seen) return json({ ok: true, deduped: true });
        await env.RELAY_KV.put(alertKey, "1", { expirationTtl: 172800 });
        const sent = await tgCall(env, "sendMessage", { chat_id: paired, text });
        if (sent.ok) return json({ ok: true, deduped: false });
        return json({ ok: false, error: sent.description || "telegram refused" }, 502);
      }
      const sent = await tgCall(env, "sendMessage", { chat_id: paired, text });
      if (sent.ok) return json({ ok: true });
      return json({ ok: false, error: sent.description || "telegram refused" }, 502);
    }

    if (request.method === "GET" && path === "/market") {
      // Companion app card (public: exchange data, no secrets). Served from
      // the five minute cache; the portal is contacted only when it expires.
      const now = new Date();
      let snapshot;
      try {
        snapshot = await marketSnapshot(env, now);
      } catch (e) {
        const fallback = await env.RELAY_KV.get("MARKET");
        if (!fallback) {
          return json({ ok: false, error: "market data unavailable",
            market_open: marketOpenNow(now), market_state: marketState(now) }, 503);
        }
        snapshot = normalizeMarket(JSON.parse(fallback));
        snapshot.stale = true;
        snapshot.market_open = marketOpenNow(now);
        snapshot.market_state = marketState(now);
      }
      const k = karachiView(now.getTime());
      const edgeState = marketState(now);
      return json({ ok: true, karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        ...snapshot,
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
      body.built_at = new Date().toISOString();
      await env.RELAY_KV.put("MARKET", JSON.stringify(body), { expirationTtl: 3600 });
      return json({ ok: true, stored: true });
    }

    if (path.startsWith("/research/") && !adminOk(request, env)) {
      return json({ ok: false, error: "admin token required" }, 403);
    }

    if (request.method === "POST" && path === "/research/observation") {
      const body = await request.json().catch(() => null);
      if (!body || !/^\d{4}-\d{2}-\d{2}$/.test(String(body.date || "")) ||
          !/^\d{2}:\d{2}$/.test(String(body.slot || "")) ||
          !body.snapshot || typeof body.snapshot !== "object") {
        return json({ ok: false, error: "invalid observation" }, 400);
      }
      const key = `RESEARCH:OBS:${body.date}:${body.slot.replace(":", "")}`;
      const existing = await env.RELAY_KV.get(key);
      if (existing) return json({ ok: true, key, stored: false, immutable: true });
      await env.RELAY_KV.put(key, JSON.stringify(body), { expirationTtl: 63072000 });
      return json({ ok: true, key, stored: true });
    }

    if (request.method === "GET" && path === "/research/observations") {
      const date = url.searchParams.get("date") || "";
      if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) {
        return json({ ok: false, error: "date required" }, 400);
      }
      const listed = await env.RELAY_KV.list({ prefix: `RESEARCH:OBS:${date}:`, limit: 100 });
      const observations = [];
      for (const item of listed.keys) {
        const value = await env.RELAY_KV.get(item.name);
        if (value) observations.push(JSON.parse(value));
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
      const existing = await env.RELAY_KV.get(key);
      if (existing) return json({ ok: true, stored: false, immutable: true });
      await env.RELAY_KV.put(key, JSON.stringify(body),
        { expirationTtl: 63072000 });
      return json({ ok: true, stored: true });
    }

    if (request.method === "GET" && path === "/research/history") {
      const listed = await env.RELAY_KV.list({ prefix: "RESEARCH:OUTCOME:", limit: 1000 });
      const sessions = [];
      for (const item of listed.keys) {
        const value = await env.RELAY_KV.get(item.name);
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
          !/^\d{2}:\d{2}$/.test(String(body.slot || ""))) {
        return json({ ok: false, error: "invalid signal claim" }, 400);
      }
      const key = `RESEARCH:SENT:${body.date}`;
      if (await env.RELAY_KV.get(key)) return json({ ok: true, claimed: false });
      await env.RELAY_KV.put(key, String(body.slot), { expirationTtl: 86400 });
      return json({ ok: true, claimed: true });
    }

    if (request.method === "GET" && path === "/research/gate") {
      const value = await env.RELAY_KV.get("RESEARCH:PRODUCTION_GATE");
      return json({ ok: true, gate: value ? JSON.parse(value) : null });
    }

    if (request.method === "POST" && path === "/research/gate") {
      const body = await request.json().catch(() => null);
      if (!body || typeof body.eligible !== "boolean" ||
          typeof body.status !== "string" || !body.rule_version) {
        return json({ ok: false, error: "invalid gate record" }, 400);
      }
      await env.RELAY_KV.put("RESEARCH:PRODUCTION_GATE", JSON.stringify(body));
      return json({ ok: true });
    }

    if (request.method === "GET" && path === "/updates") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const updates = await tgCall(env, "getUpdates", { limit: 20 });
      return json(updates);
    }

    if (request.method === "GET" && path === "/signals") {
      // Companion app poll (admin gated). Serves the latest signals the
      // local runner pushed to KV plus the Karachi schedule for the card.
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const now = new Date();
      const k = karachiView(now.getTime());
      const next = nextEvent(now);
      const signals = (await env.RELAY_KV.get("SIGNALS")) || "";
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
      await env.RELAY_KV.put("SIGNALS", text);
      return json({ ok: true, stored: text.length });
    }

    return json({ ok: false, error: "not found" }, 404);
  },

  // Cron handler: fires the owner's two texts at EVERY PKT band edge, so a
  // Friday break produces the exact pair of texts the owner already knows:
  // "Market is closed. Quant is sleeping now." at 12:00 and "Market is open.
  // Quant is online now." at 14:32.
  async scheduled(controller, env, ctx) {
    const now = new Date();
    const k = karachiView(now.getTime());
    const bands = bandsFor(k);
    if (!bands.length) return;
    const paired = (await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID;
    if (!paired) return;

    const mins = minutesOf(k);
    const near = (hm) => Math.abs(mins - (hm[0] * 60 + hm[1])) <= 2;

    let text = null;
    for (const band of bands) {
      if (near(band[0])) { text = MSG_OPEN; break; }
      if (near(band[1])) { text = MSG_CLOSED; break; }
    }
    if (!text) return;

    ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: paired, text }));
  },
};
