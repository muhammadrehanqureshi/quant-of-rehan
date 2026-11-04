# Breakthrough 1.0 results, 2026-11-04

Answers to `QoR-agent-brief-2026-11-03.md` version 2. Research and shadow work
only. Nothing here changes `kalman_trend_flip_v1`, its parameters, its gates or
the 2 percent target and 1 percent stop. Nothing is promoted. A negative answer
is a good answer, and a question the data cannot answer is written down as not
measured rather than filled in.

Report written in Karachi time (UTC+5, SO-8). All computation ran in GitHub
Actions. No backtest, replay or research run executed on the owner's PC
(SO-12, SO-21, and the owner order of 2026-10-19).

## 1. Where the work ran

| item | entry point | run | state at the time of writing |
|---|---|---|---|
| Breakthrough families 1 and 3, plus the median-only market gate | `.github/workflows/backtest.yml`, task `breakthrough` | 41794616689 | executing in the cloud; section 8 carries its state and its numbers when it reports |
| Pre-registration of the 30 new variants | `scripts/preregister_breakthrough.py`, inside the same job | 41794616689 | written before any family was scored |
| Family runner | `scripts/breakthrough_families.py` | 41794616689 | guarded by `guard_cloud_backtest`, refuses a local run |
| Relay write budget fix (not part of this brief, but it stopped the card) | PR #247, `c7fe30c` | 41797375995 | deployed, verified on `/health` |

## 2. Part 1A: the three losses, closed

The brief asked for the third loss to be verified from the record and not taken
on trust. It is verified, and it is worse than "hit its stop".

Every figure below is read from the session journal the live loop itself wrote.
The 2026-11-03 row comes from the artifact of run 41596775833
(`data/forward/session_journal.jsonl`, `date: 2026-11-03`). The 2026-10-30 and
2026-11-02 rows come from `reports/2026-11-02.md`, which the same loop wrote.

| date (PKT) | symbol | entry | entry time | score | eligible | coverage | stop | exit | exit time | minutes held | outcome | gross | net |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-30 | PRL | 98.20 | 15:12:04 | 88.21 | 26 | not recorded | 97.218 | 97.218 | 16:20:00 | 67 | STOP_HIT | -1.00% | -1.648% |
| 2026-11-02 | CNERGY | 12.50 | 09:52:00 | 89.10 | 6 | not recorded | 12.375 | 12.37 | 10:11:00 | 19 | STOP_HIT | -1.04% | recorded at the post-close finalize |
| 2026-11-03 | FECTC | 95.50 | 09:52:00 | 89.10 | 290 | 91.48% of 317 | 94.545 | 92.52 | 09:53:00 | 1 | STOP_HIT | -3.1204% | -3.7684% |

Ledger: 3 trades, 0 wins. Cost model on every row: 22.4 bps a side plus 10 bps
slippage a side, 64.8 bps round trip, 15 percent CGT on gains.

### The finding that matters

The 2026-11-03 call was **FECTC**, not a name the brief named, and the stop did
not hold:

* the stop was 94.545 and the print that closed the trade was 92.52;
* that is 2.025 points through the stop, or 2.14 percent below the stop price;
* the realised gross loss was -3.1204 percent against a -1.00 percent band, so
  the trade lost 3.12 times what the law says it can lose;
* it took one minute.

This is not a rounding error and it is not a wide bid and ask alone. A one
minute, three percent fall through a one percent stop means the fill left the
band, and the arithmetic of the law, its 58.92 percent break-even and the
2 to 1 payoff, assumes the band is real. For FECTC on 2026-11-03 it was not.

The same session's tape says why the fill is believable and why it is not a
data fault on our side: 282,388 bar rows seen, 237,092 duplicate rows, 46,282
rows carrying no usable price, first observation 09:00 PKT, and 147 of 297
symbols starting after the open. The strip was thin that morning, coverage was
290 of 317 symbols, and the trade was taken at 09:52, twenty minutes into the
band.

### What part 1A asked for and does not have

The brief lists fields the record does not carry. They are named here instead of
guessed:

