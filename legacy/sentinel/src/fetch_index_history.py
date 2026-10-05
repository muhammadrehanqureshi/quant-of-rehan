"""
PSX KMIALL BOT
KSE-100 index history fetcher - the market-trend anchor for the regime gate.

Source
------
dps.psx.com.pk/timeseries/eod/KSE100 returns the full EOD history of the
index as JSON rows [epoch, close, volume, open] (layout verified in
src/scan_positive_opens.py, which uses the same endpoint per symbol).

Why it exists
-------------
The regime gate ("be with the market") needs the index's own trend, not a
per-stock measure. One GET returns ~1,240 sessions (5 years), so the
20-session average is available from the very first cycle - no local
accumulation period.

Timing
------
EOD rows publish after close. Refreshed at each session close, plus a
self-heal at the first decide cycle of a day (the close-time refresh was
missed on 2026-09-08/09 when the runner was stopped early - the gate must
not silently run on stale history).

Usage
-----
    python src/fetch_index_history.py          # refresh data/kse100_history.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths, sessions

import requests

# Reuse the verified DPS fetch (headers, retries, row layout) instead of
# duplicating the parsing rules in a second file.
from scan_positive_opens import fetch_eod_rows

INDEX_SYMBOL = "KSE100"
MAX_ROWS = 400  # ~1.5 years is plenty for a 20-session average


def fetch_index_history(http: requests.Session) -> list[dict]:
    """
    KSE-100 EOD rows, oldest first: [{"date": date, "close": float}].

    Raises on network failure (caller decides whether that is fatal).
    """
    rows = fetch_eod_rows(INDEX_SYMBOL, http)
    if rows is None:
        raise RuntimeError("KSE-100 history fetch failed after retries")
    if not rows:
        raise RuntimeError("KSE-100 history empty - DPS layout changed?")
    return [{"date": r["date"], "close": r["close"]} for r in rows]


def store(rows: list[dict]) -> Path:
    """Persist the newest MAX_ROWS sessions to data/kse100_history.json."""
    trimmed = rows[-MAX_ROWS:]
    out = paths.DATA_DIR / "kse100_history.json"
    out.write_text(
        json.dumps(
            {
                "fetchedAt": datetime.now(timezone.utc).isoformat(),
                "rows": [
                    {"date": r["date"].isoformat(), "close": r["close"]}
                    for r in trimmed
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return out


def load_history() -> list[dict] | None:
    """Stored rows as [{"date": date, "close": float}], or None if absent."""
    path = paths.DATA_DIR / "kse100_history.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    rows = []
    for row in raw.get("rows", []):
        try:
            rows.append(
                {"date": datetime.fromisoformat(row["date"]).date(),
                 "close": float(row["close"])}
            )
        except (KeyError, TypeError, ValueError):
            continue
    return rows or None


def is_stale(rows: list[dict] | None) -> bool:
    """
    True when the stored history does not yet include the last completed
    session (the session before today's, in PKT terms).
    """
    if not rows:
        return True
    now = datetime.now(timezone.utc)
    today = sessions.trading_date(now)
    # The most recent *completed* session: yesterday's trading day, or the
    # last trading day before it. Compare against the newest stored row.
    needed = newest_completed_session_date(today)
    newest_stored = max(r["date"] for r in rows)
    return newest_stored < needed


def newest_completed_session_date(today):
    """The last trading date strictly before `today` (a date object)."""
    from datetime import timedelta

    probe = today - timedelta(days=1)
    for _ in range(10):
        if sessions.is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)
    return today - timedelta(days=10)


def refresh_if_stale(logger=None) -> bool:
    """
    Self-heal: refresh the stored history when it misses the last
    completed session. Returns True when a fetch happened. Network and
    parse failures are logged, never raised - the gate runs on whatever
    history exists (or stands down if none).
    """
    if not is_stale(load_history()):
        return False
    import requests as _requests

    http = _requests.Session()
    try:
        rows = fetch_index_history(http)
    except Exception as exc:  # noqa: BLE001
        if logger is not None:
            logger.warning("Index-history refresh failed: %s", exc)
        return False
    finally:
        http.close()
    out = store(rows)
    if logger is not None:
        logger.info(
            "KSE-100 history refreshed: %d sessions (%s).",
            len(rows), out.name,
        )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    parser = argparse.ArgumentParser(
        description="Fetch KSE-100 EOD history for the regime gate.",
    )
    args = parser.parse_args(argv)

    import requests as _requests

    http = _requests.Session()
    try:
        rows = fetch_index_history(http)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}")
        return 1
    finally:
        http.close()

    out = store(rows)
    newest = rows[-1]
    print(f"Sessions : {len(rows)}")
    print(f"Newest   : {newest['date']} close {newest['close']:,.2f}")
    print(f"Written  : {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
