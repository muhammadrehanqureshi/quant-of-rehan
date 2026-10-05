# RESEARCH AUDIT: prerequisites for the MAE-compression question

Question under audit: can we find a statistically robust subset of KMIALL
entries where MAE is substantially compressed while MFE stays high enough to
support a profitable +2% target?

This document inventories what the repository already contains (exact paths),
what is missing, and the exact analyses to run once the gaps are filled. It
claims no edge, modifies no strategy, and pre-registers the metric set before
any filter is tested, so results cannot be cherry-picked after the fact.

## 1. What already exists (exact paths)

| Path | Contents | Role in the audit |
|---|---|---|
| `data/eod_history_kmi.csv.gz` | 283,630 rows, 305 symbols, 1,238 sessions, 2021-10-04..2026-10-02, date/symbol/name/open/high/low/close/volume/rate2 | Primary dataset. Unadjusted. Universe membership = CURRENT KMIALL (survivorship-biased) |
| `data/eod_history.csv.gz` | 950,902 rows, 4,545 symbols, all boards | Same sessions, whole market. Needed to rebuild dead/renamed members |
| `data/eod_history.csv.coverage.json` | session coverage of the crawl | Completeness check |
| `data/entry_metrics_report.json` | MAE/MFE distributions, time-to-target, horizon returns, two populations | Published study this audit extends |
| `data/backtest_smoke_5y.json` | summary of the 74,654-trade baseline run | Aggregate confirmation; trade-level rows do NOT exist anywhere |
| `src/backtest/engine.py` | fill model: T close signal, T+1 open entry, TP exact, SL stop-or-gap, close-mode pierce fill, same-bar SL-wins, print-chain invalid screen, chronological equity | The execution model to audit |
| `src/backtest/walkforward.py` | rolling-origin folds, leakage asserts | Scaffolding for robustness testing |
| `scripts/entry_metrics.py` | grouped-shift path metrics, clean-window gating | Template for the trade-matrix generator |
| `scripts/smoke_backtest.py` | placeholder signal definition | Population definition |
| `data/legacy_sentinel/data/corporate_actions.json` | 190 records, notices + results by symbol (fetched 2026-09-24) | Partial corporate-action info, recent-biased, no adjustment factors |
| `data/legacy_sentinel/data/sector_map.json` | symbol to sector map, current | Current sectors only; history unknown |
| `data/legacy_sentinel/data/kmiall_tickers.json` | current KMIALL membership + Shariah flags | The survivorship-biased membership list itself |
| `data/legacy_sentinel/data/psx_holidays.json` | 2026 PSX holidays | Session calendar |
| `data/legacy_sentinel/data/close_history.json` | recent sessions with c/h/l/vol per symbol | Only recent intraday-adjacent detail; not 5 years |
| `data/legacy_sentinel/data/overnight_study.json` | by_weekday, by_month, same_night, across_closure stats from the sentinel era | Prior art for time-based analysis |
| `data/legacy_sentinel/snapshots/*.jsonl.gz` | 10 days of intraday snapshots (2026-09-17..2026-10-05) | Only intraday detail available; too short for 5-year claims |
| `data/legacy_sentinel/sweep_panels/*.jsonl` | 7 days of order-book sweep panels | Genuine depth, recent only; no 5-year depth exists anywhere |

## 2. Missing data that blocks honest answers

A. BLOCKING (must have before any filter conclusion):
   - Point-in-time KMIALL membership by date (see section 9)
   - Corporate-action adjustment factors per symbol per ex-date
   - Trade-level matrix from the 74,654-trade run (section 3)

B. STRONGLY RECOMMENDED:
   - KSE-100 / KMIALL index OHLC daily history, 5 years
   - Turnover and trade counts per symbol per day
   - Historical sector memberships (at minimum yearly snapshots)
   - Circuit-breaker (upper/lower limit) events per symbol per day
   - Suspension calendar per symbol

C. CANNOT BE SOURCED (stated per SO-3, not faked):
   - Historical bid/ask, depth, order flow, footprint. The 10-day
     snapshot window is the entire genuine depth archive in existence.
   - Intraday bars before the snapshot window.

## 3. Trade-level matrix to generate (pre-registered schema)

One row per entry, columns:
  symbol, signal_date, entry_date, entry_price,
  o1,h1,l1,c1, o2,h2,l2,c2, o3,h3,l3,c3 (entry bar first),
  mae_1bar, mfe_1bar, mae_3bar, mfe_3bar,
  t_to_mae, t_to_mfe, t_to_p05, t_to_p10, t_to_p15, t_to_p20,
  p05_before_m10, p10_before_m10, p15_before_m10, p20_before_m10,
  m10_before_p20, p20_before_m20,
  ret_close1, ret_close2, ret_close3, ret_close5, ret_close10,
  gap_next_open, holding_bars, data_invalid,
  precomputed features at T (see section 5): all as-of-T values only.

