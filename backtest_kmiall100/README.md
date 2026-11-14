# kmiall100: 100 long only strategies and a cloud backtester for the PSX KMIALL universe

One folder, one workflow. You press a button on GitHub, the strategies run on GitHub's computers against your
5 year data, and you download a ranked report. Your PC does nothing except click the button.

* 100 strategies, long only, each one a single idea or a stack of several (a trigger plus filters). The full list with every
  building block is in `STRATEGIES.md` and `strategies_catalog.csv`.
* 5 timeframes: 5m, 15m, 30m, 1h, 1d. Every strategy runs on every timeframe it makes sense on.
* 3 exit profiles per strategy, so you can see the signal separate from the exit.
* Costs, slippage and the 15 percent capital gains tax on winners are charged on every trade.
* No look ahead, and that is tested (see "How I know it does not cheat").

## 1. Your PC is never used

* `kmiall100.run` refuses to start unless it is inside a GitHub Actions job (or another cloud box that sets
  `KMIALL_CLOUD=1`). On a normal PC it prints `REFUSED` and exits with code 3 before it reads a single file.
* There is no command line flag that overrides this. A deliberate local run needs `KMIALL_ALLOW_LOCAL=1` set by hand, and even
  then it runs one process on one core at the lowest priority with a 5 percent CPU cap.
* The workflow starts only when you press Run workflow. No schedule, no push trigger.
* In the cloud the work is split over up to 20 jobs (10 run at a time), one core each. Memory measured on the synthetic set was
  about half a gigabyte for all 100 strategies. On your real data I expect each of 10 shards to stay under a gigabyte, and more shards
  means less memory per job.

## 2. One time setup (about 15 minutes, all free)

1. Make a new PRIVATE repository, for example `kmiall100-backtest`, and put the contents of this folder in it
   (`kmiall100/`, `tools/`, `tests/`, `.github/`, `requirements*.txt`, `README.md`, `STRATEGIES.md`).
   Keep it private. Your data must never sit in a public repository, and QoR's own repo is public.
2. Pack the data you already have into one zip (a normal zip is fine, any layout in section 4 works) and make it reachable by
   a link the cloud job can read. Easiest free routes:
   * a Release on the same private repo, drag the zip into the release page (the limit is 2 GB per file). Then the link is
     the release asset API address and the secret `DATA_TOKEN` is a fine grained token with read access to this repo only;
   * or a private bucket on Cloudflare R2 or similar, with a presigned https link that lasts a day.
3. In the repo: Settings, Secrets and variables, Actions, add
   * `DATA_URL` the https link (required),
   * `DATA_TOKEN` only for the private release route (optional),
   * `DATA_SHA256` the SHA-256 of the zip, so a swapped file is refused (optional, recommended).
4. Actions tab, kmiall100-backtest, Run workflow. First time, try a small one:
   `shards 1`, `tfs 1d`, `strategies S001,S091`. It proves the data loads and the pipeline works in a couple of minutes.
5. Then the full run: defaults (10 shards, all timeframes, 3 profiles, grid on).

Free minutes: a public repo has unlimited Actions minutes, a private repo on the Free plan has 2,000 a month. By scaling the
synthetic timing (all 100 strategies, 3 symbols, grid on, 3 profiles: 9 seconds in total) I expect a full run of about 100
symbols to need on the order of 30 to 90 runner minutes in total across the shards, mostly spent reading the CSV files in each
job. That is an estimate, not a measurement on your data.

## 3. What comes out

Download the `kmiall100-report` artifact from the run page (the headline is also pasted on the run summary).

| file | what it is |
|---|---|
| `REPORT.md` | headline numbers, the multiple testing warning, any shard that failed or ran out of time |
| `leaderboard.md/.csv` | top combinations by `rank_score`, the weaker of the in sample and out of sample t statistic |
| `passing.csv` | combinations that cleared every gate below |
| `best_per_strategy.csv` | the best setting of each of the 100 strategies |
| `best_per_family.md` | the best three of each family |
| `daily_signal_leaderboard.md/.csv` | the QoR use case: take only the first signal of each day, +2 percent target, -1 percent stop |
| `all_results.csv` | everything, one row per strategy, timeframe, variant and exit profile |

Each shard artifact also has `trades_passing.csv.gz` (every trade of the passing combinations, to audit by hand),
`meta.json` (counts, run time, data cleaning report per file) and `errors.txt` (empty when all is well).

