"""
Refresh the KMIALL universe from the live source.

The owner's standing order: he trades ONLY KMIALL (shariah-compliant)
stocks. KSE reconstitutes the index on reviews and ad-hoc changes, so
the stored list must be re-derived from the source of truth on a
schedule - never by hand, never assumed current.

Source of truth (v4.0.0): the owner's ECLEAR broker terminal's
GetShariahSymbol endpoint returns the full shariah-compliant REG
universe (the same list the terminal's shariah watchlist is built
from). ScripServlet enriches each member with its registered name and
sector. psxterminal.com is retired.

Safety rails (a bad parse must never replace a good list):
  * the fetched list must yield at least MIN_PLAUSIBLE members or the
    refresh aborts without writing;
  * the file is written only when membership actually changed
    (idempotent);
  * every write is preceded by printing the human diff (added /
    removed) so the change is auditable in the workflow log.

2026-09-20: the first run caught a real reconstitution - NNAR and
SOYASUP had joined KMIALL and neither repo's stored list knew it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import broker_feed, paths  # noqa: E402

UNIVERSE_FILE = paths.DATA_DIR / "kmiall_tickers.json"

MIN_PLAUSIBLE_MEMBERS = 100


def fetch_fundamentals(timeout: float = 30.0) -> list[dict]:
    """
    Every shariah-compliant REG instrument as a universe-shaped record.

    Name kept for compatibility with self_audit.py's import. The
    broker's shariah list is the membership source; ScripServlet adds
    the name. isShariahCompliant is True by construction (the endpoint
    IS the compliance list).
    """
    symbols = broker_feed.fetch_shariah_symbols(timeout=timeout)
    try:
        scrips = broker_feed.fetch_scrips(timeout=timeout)
    except Exception:  # noqa: BLE001 - names are enrichment, not membership
        scrips = {}

    records: list[dict] = []
    for symbol in sorted(symbols):
        info = scrips.get(symbol) or {}
        records.append({
            "symbol": symbol,
            "isShariahCompliant": True,
            "listedIn": ["KMIALLSHR", "ALLSHR"],
            "name": info.get("name") or "",
        })
    if not records:
        raise RuntimeError(
            "broker shariah list parsed to zero members - endpoint "
            "format changed?"
        )
    return records


def build_universe(records: list[dict]) -> list[dict]:
    """Shariah members, sorted by symbol (shape-compatible with tests)."""
    return sorted(
        (r for r in records if r.get("isShariahCompliant")),
        key=lambda r: r["symbol"],
    )


def _stored_symbols(path: Path) -> dict[str, bool]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, dict):
        raw = list(raw.values())
    out: dict[str, bool] = {}
    for item in raw:
        if isinstance(item, dict) and item.get("symbol"):
            out[str(item["symbol"])] = item.get("isShariahCompliant") is True
        elif isinstance(item, str):
            out[item] = True
    return out


def refresh(
    records: list[dict],
    universe_file: Path = UNIVERSE_FILE,
    min_members: int = MIN_PLAUSIBLE_MEMBERS,
) -> dict:
    """Diff, refuse-if-degenerate, write-if-changed. Returns the report.

    min_members is the plausibility floor (live default 100); tests pass
    a smaller floor for synthetic universes - the guarantee itself, that
    a degenerate parse is refused, never relaxes.
    """
    universe = build_universe(records)
    if len(universe) < min_members:
        raise RuntimeError(
            f"only {len(universe)} KMIALL members parsed - refusing to "
            f"replace the stored list with a degenerate parse"
        )

    before = _stored_symbols(universe_file)
    added = sorted(r["symbol"] for r in universe if r["symbol"] not in before)
    removed = sorted(s for s in before if s not in {r["symbol"] for r in universe})

    report = {
        "members": len(universe),
        "added": added,
        "removed": removed,
        "flag_flips": [],  # membership source is the compliance list itself
        "changed": bool(added or removed),
    }

    if report["changed"]:
        universe_file.write_text(
            json.dumps(universe, indent=2) + "\n", encoding="utf-8"
        )
    return report


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    check_only = "--check" in argv
    records = fetch_fundamentals()
    universe = build_universe(records)
    before = _stored_symbols(UNIVERSE_FILE)
    added = sorted(r["symbol"] for r in universe if r["symbol"] not in before)
    removed = sorted(s for s in before if s not in {r["symbol"] for r in universe})

    if check_only:
        print(f"live KMIALL members: {len(universe)} | stored: {len(before)}")
        if added or removed:
            print(f"DRIFT - added: {added} removed: {removed}")
            return 2
        print("universe is current")
        return 0

    report = refresh(records)
    print(
        f"KMIALL universe: {report['members']} members "
        f"({len(added)} added, {len(removed)} removed)"
    )
    if report["changed"]:
        print(f"added:   {report['added']}")
        print(f"removed: {report['removed']}")
        print("universe file updated")
    else:
        print("universe unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
