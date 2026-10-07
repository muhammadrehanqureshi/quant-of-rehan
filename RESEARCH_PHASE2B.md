# RESEARCH PHASE 2B: does rs20 < -5% improve the TP/SL objective?

Generated: 2026-10-07T12:00:41.185810+05:00 (Karachi, SO-8). LOCAL ONLY (SO-4).

Constraints honored: NO live-trading changes, NO TP/SL optimization, NO
machine learning, NO future information, NO fabricated data (footprint
UNAVAILABLE; daily OHLC only). Phase 2A artifacts untouched.

## 1. Research question

When rs20 < -5% occurs, does it improve the probability that a KMIALL stock reaches +2% TP before -1% SL after a realistic next-open entry?

The law is pre-specified: TP +2.0% / SL -1.0% / max hold 3 sessions.
Nothing here may be tuned toward profitability; the answer is measured,
not optimized.

## 2. Dataset

- trade matrix: trade_matrix.parquet, 75,767 rows (74,985 valid after the engine print-chain screen)
- dataset sha256 55fd6d211569620b7a9f815052e15823969d7568d2d1e645c01c4acb5bf6648e
- population: the Phase 1/2A placeholder baseline (close > MA20 and
  volume > 20d rolling median at T), the same frozen signal frame;
- universe membership remains TODAY'S KMIALL list (survivorship-
  biased); point-in-time membership cannot be reconstructed (Phase 1
  limitation, unchanged).

## 3. Intraday data resolution

- DAILY BARS ONLY 2021-10-04..2026-10-05; banked 1-minute data exists only from 2026-10-06 (forward capture); no historical intraday ordering is assumed
- consequence: ALL labels below are daily-bar labels with the
  conservative same-bar rule (section 6); a large share of legal
  label space cannot establish intrabar order and is reported per
  population as the ambiguity band (JSON 'ambiguity_band').

## 4. Entry definition

- signal decided at close T; executable entry = NEXT SESSION OPEN.
- no evaluation ever uses a price known after the signal close;
- gap_next_open is an artifact control, never information.

## 5. TP/SL definitions

- TP +2.0%: limit order, fills exactly at the target, never
  better on a gap-up (engine law).
- SL -1.0%: stop; fills at the stop, or at the open when the
  bar gapped through it (worse fill, engine law).
- max hold 3 sessions; timeout exit at the last held close.
- alternative TP/SL values are NOT explored: the exploratory surface
  already exists banked at data/stop_tp_grid/ (2026-10-06) and is
  only quoted in section 16.

## 6. Label construction

- per signal: entry, MAE/MFE (entry-referenced %), first-touch bars
  t_tp_first / t_sl_first (0 = never reached);
- labels: TP_FIRST / SL_FIRST / NEITHER, plus the diagnostic bucket
  TP_FIRST_AMBIG for bars that touch BOTH levels; the SAME-BAR RULE
  resolves such bars SL-first (conservative, documented); ambiguous
  rows are NEVER counted as TP-first;
- dual reference: the same thresholds on signal-close-referenced
  paths form the SC view; a rule must agree in BOTH references to be
  called stable (Phase 2A turnover_low lesson).

## 7. Leakage controls

- every non-obvious threshold is a discovery-split quantile, frozen
  and printed before validation/OOS scoring (JSON frozen_constants);
- rankability needs n >= 500 in every split on both sides;
- Bonferroni across 24 ledger tests;
- bootstrap 1,000 resamples, seed 20261006, two-sided;
- OOS scored once, after every choice was frozen;
- features were built causally by build_trade_matrix.py (row-
  truncation tests in tests/test_trade_matrix.py); Phase 2B adds NO
  new feature computed from bars after T.

## 8-11. Baselines and split results (A: ALL, B: rs20<-5, C: rs20>=-5)

Baseline A is the whole population, so it has no complement: its row
reports the raw TP-first rate only (lift columns None by design).

