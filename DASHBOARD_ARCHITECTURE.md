# DASHBOARD_ARCHITECTURE: a private PSX console on the owner's own feed

**Status:** design, 2026-10-13. **Scope:** one private user, the owner, on his
own machine. **Input:** the read-only broker feed this repository already
banks (`src/data/feed_capture.py`). **Not** a product, **not** redistributed
data, and **not** an order-entry path (SO-1 stands: signal-only).

The objective is a local web console that charts the feed this project already
holds, with footprint and order-flow views that are built only on what the
venue actually publishes. The first section is the measurement that decides
what those views may claim, because everything after it depends on it.

Reproduce every number below with:

```bash
python scripts/tape_capability_report.py            # newest honest session
python scripts/tape_capability_report.py --json data/tape_capability_20261013.json
```

## 1. What the feed actually is (measured 2026-10-13, 09:51 to 10:40 PKT)

3035 frames, 314 of 319 tracked symbols (98.4%), on the live wire:

| Capability | Measured today | What it supports | What it forbids |
|---|---|---|---|
| Best bid and ask, each WITH size | arrives on every snapshot | spread, quote imbalance, top-of-book pressure | no deeper levels, no queue position, no historical book |
| Venue cumulative volume and trade count | per snapshot, monotone within a session | true traded volume per bucket, from the increments | no sizes of individual trades |
| Last print: price, size, time | one print visible per snapshot | a lower bound and a direction hint per snapshot | a true footprint's per-level sizes |
| Print side, from where it traded | at the ask 33.6% of volume, at the bid 44.5%, off both 21.9% | a directional split with an explicit unknown bucket | no exact aggressor attribution |
| Snapshot cadence, per symbol | median 30.1s between two snapshots of one symbol | per-symbol time series at half-minute resolution | not tick-by-tick, not millisecond latency |
| Distinct last prices per symbol | median 5, max 43 over about 50 minutes | per-paisa price levels inside a bucket | 1-minute footprint cells are often nearly empty |
| Price grid | 0.01 PKR tick (PSX Ready Market rule) | integer paisa buckets | nothing finer than a paisa exists |
| Index frames (EXS-FEED) | KSE100, KSE30, KMI30, ALLSHR with OHLC and volume | a real index chart, refreshed with the session | no index history beyond what is banked |
| Corporate-action frames | ADDUCAP, RUCAP, ADDLCAP, RLCAP arrive on the same socket | awareness only | no adjustment maths attempted here |

Two properties matter more than the rest, and both are measured rather than
assumed:

1. **This is a snapshot cycle, not a trade tape.** A 30-second window can hold
   many prints while only the last one's size is visible. The deduplicated
   visible print sizes covered 0.432 of the venue's own volume delta at the
   median (p25 0.247, p75 0.833), and only 0.10 to 0.22 on the busiest names.
   Five symbols' visible sizes exceeded their own delta outright.
2. **The side of a print cannot always be read.** With quoted spreads wider
   than the tick (median spread 0.48 PKR against a 0.01 grid), only 64.6% of
   prints landed exactly on a quote, and 21.9% of the traded volume could not
   be attributed to a side at all.

Consequence, and it is the design's foundation: the honest unit of this feed is
**volume increments of the venue's own counter, each attributed to the price
where the print traded, with a side where one can be read and an explicit
unknown where it cannot**. A footprint built on that is a labelled
reconstruction, not a photograph of the order book. Anything that shows
"sizes" as if they were the venue's per-trade sizes is fabrication (SO-3), and
the console must carry the coverage number next to every such pane.

## 2. Architecture

```
  broker socket (read-only, 3 allowed frame types)
        |
        v
  [capture daemon]  src/data/feed_capture.py        one writer, one file per day
        |  append-only NDJSON: raw frames, immutable, the source of truth
        v
  [normaliser]  frames -> symbol snapshots -> print/increment steps
        |  dedupe by (symbol, volume delta, tick time), never by wall clock
        v
  [store]  SQLite (WAL) for the session + Parquet for research
        |      ~226k snapshot rows and ~60k steps per full session
        v
  [gateway]  FastAPI + uvicorn:  REST for history, WebSocket for the live tail
        |  every payload carries {basis, data_age_ms, session_phase}
        v
  [web]  React + TypeScript + Vite, lightweight-charts, canvas footprint pane
```

