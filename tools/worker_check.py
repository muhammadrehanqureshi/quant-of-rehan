"""Verify cloud/worker.js in a real JavaScript engine without Node.

There is no Node or wrangler on the owner's PC, so the worker cannot be run
locally with `wrangler dev`. This harness builds a small HTML page that

  1. parses the ENTIRE worker source with `new Function`, which is a real
     engine syntax check of the deployed file, and
  2. executes the worker's own market parsing functions (extracted verbatim
     from the file, not reimplemented) against live PSX Data Portal markup,
     then compares the result with what src/data/market_snapshot.py parsed
     from the same pages.

Usage:
    python tools/worker_check.py            # build tmp/worker_check.html
    # then open it in the preview panel, or read tmp/worker_check_result.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import market_snapshot as ms  # noqa: E402
from src.data import volume_split  # noqa: E402

OUT_HTML = ROOT / "tmp" / "worker_check.html"
OUT_JSON = ROOT / "tmp" / "worker_check_result.json"
PORTAL_HOME = "https://dps.psx.com.pk/"
PORTAL_INDEX = "https://dps.psx.com.pk/indices/KMIALLSHR"
PORTAL_COMPANY = "https://dps.psx.com.pk/company/"


def worker_source() -> str:
    return (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")


def extracted_functions(src: str) -> str:
    """The pure parsing half of the worker, copied verbatim from the file."""
    # Slice from the holiday list through the parsing helpers: marketOpenNow
    # depends on the clock helpers, which depend on the holiday set.
    start = src.index("const KARACHI_OFFSET_MIN")
    end = src.index("async function portalText")
    return src[start:end]


def trim(row_html: str) -> str:
    return re.sub(r"\s+", " ", row_html).strip()


def company_panels(symbols: list[str]) -> dict:
    """The REG panel of each leader's company page, plus python's parse of it.

    The panel is what the worker reads for the buy/sell split, so the harness
    stubs exactly that slice of live markup and compares the two parsers on
    it. Only the REG panel is carried: the rest of the page would be dead
    weight in the harness and would make the stub look unlike the site.
    """
    pages: dict[str, str] = {}
    parsed: dict[str, dict] = {}
    for symbol in symbols:
        html = ms._get(PORTAL_COMPANY + symbol)
        panel = ms.reg_panel(html)
        if not panel:
            continue
        pages[symbol] = ('<div class="tabs__panel" data-name="REG">'
                         + panel + "</div>")
        quote = ms.parse_symbol_quote(html, symbol)
        if quote:
            parsed[symbol] = quote
    return {"pages": pages, "parsed": parsed}


def fixtures() -> dict:
    home = ms._get(PORTAL_HOME)  # noqa: SLF001 - same fetch the module uses
    panel = re.search(
        r'<div class="tabs__panel marketIndices__details" data-name="KSE100".*?</h1>',
        home, re.S)
    constituents = ms._get(PORTAL_INDEX)
    rows = re.findall(r"<tr[^>]*>.*?</tr>", constituents, re.S)
    # header row plus the three highest-volume rows, so ordering is exercised
    parsed = ms.parse_constituents(constituents)
    leaders = ms.volume_leaders(parsed)
    top = [r["symbol"] for r in leaders]
    wanted = set(top) | {"AASM"}
    kept = [trim(r) for r in rows
            if any(f'data-order="{s}"' in r for s in wanted)]
    panel_html = company_panels(top)
    # What python's own splitter answers for these rows from these panels, so
    # the engine check is a parity test and not a second implementation. The
    # rows are filled here exactly as src/data/market_snapshot.py fills them,
    # so the label the card would print is derived from real rows too.
    expected_rows = [dict(row) for row in leaders]
    expected_label = volume_split.attach_splits(
        expected_rows, quotes=panel_html["parsed"], flows={})
    expected_splits = {
        row["symbol"]: {"buy": row["buy_volume"],
                        "sell": row["sell_volume"],
                        "method": row["split_method"]}
        for row in expected_rows
    }
    return {
        "home": panel.group(0),
        "constituents": "<table><thead><tr><th>SYMBOL</th></tr></thead><tbody>"
                        + "".join(kept) + "</tbody></table>",
        "top_symbols": top,
        "python_index": ms.parse_index(home),
        "python_leaders": leaders,
        "company_pages": panel_html["pages"],
        "python_quotes": panel_html["parsed"],
        "python_splits": expected_splits,
        "split_label": expected_label,
    }


def build() -> dict:
    src = worker_source()
    fns = extracted_functions(src)
    fx = fixtures()
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>worker check</title>
<pre id="out">running…</pre>
<script>
const WORKER_SRC = {json.dumps(src)};
const FUNCS_SRC = {json.dumps(fns)};
const HOME = {json.dumps(fx["home"])};
const CONST = {json.dumps(fx["constituents"])};
const COMPANY = {json.dumps({"prefix": PORTAL_COMPANY,
                            "pages": fx["company_pages"]})};
const SPLITS = {json.dumps({"expected": fx["python_splits"],
                            "quotes": fx["python_quotes"],
                            "label": fx["split_label"]})};
const EXPECT = {json.dumps({"top_symbols": fx["top_symbols"],
                            "python_index": fx["python_index"],
                            "python_leaders": fx["python_leaders"]})};
// exactly what android/.../Watcher.fetchMarket reads
const EXCEPT_KEYS = ["ok", "market_open", "cache_age_seconds", "kmiall_members",
                     "top_volume_basis", "index", "top_volume", "notes", "market_feed"];
const lines = [];
function say(ok, what, extra) {{
  lines.push((ok ? "PASS " : "FAIL ") + what + (extra ? " :: " + extra : ""));
}}
const result = {{}};

// 1. Whole-file syntax check in a real engine (export default -> return).
try {{
  const body = WORKER_SRC.replace("export default {{", "return {{");
  const handler = new Function(body);
  const obj = handler();
  say(typeof obj.fetch === "function" && typeof obj.scheduled === "function",
      "worker parses and exposes fetch/scheduled", Object.keys(obj).join(","));
  result.exports = Object.keys(obj);
}} catch (e) {{
  say(false, "worker parses", e.name + ": " + e.message);
}}

// 2. The worker's own parsing functions, verbatim, on live markup.
try {{
  eval(FUNCS_SRC);
  const idx = parseIndexPanel(HOME, "KSE100");
  const ex = EXPECT.python_index;
  say(idx !== null && Math.abs(idx.value - ex.value) < 0.01 &&
      Math.abs(idx.change - ex.change) < 0.01 &&
      Math.abs(idx.change_pct - ex.change_pct) < 0.01 &&
      idx.as_of === ex.as_of,
      "index panel matches the python parser", JSON.stringify(idx));
  const rows = parseConstituents(CONST);
  const leaders = topByVolume(rows, 3);
  const py = EXPECT.python_leaders;
  const same = leaders.length === py.length && leaders.every((l, i) =>
      l.symbol === py[i].symbol && l.volume === py[i].volume);
  say(same, "volume leaders match the python parser",
      JSON.stringify(leaders.map((l) => l.symbol + ":" + l.volume)) +
      " vs " + JSON.stringify(py.map((l) => l.symbol + ":" + l.volume)));
  say(!leaders.some((l) => l.volume <= 0), "zero-volume members are excluded");
  result.javascript_index = idx;
  result.javascript_leaders = leaders;
  result.python_index = ex;
  result.python_leaders = py;
}} catch (e) {{
  say(false, "parsing functions", e.name + ": " + e.message);
}}

// 3. The app's badge rule: ONLINE only inside a live session.
try {{
  const at = (y, mo, d, h, mi) => new Date(Date.UTC(y, mo - 1, d, h - 5, mi));
  say(marketOpenNow(at(2026, 10, 9, 11, 34)) === true,
      "friday mid-session is open");
  say(marketOpenNow(at(2026, 10, 9, 16, 30)) === false,
      "friday after close is closed");
  say(marketOpenNow(at(2026, 10, 9, 9, 16)) === false, "before the open is closed");
  say(marketOpenNow(at(2026, 10, 10, 11, 34)) === false, "saturday is closed");
  say(marketOpenNow(at(2026, 10, 8, 15, 30)) === false, "weekday after 15:30 is closed");
  say(marketOpenNow(at(2026, 10, 8, 15, 29)) === true, "weekday before 15:30 is open");
}} catch (e) {{
  say(false, "market open rule", e.name + ": " + e.message);
}}

// 4. The /market endpoint contract the app reads, end to end in this engine:
//    the portal is stubbed, the KV is stubbed, and the worker's own fetch
//    handler is called exactly as Cloudflare would call it.
async function endpoints() {{
  const PORTAL = "https://dps.psx.com.pk/";
  const INDEX_PAGE = "https://dps.psx.com.pk/indices/KMIALLSHR";
  let portalCalls = 0;
  let stubErrors = [];
  const stub = async (url) => {{
    const u = String(url);
    let body = u === PORTAL ? HOME : (u === INDEX_PAGE ? CONST : null);
    if (body === null && u.startsWith(COMPANY.prefix)) {{
      const symbol = u.slice(COMPANY.prefix.length);
      body = COMPANY.pages[symbol] || null;
    }}
    if (body === null) return new Response("not stubbed", {{ status: 404 }});
    portalCalls++;
    return new Response(body, {{ status: 200,
      headers: {{ "content-type": "text/html" }} }});
  }};
  window.fetch = stub;
  globalThis.fetch = stub;
  const store = new Map();
  const env = {{
    RELAY_KV: {{
      get: async (k) => (store.has(k) ? store.get(k) : null),
      put: async (k, v) => {{ store.set(k, v); }},
      delete: async (k) => {{ store.delete(k); }},
      list: async () => ({{ keys: [] }}),
    }},
    RELAY_ADMIN_TOKEN: "test-token",
    TELEGRAM_BOT_TOKEN: "",
  }};
  const handler = new Function(WORKER_SRC.replace("export default {{", "return {{"))();

  const res = await handler.fetch(new Request("https://relay.test/market"), env);
  const body = await res.json();
  say(res.status === 200 && body.ok === true, "GET /market answers 200 ok",
      "status " + res.status);
  say(true, "debug: portal stub hits + notes",
      portalCalls + " | " + JSON.stringify(body.notes) + " | " +
      JSON.stringify(stubErrors));
  say(body.index && typeof body.index.value === "number" &&
      typeof body.index.change === "number" &&
      typeof body.index.change_pct === "number" &&
      typeof body.index.as_of === "string",
      "index carries value/change/change_pct/as_of", JSON.stringify(body.index));
  say(Array.isArray(body.top_volume) && body.top_volume.length === 3 &&
      body.top_volume.every((t) => typeof t.symbol === "string" &&
        typeof t.volume === "number" && "price" in t),
      "top_volume is three symbol/volume/price rows",
      JSON.stringify(body.top_volume));
  say(EXCEPT_KEYS.every((k) => k in body),
      "every field the app reads is present",
      EXCEPT_KEYS.filter((k) => !(k in body)).join(",") || "all");

  // The buy/sell split, end to end: the worker fetched each leader's own
  // company page through this stubbed portal and split it with its own code.
  // Every number must equal what src/data/volume_split.py answers for the
  // same markup, and the sum invariant must hold on the edge as well.
  const rows = Array.isArray(body.top_volume) ? body.top_volume : [];
  const expected = SPLITS.expected;
  for (const row of rows) {{
    const want = expected[row.symbol] || {{}};
    const got = {{ buy: row.buy_volume, sell: row.sell_volume,
                   method: row.split_method }};
    say(want.buy === got.buy && want.sell === got.sell,
        "".concat(row.symbol, " split matches the python splitter"),
        JSON.stringify(got) + " vs " + JSON.stringify(want));
    if (Number.isFinite(got.buy) && Number.isFinite(got.sell)) {{
      say(got.buy + got.sell === row.volume,
          "".concat(row.symbol, " buy + sell equals the published volume"),
          "".concat(got.buy, " + ", got.sell, " vs ", row.volume));
      say(got.buy >= 0 && got.sell >= 0, "".concat(row.symbol, " sides are not negative"));
    }}
  }}
  say(body.volume_split_basis === SPLITS.label,
      "the split label names the method that produced the numbers",
      JSON.stringify(body.volume_split_basis) + " vs " + JSON.stringify(SPLITS.label));
  say(!/broker|KMIALLSHR members/i.test(String(body.volume_split_basis || "") +
      String(body.top_volume_basis || "")),
      "the card carries no legacy membership or broker capture wording",
      JSON.stringify({{ split: body.volume_split_basis,
                        top: body.top_volume_basis }}));
  say(body.market_state && typeof body.market_state.condition === "string" &&
      typeof body.market_state.condition_text === "string",
      "market_state carries the condition and its sentence",
      JSON.stringify(body.market_state && body.market_state.condition));
  // The served state must carry the sentence for the same instant the
  // condition helpers answer for, which is how the app reads it.
  say(body.market_state.condition === marketCondition(new Date()) &&
      body.market_state.condition_text === conditionText(new Date()),
      "the served market_state condition equals the condition helpers at this instant",
      JSON.stringify(body.market_state.condition_text));

  // The Friday midday break, the one condition that is neither closed nor
  // operational (SO-8). Both band edges and the middle are checked.
  const friday = (h, mi) => new Date(Date.UTC(2026, 9, 9, h - 5, mi));
  say(marketCondition(friday(11, 59)) === "OPERATIONAL",
      "friday 11:59 is operational");
  say(marketCondition(friday(12, 0)) === "BREAK" &&
      conditionText(friday(12, 0)) === "Market is on a break right now.",
      "friday 12:00 opens the break with the owner's sentence",
      conditionText(friday(12, 0)));
  say(marketCondition(friday(14, 31)) === "BREAK",
      "friday 14:31 is still the break");
  say(marketCondition(friday(14, 32)) === "OPERATIONAL" &&
      conditionText(friday(14, 32)) === "",
      "friday 14:32 resumes trading with no sentence",
      conditionText(friday(14, 32)));
  say(marketCondition(friday(16, 30)) === "CLOSED",
      "friday 16:30 is closed, not a break");
  const firstCalls = portalCalls;

  const res2 = await handler.fetch(new Request("https://relay.test/market"), env);
  const body2 = await res2.json();
  say(portalCalls === firstCalls && body2.cache_age_seconds >= 0,
      "second call is served from the cache (no portal hit)",
      "portal calls " + portalCalls + ", age " + body2.cache_age_seconds);

  const health = await (await handler.fetch(
      new Request("https://relay.test/health"), env)).json();
  say(health.ok === true && typeof health.market_open === "boolean" &&
      typeof health.karachi_now === "string",
      "GET /health reports market_open", JSON.stringify(health.market_open));

  // A closed market must not be reported as an open one.
  say(health.market_open === marketOpenNow(new Date()),
      "health market_open matches the session law at this instant");

  const pushed = await handler.fetch(new Request("https://relay.test/market", {{
    method: "POST",
    headers: {{ "content-type": "application/json", "x-admin-token": "test-token" }},
    body: JSON.stringify({{ index: {{ symbol: "KSE100", value: 1, change: 0, change_pct: 0 }},
      top_volume: [] }}),
  }}), env);
  say(pushed.status === 200, "POST /market accepts an admin snapshot",
      "status " + pushed.status);
  const refused = await handler.fetch(new Request("https://relay.test/market", {{
    method: "POST", headers: {{ "content-type": "application/json" }}, body: "{{}}",
  }}), env);
  say(refused.status === 403, "POST /market refuses a stranger",
      "status " + refused.status);
  // A partial push must be refused, and the app's field set must survive a
  // push that carries only part of the snapshot (2026-10-10 audit).
  const partial = await handler.fetch(new Request("https://relay.test/market", {{
    method: "POST",
    headers: {{ "content-type": "application/json", "x-admin-token": "test-token" }},
    body: JSON.stringify({{ top_volume: [] }}),
  }}), env);
  say(partial.status === 400, "POST /market refuses a partial snapshot",
      "status " + partial.status);
  const readBack = await (await handler.fetch(
      new Request("https://relay.test/market"), env)).json();
  say(EXCEPT_KEYS.every((k) => k in readBack),
      "a pushed snapshot still carries every field the app reads",
      EXCEPT_KEYS.filter((k) => !(k in readBack)).join(",") || "all");
  say(readBack.index === null || typeof readBack.index === "object",
      "a snapshot without an index reads back as an explicit null",
      JSON.stringify(readBack.index));

  // Portal outage with an empty cache: the field set must still hold.
  const deadPortal = async () => new Response("boom", {{ status: 500 }});
  window.fetch = deadPortal;
  globalThis.fetch = deadPortal;
  const emptyEnv = {{ ...env, RELAY_KV: {{
    get: async () => null, put: async () => {{}}, delete: async () => {{}},
    list: async () => ({{ keys: [] }}),
  }} }};
  const outage = await (await handler.fetch(
      new Request("https://relay.test/market"), emptyEnv)).json();
  say(EXCEPT_KEYS.every((k) => k in outage) && outage.index === null &&
      Array.isArray(outage.notes) && outage.notes.length > 0,
      "a dead portal still answers the full field set, with notes",
      EXCEPT_KEYS.filter((k) => !(k in outage)).join(",") || "all keys");
  window.fetch = stub;
  globalThis.fetch = stub;

  const missing = await handler.fetch(new Request("https://relay.test/nope"), env);
  say(missing.status === 404, "unknown paths still 404", "status " + missing.status);
  result.endpoint_portal_calls = portalCalls;
}}

(async () => {{
  try {{
    await endpoints();
  }} catch (e) {{
    say(false, "endpoint contract", e.name + ": " + e.message);
  }}
  const failed = lines.filter((l) => l.startsWith("FAIL")).length;
  lines.push(failed ? "RESULT FAIL " + failed : "RESULT PASS");
  result.failed = failed;
  result.lines = lines;
  document.getElementById("out").textContent = lines.join("\\n");
  window.__workerCheck = result;
}})();
</script>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    (OUT_JSON).write_text(json.dumps(fx, indent=2), encoding="utf-8")
    return {"html": str(OUT_HTML), "fixtures": str(OUT_JSON),
            "top_symbols": fx["top_symbols"], "index": fx["python_index"]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
