"""Cloud-only PSX intraday research program.

This package is deliberately separate from the live scanner, broker and
Android paths. It only reads the archived 5m/15m/30m/60m parquet files and
writes research evidence. The command line entry point is
``scripts/intraday100.py`` and it refuses to run outside GitHub Actions.
"""

from __future__ import annotations

TIMEFRAME_SECONDS = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "60m": 3600,
}

CAPITAL_PKR = 10_000_000.0
TRADE_FRACTION = 0.10
COST_SIDE_BPS = 32.4
SPREAD_SIDE_BPS = 5.0
CGT_RATE = 0.15
