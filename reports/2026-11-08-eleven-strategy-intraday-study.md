# KMIALLSHR eleven strategy intraday study

Prepared for Mr. Rehan, 2026-11-08 (Asia/Karachi).

This is the written result of the cloud study requested on 2026-11-08: test the
current intraday signal bot plus ten new intraday long strategies on the last
three years of KMIALLSHR data, with +2.00% target, -1.00% stop, one BUY
candidate per strategy per day, and an intraday exit.

Nothing in the live bot, its schedule or its configuration was changed. Every
number below was produced in GitHub Actions, never on the owner's PC (SO-23).

## Study identity

| Item | Value |
|---|---|
| Study id | `eleven_intraday_study_v1` and `eleven_daily_context_v1` |
| Cloud run | https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/runs/42448818204 |
| Run duration | 3 min 44 s, including the three-year daily context phase |
| Code | `scripts/backtest_eleven_intraday.py`, `scripts/backtest_eleven_context.py` |
| Workflow | `.github/workflows/backtest.yml`, task `eleven`, manual dispatch only |
| Study PR | #320, merged |
| Repair PR | #321, merged as `9662482` |
| Raw report | `data/research/eleven_run/eleven-intraday-42448818204/eleven_intraday.json` |
| Trade ledger | `data/research/eleven_run/eleven-intraday-42448818204/eleven_intraday_trades.csv` |
| Daily context | `data/research/eleven_run/eleven-daily-context-42448818204/eleven_daily_context.json` |

## 1. The headline

Eleven strategies were specified. Ten could be tested. None of the ten has a
positive net expectancy on the intraday data that exists. Strategy 10 (order
book imbalance) could not be tested without fabricating data and is reported as
not tested.

| # | Strategy | Trades | Win rate | Expectancy per trade | Total net | Profit factor | Max drawdown |
|---|---|---|---|---|---|---|---|
| 0 | Current bot, 1m Kalman fresh flip | 15 | 20.0% | -0.707% | -10.60% | 0.42 | -10.64% |
| 1 | EMA 20/50 + RSI pullback | 15 | 20.0% | -1.087% | -16.31% | 0.13 | -16.31% |
| 2 | VWAP reclaim + relative volume | 8 | 25.0% | -0.958% | -7.66% | 0.20 | -8.12% |
| 3 | Kalman 1H/15M + VWAP + relative strength | 13 | 30.8% | -0.553% | -7.19% | 0.34 | -8.34% |
| 4 | Donchian + ATR + relative volume | 8 | 25.0% | -0.549% | -4.39% | 0.24 | -5.58% |
| 5 | Supertrend + ADX + volume | 9 | 33.3% | -0.408% | -3.67% | 0.43 | -5.14% |
| 6 | Bollinger squeeze breakout | 7 | 14.3% | -0.910% | -6.37% | 0.15 | -7.52% |
| 7 | RSI reversal + EMA50 support | 12 | 25.0% | -0.826% | -9.92% | 0.22 | -9.92% |
| 8 | Opening range + VWAP | 5 | 60.0% | -0.296% | -1.48% | 0.55 | -3.30% |
| 9 | Relative strength rotation | 15 | 26.7% | -0.665% | -9.98% | 0.33 | -10.43% |
| 10 | Order book imbalance | not tested | n/a | n/a | n/a | n/a | n/a |

Pooled across the ten tested arms: 107 trades, 28 wins (26.2%), 79 losses
(73.8%), a summed net of -77.57% of entry value, and an average trade of
-0.725%. The arms are independent hypotheticals, so the sum is not a portfolio
return, but it shows the direction and the size of the drag.

## 2. Data: what three years actually means here

The repository holds three years of daily bars but only the captured intraday
sessions. There is no historical 5m or 15m archive, so a true three-year
intraday backtest is impossible with this repository. The study therefore uses
every stored session that could be fetched and never pads a date range.

- Intraday window: 2026-10-12 to 2026-11-06.
- Intraday sessions tested: 18.
- Universe symbols: 317.
- Sessions per day with 1m bars: 292 to 312.
- Missing sessions inside the window: 2026-10-13 and 2026-10-14 (nothing in R2).
- Absent before the window: every date back to 2026-09-03.

### 2.1 Capture coverage