A combination passes only if all of these hold: at least 100 trades, positive average net return, positive in the first
60 percent of the calendar span AND in the last 40 percent, at least 60 percent of the calendar years positive, and a
t statistic of 3 or more on the net returns.

## 4. Data layout

Any of these, csv, csv.gz or parquet, mixed freely:

```
data/5m/PRL.csv      one folder per timeframe, one file per symbol
data/5m.parquet      one long file per timeframe with a symbol column
data/PRL_5m.csv      flat, timeframe at the end of the name
```

Columns are matched loosely: time or timestamp or datetime or date, then open, high, low, close, volume. Timeframe names
5m 5min 15m 30m 1h 60m 1d daily all work. The series named KMIALL (or KMI ALL, KMI-ALL, set `--index` to override) is the
market context for the eight index strategies (S079 to S086) and is never traded. Keep the whole bundle in one time zone.
Timestamps may be bar start or bar end, the code only needs the order and the calendar date.

The loader follows QoR's own ingestion rules: rows with a missing or non positive price are dropped, untraded rows are dropped,
ragged candles are widened to contain their body, duplicate timestamps are removed, and bars near a price jump bigger than 35 percent
(an unadjusted split or a bad print, bigger than any PSX circuit band) are never used for signals. Every drop is counted in `meta.json`.

## 5. How a trade is simulated

* The signal is read at the CLOSE of a bar. The order fills at the OPEN of the next bar plus 10 bps slippage. A signal on the last bar of
  the data is dropped, a next bar with zero volume cannot be traded.
* Take profit is a limit order and fills exactly at its price. The stop fills at its price, or at the open when the bar opens already below
  it. If one bar touches both, the stop wins. Every exit except the limit target also pays 10 bps slippage.
* A trailing stop trails the highest high of COMPLETED bars, so a candle cannot raise the stop and hit it in the same bar.
* One position per symbol at a time. Intraday trades are flat by the last bar of the session, except the strategies marked
  `[overnight]` in `STRATEGIES.md`. Maximum hold when nothing else fires: 5m 36 bars, 15m 24, 30m 14, 1h 7, 1d 5.
* Costs are the QoR repository's law: 22.4 bps per side (commission, SST, levies), 10 bps slippage per side, and 15 percent capital gains
  tax on a winning trade. A losing trade gets no refund.

Exit profiles (`--profiles`):

* `law`: take profit +2 percent, stop loss -1 percent. QoR's own rule.
* `atr`: stop 1.5 ATR under the entry (clipped to 0.4 to 4 percent), target twice the stop.
* `trail`: no target, a chandelier trailing stop 2.5 ATR under the highest high (clipped to 0.4 to 6 percent).

## 6. Read this before you trust a number

* **The 2 to 1 rule has a high bar.** After costs a +2 percent winner nets about +1.32 percent and a -1 percent loser costs about
  -1.55 percent. The break even rate for the `law` profile is therefore about 54 percent of trades hitting the target before the stop.
  `be_win_rate` in the reports is that number for each strategy. A strategy needs to clear it with room.
* **1,500 to 4,000 tests means some will look great by luck.** `REPORT.md` prints the Bonferroni line for the number of tests actually run
  and how many false passes the t of 3 gate lets through by chance (a handful). Treat `passing.csv` as a shortlist.
  The honest next step is to take the top few, freeze their settings, and test them on data nobody has looked at yet (the newest months, or
  other years you hold back before the run).
* **The in sample and out of sample split is a calendar split inside the same 5 years.** It guards against a one off lucky stretch, it does
  not guard against you picking the winner after looking.
* **KMIALL itself is an index, you cannot buy it.** The strategies trade the constituent stocks one by one and use the index as the market
  regime. If you also give the loader a single combined series it will only be used as context.
* **Survivorship and liquidity.** The backtest sees the stocks you gave it, as they are today. It does not model whether a limit order would
  have filled in a thin stock, or PSX daily price limits freezing an exit. Stocks with thin volume deserve a manual look.
* **A dead end is a result.** If nothing passes, `leaderboard.md` still shows the closest, and the `trail` and `atr` columns tell you whether the
  idea has any edge before QoR's tight 2 and 1 box is applied to it.

## 7. How I know it does not cheat

* `tests/test_no_lookahead.py` blacks out every bar after a chosen cut point (prices, volumes and index become NaN), recomputes each of the
  100 strategies, and demands the same signals up to the cut. Cuts are placed where the strategy signalled and at mid session on several
  days, for every timeframe and for the parameter variants. Four deliberately leaky signals (one bar peek, full day high, centred average,
  tomorrow's close) are planted to prove the check catches them. A static scan also forbids the usual idioms (negative shifts, rolling with
  `center=True`, reversed slices).
