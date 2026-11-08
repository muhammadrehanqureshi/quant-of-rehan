# Intraday backtest forensic audit

Generated 2026-11-08T12:19:40.387478+05:00 (Asia/Karachi).
Run: https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/runs/42458265177
Commit: `f28997fa6925ae9d12d67bebcbd4fc3cae20f682`

## Verdict

**BACKTEST INVALID, CORRECTIONS REQUIRED**

The existing eleven strategy study is not admissible as a measurement of
executable PSX performance. Its 107 trades were selected from signal
frames that can contain carried and stale minutes and were executed
without checking that the chosen price was a fresh print. The replay
also ignored the entry minute's own high and low, and it dated the last
print of a session at the 15:30 boundary. Those are execution and data
defects, not strategy findings.

Corrected dataset status: **DATA INSUFFICIENT FOR VALID STRATEGY COMPARISON**.
The corrected sample contains
5 complete sessions, not the
60 required for even a preliminary
comparison. No strategy is called profitable, eligible or ready for
production. The live engine, targets, stops, notifications, broker path
and Android application were not changed.

## Headline reconciliation

| Item | Original claim | Recomputed | Finding |
|---|---:|---:|---|
| Sessions | 18 | 18 | same stored set |
| Effective full sessions | 13 | 5 | the original overstates full coverage |
| Trades | 107 | 107 | replay reproduces the published count |
| Sum net return | -77.57% | -77.57% | same ledger, same cost model |
| Strategy 10 | not tested | not tested | unchanged refusal |

The replay reconciliation matters: the defects are in the original
replay, not in a reconstruction of it. The original count is reproduced
from the same stored sessions and the same cost model.

## Data quality

- Complete sessions: 5 of 18.
- Missing stored sessions inside the study window: 2 (2026-10-13, 2026-10-14).
- Minute buckets: 1,299,434; fresh: 389,296;
  stale: 768,168; carried: 8,576.
- Duplicate consecutive rows: 3,637,557;
  out-of-order records: 0.
- Venue extreme violations reported by the bar path: 12.
- First observation of each session is listed in the quality report.

The original report's claim of 13 effective full sessions is not
supported by its own first-observation table. The honest complete count
is the sessions whose first observation is at or before the open and
whose last observation reaches the close. The exact count is printed in
the quality report; a late first observation makes a session partial
even when the afternoon tape is complete.

The study window also has no stored 2026-10-13 or 2026-10-14 capture.
Those are missing sessions, not holidays and not zero-volume days.

## Signal to execution causality

Every one of the original
107 trades has `signal_time == entry_time`.
That is not a pre-signal fill. The original simulator labels the entry at
the start of the minute it uses and fills at that minute's open, even
when the first genuine print of that minute arrived later, or when the
minute carried the previous close. The equality is a timestamp
convention that hid the delay.

The corrected execution delays the entry to the first fresh print:
median delay 18.44 seconds,
p90 137.62 seconds,
maximum 788.71 seconds.
Corrected entries are never before the signal completion:
0 violations.

The causal chain now has four separate recorded instants: the signal
frame completes, the first fresh print arrives, the entry is priced, and
the exit print arrives. No step is inferred from a bar label.

## Suspicious prices and every loss below -2.5%

Every suspect is retained in the original ledger. No losing trade was
deleted, capped or reclassified as a winner.

| Day | Symbol | Strategy | Entry | Exit | Net | Classification | Action |
|---|---|---|---:|---:|---:|---|---|
| 2026-11-05 | JATM | 1_ema_rsi_pullback | 76.9 | 74.2 | -4.16% | genuine_gap_through_stop | retained |
| 2026-10-29 | PREMA | 2_vwap_reclaim_relvol | 31.63 | 30.7 | -3.59% | genuine_gap_through_stop | retained |
| 2026-10-22 | UPFL | 3_kalman_vwap_rs | 30675.62 | 30000.0 | -2.85% | genuine_gap_through_stop | retained |
| 2026-10-20 | SLGL | 1_ema_rsi_pullback | 15.1 | 14.77 | -2.83% | genuine_gap_through_stop | retained |
| 2026-10-27 | DOL | current_kalman_flip | 31.02 | 30.51 | -2.29% | genuine_gap_through_stop | retained |
| 2026-10-23 | SLGL | 1_ema_rsi_pullback | 15.85 | 15.6915 | -1.65% | genuine_print | retained |
| 2026-10-27 | PREMA | 9_relative_strength_rotation | 32.0 | 32.64 | +1.15% | genuine_print | retained |