| spec | split | n sub | n comp | TP-first sub | TP-first comp | lift pp [CI95] | SC lift |
|---|---|---|---|---|---|---|---|
| ALL valid (baseline A) | discovery | 24,831 | 0 | 0.3132 | None | None [None, None] | None |
| ALL valid (baseline A) | validation | 24,838 | 0 | 0.2629 | None | None [None, None] | None |
| ALL valid (baseline A) | oos | 25,316 | 0 | 0.2314 | None | None [None, None] | None |
| rs20 < -5% (baseline B) | discovery | 2,841 | 21,990 | 0.3548 | 0.3078 | 4.7028 [2.8346, 6.5438] | 6.5476 |
| rs20 < -5% (baseline B) | validation | 4,303 | 20,535 | 0.284 | 0.2585 | 2.5454 [1.1295, 3.9901] | 0.2748 |
| rs20 < -5% (baseline B) | oos | 5,026 | 20,290 | 0.2583 | 0.2247 | 3.3565 [1.9068, 4.7096] | 2.1425 |
| rs20 >= -5% (baseline C) | discovery | 21,896 | 2,935 | 0.3081 | 0.3509 | -4.2844 [-5.9409, -2.2343] | -6.305 |
| rs20 >= -5% (baseline C) | validation | 20,530 | 4,308 | 0.2586 | 0.2837 | -2.5061 [-4.0214, -1.0715] | -0.2767 |
| rs20 >= -5% (baseline C) | oos | 20,285 | 5,031 | 0.2246 | 0.2584 | -3.3749 [-4.6966, -2.0094] | -2.1682 |

Discovery-specific notes: the base rates drift downward across time
(G-rate 22.0% -> 17.2% -> 14.8% in Phase 2A; TP-first shows the same
drift), so lifts, not raw rates, carry the comparison.

## 12. rs20 < -5% analysis (the candidate)

- entry-view lift: discovery 4.7028 pp, validation 2.5454 pp, OOS 3.3565 pp
- SC-view lifts: [6.5476, 0.2748, 2.1425]
- stable in both references: True; n-ok: True
- sub-buckets (D-family) and regime interactions (E-family) are in
  the ledger table below; the deepest rs20 tail (discovery q10), the
  liquidity halves and the penny band are reported, not hidden.

## 13. Market regime analysis

| regime | split | n_regime | n rs20<-5 | rs TP-first | comp TP-first | lift pp |
|---|---|---|---|---|---|---|
| strong_bull | discovery | 12,335 | 1,588 | 0.3634 | 0.3178 | 4.555 |
| strong_bull | validation | 7,319 | 1,577 | 0.293 | 0.2533 | 3.9695 |
| strong_bull | oos | 4,829 | 1,418 | 0.2581 | 0.2237 | 3.4422 |
| weak_bull | discovery | 1,377 | 206 | 0.4078 | 0.3322 | 7.5572 |
| weak_bull | validation | 7,317 | 1,459 | 0.2879 | 0.2466 | 4.1242 |
| weak_bull | oos | 12,632 | 2,921 | 0.2561 | 0.2324 | 2.3636 |
| weak_bear | discovery | 1,442 | 147 | 0.3741 | 0.2988 | 7.5308 |
| weak_bear | validation | 6,792 | 1,002 | 0.2804 | 0.2575 | 2.2926 |
| weak_bear | oos | 6,416 | 607 | 0.2702 | 0.2134 | 5.6818 |
| strong_bear | discovery | 9,612 | 900 | 0.3244 | 0.2943 | 3.0192 |
| strong_bear | validation | 3,410 | 265 | 0.2226 | 0.2926 | -6.9979 |
| strong_bear | oos | 1,439 | 80 | 0.25 | 0.2196 | 3.0398 |

## 14. Liquidity and one-winner analysis

Discovery-frozen turnover quartiles split the rs20<-5% population
(D-family rows in the ledger). Relative-volume and market-turnover
context live in the matrix columns (feat_relvol, feat_mkt_turn_ratio)
and are reported in the JSON; no arbitrary liquidity threshold is
imposed.

One-winner day layer (picks after the day's data on the research
tape; TP-first share among picked rows is a SELECTION-QUALITY
metric, never a live-day-rate claim; realized-MFE ranking is
informational only and NOT deployable):

- PRIMARY (turnover desc, rs20 asc (engineered liquidity-first)): discovery 0.22346368715083798, validation 0.226775956284153, oos 0.21518987341772153
- EXPLORATORY (rs20 depth only): discovery 0.33147113594040967, validation 0.28688524590163933, oos 0.24050632911392406
- EXPLORATORY (turnover only): discovery 0.22346368715083798, validation 0.226775956284153, oos 0.21518987341772153
- EXPLORATORY (realized MFE (informational, NOT deployable)): discovery 0.7616387337057728, validation 0.6502732240437158, oos 0.5063291139240507
- EXPLORATORY (turnover within rs20<-5): discovery 0.28846153846153844, validation 0.2621951219512195, oos 0.2246376811594203

