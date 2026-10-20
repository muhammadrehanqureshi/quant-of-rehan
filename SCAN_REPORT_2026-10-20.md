# Quant of Rehan: full scan, strategy and cleanup

Date: 2026-10-20, 11:20 PKT (SO-8).
Scope: the repository at `C:/Users/rehan/OneDrive/Desktop/quant-of-rehan`, the
Cloudflare relay, the GitHub Actions schedules, and the local desktop clutter.
Evidence: the relay's own JSON, the Actions API, the repository tree, and the
dead-code audit. No local test run, no local build, no backtest: per the
2026-10-19 order, every check that costs CPU ran in Actions.

## 1. Verdict

The machine is alive and honest. The scanner is running on the cloud schedule,
the relay is serving quotes that are seconds old, the phone build is produced
in Actions, and the suite is green. Today it is saying NO TRADE, and that
refusal is correct: breadth is 27.7 percent against a 35 percent floor.

Two things are not healthy, and neither is the scanner:

1. Telegram is not paired. `GET /status` returns `paired: false` and
   `last_delivery: null`, so the alert path cannot deliver a message. The card
   still reaches the phone through `GET /signals`, which is why the screen is
   current while the alert channel is silent.
2. There is no fresh market-wide REG frame. `market_feed` is `UNKNOWN` with
   `fresh: false`, so the relay cannot confirm OPEN or HALTED from the broker.
   The session schedule carries the state instead, and the OPEN/HALTED texts
   have no evidence to fire on.

## 2. Live snapshot (11:17 PKT)

| Fact | Value |
|---|---|
| Market | OPEN (session schedule; feed status unconfirmed) |
| KSE100 | 166,021.17, +55.09, +0.03 percent |
| KMIALL members at the relay | 313 |
| Symbols scanned today | 282 of 317 |
| Today's verdict | NO TRADE |
| Reason | breadth 27.7 percent is below the 35 percent momentum floor |
| Market label | WEAK |
| Top volume | CNERGY, T 21,476,184, B 4,130,035, S 17,346,149 |
| Quote age at read | 17 seconds |
| Relay version | e6fe76ce3f44ed4c6d9004773772e4a967452480 |
| Test suite at last PR | 1,231 tests, all green |
| Phone build | v1.7.8, versionCode 32, 568,478 bytes, 2026-10-20 |

The card at `/signals` is dated today and rewritten by the running band job.
Nothing is stale, and nothing is invented.

## 3. The strategy behind the daily intraday call

The one authoritative decision point is `src/signals/momentum_scanner.py`
(`momentum_volume_breakout_confirmation_v2`). `scripts/intraday_pipeline.py`
runs it per slot, then owns the daily lock and the delivery. The retired
opening-range engine in `src/signals/intraday_engine.py` cannot emit a signal;
only `src/research/forward_validation.py` imports its rule constants.

### 3.1 Input

One-minute bars from the read-only broker tape (MKT-FEED): open, high, low,
close from the tape prints, and volume from the venue's own running counter.
The eClear OHLC servlet is a fallback for a day with no tape. A symbol needs 20
bars, a last bar no older than 5 minutes, and a price of at least 1.00.

### 3.2 Hard gates, per symbol

All of these must hold or the symbol is not scored at all:

- fast momentum (5 minute return) above zero
- acceleration above zero: 5 minute return minus the previous 5 minute return
- session return above zero
- relative volume at least 1.5 (latest volume bucket against the median of the
  earlier buckets)
- volume still accelerating: latest bucket at least 1.0 times the one before
- close at or above the prior 5-bar high
- Wilder RSI(14) at least 50
- traded value at least PKR 5,000,000 in the session so far

### 3.3 Score

Five components, each normalized to 0..1 by a saturating half-credit curve:

| Component | Weight | Half-credit at |
|---|---|---|
| momentum | 0.32 | 0.4 percent |
| acceleration | 0.24 | 0.2 percent |
| relative volume | 0.20 | +1.0 over 1.0 |
| volume acceleration | 0.14 | +1.0 over 1.0 |
| liquidity | 0.10 | PKR 20 million |

