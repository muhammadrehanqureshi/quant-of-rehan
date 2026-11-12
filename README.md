<p align="center">
  <img src="assets/QoR.png" alt="Quant of Rehan" width="380" />
</p>

<h1 align="center">Quant of Rehan</h1>

<p align="center"><sub><code>assets/QoR.png</code> is the project's official mark: 1024 by 1024, dark plum, the gradient wordmark, the teal line and the ascending green candles.</sub></p>

[![Governance Guard](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/governance-guard.yml/badge.svg)](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/governance-guard.yml)
[![Android App](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/android-apk.yml/badge.svg)](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/android-apk.yml)

**Private, signal-only intraday research platform for PSX KMIALL stocks.**
No order placement, no broker trading integration: signals and research only.

## Contributors

| Name | Role |
|---|---|
| [Mr. Rehan](https://github.com/muhammadrehanqureshi) | Owner and sole human author (SO-7). Decision authority for every rule in [GOVERNANCE.md](GOVERNANCE.md). |

## The strategy in one paragraph

Scan the current KMIALL universe for the Kalman Trend in one of two shapes.
The first is a fresh upward flip of the one minute Kalman filter: the flip is
the entry and the last completed minute's close is the price. The second is
the pullback: when the one minute trend is already up and the 5 minute, 15
minute and 1 hour VWAP frames agree, do not enter on the agreement itself.
Wait for the pullback, take its resumption, and only while both the
pullback's low and the entry sit nearer the day's low than the day's high.
When both shapes are legal on one symbol, the higher score is carried. Either
way the plan is the owner's law: paper entry at the observed price, stop at
entry minus 1%, target at entry plus 2%, one call a day, and no trade after a
broad selloff. A candidate only exists on completed minutes; there is no
momentum or RSI fallback. Entry and exit intent only: nothing reaches a
broker (SO-1).

## Architecture

Three tiers. The recurring work lives in the cloud (SO-12, SO-23) and the
screen is the owner's own console; the owner's PC is never a dependency of the
schedule.

```text
eClear MKT-FEED REG socket (read only: no order frame is sendable)
   |
   v  src/data/feed_capture.py   banks the tape, seeds the day's baseline,
   |                             publishes one coalesced snapshot a second
   +-- src/data/quote_flow.py    sides every increment of the venue's own
   |                             counter with the bid/ask standing when it
   |                             arrived, and holds each pair monotone
   v
cloud/worker.js   Cloudflare Worker + QuoteHub Durable Object
   /quotes /flow /market /prices /signals /history /ack-upsert
   |
   +--> windows/                  the Windows console HUD (Go, one exe)
   +--> android/                  the phone card
   +--> charts/ + web/            the research charts
   +--> .github/workflows         the scan, the capture bands and the builds
```

One symbol carries one frame. The relay is the only place every surface reads,
so the newest acknowledged frame wins there and its buying and selling pair is
clamped monotone against it, and the HUD shows the age of what it is reading
rather than inventing a fresher number.

## What is true today

- **One scanner**: [src/signals/momentum_scanner.py](src/signals/momentum_scanner.py)
  returns exactly one confirmed Kalman Trend long (the fresh flip, or the three
  frame agreement's pullback), NO TRADE, or DATA BLOCKED, with market context
  gating and late-entry refusal instead of any fallback signal.
- **The latest strategy**: [src/signals/kalman_vwap_rs.py](src/signals/kalman_vwap_rs.py)
  is the running law (`kalman_vwap_rs_v3`, owner order 2026-11-09): the Kalman
  Trend with VWAP on the 5 minute, 15 minute and 1 hour charts and relative
  strength. Relative strength is the name's session return minus the
  equal-weight mean of the captured universe, measured from the session tape
  alone. Both entry paths stay: [src/signals/kalman_trend.py](src/signals/kalman_trend.py)
  owns the fresh flip (`kalman_trend_flip_v1`), and
  [src/signals/kalman_vwap_pullback.py](src/signals/kalman_vwap_pullback.py)
  owns the three frame VWAP pullback (`kalman_vwap_pullback_v2`), which must
  keep both the dip and the entry in the lower half of the day's range. The
  owner's order of 2026-11-08 set those three frames (5 minute, 15 minute and
  1 hour) and withdrew the 1 day frame and its daily file.
- **One configuration surface**: [src/config.py](src/config.py) holds the
  target, the coverage floor, the Kalman and VWAP parameters, the pullback
  window, the scan cadence and the paper/live switch. Paper is the default;
  live is off.
- **One daily trade state**: [src/signals/trade_state.py](src/signals/trade_state.py),
  with a hard one-trade-per-day lock that survives a restart.
- **One market clock**: Asia/Karachi UTC+5 forever (SO-8), in
  [src/data/sessions.py](src/data/sessions.py). Bands: Mon to Thu 09:32 to
  15:30, Friday two sessions (09:17 to 12:00 and 14:32 to 16:30) with the
  midday break between them; weekends and PSX holidays closed. `market_phase()`
  answers CLOSED, PRE_OPEN, WARMUP, OPEN, BREAK or POST_CLOSE for every
  consumer, and `market_state_at()` answers the owner's four-state law
  (PRE_MARKET, MARKET, POST_MARKET, CLOSED): the quant never scans outside
  MARKET, and the phone can never show a break as ONLINE.
- **Bars come from the broker tape**, not the dead eClear OHLC servlet:
  [src/data/tape_bars.py](src/data/tape_bars.py) builds one minute of OHLC from
  the tape's own prices and takes volume from the venue's counter.
  [scripts/intraday_pipeline.py](scripts/intraday_pipeline.py) reads the tape
  first, falls back to an on-disk capture, and carries the source label into
  the observation and the phone card.
- **Buy/sell volume is measured, never guessed**:
  [src/data/tick_volume.py](src/data/tick_volume.py) classifies a print by
  where it landed against the tape's own bid and ask, and records what the
  wire cannot say (the side of an off-quote print) as unknown.
- **Honest data states**: a broken, thin, stale or volume-less source reports
  DATA BLOCKED with measured coverage, never a market verdict.
- **The Windows HUD**: [windows/](windows/) is the owner's own console, one Go
  binary with no runtime dependency. Six screens (HOME, ALERTS, ORDER FLOW,
  SCANNER, CHARTS, SETTINGS), the KSE100 tile with the three volume leaders,
  the Orb mark, and a buying-versus-selling bar of ten boxes on every page
  that carries a split. It shows LINK, the FEED's age, PHASE and NEXT, and it
  never draws a number it was not given. The `windows-desktop` workflow builds
  it on a Windows runner; [windows/README.md](windows/README.md) records every
  build.
- **One law for the count**: [src/data/feed_capture.py](src/data/feed_capture.py)
  publishes at most one snapshot a second and never a pair below the highest it
  has already sent for a symbol that day, and [cloud/worker.js](cloud/worker.js)
  clamps the acknowledged frame the same way and refuses to follow a smaller
  total down, so buying and selling volume cannot walk backwards on any
  surface (owner order 2026-11-10).

## How it runs

Everything recurring lives in the cloud and never on the owner's PC (SO-12,
owner order 2026-10-19). Both paths run with this machine switched off.

