"""
PSX KMIALL BOT
Company-name builder - symbol -> registered company name, from the
broker's ScripServlet.

Why the broker (v4.0.0)
-----------------------
The retired source crawled 311 psxterminal.com financials pages
(~3 minutes at 0.75 s spacing); the broker's scrip master carries
symbolName for every scrip in the single ScripServlet call - no crawl,
no pacing, no retries.

The names feed headline/notice matching (news used to tag symbols via
company names; PSX notices do the same). Output shape is UNCHANGED
(data/company_names.json, {"names": {symbol: name}, "failedSymbols":
[...]}) so consumers keep working. The broker's names are fuller than
the old crawler's extracts ("Oil and Gas Development Company Limited"
vs the old "Oil and Gas Development"), which only widens headline
matches.

Usage
-----
    python src/build_company_names.py             # write the map
    python src/build_company_names.py --refresh   # bypass the cache
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
    One ScripServlet call -> {"names": {...}, "failedSymbols": []}.

    `pause` is accepted for CLI compatibility and ignored: there is no
    crawl to pace. failedSymbols is kept in the output shape (empty)
    because the old file format carried it; the single-call source has
    no per-symbol failure mode - either the master arrives or it raises.
    """
    del pause
    scrips = broker_feed.fetch_scrips(timeout=timeout)
    return {
        "names": {
            symbol: info["name"]
            for symbol, info in scrips.items()
            if info.get("name")
        },
        "failedSymbols": [],
    }


def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Build symbol -> company name from the broker's "
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

    out_path = paths.DATA_DIR / "company_names.json"
    if out_path.exists() and not args.refresh:
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            count = len(existing.get("names") or {})
            if count:
                print(f"Company names already on disk ({count}).")
                print(f"Use --refresh to re-fetch. Path: {out_path}")
                return 0
        except (json.JSONDecodeError, OSError):
            pass  # a broken file is rebuilt, never honoured

    result = crawl(timeout=args.timeout)
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"Names    : {len(result['names'])}")
    print(f"Failed   : {len(result['failedSymbols'])}")
    print(f"Written  : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
