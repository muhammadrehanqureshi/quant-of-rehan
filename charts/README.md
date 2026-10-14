# Charts of Rehan

A modular charting service for this project's own market data: minute candles,
volume, the exchange's real session clock, and a measured list of the minutes
that are missing. It is a backend (`charts/`, standard library Python) plus a
front end (`web/`, React and strict TypeScript).

Two ideas carry the whole design.

**The chart cannot know more than the data does.** Every payload says which
source the bars came from, how delayed that source is, how many bars were
revised after they first appeared, and which minutes the session expected but
no bar filled. A symbol with nothing to show is an empty series with a
sentence explaining it, never a row of zeroes.

**One authority per question.** Minute bars are built by
`src/data/tape_bars.py`, session facts by `src/data/sessions.py`, the portal
panel by `src/data/market_snapshot.py`, and what data the project genuinely
has by `src/data/registry.py`. This package wraps them. It never restates a
session table, never re-derives a holiday list, and never invents a bar.

## Quick start

The service is standard library Python, so there is nothing to install:

```bash
# The whole pipeline with no network and no exchange: deterministic replay
# bars, one deliberate gap, one revised bar, and the wire JSON printed.
python examples/charts_demo.py

# One real poll, then the health report as JSON and exit.
python -m charts --source tape --symbols OGDC --once

# Serve the API and the built front end on loopback.
python -m charts --source tape --port 8788 --static web/dist
```

The front end needs Node only for its development server and its build:

```bash
cd web
npm install
npm run dev      # http://localhost:5173, proxying /api to the service
npm test         # 64 unit tests
npm run build    # writes web/dist, which the service then serves
```

## What it serves

| Route | Answer |
|---|---|
| `GET /api/health` | the service, the Karachi clock, the resolved market phase, the source's own claims, ingest counters and per-symbol failures |
| `GET /api/symbols` | the symbols this deployment can serve |
| `GET /api/bars?symbol=..&resolution=..&limit=..` | one chart payload (see below) |
| `GET /api/stream?symbol=..&resolution=..` | Server-Sent Events: `snapshot` once, then `bars` per poll, plus `idle` and a keep-alive comment every five seconds |
| everything else | the built web app from `--static`, with a single page app fallback |

A payload:

```json
{
  "ok": true,
  "schema_version": 1,
  "as_of": "2026-10-14T15:54:44+05:00",
  "symbol": "OGDC",
  "resolution": "1m",
  "source": { "id": "broker_tape", "label": "...", "delay_seconds": 0, "note": "..." },
  "market": { "phase": "OPEN", "state": "MARKET", "trading_day": true,
              "timezone": "Asia/Karachi", "band": { "open": "09:32", "close": "15:30" },
              "next_event": { "event": "CLOSE", "at": "..." }, "as_of": "..." },
  "bars": [ { "t": "2026-10-14T15:30:00+05:00", "o": 118.03, "h": 118.87, "l": 118.0, "c": 118.41, "v": 20138 } ],
  "bar_count": 357,
  "gaps": [ { "start": "...", "end": "...", "minutes": 2, "reason": "no bar was printed in this minute" } ],
  "notes": [ "..." ],
  "ingest": { "polls": 3, "subscribers": 2, "dropped_events": 0, "errors": {} }
}
```

Every timestamp is ISO 8601 **with the Karachi offset**, produced server side,
so a browser in any timezone draws the exchange's own clock (SO-8). A naive
timestamp is refused by the contract rather than assumed.

## Architecture

```
                     +-----------------------------+
   broker tape  ---> |  charts/adapters/tape.py    |
   portal page  ---> |  charts/adapters/portal.py  |  one BarSource protocol:
   replay bars  ---> |  charts/adapters/replay.py  |  capabilities, catalog,
                     +--------------+--------------+  history, latest
                                    |
                       charts/ratelimit.py (pacing, bounded retries, breaker)
                                    |
                     +--------------v--------------+
                     |  charts/ingest.py           |  one polling thread,
                     |  poll -> upsert -> fan out  |  bounded subscriber queues
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |  charts/store.py            |  upserts, revision counts,
                     |  series, gaps               |  thread safe, copy on read
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |  charts/service.py          |  one payload builder:
                     |  bars + gaps + provenance   |  notes, limits, gap floor
                     +--------------+--------------+
                                    |
                     +--------------v--------------+
                     |  charts/http.py             |  REST, SSE, static files,
                     |  contract / error taxonomy  |  CORS allow list
                     +-----------------------------+
```

* **`charts/contract.py`** defines the wire shape once, validates it in both
  directions, and refuses a bar that is internally inconsistent (a high below
  its own close) or out of order.
* **`charts/adapters/`** is the seam. An adapter says what it can honestly
  serve (`capabilities`), what it knows (`catalog`), past bars (`history`) and
  the newest bars (`latest`). Adding a source touches nothing else.
* **`charts/ratelimit.py`** holds a token bucket, bounded retries with
  proportional jitter, and a circuit breaker, all injectable with a clock so
  tests prove them without sleeping. A 404 is never retried.
* **`charts/ingest.py`** polls only the symbols charts are actually watching,
  forgets them after fifteen idle minutes, drops the oldest event when a slow
  reader falls behind (and counts it), and names every per-symbol failure.
* **`charts/store.py`** replaces the minute still forming instead of
  duplicating it, counts those revisions, and measures gaps against the
  session law's own expected minutes.
