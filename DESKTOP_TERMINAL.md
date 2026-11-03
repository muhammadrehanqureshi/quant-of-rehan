# Quant of Rehan desktop terminal (Windows 11)

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
| Overview | session arc gauge, KSE100, market phase and next event, top volume, today's decision | session law, live feed, `trade_state` |
| Live Market | newest quote per symbol: last, change, bid, ask, spread, volume, age; symbol filter | `feed_capture` capture |
| Order Flow | OBI top-1, inferred CVD, inferred buy and sell, session VWAP, spread; measured from the day's tape | `src/data/order_flow.py` |
| Signals | the real session record, plus one local scan on demand | `src/signals/trade_state.py`, `scripts/intraday_pipeline.py` |
| System Health | recorder FRESH, STALE or DEAD, counters, last frame, last error | recorder heartbeat file |
| Settings | start the feed on open, live-table size, save | `%APPDATA%\QuantOfRehan\settings.json` |

Every page above is real. Pages that exist only as ideas (watchlist,
historical browse, performance analytics) are deliberately absent rather
than shown empty.

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
| release zip | 63.8 MB |
| launch wall time | 1.84 s including the 1.2 s smoke timer, so about 0.6 s to the window |
| peak working set, smoke run | 66 MB |
| CPU, smoke run | 0.36 s |
| smoke exit code | 0 |

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

`tests/test_desktop_bridge.py` covers the data core without PySide6, so the
normal CI install stays lean: newest quote per symbol, stale tails refused,
heartbeat FRESH and STALE and DEAD, the session gauge and its phase names,
settings roundtrip and fallback, the decision record read not invented, and
the inferred basis carried on every order-flow row.
