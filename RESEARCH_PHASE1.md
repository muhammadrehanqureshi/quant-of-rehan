# RESEARCH PHASE 1: trade matrix, path analysis, survivorship, filters

Generated: 2026-10-06T14:10:18+05:00 (Karachi, SO-8). LOCAL ONLY (SO-4).
Population: placeholder-baseline entries (close > MA20 and volume > 20d median at T). This is an entry-quality audit, NOT a strategy and NOT an edge claim.
Costs quoted where relevant: 22.4 bps/side + 15% CGT (owner schedule). No filter is ranked by profit anywhere in this report.

## 1. Data quality findings

- dataset: 283,630 rows, 305 symbols, 2021-10-04..2026-10-02, sha256 f539c950
- signals 75,096; skipped (no next bar) 442; matrix rows 74,654 (reconciles with the audit's 74,654)
- data_invalid (engine print-chain screen, band 0.60): 760 (1.02%) excluded from every metric below
- entry gap (next open vs signal close): median +0.26%, p95 +6.99%
- matrix causality and determinism: verified by tests/test_trade_matrix.py (features bit-identical when future rows are removed)

## 2. Trade matrix statistics (all valid trades)

n=73,894 | median MAE(3bar) -3.43% [p25 -6.68, p75 -1.40] | median MFE(3bar) 3.26% [p25 1.06, p75 7.32]
reach: +0.5% 82.8%, +1% 75.9%, +1.5% 69.1%, +2% 62.9% | touch: -0.5% 86.1%, -1% 80.3%, -1.5% 73.7%, -2% 67.2%
+2% before -1%: 48.3% | median ret_close3 -0.50% (mean +0.13%)

## 3. A-G path analysis

| group | n | share | MAE med | MFE med | +2 before -1 | reach +2 | touch -1 | ret3 mean |
|---|---|---|---|---|---|---|---|---|
| ALL | 73,894 | 100.0% | -3.43 | 3.26 | 48.3% | 62.9% | 80.3% | +0.13% |
| A +2 before -1 | 35,710 | 48.3% | -1.92 | 6.38 | 100.0% | 100.0% | 63.0% | +2.81% |
| B -1 before +2 | 36,860 | 49.9% | -4.80 | 1.12 | 0.0% | 29.3% | 100.0% | -2.46% |
| C -1 then +2 | 10,789 | 14.6% | -3.57 | 4.76 | 0.0% | 100.0% | 100.0% | +2.17% |
| D neither in 3 bars | 1,324 | 1.8% | -0.53 | 1.19 | 0.0% | 0.0% | 0.0% | +0.23% |
| E +2 in 1 bar | 30,224 | 40.9% | -2.24 | 6.48 | 100.0% | 100.0% | 68.0% | +2.58% |
| F MAE<=-5 & MFE>=+5 | 6,442 | 8.7% | -8.14 | 8.67 | 70.5% | 100.0% | 100.0% | +0.94% |
| G MAE>=-1 & MFE>=+2 | 13,232 | 17.9% | -0.04 | 8.24 | 100.0% | 100.0% | 0.1% | +6.67% |

Group G exists at meaningful scale: n=13,232 (17.9% of all valid trades); persistence 5,369 vs 7,863 trades across halves. G is DEFINED by its path shape (shallow adverse, +2% reached), so G is a description of geometry, not a filter result; whether features can PREDICT G is exactly what the filter matrix measures.

## 4. SURVIVORSHIP SENSITIVITY ONLY (current-membership universe; does NOT solve point-in-time membership)

- symbols in dataset: 305; complete-5y symbols: 256; dead in trailing ~60 sessions: 1 (0.0% of trades)
- first-print years: {"2021": 259, "2022": 4, "2023": 6, "2024": 11, "2025": 13, "2026": 12}
- last-print years: {"2022": 1, "2026": 304}
- trades from symbols listed after 2021: 6.9%; from symbols younger than 1y at signal: 15.2%

| population | n | MAE med | MFE med | +2 before -1 | reach +2 | touch -1 | ret3 mean |
|---|---|---|---|---|---|---|---|
| A_all_current_305 | 73,894 | -3.43 | 3.26 | 48.3% | 62.9% | 80.3% | +0.13% |
| B_complete_5y_symbols | 68,393 | -3.43 | 3.26 | 48.4% | 62.9% | 80.2% | +0.15% |
| C_listing_truncated_1y | 62,696 | -3.51 | 3.39 | 48.8% | 63.7% | 80.9% | +0.23% |

The dataset covers TODAY'S KMIALL members only. Symbols that left the index before 2026 are absent no matter when they traded, and today's members carry their pre-index history. Populations B and C test sensitivity to listing/exit effects inside that fixed universe; they CANNOT reconstruct point-in-time membership and CANNOT remove survivorship from the universe selection itself.

## 5. Single-variable filter matrix (frozen buckets, no tuning)

Minimum n = 500 per side. MAE lift = median MAE(sub) - median MAE(complement) in percentage points; positive lift means the subset's adverse excursion is shallower. Bootstrap: 1000 resamples, seed 20261006. Bonferroni across 34 tests. Ranking: MAE compression, MFE preservation, +2% reach, +2-before--1, persistence, significance. Profit is NOT a ranking criterion.

| rank | filter | n sub | comp | MAE lift pp [CI] | MAE lift SC pp [CI] | ref-consistent | MFE lift pp | +2 reach | +2 before -1 | p adj | persist |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ret_20d 0..+5% | 16,726 | 57,168 | +1.14 [+1.07, +1.21] | +0.99 [+0.93, +1.06] | yes | -0.89 (SC -1.18) | 57.4% | 43.3% | 0.000 | yes |
| 2 | gap_next_open > +0.5% (gap up entry) | 31,694 | 42,200 | -2.06 [-2.13, -1.98] | +0.99 [+0.93, +1.06] | NO | -0.67 (SC +3.10) | 57.8% | 40.1% | 0.000 | yes |
| 3 | gap_next_open 0 to +0.5% | 17,437 | 56,457 | +0.92 [+0.85, +0.98] | +0.97 [+0.90, +1.02] | yes | -0.77 (SC -1.16) | 58.4% | 44.0% | 0.000 | yes |
| 4 | clv_position < 0.33 (discount) | 894 | 73,000 | +0.72 [+0.44, +0.94] | +0.89 [+0.64, +1.01] | yes | -0.67 (SC -0.73) | 57.0% | 40.3% | 0.000 | yes |
| 5 | relvol 1.0-1.5 | 19,255 | 54,639 | +0.78 [+0.71, +0.86] | +0.64 [+0.58, +0.71] | yes | -0.58 (SC -0.89) | 60.2% | 45.3% | 0.000 | yes |
| 6 | equal_lows TRUE | 1,041 | 72,853 | +0.87 [+0.64, +1.10] | +0.56 [+0.27, +0.78] | yes | -0.81 (SC -0.92) | 56.1% | 43.2% | 0.000 | yes |
| 7 | ret_20d -5%..0 | 8,896 | 64,998 | +0.69 [+0.60, +0.78] | +0.53 [+0.44, +0.62] | yes | -0.65 (SC -0.86) | 58.3% | 44.7% | 0.000 | yes |
| 8 | relvol 1.5-2.5 | 18,220 | 55,674 | +0.49 [+0.41, +0.56] | +0.45 [+0.38, +0.52] | yes | -0.28 (SC -0.45) | 61.4% | 46.6% | 0.000 | yes |
| 9 | fvg_age1 small gap < 1% | 4,504 | 69,390 | +0.52 [+0.40, +0.60] | +0.42 [+0.31, +0.52] | yes | -0.41 (SC -0.60) | 59.9% | 46.1% | 0.000 | yes |
| 10 | clv_position 0.33-0.67 | 25,386 | 48,508 | +0.38 [+0.32, +0.46] | +0.34 [+0.28, +0.42] | yes | -0.45 (SC -0.53) | 60.8% | 46.0% | 0.000 | yes |
| 11 | regime_bull (proxy ret20 >= 0) | 44,787 | 29,107 | +0.14 [+0.07, +0.21] | +0.32 [+0.27, +0.40] | yes | +0.27 (SC +0.43) | 64.0% | 49.0% | 0.000 | yes |
| 12 | sweep_high TRUE | 12,209 | 61,685 | +0.34 [+0.27, +0.43] | +0.27 [+0.18, +0.35] | yes | -0.28 (SC -0.34) | 61.8% | 47.0% | 0.000 | yes |
| 13 | regime_strong_bull (ret20 > +5%) | 23,368 | 50,526 | +0.26 [+0.18, +0.33] | +0.25 [+0.19, +0.32] | yes | +0.06 (SC -0.00) | 63.9% | 49.4% | 0.000 | no |
| 14 | body_ratio 0.3-0.6 | 22,150 | 51,744 | +0.20 [+0.14, +0.28] | +0.24 [+0.16, +0.30] | yes | -0.26 (SC -0.38) | 61.9% | 47.0% | 0.000 | yes |
| 15 | vol_accel 0.8-1.2 | 10,498 | 63,396 | +0.11 [+0.02, +0.19] | +0.19 [+0.09, +0.27] | yes | -0.17 (SC -0.17) | 61.9% | 46.6% | 0.748 | yes |
| 16 | body_ratio < 0.3 (small body) | 22,977 | 50,917 | +0.22 [+0.15, +0.29] | +0.19 [+0.12, +0.26] | yes | -0.31 (SC -0.45) | 61.5% | 46.3% | 0.000 | yes |
| 17 | vol_accel > 1.2 | 43,215 | 30,679 | -0.04 [-0.10, +0.03] | -0.01 [-0.08, +0.07] | yes | +0.01 (SC +0.15) | 62.9% | 48.9% | 1.000 | yes |
| 18 | vol_accel < 0.8 | 20,181 | 53,713 | -0.03 [-0.10, +0.05] | -0.12 [-0.20, -0.03] | yes | +0.10 (SC -0.08) | 63.6% | 48.0% | 1.000 | no |
| 19 | Friday signals | 14,180 | 59,714 | -0.06 [-0.15, +0.02] | -0.23 [-0.32, -0.13] | yes | -0.04 (SC -0.20) | 62.3% | 48.8% | 1.000 | no |
| 20 | sweep_low TRUE | 10,728 | 63,166 | -0.07 [-0.17, +0.01] | -0.24 [-0.34, -0.16] | yes | +0.12 (SC +0.12) | 63.4% | 48.4% | 1.000 | no |
| 21 | regime_bear (ret20 < 0) | 29,043 | 44,851 | -0.15 [-0.21, -0.07] | -0.33 [-0.41, -0.27] | yes | -0.27 (SC -0.43) | 61.3% | 47.3% | 0.000 | yes |
| 22 | bos_up TRUE | 22,053 | 51,841 | -0.78 [-0.87, -0.71] | -0.35 [-0.42, -0.27] | yes | +0.77 (SC +1.41) | 66.3% | 51.4% | 0.000 | yes |
| 23 | body_ratio > 0.6 (large body) | 26,929 | 46,965 | -0.40 [-0.46, -0.33] | -0.37 [-0.43, -0.30] | yes | +0.42 (SC +0.64) | 64.8% | 50.9% | 0.000 | yes |
| 24 | displacement TRUE | 17,519 | 56,375 | -0.59 [-0.69, -0.51] | -0.40 [-0.46, -0.31] | yes | +0.67 (SC +1.11) | 66.5% | 53.8% | 0.000 | yes |
| 25 | clv_position > 0.67 (premium) | 47,514 | 26,380 | -0.42 [-0.50, -0.36] | -0.40 [-0.47, -0.34] | yes | +0.49 (SC +0.57) | 64.2% | 49.7% | 0.000 | yes |
| 26 | ret_20d < -5% | 3,185 | 70,709 | -0.41 [-0.55, -0.25] | -0.54 [-0.72, -0.42] | yes | +0.00 (SC +0.00) | 61.7% | 47.9% | 0.000 | yes |
| 27 | 20d high break TRUE | 11,980 | 61,914 | -1.41 [-1.53, -1.28] | -0.57 [-0.68, -0.46] | yes | +1.17 (SC +2.45) | 68.7% | 53.9% | 0.000 | yes |
| 28 | fvg_retrace TRUE (age-1 bull FVG, retested) | 4,440 | 69,454 | -0.15 [-0.36, -0.01] | -0.71 [-0.86, -0.54] | yes | +0.16 (SC -0.29) | 63.3% | 50.1% | 1.000 | yes |
| 29 | relvol > 2.5 | 36,419 | 37,475 | -1.04 [-1.11, -0.98] | -0.86 [-0.93, -0.80] | yes | +0.69 (SC +1.09) | 65.1% | 50.8% | 0.000 | yes |
| 30 | fvg_age1 big gap >= 1% | 13,786 | 60,108 | -0.90 [-1.01, -0.79] | -0.96 [-1.06, -0.85] | yes | +0.94 (SC +1.05) | 67.1% | 52.5% | 0.000 | yes |
| 31 | ret_20d > +5% | 44,987 | 28,907 | -1.20 [-1.25, -1.12] | -0.97 [-1.03, -0.89] | yes | +0.99 (SC +1.33) | 66.0% | 51.0% | 0.000 | yes |
| 32 | gap_next_open < 0 (gap down entry) | 24,763 | 49,131 | +1.40 [+1.33, +1.46] | -1.95 [-2.03, -1.87] | NO | +1.39 (SC -2.26) | 72.7% | 61.9% | 0.000 | yes |

Rejected for n < 500: relvol < 0.7 (n=0); relvol 0.7-1.0 (n=0)

## 6. Headline reading (honest)

MAE lift is quoted twice: entry-referenced (the engine's convention) and signal-close-referenced (SC), which removes the mechanical entry-price scaling. Ranks follow the SC view after the gap-down artifact investigation (documented deviation).

- strongest genuine MAE compressor: ret_20d 0..+5% (SC lift +0.99 pp CI [0.9325, 1.0581], p_adj 0.000, persistence match)
- strongest MFE preserver (SC view): gap_next_open > +0.5% (gap up entry) (+3.10 pp median MFE lift, CI [3.0231, 3.1956])
- filters with SC lift near zero and p_adj >= 0.5 (useless here): vol_accel > 1.2
- entry-price artifacts (big entry-referenced lift that vanishes or flips in the SC view): gap_next_open > +0.5% (gap up entry); gap_next_open < 0 (gap down entry)

## 7. Suspicious results and potential leakage

- All MAE/MFE path metrics come from the SAME daily bars used to define the features; nothing here is out-of-sample.
- Group F (MAE<=-5 & MFE>=+5) is dominated by unadjusted corporate-action artifacts; it is reported for completeness and must never be read as an opportunity set.
- The equal-weight KMIALL proxy is not the KSE-100 or the Meezan index; regime buckets inherit that substitution.
- Universe membership is today's KMIALL list: every filter result is membership-leaky until point-in-time membership exists.
- 34 frozen buckets were tested: expect false positives at the 5% level even after Bonferroni when effects are weak; persistence is the tiebreaker.
- INVESTIGATED AND EXPLAINED: the apparent top filter 'gap_next_open < 0' entry-referenced lift (+1.40 pp) is an entry-price arithmetic artifact; referenced to the signal close the same bucket's path is WORSE than the complement (median MAE -4.63% vs -2.73%). Filters that lower the entry price mechanically shrink entry-referenced MAE. Ranking therefore uses the signal-close view (documented pre-registration deviation).
- relvol <1.0 buckets have n=0 BY CONSTRUCTION: the baseline population requires volume > 20d median, so relvol < 1 cannot occur in it. These buckets are only meaningful on non-baseline (full-market) populations.

## 8. What still cannot be concluded

- No edge claim is possible: this phase measures geometry and stability, not net profitability after the owner's cost schedule (the stop/TP grid is deliberately not run yet).
- No intraday conclusion is possible: 3-bar daily paths only.
- No bid/ask, depth or footprint conclusion: none exists (SO-3).
- Point-in-time membership cannot be reconstructed from this dataset.
- Corporate-action artifacts are screened, not corrected; adjustment factors are still missing.

## 9. Recommendation for Phase 2

- If the owner approves: run the stop/TP grid ONLY on populations the filter matrix marks as MAE-compressing AND persistent, versus all entries as control, reporting the surface difference (section 7 of the audit).
- Acquire the three missing datasets (specs in the JSON); membership and corporate-action factors are blocking for any strategy conclusion.
- Keep the live signal engine running but UNGRADED: signals are observations, not recommendations, until Phase 2 lands.

## 10. Acquisition specifications for the three missing datasets

### A_point_in_time_kmiall_membership
- purpose: remove survivorship from universe selection (audit section 8)
- required fields: rebalance_notice_date, effective_date, symbol, action (add|remove), index_name (KMIALLSHR), source_document_ref
- date range: 2021-09-01 through today (covering the dataset plus lead time)
- acceptable sources: PSX index review notices (KSE Meezan reconstitution announcements); Meezan Bank index factsheets/reconstitution letters; annual PSX '5 Years Progress Report' membership tables (yearly fallback)
- expected format: CSV/JSON, one row per (effective_date, symbol, action)
- validation tests:
  - every add has a matching effective_date within session calendar
  - no duplicate (date, symbol, action)
  - membership at any date = adds minus removes, monotone
  - cross-check 3 random dates against archived KMIALL lists

### B_index_ohlc_5y
- purpose: real regime/breadth basis (KSE-100, KMI30) instead of the equal-weight proxy
- required fields: date, symbol (KSE100 | KMI30), open, high, low, close, volume
- date range: 2021-10-01 through today
- acceptable sources: PSX Data Portal index pages (manual/API); PSX Daily Downloads mkt_summary index rows if present; commercial vendor (last resort, owner cost decision)
- expected format: CSV long format, one row per (date, index)
- validation tests:
  - sessions match the KMIALL dataset session-for-session (missing days listed)
  - close continuity: no |day move| > 7% without a matching market event
  - OHLC sanity: low <= min(open, close) <= max(open, close) <= high

### C_corporate_action_factors_5y
- purpose: adjusted prices for honest multi-year paths (audit section 9)
- required fields: symbol, ex_date, action (split|bonus|right|dividend), ratio_or_amount, adjustment_factor
- date range: 2021-10-01 through today, all KMIALL symbols
- acceptable sources: PSX company notices (announcements feed); data/legacy_sentinel/data/corporate_actions.json as a seed (partial, recent-biased); paid vendor backfill (owner cost decision)
- expected format: CSV, one row per (symbol, ex_date, action)
- validation tests:
  - every symbol-day print jump > circuit band in the raw data maps to an action row (completeness)
  - no action rows dated after T are used for features at T (causality)
  - adjusted close chains have no remaining > band jumps

## Appendix: provenance

- python 3.13.15, pandas 3.0.5
- matrix provenance: {"generated_at_karachi": "2026-10-06T13:27:45.248740+05:00", "dataset": {"path": "eod_history_kmi.csv.gz", "sha256": "f539c950e840a6a8579749ed3afa9717a2307ee20d9277b264a3ab8129851dab", "rows": 283630, "symbols": 305, "start": "2021-10-04", "end": "2026-10-02"}, "population_rule": "close>MA20 and vol
- seeds: bootstrap 20261006; no other randomness
