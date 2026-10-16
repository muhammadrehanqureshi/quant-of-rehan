# Quant of Rehan

![Quant of Rehan](assets/quant-of-rehan-logo.png)

**Private, signal-only intraday research platform for PSX KMIALL stocks.**
No order placement, no broker trading integration: signals and research only.
Owner and sole human contributor: Rehan (muhammadrehanqureshi).

The strategy in one paragraph: scan the current KMIALL universe. For each symbol
score the last five minutes of price change, whether it is accelerating, the
latest bucket's volume against the session's median, whether that volume is
still growing, and traded value as a liquidity screen; penalise anything that
has already run too far or is drifting off its session high, because those are
late. Gate on market context: if the universe is not broadly advancing there is
no trade. Take the single highest score above the minimum, let the AI prior
break a near-tie or refuse a disliked candidate, enter on paper at the observed
price, target entry x 1.02, and lock the day.

## What is true today

- **One scanner**: [src/signals/momentum_scanner.py](src/signals/momentum_scanner.py)
  returns exactly one winner, NO TRADE, or DATA BLOCKED, and is gated on market
  context and a late-move decay. The old opening-range library and the FVG /
  sweep engine are retired from the trading path.
- **One configuration surface**: [src/config.py](src/config.py) holds the
  target, the coverage floor, the weights, the AI routing, the scan cadence and
  the paper/live switch. Paper is the default; live is off.
- **One daily trade state**: [src/signals/trade_state.py](src/signals/trade_state.py),
  with a hard one-trade-per-day lock that survives a restart.
- **One market clock**: Asia/Karachi UTC+5 forever (SO-8), in
  [src/data/sessions.py](src/data/sessions.py). Bands: Mon to Thu 09:32 to
  15:30, Friday two sessions (09:17 to 12:00 and 14:32 to 16:30) with the midday
  break between them; weekends and PSX holidays closed. `market_phase()`
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
- **The AI prior** ([src/signals/ai_model.py](src/signals/ai_model.py)) is a
  confirmation prior on the winner, never the decider.
- **Honest data states**: a broken, thin, stale or volume-less source reports
  DATA BLOCKED with measured coverage, never a market verdict.

## How it runs

The schedule lives in the cloud and never on the owner's PC (SO-12, owner order
2026-10-14). Both paths run with this machine switched off.

| | GitHub Actions | Cloudflare relay |
|---|---|---|
| Files | [intraday-session.yml](.github/workflows/intraday-session.yml) (the session loop) and [intraday-capture.yml](.github/workflows/intraday-capture.yml) (band slots, finalize, backstop) | [cloud/worker.js](cloud/worker.js) |
| Carries | the KMIALL scan, the post-close finalize, the observation both the phone card and the paper strategy read | the open and close texts, and the `/health`, `/signals` and `/market` endpoints the phone reads |
| Cadence | **every 30 seconds inside every PSX band** (`config.SCAN_INTERVAL_SECONDS = 30`, SO-13); per-slot fires at 10:00, 11:30, 13:00, 14:30 and Friday 16:00 stay as the backstop | on every band edge it is triggered for, and on every phone poll |
| Cost | nothing: free runner minutes on a public repository, about 2.9s of a 30s slot | the free edge tier |
| State | its own forward state on the runner | `RELAY_KV` |
| PC off | yes | yes |

One scan serves both readers: the same run, observation and data-quality report
feed the phone card and the intraday paper strategy, so there is no second,
cheaper scan for the app. The scan is that dense only because the session loop
keeps the read-only recorder alive for the whole band, so a cycle measures a
tape that already exists instead of fetching one. `config.TICK_INTERVAL_MINUTES
= 4` and its warm-up rule still govern the local tick the owner can ask for as a
local trial; the two are different runners, never two cadences for one runner.

The local runners are retired and refused in code. `scripts/kmiall_tick.py`,
`scripts/scan_loop.py`, `src/notify/schedule_runner.py` and the two installers
all call `guard_owner_requested` from [src/ci/local_only.py](src/ci/local_only.py),
which refuses a real process on this PC with SO-12's reason and passes straight
through inside GitHub Actions; the Windows task is disabled and the Startup
entry is gone. Inspecting and removing stay open always
(`python scripts/install_kmiall_tick.py --show` / `--remove`), and a local run
the owner asks for is enabled per process, in the shell that runs it:

```bash
QOR_OWNER_REQUESTED_LOCAL_RUN=scripts/kmiall_tick.py python scripts/kmiall_tick.py --status
```

Backtesting stays local for the mirror-image reason (SO-4): its entry points
refuse to run in CI.

## The AI prior, exactly

"AI-driven signals" means one concrete, auditable thing:
`P(price touches +2.00% before -0.50%, within 10 sessions)`, an L2 logistic
regression fitted in numpy from 19 causal daily features known at the decision
bar, trained by [scripts/train_signal_model.py](scripts/train_signal_model.py)
on the frozen event study, and written to `models/kmiall_signal_v1.json` with
its own provenance. Three properties keep it honest: the live featurizer is
asserted against the research table before every training run; it fails closed
on a missing, corrupt or feature-mismatched artifact; and it is wired in as the
weak lever it is. The current artifact scored holdout AUC 0.5615 on 179,872 rows
against a 20.5% base rate, so a near-tie at the top (rule scores within
`AI_TIE_BAND`) may be reordered, and the veto (`AI_GATE_ENABLED`, off by
default) may refuse only the model's own weakest `AI_REJECT_PERCENTILE`. It can
refuse a candidate; it can never create or upgrade one. Retrain with
`python scripts/train_signal_model.py` (`--check-only` for the featurizer
equivalence test alone); it refuses to overwrite a good artifact with an
unevaluated one.

