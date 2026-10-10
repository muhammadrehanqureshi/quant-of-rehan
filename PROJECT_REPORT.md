# Quant of Rehan: the complete project report

Written 2026-10-09 at 12:45 PKT (Asia/Karachi, UTC+5, SO-8).
Repository state: `master` at `69c9c59` (merge of PR #56). 121 commits, 48 merges.
Every figure below was read from the repository, the local `data/` directory, the
Cloudflare relay, or the GitHub API at that time. Test-artifact numbers are labelled
as such.

---

## 1. What this project is

A private, signal-only quantitative research platform for the **PSX KMIALL Shariah
universe** (Karachi Stock Exchange, all-share Shariah index). It decides, from
momentum plus volume expansion, whether exactly one stock is a buy today, records
that as a paper trade, watches a +2% target, and reports to the owner's phone and
Telegram. It never places an order. It is owned and authored solely by Rehan
(muhammadrehanqureshi); the agent (Buffy / the QUANT) executes and never widens its
own scope.

Everything is pinned to one timezone (Asia/Karachi, fixed UTC+5) and one session law:
Monday to Thursday 09:32 to 15:30, Friday 09:17 to 16:30, holidays and weekends
skipped.

Size of the thing:

| Measure | Value |
|---|---|
| Tracked files | 329 (215 of them quarantined under `legacy/`) |
| Python lines, tracked, excluding `legacy/` | 13,047 |
| Tests | 185 test methods across 15 files, all passing |
| GitHub Actions workflows | 3 (governance guard, intraday scan, daily signal push) |
| Cloudflare Workers | 1 relay (`quant-of-rehan-relay`) with 4 crons and 10 KV keys |
| Android app | versionCode 12 / versionName 1.5.0, APK 436,793 bytes, built without Gradle |
| Research documents | 6 (`DATA_SOURCING`, `INTRADAY_FORWARD_SYSTEM`, `RESEARCH_AUDIT`, `RESEARCH_FINAL_AUDIT`, `RESEARCH_PHASE1`, `RESEARCH_PHASE2A`, `RESEARCH_PHASE2B`) |

---

## 2. The strategy, exactly

One scanner, one score, one trade a day, one target.

**Universe**: the tracked snapshot `src/data/universe_kmiall.json` (319 symbols, all
Shariah, all listed in KMIALLSHR). The scanner loads it, filters on
`isShariahCompliant == true` and `KMIALLSHR in listedIn`, and records a SHA-256
fingerprint of the sorted list in every observation so a membership change is
visible in the record.

**Bars**: one-minute bars. Five-minute buckets are built only from five consecutive
completed minutes and only from bars strictly before the decision time.

**Score** (`src/signals/momentum_scanner.py`), each component normalized to 0..1 by a
saturating half-credit scale `sat(x, k) = max(x,0) / (max(x,0) + k)`:

| Component | Formula | Weight | Half-credit `k` |
|---|---|---|---|
| momentum | `sat(ret_5m)` | 0.32 | 0.004 (0.40%) |
| acceleration | `sat(ret_5m - ret_prev_5m)` | 0.24 | 0.002 (0.20%) |
| relative volume | `sat(rel_vol - 1)` | 0.20 | 1.0 |
| volume acceleration | `sat(bucket_ratio - 1)` | 0.14 | 1.0 |
| liquidity | `sat(session traded value)` | 0.10 | 20,000,000 PKR |

`score = 100 * sum(weight * component)`, then multiplied by two decay factors.

How the two volume terms are built: the session's completed five-minute buckets are
collected, relative volume is the latest bucket against the median of all earlier
buckets, and volume acceleration is the latest bucket against the one immediately
before it. Momentum windows are anchored on the last completed bar rather than on the
scan clock, so the fast leg and the leg before it always span the same number of
minutes and the acceleration comparison is like for like.

* **extension factor**: 1.0 up to a 6% session move, then `1/(1+excess/cap)`, so a
  move that has already run cannot win on raw momentum;
* **weakness factor**: same shape for distance below the session high, capped at 1%.

**Hard gates** (a symbol is eligible only if all pass): at least 20 bars; at least three
completed volume buckets; a usable session open; positive 5-minute momentum; positive
acceleration; positive session return; relative volume at or above 1.5; volume still
accelerating (`volume_accel_ratio >= 1.0`); session traded value at or above 5,000,000
PKR (`sum(close * volume)` over the session); last bar inside the 5-minute staleness
limit; price at or above 1.0. Extension and weakness are deliberately **not** hard
gates: they are the multiplicative decay described above, so a stock that has already
run can still be scored but loses points for being late.

**Market gate**: the whole captured cross-section must be supportive, meaning breadth
(advancing share) at or above 35% and the median return not below -1%. If not, no
trade, and the reason names the market, because a momentum strategy must not fight a
broad selloff.

**Selection**: rank all eligible symbols by score, take the highest, and require it to
be at or above **55.0**. Otherwise the day is NO TRADE.

**Target law**: `target = actual_entry_price * 1.02`. One trade per day, hard locked.

**Data honesty gates** (checked before any market logic): universe non-empty; trading
day; coverage at or above 80%; fresh coverage at or above 80%; newest bar no older
than 5 minutes; malformed share no more than 1%; and **volume present at all**. Any
failure returns `DATA_BLOCKED` with the measured numbers, never a market verdict. The
blocked message ends with "No trade issued. This is a DATA failure, not a market
decision."

---

## 3. The runtime, piece by piece

### 3.1 Data sources and the honesty registry

`src/data/registry.py` is the single source of truth for what data genuinely exists.
Engines must consult it and refuse to run otherwise (SO-3).

| Key | Availability | Honest detail |
|---|---|---|
| `daily_ohlcv` | AVAILABLE | PSX Data Portal / CSOR daily files, free and official; the 5-year backtest backbone |
| `intraday_ohlcv` | DEGRADED | No free historical PSX intraday archive; bars are captured forward only, artifacts kept 90 days |
| `footprint` | UNAVAILABLE | No PSX Level-2 or tick bid/ask history exists in any free source; the footprint engine stays disabled |
| `market_breadth` | DEGRADED | Derivable from daily OHLCV; richer breadth only as intraday capture accumulates |
| `corporate_actions` | DEGRADED | PSX publishes notices; no parsing pipeline exists yet, so conservative defaults are used |

### 3.2 Intraday capture

Two collectors exist, both read-only.

**`src/data/ohlc_poller.py`** is the one the scanner reads:
`https://vt.eclear.com.pk/pero/GetOHLCData?scrip=SYM&market=REG&check=symbol&interval=1`.
Each response carries the full day of one-minute bars (`SYM;REG;o;h;l;c;HH:MM` joined
by `|`), so a slow rotation never loses bars: every pass re-fetches the day and only
new bar times are banked. Requests are paced at 1.2s or more, an older TLS context is
needed for these hosts, and bar rows are rejected when prices are not finite and
positive, when `high < max(open, close)`, when `low > min(open, close)`, or when a
timestamp repeats with a different value. A bare acknowledgement such as `OGDC;REG;`
is rejected as a failed symbol. Banked to `data/feed_capture/ohlc_YYYYMMDD.ndjson`
plus a heartbeat `ohlc_status.json`, and a `ohlc_low_coverage.flag` when a pass fails
coverage.

**Measured on 2026-10-09 between 10:17 and 10:45 PKT, inside the Friday session**: the
source returned HTTP 200 with that bare acknowledgement and zero bar rows for OGDC,
PRL, ATRL and LUCK, at 1, 5, 15, 30 and 60 minutes, for REG, REGULAR, FUT, IND and ODD
markets, with browser and okhttp headers, with Referer and cookies, as POST form, and
it echoed a nonexistent scrip the same way. It also never carried volume in the past.
That is the single blocking fact in this project.

**`src/data/feed_capture.py`** records the broker's own feed socket (MKT-FEED plus the
EXS-FEED index subscription and a HELLO keepalive, nothing else, enforced by a
`guard()`). It is read-only by construction: three outgoing frame types, no login, no
credentials, no order messages. Tick fields map at index 0 scrip, 2 last, 3 bid, 6 ask,
8 change, 16 total volume, 19 open. It does not feed the scanner (it banks ticks for a
future footprint archive that the registry still calls UNAVAILABLE).

`src/data/capture_health.py` interprets heartbeat files without trusting stale
liveness flags: STOPPED, STALE, UNKNOWN, RUNNING, derived from heartbeat age and PID.

### 3.3 The scanner