| Day | Capture size (chars) | Symbols with bars | 1m bars | Carried share | First observation | Volume available |
|---|---|---|---|---|---|---|
| 2026-10-12 | 23,243,780 | 299 | 39,373 | 19.38% | 10:24 | yes |
| 2026-10-15 | 474,547 | 312 | 611 | 0.00% | 17:45 | no |
| 2026-10-16 | 209,685,009 | 312 | 270,531 | 0.21% | 10:05 | yes |
| 2026-10-19 | 9,876,704 | 298 | 12,515 | 0.00% | 15:13 | yes |
| 2026-10-20 | 135,147,781 | 298 | 165,666 | 0.00% | 09:52 | yes |
| 2026-10-21 | 205,722,541 | 298 | 255,186 | 0.35% | 09:52 | yes |
| 2026-10-22 | 117,315,202 | 297 | 147,146 | 0.61% | 12:24 | yes |
| 2026-10-23 | 150,498,094 | 292 | 186,710 | 0.00% | 10:31 | yes |
| 2026-10-26 | 117,265,835 | 297 | 144,619 | 0.62% | 09:00 | yes |
| 2026-10-27 | 217,235,994 | 297 | 245,540 | 0.36% | 09:00 | yes |
| 2026-10-28 | 217,792,449 | 297 | 246,030 | 0.36% | 09:00 | yes |
| 2026-10-29 | 204,388,184 | 296 | 251,922 | 0.35% | 09:52 | yes |
| 2026-10-30 | 86,561,875 | 300 | 109,704 | 0.00% | 11:22 | yes |
| 2026-11-02 | 230,729,936 | 296 | 262,814 | 0.66% | 09:00 | yes |
| 2026-11-03 | 208,464,805 | 297 | 236,106 | 0.00% | 09:00 | yes |
| 2026-11-04 | 189,218,352 | 296 | 209,110 | 0.20% | 08:57 | yes |
| 2026-11-05 | 511,249,579 | 299 | 636,017 | 0.14% | 09:37 | yes |
| 2026-11-06 | 381,697,527 | 299 | 467,211 | 0.00% | 09:19 | yes |

A late first observation means the session is partial: 2026-10-15 has only a
handful of bars per symbol and no volume, 2026-10-19 starts at 15:13, 2026-10-22 at
12:24, 2026-10-30 at 11:22, and 2026-10-12 at 10:24 with 19.38% of prices
carried forward. Strategy 8 in particular can only trade sessions whose tape
starts at the open.

### 2.2 The trade law

- Direction: long only.
- Target: +2.00% from entry.
- Stop: -1.00% from entry.
- Maximum one BUY candidate per strategy per trading day.
- Entry: the first 1m open after the signal bar closes, never the signal
  candle's close.
- Exit: target, stop, or the band close, whichever comes first.
- When one bar touches both target and stop, the stop wins.
- When several symbols qualify in the same slot, the highest setup score is
  taken.

### 2.3 Costs as modeled

| Item | Value |
|---|---|
| Cost per side | 22.4 bps |
| Slippage per side | 10.0 bps |
| Round trip | 0.648% |
| Capital gains tax on gains | 15% |

So a clean target nets 2.00% - 0.648% - 15% x (2.00% - 0.648%) = **+1.1492%**,
and a clean stop nets -1.00% - 0.648% = **-1.6480%**.

That asymmetry sets the bar: break-even win rate is
`1.6480 / (1.1492 + 1.6480)` = **58.9%**. Every arm is far below it.

### 2.4 Exit reason definitions

| Reason | Meaning |
|---|---|
| `target` | Target touched inside a bar and filled at the target. |
| `target_gap` | The bar after entry opened beyond the target, filled at that better open. |
| `stop` | Stop touched inside a bar and filled at the stop. |
| `stop_gap` | The bar opened beyond the stop, filled at that worse open. |
| `session_end` | Closed at the band close with neither level hit. |
| `tape_end` | The tape ends before the band close and the position was closed at the last print. |

### 2.5 Metric definitions

All values are fractions of entry price, net of the cost model above.

- Expectancy: mean net return per trade.
- Total net: sum of net trade returns for that arm, not compounded.
- Profit factor: gross net wins divided by absolute gross net losses.
- Max drawdown: peak to trough of the arm's cumulative net curve.

## 3. Strategy-by-strategy results

