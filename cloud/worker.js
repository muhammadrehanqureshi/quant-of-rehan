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
//   GET  /health        liveness, current Karachi clock, next scheduled event
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

// Owner order 2026-10-07: say "quant is online/sleeping now" (SO-9).
const MSG_OPEN = "Quant is online now.";
const MSG_CLOSED = "Quant is sleeping now.";

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
      if (!text) {
        return json({ ok: false, error: "empty text" }, 400);
      }
      const sent = await tgCall(env, "sendMessage", { chat_id: paired, text });
      if (sent.ok) return json({ ok: true });
      return json({ ok: false, error: sent.description || "telegram refused" }, 502);
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
      await env.RELAY_KV.put(key, JSON.stringify(body), { expirationTtl: 63072000 });
      return json({ ok: true, key });
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
      await env.RELAY_KV.put(`RESEARCH:OUTCOME:${body.date}`, JSON.stringify(body),
        { expirationTtl: 63072000 });
      return json({ ok: true });
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
      return json({ ok: true, sessions, complete: !listed.list_complete });
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
