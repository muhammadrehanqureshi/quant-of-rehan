# Quant of Rehan

![Quant of Rehan](assets/quant-of-rehan-logo.png)

**Private, signal-only quantitative research platform for PSX KMIALL stocks.**
No order placement. No broker integration for trading. Signals and research
only. Sole contributor and owner: Rehan (muhammadrehanqureshi).

## What is running today

Rebuilt 2026-10-09 and extended 2026-10-10 around one simple strategy: the
fastest current KMIALL momentum plus volume acceleration, one trade a day,
+2% target, plus one trained daily prior that can only ever refuse a candidate.

- **One authoritative scanner**: [src/signals/momentum_scanner.py](src/signals/momentum_scanner.py).
  It scores every eligible KMIALL symbol on fast momentum, momentum
  acceleration, relative volume, volume acceleration and liquidity, applies a
  market-context gate and a late-move decay, and returns exactly one winner,
  NO TRADE, or DATA BLOCKED. The old opening-range library and the FVG / sweep
  daily engine are retired from the trading path.
- **One daily trade state**: [src/signals/trade_state.py](src/signals/trade_state.py).
  A persisted state machine with a hard one-trade-per-day lock that survives a
  process or runner restart, plus the tick bookkeeping that makes the local
  4-minute runner idempotent.
- **One configuration file**: [src/config.py](src/config.py) holds the target,
  the coverage floor, the score weights, the AI routing rules, the tick cadence
  and the live-trading switch. Live trading is disabled and paper mode is the
  default.
- **One market clock**: Asia/Karachi UTC+5 forever (SO-8) in
  [src/data/sessions.py](src/data/sessions.py), with the owner's session law
  expressed as bands: Mon-Thu one session 09:32 to 15:30, Friday TWO sessions
  (09:17 to 12:00 and 14:32 to 16:30) with the exchange's midday break between
  them, and weekends plus PSX holidays closed. `market_phase()` answers
  CLOSED, PRE_OPEN, WARMUP, OPEN, BREAK or POST_CLOSE, and every consumer
  (the 4-minute runners, the scanner guard, the Cloudflare relay, the phone
  app) renders that one answer, so the app cannot call a break ONLINE.
  Beside the phases sits the owner's four-state law of 2026-10-11:
  `market_state_at()` answers PRE_MARKET (09:00 to 09:15), MARKET (every
  band), POST_MARKET (15:32 to 15:49, Friday 16:32 to 16:49) or CLOSED,
  with half-open edges so an instant exactly on a boundary belongs to the
  window that starts there. `is_scan_window()` is true only in MARKET: the
  owner's standing order is that the quant never scans pre-market or
  post-market, and the 4-minute cadence below is the standing scan timing.
- **One trained AI prior**: [src/signals/ai_model.py](src/signals/ai_model.py),
  described in full below. It is a confirmation prior on the scanner's winner,
  never the decider.
- **Honest data states**: a broken, thin, stale or volume-less source reports
  SCAN BLOCKED with measured coverage and never a market verdict. See
  [DATA_SOURCING.md](DATA_SOURCING.md) and
  [INTRADAY_FORWARD_SYSTEM.md](INTRADAY_FORWARD_SYSTEM.md).
- **The phone card** (Android `android/`, v1.6.1 APK built and signed today,
  `QuantOfRehan-v1.6.1.apk` on the OneDrive Desktop; the main screen also
  states "Quant is scanning the market every 4 minutes."):
  KSE100 points and percentage, then the day's top three KMIALL stocks by
  volume with each one's percentage change and its buy/sell/total volume
  (`B=`,`S=`,`T=`) when a genuine split exists, from the PSX Data Portal
  through the relay, plus the OFFLINE pill and a sentence explaining which
  phase the exchange is in.
- **Android companion app** (`android/`): logo-branded dark console showing
  whether the quant is working, the latest signal, and the market right now
  (KSE100 points and percentage plus the day's top three KMIALL stocks by
  volume, from the PSX Data Portal through the relay). Polls `/health`,
  `/signals` and `/market` on the edge every 5 minutes, survives reboot, and
  shows OFFLINE with a red cross whenever the session is closed.

## Two runners, deliberately

The same orchestrator is driven from two places. They write their own local
state and both archive to the relay, so one can fail without silencing the
other.