### Strategy 0: current bot, 1m Kalman fresh flip

Replays the live candidate's one minute fresh-flip arm with the owner's fixed
+2% / -1% law. The four-frame VWAP pullback arm is not evaluated because its 1D
frame needs 40 completed daily bars and the band store holds only captured
sessions.

**What this arm actually traded.** The 1m Kalman trend flip, entered on the next
1m open, one name per day, highest score when several names flip together.

| Metric | Value |
|---|---|
| Trades | 15 (3 wins, 12 losses) |
| Win rate | 20.0% |
| Expectancy | -0.7066% |
| Median trade | -1.6480% |
| Total net | -10.5997% |
| Average win | +2.5842% |
| Average loss | -1.5294% |
| Profit factor | 0.42 |
| Best trade | +5.0256% (SYS, 2026-11-02, target gap) |
| Worst trade | -2.2921% (DOL, 2026-10-27, stop gap) |
| Max drawdown | -10.6423% |
| Average hold | 77.5 minutes |
| Exit mix | 4 session_end, 5 stop, 3 stop_gap, 3 target_gap |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-12 | OGDC | 302.02 | session_end | -1.35% |
| 2026-10-16 | NETSOL | 122.20 | session_end | -0.93% |
| 2026-10-20 | ACPL | 236.00 | session_end | -1.07% |
| 2026-10-21 | NML | 124.36 | stop_gap | -1.65% |
| 2026-10-22 | ENGROH | 252.75 | stop | -1.65% |
| 2026-10-23 | NRSL | 33.45 | stop | -1.65% |
| 2026-10-26 | ITANZ | 37.48 | target_gap | +1.31% |
| 2026-10-27 | DOL | 31.02 | stop_gap | -2.29% |
| 2026-10-28 | SAZEW | 1424.99 | target_gap | +1.42% |
| 2026-10-29 | DADX | 154.00 | stop | -1.65% |
| 2026-10-30 | EPCL | 31.50 | session_end | -1.12% |
| 2026-11-02 | SYS | 107.92 | target_gap | +5.03% |
| 2026-11-03 | GHNI | 1155.00 | stop_gap | -1.69% |
| 2026-11-05 | BPL | 62.55 | stop | -1.65% |
| 2026-11-06 | GAL | 559.99 | stop | -1.65% |

**Reading.** All three wins were gap fills through the target, including one
large SYS gap (+5.03%) that carries most of the arm's positive tail. Strip that
trade and the arm is -15.63%. The flip arm is a high-frequency knife: 5 clean
stops, 3 gap stops and 4 session closes, against 3 targets.

### Strategy 1: EMA 20/50 + RSI pullback

The 40 to 50 RSI pullback is the minimum 15m RSI over the last four bars,
followed by a cross above 50. The optional 1H EMA50 filter is not added as a
separate gate.

| Metric | Value |
|---|---|
| Trades | 15 (3 wins, 12 losses) |
| Win rate | 20.0% |
| Expectancy | -1.0874% |
| Median trade | -0.8758% |
| Total net | -16.3115% |
| Average win | +0.8032% |
| Average loss | -1.5601% |
| Profit factor | 0.13 |
| Best trade | +1.1492% (CLOV, 2026-11-03, target) |
| Worst trade | -4.1591% (JATM, 2026-11-05, stop gap) |
| Max drawdown | -16.3115% |
| Average hold | 127.8 minutes |
| Exit mix | 7 session_end, 3 stop, 3 stop_gap, 2 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-16 | WAFI | 154.50 | session_end | -0.47% |
| 2026-10-20 | SLGL | 15.10 | stop_gap | -2.83% |
| 2026-10-21 | SLM | 21.95 | session_end | -0.88% |
| 2026-10-22 | EFERT | 194.40 | session_end | -0.61% |
| 2026-10-23 | SLGL | 15.85 | stop | -1.65% |
| 2026-10-26 | NRSL | 32.89 | stop_gap | -2.38% |
| 2026-10-27 | ARCTM | 80.00 | stop | -1.65% |
| 2026-10-28 | THCCL | 70.14 | stop | -1.65% |
| 2026-10-29 | OGDC | 306.65 | session_end | -0.58% |
| 2026-10-30 | MLCF | 90.99 | session_end | -1.13% |
| 2026-11-02 | HUBC | 193.89 | session_end | +0.11% |
| 2026-11-03 | CLOV | 6.39 | target | +1.15% |
| 2026-11-04 | NML | 125.00 | target | +1.15% |
| 2026-11-05 | JATM | 76.90 | stop_gap | -4.16% |
| 2026-11-06 | GLAXO | 337.21 | session_end | -0.74% |