Read: the liquidity-first default selects near-population-quality
picks; the rs20-depth-first order selects better TP-first shares
(exploratory evidence only, to be re-frozen on a FRESH discovery
window before any live use, never on this one).

## 15. Market veto research (pre-defined rule, never hardcoded)

| split | vetoed n | vetoed TP-first | passing n | passing TP-first |
|---|---|---|---|---|
| discovery | 4,977 | 0.3108 | 19,854 | 0.3137 |
| validation | 3,400 | 0.29 | 21,438 | 0.2587 |
| oos | 4,633 | 0.204 | 20,683 | 0.2375 |

Interpretation: a USEFUL veto has materially lower TP-first inside the
vetoed band in every split with acceptable veto cost (count of good
days vetoed in OOS, JSON). The rule is a RECOMMENDATION for the owner;
nothing in the live engine changes without owner approval.

## 16. Cost / slippage analysis

| population | n | gross mean % | net@0bps | net@5bps | net@10bps |
|---|---|---|---|---|---|
| ALL | 74,985 | -0.1699 | -0.6812 | -0.7771 | -0.873 |
| rs20<-5 | 12,170 | -0.1063 | -0.6225 | -0.7181 | -0.8136 |
| rs20<-5 x turnover>=discovery q75 | 2,922 | -0.2061 | -0.7143 | -0.8104 | -0.9064 |

Engine schedule: 22.4 bps/side + 15% CGT on winners; slippage added
per side at 0/5/10 bps. Reference (banked grid, ALL population, law
cell): net -1.056%/trade at 0 bps slip - selection must lift TP-first
far beyond the rs20 effect to clear costs. No profitability claim is
made; the law-geometry economics remain negative on these labels.

## 17. TP-first statistics

Every sub/comp table above and every 'sub'/'comp' block in the JSON
ledger (tp_first). The diagnostic ambiguity bucket is separate and
never counted as TP-first.

## 18. SL-first statistics

headline_block.sl_first merges pure-SL with the same-bar ambiguous
bucket (the conservative losing view); the pure-SL count is
recoverable as sl_first minus ambiguous_same_bar.

## 19. Neither-hit statistics

headline_block.neither in the JSON (max-hold timeout, no level hit).

## 20. Time-to-target analysis

median_t_tp / median_t_sl (bars 1..3, 0 = never) in every headline
block of the JSON ledger.

## 21. MAE/MFE analysis

mae_median / mfe_median (entry-referenced %) in every headline block
of the JSON ledger; ambiguous rows keep their full-range extremes.

## 22. Candidate rule comparisons (full ledger)

