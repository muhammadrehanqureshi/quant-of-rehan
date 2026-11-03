# Breakthrough 1.0: three stops, the ledger, and six families

Report date: 2026-11-03 (Karachi). Scope: research and shadow work only. No
change was made to `kalman_trend_flip_v1`, its parameters, its gates or its
2 percent / 1 percent bracket. Nothing is promoted, and the live contract is
unchanged: one call a day, target +2 percent, stop -1 percent, one session.

Sources read for this report: `reports/2026-11-02.md`, `PROJECT_REPORT.md`
sections 13 to 15, `src/signals/kalman_trend.py`,
`src/research/experiment_registry.py`, `src/research/outcome_labeler.py`,
`scripts/self_improve.py`, `scripts/kalman_grid_fit.py`,
`src/data/tape_bars.py`, `src/config.py`, the local feed capture directory,
the public relay endpoints `/market` and `/health`, and the GitHub Actions run
list. No figure below is estimated. Where a figure could not be read, the
row says BLOCKED or NOT MEASURED and stops there.

## 1. Ledger closure

The relay's public close ledger at `computed_at 2026-11-03T07:59Z` reports
`wins 0, losses 3, closed 3`. The third loss therefore exists in the ledger.
The relay's research archive (`GET /research/observations?date=2026-11-03`)
returns HTTP 403 without the admin token, and no admin token is available on
this machine, so the third trade's symbol, entry, rank and excursions could
not be read. That is a record gap, not a missing loss.

| date (PKT) | symbol | entry | entry PKT | stop | exit | exit PKT | minutes | outcome | score | rank | eligible | coverage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-30 | PRL | 98.20 | 15:12:04 | 97.218 | 97.218 | 16:20:00 | 67 | STOP_HIT, -1.00 pct gross, -1.648 pct net | 88.21 | 1 | 26 | 296/317 |
| 2026-11-02 | CNERGY | 12.50 | 09:52:00 | 12.375 | 12.37 | 10:11:00 | 19 | STOP_HIT, -1.04 pct gross, net at finalize | 89.10 | 1 | 6 | 246/317 |
| 2026-11-03 | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | BLOCKED | STOP_HIT (ledger) | BLOCKED | BLOCKED | BLOCKED | BLOCKED |

The two documented rows are carried from `reports/2026-11-02.md`, which read
them from the archive and the 2026-10-30 finalize artifact. The 2026-11-03 row
is BLOCKED: DATA for every field except the outcome; the ledger's 0 wins of 3
is the verified fact.

### 1.1 The fields the brief asks for, and why most are absent

Tick size as a percent of price, the KSE100 move at entry and over the 30
minutes before it, each stock's day range so far, its trailing 30 minute
realized volatility, the 5, 10 and 20 minute best and worst excursions after
entry, and whether the stop filled at the stop or through it are all tape
facts. They are not in the committed artifacts. The archive that holds them
is 403 without the admin token. Of the sessions involved, this clone holds a
tape for 2026-11-03 only (0.5 MB, partial), and holds no tape for 2026-10-30
or 2026-11-02. Replaying the archived tape is an Actions job and no such job
exists yet, so those cells are NOT MEASURED rather than filled from memory.

What can be said from the record: PRL's stop filled at the stop level itself
(97.218) and CNERGY's exited at 12.37, 0.005 below its 12.375 stop, a fill
within a fraction of a percent of the stop rather than far through it.

## 2. Break-even arithmetic and how much information 0 for 3 carries

The deployed bracket pays +2 percent against -1 percent. On a driftless
price the chance of touching +2 percent before -1 percent is 1 in 3, or 33.33
percent. The 64.8 bps round trip cost plus 15 percent CGT on gains moves the
break-even win rate to 58.92 percent. An entry rule therefore has to add
25.59 points of hit rate over the driftless baseline merely to break even.

| closed | wins | observed | break-even | gap to break-even | Wilson 95 pct | exact one-sided 95 pct upper | one-sided p against 58.92 pct |
|---|---|---|---|---|---|---|---|
| 3 | 0 | 0.00 pct | 58.92 pct | -58.92 pts | 0.00 to 56.15 pct | 63.16 pct | 0.2046 |

Read honestly, the line says two things at once. The point estimate is 58.92
points below the break-even, and the Wilson upper edge sits just under it.
But the exact one-sided bound still admits a true rate as high as 63.16
percent, and the one-sided p of 0.2046 is nowhere near evidence. Three
losses are consistent with a losing rule; they are also consistent with a
rule that wins 59 percent of the time. The ledger is too shallow to tell.

