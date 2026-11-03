# Quant of Rehan desktop terminal (Windows 11)

The shipped desk is the console terminal: it opens in its own terminal
window, draws the HUD in text and reads the relay the cloud keeps fed. The
Qt window in `src/desktop/app.py` remains in the repository, but the
shortcut on the Desktop points at the console build.

## The console desk (`src/desktop/tui.py`)

Owner order 2026-11-03: the desk must look and open like the console he
already runs, and it must not disagree with it. The old window read only
the capture file next to it, and that file exists only while the window is
open, so every number on screen was thin or stale. The console reads the
same public relay surface his console reads, once a second, and adds
nothing of its own:

| Page | Key | What it shows |
|---|---|---|
| Home | 1 | greeting, market status from the session law, the latest engine record with the time and age it was written, KSE100, and the top three scrips by running volume with B, S, T and a spark |
| Scanner | 2 | CUSTOM SCRIPS OF VOL: prices rising fast, more buyers and less sellers, or big buying now, from the last sixty seconds of executed buying |
| Order Flow | 3 | the day's money flow by volume: price, buy shares, sell shares, total and change |
| Signals | 4 | the local engine record, its day, trades, scans and the time of its last write |
| Health | 5 | relay address, link milliseconds, rows and fresh rows, feed age, market feed status, phase, next event, index |
| Settings | 6 | relay, poll cadence and keys |

Keys: `1` to `6` pages, up and down select a sort on the scanner, `s`
cycles the sort, `r` refreshes, `q` quits. `python -m src.desktop.tui
--once` prints one frame and exits, which is how a frame is checked
without a terminal.

### Where the numbers come from

- `/quotes` every second: price, volume, high, low and the relay's own
  `buy_volume` and `sell_volume`. These are the same rows the console
  reads, so PRL's volume and split match it instead of the local capture.
- `/market` every five seconds: KSE100 and the volume leaders.
- `/health` every fifteen seconds: the session law, the market feed's
  status and age, and the next event.
- The sixty second board is computed from each poll: a positive
  increment of the running volume is sided by the price move against the
  previous poll (or keeps the last side when the price held) and valued at
  the print price. The first sight of a scrip is its baseline, never a
  trade.
- Day buying and selling hold each side at its session high-water mark, so
  neither can fall inside a session, and the board says in words that the
  pair is the relay's range estimate and not order flow. A row the relay
  sends without a split gets the same range estimate locally.
- A quote whose running total goes backwards is never attributed, and one
  bad row never stops a poll.

The phase is always the session law's. The engine record on disk is shown
with the day it names and how old its file is, so an eight-day-old record
reads as eight days old rather than as today's signal.

Run it from source with `python -m src.desktop.tui`, or build it:

```powershell
python -m PyInstaller --noconfirm packaging/quant_of_rehan_console.spec
```

That writes `dist\QuantOfRehanConsole\QuantOfRehan.exe`, a console
application of about 19 MB on disk that needs no Qt and no local feed.

## The Qt window (`src/desktop/app.py`)

A stand-alone Windows client for the same backend this repository already
runs: the read-only Eclear feed capture, the market session law, the
order-flow layer and the local session record. It holds no broker
credential, has no order path (SO-1), and does not need Telegram or
Cloudflare to open, read the banked tape or show the session record.

The terminal is honest by construction: every screen is filled from
`src/desktop/bridge.py`, which reads the real modules. A value the backend
does not carry prints as a dash, never as a zero, and an inferred order-flow
number says so next to itself.

## What is implemented

| Page | What it shows | Source |
|---|---|---|
| Home | Quant status chip and greeting, the local session record's latest signal, the index and top volume scrips with price, change and the B/S/T money flow per scrip, a buying-now board and a dotted chart each, telemetry | session law, banked tape, live feed, `trade_state`, `volume_split` |
| Live Market | newest quote per symbol: last, change, bid, ask, spread, volume, age; symbol filter | `feed_capture` capture |
| Order Flow | OBI top-1, inferred CVD, inferred buy and sell, session VWAP, spread; measured from the day's tape | `src/data/order_flow.py` |
| Signals | the real session record, plus one local scan on demand | `src/signals/trade_state.py`, `scripts/intraday_pipeline.py` |
| System Health | recorder FRESH, STALE or DEAD, counters, last frame, last error | recorder heartbeat file |
| Settings | start the feed on open, live-table size, save | `%APPDATA%\QuantOfRehan\settings.json` |

