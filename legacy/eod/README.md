# Sentinel-EOD

The end-of-day next-day predictor for the **PSX KMIALL universe** - a
sister system to The Sentinel, built around one question: which stock,
bought at today's close, is most likely to give +2.0% tomorrow?

It runs entirely in the cloud on GitHub Actions. The owner's PC is
never needed.

## The daily rhythm (all times PKT)

| Time | What |
|---|---|
| 09:00 | Self-audit: freshness, suite, book integrity |
| 14:20 (Fri 15:20) | Reference capture: the final-hour surge baseline is stored |
| 15:00-15:23 (Fri 16:00-16:23) | Analysis window: score the whole universe |
| 15:21/15:24 + rescue :26 (Fri +1h) | Pick card published - MARKET OPEN card rides the pick run |
| by 15:25 (Fri by 16:25) | The card MUST be in hand - GitHub email + Telegram |
| next session 09:32 | Morning trace follows the pick: TP +2.0% / SL -1.0% / force-close 11:30 |
| 15:36 (Fri 16:36) | MARKET CLOSED card on GitHub + Telegram - both bots sleep until the next market day |
| 13:15 daily | Watchdog pulse: GitHub proves it is alive to the seatbelt; 26h of silence = Telegram alarm |

One pick per day, or an explicit "NO LIVE CANDIDATE - NO BUYING FOR
THE NEXT MARKET DAY" card. The bot ran and decided: stand aside. A
signal withheld by the data is not a dropped signal.

## The law

- **TP +2.0%, SL -1.0%, force-close 11:30** - the owner's universal
  law, permanent.
- **The lock class**: picks come from the >=8% close bracket, where
  next-session continuation actually pays. The >=500M distribution
  trap and the 5-8% failed-gap zone are vetoed.
- **Blow-off veto**: no pick from a close at the day extreme.
- **Dead-stock gate**: flat final-hour tape is never picked; positive
  late momentum required.
- **Lock-quality gates** (full-corpus validated): locks on >5x average
  volume (one-way distribution) and locks after a dead prior day are
  refused. Simple extension/quality thresholds - part of the clean
  core.
- **Liquidity floor**: price >= 20 PKR, traded value bar, thin names
  never eligible.
- **Volume Profile** (v3.5.0): the 10-session volume profile's point
  of control anchors the ninth tape layer (3% of the rank) - trading
  at the POC outranks fighting it from below; `vpvr_enabled`
  kill-switch.
- **Retired from production** (research code stays, opt-in via
  `eod_bot.MEMORY_LAYERS_ENABLED`): per-symbol lock memory, the
  rolling market lesson, the ledger weight re-fit. Outcomes are still
  traced and labeled every morning.

## Delivery

GitHub signals issue (email) is primary; Telegram is the independent
backup. A WhatsApp layer (CallMeBot) is built into the code but
DORMANT by the owner's decision (2026-09-30): the free relay could
not activate his number, so no secrets are set and the channel never
fires. A missing channel is retried by the watchdog slots from the
committed book, never re-decided. Every market day opens with a MARKET
OPEN card and closes with a MARKET CLOSED card on the live channels,
all times PKT. Every scheduled workflow job is fail-safe
(`continue-on-error`) - a crashed step can never red-X a run, so
GitHub never emails a failure; an ops alert rides Telegram instead.
The Cloudflare seatbelt (every 10 min) rescues a lost reference
capture and alarms if no card exists by :26.

## Layout

```
src/run_eod.py        the daily pipeline (reference / pick / trace / close-card)
src/eod_bot.py        scoring, tracing, net returns, volume profile
src/session_cards.py  MARKET OPEN / MARKET CLOSED cards (stdlib-only channels)
src/lock_memory.py    per-symbol lock memory (research; disarmed)
src/market_lessons.py the rolling market-lesson sync (research; disarmed)
src/lock_quality_gate.py grind-8/9 volume + prior-day quality gates
src/telegram_notify.py the backup channel (Telegram; dormant WhatsApp layer)
src/refresh_universe.py KMIALL universe freshness (owner's standing order)
src/psx_core/broker_feed.py the ECLEAR broker feed client (read-only)
data/picks/           one committed book per day
tests/                188 tests - run before every PR
```