Generation: `scripts/build_trade_matrix.py`, output
`data/trade_matrix.parquet` (gitignored), ~74,654 rows x ~60 cols.

## 4. Pre-registered quality metric set (every filter, no exceptions)

n, median MAE, MAE p25/p75, median MFE, MFE p25/p75,
reach rates for +0.5/+1/+1.5/+2, touch rates for -0.5/-1/-1.5/-2,
p20_before_m10, p20_before_m20, median t_to_p10, median t_to_p20,
mean ret_close3, median ret_close3, MAE-compression ratio
(median MAE subset / median MAE complement), lift vs complement with
bootstrap 95% CI (1,000 resamples), n>=500 gate.

Ranking order (owner-registered): MAE compression first, MFE preservation
second, +2% reach third, +2-before-adverse fourth, significance fifth.
Raw profit is NOT a ranking criterion.

## 5. Single-variable experiment matrix (as-of-T features only)

MARKET REGIME (from index history once fetched):
  KMIALL proxy close > / < its 20-day and 50-day means; 20-day return
  quintile; breadth = share of universe above own 20-day mean; 20-day
  realized vol quintile of the index proxy.

RELATIVE STRENGTH (needs index proxy):
  stock 5d/10d/20d return minus index 5d/10d/20d, quintiled;
  RS acceleration = 5d RS minus prior 5d RS.

VOLUME (per-symbol history only):
  relvol = volume / 20-day median, buckets <0.7, 0.7-1.0, 1-1.5, 1.5-2.5,
  >2.5; volume acceleration = vol(T)/vol(T-1) buckets; dollar turnover
  quintiles; zero-volume-day flag.

PRICE ACTION (per-symbol):
  candle body ratio = |c-o|/(h-l) quartiles; upper/lower wick ratio
  quartiles; close location value = (c-l)/(h-l) quintiles; 3-bar range
  expansion flag (true range > 1.5x 20-day median TR); 20-day high break
  flag; pullback-then-resume flag (close>MA20 with 3 consecutive lower
  closes before T).

SMC (operationalized on daily bars, no mythology):
  sweep_low: min(l1..l5 over T-6..T-2) < min(l over T-16..T-6) and
    close(T) > that swept low; sweep_high mirror;
  BOS_up: close(T) > max(close over prior 20 bars);
  displacement: body(T) >= 2x median body(20) and direction up;
  premium/discount: close(T) position within 20-bar range, top/bottom
  third; equal-lows cluster flag (two lows within 0.3% in last 10 bars).

FVG (daily, causal):
  bullish FVG at T-1: low(T-1) > high(T-3); age in bars; size in %;
  retracement state: l(T) <= fvg midpoint.

AMT/VOLUME PROFILE: REJECTED for now. 5 years of daily bars cannot
  produce honest volume-by-price; the genuine depth archive is 10 days.
  Any profile feature would be fabricated precision (SO-3).

Each filter: report the section-4 metric set on its subset AND its
complement, with n for both. No thresholds are tuned before first pass;
buckets are fixed above.

## 6. Combination experiments (smallest meaningful set)

Test only after single-variable results exist, and only pairs/triples whose
mechanics are independent:
  1. market trend x relative strength (regime gate, stock selection)
  2. relative strength x volume bucket (selection x participation)
  3. sweep_low x displacement (liquidity event x intent)
  4. sweep_low x BOS_up (event x structure)
  5. regime gate x sweep_low x FVG-retrace (full stack, 3 conditions)
Multiplicity: report Bonferroni-adjusted significance across the full
tested set; require plateaus across neighboring buckets, not single-cell
wins.

## 7. Stop/TP grid (after entry-quality work)

Stops: -0.5, -0.75, -1.0, -1.25, -1.5, -2.0, -2.5, -3.0, -4.0
Targets: +0.5, +1.0, +1.5, +2.0, +2.5, +3.0
Fill model reuses engine.py semantics (exact TP fill, gap-through SL at
open, same-bar SL-wins). Costs: 22.4 bps per side round trip + CGT 15% on
winners; slippage sensitivity at +0, +5, +10 bps. Exit-race evaluation per
(bar-level first-touch order) not per trade outcome. Robustness = plateau
detection: a cell qualifies only if at least 3 of its 4 neighbors in the
grid have positive net expectancy with overlapping bootstrap CIs.

## 8. Survivorship audit (section 9 of the brief)