**Reading.** The worst result of the eleven. It trades often, holds long, and
seven of fifteen trades simply die at the close, so the 0.648% cost is paid on a
flat move. The two targets are the minimum win, and one JATM gap cost 4.16%,
which is more than three clean wins.

### Strategy 2: VWAP reclaim + relative volume

The reclaim bar is a 5m close above session VWAP after the prior 5m close was at
or below it; the following 5m bar closing above VWAP is the hold. A separate
retest is not required.

| Metric | Value |
|---|---|
| Trades | 8 (2 wins, 6 losses) |
| Win rate | 25.0% |
| Expectancy | -0.9580% |
| Median trade | -1.1195% |
| Total net | -7.6637% |
| Average win | +0.9681% |
| Average loss | -1.6000% |
| Profit factor | 0.20 |
| Best trade | +1.4831% (KOHC, 2026-11-04, target gap) |
| Worst trade | -3.5882% (PREMA, 2026-10-29, stop gap) |
| Max drawdown | -8.1168% |
| Average hold | 79.0 minutes |
| Exit mix | 3 session_end, 2 stop, 2 stop_gap, 1 target_gap |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-27 | NML | 122.05 | session_end | -0.44% |
| 2026-10-28 | FCCL | 52.67 | session_end | -0.59% |
| 2026-10-29 | PREMA | 31.63 | stop_gap | -3.59% |
| 2026-11-02 | CPHL | 61.52 | stop | -1.65% |
| 2026-11-03 | CNERGY | 12.48 | stop_gap | -1.69% |
| 2026-11-04 | KOHC | 89.85 | target_gap | +1.48% |
| 2026-11-05 | ICL | 139.90 | stop | -1.65% |
| 2026-11-06 | FANM | 12.70 | session_end | +0.45% |

**Reading.** Only 8 setups in 18 sessions, and two of the three losses worse
than a clean stop were gaps. The reclaim rule is selective but the winners are
too small to carry the gaps.

### Strategy 3: Kalman 1H/15M + VWAP + relative strength

The market leg of RS20 is the equal weight mean return of the captured KMIALL
symbols, not the KMIALLSHR index level. The 15M and 1H Kalman filters use the
same Q/R/threshold as the live 1m filter.

| Metric | Value |
|---|---|
| Trades | 13 (4 wins, 9 losses) |
| Win rate | 30.8% |
| Expectancy | -0.5529% |
| Median trade | -0.6480% |
| Total net | -7.1876% |
| Average win | +0.9433% |
| Average loss | -1.2179% |
| Profit factor | 0.34 |
| Best trade | +1.1492% (DNCC, 2026-10-21, target) |
| Worst trade | -2.8505% (UPFL, 2026-10-22, stop gap) |
| Max drawdown | -8.3368% |
| Average hold | 122.3 minutes |
| Exit mix | 5 session_end, 3 stop, 1 stop_gap, 1 tape_end, 3 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-21 | DNCC | 20.40 | target | +1.15% |
| 2026-10-22 | UPFL | 30675.62 | stop_gap | -2.85% |
| 2026-10-23 | SZTM | 132.52 | stop | -1.65% |
| 2026-10-26 | THCCL | 71.00 | target | +1.15% |
| 2026-10-27 | SZTM | 153.01 | target | +1.15% |
| 2026-10-28 | AIRLINK | 121.40 | stop | -1.65% |
| 2026-10-29 | OGDC | 306.65 | session_end | -0.58% |
| 2026-10-30 | MEBL | 528.74 | session_end | -0.65% |
| 2026-11-02 | CLOV | 6.64 | stop | -1.65% |
| 2026-11-03 | LPGL | 95.61 | session_end | -0.65% |
| 2026-11-04 | HUBC | 201.70 | tape_end | +0.33% |
| 2026-11-05 | FANM | 11.68 | session_end | -0.65% |
| 2026-11-06 | BPL | 68.19 | session_end | -0.65% |

