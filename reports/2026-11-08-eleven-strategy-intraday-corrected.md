# Corrected eleven strategy intraday performance

Generated 2026-11-08T12:19:40.387478+05:00 (Asia/Karachi).

## Status

Existing backtest: **BACKTEST INVALID, CORRECTIONS REQUIRED**.
Corrected dataset: **DATA INSUFFICIENT FOR VALID STRATEGY COMPARISON**.

No strategy is called profitable. The corrected sample is
5 complete sessions of the required
60, so the comparison is stopped.

## Corrected arms

The primary corrected run uses the strict signal frames and the genuine
execution path. The execution-only run keeps the original signal frames and
changes only execution. Both are shown so the effect of the data defect is
not confused with the effect of the strategy.

| # | Strategy | Trades | Win rate | Target first | Gross exp | Net before CGT | Net exp | Profit factor | Max DD | 95% CI net |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0 | Current bot: 1m Kalman Trend fresh flip | 15 | +20.00% | +20.00% | -0.17% | -0.82% | -0.86% | 0.2113 | -11.60% | -1.38% to -0.29% |
| 1 | EMA 20/50 + RSI pullback | 9 | +11.11% | +0.00% | -0.33% | -0.98% | -0.98% | 0.0124 | -8.00% | -1.34% to -0.59% |
| 2 | VWAP reclaim + relative volume | 8 | +0.00% | +0.00% | -0.18% | -0.83% | -0.83% | 0.0 | -5.87% | -1.23% to -0.47% |
| 3 | Kalman 1H/15M + VWAP + relative strength | 11 | +27.27% | +9.09% | +0.02% | -0.63% | -0.65% | 0.166 | -5.70% | -1.15% to -0.12% |
| 4 | Donchian breakout + ATR + relative volume | 4 | +0.00% | +0.00% | -0.35% | -1.00% | -1.00% | 0.0 | -3.44% | -1.67% to -0.33% |
| 5 | Supertrend + ADX + volume expansion | 8 | +25.00% | +12.50% | +0.57% | -0.07% | -0.12% | 0.6918 | -1.98% | -0.72% to +0.48% |
| 6 | Bollinger squeeze + volume breakout | 1 | +0.00% | +0.00% | +0.09% | -0.56% | -0.56% | 0.0 | +0.00% | n/a |
| 7 | RSI reversal + EMA 50 support | 5 | +20.00% | +0.00% | -0.21% | -0.85% | -0.86% | 0.0475 | -2.88% | -1.51% to -0.21% |
| 8 | Opening range breakout + VWAP | 5 | +20.00% | +20.00% | -0.11% | -0.76% | -0.80% | 0.2235 | -4.41% | -1.55% to +0.20% |
| 9 | Relative strength rotation | 11 | +18.18% | +0.00% | -0.26% | -0.90% | -0.92% | 0.114 | -9.98% | -1.45% to -0.35% |
| 10 | Order book imbalance + VWAP + intensity | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

Strategy 10 is not tested: the capture does not carry top-five depth or a
reliable aggressor sequence.

## Complete-session subset

| # | Strategy | Complete trades | Net exp | Target first | 95% CI |
|---|---|---:|---:|---:|---|
| 0 | Current bot: 1m Kalman Trend fresh flip | 5 | -0.83% | +20.00% | -1.64% to +0.16% |
| 1 | EMA 20/50 + RSI pullback | 1 | +0.11% | +0.00% | n/a |
| 2 | VWAP reclaim + relative volume | 4 | -0.82% | +0.00% | -1.40% to -0.41% |
| 3 | Kalman 1H/15M + VWAP + relative strength | 5 | -0.50% | +0.00% | -1.12% to +0.04% |
| 4 | Donchian breakout + ATR + relative volume | 1 | -1.70% | +0.00% | n/a |
| 5 | Supertrend + ADX + volume expansion | 4 | -0.01% | +25.00% | -0.62% to +0.79% |
| 6 | Bollinger squeeze + volume breakout | 1 | -0.56% | +0.00% | n/a |
| 7 | RSI reversal + EMA 50 support | 2 | -0.79% | +0.00% | -1.79% to +0.22% |
| 8 | Opening range breakout + VWAP | 4 | -1.29% | +0.00% | -1.67% to -0.90% |
| 9 | Relative strength rotation | 5 | -0.96% | +0.00% | -1.80% to -0.12% |
| 10 | Order book imbalance + VWAP + intensity | 0 | n/a | n/a | n/a |

## What changed

- Carried and stale minutes are no longer executable. The strict run also
  keeps them out of the 5m, 15m and 1h signal frames.
- The entry minute's own high and low are checked; the stop wins a tie.
- A last-print exit is dated from the print, not from the 15:30 boundary.
- A session is complete only when the capture starts before the open and
  ends at the close. The original report's 13 full sessions are not
  supported by its own first-observation column; five sessions are
  complete, 2026-11-04 starts before the open but ends at 15:24, and
  2026-11-06 is two minutes late on a Friday.
- Gross, cost, CGT and net are reported separately. The 15% CGT is an
  assumption, not a measured tax determination.
- Costs remain the repository model: 22.4 bps per side plus 10 bps
  modelled slippage per side, with 15% CGT on positive net returns.

## Limitation

These are descriptive corrected results on a small, partial sample. They
do not establish an edge, validate a strategy or justify a production
change. The next comparison is blocked until 60 complete sessions exist.