| family | spec | D lift | V lift | OOS lift | SC D/V/OOS | stable+ | n-ok |
|---|---|---|---|---|---|---|---|
| BASE | ALL valid (baseline A) | None | None | None | None/None/None | False | True |
| BASE | rs20 < -5% (baseline B) | 4.7028 | 2.5454 | 3.3565 | 6.5476/0.2748/2.1425 | True | True |
| BASE | rs20 >= -5% (baseline C) | -4.2844 | -2.5061 | -3.3749 | -6.305/-0.2767/-2.1682 | False | True |
| D | rs20<-5% x turnover >= discovery q75 | -1.6842 | -1.9169 | 2.1436 | 7.5602/6.1006/8.6909 | False | True |
| D | rs20<-5% x turnover <= discovery q25 | 9.4854 | 8.2286 | 7.7698 | 1.5001/-3.4213/-8.1336 | False | True |
| D | rs20<-5% x price >= 20 PKR | 5.7596 | 2.5905 | 3.608 | 8.412/1.8426/2.3837 | True | True |
| D | rs20<-5% x price 5..20 PKR | 2.5371 | 1.7881 | 1.3427 | 4.3734/-2.274/0.3599 | False | True |
| D | rs20<-5% x price < 5 PKR (penny band) | 0.325 | 1.9228 | 6.2804 | -7.2301/-7.0095/17.2855 | False | False |
| D | rs20<-5% x gap-down entry (<0%) | 16.8632 | 22.4255 | 20.8866 | -12.5161/-12.7/-11.7954 | False | True |
| D | rs20<-5% x gap-up entry (>+0.5%) | -7.756 | -11.9019 | -10.1406 | 21.5066/9.3419/10.8403 | False | True |
| D | rs20<-5% x rs20 depth <= discovery q10 (deepest) | 9.85 | 1.1918 | 4.7503 | 7.6942/-0.0564/2.168 | False | False |
| D | rs20<-5% x NO jump bars 1-3 | 4.2269 | -0.8368 | 0.8703 | 7.9524/-0.4614/0.7642 | False | True |
| E | rs20<-5% x regime weak_bull | 9.5402 | 2.648 | 2.7945 | 10.7456/0.7302/4.1653 | True | False |
| E | rs20<-5% x regime strong_bull | 5.3622 | 3.2053 | 2.8342 | 7.6517/-0.7994/-2.43 | False | True |
| E | rs20<-5% x regime weak_bear | 6.1356 | 1.8231 | 3.9779 | 6.0592/2.6613/1.6233 | True | False |
| E | rs20<-5% x regime strong_bear | 1.1712 | -4.0737 | 1.8703 | 2.3277/-5.3535/1.9861 | False | False |
| E | rs20<-5% x breadth >= discovery q66 (broad strength) | 5.5222 | 2.3365 | 3.8934 | 9.7165/2.8222/4.5645 | True | True |
| E | rs20<-5% x breadth <= discovery q35 (weak tape) | 4.3656 | 0.6596 | -1.6068 | -3.7917/-4.046/-1.8892 | False | False |
| VETO | ALL x breadth <= discovery q20 (deep-selloff band) | -0.291 | 3.1347 | -3.3518 | -3.4518/-0.2771/-6.3374 | False | True |
| VETO | ALL x breadth <= discovery q10 (extreme band) | -1.0648 | 1.5075 | -2.685 | -5.8894/-0.296/-5.9632 | False | True |
| VETO | ALL x regime strong_bear | -2.6152 | 2.7997 | -1.0257 | -2.4941/-1.699/-6.7279 | False | True |
| SMC | rs20<-5% x sweep_low TRUE | 1.8402 | 3.8083 | 2.5742 | 0.8662/1.9681/0.3892 | True | False |
| SMC | rs20<-5% x fvg_retrace TRUE | 4.2786 | 5.8454 | 5.5496 | 3.4972/-0.1722/5.0268 | False | False |
| SMC | rs20<-5% x bos_up TRUE | 8.9256 | 1.9753 | 2.9291 | 12.7337/-1.2866/3.5353 | False | False |

No spec other than the rs20 candidate is promoted; SMC/FVG checks
inside the rs20 population are exploratory and reported as such.
VETO-family rows are expected to show NEGATIVE lifts when the veto
screens genuinely bad tape; read sign accordingly.

## 23. Multiple-testing controls

- Bonferroni over 24 tests (JSON
  'tp_first_p_bonferroni' per spec/split);
- thresholds frozen on discovery before any later split was scored;
- the ledger is complete: no untested variant was tried and dropped;
- per-family bootstrap seeds are fixed offsets from the 2A seed,
  deterministic across runs.

## 24. Robustness checks

- top-3-symbol exclusion and artifact-row exclusion (single-bar
  >= +/-9.9% moves) per population, JSON 'robustness';
- alternative one-winner ranking orders are LABELED EXPLORATORY in
  JSON 'one_winner.exploratory_rank' and are not frozen defaults;
- ambiguity-band sensitivity per population and split;
- SC-reference agreement for every spec (Phase 2A lesson applied).

## 25. Recommendation

Pre-defined gate outcome: B (rubric frozen before the run;
checks in the JSON 'gate' block). The honest reading of the evidence:
rs20<-5% is direction-stable for TP-first but SMALL in magnitude, and
the law-geometry economics after real costs stay deeply negative, so
live promotion is NOT justified by this phase alone.

## 26. Exact production-readiness status

- live engine: UNCHANGED, still UNGRADED, NO TRADE default intact;
- Phase 2B wires NOTHING into production; the owner must approve any
  rule promotion separately;
- the research artifacts of Phase 2A are untouched;
- remaining before any paper-trading promotion: owner-approved market
  veto rule, a liquidity floor justified by separate research, and a
  forward-capture growth of the 1-minute archive to re-label with
  true intrabar ordering when weeks of sessions exist.

## Appendix: provenance

- python 3.13.15, pandas 3.0.5; one-shot local run
- bootstrap seed 20261006; zero resident processes after exit

