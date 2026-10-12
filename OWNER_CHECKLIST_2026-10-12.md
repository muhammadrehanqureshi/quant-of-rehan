# Quant of Rehan, operations checkup and owner checklist

**Date:** 2026-10-12, ~14:25-14:36 PKT, taken while the PSX session was live.
**Scope:** repo state, test suite, governance, local services (tape, tick, notifier), data health, relay and phone card, GitHub Actions.
**Method:** every claim below was measured just now, live process/files/API reads, the CI test command, and the vendor endpoint probed directly.

---

## 1. Verdict

Everything that can run locally **is** running, and nothing in the codebase is erroring. The one hard failure is the **intraday quote vendor**: the OHLC servlet has returned nothing for the whole session (0.0% coverage), so the scanner correctly stayed `DATA_BLOCKED` and took no trades. The one process gap is that **no alert reached the phone today** about that outage.

- ✅ 705 tests pass; governance guard passes; PR CI green.
- ✅ Tape daemon, 4-minute tick, notification runner, relay, and phone card all live and fresh.
- ⛔ Intraday quote source returning bare acknowledgements since at least 2026-10-09 → no intraday bars, no scans.
- ⚠️ Outage did not page the owner today; CI crons unreliable (no scheduled fire since 2026-10-10).

---

## 2. Verified healthy (evidence measured today)

| Thing | Evidence |
|---|---|
| Test suite | `python -m unittest discover -s tests` → **Ran 705 tests, OK** (69 s) |
| Governance | `python scripts/check_governance.py` → **PASSED** (secrets, SO-7, SO-8, SO-4) |
| Tape daemon | pid **8772** alive; heartbeat **30 s** at 14:31:51; 0 reconnects / 0 errors; 1,750 messages, 6,315 ticks today; `data/feed_capture/capture_20261012.ndjson` = 4,114 rows / 9.3 MB |
| Tick scheduler | Scheduled task `quant-of-rehan-kmiall-tick` Running, next fire 14:28; `data/tick.lock` pid 24888 @14:31:57; `data/tick_health.json` fresh; forward-observation files written each tick (`data/forward/*` @14:31) |
| Notification runner | `pythonw -m src.notify.schedule_runner` pid **16320**, alive since 09:32:18 (Startup-folder script); relay reports `paired: true`; next event **CLOSE 15:30** |
| Relay | `/health` 200, market OPEN; `/market` 200, card `as_of` 14:28 with KSE100 165,610.95 (−0.88%) and leaders TREET / PRL / PIBTL; **all three splits `tape_flow`** with honest `split_source` notes; admin routes 403 without token |
| Phone card path | Card refreshed every tick and served to the app; last publish 14:31 |
| EOD window | `data/eod_signal_window.csv.gz` content through **2026-10-09** (last completed session), 73 sessions, 152,492 rows |
| Git / PRs | Branch 2 commits ahead of master, in sync with origin; PRs **#72** and **#73** open; all governance runs today green |

---

## 3. Checklist, what needs your attention

### A. HIGH: the intraday quote source is returning nothing

**What was measured (live, just now):** the OHLC servlet at `vt.eclear.com.pk` answers the bare envelope for every symbol:
`BAFS → 'BAFS;REG;'`, `TREET → 'TREET;REG;'`, `OGDC → 'OGDC;REG;'`, zero bars, all mirrors. This is the same rejection measured on 2026-10-09, so the source has been dark for at least four sessions.

**Consequences today:** coverage 0.0% (0 of 319 symbols), `ohlc_low_coverage.flag` set, **34 consecutive failed capture passes** (last measured 14:35), `trade_state=DATA_BLOCKED`, 0 scans with data, 0 trades. This is the fail-closed path working exactly as designed, no fabricated data, no bad trades, but the system cannot scan while it lasts.

- [ ] **Decide the recovery path for intraday data** (this is the only blocker to trading logic):
  - [ ] a. Contact eclear / check whether unauthenticated quote access was disabled or the endpoint moved (the recon notes still apply: `legacy/sentinel/eclear_recon/RECON_REPORT.md`).
  - [ ] b. Consider building intraday bars from the **real-time tape instead of the dead REST servlet**, the tape is *up right now* (6,315 ticks today, 319 symbols subscribed) and already feeds the market card's B/S split. This would remove the single point of failure entirely.
  - [ ] c. Decide whether any paid/alternative source is warranted (see `DATA_SOURCING.md`).

### B. HIGH: the outage did not page you today

The local tick alerts **once, exactly at the 3rd consecutive capture failure**. That crossing already happened (counter is now **34**), so a continuing outage never alerts again. The daily flag-gated alert (`scripts/ops_alert.py --capture-health`) exists for exactly this case but is only invoked from the **CI workflow**, which did not fire today. Net result: a full-session outage produced **no message to your phone** today.

