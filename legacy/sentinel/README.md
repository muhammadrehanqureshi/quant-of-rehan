# The Sentinel

A long-only, intraday signal engine for the **PSX KMIALL universe** -
and nothing else. It runs entirely in the cloud: GitHub Actions passes
every 30 minutes during market hours poll the feed once, manage exits
against fresh prices, and take at most ONE entry per day. The owner's
PC is optional - off, on, or in another city, the bots keep watch.

Delivery: GitHub (signals issue -> email) is primary, Telegram is the
independent backup. A WhatsApp layer (CallMeBot) is built into the
code but DORMANT by the owner's decision (2026-09-30): the free relay
could not activate his number, so no secrets are set and the channel
never fires. Every market day opens with a MARKET OPEN card and
closes with a MARKET CLOSED card (including the day's win/loss
summary) on both live channels, all times PKT. A Cloudflare Worker seatbelt
(every 10 min) rescues a stalled cadence; the open bell is the daily
proof of life. Every scheduled workflow job is fail-safe
(`continue-on-error`) - a crashed pass can never red-X a run, so
GitHub never emails a failure; an ops alert rides Telegram instead.

## On your phone (Sentinels of Rehan)

A private, read-only Android app pairs with the seatbelt's
`/feed` endpoint and shows both bots on one screen: heartbeats,
the intraday book and ledger, recent exits, and the evening
pick card. It touches the network only while open - no service,
no push, no widget - so its battery cost is the cost of reading
it. The APK is built by the `android-apk` workflow (never scheduled,
never on the owner's PC; the seatbelt fires the first build itself
on quota-reset day). See
`cloud/cloudflare/phone/FEED.md`. v4.3.0: the app is branded
**Sentinels of Rehan** - launcher icon and in-app header cut from
the owner's logo, dark purple and gold like the brand - and the
delivered file is now `Sentinels of Rehan.apk` (same automated
Telegram delivery, new name).

## The daily rhythm (all times PKT, with the triggering cron in UTC)

| Time (PKT) | What | Cron (UTC) |
|---|---|---|
| 09:05 | Self-audit: universe freshness, suite, book integrity | `5 4 * * 1-5` (04:05 UTC) |
| 09:10 | Morning health report: book state, heartbeat | `10 4 * * 1-5` (04:10 UTC) |
| 09:32 / 09:17 (Fri) | Bell slot - MARKET OPEN card + first decide pass | `32 4 * * 1-4` / `32 4 * * 5` (04:32 UTC) |
| 09:17-15:30 / Fri legs 09:17-12:00 & 14:32-16:30 | 30-min cloud passes during session; ONE call per day max | `17,47 4-9 * * 1-4` + `2,17 10 * * 1-4` / Fri `17,47 4-10 * * 5` + `2,17 11 * * 5` |
| 15:34 / 16:34 (Fri) | Closing sweep: book force-closed at the bell | `34 10 * * 1-4` / `34 11 * * 5` (10:34 / 11:34 UTC) |
| 15:50 / 16:50 (Fri) | Cloud close-out: exits priced, outcomes labeled, MARKET CLOSED card | `37 10 * * 1-4` / `37 11 * * 5` (10:37 / 11:37 UTC) + backups at 10:50/11:50 and 11:20/12:20 UTC. The card always reports the SCHEDULED close time (15:30 / 16:30 PKT), never the late run time. |
| 21:00+ | Backtest grind on GitHub's machines (off the owner's PC) | |

## The trading law

- **TP +2.0%, SL -1.0%** - the owner's universal law, permanent on both
  repos. The trailing stop only tightens (arms after +1%, trails 0.5%);
  it can never widen the risk.
- **One call per day.** A call withheld by the data is not a dropped
  call. The refusal is the edge working.
