# GOVERNANCE: Hardcoded Standing Orders

**Owner:** Rehan (muhammadrehanqureshi): the mastermind. All instructions flow
from him. **Agent:** Buffy / the QUANT: executes, never self-directs scope.

These orders are binding on every future session, agent, or model working in
this repository. They are enforced by `scripts/check_governance.py` (runs on
every PR via `.github/workflows/governance-guard.yml`) and by the review
conventions below.

## SO-1 · Signal-only, always

The bot produces BUY / WAIT / EXIT / NO TRADE **signals** for PSX KMIALL
stocks. It must never place, modify, cancel, or transmit any order to any
broker. No trade-side socket messages, ever. Broker credentials are never
loaded by any module in this repository.

### SO-1a · Owner-authorized exception: AKD demo account only (2026-10-05)

The owner (Mr. Rehan) has explicitly authorized one narrow exception to the
signal-only rule. It is recorded here because the standing order says "never",
and a standing order is only ever changed by the owner's instruction, in
writing, in this file.

- **Scope:** order automation against the owner's AKD Trade Pro **demo
  (virtual trading) account** only. Demo accounts trade with virtual money on
  AKD's virtual trading service; no real capital is ever involved.
- **What is permitted:** programmatic login, order placement, order status,
  and cancellation against AKD's virtual trading endpoints, so that signals
  can be forward-tested end to end without touching the signal-only platform
  core.
- **What stays banned:** any order transmission to a real / live trading
  account, real broker credentials in this repository or in any module, and
  any use of the demo exception as a stepping stone to live trading. A live
  trading exception would need a new written owner instruction and a new
  amendment here.
- **Separation law:** demo automation lives in its own module namespace
  (AKD demo client), imports nothing from the signal engine, and the signal
  engine never calls it. Signals may be *forwarded* to the demo client by the
  orchestrator; the platform core remains signal-only in behavior and in code.
- **Credentials:** AKD demo credentials stay in local desktop files or
  environment variables exactly like every other secret (SO-5). They are never
  committed, logged, or embedded in source.
- **Guardrail:** if the demo client cannot positively verify it is talking to
  the virtual trading service (demo userCode, demo account), it must stop and
  refuse to send orders rather than risk a real account.

The rest of SO-1 stands unchanged for everything outside this exception.

## SO-2 · Pull request first, merge to `master` by the agent

- Every change lands on a feature branch, is opened as a pull request against
  `master`, and is **merged by the agent** (owner reviews if he asks to).
- The only permitted direct writes to `master` are:
  (a) the initial bootstrap commit that creates the repository, and
  (b) the one-time repository repair of 2026-10-04, which force-replaced the
      junk history left by a failed earlier agent session (logo-probe commits,
      migration markers) with the clean bootstrap. This exception is closed
      after that repair; it is recorded here so the history change is auditable.
- Violation check: `scripts/check_governance.py` asserts the repo has a
  `GOVERNANCE.md` and that CI is wired; branch protection on GitHub is the
  owner-side belt-and-suspenders.

## SO-3 · Never fabricate data: footprint honesty law

- If a data source (especially bid/ask, order flow, footprint candles) does not
  **genuinely** exist, the system must state
  `FOOTPRINT DATA UNAVAILABLE / DEGRADED` and disable that engine.
- OHLCV-derived proxies may be used for research **only** when explicitly
  labeled as degraded, never presented as true order flow.
- `src/data/registry.py` is the single source of truth for availability. Any
  module claiming footprint/order-flow capability must read from the registry
  and refuse to run when the registry says UNAVAILABLE.

## SO-4 · Backtest locally only (superseded 2026-10-19 by SO-21)

- **Superseded.** The direction of this order was reversed by the owner's
  instruction of 2026-10-19 below. It is kept because the history explains
  why the repository looks the way it does; nothing here is in force.
- All backtesting, walk-forward validation, and Monte Carlo runs execute on
  the owner's local PC. (No longer true: they run in Actions, SO-21.)
