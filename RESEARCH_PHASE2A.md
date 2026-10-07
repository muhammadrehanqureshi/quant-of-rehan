# RESEARCH PHASE 2A: can Group G be identified prospectively?

Generated: 2026-10-07T09:51:07+05:00 (Karachi, SO-8). LOCAL ONLY (SO-4).

Scope and constraints honored: NO live trading, NO production threshold changes, NO TP/SL optimization, NO machine learning, NO future information. The live v1 stack and every production file are untouched by this study. Daily OHLCV only: no bid/ask, depth, order-flow or footprint data exists in this project (registry: footprint UNAVAILABLE) and none is implied.

## 1. Data and rebuild reconciliation

- dataset: 287,962 rows, 320 symbols, 2021-10-04..2026-10-05, sha256 55fd6d21
- signals 76,222; skipped (no next bar / missing symbol / bad entry) 455; matrix rows 75,767 x 76 cols (reconciles: signals minus skipped)
- data_invalid (engine print-chain screen, band 0.60): 782 (1.03%) excluded from every metric below
- matrix provenance: close>MA20 and volume>20d rolling median at T (placeholder baseline, NOT a strategy); built 2026-10-07T08:48:03.720851+05:00
- the matrix was rebuilt for this phase on the updated dataset (adds the 2026-10-05 session and the Phase 2A feature columns; the Phase 1 build ended 2026-10-02)

## 2. Protocol (frozen before any validation/OOS scoring)

