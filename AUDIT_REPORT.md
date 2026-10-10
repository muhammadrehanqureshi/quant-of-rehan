# Audit report: local checkout vs GitHub, 2026-10-10

Scope: the `quant-of-rehan` working copy at
`C:/Users/rehan/OneDrive/Desktop/quant-of-rehan` and its GitHub remote
`muhammadrehanqureshi/quant-of-rehan` (private). Method: every claim below was
produced by a command run in this session; the evidence is quoted inline.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Branch / HEAD | `master` @ `0e6916a` (cron rebuild for GitHub schedule delivery) |
| Drift vs remote | `git rev-list --left-right --count origin/master...HEAD` = `0 0`; `git fetch --dry-run` clean |
| Visibility | unauthenticated `api.github.com` returns 404 → the repository is private |
| Working tree | 31 modified tracked files, 26 untracked paths (57 files of unpublished work) |
| Remote branches | 35 total, 10 not merged into `origin/master` |
| Open PRs | none; last merged PR is #56 (2026-10-09) |
| Toolchain here | Python 3.13, pandas/requests; gh 2.102.0 (authenticated as the owner); JDK 17 + aapt2 + D8 + uber-apk-signer in `C:/Users/rehan/android-tools`; **no Node, no wrangler** |

## 2. Structural integrity and dependencies

Executed, all green:

- `python -m compileall -q src scripts tests examples cloud` → exit 0 (every file parses).
- Import sweep of every module by path → **50/50 modules import** (no `__init__.py`; PEP 420 namespace packages).
- `python -m pip check` → "No broken requirements found." `requirements.txt` pins `pandas>=2.2,<3.1`, `requests>=2.31` and CI installs exactly that.
- `python -m pytest tests -q` → **347 passed, 93 subtests passed, exit 0**.
- `python scripts/check_governance.py` → PASS (secrets clean, footprint honesty, standing orders, SO-7 style/identity, SO-8 Karachi pin).
- Android app rebuilt from source in this session: `aapt2 compile` OK, `aapt2 link` OK, `javac` exit 0 (5 sources), `D8` exit 0, signer "Successfully processed 1 APKs and 0 errors"; `aapt2 dump badging` → `pk.quantofrehan versionCode='14' versionName='1.6.0'`.
- `cloud/worker.js` executed in a real engine (see §5): whole-file parse OK, 26/26 behaviour checks PASS.

Findings:

- **W-8 (reproducibility)** `models/kmiall_signal_v1.json` is required by `src/signals/ai_model.py` (`MODEL_PATH`), named in `src/config.py`, and documented as part of the tree, but `git ls-files models` is **empty** and the path is not ignored. A fresh clone or a CI job has no AI prior. Impact is bounded because `ai_model.load()` never raises (returns `None`) and `ai_model.status()` reports `artifact_exists: false` with a reason, it degrades honestly rather than crashing. Remediation: either commit the 5 KB artifact (`git add models/kmiall_signal_v1.json`) or add `models/` to `.gitignore` and point the docs at `scripts/train_signal_model.py` as the only producer.
- **I-2 (type safety coverage)** No static type checker or linter is installed locally or configured in CI (`mypy`, `ruff`, `pyflakes` all absent; `requirements.txt` carries no dev tools). Measured instead with `ast`: **474/493 function defs carry a return annotation (96.1 %)**; the 19 exceptions are in research tooling (`scripts/research_phase2a.py` 5, `scripts/intraday_pipeline.py` 2, `scripts/verify_market_signals.py` 2, `scripts/scan_loop.py`, `scripts/phase2b_lib.py`, `scripts/research_phase1.py`, `scripts/research_phase2b.py`, `scripts/condition_scan.py`, `scripts/check_governance.py`, `scripts/train_signal_model.py`, `src/signals/ai_model.py` 2, `src/signals/contracts.py` 1), none in `src/data` or the scanner core. Remediation: add `mypy --ignore-missing-imports src` and `ruff` to `governance-guard.yml` as a non-blocking first step, then ratchet.
- **I-5 (hygiene)** No `TODO`/`FIXME`/`XXX`/`HACK` in `src`, `scripts`, `tools`, `examples`. No bare `except:` anywhere. No `eval`/`os.system`. The only `shell=True` call is `scripts/install_scheduler.py` (fixed command string, no user input).

## 3. Security

