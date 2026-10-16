# Quant of Rehan

![Quant of Rehan](assets/quant-of-rehan-logo.png)

**Private, signal-only quantitative research platform for PSX KMIALL stocks.**
No order placement. No broker integration for trading. Signals and research
only. Sole contributor and owner: Rehan (muhammadrehanqureshi).

The strategy, in one paragraph: scan the whole current KMIALL universe. For
each symbol measure the last five minutes of price change, whether that change
is accelerating versus the previous five minutes, the volume of the latest
five-minute bucket against the session's own median bucket, whether that volume
is still growing, and the session's traded value as a liquidity screen.
Penalise anything that has already run too far or is drifting away from its
session high, because those are late. Gate the whole thing on market context:
if the KMIALL universe is not broadly advancing, there is no trade. Take the
single highest score above the configured minimum, let the AI prior break a
near-tie or refuse a disliked candidate, enter on paper at the observed price,
set the target at entry x 1.02, and lock the day. One winner, one entry, one
target, then monitor and sleep.

## What is true today

- **One scanner**: [src/signals/momentum_scanner.py](src/signals/momentum_scanner.py).
  It scores every eligible KMIALL symbol on fast momentum, momentum
  acceleration, relative volume, volume acceleration and liquidity, applies a
  market-context gate and a late-move decay, and returns exactly one winner,
  NO TRADE, or DATA BLOCKED. The old opening-range library and the FVG / sweep
  daily engine are retired from the trading path.
- **One configuration surface**: [src/config.py](src/config.py) holds the
  target, the coverage floor, the score weights, the AI routing rules, the
  tick cadence and the live-trading switch. Paper mode is the default and
  live trading is disabled.
- **One daily trade state**: [src/signals/trade_state.py](src/signals/trade_state.py).
  A persisted state machine with a hard one-trade-per-day lock that survives a
  process or runner restart, plus the tick bookkeeping that makes the local
  4-minute runner idempotent.
- **One market clock**: Asia/Karachi UTC+5 forever (SO-8) in
  [src/data/sessions.py](src/data/sessions.py). The session bands are
  Mon to Thu 09:32 to 15:30, and Friday TWO sessions (09:17 to 12:00 and
  14:32 to 16:30) with the exchange's midday break between them; weekends and
  PSX holidays are closed. `market_phase()` answers CLOSED, PRE_OPEN, WARMUP,
  OPEN, BREAK or POST_CLOSE for every consumer (the runners, the scanner guard,
  the relay, the phone app), so the app cannot call a break ONLINE. Beside the
  phases sits the owner's four-state law of 2026-10-11: `market_state_at()`
  answers PRE_MARKET, MARKET, POST_MARKET or CLOSED, and `is_scan_window()` is
  true only in MARKET: the quant never scans pre-market or post-market.
- **One trained AI prior**: [src/signals/ai_model.py](src/signals/ai_model.py),
  described in full below. It is a confirmation prior on the scanner's winner,
  never the decider.
- **Honest data states**: a broken, thin, stale or volume-less source reports
  DATA BLOCKED with measured coverage and never a market verdict. See
  [DATA_SOURCING.md](DATA_SOURCING.md) and
  [INTRADAY_FORWARD_SYSTEM.md](INTRADAY_FORWARD_SYSTEM.md).
- **The phone app**: `android/` v1.7.0 in this tree (versionCode 24; the last
  APK built and signed is `QuantOfRehan-v1.6.8.apk` on the OneDrive Desktop).
  It shows the status pill with the relay's own phase sentence, the latest
  signal, and the market card: KSE100 points and percentage, then the three
  KMIALL stocks with the highest session volume, each with its percentage
  change and its buy/sell/total volume when a genuine split exists: since
  v1.7.0 the B and S are the numbers the broker feed itself counted, exact
  and unrounded, with `=` on a measured row and an approximation sign (drawn
  by the system face, which the brand face cannot render legibly) on an
  estimated one. The status
  beacon breathes only while the market is live, as a view property animation
  on alpha and scale that the platform interpolates on the render thread, the
  settings gear is centred on the brand name, and the cadence sentence stands
  12dp under the last diamond rule, on the same grid as the tiles. It polls
  `/health`, `/signals` and `/market` on the edge, survives reboot, and never
  derives a session from its own clock. See [android/README.md](android/README.md).