## The phone app

`android/` is the companion console: version 1.7.3 (versionCode 27), the owner's
own faces and palette, built with aapt2 and D8, no Gradle. It shows the status
pill with the relay's own phase sentence, the latest signal, and the market
card (KSE100 points and percentage, then the three volume leaders with their
counted buy/sell/total volumes). It polls `/health` and `/signals` on the edge
every second while the relay reports the market open, every 30 seconds when it
does not, and the exchange-backed card every 30 live rounds; the status beacon
breathes only while a session is live, and the app never derives a session from
its own clock. See [android/README.md](android/README.md).

## Charts of Rehan

`charts/` is a standard-library Python service and `web/` its React and
TypeScript front end: candles, volume, measured missing minutes and the
exchange's session clock, drawn only from bars this project can name. It is a
foreground tool and nothing else: no schedule, daemon, watcher or autostart, it
refuses to start inside GitHub Actions, and it binds loopback unless the
operator says otherwise. `python examples/charts_demo.py` runs the whole
pipeline offline, `python -m charts --source tape --port 8788` serves real bars
on loopback, and `cd web && npm run dev` runs the UI with hot reload. Full
detail in [charts/README.md](charts/README.md) and
[web/README.md](web/README.md).

## Layout

```
src/config.py                     the ONE configuration surface
src/signals/momentum_scanner.py   the ONE scanner
src/signals/ai_model.py           the trained daily prior and its featurizer
src/signals/trade_state.py        the persisted daily state and trade lock
src/signals/contracts.py          the typed boundary: models, faults, ingest guard
src/data/sessions.py              Karachi-pinned clock, session law, owner texts
src/data/tape_bars.py             intraday bars from the tape
src/data/feed_capture.py          the broker tick tape (banked once a live session)
src/data/tick_volume.py           buy/sell/total volume split from the tape
src/data/live_card.py             the live card the relay serves to the app
src/data/market_snapshot.py       KSE100 and the KMIALL volume leaders
src/ci/budget.py                  adaptive Actions budget for a cycle
src/notify/telegram.py            env-driven notifier (fails closed)
scripts/intraday_pipeline.py      the orchestrator (scan, finalize, card, archive)
scripts/scan_loop.py              supervised interval scan loop (cloud runner)
scripts/land.sh                   stage, validate and land one change through a PR
scripts/check_governance.py       secret, style, identity and SO-8 enforcement
scripts/train_signal_model.py     trains and validates the AI prior
scripts/verify_market_signals.py  end to end verdict: config, tests, relay, state, AI
cloud/worker.js                   Cloudflare relay and edge crons (Karachi math)
android/                          companion app source
models/kmiall_signal_v1.json      the trained AI prior with its holdout metrics
data/                             gitignored: datasets, journals, forward state
legacy/                           quarantined code from the deleted sentinel repos
```

## Standing orders (full text in [GOVERNANCE.md](GOVERNANCE.md))

1. **SO-1 Signal-only.** No order is ever placed, modified or cancelled.
2. **SO-2 / SO-6 Pull request first.** Every change lands as a PR that the
   agent opens and merges, never a direct push; `scripts/land.sh` does that flow.
3. **SO-3 Never fabricate data.** Missing footprint or order flow is labelled
   UNAVAILABLE, never invented.
4. **SO-4 Backtests local only.** No backtest, walk-forward or grid in CI.
5. **SO-5 Secrets never enter the repo**, a log line or a message.
6. **SO-7 Sole human author, human style.** Every commit is authored by
   Mr. Rehan and em dashes are banned from commits and files.
7. **SO-7a The agent is the co-author.** Every commit, PR body and merge
   carries `Co-Authored-By: Codebuff <noreply@codebuff.com>`; `scripts/land.sh`
   appends it and `scripts/check_governance.py` requires it.
8. **SO-8 Karachi time forever.** UTC+5, hardcoded, no other zone.
9. **SO-9 Owner notifications** at open and close, through the relay.
10. **SO-12 / SO-13 Cloud cadence.** The 30-second scan runs on Actions
    minutes and the Cloudflare relay, with the owner's PC switched off.

## Checks and commands

```bash
# the same checks CI runs
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
- [RESEARCH_FINAL_AUDIT.md](RESEARCH_FINAL_AUDIT.md): the research results, the
  data limitations and the signal status.
- [DASHBOARD_ARCHITECTURE.md](DASHBOARD_ARCHITECTURE.md): the private console
  design on the owner's broker feed, with the measured capability matrix that
  decides what a footprint view may claim.
- [PROJECT_REPORT.md](PROJECT_REPORT.md): the long-form build record.
- [android/README.md](android/README.md), [charts/README.md](charts/README.md),
  [cloud/README.md](cloud/README.md): the three components in full.

## Status, 2026-10-16

- **Suite green**: `python -m unittest discover -s tests` reports
  `Ran 1117 tests`, OK. The suite leaves every live file byte-identical.
- **Every change lands as a pull request**: the `governance-guard` workflow must
  pass (governance check, the whole unit suite, the worker's JavaScript syntax)
  before the agent merges with a merge commit.
- **Signal-only and paper only**: live trading is disabled, and the paper gate
  needs genuinely accumulated forward sessions before it opens.
- **Known limitation**: the AI prior's daily panel lags by a few sessions, and
  it is disclosed in every observation as `prior_panel_as_of` rather than
  hidden.