`src/signals/momentum_scanner.py` (687 lines) is the only place in the repository that
decides whether a stock is a candidate. Its pipeline is: load capture, assess quality,
build market context, score every symbol, rank, select one. It returns a `ScanResult`
with `DATA_BLOCKED`, `NO_TRADE` or `TRADE`, the full `QualityReport` (coverage, fresh
coverage, missing and stale symbols, duplicates, malformed, impossible OHLC, zero-volume
bars, newest and oldest bar, data age, source name, scanner version), the top ten ranked
candidates, and a coverage string. Message builders live in the same module so the
Telegram text and the app text can never drift: `signal_message`, `no_trade_message`,
`scan_blocked_message`, `target_hit_message`.

Two older engines remain in the tree and are not on the intraday trading path. The
opening-range engine `src/signals/intraday_engine.py` is read by exactly one live
consumer, the frozen research gate (`src/research/forward_validation.py`, which takes
its candidate rules and TP/SL constants), and its own test is retired to
`legacy/retired_scanners/test_intraday_engine_retired.py`. The daily engine
`src/signals/engine.py` is still genuinely used, by the post-close daily push
(`src/signals/signal_push.py`) and by the trade-matrix builder
(`scripts/build_trade_matrix.py`), so it is research and status machinery rather than
dead code. `tests/test_rebuild_schedule.py` asserts that the orchestrator never
mentions the retired intraday engine.

### 3.4 The daily state machine

`src/signals/trade_state.py` holds one persisted state per Karachi trading date in
`data/forward/session_state.json`, appended to `data/forward/session_journal.jsonl`
when a day closes. States: MARKET_CLOSED, MARKET_OPEN, SCANNING, CANDIDATE_FOUND,
TRADE_ENTERED, TARGET_MONITORING, TARGET_HIT, TRADE_CLOSED, DAILY_LOCKED, DATA_BLOCKED.
`can_enter()` requires an open state **and** an unused allowance, so exactly one entry
per day is possible, and it survives a process restart because it is on disk. A blocked
day does not consume the allowance, and a blocked day can never erase a taken trade. A
target hit keeps the bot online and locked.

### 3.5 The orchestrator

`scripts/intraday_pipeline.py` contains no strategy logic. Two modes:

`--scan --slot HH:MM` (slots 10:00, 11:30, 13:00, 14:30, 16:00):
1. refuse to run outside the configured session (SO-8), returning `OUTSIDE_SESSION`;
2. load the state, begin session and scan (incrementing the scan counter);
3. load the capture and assess quality; on `DATA_BLOCKED` record the reason and
   coverage, write the observation, send the SCAN BLOCKED text as an ops alert, stop;
4. otherwise check an open position against the target, and if hit, record and send
   TARGET HIT;
5. if a trade is allowed and the scanner found one, enter it at the observed last
   price, record the target from that price, and send the signal;
6. if a trade was already taken, the day is reported as TARGET_MONITORING or
   DAILY_LOCKED and a new candidate is recorded as observed and refused, never presented
   as actionable;
7. otherwise NO TRADE, recorded and delivered.

Every pass writes `data/forward/observation.json` with the quality report, the market
context, the ranked top ten, the trade state, the universe size and fingerprint, the
scanner version and the full config snapshot.

`--finalize` (after the close) values the paper position, labels the outcome
(`TARGET_HIT`, `CLOSED_AT_SESSION_END`, `UNVERIFIABLE` when an open position cannot be
valued from real bars, or `NO_CANDIDATE`), computes minutes held, writes
`data/forward/daily_outcome.json` and `data/forward/production_gate.json`, and appends
the session record to the journal. Costs are not modelled here, so net equals gross at
this stage, and the record says so.

### 3.6 The forward research gate

`src/research/forward_validation.py` implements the frozen evidence gate for the
registered candidate library (five small candidates from the retired intraday engine:
30-minute opening-range breakout variants, one 60-minute, with and without the
relative-strength floor, breadth gate and extension caps). Rules:

* labels are computed strictly after the decision bar, stop-first when one bar touches
  both levels, with a stop gap filling at the bar open when it is below the stop;
* costs: 22.4 basis points per side (commission, SST, levies), 10 bps slippage per
  side, 15% CGT on positive net returns;
* 60 discovery sessions, then 60 validation sessions, then 60 locked out-of-sample
  sessions, selected by discovery plus multiplicity-adjusted validation only;
* pass conditions include at least 40 OOS trades, positive net expectancy, a positive
  adjusted lower bound, profit factor at least 1.10, top-ten-symbol share at most 60%,
  drawdown at most 15%, worst streak at most ten, and no more than 50% expectancy
  degradation from validation;
* after passing, production is monitored on the latest 20 outcomes and demoted
  automatically on non-positive expectancy, drawdown above 10%, a losing streak of
  eight or more, or loss of source confirmation;
* failed cohorts freeze rather than retune.

Current gate (live, read from the relay at 12:41 PKT): `RESEARCH_INSUFFICIENT_DATA`,
`eligible: false`, `sessions_required: 120`, `sessions_collected: 0`,
`live_signal_enabled: false`, `paper_observation_enabled: true`.

### 3.7 Notifications

Two delivery paths, both through the relay (Telegram is blocked inside Pakistan, SO-9).

**Edge crons** (in the worker, independent of the PC): the owner's fixed texts at
09:32 / 15:30 Monday to Thursday and 09:17 / 16:30 Friday. Texts are exact:
"Market is open. Quant is online now." and "Market is closed. Quant is sleeping now."
The worker re-derives Karachi time from a fixed UTC+5 offset and re-checks the schedule
edge within a two-minute window, so a one-minute cron drift still sends exactly once.