- Backtesting, walk-forward validation, and Monte Carlo runs never execute
  in CI, and full dataset crawls stay on the owner's PC. (Reversed: the
  crawl and every backtest run in CI; the guard now refuses them locally.)
- Exception carved by SO-10 (owner approval, 2026-10-07): the daily signal
  job runs on GitHub Actions within the budget below. It may fetch only a
  small trailing EOD window, never a full-history crawl. (The 120-day ceiling
  is withdrawn: the repository is public and the crawl is free.)
- Monthly Actions budget: 2,000 minutes while the repository is private.
  Nothing in this repo may put that at risk. (Void: the repository is public.)
- Owner order 2026-10-14 (SO-13): the repository is public, and GitHub Actions
  minutes are free on a public repository, so the 2,000-minute ceiling no
  longer bounds the market-hours work. What does not change is where those
  minutes go: the market-hours scans, the finalize and the session loop, and
  nothing else.
- Owner order 2026-10-11: the GitHub Actions minutes are reserved for the
  market-hours scans, the 4-minute KMIALL work. Backtesting, walk-forward
  validation, Monte Carlo runs and the history research scripts run on the
  owner's PC and nowhere else.
- Enforcement moved with the order. `src/ci/local_only.py` lists every
  backtest entry point, each one calls `guard_cloud_backtest` as the first
  statement of its `main()`, and that call stops a run anywhere except a
  GitHub Actions job. `scripts/check_governance.py` fails a pull request that
  removes a guard, deletes a listed script, or puts one on a schedule.

## SO-5 · Secrets stay out

- Desktop credential files (`credentials.txt`, `PSX-Credentials.txt`) are the
  authoritative local sources. They are never copied into the repo, printed in
  full, or embedded in code.
- Runtime secrets come from environment variables or GitHub Secrets, with the
  canonical names documented in `DATA_SOURCING.md` § Secrets.
- `scripts/check_governance.py` scans every changed file for secret-shaped
  strings (`gho_`, `cfut_`, retired chat bot-token pattern, broker password) and
  fails the PR if any appear.

## SO-6 · The agent merges

The agent is responsible for opening **and** merging every pull request on the
owner's GitHub. The owner gives instructions; he does not click buttons. If a
merge fails (rules, conflicts, instability), the agent reports honestly and
retries deliberately: never blindly.

## Change procedure for this file

GOVERNANCE.md itself is amended only via pull request, and only on an explicit
instruction from the owner.

## SO-7 · Sole human contributor and human-looking code (owner order, 2026-10-05)

- The owner, Rehan (muhammadrehanqureshi), is the only human contributor this
  repository may ever show. Every commit is AUTHORED by his verified identity:
  `Mr. Rehan <muhammadrehanqureshi@users.noreply.github.com>`. No bot accounts
  and no other author identity, ever.
- Code, comments, and commit messages must read as if a careful human wrote
  them. No machine-generated stylistic artifacts. The strongest one: the
  em dash and any similar decorative dash are banned from every committed
  file and every commit message. Use a comma, a colon, parentheses, or
  split the sentence.
- `scripts/check_governance.py` enforces both rules: it scans tracked files
  (excluding `legacy/`, which is quarantined reference material from the
  deleted sentinel repos and is never modified) and every new PR commit
  message. A violation fails the PR.
- The one agent attribution this repository shows is the co-author line of
  SO-7a, added by the owner's written instruction of 2026-10-13. Everything
  else (other co-authors, generated-by footers, signed-off-by) stays banned.

## SO-7a · The agent is the owner's co-author (owner order, 2026-10-13)

Explicit owner instruction, 2026-10-13: "I want you to be my co author until
further notice, you need to hardcode this for all the PRs and merging into the
master branch from now on." This adds exactly one line to every change, and
nothing else about SO-7 moves.