**Reading.** The best of the trend following arms on accuracy (30.8%), but every
non-target win is smaller than the cost-adjusted target and four closes were
exactly flat, each paying -0.648%. Three clean targets is not enough.

### Strategy 4: Donchian breakout + ATR + relative volume

ATR must expand against its prior 20 bar average. The suggested 0.25% to 0.90%
normalized ATR band is not used as a hard gate, as the specification calls it a
research range.

| Metric | Value |
|---|---|
| Trades | 8 (2 wins, 6 losses) |
| Win rate | 25.0% |
| Expectancy | -0.5491% |
| Median trade | -0.5113% |
| Total net | -4.3926% |
| Average win | +0.6998% |
| Average loss | -0.9654% |
| Profit factor | 0.24 |
| Best trade | +1.1913% (LOADS, 2026-10-27, target gap) |
| Worst trade | -1.6480% (SSOM, 2026-10-28, stop) |
| Max drawdown | -5.5839% |
| Average hold | 180.9 minutes |
| Exit mix | 4 session_end, 2 stop, 1 tape_end, 1 target_gap |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-27 | LOADS | 11.71 | target_gap | +1.19% |
| 2026-10-28 | SSOM | 420.07 | stop | -1.65% |
| 2026-10-29 | MLCF | 91.80 | stop | -1.65% |
| 2026-11-02 | FCEPL | 137.90 | session_end | -1.37% |
| 2026-11-03 | ENGROH | 263.48 | session_end | -0.37% |
| 2026-11-04 | FFC | 578.83 | tape_end | -0.10% |
| 2026-11-05 | OGDC | 312.40 | session_end | +0.21% |
| 2026-11-06 | FANM | 12.85 | session_end | -0.65% |

**Reading.** Smallest trade count with the longest holds (181 minutes average).
Breakouts that survived the entry usually stalled, and four of eight exits were
the band close, not a level.

### Strategy 5: Supertrend + ADX + volume

The continuation variant is tested: any bullish Supertrend with ADX above 20,
+DI above -DI and the volume floor qualifies. The separate controlled pullback
qualifier is not enforced.

| Metric | Value |
|---|---|
| Trades | 9 (3 wins, 6 losses) |
| Win rate | 33.3% |
| Expectancy | -0.4075% |
| Median trade | -0.6480% |
| Total net | -3.6677% |
| Average win | +0.9227% |
| Average loss | -1.0726% |
| Profit factor | 0.43 |
| Best trade | +1.1492% (CLOV, 2026-11-02, target) |
| Worst trade | -1.7014% (FFL, 2026-10-29, stop gap) |
| Max drawdown | -5.1398% |
| Average hold | 134.2 minutes |
| Exit mix | 4 session_end, 2 stop, 1 stop_gap, 1 tape_end, 1 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-27 | NETSOL | 120.64 | session_end | -0.14% |
| 2026-10-28 | SZTM | 171.94 | stop | -1.65% |
| 2026-10-29 | FFL | 13.29 | stop_gap | -1.70% |
| 2026-10-30 | MACFL | 50.52 | stop | -1.65% |
| 2026-11-02 | CLOV | 6.55 | target | +1.15% |
| 2026-11-03 | OML | 125.00 | session_end | +0.56% |
| 2026-11-04 | FCCL | 55.89 | tape_end | +1.06% |
| 2026-11-05 | FANM | 11.68 | session_end | -0.65% |
| 2026-11-06 | BPL | 68.19 | session_end | -0.65% |

**Reading.** Second best of the ten and the best profit factor among the trend
arms (0.43), but it still needs roughly one more target per nine trades to break
even. Its edge, such as it is, comes from a 1.06% tape-end win on FCCL and a
0.56% close on OML.

### Strategy 6: Bollinger squeeze + volume breakout

Squeeze is 15m band width below its own 20th percentile over the previous 100
observations. "1H not bearish" means 1H close above the 1H EMA50.

