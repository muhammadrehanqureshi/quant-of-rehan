# Intraday Forward Validation System

Status date: 2026-10-08 (Karachi)

## Current state

The active research gate has no stored sessions yet. Cloudflare currently reports an empty research history, and the scheduled capture workflow has not completed its first run. The one local intraday capture is from 2026-10-06 and is not a strategy sample. A read-only check of the configured source at 10:10 PKT on 2026-10-08 returned no OHLC bars for OGDC at 1-, 5-, or 15-minute intervals. The first scheduled scan is 10:45 PKT. Until that run proves broad coverage, the collector is not verified operational.

The system may send one explicitly labeled PAPER SIGNAL for the original rule. A production signal remains disabled until all of these conditions are satisfied:

- an eligible strategy passes the chronological statistical gate below
- source rights, source latency, and current KMIALL membership are confirmed through the GitHub Actions variables `KMIALL_DATA_RIGHTS_CONFIRMED`, `KMIALL_DATA_LATENCY_CONFIRMED`, and `KMIALL_UNIVERSE_CONFIRMED`
- the current scan has structurally valid data and a breakout no more than five minutes old
- persistent one-per-day claim succeeds

The variables default to false when unset. A passing paper result alone cannot send a production signal. The gate rechecks data and membership confirmation for the full evidence window and demotes production if confirmation is lost.

The collector reads the read-only broker tape (MKT-FEED) and builds one-minute bars from it: open, high, low and close are the prices the tape carried in that minute, and volume is the difference of the venue's own running counter (`src/data/tape_bars.py`, owner order 2026-10-14, after the eClear OHLC servlet stopped serving bars). The eClear `GetOHLCData` public read tier is the FALLBACK, used only for a day that has no tape capture; code verifies TLS certificate chains and hostnames on that path, and it returned OHLC without volume, quote depth or order flow even when it worked. Its delivery latency and rights for cloud retention and signal redistribution have not been independently verified. Structural OHLC validation is not source certification. The official PSX Data Portal labels its data delayed by five minutes and publishes a notice requiring rights or a license for data transmission. Do not describe this eClear feed as live based on its host or minute bars alone.

## Causal scan and registered strategies

The scanner currently reads the versioned Shariah-compliant KMIALL list in `src/data/universe_kmiall.json`. This is a current membership snapshot, not point-in-time history. Historical EOD studies remain survivorship-biased. The daily research record stores the sorted-universe fingerprint so future membership changes are visible, but the list is not refreshed from an official constituents service during a scan.

The collector captures one-minute OHLC. The scanner creates five-minute bars only from five consecutive minutes and uses bars completed before the decision time. It rejects malformed or structurally stale captures. A candidate must be a recent breakout, and it is rejected when its latest complete bar is more than five minutes old. No stale breakout is replayed. A score tie inside the pre-registered margin returns NO TRADE.

Five small candidates are evaluated on identical dates and cost assumptions:

1. 30-minute opening-range breakout, relative-strength floor, breadth gate, and anti-chase caps
2. the same breakout with no relative-strength floor
3. 60-minute opening-range breakout with the other baseline filters
4. the 30-minute breakout with the breadth gate omitted
5. the 30-minute breakout with the extension caps omitted

These are controlled comparisons, not evidence that any candidate works. All candidates still use OHLC only. Volume confirmation, VWAP, order flow, bid/ask spread, sector breadth, and liquidity filters cannot be tested from this feed.

The common market proxy is the cross-sectional median return and advancing share. It is not the official KMIALL index. The feature thresholds are hypotheses registered for paper comparison, not empirically established production rules.

## Entry and outcome semantics

The entry reference is the close of the completed five-minute signal bar. It is explicitly a paper reference and may not be executable when delivered. The target is exactly `entry * 1.02`; the adverse reference is exactly `entry * 0.99`.

Only bars strictly after the decision timestamp are used. If one five-minute OHLC bar touches both target and stop, the outcome is stop-first. A stop gap fills at the bar open when that open is below the stop; otherwise it fills at the stop level. A target gap fills at the target price. If neither threshold is touched, the last completed bar before the session close is used as the timeout exit. Missing scheduled scan slots, incomplete capture, and structurally invalid data make the date ineligible for a research session.

