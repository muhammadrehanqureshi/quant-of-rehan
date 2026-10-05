"""
Positive-open scanner - which KMIALL names ALWAYS gap up on a given weekday?

Question answered (user request, 2026-09-09): over 2025-09-09 .. 2026-09-09,
which KMIALL stocks open above the previous close on *every* Monday, every
Tuesday, ... so a weekday-specific open bias can be traded.

Data source: PSX Data Portal (dps.psx.com.pk) company timeseries,

    GET https://dps.psx.com.pk/timeseries/eod/<SYMBOL>

which returns {status: 1, data: [[epoch, close, volume, open], ...]} - most
recent first. Row layout was verified against the bot's own Sep 8 snapshot
(MLCF open 98.75 matches the first live poll exactly; prev-row close 99.05
explains the live change -0.30). The previous trading row's close is the
previous close; a positive open is `open > prev_close` (strictly - a flat
open is NOT positive).

A symbol qualifies for a weekday when it had a positive open on 100% of that
weekday's sessions in the window (minimum session count applies, because a
qualifier with 3 sessions is luck, not pattern). "Near-miss" names (one
missed open) are reported separately as a sanity tier.

Refinement (user request, 2026-09-09): --min-gap-pct raises the bar from
"any higher open" to "open at least +X% above the previous close", so tiny
+0.1% technical opens no longer count as positive. Opens that gap up but
by less than the threshold are tracked as "weak_gap".
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths
from psx_core import universe

import requests

DPS_TIMESERIES_URL = "https://dps.psx.com.pk/timeseries/eod/{symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

REQUEST_TIMEOUT = 20.0
REQUEST_PAUSE = 0.35          # be polite: 307 symbols at ~0.35s ≈ 2 min
RETRIES = 3

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_eod_rows(
    symbol: str,
    http: requests.Session,
) -> list[dict] | None:
    """
    Full EOD history rows for one symbol, oldest first:

        {"date": date, "open": float, "close": float, "volume": float}

    None means the fetch failed after retries (network/5xx); an empty
    list means the symbol genuinely has no DPS history (delisted, wrong
    symbol form). Callers must distinguish the two.
    """
    url = DPS_TIMESERIES_URL.format(symbol=symbol)
    for attempt in range(1, RETRIES + 1):
        try:
            resp = http.get(url, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            resp = None
        if resp is not None and resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            rows = (payload or {}).get("data")
            if payload is not None and payload.get("status") == 1:
                out = []
                for row in rows or []:
                    # [epoch, close, volume, open] - verified layout.
                    epoch, close, volume, open_ = row[0], row[1], row[2], row[3]
                    day = datetime.fromtimestamp(
                        epoch, tz=timezone.utc
                    ).date()
                    out.append({
                        "date": day,
                        "open": float(open_),
                        "close": float(close),
                        "volume": float(volume),
                    })
                out.sort(key=lambda r: r["date"])
                return out
            return []            # valid response, no history
        if attempt < RETRIES:
            time.sleep(1.5 * attempt)
    return None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def positive_open_rates(
    rows: list[dict],
    start: date,
    end: date,
    min_gap_pct: float = 0.0,
) -> dict[str, dict]:
    """
    Per-weekday open-gap stats for one symbol within [start, end].

    Returns {weekday: {"sessions": n, "positive": p, "weak_gap": w,
                       "flat": f, "negative": g}} for weekdays with at
    least one session. The previous close is the previous *trading*
    row's close (the first row of the window whose prior row falls
    outside is kept: its prev close still exists in the feed history).

    min_gap_pct raises the bar for "positive": the open must gap up by
    at least that percentage above the previous close. With 0.0 any
    strictly-higher open counts (the original rule). Opens that gap up
    but by less than the threshold land in "weak_gap".
    """
    window = [r for r in rows if start <= r["date"] <= end]
    stats: dict[str, dict] = defaultdict(
        lambda: {"sessions": 0, "positive": 0, "weak_gap": 0,
                 "flat": 0, "negative": 0}
    )
    for i, row in enumerate(window):
        if i == 0:
            prev = next((r for r in rows if r["date"] < row["date"]), None)
        else:
            prev = window[i - 1]
        if prev is None:
            continue               # no prev close -> first-ever session
        bucket = stats[row["date"].strftime("%A")]
        bucket["sessions"] += 1
        gap = (
            (row["open"] - prev["close"]) / prev["close"] * 100
            if prev["close"] > 0 else None
        )
        if gap is None:
            bucket["negative"] += 1     # unusable previous close
        elif gap > 0 and gap >= min_gap_pct:
            bucket["positive"] += 1
        elif gap > 0:
            bucket["weak_gap"] += 1
        elif gap == 0:
            bucket["flat"] += 1
        else:
            bucket["negative"] += 1
    return dict(stats)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_outputs(
    per_symbol_stats: dict[str, dict[str, dict]],
    failed: list[str],
    empty: list[str],
    start: date,
    end: date,
    min_sessions: int,
    min_gap_pct: float = 0.0,
) -> tuple[Path, Path]:
    """
    CSV of every symbol×weekday row + the markdown answer. Returns the
    two paths. A non-zero min_gap_pct suffixes the filenames so the
    original any-positive-open outputs are not clobbered.
    """
    stamp = f"{start:%Y%m%d}_{end:%Y%m%d}"
    suffix = f"_gap{min_gap_pct:g}pct" if min_gap_pct > 0 else ""
    csv_path = paths.REPORTS_DIR / f"positive_open_scan_{stamp}{suffix}.csv"
    md_path = paths.REPORTS_DIR / f"positive_open_scan_{stamp}{suffix}.md"

    lines = ["symbol,weekday,sessions,positive_opens,weak_gaps,flat_opens,"
             "negative_opens,positive_rate,qualifies"]
    for symbol in sorted(per_symbol_stats):
        for weekday in WEEKDAYS:
            s = per_symbol_stats[symbol].get(weekday)
            if not s or s["sessions"] == 0:
                continue
            rate = s["positive"] / s["sessions"]
            lines.append(
                f"{symbol},{weekday},{s['sessions']},{s['positive']},"
                f"{s['weak_gap']},{s['flat']},{s['negative']},{rate:.4f},"
                f"{'YES' if s['positive'] == s['sessions'] and s['sessions'] >= min_sessions else ''}"
            )
    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- the markdown answer -------------------------------------------
    md: list[str] = []
    md.append("# Positive-open scan - KMIALL universe")
    md.append("")
    md.append(f"- Window: **{start} .. {end}** (PSX trading sessions)")
    md.append(f"- Universe: {len(per_symbol_stats)} KMIALL symbols fetched"
              f" from dps.psx.com.pk EOD timeseries")
    rule = ("open strictly above the previous close" if min_gap_pct <= 0
            else f"open at least +{min_gap_pct:g}% above the previous close")
    md.append(f"- Rule: a symbol qualifies for a weekday when **every**"
              f" open of that weekday in the window gapped up"
              f" ({rule})")
    md.append(f"- Minimum sessions per weekday to qualify: **{min_sessions}**")
    md.append("")

    for weekday in WEEKDAYS:
        perfect, near = [], []
        total_sessions = 0
        for symbol, by_wd in per_symbol_stats.items():
            s = by_wd.get(weekday)
            if not s or s["sessions"] == 0:
                continue
            total_sessions += s["sessions"]
            if s["positive"] == s["sessions"]:
                if s["sessions"] >= min_sessions:
                    perfect.append((symbol, s["sessions"]))
                else:
                    near.append((symbol, s["sessions"], s["positive"]))
            elif s["sessions"] - s["positive"] == 1 and s["sessions"] >= min_sessions:
                near.append((symbol, s["sessions"], s["positive"]))
        perfect.sort(key=lambda t: (-t[1], t[0]))
        near.sort(key=lambda t: (-(t[1] - t[2]), t[0]))

        md.append(f"## {weekday} - always open positive")
        md.append("")
        if perfect:
            md.append(f"**{len(perfect)} symbol(s)** with a perfect record:")
            md.append("")
            md.append("| Symbol | Sessions |")
            md.append("|--------|----------|")
            for symbol, n in perfect:
                md.append(f"| {symbol} | {n} |")
        else:
            md.append("*None - no symbol gapped up on every "
                      f"{weekday} of the window.*")
        shown = ""
        more = ""
        if near:
            shown = ", ".join(
                f"{sym} ({pos}/{ses})" for sym, ses, pos in near[:12]
            )
            more = (
                f" … (+{len(near) - 12} more)" if len(near) > 12 else ""
            )
            md.append("")
        md.append(f"*Near-misses (≤1 missed open or short record):* "
                      f"{shown}{more}")

        # Leaderboard: the best openers even when nobody is perfect.
        # Rate first, then sessions, so a 50/51 beats a 40/41.
        ranked = [
            (symbol, s["sessions"], s["positive"])
            for symbol, by_wd in per_symbol_stats.items()
            if (s := by_wd.get(weekday))
            and s["sessions"] >= min_sessions and s["positive"] > 0
        ]
        ranked.sort(
            key=lambda t: (t[2] / t[1], t[1], t[0]), reverse=True
        )
        top = ranked[:10]
        if top:
            md.append("")
            md.append(f"**Top {len(top)} {weekday} openers** (best rates, "
                      f"≥{min_sessions} sessions):")
            md.append("")
            md.append("| Symbol | Positive opens | Rate |")
            md.append("|--------|----------------|------|")
            for symbol, sessions_, positive in top:
                md.append(
                    f"| {symbol} | {positive}/{sessions_} | "
                    f"{positive / sessions_:.0%} |"
                )
        md.append("")

    if empty:
        md.append(f"## Symbols with no DPS history ({len(empty)})")
        md.append("")
        md.append(", ".join(sorted(empty)))
        md.append("")
    if failed:
        md.append(f"## Symbols that failed to fetch ({len(failed)})")
        md.append("")
        md.append(", ".join(sorted(failed)))
        md.append("")

    md.append("---")
    md.append("")
    md.append("*Generated by `src/scan_positive_opens.py`. Open = DPS EOD"
              " `open` field; positive = strictly above the previous"
              " trading session's close. Past open behaviour is a"
              " statistic, not a guarantee.*")

    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return csv_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    # Karachi wall-clock default (owner's order: PKT everywhere) -
    # a UTC-offset machine would pick the wrong "today" before noon.
    today = datetime.now(ZoneInfo("Asia/Karachi")).date()
    parser = argparse.ArgumentParser(
        description=(
            "Scan DPS historical EOD for KMIALL stocks that open positive "
            "on every Monday/Tuesday/... within a window."
        )
    )
    parser.add_argument(
        "--start", type=date.fromisoformat, default=date(today.year - 1, 9, 9),
        help="Window start (ISO), default one year back: %(default)s",
    )
    parser.add_argument(
        "--end", type=date.fromisoformat, default=today,
        help="Window end (ISO), default today: %(default)s",
    )
    parser.add_argument(
        "--min-sessions", type=int, default=40,
        help="Minimum sessions of a weekday for a perfect record to count "
             "(default %(default)s)",
    )
    parser.add_argument(
        "--min-gap-pct", type=float, default=0.0,
        help="Minimum opening gap, in %% above the previous close, for an "
             "open to count as positive (default 0.0 = any higher open)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Fetch only the first N symbols (debug)",
    )
    parser.add_argument(
        "--from-cache", metavar="PATH", default=None,
        help="Skip fetching; read raw EOD rows from a previous --cache "
             "file",
    )
    parser.add_argument(
        "--cache", action="store_true",
        help="Write the raw EOD rows to data/processed/psx_eod_history.json",
    )
    return parser.parse_args()


def main() -> int:
    paths.ensure_dirs()
    paths.enable_utf8_stdout()

    args = parse_args()
    start, end = args.start, args.end
    min_sessions = args.min_sessions

    symbols = universe.load()
    if args.limit:
        symbols = symbols[: args.limit]
    gap_note = ("" if args.min_gap_pct <= 0 else
                f", gap at least +{args.min_gap_pct:g}%")
    print(
        f"Positive-open scan: {len(symbols)} KMIALL symbols, "
        f"{start} .. {end}, min {min_sessions} sessions per weekday"
        f"{gap_note}"
    )

    http = requests.Session()
    http.headers.update(HEADERS)

    per_symbol_stats: dict[str, dict[str, dict]] = {}
    failed: list[str] = []
    empty: list[str] = []
    cache: dict[str, list] = {}

    if args.from_cache:
        raw = json.loads(
            Path(args.from_cache).read_text(encoding="utf-8")
        )
        cache = {
            symbol: [
                {**row, "date": date.fromisoformat(row["date"])}
                for row in rows
            ]
            for symbol, rows in raw.items()
        }
        symbols = list(cache)
        for symbol in symbols:
            per_symbol_stats[symbol] = positive_open_rates(
                cache[symbol], start, end, args.min_gap_pct
            )
        print(f"Loaded {len(symbols)} symbols from cache "
              f"{args.from_cache}")
    else:
        try:
            for index, symbol in enumerate(symbols, start=1):
                rows = fetch_eod_rows(symbol, http)
                if rows is None:
                    failed.append(symbol)
                elif not rows:
                    empty.append(symbol)
                else:
                    per_symbol_stats[symbol] = positive_open_rates(
                        rows, start, end, args.min_gap_pct
                    )
                    if args.cache:
                        cache[symbol] = [
                            {**r, "date": r["date"].isoformat()} for r in rows
                        ]
                if index % 25 == 0 or index == len(symbols):
                    print(
                        f"  {index}/{len(symbols)} fetched "
                        f"({len(failed)} failed, {len(empty)} empty)"
                    )
                time.sleep(REQUEST_PAUSE)
        except KeyboardInterrupt:
            print("\nInterrupted - partial results not written.",
                  file=sys.stderr)
            return 130
        finally:
            http.close()

    if not per_symbol_stats:
        print("No symbol produced data - nothing to report.", file=sys.stderr)
        return 1

    csv_path, md_path = write_outputs(
        per_symbol_stats, failed, empty, start, end, min_sessions,
        args.min_gap_pct,
    )

    if args.cache and cache:
        cache_path = paths.PROCESSED_DIR / "psx_eod_history.json"
        cache_path.write_text(
            json.dumps(cache, separators=(",", ":")), encoding="utf-8"
        )
        print(f"Raw EOD cache written: {cache_path.name}")

    # Console headline: the perfect lists, per weekday.
    print()
    for weekday in WEEKDAYS:
        perfect = [
            (symbol, s["sessions"])
            for symbol, by_wd in per_symbol_stats.items()
            if (s := by_wd.get(weekday))
            and s["positive"] == s["sessions"]
            and s["sessions"] >= min_sessions
        ]
        perfect.sort(key=lambda t: (-t[1], t[0]))
        names = ", ".join(sym for sym, _ in perfect) or "- none -"
        print(f"{weekday:>10}: {len(perfect):>3} always-positive -> {names}")

    print(f"\nFull report: {md_path}")
    print(f"Full CSV:    {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
