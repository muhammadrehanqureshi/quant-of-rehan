"""Write the Breakthrough 1.0 pre-registration rows into the registry.

The rows are written before any result exists: each carries `results: null`,
`decision: "preregistered"` and the exact parameter grid. Running this script
twice does not duplicate rows; it skips a hypothesis that is already present.

Nothing here executes a backtest, reads a network or waits on a clock. It
only appends rows to the gitignored research registry, which is the file the
Holm correction counts.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.research.experiment_registry import Registry, code_hash  # noqa: E402

SPLIT = (
    "discovery 2016-10-29..2024-06-30; validation 2024-07-01..2025-12-31; "
    "test 2026-01-01..2026-10-30 locked"
)
KILL = "KILL_FEW_TRADES, KILL_NEGATIVE_EDGE at the shape's own break-even"
DATA = "pending: ten year KMIALL daily panel"
PRED = "net expectancy above zero at the shape's own break-even"

F1_BASE = {
    "universe": "top 50 by 60 day median traded value",
    "proximity_252d_high_pct": None,
    "volume_multiple_20d": 1.5,
    "entry": "next open",
    "hold_closes": None,
    "bracket": None,
}

F3_BASE = {
    "universe": "top 50 by 60 day median traded value",
    "close_above_sma50": True,
    "drop_days": 3,
    "drop_pct": None,
    "entry": "next open",
    "exit": "2 pct bounce or 3 closes",
}


def rows() -> list[dict]:
    out: list[dict] = []

    for proximity in (2, 3, 5):
        for hold in (2, 3, 5):
            for bracket in ("none", "2/1"):
                params = dict(F1_BASE)
                params["proximity_252d_high_pct"] = proximity
                params["hold_closes"] = hold
                params["bracket"] = bracket
                out.append({
                    "hypothesis": (
                        f"F1 52w high {proximity}pct, hold {hold} closes, "
                        f"bracket {bracket}"
                    ),
                    "params": params,
                })

    out.append({
        "hypothesis": (
            "F1b 52w high 3pct with the Kalman flip as the entry timer on "
            "tape sessions"
        ),
        "params": {
            **F1_BASE,
            "proximity_252d_high_pct": 3,
            "hold_closes": 1,
            "bracket": "2/1",
            "timer": "kalman_trend_flip_v1",
            "sessions": "tape sessions only",
        },
    })

    gate = (
        "median KMIALL stock above SMA50 AND KSE100 above SMA50 AND KSE100 "
        "20 day realized volatility below its trailing 252 day median"
    )
    for base_name, base_params in (
        ("F1 3pct hold 3 bracket 2/1", {
            **F1_BASE,
            "proximity_252d_high_pct": 3,
            "hold_closes": 3,
            "bracket": "2/1",
        }),
        ("F3 drop 4pct", {**F3_BASE, "drop_pct": 4}),
    ):
        out.append({
            "hypothesis": f"F2 regime gate on {base_name}",
            "params": {"gate": gate, "base": base_name, **base_params},
        })

    for drop in (3, 4, 5):
        out.append({
            "hypothesis": f"F3 pullback drop {drop}pct",
            "params": {**F3_BASE, "drop_pct": drop},
        })

    for source in ("F1", "F3"):
        for multiple in (1.0, 1.5, 2.0):
            out.append({
                "hypothesis": (
                    f"F4 {source} eligible plus gate, stop {multiple}x 30m RV, "
                    "target 2x stop"
                ),
                "params": {
                    "eligible": source,
                    "gate": gate,
                    "entry_timer": "kalman_trend_flip_v1",
                    "stop_rv_multiple_30m": multiple,
                    "target": "2x stop",
                    "sessions": "tape sessions only",
                },
            })

    return out


def main() -> int:
    registry = Registry()
    seen = {str(row.get("hypothesis", "")) for row in registry.rows()}
    written = 0
    for spec in rows():
        if spec["hypothesis"] in seen:
            continue
        registry.append({
            "hypothesis": spec["hypothesis"],
            "code_hash": code_hash(ROOT),
            "data_hash": DATA,
            "params": spec["params"],
            "seed": 0,
            "split": SPLIT,
            "results": None,
            "pred": PRED,
            "kill": KILL,
            "decision": "preregistered",
        })
        seen.add(spec["hypothesis"])
        written += 1
    print(f"registered {written} new rows; registry total {registry.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