The evaluator models 22.4 basis points per side, 10 basis points of slippage per side, and 15% CGT on positive net returns. Those are assumptions, not verified fills or a guarantee of execution. The no-volume feed cannot show whether a limit-up, halt, queue, or thin market would have allowed a fill.

## Candidate selection and frozen evidence gate

The gate consumes only unique dates with a structurally verified capture and all required scan observations. Unverifiable dates do not consume a session. One candidate per strategy per day is labeled, or the date is recorded as NO CANDIDATE.

For each research cohort:

- first 60 valid sessions are discovery
- next 60 are validation
- discovery and multiplicity-adjusted validation select at most one strategy
- the next 60 sessions are locked OOS for that selected strategy
- selection uses discovery and validation only; OOS never chooses or retunes a candidate

There are five pre-registered comparisons. The bootstrap uses a circular moving-block method. Family-wise alpha is spent across both candidates and repeated cohorts, so the actual reported lower-bound confidence level is recorded and may exceed 95%. OOS must have at least 40 trades, positive net expectancy, a positive adjusted lower bound, profit factor at least 1.10 when defined, top-ten-symbol share no greater than 60%, drawdown no greater than 15%, worst losing streak no greater than ten, one trade per day, and no more than 50% expectancy degradation from validation. Discovery and validation each need at least 30 trades and positive net expectancy; the validation lower bound must pass the candidate and cohort correction.

If no strategy passes discovery and validation, the failed cohort is frozen and the next cohort begins on new valid dates. If OOS fails, the OOS cohort is frozen and later dates begin a new search cycle. This prevents retuning against failed OOS data. The library is small and fixed; it does not run an open-ended parameter grid.

After the OOS gate passes, the selected rule is monitored on its latest 20 production outcomes. Non-positive net expectancy, drawdown above 10%, a losing streak of eight or more, or loss of source confirmation demotes it automatically. The production path then stays closed while fresh candidate research continues.

Metrics include trade count, positive-net trade rate, gross and net total return, gross and net expectancy, median trade, profit factor, maximum drawdown, average winner and loser, target/adverse/timeout rates, average holding time, symbol concentration, maximum daily trade count, worst losing streak, and block-bootstrap confidence bounds. These are measured per trade with one candidate per day.

## Cloud operation and messages

GitHub Actions is scheduled at 10:45, 12:45 Monday to Thursday, 14:45, and 16:45 PKT. Friday's midday break is skipped. The first scan slots evaluate the candidate rules; the last slot labels the day's outcomes and updates the gate. A one-pass capture below 80% symbol coverage fails before scanning or recording an outcome, and the owner receives a data-free NO TRADE alert with the failed run link. Raw capture artifacts are retained for 90 days. Research observations, daily outcomes, and the current gate are stored in Cloudflare KV with a two-year retention. Existing observation and outcome keys are write-once.

A research candidate message begins `PAPER SIGNAL`; the eligible path begins `PRODUCTION SIGNAL` and says `BUY <SYMBOL>`. The daily status message may say NO TRADE. The bot does not place orders or connect to broker order endpoints.

The monthly scheduled ceiling remains below the documented 2,000 Actions-minute allowance: up to 1,380 capture minutes plus up to 460 daily signal minutes across a 23-weekday month.

## Historical reports and limitations

The old 27.487% positive-net result is from a placeholder daily moving-average/volume rule, with next-session-open entries and a mean net expectancy of -1.0559% per trade. It is not intraday accuracy, not the current signal rule, and not evidence of an edge. Its historical universe uses current membership and is not fully corporate-action adjusted.

The local one-session intraday capture contains 32,639 one-minute bars across 298 symbols for 2026-10-06. Historical intraday sequence is not present in the repository. PSX's official site describes historical market data availability through its data services, but no licensed intraday archive is configured in this project. The current production data approval variables remain unset, so current evidence can only stay paper.

No broker order placement, leverage, short selling, futures, or margin was added.