Current membership is DEFINITELY point-in-time-wrong: kmiall_tickers.json
is today's list. Verification plan:
  a. dead-symbol test: count symbols in the 5-year file with no prints in
     the trailing 60 sessions (delistings/suspensions present in data but
     excluded from signals);
  b. listing-date test: first-print distribution by year (IPOs entering
     late inflate recent-window stats);
  c. PSX annual report reconstitution (5 Years Progress Report and index
     review notices) to approximate yearly membership snapshots;
  d. sensitivity: re-run the study on the subset of symbols that existed
     the full 5 years, then on all symbols with listing-date truncation;
     if MAE/MFE conclusions survive both, survivorship is second-order;
     if not, the point-in-time rebuild is mandatory before any filter
     conclusion.

## 9. Execution-model audit checklist (engine.py, by test)

  entry fill: next-bar open, no look-ahead (locked by tests, re-verify on
    real data with signal->entry cross-tab);
  TP fill: exact tp_price even on gap-up (conservative, test-locked);
  SL fill: stop price, gap-through at open (conservative, test-locked);
  same-bar TP+SL: SL wins (pessimistic, test-locked); quantified in the
    matrix via p20_before_m10;
  price limits: NOT modeled. Add flag when |ret| within 0.3% of +/-10%
    band and entry would be unfillable at limit (unmodeled slippage);
  halts/suspensions: partially modeled (zero-open rows flagged invalid);
    needs suspension-day count audit;
  illiquidity: NOT modeled; add volume-participation cap check;
  partial fills: N/A at single-order size assumption, document it;
  slippage/spread: no historical spread exists (SO-3); model as bps
    sensitivity parameter, not as data;
  costs: 22.4 bps/side + 15% CGT from the owner schedule (locked);
  corporate actions: print-chain screen flags artifacts; adjustment
    factors still missing (blocking).

HL touch realism verdict: touching high/low is realistic as an event;
the guarantee of a fill at exactly the touch price is optimistic for TP
requires queue position; the model's exact-fill TP is therefore the
pessimistic-conservative choice for TP and the optimistic-assumption
only for SL-within-bar-at-touch, which SL-wins-overrides. Net: model is
conservative overall; residual risk is limit-up/down unfillability.

## 10. Leakage audit checklist

  indicators: rolling windows end at T (verified in smoke_backtest.py
    baseline and required for every feature in section 5);
  membership: point-in-time rebuild (section 8) removes future-listing
    leakage; until then, mark the whole study membership-leaky;
  sector: current-sector features are future-leaky for sector rotations;
    use only with the yearly-snapshot caveat or drop;
  corporate actions: never use adjustment factors dated after T;
  normalization: any z-score/percentile computed on full-sample
    distributions is banned; rolling windows only;
  walk-forward: src/backtest/walkforward.py asserts train-end < test-start;
  ML: none in this stage; when introduced, purged/embargoed CV only.

## 11. Time-based analysis

Daily bars limit honest buckets to: day-of-week (Mon-Thu law differs from
Friday law by construction), session-of-month (first/second half),
month-of-year, and around-holiday sessions. Intraday buckets (first 15
minutes etc.) are IMPOSSIBLE on 5 years of data; only the 10-day snapshot
window could support intraday claims, and it is too short to conclude
anything. The overnight_study.json weekday/month tables are prior art to
reproduce on the 5-year file.

## 12. Regime definitions (exact, causal)

  trend: index proxy 20d return > +5% strong bull; 0..+5% weak bull;
    -5..0% weak bear; < -5% strong bear (computed on the KMIALL
    equal-weight proxy until an index history is fetched);
  volatility: 20d realized vol of proxy, terciles;
  breadth: fraction of universe above own MA20, terciles;
  volume regime: universe total turnover 20d vs trailing 60d, terciles.

## 13. Deliverables after the audit

  A. files to send: point-in-time membership (or authority to rebuild
     from PSX notices), index OHLC history, corporate-action factors
  B. fields: as section 2
  C. analyses to run: trade matrix, single-variable matrix, combinations,
     stop/TP grid, survivorship sensitivity, time/regime cuts
  D. analyses NOT to run yet: volume-profile/AMT on daily bars, intraday
     timing claims, ML, parameter optimization of the placeholder
  E. top 10 experiments, ordered:
     1. build_trade_matrix.py (everything depends on it)
     2. survivorship sensitivity (validity of everything else)
     3. corporate-action factor rebuild (data honesty)
     4. index proxy + regime cuts
     5. relative-strength quintiles
     6. relvol buckets
     7. candle-structure quartiles (body, CLV, wicks)
     8. sweep/BOS daily SMC set
     9. FVG daily set
     10. stop/TP grid on the best-MAE subset vs all entries
  F. known risks: survivorship (confirmed), unadjusted prices (partial
     screen only), no historical spread/limits data, 10-day depth archive,
     current-sector leakage, multiple-testing (handled by pre-registration
     and adjustment)
  G. scripts to write: build_trade_matrix.py, features.py,
     filter_matrix.py, stop_tp_grid.py, survivorship_audit.py,
     regime_cuts.py (each local-only, outputs under data/, gitignored)
