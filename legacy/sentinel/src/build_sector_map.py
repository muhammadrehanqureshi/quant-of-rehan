"""
PSX KMIALL BOT
Sector map builder - symbol -> sector, from the broker's ScripServlet.

Why the broker (v4.0.0)
-----------------------
The retired source (psxterminal.com/sectors) needed 39 slow page
requests to expose what the broker's scrip master carries in one call:
ScripServlet returns every scrip with its sectorName. The map feeds
two ranking inputs (sector breadth, foreign sector flow) and the
universe loader's ETF/REIT exclusion, so it must cover the whole
approved REG market - 554 scrips as of 2026-09-25 - and stay stable
across runs.

Output shape is UNCHANGED (data/sector_map.json):
    {"fetchedAt": ..., "sectors": {slug: [symbols...]},
     "symbolToSector": {symbol: slug}}
so every consumer (universe loader, feature engine, sector flow
mapper) keeps working without edits.

Usage
-----
    python src/build_sector_map.py              # write data/sector_map.json
    python src/build_sector_map.py --refresh    # bypass the local cache
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import broker_feed, paths


def crawl(timeout: float = 30.0, pause: float = 0.0) -> dict:
    """
    One ScripServlet call -> {symbol: sector_slug}, grouped by sector.

    `pause` is accepted for CLI compatibility and ignored: there is no
    crawl anymore, so there is nothing to pace. A symbol appears once
    per market; approved REG scrips only (the bot's world).
    """
    del pause
    scrips = broker_feed.fetch_scrips(timeout=timeout)

    mapping: dict[str, str] = {}
    sector_symbols: dict[str, list[str]] = {}

    for symbol, info in scrips.items():
        slug = info.get("sector_slug") or "unknown"
        mapping[symbol] = slug
        sector_symbols.setdefault(slug, []).append(symbol)

    return {
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "sectors": {
            slug: sorted(symbols)
            for slug, symbols in sorted(sector_symbols.items())
        },
        "symbolToSector": mapping,
    }


def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Build the symbol -> sector map from the broker's "
        "scrip master (ScripServlet).",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force a fresh ScripServlet fetch even if cached.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--pause", type=float, default=0.0,
        help="Accepted for compatibility; no crawl to pace.",
    )
    args = parser.parse_args(argv)

    out_path = paths.DATA_DIR / "sector_map.json"
    if out_path.exists() and not args.refresh:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            count = len(existing.get("symbolToSector") or {})
            if count:
                print(f"Sector map already on disk ({count} symbols).")
                print(f"Use --refresh to re-fetch. Path: {out_path}")
                return 0
        except (json.JSONDecodeError, OSError):
            pass  # a broken file is rebuilt, never honoured

    result = crawl(timeout=args.timeout)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Sectors  : {len(result['sectors'])}")
    print(f"Symbols  : {len(result['symbolToSector'])}")
    print(f"Written  : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
