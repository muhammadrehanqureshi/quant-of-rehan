"""Build the 30-day KMIALL EOD corpus from DPS (open/close/volume, per symbol).

One GET per symbol (the endpoint returns the full history; we keep the
last ~40 sessions). Output: data/backtest/eod_corpus.json - a
date-keyed map of {symbol: {open, close, volume, prev_close}} used by
backtest_eod_30d.py. No high/low exists publicly; the backtest's
bracket method (close-based, conservative) is documented there.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import requests

from psx_core import paths
from scan_positive_opens import fetch_eod_rows

OUT = ROOT / "data" / "backtest" / "eod_corpus.json"
SESSIONS = 130  # ~6 months; the grind slices the last 30 and 90 sessions


def main() -> int:
    universe = json.loads(paths.UNIVERSE_FILE.read_text(encoding="utf-8"))
    symbols = [u["symbol"] for u in universe] if isinstance(universe, list) else list(universe)
    print(f"universe: {len(symbols)} symbols")

    cutoff = date.today() - timedelta(days=SESSIONS * 2)  # generous: holidays
    corpus: dict[str, dict] = {}
    errors = []

    with requests.Session() as http:
        for i, sym in enumerate(symbols):
            try:
                rows = fetch_eod_rows(sym, http)
            except Exception as exc:  # noqa: BLE001
                errors.append((sym, repr(exc)))
                continue
            recent = [r for r in rows if r["date"] >= cutoff]
            if len(recent) < 2:
                continue
            hist = []
            for r in recent:
                hist.append(
                    {
                        "date": r["date"].isoformat(),
                        "open": r["open"],
                        "close": r["close"],
                        "volume": r["volume"],
                    }
                )
            corpus[sym] = hist
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(symbols)} fetched")
            time.sleep(0.05)  # polite pacing; network-bound, not CPU

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(corpus), encoding="utf-8")
    n_days = len({d for sym in corpus for d in [h["date"] for h in corpus[sym]]})
    print(f"corpus: {len(corpus)} symbols, ~{n_days} sessions, errors {len(errors)}")
    if errors:
        print("errors (first 5):", errors[:5])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