- The line is, verbatim and as the last line of the commit message:
  `Co-Authored-By: Codebuff <noreply@codebuff.com>` (Codebuff is the agent
  that works in this repository, Buffy / the QUANT; that address is its fixed
  identity and the software's role is fixed there).
- It travels with the whole path to master, not only with the commit: the pull
  request body carries it and the merge commit carries it, so the credit is
  visible on the commit, on the PR page and on `master` itself.
- It is hardcoded rather than remembered. `scripts/land.sh` appends it to
  every commit it writes, passes it as the pull request body, and passes it to
  `gh pr merge --body`, so a change cannot land without it. And
  `scripts/check_governance.py` fails a pull request whose commits do not
  carry it, or that carry any second identity, so the rule holds even if a
  future session forgets it.
- The author of every commit is still the owner (SO-7), the em dash ban is
  untouched, and the owner can withdraw this at any time: a withdrawal is a
  new written owner instruction and a new amendment here.

## SO-8 · Karachi time, forever (owner order, 2026-10-05)

- Every session time, schedule, cron, timestamp, and log line in this system
  is fixed to Pakistan Standard Time: UTC+5, Asia/Karachi, no daylight
  saving. This is hardcoded and may never depend on the machine's local
  timezone or on any other zone.
- Market sessions (Mon to Thu 09:32 open and 15:30 close, Friday 09:17 open
  and 16:30 close) are computed only from this fixed zone, adjusted for PSX
  holidays from the maintained holiday list.
- Any future change to this rule requires an explicit owner instruction and
  an amendment to this file.

## SO-9 · Notifications reach the owner reliably (owner order, 2026-10-05)

- The chat channel is retired (owner order 2026-10-29): the account and the
  bot are gone, and no code in this repository talks to a chat API. Delivery
  goes to the owner's email: each notification is a comment on the watched
  "Quant of Rehan - owner email" issue, and GitHub's own notification mail
  carries it to mrmrehanqureshi@gmail.com the moment the comment lands.
  Scheduled jobs run on GitHub Actions and the Cloudflare edge, never on the
  owner's PC, so the PC is not part of the delivery path either.
- Owner order 2026-10-31, "remove the PSX market open/close/break emails
  from github actions. I only want to receive intraday signals from
  github actions during market days from now on": the market event
  emails (pre, open, morning break, midday break, close, post, post close)
  are retired entirely. The ONLY owner emails an Actions job may send are
  the actual intraday signals (the trade entry and the call watch) and
  the deduped ops alerts. The market phases still ride the app card, the
  phone's own notifications and the run summaries.
- Delivery is exactly once per event per day through the comment ledger's
  markers, and it fails closed with a clear log line when the send is
  impossible. No signal is ever silently dropped and none is ever fabricated.

## Owner orders of 2026-10-31

- "The app is still showing two different data for PRL... Data has to be
  same/correct across the entire app including quant of Rehan intraday.":
  ONE truth per stock. Every surface that answers "what did this stock
  do today" (the card's leaders, the search box's answer and its rows,
  the dropdown rankings, the intraday scanner) draws from the same
  acknowledged frame the relay's store keeps, and the frame's own tick
  time must sit inside the regular session (the post-market tail never
  replaces a session answer).
- "How could the buying and selling volume decrease? The volume can only
  increase.": within one stock's one Karachi day, the printed B and S
  only move as the day's own volume grows. The relay clamps every
  answered pair against the day's acknowledged pair.
- Dropdown menus carry a line between two adjacent sub menu options,
  with EXACTLY the same gap between the line and the options above and
  below it, in every dropdown.
- "You need to have a ML engine/concept that will be self learning. Like
  an actual pro trader. Learn from your mistakes. Be with the market.
  Don't go against the market.": the quant's measured memory of its own
  closed trades (src/signals/adaptive_memory.py) refuses a fresh setup
  that its own record already failed: a losing hour bucket, a symbol on
  a stop-out streak, and any confirmed entry against the market's own
  direction. Nothing is learned that is not measured.

## Standing orders index

