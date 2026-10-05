"""
PSX KMIALL BOT
Shared core package.

Every production script imports from here instead of re-implementing
universe loading, path anchoring, session logic, or feed parsing.

Import convention for scripts under src/:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from psx_core import paths, universe, sessions, feed, storage, logs
"""

__all__ = [
    "paths",
    "universe",
    "sessions",
    "feed",
    "storage",
    "logs",
]

# The Sentinel's version. One constant, one source of truth.
# v2.0.0 (2026-09-17): the purge release - dead modules removed
# (postmortem, build_positive_open_pdf, mine_panels), the leak-free
# IC-fitted weight table is the live brain, same-day exits enforced by
# the closing sweep, and every refuted gate sits config-off.
# v3.1.0 (2026-09-24): the open bell - one "I am online" Telegram card
# per trading leg, so the owner never has to guess whether the machine
# woke up. Session doctrine made observable.
# v3.1.1 (2026-09-24): the owner's law - the Kalman trend filter and
# the Bollinger %B stretch veto are REMOVED from the rulebook and the
# master score (their 3% weight redistributed). The trend evidence is
# price-vs-VWAP only. Also fixes the fast-path UnboundLocalError that
# crashed a live cloud pass at 11:55 PKT (current_date read before
# assignment).
# v3.2.0 (2026-09-24): the whitelist law - Parkinson and Garman-Klass
# volatility, the Lo-MacKinlay variance ratio, and the divergence and
# correlation gates are removed; the indicator whitelist is ATR, Price
# Channel, EMA, RSI, MACD, Volume, VWAP. One change at a time from now
# on: nothing joins the bots until the owner orders it.
# v3.2.2 (2026-09-25): the dead-code sweep - every retired knob that
# decided nothing is deleted (the four Kalman config fields, the
# momentum-core switch, KALMAN_WINDOW/PARKINSON_WINDOW, the replay and
# sweep carries).
# v3.3.0 (2026-09-25): the owner's final word - the retired
# measurements are not even emitted as NaN schema placeholders anymore
# (kalman_trend_score, bollinger_pctb, variance_ratio, parkinson,
# garman-klass, divergence columns deleted). Old stored files still
# load; new feature schemas are exactly the whitelist.
# v4.0.0 (2026-09-26): the feed is the owner's ECLEAR broker terminal
# (read-only, MKT-FEED socket + ScripServlet master list) -
# psxterminal.com is retired everywhere and its fetchers, crawlers and
# parsers are deleted. Both bots' schemas are unchanged.
# v4.0.1 (2026-09-26): EXS-FEED group selection fixed - a closed-market
# capture put ALLSHR first and the first-group read returned the wrong
# index; the parser now selects the KSE100 group wherever it sits.
# Adds the local pipeline rehearsal and the trailing-stop audit
# scripts; sector map and company names regenerated from ScripServlet.
# v4.0.2 (2026-09-27): WhatsApp (CallMeBot) joins as the second backup
# delivery channel - every BUY/EXIT, session card and ops alert also
# texts the owner's WhatsApp when CALLMEBOT_PHONE and CALLMEBOT_APIKEY
# exist. Silent no-op without the secrets, never fatal, same dedup
# ledger as Telegram.
# v4.1.0 (2026-09-30): the 8-feature ranking layer (src/ranking.py)
# behind ranking_8f_enabled, the shared research core
# (src/psx_core/research.py: barriers, overnight labels, walk-forward
# folds, cost stack, signal log), and the overnight/feasibility
# studies of the book's own data.
# v4.3.0 (2026-10-02): the SENTINELS OF REHAN rebrand - every card
# carries the brand, the viewer APK is renamed "Sentinels of Rehan"
# (launcher icon and in-app header cut from the owner's logo, the
# dark-purple and gold UI), and pr-guard validates workflow YAML on
# every pull request.
# v4.3.1 (2026-10-02): the seatbelt survives its own death - the
# worker stamps a last_tick heartbeat every cron tick (Cloudflare
# silently stopped firing it on 2026-10-02), /alive reports the tick
# age, a 09:35 GitHub watchdog screams when the tick goes stale, the
# cron-down alarm+cure now fire off self-audit canaries and dispatch
# the proven keep-alive workflows, and Guard E delivers the MARKET
# CLOSED card at the bell on flat books too.
# v4.4.0 (2026-10-02): the Rule 27 tripwire - the daily self-audit now
# proves from the bot's own decisions log that every entry respects
# the penny floor, so a mystery "KEL call" on the owner's phone is
# machine-proven in or out of the bot within one audit cycle.
VERSION = "4.4.3"  # v4.4.3: heartbeat stamps on every run_decide return path (live_py) + stale-last-exit card marker (worker + APK) so a 28-day-old Rule-6 close is not headlined as a current exit.
# v4.4.3 (this round):
#   * src/live.py: heartbeat.stamp(source='live_py') now fires on EVERY
#     return path inside run_decide (fast-path, warm-up, cap-reached,
#     daily-loss-breaker, engine-evaluate, build-stage-failure and the
#     except-block fallback) - not only after run_decide returns in
#     run_live. Closes the 109-min 'heartbeat: N min ago' lie at 12:41
#     PKT on 2026-10-02 when no cloud pass fires during session hours.
#   * cloud/cloudflare/seatbelt-worker.js: summarizeBook() + 
#     recordLastClosed() now flag a closed trade as stale when its
#     exit_date is older than the last completed session, and expose
#     last_close_date so the card can say 'book flat since <date>'.
#   * android/ MainActivity.java: the 'Last exit' card line renders the
#     exit_date and a '(stale)' marker for old closes, and mutes the
#     headline when the most recent close is stale - so DCL -1.36% net
#     (Rule 6, closed 2026-09-05) is shown as a stale historical exit,
#     not a current one. The 'Recent exits' list also marks stale rows.
#   * ORB (z_orb 0.05) and ATR (z_atr 0.03, Wilder's ATR) were already
#     wired into the master blend before this round; this round adds no
#     new indicator math - it fixes the two display/trust bugs above.

