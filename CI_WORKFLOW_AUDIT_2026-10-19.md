# CI audit: charts of Rehan and quant of Rehan (2026-10-19)

Owner request: audit, debug and resolve the recurring GitHub Actions failures
in both repositories, then leave the pipelines stable and a verification plan
behind.

Evidence below is from the GitHub API on 2026-10-19 08:20 UTC and the run logs
themselves. No test was relaxed and no failure was hidden to make a run green.

## What was actually failing

### quant-of-rehan: the bands were missed, not the jobs

The scheduled workflows were green, which is worse than red: the runs happened
hours after their cron time, found a shut market, did nothing, and still
reported success.

| Cron (UTC) | What it is for | Run created (UTC) | Delay |
|---|---|---|---|
| `17 4 * * 5` | Friday band 1, 09:17 PKT | 2026-10-16 09:01 | 4h44m |
| `32 9 * * 5` | Friday band 2, 14:32 PKT | 2026-10-16 14:10 | 4h38m |
| `45 3 * * 2-6` | pre-open safety net | 2026-10-17 08:03 | 4h18m |
| `45 13 * * 1-4` | post-close push | 2026-10-16 18:21 | 3h36m |

GitHub's cron queue is delivering `schedule` events 3 to 5 hours late for this
account, and it did so from the first day the band workflow existed. GitHub
documents that scheduled events are delayed during high load and may be
dropped; this is platform behaviour, not a YAML error (the workflow parses,
its crons are inside real bands, and Actions is operational).

Two repository bugs made that platform delay much worse:

1. **The session gate was forced on every fire.**
   `.github/workflows/intraday-session.yml` ran
   `session_gate --check --force --purpose scan`, and `--force` means RUN
   unconditionally. A fire that arrived at 19:11 PKT therefore started the
   loop instead of stopping at the gate.
2. **The loop slept after finalizing the day.** Run 38913659490 (2026-10-16,
   started 14:10 UTC) finalized at 19:11 PKT and logged
   `sleeping 224435s (failures=0, action=finalize)`, then the job timeout
   killed it two hours later. The band had not been scanned at all, and 190
   minutes were billed for an empty wait.

The scheduled capture workflow was already correct: it passes
`--schedule "${{ github.event.schedule }}"` and reserves `--force` for a human
dispatch. Only the session loop carried the bug.

Secondary issues found while auditing:

- actions/checkout@v4, setup-python@v5, setup-node@v4 and upload-artifact@v4
  all run on Node 20, which GitHub is already forcing onto Node 24 and warns
  about on every run.
- Three workflows installed floating packages (`pip install pandas numpy
  requests`) while `requirements.txt` pinned the same tree, so a resolver
  failure or an upstream release could change a scheduled run with no commit.
- `tools/worker_check.py`, the only local syntax check for the relay worker,
  had gone stale when the Durable Object class was added: it parsed the whole
  file as a function body and failed on `export class`, reporting
  `SyntaxError: Unexpected token 'export'` before checking anything.

### charts-of-rehan: three different causes, all visible in the logs

| Run | Event | Cause |
|---|---|---|
| 39204205901 (2026-10-19 05:22) | push | 13 failures in `test_charts_cli`: the GitHub Actions guard wrapped the whole CLI, including read-only `--sessions` and `--once`, so those commands exited 2 with the "foreground chart service" sentence and the tests expecting real output failed |
| 39114307671 (2026-10-18 09:10) | push | `tools/sanitize.py` was not on that branch, so the publish gate failed with exit 2 |
| 39114307671 (2026-10-18 09:10) | push | setup-node failed before `npm ci`: `cache-dependency-path: web/package-lock.json` did not exist on that branch, so the job died with "Some specified paths were not resolved" |
| 39109582530 (2026-10-18 07:57) | push | same class as above on the then-default branch |
| 39204205901 | push + pull_request | both events ran the same tree, so a superseded run could still show a red X after the newer one was green |

The guard scoping bug has already been fixed on `charts-of-rehan` master: the
guard now treats `--sessions`, `--build-archive` and `--once` as bounded
commands, and the suite passes locally (189 tests). The remaining two causes
were branch-state problems that a clearer, failure-tolerant workflow prevents.

## Changes made

### quant-of-rehan

- `.github/workflows/intraday-session.yml`
  - the session gate is schedule aware. A scheduled fire passes
    `--schedule "${{ github.event.schedule }}"`; `--force` survives only in
    the `workflow_dispatch` branch.
  - a skipped fire now writes a run summary saying it did no work and why, so
    a late delivery is visible instead of looking like a healthy run.
  - `actions/checkout@v7`, `actions/setup-python@v7`,
    `actions/upload-artifact@v7`.
  - dependencies come from `requirements.txt` with retry and timeout flags.
- `scripts/scan_loop.py`
  - a finalized day ends the loop. It no longer sleeps 224,435 seconds to the
    next open and lets the shell timeout kill an idle job.
- `.github/workflows/intraday-capture.yml`, `signal-push.yml`,
  `deploy-relay.yml`, `governance-guard.yml`, `secret-scan.yml`
  - action majors raised to v7 (Node 24 native, no deprecation warning).
  - pip installs pinned to `requirements.txt` with retries and a 60s timeout.
- `cloud/worker.js`
  - the relay already wakes on Cloudflare crons at every band edge. The same
    wake now dispatches `intraday-session.yml` through the GitHub API, so a
    band starts in seconds instead of waiting for a late GitHub cron.
  - opt-in and fail-open: no `GH_DISPATCH_TOKEN`, no dispatch; one dispatch
    per band per day in KV; ten second timeout; a non-204 response leaves the
    key free and is recorded in `SCAN:DISPATCH:LAST`.
  - `cloud/README.md` documents the one-time secret step.
