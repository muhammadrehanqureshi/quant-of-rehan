# Running the kit inside Quant of Rehan

The kit stays cloud-only. `.github/workflows/kmiall100-backtest.yml` is the
QoR entry point; `kmiall100.run` still refuses to start outside GitHub Actions.

## Data source

The job restores the six yearly artifacts from the successful
`intraday-history` run `43403044554`:

* `intraday-history-2021`
* `intraday-history-2022`
* `intraday-history-2023`
* `intraday-history-2024`
* `intraday-history-2025`
* `intraday-history-2026`

`scripts/prepare_kmiall100_data.py` joins the requested partitions into one
long parquet per timeframe. It keeps only rows flagged `regular`, so pre-open
and post-close bars do not become trading signals. The archive names the daily
folder `1D`, which the script maps to the kit's `1d`; a missing year stops the
job.

## Why the index strategies are skipped

The archive holds KMIALL constituent stocks, not a KMIALL index series. The
kit therefore skips S079 to S086 (`needs_index`) and says so in its metadata.
No index is invented.

## What runs together

Intraday runs pass `--tfs 5m,15m,30m` in one invocation, so every shard loads
the same three-timeframe dataset. Swing runs pass `--tfs 1d` with the swing
profiles, because a 10 percent target and a 30-session hold do not mean the
same thing on an intraday bar. The workflow refuses to mix the two modes.

The merge job then writes:

* `REPORT.md` and `leaderboard.md` from the kit's own ranking
* `MULTITF.md` and `multitf_leaderboard.csv`, which include only strategies
  with a usable result on all three timeframes

`MULTITF.md` orders by the weakest of the requested rank scores. It also
reports how many strategies are positive on every requested timeframe and how
many reach t 3 or more on all of them. For a swing run the requested list is
just `1d`, so the table is the daily leaderboard.

## Day-low dispatch

```
gh workflow run kmiall100-backtest.yml -f data_run_id=43403044554 \
  -f shards=10 -f tfs=5m,15m,30m -f profiles=daylow \
  -f grid=true -f min_trades=100
```

`daylow` takes profit at 1.2 percent and stops at the session low known at
the signal bar. It is intraday only; the final low of the day is never used.

## Swing dispatch

```
gh workflow run kmiall100-backtest.yml -f data_run_id=43403044554 \
  -f shards=10 -f tfs=1d -f profiles=swing,swingatr,swingtrail \
  -f grid=true -f min_trades=50
```

The swing profiles are `swing` (10 percent target, 5 percent stop),
`swingatr` (2.5 ATR stop, 3R target) and `swingtrail` (3 ATR chandelier, no
target). Each holds for up to 30 completed daily bars.
