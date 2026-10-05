"""PSX Data Portal "Daily Downloads" EOD fetcher (mkt_summary).

All session dates handled here are Asia/Karachi calendar dates (UTC+5).
The session schedule itself lives in src/data/sessions.py.

The 2026-09 portal redesign killed the old 5-year-per-GET timeseries
endpoint, but the /downloads page exposes per-date files with a stable
URL pattern:

    https://dps.psx.com.pk/download/mkt_summary/{YYYY-MM-DD}.Z

Despite the `.Z` name, the payload is either a ZIP (PK, ~2021 onward) or
a gzip (1f8b, older years) containing one fixed-format pipe-delimited
listing, `closing11.lis`:

    02OCT2026|OGDC|0820|Oil & Gas Dev|313.01|315.95|311.8|314.62|1836867|313.39|||

    fields: session-date | symbol | code | name | OPEN | HIGH | LOW |
            CLOSE | VOLUME | rate2 (unverified: LDCP or weighted avg) | | |

This gives full OHLCV **with high/low**: strictly better than the old
endpoint, which had no high/low at all. Non-session dates (weekends,
holidays, pre-archive dates) return 404.

Usage is LOCAL ONLY (GOVERNANCE.md SO-4): private research on the owner's
machine; the dataset is never committed (`.gitignore` roots `/data/`).

Politeness: REQUEST_PAUSE seconds between requests, RETRIES on transport
errors, 404 is a normal "no session" answer, never an error.
"""

from __future__ import annotations

import gzip
import io
import time
import zipfile
from datetime import date as date_cls, datetime, timedelta
from typing import Callable, Optional

import requests

BASE = "https://dps.psx.com.pk"
MKT_SUMMARY_URL = BASE + "/download/mkt_summary/{date}.Z"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/131.0 Safari/537.36"),
    "Accept": "*/*",
    "Referer": BASE + "/downloads",
}

REQUEST_PAUSE = 0.35   # seconds between requests (legacy sentinel discipline)
RETRIES = 3


def iter_weekdays(start: str, end: str) -> list[date_cls]:
    """All weekdays (Mon-Fri) from start to end inclusive, ascending.

    Holidays are NOT known client-side; they simply 404 at fetch time.
    """
    d0 = date_cls.fromisoformat(start)
    d1 = date_cls.fromisoformat(end)
    if d1 < d0:
        raise ValueError(f"end {end} before start {start}")
    out = []
    d = d0
    while d <= d1:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def parse_closing_lis(text: str) -> tuple[list[dict], dict]:
    """Parse `closing11.lis` content into row dicts + a parse-info dict.

    Rows are never fabricated: malformed lines are skipped and COUNTED
    (SO-3), and zero prices are kept exactly as printed (the engine's
    data-quality screen handles them honestly).
    """
    rows: list[dict] = []
    skipped = 0
    seen: set[str] = set()
    dupes = 0
    for ln in text.splitlines():
        ln = ln.strip("\r\n").strip()
        if not ln:
            continue
        parts = ln.split("|")
        if len(parts) < 9:
            skipped += 1
            continue
        date_raw, symbol, _code, name = parts[0], parts[1], parts[2], parts[3]
        vals = parts[4:10] + [""] * (10 - len(parts))
        try:
            session = datetime.strptime(date_raw, "%d%b%Y").date().isoformat()
        except ValueError:
            session = date_raw  # keep raw, flag below
        try:
            o, h, lo, c, v = (float(vals[0]), float(vals[1]), float(vals[2]),
                              float(vals[3]), float(vals[4]))
            rate2 = float(vals[5]) if vals[5] else None
        except ValueError:
            skipped += 1
            continue
        if symbol in seen:
            dupes += 1
            continue
        seen.add(symbol)
        rows.append({
            "date": session,
            "symbol": symbol,
            "name": name,
            "open": o,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v,
            "rate2": rate2,
        })
    info = {"lines_malformed": skipped, "duplicate_symbols": dupes,
            "rows": len(rows)}
    return rows, info


def _decompress(content: bytes) -> Optional[str]:
    """ZIP (PK) or gzip (1f8b) payload -> closing11.lis text, else None."""
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            name = z.namelist()[0]
            return z.read(name).decode("utf-8", "replace")
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content).decode("utf-8", "replace")
    return None


def fetch_mkt_summary(d: date_cls, pause: float = REQUEST_PAUSE,
                      retries: int = RETRIES) -> tuple[Optional[list[dict]], dict]:
    """Fetch one session's mkt_summary file.

    Returns (rows, info). rows is None when there was no session (404) or
    the payload was unreadable: both recorded in info, never fabricated.
    """
    url = MKT_SUMMARY_URL.format(date=d.isoformat())
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 404:
                time.sleep(pause)
                return None, {"date": d.isoformat(), "status": "no_session",
                              "url": url}
            if r.status_code == 429:
                # back off harder, keep trying within the retry budget
                time.sleep(pause * 8)
                last_err = "429"
                continue
            r.raise_for_status()
            text = _decompress(r.content)
            if text is None:
                return None, {"date": d.isoformat(), "status": "bad_payload",
                              "magic": r.content[:2].hex(), "url": url}
            rows, pinfo = parse_closing_lis(text)
            time.sleep(pause)
            return rows, {"date": d.isoformat(), "status": "ok", "url": url,
                          "bytes": len(r.content), **pinfo}
        except requests.RequestException as e:
            last_err = str(e)[:120]
            time.sleep(pause * (attempt + 2))
    return None, {"date": d.isoformat(), "status": "error", "error": last_err,
                  "url": url}