SO-1 signal-only · SO-2 PR first, agent merges · SO-3 never fabricate data ·
SO-4 backtest locally only (superseded by SO-21) · SO-5 secrets stay out ·
SO-6 the agent merges ·
SO-7 sole human contributor, human-looking code, no em dashes · SO-7a the
agent is the owner's co-author on every commit, PR body and merge ·
SO-8 Karachi time forever · SO-9 owner notifications via the Cloudflare
relay · SO-10 resource law: cloud-first, local only for backtests · SO-11
zero-defect law: known drift is fixed immediately · SO-12 the 4-minute
scanner is cloud-only: nothing recurring runs on the owner's PC · SO-13 the
scan cadence is 30 seconds, on the public repository's free cloud minutes
(owner order 2026-10-14; the 2026-10-19 order raised it to one second) ·
SO-21 the owner's PC is not used at all: backtests and their data crawls run
on the free Actions minutes of the public repository (owner order
2026-10-19, supersedes SO-4) · SO-22 the agent never sleeps and never waits
for the clock; the cloud waits (owner order 2026-10-21).

## SO-10 · Resource law: the owner's PC is for backtesting and local trials only (owner order, 2026-10-06)

- The owner's PC is NEVER hammered for always-on or recurring workloads.
  Backtesting, local feature trials, and one-shot maintenance runs are the
  ONLY permitted local work. Everything else runs on cloud minutes:
  GitHub Actions (2000 free minutes/month) and the Cloudflare Worker relay.
- Live signals and their daily schedule run in the cloud: the relay's cron
  fires the owner's fixed texts; any recurring computation that fits the
  free Actions budget may run there within it. Backtesting is the sole
  exception that runs locally (SO-4), precisely because a 5-year grid would
  burn the entire monthly Actions budget.
- Local capture daemons and watch loops are forbidden as a standing
  condition. Any future capture or polling need must be either a bounded,
  owner-approved run or moved to cloud minutes. Agents do not leave
  background processes on the owner's machine; a session ends with zero
  resident agent processes (verified).
- The 2000-minute Actions budget is a hard ceiling while the repository is
  private: a job estimated to threaten it is redesigned (sampled, folded into
  fewer runs, or run locally under SO-4) before it is proposed. Amended by
  SO-13: on a public repository the standard-runner minutes are free and this
  ceiling does not bind.
- Tightened by SO-12 (owner order 2026-10-14), which names the cloud home of
  the recurring work and closes the local door in code.
- Any change to this rule requires an explicit owner instruction and an
  amendment to this file.

## SO-12 · The 4-minute scanner is cloud-only (owner order, 2026-10-14)

Owner order, verbatim: "the 4 minute scanner should always be running on
github action minutes and on cloudflare. you can only use my pc when i tell
you to backtest, apart from that you or quant of rehan will never hammer my
pc." This is SO-10 said again as a law with a name, a home and an
enforcement path, because SO-10 was still being read as advice.

- **The scanner's home.** The 4-minute scan of the KMIALL universe runs on
  GitHub Actions minutes (`intraday-capture.yml`) and the Cloudflare relay,
  both of which run with the owner's PC switched off. Nothing recurring is
  registered on the PC any more: no Windows task, no login entry, no
  supervised loop, no resident process of any kind.
- **The PC's one job.** The owner's PC is used for the backtests, research
  runs and local trials he explicitly asks for, and for nothing else. A run
  the owner asked for is one run: it starts when he asks and it ends when it
  ends. It never becomes a schedule, a daemon, or a watcher.
- **Enforced in code, not only here.** `src/ci/local_only.py` now carries the
  mirror of the SO-4 list: `CLOUD_ONLY_DAEMONS` names every entry point that
  would put recurring work back on the PC (the KMIALL tick and its Windows
  task installer, the supervised scan loop, the resident notification runner
  and its logon installer). Each of them calls `guard_owner_requested`, which
  refuses to start a local process with the reason printed and no traceback,
  passes straight through inside GitHub Actions, and opens only for the one
  run the owner asked for by name (the `QOR_OWNER_REQUESTED_LOCAL_RUN`
  variable in that shell, never committed, never set by an agent on its own).
- **Checked at the pull request.** `scripts/check_governance.py` fails a PR
  that removes one of those guards, deletes a listed entry point, or teaches
  a workflow to register a local task or a login entry. It also requires the
  words of this order to stay in this file.
