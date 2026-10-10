"""Universe drift checker: the tracked KMIALL snapshot vs the live KMIALLSHR table.

The scanner loads the tracked snapshot ``src/data/universe_kmiall.json``: the
Shariah symbols that were listed in KMIALLSHR when the snapshot was taken. The
exchange publishes its own constituent table live, so membership changes over
time and the tracked list can go stale (a delisted name, a newly admitted
member). When it does, every coverage figure in a scan is measured against a
list that no longer matches the exchange, which is exactly the kind of silent
drift this project refuses to hide.

This module does NOT invent a refreshed universe. It reports the drift, name by
name, so the drift is visible instead of guessed:

  * tracked but not live  -> the snapshot still carries a name the exchange no
    longer lists in KMIALLSHR (delisting, name change, index removal);
  * live but not tracked  -> the exchange lists a member the snapshot lacks.

The honest remedy for the first kind is a deliberately refreshed snapshot,
which is an owner decision. This checker produces the evidence for it.

Usage:
    python -m src.data.universe_refresh            # report the drift
    python -m src.data.universe_refresh --write     # also save the report
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.market_snapshot import fetch_constituents  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

TRACKED = ROOT / "src" / "data" / "universe_kmiall.json"
DRIFT_REPORT = ROOT / "data" / "universe_drift.json"
MEMBERSHIP = "KMIALLSHR"


def tracked_symbols(path: Path = TRACKED) -> list[str]:
    """The tracked snapshot exactly as the scanner resolves it.

    Same filter as scripts/intraday_pipeline.load_kmiall: Shariah compliant AND
    listed in KMIALLSHR. Keeping this in one shape is what makes the drift
    count meaningful.
    """
    rows = json.loads(path.read_text(encoding="utf-8"))
    return sorted({
        str(row["symbol"]).strip().upper()
        for row in rows
        if row.get("isShariahCompliant") is True
        and MEMBERSHIP in row.get("listedIn", [])
        and row.get("symbol")
    })


def live_symbols(membership: str = MEMBERSHIP) -> list[str]:
    """The exchange's own current member list, straight from the portal table."""
    rows = fetch_constituents(membership)
    return sorted({
        str(row["symbol"]).strip().upper()
        for row in rows
        if row.get("symbol")
    })


def diff(tracked: list[str], live: list[str]) -> dict:
    """Name-by-name symmetric difference between two symbol lists."""
    tracked_set = {s.strip().upper() for s in tracked if s}
    live_set = {s.strip().upper() for s in live if s}
    stale = sorted(tracked_set - live_set)
    untracked = sorted(live_set - tracked_set)
    return {
        "tracked_count": len(tracked_set),
        "live_count": len(live_set),
        "overlap": len(tracked_set & live_set),
        "in_sync": not stale and not untracked,
        "missing_from_live": stale,
        "missing_from_tracked": untracked,
    }


def check(path: Path = TRACKED, membership: str = MEMBERSHIP) -> dict:
    """Fetch the live table and diff it against the tracked snapshot.

    A fetch failure is reported as a failure, never as a clean bill of health:
    an unreachable portal is not evidence that the universe is in sync.
    """
    tracked = tracked_symbols(path)
    try:
        live = live_symbols(membership)
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        return {
            "ok": False,
            "membership": membership,
            "tracked_count": len(tracked),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {"ok": True, "membership": membership, **diff(tracked, live)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KMIALL universe drift check")
    parser.add_argument("--write", action="store_true",
                        help="save the report to data/universe_drift.json")
    args = parser.parse_args(argv)

    report = check()
    report["checked_at"] = now_karachi().isoformat(timespec="seconds")
    if args.write:
        DRIFT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        DRIFT_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        print(f"wrote {DRIFT_REPORT.relative_to(ROOT)}")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
