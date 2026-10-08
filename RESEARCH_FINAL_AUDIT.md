# Research and Production Audit

Original audit snapshot: 2026-10-08 (Karachi), before PR #44. Its daily research results remain historical. The current implementation status is in the addendum at the end of this file.

## A. Current diagnosis

The project had four material problems:

1. The five-year 27.5% result was described too loosely and came from a placeholder daily entry rule, not the production FVG/sweep rule.
2. The Phase 1 trade-matrix helper treated a same-day target and stop touch as target-first, contradicting the backtest's stop-first convention.
3. The Phase 2B cost helper looked at the entry bar's open for a gap-through stop. That open is the entry itself, so it missed stop gaps on that bar and all later bars.
4. The scheduled "intraday" scanner aggregated all available one-minute bars into a single partial daily candle, then passed it to the daily engine. That is not chronological intraday signal logic.

At this original audit snapshot, production failed closed and the broken intraday scanner had been removed. PR #44 later added a chronological paper scanner. No order placement or broker execution was added.

## B. What the 27% result means

The local smoke artifact `data/backtest_smoke_5y.json` reports a 27.487% win rate. This is the fraction of valid trades with a positive net return after the modeled fee and tax schedule. It is not the production strategy's accuracy and is not the TP-first rate.

- Rule: close above the 20-day moving average and volume above its 20-day median at close T; entry at the next session's open.
- Data: 283,630 daily rows, 305 symbols, 2021-10-04 through 2026-10-02, from the local five-year PSX Daily Downloads file.
- Universe: the KMIALL list available when the dataset was built, applied retrospectively. Historical membership and delistings are not reconstructed.
- Valid denominator: 74,642 of 74,654 simulated fills; 12 were screened as data-invalid.
- Result: 27.487% positive net returns; 26.866% TP exits; 71.320% SL exits; 1.814% timeouts; mean net expectancy -1.0559% per trade.
- Fill law: daily OHLC high/low, entry next open, +2% exact target fill, -1% stop or worse opening gap, stop wins same-bar ambiguity, three-session maximum, 22.4 bps per side and 15% CGT on winners. No additional slippage was modeled.
- It is a daily-bar result, not an intraday result, and it does not represent the deployed FVG/sweep signal engine.
- It includes many trades on the same days and overlapping holdings, so the report's compounding drawdown is not a valid account-level portfolio drawdown.

The local five-year file is not fully adjusted for corporate actions. The 60% adjacent-print screen excludes obvious discontinuities but does not repair subtler adjustment errors. This is also a current-membership backtest, so survivorship bias remains.

## C. Data audit

| Data | Available | Limitation |
|---|---|---|
| Daily OHLCV | 2021-10-04 to 2026-10-02 in the local smoke artifact | Current KMIALL membership; no verified point-in-time reconstitution table; unadjusted corporate actions remain |
| Genuine intraday | One session, 2026-10-06: 32,639 one-minute bars across 298 symbols in local capture | Insufficient sessions for discovery, validation, or OOS; no historical intraday labels |
| Intraday volume | Not present in the captured one-minute bars | No relative-volume or volume-acceleration claim is possible intraday |
| Official market index history | Not available in the research inputs audited | The daily engine's equal-weight stock proxy is not the KMIALL index |
| Footprint / bid-ask / depth | Unavailable | OHLC cannot be relabeled as order flow |

At the original audit snapshot, the scheduled capture stored four daily snapshots at 10:45, 12:45, 14:45, and 16:45 PKT and did not generate intraday candidates. PR #44 later added the chronological scanner and Cloudflare outcome storage. Raw workflow artifacts still expire after 90 days. The scheduled ceiling remains about 1,840 GitHub Actions minutes per 23-weekday month: 1,380 capture minutes plus 460 daily-signal minutes.

## D. Strategy audit

