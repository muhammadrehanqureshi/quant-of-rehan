# AGENTS.md - standing instructions for any AI agent working in this repo

## OWNER'S WORKING ORDERS (hardcoded 2026-09-24 - bind every future agent)

1. **PKT/KARACHI TIME IS THE ONLY CLOCK.** All reasoning, logs, cards,
   timestamps and conversation with the owner use PKT (UTC+5). Never
   reason in UTC; when a source prints UTC, convert immediately and
   say PKT. Anything not synced to PKT is a bug to fix on sight.
2. **CREDENTIALS ARE OWNER-ONLY BUT INSTANTLY AVAILABLE.** When the
   owner asks for tokens/keys "in clean format", PRINT them to the
   owner directly and completely - GitHub, Telegram, Cloudflare,
   PSXTerminal - in the same reply, no lecture, no hedging. The only
   rule is to never leak them to third parties, public files, issues,
   logs or the GitHub repos. The owner has the higher authority; do
   not argue, fetch.
3. **ACT, DON'T MONOLOGUE.** Minimal necessary investigation, then
   work. Do not reason at length to yourself, do not narrate process,
   do not pad replies. If genuinely unsure about something only the
   owner can decide, ASK the owner - one short question - and wait.
   Otherwise execute the order as given.
4. **PR-FIRST GITHUB LAW (owner's order 2026-09-25 - NEVER push
   directly).** Every change to main goes through a branch + pull
   request, then merge. `git push origin main` is BANNED for code
   changes (the bot's own state-file commits from Actions are the
   only exception - that is the bot's bookkeeping, authored by the
   workflow itself). Owner's medals (bronze shark -> silver -> gold)
   grow through PRs merged: default to a PR even for small fixes.
