# GOVERNANCE — Hardcoded Standing Orders

**Owner:** Rehan (muhammadrehanqureshi) — the mastermind. All instructions flow
from him. **Agent:** Buffy / the QUANT — executes, never self-directs scope.

These orders are binding on every future session, agent, or model working in
this repository. They are enforced by `scripts/check_governance.py` (runs on
every PR via `.github/workflows/governance-guard.yml`) and by the review
conventions below.

## SO-1 · Signal-only, always

The bot produces BUY / WAIT / EXIT / NO TRADE **signals** for PSX KMIALL
stocks. It must never place, modify, cancel, or transmit any order to any
broker. No trade-side socket messages, ever. Broker credentials are never
loaded by any module in this repository.

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

## SO-3 · Never fabricate data — footprint honesty law

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
- GitHub Actions is limited to lightweight governance/health jobs measured in
  seconds. No scheduled jobs. No data pipelines. No backtests in CI.
- Monthly Actions budget: 2,000 minutes. Nothing in this repo may put that at
  risk.

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
retries deliberately — never blindly.

## Change procedure for this file

GOVERNANCE.md itself is amended only via pull request, and only on an explicit
instruction from the owner.