| Rule or feature | Discovery | Validation | OOS | Effect and decision |
|---|---:|---:|---:|---|
| Production stack: regime x sweep_low x FVG retrace | 106 discovery cases, below the 500 minimum | No rankable validation set | No rankable OOS set | Not validated; disabled for production |
| rs20 < -5% | n=2,841; TP-first 35.48% vs 30.78% complement, +4.70 pp | n=4,303; 28.40% vs 25.85%, +2.55 pp | n=5,026; 25.83% vs 22.47%, +3.3565 pp, 95% CI [1.9068, 4.7096] | Small predictive lift, but not profitable after costs; research-only |
| Group G: MAE >= -1%, MFE >= +2% | n=13,484 / 74,985 valid rows overall | Future-path outcome description | Future-path outcome description | Uses future MAE/MFE; cannot be an entry signal or ranker |
| Liquidity-first one-winner rank | Phase 2B OOS pick share 21.52% TP-first | 22.68% | 22.35% | Underperforms full OOS baseline 23.14%; not promoted |
| rs20-depth-first rank | 33.15% | 28.69% | 24.05% | Explored after seeing this research window; not a locked untouched test and not deployable |
| Breadth q20 market veto | Vetoed 31.08%, pass 31.37% | Vetoed 29.00%, pass 25.87% | Vetoed 20.40%, pass 23.75% | Effect changes by period; not a stable market gate |
| sweep_low within rs20 subset | +1.84 pp | +3.81 pp | +2.57 pp | Fails the report's sample/rankability gate; not retained |
| FVG retrace within rs20 subset | +4.28 pp | +5.85 pp | +5.55 pp | Fails the sample/rankability gate; not retained |
| BOS up within rs20 subset | +8.93 pp | +1.98 pp | +2.93 pp | Fails the sample/rankability gate; not retained |
| High-turnover rs20 subset | -1.68 pp | -1.92 pp | +2.14 pp | Sign changes; no stable selection value |

The Phase 2B cost table is not authoritative for gap execution because its gap-through-stop code used the entry-bar open and omitted later stop-bar opens. The helper is repaired and regression-tested in this change. The table must be regenerated before its cost estimates are reused. The one-winner economic figures below were separately recomputed with the daily backtest engine's actual gap and tie rules.

Phase 1's headline same-bar target-before-stop flags are also not authoritative: ties counted as target-first. The frozen report is preserved as an historical artifact. Future matrices use strict earlier-bar ordering, and same-bar touches are not classified as target-first. The exact corrected historical Phase 1 headline was not regenerated in this audit.

## E. Backtest audit

The daily engine's causal timing is signal at close T and entry at next open. It applies the stated TP/SL, gap-stop and same-bar stop-first conventions, models fees and CGT, and screens adjacent-print jumps above 60%. Those are daily-bar assumptions; they do not determine intraday ordering.

The major unresolved limitations are current-universe survivorship, incomplete corporate-action adjustment, no intraday volume, and overlapping positions. A per-trade compounded drawdown does not define portfolio drawdown when positions overlap and capital allocation is unspecified. Portfolio drawdown is therefore not reported as a valid measure.

## F. New strategy

No candidate strategy survived the daily-bar economic and evidence gates in this report. The later intraday candidates are separate paper rules and have not been validated. There is no claim of 90% accuracy.

## G. One-winner selection

At the original audit snapshot, production emitted zero candidates while the engine was disabled. PR #44 later added a one-winner paper ranking. No research ranking has established production eligibility.

## H. NO TRADE conditions

The daily signal job sends NO TRADE ENGINE READY because no daily-bar strategy is enabled. The later intraday pipeline may send a clearly labeled PAPER SIGNAL; it cannot send a production signal until its own evidence and source gates pass.

## I. Final OOS results

The most defensible available economic check is the frozen liquidity-first one-winner selection, evaluated with the daily backtest engine. The 316 Phase 2B OOS picks include only 314 with a fully observable three-session path after excluding the final incomplete dates.