### 2.1 How many labeled trades the question needs

Using the observed-rate standard error at p = 0.5892 and a 95 percent normal
interval:

| target half-width | labeled trades needed |
|---|---|
| 8 points | 146 |
| 5 points | 372 |
| 3 points | 1033 |

The ledger has 3. A candidate-labeling pass over one session produces
several labeled candidates but only one independent day, so the day count,
not the candidate count, is the honest denominator for question 2.

## 3. Part 1 studies: registered method, absent results

| item | status | what exists | what is missing |
|---|---|---|---|
| A. Close the ledger | PARTIAL | PRL and CNERGY rows above, 0/3 from `/market` | 2026-11-03 details (archive 403), tick, KSE100 move, range, RV, excursions |
| B. Label every ranked candidate | NOT MEASURED | `src/research/outcome_labeler.py`, `src/data/tape_bars.py` | no replay job, no archived observation dump, no tape for 10-30 or 11-02 in this clone |
| C. Excursion study | NOT MEASURED | depends on B | same |
| D. Volatility scaled bracket | NOT MEASURED | depends on C for the RV distribution | no run |
| E. Abstention | NOT MEASURED | depends on B and D | no run |
| F. Run 4, four wide stop shapes | BLOCKED: RECORD | none found | no run id or artifact matching four wide stop shapes |

Local tapes present: 2026-10-18 (2.5 MB), 2026-10-21 (135.8 MB), 2026-10-23
(93.8 MB), 2026-11-03 (0.5 MB, partial). The two sessions with documented
trades have no local tape. The last 25 Actions runs are console work. Two
earlier backtest runs, 41273110941 (the ten year panel) and 41278455054, both
succeeded, but neither is the four shape stop run, and the four wide stop
shapes the brief says were dispatched in section 14 do not appear anywhere in
this clone's run record. Section 14 of this repository's `PROJECT_REPORT.md`
covers the Friday and band record, not a run registry, so the four shapes
cannot be traced from it. Their trial count is
still carried below, per the brief, and the record gap is reported rather
than papered over.

### 3.1 What a labeling job would be

One `backtest.yml` task, `label-candidates`, taking a date range and reading
the archived observation snapshots plus the tape. For each entry pass it
would replay the ranked list under the deployed law: entry at the next
completed bar, stop first when a bar touches both, the repo's 64.8 bps and
CGT, then emit per candidate the rank bucket, excursions at 5, 10, 20 and 60
minutes and to the close, the time-of-day bucket, the price tier, and the
tick as a percent of price. Results would land as an artifact and a registry
row, with the day as the resampling unit. It does not exist, so there is no
hit rate for rank 1, for ranks 2 to 5, for rank 6 and below, or for a random
eligible pick at the same minute. Writing those numbers without the job would
break SO-3.

## 4. Pre-registration, before any result

The registry at `data/research/experiments.jsonl` held zero rows when this
work started. `scripts/preregister_breakthrough.py` writes the rows below
with `results: null` and `decision: preregistered`. The file is gitignored,
so the table is the durable copy in the pull request.

Trial accounting carried forward: 39 prior trials, plus the 4 wide stop shapes
of run 4, plus 30 new variants registered here, for a family size of 73 before
any Holm adjustment. The four run-4 shapes are counted even though their
record is missing.

| family | variants | exact grid |
|---|---|---|
| 1. 52 week high | 18 | top 50 by 60 day median traded value; close within {2, 3, 5} pct of the 252 day high; volume at least 1.5 times its 20 day average; entry next open; hold {2, 3, 5} closes; bracket {none, 2/1} |
| 1b. 52 week high, Kalman timer | 1 | proximity 3 pct, volume 1.5 times, tape sessions only, Kalman flip as entry timer, 2/1 bracket |
| 2. Regime gate | 2 | gate = median KMIALL stock above its 50 day average AND KSE100 above its 50 day average AND KSE100 20 day realized volatility below its trailing 252 day median; applied to family 1 base (3 pct, 3 closes, 2/1) and family 3 base (4 pct drop, 2 pct bounce) |
| 3. Pullback in uptrend | 3 | top 50 by 60 day median value; close above 50 day average; 2 to 3 day drop of at least {3, 4, 5} pct; buy next open; exit on a 2 pct bounce or after 3 closes |
| 4. Daily filter plus intraday trigger | 6 | eligible set from family 1 or family 3 and gate 2; Kalman flip times the entry; stop at {1.0, 1.5, 2.0} times trailing 30 minute realized volatility; target twice the stop; tape sessions only |
| 5. Event drift | 0 | BLOCKED: DATA, no calendar, no row |
| 6. Sector lead lag | 0 | BLOCKED: DATA, no sector field, no row |