UPFL is a genuine high-priced stock, not a decimal error. The
repository's daily panel for 2026-10-22 records open 30,670, high
30,675.62, low 28,000 and close 29,103.21. The entry equals the day's
high and the exit is inside the day's range, so the -2.85% result is a
real gap through the stop on Unilever Foods. It is retained.

JATM, PREMA, SLGL and DOL are retained with their raw bar evidence. The
daily panel and the venue range place their exits inside the day's real
range, so the losses are genuine gaps through the stop, not parsing
errors. Where a bar was carried or stale, the original fill is marked
as non-executable and the corrected run either re-enters on the next
fresh print or records a rejection.

## Execution realism

- Same-bar ambiguity found and resolved stop-first: 0.
- Last genuine print exits instead of 15:30 labels: 10.
- Carried entries remaining in the corrected arm: 0.
- Stale entries remaining in the corrected arm: 0.
- Gap losses beyond the stop: {'0-50bps': 17, '100-250bps': 3, '50-100bps': 1}.
- Quoted spread at entry or exit minutes: median 20.95 bps,
  p90 442.56 bps over 497 observations.
- Modelled cost: 22.4 bps per side plus
  10.0 bps slippage per side; CGT
  15% on positive net returns. Cost and CGT remain
  assumptions, not measured broker fills or a tax determination.

Partial fills, queue position and market impact are not modelled. A
signal-only research result cannot establish executable capacity. The
corrected run reports volume and turnover at entry and exit but does not
pretend that a 5m bar's volume was available to this account.

## Strategy specification audit

| # | Strategy | Status | Documented deviation |
|---|---|---|---|
| 0 | Current bot, 1m Kalman Trend fresh flip | tested | Only the 1m flip arm is replayed. The live four-frame VWAP pullback arm is not tested because its 1D frame needs 40 completed daily bars that the band store does not hold. |
| 1 | EMA 20/50 + RSI pullback | tested | The optional 1H EMA50 filter is omitted. The 5m close above the prior high is an added trigger. |
| 2 | VWAP reclaim + relative volume | tested | The separate retest in the written specification is not required. |
| 3 | Kalman 1H/15M + VWAP + relative strength | tested | The market leg of RS20 is the equal-weight mean of captured KMIALL symbols, not the KMIALLSHR index level. |
| 4 | Donchian breakout + ATR + relative volume | tested | The suggested 0.25% to 0.90% normalized ATR band is not a hard gate. A 0.75% anti-chase cap is added. |
| 5 | Supertrend + ADX + volume expansion | tested | The separate controlled pullback qualifier is not enforced. |
| 6 | Bollinger squeeze + volume breakout | tested | The written specification's 1h condition is represented only by close above EMA50. |
| 7 | RSI reversal + EMA 50 support | tested | No separate written-specification gate beyond the 1h EMA50 and the higher low is omitted. |
| 8 | Opening range breakout + VWAP | tested | The anti-chase cap allows at most 0.5% above the opening-range high. |
| 9 | Relative strength rotation | tested | The market is the equal-weight captured universe, not the KMIALLSHR index. The 1h RS component named in the note is not an explicit gate. |
| 10 | Order book imbalance + VWAP + intensity | not_tested | The capture has last price, best bid, best ask and print sizes, but not top-five depth or a reliable aggressor sequence. Computing imbalance would fabricate the missing book. |

Strategy 10 is not_tested. The capture has
last price, best bid and best ask, print sizes and print-side evidence,
but not the top five depth levels or a reliable aggressor sequence.
Computing an order-book imbalance from those fields would invent the
book. It remains NOT TESTED.