* **`charts/service.py`** is the single path from the store to the wire, so
  the API, the SSE snapshot, the example and the tests cannot disagree.
* **`charts/http.py`** serves the API, the event stream and the built UI.

## The sources, and what each one is allowed to claim

| Source | Serves | Honest limits |
|---|---|---|
| `tape` (`broker_tape`) | `1m` bars from this project's read-only MKT-FEED recording, built by `src/data/tape_bars.py` | only what the recorder banked; a symbol that started late says so; volume comes from the venue's own counter |
| `portal` (`psx_portal`) | `session`: one bar per trading day from the company page's REG panel | about five minutes delayed, and it is not an intraday series; a cleared panel is a named failure, not a zero bar |
| `replay` | `1m` synthetic bars | labelled synthetic, refused unless named on the command line; it exists to test the pipeline and demo it offline |

The portal's `/timeseries/eod/{symbol}` endpoint answered an HTML shell and
`/timeseries/int/{symbol}` answered 404 when measured on 2026-10-14, so no
daily or intraday series is claimed from there. `DATA_SOURCING.md` records the
measurement and `src/data/registry.py` (`session_snapshot`) is where that
capability is declared.

## Failure behaviour

| Situation | Answer |
|---|---|
| source timeout | retried with backoff, then `504` with category `TIMEOUT` and `Retry-After` |
| source 429 | retried once within the bucket, then `503 RATE_LIMITED` |
| source 404 | not retried, `502 HTTP_ERROR` |
| source answers with no usable data | `EMPTY_ACK` recorded against the symbol, visible in `/api/health` and in the payload's notes |
| repeated failures | circuit breaker refuses for its cooldown, `503 CIRCUIT_OPEN`, one probe per window |
| missing `?symbol=` | `400 MISSING_SYMBOL` |
| symbol outside the catalogue | `404 UNKNOWN_SYMBOL` |
| resolution the source does not serve | `400 UNSUPPORTED_RESOLUTION`, naming what it does serve |
| malformed or inconsistent payload | `400 CONTRACT` with the sentence that says why |

## Edge cases the code answers rather than assumes

* **Market holidays and weekends.** Expected minutes come from
  `src/data/sessions.py`, so a holiday produces no gaps at all and a Friday's
  midday break is never reported as missing data.
* **The Friday break and the two-band day.** The session law owns the bands;
  the chart shades what it is told and computes nothing.
* **A quiet minute.** The tape builder carries the previous close across a
  watched gap and counts those bars separately; a stretch with no bar at all
  becomes a measured gap of two minutes or more (one missing minute inside a
  live tape is normal and is not shouted about).
* **A late start.** A series that begins mid-session says when it begins and
  how many session minutes it did not see, instead of drawing the whole
  morning as one enormous gap.
* **A revised bar.** Replacing a timestamp counts a revision, and the payload
  discloses the count.
* **A slow reader.** Subscriber queues are bounded and drop the oldest event,
  so a stale browser tab cannot slow the poller or grow the process.

## Performance notes

* The store hands readers a copy, so a payload is assembled without holding
  the write lock.
* A live chart asks for a tail (`limit`), not the whole series.
* On the client, bars live in parallel typed arrays; a pointer move repaints
  from them and never re-renders the React tree.
* Zoomed out, the client folds bars into buckets with the exchange's own OHLC
  rules (`open` first, `high` and `low` extremes, `close` last, volume
  summed), so a session of minutes still draws readable candles in a few
  hundred pixels.
* `Cache-Control: no-store` on every API answer; hashed assets only are cached
  for a year.

## Testing

```bash
python -m pytest tests/test_charts_contract.py tests/test_charts_store.py \
  tests/test_charts_ratelimit.py tests/test_charts_sources.py \
  tests/test_charts_service.py tests/test_charts_http.py -q     # 104 tests
cd web && npm test                                             # 64 tests
```

The Python tests include a real HTTP server on an ephemeral port exercised
over a real socket, including the event stream. The front-end tests prove the
validators, the retry and timeout paths, the stream reconnection and the
series maths with fake transports and a fake clock, so none of them waits a
real second or touches an exchange. The portal tests use a saved panel
fixture; the tape tests use a temporary capture file.

## Running it without breaking the house rules

This service is a **foreground tool**. It registers no schedule, no daemon,
no watcher and no autostart entry, and it refuses to start under GitHub
Actions, because the runner minutes belong to the market-hours scans. It binds
loopback unless the operator passes `--allow-public-bind`, and it stops with
Ctrl+C. Reading and taking work off the machine are always allowed; putting
something on it to run by itself is not.

```bash
python -m charts --source tape --port 8788            # loopback, foreground
python -m charts --source replay --once               # one pass, then exit
python -m charts --source replay --symbols R1 --port 8788 --static web/dist
```

## Layout

```
charts/
  contract.py     the wire contract, validated both ways
  adapters/       base.py, tape.py, portal.py, replay.py
  ratelimit.py    token bucket, retries, circuit breaker, ledger
  store.py        series store, upserts, revisions, gaps
  ingest.py       the polling loop and the subscriber fan-out
  service.py      the one payload builder
  sessions.py     session facts, asked of src/data/sessions.py
  http.py         REST, SSE, static files
  app.py          the command line entry point
tests/test_charts_*.py
examples/charts_demo.py
web/              the React and TypeScript front end (see web/README.md)
```