- **C-1 (fixed in this audit) Unignored credential file inside the repo tree.**
  `legacy/eod/data/web_token.txt`, 32 bytes, opaque, a bearer token for the
  legacy sentinel web console (`legacy/sentinel/src/web_console.py` reads
  `DATA_DIR / "web_token.txt"`). It was untracked but **not ignored**: the
  `.gitignore` patterns (`credentials*`, `.env*`, `secrets*`) do not match it,
  so a single `git add -A` would have published it with the next push.
  Containment: the repository is private, the file was never committed, and
  GitHub's own secret scanning is disabled for it (see W-6), so the local
  governance scan was the only gate, and it did not know this filename.
  Remediation applied: `.gitignore` now ignores `legacy/eod/data/`,
  `legacy/sentinel/data/` and `*_token.txt`; verified with
  `git check-ignore -v` and by confirming no tracked file matches the new
  rules (`git ls-files` empty for those paths). Recommended follow-up:
  rotate the token if the folder was ever archived, forked, or zipped for
  sharing, and keep future secrets in the already-ignored `data/secrets/`.
- **I-3 Secret handling elsewhere is sound**: no tracked file matches
  `secret|token|.env|.pem|.key|credential`; `RELAY_ADMIN_TOKEN` lives in the
  local `.env` and in GitHub Actions secrets (present, set 2026-10-08), and
  workflow permissions are least-privilege (`contents: read` in
  `governance-guard.yml` and `signal-push.yml`, `actions: read` added in
  `intraday-capture.yml`). No `pull_request_target`, no untrusted-input
  interpolation into `run:`.