There is also a third, portable way to drive it: [scripts/scan_loop.py](scripts/scan_loop.py),
a supervised interval loop for hosts where Task Scheduler does not exist (a
Linux VM, a container, a laptop run in the foreground). It owns the schedule,
the pause windows, the backoff and the health file, and delegates every scan to
the same orchestrator, so the slot guard and the one-trade lock are identical.
On this PC the scheduled tick stays the primary runner: a loop dies with the
shell that started it, and this project has already lost a running loop to a
desktop restart.

| | GitHub Actions | Local 4-minute tick |
|---|---|---|
| File | [.github/workflows/intraday-capture.yml](.github/workflows/intraday-capture.yml) | [scripts/kmiall_tick.py](scripts/kmiall_tick.py) |
| Cadence | 5 scans a day (10:00, 11:30, 13:00, 14:30, and 16:00 on Friday) plus a post-close finalize | every 4 minutes all day, scanning only in MARKET and pausing itself in every other state |
| Why it exists | runs without the owner's PC | sees the whole session, not four snapshots of it |
| Cost | about 1,300 runner minutes a month, inside the 2,000 minute ceiling | nothing but a few seconds of CPU per tick |
| State | its own forward state on the runner | `data/forward/` in this checkout |

Why a tick script plus Windows Task Scheduler, and not an in-process loop: a
loop dies with the shell that started it. This project has already lost a
running loop to a desktop restart, and a session that silently stops being
scanned is the exact failure the design exists to prevent. Task Scheduler
survives logoff, sleep and reboot, needs no terminal open, and keeps its own
run history. Everything that needs judgement, meaning whether the market is
open, whether this slot was already scanned, whether the capture worked and
whether it is time to finalize, lives in the tick script where it is tested.

The local tick refuses to run outside the session, never scans the
pre-market or post-market windows (owner order 2026-10-11; post-market is
finalize-only), refuses to run during the first 20 minutes after the open
(the strategy needs 20 bars and three volume buckets before it can score
anything), scans each 4-minute slot at most once,
holds a lock so two ticks cannot fight over the state file, reclaims a stale
lock left by a crashed tick, alerts once after three consecutive capture
failures, and finalizes the day exactly once. Install it with:

```bash
python scripts/install_kmiall_tick.py           # create or replace the task
python scripts/install_kmiall_tick.py --show    # query it
python scripts/install_kmiall_tick.py --remove  # delete it
```

## The AI prior, exactly

"AI-driven signals" in this repository means one concrete, auditable thing:

```
P(price touches +2.00% before it touches -0.50%, within 10 sessions)
```

from 19 causal daily features known at the decision bar (returns over 1, 5, 10
and 20 sessions, overnight gap, 5-session gap, 20-day range, ATR, average
volume, 20 and 60 session highs, 20 session low, above-20-day-average flag,
proximity to the 20 and 60 session highs, relative volume, turnover, and market
return and breadth). It is an L2 logistic regression fitted in numpy, trained
by [scripts/train_signal_model.py](scripts/train_signal_model.py) on the frozen
event study in `data/event_study/events.parquet`, and written to
`models/kmiall_signal_v1.json` as a readable coefficient vector with its own
provenance.

Three properties make it trustworthy rather than decorative:

1. **One feature definition.** The live featurizer in `ai_model.panel_features`
   is asserted against the research table before every training run. If the two
   ever drift, training refuses to produce an artifact. The last run reported
   0.00% disagreement across 500 sampled rows.
2. **It fails closed.** A missing, corrupt, feature-mismatched or ineligible
   artifact disables the prior and says why. A feature row with too many
   missing inputs yields no probability, never an imputed guess.
3. **It is weak, and it is wired in as weak.** The current artifact was trained
   on 98,374 rows before 2024, validated on 179,872 rows after it, and scored
   holdout AUC 0.5615 against a 20.5% base rate with a top-decile rate of 23.7%.
   That is a real but small edge, so the prior is a *bounded* lever:

   - every candidate carries its `ai_probability` and `ai_percentile`, both
     recorded in the observation;
   - a near-tie at the top (rule scores within `AI_TIE_BAND`, default 2 points)
     may be reordered by the prior. A clear rule win is never overturned;
   - the veto (`AI_GATE_ENABLED`, off by default) refuses only the weakest
     `AI_REJECT_PERCENTILE` (default 25%) of the model's own ranking for the
     day. It can refuse a candidate. It can never create or upgrade one;
   - with the veto off, the AI component cannot change what is traded at all,
     it only annotates the record.

