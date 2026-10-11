"""Walk a trading day through the owner's four market states.

Run from the repo root:

    python examples/market_state_walk.py
    python examples/market_state_walk.py --date 2026-10-09   # a Friday

Prints every state change between 08:00 and 18:00 for the chosen day
(Monday 2026-10-12 by default) and then the exact window edges, so the
strict boundaries are visible: 09:15:00 ends the pre-market, 09:32:00 opens
the market, 15:30:00 closes it, 15:32:00 starts the post-market and
15:49:00 ends it. Friday trades two windows and has its own post-market
window.

The scanner runs only where the state is MARKET. Pre-market and post-market
are reported for the record and are never scanned (owner order 2026-10-11).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    KARACHI,
    MarketState,
    is_scan_window,
    market_state_at,
    post_market_window,
    pre_market_window,
    session_bands,
)

WALK_FROM = 8 * 60    # 08:00
WALK_TO = 18 * 60     # 18:00


def at(day: date, minute_of_day: int, *, second: int = 0,
       microsecond: int = 0) -> datetime:
    """A Karachi instant on `day`, from a minute-of-day and optional sub-parts."""
    return datetime(day.year, day.month, day.day, 0, 0,
                    tzinfo=KARACHI) + timedelta(
                        minutes=minute_of_day, seconds=second,
                        microseconds=microsecond)


def hhmm(pair: tuple[int, int]) -> str:
    return f"{pair[0]:02d}:{pair[1]:02d}"


def windows(day: date) -> list[tuple[str, str, str, bool]]:
    """The day's windows as (state, start, end, scannable), in time order."""
    rows: list[tuple[str, str, str, bool]] = []
    pre = pre_market_window(day)
    if pre is not None:
        rows.append((MarketState.PRE_MARKET.value, hhmm(pre[0]), hhmm(pre[1]),
                     False))
    for band in session_bands(day):
        rows.append((MarketState.MARKET.value, hhmm(band[0]), hhmm(band[1]),
                     True))
    post = post_market_window(day)
    if post is not None:
        rows.append((MarketState.POST_MARKET.value, hhmm(post[0]),
                     hhmm(post[1]), False))
    return rows


def timeline(day: date) -> list[tuple[str, int, int]]:
    """(state, start_minute, end_minute) runs across the walked window."""
    runs: list[tuple[str, int, int]] = []
    current, started = None, WALK_FROM
    for minute in range(WALK_FROM, WALK_TO):
        state = market_state_at(at(day, minute)).value
        if state != current:
            if current is not None:
                runs.append((current, started, minute))
            current, started = state, minute
    runs.append((current or MarketState.CLOSED.value, started, WALK_TO))
    return runs


def text_of(minute_of_day: int) -> str:
    return f"{minute_of_day // 60:02d}:{minute_of_day % 60:02d}"


def show_edges(day: date) -> None:
    """The last microsecond before, and the first instant of, every window."""
    for _, start, end, _ in windows(day):
        start_minute = int(start[:2]) * 60 + int(start[3:])
        end_minute = int(end[:2]) * 60 + int(end[3:])
        for minute, micro in ((start_minute, -1), (start_minute, 0),
                              (end_minute, -1), (end_minute, 0)):
            moment = at(day, minute) + timedelta(microseconds=micro)
            print(f"  {moment:%H:%M:%S.%f}  "
                  f"{market_state_at(moment).value:<12}"
                  f"scan: {'yes' if is_scan_window(moment) else 'no'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="market_state_walk")
    ap.add_argument("--date", default="2026-10-12",
                    help="any date to walk (default 2026-10-12, a Monday)")
    args = ap.parse_args(argv)
    day = date.fromisoformat(args.date)

    print(f"Owner windows, {day.isoformat()} ({day.strftime('%A')})")
    for name, start, end, scannable in windows(day):
        print(f"  {name:<12} {start}-{end}   scanned: "
              f"{'yes' if scannable else 'no'}")
    if not windows(day):
        print("  (no session: weekend or PSX holiday)")
    print()

    print(f"Timeline, {text_of(WALK_FROM)} to {text_of(WALK_TO)}")
    for state, start, end in timeline(day):
        note = "   (scanning runs here)" if state == MarketState.MARKET.value \
            else ""
        print(f"  {text_of(start)}-{text_of(end)}  {state:<12}{note}")
    print()

    print("Exact edges (one microsecond before each boundary, then on it)")
    show_edges(day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
