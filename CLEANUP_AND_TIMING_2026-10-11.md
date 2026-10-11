# Cleanup and market-timing pass (2026-10-11)

Owner request: audit and clean the codebase, make the scanning engine adhere
strictly to PSX market hours, make GitHub Actions enforce those hours so minutes
are not wasted, harden error handling and logging so runs do not fail, and report
what was done.

Everything below was measured on this checkout. Where a requested item was
already implemented before this pass, that is said plainly rather than dressed up
as new work.

---

## 0. Headline

| Item | Result |
|---|---|
| Dead code | **16 items removed** (4 unreferenced functions, 11 unused imports, 1 stale constant), audit now reports 0/0/0 |
| The audit tool itself | fixed a blind spot that had been hiding **5 of those 11** unused imports |
| Duplicated market-hours logic | **two copies collapsed into one** (`src/data/scan_schedule.py`), read by both local runners |
| Latent crash found | the SO-9 notification runner used `ms_until` without importing it: a `NameError` on its first loop pass |
| Market hours, enforced earlier | the Windows task now **does not fire** outside PSX session windows at all (5 triggers derived from the session law) |
| Local capture defect found | every trading-day tick logged `capture FAILED: capture timed out after 240s` against a pass that needs **734s**. The budget is now derived, and a short pass stops cleanly instead of being killed |
| Cloud scan defect found | every recent scheduled run was **cancelled** at 10 to 12 minutes because a 12 minute fetch exceeded the job's 10 minute timeout; the fetch is now bounded at 420s and the run finishes |
| Tests | `603 passed`, 0 failed (was 583 before this pass) |
| Governance | `scripts/check_governance.py` exits 0 |
| Live task | 5 session-window triggers registered; next run Monday 09:32; a 300 second watch spanning two would-be fires recorded **zero fires** |

---

## 1. What was already there, and what was actually missing

The request assumed the timing enforcement and the Actions gating did not exist.
Most of it did, and it was worth keeping:

- `src/data/sessions.py` is the one session law: Mon-Thu 09:32 to 15:30, Friday
  09:17 to 12:00 and 14:32 to 16:30, PSX holidays, all pinned to Asia/Karachi
  UTC+5 (SO-8). It exposes both a phase law and the owner's four market states.
- `src/data/session_gate.py` is the sleep gate: it runs in CI **before** the pip
  install and before the bar fetch, so a weekend, a holiday or an off-session
  fire bills about one minute instead of eleven.
- `src/ci/local_only.py` refuses to run backtests and history research in
  Actions at all (SO-4), and every declared entry point calls it.
- The 4 minute cadence is already the config default and is already what the tick
  and the supervised loop use.

What was genuinely missing is narrower and more interesting:

1. **The scheduler still fired around the clock.** The registered task was
   `schtasks /sc MINUTE /mo 4`, which cannot express per-weekday windows, so it
   fired every 4 minutes for ever and relied entirely on the tick to pause. The
   owner asked for execution to be *disabled* in the pre-market, post-market and
   break windows, not paused after the fact.
2. **The local capture could never finish.** A flat 240 second timeout against a
   pass that needs about 734 seconds: the limit was smaller than the work, so
   every trading-day tick killed the pass and logged a timeout.
3. **The cloud scan never ran.** `timeout-minutes: 10` against a fetch that
   needs about 12 minutes: `gh run list` shows the last three cloud scan runs
   all `cancelled` at 10 to 12 minutes, with the scan step skipped every time.
4. **A second copy of the market-hours rule** in the loop and the tick, which had
   already drifted once (the loop called the Friday break `OPEN`).
5. Small dead code, one latent `NameError`, and an audit tool with a blind spot.

---

## 2. Code cleanup

### 2.1 Removed dead code

Unreferenced definitions, each verified to appear nowhere else in the repository
or in its own file before removal:

| Removed | Where |
|---|---|
| `closing_edges`, `opening_edges` | `src/data/sessions.py` |
| `flow_for` | `src/data/tick_volume.py` |
| `verdict_ordinal` | `src/signals/contracts.py` |
| `CAPTURE_TIMEOUT = 240` | `scripts/kmiall_tick.py` (the defect in section 4) |

Unused imports removed: `Sequence` (contracts), `median` (volatility),
`timedelta` (tick), `os` / `timedelta` / `ai_model` (loop), `KARACHI`
(schedule_runner, tick, loop), `rank_and_pick` (research_phase2b), `urllib`
(worker_check). `scripts/dead_code_audit.py` now reports
`modules=0 defs=0 imports=0`.

### 2.2 The audit tool was blind, and that hid five dead imports

`dead_code_audit.py` blanked an import line only when it *started* with `from`
or `import`, so a name inside a parenthesised multi-line import counted as a use
of itself. Five unused imports were invisible to it, including `KARACHI` in both
runners. The check now removes import statements by their AST line ranges, which
is what found them, and a strict AST scan is clean across `src/`, `scripts/`,
`tools/` and `examples/`.