Retrain any time the panel grows; the command refuses to overwrite a good
artifact with an unevaluated one:

```bash
python scripts/train_signal_model.py              # train, evaluate, write
python scripts/train_signal_model.py --check-only # featurizer equivalence only
```

## Standing Orders (hardcoded, see [GOVERNANCE.md](GOVERNANCE.md))

1. **Signal-only.** The bot never places, modifies, or cancels any order.
2. **Pull request first, merged to `master` by the agent.** No direct pushes.
3. **Never fabricate data.** Missing footprint/order-flow is labeled
   UNAVAILABLE, never invented.
4. **Backtest locally only.** No backtest, walk-forward or grid ever runs
   in CI. The one cloud exception (SO-10, owner approved): the daily
   post-close signal job on GitHub Actions fetches a bounded trailing EOD
   window and pushes the verdict; full-history crawls stay on the PC.
5. **Secrets never enter the repo.** Desktop files and worker bindings only.
6. **Sole contributor, human style (SO-7).** Every commit is authored by
   Mr. Rehan. Em dashes are banned from commits and files. `legacy/` is
   quarantined reference material from the deleted sentinel repos.
7. **Karachi time forever (SO-8).** UTC+5, hardcoded, no other zone.
8. **Owner notifications (SO-9).** "Quant is online now." at open;
   "Quant is sleeping now." at close, through the Cloudflare relay.

## Layout

```
src/config.py                     the ONE configuration surface (target, floors, weights, AI routing)
src/signals/momentum_scanner.py   the ONE scanner (momentum + volume + acceleration)
src/signals/ai_model.py           the ONE trained daily prior and its featurizer
src/signals/trade_state.py        the ONE persisted daily state, trade lock and tick bookkeeping
src/signals/contracts.py          the typed boundary: validated models, fault taxonomy, ingestion guard
src/signals/volatility.py         volatility regime and edge cases (measured, picks nothing, off by default)
scripts/intraday_pipeline.py      the orchestrator (scan, finalize, card, archive)
scripts/kmiall_tick.py            the local 4-minute tick (pause, guard, lock, capture, finalize)
examples/market_state_walk.py     the owner's four market states, walked edge by edge
scripts/scan_loop.py              supervised interval scan loop (portable alternative to the task)
examples/scan_once.py             one scan by hand, printing every layer of the decision path
scripts/install_kmiall_tick.py    registers the Windows scheduled task
scripts/train_signal_model.py     trains and validates the AI prior
scripts/verify_market_signals.py  end to end verification: config, tests, relay, state, AI, scheduler
scripts/dead_code_audit.py        evidence-based dead code report (modules, defs, imports)
scripts/check_governance.py       secret, style, identity and SO-8 enforcement
src/data/sessions.py              Karachi-pinned clock, session law, owner texts
src/data/ohlc_poller.py           the intraday source poller (one complete bar pass)
src/data/universe_refresh.py      KMIALL drift check: tracked snapshot vs the live exchange table
src/data/market_snapshot.py       KSE100 + KMIALL volume leaders (app card)
scripts/entry_metrics.py          MAE/MFE, time-to-target and horizon study (local only)
scripts/condition_scan.py         per-condition lift table over the event study
scripts/event_study.py            builds the frozen daily event study and its labels
scripts/walk_forward_check.py     chronological persistence check on the study
src/backtest/engine.py            TP/SL engine (conservative fills, invalid screen)src/backtest/walkforward.py      rolling-origin folds + leakage assertions
src/ci/budget.py                  adaptive Actions budget: the scan interval left in the cycle
src/ci/budget_orchestrator.py     the scheduler as a CLI: report or JSON plan for a cycle
src/notify/telegram.py            env-driven notifier (fail closed)
src/notify/schedule_runner.py     local open/close notifier with journal
src/signals/engine.py             retired daily research engine (feeds the EOD push, not the intraday path)
src/signals/intraday_engine.py    retired opening-range library (only the frozen research gate reads it)
cloud/worker.js                   Cloudflare relay + edge crons (Karachi math)
cloud/pair.py                     deploy + pair + test from the owner's PC
android/                          companion app source (signals + status on phone)
models/kmiall_signal_v1.json      the trained AI prior with its holdout metrics
data/                             gitignored: datasets, journals, forward state, relay url
legacy/                           quarantined code from the deleted sentinel repos
```

