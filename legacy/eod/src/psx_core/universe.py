"""
The single canonical KMIALL universe loader.

Previously five scripts each carried their own near-identical loader, with
subtly different key precedence and dedup behaviour. Any drift between them
would silently change which symbols the pipeline considered in scope.

data/kmiall_tickers.json is a list of objects:

    [{"symbol": "AASM", "isShariahCompliant": true,
      "listedIn": ["ALLSHR", "KMIALLSHR"]}, ...]

Older exports used bare strings or different key names, so the loader still
accepts those shapes.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import paths

# The index membership tag that defines the tradable universe.
KMIALL_INDEX_TAG = "KMIALLSHR"

_SYMBOL_KEYS = ("symbol", "SYMBOL", "ticker", "code")

# Sectors excluded from the tradable universe regardless of the
# compliance flag: ETFs are pass-through vehicles (no intraday
# selection edge, and the Shariah status of the underlying holdings is
# opaque), and REITs are property trusts with a different risk profile
# than the operating equities this strategy ranks.
EXCLUDED_SECTORS = frozenset({
    "exchange-traded-funds",
    "real-estate-investment-trust",
})


class UniverseError(RuntimeError):
    """Raised when the universe file is missing or unusable."""


def is_shariah_compliant(record: dict) -> bool:
    """
    A record is compliant only when the file says so explicitly.

    Missing, None, or false flags are all treated as non-compliant -
    the default is exclusion, never inclusion. A legacy file without
    the flag therefore yields nothing, which fails loudly at startup
    instead of silently trading non-compliant instruments.
    """
    return record.get("isShariahCompliant") is True


def _extract_symbol(item: object) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in _SYMBOL_KEYS:
            value = item.get(key)
            if value:
                return str(value)
    return None


def load_records(path: Path | None = None) -> list[dict]:
    """Return the raw universe records, normalised to dicts with 'symbol'."""
    path = path or paths.UNIVERSE_FILE

    if not path.exists():
        raise UniverseError(f"Universe file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise UniverseError(f"Universe file is not valid JSON: {path}") from exc

    if isinstance(raw, dict):
        # Legacy shape: {"AASM": {...}, ...}
        raw = [
            {"symbol": key, **(value if isinstance(value, dict) else {})}
            for key, value in raw.items()
        ]

    if not isinstance(raw, list):
        raise UniverseError(
            f"Universe file must contain a list or object, got "
            f"{type(raw).__name__}: {path}"
        )

    records: list[dict] = []
    seen: set[str] = set()

    for item in raw:
        symbol = _extract_symbol(item)
        if not symbol:
            continue

        symbol = symbol.strip().upper()
        if not symbol or symbol in seen:
            continue

        seen.add(symbol)
        record = dict(item) if isinstance(item, dict) else {}
        record["symbol"] = symbol
        records.append(record)

    if not records:
        raise UniverseError(f"Universe file contains no symbols: {path}")

    return records


def load(
    path: Path | None = None,
    *,
    shariah_only: bool = True,
    exclude_etf_sectors: bool = True,
) -> list[str]:
    """
    Return the tradable KMIALL symbols in file order.

    By default the list is FILTERED:

      shariah_only         -- records must carry isShariahCompliant: true.
      exclude_etf_sectors  -- symbols mapped to EXCLUDED_SECTORS
                              (ETFs, REITs) via data/sector_map.json
                              are dropped even when flagged compliant.

    Pass shariah_only=False / exclude_etf_sectors=False to inspect the
    raw file (the audit tools do).

    Order is preserved rather than sorted because the dataset builder
    emits one row per symbol per snapshot and downstream diffs are
    easier to read when the ordering is stable across runs.
    """
    records = load_records(path)
    if shariah_only:
        records = [r for r in records if is_shariah_compliant(r)]
    if exclude_etf_sectors:
        records = [
            r for r in records
            if _mapped_sector(r["symbol"]) not in EXCLUDED_SECTORS
        ]
    return [record["symbol"] for record in records]


def _mapped_sector(symbol: str) -> str:
    """The symbol's sector slug from data/sector_map.json, or ''."""
    import json as _json

    sector_map_path = paths.DATA_DIR / "sector_map.json"
    if not sector_map_path.exists():
        return ""
    try:
        raw = _json.loads(sector_map_path.read_text(encoding="utf-8"))
        return str((raw.get("symbolToSector") or {}).get(symbol, "") or "")
    except (json.JSONDecodeError, OSError):
        return ""


def load_set(
    path: Path | None = None,
    *,
    shariah_only: bool = True,
    exclude_etf_sectors: bool = True,
) -> set[str]:
    return set(load(path, shariah_only=shariah_only,
                    exclude_etf_sectors=exclude_etf_sectors))


def check_membership(path: Path | None = None) -> dict:
    """
    Report how many records actually carry the KMIALL index tag.

    The universe file is a snapshot of index membership taken at audit time.
    KMIALL rebalances periodically, so a caller that cares about staleness can
    use this instead of trusting a hardcoded expected size.
    """
    records = load_records(path)

    tagged = [
        record["symbol"]
        for record in records
        if KMIALL_INDEX_TAG in (record.get("listedIn") or [])
    ]

    return {
        "total": len(records),
        "tagged_kmiall": len(tagged),
        "shariah_compliant": sum(
            1 for record in records if is_shariah_compliant(record)
        ),
        "etf_sector_excluded": sorted(
            symbol for symbol in tagged
            if _mapped_sector(symbol) in EXCLUDED_SECTORS
        ),
        "untagged": sorted(
            {record["symbol"] for record in records} - set(tagged)
        ),
    }
