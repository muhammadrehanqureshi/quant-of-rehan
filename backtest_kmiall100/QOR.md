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

`scripts/prepare_kmiall100_data.py` joins the 5m, 15m and 30m partitions into
`5m.parquet`, `15m.parquet` and `30m.parquet`. It keeps only rows flagged
`regular`, so pre-open and post-close bars do not become trading signals. A
missing year stops the job.

## Why the index strategies are skipped

The archive holds KMIALL constituent stocks, not a KMIALL index series. The
kit therefore skips S079 to S086 (`needs_index`) and says so in its metadata.
No index is invented.

## What runs together

The run job passes `--tfs 5m,15m,30m` in one invocation, so every shard loads
the same three-timeframe dataset. The merge job then writes:

* `REPORT.md` and `leaderboard.md` from the kit's own ranking
* `MULTITF.md` and `multitf_leaderboard.csv`, which include only strategies
  with a usable result on all three timeframes

`MULTITF.md` orders by the weakest of the three rank scores. It also reports
how many strategies are positive on all three and how many reach t 3 or more
on all three.
