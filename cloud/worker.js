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

const QUOTE_HUB_SOCKET_TAG = "live-quotes";
function quoteHubBinding(env) {
  return env.QUOTE_HUB || env.RELAY_KV;
}
// Owner order 2026-10-08: name the market event first, then the quant
// state (SO-9).
const MSG_OPEN = "Market is open. Quant is online now.";
const MSG_CLOSED = "Market is closed. Quant is sleeping now.";

// Owner's exact condition texts (order of 2026-10-11), mirroring
// src/data/sessions.py. The break sentence is for the exchange's own Friday
// midday break and nothing else.
const CONDITION_BREAK = "Market is on a break right now.";
const CONDITION_CLOSED = "Market is closed right now.";
const MSG_MARKET_OPEN = "Market is open. Quant is online now.";
const MSG_MARKET_CLOSED = "Market is closed. Quant is sleeping now.";
const MSG_MARKET_BREAK = "Market is on a break. Quant is sleeping until the market reopens.";
const MSG_MARKET_HALTED = "Market is halted now. Quant is sleeping until the market reopens.";
const MARKET_STATUS_MAX_AGE_MS = 90 * 1000;
const MARKET_OPEN_GRACE_MS = 5 * 60 * 1000;
const MARKET_TRANSITION_RETRY_MS = 5 * 60 * 1000;
const MARKET_STATE_KEY = "MARKET:LAST_CONFIRMED_STATE";
const MARKET_PENDING_KEY = "MARKET:NOTIFICATION_PENDING";
const MARKET_DELIVERY_KEY = "MARKET:LAST_NOTIFICATION";
const QUOTE_MAX_AGE_MS = 90 * 1000;
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

function marketNotificationText(state) {
  if (state === "OPEN") return MSG_MARKET_OPEN;
  if (state === "BREAK") return MSG_MARKET_BREAK;
  if (state === "CLOSED") return MSG_MARKET_CLOSED;
  if (state === "HALTED") return MSG_MARKET_HALTED;
  return null;
}