| Measure | OOS result |
|---|---:|
| Complete selected trades | 314 |
| TP exits | 21.34% |
| SL exits | 77.39% |
| Timeouts | 1.27% |
| Mean net expectancy, modeled fees/tax, zero extra slippage | -0.8514% per trade |
| Profit factor | 0.5504 |
| Median net return | -1.448% |
| Average holding time | 1.169 sessions |
| Trade-sequence drawdown | 93.32%, not a valid portfolio drawdown |

Year splits: 2025, n=130, TP 22.31%, SL 76.15%, timeout 1.54%, net expectancy -0.8221%. 2026, n=184, TP 20.65%, SL 78.26%, timeout 1.09%, net expectancy -0.8721%.

OOS regime breakdown:

| Regime | n | TP exits | Net expectancy |
|---|---:|---:|---:|
| strong bear | 47 | 27.66% | -0.683% |
| weak bear | 104 | 21.15% | -0.846% |
| weak bull | 116 | 19.83% | -0.900% |
| strong bull | 47 | 19.15% | -0.911% |

OOS liquidity grouping at frozen discovery cutoffs: high turnover n=309, TP 21.36%, net -0.851%; mid turnover n=5, TP 20.00%, net -0.895%; low turnover n=0. This does not support a low/mid/high liquidity conclusion. Selected 44 symbols; the top ten account for 57.01% of picks; one symbol was selected 26 times.

Slippage sensitivity for this selected set: -0.8514% at 0 bps/side, -0.9481% at 5 bps/side, and -1.0448% at 10 bps/side. All are negative.

## J. Production readiness

**NOT READY**

The historical findings in this report remain unchanged. The implementation state below supersedes its older scanner and deployment descriptions.

## Current implementation addendum (2026-10-08)

Remote master at the start of the addendum was `d6ef9bb56c050ef293f7ea4d0df688d5f4ac94d9`. PR #44 added a chronological one-minute to five-minute KMIALL paper scanner, persistent observations and outcomes, and a closed statistical gate. A new implementation update preregisters five controlled candidates, excludes invalid sessions, locks chronological OOS, cycles to fresh cohorts after failure, monitors the latest 20 production outcomes, and makes stored observations/outcomes immutable.

The Cloudflare research history is currently empty. The only local capture is the genuine 2026-10-06 session: 32,639 one-minute OHLC bars across 298 symbols. There is no historical intraday sample large enough to evaluate any of the new candidates. The repository's KMIALL universe is a static current-membership file, so it does not provide point-in-time historical membership.

The collector uses an eClear public read-tier endpoint. The source's latency and rights for cloud retention or signal redistribution are not independently verified. Production remains disabled unless the full 60/60/60 evidence gate passes and the GitHub Actions variables `KMIALL_DATA_RIGHTS_CONFIRMED`, `KMIALL_DATA_LATENCY_CONFIRMED`, and `KMIALL_UNIVERSE_CONFIRMED` are true for the full evidence window. Paper messages are explicitly labeled. The official PSX Data Portal states that its own data is delayed five minutes and publishes a data-rights notice; that statement does not certify the separate eClear endpoint.

The 27.487% figure remains the placeholder daily rule's positive-net trade rate. It is not intraday accuracy or evidence for any current candidate. All financial metrics in this historical report remain tied to their listed daily-bar assumptions and bias limitations.

## Changes in this repair

- Removed the partial-daily-candle scanner and its alert route.
- Kept scheduled one-minute market data capture and 90-day artifact retention.
- At the original audit snapshot, candidate delivery was disabled and the daily app/Telegram payload was NO TRADE ENGINE READY. Later intraday paper messages are covered by the current implementation addendum.
- Changed trade-matrix target-before-stop logic to count only a strictly earlier target touch; added same-bar ordering tests.
- Corrected Phase 2B gap-stop cost logic to use the open of the actual stop-touch bar; added gap-fill regression tests.
- Corrected README and data-source descriptions to match the running architecture and evidence.