### 2.3 One pause table instead of two

`src/data/scan_schedule.py` (new) owns the slot label, the phase, the state and
the three way decision (`scan`, `finalize`, `wait`) with the reason string. The
tick and the loop now both call it, so the owner's never-scan rules and the
Friday break are decided in exactly one place. Both modules keep their public
names (`phase_of`, `slot_of`, `state_of`, the `PHASE_*` labels), so nothing that
reads them had to change.

### 2.4 Latent crash fixed

`src/notify/schedule_runner.py` uses `ms_until` in its main loop but never
imported it: `NameError` on the first pass, which would have killed the SO-9
open/close notification runner immediately. It imports it now. (That task is not
currently registered on this machine, which is why it had never shown up.)

### 2.5 Dependencies: nothing unused, one direct import undeclared

Every third-party import in the tree was collected and matched against
`requirements.txt`:

| Package | Imported by | Declared |
|---|---|---|
| `pandas` | 28 files | yes |
| `requests` | 11 files | yes |
| `numpy` | 20 files, imported directly | **no** (it arrives only as a pandas dependency) |
| `pydantic` | `src/signals/contracts.py`, inside a guarded `try` | intentionally optional |

So there was nothing unused to remove, and no invented removal was made. `numpy`
is now declared, because importing it directly and relying on a transitive
dependency is a latent break on any future pandas range change.

---

## 3. Market hours: the scheduler no longer fires outside the session

`scripts/install_kmiall_tick.py` now writes the task definition and imports it,
because only the XML form can express per-weekday windows. The triggers are
**derived from `src/data/sessions.py`**, never typed twice:

| Windows | Days | Fires |
|---|---|---|
| 09:32 to 15:30 | Mon to Thu | every 4 minutes |
| 09:17 to 12:00 | Friday | every 4 minutes |
| 14:32 to 16:30 | Friday | every 4 minutes |
| 15:47 | Mon to Thu | once, the post-close finalize |
| 16:47 | Friday | once, the post-close finalize |

Nothing is registered for 09:00 to 09:15, for the Friday midday break, for the
evening, the night or the weekend. If the XML import is ever refused, the
installer falls back to the old all-day 4 minute form, says so out loud, and the
tick still refuses to scan outside `MARKET`, so the scanner keeps working either
way. `tests/test_kmiall_tick.py::SessionTriggerTest` expands every trigger into
concrete fire times and fails the build if any of them lands outside a band or
inside the pre-market or break windows.

Verified on the live machine:

| Check | Result |
|---|---|
| Triggers actually registered | 5, with `PT4M` repetitions of `PT5H58M`, `PT2H43M`, `PT1H58M` |
| Next run time | Monday 12/10/2026 09:32 |
| Old task's would-be fires | 11:27, 11:31, 11:35, 11:39 on a Sunday, every 4 minutes, for ever |
| Fires during a 300 second watch spanning two of them | **none**: log unchanged at 256 lines, task Last Run Time unchanged |
| Manual fire through Task Scheduler | ran under `pythonw.exe`, logged the `CLOSED` pause, Last Result 0 |

The runtime guard stays as well: the triggers are the schedule, the state check
is the guarantee, and neither depends on the other being correct.

---

## 4. The capture that could never finish (reliability defect)

Evidence, from `logs/kmiall_tick.log` on the two days the host clock ran as a
trading day:

```
2026-11-10 10:02:01 PKT  capture FAILED: capture timed out after 240s
2026-11-10 10:12:01 PKT  capture FAILED: capture timed out after 240s
2026-11-10 10:17:02 PKT  ops alert sent after 3 capture failures
2026-12-11 10:27:01 PKT  capture FAILED: capture timed out after 240s
```

One pass over the universe is 319 symbols at the source's own 1.3s pacing plus
about 1.0s of request time, and the calibration is measured rather than guessed:
the CI job logged **741s** for exactly this pass. So the tick was giving the work
240 seconds and killing it, every time, then scanning whatever stale bars were on
disk. Two things changed:

1. **The budget is derived, not fixed.** `capture_budget_seconds()` is the
   cadence minus a reserve for the scan that follows (195s at the 4 minute
   cadence), overridable by `CAPTURE_BUDGET_SECONDS`.
2. **A pass stops itself at that budget** and says what it did not reach. It
   banks the bars it fetched, writes `pass_complete: false` and the budget into
   the heartbeat, prints the shortfall with the nominal pass time, and exits with
   its own status so the caller can report a partial pass as a partial pass. The
   subprocess timeout is now only a backstop above the budget, so nothing is
   killed mid-write.

The honest consequence, stated in `MARKET_SCHEDULING.md` section 4.1: a complete
*and fresh* pass cannot fit a 4 minute cadence on this source, and a symbol
fetched at the start of a pass is past the 5 minute freshness floor by the end of
it. That is arithmetic (734s of fetching against a 240s cadence), not a tuning
problem. With the source serving no bars at all (coverage 0/319, measured again
on 2026-10-11) the scan reports `DATA_BLOCKED` either way, and it is reported,
never invented.