| | GitHub Actions | Cloudflare relay |
|---|---|---|
| Files | [intraday-session.yml](.github/workflows/intraday-session.yml) (the session loop) and [intraday-capture.yml](.github/workflows/intraday-capture.yml) (band slots, finalize, backstop) | [cloud/worker.js](cloud/worker.js) |
| Carries | the KMIALL scan, the post-close finalize, the observation both the phone card and the paper strategy read | the `/health`, `/signals`, `/market`, `/quotes` and `/prices` endpoints the phone reads |
| Cadence | **every second inside every PSX band** (`config.SCAN_INTERVAL_SECONDS = 1`, owner order 2026-10-19); one cycle costs about 2.9 s, so the loop runs back to back and the achieved rate is its own latency | on every band edge it is triggered for, and on every phone poll |
| Cost | nothing: free runner minutes on a public repository | the free edge tier |
| State | its own forward state on the runner | the `QuoteHub` Durable Object |
| PC off | yes | yes |

One scan serves both readers: the same run, observation and data-quality
report feed the phone card and the intraday paper strategy, so there is no
second, cheaper scan for the app.

Backtesting runs on Actions minutes by the owner's 2026-10-19 order, not on
the PC; the declared backtest entry points each call `guard_cloud_backtest`,
which refuses them outside a GitHub Actions job.