- **W-6 No platform security automation.** Dependabot alerts, secret scanning
  and code scanning are all disabled on the repository (API: "Dependabot
  alerts are disabled", "Secret scanning is disabled", "Code scanning is not
  enabled"). Dependabot alerts/updates are free for private repos and would
  cover `pandas`/`requests`; for private repos CodeQL needs GitHub Advanced
  Security, so the practical alternative is running `bandit`/`semgrep` and
  `pip-audit` inside `governance-guard.yml`, which already runs on every PR
  in seconds.
- **W-7 (fixed in this audit) The relay's own data contract could be stripped by a partial push.**
  Verified by execution, not by reading: posting `{"top_volume": []}` with a
  valid admin token to `POST /market` returned `200 {"ok":true,"stored":true}`,
  and the next `GET /market` then answered with keys
  `ok, karachi_now, top_volume, source, built_at, market_open, market_state, cache_age_seconds`,
  with **no `index`, no `notes`, no `kmiall_members`, no `top_volume_basis`**,
  i.e. exactly the fields the phone app reads. A partial or buggy push would
  therefore blank the KSE100 card and the footnote for up to five minutes.
  `tools/worker_check.py` did not cover this path (it only pushed a
  well-formed snapshot).

  Remediation applied in `cloud/worker.js`:
  1. `snapshotShapeError()` rejects a push that omits `index` or `top_volume`
     or sends the wrong type → `400 {"error": "snapshot is missing index"}`.
  2. `normalizeMarket()` runs on every snapshot served from KV (cached path,
     fresh path, and the outage fallback), so `index`, `top_volume`,
     `kmiall_members`, `top_volume_basis` and `notes` always exist with
     explicit `null`/`0`/`[]` values instead of disappearing.

  The only producer of that endpoint, `src/data/market_snapshot.py`
  (`push_snapshot`), always sends the full shape, so the stricter validation
  does not break the real push path.

  Regression tests added to `tools/worker_check.py`: refuses a partial
  snapshot; a pushed snapshot still carries every field the app reads; a
  snapshot without an index reads back as an explicit `null`; a dead portal
  with an empty cache still answers the full field set with `notes`.

## 4. Remote synchronization and drift

- **No drift in the tracked history**: `master` equals `origin/master` at
  `0e6916a`; `git fetch --dry-run` printed nothing.
- **PR/merge status (direct answer to the question).** No open PRs exist.
  PRs **#47-#56 are all MERGED**, the last four being #53 (v1.4.5),
  #54 (v1.4.6), #55 (momentum+volume scanner) and #56 (market card), i.e. work
  **is** being branched, PR'd, checked by `governance-guard` and merged into
  `master`. Authorship/merge actor for #54-#56 is the `muhammadrehanqureshi`
  account (the same identity the local `gh` token authenticates as), and the
  commits are authored as `Mr. Rehan`. Nothing of today's session has been
  pushed: this session made no commit, no push and no PR.
- **W-1 (unpublished work)** The entire 2026-10-10 body of work exists only as
  working-tree changes: 31 modified tracked files plus 26 untracked paths
  (`examples/`, `scripts/scan_loop.py`, `scripts/kmiall_tick.py`,
  `scripts/event_study.py`, `scripts/verify_market_signals.py`,
  `scripts/train_signal_model.py`, `scripts/condition_scan.py`,
  `scripts/walk_forward_check.py`, `scripts/dead_code_audit.py`,
  `scripts/install_kmiall_tick.py`, `src/signals/contracts.py`,
  `src/signals/volatility.py`, `src/signals/ai_model.py`,
  `src/data/tick_volume.py`, `src/data/universe_refresh.py`, 7 test modules,
  `models/`, `PROJECT_REPORT.md`). No commit, no branch, no PR. Remediation:
  commit on a feature branch and open a PR (the standing order is that
  `governance-guard` gates `master`), then merge, none of which this audit
  performed, because writing to the remote is the owner's call.
- **W-3 (stale branch inventory)** 10 remote branches are not merged into
  `master`, carrying 57 unique commits dated 2026-10-06…08:
  `feature/forward-intraday-validation` (27), `feat/intraday-signal-alerts` (7),
  `fix/capture-health-reporting` (5), `fix/final-kmiall-signal-engine` (4),
  `fix/signal-entry-reference` (4), `ops/daily-intraday-capture` (3),
  `ops/market-hour-capture` (3), `feat/three-daily-intraday-scans` (2),
  `fix/demo-execution-truth` (1), `research/phase1-path-a` (1, also present
  locally). `master`'s tree is a strict superset of these branches
  (`git diff --stat` master→branch shows only deletions, e.g.
  `45 files changed, 706 insertions(+), 5095 deletions(-)` for the largest),
  so they read as superseded iterations of work that later landed on `master`
  in different commits, not as stranded features. Remediation: confirm the
  two that look least derivable (`feature/forward-intraday-validation`,
  `feat/intraday-signal-alerts`) and then delete the remote branches; deleting
  is deliberately left to the owner.
- **W-4 (documented gate is dead wiring)** `DATA_SOURCING.md` states that the
  production gate "cannot open" until `KMIALL_DATA_RIGHTS_CONFIRMED`,
  `KMIALL_DATA_LATENCY_CONFIRMED` and `KMIALL_UNIVERSE_CONFIRMED` are true,
  and that they "default to false". Measured: the repository has **0**
  Actions variables (`gh api …/actions/variables` → `total_count: 0`), the CI
  log shows all three expanded to empty strings, and **no live module reads
  them** (only `legacy/retired_scanners/test_intraday_engine_retired.py`).
  So the documented gate is unenforced in the current pipeline. Trading is
  still paper-only (`PAPER_TRADING_ENABLED: "true"`, `LIVE_TRADING_ENABLED:
  "false"`), which is why this is a Warning and not a Critical. Remediation:
  either re-wire the gate where the signal path decides, or amend
  `DATA_SOURCING.md` so the doc matches the code.
- **I-6 Repository protection is not available**: requesting branch protection
  for `master` returns 403 ("Upgrade to GitHub Pro or make this repository
  public"). The PR→`governance-guard`→merge flow is therefore a convention
  plus a CI check, not an enforced rule; anyone with write access can push
  directly to `master`.

## 5. CI history and runtime reliability

`gh run list --limit 40` (all branches):

- `daily signal push`: 3/3 recent scheduled runs **success** (2026-10-07,
  -08, -09). `RELAY_ADMIN_TOKEN` is present in Actions secrets, which is what
  the push needs.
- `governance-guard`: green on every merged PR; the four failures on
  2026-10-08 are pre-merge iterations of PR #48's own branch.
- `KMIALL intraday momentum scan`: mostly success, but
  - **W-5a** 2026-10-08 failure, `exit code 2` from the scan step, cause found
    in the log: `Unknown schedule slot`, the old `case` block did not match
    the delivered cron expression. That is a fail-closed guard (good) that
    also means a schedule/`case` mismatch silently costs a scan. The rebuilt
    schedule (`0e6916a`) now parses its crons out of the same table the tests
    re-derive, so the mismatch class is closed for the current slot list.
  - **W-5b** two 2026-10-09 scheduled runs were created and started at
    **17:24Z and 17:33Z**, hours after the last cron (11:47Z), and each was
    cancelled mid-scan ("The operation was canceled." at 17:34:33 and
    17:45:28). `concurrency: cancel-in-progress: false` was already committed
    at `0e6916a`, and the run metadata records no canceller, so the cause is
    either a deliberate cancel from the owner's account (the workflow comments
    do track a 2,000-minute monthly Actions ceiling) or a platform-side
    cancellation of queued scheduled runs. **Unresolved, needs the owner's
    confirmation.**
  - **W-5c** as a consequence, the rebuilt schedule has **no completed
    scheduled run yet**: the next weekday's runs are the first real test.
    Watch them with `gh run list --workflow=intraday-capture.yml`.
- **W-7b (planned breakage)** the runner warns that `actions/checkout@v4`,
  `actions/setup-python@v5` and `actions/upload-artifact@v4` are Node-20
  actions now forced onto Node 24. Bump them to the current majors before
  GitHub drops Node 20.
- **I-3b Worker syntax is gated in CI** by
  `node --input-type=module --check < cloud/worker.js` in
  `governance-guard.yml`, which is the strongest available check for a file
  that cannot be run locally (no Node/wrangler on this PC). Out of band this
  audit executed it in Chromium instead: `tools/worker_check.py` rebuilt
  `tmp/worker_check.html`, which parses the whole file with `new Function`,
  runs the worker's own `parseIndexPanel`/`topByVolume` against live PSX
  markup and compares with `src/data/market_snapshot.py`'s results, then drives
  `handler.fetch` with stubbed `fetch`/KV, **26/26 checks PASS, 0 failed**,
  including KSE100 `167,089.27 (-0.21 %)`, leaders `CNERGY/PRL/TREET`
  matching the Python parser bar-for-bar, `saturday is closed`,
  `/market` 200 + cache hit, `POST /market` 403 for a stranger, 404 for
  unknown paths, and the four new negative tests from §3.

## 6. Verification log (what was executed in this audit)

| Check | Command | Result |
|---|---|---|
| Syntax, all Python | `python -m compileall -q …` | exit 0 |
| Import integrity | path sweep of `src`, `scripts`, `examples` | 50/50 import |
| Dependencies | `python -m pip check` | no broken requirements |
| Tests | `python -m pytest tests -q` | 347 passed, 93 subtests, exit 0 |
| Governance | `python scripts/check_governance.py` | PASS |
| Worker behaviour | `python tools/worker_check.py` + Chromium | 26/26 PASS |
| Worker negative paths | same harness, new cases | 4/4 PASS |
| Android build | aapt2 + javac + D8 + signer | exit 0, signed, v1.6.0/14 |
| Core logic example | `python examples/market_card.py --offline` | exit 0, see §7 |
| Remote state | `git fetch --dry-run`, `gh pr list`, `gh run list` | clean, 0 open PRs, PRs #47-#56 merged |
| Secret hygiene fix | `git check-ignore -v legacy/eod/data/web_token.txt` | matched by `.gitignore:21` |

Not runnable here, reported as limitations rather than passes: `wrangler dev`
/ Miniflare (no Node, no wrangler), a live signed-in Telegram round trip (no
bot token in this shell), and the unmerged-branch contents beyond metadata.

## 7. Runnable usage example (verified just now)

```bash
python examples/market_card.py --offline
```

```
offline: validating the built-in fixture instead of the portal

MARKET NOW   BREAK   closed (weekend or PSX holiday)
KSE100  167,089.27   -0.21%
1. CNERGY   T=27,276,548   Rs 12.52   up 1.05%
2. PRL   T=24,123,072   Rs 93.07   down 2.14%
3. TREET   T=22,903,682   Rs 41.10   up 0.51%
   volume: top 3 of 313 KMIALLSHR members
   OFFLINE: no session is live at this instant
   buy/sell split unavailable: no broker tick capture banked for 2026-10-09

refusals (a card is only as good as what it rejects):
  refused a negative volume: X.volume is below 0: -5
  refused a percentage that is not a number: X.change_pct is not a number: 'up'
  refused half a split: X carries only one side of the split
  refused an unknown phase: unknown market phase: 'LUNCH'
  refused a duplicated leader: the same symbol appears twice in the leaders
```

`examples/scan_once.py` is the second, scanner-side example (fixture-driven,
no network).

## 8. Files changed by this audit

| File | Change |
|---|---|
| `cloud/worker.js` | push-shape validation + `normalizeMarket()` on every served snapshot |
| `tools/worker_check.py` | four new negative-path checks (partial push, field-set survival, explicit-null index, portal outage) |
| `.gitignore` | ignores the legacy local token directories and `*_token.txt` |
| `AUDIT_REPORT.md` | this report |

## 9. Recommended order of work

1. Commit the 57 unpublished files on a branch and open a PR (§4 W-1), so the
   Oct-10 work stops existing as the only copy.
2. Confirm the two cancelled intraday runs (§5 W-5b) and watch the next
   weekday's scheduled runs; the rebuilt cron table has not yet completed one.
3. Re-wire or re-document the `KMIALL_*_CONFIRMED` gate (W-4).
4. Enable Dependabot alerts and add `pip-audit`/`bandit` to
   `governance-guard.yml` (W-6); bump the action majors (W-7b).
5. Decide the fate of the 10 unmerged branches (W-3) and the required-but-
   untracked model artifact (W-8).
6. Rotate the legacy web-console token if that folder was ever shared (C-1).