## Market data (v4.0.0)

The feed is the owner's ECLEAR broker terminal, read-only: live
MKT-FEED ticks for the whole KMIALL universe plus the broker's shariah
list, the KSE-100 quote on the same socket, and the ScripServlet master
list behind the universe refresher (`src/psx_core/broker_feed.py`).
psxterminal.com is retired everywhere - the broker is a paid, regulated
business and its data tier is authoritative. The corporate-actions
notices the old source carried are dormant on the stored map
(`data/corporate_actions.json`); the book-closure and fresh-results
logic still rules on it.

## Verification

```
python -m pytest -q
```

Current: **v2.6.2** - the SENTINELS OF REHAN rebrand and the
verdict-card fix (2026-10-02): the "no live candidate" Telegram
card now actually sends - a NameError on an undefined name
silently ate the 2026-10-01 evening card (GitHub got it, Telegram
never did); every card failure is now LOUD in the log, every card
carries the SENTINELS OF REHAN brand, a pr-guard workflow
validates all workflow YAML on every pull request (a bad push can
never email a startup-failure again), and the pick card no longer
prints the vpvr feature twice. v2.6.3 (2026-10-02): the MARKET
CLOSED card arrived 22:09 PKT - 6.5 hours late - because GitHub's
dead crons burst-fired in the evening. The seatbelt now forces this
repo's close card at the bell (Guard E), the close-card workflow
gains 15:44/16:44 backup slots, an eod-keep-alive workflow cycles
the schedule registry weekly and on the seatbelt's canary signal,
and the close-card state commit can no longer be skipped silently.
v2.6.1 - the STRATEGY SWITCH to the morning-fade engine
(owner's order 2026-09-30): buy late momentum near the close, sell in
the first minutes of the next session. `src/morning_fade.py` carries
the new book (exactly 8 features, exactly 5 hard vetoes,
rank-top1-or-no-trade), `src/overnight_memory.py` feeds each stock's
OWN close-to-open history, `src/session_opens.py` records the real
next-session opening print, and the trace enforces the exit ladder
(open+5min sell, gap-stop, weak-open +15min, never hold a lock-open).
The legacy lock-continuation policy stays behind
`morning_fade.STRATEGY_SWITCH = False` for A/B. The WhatsApp layer
stays DORMANT (owner's decision 2026-09-30), delivery is GitHub email
+ Telegram, ECLEAR broker feed, PKT-only timestamps, fail-safe
workflows, and the owner's standing laws hardcoded in AGENTS.md:

1. PKT is the only clock.
2. Credentials owner-only but instantly printable to the owner.
3. Act, don't monologue.
4. GitHub changes go branch -> pull request -> merge. Direct pushes
   to main are banned for code changes.
5. Zero failure emails - every job is fail-safe.
6. One contributor forever: Mr. Rehan on every commit.
7. No em/en dashes anywhere, swept before every merge.
8. README always current the moment a PR merges.
9. **The broker terminal is READ-ONLY. No trading from it - not now,
   not later, until the owner explicitly orders it in writing. The
   bot trades nowhere but its own paper book.**
10. **The Actions allowance is a guardrail, never a fuel tank.** The
   free monthly minutes must never run out: a twice-weekly audit Telegrams
   at the 25% line, trims hit redundant slots first and never touch
   what the bot sees or decides.
11. **The WhatsApp layer stays DORMANT** (owner's order, 2026-09-30,
   superseding 2026-09-27): the CallMeBot relay could not activate
   his number (support confirmed a capacity overload), so the
   secrets are never set and the channel never fires. The code stays
   as a silent no-op in case he re-arms it one day.
12. **Bot B is the morning-fade trade** (owner's order, 2026-09-30,
   superseding the v2.3.0 lock law as the default): buy on late
   momentum near the close, sell in the first minutes of the next
   session; the pick is rank 1 or NO TRADE; the 5 vetoes are price<10,
   spread, liquidity, red market, circuit; never buy a stock locked into the
   close; the TP/SL law (2%/1%) governs only after a non-exited
   position reaches the 11:30 force-close.

Ledger to date: 6 closed outcomes, 3W-3L, +14.2% net total
(+2.4%/trade avg).
