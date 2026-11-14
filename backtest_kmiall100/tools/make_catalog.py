"""Write STRATEGIES.md and strategies_catalog.csv from the registry, so the docs can never drift from the code.

    python tools/make_catalog.py
"""

import csv
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KMIALL_CLOUD", "1")

from kmiall100.core import REGISTRY  # noqa: E402
from kmiall100.strategies import REGISTRY as _R  # noqa: E402,F401
from kmiall100.run import DEFAULT_HOLD, hold_for  # noqa: E402

ORDER = ["Trend following", "Pullback in an uptrend", "Breakout and volatility", "Candlestick pattern",
         "Volume and money flow", "Intraday session", "Market index and relative strength", "Calendar",
         "Composite and multi timeframe"]


def main():
    rows = []
    for sid in sorted(REGISTRY):
        s = REGISTRY[sid]
        rows.append(dict(id=sid, name=s.name, family=s.family, timeframes=" ".join(s.tfs),
                         building_blocks=" + ".join(s.parts), base_params=json.dumps(s.params, sort_keys=True),
                         variants=len(s.grid), holds_overnight="yes" if s.overnight else "no",
                         needs_index="yes" if s.needs_index else "no",
                         max_hold_bars=" ".join(f"{t}:{hold_for(s, t)}" for t in s.tfs), note=s.note))
    with open(ROOT / "strategies_catalog.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    md = ["# The 100 strategies", "",
          "All long only, all built for the PSX KMIALL universe (trade the constituent stocks, use the KMIALL index as market context).",
          "A signal is read at the close of a bar and the trade enters at the next bar's open. Every strategy runs on 5m, 15m, 30m, 1h and 1d",
          "unless its row says otherwise. Strategies marked [index] need the KMIALL series in the data folder and are skipped without it.", "",
          f"Default maximum hold in bars per timeframe: {', '.join(f'{k} {v}' for k, v in DEFAULT_HOLD.items())}. "
          "Intraday trades are flat by the last bar of the session unless the row says it holds overnight.", ""]
    for fam in ORDER:
        group = [r for r in rows if r["family"] == fam]
        md.append(f"## {fam} ({len(group)})")
        md.append("")
        for r in group:
            tags = []
            if r["needs_index"] == "yes":
                tags.append("[index]")
            if r["holds_overnight"] == "yes":
                tags.append("[overnight]")
            if r["timeframes"] != "5m 15m 30m 1h 1d":
                tags.append("[" + r["timeframes"] + "]")
            md.append(f"### {r['id']} {r['name']} {' '.join(tags)}".rstrip())
            for part in r["building_blocks"].split(" + "):
                md.append(f"- {part}")
            md.append(f"- base parameters {r['base_params']}, {r['variants']} variant(s) with --grid")
            if r["note"]:
                md.append(f"- note: {r['note']}")
            md.append("")
    (ROOT / "STRATEGIES.md").write_text("\n".join(md) + "\n")
    print("wrote STRATEGIES.md and strategies_catalog.csv,", len(rows), "strategies")


if __name__ == "__main__":
    main()