async function deliverMarketTransition(env, chatId, state, identity, evidence, now) {
  const text = marketNotificationText(state);
  const currentRaw = await env.RELAY_KV.get(MARKET_PENDING_KEY);
  let current = null;

  try {
    current = currentRaw ? JSON.parse(currentRaw) : null;
  } catch (_) {
    current = null;
  }
  // A superseding feed observation may have replaced this pending transition.
  if (!text || !current || current.identity !== identity) return;

  const record = await sendAndRecord(env, chatId, text, "market", null);
  if (!record.ok) {
    const latestRaw = await env.RELAY_KV.get(MARKET_PENDING_KEY);
    try {
      const latest = latestRaw ? JSON.parse(latestRaw) : null;
      if (latest && latest.identity === identity) {
        latest.retry_after_ms = Date.now() + MARKET_TRANSITION_RETRY_MS;
        latest.error = record.description;
        await env.RELAY_KV.put(MARKET_PENDING_KEY, JSON.stringify(latest),
                               { expirationTtl: 3600 });
      }
    } catch (_) {
      // A malformed retry marker cannot turn a failed send into a success.
    }
    return;
  }

  const latestRaw = await env.RELAY_KV.get(MARKET_PENDING_KEY);
  try {
    const latest = latestRaw ? JSON.parse(latestRaw) : null;
    if (!latest || latest.identity !== identity) return;
  } catch (_) {
    return;
  }
  await env.RELAY_KV.put(MARKET_STATE_KEY, JSON.stringify({
    state, identity, confirmed_at_ms: Date.now(), evidence,
  }), { expirationTtl: 604800 });
  await env.RELAY_KV.put(MARKET_DELIVERY_KEY, JSON.stringify({
    state, text, at: new Date().toISOString(), evidence,
  }), { expirationTtl: 604800 });
  await env.RELAY_KV.delete(MARKET_PENDING_KEY);
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

function applyLiveQuotes(snapshot, quotes, now) {
  if (!quotes) return refreshMarketFeed(snapshot, now);
  const freshQuotes = quotes.quotes.filter((row) => row.fresh &&
    Number.isFinite(row.price) && row.price > 0);
  if (freshQuotes.length) {
    const previous = new Map((snapshot.top_volume || []).map((row) => [row.symbol, row]));
    const liveBySymbol = new Map(freshQuotes.map((row) => [row.symbol, row]));
    const merged = (snapshot.top_volume || []).map((row) => {
      const quote = liveBySymbol.get(row.symbol);
      if (!quote) return { ...row, quote_fresh: false };
      liveBySymbol.delete(row.symbol);
      return {
        ...row,
        price: quote.price,
        volume: quote.volume ?? row.volume,
        change_pct: quote.change_pct ?? row.change_pct,
        feed_as_of: quote.observed_at,
        feed_age_seconds: quote.age_seconds,
        quote_fresh: true,
        quote_source: quote.source,
      };
    });
    for (const row of liveBySymbol.values()) {
      if (Number.isFinite(row.volume) && row.volume > 0) {
        merged.push({
          ...row,
          basis: "current session volume (fresh eClear REG quote)",
          quote_fresh: true,
          quote_source: row.source,
        });
      }
    }
    snapshot.top_volume = merged
      .filter((row) => Number.isFinite(row.volume) && row.volume > 0)
      .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
      .slice(0, MARKET_TOP_N);
    snapshot.top_volume_basis = snapshot.top_volume.length
      ? `current session volume, top ${snapshot.top_volume.length} from fresh REG feed`
      : snapshot.top_volume_basis;
  } else if (snapshot.top_volume) {
    snapshot.top_volume = snapshot.top_volume.map((row) => ({
      ...row, quote_fresh: false,
    }));
  }
  if (quotes.index && quotes.index.fresh) {
    snapshot.index = quotes.index;
  }
  if (quotes.market_feed && quotes.market_feed.fresh) {
    snapshot.market_feed = quotes.market_feed;
  }
  snapshot.quote_snapshot_updated_at = quotes.updated_at;
  snapshot.quote_snapshot_stale = quotes.stale;
  return refreshMarketFeed(snapshot, now);
}

async function marketResponseSnapshot(env, now) {
  let snapshot;
  try {
    snapshot = await marketSnapshot(env, now);
  } catch (e) {
    const fallback = await env.RELAY_KV.get("MARKET");
    if (!fallback) throw e;
    snapshot = normalizeMarket(JSON.parse(fallback));
    snapshot.stale = true;
    snapshot.market_open = marketOpenNow(now);
    snapshot.market_state = marketState(now);
  }
  return applyLiveQuotes(snapshot, await readQuoteSnapshot(env), now);
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
  }

  const day = edge.date;
  const identity = `${day}:${state}`;
  let previous = null;
  let pending = null;
  const [raw, waiting] = await Promise.all([
    env.RELAY_KV.get(MARKET_STATE_KEY),
    env.RELAY_KV.get(MARKET_PENDING_KEY),
  ]);
  try {
    previous = raw ? JSON.parse(raw) : null;
  } catch (_) {
    previous = null;
  }
  try {
    pending = waiting ? JSON.parse(waiting) : null;
  } catch (_) {
    pending = null;
  }
  if (previous && previous.identity === identity) {
    return { state, evidence, delivered: false, duplicate: true };
  }
  if (pending && pending.identity === identity &&
      now.getTime() < Number(pending.retry_after_ms || 0)) {
    return { state, evidence, delivered: false, pending: true };
  }

  const oldState = previous && previous.state;
  const oldDay = previous && typeof previous.identity === "string"
    ? previous.identity.slice(0, 10) : "";
  const bandOpen = edge.live_band && edge.live_band.open;
  const openAt = bandOpen ? Date.parse(`${day}T${bandOpen}:00+05:00`) : NaN;
  const withinOpeningGrace = Number.isFinite(openAt) &&
    now.getTime() >= openAt && now.getTime() - openAt <= MARKET_OPEN_GRACE_MS;
  const retryPending = pending && pending.identity === identity &&
    now.getTime() >= Number(pending.retry_after_ms || 0);
  const shouldNotify = retryPending || (state === "BREAK" || state === "CLOSED"
    ? oldState !== state || (!previous && evidence === "session_schedule" &&
      (state === "BREAK" ||
       (Number.isFinite(openAt) && now.getTime() - openAt <= MARKET_OPEN_GRACE_MS)))
    : state === "HALTED"
      ? oldState !== "HALTED"
      : oldState === "HALTED" || oldState === "BREAK" || oldState === "CLOSED" ||
        (oldDay !== "" && oldDay !== day) || (!previous && withinOpeningGrace));
  if (!shouldNotify) {
    // Seed a baseline when first observing OPEN after the opening grace. This
    // prevents a later app launch from replaying a greeting hours late.
    if (state === "OPEN") {
      await env.RELAY_KV.put(MARKET_STATE_KEY, JSON.stringify({
        state, identity, confirmed_at_ms: now.getTime(), evidence,
      }), { expirationTtl: 604800 });
    }
    return { state, evidence, delivered: false, baseline: true };
  }
  const paired = (await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID;
  if (!paired) return { state, evidence, delivered: false, reason: "not paired" };

  // Reserve the identity before scheduling I/O: overlapping one-second app
  // reads and 30-second feed pushes cannot queue duplicate Telegram messages.
  await env.RELAY_KV.put(MARKET_PENDING_KEY, JSON.stringify({
    state, identity, evidence, at: now.toISOString(),
    retry_after_ms: now.getTime() + 60000,
  }), { expirationTtl: 3600 });
  ctx.waitUntil(deliverMarketTransition(env, paired, state, identity, evidence, now));
  return { state, evidence, delivered: false, delivery: "pending" };
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

//: The last send's outcome, kept in KV so /status can report it.
//
// The owner asked for four different facts to stay four different facts: a
// candidate was generated, a notification was attempted, the relay accepted
// it, and Telegram delivered it. Only the relay can see the last of those, so
// it records it here instead of letting a fast sender guess.
async function sendAndRecord(env, chatId, text, kind, dedupeKey) {
  const sent = await tgCall(env, "sendMessage", { chat_id: chatId, text },
                            TELEGRAM_SEND_TIMEOUT_MS);
  const record = {
    at: new Date().toISOString(),
    kind: String(kind || "signals"),
    ok: Boolean(sent.ok),
    description: String(sent.description || (sent.ok ? "ok" : "unknown"))
        .slice(0, 200),
  };
  try {
    await env.RELAY_KV.put("DELIVERY:LAST", JSON.stringify(record),
                            { expirationTtl: 604800 });
    // The ops dedupe key is written ONLY after Telegram accepted the message.
    // It used to be written before the send, so a failed alert was suppressed
    // by its own attempt and never retried (measured 2026-10-16: a labelled
    // test alert was deduped away while Telegram answered nothing).
    if (sent.ok && dedupeKey) {
      await env.RELAY_KV.put(dedupeKey, "1", { expirationTtl: 172800 });
    }
  } catch (_) {
    // The record is best effort: the send itself has already happened, and a
    // missing record must never turn a delivered message into a claimed one.
  }
  return record;
}

async function healthPayload(env) {
  const now = new Date();
  const k = karachiView(now.getTime());
  const next = nextEvent(now);
  let lastDelivery = null;
  let marketFeed = null;
  try {
    const cachedMarket = await env.RELAY_KV.get("MARKET");
    if (cachedMarket) {
      const parsed = JSON.parse(cachedMarket);
      marketFeed = parsed.market_feed || null;
    }
  } catch (_) {
    marketFeed = null;
  }
  try {
    const raw = await env.RELAY_KV.get("DELIVERY:LAST");
    lastDelivery = raw ? JSON.parse(raw) : null;
  } catch (_) {
    lastDelivery = null;
  }
  return {
    ok: true,
    service: "quant-of-rehan-relay",
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
    paired: Boolean((await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID),
    // What the last Telegram send actually did, as the relay saw it. Null
    // means no send has been recorded yet, which is not the same as a
    // successful one.
    last_delivery: lastDelivery,
    next_event: next.event
      ? { event: next.event, at_pk: `${dayStamp(karachiView(next.at.getTime()))} ${hhmm(karachiView(next.at.getTime()))}` }
      : null,
  };
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

//: Telegram's own deadline, in milliseconds.
//
// Measured live 2026-10-16: an unbounded sendMessage took 42.2 seconds to
// answer, while every client of this relay (scripts/intraday_pipeline.py,
// scripts/ops_alert.py, src/signals/signal_push.py) gives up at 30. A sender
// that times out cannot tell a refusal from a slow yes, so the message would
// arrive on the phone and the sender would still record a failure. Ten
// seconds is far above Telegram's normal latency and comfortably inside the
// client's budget, so a deadline here is reported as the failure it is
// instead of becoming a phantom undelivered signal.
const TELEGRAM_TIMEOUT_MS = 10000;

//: The deadline for a send nobody is waiting on, in milliseconds.
//
// A signal is not allowed to be decided by this deadline the way it was: the
// 10 second synchronous budget above is shorter than Telegram's own measured
// answer time (42.2 seconds on 2026-10-16), so /notify recorded every signal
// as a delivery failure while Telegram would have delivered it late. Measured
// again on 2026-10-16 11:47 PKT from the relay: /notify and /updates both
// answered "telegram did not answer within 10s (TimeoutError)". A send whose
// answer nobody is waiting for may wait, so it gets Telegram's real latency
// plus room, and its outcome is written to KV for /status to report.
const TELEGRAM_SEND_TIMEOUT_MS = 45000;

async function tgCall(env, method, params, timeoutMs) {
  let r;
  try {
    r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params),
      signal: AbortSignal.timeout(timeoutMs || TELEGRAM_TIMEOUT_MS),
    });
  } catch (e) {
    // Reported, never swallowed: the caller turns this into a 502 with the
    // reason in it, so a delivery failure is visible and not guessed at.
    //
    // The budget quoted is the one this call actually used. It used to print
    // TELEGRAM_TIMEOUT_MS (10s) even when the caller had passed the 45 second
    // send budget, so a timed out signal reported a deadline sixteen times
    // shorter than the one that expired. A diagnostic that misstates its own
    // deadline sends the reader looking for the wrong fault.
    const why = e && e.name ? e.name : "error";
    const budget = timeoutMs || TELEGRAM_TIMEOUT_MS;
    return { ok: false,
             description: `telegram did not answer within ${budget / 1000}s (${why})` };
  }
  return r.json().catch(() => ({}));
}

function json(obj, status = 200, extraHeaders = {}) {
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
      // The send runs in the background, and the answer separates two facts:
      // this relay ACCEPTED the message (ok: true), and Telegram's own answer
      // is recorded in DELIVERY:LAST for /status to report. Waiting for
      // Telegram inside the request is what broke delivery: a sender with a
      // 30 second budget cannot hold a call Telegram answers in 42, and a
      // scan cycle must not be held hostage to it either.
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
        if (seen) return json({ ok: true, deduped: true, delivery: "deduped" });
        ctx.waitUntil(sendAndRecord(env, paired, text, "ops", alertKey));
        return json({ ok: true, accepted: true, delivery: "pending" });
      }
      ctx.waitUntil(sendAndRecord(env, paired, text, "signals", null));
      return json({ ok: true, accepted: true, delivery: "pending" });
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
        signals: (await env.RELAY_KV.get("SIGNALS")) || "",
        market: snapshot });
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
      return json({ ok: true, karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        ...snapshot,
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
      await env.RELAY_KV.put("MARKET", JSON.stringify(body), { expirationTtl: 3600 });
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
          !/^\d{2}:\d{2}(:\d{2})?$/.test(String(body.slot || ""))) {
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
      // Companion app poll. Owner order 2026-10-19 retired the token field
      // from the phone, so this read is public: it returns what the owner's
      // own runner already sent his phone, and the write route below stays
      // admin gated. Nothing here can change state.
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
    if (!bandsFor(k).length) return;

    // Cron is an edge wake-up, not a substitute for a feed observation.
    // Reuse the latest broker snapshot when fresh; break/close transitions are
    // still derived from the shared Karachi session law if the feed has ended.
    let snapshot = null;
    try {
      const raw = await env.RELAY_KV.get("MARKET");
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

  async fetch(request) {
    const url = new URL(request.url);
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
      for (const quote of body.quotes) {
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
      const answer = { ok: true, stored: true, quotes: body.quotes.length,
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