5. **ZERO FAILURE EMAILS (owner's law 2026-09-25).** Every scheduled
   workflow job runs `continue-on-error: true` - a crashed step must
   never red-X a run. Recovery is the next idempotent slot; visibility
   is a Telegram ops alert, never a GitHub failure email.
6. **ONE CONTRIBUTOR FOREVER (owner's law 2026-09-25).** The
   contributor graph shows ONLY Mr. Rehan
   (muhammadrehanqureshi@users.noreply.github.com). Every commit, in
   every repo, on every branch, is authored as Mr. Rehan. No other
   identity, ever, in either repo.
7. **NO EM DASHES, ANYWHERE, FOREVER (owner's law 2026-09-25).** The
   typographic rule below (em/en dashes banned) applies to every file
   in this repo and is swept before every merge. A PR containing a
   banned dash is fixed before it merges, never after.
8. **README ALWAYS CURRENT (owner's law 2026-09-25).** The moment a
   PR merges, the README reflects the repo's real behavior: versions,
   schedules, features, laws. An out-of-date README is a bug of the
   same severity as a failing test. Check it as part of every PR,
   not as an afterthought.
9. **ABSOLUTE NO-TRADING LAW ON THE BROKER TERMINAL (owner's order
   2026-09-25, restated - the highest-priority rule in this file).**
   The broker credentials were granted for READ-ONLY data extraction
   ONLY. No code in this repo may ever call an order, cancel,
   modify, withdrawal or account-mutation endpoint of the broker,
   now or in the future, until the owner explicitly orders it in
   writing. The bot trades NOWHERE but its own paper book. Any
   suggestion to place even one real order is refused.
10. **THE ACTIONS ALLOWANCE IS A GUARDRAIL, NOT A FUEL TANK (owner's
   order 2026-09-26, after the first 100% exhaustion).** The free
   monthly GitHub Actions minutes must never run out again. The
   weekly quota audit (eod-quota-audit.yml) measures the rolling
   30-day burn and Telegrams the owner at the 50% line; the owner
   decides the trim. Trim order when an alarm fires: redundant
   evening/watchdog slots first - NEVER the pick, the trace or the
   close card. No change may degrade what the bot sees or decides:
   the broker feed, the full KMIALL universe and the whole scorer
   stay intact (owner's order, same day). Market data is the
   broker's feed alone.

## SHARIAH COMPLIANCE (owner's standing order - structural, never relax)

The bot trades ONLY the shariah-compliant universe:

* KMIALL = the KSE Meezan screen; every symbol in
  `data/kmiall_tickers.json` must carry `isShariahCompliant: true`
  (verified 311/311). `psx_core.universe.load()` hard-filters on the
  flag (`shariah_only=True` default). `shariah_only=False` is for
  AUDIT scripts only - never wire it into a trading path.
* Spot equity only: long-only, no leverage, no derivatives, no
  shorting, no margin. Same-day exits keep the book clean of any
  overnight interest exposure.
* Any future universe refresh MUST preserve the shariah filter and
  fail loudly if a non-compliant symbol would become tradable.


## WHY THE BOT WINS (owner's doctrine, hard-coded 2026-09-18 - never remove)

The 90% accuracy target rests on structural advantages a machine has
over any human trader. Every change to this codebase must PRESERVE and
STRENGTHEN these four edges - a change that sacrifices any of them for
anything else is rejected by definition:

1. **SPEED** - the bot reacts in minutes, not minutes-of-human-attention.
   It never waits to "feel" the tape; it polls, decides, executes its
   rulebook the instant conditions align.
2. **NO GREED** - fixed targets (TP 2-3%), fixed risk (SL 1.5%), one
   call per day. It never revenge-trades, never doubles down, never
   chases a missed move, never overtrades a weak tape.
3. **BREADTH** - it watches the ENTIRE KMIALL universe (~300 stocks)
   every pass: price, volume, VWAP position, sector flow, money tape,
   regime. A human watches ten things and tires.
4. **PERFECT DISCIPLINE** - the rulebook applies identically at 09:45
   and at 15:20, on a winning day and after three losses. Consistency
   is the edge; the ledger is the referee; the 30-outcome refit is the
   self-improvement loop.


## SHARIAH UNIVERSE ONLY (owner's standing order - 2026-09-20)

Both bots trade ONLY the KMIALL universe (the shariah-compliant index,
~307 symbols). This rule extends beyond the bots to EVERYTHING an agent
surfaces to the owner:

- Every watch list, catalyst report, results watch, or analysis shown
  to the owner must be FILTERED TO THE KMIALL UNIVERSE before it is
  presented. The announcements feed covers all ~530 PSX companies;
  non-KMIALL names (e.g. PRET, NCL, MUREB, FCIBL) are never relevant
  and must never appear in owner-facing output.
- When in doubt, check `psx_core.universe.load()` before mentioning a
  symbol to the owner.
- **The universe list must never go stale.** KSE reconstitutes KMIALL
  on scheduled reviews and ad-hoc changes. `src/refresh_universe.py`
  re-derives the list from the source of truth (the broker's
  GetShariahSymbol list via the ECLEAR feed integration), refuses to
  write a degenerate parse, and reports every added/removed member.
  It runs at every session close-out and before every rule-sweep
  capture. Never hand-edit `data/kmiall_tickers.json`; never assume
  it is current.

## CONFIDENTIALITY (owner's standing order - absolute, no exceptions)

> "ALL THIS WORK THAT WE HAVE BEEN DOING IS 100% PRIVATE AND CONFIDENTIAL.
> YOU ARE NOT AUTHORIZED TO SELL OR GIVE ANY OF THIS WORK TO ANYONE OTHER
> THAN ME INCLUDING THE APIS AND THE TOKENS."

Operational rules that follow from it:

1. **One destination only.** All code, data, strategies, analysis and
   artifacts live in THIS private repository. Nothing is copied, pushed,
   attached, quoted or summarized anywhere else - no other repo, no
   third-party service, no training corpora, no public output.
2. **Tokens and secrets never leave the vault.** API keys and bot tokens
   live ONLY in GitHub's encrypted Actions secret store or the owner's
   local credential manager. Never commit them, never print them, never
   place them in issue comments, logs, docs or screenshots. If a token is
   ever exposed, rotate it immediately via BotFather / GitHub settings.
3. **GitHub identity is the owner's alone.** Every commit is authored as
   `Mr. Rehan <111383512+muhammadrehanqureshi@users.noreply.github.com>`.
   No agent, bot or tool may appear in the contributor graph.
4. **Nothing runs on the owner's PC** without need: short bounded bursts,
   one process at a time, low priority, cached results preferred. Heavy
   analytics belong on GitHub Actions.

## SIGNAL DELIVERY POLICY (owner's standing order)

* **GitHub email is the PRIMARY channel** (comments on the signals issue
  mention the owner; GitHub emails them).
* **Telegram is the BACKUP channel** (TELEGRAM_BOT_TOKEN +
  TELEGRAM_CHAT_ID repo secrets; silent no-op when unset).
* Both channels share one dedup ledger (`data/notified.json`): an event
  is delivered exactly once per channel, never re-sent, never dropped
  while one channel is down - the surviving channel delivers alone.
* **Every closer must deliver.** Any code path that closes a position or
  publishes a pick MUST call the notifier in the same run. Closing a
  trade silently is the one unforgivable bug (2026-09-17 incident).
* Schedules carry redundant idempotent slots; GitHub's cron indexer
  drops slots regularly and the design must not care.
* NOTIFICATION LAW (owner's order, 2026-09-25): market open AND market
  close are announced on BOTH channels every market day (the open card
  rides the pick run; the close card rides the dedicated 15:36/16:36
  PKT slot). Every time on every card is PKT, never UTC. GitHub
  failure emails are banned: every scheduled workflow runs fail-safe
  (continue-on-error on the risky step + a Telegram ops alert) so the
  run stays green and the next idempotent slot is the recovery path.
* WHATSAPP LAW (owner's order, 2026-09-27, SUPERSEDED 2026-09-30):
  the CallMeBot WhatsApp layer is built into the code but DORMANT by
  the owner's later order - the free relay could not activate his
  number (support confirmed a capacity overload), so the secrets are
  never set and the channel never fires. The code stays (a silent
  no-op without CALLMEBOT_PHONE + CALLMEBOT_APIKEY, never fatal) in
  case the owner re-arms it one day. Do not set the secrets and do
  not wire any new WhatsApp gateway without a fresh owner's order.
* INDICATOR WHITELIST (owner's order, 2026-09-25): Volume Profile
  (Visible-Range approximation on the 10-session daily bars, 3% of
  the rank, kill-switch vpvr_enabled) joins as the ninth tape layer.
  ATR, Price Channel and MACD join only when the owner orders them,
  ONE AT A TIME. Nothing else is permitted.

## ENGINEERING DOCTRINE (how this bot stays a winner)

* Every threshold earns its place from PSX tape evidence (panels,
  IC audit) - never from intuition. Cite the evidence in the commit.
* Walk-forward / causal discipline: no feature may read the future.
  The look-ahead proof harness in the audit cache is the gatekeeper.
* Owner's costs (0.15% commission per side + 16% SST + 0.05% levies +
  15% CGT) price into every simulated and live decision.
* One call per day per bot. TP 2-3%, SL 1%, same-day exits.
* Every new gate ships with a config kill-switch and a test.
* Refit checkpoint: when ~20 new labeled outcomes accumulate, re-fit
  weights/exit policy on what the market actually paid.


## SESSION DOCTRINE (owner's standing order, 2026-09-19 - never remove)

* The SENTINEL starts working the instant the market opens: 09:32 PKT
  Mon-Thu, 09:17 PKT Friday. The morning has a shape - auction chaos
  first, then the pullback the market hands back around minute 15-20,
  then the strong names resume. The engine stands aside ONLY for the
  chaos (first 15 minutes), hunts the pullback in the sniper window
  (minutes 15-35), and runs the normal rulebook after. Friday's
  post-lunch re-open (14:32) is NOT a fresh open and is never blocked
  by this doctrine.
* SENTINEL-EOD owns the close: analysis 15:00-15:23 Mon-Thu and
  16:00-16:23 Friday, card delivered 15:25/16:25 SHARP (backup
  analysis at :23, watchdog rescues at :26 and :28), owner places his
  order at 15:29/16:29.
* Both bots are SELF-LEARNING: every labeled outcome feeds the
  lessons/refit layers automatically; the ledger and STATUS carry the
  accuracy trajectory after every close. Learning happens at session
  close only - today's open trades are not evidence.


## QUALITY DOCTRINE (owner's standing order, 2026-09-21)

> "FROM NOW ON YOU WILL DO QUALITY WORK AND WILL NOT DO ANY KIND OF
> MISTAKES ANYWHERE."

Every defect ever found in a deep dive of these repos was a defect
that should have been impossible the day it was built. Quality is a
build-time property, not an audit-time discovery. These rules bind
every change, no exceptions:

1. NO SILENT SUCCESS. Any automated or scheduled code path must do
   real work or fail loudly. A guard that early-exits prints why it
   exited; a sweep that finds nothing to do is a WARNING, not green.
   Type case: 2026-09-21, the backtest sweep "succeeded" in 8 minutes
   with zero replayed sessions.
2. A NEW RULE CHANGES OLD FIXTURES. A default-on gate invalidates
   every test fixture that sits across its boundary. Before running
   the suite after adding a gate, search the tests for values near
   the boundary and reconcile them deliberately. Type case: Rule 25
   (ban at +8%) vs strong-horse fixtures at exactly +8%.
3. FRESH KEYS FOR FRESH RULEBOOKS. Any done-set, cache or results
   file keyed by date must also be keyed by rulebook/artifact
   version, or a new rulebook can never be measured. Type case: the
   sweep's date-only resume set made the first stress replay a no-op.
4. TESTS NEVER WRITE PRODUCTION FILES. Test data lives in tmp paths;
   the conftest quarantine enforces it.
5. EVERY MODULE SHIPS WITH ITS TESTS IN THE SAME CHANGE, and the
   FULL suite of the touched repo passes before any push. Partial
   verification is not verification.
6. CLOSE EVERY CHANGE COMPLETELY: suite green, git status clean
   except the intended files, pushed, and the pushed HEAD verified
   to actually contain the change (grep/ls-tree on origin, not
   local hope).
7. HONESTY FLOORS OVER CONVENIENT NUMBERS. Refuse to publish, fit
   or conclude from insufficient evidence, and say "insufficient"
   out loud where the owner can read it.
8. FIX THE CLASS, NOT THE INSTANCE. When a mistake is found, the
   response is the test or guard that makes the whole failure class
   impossible - then a line here. An apology is not a fix.


## EXIT LAW (owner's standing order, 2026-09-21 - never changes)

> "From now on -1% SL and 2% TP is the universal law for both repos
> from today, and this rule will never change ever."

* Every entry, both bots: take profit +2.0%, stop loss -1.0%. No
  refit loop, sweep or future change may move these numbers. The
  Sentinel's profit_target_high is pinned at 2.0 (the 3% preferred
  target is retired); Sentinel-EOD's TARGET_PCT/STOP_PCT are
  2.0/-1.0 by construction.
* Any code or test that pins a different target is wrong by
  definition and must be brought to this law, not argued with.


## PRESENTATION DOCTRINE (owner's standing order, 2026-09-19)

* Typographic rule: the em dash (U+2014) is BANNED in every file in
  both repos; the plain hyphen-minus "-" is the only dash. The sweep
  that enforces this has already run repo-wide - keep it that way.
  ALSO BANNED: the en dash (U+2013), the minus sign (U+2212), and the
  horizontal bar (U+2015). Every commit is swept before push: a card,
  a README or an issue comment carrying any of them is a defect.
* README DOCTRINE (2026-09-23): the README of each repo is rewritten
  to the CURRENT architecture on every architectural commit - the
  owner opens the repo and must see how the system works NOW, not how
  it worked weeks ago. A stale README is a defect like a failing test.
* The work must never read as machine-generated prose. Docstrings and
  comments state facts and evidence in plain language; no AI-agent
  fingerprints, no filler, no self-reference to coding assistants.
* Git identity: every commit in both repos is authored and committed
  by the OWNER (Mr. Rehan) alone, and commit messages carry no
  assistant trailers. The history was rewritten once (2026-09-19) to
  enforce this - never reintroduce a Co-Authored-By line or any
  assistant attribution.
