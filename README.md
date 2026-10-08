# Quant of Rehan

![Quant of Rehan](assets/quant-of-rehan-logo.png)

**Private, signal-only quantitative research platform for PSX KMIALL stocks.**
No order placement. No broker integration for trading. Signals and research
only. Sole contributor and owner: Rehan (muhammadrehanqureshi).

## What is running today

- **Daily-bar research engine** for the owner's TP +2% / SL -1% law. Its
  historical universe is today's KMIALL list and its prices are not fully
  corporate-action adjusted, so those results are survivorship-biased and
  affected by unadjusted prints. They do not validate the live signal rule.
- **5-year EOD dataset** built from the PSX Data Portal Daily Downloads
  (`/download/mkt_summary/{date}.Z`, full OHLCV with high/low, archive back
  to 2015). Crawler is local-only and resumable (SO-4).
- **Market clock** pinned to Asia/Karachi (UTC+5) forever (SO-8), with the
  owner's session law: Mon-Thu open 09:32 close 15:30, Friday open 09:17
  close 16:30, PSX holidays and weekends skipped.
- **Telegram delivery through the Cloudflare edge** (SO-9): scheduled
  GitHub Actions jobs keep sending system status to the app and Telegram.
- **Intraday paper research**: the scheduled workflow evaluates a small,
  preregistered one-minute to five-minute KMIALL strategy library. A research
  candidate is labeled PAPER SIGNAL. Production is gated by locked OOS
  economics plus confirmed data rights and latency. See
  [INTRADAY_FORWARD_SYSTEM.md](INTRADAY_FORWARD_SYSTEM.md).
- **Android companion app** (`android/`, APK on the Desktop, v1.3.0):
  logo-branded dark console showing whether the quant is working, plus
  signal and status notifications on the phone. Polls `/health` and
  `/signals` on the edge, 15-minute watchdog, survives reboot.

## The app

<p align="center">
  <img src="docs/app_ui.png" alt="Quant of Rehan app UI" width="320">
</p>

The console opens with the brand mark centered between gold rules, the
live status card ("Quant is working." with the Karachi clock), the latest
signal, the owner's reminder in the quiet of the screen, and the diamond
rule closing the frame at the bottom. The launcher icon mirrors the logo's
diamond-and-rule motif above AND below the candles at the same distance
(v1.3.0).
- **Governance guard** in CI: secret scan, footprint honesty, owner-only
  commit identity, human-style enforcement, Karachi-pin check.

## Standing Orders (hardcoded, see [GOVERNANCE.md](GOVERNANCE.md))

1. **Signal-only.** The bot never places, modifies, or cancels any order.
2. **Pull request first, merged to `master` by the agent.** No direct pushes.
3. **Never fabricate data.** Missing footprint/order-flow is labeled
   UNAVAILABLE, never invented.
4. **Backtest locally only.** No backtest, walk-forward or grid ever runs
   in CI. The one cloud exception (SO-10, owner approved): the daily
   post-close signal job on GitHub Actions fetches a bounded trailing EOD
   window and pushes the verdict; full-history crawls stay on the PC.
5. **Secrets never enter the repo.** Desktop files and worker bindings only.
6. **Sole contributor, human style (SO-7).** Every commit is authored by
   Mr. Rehan. Em dashes are banned from commits and files. `legacy/` is
   quarantined reference material from the deleted sentinel repos.
7. **Karachi time forever (SO-8).** UTC+5, hardcoded, no other zone.
8. **Owner notifications (SO-9).** "Quant is online now." at open;
   "Quant is sleeping now." at close, through the Cloudflare relay.

## Research notes

- [Final research and production audit](RESEARCH_FINAL_AUDIT.md): explains the
  27% result, data limitations, OOS economics, and current signal status.
- [Intraday forward system](INTRADAY_FORWARD_SYSTEM.md): documents registered
  candidates, automatic promotion/demotion rules, source checks, and current
  data limitations.
- Entry-metrics study (`scripts/entry_metrics.py`, report in
  `data/entry_metrics_report.json`, local only): MAE/MFE distributions,
  time-to-target, and horizon returns over 272,835 clean next-bar-open
  entries. Headline: within the 3-bar hold, +2% is reachable in 59.6% of all
  entries (63.0% baseline) with median time one bar, while 78.1% of all
  entries (80.3% baseline) touch -1% intraday. Stop placement is the binding
  constraint on this universe.

## Layout

```
src/data/sessions.py        Karachi-pinned clock, session law, owner texts
src/data/psx_daily_downloads.py   PSX Daily Downloads fetcher/parser
src/data/corpus.py          legacy eod_corpus.json loader
src/backtest/engine.py      TP/SL engine (conservative fills, invalid screen)
src/backtest/walkforward.py rolling-origin folds + leakage assertions
src/notify/telegram.py      env-driven notifier (fail closed)
src/notify/schedule_runner.py  local open/close scheduler with journal
cloud/worker.js             Cloudflare relay + edge crons (Karachi math)
cloud/pair.py               deploy + pair + test from the owner's PC
android/                    companion app source (signals + status on phone)
scripts/build_eod_history.py  resumable 5-year dataset crawler
scripts/entry_metrics.py    MAE/MFE, time-to-target and horizon study
scripts/check_governance.py secret, style, identity and SO-8 enforcement
legacy/                     quarantined code from the deleted sentinel repos
data/                       gitignored: datasets, journals, relay url
```

## Running things locally

```bash
# checks (same as CI)
python scripts/check_governance.py
python -m unittest discover -s tests

# notifications: one-time setup (message the bot on Telegram first)
python cloud/pair.py deploy && python cloud/pair.py discover && python cloud/pair.py test

# local scheduler (edge crons already deliver without the PC)
python -m src.notify.schedule_runner      # foreground
python scripts/install_scheduler.py       # auto-start at login

# data and research
python scripts/build_eod_history.py --start 2021-10-04 --end 2026-10-02
python scripts/smoke_backtest.py --dataset data/eod_history_kmi.csv.gz
```

## Current status

- Placeholder-baseline 5-year result: expectancy -1.06% per trade, win rate
  27.5%. That verdict belongs to the placeholder entry rule, not to the
  owner's law.
- Phase 1 research (2026-10-06, see RESEARCH_PHASE1.md): 74,654-trade causal
  matrix, A-G path analysis, survivorship sensitivity, frozen filter matrix.
  No edge claim; the stop/TP grid is banked pending the owner's review.
- Signal delivery runs on GitHub Actions and Cloudflare with the PC off.
  Daily FVG/sweep candidates remain research-only. The intraday workflow may
  send one PAPER SIGNAL per day; production stays disabled until every gate
  passes.
  App v1.3.0: centered brand header, "Quant is working." status line,
  motivational panel, framed dividers top and bottom, mirrored icon
  motif, "Quant is online/sleeping now." texts on the edge crons and
  relay.
- Historical intraday coverage is not sufficient: only one captured session
  (2026-10-06) is available in the local audit. GitHub Actions retains capture
  artifacts for 90 days. No historical minute-bar signal validation exists.
- Footprint and order-flow data: UNAVAILABLE. Captures contain OHLC, not
  order-book depth or bid/ask flow (see DATA_SOURCING.md).