## Corrected performance

Two corrected arms are reported so the execution defect is not confused
with the strategy:

1. **Execution-only**: original signal frames, genuine fresh-print entry
   and exit, entry-minute stop and target, last-print close handling.
2. **Strict**: the same execution law, with carried and stale minutes
   removed from the 5m, 15m and 1h signal frames as well.

| Arm | Trades | Win rate | Target first | Gross exp | Net before CGT | Net exp | Profit factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 107 | 0.2617 | 0.1682 | -0.026% | +0.000% | -0.725% | 0.2838 | -76.22% |
| Execution-only | 106 | 0.2925 | 0.1887 | +0.089% | -0.558% | -0.616% | 0.3448 | -63.91% |
| Strict | 77 | 0.1688 | 0.0779 | -0.103% | -0.751% | -0.774% | 0.1423 | -58.23% |

| Arm | Complete sessions | Complete trades | Complete net exp | Complete target first |
|---|---:|---:|---:|---:|
| Baseline | 5 | 44 | -0.415% | 0.25 |
| Execution-only | 5 | 44 | -0.302% | 0.2727 |
| Strict | 5 | 32 | -0.739% | 0.0625 |

No strategy has a positive corrected net expectancy with a confidence
interval that excludes zero on a sufficient independent sample. Even a
positive point estimate here would describe the complete sessions on hand,
an edge.

## Why selection stops

- Complete sessions: 5.
- Required for a preliminary comparison: 60.
- Preferred across regimes: 100.
- The original sample is 18 stored sessions, not three years.
- Daily bars exist for years; intraday bars exist only for the captures.
- Mixing daily history into an intraday comparison would pad the sample
  with a different market and is forbidden.

## Required next data work

1. Keep capturing complete regular sessions, including the open and the
   close, and store the raw tape hash with every session.
2. Preserve the strict fresh-print rule in the signal frames and the
   execution path.
3. Reach 60 complete sessions before another preliminary comparison;
   prefer 100 or more across calm, trending and gap regimes.
4. Keep Strategy 10 out until genuine depth and aggressor data exist.
5. Re-run this audit and compare the execution-only and strict arms on
   the larger sample before any production discussion.

## Reproducibility

- Command: `python scripts/backtest_forensic_audit.py --from-store 20`
- Workflow run: https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/runs/42458265177
- Replay seconds: 365.94
- Sessions: 2026-10-12, 2026-10-15, 2026-10-16, 2026-10-19, 2026-10-20, 2026-10-21, 2026-10-22, 2026-10-23, 2026-10-26, 2026-10-27, 2026-10-28, 2026-10-29, 2026-10-30, 2026-11-02, 2026-11-03, 2026-11-04, 2026-11-05, 2026-11-06
- Corrected ledger: `data/research/eleven_corrected_trades.csv`
- Execution-only ledger: `data/research/eleven_execution_corrected_trades.csv`
- Machine-readable audit: `data/research/backtest_forensic_audit.json`
- Data quality report: `reports/2026-11-08-intraday-data-quality.md`
- Corrected performance report: `reports/2026-11-08-eleven-strategy-intraday-corrected.md`

## Limitations

- Only 5 complete sessions are available.
- The capture is a snapshot feed; a quiet symbol can have no fresh print
  in a minute, and the strict arm correctly refuses to turn that into a
  trade.
- The cost, slippage and CGT figures are assumptions from the repository
  configuration, not measured executions or a filed tax treatment.
- Partial fills, queue position and market impact are not modelled.
- Relative volume and the cross-sectional market return use the stored
  sessions only.
- No claim is made about live profitability, capacity or deployment.

## Final conclusion

**BACKTEST INVALID, CORRECTIONS REQUIRED**

Corrected dataset: **DATA INSUFFICIENT FOR VALID STRATEGY COMPARISON**.
No production signal is activated.

Existing backtest: **BACKTEST INVALID, CORRECTIONS REQUIRED**.