Total registered here: 18 + 1 + 2 + 3 + 6 = 30. No grid may be widened after
a result is seen. Each family is killed by its own break-even, computed from
its own stop, target and holding period, using KILL_FEW_TRADES and
KILL_NEGATIVE_EDGE; no shape is compared against a flat 90 percent or 60
percent floor.

## 5. The six families: data inventory and status

The common panel is the 10 year KMIALL daily panel used by run 41273110941,
with the locked splits: discovery 2016-10-29 to 2024-06-30,
validation 2024-07-01 to 2025-12-31, test 2026-01-01 to 2026-10-30. Entry at
the next bar's open, stop first when one bar touches both levels, repo costs
and CGT. The primary metric is mean net return per trade with a day clustered
bootstrap lower bound, printed beside the hit rate and its Wilson interval,
its own break-even, the worst single loss, the 5th percentile trade and
trades per month.

Family 1 is buildable from that panel and was not run in this session. Family
2 needs an index series in the panel; if the panel carries no KSE100 series
the run must fall back to the median KMIALL stock alone and say so in its
artifact. Family 3 is buildable and was not run. Family 4 is tape-only: four
local tape sessions exist, so it is thin by construction and its report would
have to state the session count. Family 5 has no dated event calendar:
`src/data/registry.py` still lists corporate actions as a degraded source
with no parsing pipeline, and no dividend, book closure, results or SBP rate
file exists in the repository. Free option: the PSX announcements pages and
the SBP monetary policy calendar, read under each site's terms, parsed into a
dated table; that is a data build, not a scrape to start silently. Family 6
is blocked: `src/data/universe_kmiall.json` carries 319 rows with `symbol`,
`name`, `isShariahCompliant` and `listedIn` only, no sector. Free option: the
PSX sector classification or the KMIALL composition sheet, mapped by hand and
committed as a table.

The literature check in the brief was not redone in this session. The Sadaqat
and Butt (2018, IBA Business Review 12(1)) momentum and volatility scaling
result is carried as quoted; the 52 week high attribution and the volatile
down market claim are not cited here because they were not confirmed. None of
the tests above depends on them.

## 6. The six questions

1. Does rank 1 beat a random eligible pick at the same minute on +2 percent
   before -1 percent? NOT MEASURED. The labeling job does not exist.
2. Is the rank 1 hit rate above 58.92 percent? NOT MET on the forward ledger,
   which is rank 1 by construction: 0 of 3, 58.92 points below break-even.
   The interval cannot separate it from break-even; 146 labeled trades are
   needed for an 8 point half-width, the ledger has 3.
3. Does time of day or price tier justify a no trade zone? NOT MEASURED.
4. Under a volatility scaled bracket, what are the break-even and the
   observed rate? NOT MEASURED.
5. How many labeled sessions are needed, and how many exist? 146 for an 8
   point half-width at 95 percent, 372 for 5 points; the ledger has 3 closed
   trades. If one session yields several labeled candidates, the day count is
   what matters and one session is one day.
6. Which families survive their own break-even, and which are BLOCKED: DATA?
   None have been run, so none has survived. Families 1 to 4 are NOT RUN.
   Family 5 is BLOCKED: DATA, no event calendar. Family 6 is BLOCKED: DATA,
   no sector field.

## 7. What a survivor would ask of the owner

Nothing, because there is no survivor yet. When a family first clears its own
break-even at discovery, the report that follows must state the holding
period in days, the signals per month, the worst single loss and the 5th
percentile trade, so the owner can decide whether it fits the live contract.
A survivor is shadowed until it has at least 100 locked forward trades.

## 8. Closing line

Measured this session: three closed calls with zero wins, the two documented
entries with their stops and scores, the break-even arithmetic and the width
of the evidence, the pre-registration of 30 new variants against a family of
73, and the data inventory that blocks families 5 and 6. Not measured: the
2026-11-03 trade's details, candidate labeling, excursions, the volatility
scaled bracket, abstention, run 4, and families 1 to 4. No number was
invented, no grid was widened, nothing was promoted, and the live law is
unchanged.