- [ ] **Arm a daily local reminder while coverage stays 0**, e.g. the tick calls `ops_alert.py --capture-health` (or the relay `/notify` ops path) once per session; the relay already dedupes per UTC day, so you get one reminder per day, not spam.
- [ ] Optionally rerun this check after the 15:30 close: `data/notify_log.jsonl` should appear with the CLOSE notice (it does not exist yet, nothing sent today).

### C. MEDIUM: scheduled GitHub Actions runs are unreliable

Facts measured: the scan workflow's crons are on master (`10:07 / 11:37 / 13:07 / 14:37 / 16:07 PKT` + finalizes), Actions is enabled, repo is active, yet **no scheduled fire at all since 2026-10-10**, and today's 10:07 and 11:37 scans never ran. History shows this repo's scheduled fires arrive hours late (Oct-08 fires for 05:07-10:47Z crons landed 12:14-17:59Z, one dropped; the signal push scheduled 03:45Z Sat ran at 10:07Z). GitHub cron on private repos is best-effort; your local tick is the dependable path.

- [ ] Treat the local 4-minute tick as the primary scanner and CI as backup, and consider a small **missed-slot watchdog** (the tick can complain, or a scheduled task can, when a CI slot that should have run has no run).
- [ ] Check GitHub **billing → Actions minutes** once in the UI: if the private-repo allowance runs out mid-month, scheduled runs stop silently (the CLI token here cannot read billing, so this one needs your eyes).

### D. MEDIUM: one live question hidden behind the outage

A full 319-symbol sweep needs **~734 s** of polite asking, but the local tick gives capture **195 s** inside its 4-minute cadence (the reason string says so). Today this is moot because the source is dark. Once a source returns:

- [ ] Verify that coverage **accumulates across successive passes** within the day (it should climb ~25-30% per pass and clear the 80% gate after several passes). If it does not, decide: cumulative-coverage gate, a longer-running capture worker, or a smaller scan universe.

### E. LOW: housekeeping

- [ ] **Commit / PR the uncommitted work**: 16 modified + 3 untracked files on `buffy/harden-kmi-capture-mirror-fallthrough` (market-card split refinements, `src/data/live_card.py` + test, `APP_UPDATE_2026-10-12.md`, docs). Your own governance rule is that every change is a PR; PRs **#72** and **#73** are also open and awaiting your call.
- [ ] **Tidy leftover fake-clock artifacts** so future audits are not confused: `data/feed_capture/capture_20261211.ndjson` (contains 2026-10-09 frames under a Dec-11 name), `data/feed_capture/ohlc_20261011.ndjson`, and the Nov-10 / Dec-11 blocks inside `logs/kmiall_tick.log`. Harmless for the day-stamped readers; delete or move them.
- [ ] **`python -m pytest` from the repo root fails to collect** (5 errors in `legacy/`: duplicate test module names, retired imports). The CI-correct command is `python -m unittest discover -s tests`. Optional: add a pytest config that restricts collection to `tests/` so the wrong command cannot mislead you again.
- [ ] **Startup coverage for the tape**: today the tape daemon (pid 8772) started at **14:02**, mid-session, and it is not registered anywhere automatic (the Startup folder runs only the notification runner; the scheduled task runs only the tick). If the machine reboots mid-session, the tape-derived B/S splits silently lose the morning. Decide whether to add it to startup/scheduler.
- [ ] Today's 09:32 **OPEN notice was missed** because the notifier started 09:32:18 (booted 18 s after the bell; by design there is no catch-up). If you want the open bell to always arrive, start the runner before 09:30 or allow same-day catch-up.

---

## 4. What was not verified

- **The phone itself**, no install/use of the APK here; the card path is verified from the relay side (which is what the app reads).
- **Node/worker syntax**, `node` is not installed locally, so the `cloud/worker.js` syntax check ran only in CI (green). The relay itself answered live, which exercises the deployed worker.
- **GitHub Actions minutes/billing**, the token lacks billing scope (404), as noted in item C.
- **The 15:30 close and tonight's 18:45 signal push**, they had not happened yet at checkup time; recheck `data/notify_log.jsonl` and the signal-push run afterwards.

---

## 5. Suggested order of play

1. Chase the quote source (A), nothing trades until it returns.
2. Arm the daily outage reminder (B), so the next dark session pages you.
3. Verify the cumulative-coverage assumption (D) on the first healthy session.
4. Close out the uncommitted work and PRs (E) and decide on the CI cron watchdog (C).