| Metric | Value |
|---|---|
| Trades | 7 (1 win, 6 losses) |
| Win rate | 14.3% |
| Expectancy | -0.9102% |
| Median trade | -1.1953% |
| Total net | -6.3714% |
| Average win | +1.1492% |
| Average loss | -1.2534% |
| Profit factor | 0.15 |
| Best trade | +1.1492% (DNCC, 2026-11-05, target) |
| Worst trade | -1.7508% (FCCL, 2026-10-29, stop gap) |
| Max drawdown | -7.5206% |
| Average hold | 67.1 minutes |
| Exit mix | 4 session_end, 1 stop, 1 stop_gap, 1 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-28 | FCCL | 52.99 | session_end | -1.20% |
| 2026-10-29 | FCCL | 53.50 | stop_gap | -1.75% |
| 2026-10-30 | GHNI | 1169.00 | session_end | -0.56% |
| 2026-11-02 | ITANZ | 35.13 | session_end | -1.02% |
| 2026-11-03 | FATIMA | 138.98 | session_end | -1.35% |
| 2026-11-04 | JVDC | 130.50 | stop | -1.65% |
| 2026-11-05 | DNCC | 23.20 | target | +1.15% |

**Reading.** The worst hit rate (14.3%) and the lowest profit factor (0.15). A
squeeze breakout needs a large move to pay, and in this sample four of seven
breakouts failed without even reaching the stop.

### Strategy 7: RSI reversal + EMA50 support

The 15m RSI must have touched 30 to 45 in the last five bars and cross back
above 45. The 1H positive trend is 1H close above the 1H EMA50.

| Metric | Value |
|---|---|
| Trades | 12 (3 wins, 9 losses) |
| Win rate | 25.0% |
| Expectancy | -0.8263% |
| Median trade | -1.3718% |
| Total net | -9.9150% |
| Average win | +0.9094% |
| Average loss | -1.4048% |
| Profit factor | 0.22 |
| Best trade | +1.1492% (SZTM, 2026-10-23, target) |
| Worst trade | -1.9236% (SZTM, 2026-11-05, stop gap) |
| Max drawdown | -9.9150% |
| Average hold | 89.3 minutes |
| Exit mix | 4 session_end, 3 stop, 3 stop_gap, 2 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-21 | NML | 124.00 | stop_gap | -1.66% |
| 2026-10-23 | SZTM | 121.50 | target | +1.15% |
| 2026-10-26 | MARI | 627.50 | session_end | +0.43% |
| 2026-10-27 | ASTM | 59.00 | stop | -1.65% |
| 2026-10-28 | MARI | 635.99 | stop_gap | -1.75% |
| 2026-10-29 | MARI | 635.00 | session_end | -0.41% |
| 2026-10-30 | MLCF | 90.75 | session_end | -0.87% |
| 2026-11-02 | GHNI | 1140.00 | target | +1.15% |
| 2026-11-03 | TREET | 23.53 | stop | -1.65% |
| 2026-11-04 | THCCL | 73.15 | stop | -1.65% |
| 2026-11-05 | SZTM | 156.00 | stop_gap | -1.92% |
| 2026-11-06 | PPL | 219.00 | session_end | -1.10% |

**Reading.** Three stops and three gap stops against two targets. The reversal
entry is frequently early, and the average loss (-1.40%) is more than the law's
clean stop because of gaps.

### Strategy 8: Opening range breakout + VWAP

The opening range is the first complete 15m bar at the band open. A session
whose tape starts after the open has no opening range and cannot signal that
day.

| Metric | Value |
|---|---|
| Trades | 5 (3 wins, 2 losses) |
| Win rate | 60.0% |
| Expectancy | -0.2962% |
| Median trade | +0.3013% |
| Total net | -1.4809% |
| Average win | +0.6050% |
| Average loss | -1.6480% |
| Profit factor | 0.55 |
| Best trade | +1.1492% (LUCK, 2026-11-04, target) |
| Worst trade | -1.6480% (SEARL, 2026-10-28, stop) |
| Max drawdown | -3.2960% |
| Average hold | 184.6 minutes |
| Exit mix | 2 session_end, 2 stop, 1 target |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-27 | GCIL | 32.50 | session_end | +0.36% |
| 2026-10-28 | SEARL | 75.10 | stop | -1.65% |
| 2026-11-02 | CNERGY | 12.48 | stop | -1.65% |
| 2026-11-03 | EFERT | 199.50 | session_end | +0.30% |
| 2026-11-04 | LUCK | 406.00 | target | +1.15% |

**Reading.** The best hit rate and the smallest loss, but only five trades
because partial tapes kill the opening range. Its wins average only +0.61%
against -1.65% losses, so a 60% hit rate still loses money. Two more targets in
five would have made it roughly break even, which is the clearest statement of
how tight the cost arithmetic is.

