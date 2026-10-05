"""
PSX KMIALL BOT - corporate actions layer (v0.20.1).

THE OWNER'S DIVIDEND-RUNWAY DOCTRINE (2026-09-19, supersedes v0.19.0):
  Our goal is intraday capital gain, NEVER the dividend itself. So a
  dividend announcement is not a hazard - it is a SET-UP with two
  faces:

    * RUNWAY (closure weeks away): dividend-chasers accumulate for
      days before the book-closure window. That      accumulation is real, persistent buying demand we can ride. ENTER is allowed - we
      are riding the chasers, and we dump before the window opens.
    * LAST SESSIONS before the window / the window itself / the
      ex-date: the circus turns into the dump. The crowd exits, the
      print is guaranteed to drop by roughly the dividend. VETO -
      nothing is worth holding into the drop.

  Zones per symbol (min_runway_sessions=3 trading sessions):
      [ex/window .. ∞)                    -> VETO (inside/behind)
      [closure - 3 sessions .. ex/window) -> VETO ("too soon": an
          entry now cannot be exited cleanly before the circus ends)
      (-∞ .. closure - 3 sessions)        -> ALLOW, and dividend_runway()
          reports the sessions of runway left (evidence + learning)

  PPL example (owner, 2026-09-19): closure Oct 19-20 -> the whole of
  late September is RUNWAY: trade it, exit before ~Oct 14.

RESULTS CATALYST (unchanged v0.19.0): good earnings pull buyers
  immediately; fresh results (<= max_age_days, EPS present) are
  surfaced as evidence on every card - never a veto, a magnet.

SOURCE: RETIRED with psxterminal.com (v4.0.0).

The notice fetcher has no broker or PSX source reachable from this
machine (dps.psx.com.pk WAF-blocks programmatic POSTs; the broker app
carries no notices endpoint). The module stays for its PURE LOGIC -
book-closure windows, ex-date alignment, fresh-results evidence - and
load_map() still serves any data/corporate_actions.json the owner
places by hand. fetch_corporate_actions() raises RetiredSource so
callers hit their established "layer inert" path instead of crashing.

(Original source line, kept for the audit trail:)
(one JS object per notice) carrying symbol, announcement_type, title,
and - critically - DATED fields the title text never has:

    book_closure_date_from / book_closure_date_to   (the veto window)
    ex_date                                          (the price-drop day)
    unconsolidated_eps / consolidated_eps / growth_in_pat  (results)

PARSING: the records are JS-ish ({d:{id:...,symbol:"X",field:null,...}})
- unquoted keys, double-quoted strings, bare nulls. Regex-per-field
inside {d:{ ... }} chunks is exact for this shape and needs no
third-party parser.

OUTPUT: data/corporate_actions.json
{
  "fetchedAt": "...",
  "bySymbol": {
    "THCCL": {"book_closure_from": "2026-09-17", "book_closure_to": "2026-09-21",
               "ex_date": null, "notices": ["Book Closure Notice ..."]},
    "LUCK":  {"results": [{"date": "2026-09-18", "eps": 12.3,
                            "eps_yoy": 4.1, "title": "Financial Results ..."}],
               "notices": [...]}
  }
}

QUERIES (the whole point):
    book_closure_block(symbol, today, buffer_sessions=3) -> str | None
        veto reason when today sits in the LAST SESSIONS before the
        window, inside the window, or at/behind the ex-date - None
        when the symbol is in the RUNWAY (tradeable) or has no
        dividend dates at all.
    dividend_runway(symbol, today) -> int | None
        trading sessions of runway left before the circus starts
        (the owner's hunting-ground metric). None = no dates.
    fresh_results(symbol, today, max_age_days=2) -> dict | None
        the freshest results record with a positive EPS - the
        earnings-buying catalyst the owner refuses to miss.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths  # noqa: E402
from psx_core import sessions as sessions_mod  # noqa: E402  (runway math)

ANNOUNCEMENTS_URL = "retired://psxterminal.com/announcements"
OUTPUT = paths.DATA_DIR / "corporate_actions.json"
# (HEADERS retired with the fetcher - kept out of the module to make
# the retirement obvious in diffs.)

# The results-type codes that carry EPS/earnings data on PSX DPS feeds.
RESULTS_TYPES = {"FRYEV1003", "FRYEV1001", "FRYEV1002", "DARYEV1005"}
# The record field -> our key map (regex-extracted, quoted or null).
_FIELDS = (
    "symbol", "announcement_type", "title", "name", "date",
    "book_closure_date_from", "book_closure_date_to", "ex_date",
    "unconsolidated_eps", "consolidated_eps", "growth_in_pat",
)

_RECORD_SPLIT = re.compile(r"\{d:\{")
_UNQUOTED_STR = "([A-Za-z0-9_]+):\"([^\"]*)\""
_UNQUOTED_NUM = r"([A-Za-z0-9_]+):(-?\d+(?:\.\d+)?)"


def _parse_record(chunk: str) -> dict | None:
    """One {d:{...}} chunk -> a flat dict of the fields we care about."""
    rec: dict = {}
    for key, val in re.findall(_UNQUOTED_STR, chunk):
        if key in _FIELDS and val != "":
            rec[key] = val
    for key, val in re.findall(_UNQUOTED_NUM, chunk):
        if key in _FIELDS and key not in rec:
            rec[key] = float(val)
    sym = rec.get("symbol")
    return rec if sym else None


def parse_records(html: str) -> list[dict]:
    """Extract the structured announcement records from the page."""
    records = []
    for chunk in _RECORD_SPLIT.split(html)[1:]:
        rec = _parse_record(chunk)
        if rec:
            records.append(rec)
    return records


def build_map(records: list[dict]) -> dict:
    """Records -> the bySymbol map (book closures + results)."""
    by: dict = {}
    for rec in records:
        sym = rec["symbol"]
        entry = by.setdefault(sym, {"notices": [], "results": []})
        title = rec.get("title", "")
        if title and title not in entry["notices"]:
            entry["notices"].append(title)

        bcf = rec.get("book_closure_date_from")
        bct = rec.get("book_closure_date_to")
        if isinstance(bcf, str) and re.match(r"\d{4}-\d{2}-\d{2}", bcf):
            entry["book_closure_from"] = bcf
            entry["book_closure_to"] = bct if isinstance(bct, str) else bcf
            # Dividend size when the notice title carries it ("... final
            # cash dividend of Rs. 8.00 ..." or "Rs 250%"). None today
            # on this feed - the extraction is here so the moment a
            # title carries the number, the map has it (owner's ask:
            # decisions from the reports, not guesses).
            m = re.search(r"Rs\.?\s*(\d+(?:\.\d+)?)\s*%?", title or "", re.IGNORECASE)
            if m:
                entry["dividend_per_share"] = float(m.group(1))
        if isinstance(rec.get("ex_date"), str) and re.match(
            r"\d{4}-\d{2}-\d{2}", rec["ex_date"]
        ):
            entry["ex_date"] = rec["ex_date"]

        if rec.get("announcement_type") in RESULTS_TYPES:
            eps = rec.get("unconsolidated_eps", rec.get("consolidated_eps"))
            entry["results"].append({
                "date": rec.get("date", ""),
                "eps": eps if isinstance(eps, (int, float)) else None,
                "growth_in_pat": (
                    rec["growth_in_pat"]
                    if isinstance(rec.get("growth_in_pat"), (int, float))
                    else None
                ),
                "title": title,
            })
    for entry in by.values():
        entry["results"].sort(key=lambda r: r.get("date", ""), reverse=True)
    return by


class RetiredSource(RuntimeError):
    """The notices source died with psxterminal.com; see module header."""


def fetch_corporate_actions(timeout: int = 25) -> dict:
    """Retired: raise so callers take their inert path. Pure logic above
    stays live; load_map() still serves a hand-curated JSON file."""
    del timeout
    raise RetiredSource(
        "corporate actions notices died with psxterminal.com - "
        "no replacement source is reachable; place "
        "data/corporate_actions.json by hand or run without the layer"
    )


def load_map() -> dict:
    """The stored bySymbol map ({} when the file is missing/corrupt)."""
    try:
        return json.loads(OUTPUT.read_text(encoding="utf-8")).get(
            "bySymbol", {}
        )
    except Exception:  # noqa: BLE001 - the veto must never crash a pass
        return {}


def _parse_d(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _closure_start(entry: dict) -> date | None:
    """The day the dividend circus turns into the dump: the earlier of
    the book-closure window opening and the ex-date (they can differ;
    the drop lands at the window's open)."""
    bcf = _parse_d(entry.get("book_closure_from"))
    exd = _parse_d(entry.get("ex_date"))
    if bcf and exd:
        return min(bcf, exd)
    return bcf or exd


def dividend_runway(
    symbol: str,
    today: date | str,
    min_runway_sessions: int = 3,
    actions: dict | None = None,
) -> int | None:
    """Trading sessions of clean runway left before the dividend circus
    starts (window open / ex-date, whichever lands first).

    None = no dividend dates on file (nothing to runway about).
    The owner's hunting-ground metric: a positive value means the
    chasers are still accumulating and we can ride them - as long as
    there are at least `min_runway_sessions` sessions left to exit
    through.
    """
    if isinstance(today, str):
        today = _parse_d(today)
    actions = actions if actions is not None else load_map()
    start = _closure_start(actions.get(symbol) or {})
    if start is None or today >= start:
        return None if start is None else 0
    sessions = 0
    probe = today
    while True:
        probe += timedelta(days=1)
        if probe >= start:
            break
        if sessions_mod.is_trading_day(probe):
            sessions += 1
    return sessions


def book_closure_block(
    symbol: str,
    today: date | str,
    buffer_sessions: int = 3,
    actions: dict | None = None,
) -> str | None:
    """Veto reason when `symbol` is past its runway.

    The owner's doctrine (v0.20.1): the run-up BEFORE the closure is
    the hunting ground - chasers accumulate for weeks and we ride
    them, exiting before the window. Only the LAST `buffer_sessions`
    trading sessions before the window/ex-date, the window itself,
    and the ex-date are fatal: an entry there cannot be exited
    cleanly before the drop. None = safe (runway or no dates).
    """
    if isinstance(today, str):
        today = _parse_d(today)
    actions = actions if actions is not None else load_map()
    entry = actions.get(symbol) or {}
    start = _closure_start(entry)
    if start is None:
        return None
    if today >= start:
        return (
            f"dividend circus day: window/ex-date {start} - the drop is "
            "landing or landed (owner rule: never hold into it)"
        )
    sessions = dividend_runway(
        symbol, today, actions=actions, min_runway_sessions=buffer_sessions
    )
    if sessions < buffer_sessions:
        return (
            f"dividend runway {sessions} session(s) < {buffer_sessions} - "
            f"window/ex-date {start}; no clean exit before the drop "
            "(owner rule: ride the runway, never the circus)"
        )
    return None


def fresh_results(
    symbol: str,
    today: date | str,
    max_age_days: int = 2,
    actions: dict | None = None,
) -> dict | None:
    """The freshest results record (<= max_age_days old, EPS present)."""
    if isinstance(today, str):
        today = _parse_d(today)
    actions = actions if actions is not None else load_map()
    for rec in (actions.get(symbol) or {}).get("results", []):
        rdate = _parse_d(rec.get("date"))
        if (
            rdate
            and (today - rdate).days <= max_age_days
            and rec.get("eps") is not None
        ):
            return rec
    return None


if __name__ == "__main__":
    paths.enable_utf8_stdout()
    payload = fetch_corporate_actions()
    by = payload["bySymbol"]
    closures = [
        s for s, e in by.items() if e.get("book_closure_from") or e.get("ex_date")
    ]
    results = [s for s, e in by.items() if e["results"]]
    print(
        f"corporate actions: {payload['records']} records -> "
        f"{len(by)} symbols | book-closure/ex: {closures} | "
        f"results: {len(results)}"
    )
