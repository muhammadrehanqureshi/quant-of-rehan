# Deep scan audit: Quant of Rehan, 2026-10-10

Two audits in one document, both grounded in commands that were actually run
against this checkout and against the live GitHub API, not in recollection:

* Part 1 is the DevOps root cause analysis of the failed `governance-guard`
  jobs on commit `860fdab`.
* Part 2 is the quantitative and code integrity audit of the KMIALL core.

Every claim below is followed by the command or API response that produced it.
Anything that could not be verified is marked as such at the end.

---

## Part 1: DevOps root cause analysis, `governance-guard` on `860fdab`

### 1.1 What actually failed (evidence, not inference)

The PR head commit under investigation:

```
$ git log -1 --format='%H%n%an <%ae>' 860fdab
860fdabd575c215420d1b6d6d5102d95bdc96fd0
Mr. Rehan <111383512+muhammadrehanqureshi@users.noreply.github.com>
```

Two check runs named `governance` were recorded against that SHA, and **both
concluded `failure`** (GitHub API, PR #58 check runs):

| run | job | started | completed | conclusion |
|---|---|---|---|---|
| 38030463451 | 114150122106 | 06:18:18Z | 06:18:36Z | failure |
| 38030564326 | 114150434849 | 06:20:06Z | 06:20:21Z | failure |

The same workflow against the clean sibling commit `7e94802` **succeeded**
(PR #57, run 38031091120, job 114152010100, conclusion `success`). So the
failure is specific to `860fdab`, not to the workflow, the runner, the
schedule, or the repository configuration.

### 1.2 Root cause

The commit message of `860fdab` carries an agent trailer that the repository's
own Standing Order SO-7 bans. Fetched from the GitHub API verbatim:

```
$ git log -1 --format=%B 860fdab
... a pile of ad-hoc edits. The batch includes ...

<robot emoji> Generated with Codebuff
Co-Authored-By: Codebuff <noreply@codebuff.com>
```

`scripts/check_governance.py` enforces this directly, and the CI step runs it
with `GOVERN_COMMIT_RANGE=origin/master..HEAD`. Reproduced locally, with the
tested command's exit status preserved:

```
$ GOVERN_COMMIT_RANGE=origin/master..HEAD python scripts/check_governance.py
GOVERNANCE CHECK FAILED, PR must not merge:

  - [SO-7] commit message contains banned trailer 'co-authored-by:'
  - [SO-7] commit message contains banned trailer 'generated with'
EXIT=1
```

That non-zero status is the whole failure. The job is behaving correctly: the
gate is doing exactly what GOVERNANCE.md says it must, and it is the commit,
not the pipeline, that is non-compliant.

### 1.3 Why the job stopped there, and why the green steps do not matter

The guard is a single job with ordered steps. Step 5 (unit tests) passes on
`860fdab`, verified locally:

```
$ python -m unittest discover -s tests -v
Ran 347 tests in 12.827s
OK
```

Step 6 (worker syntax) never runs, because step 4 exited 1 first. That is
correct fail-fast behaviour, and it is also why the raw log only shows one red
step. Both failing runs completed in 15 and 18 seconds, which is consistent
with aborting before the 13 second test suite, not with a timeout or a flaky
runner.

### 1.4 Secondary defect found while auditing the gate itself

The gate has a real, platform-dependent defect. `check_commit_messages` read
git's output with `subprocess.run(..., text=True)` and no explicit encoding, so
Python decoded it with the ambient locale. On a cp1252 Windows box the robot
emoji `U+1F916` (bytes `F0 9F A4 96`) decodes such that its final byte `0x96`
becomes `U+2013 EN DASH`, which the banned-dash rule then flags:

```
$ python -c "print([f'U+{ord(c):04X}' for c in b'\xf0\x9f\xa4\x96'.decode('cp1252')])"
['U+00F0', 'U+0178', 'U+00A4', 'U+2013']
```

The result was a **third** error, a phantom "banned dash character", that
appears on Windows and not on the UTF-8 Linux runner. A gate whose verdict
depends on the reviewer's locale is not a gate. Classified as a real defect and
repaired at the cause in section 2.2.

### 1.5 Remediation options for `860fdab`

| option | effect | risk |
|---|---|---|
| **Merge PR #57 instead** (head `7e94802`) | Identical content, clean message, and the guard already passed on it | None. Verified below |
| Rewrite `860fdab`'s message and force push | Guard passes on the same SHA history | Rewrites published history, requires force push, and `860fdab` is already the closed PR #58 pointer |
| Merge with an admin override | Red gate is bypassed | Breaks the PR first law in GOVERNANCE.md. Not recommended |

The first option is verified sound, not assumed. The trees are byte-identical
and the clean commit passes the guard:

```
$ git rev-parse 7e94802^{tree} 860fdab^{tree}
fdbea9b796b21a391a6ecd661f2c0a8934513c8f
fdbea9b796b21a391a6ecd661f2c0a8934513c8f

$ GOVERN_COMMIT_RANGE=0e6916a..7e94802 python scripts/check_governance.py
GOVERNANCE CHECK PASSED: ...
EXIT=0
```

### 1.6 Checklist: common GitHub Actions failure points

Use this in order when any job goes red. It is ordered by how often each one is
the actual cause in practice.

1. **Commit and PR metadata gates.** Identity, trailers, banned characters,
   signed-off-by. Read the commit, not the code, first. (This was the cause
   here.)
2. **Dependency resolution.** Unpinned or missing package, private index
   credentials absent on a fork, `pip install` succeeding on a cached wheel
   locally and failing cold on the runner.
3. **Swallowed exit status.** `cmd | tail`, `cmd || true`, `continue-on-error`,
   missing `set -o pipefail`. The step reports green while the test failed.
4. **Environment variable scope.** A secret set at repo level but read in a
   job that runs fork code, or a variable that exists only on the default
   branch. `GOVERN_COMMIT_RANGE` itself is an example of a variable whose
   absence silently disables a whole check.
5. **Runner connectivity and quota.** Actions minutes exhausted on a private
   repo, runner image deprecation, transient 5xx from the artifact service.
6. **Workflow syntax and schema.** Invalid `on:` block, an expression in a
   context where it is not allowed, a reusable workflow whose `uses` path is
   wrong. Validate before pushing.
7. **Checkout depth.** `fetch-depth: 1` on a job that diffs against the base
   branch, so the range resolves empty and the check passes vacuously.
8. **Cache and workspace pollution.** A stale `pip` cache serving a
   different revision, or generated files left in the tree that a scanner then
   reads.
9. **Timeout and cancellation.** Job killed at `timeout-minutes`, or a
   concurrency group cancelling the run that a required check was waiting on.
10. **Permissions.** `GITHUB_TOKEN` lacking the scope the step needs, or a
    workflow-level `permissions` block narrower than a step assumes.

### 1.7 Steps to debug this specific failure

1. Read the failing job's step list, not the summary. Run
   `38030564326` / job `114150434849`.
2. Identify the first step whose conclusion is `failure`. Everything after it
   did not run, so any green below it is not evidence.
3. Reproduce that exact step locally with the same environment:
   `GOVERN_COMMIT_RANGE=origin/master..HEAD python scripts/check_governance.py`.
4. Confirm the exit status is preserved and is non-zero:
   `... ; echo "EXIT=$?"`.
5. Compare against a commit known to be green for the same workflow
   (`7e94802`), to prove the defect is in the commit rather than the pipeline.
6. Only then decide: fix the commit, or fix the gate.

### 1.8 Hardened workflow template

`docs/ci/hardened-governance-guard.template.yml` is a drop-in replacement for
the current guard. It is deliberately kept outside `.github/workflows` so it
cannot run until the owner copies it into place. Its hardening, in order:

1. `set -euo pipefail` on every script step, so a piped install cannot report
   success with a non-zero status.
2. A **preflight** step that separates an environment fault (missing runner
   tool, missing repo file) from a code fault, so a red job is diagnosable on
   sight.
3. Explicit exit code capture plus a `::error::` annotation, so the numeric
   status reaches the job summary instead of only the raw log.
4. The governed range derived from `github.base_ref` rather than a hardcoded
   `origin/master`, so a retargeted PR cannot scan the wrong range.
5. A dedicated **edge case validation** gate running
   `examples/deep_scan_stress.py`, so a numerically broken reading cannot merge
   behind a green style check.
6. Concurrency cancellation, least privilege, and a bounded timeout.

Note for anyone parse-checking that template with PyYAML: it will report the
`on:` key as boolean `True`. That is the YAML 1.1 `on`/`off` scalar rule, and
GitHub's own parser treats it as the event key. It is not a defect in the file.

### 1.9 Fail-fast and exit code reporting, demonstrated

The pattern that makes a failure visible instead of plausible:

```bash
set -euo pipefail                      # first failing command ends the step
set +e; python scripts/check_governance.py; status=$?; set -e
if [ "$status" -ne 0 ]; then
  echo "::error title=Governance violation::exited $status; must not merge"
  exit "$status"                       # reported, never swallowed
fi
```

And the same discipline in the harness itself, which returns 1 on the first
violated expectation and 0 only when every one held. A worked example of the
non-zero path: an earlier revision of the harness asserted the veto fault was a
`ValueError`. It is not, it is `InsufficientCoverage`, so the harness exited 1
and named the mismatch. The assertion was corrected, not the harness weakened.

---

## Part 2: Quantitative and code integrity audit

### 2.1 Findings

| # | severity | area | finding | status |
|---|---|---|---|---|
| 1 | **blocking** | CI | `860fdab` carries SO-7 banned trailers; gate correctly fails | Remediated by merging `7e94802` |
| 2 | **high** | CI | `check_commit_messages` decoded git output with the ambient locale; cp1252 produced a phantom banned-dash error and a locale-dependent verdict | **Repaired** |
| 3 | **medium** | signals | `volatility.assess` returned a confident regime for samples below `MIN_BARS_FOR_VOLATILITY`, contradicting its own documented contract ("reported as UNKNOWN rather than guessed") | **Repaired** |
| 4 | low | signals | `average_true_range_pct` is a simple mean of true range over the last close, which is standard NATR but is not Wilder's smoothed ATR despite the "Wilder" wording on `true_ranges` | Documented below |
| 5 | info | interface | `as_dict()` would pass a non-finite float straight to `json.dumps`, which emits the invalid JSON token `NaN`. **Not reachable** while the `Bar` boundary holds, because `Bar` refuses non-finite prices (verified) | Regression-guarded, see 2.6 |

### 2.2 Findings 2 and 3, the repairs that were made

**Finding 2 repaired.** `scripts/check_governance.py` now pins the decode,
removing the locale dependency without weakening the rule:

```python
out = subprocess.run(
    ["git", "log", rng, "--format=%an%x09%ae%x09%B%x00"],
    capture_output=True, text=True, encoding="utf-8",
    errors="replace", timeout=30, check=True,
).stdout
```

Verified: the phantom dash is gone and the two genuine trailer violations
remain, so the gate still fails `860fdab` for the right reason:

```
GOVERNANCE CHECK FAILED, PR must not merge:

  - [SO-7] commit message contains banned trailer 'co-authored-by:'
  - [SO-7] commit message contains banned trailer 'generated with'
```

**Finding 3 repaired.** The reading now honours the documented floor:

```python
edge_cases = detect_edge_cases(ordered, as_of, previous_close)
# A reading from fewer than MIN_BARS_FOR_VOLATILITY bars is reported as
# UNKNOWN rather than guessed, exactly as this module's contract states.
regime = (classify(atr_pct) if len(ordered) >= MIN_BARS_FOR_VOLATILITY
          else Regime.UNKNOWN)
```

Verified before and after, on the same three bar input:

```
before: 3 bars -> regime=ELEVATED  atr_pct=0.019608
after:  3 bars -> regime=UNKNOWN   (contract: UNKNOWN)  edges=['THIN_SAMPLE']
12 bars -> regime=ELEVATED         (unchanged, so the fix is narrow)
```

### 2.3 Finding 4, the ATR normalisation note

`average_true_range_pct` divides the mean true range by `bars[-1].close`, so
every bar's range is normalised by the session's *final* price. Measured on a
clean 12 bar fixture whose price walks from 100 to 155, one point of range
early in the session is reported as 35 percent smaller than it actually was at
the time:

```
$ 12 bars, last close 155, each bar's own range near 2.0
atr_pct = 0.036559
```

This is the industry standard NATR denominator, so it is defensible as written,
and the docstring is honest about it ("Mean true range as a share of the last
close"). Flagged as a methodological note rather than a defect, because it
makes the regime of a strongly trending name look calmer than the tape that
produced it. The regime aware target multiplier is off by default, so nothing
in the live path depends on it today. If regime scaling is ever enabled, the
recommended change is per bar normalisation by that bar's own close, or Wilder
smoothing, and re-fitting `ATR_CALM_PCT` / `ATR_ELEVATED_PCT` /
`ATR_EXTREME_PCT` against the new definition.

### 2.4 What the codebase does well, evidenced

These are not courtesies; each was exercised while auditing:

* **The typed boundary works.** Impossible prints are refused at construction
  rather than scored. All of these raise, verified:

  ```
  NaN       -> rejected: open=nan is not a positive finite price
  inf       -> rejected: open=inf is not a positive finite price
  zero      -> rejected: open=0.0 is not a positive finite price
  negative  -> rejected: open=-5.0 is not a positive finite price
  high<low  -> rejected: impossible OHLC
  ```

* **Pydantic is optional and the invariants are duplicated in `__post_init__`**,
  so the strict path and the fallback path enforce the same law. This box runs
  `MODEL_MODE = pydantic`; CI without pydantic still enforces the invariants.
* **The session law lives in exactly one place.** `src/data/sessions.py` owns
  the UTC+5 pin and the Friday two band schedule, and the Cloudflare worker
  mirrors it, with a parity test guarding drift.
* **The fault taxonomy is typed**, so callers branch on the class rather than
  string matching a reason: `ScanFault` with `InsufficientCoverage`,
  `StaleFeed`, `VolumeUnavailable`, `SourceUnavailable`, `MarketClosed`,
  `ScanAborted`.

### 2.5 Complete runnable example

Two examples, both actually executed.

**(a) The shipped core model run**, existing file, verified working:

```
$ python examples/scan_once.py --synthetic
verdict   : TRADE 10:02 2026-10-09 10:02 PKT AASM score 69.87 coverage 319/319
candidate : AASM score 69.87 entry 103.9216 target 106.0
volatility: AASM regime=CALM atr=0.00103 edges=[]
EXAMPLE_EXIT=0
```

**(b) The new edge case harness**, `examples/deep_scan_stress.py`, which drives
the real `contracts` and `volatility` modules through the pathological inputs a
KMIALL session actually produces, asserts a pre-declared outcome for each, and
fails fast:

```
$ python examples/deep_scan_stress.py --json data/deep_scan_stress.json
[PASS] volatility spike escalates the regime
[PASS] thin sample reports UNKNOWN, never a guess
[PASS] stale last bar is flagged
[PASS] limit lock is untradable
[PASS] absent volume is flagged
[PASS] gap open is flagged
[PASS] malformed bar refused at the boundary
[PASS] veto is typed and off by default

8/8 expectations held
STRESS_EXIT=0
```

It also enforces the strict JSON invariant from finding 5: every assessment
must survive `json.dumps(..., allow_nan=False)`. Finding 5 is informational
rather than a live defect, because `Bar` already refuses non-finite prices at
construction, so a non-finite reading is unreachable through the supported API.
The assertion is kept as a regression guard, for the day someone measures bars
from a path that bypasses the boundary.

### 2.6 Refactored snippet, strictly typed, and executed

The audit's recommended shape for the volatility reading, applied. It is
standalone standard library code, matching what the project already uses
(`statistics`, `dataclasses`) rather than introducing numpy or pandas, and it
was executed during this audit, not pasted from memory. Output:

```
[PASS] thin sample: {"regime": "UNKNOWN", "atr_pct": null, "bars": 3,
                     "reason": "thin sample: 3 bars, 10 required"}
[PASS] calm tape: {"regime": "CALM", "atr_pct": 0.00099..., "bars": 30}
[PASS] volatility spike: {"regime": "EXTREME", "atr_pct": 0.0644..., "bars": 30}
[PASS] malformed print: {"regime": "UNKNOWN", "atr_pct": null, "bars": 12,
                         "reason": "impossible OHLC at 10:06: high 98.0 below low 101.0"}
       per-bar normalised true range: first 0.02000, last 0.03871
       (old rule divided both by 155.0)

4/4 expectations held, exit 0
```

The four design decisions it makes explicit, each of which maps to a finding
above:

1. **Missing data is an answer, not an exception.** Below the coverage floor
   the function returns `UNKNOWN` carrying a reason, so a caller logs why
   instead of catching a mystery (finding 3).
2. **Malformed data is an exception.** A non-finite, non-positive, or
   impossible OHLC bar raises the typed `InsufficientCoverage`, which is the
   `ScanFault` pattern the repository already uses, so callers branch on the
   class and not on a reason string.
3. **Normalisation is per bar, by that bar's own close**, removing the
   session-end dependency described in 2.3. Measured on the same walk fixture,
   the first bar reads 0.02000 instead of being divided down by 155.0.
4. **Serialisation is strict.** `as_dict` replaces any non-finite value with
   `None`, so `json.dumps(..., allow_nan=False)` cannot fail downstream and a
   `NaN` can never reach the Cloudflare edge or the phone app (finding 5).

```python
class Regime(str, Enum):
    CALM = "CALM"; NORMAL = "NORMAL"; ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"; UNKNOWN = "UNKNOWN"


class InsufficientCoverage(ValueError):
    """Typed fault: the data cannot support a reading."""


@dataclass(frozen=True, slots=True)
class Reading:
    regime: Regime
    atr_pct: float | None
    bars: int
    reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        value = self.atr_pct
        if value is not None and not math.isfinite(value):
            value = None
        return {"regime": self.regime.value, "atr_pct": value,
                "bars": self.bars, "reason": self.reason}


def true_range_pct(bars: Sequence[MinimalBar]) -> list[float]:
    """Per-bar true range as a share of that bar's OWN close."""
    out: list[float] = []
    for index, bar in enumerate(bars):
        if not _finite_positive(bar.high, bar.low, bar.close):
            raise InsufficientCoverage(
                f"bar at {bar.timestamp:%H:%M} has a non-finite or "
                f"non-positive price ({bar.high}, {bar.low}, {bar.close})")
        if bar.high + 1e-9 < bar.low:
            raise InsufficientCoverage(
                f"impossible OHLC at {bar.timestamp:%H:%M}: "
                f"high {bar.high} below low {bar.low}")
        span = (bar.high - bar.low if index == 0 else
                max(bar.high - bar.low,
                    abs(bar.high - bars[index - 1].close),
                    abs(bar.low - bars[index - 1].close)))
        out.append(span / bar.close)
    return out


def read(bars: Sequence[MinimalBar]) -> Reading:
    """Never raises for missing data, always for malformed data, and never
    guesses below the coverage floor."""
    ordered = sorted(bars, key=lambda b: b.timestamp)
    if len(ordered) < MIN_BARS_FOR_VOLATILITY:
        return Reading(Regime.UNKNOWN, None, len(ordered),
                       f"thin sample: {len(ordered)} bars, "
                       f"{MIN_BARS_FOR_VOLATILITY} required")
    try:
        pcts = true_range_pct(ordered)
    except InsufficientCoverage as fault:
        return Reading(Regime.UNKNOWN, None, len(ordered), str(fault))
    atr = sum(pcts) / len(pcts)
    return Reading(classify(atr), atr, len(ordered))
```

This is offered as the target shape for `src/signals/volatility.py`, not as a
second engine. Only item 3 changes a number; items 1, 2 and 4 change how a
failure is reported, which is where the audit found the real ambiguity.

### 2.7 Bottlenecks, measured rather than asserted

The request asked for bottlenecks. Measured on this machine over a full KMIALL
session shape (319 symbols, 75 bars each, 23,925 bars):

| stage | measured | share of a 5 minute tick |
|---|---|---|
| bar construction including schema validation | 91.3 ms | 0.03 percent |
| `volatility.assess` over the whole universe | 35.2 ms (110 us per symbol) | 0.012 percent |
| whole decision path, `scan_once.py --synthetic` | 0.85 s wall, exit 0 | includes interpreter start |

**There is no CPU bottleneck to fix.** All the arithmetic in a scan is roughly
0.04 percent of the tick budget, and the dominant cost in the 0.85 s figure is
interpreter startup and module import, not the model. Optimising the signal
maths here would be work with no measurable payoff, so none was done.

The real bottlenecks are outside the model:

1. **Process startup and import** dominates a single-run scan. If ticks ever
   feel slow, the fix is a warm process, not a faster ATR.
2. **Network IO** on the capture refresh and the Telegram relay call is
   unbounded by anything measured here, and it is the only part that can
   threaten a 5 minute slot.
3. **A minor micro-inefficiency**, recorded for completeness: `assess` walks the
   bars for `max`/`min` twice (once in `detect_edge_cases`, once for the swing
   reading). At 110 us per symbol this is noise, and folding the two passes
   would trade clarity for a saving smaller than the measurement error.

---

## Verification log

| check | command | result |
|---|---|---|
| Governance on `860fdab` | `GOVERN_COMMIT_RANGE=origin/master..HEAD python scripts/check_governance.py` | exit 1, two real SO-7 trailer violations, no phantom dash |
| Governance on `7e94802` | `GOVERN_COMMIT_RANGE=0e6916a..7e94802 ...` | exit 0, passed |
| Tree equivalence | `git rev-parse 7e94802^{tree} 860fdab^{tree}` | identical, `fdbea9b7...` |
| Full unit suite | `python -m unittest discover -s tests -v` | 347 tests, OK, exit 0 |
| Core model run | `python examples/scan_once.py --synthetic` | exit 0, TRADE AASM 69.87 |
| Edge case harness | `python examples/deep_scan_stress.py` | 8/8, exit 0, strict JSON artifact written |
| Template YAML | `yaml.safe_load(...)` | parses, 9 named steps |
| Refactored snippet | executed standalone during the audit | 4/4, exit 0, typed reasons instead of NaN |
| Performance | bar build 91.3 ms, `assess` 35.2 ms over 23,925 bars | 0.04 percent of a 5 minute tick |
| Governance clean-check | banned-dash scan on all 5 added/changed files | 0 hits, no new file-level violations |

## Limitations, stated plainly

1. **`node` is not installed on this machine.** The CI step
   `node --input-type=module --check < cloud/worker.js` could not be run
   locally, so worker syntax validity is unverified here. It is not evidence of
   a defect: both failing runs aborted at the governance step, and PR #57's
   identical tree passed the whole job including that step.
2. **The governance failure is a commit message defect, not a code defect.**
   No source change fixes `860fdab`; the repair is to land `7e94802` (PR #57),
   which the GitHub API confirms is open, clean, and green.
3. **Nothing was pushed, merged, or deployed.** PR #57 remains open, PR #58
   remains closed, and the differences in this working tree are uncommitted.
   Merging and force-pushing are the owner's calls.
4. **Finding 4 is a judgement call, not a bug.** It is recorded so the owner
   can decide before enabling regime aware targets.