**Local scheduler** (`src/notify/schedule_runner.py`, owner's PC only, SO-4): sleeps
until the next event from `src/data/sessions.py`, delivers through the relay, journals
every attempt to `data/notify_log.jsonl`, retries after two minutes on failure, and
never invents a success. A missed moment is simply missed, not faked.

`src/notify/telegram.py` is the direct notifier for local use (env or `.env` token,
three retries, fail closed, token masked). `scripts/ops_alert.py` turns a low-coverage
flag or a failed push into exactly **one** deduped Telegram message per day (the relay
dedupes `kind: "ops"` on UTC date plus a text digest), which is how the scheduled jobs
stay green instead of mailing GitHub failures.

### 3.8 The relay worker (`cloud/worker.js`, 617 lines)

| Route | Gate | Purpose |
|---|---|---|
| `GET /health` | public | liveness, Karachi clock, next event, pairing state, `market_open` |
| `GET /market` | public | KSE100 points/percentage plus the top three KMIALL stocks by current session volume, five-minute cache |
| `POST /market` | admin | stores a snapshot built by `python -m src.data.market_snapshot --push` |
| `POST /pair/start`, `POST /pair/confirm` | admin | two-step Telegram pairing with a 4-digit code in KV |
| `POST /notify` | admin | delivers to the paired chat; `kind: "ops"` is deduped per day |
| `GET /signals`, `POST /signals` | admin | the phone app's signal card |
| `GET /updates` | admin | raw `getUpdates` proxy for debugging |
| `POST/GET /research/observation`, `/research/outcome`, `/research/history`, `/research/claim`, `GET/POST /research/gate` | admin | the frozen research archive (write-once keys, two-year retention) |

KV keys in use: `PAIRED_CHAT_ID`, `PENDING_CODE`, `PENDING_CHAT`, `SIGNALS`, `MARKET`,
`ALERT:<utc-date>:<digest>`, `RESEARCH:OBS:<date>:<slot>`, `RESEARCH:OUTCOME:<date>`,
`RESEARCH:SENT:<date>`, `RESEARCH:PRODUCTION_GATE`.

Crons (UTC): 04:32 Monday to Thursday and 04:17 Friday open; 10:30 Monday to Thursday
and 11:30 Friday close.

`/market` parses two PSX Data Portal pages server-side. The KSE100 panel
(`data-close`, the signed change line, the `change__text--pos/neg` class, `data-date`),
and `/indices/KMIALLSHR`, the index's own constituent table, whose current session
VOLUME column decides the ranking. Membership comes from the exchange's own list, never
from a hardcoded one, and a member that has not traded is excluded rather than ranked.
The same parsing exists in `src/data/market_snapshot.py` for the local runner, and
`tools/worker_check.py` checks the two implementations against each other on live
markup.

### 3.9 The Android app

Four source files: `MainActivity.java` (console), `Watcher.java` (network, state,
notifications), `StatusService.java` (manifest facade), `PollReceiver.java` (alarm and
boot re-arm).

Layout, top to bottom: brand header with the gear; gold rule with diamond; SYSTEM
STATUS card (pill plus the Karachi clock); LATEST SIGNAL card; gold rule; hidden
SETTINGS panel; MARKET NOW card (KSE100 line, the three volume leaders with volume and
price, and a footnote naming the basis, the index timestamp and the KMIALLSHR member
count); spacer; closing gold rule.

Rules encoded: the pill reads ONLINE with a green check only when a session is live and
the relay answers, otherwise OFFLINE with a red cross; relay reachability is tracked
separately so a market close never fires the "unreachable" alarm; notifications go out
for relay up/down, market open/close (the owner's texts, in the app's own wording),
and new signals; "No signal today" and informational notes never ring the phone; the
watchdog re-arms every 5 minutes and survives a reboot.

Build: no Gradle and no Android Studio. `aapt2` compiles and links the resources, `javac`
against the platform-30 `android.jar`, D8 produces `classes.dex`, `uber-apk-signer`
signs with the local debug key (v2 and v3). Documented in `android/README.md`, output
goes to the Desktop as `QuantOfRehan-v1.5.0.apk`.

### 3.10 CI (three workflows)

**governance-guard.yml** (`pull_request` only, 2-minute cap): governance check with the
PR commit range, the full unit test suite, and `node --input-type=module --check <
cloud/worker.js`, so the worker's syntax is verified in CI even though this PC has no
Node.

**intraday-capture.yml** ("KMIALL intraday momentum scan"): crons 05:00, 06:30, 08:00,
09:30 UTC every weekday (10:00, 11:30, 13:00, 14:30 PKT), 11:00 UTC Friday (16:00 PKT),
and finalize at 10:45 UTC Monday to Thursday and 11:45 UTC Friday. Steps: install
pandas/numpy/requests, one full `ohlc_poller --once` pass, then the scan or finalize,
then a deduped ops alert when the capture was degraded, then a run summary in the job
step summary, then artifacts (observation, outcome, gate, journal, state, captured
bars) retained 90 days. Job timeout 10 minutes; the file states about 1,300 minutes a
month, inside the 2,000-minute ceiling.

**signal-push.yml** ("daily signal push"): crons 13:45 UTC Monday to Thursday, 14:45
Friday, and 03:45 UTC Tuesday to Saturday (08:45 PKT safety net). It fetches a bounded
100-day EOD window (never a full crawl, enforced in `build_eod_history.py`), filters it
to the universe, and pushes the fail-closed verdict to the app card and Telegram;
a failure raises one deduped ops alert instead of a GitHub failure mail, and the next
slot retries. Combined scheduled ceiling claimed: 1,840 minutes a month.

### 3.11 How governance is enforced mechanically

`scripts/check_governance.py` (246 lines) runs on every PR and checks: secret-shaped
strings (`gho_`, `ghp_`, `github_pat_`, Cloudflare `cfut_`, Telegram bot tokens, broker
passwords) in changed files; the footprint honesty statement; the presence of the
standing orders in `GOVERNANCE.md` and CI; banned dash characters in files and commit
messages; owner-only commit identity with no bot or co-author trailers; and the SO-8
Karachi pin rule (any `src/*.py` that mentions a clock time and a session/market word
must carry both "UTC+5" and "Asia/Karachi"). SO-4 is enforced in code: the 5-year crawl
refuses to run in CI.

---

## 4. Data assets on this PC (all gitignored under `/data/`)

| Asset | Size | Date | Notes |
|---|---|---|---|
| `eod_history.csv.gz` | 12.8 MB | 2026-10-06 | Raw PSX Daily Downloads crawl (full market, OHLCV with high/low) |
| `eod_history_kmi.csv.gz` | 5.2 MB | 2026-10-06 | The same, filtered to the KMIALL universe: the backtest backbone |
| `eod_history_signal.csv.gz` | 376 KB | 2026-10-07 | The CI window file used by the daily push |
| `trade_matrix.parquet` | 20.3 MB | 2026-10-07 | 74,654-row causal trade matrix with provenance sidecar |
| `event_study/events.parquet` | 56.6 MB | 2026-10-08 | Event study panel with reports and a walk-forward check |
| `research_phase1/`, `research_phase2a/`, `phase2b_report.json` | 0.16, 0.73, 0.08 MB | 2026-10-06 to 07 | Phase 1 matrix, Phase 2A candidate identification, Phase 2B stop/TP objective |
| `legacy_sentinel/` | about 20 MB | 2026-10-05 | The quarantined sentinel corpus: 177 sessions, 305 KMIALL symbols, snapshots, sweep panels, logs |
| `feed_capture/capture_20261006.ndjson` | 84.6 KB | 2026-10-06 | The single genuine socket capture (that day's ticks) |
| `feed_capture/ohlc_status.json` | 0.3 KB | 2026-10-09 10:28 | Poller heartbeat from the last pass |
| `forward/*.json` | 7 KB | 2026-10-09 12:30 | Local mirror of observation, outcome and gate. **Currently test artifacts, see defect 1** |
| `relay_url.txt`, `relay_kv_id.txt` | tiny | 2026-10-09 | Relay endpoint and KV namespace id |
| `stop_tp_grid/`, `entry_metrics_report.json`, `backtest_smoke*.json` | small | 2026-10-04 to 06 | Stop/TP surface, entry-quality study, smoke backtests |

Headline research numbers already banked: the 5-year placeholder-baseline backtest
(entry rule: close above MA20 with volume above the 20-day median) gives -1.06% net
expectancy per trade and a 27.487% positive-net rate, and the verdict belongs to that
placeholder rule, not to the owner's law. The entry study over 272,835 clean next-open
entries reports +2% reachable within three bars in 59.6% of entries while 78.1% touch
-1% intraday, which is why stop placement is called the binding constraint.

---

## 5. Live state at 12:45 PKT on 2026-10-09

*(Historical reading, kept as written. Section 12 carries the 2026-10-10
state and resolves the defects listed below.)*

| Where | Reading |
|---|---|
| Relay `/health` | ok, Karachi 12:17 PKT, `market_open: true`, paired |
| Relay `/market` | KSE100 167,427.78, -14.12 (-0.01%), 313 KMIALLSHR members, top volume CNERGY 10,706,270 (Rs 12.50), TREET 10,602,778 (Rs 23.85), PRL 4,702,039 (Rs 91.62) |
| Relay `/signals` (app card) | still the **2026-10-07** text from the old stack, "No signal today: the v1 stack (regime x sweep_low x FVG-retrace) did not fire", labelled UNGRADED |
| Relay `/research/gate` | `RESEARCH_INSUFFICIENT_DATA`, 0 of 120 sessions, live signals disabled |
| Relay `/research/history` | 1 session stored |
| Relay `/research/observations?date=2026-10-09` | 0 |
| Intraday scans that banked anything | none: the scanner reports coverage 0/319 on the eClear tier |
| GitHub Actions today | two governance-guard PR runs only. The last intraday-capture runs were 2026-10-08 17:59 UTC under the **old** workflow name; the rebuilt schedule has not produced a run yet |

---

## 6. What works, end to end, today

Governance and its guard; the 185-test suite; the Karachi clock and schedule law with
its boundary tests; the momentum scanner and its blocked-versus-verdict separation; the
persisted daily lock including restart survival; the orchestrator's two modes; the relay
worker (all ten routes with their gates intact) and its four crons; Telegram pairing and
delivery; the deduped ops alerting; the phone app, its build, its badge rule and its new
market card; the PSX Daily Downloads EOD fetcher, its 5-year crawl and the backtest
engine with conservative fills, cost schedule and corporate-action screens; the frozen
research gate; the stock/TP grid, entry-metrics and phase studies.

## 7. What is blocked, and by what

**The strategy cannot run at all, because no configured source serves current-session
volume.** The eClear read tier carries OHLC only and, as measured today, no bars at all.
The old screener page publishes a 30-day average, which is a different quantity. The
honest state is `SCAN BLOCKED`, coverage 0/319, zero sessions banked, gate closed, live
signals off. Nothing in the system fabricates a way around it, which is the point.

Two consequences worth naming plainly:

* there is **no historical minute-bar basis** to learn from, so no adaptive model exists
  and none is pretended to exist. The journal is append-only session records, which is
  the right substrate for learning once sessions exist;
* the one genuine intraday session that survives as one-minute bars is 2026-10-06
  (32,639 bars, 298 symbols), and it exists only inside a GitHub Actions artifact with a
  90-day window, so it expires around 2027-01-04. Locally there is one socket tick
  capture from the same day (`data/feed_capture/capture_20261006.ndjson`, 84.6 KB), which
  is not a strategy sample.

A new fact from today's work: the PSX Data Portal's own **`/indices/KMIALLSHR`
constituent table does carry live per-symbol session volume**, which is how the phone
card now ranks the day's leaders. That is public, delayed, non-tick data and its rights
and latency are unconfirmed, but it is the first genuine volume-bearing source this
project has identified, and it is a candidate path out of the block.

---

## 8. Defects and risks found while writing this report

1. **The pipeline test overwrites the real forward-state files.** Running
   `tests/test_pipeline_paper_cycle.py` rewrites `data/forward/observation.json`,
   `daily_outcome.json` and `production_gate.json` in the repository root, because
   `trade_state.ROOT` is patched to a temp directory but
   `scripts.intraday_pipeline.FORWARD_DIR` is not. Verified by timestamp: all three files
   moved to 12:30:22 when only that test ran. The local file therefore currently claims
   a synthetic paper trade (OGDC entered at 103.6113, target hit at 105.9644) that never
   happened. Harmless to CI (the canonical record is the workflow artifact), misleading
   to anyone reading the local state. Fix: patch `scripts.intraday_pipeline.FORWARD_DIR`
   in the test's `setUp`, or route the file writes through `trade_state.ROOT`.
2. **The app's signal card is stale.** It still shows 2026-10-07 because the rebuilt
   orchestrator delivers SCAN BLOCKED and signal texts through `/notify` (Telegram) and
   never through `POST /signals` (the card). Either the orchestrator should also push the
   card, or the card should be retired in favour of the status and market cards.
3. **Universe drift.** The tracked snapshot holds 319 KMIALLSHR symbols; the live index
   table lists 313 today. The scan reports 319 expected, so coverage is measured against
   a slightly stale list. A refresh path (or a marker that the snapshot date is stale)
   does not exist.
4. **The relay's research archive is no longer fed.** The rebuilt orchestrator writes
   observations and outcomes locally and into CI artifacts; it never POSTs to
   `/research/*` (verified: the only "research" references in
   `scripts/intraday_pipeline.py` are the import of `evaluate_gate` and a docstring line
   on line 9 that promises a "research log" to the relay, which the code does not do).
   The KV archive holds 1 session and its gate is a snapshot from the earlier flow. The
   daily outcome and gate therefore exist only as a PC file and a 90-day artifact, which
   is weaker than the two-year KV retention the design documents describe.
5. **No run yet under the rebuilt schedule.** As of 12:38 PKT on 2026-10-09, after the
   06:07 UTC merge, the 06:30 UTC slot had produced no run. Either GitHub has not
   re-registered the new crons yet or something is wrong with the schedule; the first
   observation will settle it.
6. **One retired engine remains inside `src/`** (`src/signals/intraday_engine.py`),
   kept alive only by the frozen research gate and referenced nowhere else on the trading
   path, with its test quarantined under `legacy/`. `src/signals/engine.py` is a
   different case and is still used by the daily push and the trade matrix.
7. **Untracked work on the PC.** `scripts/condition_scan.py`, `scripts/event_study.py`,
   `scripts/walk_forward_check.py` and `legacy/eod/data/` are present but in no commit.
   They should be either committed with their reports or removed deliberately.
8. **Android alarm throttling.** A 5-minute watchdog is best-effort on Android; Doze and
   OEM battery managers can push it to roughly nine minutes or stop it entirely. The app
   refreshes on open and on resume, so the card is never stale while the owner is
   looking at it, but background pings are not guaranteed to be exactly five minutes.
9. **Costs are not modelled in the paper cycle.** `net_return` currently equals
   `gross_return` because no execution cost model is wired into the rebuilt path, while
   the research gate does model 22.4 bps per side plus slippage and CGT. Those two
   definitions of "net" will collide if the paper cycle ever feeds the gate.

---

## 9. How to operate it

```bash
# checks (same as CI)
python scripts/check_governance.py
python -m unittest discover -s tests

# the scheduled cycle by hand (paper only)
python scripts/intraday_pipeline.py --scan --slot 10:00
python scripts/intraday_pipeline.py --finalize

# what is the intraday source serving right now
python -m src.data.ohlc_poller --probe OGDC
python -m src.data.ohlc_poller --once --limit 5

# the phone card's data
python -m src.data.market_snapshot --show
python -m src.data.market_snapshot --push

# the relay in a browser engine (no Node on this PC)
python tools/worker_check.py     # then open tmp/worker_check.html

# relay lifecycle
python cloud/pair.py deploy      # upload worker, set crons and the workers.dev URL
python cloud/pair.py health      # live status

# notifications
python -m src.notify.schedule_runner      # local scheduler, foreground

# data and research
python scripts/build_eod_history.py --start 2021-10-04 --end 2026-10-02
python scripts/smoke_backtest.py --dataset data/eod_history_kmi.csv.gz
```

---

## 10. Open decisions for the owner

1. **Find a volume-capable intraday source.** This is the whole game. The portal's
   KMIALLSHR constituent table proves live volume is publicly reachable; a licensed or
   keyed minute source is the clean answer, and the rights and latency questions then
   need the owner's confirmation before the gate can ever open.
2. **Decide what the app's signal card should show** once the scan is running (today's
   blocked verdict, or the live paper trade and its target), instead of the stale text.
3. **Decide whether the relay's research archive should be re-fed** by the rebuilt
   orchestrator, so the two-year KV retention is real again.
4. **Fix or accept defect 1** (test overwriting local forward state) and defect 5
   (the schedule's first run) as small engineering items.
5. **Plan the artifact rescue** before the 2026-10-06 capture expires around 2027-01-04.

---

## 11. What I verified today, and what I did not

Ran and passed on the merged master: `python scripts/check_governance.py`, `python -m
unittest discover -s tests` (185 tests then, 233 after the 2026-10-10 work in section
12), `tools/worker_check.py` in the browser engine
(whole-file parse, parser parity with Python on live markup, all four session boundaries,
the `/market` contract, the five-minute cache, the admin gate, the 404 path), a live
deploy of the relay followed by HTTP checks of all ten routes, and an APK build whose
`classes.dex`, `resources.arsc` and manifest match the delivered file byte for byte.

Could not run here: the worker in workerd itself (no Node or wrangler on this PC; CI
does `node --check` on it, and the live relay answered every route after deploy), the
Android UI on a real phone, and the live market close at 16:30 PKT (the session law is
tested at that boundary but the live close was not observed). The 2026-10-09 scan
observation in the local `data/forward/observation.json` is a test artifact, per
defect 1, not a record of a real scan.

---
## 12. 2026-10-10: the AI prior, the local 5-minute runner, and the audit

Written after the work described here, from commands actually run on this PC
between 08:45 and 09:15 PKT on Saturday 2026-10-10 (market closed, so the
session paths were exercised on synthetic and pinned-clock sessions, and the
relay was read live).

### 12.1 What the repository state was when this session started

The previous attempt at "remove the dead code" had deleted six modules from
`src/` that live code imports:

| Deleted | Who actually imports it |
|---|---|
| `src/data/capture_health.py` | `src/data/feed_capture.py`, `src/data/ohlc_poller.py` |
| `src/notify/schedule_runner.py` | `src/signals/signal_push.py` (the daily push) |
| `src/notify/telegram.py` | `tests/test_telegram.py`, and it is referenced by `DATA_SOURCING.md` |
| `src/data/psx_eod.py` | `scripts/signal_daily.py` |
| `src/data/corpus.py` | `scripts/smoke_backtest.py` |
| `src/backtest/walkforward.py` | `tests/test_backtest.py`, `scripts/smoke_backtest.py` |

Proof it was broken, and not merely suspicious: importing
`src.data.ohlc_poller` raised `ModuleNotFoundError: No module named
'src.data.capture_health'`, and `src.signals.signal_push` raised the same for
`src.notify.schedule_runner`. All six were restored from HEAD, after which all
22 modules under `src/` import cleanly.

### 12.2 Dead code, done properly

`scripts/dead_code_audit.py` was added: it reports unreferenced modules,
unreferenced defs and unused imports, where the evidence for a definition is
that its name appears nowhere in the repository outside its own file. It only
reports; removal stays a decision. Its findings and the decisions taken:

- **No module under `src/` is unreferenced.** Every one is imported by
  something. The audit's only module-level hits are two CLI entry points
  (`dead_code_audit.py` itself and `install_kmiall_tick.py`), which nothing
  imports by design.
- **One dead def removed:** `historical_signals` in `src/signals/engine.py`.
  Nothing called it, and its docstring claimed "Used by the sanity backtest",
  which was not true.
- **Fourteen unused imports removed** across `src/` and `scripts/`, including a
  stale import of `walk_forward_splits` in `scripts/smoke_backtest.py` that
  would have re-broken that script had the deleted module stayed deleted.
- **Three dead defs left in place, in research scripts:**
  `bootstrap_ci_mean` (`scripts/research_phase1.py`), `relabel`
  (`scripts/research_phase2b.py`) and `surface_grid`
  (`scripts/stop_tp_grid.py`). They are unreachable, but those three files are
  frozen one-off research runs whose outputs are cited as evidence elsewhere in
  this report, and `scripts/` was outside the stated scope of the `src/`
  cleanup. The audit keeps reporting them so the decision stays visible rather
  than being quietly forgotten.
- **Two dead defs deliberately kept:** `parse_capture` and `scan_snapshot` in
  `src/signals/intraday_engine.py`. That module is the retired opening-range
  library, retained whole as the record the frozen research gate reads, with
  its tests quarantined to `legacy/retired_scanners/` and a test asserting that
  only `forward_validation.py` may import it. Removing pieces of a deliberately
  preserved historical module is not a safe removal.

### 12.3 AI-driven signals: one concrete path

"AI-driven signals" now means one auditable object:
`P(+2% before -0.5%, within 10 sessions)`, an L2 logistic regression over 19
causal daily features, trained by `scripts/train_signal_model.py` on
`data/event_study/events.parquet` and written to
`models/kmiall_signal_v1.json` as a readable coefficient vector.

| Property | Value, measured |
|---|---|
| Feature definition drift | 0.00% worst disagreement on 500 sampled rows, live featurizer vs research table |
| Training rows | 98,374 (entry dates before 2024-01-01) |
| Holdout rows | 179,872 (2024-01-01 onward) |
| Holdout AUC | 0.5615 |
| Base rate, holdout | 20.48% |
| Top-decile rate, holdout | 23.67% (+3.19 pp) |
| Eligibility rule | holdout AUC > 0.50 and holdout rows >= 5,000 |

That is a real but small edge, so the wiring matches the evidence:

- every candidate in an observation carries `ai_probability` and
  `ai_percentile`;
- a near-tie (rule scores within `AI_TIE_BAND`, default 2.0 points) may be
  reordered by the prior; a clear rule win is never overturned;
- the veto (`AI_GATE_ENABLED`) is **off by default** and, when on, refuses only
  the weakest `AI_REJECT_PERCENTILE` (25%) of that day's model ranking;
- the prior can refuse a candidate. It can never create, upgrade or score one;
- a missing, corrupt, feature-mismatched, ineligible or unreadable artifact
  disables the prior and states the reason. Too many missing inputs in a
  feature row yields no probability rather than an imputed guess.

One honest observation from the end-to-end rehearsal: on the synthetic Friday
session the rule winner (OGDC, score 64.36) sat at the **3rd percentile** of the
model's ranking, meaning the daily prior disliked the name the intraday rule
liked. With the veto off, that disagreement is recorded and ignored. That is
exactly why the veto ships off: the two horizons disagree, and the intraday rule
is the one with a live trigger.

### 12.4 The local 5-minute runner

Windows Task Scheduler, not an in-process loop, because a loop dies with its
shell and this project has already lost one that way. The task
`quant-of-rehan-kmiall-tick` runs `scripts/kmiall_tick.py` every 5 minutes all
day; the script decides everything else:

- **pause** outside the session, before the open, and during the first 20
  minutes after the open (the strategy needs 20 bars and three volume buckets);
- **one scan per 5-minute slot per day**, persisted in the session state, so a
  scheduler retry, a manual run or a woken laptop cannot double-scan;
- **a lock file** with a live pid, so two ticks cannot fight over the state
  file, and a stale lock (dead pid, or older than 15 minutes) is reclaimed;
- **capture refresh** with a 240 s timeout; a failure is recorded, the tick
  still scans (the scanner then reports a data failure honestly) and the exit
  code is 2;
- **one ops alert** after three consecutive capture failures, fired once at the
  threshold rather than every five minutes;
- **finalize exactly once** after the close, guarded by a persisted flag.

Card pushes are now idempotent: the pipeline stores a signature of the last
published card in the session state and does not republish an unchanged
verdict. Without it, a 5-minute runner would rewrite the same line seventy
times a session.

The runner and the prior are covered by 33 new offline tests
(`tests/test_kmiall_tick.py`, 20 tests: phases, slot guard, force rescan, live
lock refusal, stale lock reclaim, lock release, failed capture, health reset,
the once-only alert, slot recording, finalize once, and a failing scan exiting
3 with the lock released; and `tests/test_ai_model.py`, 13 tests: live-versus-
research feature equivalence, fail-closed loading of a missing, corrupt or
feature-mismatched artifact, monotone inference, refusal to answer with too
many missing inputs, percentile ranking, no-op without an active model, gate
inactive without a model, tie-break inside and outside the band, and that the
prior never invents a candidate).

Registered and exercised live: `schtasks` created the task, a forced run at
08:58:53 PKT returned **Last Result 0** (correctly paused on a Saturday), and
the task then kept firing on its own cadence while this report was being
written (observed at 09:08, 09:13 and 09:18 PKT, last result 0 each time) with
every entry in `logs/kmiall_tick.log` recording the pause. The definition is
available with `python scripts/install_kmiall_tick.py --show`.

### 12.5 End-to-end rehearsal through the real pipeline

Driven through `scripts/kmiall_tick.py` itself, with the real AI prior, the real
13 MB daily panel, the real orchestrator, a stubbed relay and every writable
path redirected into a temporary directory:

| Step | Result |
|---|---|
| Tick 1, in session (pinned 2026-10-09 10:00 PKT) | exit 0, status TRADE, candidate OGDC, reason "strongest current momentum plus volume; AI prior 0.118 (3% percentile)" |
| Relay calls from tick 1 | `/notify`, `/signals`, `/research/observation` |
| Prior cache | written, 308 symbols, panel 2026-10-05 |
| Tick 2, same slot | exit 0, **zero** new relay calls (idempotent) |
| Tick 3, post close | exit 0, finalized flag set, outcome TARGET_HIT, gross 0.02, net 0.011492 after costs and CGT, storage relay+local |
| Session journal | exactly 1 record |
| Owner's real `data/forward/` | untouched (empty), no stray lock |

The net-versus-gross gap is the cost model doing its job: 2 x (22.4 + 10.0) bps
plus 15% CGT on the positive result.

### 12.6 Live verification of the current state

- **Suite:** 233 tests and 62 subtests pass, exit 0, under both
  `python -m pytest tests -q` and `python -m unittest discover -s tests`. The
  run is offline; the Telegram and relay lines that appear after the summary are
  mocked failures flushed late from buffered stdout, not network calls.
- **Governance:** `python scripts/check_governance.py` passes (secrets, style,
  identity, SO-8 pin).
- **Imports:** all 22 `src/` modules import cleanly.
- **Remote:** GitHub `master` head is `0e6916a`, identical to this checkout, so
  the local tree is neither behind nor ahead of the remote.
- **Relay:** `/health` 200, `paired: true`, `market_open: false`, next event
  `OPEN at 2026-10-12 09:32`; `/market` 200; `/research/gate` 200 with
  `RESEARCH_INSUFFICIENT_DATA`, `eligible: false`, live signals off;
  `/research/history` 200 with 1 session (2026-10-08); an unauthenticated read
  is refused with 403.
- **Relay client gotcha, recorded so it is not rediscovered:** Cloudflare's
  browser integrity check answers Python `urllib`'s default user agent with
  HTTP 403 and the body `error code: 1010`, which looks exactly like a dead
  relay. `requests` and `curl` are both served normally.
- **Scheduler:** task registered, next run observed, last result 0.
- **`scripts/verify_market_signals.py`** was added to make all of the above one
  command. Its first live run reported 30 pass, 4 warn, 0 fail, 2 skipped.

### 12.7 Defect status against section 8

| Section 8 defect | Status on 2026-10-10 |
|---|---|
| 1. The pipeline test overwrites the real forward-state files | **Fixed.** The forward directory is derived from `trade_state.ROOT` at call time, and the new AI prior cache follows the same rule. It is asserted by `tests/test_pipeline_paper_cycle.py::assert_real_forward_untouched`, which caught a real violation of exactly this kind while this work was being written. |
| 2. The app's signal card is stale | **Partly fixed.** The orchestrator now pushes `/signals` on every verdict change. The card itself is still the 2026-10-07 text because no in-session run has happened since; the verifier reports it as two trading sessions behind. |
| 3. Universe drift | **Addressed as reporting.** `src/data/universe_refresh.py` diffs the tracked snapshot against the exchange's live KMIALLSHR table and reports the drift in both directions. It deliberately does not invent a refreshed universe; refreshing the snapshot stays an owner decision. |
| 4. The relay research archive is no longer fed | **Fixed.** `run_scan` and `run_finalize` now POST observations, the daily outcome and the gate to `/research/*`, and record the honest storage status (`relay+local` or `local-only`) in the local record. |
| 5. No run yet under the rebuilt schedule | **Not verifiable from here.** The repository is private and the API refuses unauthenticated run listings. The local 5-minute runner no longer depends on that schedule, and it was observed running on this PC. |

### 12.8 What is still wrong, and what I did not prove

- **The intraday data source is still the blocker.** The configured tier returns
  acknowledgement-only payloads with no volume, so the pipeline reports SCAN
  BLOCKED. Nothing in this work changes that; the AI prior does not make a
  volume-less feed usable.
- **The AI prior's panel is behind.** `data/eod_history_kmi.csv.gz` reaches
  2026-10-05, so the prior is computed from features several sessions old. The
  observation now records `prior_panel_as_of` and the verifier warns about it.
  Refreshing the EOD panel is a data task, not a code fix.
- **The AI model is weak.** Holdout AUC 0.5615 is a real edge and a small one.
  It is wired in as a bounded prior precisely so that this honesty is not
  laundered into an implied edge. It should not be promoted to a live veto
  until it has been retrained on a fresh panel and its top-decile lift still
  holds out of sample.
- **No live in-session run has happened with any of this.** Every session path
  was exercised with a pinned clock and synthetic bars. The first real
  confirmation is the next trading day's first tick after 09:52 PKT.
- **The local and cloud runners keep separate state.** Both archive to the
  relay, but their session locks are independent, so the same slot can be
  scanned twice in two places. That is tolerable for paper research, and it is
  stated in the README rather than hidden.
- **Android app:** unchanged, not rebuilt, not installed on a phone here.

### 12.9 Files added or changed on 2026-10-10

Added: `src/signals/ai_model.py`, `scripts/train_signal_model.py`,
`scripts/kmiall_tick.py`, `scripts/install_kmiall_tick.py`,
`scripts/verify_market_signals.py`, `scripts/dead_code_audit.py`,
`tests/test_ai_model.py`, `tests/test_kmiall_tick.py`,
`models/kmiall_signal_v1.json`.

Changed: `src/config.py` (AI routing and tick cadence),
`src/signals/momentum_scanner.py` (prior attachment, bounded tie-break,
optional veto), `src/signals/trade_state.py` (tick and card bookkeeping),
`scripts/intraday_pipeline.py` (AI component, idempotent card, prior
provenance), `README.md` (rewritten), `PROJECT_REPORT.md` (this section), plus
the fourteen unused-import removals and the one removed dead def.

Restored: the six modules listed in 12.1.

## 13. 2026-10-10, the typed boundary, the edge cases and a supervised loop

Requested as a deliverable: a technical report plus a production ready skeleton,
with strict type safety, error handling for API connectivity and data gaps, and
edge case coverage for market volatility. Sections 1 to 12 already describe the
runtime. This section adds the three things that were still missing around it,
and records the defects the new tests found in my own work.

### 13.1 Why a typed boundary and not another engine

This repository has exactly one scanner (`src/signals/momentum_scanner.py`) and
exactly one orchestrator (`scripts/intraday_pipeline.py`). The rebuild removed
four competing engines and the owner's law is that there is one. So the new
modules are ADAPTERS at the edges:

- `src/signals/contracts.py` (736 lines) holds the validated shapes of what
the scanner consumes and emits, and the fault taxonomy;
- `src/signals/volatility.py` (267 lines) measures the regime and the untradable
  edge cases, and picks nothing;
- `scripts/scan_loop.py` (589 lines) supervises interval scans and delegates
  every scan to the existing orchestrator;
- `examples/scan_once.py` (262 lines) is the usage example: one scan, offline,
  printing every layer of the decision path.

Nothing here scores a symbol. If any of these files grew a scoring rule it would
be the second engine this rebuild exists to prevent, so the boundary is stated
in each module's docstring as a rule rather than a preference.

### 13.2 Strict types, with pydantic optional

pydantic is installed on this PC (2.13.5) but is NOT in `requirements.txt`, so
treating it as a hard dependency would have broken CI. The contract layer is
therefore written as typed dataclasses with the invariants in `__post_init__`,
which is the same code path with or without the library, and the same classes
are re-decorated with `pydantic.dataclasses.dataclass` when it is importable.
`PYDANTIC_AVAILABLE` and `MODEL_MODE` report which mode is live.

`tests/test_contracts.py::FallbackModeTest` runs the models in a subprocess with
pydantic blocked at import time and asserts that the invariants still fire, so
the fallback is tested rather than assumed. Invariants enforced at construction:
positive finite prices, `high >= max(open, close)`, `low <= min(open, close)`,
tz aware timestamps, volume finite and non negative, scores inside 0 to 100,
probabilities and percentiles inside 0 to 1, coverage as a real fraction, and no
more symbols with bars than symbols expected. `ScanOutcome` additionally refuses
a TRADE with no candidate and a non TRADE that carries one.

### 13.3 Faults are typed, not matched by strings

String matching on a human readable reason is how a retry policy gets decided by
accident. Every blocked scan now maps to a typed `ScanFault` subclass with its
own `retryable` flag: `InsufficientCoverage`, `StaleFeed`, `VolumeUnavailable`,
`SourceUnavailable`, `MarketClosed`, `ScanAborted`. The mapping is one function,
`fault_from_quality`, and callers branch on the class. The loop counts faults by
class in its health file, so a night of failures reads as a histogram rather
than as text to be reread.

The ingestion edge (`validate_bar_rows`) is the strictest place: every refused
row is counted against a typed reason (malformed, impossible OHLC, non positive
price, not finite, future bar, wrong session, naive timestamp, negative volume,
duplicate conflict), nothing is repaired, interpolated or forward filled, and a
feed that is mostly refusals is raised as a source fault with the histogram
attached rather than reported as a thin market.

### 13.4 Volatility regimes and edge cases, off by default

The scanner decays late moves multiplicatively but has no idea whether the
session is calm, violent or broken. `src/signals/volatility.py` adds that
reading from the bars themselves: average true range as a share of price,
bucketed into calm, normal, elevated and extreme; realised volatility; the gap
from the previous close; the intraday high to low swing; and a typed set of edge
cases (limit locked prints, flat and repeated bars, a zero range session, a thin
sample, a stale last bar, gap up or down, an extreme swing, missing volume).
Under ten bars it returns UNKNOWN instead of guessing.

Two behaviours are wired but deliberately OFF, both as flags in `src/config.py`:
`VOLATILITY_AWARE_TARGETS` scales the +2% target by regime, and
`VOLATILITY_VETO_ENABLED` refuses the objectively untradable cases. With both
off, `target_multiplier` returns exactly 1.0 and the live strategy is byte for
byte the one described in section 2. They exist so the owner can turn them on
with evidence, not so this work can change the rule quietly.

### 13.5 The supervised loop

Section 12.4 registered a Windows Task Scheduler tick because a loop in a shell
window dies with the shell. `scripts/scan_loop.py` is the second supported way
to drive the same orchestrator, for hosts where Task Scheduler does not exist:

- wake on a fixed interval with drift correction, so a slow scan does not push
  every later scan late;
- pause outside the session, before the open, in the warm up window, and after
  a finalize (a finalize sleeps until the next session rather than spinning on a
  closed market);
- exponential backoff with jitter on consecutive failures, reset by one
  success, and a stop after the configured streak instead of retrying into a
  dead feed for ever;
- classify every failure with the taxonomy above, never report a fault as a
  market verdict;
- a health file (`data/scan_loop_health.json`) with cycles, scans, pauses,
  faults by class, the consecutive failure streak and the last verdict and
  latency;
- SIGINT and SIGTERM stop the loop between cycles, never mid scan.

It duplicates no strategy: the slot label, the warm up window and the sessions
all come from `src/data/sessions.py` and `src/config.py`, and the scan itself is
`scripts/intraday_pipeline.run_scan`. The slot guard, the single trade lock and
the idempotent card push are therefore identical to the scheduled tick, which is
the point.

### 13.6 Three real defects the new tests found, and one the governance check did

1. **`str()` on a str mixin enum.** `str(Quality.OK)` returns `'Quality.OK'` on
   Python 3.11 and later, not `'OK'`, so a naive upper case coercion produced an
   invalid quality status. Found by the contract tests, fixed in `as_quality`
   and `verdict_from_status` by taking the last dotted component.
2. **A healthy locked day read as a failed scan.** Once the day has its one
trade the orchestrator reports a state name (`TARGET_MONITORING`), which the
   adapter was filing as ABORTED. That would have counted every healthy cycle
   after the trade as a fault and could have driven the loop into backoff during
   the only window that matters. Fixed with an explicit monitoring status set,
   surfaced as `Verdict.MONITORING` with `fault()` returning None.
3. **`run_cycle` returned no outcome.** Every path returned `None` for the
   outcome, so `--once` printed a fallback line instead of the verdict. The
   tests had only asserted loop health, which is why they missed it. Now
   asserted directly, including the printed verdict through `main(["--once"])`.
4. **A silent timezone shift at the ingestion edge.** A bare `"10:01"` bar was
   stamped with the caller's offset, so any caller holding a UTC instant would
   have moved every bar five hours and turned a whole session into future or
   wrong session bars. Bars now carry the Karachi pin imported from
   `src/data/sessions.py`, and a naive scan instant is refused rather than
   guessed. The governance check is what surfaced this file at all, since SO-8
   requires the explicit Asia/Karachi UTC+5 pin in any module that mentions
   session times.

### 13.7 Verification

- **Suite:** `python -m unittest discover -s tests` runs 320 tests, OK, exit 0,
  offline. That includes 40 contract tests, 18 volatility tests and 29 loop
  tests, all new today.
- **Governance:** `python scripts/check_governance.py` passes (secrets, style,
  identity, SO-8 Karachi pin) after the pin fix in 13.6.
- **Example, run live:** `python examples/scan_once.py` prints, in order, the
  loaded config, the validation mode, the clock, the 319 symbol universe, the
  capture it used (synthetic here, because no real capture exists for that
  date), 14,355 bars accepted with 0 refused, the AI prior's provenance, the
  verdict `TRADE 10:02 AASM score 69.87 coverage 319/319`, the candidate with
  entry and target, and the volatility reading.
- **Loop against the real orchestrator:** a pinned-clock loop run pointed at
  the real pipeline (no stubs, real scanner, real capture directory, real
  forward state) returned `DATA_BLOCKED` for both cycles, mapped the failure to
  `SourceUnavailable` by class, and wrote the histogram
  `{"SourceUnavailable": 2}` with two scans and one consecutive failure. That
  is the same evidence path as the scheduled tick would produce, and it is the
  real operational state today: the feed is serving no usable bars.
- **Loop, run live:** `python -m scripts.scan_loop --once --skip-capture` on a
  Saturday decided `wait: CLOSED: no session` and wrote its health file, and
  `--status` printed the current phase, window and health without scanning.
- **One thing the rehearsal taught me:** pinning the loop's clock does not pin
  the scan instant, because the orchestrator reads its own clock. A pinned
  rehearsal therefore exercises the adapter and the taxonomy, but a genuine
  in-session TRADE through the loop can only be produced by a live session.
  The mocked TRADE payload in `tests/test_scan_loop.py` covers the adapter's
  happy path; the live session covers the rest.

### 13.8 What this does not fix

- The intraday feed is still the blocker (section 12.8). A typed boundary makes
  the failure louder and better classified. It does not make a volume less feed
  tradeable.
- The loop shares the local session lock with the scheduled tick but not with
  the cloud runner, so the same slot can still be scanned in two places.
- The volatility options are untested against real volatility, because no real
  capture exists yet. Their default off state is what keeps that honest.

Added: `src/signals/contracts.py`, `src/signals/volatility.py`,
`scripts/scan_loop.py`, `examples/scan_once.py`, `tests/test_contracts.py`,
`tests/test_volatility.py`, `tests/test_scan_loop.py`.

Changed: `src/config.py` (volatility flags and regime multipliers, off by
default), `README.md` and `PROJECT_REPORT.md` (this section).

## 14. 2026-10-10, the Friday break, the card's missing numbers, and a failure message with no cause

The owner reported three failures on the phone app and one on notifications.
All four are real, they had three different causes, and one of them was not a
code bug at all but a clock.

### 14.1 What the exchange actually does on a Friday

The app showed ONLINE at 14:23 on a Friday while the exchange was shut, with
trading resuming at 14:32. The exchange's own trading-hours page
(psx.com.pk/psx/exchange/general/trading-hours, read 2026-10-10) says Friday is
TWO sessions:

| Session | Pre-open | Matching break | Open | Close |
|---|---|---|---|---|
| Friday 1 | 09:00-09:15 | 09:15-09:17 | 09:17 | 12:00 |
| Friday 2 | 14:15-14:30 | 14:30-14:32 | 14:32 | 16:30 |

Monday to Thursday is one session, 09:32 to 15:30, which the owner's law
already had right. The Friday midday break is 12:00 to 14:32, so 14:23 is
inside a closed exchange and 14:32 is the reopen. The repository even had a
sentence about it in INTRADAY_FORWARD_SYSTEM.md ("Friday's midday break is
skipped") while no code modelled it: sessions.py described Friday as one
continuous 09:17 to 16:30 window, and the worker, both local runners, the
scanner guard, the cron tables and the app all inherited that single window.

Independently confirmed from the other side of the wire: the broker feed's own
reconciliation report notes that "during the Friday lunch break only the index
snapshot flows", and a live capture run during a shut market received exactly
that, EXS-FEED plus movers and stats frames and zero per-symbol ticks.

### 14.2 One session law, expressed as bands

`src/data/sessions.py` now describes a trading day as BANDS, not one window:

```
Monday to Thursday : ((09:32, 15:30),)
Friday             : ((09:17, 12:00), (14:32, 16:30))
Holidays, weekends : no bands at all
```

and answers every question with one function, `market_phase(now)`:

| Phase | Meaning | Pill |
|---|---|---|
| CLOSED | weekend or PSX holiday | OFFLINE |
| PRE_OPEN | a trading day, before the first band | OFFLINE |
| WARMUP | inside a band, within its first N minutes | ONLINE |
| OPEN | inside a band | ONLINE |
| BREAK | between two bands on the same day | OFFLINE |
| POST_CLOSE | after the last band | OFFLINE |

`is_market_open` is exactly OPEN or WARMUP, so a break, a weekend, a holiday
and the hours before the open are all offline by construction rather than by
six separate call sites remembering. `market_state(now)` returns the phase
plus the live band, the day's bands and the next band edge, which is the block
the relay serves and the app renders.

The warmup applies per band, so the reopen at 14:32 gets its own 20 minutes of
bar building before the strategy may score anything. That is the same rule the
morning open already had, applied to the second session instead of skipped.

### 14.3 Where the phase had to reach

Every consumer was moved onto the one law, and each has a test:

| Consumer | Before | Now |
|---|---|---|
| `src/data/sessions.py` | one window per day | bands, phases, market_state, band-aware next_event |
| `scripts/kmiall_tick.py` | its own phase maths | `sessions.market_phase`, and BREAK pauses the tick |
| `scripts/scan_loop.py` | its own phase maths | the same call, and BREAK waits |
| `scripts/intraday_pipeline.py` | open <= now <= close | `is_market_open`, so a scan inside the break is refused |
| `cloud/worker.js` | one window (09:17-16:30 Friday) | the same band table, `market_state` on /health and /market |
| `cloud/pair.py`, `wrangler.toml` | 4 crons | 6: Friday gains a 12:00 close and a 14:32 reopen |
| `.github/workflows/intraday-capture.yml` | 13:07 PKT scan on Friday too | 13:00 slot is Mon-Thu only; Friday's afternoon comes from 14:37 |
| Android `Watcher`/`MainActivity` | market_open flag only | renders the relay's phase, with a sentence per phase |

The Android app never decides the session against its own clock, which is the
property that makes all of this safe: the relay answers, the phone renders.

One more precedence rule is pinned by a test: in the `/market` response the
relay's own `market_state` is applied AFTER a snapshot pushed by the PC, so a
local push owns the market DATA (index, leaders, split) while the edge owns
whether the exchange is OPEN. A PC whose clock has drifted can therefore not
report ONLINE during the Friday break.

### 14.4 The card: a percentage that was parsed and thrown away, a footnote that made no sense, and a split that needs a real source

1. **The day's percentage per leader.** The parser read `change_pct` out of the
exchange's constituent row and then dropped it on the floor when building the
leader rows, so the app had nothing to display. It is now carried end to end,
and the card renders `▲ 1.05%` in green or `▼ 2.14%` in red per stock.
2. **The footnote.** The old line was `volume: today, top of 313 KMIALLSHR
members`, which read as a truncated sentence and never said how many leaders
were shown. The relay's own accurate sentence is now used ("current session
volume, top 3 of 313 KMIALLSHR members"), with the same sentence rebuilt
locally from the same numbers when the relay's is missing. The 313 itself was
never wrong: the live KMIALLSHR table returns 313 members today.
3. **The buy/sell/total split.** The owner asked for `B=`, `S=` and `T=` per
stock. No configured source publishes that split: the exchange's constituent
table has one VOLUME column (verified against the live page: 11 columns,
index 8 is the only volume), and the broker's OHLC endpoint returns bars only.
The split genuinely exists in the broker's MKT-FEED tick stream, whose field
map carries `direction`, `last-trade volume`, `bid`, `ask` and the symbol's
cumulative `total volume`.

`src/data/tick_volume.py` computes the split from that stream and refuses to
invent the rest:

  * only MKT-FEED frames are counted. The same capture file holds index,
    movers and market-stats frames whose fields are a different layout, and
    counting them would have fabricated a 45,745,000 share buy from a
    market-stats row (the mislabelling is fixed in feed_capture too);
  * a side comes from a recognised direction token, or from the tick rule
    against the quoted bid and ask, or the trade is reported unclassified;
  * the per-side sums are cross-checked against the symbol's own cumulative
    total, and a partial capture is labelled as a floor rather than passed off
    as the day;
  * no capture, or no ticks for that stock, renders as `T=` only with the
    reason in the footnote. A made up buy/sell ratio would be a lie about the
    tape (SO-3).

The card reads `1. CNERGY   B=12,345  S=9,876  T=22,221   Rs 12.52   ▲ 1.05%`
when the split is real, and `1. CNERGY   T=27,276,548   Rs 12.52   ▲ 1.05%`
with "buy/sell split unavailable: no broker tick capture banked for ..." when
it is not.

### 14.5 The Telegram failure: the message was the bug

`signal-push.yml` keeps the scheduled run green and reports failures through
one deduped Telegram ops alert. The alert said only that "the daily signal push
failed this slot". Four separate defects made that message useless or missing:

1. **No cause in the alert.** The job's output was never captured, so the
   reason lived in a GitHub log the owner does not read. The workflow now
   captures the run output, appends the last lines to the alert, and writes the
   same reason into the run summary, which is readable even when the relay
   itself is what is broken and no Telegram message can be delivered.
2. **The alerting script could not find the token.** `ops_alert.py` read
   `RELAY_ADMIN_TOKEN` from the environment only, while every other module
   falls back to the repo `.env`. On this PC that printed "ops alert skipped:
   relay admin token is missing" and sent nothing. There is now one resolver
   (`schedule_runner.load_relay_admin_token`) used by the alert, the push and
   the snapshot publisher.
3. **No preflight and no retry.** A rotated token or an unpaired relay was only
discovered after the multi-minute EOD fetch. `signal_daily.py` now checks the
   relay and the token first and fails in seconds with a named reason, and
   `post_json` retries transient network failures three times before giving up.
4. **Every refusal now names its own fix** (403: the GitHub secret and the
   worker binding disagree; 409: not paired, run cloud/pair.py; 502: the relay
   reached Telegram and Telegram refused, check the bot token and the chat;
   503: the relay's store is down).

Live evidence, not a claim: with the token resolver fixed, a real deduped ops
alert through the relay came back `ops alert delivered`, and the new preflight
against the deployed worker returned ready (`/health` ok, paired true,
`/signals` accepted the admin token). The Telegram path is healthy. What was
broken was the direction of information on failure, and that is what changed.

### 14.6 Not a code bug, but worth recording: this PC's clock moved during the session

The verifier reported one FAIL, "session state agrees with the local clock:
relay=False local=True". The cause was not the session law, it was the clock:

| Observer | Reading at the time | Implies |
|---|---|---|
| PSX portal's own index panel | newest session 2026-10-09 16:50 | the exchange's last session was Friday 9 October |
| Cloudflare edge (the relay) | 2026-10-10 10:26 PKT | real world: Saturday, weekend |
| this PC, at the start | 2026-10-10 09:49 PKT | agrees |
| this PC, mid-session | 2026-11-10 10:09 PKT | a month ahead: a trading day |
| this PC, while signing the APK | 2026-12-11 10:24 PKT | five weeks further ahead |
| this PC, at the end | 2026-10-10 10:35 PKT | agrees again |

So the machine's clock moved forward a month and then jumped back, and while it
was wrong the local runner treated a day the exchange did not have as a trading
day: it scanned, and recorded DATA_BLOCKED observations (three of them) for a
date that does not exist on the exchange's calendar. The app was never confused,
because the app renders the relay's phase rather than deriving one from the
phone's clock, and the relay's edge clock was right throughout. The Monday of
that period, 2026-11-09, is also a PSX holiday, so a local-only decision made on
the wrong date would have been doubly wrong.

This is worth stating as a hazard rather than a bug: any decision made from a
local clock is only as good as that clock, which is the reason the phone app,
the relay and the notification crons all read the session law against a clock
that is either the edge's or the exchange's, and why the runner's own status
file now prints the bands it thinks it is inside. I did not change the clock.

### 14.7 Verification

- **Suite:** `python -m unittest discover -s tests` runs 347 tests, OK, exit 0,
  offline (347 under pytest too, with 93 subtests). New coverage: the break law and its four edges, the second session's
  warmup, weekend and holiday closure, the scanner refusing inside the break,
  both runners delegating to the one law, the worker's band table (parsed out of
  worker.js and compared band for band), the six cron edges, the tick split
  (frame filtering, direction tokens, tick rule, unclassified trades, duplicate
  ticks, cumulative cross-check), the card's percentage and footnote, portal
  downtime, and the push diagnostics.
- **Governance:** passes (secrets, style, identity, SO-8 Karachi pin).
- **Android:** compiled with the local toolchain (aapt2, javac, D8), signed,
  versionCode 14 / versionName 1.6.0, and copied to
  `QuantOfRehan-v1.6.0.apk` on the Desktop as the release artifact.
- **Tick capture:** `python -m src.data.feed_capture` connected to all three
  feed hosts (`Welcome*%`) and an 80 second run banked the index, movers and
  stats frames and zero per-symbol ticks, which is what a shut exchange sends.

### 14.8 What is not done, and what only the owner can do

- **The relay still runs the old code.** `cloud/worker.js` now carries the band
  table and `market_state`, but deploying it needs wrangler (no Node on this
  PC) or `python cloud/pair.py deploy` with the Cloudflare token. Until then
  `/health` has no `market_state`, and the app falls back to `market_open` and
  shows no phase sentence. The pair script now also sets six crons.
- **`worker.js` cannot be executed on this PC.** There is no Node and no
  wrangler, so the relay's JavaScript is verified by parity (the band table and
  phase names are parsed out of the file and compared with the Python law) and
  by the live `/health` comparison after deploy, not by running it here.
- **The split has no live data yet, and its direction tokens are unconfirmed.**
  The field map is documented from the mobile client, but the token values on
  the wire are only observable in a live session; the engine reports the tokens
  it actually sees so the mapping can be completed from evidence. Nothing in
  the card fabricates a split in the meantime.
- **The capture is not yet a scheduled task.** It was started by hand and
  proved to connect; making it survive reboots needs a second Windows task in
  the style of `install_kmiall_tick.py`, and it must run during a live session
  to bank ticks.

Added: `src/data/tick_volume.py`, `tests/test_tick_volume.py`.

Changed: `src/data/sessions.py` (bands and phases), `scripts/kmiall_tick.py`,
`scripts/scan_loop.py`, `scripts/intraday_pipeline.py`, `scripts/signal_daily.py`,
`scripts/ops_alert.py`, `src/signals/signal_push.py`, `src/data/market_snapshot.py`,
`src/data/feed_capture.py`, `src/notify/schedule_runner.py`, `cloud/worker.js`,
`cloud/pair.py`, `cloud/wrangler.toml`, `.github/workflows/intraday-capture.yml`,
`.github/workflows/signal-push.yml`, `android/.../Watcher.java`,
`android/.../MainActivity.java`, `android/app/src/main/AndroidManifest.xml`,
`tests/test_rebuild_schedule.py`, plus the READMEs in this section.
