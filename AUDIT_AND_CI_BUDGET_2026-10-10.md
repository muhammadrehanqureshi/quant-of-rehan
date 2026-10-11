# Quant of Rehan, Audit & CI/CD Budget Report

**Date:** 2026-10-10 (Saturday, PSX closed)
**Scope:** local desktop checkout (`C:\Users\rehan\OneDrive\Desktop\quant-of-rehan`) and `muhammadrehanqureshi/quant-of-rehan`
**Method:** repo inspection + live GitHub Actions API measurements. Every number below is measured, not assumed; the raw evidence is in §3.

---

## 0. Headline

| Finding | Evidence |
|---|---|
| Test suite is **green** | `pytest tests/` → **348 passed, 115 subtests passed in 11.3s** |
| The headline CI job is **broken** | `KMIALL intraday momentum scan`: **3 of 3 runs `cancelled`**; the scan step was **skipped every time** |
| The job is not slow, **one step is slow** | the bar fetch is **741s of a 767s job = 96.6%**; the actual scan is **3s** |
| The 10-minute timeout is smaller than the work | successful pre-rebuild runs took **771-805s** against `timeout-minutes: 10` |
| Current burn | **~1,369 min/month (68%)**, and it buys a scan that never executes |
| If the timeout is raised so the job *can* finish | **~1,695 min/month (85%)** |
| Verdict on sub-15-minute cadences | **15 min = affordable. 5 min = marginal. 1 min = impossible** (arithmetic *and* GitHub's 5-minute cron floor) |

**Bottom line:** the GitHub Actions budget is not the constraint you think it is. The scanner does not currently work on Actions at all, and no amount of quota would let it run at 1-minute cadence. The fix is architectural, not financial.

---

## 1. Audit

### 1.1 Grounded health snapshot

`python scripts/verify_market_signals.py` → **23 pass, 2 warn, 0 fail, 2 skipped**

The two warnings are both real:

- `STATE session journal, no journal yet`, forward validation has no session records.
- `AI prior panel freshness, panel 2026-10-05 is 4 trading session(s) behind`, the ML prior is stale.

Also visible and correct: `tick cadence every 5 min, warmup 20 min`; scheduler task `quant-of-rehan-kmiall-tick` registered with `last result 0`; tick log shows a clean pause (`not a PSX trading day`), which is why the companion app reads **OFFLINE** right now.

### 1.2 Completed

- **Signal stack**, 24 modules under `src/`, covering capture, sessions/schedule, contracts, momentum scanning, intraday engine, volatility, trade state, signal push, and a bounded ML prior (holdout AUC **0.5615** on 179,872 rows, routed as a *bounded prior*, not an authority).
- **Test suite**, 348 tests + 115 subtests green in 11s.
- **CI/CD**, three workflows wired: intraday capture/scan, daily signal push, governance guard.
- **Relay**, Cloudflare Worker with KV, admin-gated `GET/POST /signals`, `/research/gate`, and a `scheduled()` handler that emits the market open/close texts.
- **Companion app**, Android watchdog (`Watcher`, `PollReceiver`, `StatusService`) with the status / latest-signal / market-now card layout shown in the screenshot.
- **Local always-on runner**, Task Scheduler registration (`scripts/install_scheduler.py`), the path that makes §2.7 possible.
- **Governance**, `GOVERNANCE.md` (SO-1…SO-8) enforced on every PR by `governance-guard`.
- **Code hygiene**, **zero** `TODO`/`FIXME`/`XXX`/`HACK` markers across `src/`, `scripts/`, `cloud/`, and the Android sources.

### 1.3 Pending / broken, severity ordered

| # | Sev | Item | Evidence |
|---|---|---|---|
| 1 | **P0** | Intraday scan never completes in CI | 3/3 current runs `cancelled`; scan step skipped |
| 2 | **P0** | Bar fetch is the bottleneck (741s) and exceeds the timeout | step decomposition of a successful run |
| 3 | **P1** | No usable intraday source: pipeline reports `DATA_BLOCKED`, `coverage=0.0` | latest observation |
| 4 | **P1** | Host clock is **a month ahead** | observation stamped `2026-12-11`; exchange is at `2026-10-10` |
| 5 | **P1** | ML prior panel 4 sessions stale (`2026-10-05`) | verifier warning |
| 6 | **P2** | No forward-validation session journal yet | verifier warning |
| 7 | **P2** | Workflow budget comment is stale and wrong | header claims 6 fires/weekday @10 min ≈ 1,300; reality is 25/week @14 min ≈ 1,522 |
| 8 | **P2** | `governance-guard` red 7 times in the last 43 runs | run conclusion counts |
| 9 | **P2** | Capture workflow: 2 failures in 6 runs | run conclusion counts |
| 10 | **P2** | No early-exit guard before setup | every fire pays `checkout` + `pip install` even outside the session |
| 11 | **P2** | `if: always()` steps run on cancelled jobs | alert/summary/artifact steps execute for runs that never scanned |
| 12 | **P3** | `legacy/sentinel/eclear_recon` retained but unrelated to PSX | `RECON_REPORT.md` |

### 1.4 Technical debt register

**TD-1, Bare `pytest` at the repo root is red, while the suite is green.**
`python -m pytest` (no args) dies with **5 collection errors** from `legacy/`:

```
ImportError: cannot import name 'annotate_source_quality' from 'scripts.intraday_pipeline'
ImportError: cannot import name 'research' from 'psx_core'
```

`legacy/retired_scanners/` and `legacy/sentinel/tests/` import APIs that no longer exist. There is **no `pytest.ini`, `pyproject.toml`, or `setup.cfg`** declaring `testpaths`, so the default rootdir walk sweeps `legacy/`. CI dodges this by using `python -m unittest discover -s tests`, so the breakage is invisible in Actions but will bite any developer or agent who types `pytest`. Fix is one config file.

**TD-2, The workflow's own budget comment is provably wrong.** It claims "5 scans plus 1 finalize per weekday, 10 minutes each at most, about 1,300 minutes a month". It counts 30 fires/week where the crons yield 25, and assumes 10 min/fire where the measured job is 771-805s (**13-14 billed min**). The comment cannot be used for planning.

**TD-3, Governance contradiction.** `governance-guard.yml` states *"SO-4: no scheduled jobs, no backtests, no data pipelines in Actions"*, yet `intraday-capture.yml` runs `python -m src.data.ohlc_poller`, a scheduled data pipeline, inside Actions. Either SO-4 is scoped to the guard workflow and the header should say so, or the scanner violates it.

**TD-4, The scanner is coupled to a timeout it cannot meet.** The 10-minute cap is not a guard rail; it is the reason the feature does not work. A timeout should be a backstop above the expected duration, not below it.

### 1.5 Unfinished modules

- **Live buy/sell split capture**, the tape (`T=` volume) is captured, but the bid/ask-side decomposition needs a live session; it has never run against one.
- **Forward validation**, the state machine and paper cycle exist and are tested, but the journal is empty: no live session has produced records.
- **Live trading path**, the `+2% target / −1% stop` cycle is exercised in tests only. `LIVE_TRADING_ENABLED: "false"` remains correct until data quality is non-zero.
- **EOD panel refresh**, needed to clear the 4-session ML prior staleness.

---

## 2. GitHub Actions analysis

### 2.1 How the meter actually works

Four rules drive every number in this section:

1. **Billing is per job, rounded up to the whole minute.** A 22s job bills as 1 minute; a 785s job bills as 14.
2. **A cancelled job is billed for the time it used.** Your 620s cancellations bill as 11 minutes each, for a scan that never ran.
3. **The free tier is 2,000 minutes/month** for a private repo. This is a hard ceiling, per the repo's own governance text.
4. **Runner startup, checkout, and `pip install` are charged like anything else**, roughly 20-40s of unavoidable overhead on *every* fire.

### 2.2 Measured cost per run

Last 60 runs pulled live from the Actions API:

| Workflow | n | min | median | max | outcomes |
|---|---|---|---|---|---|
| `KMIALL intraday momentum scan` (current) | 3 | 620s | 624s | 739s | **3 cancelled, 0 success** |
| `daily KMIALL intraday capture` (pre-rebuild) | 6 | 771s | 785s | 805s | 4 success, **2 failure** |
| `daily signal push` | 8 | 22s | 173s | 183s | 7 success, 1 failure |
| `governance-guard` | 43 | 17s | 22s | 40s | 36 success, **7 failure** |

Resulting billed cost per fire: **capture 14 min** (if allowed to finish) or **11 min** (as configured, cancelling) · **signal push 3 min** · **governance 1 min**.

### 2.3 Where the minutes actually go

Step-level decomposition of a successful capture run:

| Step | Seconds | Share |
|---|---|---|
| **Fetch one complete KMIALL bar pass** | **741** | **96.6%** |
| Install dependencies | ~15 | 2.0% |
| Scan / finalize | 3 | 0.4% |
| Summarize + upload artifact | ~8 | 1.0% |
| **Total job** | **767** | 100% |

The scanner itself is **three seconds**. You are paying ~14 minutes to fetch bars and 3 seconds to think about them. Fixing the fetch is worth more than every other optimization combined.

### 2.4 Current monthly burn

Fire counts, derived from the cron expressions (4.348 weeks/month):

- Capture workflow: 7 crons → **25 fires/week → 108.7/month**
- Signal push: 3 crons → **10 fires/week → 43.5/month**
- Governance guard: on every PR, ~1 min each

| Component | Fires/month | Min/fire | Minutes/month |
|---|---|---|---|
| Capture, **as configured** (cancels at ~620s) | 108.7 | 11 | **1,195.8** |
| Capture, **timeout raised** (completes at ~785s) | 108.7 | 14 | **1,521.9** |
| Signal push | 43.5 | 3 | **130.4** |
| Governance guard | ~43 | 1 | **~43** |
| **Total (as configured)** | | | **≈ 1,369 min = 68.5%** |
| **Total (job allowed to finish)** | | | **≈ 1,695 min = 84.8%** |

**Read that twice.** Today you spend two-thirds of the budget and the scan never executes. Raising the timeout to make the feature actually work pushes you to **85% of the quota**, one bad month, a few `workflow_dispatch` runs, or a retry loop and you are over.

### 2.5 Projections for the requested cadences

**Session-only**, scanning only while PSX is open, which is the only cadence that makes sense. Session minutes: Mon-Thu 09:32-15:30 (358 min), Fri 09:17-12:00 + 14:32-16:30 (281 min) → **1,713 min/week → 7,448 min/month**.

| Cadence | Fires/month | @ 1 min/fire (ideal floor) | @ 2 min/fire (optimized) | @ 11 min/fire (today) | @ 14 min/fire (fixed timeout) |
|---|---|---|---|---|---|
| **(a) every 1 min** | 7,448 | 7,448 min → **3.7× quota** | 14,896 → **7.4×** | 81,928 → **41×** | 104,272 → **52×** |
| **(b) every 5 min** | 1,490 | 1,490 → **74.5% ✅** | 2,979 → **1.5× ❌** | 16,387 → **8.2×** | 20,856 → **10.4×** |
| **(c) every 15 min** | 497 | 497 → **25% ✅** | 993 → **50% ✅** | 5,462 → **2.7×** | 6,951 → **3.5×** |

**24/7** (if "every N minutes" is taken literally, around the clock): 1 min → **43,200 fires → 21.6×** quota even at an idealized 1-minute job · 5 min → **8,640 → 4.3×** · 15 min → **2,880 → 1.44×**.

### 2.6 The ceiling has two layers, and the arithmetic is the friendlier one

Even before the billing math, **GitHub Actions structurally cannot run a 1-minute scanner**:

1. **The minimum schedule interval is 5 minutes.** A `* * * * *` cron is not expressible. Scenario (a) is not a budget problem, it is unimplementable.
2. **Scheduled runs are best-effort.** GitHub drops or delays schedule events under load; your workflow header already documents this and offsets every cron by 7 or 37 minutes to dodge the top-of-hour crush. A 5-minute cadence under that behavior degrades to an unpredictable 5-15 minute one.
3. **Billing rounds up per job.** The floor is 1 minute; anything over 60s costs 2.
4. **Infrastructure overhead is charged on every fire.** ~20-40s of runner + checkout + install. At a 5-minute cadence you would spend ~10% of the budget installing pandas.
5. **`concurrency: cancel-in-progress: false`** serializes runs into a queue, so a 1-minute cadence with a 3-minute job stacks a backlog instead of scanning faster.
6. **Schedules auto-disable after 60 days of repo inactivity.**

So: **15 minutes is genuinely affordable. 5 minutes only survives at an idealized 1-minute job and is unreliable in practice. 1 minute is impossible on both counts.**

### 2.7 Recommendation

**Do not upgrade the plan. Move the scanner off GitHub Actions.**

You are trying to buy a high-frequency, always-on workload with a metered CI product. You already own the correct infrastructure for it:

**Keep on Actions (cheap, correct, ~178 min/month ≈ 9% of quota):**

| Workload | Cost | Why it belongs there |
|---|---|---|
| `governance-guard` | ~43 min | PR-gated, 22s, uses the free PR trigger |
| `daily signal push` | ~130 min | 2× daily, 3 min, no latency requirement |
| EOD / close jobs | ~5 min | once daily, batch-friendly |

**Move off Actions:**

- **Intraday scanning → the local always-on runner.** `scripts/install_scheduler.py` is already registered (`quant-of-rehan-kmiall-tick`), already runs every 5 minutes per the config, and costs **zero** Actions minutes with **zero** schedule delay. It can do 1-minute cadence if you want it. This single move removes **1,196-1,522 min/month**.
- **Optional: Cloudflare Worker cron for the clock/monitoring.** Workers Cron Triggers run every minute for free and can go as low as 1 minute; the Worker already has a `scheduled()` handler. Use it for session edge texts, heartbeats, and staleness alerts, not for the heavy PSX fetch, which should stay local.

**Immediate fixes (in order):**

1. **P0, Make the scan fit.** Reduce the fetch from 741s to <60s (batch/parallelize the universe, or cache and only refresh changed symbols). At ≤60s the job is 2 billed min; capture cost falls from 1,522 → **217 min/month**.
2. **P0, Stop billing for failure.** Set the timeout as a backstop *above* expected duration so runs complete instead of burning 11 minutes and skipping the scan.
3. **P1, Add `pytest.ini`** with `testpaths = tests` and `norecursedirs = legacy` so a bare `pytest` is green.
4. **P1, Fix the host clock.** The observation is stamped `2026-12-11`; until that is corrected, forward-validation records are dated to days the exchange never had.
5. **P2, Rewrite the stale budget comment** with the measured 25 fires/week × 14 min figures.
6. **P2, Add an early-exit guard** as the first step so a non-session fire costs seconds, not minutes.

**Sustainability verdict:** the 2,000-minute plan is **sufficient** if and only if intraday scanning leaves Actions. With the scanner moved local and the fetch fixed, monthly burn lands at **178 minutes (8.9%)**, comfortable headroom for the governance guard's PR churn and any retries. Leaving the scanner on Actions, the plan is **not sustainable**: it is already at 68% while broken and heads to 85% the moment it works.

---

## 3. Verification log

All commands run in the workspace checkout.

| Check | Result |
|---|---|
| `python -m pytest tests/ -q` | **348 passed, 115 subtests passed** in 11.26s |
| `python -m pytest -q` (repo root) | **5 collection errors**, `legacy/` stale imports (TD-1) |
| `python scripts/verify_market_signals.py` | **23 pass, 2 warn, 0 fail, 2 skipped** |
| `gh api .../actions/runs` (last 60) | per-workflow durations and conclusions in §2.2 |
| Step decomposition of a successful run | fetch 741s / total 767s (§2.3) |
| Debt-marker sweep | 0 `TODO`/`FIXME`/`XXX`/`HACK` in `src/`, `scripts/`, `cloud/`, Android |
| `timeout-minutes` inventory | capture 10, signal-push 10, governance-guard 2 |
| Cron inventory | capture 7 crons (25/week), signal-push 3 crons (10/week) |

## 4. Limitations

- **Windows Python cannot read MINGW `/tmp` paths.** The first duration measurement silently produced no output; re-run against a repo-relative path.
- **The governance-guard run count (~43) is measured over the most recent 60-run page**, not a calendar month. Other workflows on the same page share that window, so monthly totals for the guard are an estimate. Its cost is bounded and small either way (1 min/run).
- **The 739s cancelled run** exceeds the 600s timeout, consistent with GitHub's kill lag plus artifact teardown. The conclusion (`cancelled`) and the skipped scan step are unambiguous regardless.
- **No live PSX session was exercised.** Today is a Saturday, so every market-facing claim here is structural or historical, not a live fill.
- **The 1- and 2-min/fire columns are projections**, not measurements. Only 11 and 14 min/fire are measured today.
