"""
PSX KMIALL BOT
Daily closes memory - the multi-day extension check's data source.

Why it exists
-------------
Rule 4 ("no chasing") only saw the SAME day's move, so ECOP could pass a
±4% filter at 09:58 while having risen ~20% over the two sessions before.
The extension gate needs each candidate's recent daily closes.

How closes arrive
-----------------
Two sources, merged at load time (see market_regime.load_context):

  1. data/processed/psx_eod_history.json - the positive-open scan's DPS
     cache: full EOD history for all 307 symbols, refreshed manually
     (`python src/scan_positive_opens.py --cache`). Can lag by days.

  2. data/daily_closes.json - this module. At the first decide cycle of
     each session the runner records every symbol's prior close,
     reconstructed from the live feed: prior = price / (1 + change_pct/100).
     change_pct is quoted against the previous close all day, so the
     reconstruction holds at any time of session - no first-tick race.
     One record per session, kept for the last 40.

The gate needs the most recent 3-5 closes per symbol; source 1 provides
depth, source 2 keeps the tail fresh. Neither is required: symbols with
too few closes are simply not judged (missing data never blocks).

Usage
-----
    python src/daily_closes.py --bootstrap     # fill from archived snapshots
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths

CLOSES_FILE = "daily_closes.json"
MAX_RECORDS = 40


def _closes_path() -> Path:
    return paths.DATA_DIR / CLOSES_FILE


def record_prior_closes(
    prior: dict[str, float],
    as_of: str,
) -> int:
    """
    Store one session's prior closes under `as_of` (the session whose
    open they preceded). Idempotent per as_of; keeps the newest
    MAX_RECORDS sessions. Returns the number of symbols stored.
    """
    if not prior:
        return 0
    path = _closes_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        raw = {}
    records: dict = raw.get("records", {})
    records[as_of] = {str(k): float(v) for k, v in prior.items() if v > 0}
    # Keep only the newest MAX_RECORDS keys (as_of is an ISO date: sort works).
    trimmed = dict(sorted(records.items())[-MAX_RECORDS:])
    raw["records"] = trimmed
    path.write_text(
        json.dumps(raw, separators=(",", ":")), encoding="utf-8"
    )
    return len(records[as_of])


def record_from_frame(latest, as_of: str) -> int:
    """
    Extract prior closes from a feature frame slice (one row per symbol,
    columns: symbol, price, change_pct - change_pct in percent units,
    the feature engine's convention).
    """
    import pandas as pd

    if latest is None or getattr(latest, "empty", True):
        return 0
    if "price" not in latest.columns or "change_pct" not in latest.columns:
        return 0
    prior: dict[str, float] = {}
    for sym, price, chg in zip(
        latest["symbol"],
        pd.to_numeric(latest["price"], errors="coerce"),
        pd.to_numeric(latest["change_pct"], errors="coerce"),
    ):
        if pd.isna(price) or pd.isna(chg) or price <= 0 or chg <= -100:
            continue
        prior[str(sym)] = float(price) / (1.0 + float(chg) / 100.0)
    return record_prior_closes(prior, as_of)


def load_records() -> dict[str, dict[str, float]]:
    """Stored records: {as_of_date: {symbol: close}}."""
    try:
        raw = json.loads(_closes_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    records = raw.get("records", {})
    return {k: v for k, v in records.items() if isinstance(v, dict)}


# ---------------------------------------------------------------------------
# Bootstrap from archived snapshots
# ---------------------------------------------------------------------------

def bootstrap_from_snapshots() -> int:
    """
    Rebuild prior-close records from data/snapshots/<date>.jsonl.gz.

    The LAST snapshot of each archived day reconstructs that day's
    prior closes (raw feed changePercent is a fraction, so
    prior = price / (1 + changePercent)). Missing archives simply leave
    gaps; the live runner fills the tail going forward.
    """
    snap_dir = paths.SNAPSHOT_DIR
    if not snap_dir.exists():
        print(f"No snapshot dir: {snap_dir}")
        return 1
    total = 0
    for snap_file in sorted(snap_dir.glob("*.jsonl.gz")):
        as_of_date = snap_file.stem  # e.g. 2026-09-10
        last_line = None
        with gzip.open(snap_file, "rt", encoding="utf-8") as fh:
            for last_line in fh:
                pass
        if not last_line:
            continue
        try:
            row = json.loads(last_line)
        except json.JSONDecodeError:
            continue
        prior: dict[str, float] = {}
        for sym, q in (row.get("quotes") or {}).items():
            price = q.get("price")
            chg = q.get("changePercent")
            if not price or price <= 0 or chg is None or chg <= -1.0:
                continue
            prior[sym] = float(price) / (1.0 + float(chg))
        if prior:
            record_prior_closes(prior, as_of_date)
            total += len(prior)
            print(f"  {as_of_date}: {len(prior)} prior closes")
    print(f"Bootstrap complete: {total} close points written.")
    return 0


def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()
    parser = argparse.ArgumentParser(
        description="Daily closes memory for the extension gate.",
    )
    parser.add_argument(
        "--bootstrap", action="store_true",
        help="Rebuild records from archived snapshots.",
    )
    args = parser.parse_args(argv)
    if args.bootstrap:
        return bootstrap_from_snapshots()
    records = load_records()
    print(f"records: {len(records)} sessions")
    for as_of in sorted(records)[-5:]:
        print(f"  {as_of}: {len(records[as_of])} symbols")
    return 0


if __name__ == "__main__":
    sys.exit(main())