Every page above is real. Pages that exist only as ideas (watchlist,
historical browse, performance analytics) are deliberately absent rather
than shown empty.

## How it looks and behaves (reworked 2026-11-03 after owner review)

The first two builds were replaced after owner review. The terminal now
reads as the same HUD the owner runs on the phone and the console:

- Near-black field, cyan bracket boards, gold brand. Status chips at the
  top: link state with live age (LIVE, LAGGING, OFFLINE), market phase,
  KSE100 chip and Karachi clock, over a thin cyan session bar.
- Home carries the Quant Core status, a buying-now board, telemetry
  (link, feed, phase, next event, scan cadence, flow), the latest
  signal from the local record, and the index plus top scrips of volume
  with a dotted chart each.
- Separated buying and selling volume, measured and monotonic: the
  B/S/T rows on Home come from `bridge.FlowMemory`, which classifies
  every positive increment of the venue's running total with the
  repository's own window rules (`src/data/tick_volume.py`: print at the
  ask, print at the bid, else the tick rule) and accumulates. The owner's
  law of 2026-11-03 came from a real bug: the retired range-position
  estimate re-attributed the whole day's volume by where the price sat
  in the day's range, so a scrip printing at its high showed sell volume
  0 and one at its low showed buy volume 0, wiping real volume. The
  memory here can only add: buy, sell and the venue total never fall
  inside a session. Windows without evidence, outages longer than ten
  minutes, shares counted before the terminal started, and running totals
  that go backwards are reported as unattributed rather than split by
  guess, and the board carries that basis sentence. Sides per print
  remain on the Order Flow page, INFERRED by the tick rule, with the
  Level-2 registry verdict attached.
- Charts read the tape's tail for the last configured 45 minutes once
  at start (`bridge.spark_series`), then grow from the live print stream
  in memory, downsampled to a bounded point count.
- About the feed delay: the recorder banks every frame the instant the
  broker socket pushes it, and the window renders each batch as it
  arrives; the terminal adds no wait and no polling interval to the
  panel any more (the flow board used to be recomputed every 30
  seconds). The remaining few seconds are the subscription itself, as
  measured in the 2026-11-03 forensic audit: the wire publishes a new
  top-of-book row per symbol every ~24 seconds, and a new print reaches
  it a median 8.6 s and 95th percentile 22.5 s after the exchange clock.
  No terminal can see a print before the broker's own sampler publishes
  it, and adding subscriptions was forbidden. The System Health page
  measures the live number every fifteen seconds (`bridge.wire_lag`):
  median, p95, worst print lag and the newest frame's age, straight from
  the newest banked frame's own print clocks.
- The market phase shown anywhere comes from the session law, never from
  the engine's record file. The LATEST SIGNAL card shows the engine's
  own vocabulary; a market marker such as MARKET_CLOSED written before
  the open prints as NO TRADE TODAY, with the record's state and the
  time it was written beside it (`bridge.session_record`), so an old
  record can never read as the live market state.
- The home flow board is the top three scrips by the venue's running
  volume, not by any estimate, and the BUYING NOW board ranks measured
  buying volume. A scrip with volume but no attributable window yet
  shows a dash for B and S rather than a false zero, and the footnote
  counts the unattributed shares.
- Every page fills from the banked tape on open (`bridge.quote_rows`),
  before the live feed says anything; the live session then overrides
  each symbol it reports.
- Live tables are right-aligned and colour-coded: green up, red down,
  and a dimmed age once a quote is more than two minutes old.