## How it runs

The schedule lives in the cloud and never on the owner's PC (SO-12, owner
order 2026-10-14). Two paths carry it, both of which run with this machine
switched off, so a market session is never waiting on a laptop being awake
and charged:

| | GitHub Actions | Cloudflare relay |
|---|---|---|
| File | [.github/workflows/intraday-session.yml](.github/workflows/intraday-session.yml) (the 30-second session loop) and [.github/workflows/intraday-capture.yml](.github/workflows/intraday-capture.yml) (the band slots, the finalize and the backstop) | [cloud/worker.js](cloud/worker.js) |
| Carries | the every-30-seconds scan of the KMIALL universe, the post-close finalize, and the observation both the phone's card and the intraday paper strategy read | the owner's open and close texts, and the `/health`, `/signals` and `/market` endpoints the phone reads |
| Cadence | **every 30 seconds inside every PSX band** (`config.SCAN_INTERVAL_SECONDS = 30`, owner order 2026-10-14, SO-13); the per-slot fires at 10:00, 11:30, 13:00, 14:30 and Friday 16:00 remain as the backstop | on every band edge it is triggered for, and on every phone poll |
| Cost | nothing: standard runner minutes are free on a public repository (this one is public since the owner's 2026-10-14 order), and one cycle costs about 2.9s of a 30s slot | the free edge tier |
| State | its own forward state on the runner | `RELAY_KV` |
| Works with the PC off | yes | yes |

One scan serves both readers: the same run, observation and data-quality
report feed the phone's card and the intraday paper strategy, so there is no
second, cheaper scan for the app. The scan is only that dense because the
session loop keeps the read-only broker recorder alive for the whole band, so
a cycle measures a tape that already exists instead of fetching one:
`config.TICK_INTERVAL_MINUTES = 4` and its 20-minute warm-up rule still govern
the local 4-minute tick the owner can ask for as a local trial, and the two
are different runners, never two cadences for one runner.

The bars those scans read come from the broker tape, not from the eClear OHLC
servlet (owner order 2026-10-14, after the servlet stopped serving bars).
`src/data/tape_bars.py` builds one minute of open, high, low and close from
the prices the tape carried, and takes volume from the venue's own running
counter; `scripts/intraday_pipeline.py` reads the tape first and falls back to
a servlet capture that is already on disk. The same coverage, freshness,
volume and structure gates judge either source, and the source label travels
into the observation and the phone message. See [DATA_SOURCING.md](DATA_SOURCING.md)
for the measured numbers.

Those gates were measured against a real session on 2026-10-15 and the
freshness half of them was unreachable: across the whole 319 symbol KMIALL
universe, fresh coverage peaks at 74.9% to 78.7% inside five minutes, because
a slice of KMIALL genuinely prints less often than that, so the 80% 
whole-universe floor blocked every live scan and no signal could ever exist
(run 38530614304: 88 cycles, 87 scans, every one DATA BLOCKED). Freshness and
depth are now judged where they decide something, on the volume leaders a
candidate comes from and on the count of symbols a ranking can use, and the
illiquid tail is reported with its count instead of blocking the scan for
every symbol. A capture younger than the 20 bars the strategy needs is a
WARMING UP countdown rather than a coverage fault, so a runner that starts
mid-band is no longer counted as a dead feed. Measured on the same real tape
with the new gates: 230 to 245 rankable symbols and 19 to 20 of the top 20
leaders fresh at every instant, and the scan renders market verdicts
(NO TRADE at 10:30, entries at 11:00, 12:00, 13:00 and 13:45) where it
previously blocked.

The local runners are retired and refused in code. `scripts/kmiall_tick.py`
(the Windows tick), `scripts/scan_loop.py` (the supervised loop),
`src/notify/schedule_runner.py` (the resident open and close runner) and the
two installers that registered them all call `guard_owner_requested` from
`src/ci/local_only.py`: a real process starting on this PC is refused with
SO-12's reason, the same call passes straight through inside GitHub Actions,
and the Windows task `quant-of-rehan-kmiall-tick` is disabled while the
Startup entry is gone. `scripts/check_governance.py` fails a pull request that
puts either of them back, and `tests/test_local_only.py` holds the guards.

What the tick does when the owner does run it, and what the retired task used
to fire inside the PSX session windows only, is unchanged. Its triggers were
derived from `src/data/sessions.py`:

| Windows | Days | Cloud (the live cadence) | Local tick, if the owner runs one |
|---|---|---|---|
| 09:32 to 15:30 | Mon to Thu | every 30 seconds | every 4 minutes |
| 09:17 to 12:00 | Friday | every 30 seconds | every 4 minutes |
| 14:32 to 16:30 | Friday | every 30 seconds | every 4 minutes |
| 15:47 (16:47 Friday) | session days | once, the post-close finalize | once |

The cloud is the cadence that runs: `intraday-session.yml` starts
`scripts/scan_loop.py --loop --interval 30` for the length of each PSX band on
GitHub Actions minutes, with the Cloudflare relay serving the card, so the 30
second scan happens with the owner's PC switched off (SO-13, owner order
2026-10-14). The right-hand column is the retired Windows tick's own interval,
kept only because the owner may still ask for a local trial.