The old local runners are refused in code: the entry points call
`guard_owner_requested` from [src/ci/local_only.py](src/ci/local_only.py),
which passes inside Actions and refuses anywhere else. A local run the owner
asks for is enabled per process, in the shell that runs it:

```bash
QOR_OWNER_REQUESTED_LOCAL_RUN=scripts/kmiall_tick.py python scripts/kmiall_tick.py --status
```

## The phone app

`android/` is the companion console: v1.9.13 (versionCode 54), the owner's own
faces and palette, built with aapt2 and D8, no Gradle. It shows the status
pill with the relay's own phase sentence, the latest signal, and the market
card (KSE100 points and percentage, then the three volume leaders with their
counted buy/sell/total volumes). Search finds any symbol and shows a row that
re-styles in place every second while the panel is open: price, the day's
percent move in green or red, and the pinned tap answer, with a 30 second
staleness threshold that anything older is flagged against. It polls the edge
every second while the relay reports the market open, every 30 seconds when it
does not, and the broker-backed card on every live round; the status beacon
breathes only while a session is live, and the app never derives a session
from its own clock. See [android/README.md](android/README.md).

## Charts of Rehan

`charts/` is a standard-library Python service and `web/` its React and
TypeScript front end: candles, volume, measured missing minutes and the
exchange's session clock, drawn only from bars this project can name. It is a
foreground tool and nothing else: no schedule, daemon, watcher or autostart,
it refuses to start inside GitHub Actions, and it binds loopback unless the
operator says otherwise. `python examples/charts_demo.py` runs the whole
pipeline offline, `python -m charts --source tape --port 8788` serves real
bars on loopback, and `cd web && npm run dev` runs the UI with hot reload.
Full detail in [charts/README.md](charts/README.md) and
[web/README.md](web/README.md).

## Layout

```
src/config.py                     the ONE configuration surface
src/signals/momentum_scanner.py   the ONE scanner (ICT/SMC gates, one winner)
src/signals/smc.py                sweep, market structure shift, FVG retest
src/signals/trade_state.py        the persisted daily state and trade lock
src/signals/contracts.py          the typed boundary: models, faults, ingest guard
src/data/sessions.py              Karachi-pinned clock, session law, owner texts
src/data/tape_bars.py             intraday bars from the tape
src/data/feed_capture.py          the broker tick tape (banked once a live session)
src/data/tick_volume.py           buy/sell/total volume split from the tape
src/data/live_card.py             the live card the relay serves to the app
src/data/market_snapshot.py       KSE100 and the KMIALL volume leaders
src/ci/local_only.py              the guards that keep runtime work in the cloud
src/ci/budget.py                  adaptive Actions budget for a cycle
src/notify/owner_email.py         owner email over GitHub notification mail
scripts/intraday_pipeline.py      the orchestrator (scan, finalize, card, archive)
scripts/scan_loop.py              supervised interval scan loop (cloud runner)
scripts/land.sh                   stage, validate and land one change through a PR
scripts/check_governance.py       secret, style, identity and SO-8 enforcement
cloud/worker.js                   Cloudflare relay and edge crons (Karachi math)
src/data/quote_flow.py            wire-side buy/sell separation and its law
windows/                          the Windows console HUD (Go, one exe)
windows/README.md                 the HUD build record, one bullet per build
windows-desktop.yml               builds the HUD on a Windows runner
android/                          companion app source
data/                             gitignored: datasets, journals, forward state
legacy/                           quarantined code from the deleted sentinel repos
```

