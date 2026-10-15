# Market scheduling and the sleep gate

How Quant of Rehan decides **whether a scheduled fire should do any work**, and
what keeps the 2,000 minute Actions ceiling and the Cloudflare edge quiet while
the exchange is shut.

Owner orders implemented 2026-10-10 (the sleep gate) and 2026-10-11 (the four
market states, the never-scan rule and the scan cadence: 30 seconds in the
cloud since the owner's order of 2026-10-14, SO-13; 4 minutes on the local
tick he can still ask for). Sources:
`src/data/session_gate.py`, `src/data/market_probe.py`, `src/data/sessions.py`,
`src/config.py`, `scripts/kmiall_tick.py`, `.github/workflows/intraday-capture.yml`.

---

## 1. The two layers, and which one decides

| layer | module | role |
|---|---|---|
| **session law** | `src/data/sessions.py` | **decides.** The exchange's published hours and the PSX holiday list, pinned to UTC+5 (SO-8). This is the only authority on whether a session is live. |
| **live probe** | `src/data/market_probe.py` | **verifies.** One bounded request to the exchange's own Data Portal, strictly to corroborate the law. It can never authorise work by itself. |
| **the gate** | `src/data/session_gate.py` | asks the law first, then the probe, and returns one typed decision. |

The asymmetry is deliberate and is the whole safety design:

- **A blocked, slow or unparseable portal can never silence a live session.** A
  probe failure degrades to *RUN, unverified*, the law still decides.
- **An unexpected closure can never be scanned as if it were trading.** A probe
  that positively reports the exchange shut (`SUSPENDED`, `Closed`) vetoes the
  scan.

## 2. Decision order

First match wins.

| # | Condition | Verdict | Network? |
|---|---|---|---|
| 1 | `--force` (a human dispatched the run) | **RUN** | no |
| 2 | weekend or PSX holiday | **SLEEP** | **no** |
| 3 | purpose is `finalize` and the day has closed | **RUN** | no |
| 4 | a scan in the pre-market or post-market window | **SLEEP** (owner order 2026-10-11) | **no** |
| 5 | outside every band (pre-open, Friday midday break, post-close) | **SLEEP** | no |
| 6 | inside a band, probe reports the exchange **open** | **RUN**, verified | 1 request |
| 7 | inside a band, probe positively reports **shut** | **SLEEP** (halt or delayed open) | 1 request |
| 8 | inside a band, probe **unreadable** | **RUN**, unverified | 1 request |

Only index 6 opens a socket and gets a scan. Everything else is decided from
the law alone, which is why an idle fire is cheap.

## 2.1 The owner's four market states, and where scanning is allowed

Owner order 2026-10-11. `market_state_at()` in `src/data/sessions.py` answers
one of four states for a timezone-aware instant; `is_scan_window()` is true
only in `MARKET`. Windows are half-open, `[start, end)`, so an instant exactly
on a boundary belongs to the window that starts there, never to the one ending
there.

| state | Mon-Thu | Friday | scanned |
|---|---|---|---|
| `PRE_MARKET` | 09:00 to 09:15 | 09:00 to 09:15 | **never** |
| `MARKET` | 09:32 to 15:30 | 09:17 to 12:00 and 14:32 to 16:30 | **yes, every 30 seconds in the cloud (owner order 2026-10-14, SO-13); every 4 minutes on the local tick** |
| `POST_MARKET` | 15:32 to 15:49 | 16:32 to 16:49 | **never** (finalize only) |
| `CLOSED` | everything else, including 15:30 to 15:32 | everything else, including 16:30 to 16:32 | no |

The 2-minute gaps after each close are `CLOSED` on purpose: 15:30:00 itself is
no longer the market, and post-market does not begin until 15:32:00.

The cloud's scan cadence is `config.SCAN_INTERVAL_SECONDS = 30` (owner order
2026-10-14, SO-13): `intraday-session.yml` runs `scripts/scan_loop.py` for the
length of each band, and the loop keeps the read-only broker tape alive so a
30-second cycle measures bars that already exist (2.9s measured on the real
2026-10-13 session tape). The local 4-minute tick keeps
`config.TICK_INTERVAL_MINUTES = 4`: the same 4 drives the Windows tick trigger,
the tick's slot guard and its 20-minute warm-up rule, so a rebuild or a fresh
clone still runs a local trial at 4 minutes with no environment change. The
slot guard is keyed on the runner's own cadence, because a 30-second runner
reported in minute slots would scan once a minute while claiming otherwise.

Whatever the cadence, the fire belongs to a **slot boundary**, not to "the
last fire plus the interval": `src/data/scan_scheduler.next_slot` owns that
grid, and `scripts/scan_loop.py` sleeps to it in both of its modes. A cycle
that spends 2.9s of a 30 second slot, or 9s of a 4 minute one, therefore does
not push every later fire late, and the slot label an observation carries is
the slot that fire actually worked in.

`scripts/scan_loop.py` has two ways to be driven and one way to decide:

