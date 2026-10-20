# ICT/SMC intraday replacement

Version: ict_smc_sweep_mss_fvg_retest_v1. Time: Asia/Karachi (UTC+5).

## Scope

KMIALL constituent stocks, long only, paper signals only, at most one entry
per Karachi day. No broker login, order placement, shorting, leverage or
margin. The historical momentum_scanner import name remains for callers;
its momentum, RSI entry gates, score and AI routing have been removed.
Historical EOD studies and the HCAR diagnostic remain explicitly historical.
Their performance is not evidence for this strategy.

## Frozen entry rules

Use completed one-minute OHLCV bars from the current PSX band only. Never
bridge Friday's break or a missing minute. Require 20 contiguous bars,
price at least PKR 1, session observed turnover at least PKR 5 million, and
a last completed bar no more than 60 seconds old. No new entries in the last
30 minutes of a band. Existing universe coverage and volume-quality checks
remain, and broad median selloffs below -1% veto longs. Breadth is context,
not the retired momentum breadth trigger.

1. Confirm strict swing highs/lows with two bars on each side. Confirmation
   becomes available after the second right-hand bar closes, never at the
   plotted pivot time. Tied extrema are not pivots.
2. Within 30 bars, price must sweep an untouched confirmed low by at least
   PKR 0.01 and close back above that level. Freeze the latest confirmed
   swing high as the structure threshold before the sweep.
3. Within four bars, a bullish displacement must close above that threshold,
   have body at least the preceding 14-bar mean true range and close in the
   upper quarter of its range. Displacement volume must be at least 1.5 times
   the preceding median bar volume. A preceding down candle identifies the
   bullish order-block price zone; it is not evidence of institutional orders.
4. The displacement is the middle candle of a bullish three-candle fair-value
   gap: the third low exceeds the first high by at least a tick and 0.01% of
   the signal price. The gap becomes known only after its third candle closes.
5. The first subsequent retracement, within five bars, must intersect the gap,
   close bullish above its midpoint, and not close more than 0.1% above its
   top. No earlier mitigation or structural failure is allowed.
6. Entry is that latest completed retest CLOSE, a paper reference observable
   now, never a retrospectively filled midpoint limit. It must be in discount
   below the midpoint of the pre-sweep dealing range.
7. Stop reference is the sweep low minus PKR 0.01. Entry-to-stop risk must be
   0.1% to 1.2%. Modelled net reward / cost-inclusive risk must be at least 1.
   The nearest untouched confirmed overhead swing must exceed the 2% target
   plus modelled round-trip friction. No target room means no signal.

All thresholds are hypotheses fixed before evaluation, not tuned promises.
The score ranks displacement, volume confirmation and reward/risk. It is not
an estimated winning probability. The old daily-model prior cannot create,
promote or veto a setup.

## Exit and accounting

Target = recorded entry * 1.02, rounded to four decimals, a gross reference.
It is not a claim of 2% net profit. A subsequent completed bar touching the
stop and target is stop-first. Stops gapping lower use the worse bar open;
target touches use the target reference, not the touching bar close. Bars
preceding the signal cannot count as exits. A structural stop closes the
paper position without releasing the persisted/shared one-trade daily lock.
At session end use an actual final bar; missing close data stays unverifiable.
Old open positions keep their saved version and target; no new stop is
retroactively invented for them.

Costs remain the explicit project assumptions: 22.4 bps fees plus 10 bps
slippage per side, and 15% tax on positive net returns. Actual fees/taxes,
spreads, queues, circuit limits, source rights and execution are not inferred
from OHLC. Tick size is the configurable research reference PKR 0.01, not a
substitute for an instrument-specific execution check.

## Validation

The unit suite exercises positive and negative sequences, pivot availability,
incomplete minutes, future-prefix invariance, absent volume, target room,
first mitigation, Friday boundaries, target/stop ties, gaps and daily locks.
The actual servlet and tape loaders run the full paper pipeline fixture.
Fixtures are synthetic and never included in a performance denominator.

The manual/PR cloud workflow replays retained real tape_bars archives through
the same scanner on prefixes. It records input hashes, current-membership
bias, conflicting archives, scan count, timing, unresolved exits, net returns,
and the final chronological third separately without parameter tuning. It
never posts signals, claims a day, or mutates live research history. Missing
real bars fails the research job rather than producing a fictitious result.
The prospective production evidence gate remains required to establish an
edge; no new strategy inherits the predecessor's validation record.

## References

- PSX sessions: https://psx.com.pk/psx/exchange/general/trading-hours
- PSX rules: https://www.psx.com.pk/psx/regulations/legal-framework
- Causal bar/fill semantics: https://www.tradingview.com/pine-script-docs/concepts/strategies/

ICT/SMC terminology describes price patterns. It does not guarantee a winning
signal or a 2% move. Results, including no signals and losing signals, must be
measured and reported, never fabricated to satisfy a target.
