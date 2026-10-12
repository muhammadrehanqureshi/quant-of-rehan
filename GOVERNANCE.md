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

## SO-4 · Backtest locally only

- All backtesting, walk-forward validation, and Monte Carlo runs execute on
  the owner's local PC.
- Backtesting, walk-forward validation, and Monte Carlo runs never execute
  in CI, and full dataset crawls stay on the owner's PC (a CI crawl of the
  5-year history is refused in code).
- Exception carved by SO-10 (owner approval, 2026-10-07): the daily signal
  job runs on GitHub Actions within the budget below. It may fetch only a
  small trailing EOD window (bounded by the CI guard in
  scripts/build_eod_history.py), never a full-history crawl.
- Monthly Actions budget: 2,000 minutes. Nothing in this repo may put that at
  risk.
- Owner order 2026-10-11: the GitHub Actions minutes are reserved for the
  market-hours scans, the 4-minute KMIALL work. Backtesting, walk-forward
  validation, Monte Carlo runs and the history research scripts run on the
  owner's PC and nowhere else.
- This is enforced in code, not only here. `src/ci/local_only.py` lists every
  local-only entry point, each of those scripts calls `guard_local_only` as the
  first statement of its `main()`, and that call stops a job running in
  GitHub Actions with the reason named and no traceback.
  `scripts/check_governance.py` fails a pull request that removes a guard,
  deletes a listed script, or teaches a workflow to invoke one.

## SO-5 · Secrets stay out

- Desktop credential files (`credentials.txt`, `PSX-Credentials.txt`) are the
  authoritative local sources. They are never copied into the repo, printed in
  full, or embedded in code.
- Runtime secrets come from environment variables or GitHub Secrets, with the
  canonical names documented in `DATA_SOURCING.md` § Secrets.
- `scripts/check_governance.py` scans every changed file for secret-shaped
  strings (`gho_`, `cfut_`, Telegram bot-token pattern, broker password) and
  fails the PR if any appear.

## SO-6 · The agent merges

The agent is responsible for opening **and** merging every pull request on the
owner's GitHub. The owner gives instructions; he does not click buttons. If a
merge fails (rules, conflicts, instability), the agent reports honestly and
retries deliberately: never blindly.

## Change procedure for this file

GOVERNANCE.md itself is amended only via pull request, and only on an explicit
instruction from the owner.

## SO-7 · Sole contributor and human-looking code (owner order, 2026-10-05)

- The owner, Rehan (muhammadrehanqureshi), is the only contributor this
  repository may ever show. Every commit carries his verified identity:
  `Mr. Rehan <muhammadrehanqureshi@users.noreply.github.com>`. No bot
  accounts, no co-author trailers, no generated-by footers, ever.
- Code, comments, and commit messages must read as if a careful human wrote
  them. No machine-generated stylistic artifacts. The strongest one: the
  em dash and any similar decorative dash are banned from every committed
  file and every commit message. Use a comma, a colon, parentheses, or
  split the sentence.
- `scripts/check_governance.py` enforces both rules: it scans tracked files
  (excluding `legacy/`, which is quarantined reference material from the
  deleted sentinel repos and is never modified) and every new PR commit
  message. A violation fails the PR.

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

- Telegram is blocked for direct connections inside Pakistan. The system
  therefore never calls api.telegram.org from the owner's PC. Delivery goes
  through the quant-of-rehan Cloudflare Worker relay, which runs on the
  Cloudflare edge outside that block. The owner reads messages on his phone
  over his VPN as he always has.
- The owner receives, every trading day: "Quant is online now." at open,
  and "Quant is sleeping now." at close, per the SO-8 schedule (owner order
  2026-10-07 reworded the texts from the market/system phrasing). These
  texts are fixed by the owner.
- The local scheduler retries through the relay and fails closed with a
  clear log line when delivery is impossible. No signal is ever silently
  dropped and none is ever fabricated.

## Standing orders index

SO-1 signal-only · SO-2 PR first, agent merges · SO-3 never fabricate data ·
SO-4 backtest locally only · SO-5 secrets stay out · SO-6 the agent merges ·
SO-7 sole contributor, human-looking code, no em dashes · SO-8 Karachi time
forever · SO-9 owner notifications via the Cloudflare relay · SO-10 resource law: cloud-first, local only for backtests · SO-11 zero-defect law: known drift is fixed immediately.

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
- The 2000-minute Actions budget is a hard ceiling: a job estimated to
  threaten it is redesigned (sampled, folded into fewer runs, or run
  locally under SO-4) before it is proposed.
- Any change to this rule requires an explicit owner instruction and an
  amendment to this file.

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