* Higher timeframe values (hour, day, week) are always the PREVIOUS completed group. The index is joined by timestamp with forward fill only.
* `tests/test_engine.py` pins every execution rule: next open entry, limit fill, gap through the stop, stop wins ties, trailing on completed
  bars, slippage, costs and tax, one position at a time.
* Random walk data with realistic volatility (`tools/make_synthetic.py`) has no edge, and the result is what it should be: none of the roughly
  2,900 combinations in the full synthetic run passes, average net return is about -0.6 percent, which is the cost drag. A leak would show up
  as a wall of positive t statistics.
* The opposite check is in `tests/test_positive_control.py`: a series with a built in upward drift must make the gates pass, and the same
  series without the drift must not. A pipeline that can never say yes would look just like an honest one that found nothing.

The workflow runs all of these checks first (job `plan`) and stops if any fails.

## 8. The 100 strategies at a glance

| ids | family | count |
|---|---|---|
| S001 to S016 | Trend following (EMA and SMA crosses, Supertrend, Donchian, Ichimoku, Aroon, Vortex, PSAR, HMA, linear regression) | 16 |
| S017 to S034 | Pullback in an uptrend (RSI and Connors RSI dips, Bollinger, Keltner, Z score, stochastic, Williams %R, CCI, MFI, Fibonacci retracement, VWAP dip, gap reversal) | 18 |
| S035 to S050 | Breakout and volatility (squeeze, NR7, inside bar, opening range, previous day high, gap hold, volume spike, one year high, Darvas box, swing high) | 16 |
| S051 to S060 | Candlestick patterns (hammer, engulfing, morning star, soldiers, piercing, harami and others, each with a trend filter) | 10 |
| S061 to S070 | Volume and money flow (OBV, CMF, MFI, A/D line, Force Index, ease of movement, volume dry up, selling climax, VWAP) | 10 |
| S071 to S078 | Intraday session (VWAP reclaim, opening range, first hour, afternoon strength, overnight hold) | 8 |
| S079 to S086 | Market index and relative strength (needs KMIALL) | 8 |
| S087 to S090 | Calendar (turn of month, quarter end, Thursday, Monday), daily bars | 4 |
| S091 to S100 | Composite and multi timeframe (Kalman trend flip, Heikin Ashi, Elder triple screen, squeeze, Schaff cycle, a four way vote, a higher timeframe trend filter with a lower timeframe trigger) | 10 |

`S091` is the analogue of QoR's current Kalman trend flip. It is the baseline: QoR's live Kalman flip lost its first three
signals, so any strategy that cannot beat S091 on the same exit profile is not an improvement.

## 9. Command line (inside the cloud job, shown for reference)

```
python tools/fetch_data.py data
python -m kmiall100.run --data data --out results/shard_0 --shard 0/10 --grid
python -m kmiall100.merge results --out report
python tools/make_catalog.py        # rewrites STRATEGIES.md and strategies_catalog.csv from the code
python -m pytest tests -q           # run by the workflow, you do not need to run it yourself
```

`run` options: `--tfs`, `--profiles`, `--strategies S001,S091`, `--symbols PRL,LUCK`, `--grid`, `--min-trades`,
`--time-budget-min` (stop starting new series after that many minutes and say so in `meta.json`), `--index`.

## 10. Safety notes on the workflow

* `permissions: contents read`, nothing can write to your repo or its secrets.
* Workflow inputs go through environment variables and are checked against strict patterns in the `plan` job. They are never pasted into
  a shell line.
* The data link is a secret. `fetch_data.py` insists on https, caps the size, verifies the SHA-256 when you give one, rejects archive members
  that escape the folder (zip slip) and links inside archives, never prints the full link, and drops the token if a download is redirected to
  another host. The data job needs no other secret.
* The actions used are `checkout`, `setup-python`, `upload-artifact` and `download-artifact` on their current major versions. If you want
  supply chain hardening, pin each to a full commit SHA.

## 11. Add your own strategy

Open `kmiall100/strategies_2.py`, copy any function, change the id to `S101`, and return a boolean array that is True on the bar whose
close completes the setup. Use `sh(a, k)` for earlier bars and the `x.` helpers for indicators, never a negative shift. Update the count in
`strategies.py` and `tests/test_registry.py`, then let the workflow's self checks run.
