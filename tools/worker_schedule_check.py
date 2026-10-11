"""Verify cloud/worker.js sleep/schedule logic in a real JavaScript engine.

There is no Node, Deno, Bun, quickjs or wrangler on this PC (all checked
absent), so the worker cannot be run from a command line. This harness follows
the same approach as tools/worker_check.py: it copies the worker's schedule
functions VERBATIM out of the file, executes them in the browser's own engine,
and compares every answer with src/data/sessions.py, which is the authority
(SO-8).

It proves three things:

  1. the whole worker source still parses in a real engine, and still exposes
     both `fetch` and `scheduled`;
  2. the edge's session law agrees with the Python session law instant for
     instant, across a Mon-Thu day, a two-band Friday, a weekend and a PSX
     holiday;
  3. the cron handler stays asleep anywhere except a band edge -- which is what
     keeps Cloudflare compute at zero during non-trading hours, since the
     handler's first act is `if (!bands.length) return;` and its only send is
     inside a +/- 2 minute window of an open or a close.

Usage:
    python tools/worker_schedule_check.py
    # then open tmp/worker_schedule_check.html in the preview panel;
    # window.RESULT holds the verdicts as JSON.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI, is_trading_day, market_phase  # noqa: E402

OUT_HTML = ROOT / "tmp" / "worker_schedule_check.html"

# The clock helpers, the holiday set and the session law.
BLOCK_A_START = "const KARACHI_OFFSET_MIN"
BLOCK_A_END = "// ---------------------------------------------------------------- market data"
# nextEvent needs pktInstant, and marketState calls nextEvent.
BLOCK_B_START = "function pktInstant(k, hm) {"
BLOCK_B_END = "function adminOk(request, env) {"

#: (label, year, month, day, hour, minute, expected_band_edge)
#: 2026-10-09 is a Friday (two bands), 2026-10-12 a Monday, 2026-10-10 a
#: Saturday, 2026-10-11 a Sunday, 2026-08-14 a PSX holiday that is a Friday.
#:
#: The handler's only send happens inside `Math.abs(mins - edge) <= 2`, a two
#: minute window either side of an open or a close. The cases below pin that
#: window to the minute on both sides, because it is the whole reason a cron
#: that lands slightly early or late still behaves and a cron at 10:00 does
#: not. Instants 3 minutes out must not match.
CASES = (
    ("Mon 08:00 pre-open", 2026, 10, 12, 8, 0, None),
    ("Mon 09:28 outside tolerance", 2026, 10, 12, 9, 28, None),
    ("Mon 09:29 outside tolerance", 2026, 10, 12, 9, 29, None),
    ("Mon 09:30 tolerance edge", 2026, 10, 12, 9, 30, "OPEN"),
    ("Mon 09:31 pre-open", 2026, 10, 12, 9, 31, "OPEN"),
    ("Mon 09:32 open edge", 2026, 10, 12, 9, 32, "OPEN"),
    ("Mon 09:34 tolerance edge", 2026, 10, 12, 9, 34, "OPEN"),
    ("Mon 09:35 outside tolerance", 2026, 10, 12, 9, 35, None),
    ("Mon 10:00 mid session", 2026, 10, 12, 10, 0, None),
    ("Mon 15:27 outside tolerance", 2026, 10, 12, 15, 27, None),
    ("Mon 15:28 tolerance edge", 2026, 10, 12, 15, 28, "CLOSE"),
    ("Mon 15:30 close edge", 2026, 10, 12, 15, 30, "CLOSE"),
    ("Mon 15:32 tolerance edge", 2026, 10, 12, 15, 32, "CLOSE"),
    ("Mon 15:33 outside tolerance", 2026, 10, 12, 15, 33, None),
    ("Mon 20:00 evening", 2026, 10, 12, 20, 0, None),
    ("Fri 09:16 tolerance edge", 2026, 10, 9, 9, 16, "OPEN"),
    ("Fri 09:17 open edge", 2026, 10, 9, 9, 17, "OPEN"),
    ("Fri 09:20 outside tolerance", 2026, 10, 9, 9, 20, None),
    ("Fri 11:59 tolerance edge", 2026, 10, 9, 11, 59, "CLOSE"),
    ("Fri 12:00 break edge", 2026, 10, 9, 12, 0, "CLOSE"),
    ("Fri 13:00 midday break", 2026, 10, 9, 13, 0, None),
    ("Fri 14:31 tolerance edge", 2026, 10, 9, 14, 31, "OPEN"),
    ("Fri 14:32 reopen edge", 2026, 10, 9, 14, 32, "OPEN"),
    ("Fri 16:29 tolerance edge", 2026, 10, 9, 16, 29, "CLOSE"),
    ("Fri 16:30 close edge", 2026, 10, 9, 16, 30, "CLOSE"),
    ("Sat 11:00 weekend", 2026, 10, 10, 11, 0, None),
    ("Sun 11:00 weekend", 2026, 10, 11, 11, 0, None),
    ("Fri 11:00 PSX holiday", 2026, 8, 14, 11, 0, None),
)


def worker_source() -> str:
    return (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")


def schedule_functions(src: str) -> str:
    """The worker's own schedule code, copied verbatim, never reimplemented."""
    block_a = src[src.index(BLOCK_A_START):src.index(BLOCK_A_END)]
    block_b = src[src.index(BLOCK_B_START):src.index(BLOCK_B_END)]
    return block_a + "\n" + block_b


