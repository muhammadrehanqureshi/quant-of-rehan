# Intraday 100: ten-architecture pilot and cost-wall verdict

Generated 2026-11-13. Scope: the pre-registered ten-strategy pilot on the
KMIALL 5m/15m/30m/60m intraday archive. This is **not** the final
100-strategy ranking. The locked test period was not read.

## Status

- Data audit: complete. The archive is structurally clean but sparse in
  5m coverage and zero-volume bars.
- Execution engine: complete and tested for next-bar entry, same session
  band, one trade per day, stop-before-target, forced band close, costs,
  CGT, liquidity and gap screens.
- Pilot: 10 architectures x 4 native timeframes = 40 strategy-timeframe
  cells. **Zero cells have positive net expectancy.**
- Full 100 catalog: **not run**. The pilot gate failed before the
  expensive stage.
- Locked test 2025-07-01 to 2026-11-13: **untouched**.
- No production signal, broker, Android or scanner path was changed.

## Data actually used

| timeframe | rows loaded (development) | symbols | valid session bars | development dates |
|---|---:|---:|---:|---|
| 5m | 8,786,185 | 295 | 8,360,645 | 2021-11-15 to 2025-06-30 |
| 15m | 3,623,254 | 295 | 3,309,759 | 2021-11-15 to 2025-06-30 |
| 30m | 2,045,656 | 295 | 1,738,608 | 2021-11-15 to 2025-06-30 |
| 60m | 1,232,265 | 295 | 828,902 | 2021-11-15 to 2025-06-30 |

The full archive audit covers 2021-11-15 to 2026-11-12: 14,495,663 5m
rows, 312 symbols, 1,238 sessions, 774,926 invalid 5m bars, 5,217,429
zero-volume 5m rows, and 121 symbols below 50 percent median 5m
coverage. The audit's structural checks found zero duplicate timestamps,
zero off-grid rows, zero invalid OHLC, zero negative volume and zero
non-positive prices. The detailed evidence is in
`data/research_download/audit/DATA_QUALITY_REPORT.md`; the cloud source
is Actions run 43382889771.

Median 5m symbol coverage by year is 55.4 percent (2021), 50.7 (2022),
61.1 (2023), 78.9 (2024), 91.7 (2025) and 93.4 (2026). This is why the
5m result is not treated as a complete-market result.

## Execution and cost law

- Capital PKR 10,000,000; notional PKR 1,000,000 per trade, 10 percent.
- Long only. No leverage, margin, futures, options or overnight holding.
- One trade per strategy per Karachi session.
- Entry at the next bar open after the signal bar closes, with a
  15 percent maximum entry gap.
- Stop checked before target. Positions close at the session band close.
- 5m/15m/30m/60m only; no 1m archive exists.
- Cost 32.4 bps all-in per side (22.4 bps commission and tax plus 10 bps
  slippage) plus 5.0 bps spread per side. Round trip 0.748 percent before
  CGT; 15 percent CGT on positive net returns.
- Prior 20-bar median turnover must be at least PKR 1,000,000.
- Round-trip cost on PKR 1,000,000 is PKR 7,480. A rule needs roughly
  0.75 percent gross just to break even, or about 0.88 percent gross to
  net +0.1 percent after CGT.

## Five-minute full result

| ID | Family | Trades | Net return | Net expectancy | Win rate | Validation expectancy | Validation trades |
|---|---|---:|---:|---:|---:|---:|---:|
| P01 | A trend | 695 | -59.500% | -0.8561% | 20.3% | -0.7931% | 234 |
| P02 | F structure | 828 | -67.930% | -0.8204% | 18.1% | -0.9305% | 240 |
| P03 | C reversion | 486 | -32.342% | -0.6655% | 15.6% | -0.6367% | 191 |
| P04 | D volume | 772 | -64.252% | -0.8323% | 17.4% | -0.9162% | 240 |
| P05 | E volatility | 646 | -53.129% | -0.8224% | 18.3% | -0.7852% | 234 |
| P06 | F structure | 794 | -71.977% | -0.9065% | 22.7% | -1.0075% | 241 |
| P07 | G statistical | 386 | -24.512% | -0.6350% | 14.0% | -0.6575% | 163 |
| P08 | B momentum | 840 | -66.940% | -0.7969% | 21.7% | -0.8174% | 243 |
| P09 | I hybrid | 746 | -62.808% | -0.8419% | 20.6% | -0.8048% | 242 |
| P10 | I hybrid | 363 | -23.342% | -0.6430% | 14.6% | -0.6452% | 145 |

P01 is EMA plus Donchian; P02 is opening-range breakout; P03 is VWAP
z-score reversion; P04 is VWAP reclaim with volume; P05 is a volatility
squeeze breakout; P06 is prior-session-high reclaim; P07 is
trend-filtered residual reversion; P08 is positive statistical momentum;
P09 is trend/volume/volatility agreement; P10 is reversion inside a
positive regime.

## The only positive gross results

The 5m trade file separates gross from net. Three reversion rules have a
small positive gross expectancy before costs:

