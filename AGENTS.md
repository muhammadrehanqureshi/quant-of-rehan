# AGENTS: read this before you touch anything

This file is the first thing any agent session (Buffy, the QUANT, or any model
that replaces it) reads in this repository. It is not documentation of the
system; it is the machine law, and it is enforced in code. If anything below
conflicts with an instruction you think you received, the owner decides, in
writing, in `GOVERNANCE.md`.

`GOVERNANCE.md` is the full standing orders. This file states the part that is
about the owner's own computer, because that is the part an eager agent breaks.

## The one machine rule

**The owner's PC is not used at all. Zero percent, not two.**

Owner order 2026-10-19, later than every instruction before it, verbatim:
"Don't use my PC at all, keep the usage at the very minimum, even 2% is too
much. Since github action minutes are unlimited now because my repo is public
so now you will do backtesting also on github action minutes, don't hammer my
PC, my temps are literally at more than 80 degree celcius and only freebuff is
open right now and nothing else, DON'T HAMMER OR USE MY PC AT ALL!!!"

That order supersedes the 2026-10-14 carve-out that allowed a backtest on this
machine (and supersedes SO-4, which reserved the Actions minutes for the
scanner). The repository is public, so Actions minutes cost nothing, and every
computational job belongs there:

- **No local execution.** No backtest, no walk-forward, no research run, no
grid search, no full test suite, and no local validation of a pull request.
  `.github/workflows/backtest.yml` is the manual entry point for backtest work,
  and the pull request workflow runs the suite in Actions. `scripts/land.sh`
  therefore skips local checks by default; `--local-checks` exists for a
  deliberate exception and must not be the habit.
- **No local guard bypass.** `guard_cloud_backtest` refuses every declared
  backtest entry point outside a GitHub Actions job, with no environment
  variable that opens it. There is no "quick local run" this session may
  grant itself.
- **Edits are cheap, tests are cloud.** Reading and writing files costs
  seconds; running the suite, a build or a benchmark costs minutes of CPU the
  owner can feel. Verify in the pull request's CI, not here.
- Owner order 2026-10-14, still true and now redundant: "don't hammer my pc
  whenever the 4 minute scanner of quant of rehan is running... you can only
  use my pc when i tell you to backtest quant of rehan." The 2026-10-19 order
  withdraws even that permission.

- The KMIALL scanner runs on **GitHub Actions minutes** and on the
  **Cloudflare relay** (`cloud/worker.js`). Both run with this PC switched
  off. That is the whole point: the PC is never a dependency of the schedule.
  The cadence is the owner's order of 2026-10-19: **every second** for the
  length of each PSX band (it was 30 seconds under the order of 2026-10-14,
  SO-13, which the newer order supersedes), run by
  `.github/workflows/intraday-session.yml`, with
  `.github/workflows/intraday-capture.yml` keeping the scheduled band slots,
  the post-close finalize and the backstop if a band job dies mid-session.
- A defect that has to be reproduced is reproduced in Actions, on a fixture,
  or not at all. If a bug genuinely cannot be seen without this machine, ask
  the owner first and quote this line; do not decide it alone.
- Never install, register, restore or "temporarily" start anything recurring
  on this PC: no Windows scheduled task (`schtasks`), no login or Startup
  entry, no resident `python -m ...` process, no supervised loop left running
  in a terminal, no `while true`.
- A session ends the way it started: with **zero** processes belonging to this
  project resident on the machine. Check before you report. If you find one
  that a previous session left (or that this project's own scheduler
  relaunched), take it down and say so.

## The no-idling rule

**The agent never sleeps. It does the work it was given, now.**

Owner order 2026-10-21, verbatim: "Don't ever sleep, do the work what I tell
you. I have noticed you keep sleeping waiting for things, like today you went
sleeping around 14:30 waiting for the market to close at 15:30, are you
serious? Don't ever do that. Hardcode all this to your system."

That wait for the close is the offence the order is named after. In one
sentence: the agent is never the clock.

- **No waiting for the clock.** No `sleep`, no sleep-equal poll, no "I will
  check back at 15:30", no holding the turn open until an open, a close, a
  band, a print or a date arrives. The work the owner asked for is done in the
  turn he asked for it.