Rules that hold across every layer:

- **One writer per artifact.** The daemon owns the raw file; the normaliser
  owns the store; nothing else writes either. Same discipline the tick lock
  already enforces (`data/feed_capture/status.json`).
- **Raw first, derived second, and derivations are replayable.** Any store row
  can be rebuilt from the raw file; the store carries the raw file's day and a
  normaliser version so a bug fix means a replay, not a lost session.
- **Every derived value carries its basis.** `measured` (venue increments and
  quotes), `inferred` (side from print location), `unclassified` (volume that
  could not be attributed), `estimated` (anything projected, marked with the
  same U+2248 the phone card uses). Nulls are explicit, never zeros.
- **Staleness is data.** Each snapshot knows its arrival time; the gateway
  stamps `data_age_ms` on everything it sends, and the UI must dim and say so
  past 90 seconds. A frozen chart must never read as a live one.

## 3. Recommended stack

| Layer | Choice | Why this and not the alternative |
|---|---|---|
| Ingest | existing Python daemon (`src/data/feed_capture.py`) | read-only guard and field map are already written, tested and live-verified; a rewrite would re-litigate the wire |
| Store | SQLite in WAL mode for the session, Parquet + DuckDB for research | single user, tens of MB per session; SQLite needs no server and survives reboots; Parquet answers research queries without touching the live file |
| Gateway | FastAPI + uvicorn (Python, same venv) | one runtime for the whole machine, Pydantic models for the payload contract, native WebSocket support |
| Web | React + TypeScript + Vite | the owner's stated preference; TS is what keeps nullable financial fields honest at the read site, the same argument the Android app already uses |
| Charts | TradingView **lightweight-charts 5.2.1** | 45 KB, canvas, and a documented custom-series API; built-in candlesticks and index lines for free |
| Footprint pane | custom series (or a series primitive over candles) | the documented route for drawing inside each bar's slot; canvas `fillRect`/`fillText` per cell |
| State | server-side SQLite, small client store | drawings and watchlists must survive a browser wipe and follow the owner to the phone |
| Hosting | loopback + Cloudflare Tunnel with Access | the feed lives at home; a public host cannot reach the broker socket |

Node LTS is required at build time for the web tier. It is not installed on
this machine today (the worker's syntax check already runs in CI for that
reason), so the front end is the one part of this stack that cannot be built
or verified here yet. If the owner prefers zero new toolchains, the same UI
works as plain ES modules with a vendored `lightweight-charts.standalone.js`
served by FastAPI; TypeScript and JSX are then lost, nothing else.

## 4. Footprint and order-flow views: what to build, and what to label

**Data model.** One row per (symbol, bucket, price level):

```
{ symbol, bucket_start_ms, price,             # price on the 0.01 grid
  buy_volume, sell_volume, unknown_volume,    # venue increments by side
  steps, visible_print_size,                  # how much of it was seen
  basis: "measured" | "inferred" | "unclassified" }
```

Bucket size follows the measurement, not fashion: with a median of 5 distinct
prices per symbol per ~50 minutes, a 1-minute footprint cell is mostly a
single price, which is a candle with extra steps. Default to 5-minute buckets,
offer 15 and the session profile, and put the distinct-price count in the
bucket header so the owner can see when a cell is thin.

**Rendering requirements.** These are the technical facts that decide whether
the pane is usable at all:

- A custom series is the right container for footprint candles because it
  replaces the candle drawing entirely; a series **primitive** is the right
  container for decorating ordinary candles. Do not mix the two up: the
  interfaces differ (`ICustomSeriesPaneView` with `renderer()`,
  `priceValueBuilder()`, `update()`, `isWhitespace()`, `defaultOptions()`
  versus the primitive's `paneViews()`).
- Cells are canvas work: `target.useMediaCoordinateSpace(...)`,
  `fillRect` per level, `fillStyle` switched by side, `fillText` for the
  numbers. Text only above a zoom threshold (roughly when a cell is wider than
  34 px), otherwise the colour gradient alone.
- Draw only the visible range. The renderer receives the visible bars and the
  bar spacing; iterating all history per frame is the one mistake that turns a
  fast pane into a slideshow.
- The live bucket must be updated with `series.update(item)`, never by calling
  `setData()` on every frame.
- Pixel ratio: size the canvas to `devicePixelRatio` and keep the cell grid
  aligned to whole device pixels, or text will smear on the phone.

**Labeling requirements (SO-3, non-negotiable).**

- Each pane carries its own coverage badge: visible print size divided by the
  venue's volume delta over the same window, plus the unclassified share.
- The unknown bucket is drawn, not hidden. A pane that shows only buy and sell
  when 21.9% of the volume is unattributable is the kind of lie this project
  already refuses in its scanner.
- Session volume profile (per-price volume) is the most robust order-flow view
  this feed can support: it aggregates the increments over the whole session,
  so the 30-second cadence stops mattering, and its fidelity is measurable.

## 5. Watchlists, drawings, and indicator scripts

**Watchlists.** A table, ordered, with per-symbol pins and a `notes` column.
The console opens on the watchlist, not on a blank chart, so a session starts
where the last one ended.

**Drawings.** Stored server-side so they survive a browser wipe and follow the
owner to any device:

```sql
create table drawing (
  id          text primary key,
  symbol      text not null,
  kind        text not null,          -- trendline, hline, rect, fib, note
  anchor_time integer not null,       -- ms; bar time for the first anchor
  anchor_price real not null,
  anchor2_time integer, anchor2_price real,   -- second anchor where the kind has one
  style_json  text not null,          -- colour, width, dash, font size
  revision    integer not null,       -- last write wins per id, never per table
  updated_at  text not null
);
```

Export and import as one JSON file, so the drawing set is portable and
diffable. A drawing whose anchor time falls outside the loaded range is listed
but not drawn, rather than silently dropped.

**Indicator scripts.** The owner writes Python, because this repository is
Python and his own research already is. The honest model for a single-user
tool is a **trusted subprocess**, not a security sandbox:

- a script lives in `dashboard/indicators/<name>.py` with a manifest (name,
  parameters, outputs, description);
- it is executed by the gateway in a subprocess with a wall-clock timeout
  (default 20s), a working directory of its own, and a read-only data handle:
  it receives frames or bars as arguments and returns time series;
- no network by default (the machine can still reach the network; this is a
  discipline, not a jail, and the README must say so plainly);
- results are cached in `indicator_run` keyed by (script hash, params hash,
  data window), so a redraw does not recompute and a changed script
  invalidates itself;
- a runaway script is killed by the timeout and the run row records the kill.

## 6. Hosting

**Recommended: this PC, loopback only.** Two Windows scheduled tasks following
the existing pattern (`scripts/install_kmiall_tick.py`): the capture daemon
(already running) and the gateway (`uvicorn --host 127.0.0.1 --port 8788`).
The web build is served as static files by the same gateway, so there is one
process to supervise and no CORS. Logs go under `logs/`, beside the tick's.

**Phone and second device: the existing Cloudflare tunnel.** `cloudflared`
tunnel to the loopback port, gated by Cloudflare Access with the owner's email
as the only allowed identity. No port forwarding, no public IP, nothing to
attack: the dashboard stays a private single-user tool, which is also what the
PSX terms permit (section 7).

**Low-cost cloud, and why it is second choice.** A $5/month VPS could host the
UI tier, but the feed must be captured where the broker socket is reachable,
so the cloud half would need the gateway to reach back home for data. That is
a second network path and a second attack surface for one user who is usually
at the machine. Revisit only if the owner wants the console when the PC is off,
and then only the UI tier, with a read replica of the store.

**Budget.** Raw tape: about 24 MB per full session as NDJSON (measured on
2026-10-12). Store: roughly 226k snapshot rows and 60k increment steps per
session, tens of MB per year with pruning; research Parquet lives outside the
session path. RAM for the gateway plus store: comfortably under 200 MB.

## 7. Legal and technical feasibility

**Build it, on your own feed.** The owner approved read-only capture on
2026-10-06 (DATA_SOURCING.md section 4, Path A). The daemon's guard already
refuses every frame that is not a subscription, an index subscription or a
heartbeat, so the dashboard inherits a recorder that cannot place, amend or
cancel anything. Personal, non-commercial, single-user use is the position the
PSX Terms of Use describe for a single copy of site content, and the console
is exactly that: private, unauthenticated from outside, never sold or shared.

**Do not reverse-engineer proprietary platforms.** Beyond the terms-of-service
problem, client-side patching of a third-party terminal is an anti-circumvention
risk, breaks on every vendor update, and puts the trading workflow behind
someone else's build. The honest alternative is the one being built here: use
the data the owner is entitled to (his own broker's read-only feed, the PSX
portal's published files) and label the rest as unavailable. That is also what
DATA_SOURCING.md already concluded.

**If this ever stops being private.** PSX's Data Services and Vending page
states that commercial dissemination or use of live or delayed market data
requires the relevant PSX rights or a licence, and that a sub-client needs its
own licence too
([PSX data services](https://www.psx.com.pk/psx/product-and-services/data-services-vending),
[PSX terms of use](https://www.psx.com.pk/psx/terms-of-use)). Anything
multi-user, published, or paid goes through `marketdatarequest@psx.com.pk`
first. Until then: keep it on loopback, keep it private.

**Open items that the dashboard does not change.** The broker feed's own
redistribution rights and latency remain unconfirmed (DATA_SOURCING.md
section 5), and the production gate stays closed. A private console is not an
argument for opening it.

## 8. Roadmap

| Milestone | Deliverable | Acceptance test |
|---|---|---|
| **M0** (done today) | this document and `scripts/tape_capability_report.py` | the report runs on a real session and prints the coverage, fidelity and side numbers above; 11 unit tests pin the increment rule, the side rule and the file pick |
| **M1** | canonical store + replay: normalise a raw day into SQLite, rebuild from raw on demand | replaying 2026-10-13 from raw reproduces byte-identical store rows; a truncated raw file is reported, never silently accepted |
| **M2** | gateway: REST history + WebSocket tail, with `basis`, `data_age_ms`, `session_phase` on every payload | loopback latency p95 under 1 second from tape frame to browser paint; a killed reconnect resumes from the last accepted sequence without duplicating a step |
| **M3** | web console: watchlist, candlestick + index + volume charts, drawings with server persistence | drawings survive a browser wipe and a machine restart; the same set renders on a 375 px phone width; no layout shift past 60 ms |
| **M4** | footprint and session-profile panes with coverage badges | the badge recomputes from the same store the pane draws; the unknown bucket is visible and non-zero on a real session; the pane holds 60 fps at 5k visible cells on the owner's phone |
| **M5** | indicator runner with manifests, timeout, cache | a runaway script is killed at the timeout and recorded; a cached run is not recomputed; a changed script invalidates its own cache |

A parallel change is worth deciding on before M3: this feed can also produce
the intraday bars the strategy has been missing since the OHLC servlet died
(bar OHLC from prints, volume from the venue counter, which
DATA_SOURCING.md already describes as banked but not yet wired in). That
change un-blocks the scanner; the dashboard would then chart the same bars the
strategy trades.

## 9. Snippets

### 9.1 Gateway: the canonical step and a live tail (Python, M2 target)

```python
# dashboard/gateway/app.py  (M2 target, not wired yet)
from fastapi import FastAPI, WebSocket
from pydantic import BaseModel

class Step(BaseModel):
    symbol: str
    at: str                  # capture arrival, Karachi ISO
    price: float             # where the print traded
    volume: float            # the venue counter's increment, never a print size
    side: str                # "buy" | "sell" | "unknown"
    basis: str               # "measured" | "inferred" | "unclassified"
    visible_print: float | None
    data_age_ms: int

app = FastAPI()

@app.websocket("/tail")
async def tail(ws: WebSocket) -> None:
    await ws.accept()
    async for step in store.follow():        # yields persisted steps, in order
        await ws.send_text(step.model_dump_json())
```

The normaliser's whole reason for existing is one rule, and it is the rule the
unit tests pin:

```python
def step_from(previous: dict, current: dict) -> Step | None:
    """One increment of the venue's counter, or None when nothing traded."""
    delta = float(current["volume"]) - float(previous["volume"])
    if delta <= 0:
        return None                          # the same print echoed again
    last, bid, ask = current["last"], current["bid"], current["ask"]
    if last == ask:
        side, basis = "buy", "inferred"
    elif last == bid:
        side, basis = "sell", "inferred"
    else:
        side, basis = "unknown", "unclassified"
    return Step(symbol=current["scrip"], at=current["ts"], price=float(last),
                volume=delta, side=side, basis=basis,
                visible_print=float(current["last_volume"] or 0),
                data_age_ms=0)
```

### 9.2 Web chart: candles plus a custom footprint series (M3/M4 target)

```tsx
// dashboard/web/src/Chart.tsx  (M3 target; needs Node at build time)
import { useEffect, useRef } from "react";
import {
  CandlestickSeries, createChart, type IChartApi, type UTCTimestamp,
} from "lightweight-charts";
import { FootprintSeries, type FootprintItem } from "./FootprintSeries";

export function Chart() {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const footprint = useRef<ReturnType<IChartApi["addCustomSeries"]> | null>(null);

  useEffect(() => {
    if (!host.current) return;
    chart.current = createChart(host.current, { layout: { background: { color: "#120c1a" } } });
    chart.current.addSeries(CandlestickSeries, { upColor: "#43c98a", downColor: "#c14a52" });
    // A custom series REPLACES the candle drawing in its own pane; if the
    // owner only wants cells drawn over ordinary candles, use a series
    // primitive instead (see the docs' series-primitives page).
    footprint.current = chart.current.addCustomSeries(new FootprintSeries(), {
      gridLineColor: "#2a1e38",
      textThresholdPx: 34,          // numbers only when a cell can hold them
    });
    return () => chart.current?.remove();
  }, []);

  useEffect(() => {
    const ws = new WebSocket("ws://127.0.0.1:8788/tail");
    ws.onmessage = (event) => {
      const item: FootprintItem = JSON.parse(event.data);
      // update() for the live bucket; setData() only when history changes.
      footprint.current?.update(item);
    };
    return () => ws.close();
  }, []);

  return <div ref={host} style={{ width: "100%", height: "60vh" }} />;
}
```

```ts
// dashboard/web/src/FootprintSeries.ts  (M4 target)
import type {
  CustomSeriesPricePlotValues, ICustomSeriesPaneRenderer, ICustomSeriesPaneView,
  PaneRendererCustomData, Time, WhitespaceData,
} from "lightweight-charts";

export interface FootprintItem {
  time: Time;
  open: number; high: number; low: number; close: number;
  levels: { price: number; buy: number; sell: number; unknown: number }[];
  coverage: number;              // visible prints / venue delta, shown in-pane
}

class Renderer implements ICustomSeriesPaneRenderer {
  draw(target: Parameters<ICustomSeriesPaneRenderer["draw"]>[0],
       priceToCoordinate: (p: number) => number | null): void {
    // Cells are canvas work: switch fillStyle by side, fillText only above the
    // threshold passed in options, and touch nothing outside the visible range.
  }
}

export class FootprintSeries implements ICustomSeriesPaneView<Time, FootprintItem, object> {
  renderer(): ICustomSeriesPaneRenderer { return new Renderer(); }
  update(data: PaneRendererCustomData<Time, FootprintItem>, _options: object): void {}
  priceValueBuilder(item: FootprintItem): CustomSeriesPricePlotValues {
    // Autoscale and the price line read this: high, low, then current.
    return [item.low, item.high, item.close];
  }
  isWhitespace(item: FootprintItem | WhitespaceData): item is WhitespaceData {
    return (item as FootprintItem).high === undefined;
  }
  defaultOptions() { return {}; }
}
```

Both snippets are starting skeletons, not finished code: the repo has no
JavaScript test runner, so nothing here is verified on this machine. They are
included because the API contract is the part worth getting right before the
milestone that builds them, and the anchors are the official docs
([custom series](https://tradingview.github.io/lightweight-charts/docs/plugins/custom_series),
[canvas rendering target](https://tradingview.github.io/lightweight-charts/docs/plugins/canvas-rendering-target),
[series primitives](https://tradingview.github.io/lightweight-charts/docs/plugins/series-primitives)).

## 10. Decisions for the owner

1. **Default bucket size**: 5 minutes (recommended, measured), or 1 minute
   with thin cells made explicit, or session profile only.
2. **Toolchain**: install Node LTS for the React build, or take the no-build
   variant (ES modules plus the standalone chart bundle) and stay Python-only.
3. **Order of work**: M1 through M5 as listed, or first wire tape-derived bars
   into the scanner (the parallel change above) and let the strategy run again
   on genuine bars before the console is built on top of them.
4. **Phone access**: leave the console loopback-only, or expose it through the
   existing Cloudflare tunnel with Access. Recommended: tunnel plus Access
   when M3 lands, never a public port.