| Mode | Who owns the clock | Who retries |
|---|---|---|
| `--loop` (the cloud's, SO-13) | the loop, sleeping to `next_slot` between cycles | the loop's own backoff and five-strike give-up |
| `--scheduled` (the non-blocking form) | `src/data/scan_scheduler.run_scanner_schedule`, on absolute wake targets | the scheduler, with jittered exponential backoff and exit code 3 |

Both modes run the same cycle body and the same pause table, so a scheduled
run and a synchronous run cannot disagree about when to scan, when to pause,
or what a verdict means. `tests/test_scheduled_scan.py` pins the grid and the
signal end to end on simulated market data.

Enforcement is layered, so no single edit can quietly re-enable pre-market or
post-market scanning:

0. **The job's own triggers exclude those windows, and they now live in the
   cloud.** Owner order 2026-10-11 asked for execution to be *disabled* in the
   pre-market, post-market and Friday break windows, not merely paused after
   the fact, so `scripts/install_kmiall_tick.py` derives its triggers from this
   same law: one repeating trigger per band (09:32 to 15:30 Mon-Thu; 09:17 to
   12:00 and 14:32 to 16:30 Friday) at the configured cadence, plus one
   post-market fire per trading day for the finalize (15:47 and 16:47 PKT),
   and nothing at all for 09:00 to 09:15, for 12:00 to 14:32 on a Friday, for
   the evening, the night or the weekend.
   `tests/test_kmiall_tick.py::SessionTriggerTest` still fails the build if a
   trigger ever lands outside a band. Owner order 2026-10-14 (SO-12) moved
   where those triggers run: the Windows task is disabled, the installer
   refuses to register it again, and the definition is kept as the written
   shape of the session law that the GitHub Actions crons mirror.
1. `market_state_at` is the law; the windows live in `src/data/sessions.py`
   beside the bands (SO-8).
2. `src/data/scan_schedule.py` is the one pause table both local runners read
   (`decide()` returns scan, finalize or wait and names the state that
   decided), so the tick and the supervised loop cannot drift apart on it.
3. `src/data/session_gate.py` refuses a scan in either window with an explicit
   row in the decision table above, *separate* from the band check.
4. `scripts/kmiall_tick.py` and `scripts/scan_loop.py` check the state before
   they scan; the tick reports `PRE_MARKET` and pauses, and treats
   `POST_MARKET` as finalize-only. Both are cloud-only since SO-12 (owner
   order 2026-10-14): a real process starting on the owner's PC is refused,
   and the GitHub Actions job carries the scanning.
5. `scripts/intraday_pipeline.py::session_legal` asks `is_scan_window`, so a
   hand-run `--scan` outside `MARKET` is refused too.
6. `tests/test_sessions_and_schedule.py::TestMarketStateLaw` pins every edge,
   including 09:15:00, 15:30:00, 15:31:59, 15:32:00 and 15:48:59;
   `tests/test_kmiall_tick.py::ScanWindowTest` and
   `tests/test_session_gate.py::TestOwnerScanWindowOrder` pin the refusals.

The finalize crons fire at 15:47 and 16:47 PKT, which is *inside* the
post-market window: a finalize values the session that has just closed and is
not a scan, so it still runs there. See section 3.

## 3. The finalize exception (why it cannot share the scan gate)

The workflow does two different jobs on the same clock:

- a **scan** is only meaningful inside a live band;
- a **finalize** is only meaningful *after* the last close, and its crons fire
  at **15:47** and **16:47 PKT**, inside the post-market window but outside
  every band.

Gating both on "is a band live" would have put the finalize permanently to
sleep and silently deleted the daily outcome. `--purpose finalize` therefore
runs on the law alone once the trading day has closed, and stays asleep before
it. `tests/test_session_gate.py::TestFinalizePurpose` pins this.

The cron → work mapping lives in `SCHEDULE_PLAN` in `session_gate.py` rather
than in YAML, so it is unit tested and the gate is the single authority on what
a given schedule event means. A test fails the build if that table and the
workflow's crons ever drift.

## 4. Measured cost of a sleeping fire

| | before the gate | with the gate |
|---|---|---|
| a fire outside the session | `checkout` → `setup-python` → `pip install` → **741s bar fetch** → scan | `checkout` → `setup-python` → **gate** |
| billed | **11-14 min** | **1 min** |
| wall clock, gate itself |, | **0.116 s** (measured locally) |

The gate sits after `checkout` and `setup-python`, so the interpreter is the
one the job pinned, not whatever the image happens to ship, but *before* the
`pip install` and the bar fetch. It depends on nothing but the standard library,
so it is deliberately not gated behind the install it is meant to avoid. The
whole prefix (`checkout`, `setup-python`, gate) is a few seconds, far inside the
one minute that billing rounds up to, so moving the gate behind `setup-python`
costs nothing measurably while removing a "which python is this?" failure mode.
It also means the exact command CI runs can be executed and checked locally.

**Honest scope of the saving.** Today's crons are already weekday-and-in-session,
so on a normal trading day every fire legitimately works and the gate saves
nothing. What it removes now is the **holiday and unscheduled-closure** waste , 
about **12 PSX holidays × 5 fires = 60 fires a year**, roughly 660 billed
minutes before and 60 after, so on the order of **50 minutes a month**. Its real
value is as the prerequisite for any denser cadence: at a 1, 5 or 15 minute
interval most fires land outside the session, and the gate is what makes those
cost one minute instead of fourteen. See `AUDIT_AND_CI_BUDGET_2026-10-10.md` for
why a 741 second fetch, not the quota, is the binding constraint.

### 4.1 The capture budget, and the pass that does not fit the cadence

The bar capture is one polite, sequential pass over the universe at the
source's own pacing: **319 symbols × (1.3s pacing + about 1.0s per request) ≈
734s, about 12 minutes**. That number is measured, not modelled: the CI job
logged 741s for exactly this pass.

Owner order 2026-10-14 moved the bar source off that pass. The eClear OHLC
servlet serves nothing now, so the bars a scan reads are built from the broker
tape (`src/data/tape_bars.py`), which needs ONE subscription for the whole
universe instead of a request per symbol: the arithmetic above is the
fallback's cost, not the bar path's. What the tape changes about the schedule
is that a bounded capture now has to be long enough to hold the history the
strategy ranks on, which is a bar-depth question, not a pacing one, and the
scanner reports it as DATA BLOCKED when the capture is too short.

Two consequences, both of which used to be silent:

1. **The local tick gave the capture a flat 240 second timeout**, so on every
trading day it logged `capture FAILED: capture timed out after 240s` and killed
the pass mid-flight (`logs/kmiall_tick.log`, 2026-11-10 and 2026-12-11 entries).
   The limit was smaller than the work. The capture now gets
   `cadence − reserve` (195s at the owner's 4 minute cadence) and **stops itself
   cleanly at that budget**, banking what it fetched, writing `pass_complete:
   false` into the heartbeat, and exiting with its own status so the caller can
   report a partial pass as a partial pass. The subprocess timeout is now only a
   backstop above the budget.
2. **A complete, fresh pass cannot fit a 4 minute cadence** on this source:
   734s of fetching against a 240s cadence, and a symbol fetched at the start of
   a pass is already past the 5 minute freshness floor by the end of it. This is
   arithmetic, not a tuning problem. It is why a partial capture is reported
   honestly rather than dressed up: with the source serving no bars at all
   (coverage 0/319, measured again on 2026-10-11) the scan reports
   `DATA_BLOCKED` either way. Resolving it needs either a faster fetch (bounded
   concurrency at the source), a smaller universe, a longer cadence, or a
   different intraday source, and each of those is the owner's call.

In CI the pass is bounded at 420s for the same reason: the job's timeout is 10
minutes and a 12 minute fetch meant every scheduled run was **cancelled before
it reached the scan step**. The bounded pass finishes, the scan step runs, and
the run bills about 8 minutes instead of 11 to 14.

## 5. Cloudflare

`cloud/worker.js` needed **no change**, and that is a verified finding, not an
assumption. Its `scheduled()` handler already:

1. returns immediately when `bandsFor(k)` is empty, which is the case for every
   weekend and every PSX holiday, because the worker carries the same holiday
   set; and
2. only sends a text inside `Math.abs(mins - edge) <= 2`, a two minute window
   around an open or a close, so a mid-session cron does nothing at all.

Verification: `python tools/worker_schedule_check.py`, then open
`tmp/worker_schedule_check.html`. It copies the worker's schedule functions
**verbatim** and runs them in the browser's own engine, because there is no
Node, Deno, Bun, quickjs or wrangler on this PC. Result on 2026-10-10:
**144 assertions, 144 passed, 0 failed**, covering a Mon-Thu day, a two-band
Friday, a weekend, a PSX holiday, and both sides of the ±2 minute tolerance.

Adding the portal probe to the worker was deliberately *not* done: the law is
the authority at the edge too, and an extra outbound call would only add compute
for no decision it is allowed to make.

## 6. Escape hatches

| Situation | Action |
|---|---|
| The portal is blocking or misleading and is vetoing real sessions | set `PSX_PROBE_ENABLED=false` (a repo variable in CI, an env var locally). The law alone decides and no socket is opened. |
| Need to run outside the session on purpose | `workflow_dispatch`, which passes `--force`. |
| Want the verdict without it setting CI outputs | `python -m src.data.session_gate --check --json` |
| See why the portal says what it says | `python -m src.data.market_probe --show` |

## 7. Verifying this system

```bash
python -m pytest tests/test_session_gate.py tests/test_market_probe.py -q   # 68 tests
python -m src.data.market_probe --show                                      # live portal
python -m src.data.session_gate --check --json                              # today's verdict
python tools/worker_schedule_check.py                                       # worker law parity
```

`tests/test_session_gate.py` walks a timeline across the weekend → Monday open
transition and asserts the verdict is IDLE at 09:31, ACTIVE at 09:32, ACTIVE at
15:29 and IDLE again at 15:30, and that the portal is consulted on exactly the
live slots and never while asleep. The probe suite asserts the parser against
the portal's real captured markup and that **every** socket failure, timeout,
DNS, HTTP 503, a reset, garbage bytes, returns UNKNOWN without raising.