- discovery: 2021-10-04 .. 2023-12-31
- validation: 2024-01-01 .. 2025-06-30
- untouched OOS: 2025-07-01 .. 2026-10-05
- Group G (target): mae_3bar >= -1.0% AND mfe_3bar >= +2.0% (entry-referenced, Phase 1 definition). G_sc robustness target: the same thresholds on signal-close-referenced paths.
- thresholds: fixed a priori where natural; quantile cuts frozen on DISCOVERY rows only: breadth q33/q66 = 0.4774/0.7282, rvol20 q33/q66 = 0.0077/0.0122, turnover q33/q66 = 1.751e+06/2.569e+07
- ranking on discovery only: entry-referenced G-rate lift (pp; the owner's G definition), then SC-referenced G-rate lift, MAE-SC lift, MFE-SC lift, +2% reach, n. n >= 500 both sides to be rankable. A strong candidate must hold the lift in BOTH path references. The three gap filters are entry-reference-coupled artifact controls (the gap shifts the reference itself; entry view favors gap-down, SC view favors gap-up) and are excluded from ranking.
- bootstrap: 1000 resamples, seed 20261006; Bonferroni across 54 tests (all filters + combinations).
- disclosure: Phase 1 already glanced at full-sample SC lifts. Mitigation: every choice in this phase uses the discovery split only; validation and OOS are scored once with frozen cuts.

## 3. Group G baseline and composition

Full valid sample: n=74,985; G n=13,484 (G rate 18.0%); median MAE -3.43% [p25 -6.69, p75 -1.39]; median MFE 3.24% [p25 1.05, p75 7.31].
Reach: +0.5% 82.7%, +1% 75.8%, +1.5% 69.0%, +2% 62.8%; touch: -0.5% 86.0%, -1% 80.2%, -1.5% 73.5%, -2% 67.1%; +2% before -1%: 48.2%; median t_to_p10 1.0 bars, t_to_p20 1.0 bars.

Note the base-rate drift: G rate falls from 22.0% (discovery) to 14.8% (OOS). Every candidate lift must be read against this drifting base, which is why lifts (sub minus complement), not raw rates, are compared across splits.

| split | n | G rate | G n | G median MAE | G median MFE | G +2 before -1 | G ret3 median |
|---|---|---|---|---|---|---|---|
| discovery | 24,831 | 22.0% | 5,458 | -0.02 | 7.19 | 0.9996 | 3.93 |
| validation | 24,838 | 17.2% | 4,268 | -0.01 | 9.47 | 0.9998 | 4.95 |
| oos | 25,316 | 14.8% | 3,758 | -0.09 | 8.86 | 0.9997 | 4.39 |

G spans 304 symbols; top-10 share 7.2%. G_sc overlap: 8,309 of G also G_sc (Jaccard 0.420).

| feature incidence | in G | in complement | lift pp |
|---|---|---|---|
| sweep_low | 14.7% | 14.5% | +0.2 |
| fvg_retrace | 6.2% | 6.0% | +0.3 |
| bos_up | 29.0% | 30.1% | -1.1 |
| displacement | 23.8% | 23.6% | +0.2 |
| equal_lows | 1.6% | 1.4% | +0.3 |
| range_expansion | 36.2% | 41.9% | -5.7 |
| 20d_high_break | 15.3% | 16.5% | -1.1 |
| pullback_resume | 4.1% | 4.6% | -0.5 |
| clv<0.33 | 1.1% | 1.2% | -0.1 |
| clv>=0.67 | 65.9% | 64.2% | +1.7 |
| rs20>0 | 60.4% | 64.6% | -4.1 |
| rs5>0 | 67.6% | 71.5% | -3.9 |
| relvol>2.5 | 45.7% | 49.7% | -4.0 |

Artifact-related incidence inside G:

- single-bar moves >= +9.9%: G 23.5% vs comp 16.0%; <= -9.9%: G 6.5% vs comp 14.3%
- MFE >= +25%: G 4.7% vs comp 1.0%; MFE >= +50%: G 0.1% vs comp 0.0%
- gap-down share: G 50.3% vs comp 29.9% (median gap -0.011% vs +0.377%)
- price level: median close 54.70 PKR in G vs 47.61 PKR in comp; share below 20 PKR 25.8% vs 28.1%

| year | n | G rate | G median MAE | G median MFE |
|---|---|---|---|---|
| 2021 | 1,458 | 19.8% | -0.09 | 6.53 |
| 2022 | 9,719 | 20.2% | -0.03 | 6.78 |
| 2023 | 13,654 | 23.5% | -0.01 | 7.48 |
| 2024 | 16,494 | 17.8% | -0.01 | 9.24 |
| 2025 | 19,511 | 15.8% | -0.07 | 9.26 |
| 2026 | 14,149 | 14.1% | -0.04 | 9.04 |

Halves: 2021-23: n=24,831, G rate 22.0%; 2024-26: n=50,154, G rate 16.0%

Individual G examples (deterministic pick: 5 highest-MFE and 5 closest to the median MFE; full rows in the JSON):

| symbol | signal date | close | gap % | MAE | MFE | jump up | jump dn | regime | c1 | c2 | c3 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DFSM | 2022-12-06 | 2.56 | +5.47 | +0.00 | +88.89 | Y | Y | weak_bull | 3.56 | 4.56 | 4.34 |
| FECM | 2023-12-06 | 3.94 | -18.78 | +0.00 | +87.50 | Y | Y | strong_bull | 4.0 | 5.0 | 5.92 |
| FECM | 2024-06-27 | 5.45 | -15.41 | +0.00 | +83.30 | Y | Y | strong_bear | 6.45 | 7.45 | 8.45 |
| FECM | 2023-12-04 | 3.23 | -19.50 | +0.00 | +70.77 | Y | Y | strong_bull | 3.0 | 3.94 | 4.0 |
| SYM | 2024-05-20 | 3.94 | +2.28 | -0.99 | +64.76 | Y | Y | weak_bull | 4.94 | 5.94 | 5.74 |
| BIPL | 2022-08-11 | 11.15 | -1.34 | +0.00 | +8.18 | - | - | strong_bull | 11.14 | 11.57 | 11.54 |
| PIBTL | 2025-08-21 | 10.85 | +1.38 | -0.46 | +8.18 | - | - | weak_bull | 11.53 | 11.2 | 11.19 |
| EPQL | 2023-11-03 | 28.6 | +0.00 | +0.00 | +8.18 | - | - | strong_bull | 28.78 | 29.72 | 29.16 |
| GGGL | 2025-06-26 | 9.17 | +0.00 | -0.22 | +8.18 | - | - | weak_bear | 9.57 | 9.61 | 9.4 |
| BERG | 2022-02-01 | 76.62 | -0.09 | +0.00 | +8.18 | - | - | strong_bear | 78.25 | 77.04 | 82.81 |

## 4. Top 10 candidate filters (ranked on discovery only)

G rate is the share of trades in G; lift is sub minus complement in percentage points; G-SC lift uses the signal-close reference; MAE/MFE lifts are median differences (MAE signal-close view for ranking); the D/V/OOS column shows the entry-referenced G lift per split; stable = positive lift in all three splits in BOTH path references. p_adj is Bonferroni over all tests on discovery (entry view).

| rank | filter | n sub | G rate | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC lift | MFE-SC lift | +2 before -1 | capture | precision | D/V/OOS G lift (entry) | stable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | turnover_low (<= discovery q33) | 8,195 | 0.253 | -2.79 [-3.87, -1.75] | 0.000 | +5.00 | -1.24 | +0.26 | 0.495 | 0.380 | 0.253 | +5.0/+5.1/+2.1 | no |
| 2 | rs20 < -5% | 2,841 | 0.263 | +6.55 [+4.85, +8.16] | 0.000 | +4.83 | +0.66 | +0.36 | 0.496 | 0.137 | 0.263 | +4.8/+2.0/+3.6 | yes |
| 3 | proxy_rvol20_low (<= discovery q33) | 8,236 | 0.235 | +3.83 [+2.75, +4.87] | 0.000 | +2.21 | +0.38 | +0.39 | 0.482 | 0.354 | 0.235 | +2.2/+0.3/+0.2 | no |
| 4 | breadth_high (>= discovery q66) | 8,477 | 0.232 | +4.77 [+3.63, +5.83] | 0.000 | +1.80 | +0.47 | +0.85 | 0.499 | 0.360 | 0.232 | +1.8/-0.7/+0.5 | no |
| 5 | fvg_age1 big gap >= 1% | 5,149 | 0.234 | +1.27 [-0.02, +2.44] | 1.000 | +1.77 | -0.72 | +0.84 | 0.508 | 0.221 | 0.234 | +1.8/-0.9/-2.2 | no |
| 6 | relvol 1.0-1.5 | 6,394 | 0.232 | +0.21 [-0.99, +1.32] | 1.000 | +1.63 | +0.47 | -0.60 | 0.448 | 0.272 | 0.232 | +1.6/+1.4/+3.0 | no |
| 7 | regime_strong_bull (proxy ret20>+5%) | 12,335 | 0.228 | +2.04 [+1.04, +2.97] | 0.000 | +1.53 | +0.37 | +0.38 | 0.485 | 0.514 | 0.228 | +1.5/-0.3/+0.6 | no |
| 8 | fvg_retrace TRUE (age-1 bull FVG, retested) | 1,741 | 0.234 | -2.14 [-3.96, -0.25] | 1.000 | +1.50 | -0.55 | -0.20 | 0.478 | 0.075 | 0.234 | +1.5/+1.1/-2.1 | no |
| 9 | clv_position >= 0.67 (premium) | 16,706 | 0.224 | +1.70 [+0.63, +2.73] | 0.216 | +1.11 | -0.23 | +0.48 | 0.483 | 0.684 | 0.224 | +1.1/+0.7/+0.6 | yes |
| 10 | regime_weak_bull (0<=proxy ret20<+5%) | 1,377 | 0.230 | +1.61 [-0.57, +3.83] | 1.000 | +1.02 | +0.16 | +0.53 | 0.510 | 0.058 | 0.230 | +1.0/-0.8/+0.8 | no |

Not rankable (reported for completeness): clv_position < 0.33 (discount) (n=209, n < 500 on discovery); equal_lows TRUE (n=319, n < 500 on discovery); gap_next_open < 0 (gap-down entry) (n=9,791, entry-reference-coupled artifact control (excluded from ranking)); gap_next_open 0..+0.5% (n=5,609, entry-reference-coupled artifact control (excluded from ranking)); gap_next_open > +0.5% (gap-up entry) (n=9,431, entry-reference-coupled artifact control (excluded from ranking))

## 5. Top 10 candidate combinations (ranked on discovery only)

| rank | combo | n sub | G rate | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC lift | MFE-SC lift | +2 before -1 | capture | precision | D/V/OOS G lift (entry) | stable |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ret_20d 0..+5% x rs20>0 | 3,545 | 0.220 | -1.55 [-2.99, -0.22] | 1.000 | -0.01 | +0.36 | -0.95 | 0.426 | 0.143 | 0.220 | -0.0/+2.7/-0.6 | no |
| 2 | ret_20d 0..+5% x sweep_low | 1,012 | 0.219 | -1.16 [-3.58, +1.33] | 1.000 | -0.05 | -0.01 | -0.21 | 0.450 | 0.041 | 0.219 | -0.0/+1.9/+3.3 | no |
| 3 | sweep_low x displacement | 1,207 | 0.216 | -2.09 [-4.42, +0.20] | 1.000 | -0.38 | -0.80 | +0.59 | 0.504 | 0.048 | 0.216 | -0.4/+0.6/+1.5 | no |
| 4 | sweep_low x bos_up | 718 | 0.206 | -0.14 [-3.15, +2.83] | 1.000 | -1.41 | -0.72 | +0.52 | 0.487 | 0.027 | 0.206 | -1.4/+0.2/+1.0 | no |
| 5 | rs20>0 x sweep_low | 1,990 | 0.205 | -3.07 [-4.80, -1.38] | 0.000 | -1.61 | -0.62 | +0.13 | 0.472 | 0.075 | 0.205 | -1.6/-1.2/+0.0 | no |

Combos not rankable on discovery (n < 500; full records in the JSON): sweep_low x fvg_retrace (n=238); ret_20d 0..+5% x sweep_low x fvg_retrace (n=77); live v1 stack: regime_bull x sweep_low x fvg_retrace (n=106)

The owner's sweep- and FVG-based combinations do not enrich G: every rankable combo shows a G entry lift at or below +0.1 pp on discovery, and most are negative. The live v1 stack's building blocks select ordinary-quality entries with respect to G membership.

## 6. Best candidates: discovery / validation / untouched OOS

### turnover_low (<= discovery q33)

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 8,195 | 16,636 | 0.253 | 0.203 | -2.79 [-3.87, -1.75] | 0.000 | +5.00 | -3.72/-2.49 | 3.27/3.01 | 0.380 | 0.253 |
| validation | 7,967 | 16,871 | 0.206 | 0.155 | -5.49 [-6.47, -4.52] | 0.000 | +5.10 | -5.48/-3.12 | 4.99/3.86 | 0.385 | 0.206 |
| oos | 6,311 | 19,005 | 0.164 | 0.143 | -7.52 [-8.52, -6.55] | 0.000 | +2.09 | -5.45/-3.07 | 5.31/3.53 | 0.276 | 0.164 |

- degradation (OOS minus discovery, entry-referenced G lift): -2.91 pp; stable sign all splits (both references): no (entry yes / SC no); MAE-SC positive all splits: no
- discovery G-SC lift excluding the top-3 G-contributing symbols: -2.50 pp (n_sub 8,183); excluding artifact-flagged rows: -1.03 pp (n_sub 6,432)

### rs20 < -5%

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 2,841 | 21,990 | 0.263 | 0.214 | +6.55 [+4.85, +8.16] | 0.000 | +4.83 | -2.22/-2.88 | 3.40/3.03 | 0.137 | 0.263 |
| validation | 4,303 | 20,535 | 0.189 | 0.168 | +0.27 [-0.96, +1.48] | 1.000 | +2.04 | -3.29/-3.76 | 3.90/4.17 | 0.190 | 0.189 |
| oos | 5,026 | 20,290 | 0.178 | 0.141 | +2.14 [+0.92, +3.31] | 0.000 | +3.65 | -2.71/-3.82 | 3.47/4.04 | 0.238 | 0.178 |

- degradation (OOS minus discovery, entry-referenced G lift): -1.18 pp; stable sign all splits (both references): yes (entry yes / SC yes); MAE-SC positive all splits: yes
- discovery G-SC lift excluding the top-3 G-contributing symbols: +6.67 pp (n_sub 2,809); excluding artifact-flagged rows: +7.32 pp (n_sub 2,555)

### proxy_rvol20_low (<= discovery q33)

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 8,236 | 16,595 | 0.235 | 0.212 | +3.83 [+2.75, +4.87] | 0.000 | +2.21 | -2.55/-2.93 | 3.33/2.95 | 0.354 | 0.235 |
| validation | 8,821 | 16,017 | 0.174 | 0.171 | -0.46 [-1.46, +0.52] | 1.000 | +0.30 | -3.61/-3.69 | 3.91/4.30 | 0.359 | 0.174 |
| oos | 11,199 | 14,117 | 0.150 | 0.147 | +1.26 [+0.39, +2.20] | 0.324 | +0.25 | -3.13/-3.95 | 3.40/4.37 | 0.447 | 0.150 |

- degradation (OOS minus discovery, entry-referenced G lift): -1.96 pp; stable sign all splits (both references): no (entry yes / SC no); MAE-SC positive all splits: yes
- discovery G-SC lift excluding the top-3 G-contributing symbols: +4.01 pp (n_sub 8,064); excluding artifact-flagged rows: +3.66 pp (n_sub 7,432)

### breadth_high (>= discovery q66)

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 8,477 | 16,354 | 0.232 | 0.214 | +4.77 [+3.63, +5.83] | 0.000 | +1.80 | -2.51/-2.97 | 3.62/2.77 | 0.360 | 0.232 |
| validation | 4,548 | 20,290 | 0.166 | 0.173 | +2.00 [+0.66, +3.27] | 0.000 | -0.71 | -3.50/-3.68 | 5.18/3.93 | 0.177 | 0.166 |
| oos | 6,223 | 19,093 | 0.152 | 0.147 | +3.61 [+2.43, +4.68] | 0.000 | +0.50 | -3.49/-3.56 | 4.45/3.73 | 0.252 | 0.152 |

- degradation (OOS minus discovery, entry-referenced G lift): -1.31 pp; stable sign all splits (both references): no (entry no / SC yes); MAE-SC positive all splits: yes
- discovery G-SC lift excluding the top-3 G-contributing symbols: +4.90 pp (n_sub 8,313); excluding artifact-flagged rows: +4.31 pp (n_sub 7,718)

### fvg_age1 big gap >= 1%

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 5,149 | 19,682 | 0.234 | 0.216 | +1.27 [-0.02, +2.44] | 1.000 | +1.77 | -3.40/-2.68 | 3.74/2.91 | 0.221 | 0.234 |
| validation | 4,576 | 20,262 | 0.164 | 0.174 | +0.89 [-0.38, +2.07] | 1.000 | -0.95 | -4.56/-3.52 | 5.43/3.94 | 0.176 | 0.164 |
| oos | 4,285 | 21,031 | 0.130 | 0.152 | -0.15 [-1.40, +1.09] | 1.000 | -2.22 | -4.77/-3.35 | 4.98/3.76 | 0.148 | 0.130 |

- degradation (OOS minus discovery, entry-referenced G lift): -3.99 pp; stable sign all splits (both references): no (entry no / SC no); MAE-SC positive all splits: no
- discovery G-SC lift excluding the top-3 G-contributing symbols: +1.50 pp (n_sub 5,062); excluding artifact-flagged rows: +1.76 pp (n_sub 4,371)

### ret_20d 0..+5% x rs20>0

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 3,545 | 21,286 | 0.220 | 0.220 | -1.55 [-2.99, -0.22] | 1.000 | -0.01 | -2.50/-2.85 | 2.27/3.21 | 0.143 | 0.220 |
| validation | 2,315 | 22,523 | 0.196 | 0.169 | -1.64 [-3.11, -0.08] | 1.000 | +2.68 | -3.07/-3.73 | 2.82/4.33 | 0.106 | 0.196 |
| oos | 1,450 | 23,866 | 0.143 | 0.149 | -5.87 [-7.57, -4.11] | 0.000 | -0.60 | -3.47/-3.55 | 2.69/4.00 | 0.055 | 0.143 |

- degradation (OOS minus discovery, entry-referenced G lift): -0.60 pp; stable sign all splits (both references): no (entry no / SC no); MAE-SC positive all splits: yes
- discovery G-SC lift excluding the top-3 G-contributing symbols: -1.76 pp (n_sub 3,470); excluding artifact-flagged rows: -1.89 pp (n_sub 3,310)

### ret_20d 0..+5% x sweep_low

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 1,012 | 23,819 | 0.219 | 0.220 | -1.16 [-3.58, +1.33] | 1.000 | -0.05 | -2.81/-2.80 | 2.88/3.08 | 0.041 | 0.219 |
| validation | 1,291 | 23,547 | 0.190 | 0.171 | -1.46 [-3.42, +0.68] | 1.000 | +1.89 | -3.12/-3.68 | 3.32/4.19 | 0.057 | 0.190 |
| oos | 1,036 | 24,280 | 0.180 | 0.147 | -1.18 [-3.39, +1.09] | 1.000 | +3.34 | -3.17/-3.56 | 3.05/3.95 | 0.050 | 0.180 |

- degradation (OOS minus discovery, entry-referenced G lift): +3.39 pp; stable sign all splits (both references): no (entry no / SC no); MAE-SC positive all splits: no
- discovery G-SC lift excluding the top-3 G-contributing symbols: -1.49 pp (n_sub 999); excluding artifact-flagged rows: -1.67 pp (n_sub 923)

### sweep_low x displacement

| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |
|---|---|---|---|---|---|---|---|---|---|---|---|
| discovery | 1,207 | 23,624 | 0.216 | 0.220 | -2.09 [-4.42, +0.20] | 1.000 | -0.38 | -3.57/-2.77 | 3.64/3.05 | 0.048 | 0.216 |
| validation | 1,190 | 23,648 | 0.177 | 0.172 | +3.42 [+1.11, +5.83] | 0.108 | +0.58 | -3.51/-3.66 | 5.01/4.10 | 0.049 | 0.177 |
| oos | 969 | 24,347 | 0.163 | 0.148 | +0.15 [-2.29, +2.56] | 1.000 | +1.52 | -3.91/-3.53 | 4.70/3.88 | 0.042 | 0.163 |

- degradation (OOS minus discovery, entry-referenced G lift): +1.89 pp; stable sign all splits (both references): no (entry no / SC no); MAE-SC positive all splits: no
- discovery G-SC lift excluding the top-3 G-contributing symbols: -2.13 pp (n_sub 1,192); excluding artifact-flagged rows: -1.77 pp (n_sub 1,018)

## 7. Artifact audit

- data_invalid rows excluded: 782 (1.03% of matrix rows); engine band 0.60 print-chain screen, same semantics as the engine.
- entry-vs-SC consistency: 54 filters tested; 18 show entry-referenced and signal-close G lifts with opposite signs (entry-price arithmetic). The final protocol ranks by the entry view (the owner's G definition) and requires SC agreement for a strong candidate; the three gap filters are excluded from ranking as reference-coupled (entry view favors gap-down, SC view favors gap-up, mechanically).
- the Phase 1 gap-down artifact re-check on the new build: 'gap_next_open < 0' entry-referenced MAE lift +1.02 pp vs signal-close -1.93 pp (entry-referenced lift flips sign in the SC view: confirmed entry-price arithmetic artifact).
- corporate-action exposure: no adjustment factors exist in the repo (acquisition spec C in RESEARCH_PHASE1.md); as a screen, single-bar moves >= 9.9% inside bars 1-3 appear in 23.5% of G trades vs 16.0% of the complement (up) and 6.5% vs 14.3% (down); PSX circuit bands around these levels mean genuine limit moves and unadjusted corporate actions cannot be separated without the factor file, so both are reported
- survivorship: universe membership is today's KMIALL list (survivorship-biased); 8 symbols stopped printing > 90 days before the dataset end; 1.8% of G trades come from them; point-in-time membership still cannot be reconstructed
- order-flow fabrication: no bid/ask, depth, order-flow, AMT or footprint information exists in this project (registry: UNAVAILABLE); none is implied anywhere
- concentration: G trades span 304 symbols; top-10 symbols carry 7.2% of G; deep-dive candidates are re-measured with the top-3 G symbols removed (see best candidates)

## 8. What defines Group G (classification)

**mixture of several states: some signal-time filters carry stable but modest information about G; no single dominant state, and the residual remains partly unexplained**

- G rate is stable across splits: discovery 22.0%, validation 17.2%, OOS 14.8% (halves 22.0% vs 16.0%)
- G_sc overlap Jaccard 0.420: the entry-price reference is not what creates G
- single-bar jump flags: 24.7% of G vs 23.2% of complement
- top-10 symbols carry 7.2% of G over 304 symbols
- 1 of 8 deep-dive candidates keep a positive G-rate lift in all three splits in both path references; 0 clear the full strong-candidate bar

## 9. Final recommendation

**B. Promising but requires more validation**

One or more candidates show a G-rate lift that stays positive across discovery, validation and OOS with at least suggestive corrected significance, but none clears the full strong-candidate bar (>= +5 pp, Bonferroni-significant, MAE-SC positive in all splits, concentration-safe). The honest reading is a weak-to-moderate signal that needs more data or better features before any TP/SL testing.

Rubric applied (frozen in the script):

- stable+suggestive candidates: rs20 < -5%

## 10. What still cannot be concluded

- No profitability claim of any kind: this phase measures identifiability of a path shape, never net returns after the owner's cost schedule.
- No intraday conclusion: 3-bar daily paths only.
- Corporate actions are screened, not corrected (no adjustment factors).
- Point-in-time index membership cannot be reconstructed; every result inherits the current-membership universe.
- The equal-weight proxy is not the KSE-100 or Meezan index; regime, breadth, vol and turnover-regime features inherit that substitution.
- Late-volume behavior is unavailable on daily bars (declared, not fabricated); FVG features exist only at age 1 in this engine.
- Validation and OOS windows are scored once with frozen cuts, but the OOS window is short (about 15 months) and one market regime.

## Appendix: exact feature definitions

- G (target): mae_3bar >= -1.0 AND mfe_3bar >= +2.0, both referenced to the entry price (next open); mae_3bar is the minimum low over bars 1..3 vs entry, mfe_3bar the maximum high
- G_sc (robustness): same thresholds referenced to the signal close (feat_close) instead of the entry price
- regime: equal-weight KMIALL proxy 20-session return bands: >+5% strong_bull, 0..+5% weak_bull, -5..0 weak_bear, <-5% strong_bear (Phase 1 level definition, unchanged)
- feat_ret_20d: close(T)/close(T-20) - 1, positional sessions
- feat_rs5/rs10/rs20: per-symbol return over 5/10/20 sessions minus the cross-sectional mean per-symbol return over the same window (composition-safe equal-weight market return), positional sessions
- feat_rs_accel: rs5(T) minus rs5 measured 5 sessions earlier
- feat_breadth: share of symbols with close(T) > MA20(T) among symbols with a defined MA20 on that date
- feat_rvol20: 20-session rolling std of the cross-sectional mean per-symbol daily return (composition-safe proxy realized volatility)
- feat_mkt_turn_ratio: mean daily universe turnover (sum of close x volume) over trailing 20 sessions divided by the same over trailing 60 sessions
- feat_turnover: close(T) x volume(T) for the symbol (PKR)
- feat_relvol: volume(T) / rolling median volume over T-19..T
- feat_vol_accel: volume(T) / volume(T-1)
- feat_clv_position: (close - low of prior 20 bars) / (high-low range of prior 20 bars); premium/discount buckets 0.33/0.67
- feat_body_ratio: |close-open| / (high-low) at T
- feat_lower_wick: (min(open,close) - low) / (high - low) at T; values outside [0,1] are raw-data dirt and treated as missing
- feat_range_expansion: true range(T) > 1.5 x trailing 20-bar median true range; TR = max(high-low, |high-prev close|, |low-prev close|)
- feat_20d_high_break: close(T) >= prior 20-bar high (T-20..T-1)
- feat_pullback_resume: close(T) > MA20(T) AND close(T-1) < close(T-2) < close(T-3) < close(T-4) (three consecutive lower closes before T)
- feat_sweep_low: min low of T-6..T-2 < prior low of T-16..T-6 AND close(T) > that prior low
- feat_bos_up: close(T) > max close of T-20..T-1
- feat_displacement: |close-open| >= 2 x trailing 20-bar median body AND close > open
- feat_equal_lows: today's low within 0.3% of the prior 9-bar low
- feat_fvg_bull_age1: low(T-1) > high(T-3) (bullish FVG formed at T-1)
- feat_fvg_size_pct: (low(T-1) - high(T-3)) / close(T-1)
- feat_fvg_retrace: bullish age-1 FVG AND low(T) <= FVG midpoint (low(T-1)+high(T-3))/2
- gap_next_open: (next open / signal close - 1) x 100; entry price
- jump_up / jump_dn flags: max / min single-bar move >= +9.9% / <= -9.9% inside bars 1-3, referenced to the previous close (artifact screen only)
- frozen cuts: breadth q33/q66 0.4774/0.7282; rvol20 q33/q66 0.0077/0.0122; turnover q33/q66 1.751e+06/2.569e+07; fixed cuts: wick 0.3/0.5, rs 0/+2.5%/-5%, band 0..5%, fvg size 1%, gap 0.5%, turn ratio 1.0
- declared unavailable: late-volume behavior (daily bars only), FVG ages beyond 1 (engine computes age-1 only), order-flow/depth/footprint (registry UNAVAILABLE)

## Appendix: provenance

- python 3.13.15, pandas 3.0.5
- bootstrap seed 20261006; no other randomness; one-shot local run
- matrix: 75,767 rows, built by scripts/build_trade_matrix.py from 287,962 dataset rows (sha256 55fd6d21)