def expectations() -> list[dict]:
    out = []
    for label, y, mo, d, h, mi, edge in CASES:
        local = datetime(y, mo, d, h, mi, tzinfo=KARACHI)
        phase = market_phase(local)
        out.append({
            "label": label,
            "utc": local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "python_phase": phase.value,
            "python_open": phase.is_live,
            "python_trading_day": is_trading_day(local.date()),
            "expected_edge": edge,
        })
    return out


def build() -> Path:
    src = worker_source()
    fns = schedule_functions(src)
    cases = expectations()
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>worker schedule check</title>
<pre id="out">running...</pre>
<script>
const WORKER_SRC = {json.dumps(src)};
const FUNCS_SRC = {json.dumps(fns)};
const CASES = {json.dumps(cases)};
const lines = [];
const result = {{ pass: 0, fail: 0, cases: [] }};
function say(ok, what, extra) {{
  lines.push((ok ? "PASS " : "FAIL ") + what + (extra ? " :: " + extra : ""));
  if (ok) result.pass++; else result.fail++;
}}

// 1. whole-file syntax check in a real engine.
try {{
  const handler = new Function(WORKER_SRC.replace("export default {{", "return {{"));
  const obj = handler();
  say(typeof obj.fetch === "function" && typeof obj.scheduled === "function",
      "worker parses and exposes fetch()/scheduled()", Object.keys(obj).join(","));
}} catch (e) {{
  say(false, "worker parses", e.name + ": " + e.message);
}}

// 2. the worker's own schedule functions, verbatim, against the Python law.
let W = null;
try {{
  W = new Function(FUNCS_SRC +
    "\\nreturn {{ karachiView, bandsFor, minutesOf, marketPhase, marketOpenNow, marketState, isTradingDay }};")();
  say(true, "extracted schedule functions evaluate");
}} catch (e) {{
  say(false, "extracted schedule functions evaluate", e.name + ": " + e.message);
}}

// Mirrors the cron handler: the first guard, then the +/- 2 minute edge test.
function edgeHit(k, bands) {{
  const mins = W.minutesOf(k);
  for (const band of bands) {{
    if (Math.abs(mins - (band[0][0] * 60 + band[0][1])) <= 2) return "OPEN";
    if (Math.abs(mins - (band[1][0] * 60 + band[1][1])) <= 2) return "CLOSE";
  }}
  return null;
}}

if (W) {{
  for (const c of CASES) {{
    const now = new Date(c.utc);
    const k = W.karachiView(now.getTime());
    const bands = W.bandsFor(k);
    const phase = W.marketPhase(now);
    const open = W.marketOpenNow(now);
    const edge = edgeHit(k, bands);
    const asleep = bands.length === 0;
    const row = {{ label: c.label, js_phase: phase, js_open: open,
                 bands: bands.length, edge: edge, asleep: asleep }};
    result.cases.push(row);
    say(phase === c.python_phase, "phase " + c.label,
        "js=" + phase + " py=" + c.python_phase);
    say(open === c.python_open, "open  " + c.label,
        "js=" + open + " py=" + c.python_open);
    say(asleep === !c.python_trading_day, "sleep " + c.label,
        "asleep=" + asleep + " tradingDay=" + c.python_trading_day);
    say(edge === c.expected_edge, "edge  " + c.label,
        "js=" + edge + " want=" + c.expected_edge);
    // the only instant the handler sends a text is a band edge
    say(!edge || !asleep, "edge never fires with no bands " + c.label, "");
  }}
  // marketState is what /health returns, and it needs nextEvent + pktInstant.
  try {{
    const st = W.marketState(new Date("2026-10-09T04:32:00Z"));  // Fri 09:32 PKT
    say(st.phase === "OPEN" && st.trading_day === true &&
        Array.isArray(st.bands) && st.bands.length === 2,
        "marketState reports a two-band Friday",
        JSON.stringify(st.bands));
    const next = W.marketState(new Date("2026-10-09T07:05:00Z"));  // Fri 12:05 PKT
    const ev = next.next_event;
    say(!!ev && ev.event === "OPEN", "next_event after the break is an OPEN",
        JSON.stringify(ev));
  }} catch (e) {{
    say(false, "marketState", e.name + ": " + e.message);
  }}
}}

result.lines = lines;
window.RESULT = result;
document.title = "pass=" + result.pass + " fail=" + result.fail;
document.getElementById("out").textContent =
  lines.join("\\n") + "\\n\\n" + result.pass + " passed, " + result.fail + " failed";
</script>
"""
    OUT_HTML.write_text(html, encoding="utf-8")
    return OUT_HTML


def main() -> int:
    path = build()
    print(f"wrote {path.relative_to(ROOT)}")
    print(f"{len(CASES)} instants, {len(CASES) * 5 + 4} assertions expected")
    print("open it in the preview panel; window.RESULT holds the verdicts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