## Running things locally

```bash
# the same checks CI runs
python scripts/check_governance.py
python -m unittest discover -s tests
python -m pytest tests -q                        # same suite, pytest runner

# how often may the scan run inside the rest of the Actions budget?
python -m src.ci.budget_orchestrator --known-used 1369 --period-end 2026-10-31
python -m src.ci.budget_orchestrator --known-used 398 --json
python examples/budget_plan.py                   # the month, day by day

# is the whole system actually working? (one command, honest verdict)
python scripts/verify_market_signals.py          # config, universe, local state, AI, scheduler
python scripts/verify_market_signals.py --live   # also dial the relay and read the cards
python scripts/verify_market_signals.py --all    # add the test suite

# the scheduled cycle by hand (paper only, no orders)
python scripts/intraday_pipeline.py --scan --slot 10:00
python scripts/intraday_pipeline.py --finalize

# the local 4-minute runner
python scripts/kmiall_tick.py --status           # where are we right now
python scripts/kmiall_tick.py                    # one tick, what the task runs
python scripts/kmiall_tick.py --force            # ignore the slot and finalize guards

# the supervised loop (same orchestrator, owns its own cadence)
python scripts/scan_loop.py --once --skip-capture  # one cycle, no capture
python scripts/scan_loop.py --loop --interval 240  # run until stopped (4 minutes)
python scripts/scan_loop.py --dry-run --loop       # decide and log, never scan
python scripts/scan_loop.py --status               # phase, window and loop health

# one scan by hand, with every layer printed (offline, synthetic if no capture)
python examples/scan_once.py

# the core model driven through market edge cases (volatility spike, thin
# sample, stale feed, limit lock, absent volume, gap open, malformed print).
# Exits 1 on the first violated reading, so it works as a gate.
python examples/deep_scan_stress.py

# the session law and the phase the app will show, right now
python -c "from src.data.sessions import market_state; import json; print(json.dumps(market_state(), indent=2))"

# buy/sell/total volume from banked broker ticks (needs a live-session capture)
python -m src.data.feed_capture --duration 600   # bank ticks (run in a session)
python -m src.data.tick_volume --show OGDC PSO   # inspect the split
python -m src.data.market_snapshot --push        # publish the card to the relay

# the AI prior
python scripts/train_signal_model.py
python -c "from src.signals import ai_model; print(ai_model.status())"

# housekeeping
python scripts/dead_code_audit.py                # unreferenced modules, defs, imports
python -m src.data.universe_refresh            # KMIALL drift vs the live exchange table
python -m src.data.ohlc_poller --probe OGDC      # what is the source serving now?
```

## Research notes

- [Final research and production audit](RESEARCH_FINAL_AUDIT.md): explains the
  27% result, the data limitations, the out-of-sample economics and the current
  signal status.
- [Deep scan audit, 2026-10-10](AUDIT_DEEP_SCAN_2026-10-10.md): the
  governance guard failure on `860fdab`, the locale dependent decode inside the
  gate itself, the thin sample regime that contradicted its own contract, the
  measured scan cost, and the hardened workflow template in `docs/ci/`.
- [Android update, 2026-10-10](ANDROID_APP_UPDATE_2026-10-10.md): why the app
  showed no percentages (the relay was older than the repo), the owner's new
  session copy, and strict typing for the card's financial values.
- [Intraday forward system](INTRADAY_FORWARD_SYSTEM.md): registered candidates,
  promotion and demotion rules, source checks, and the data limitations.
- Entry-metrics study (`scripts/entry_metrics.py`, report in
  `data/entry_metrics_report.json`, local only): MAE/MFE distributions,
  time-to-target and horizon returns over the clean next-bar-open entries.
  Headline: inside the 3-bar hold, +2% is reachable in 59.6% of entries
  (63.0% baseline) with a median time of one bar, while 78.1% of entries
  (80.3% baseline) touch -1% intraday. Stop placement is the binding
  constraint on this universe.