`score = 100 * sum(weight * component)` with two multiplicative decays:

- extension: above +6 percent session return, factor `1 / (1 + excess/6%)`
- weakness: more than 1 percent below the session high, the same shape

The penalty is multiplicative on purpose. A capped subtraction still lets a
runaway mover win on saturated momentum, which is the chase the owner banned.

### 3.4 Market gate and selection

The market proxy is KMIALL's own cross-section: breadth (share of symbols
above zero) and the median return. Breadth below 35 percent, or a median
return at or below minus 1 percent, is NO TRADE regardless of any single
stock. That is today's case at 27.7 percent.

Otherwise the highest score at or above 55 wins. Exactly one symbol, or NO
TRADE, or DATA_BLOCKED. A data failure is never reported as a market verdict.
The AI prior can only reorder a near-tie inside 2 points, and its veto is off
by default (`AI_GATE_ENABLED = False`).

### 3.5 Trade semantics

- Entry: the last price at signal time, labelled a paper reference.
- Target: entry times 1.02, exactly 2 percent.
- Stop loss: none. The position is valued at the session close if the target is
  not touched. The phone prints "Stop Loss: Not reported" because that is true.
- One trade per market day (`MAX_TRADES_PER_DAY = 1`). The lock is persisted in
  `data/forward/session_state.json` and claimed across runners through the
  relay's `/research/claim`, so two runners cannot both enter.
- After entry the day is locked. Later candidates are reported as observed and
  refused, never as a second call.
- Signal-only (SO-1). No broker endpoint, no order, no leverage.

### 3.6 Cadence and delivery

`intraday-session.yml` runs the loop for each band. The request is one second;
one cycle costs about 2.9 seconds on the 2026-10-13 tape, so the achieved rate
is the pipeline's own latency. Every verdict is posted to `/signals` (the
phone's card) and a taken trade is posted to `/notify` for Telegram. A blocked
scan updates the card without an alert.

## 4. Findings

### F1, high: Telegram is unpaired

`/status` reports `paired: false` and `last_delivery: null`. Any trade today
would be entered and would update the card, but `deliver()` would be refused
and the journal would record `TRADE_UNDELIVERED`. This is an owner action: pair
the chat (`cloud/pair.py start`, then confirm) or state that the phone card is
the only channel. The code already refuses to call this a delivery.

### F2, medium: no market-wide feed frame

`market_feed.status` is `UNKNOWN`, `fresh` false. Open, break and close texts
fall back to the session schedule, so the times are right, but a HALTED state
cannot be detected from the venue. The fix is on the publisher side: publish
the REG market status frame with the same cadence as the quotes.

### F3, medium: two universes

The scan reports 317 expected symbols; the relay reports 313 KMIALL members.
The difference is four symbols between the scan list and the membership table
the relay derives. It is small, but it means coverage percentages are computed
against a different denominator than the one shown on the phone.

### F4, medium: no stop loss

The live strategy has a target and a session-close exit, and no adverse stop.
That is a deliberate shape, but it should be a stated risk rather than a blank
field on the phone. If a stop is wanted, it belongs in `config.py` beside
`TARGET_PCT` and in the state machine, not only in the old retired engine.

### F5, low, fixed: the card header shipped mojibake

`/signals` carried U+00C2 immediately before U+00B7 where the separator should
have been (the reader saw a stray A-circumflex before the dot), so the
separator had arrived double decoded. The header is ASCII now (`|` separator), with a test that
encodes it as ASCII, so the transport's charset cannot corrupt it again. The
running band job picked its code up at 09:43, so the clean header appears when
the next band job starts.

### F6, low: the research gate is not publicly readable

`GET /research/history` is admin gated behind `/research/*`. That is correct
for writes and for the claim route, but it means the public relay cannot be
used to audit forward performance without the admin token. The gate's own
state lives in Cloudflare and was not read in this scan.