Nothing is registered for the pre-market window, the Friday midday break, the
evening or the weekend. The tick refuses to scan outside MARKET, pauses for
the first 20 minutes after the open (the strategy needs 20 bars and three
volume buckets before it can score anything), scans each 4-minute slot at most
once, holds a lock so two ticks cannot fight over the state file, reclaims a
stale lock left by a crashed tick, alerts after three consecutive capture
failures, and finalizes the day exactly once. Its record lives in
`logs/kmiall_tick.log` and `data/tick_health.json`.

The one local run the standing orders allow is the one the owner asks for, and
it is named in the shell that runs it, so nothing sets it by accident:

```bash
QOR_OWNER_REQUESTED_LOCAL_RUN=scripts/kmiall_tick.py python scripts/kmiall_tick.py --status
```

Inspecting and removing stay open always, because taking work off the machine
is never the offence. Backtesting stays local for the mirror-image reason
(SO-4): its entry points refuse to run in CI instead.

```bash
python scripts/install_kmiall_tick.py --show       # query the retired task
python scripts/install_kmiall_tick.py --remove     # delete it for good
python scripts/install_kmiall_tick.py --print-xml  # show the definition
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
   ever drift, training refuses to produce an artifact.
2. **It fails closed.** A missing, corrupt, feature-mismatched or ineligible
   artifact disables the prior and says why. A feature row with too many
   missing inputs yields no probability, never an imputed guess.
3. **It is weak, and it is wired in as weak.** The current artifact scored
   holdout AUC 0.5615 on 179,872 rows against a 20.5% base rate, with a
   top-decile rate of 23.7%. That is a real but small edge, so the prior is a
   *bounded* lever:

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
6. **Sole human contributor, human style (SO-7).** Every commit is authored
   by Mr. Rehan. Em dashes are banned from commits and files. `legacy/` is
   quarantined reference material from the deleted sentinel repos.
7. **The agent is the co-author (SO-7a, owner order 2026-10-13).** Every
   commit, every pull request body and every merge carries one line:
   `Co-Authored-By: Codebuff <noreply@codebuff.com>`. `scripts/land.sh`
   appends it and `scripts/check_governance.py` requires it. Any other
   identity or trailer still fails the check.
8. **Karachi time forever (SO-8).** UTC+5, hardcoded, no other zone.
9. **Owner notifications (SO-9).** "Quant is online now." at open;
   "Quant is sleeping now." at close, through the Cloudflare relay.

## Layout

```
src/config.py                     the ONE configuration surface (target, floors, weights, AI routing)
src/signals/momentum_scanner.py   the ONE scanner (momentum + volume + acceleration)
src/signals/ai_model.py           the ONE trained daily prior and its featurizer
src/signals/trade_state.py        the ONE persisted daily state, trade lock and tick bookkeeping
src/signals/contracts.py          the typed boundary: validated models, fault taxonomy, ingestion guard
src/signals/volatility.py         volatility regime and edge cases (measured, picks nothing, off by default)
src/data/sessions.py              Karachi-pinned clock, session law, owner texts
src/data/tape_bars.py             intraday bars from the tape (prints for OHLC, the venue counter for volume)
src/data/ohlc_poller.py           the servlet bar pass, kept as the fallback source
src/data/feed_capture.py          the broker tick tape (banked ticks, once a live session)
src/data/tick_volume.py           buy/sell/total volume split from the tape
src/data/live_card.py             the live card the relay serves to the app
src/data/market_snapshot.py       KSE100 + KMIALL volume leaders (app card)
src/data/universe_refresh.py      KMIALL drift check: tracked snapshot vs the live exchange table
src/ci/budget.py                  adaptive Actions budget: the scan interval left in the cycle
src/ci/budget_orchestrator.py     the scheduler as a CLI: report or JSON plan for a cycle
src/notify/telegram.py            env-driven notifier (fail closed)
src/notify/schedule_runner.py     local open/close notifier with journal
scripts/intraday_pipeline.py      the orchestrator (scan, finalize, card, archive)
scripts/kmiall_tick.py            the local 4-minute tick (pause, guard, lock, capture, finalize)
scripts/scan_loop.py              supervised interval scan loop (portable alternative to the task)
scripts/install_kmiall_tick.py    registers the Windows scheduled task
scripts/land.sh                   stage, validate and land one change through a PR
scripts/train_signal_model.py     trains and validates the AI prior
scripts/verify_market_signals.py  end to end verification: config, tests, relay, state, AI, scheduler
scripts/tape_capability_report.py the measured capability matrix of a banked tape session
scripts/check_governance.py       secret, style, identity and SO-8 enforcement
scripts/dead_code_audit.py        evidence-based dead code report (modules, defs, imports)
scripts/event_study.py            builds the frozen daily event study and its labels
scripts/condition_scan.py         per-condition lift table over the event study
scripts/entry_metrics.py          MAE/MFE, time-to-target and horizon study (local only)
examples/scan_once.py             one scan by hand, printing every layer of the decision path
examples/market_state_walk.py     the owner's four market states, walked edge by edge
cloud/worker.js                   Cloudflare relay + edge crons (Karachi math)
cloud/pair.py                     deploy + pair + test from the owner's PC
android/                          companion app source (signals + market on the phone)
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