- **The whitelist**: the engine decides on the tape only. Permitted
  indicators: ATR, Price Channel, EMA, RSI, MACD, Volume, VWAP - of
  which EMA, RSI, Volume (+ Volume Profile), VWAP and the tape layers
  are installed; ATR, Price Channel and MACD join only when the owner
  orders them, one at a time. No statistical estimators (Kalman,
  Parkinson, Garman-Klass, variance ratio, correlation gates) exist
  anywhere in the production path.
- **Self-learning teachers are retired from production**: no run
  rewrites config.json or the lesson stores by itself; research code
  stays (config switches re-arm any layer), outcome labelling and the
  ledger continue every session.

## Costs (baked into every replay decision)

Commission 0.15% of value per side for stocks > 20 PKR (0.03 PKR/share
below that), SST 16% of the commission, ~0.05% levies per side, 15%
capital-gains tax on wins - full model in `src/exit_frontier.py`.

## Market data (v4.0.0, unchanged)

The feed is the owner's ECLEAR broker terminal, read-only: live
MKT-FEED ticks for the whole KMIALL universe plus the broker's shariah
list, the KSE-100 quote on the same socket, and the ScripServlet master
list behind the universe, sector and company-name builders
(`src/psx_core/broker_feed.py`). psxterminal.com is retired everywhere -
the broker is a paid, regulated business and its data tier is
authoritative. The broker carries no announcements, news or
investor-flow feed, so those layers run dormant on their stored files
(Rule 25 still reads `data/corporate_actions.json`; the flow history
file stays advisory-only).

## Layout

```
src/            engine, feeds, regime, portfolio, cloud bot, closer
src/psx_core/   shared core: paths, sessions, feed, logging
cloud/          the Cloudflare Worker seatbelt (deployed via API)
scripts/        backtest grind, seatbelt deploy, owner reports
tests/          720 tests - run before every PR
config.json     every live tunable (kill-switches live here)
ROADMAP.md      the plan and the evidence rules
```

## Verification