- `tools/worker_check.py`
  - the whole-file syntax check strips `export class` as well as
    `export default`, so the relay is once again checked in a real engine.
- Tests added or tightened: `tests/test_scan_loop.py` (finalized day stops the
  loop), `tests/test_rebuild_schedule.py` (scheduled fires are gated, not
  forced; the loop is gated on `should_run`), and
  `tests/test_relay_worker_contracts.py` (dispatch contract, opt-in, dedupe,
  timeout).

### deploy-relay: a refused upload that could read as a green edge

Measured on 2026-10-19, not inferred. Run 39216586610 (07:32 UTC, commit
`2c59748`) deployed the relay green. Run 39225627067 (08:55 UTC, commit
`d7ac13a`) failed at `npx wrangler deploy` with:

```
KV namespace '<RELAY_KV_ID>' not found. Verify the namespace
exists in your account and that the namespace_id in your configuration is
correct. [code: 10041]
```

The inputs were identical: same wrangler (4.151.1), same `RELAY_KV_ID`, same
account and token. The live worker still reads that namespace (`/health`
returns `paired: true` and `last_delivery` from it, one minute before the
failing rerun), so the namespace exists and the data plane is healthy. What is
refusing is the management API, and a `workflow_dispatch` rerun failed the
same way, so it is not a one-off.

Two defects are in the repository even though the trigger is external:

1. The workflow reported a red X with no instruction. 10041 is never caused by
   the code under `cloud/`; it is the token, the account or the namespace id.
   The failure now says so and names all three.
2. `"ok": true` was read as proof of a deploy. It proves only that *something*
   answers. The worker now reports `version: env.WORKER_VERSION` and the
   workflow deploys with `--var WORKER_VERSION:$GITHUB_SHA`, then polls
   `/health` until the edge names the commit it just built. A deploy that
   uploads nothing fails, and a worker uploaded outside CI (`cloud/pair.py`)
   reports `null` and passes with a warning.

- `.github/workflows/deploy-relay.yml`
  - three deploy attempts with backoff, because the management API answered
    404 for a namespace it had accepted ninety minutes earlier;
  - the run is verified against the deployed commit, not against `ok: true`;
  - a `failure()` step lists the three credential and namespace checks.
- `cloud/worker.js`
  - `/health` (and `/status`) carries the commit the edge is running.

### charts-of-rehan

- `.github/workflows/ci.yml`
  - action majors raised to v7.
  - `concurrency` cancels a superseded run for the same ref, so a red X
    always describes the newest commit and free minutes are not spent twice.
  - the npm cache is enabled only when `web/package-lock.json` exists; a
    branch without the web app no longer fails inside setup-node before its
    first test.
  - `npm ci --no-audit --no-fund` removes two network round trips from a job
    with a ten minute cap.

## Verification plan

Local, both repositories:

```bash
# quant-of-rehan
python -m pytest tests -q
python scripts/check_governance.py
python tools/worker_check.py          # then open tmp/worker_check.html
# expect: RESULT PASS, including "worker parses and exposes fetch/scheduled"

# charts-of-rehan
python tools/sanitize.py
python -m unittest discover -s tests -v
python examples/charts_demo.py > /dev/null
cd web && npm ci --no-audit --no-fund && npm run typecheck && npm test && npm run build
```

CI, after the change lands:

1. Push to a branch and open a pull request: quant's governance-guard,
   secret-scan and deploy-relay (on master) must be green, and charts' CI
   must run once per ref rather than twice.
2. On the next PSX band edge, check
   `gh run list -R muhammadrehanqureshi/quant-of-rehan --event workflow_dispatch`
   for a run created within a minute of the edge (with `GH_DISPATCH_TOKEN`
   configured), or `--event schedule` as the fallback. Confirm the run summary
   says RUN rather than SLEEP, and that the loop logs scans inside the band.
3. Confirm a late scheduled fire now exits in about a minute with a SLEEP
   summary, and that no run logs `sleeping 224435s` again.
4. Watch `charts-of-rehan` CI on the next two pushes: exactly one run per ref,
   backend and frontend green, no setup-node cache error.
5. After the next `deploy-relay` run, confirm it logs
   `live /health reports version <sha>` for the merge commit. Until that line
   appears, the edge is still running the previous build, whatever the run's
   colour says.

## Residual risks

- GitHub cron punctuality is outside this repository's control. The Cloudflare
  dispatch removes the dependency on it once the token is set; until then the
  scheduled trigger is still the fallback and can still be late.
- The dispatch needs a fine grained GitHub token with Actions: write, stored
  only as the Worker secret `GH_DISPATCH_TOKEN` (SO-5). It is not in the repo.
- If GitHub answers 403 because the token lacks Actions write, the worker
  records the failure in `SCAN:DISPATCH:LAST` and the next punctual cron
  retries; nothing else is affected.
- Action v7 majors are verified by a real run after landing; a breaking change
  would surface in the same PR's CI, not in a scheduled band.
- The relay deploy is currently refused by Cloudflare's management API with
  error 10041 although the same namespace, token and account deployed green at
  07:32 UTC and the live worker still reads it. Until that is resolved in the
  Cloudflare dashboard (namespace present, token carrying Workers Scripts:
  Edit and Workers KV Storage: Read), the dispatch code merged today is not on
  the edge. The GitHub-side fixes are unaffected: the bands are gated and
  dispatched without this deploy.
- `--var WORKER_VERSION` is honoured by wrangler 4.151.1, the version this run
  installs. The verify step treats a missing version as a warning, so an older
  worker or a `cloud/pair.py` upload cannot be locked out.