### Strategy 9: Relative strength rotation

RS8 and 1H RS use the equal weight mean of the captured KMIALL symbols as the
market. Standardisation is cross-sectional at each 15m timestamp, and the next
5m bar must close above the prior high.

| Metric | Value |
|---|---|
| Trades | 15 (4 wins, 11 losses) |
| Win rate | 26.7% |
| Expectancy | -0.6651% |
| Median trade | -1.6480% |
| Total net | -9.9763% |
| Average win | +1.2521% |
| Average loss | -1.3623% |
| Profit factor | 0.33 |
| Best trade | +2.2570% (CLOV, 2026-11-02, target gap) |
| Worst trade | -1.7539% (OML, 2026-10-28, stop gap) |
| Max drawdown | -10.4294% |
| Average hold | 56.8 minutes |
| Exit mix | 4 session_end, 4 stop, 4 stop_gap, 2 target, 1 target_gap |

| Day | Symbol | Entry | Exit | Net |
|---|---|---|---|---|
| 2026-10-16 | GCIL | 32.68 | session_end | -0.28% |
| 2026-10-20 | KPUS | 1424.99 | stop_gap | -1.70% |
| 2026-10-21 | HCAR | 208.19 | stop | -1.65% |
| 2026-10-22 | FPJM | 19.80 | stop_gap | -1.66% |
| 2026-10-23 | THCCL | 70.00 | target | +1.15% |
| 2026-10-26 | SZTM | 142.10 | session_end | -0.65% |
| 2026-10-27 | PREMA | 32.00 | target | +1.15% |
| 2026-10-28 | OML | 85.00 | stop_gap | -1.75% |
| 2026-10-29 | TGL | 172.88 | stop | -1.65% |
| 2026-10-30 | THCCL | 74.80 | stop_gap | -1.70% |
| 2026-11-02 | CLOV | 6.66 | target_gap | +2.26% |
| 2026-11-03 | OML | 126.63 | session_end | -0.65% |
| 2026-11-04 | INIL | 147.00 | stop | -1.65% |
| 2026-11-05 | PIOC | 263.99 | stop | -1.65% |
| 2026-11-06 | FANM | 12.70 | session_end | +0.45% |

**Reading.** The shortest holds (57 minutes) and the most two-sided result:
three targets, four stops, four gap stops and four session closes. The rotation
rule finds movers, but the next 5m bar confirmation arrives late enough that
half the exits are stops.

### Strategy 10: Order book imbalance + VWAP + intensity

Status: **not tested**.

The capture carries last price, best bid, best ask, print sizes and print-side
evidence, but not the top five bid and ask levels or a reliable sequence of
aggressor-classified trades. OBI and the 60 second trade intensity comparison
cannot be computed without fabricating the missing book (SO-3). No result is
reported for this arm.

## 4. Three-year daily context

This is a separate measurement, not a backtest of the intraday strategies. It
asks a simpler question over three years of daily bars: how often does price
touch +2% before -1%? Daily bars cannot reconstruct 5m or 15m entries or the
intraday order of the two levels.

| Item | Value |
|---|---|
| Window | 2023-11-04 to 2026-11-03 |
| Sessions | 742 |
| Symbols | 304 |
| Forward samples | 181,172 |
| Both-touch convention | Counted as a stop, conservative |

| Horizon | Target first, all samples | Target first, resolved only | Average days to target |
|---|---|---|---|
| 1 day | 20.92% | 24.67% | 1.00 |
| 5 days | 26.59% | 26.76% | 1.30 |
| 10 days | 26.81% | 26.84% | 1.35 |

### 4.1 Liquidity

30-day median daily traded value, close x volume, in PKR.

| Percentile | Value (PKR) |
|---|---|
| p10 | 43,069 |
| p25 | 243,296 |
| p50 | 2,920,165 |
| p75 | 27,900,618 |
| p90 | 166,144,941 |

Share above the live PKR 5,000,000 floor: **44.21%**.