# is the whole system actually working? (one command, honest verdict)
python scripts/verify_market_signals.py          # config, universe, local state, AI, scheduler
python scripts/verify_market_signals.py --live   # also dial the relay and read the cards
python scripts/verify_market_signals.py --all    # add the test suite

# how often may the scan run inside the rest of the Actions budget?
python -m src.ci.budget_orchestrator --known-used 1369 --period-end 2026-10-31
python examples/budget_plan.py                   # the month, day by day

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
python scripts/scan_loop.py --scheduled --interval 240  # the same cycles, on
                             # the async scheduler's absolute 4-minute grid
python scripts/scan_loop.py --status               # phase, window and loop health

# one scan by hand, with every layer printed (offline, synthetic if no capture)
python examples/scan_once.py

# the session law and the phase the app will show, right now
python -c "from src.data.sessions import market_state; import json; print(json.dumps(market_state(), indent=2))"

# buy/sell/total volume from banked broker ticks (needs a live-session capture)
python -m src.data.feed_capture --duration 600   # bank ticks (run in a session)
python -m src.data.tick_volume --show OGDC PSO   # inspect the split
python -m src.data.market_snapshot --push        # publish the card to the relay

# what is the intraday source serving right now?
python -m src.data.ohlc_poller --probe OGDC

# the AI prior
python scripts/train_signal_model.py
python -c "from src.signals import ai_model; print(ai_model.status())"