## Standing orders (full text in [GOVERNANCE.md](GOVERNANCE.md))

1. **SO-1 Signal-only.** No order is ever placed, modified or cancelled.
2. **SO-2 / SO-6 Pull request first.** Every change lands as a PR that the
   agent opens and merges, never a direct push; `scripts/land.sh` does that
   flow.
3. **SO-3 Never fabricate data.** Coverage, prices, volume and verdicts are
   measured results only, never invented.
4. **SO-4 Backtests never on the owner's PC.** The owner's 2026-10-19 order
   moved all compute to Actions minutes; `guard_cloud_backtest` refuses every
   declared backtest entry point outside CI.
5. **SO-5 Secrets never enter the repo**, a log line or a message.
6. **SO-7 Sole human author, human style.** Every commit is authored by
   Mr. Rehan and em dashes are banned from commits and files.
7. **SO-7a No agent attribution.** No commit, PR body or merge carries a
   co-author trailer, generated-by footer or signature (owner order 2026-11-08).
8. **SO-8 Karachi time forever.** UTC+5, hardcoded, no other zone.
9. **SO-9 Owner notifications** at open and close, through the relay.
10. **SO-12 / SO-13 Cloud cadence.** The one-second scan runs on Actions
    minutes and the Cloudflare relay, with the owner's PC switched off.

## Checks and commands

```bash
# the same checks CI runs (validation belongs in Actions, SO-21)
python scripts/check_governance.py
python -m unittest discover -s tests

# is the system working? one command, honest verdict
python scripts/verify_market_signals.py          # config, universe, state, AI, scheduler
python scripts/verify_market_signals.py --live   # also dial the relay and read the cards

# the scheduled cycle by hand (paper only, no orders)
python scripts/intraday_pipeline.py --scan --slot 10:00
python scripts/intraday_pipeline.py --finalize
```

## Documentation

- [GOVERNANCE.md](GOVERNANCE.md): the standing orders, in full.
- [MARKET_SCHEDULING.md](MARKET_SCHEDULING.md): the session law, the four
  states and the cadence decisions behind them.
- [DATA_SOURCING.md](DATA_SOURCING.md): every input, what is measured versus
  inferred, and what happens when a source goes quiet.
- [INTRADAY_FORWARD_SYSTEM.md](INTRADAY_FORWARD_SYSTEM.md): candidate
  registration, promotion and demotion rules, source checks, limitations.
- [RESEARCH_FINAL_AUDIT.md](RESEARCH_FINAL_AUDIT.md): the research results,
  the data limitations and the signal status.
- [DASHBOARD_ARCHITECTURE.md](DASHBOARD_ARCHITECTURE.md): the private console
  design on the owner's broker feed, with the measured capability matrix that
  decides what a footprint view may claim.
- [PROJECT_REPORT.md](PROJECT_REPORT.md): the long-form build record.
- [android/README.md](android/README.md), [charts/README.md](charts/README.md),
  [cloud/README.md](cloud/README.md): the three components in full.

## Status, 2026-11-10

- **Suite green**: every pull request runs `governance-guard` (the governance
  check, the whole unit suite, the worker's JavaScript) and the HUD's own
  `build` job, and it merges only when all of them pass.
- **Every change lands as a pull request**: `scripts/land.sh` opens it, waits
  on the checks and merges with a merge commit. The owner's approval is
  standing (SO-24); the checks are never waived.
- **Signal-only and paper only**: live trading is disabled, and the paper gate
  needs genuinely accumulated forward sessions before it opens.
- **Versions**: the HUD is v3.3.2 and the phone app v4.0.20.