| field | state |
|---|---|
| tick size as a percent of price | NOT MEASURED: no verified tick size table is applied in this repo |
| rank at entry | NOT MEASURED for all three: only the score is journalled |
| KSE100 move at entry and over the 30 minutes before it | NOT MEASURED: the 2026-11-03 journal carries breadth and median return, not the index |
| the stock's day range so far at entry | NOT MEASURED |
| trailing 30 minute realised volatility at entry | NOT MEASURED |
| 5, 10 and 20 minute best and worst excursion after entry | NOT MEASURED: needs the tape replay of part 1B |
| stop filled at the stop or through it | MEASURED: PRL and CNERGY filled at the stop; FECTC filled 2.14 percent through it |

## 3. Part 1B to 1E: why there is no number yet

Part 1B is the load bearing item. It labels every ranked candidate under the
deployed law, and questions 1, 2, 3 and 4 are all read off it. It is not
measured, and the reason is structural rather than a decision to skip it.

The replay needs one session of bars per session replayed. That tape exists in
exactly two places:

* on the owner's PC, under `data/feed_capture/`, which `/data/` in `.gitignore`
  keeps out of the repository, so a GitHub Actions runner never sees it;
* in the cloud, as `data/forward/tape_bars_<date>.ndjson` uploaded by
  `intraday-capture.yml`. Only two such artifacts exist in the last 100, both
  thin, and neither is enough for a rate.

Running the replay on this PC is refused by the owner order of 2026-10-19 and by
`guard_cloud_backtest`, and the relay's own observation archive, which would be
the third path, is unreadable while its daily budget is spent.

So parts 1B, 1C, 1D and 1E are **BLOCKED: DATA**, with a named fix rather than a
shrug: a labeller that runs inside the band runner, where that band's tape
already exists, labels every ranked candidate once per session and uploads only
the labels. That is the next change, and it is what turns these four questions
from blocked into accumulating.

## 4. Part 1F: run 4

**BLOCKED: RECORD.** No run id, artifact or report matches the four wide stop
shapes described in section 14. Nothing is claimed about them.

## 5. Part 2 and question 6

Families 1 and 3 and the median-only market gate were registered and dispatched
in run 41794616689. The common method is the one the brief fixes: ten year
KMIALL daily panel, entry at the next open, stop first when one bar touches both
levels, repo costs and CGT, splits locked at discovery 2016-10-29 to 2024-06-30,
validation 2024-07-01 to 2025-12-31, test 2026-01-01 to 2026-10-30. Kill rules
are `KILL_FEW_TRADES` and `KILL_NEGATIVE_EDGE` at each shape's own break-even.

The market gate has a defect of coverage worth stating before any result: the
daily panel carries no KSE100 series, so the two index legs of family 2
(KSE100 above its 50 day average, and the index's 20 day realised volatility
below its trailing median) are **NOT MEASURED**, and the gate that was tested is
the median KMIALL stock above its 50 day average, which the brief permits as the
fallback. Every gated row names that fallback.

| family | state |
|---|---|
| F1, 52 week high momentum, 18 shapes (3 proximity, 3 holds, bracket none or 2/1) | registered and dispatched |
| F2, market gate on the F1 base and the F3 base | median KMIALL leg only; KSE100 legs NOT MEASURED |
| F3, pullback in an uptrend, 3 shapes (drop 3, 4 or 5 percent) | registered and dispatched |
| F4, daily filter plus intraday Kalman trigger, volatility sized stop | registered as 6 rows (2 eligible sets, F1 and F3, times 3 stop multiples); needs tape, so NOT MEASURED |
| F5, event drift | **BLOCKED: DATA**: no dated event calendar exists in the repo or the relay |
| F6, sector lead lag | **BLOCKED: DATA**: the KMIALL universe carries no sector field |

The family table itself, with each shape's own numbers, is section 8. It is
filled from the run's artifact the moment the job reports, and the report is
then landed as one document rather than two.

## 6. The six questions