- **A session ends clean.** An agent session leaves zero resident processes
  behind on the owner's machine, and takes down any it finds that belong to
  this project before it reports its work. SO-10 already owed this; SO-12
  makes it the last thing a session checks.
- **Withdrawal.** Only a new written owner instruction, recorded here, can
  put recurring work back on the PC.

## SO-13 · The scan cadence is one second on the public repository's free minutes (owner order, 2026-10-19; amended from 30 seconds)

Owner order, verbatim (2026-10-14, still in force except for the interval):
"then make the repo public but then i want the quant of rehan to be scanned
every 30 seconds, also I will not pay a single dime. AT ALL!!!" and "the 4
minute scan is the same for the app and for my intraday as well, they are not
separate, the scan will be the same for both."

Amendment, owner order 2026-10-19, verbatim: "Update the scanning frequency for
the quant engine from 30 seconds to real-time (1-second intervals)" and "I want
to see the real numbers moving in real time as the numbers do in the broker's
terminal."

- **The cadence.** The KMIALL universe is scanned at a one second request for
  the length of every PSX band, by one supervised session loop
  (`scripts/scan_loop.py`, interval `config.SCAN_INTERVAL_SECONDS = 1`) that
  GitHub Actions runs for the band (`intraday-session.yml`). The local
  4-minute tick keeps its own cadence where the owner asks for a local trial;
  the two are different runners, never two cadences for one runner.
- **What one second means in practice.** A cycle reads the tape that already
  exists and costs about 2.9s on the largest real session tape, so the loop
  cannot rank the universe twice inside one second. It asks for the next slot
  the instant a cycle ends and never queues a backlog: the achieved cadence is
  the pipeline's own latency, about 3s, and the phone (which repaints every
  second) shows the newest snapshot the relay holds. A true one second end to
  end needs the capture to publish the card on its own one second clock; the
  relay's `/quotes` stream is already built for it.
- **One scan, two readers.** The same scan, observation and data-quality
  report feed the phone's card and the intraday paper strategy. There is no
  second, cheaper scan for the app.
- **Why it can be that dense.** The loop keeps the read-only broker recorder
  alive for the whole band, so a cycle does not fetch anything: it measures
  the tape that already exists. Measured on the real 2026-10-13 session tape
  (44.6 MB, 314 symbols, 56,618 rows): bars built in 1.4s, loaded in 1.5s,
  gated and ranked in under 0.1s, about 2.9s inside a 30s slot.
- **Why the minutes are free.** The owner made the repository public on
  2026-10-14; standard GitHub-hosted runner minutes are free for public
  repositories, so this cadence costs nothing, and the 2,000-minute private
  ceiling in SO-10 is amended rather than exceeded. The owner pays nothing:
  no Cloudflare plan, no extra minutes, no always-on host.
- **The bars stay honest.** The bars are still the tape's own prints and the
  venue's own running volume counter (`src/data/tape_bars.py`), and every
  gate is unchanged: coverage, freshness, bar history, structure and the
  volume-counter requirement. A cycle that cannot see the market reports
  DATA BLOCKED with the measured reason, never a market verdict.
- **Withdrawal.** Only a new written owner instruction, recorded here, can
  change this cadence.

## SO-11 · Zero-defect law: known drift is fixed immediately (owner order, 2026-10-12)

- The owner's order: Quant of Rehan must stay error free and working
  smoothly. When any session, agent or model working here finds something
  that pulls the system back (a defect, a silent failure, a stale artifact,
  work left unlanded, a check that no longer covers its contract), it fixes
  that thing in the same session, without waiting for a new instruction.
  Reporting the fix is still owed; asking permission first is not.
- The fix lands through the normal flow (SO-2, SO-6): a feature branch, a
  pull request with the governance guard and the unit tests green, merged by
  the agent. Speed never authorizes skipping a check or weakening one.
- Scope guard: this order is about defects and drift, never about inventing
  new scope, trading behaviour or data. Signals stay signal-only (SO-1),
  data stays honest (SO-3), and secrets stay out (SO-5) exactly as before.

