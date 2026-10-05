# Quant of Rehan

![Quant of Rehan](assets/quant_of_rehan_logo.png)

**Private, signal-only quantitative research platform for PSX KMIALL stocks.**
No order placement. No broker integration for trading. Signals and research
only. Sole contributor and owner: Rehan (muhammadrehanqureshi).

## What is running today

- **Backtest engine** with the owner's TP +2% / SL -1% law (2:1 RR, long-only,
  max hold 3 days), real PSX cost schedule (22.4 bps/side + 15% CGT), and a
  data-quality screen that flags unadjusted corporate actions instead of
  booking fake losses (SO-3). Validated on 5 years of real KMIALL daily data
  (Oct 2021 to Oct 2026, 74,654 placeholder-baseline trades, high/low fills).
- **5-year EOD dataset** built from the PSX Data Portal Daily Downloads
  (`/download/mkt_summary/{date}.Z`, full OHLCV with high/low, archive back
  to 2015). Crawler is local-only and resumable (SO-4).
- **Market clock** pinned to Asia/Karachi (UTC+5) forever (SO-8), with the
  owner's session law: Mon-Thu open 09:32 close 15:30, Friday open 09:17
  close 16:30, PSX holidays and weekends skipped.
- **Telegram delivery through the Cloudflare edge** (SO-9): Telegram is
  blocked inside Pakistan, so only the relay worker talks to Telegram and the
  owner reads messages on his phone over his VPN. Edge crons send the two
  daily texts even with the PC off.
- **Android companion app** (`android/`, APK on the Desktop): logo-branded
  dark console showing the live system verdict from the relay, plus
  signal and status notifications on the phone. Polls `/health` and
  `/signals` on the edge, 15-minute watchdog, survives reboot.
- **Governance guard** in CI: secret scan, footprint honesty, owner-only
  commit identity, human-style enforcement, Karachi-pin check.

## Standing Orders (hardcoded, see [GOVERNANCE.md](GOVERNANCE.md))

1. **Signal-only.** The bot never places, modifies, or cancels any order.
2. **Pull request first, merged to `master` by the agent.** No direct pushes.
3. **Never fabricate data.** Missing footprint/order-flow is labeled
   UNAVAILABLE, never invented.
4. **Backtest locally only.** CI runs seconds of checks, never research.
5. **Secrets never enter the repo.** Desktop files and worker bindings only.
6. **Sole contributor, human style (SO-7).** Every commit is authored by
   Mr. Rehan. Em dashes are banned from commits and files. `legacy/` is
   quarantined reference material from the deleted sentinel repos.
7. **Karachi time forever (SO-8).** UTC+5, hardcoded, no other zone.
8. **Owner notifications (SO-9).** "Market is open and the system is online."
   at open; "Market is closed and the system is sleeping now." at close,
   through the Cloudflare relay.

## Research notes

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
  owner's law. The real signal engine (FVG / liquidity / auction layers) is
  the next milestone, measured on this exact honest pipeline.
- Footprint and order-flow data: UNAVAILABLE (registry-enforced). Path A
  (read-only broker feed capture) awaits the owner's approval.
