// Smoke test for the seatbelt's phone feed (cloud/cloudflare/seatbelt-worker.js).
//
// What it proves, without any network or Cloudflare account:
//   1. GET /feed returns 200 JSON with both bots' heartbeats, the
//      intraday book summary, the KV "last exits" snapshot and the
//      evening pick card (the Friday/Monday pick-date walk included).
//   2. The optional FEED_KEY lock denies requests without ?key=...
//      and allows requests with it.
//   3. The root path still serves the human health banner, and the
//      scheduled handler still runs with the feed additions (its
//      KV snapshot writes only inside market hours, so both the
//      wrote-it and skipped-it outcomes are accepted here).
//
// Run:  node scripts/test_feed.mjs cloud/cloudflare/seatbelt-worker.js
// (the android-apk workflow runs exactly this after every build)

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const workerPath = process.argv[2];
if (!workerPath) {
  console.error(
    "usage: node scripts/test_feed.mjs <path-to-seatbelt-worker.js>"
  );
  process.exit(1);
}

let failures = 0;
function expect(cond, label) {
  if (cond) {
    console.log(`  ok: ${label}`);
  } else {
    failures += 1;
    console.error(`  FAIL: ${label}`);
  }
}

// Minimal in-memory stand-in for the Workers KV API surface.
function makeKV() {
  const store = new Map();
  return {
    async get(key) {
      return store.has(key) ? store.get(key) : null;
    },
    async put(key, value) {
      store.set(key, String(value));
    },
    _store: store,
  };
}

// A fetch stand-in that answers GitHub contents URLs from fixtures,
// records every call, and returns 404 for anything else - which is
// exactly how a dispatch endpoint failing should look to the guards.
function makeFetchSink(fixtures) {
  const calls = [];
  const fn = async (input) => {
    const url = String(
      input instanceof URL ? input : typeof input === "object" && input.url ? input.url : input
    );
    calls.push(url);
    const hit = fixtures.find(([prefix]) => url.includes(prefix));
    if (!hit) {
      return { ok: false, status: 404, json: async () => ({}) };
    }
    const payload = hit[1];
    return {
      ok: true,
      status: 200,
      json: async () => payload,
    };
  };
  fn.calls = calls;
  return fn;
}

const b64 = (obj) => Buffer.from(JSON.stringify(obj)).toString("base64");

const threeMinAgo = new Date(Date.now() - 3 * 60000).toISOString();

// Newest first, mirroring the live book's ordering.
const book = [
  { symbol: "MARI", status: "OPEN" },
  {
    symbol: "ECOP",
    status: "CLOSED",
    exit_date: "2026-09-07",
    exit_reason: "Rule 3: profit target reached",
    pnl: 1.13,
    pnl_net_pct: 1.5066,
  },
  {
    symbol: "PIOC",
    status: "CLOSED",
    exit_date: "2026-09-07",
    exit_reason: "Rule 7: stop-loss triggered",
    pnl: -5.22,
    pnl_net_pct: -2.4553,
  },
  {
    symbol: "BUXL",
    status: "CLOSED",
    exit_date: "2026-09-09",
    exit_reason: "Rule 7: stop-loss triggered",
    pnl: -30.01,
    pnl_net_pct: -3.1025,
  },
];

const pick = {
  pick_date: "2026-09-29",
  picked_at_pkt: "2026-09-29T15:21:50.330510+05:00",
  picks: [
    {
      symbol: "MARI",
      score: 0.9102,
      raw_score: 0.8812,
      entry_price: 659.92,
      close_position: 0.97,
      volume_surge: 4.8,
      change_pct: 2.6,
      late_momentum_pct: 1.9,
      book_pressure: 0.41,
      aggression: 0.55,
    },
  ],
  red_tape_bar: 1.5,
  degraded: false,
};