| # | question | answer | verdict |
|---|---|---|---|
| 1 | Does the rank 1 pick hit +2 percent before -1 percent more often than a random eligible pick at the same minute? | NOT MEASURED. Part 1B is blocked on tape, section 3. Nothing is substituted for it. | NOT MET |
| 2 | Is the rank 1 hit rate above 58.92 percent, and if not by how many points is it below? | NOT MEASURED for the same reason. The live ledger's own rate is 0 of 3, which is a fact about three trades and not a hit rate. | NOT MET |
| 3 | Does the hit rate change with time of day or price tier enough to justify a no trade zone? | NOT MEASURED. Part 1C needs the same labelled candidates. | NOT MET |
| 4 | Under the volatility scaled bracket, what are the break-even and the observed rate? | NOT MEASURED. Part 1D is registered as F4 (stops at 1.0, 1.5 and 2.0 times 30 minute realised volatility) and cannot be scored without tape. | NOT MET |
| 5 | How many labelled sessions are needed before question 2 can be answered at 95 percent, and how many does the ledger have today? | MEASURED, arithmetic in section 7: 381 sessions to resolve a 65 percent rate against the 58.92 percent break-even at 80 percent power, 1,536 for 62 percent, 12,722 for 60 percent. The ledger holds 3. | MET |
| 6 | Which Breakthrough families survive their own break-even at discovery, at validation and on the locked test, and which are BLOCKED: DATA? | F5 and F6 are BLOCKED: DATA. F1, F2, F3 and F4 were registered; F1, F2 and F3 were dispatched in 41794616689 and F4 needs tape. Survivors: section 8. | PARTLY MET |

## 7. Question 5, worked out

The break-even is 58.92 percent. A one sided test at 95 percent with 80 percent
power needs this many rank 1 sessions, using the normal approximation on the
proportion:

| true rank 1 rate | difference from break-even | sessions needed |
|---|---|---|
| 65 percent | +6.08 points | 381 |
| 62 percent | +3.08 points | 1,536 |
| 60 percent | +1.08 points | 12,722 |

And the interval itself at a 65 percent observed rate: 381 sessions give a
Wilson interval of 60.1 to 69.6 percent, which clears 58.92. At 100 sessions the
interval is 55.3 to 73.6 percent, which does not.

The ledger has 3 sessions. It is 127 times short of the first row of that table.

## 8. The family table

Run 41794616689 was still building its ten-year panel when this report was
written and landed, so there is no family number in it yet. That is stated
plainly rather than left to look like a pass. The job's own state and, when it
reports, the artifact's own rows are appended to this file in a follow-up
commit; if the job fails, its failure and log are written here instead.

What the run will settle, and how each shape is judged, so the numbers cannot
be read as a verdict after the fact:

* discovery keeps a shape only if it clears `KILL_FEW_TRADES` and
  `KILL_NEGATIVE_EDGE` at that shape's own break-even, so an 8 shape cannot be
  passed by a 6 shape's arithmetic;
* the primary metric is mean net return per trade with a day clustered
  bootstrap lower bound at 2.5 percent, not a win rate;
* beside it: the Wilson interval on the hit rate, that shape's break-even, the
  worst single loss, the 5th percentile trade and trades per month;
* validation is scored once with the frozen cuts, and the locked test only
  after validation keeps the shape;
* a shape that dies at discovery is not widened to rescue it.

## 9. Trial accounting

Carried forward as the brief requires, so Holm sees the whole family and not
only what was convenient today:

* 39 trials in the search program before this brief;
* the 4 wide stop shapes of run 4;
* 30 new variants registered by `scripts/preregister_breakthrough.py`:
  18 for F1, 3 for F3, 2 for F2, 6 for F4 (two eligible sets times three stop
  multiples), and 1 for the F1b Kalman entry timer;
* family size before any Holm correction: **73**.

The registry file the job uploads holds the 30 new rows with `decision:
preregistered`, because a fresh runner starts with an empty gitignored registry.
The 39 and the 4 are carried in the count above, not in that file.

No grid was widened after a result. No parameter was added after a number was
seen.

## 10. What was measured and what was not

Measured: the three trades of the live ledger, including the third one, which is
FECTC and which lost 3.12 times its own stop band; the fact that the stop filled
2.14 percent through its price on that trade in one minute; the sample size
question 2 actually needs, which is 381 sessions at the most generous assumption
the brief allows and 12,722 at a one point edge; and the relay's own write
budget, which was spending the whole free plan day by 12:10 PKT and is fixed as
of `c7fe30c`.

Not measured, and not guessed: whether the rank 1 pick beats a random eligible
pick; the rank 1 hit rate against 58.92 percent; any time of day or price tier
effect; the volatility scaled bracket's observed rate; every Breakthrough family
result that depends on tape; the KSE100 legs of the market gate; the four wide
stop shapes of run 4; and the results of families 1, 2 and 3 at the time this
section was written.

Nothing here is promoted. A survivor stays shadowed until it has at least 100
locked forward trades.