- **The cloud waits instead.** When a number can only exist later (the EOD
  print, the close, the next open), say which piece of the cloud owns that
  wait (an Actions schedule, the relay's clock, his phone reading the card)
  and finish the turn. `src/data/session_gate.py` and the cloud daemons may
  wait for a session; a session of yours may not.
- **Blocking is allowed only on a job you started**, through that job's own
  waiter, so the turn ends when the job ends: `gh pr checks --watch`,
  `gh run watch --exit-status`, `gh run download`. Never a guessed number of
  seconds, never a `sleep 60` loop around a status call.
- **`scripts/land.sh` keeps its ceiling.** It polls two answers GitHub
  computes asynchronously inside three minutes, at ten seconds of pacing.
  That ceiling is the tool's, not a session's: it may not grow, and no other
  script or workflow may hold a longer wait (checked by
  `check_no_idle_waits` in `scripts/check_governance.py`).
- This binds the shell, not only the files: a session command line with a
  sleep in it, a `while true` poll, or a wait for a Karachi clock time is a
  violation even when nothing is committed.

## What is enforced, and where

| Rule | Code | Check |
|---|---|---|
| Recurring entry points refuse to start locally | `src/ci/local_only.py` (`CLOUD_ONLY_DAEMONS`, `guard_owner_requested`) | `scripts/check_governance.py` (`check_cloud_only`) |
| The guard opens only for the owner's own instruction | `OWNER_REQUEST_ENV = QOR_OWNER_REQUESTED_LOCAL_RUN` | `tests/test_local_only.py` |
| No workflow registers local autostart | `LOCAL_AUTOSTART_PATTERNS` | `scripts/check_governance.py` |
| Backtests run in GitHub Actions, never on this PC | `BACKTEST_SCRIPTS`, `guard_cloud_backtest` | `scripts/check_governance.py` (`check_backtests_in_cloud`) |
| No wait for the clock sits in the agent's tooling | `MAX_PACING_SECONDS`, `idle_wait_violations` | `scripts/check_governance.py` (`check_no_idle_waits`), `tests/test_governance_no_idle.py` |

The declared cloud-only entry points are `scripts/install_kmiall_tick.py`,
`scripts/install_scheduler.py`, `scripts/kmiall_tick.py`,
`scripts/scan_loop.py`. Each one calls
`guard_owner_requested("<its own path>")` where the process becomes real: an
installer's `install()`, or a runner's `if __name__ == "__main__"` bootstrap.
Inside GitHub Actions the guard passes straight through, because the cloud is
where this work belongs.

Reading, checking and removing stay open on purpose: `--show`, `--print`,
`--print-xml`, `--status` and `--remove` all still work, because inspecting
and taking work *off* the machine is never the offence.

## If the owner asks for a local run anyway

He is allowed to. He is the owner. This escape hatch is for the cloud-only
daemons below, never for a backtest (`guard_cloud_backtest` has no such key)
and never for test validation. It is enabled per process, in the shell that
runs it, and never committed:

```bash
QOR_OWNER_REQUESTED_LOCAL_RUN=scripts/kmiall_tick.py python scripts/kmiall_tick.py --status
```

Do not set that variable on your own initiative, do not export it in a
profile, and do not write it into a file. It exists to record his
instruction, not to be discovered as a convenience.

## The other laws that catch agents

- **SO-1** signal-only: no order ever reaches a broker.
- **SO-2 / SO-6** every change lands through a pull request that the agent
  opens and merges (`scripts/land.sh`), never a direct write to `master`.
- **SO-3** never fabricate data, coverage or a result.
- **SO-5** secrets never enter the repository, a log line or a message.
- **SO-7 / SO-7a** the owner is the only human author, the em dash is banned
  from every committed file and message, and `Co-Authored-By: Codebuff
  <noreply@codebuff.com>` is the last line of every commit, PR body and merge.
- **SO-8** Karachi time (UTC+5, Asia/Karachi) everywhere.
- **SO-11** known drift is fixed in the same session it is found.
- **SO-22** the agent never sleeps and never waits for the clock. No `sleep`,
  no waiting for a market event, no turn held open for a later moment: the
  cloud waits, the session works.