| Liquidity quartile | Median value (PKR) | 5-day target rate (all) | 5-day target rate (resolved) |
|---|---|---|---|
| 1 (least liquid) | 59,978 | 33.36% | 33.50% |
| 2 | 843,297 | 24.98% | 25.15% |
| 3 | 9,130,992 | 22.91% | 23.10% |
| 4 (most liquid) | 115,754,879 | 25.11% | 25.25% |

The only quartile above 30% is the least liquid one, with a median daily traded
value of about PKR 60,000, which cannot absorb real size. Above the live floor
the rate is roughly 23% to 25%.

### 4.2 Volatility

14-day ATR as a percent of close.

| Percentile | ATR / close |
|---|---|
| p10 | 2.82% |
| p25 | 3.64% |
| p50 | 4.92% |
| p75 | 6.88% |
| p90 | 8.90% |

| ATR quartile | Median ATR | 5-day target rate (all) |
|---|---|---|
| 1 | 2.98% | 27.22% |
| 2 | 4.24% | 26.49% |
| 3 | 5.78% | 25.68% |
| 4 | 8.46% | 26.97% |

Volatility alone does not lift the base rate: the four quartiles sit within 1.5
percentage points of each other.

## 5. Cross-strategy findings

1. **The cost arithmetic dominates.** With a clean target netting +1.1492% and a
   clean stop netting -1.6480%, break-even is 58.9%. The pooled win rate across
   107 trades was 26.2%, and the three-year five-day base rate is 26.8%. Both
   are less than half of what the +2/-1 law needs.
2. **Targets are rare.** Only 18 of 107 trades reached the target, 12 cleanly and
   6 through a gap. Session closes account for 41 exits, stops for 27 and gap
   stops for 18.
3. **Gaps are asymmetric.** Four trades lost more than 2.5% (JATM -4.16%, PREMA
   -3.59%, UPFL -2.85%, SLGL -2.83%) while the best non-SYS winner was +2.26%.
   The median gap stop cost about 0.10% beyond the stop, and the four worst cost
   0.64% to 2.51% beyond it.
4. **High hit rate is not enough.** Strategy 8 won 60% and still lost, because
   its average win was +0.61% against -1.65% losses.
5. **The current bot is not the outlier.** Its -0.71% per trade sits in the
   middle of the field and its loss is explained by the same arithmetic, not by
   a fault unique to it.
6. **The SYS trade distorts the current arm.** Without the +5.03% gap, the
   current bot's 14 remaining trades net -15.63%, close to strategy 1.
7. **Nothing here is statistically strong.** The best arm has 5 trades, the
   worst 15. One 18-session regime cannot separate a real edge from noise, but
   it can show that no arm was close to the break-even bar.

## 6. Limitations

- A three-year intraday backtest is impossible with this repository's data. The
  18 stored sessions are the entire intraday sample.
- Two sessions in the window (2026-10-13, 2026-10-14) have no stored capture,
  and five captures are partial, so the effective sample is closer to 13 full
  sessions.
- The current bot's pullback arm is not tested because the 1D VWAP frame needs
  40 completed daily bars. Only the 1m flip arm is replayed.
- Strategy 10 is not tested because the feed lacks top five depth and a reliable
  aggressor sequence.
- The KMIALLSHR index level is not in the repository. Relative strength arms use
  the equal weight mean of the captured universe as the market proxy.
- Relative volume and cross-sectional returns use only the stored sessions, so
  early sessions have no signal and the sample is smaller than the rule assumes.
- Costs are modeled from the repository's config, not measured from fills.
  Spread widening, queue position and partial fills are not simulated.
- The daily context counts a same-day target and stop as a stop, so it is
  conservative.
- The summed net across arms is not a portfolio return; the arms are independent
  hypotheticals.

## 7. Reproducibility

```bash
# Re-run the whole study in the cloud, no local compute
gh workflow run backtest.yml -f task=eleven --ref master

# Fetch the artifacts of the run
gh run download <run-id> -D data/research/eleven_run
```

The workflow is manual dispatch only. It fetched 18 sessions from the R2 band
store and cached the ten-year EOD panel, which is why the run finished in under
four minutes.

## 8. Bottom line

On all the intraday data that exists in this repository, none of the eleven
strategies clears the owner's cost model, and the three-year daily base rate
says the +2% / -1% law needs a hit rate this market does not produce at these
horizons. This is evidence against the current configuration, not proof: the
sample is 18 sessions and one regime. The live bot was left untouched, as
instructed.