- Condition and event studies (`scripts/event_study.py`,
  `scripts/condition_scan.py`, `scripts/walk_forward_check.py`): the frozen
  daily panel, the per-condition lift table and the chronological persistence
  check. These are the inputs the AI prior is trained from.

## The strategy, in one paragraph

Scan the whole current KMIALL universe. For each symbol measure the last
five minutes of price change, whether that change is accelerating versus the
previous five minutes, the volume of the latest five-minute bucket against
the session's own median bucket, whether that volume is still growing, and
the session's traded value as a liquidity screen. Penalise anything that has
already run too far or is drifting away from its session high, because those
are late. Gate the whole thing on market context: if the KMIALL universe is
not broadly advancing, there is no trade. Take the single highest score above
the configured minimum, let the AI prior break a near-tie or refuse a
disliked candidate, enter on paper at the observed price, set the target at
entry x 1.02, and lock the day. One winner, one entry, one target, then
monitor and sleep.

## Current status, 2026-10-11

- **Every change lands as a pull request.** One PR per change, based on
  `master`, and the `governance-guard` workflow has to pass on it first: the
  governance check (secrets, footprint honesty, standing orders, SO-7 style and
  identity, SO-8 Karachi pin, SO-4 local-only backtests), the whole unit suite,
  and the worker's JavaScript syntax. The agent then merges it to `master` with
  a merge commit. There are no direct pushes. The 2026-10-11 batch is the
  pattern: #60 the session law and the 4-minute cadence, #61 the CI budget
  scheduler, #62 the relay URL resolution and the push preflight, #63 the
  backtest engine and optimizer, #64 SO-4 enforced in code, #65 the app v1.6.1
  scan-cadence line, #66 these docs.
- **Suite green.** 581 tests pass (`python -m pytest tests -q` reports 581
  passed and 239 subtests; `python -m unittest discover -s tests` reports
  `Ran 581 tests`, OK). All 32 modules under `src/` import cleanly. The
  governance guard passes end to end (SO-7 dashes, SO-8 Karachi pin, secrets,
  footprint honesty, standing orders).
- **Scanning is 4 minutes, and only in MARKET.** Owner order 2026-10-11:
  `config.TICK_INTERVAL_MINUTES = 4` drives the Windows tick, the supervised
  loop and the slot guard, and `is_scan_window` (src/data/sessions.py) is true
  only in the MARKET state. Pre-market (09:00 to 09:15) and post-market
  (15:32 to 15:49, Friday 16:32 to 16:49) are reported and never scanned;
  post-market stays finalize-only. GitHub Actions cannot express a 4-minute
  cron (its floor is 5), so the 4-minute full-universe scan is the local
  always-on runner and the Actions path stays at its 5 gated scans a day.
- **The Actions budget answers for itself.** [src/ci/budget.py](src/ci/budget.py)
  reproduces the audit's figures (1,369 min a month, 68.5%, 630.8 to spare)
  and converts the minutes left into a scan interval: 53 min on the 1st,
  172 min on the audit day with 1,369 burned, nothing once the runway is
  gone. The reset on the 1st, a 28-day February, the fire margin and a burst
  mid-month are all covered by [tests/ci/test_budget.py](tests/ci/test_budget.py).
- **Relay healthy.** `/health` returns 200 with `paired: true` and the correct
  next session (`OPEN at 2026-10-12 09:32`); the market card and the research
  gate answer; an unauthenticated read is refused with 403.
- **The published signal card is stale.** It still carries the 2026-10-07
  verdict from the retired v1 stack, two trading sessions behind the last
  completed session. The 4-minute runner rewrites the card whenever its verdict
  changes, so the first in-session tick on the next trading day replaces it.
  Until then the app shows an old line and the verifier says so.
- **The AI prior is live but the daily panel is behind.** The artifact was
  trained today, but `data/eod_history_kmi.csv.gz` reaches only 2026-10-05, so
  the prior is computed from features a few sessions old. It is disclosed in
  the observation (`prior_panel_as_of`) and flagged by the verifier; refresh
  the EOD panel to sharpen it.
- **Blocked on the intraday data source, unchanged.** The configured source
  returns acknowledgement-only payloads with no volume, so the pipeline reports
  SCAN BLOCKED and trades nothing. That is fail-closed behaviour, not a working
  capture.
- **No local forward state yet.** `data/forward/` is empty in this checkout
  because no in-session tick has run here; the cloud runner keeps its own.
