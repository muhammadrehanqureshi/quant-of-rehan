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
//   GET  /health   liveness, current Karachi clock, next scheduled event
//   POST /pair     admin only: discover the chatting owner, return chat id
//   POST /notify   admin only: {text, kind} forwarded to the paired chat
//   GET  /updates  admin only: raw getUpdates proxy for local debugging
//
// Cron triggers (UTC, set by cloud/pair.py):
//   04:32 Mon-Thu = 09:32 PKT open | 10:30 Mon-Thu = 15:30 PKT close
//   04:17 Fri     = 09:17 PKT open | 11:30 Fri     = 16:30 PKT close

const KARACHI_OFFSET_MIN = 5 * 60; // SO-8: UTC+5, fixed forever

const MSG_OPEN = "Market is open and the system is online.";
const MSG_CLOSED = "Market is closed and the system is sleeping now.";

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
        paired: Boolean(env.PAIRED_CHAT_ID),
        next_event: next.event
          ? { event: next.event, at_pk: `${dayStamp(karachiView(next.at.getTime()))} ${hhmm(karachiView(next.at.getTime()))}` }
          : null,
      });
    }

    if (request.method === "POST" && path === "/pair") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const updates = await tgCall(env, "getUpdates", { limit: 50 });
      if (!updates.ok) {
        return json({ ok: false, error: updates.description || "getUpdates refused" }, 502);
      }
      let best = null;
      for (const u of updates.result || []) {
        const m = u.message || u.channel_post || {};
        if (!m.chat || m.chat.id === undefined) continue;
        if (!best || (m.date || 0) > (best.date || 0)) best = m;
      }
      if (!best) {
        return json({ ok: false, error: "no chat has messaged this bot recently; send it a message from the owner phone, then rerun pairing" }, 404);
      }
      return json({
        ok: true,
        chat_id: String(best.chat.id),
        chat_kind: best.chat.type,
        chat_name: best.chat.title || best.chat.username || best.chat.first_name || "",
      });
    }

    if (request.method === "POST" && path === "/notify") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      if (!env.PAIRED_CHAT_ID) {
        return json({ ok: false, error: "not paired; run cloud/pair.py first" }, 409);
      }
      const body = await request.json().catch(() => ({}));
      const text = String(body.text || "");
      if (!text) {
        return json({ ok: false, error: "empty text" }, 400);
      }
      const sent = await tgCall(env, "sendMessage", { chat_id: env.PAIRED_CHAT_ID, text });
      if (sent.ok) return json({ ok: true });
      return json({ ok: false, error: sent.description || "telegram refused" }, 502);
    }

    if (request.method === "GET" && path === "/updates") {
      if (!adminOk(request, env)) {
        return json({ ok: false, error: "admin token required" }, 403);
      }
      const updates = await tgCall(env, "getUpdates", { limit: 20 });
      return json(updates);
    }

    return json({ ok: false, error: "not found" }, 404);
  },

  // Cron handler: fires the owner's two texts at the PKT schedule edges.
  async scheduled(controller, env, ctx) {
    const now = new Date();
    const k = karachiView(now.getTime());
    if (!isTradingDay(k)) return;
    if (!env.PAIRED_CHAT_ID) return;

    const hm = [k.getUTCHours(), k.getUTCMinutes()];
    const near = (h, m) => Math.abs(hm[0] * 60 + hm[1] - (h * 60 + m)) <= 2;

    let text = null;
    if (near(...openHM(k))) text = MSG_OPEN;
    else if (near(...closeHM(k))) text = MSG_CLOSED;
    if (!text) return;

    ctx.waitUntil(tgCall(env, "sendMessage", { chat_id: env.PAIRED_CHAT_ID, text }));
  },
};