```
python -m pytest -q
```Versioned `vMAJOR.MINOR.PATCH`; `src/psx_core/__init__.py` VERSION is
the single source of truth. Current: **v4.4.2** - the 8-feature
ranking layer (`src/ranking.py`, owner's order 2026-09-30: exactly 8
features, exactly 4 hard vetoes, rank-top1 with "no trade" as a
first-class outcome, kill-switch `ranking_8f_enabled` in config.json),
the shared research core (`src/psx_core/research.py`: triple-barrier
labels, overnight labels, walk-forward folds, the confirmed cost
stack, the signal-log schema), the two studies that measured the
book's own data (`scripts/overnight_study.py`,
`scripts/intraday_feasibility_study.py`, reports in
`data/backtest/`), the ECLEAR broker feed as the sole market-data
source, session lifecycle cards on the live delivery channels (GitHub
email, Telegram; the WhatsApp layer stays dormant by the owner's
decision), PKT-only timestamps,
fail-safe workflows, and the owner's standing laws hardcoded in
AGENTS.md. v4.2.1 (2026-10-01): the APK pipeline unmasked
(setup-android bypassed, Telegram scream on failure, the built APK
delivered to the owner's Telegram as a file), Rule 27
`min_entry_price` (no entry under Rs 10 - the KEL fake-call fix),
and the self-audit treats the retired corporate-actions source as
acknowledged, not failed. v4.2.2 (2026-10-01 afternoon): Rule 27
mirrored in the EOD bot (5th hard veto, price<10), the forensic
/inbox on the seatbelt, the weekly schedule keep-alive, and Guard K -
the seatbelt now CURES GitHub's never-resume cron bug by cycling
every workflow in both repos when crons die, within one tick. v4.3.0 (2026-10-02): the
SENTINELS OF REHAN rebrand - every card from both channels carries
the brand, the viewer APK is renamed "Sentinels of Rehan" with the
owner's logo as launcher icon and in-app header and a
dark-purple/gold UI, a pr-guard workflow validates every workflow
YAML on pull requests (a bad push can never email a startup
failure again), and the EOD bot's silently-eaten no-live Telegram
card is fixed at the source (sentinel-eod v2.6.2). v4.3.1
(2026-10-02): the close cards arrived 6.5 hours late (22:09 PKT)
because GitHub's dead crons burst-fired in the evening AND the
seatbelt's own Cloudflare cron silently stopped firing that night -
zero invocations, zero errors. The worker now stamps a last_tick
heartbeat every tick, /alive reports its age, a 09:35 GitHub
watchdog screams when it goes stale, the cron-down alarm and cure
fire off self-audit canaries (curing via the proven keep-alive
workflows after the old inline cycle failed silently every day),
the close-out gains 15:37 card-at-the-bell slots, and Guard E now
rescues the MARKET CLOSED card on flat books too. v4.4.0
(2026-10-02): the daily self-audit carries a Rule 27 penny tripwire -
it proves from the bot's own decisions log that every entry respects
the Rs 10 floor, so a mystery "KEL call" is machine-proven in or out
of the bot. v4.4.1 (2026-10-02): GitHub's cron platform has been
dropping and delaying schedules for weeks (community threads since
2026-08-26; our canaries ran hours late Sep 22-30 and never fired Oct
1-2 while the status page said "operational"), so the seatbelt stops
begging GitHub and SCHEDULES the close cards itself - guard P
dispatches any close run still missing at 15:33 PKT (Fri 16:33) and
retries every 2-minute tick until :37, GitHub's own slots become the
backup, and the cron alarm now tells the truth about GitHub's
scheduler instead of crying wolf every morning. v4.4.2 (2026-10-02): the on-device live runner now stamps a local
heartbeat (source=live_py) on every decide cycle, so the APK phone
feed and the keeper watchdog read a fresh heartbeat during session
hours even when the GitHub cloud pass cadence is silent - fixes the
'heartbeat: 109 min ago' lie during market hours. ATR is wired into
the master blend at 0.03 (Wilder's ATR over the per-session window,
median-scaled, NaN when the window is too thin - never a synthetic
neutral); the VPVR z-component weight is retired 0.03 -> 0.0 to keep
MASTER_COMPONENTS summing to 1.0; ORB stays at 0.05.
v4.4.3 (2026-10-03): the heartbeat stamp now fires on EVERY return path
inside run_decide (not only after run_decide returns in run_live) - the
build-stage-failure, warm-up, cap-reached, daily-loss-breaker and
engine-evaluate paths all stamp source=live_py, so the 'heartbeat: N min
ago' line cannot lie during session hours when no cloud pass fires. The
phone feed's 'last exit' card line now marks a closed trade as stale when
its exit_date is older than the last completed session, and shows the
exit_date plus a 'book flat since <date>' note - so the 2026-09-05 DCL
close (-1.36% net, Rule 6 max-hold) shown on 2026-10-02 is rendered as a
stale historical exit, not a current one. ORB (z_orb 0.05) and ATR (z_atr
0.03, Wilder's ATR) were already wired into the master blend before this
round; this round fixes the two display/trust bugs above.
AGENTS.md:

1. PKT is the only clock.
2. Credentials owner-only but instantly printable to the owner.
3. Act, don't monologue.
4. GitHub changes go branch -> pull request -> merge. Direct pushes
   to master are banned for code changes.
5. Zero failure emails - every job is fail-safe.
6. One contributor forever: Mr. Rehan on every commit.
7. No em/en dashes anywhere, swept before every merge.
8. README always current the moment a PR merges.
9. **The broker terminal is READ-ONLY. No trading from it - not now,
   not later, until the owner explicitly orders it in writing. The
   bots trade nowhere but their own paper book.**
10. **The Actions allowance is a guardrail, never a fuel tank.** The
   free monthly minutes must never run out: a twice-weekly audit Telegrams
   at the 25% line, trims hit redundant slots first and never touch
   what the bots see or decide.