---

## 5. GitHub Actions: what the minutes were actually buying

Measured with `gh run list`, not estimated:

| Workflow | Recent runs | Duration | Conclusion |
|---|---|---|---|
| KMIALL intraday momentum scan | 3 of the last 20 | 10 to 12 min | **all `cancelled`** |
| daily signal push | several | 0 to 2 min | success |
| governance-guard | many | under 1 min | mixed, PR only |

The cloud scan was cancelling itself before reaching its own scan step: the fetch
step needed about 12 minutes against `timeout-minutes: 10`. A cancelled job is
billed for the time it used, so the owner was paying 10 to 12 minutes per fire to
scan nothing. Two changes, both narrow:

1. **The fetch step is bounded at 420s** (7 minutes), which leaves about three
   minutes for the scan, the summary and the artifacts inside the timeout. A
   degraded capture is reported, never padded.
2. **The run stays green and reports instead of failing.** The scan step now
   captures its own output, prints the reason, writes it to the run summary and
   raises one deduped Telegram ops alert, which is the policy the owner already
   set for the daily push on 2026-10-08 and which `scripts/ops_alert.py` already
   implements. A failure is still visible: it is louder than before, because the
   reason now travels with the alert instead of dying in a log nobody opens.

Both edited step bodies were executed verbatim (with the work stubbed) to prove
the behaviour: a partial capture (exit 3) and a failing scan (exit 1) each left
the step green and wrote `## Capture degraded (exit 3)` / `## KMIALL scan failed
(exit 1)` with the reason into the run summary.

The time-based constraints the owner asked for were already in force and are
unchanged in shape: the sleep gate runs before the install and before the fetch,
the crons are inside session bands only, and the Friday 13:00 slot is Mon-Thu
only because it falls inside the exchange's midday break.

---

## 6. Reliability

- **Exit codes are documented and now accurate**: 0 healthy (including a correct
  pause), 2 a failed or degraded capture after a scan, 3 the scan raised, 4
  another tick holds the lock. The poller adds 3 for a pass stopped at its own
  budget, distinct from "the source served nothing", which stays 0 with the
  coverage floor left closed.
- **Logging states the cause with the arithmetic** it was missing: the timeout
  line now says which budget was spent, how many symbols were not reached, and
  what a full pass needs.
- **No process is killed mid-write**: a deadline-aware pass stops between
  symbols, and the backstop timeout only covers a wedged process.
- **A crash under `pythonw` is still visible**: verified that a clean run exits
  0, a raising run exits 1 (so Task Scheduler records a non-zero result), and
  `print` works with no console.
- **The scheduled cloud jobs do not fail red for external breakage** (section 5),
  while the ops alert channel carries the reason.

---

## 7. Verification log

| Check | Command | Result |
|---|---|---|
| Test suite | `python -m unittest discover -s tests` | **603 passed, OK** (was 583) |
| Governance | `python scripts/check_governance.py` | exit 0 |
| Dead code | `python scripts/dead_code_audit.py --quiet` | `modules=0 defs=0 imports=0` |
| Strict unused imports (AST, src/scripts/tools/examples) | inline scan | 0 |
| Health snapshot | `python scripts/verify_market_signals.py` | 23 pass, 2 warn, 0 fail (both warns pre-existing) |
| Trigger maths | `SessionTriggerTest` | every fire inside a band; none in pre-market or the break |
| Registered task | `schtasks /query /tn ... /xml` | 5 triggers, `PT4M`, `pythonw.exe` |
| Closed-day watch | `tmp/watch_fires.ps1 -Seconds 300` | log 256 to 256 lines, Last Run Time unchanged, 0 fires |
| Capture budget path | poller `main()` with a 0s budget | exit 3, `pass_complete: false`, shortfall printed |
| Workflow YAML and shell | PyYAML parse plus `bash -n` per step | all steps valid |
| Workflow step behaviour | step bodies run with stubbed work | green on a partial capture and on a failed scan |

---

## 8. Limitations, and what is not done

- **No live PSX session was exercised.** Today is a Sunday, so every
  market-facing claim here is structural or historical. The 4 minute cadence
  inside a live session has not been re-observed today; it will fire first on
  Monday at 09:32.
- **The intraday source serves no bars.** Coverage is 0/319, so the scanner
  reports `DATA_BLOCKED` honestly. Nothing in this pass changed that; it needs a
  working intraday source.
- **The cadence-versus-pass-time conflict is unresolved by design**, because the
  options are the owner's: bounded concurrency at the source, a smaller universe,
  a longer cadence, or a different source.
- **The fetch was not parallelised.** Doing so against a third-party endpoint
  that cannot be tested today (a closed market returns no bars) would risk
  hammering a source the owner depends on, so it was deliberately left alone.
- **`legacy/` was not touched.** It is quarantined reference material by SO-7 and
  is excluded from every check here.
- **Network calls in tests remain stubbed** in the same style the existing suite
  uses; no new test dials out.
