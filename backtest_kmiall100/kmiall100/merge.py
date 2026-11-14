"""Put the shard results together and say plainly what survived.

    python -m kmiall100.merge results --out report

Reads every ``summary.csv`` below the folder (one per shard), and writes

* ``all_results.csv``      every strategy x timeframe x variant x exit profile
* ``leaderboard.md/.csv``  the best by ``rank_score`` (the weaker of the in sample and out of sample t statistic)
* ``passing.csv``          the ones that cleared every gate in metrics.py
* ``best_per_strategy.csv`` and ``best_per_family.md``
* ``daily_signal_leaderboard.md/.csv``  one call a day scoring, the QoR use case (profile ``law``: +2 percent, -1 percent)
* ``REPORT.md``            the headline, the multiple testing warning and any partial or failed shard

Pure pandas. Safe to run anywhere, it only reads CSV files.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import NormalDist

import pandas as pd

from .metrics import wilson_lower

SHOW = ["id", "name", "tf", "variant", "profile", "n", "symbols", "win_rate", "be_win_rate", "exp_net", "profit_factor",
        "t_stat", "is_exp", "oos_exp", "years_pos", "tp_rate", "sl_rate", "passes"]
DAILY = ["id", "name", "tf", "variant", "daily_n", "days_signal_pct", "daily_win_rate", "daily_wilson_low", "be_win_rate",
         "daily_exp", "daily_tp_rate", "n", "t_stat", "oos_exp"]


def md_table(df: pd.DataFrame, cols, fmt=None) -> str:
    fmt = fmt or {}
    head = "| " + " | ".join(cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n"
    rows = []
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if isinstance(v, float):
                cells.append("" if math.isnan(v) else (fmt.get(c, "{:.2f}")).format(v))
            else:
                cells.append(str(v).replace("|", "/"))
        rows.append("| " + " | ".join(cells) + " |")
    return head + "\n".join(rows) + "\n"


def load(root: Path):
    parts, metas = [], []
    for f in sorted(root.rglob("summary.csv")):
        parts.append(pd.read_csv(f))
        m = f.with_name("meta.json")
        if m.exists():
            metas.append((f.parent.name, json.loads(m.read_text())))
    if not parts:
        raise SystemExit(f"no summary.csv under {root}")
    return pd.concat(parts, ignore_index=True), metas


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", help="folder holding the shard folders")
    ap.add_argument("--out", default="report")
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--top", type=int, default=40)
    a = ap.parse_args(argv)

    df, metas = load(Path(a.results))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df["daily_wilson_low"] = [wilson_lower(int(round(w / 100 * n)), int(n)) * 100 if n and n == n else float("nan")
                              for w, n in zip(df["daily_win_rate"], df["daily_n"])]
    df = df.sort_values(["id", "tf", "variant", "profile"]).reset_index(drop=True)
    df.to_csv(out / "all_results.csv", index=False, float_format="%.5g")

    ok = df[(df["n"] >= a.min_trades) & df["rank_score"].notna() & (df["rank_score"] > float("-inf"))].copy()
    lead = ok.sort_values("rank_score", ascending=False).head(a.top)
    lead.to_csv(out / "leaderboard.csv", index=False, float_format="%.5g")
    (out / "leaderboard.md").write_text("# Leaderboard (weaker of in sample and out of sample t statistic)\n\n"
                                        + md_table(lead, SHOW))
    passing = ok[ok["passes"] == 1].sort_values("rank_score", ascending=False)
    passing.to_csv(out / "passing.csv", index=False, float_format="%.5g")

    best = ok.sort_values("rank_score", ascending=False).groupby("id", as_index=False).head(1).sort_values("id")
    best.to_csv(out / "best_per_strategy.csv", index=False, float_format="%.5g")
    fam = ok.sort_values("rank_score", ascending=False).groupby("family", as_index=False).head(3)
    fam = fam.sort_values(["family", "rank_score"], ascending=[True, False])
    (out / "best_per_family.md").write_text("# Best three per family\n\n" + md_table(fam, ["family"] + SHOW))

    law = ok[(ok["profile"] == "law") & (ok["daily_n"] >= 100)].copy()
    law = law.sort_values(["daily_wilson_low", "daily_exp"], ascending=False).head(a.top)
    law.to_csv(out / "daily_signal_leaderboard.csv", index=False, float_format="%.5g")
    (out / "daily_signal_leaderboard.md").write_text(
        "# One signal a day: first signal of each day, profile law (+2 percent target, -1 percent stop)\n\n"
        "daily_wilson_low is the 95 percent lower bound of the daily win rate. It has to sit above be_win_rate "
        "(the break even win rate for that strategy after costs) before the idea is worth a live trial.\n\n"
        + md_table(law, DAILY))

    n_tests = int(len(ok))
    z = NormalDist().inv_cdf(1 - 0.05 / max(1, n_tests)) if n_tests else float("nan")
    chance = n_tests * (1 - NormalDist().cdf(3.0))
    lines = ["# kmiall100 report", "",
             f"* strategy x timeframe x variant x exit profile combinations with at least {a.min_trades} trades: {n_tests:,}",
             f"* combinations that passed every gate: {len(passing)}",
             f"* Bonferroni threshold for {n_tests:,} tests at 5 percent: t above {z:.2f}",
             f"* false passes expected from pure luck at t above 3: about {chance:.1f}",
             "", "A pass here is a short list to study, not a signal to trade. Re run the passing ones on data you have",
             "not looked at, and trade nothing with a t statistic under the Bonferroni line without a reason you can explain.", ""]
    bad = [(n, m) for n, m in metas if m.get("partial") or m.get("errors")]
    if bad:
        lines.append("## Shards that need attention")
        for n, m in bad:
            lines.append(f"* {n}: partial={m.get('partial')} errors={m.get('errors')} units {m.get('units_done')}/{m.get('units_total')}")
        lines.append("")
    if not metas:
        lines.append("note: no meta.json files were found next to the summaries.")
    if len(passing):
        lines += ["## Passing combinations", "", md_table(passing.head(a.top), SHOW)]
    else:
        lines += ["## Passing combinations", "", "None cleared every gate. That is a normal outcome, see the README for what to try next.", ""]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(f"merged {len(df):,} rows, {len(ok):,} with enough trades, {len(passing)} passing -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
