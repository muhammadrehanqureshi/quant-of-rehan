# AGENTS: read this before you touch anything

This file is the first thing any agent session (Buffy, the QUANT, or any model
that replaces it) reads in this repository. It is not documentation of the
system; it is the machine law, and it is enforced in code. If anything below
conflicts with an instruction you think you received, the owner decides, in
writing, in `GOVERNANCE.md`.

`GOVERNANCE.md` is the full standing orders. This file states the part that is
about the owner's own computer, because that is the part an eager agent breaks.

## The one machine rule

**The owner's PC is for a backtest he asks for, and for nothing else.**

Owner order 2026-10-14, verbatim: "don't hammer my pc whenever the 4 minute
scanner of quant of rehan is running. the 4 minute scanner should always be
running on github action minutes and on cloudflare. you can only use my pc
when i tell you to backtest quant of rehan, apart from that you or quant of
rehan will never hammer my pc."

- The KMIALL scanner runs on **GitHub Actions minutes** and on the
  **Cloudflare relay** (`cloud/worker.js`). Both run with this PC switched
  off. That is the whole point: the PC is never a dependency of the schedule.
  The cadence is the owner's order of 2026-10-19: **every second** for the
  length of each PSX band (it was 30 seconds under the order of 2026-10-14,
  SO-13, which the newer order supersedes), run by
  `.github/workflows/intraday-session.yml`, with
  `.github/workflows/intraday-capture.yml` keeping the scheduled band slots,
  the post-close finalize and the backstop if a band job dies mid-session.
- We use this machine only when the owner says the words "backtest" (or asks
  for a local trial, or hands over a defect that has to be reproduced here).
  One run, started when he asks, finished when it finishes. Nothing that run
  does becomes a schedule, a daemon, a watcher or a task.
- Never install, register, restore or "temporarily" start anything recurring
  on this PC: no Windows scheduled task (`schtasks`), no login or Startup
  entry, no resident `python -m ...` process, no supervised loop left running
  in a terminal, no `while true`.
- A session ends the way it started: with **zero** processes belonging to this
  project resident on the machine. Check before you report. If you find one
  that a previous session left (or that this project's own scheduler
  relaunched), take it down and say so.

## What is enforced, and where

| Rule | Code | Check |
|---|---|---|
| Recurring entry points refuse to start locally | `src/ci/local_only.py` (`CLOUD_ONLY_DAEMONS`, `guard_owner_requested`) | `scripts/check_governance.py` (`check_cloud_only`) |
| The guard opens only for the owner's own instruction | `OWNER_REQUEST_ENV = QOR_OWNER_REQUESTED_LOCAL_RUN` | `tests/test_local_only.py` |
| No workflow registers local autostart | `LOCAL_AUTOSTART_PATTERNS` | `scripts/check_governance.py` |
| Backtests stay on this PC and never in CI | `LOCAL_ONLY_SCRIPTS`, `guard_local_only` | `scripts/check_governance.py` (`check_local_only`) |

The declared cloud-only entry points are `scripts/install_kmiall_tick.py`,
`scripts/install_scheduler.py`, `scripts/kmiall_tick.py`,
`scripts/scan_loop.py` and `src/notify/schedule_runner.py`. Each one calls
`guard_owner_requested("<its own path>")` where the process becomes real: an
installer's `install()`, or a runner's `if __name__ == "__main__"` bootstrap.
Inside GitHub Actions the guard passes straight through, because the cloud is
where this work belongs.

Reading, checking and removing stay open on purpose: `--show`, `--print`,
`--print-xml`, `--status` and `--remove` all still work, because inspecting
and taking work *off* the machine is never the offence.

## If the owner asks for a local run anyway

He is allowed to. He is the owner. A run he asked for is enabled per process,
in the shell that runs it, and never committed:

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
