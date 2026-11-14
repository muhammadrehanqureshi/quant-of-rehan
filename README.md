<p align="center">
  <img src="assets/QoR.png" alt="Quant of Rehan" width="340" />
</p>

<h1 align="center">Quant of Rehan</h1>

<p align="center"><sub><code>assets/QoR.png</code> is the project's official mark: the owner's own picture, 2048 by 2048, and the same bytes are pinned as <code>windows/assets/icon-source.png</code>, so the README and the console's own icon carry one image (owner order 2026-11-12).</sub></p>

[![Governance Guard](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/governance-guard.yml/badge.svg)](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/governance-guard.yml)
[![Android App](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/android-apk.yml/badge.svg)](https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/workflows/android-apk.yml)

**Private, signal-only intraday research platform for PSX KMIALL stocks.**
No order placement, no broker trading integration: signals and research only.

## Contributors

| Name | Role |
|---|---|
| [Mr. Rehan](https://github.com/muhammadrehanqureshi) | Owner and sole human author (SO-7). Decision authority for every rule in [GOVERNANCE.md](GOVERNANCE.md). |

## The strategy in one paragraph

Scan the current KMIALL universe for one setup, the one the owner named: the
Kalman Trend with VWAP on the 5 minute, 15 minute and 1 hour charts and the
hybrid statistical arbitrage and mean reversion model. The one minute Kalman
trend must be up and the 5 minute frame's Kalman state must have turned up.
The mean reversion half asks the last close to sit at least `HYBRID_Z_MIN`
standard deviations below the 15 minute frame's own VWAP, measured against
that frame's own dispersion so a quiet scrip needs a smaller move than a
violent one. The statistical arbitrage half asks the name to be lagging the
scan's equal weight market leg by `HYBRID_LAG_MIN_PCT`, which is the cheap
side of the pair: the law buys a stretched laggard on the reversion, never a
leader it is chasing. The plan is the owner's law either way: paper entry at
the last completed close, stop at entry minus 1%, target at entry plus 2%,
one call a day, and no trade after a broad selloff. A candidate only exists
on completed minutes; there is no momentum fallback, no RSI fallback and no
second strategy. Entry and exit intent only: nothing reaches a broker (SO-1).

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

- **One scanner, one strategy**: [src/signals/momentum_scanner.py](src/signals/momentum_scanner.py)
  returns exactly one confirmed long under the one running law, NO TRADE, or
  DATA BLOCKED, with market context gating and late-entry refusal instead of
  any fallback signal.
- **The one strategy**: [src/signals/hybrid_arb_mr.py](src/signals/hybrid_arb_mr.py)
  is the running law (`kalman_vwap_hybrid_sa_mr_v1`, owner order 2026-11-12):
  the Kalman Trend with VWAP on the 5 minute, 15 minute and 1 hour charts and a
  hybrid statistical arbitrage and mean reversion model. It calls a name
  stretched at least `HYBRID_Z_MIN` standard deviations below the 15 minute
  frame's VWAP while the 5 minute frame's Kalman state has turned up and the
  name lags the scan's own equal weight market leg, the cheap side of the pair.
  The owner's order of 2026-11-12 removed every previous strategy: the fresh
  one minute flip, the three frame VWAP pullback and the relative strength
  gate are gone from the tree, `kalman_trend.py` builds no entry from them, and
  only the market leg measurement survives ([src/signals/market_leg.py](src/signals/market_leg.py))
  because the running law reads it. The owner's order of 2026-11-08 set the
  three frames (5 minute, 15 minute and 1 hour) and withdrew the 1 day frame
  and its daily file.
- **One configuration surface**: [src/config.py](src/config.py) holds the
  target, the coverage floor, the Kalman and VWAP parameters, the hybrid
  thresholds (`HYBRID_Z_MIN`, `HYBRID_LAG_MIN_PCT` and the two frame choices),
  the market leg minimum, the scan cadence and the paper/live switch. Paper
  is the default; live is off.
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
  binary with no runtime dependency. Five screens (HOME, ALERTS, ORDER FLOW,
  SCANNER, SETTINGS), the KSE100 tile with the three volume leaders,
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

## The five year intraday archive

`data/history/` holds 5m, 15m, 30m, 1h and 1D bars for every KMIALL scrip back
to 2021-11-15, so a strategy can be tested on real bars instead of
forward-captured sessions. The source is the SCS Trade chart datafeed, which
is free and unauthenticated and carries volume on every bar; the broker's own
OHLC servlet serves only the current session, so it cannot backfill. See
[DATA_SOURCING.md](DATA_SOURCING.md) section 3b for the measured endpoints.

The archive is gitignored and never committed. Build one year (or all of them)
in Actions, then read it with the loader:

```bash
gh workflow run intraday-history.yml -f years='[2021,2022,2023,2024,2025,2026]'
python -c "from src.data.intraday_history import load; print(load('5m', years=[2025]).head())"
```

Each parquet partition carries `symbol, ts, open, high, low, close, volume,
regular`. `regular` is true only inside the exchange's trading bands; the
pre-open auction and post-close bars are kept and flagged. A 1D row is stamped
at 00:00 Karachi on its session date and aggregates that date's regular-session
5m bars, so the daily open, high, low, close and volume are the exchange day's
values; the auction and post-close rows stay in the intraday frames. Prices are
as traded, with no split or bonus adjustment, and
`regular_only=True` filters an intraday study to the session. The archive
workflow's `verify` job reproduces 1D/15m/30m/60m from 5m and fails on any
row, stamp or value mismatch before the data is used.

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

### Monday morning

The first fire on a trading Monday is **08:55 PKT (03:55 UTC)**, twenty
minutes before the exchange's 09:15 pre-open. The warm-up gate starts the
recorder and the session loop at 08:55; the loop's own gate holds scanning
until the pre-open opens, and the first pre-market print is captured. Friday
keeps the same 08:55 start, five minutes before its 09:00 pre-open.

The same start is hardcoded in `src/data/sessions.py`, `session_gate.py`,
`cloud/worker.js`, `intraday-session.yml` and the Windows HUD. The 08:45
readiness job checks the relay; the 09:20 job checks that frames are already
stored. A green 08:55 run that is still in progress at 09:15 is the healthy
shape, not a late job.

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

`android/` is the companion console: v4.3.8 (versionCode 131), the owner's own
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
src/signals/momentum_scanner.py   the ONE scanner (one law, one winner)
src/signals/hybrid_arb_mr.py       the ONE strategy: Kalman, three VWAP frames, hybrid stat arb and mean reversion
src/signals/kalman_trend.py       the causal trend clock and the one entry builder
src/signals/mtf_vwap.py           the 5 minute, 15 minute and 1 hour VWAP frames
src/signals/market_leg.py         the scan's measured equal weight market leg
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
- [RUNBOOK.md](RUNBOOK.md): the before-open checks, the hand-start commands and
  what to do when the feed or relay stops.
- [PROJECT_REPORT.md](PROJECT_REPORT.md): the long-form build record.
- [android/README.md](android/README.md), [charts/README.md](charts/README.md),
  [cloud/README.md](cloud/README.md): the three components in full.

## Status, 2026-11-14

- **One strategy only**: the fresh one minute flip, the three frame VWAP
  pullback and the relative strength strategy were removed on the owner's
  order of 2026-11-12. The only entry law is the Kalman Trend with the three
  VWAP frames and the hybrid statistical arbitrage and mean reversion model
  (`kalman_vwap_hybrid_sa_mr_v1`), and the scan now always reads its frames.
- **Suite green**: every pull request runs `governance-guard` (the governance
  check, the whole unit suite, the worker's JavaScript) and the HUD's own
  `build` job, and it merges only when all of them pass.
- **Every change lands as a pull request**: `scripts/land.sh` opens it, waits
  on the checks and merges with a merge commit. The owner's approval is
  standing (SO-24); the checks are never waived.
- **Signal-only and paper only**: live trading is disabled, and the paper gate
  needs genuinely accumulated forward sessions before it opens.
- **Versions**: the HUD is v3.5.10 (build 111) and the phone app v4.3.8.