const kv = makeKV();
const tmp = mkdtempSync(join(tmpdir(), "sentinel-feed-"));
const fetchSink = makeFetchSink([
  [
    "data/heartbeat.json",
    { content: b64({ utc: threeMinAgo, source: "cloud_bot" }) },
  ],
  ["data/portfolio.json", { content: b64(book) }],
  [
    "tracker.json",
    { content: b64({ open: [{ symbol: "MARI" }], pick_date: "2026-09-30" }) },
  ],
  ["data/picks/", { content: b64(pick) }],
  [
    "phone_feed_state.json",
    {
      content: b64({
        last_closed: [
          {
            symbol: "ECOP",
            exit_date: "2026-09-07",
            exit_price: 50.14,
            exit_reason: "Rule 3: profit target reached",
            pnl: 1.13,
            pnl_net_pct: 1.5066,
            // v4.4.3: the mock's pickFeedDate returns 2026-09-30, so
            // 2026-09-07 is stale (older than one session ago).
            stale: true,
          },
        ],
      }),
    },
  ],
]);
globalThis.fetch = fetchSink;

try {
  const workerUrl = pathToFileURL(workerPath).href;
  const mod = await import(`${workerUrl}?t=${Date.now()}`);
  const env = { GITHUB_TOKEN: "test", SEATBELT: kv };

  console.log("GET /feed:");
  const res = await mod.default.fetch(
    new Request("https://seatbelt.example/feed"),
    env
  );
  expect(res.status === 200, "returns 200");
  const feed = await res.json();
  expect(feed.ok === true, "ok flag true");
  expect(typeof feed.pkt_date === "string" && feed.pkt_date.length === 10, "pkt_date present");
  expect(feed.intraday.heartbeat_age_min === 3, "intraday heartbeat age (3 min)");
  expect(feed.intraday.book.closed_total === 3, "book summary closed_total");
  expect(feed.intraday.book.win_rate === 33, "book summary win_rate (33%)");
  expect(feed.intraday.book.avg_win_net === 1.51, "avg win net (1.51%)");
  expect(feed.intraday.book.avg_loss_net === -2.78, "avg loss net (-2.78%)");
  expect(
    Array.isArray(feed.intraday.book.open) &&
      feed.intraday.book.open[0].symbol === "MARI",
    "open position surfaced"
  );
  expect(
    feed.intraday.last_closed[0] && feed.intraday.last_closed[0].symbol === "ECOP",
    "KV last-exits snapshot passes through"
  );
  expect(feed.evening.heartbeat_age_min === 3, "evening heartbeat age");
  expect(feed.evening.open_count === 1, "evening open position count");
  expect(feed.evening.pick && feed.evening.pick.name === "MARI", "pick name surfaced");
  expect(feed.evening.pick.entry_price === 659.92, "pick entry price surfaced");
  expect(feed.evening.pick.degraded === false, "pick degraded flag");

  console.log("Root path:");
  const root = await mod.default.fetch(
    new Request("https://seatbelt.example/"),
    env
  );
  expect(root.status === 200, "root still serves 200");
  expect(
    String(await root.text()).includes("sentinel seatbelt"),
    "root still shows the health banner"
  );

  console.log("GET /alive:");
  const alive = await mod.default.fetch(
    new Request("https://seatbelt.example/alive"),
    env
  );
  expect(alive.status === 200, "/alive serves 200");
  expect(
    String(await alive.text()).includes("alive - Karachi"),
    "/alive keeps the original banner"
  );

  console.log("FEED_KEY lock:");
  const envKeyed = { GITHUB_TOKEN: "test", FEED_KEY: "s3cret", SEATBELT: makeKV() };
  const denied = await mod.default.fetch(
    new Request("https://seatbelt.example/feed"),
    envKeyed
  );
  expect(denied.status === 403, "denied without the key");
  const allowed = await mod.default.fetch(
    new Request("https://seatbelt.example/feed?key=s3cret"),
    envKeyed
  );
  expect(allowed.status === 200, "allowed with the key");

  console.log("Scheduled handler with feed additions:");
  await mod.default.scheduled({ noRetry: () => {} }, env, { waitUntil() {} });
  const savedRaw = kv._store.get("phone_feed_state.json");
  if (savedRaw === undefined) {
    console.log("  ok: snapshot skipped (outside market hours or no new exit) - accepted");
  } else {
    const saved = JSON.parse(savedRaw);
    expect(saved.last_closed.length >= 1, "snapshot holds history");
  }

  if (failures > 0) {
    console.error(`phone feed smoke test: ${failures} check(s) FAILED`);
    process.exit(1);
  }
  console.log("phone feed smoke test: all checks passed");
} finally {
  rmSync(tmp, { recursive: true, force: true });
}