### F7, low: the local journal is not the live record

`data/forward/session_journal.jsonl` ends on 2026-10-12 with a blocked session.
The live record is the cloud runner's, and its observations and outcomes are
stored at the relay. Do not read the local file as current performance.

### F8, info: legacy is deliberate, not dead

`legacy/` is 7.4 MB of the deleted sentinel and EOD repositories, quarantined
by `legacy/README.md` as reference only. Nothing imports it and CI does not run
it. It is kept on purpose and was not deleted.

## 5. Cleanup ledger

### 5.1 Repository code (PR #52)

- Removed two unused imports from `src/data/band_state.py` (`datetime`,
  `timezone`). The audit is clean at zero modules, zero defs, zero imports.
- Deleted `governance_gate.json`, a stale unreferenced snapshot of the Karachi
  pinned files that still listed the retired engine.
- Replaced the non-ASCII card separator with ASCII.
- Wired the dead-code audit into the suite as `tests/test_dead_code_gate.py`,
  so the next unused import fails its pull request instead of accumulating.
- Kept `legacy/` (documented reference), `data/` (gitignored corpus and forward
  state), `web/node_modules` (dev dependency cache), and every module the audit
  found referenced.

### 5.2 Local machine

Deleted, all of it regenerable or superseded:

| Item | Size |
|---|---|
| `tmp/` (HCAR postmortem copies, replay capture, audit logs) | 413 MB |
| `logs/` (October 12 to 16 logs) | 1.5 MB |
| `.pytest_cache/` | 219 KB |
| `android/app/build/` (generated APK and classes) | 2.6 MB |
| every `__pycache__` under the tree | small |
| stale clone `Desktop/quant-of-rehan-repo` (4 October, clean) | 400 KB |
| five superseded APKs on `C:/Users/rehan/Desktop` (1.6.1, 1.6.2, 1.7.1, Quant, Quant-previous) | 2.3 MB |
| local branches already contained in master | 115 branches |

The repository folder went from 784 MB to 357 MB.

Kept, with reasons: `data/` (the only copy of the historical corpus and the
forward state), `legacy/` (documented reference), `web/node_modules` (needed to
run the web app), `charts-of-rehan`, `J.A.R.V.I.S`, `jarvis` and the other
personal folders on the desktop (different projects, not mine to delete), the
`buffy/wip-two-days` branch (not merged into master), and the current APK.

The APK on the OneDrive desktop had gone missing before the cleanup and was
restored from the Actions artifact: `QuantOfRehan-v1.7.8.apk`, 568,478 bytes,
badging reads `versionCode=32 versionName=1.7.8`.

## 6. Pull requests landed today

| PR | Change |
|---|---|
| #45 | Phone tiles read the live feed, symbol search, green ONLINE badge, 1 second watchdog |
| #46 | One spelling for the empty signal tile |
| #47 | APK build in Actions |
| #48 | setup-android asks only for packages that still exist |
| #49 | Missing semicolon in the search panel (caught by the new build) |
| #50 | Dispatch token bound to the Worker from CI, never from a file |
| #51 | Node 22 for wrangler |
| #52 | Dead code removed, card header made ASCII, audit wired into CI |

Every one went through a pull request, was merged by `scripts/land.sh`, and
carries `Co-Authored-By: Codebuff <noreply@codebuff.com>` as its last line.

## 7. What is not verified here

- Telegram delivery: unpaired, so nothing can be sent until it is paired.
- Research gate history: admin gated, not read without the token.
- The ASCII card header on the live relay: the source and its test are green,
  but the running band job started before the change. The 12:30 PKT band job is
  the first one that will publish it.
- The relay's punctual band dispatch: bound and token-verified today, but its
  first live fire is the next band open, not something this scan could force.
- Any performance claim: no backtest and no forward sample was run in this
  session, and none is asserted here.