- The feed watchdog: on the one-second clock (a state check, never a
  wait), a feed thread that dies while the market is open is restarted,
  capped at 24 restarts per session. The watchdog never overrides
  `--no-feed` or `--smoke`: those runs touch no socket.
- The window icon and the EXE icon are the same flat gold-and-green
  candlestick tile drawn in `assets/quant-of-rehan.ico`.

Two real bugs the rework fixed: while frozen, the heartbeat reader still
looked at the repository's capture root instead of
`%APPDATA%\QuantOfRehan\data\feed_capture`, so a running feed could
report DEAD; and the first watchdog draft violated the `--smoke`/
`--no-feed` contract by reopening the socket. Both are closed.

## Run from source

```powershell
python -m pip install -r requirements.txt -r requirements-desktop.txt
python -m src.desktop.app
```

Flags: `--no-feed` opens the window without the socket, `--smoke` builds
the whole window offscreen, ticks its clock once and exits (packaging and
CI use this).

## Build the executable

```powershell
python -m pip install -r requirements.txt -r requirements-desktop.txt
python -m PyInstaller --noconfirm packaging/quant_of_rehan.spec
```

That writes `dist\QuantOfRehan\QuantOfRehan.exe` (one-dir, so launch stays
fast and nothing is unpacked into `%TEMP%` on every start). The same build
runs on GitHub Actions through `.github/workflows/desktop-windows.yml`,
which publishes the zip as an artifact; the runner does the packaging so
the owner's PC does not.

## Measured, not estimated

Built and measured on the owner's PC on 2026-11-03 with PyInstaller and
PySide6 6.12:

| Measure | Value |
|---|---|
| `dist\QuantOfRehan` on disk | 152 MB |
| `QuantOfRehan.exe` | 6.76 MB |
| release zip | 63.9 MB |
| launch wall time | 1.83 s including the 1.2 s smoke timer, so about 0.6 s to the window |
| peak working set, smoke run | 70 MB |
| CPU, smoke run | 0.38 s |
| smoke exit code | 0 |

Remeasured after the 2026-11-03 HUD rework (cyan boards, B/S/T money
flow, dotted charts, watchdog) on the same machine; earlier numbers
belonged to superseded builds.

The smoke run is a short launch, not a claim about a full session. The live
feed itself is the same `CaptureSession` the cloud recorder runs; opening
the terminal during a session samples the wire at the wire's own cadence
(about 24 s per symbol), it does not add subscriptions.

## Where it writes

- Settings: `%APPDATA%\QuantOfRehan\settings.json`
- Frozen build's capture, status and tape: `%APPDATA%\QuantOfRehan\data\feed_capture`
- Source runs use the repository's own `data/feed_capture`

The frozen build deliberately does not write inside its install directory.

## What the terminal will not do

- Send an order, a cancel or a modify. The recorder admits only MKT-FEED,
  EXS-FEED and HELLO frames.
- Show a depth ladder, order-level data or cancellations: the registry
  records footprint as UNAVAILABLE and the wire carries top of book only.
- Present inferred flow as measured flow. Sign classification is marked
  `INFERRED_LIMITED`, the CVD and buy and sell columns inherit that label,
  and the Order Flow page states the basis in words.
- Replace the cloud session loop. The scan button runs one local pass of
  the same engine; the schedule, the relay and the record remain in the
  cloud.

## Tests

`tests/test_desktop_tui.py` covers the console without a terminal: the
relay's split is used as given and held monotone, a rebalanced split cannot
pull either side down, the sixty second flow sides by poll delta and keeps
the last side on a held price, a backwards total is ignored, the window
empties after sixty seconds, the top three are the volume leaders, every
page renders inside the terminal's size, and missing quotes still draw a
frame.

`tests/test_desktop_bridge.py` covers the data core without PySide6, so the
normal CI install stays lean: newest quote per symbol, stale tails refused,
heartbeat FRESH and STALE and DEAD, the session gauge and its phase names,
settings roundtrip and fallback, the decision record read not invented, and
the inferred basis carried on every order-flow row.