| ID | Average gross per trade | Average net per trade | Round-trip cost | Target exits | Stop exits | Time exits |
|---|---:|---:|---:|---:|---:|---:|
| P03 | **+0.095%** | -0.665% | 0.748% | 9.1% | 21.8% | 69.1% |
| P07 | **+0.125%** | -0.635% | 0.748% | 9.3% | 18.7% | 72.0% |
| P10 | **+0.116%** | -0.643% | 0.748% | 8.0% | 18.7% | 73.3% |

This is the central finding. The mean-reversion family is not obviously
random: it earns a small gross concession. But the concession is about
one-sixth of the round trip, so the strategy loses roughly PKR 6,300 to
6,650 per PKR 1,000,000 trade after cost. The other seven rules are
negative both gross and net. The target floor of 1.5 percent was set
above the cost, but only 8 to 9 percent of reversion trades reach it;
most exit on time with a small gross gain that costs consume.

## Timeframe sensitivity

| timeframe | trades per strategy | best net expectancy | best strategy | best validation expectancy | worst net expectancy |
|---|---:|---:|---|---:|---:|
| 5m | 363 to 840 | **-0.6350%** | P07 | -0.6575% | -0.9065% (P06) |
| 15m | 193 to 764 | -0.6733% | P10 | -0.6476% | -1.0369% (P06) |
| 30m | 76 to 637 | -0.7679% | P10 | -0.8522% | -1.0322% (P03) |
| 60m | 11 to 398 | -0.6863% | P07 | -0.7132% | -1.1423% (P06) |

Higher timeframes do not rescue the rules. They cut trade count and
raise the loss per trade. At 60m, P03 has only 11 trades and P10 34, so
the 60m sample is too thin to support any claim in either direction.
Every one of the 40 cells is net negative.

## Why the full 100 was not executed

The pilot was deliberately a gate, not a formality. It covered nine of
the ten families: trend (A), momentum (B), mean reversion (C), volume and
liquidity (D), volatility (E), market structure (F), statistical (G) and
hybrids (I). The machine-learning family (H) was not represented. Ten
hand-built rules across those families, at four timeframes, all lost
after cost. Running 90 more fixed-target 5m variants would produce a
longer ranking of the same cost-negative geometry, not evidence of an
edge. The assignment's own rule applies: prefer a small number of robust
strategies over 100 impressive but unreliable backtests, and do not
manufacture a winner.

The 100-architecture catalog, walk-forward table, out-of-sample table,
combination table and final rankings are therefore **not delivered**.
Delivering them with 10 tested specs and 90 untested names would be a
false claim. The locked test remains untouched, so it can still be spent
once, legitimately, if a later candidate clears the cost gate in
discovery.

## What would have to change

The next research gate is not another 5m indicator threshold. It is one
of these, pre-registered before looking at validation:

1. **Exit geometry that gives the gross move room to exceed 0.9
   percent.** A reversion rule with a 1.5 percent target and a 0.8
   percent stop spends most of its life in the time exit. A session-close
   or volatility-scaled exit needs its own test, including the tail risk
   of holding to the close without a stop.
2. **A genuinely different information source.** The H family
   (walk-forward gradient boosting, random forest, logistic, regime
   models) is the only pilot family not tested. It must be trained on
   discovery only and scored once on validation.
3. **A higher gross-move universe.** The 5m archive is dominated by
   zero-volume bars and low turnover. A turnover and volatility bucket
   analysis should establish whether any liquid subset produces gross
   moves large enough to pay 0.748 percent.
4. **Cost sensitivity.** Report the break-even cost for every candidate.
   A rule that needs costs below 20 bps per side is not executable on
   this market, regardless of its backtest.

Until one of those clears the gate, the evidence says the current
long-only intraday design on KMIALL has no defensible net edge.

## Evidence

- 5m pilot: Actions run 43384732181, artifact
  `intraday100-pilot-43384732181`, local
  `data/research_download/pilot_realism/`.
- 15m pilot: Actions run 43392819433, artifact
  `intraday100-pilot-15m-43392819433`.
- 30m pilot: Actions run 43392826746, artifact
  `intraday100-pilot-30m-43392826746`.
- 60m pilot: Actions run 43392627912, artifact
  `intraday100-pilot-60m-43392627912`.
- Audit: Actions run 43382889771, artifact
  `intraday100-audit-43382889771`.
- Engine and tests: `src/research/intraday100/`,
  `tests/test_intraday100.py`; CLI `scripts/intraday100.py`; workflow
  `.github/workflows/intraday-100.yml`.

## Limitations

- No historical KMIALL membership; the current 319-symbol universe is
  applied backward. This is survivorship-biased.
- No corporate-action file; large gaps are screened, not adjusted.
- No historical quotes; spread and slippage are explicit proxies.
- The 5m archive has 36 percent zero-volume rows and only 295 symbols in
  the development window; results are not a complete-market tape.
- The pilot is exploratory and cannot establish a production edge.
- The only local processing used to inspect the downloaded pilot CSV
  was a shell aggregation; no Python, backtest, test or formatter was run
  on the owner's PC. All backtests ran on GitHub Actions.
