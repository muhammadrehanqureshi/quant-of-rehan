# Charts of Rehan, the web front end

React 18 and TypeScript, strict, no UI framework and no charting library. The
candles are drawn on a canvas by about four hundred lines in `src/chart/`, and
the data layer is a typed client the tests drive with fake transports.

## Running it

```bash
npm install
npm run dev        # http://localhost:5173, /api proxied to http://127.0.0.1:8788
npm test           # 64 unit tests, no network, no browser
npm run typecheck  # tsc in strict mode over src and the Vite config
npm run build      # writes dist/, which the Python service can serve itself
```

Start the backend first (from the repository root):

```bash
python -m charts --source tape --port 8788
```

Then open the dev server, or build and let the service serve `web/dist`:

```bash
python -m charts --source tape --port 8788 --static web/dist
```

`vite.config.ts` holds the proxy target; change it there if you start the
service on another port. In a built deployment the service serves this bundle
itself, so the browser sees one origin in both cases and there is no CORS
preflight in normal use.

## How it is put together

```
src/
  api/types.ts        the server contract, typed and validated at the boundary
  api/client.ts       REST and SSE client: retries, timeouts, named failures
  chart/series.ts     typed-array series: upsert, window, aggregation
  chart/scale.ts      nice ticks and linear scales
  chart/format.ts     Karachi time and price formatting
  chart/render.ts     the canvas renderer: candles, volume, gaps, crosshair
  components/         ChartCanvas, MarketHeader, NotesPanel, SymbolPicker
  hooks/useChartFeed.ts   series, stream, status and metadata for one symbol
  App.tsx, main.tsx, styles.css
```

Three decisions shape the code.

**A payload is parsed, never cast.** `parsePayload` checks every field a chart
draws from, including that each timestamp carries a UTC offset, that bars are
ascending and unique, and that each bar's high and low are consistent with its
own open and close. A response that fails becomes a named `CONTRACT` error
rather than a chart of `undefined`s.

**React re-renders for metadata; the canvas repaints for pixels.** Bars live in
parallel `Float64Array` columns inside a ref. A poll, or a pointer move, marks
the canvas dirty and repaints from those arrays; nothing allocates per frame
and no hover re-renders the tree.

**Nothing is hidden.** The notes panel shows the series' own caveats, the
measured gaps and any ingest failure. The header shows which source the bars
came from and its delay. A status pill says `live`, `reconnecting` or
`closed`, and the stream reconnects with a bounded backoff instead of
pretending a dropped connection is still live.

## Rendering

`drawChart` is one function and one frame. It computes a price range over the
visible window, draws grid and axis labels from the tick maths, shades the
measured gaps with their minute count, draws candles and volume, marks the last
price, and draws a crosshair with an OHLCV readout when the pointer is inside
the plot.

When the visible window holds more bars than the plot has room for candles,
the series is folded into buckets first: `open` from the first bar of the
bucket, `high` and `low` from its extremes, `close` from its last bar, volume
summed. That is the exchange's own OHLC rule, and it means a session of
minutes still draws readable candles in a few hundred pixels. The underlying
minute series is untouched, so zooming back in shows every minute again.

The time axis always prints Karachi time (`Asia/Karachi`), never the viewer's
zone, matching the one clock rule the backend enforces (SO-8).

## What is not here yet

Honest gaps, so the next reader does not have to guess:

* no pan, zoom or range selection yet; the view shows the newest 260 bars;
* no indicator overlays or drawings;
* no offline caching of series, so a reload refetches history;
* the tests cover the data layer and the series maths, not the canvas
  renderer; the renderer is verified by looking at it.

## Types and tooling

`tsconfig.json` runs with `strict`, `noUncheckedIndexedAccess`,
`exactOptionalPropertyTypes`, `noImplicitOverride`, `noFallthroughCasesInSwitch`,
`noUnusedLocals` and `noUnusedParameters`. The test runner is Vitest in a Node
environment, because the tested modules are pure: a browser environment would
only slow the suite down without proving more.

The build is Vite. The decision to keep dependencies to React, Vite and the
type packages is deliberate: this front end reads one JSON contract and draws
candles, and a charting framework would have hidden the two things this
application most needs to be honest about (which bar came from where, and what
is missing).
