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
//                       three KMIALL stocks by current session volume, served
//                       from a five minute cache of the PSX Data Portal
//   POST /market        admin only: store a snapshot built by the local runner
//                       (src/data/market_snapshot.py), which takes precedence
//                       over the edge's own cache for five minutes
//   POST /pair/start    admin only: find the chat that just messaged the bot,
//                       store a pairing code in KV and send the code to it
//   POST /pair/confirm  admin only: {code} -> sets the paired chat id
//   POST /notify        admin only: {text, kind} forwarded to the paired chat
//   GET  /updates       admin only: raw getUpdates proxy for local debugging
//
// Cron triggers (UTC, set by cloud/pair.py):
//   04:32 Mon-Thu = 09:32 PKT open | 10:30 Mon-Thu = 15:30 PKT close
//   04:17 Fri     = 09:17 PKT open | 11:30 Fri     = 16:30 PKT close

const KARACHI_OFFSET_MIN = 5 * 60; // SO-8: UTC+5, fixed forever

// Owner order 2026-10-08: name the market event first, then the quant
// state (SO-9).
const MSG_OPEN = "Market is open. Quant is online now.";
const MSG_CLOSED = "Market is closed. Quant is sleeping now.";

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

function openHM(k) {
  return k.getUTCDay() === 5 ? [9, 17] : [9, 32];
}

function closeHM(k) {
  return k.getUTCDay() === 5 ? [16, 30] : [15, 30];
}

// Owner's session law (SO-8): is a session live at this instant?
function marketOpenNow(nowUtc) {
  const k = karachiView(nowUtc.getTime());
  if (!isTradingDay(k)) return false;
  const o = openHM(k);
  const c = closeHM(k);
  const mins = k.getUTCHours() * 60 + k.getUTCMinutes();
  return mins >= o[0] * 60 + o[1] && mins < c[0] * 60 + c[1];
}

// ---------------------------------------------------------------- market data
// Owner order 2026-10-09: the app shows the KSE100 index with its points and
// percentage, and the top three KMIALL stocks by volume, refreshed every five
// minutes. Both come from the PSX Data Portal's own server rendered pages,
// which are public and live during the session. Nothing is estimated here: an
// unreachable portal yields a stated gap, never a made up number.
const PORTAL_HOME = "https://dps.psx.com.pk/";
const PORTAL_INDEX = "https://dps.psx.com.pk/indices/"; // + membership name
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

function topByVolume(rows, limit) {
  return rows
    .filter((r) => r.volume && r.volume > 0)
    .sort((a, b) => (b.volume - a.volume) || a.symbol.localeCompare(b.symbol))
    .slice(0, limit)
    .map((r) => ({
      symbol: r.symbol,
      volume: Math.round(r.volume),
      price: r.current,
      basis: "current session volume (PSX " + MARKET_MEMBERSHIP + " constituents)",
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
    index: null,
    kmiall_members: 0,
    top_volume: null,
    top_volume_basis: null,
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
      snapshot.notes.push(`${MARKET_MEMBERSHIP} constituent table was empty`);
    } else {
      snapshot.top_volume = topByVolume(rows, MARKET_TOP_N);
      snapshot.top_volume_basis = snapshot.top_volume.length
        ? `current session volume, top ${snapshot.top_volume.length} of ${rows.length} ${MARKET_MEMBERSHIP} members`
        : "no member of the index has traded yet this session";
    }
  } catch (e) {
    snapshot.notes.push("constituents fetch failed: " + describe(e));
    snapshot.top_volume_basis =
      `${MARKET_MEMBERSHIP} constituent table unreachable, so the session volume ranking is unavailable`;
  }
  return snapshot;
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
        cached.cache_age_seconds = Math.round((now.getTime() - built) / 1000);
        return cached;
      }
    } catch (_) {
      // malformed cache: fall through and rebuild
    }
  }
  const fresh = await buildMarketSnapshot(now);
  fresh.built_at = now.toISOString();
  fresh.cache_age_seconds = 0;
  await env.RELAY_KV.put("MARKET", JSON.stringify(fresh), { expirationTtl: 3600 });
  return fresh;
}

function pktInstant(k, hm) {
  return new Date(`${dayStamp(k)}T${pad(hm[0])}:${pad(hm[1])}:00+05:00`);
}

function nextEvent(nowUtc) {
  for (let offset = 0; offset < 10; offset++) {
    const probe = karachiView(nowUtc.getTime() + offset * 86400000);
    if (!isTradingDay(probe)) continue;
    const o = pktInstant(probe, openHM(probe));
    const c = pktInstant(probe, closeHM(probe));
    if (o.getTime() > nowUtc.getTime()) return { event: "OPEN", at: o };
    if (c.getTime() > nowUtc.getTime()) return { event: "CLOSE", at: c };
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
        market_open: marketOpenNow(now),
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
            market_open: marketOpenNow(now) }, 503);
        }
        snapshot = JSON.parse(fallback);
        snapshot.stale = true;
        snapshot.market_open = marketOpenNow(now);
      }
      const k = karachiView(now.getTime());
      return json({ ok: true, karachi_now: `${dayStamp(k)} ${hhmm(k)} PKT`,
        market_open: marketOpenNow(now), ...snapshot });
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

  // Cron handler: fires the owner's two texts at the PKT schedule edges.
  async scheduled(controller, env, ctx) {
    const now = new Date();
    const k = karachiView(now.getTime());
    if (!isTradingDay(k)) return;
    const paired = (await env.RELAY_KV.get("PAIRED_CHAT_ID")) || env.PAIRED_CHAT_ID;
    if (!paired) return;

    const hm = [k.getUTCHours(), k.getUTCMinutes()];
    const near = (h, m) => Math.abs(hm[0] * 60 + hm[1] - (h * 60 + m)) <= 2;

    let text = null;
    if (near(...openHM(k))) text = MSG_OPEN;
    else if (near(...closeHM(k))) text = MSG_CLOSED;
    if (!text) return;

    ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: paired, text }));
  },
};