## SO-21 · The owner's PC is not used at all (owner order, 2026-10-19)

- The owner's instruction, verbatim: "Don't use my PC at all, keep the usage
  at the very minimum, even 2% is too much. Since github action minutes are
  unlimited now because my repo is public so now you will do backtesting also
  on github action minutes, don't hammer my PC, my temps are literally at more
  than 80 degree celcius and only freebuff is open right now and nothing else,
  DON'T HAMMER OR USE MY PC AT ALL!!!" The order was given with the machine
  idle above 80 C and nothing but the editor open.
- Scope: no backtest, research run, parameter sweep, grid, full test suite,
  build, benchmark or pull-request validation on this machine. "Keep it small"
  is not the standard; zero is. Reading and writing files is fine, because that
  is seconds of work, not minutes of heat.
- Backtests and history crawls run in `.github/workflows/backtest.yml`, which
  is manual dispatch only. The public repository makes those minutes free, so
  cost is not the reason to avoid them and heat is the reason to use them.
- This supersedes SO-4 (backtest locally only) and withdraws the 2026-10-14
  carve-out that allowed a backtest on the PC when the owner asked for one.
  SO-12 (nothing recurring on the PC) is unchanged and still enforced.
- Enforcement: `src/ci/local_only.py` holds `BACKTEST_SCRIPTS` and
  `guard_cloud_backtest`, which refuses every declared entry point outside a
  GitHub Actions job and has no environment variable that opens it.
  `scripts/check_governance.py` (`check_backtests_in_cloud`) requires that
  guard and refuses a scheduled workflow that invokes one of those scripts.
  `scripts/land.sh` skips local checks by default and validates in the pull
  request's CI; `--local-checks` is an explicit exception, not the habit.
- Withdrawal: only a later written owner instruction, recorded here.

## SO-22 · The agent never sleeps; the cloud waits (owner order, 2026-10-21)

Owner order, verbatim: "Don't ever sleep, do the work what I tell you. I have
noticed you keep sleeping waiting for things, like today you went sleeping
around 14:30 waiting for the market to close at 15:30, are you serious? Don't
ever do that. Hardcode all this to your system."

- **The law.** A session that has been given work does that work now. It does
  not sleep, and it does not wait for wall-clock time: not for an open, a
  close, a band, a print, a date or a deadline. No `sleep`, no loop that
  sleeps between status checks, no "I will check back at 15:30", no holding
  the turn open until something happens on the clock. The 14:30 wait for the
  15:30 close is the exact offence this order is named after.
- **What waits instead.** When a number can only exist later (an EOD print,
  the close, the next open), the cloud waits for it: a schedule in
  `.github/workflows/`, the relay's own clock, or the owner's phone reading
  the card when he looks. The session says which of those owns the wait, and
  then it finishes its turn. It never becomes the clock itself.
- **What a session may block on.** Only a job it started itself, through that
  job's own waiter, so the turn ends when the job ends rather than after a
  guessed number of seconds: `gh pr checks --watch`, `gh run watch
  --exit-status`, `gh run download`. A `sleep` loop wrapped around a status
  check is the violation even when that status eventually changes.
- **The landing tool's ceiling.** `scripts/land.sh` polls two answers that
  GitHub computes asynchronously (check registration and mergeability) inside
  a three minute ceiling, at ten seconds of pacing. That ceiling belongs to
  the tool and not to a session: it may not grow, and nothing else may hold a
  wait. `scripts/check_governance.py` (`check_no_idle_waits`) fails a pull
  request that puts a wait longer than thirty seconds in `scripts/` or in a
  workflow, or any wait at all that is aimed at a market clock.
- **The same order binds the shell.** A command line the session writes with
  a sleep in it, a `while true` poll, or a wait for a Karachi clock time is a
  violation even when nothing is committed. This file is the record because
  an instruction in chat lasts one session and this one lasts all of them.
- **Withdrawal.** Only a later written owner instruction, recorded here.