# what can the banked tape actually support? (measured, per session)
python scripts/tape_capability_report.py         # coverage, print fidelity, side attribution

# housekeeping
python scripts/dead_code_audit.py                # unreferenced modules, defs, imports
python -m src.data.universe_refresh              # KMIALL drift vs the live exchange table
```

## Research notes and the audit trail

- [RESEARCH_FINAL_AUDIT.md](RESEARCH_FINAL_AUDIT.md): the 27% result explained,
  the data limitations, the out-of-sample economics and the signal status.
- [INTRADAY_FORWARD_SYSTEM.md](INTRADAY_FORWARD_SYSTEM.md): registered
  candidates, promotion and demotion rules, source checks, data limitations.
- [DATA_SOURCING.md](DATA_SOURCING.md): where every input comes from, what is
  measured versus inferred, and what happens when a source goes quiet.
- [DASHBOARD_ARCHITECTURE.md](DASHBOARD_ARCHITECTURE.md): the private web
  console design on the owner's own broker feed, with the measured capability
  matrix (30.1s snapshot cadence, print fidelity 0.43 median, 21.9% of volume
  unattributable by side) that decides what a footprint view may claim.
- [MARKET_SCHEDULING.md](MARKET_SCHEDULING.md): the session law, the four
  states and the cadence decisions behind them.
- [AUDIT_AND_CI_BUDGET_2026-10-10.md](AUDIT_AND_CI_BUDGET_2026-10-10.md) and
  [AUDIT_DEEP_SCAN_2026-10-10.md](AUDIT_DEEP_SCAN_2026-10-10.md): the Actions
  budget, the governance guard failure and the hardening that followed.
- [APP_UPDATE_2026-10-12.md](APP_UPDATE_2026-10-12.md) and
  [ANDROID_APP_UPDATE_2026-10-10.md](ANDROID_APP_UPDATE_2026-10-10.md): why the
  card showed only a total, and how the app reached v1.6.5.
- [PROJECT_REPORT.md](PROJECT_REPORT.md): the long-form build record.
- Entry-metrics, condition and event studies (`scripts/entry_metrics.py`,
  `scripts/event_study.py`, `scripts/condition_scan.py`,
  `scripts/walk_forward_check.py`): the frozen daily panel and the studies the
  AI prior is trained from. Headline from the entry-metrics study: inside the
  3-bar hold, +2% is reachable in 59.6% of entries (63.0% baseline), while
  78.1% of entries (80.3% baseline) touch -1% intraday. Stop placement is the
  binding constraint on this universe.

## Charts of Rehan (the chart app)

`charts/` is a standard-library Python service and `web/` is its React and
TypeScript front end: candles, volume, the measured minutes that are missing,
and the exchange's own session clock, drawn only from bars this project can
name. It is a foreground tool and nothing else. It registers no schedule,
daemon, watcher or autostart entry, it refuses to start inside GitHub Actions
because the runner minutes belong to the market-hours scans, and it binds
loopback unless the operator says otherwise.

| Piece | File |
|---|---|
| The wire contract, validated in both directions | [charts/contract.py](charts/contract.py) |
| One adapter per source, behind one small protocol | [charts/adapters](charts/adapters) |
| Pacing, bounded retries, circuit breaker | [charts/ratelimit.py](charts/ratelimit.py) |
| Series store, revisions, measured gaps | [charts/store.py](charts/store.py) |
| The one payload builder every door uses | [charts/service.py](charts/service.py) |
| REST, Server-Sent Events and the built UI | [charts/http.py](charts/http.py) |
| The UI: strict TypeScript, canvas renderer | [web/src](web/src) |

Sources: the broker tape for minute bars, the PSX Data Portal company page for
one session snapshot (about five minutes delayed, one bar per day), and a
labelled synthetic replay source that exists for tests and the offline demo.
The portal's old EOD endpoint answers an HTML shell and `/timeseries/int` is a
404 (both measured 2026-10-14), so no daily or intraday series is claimed from
there; `src/data/registry.py` declares that as `session_snapshot` and
[DATA_SOURCING.md](DATA_SOURCING.md) records the measurement.

```bash
python examples/charts_demo.py                    # the whole pipeline, offline
python -m charts --source tape --port 8788        # real bars, loopback only
python -m charts --source replay --once           # one poll, then exit
cd web && npm install && npm run dev              # the UI with hot reload
```

104 Python tests cover the contract, the store, the rate limiter, the three
sources and the HTTP surface over a real socket (including the event stream);
64 front-end tests cover the validators, the retry and timeout paths, the
stream reconnection and the series maths. Full detail in
[charts/README.md](charts/README.md) and [web/README.md](web/README.md).

## Status, 2026-10-13

- **Every change lands as a pull request.** One PR per change, based on
  `master`, and the `governance-guard` workflow has to pass on it first: the
  governance check (secrets, standing orders, SO-7 style and identity, SO-8
  Karachi pin, SO-4 local-only backtests), the whole unit suite, and the
  worker's JavaScript syntax. The agent then merges it with a merge commit;
  there are no direct pushes. `scripts/land.sh` does that flow locally and
  through `gh`.
- **Suite green, and it now stays inside itself.** 756 tests pass
  (`python -m unittest discover -s tests` reports `Ran 756 tests`, OK). The
  suite used to reach out of its sandbox in two ways: a capture-health test
  posted a real Telegram alert from a five-symbol fixture (the "capture
  degraded (coverage 0.0%, 0/5 symbols)" message), and a poller test rewrote
  the live `data/feed_capture/ohlc_status.json` with a synthetic one-symbol
  pass. Both are fixed: the alert transport is patched in the test, the poller
  heartbeat is written inside the patched paths, the scan loop's log is
  redirected, and a full suite run now leaves every live file byte-identical
  (verified with a before/after hash of the whole tree).
- **The intraday OHLC source is dead.** Every mirror answers
  `vt.eclear.com.pk` with the bare acknowledgement and zero rows. Measured
  today: the 09:52 capture pass asked 124 symbols and every one of them
  answered with no bars, coverage 0.0%, and the tick logged its 50th
  consecutive failed capture. Fail-closed behaviour follows: DATA BLOCKED, no
  scan, no trade, and the day's slots record nothing but that. The broker tick
  tape is a separate feed and is alive (ticks were banked this morning).
- **A full capture pass does not fit the tick.** A complete 319-symbol pass
  needs about 734s at the source's own pacing; the tick allows 195s, so every
  pass is partial and says so. The coverage gate stays closed even if a few
  symbols answer. Widening the budget, speeding the source or narrowing the
  universe is a decision still to be made.
- **The capture alert is working, and its wording was not the outage's.** While
  the outage continues, the reminder arrives through the relay at most once a
  Karachi day (the last real alert day is 2026-10-12). The "0/5 symbols"
  message on the morning of 2026-10-13 was the test suite's own fixture, now
  stopped as described above. Production alerts after three consecutive
  failures and carry the live coverage of the real 319-symbol universe.
- **The AI prior is live; its daily panel is behind.** The artifact is
  feature-matched and routing as a bounded prior. `data/eod_history_kmi.csv.gz`
  reaches 2026-10-05, six trading sessions back, so the prior is computed from
  features a few sessions old. It is disclosed in the observation
  (`prior_panel_as_of`) and flagged by the verifier; refresh the EOD panel to
  sharpen it.
- **The published signal card is stale by consequence, not by fault.** The
  last recorded observation is 2026-10-12 15:24, DATA BLOCKED. It rewrites
  itself when a verdict changes, which cannot happen while the source serves
  nothing, so the app keeps showing the last honest line and the verifier says
  so. The market card (KSE100 and the volume leaders) is separate and keeps
  refreshing; this morning's carries three estimates from the day's range and
  marks them as estimates.
- **The relay is healthy and live trading stays off.** `/health`, `/market`
  and the market card answer; an unauthenticated read is refused with 403.
  Paper mode is the default and the only mode until the frozen paper gate
  opens, which needs genuine accumulated sessions first.
