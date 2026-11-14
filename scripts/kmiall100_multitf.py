#!/usr/bin/env python3
"""Build the cross-timeframe view of the kmiall100 report.

One row per strategy that has a usable result on every requested timeframe.
Each timeframe contributes its best combination by the kit's own
``rank_score``. The table deliberately requires all three timeframes, so a
strategy cannot appear here on the strength of one chart alone.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

DEFAULT_TFS = ("5m", "15m", "30m")


def build(results: Path, out: Path, tfs: tuple[str, ...], min_trades: int,
          top: int) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(results)
    need = {"id", "name", "tf", "n", "exp_net", "t_stat", "rank_score", "passes"}
    absent = sorted(need - set(df.columns))
    if absent:
        raise SystemExit(f"{results} is missing columns {absent}")

    usable = df[(df["n"] >= min_trades) & df["rank_score"].notna()].copy()
    best = usable.sort_values("rank_score", ascending=False).drop_duplicates(["id", "tf"])

    merged: pd.DataFrame | None = None
    for tf in tfs:
        part = best[best["tf"] == tf][["id", "name", "rank_score", "exp_net", "t_stat", "n", "passes"]]
        if part.empty:
            raise SystemExit(f"no usable {tf} rows in {results}")
        part = part.rename(columns={
            "rank_score": f"{tf}_rank",
            "exp_net": f"{tf}_exp",
            "t_stat": f"{tf}_t",
            "n": f"{tf}_n",
            "passes": f"{tf}_passes",
        })
        merged = part if merged is None else merged.merge(part.drop(columns=["name"]), on="id", how="inner")

    assert merged is not None
    rank_cols = [f"{tf}_rank" for tf in tfs]
    exp_cols = [f"{tf}_exp" for tf in tfs]
    t_cols = [f"{tf}_t" for tf in tfs]
    merged["min_rank"] = merged[rank_cols].min(axis=1)
    merged["min_exp"] = merged[exp_cols].min(axis=1)
    merged["min_t"] = merged[t_cols].min(axis=1)
    merged["positive_all"] = (merged[exp_cols] > 0).all(axis=1)
    merged["t3_all"] = (merged[t_cols] >= 3).all(axis=1)
    merged = merged.sort_values(["min_rank", "min_exp"], ascending=False).reset_index(drop=True)

    out.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out / "multitf_leaderboard.csv", index=False, float_format="%.5g")

    stats = {
        "strategies_all_three": int(len(merged)),
        "positive_all_three": int(merged["positive_all"].sum()),
        "t3_all_three": int(merged["t3_all"].sum()),
    }
    show = merged.head(top)
    label = " + ".join(tfs)
    heading = f"{label} together" if len(tfs) > 1 else label
    noun = "timeframes" if len(tfs) > 1 else "timeframe"
    cols = ["id", "name", "min_rank", "min_exp", "min_t", "positive_all", "t3_all"]
    lines = [
        f"# {heading}",
        "",
        f"* strategies with a usable result on all requested {noun}: {stats['strategies_all_three']}",
        f"* positive net return on all requested {noun}: {stats['positive_all_three']}",
        f"* t statistic at least 3 on all requested {noun}: {stats['t3_all_three']}",
        "",
        f"A strategy enters this table only if its best combination exists on {label} "
        "with at least the minimum trade count. `min_rank` is the weakest of the requested rank scores, "
        "so the table is ordered by the timeframe that is hardest to satisfy.",
        "",
        "| " + " | ".join(cols) + " |",
        "|" + "|".join("---" for _ in cols) + "|",
    ]
    for _, row in show.iterrows():
        cells = []
        for col in cols:
            value = row[col]
            if isinstance(value, bool):
                cells.append("yes" if value else "no")
            elif isinstance(value, float):
                cells.append(f"{value:.3f}")
            else:
                cells.append(str(value))
        lines.append("| " + " | ".join(cells) + " |")
    (out / "MULTITF.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"cross-timeframe rows: {len(merged)}, positive all requested: {stats['positive_all_three']}, "
          f"t>=3 all requested: {stats['t3_all_three']}", flush=True)
    return merged, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--results", default="report/all_results.csv")
    ap.add_argument("--out", default="report")
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS))
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--top", type=int, default=40)
    args = ap.parse_args()
    tfs = tuple(t.strip() for t in args.tfs.split(",") if t.strip())
    build(Path(args.results), Path(args.out), tfs, args.min_trades, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