- **Dead code audit is clean.** Every module under `src/` is referenced. One
  unreferenced function was removed from the live daily engine and 14 unused
  imports were dropped. Two dead functions remain inside the retired
  opening-range library on purpose: that module is preserved whole as the
  record the frozen research gate still reads, and its retention is enforced by
  a test.
- **This PC's clock is a month ahead of the exchange.** The portal's newest
  session is 2026-10-09 and the relay's edge clock says 2026-10-10, while this
  PC reads 2026-11-10 (the build toolchain printed 2026-12-11). The local
  runner therefore scans days the exchange did not have and records
  DATA_BLOCKED, while the relay, and therefore the app, correctly reports the
  weekend. Fixing the PC clock is a housekeeping task, not a code change: the
  verifier's "relay agrees with the local clock" check passes once the clock
  is right.
- **The relay is deployed and current.** `python cloud/pair.py deploy` runs
  from this PC over the Cloudflare REST API, so no Node and no wrangler are
  needed. Verified live after the deploy: `/health` and `/market` both carry
  `market_state` (phase `CLOSED`, next event `OPEN 2026-10-12 09:32`), every
  volume leader carries `change_pct`, and `volume_split_basis` explains the
  missing split. The phone card therefore shows the day's move and the session
  sentence instead of a bare total.
- **The cron schedule is capped at five triggers, not six.** Workers Free
  allows 5 cron triggers per ACCOUNT, so the six edge list was rejected with
  Cloudflare error `10072`, and that rejection used to abort the deploy AFTER
  the script upload, leaving the code live and the schedules stale. The two
  Friday midday edges are now packed into one expression
  (`0,32 7,9 * * 5`); the worker's handler only sends within two minutes of a
  real edge, so the extra fires are discarded and no edge fires twice. The
  schedule test proves coverage, uniqueness, the harmless extras and the five
  trigger cap, and a mutation check confirms it catches a dropped edge.
- **The relay admin token has been rotated** (it had been exposed in a chat
  transcript). The new value lives in the gitignored `.env`, in the worker
  binding, and in the `RELAY_ADMIN_TOKEN` Actions secret, which was updated in
  the same pass so the scheduled workflows keep authenticating. Verified: the
  new token returns 200 from `/signals` and a bogus one is refused with 403.
- **Backtesting is local-only in code, not just in a document.** Owner order
  2026-10-11: the Actions minutes are reserved for the market-hours scans, so
  `src/ci/local_only.py` lists every backtest and history-research entry point
  and each one calls `guard_local_only` first. Run a backtest in Actions and
  it stops with `REFUSED (SO-4)` and the reason, instead of burning minutes;
  `check_governance.py` fails a pull request that drops a guard, deletes a
  listed script, or puts one into a workflow. Verified live: the guard refuses
  under `GITHUB_ACTIONS=true` and does not touch the market-hours jobs.
- **The scheduled daily push went red on its own configuration file.**
  `data/relay_url.txt` is gitignored, so a fresh Actions runner never has it;
  the preflight added on 2026-10-10 read that file before the job wrote it,
  and the RuntimeError it raised was the whole alert (the last four log lines).
  The order is load-bearing and is now tested, resolution failures come back
  as a sentence instead of a traceback, and the public worker URL can be given
  to any runner as the `RELAY_URL` repository variable
  (`schedule_runner.load_relay_url`: env, then file, else fail closed).
  Verified by mutation: restoring the old order fails the new tests.
  The phone's gear panel still holds the old token, so the signals card will
  ask for the new one until it is pasted again; the status and market cards
  need no token and are unaffected.
- **The Telegram bot token could NOT be rotated here.** It is the same value
  that was exposed, so it still needs regenerating with BotFather on the
  owner's phone. After regenerating, paste the new token into
  `Desktop/credentials.txt` and rerun `python cloud/pair.py deploy` to rebind
  it; nothing else has to change.
- **The buy/sell split has no live data yet.** The engine, the card plumbing
  and the tests are done; the broker sends per-symbol ticks only while the
  exchange is trading (its own recon report says the same about the Friday
  break), so the split fills in from the first armed capture during a live
  session. Until then the card shows the total and says the split is
  unavailable.
- **Live trading stays off** until the frozen paper gate opens, which needs
  genuine accumulated sessions first.
