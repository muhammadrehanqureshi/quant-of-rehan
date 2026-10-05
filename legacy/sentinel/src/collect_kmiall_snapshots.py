"""
KMIALL snapshot collector.

What this replaces
------------------
The previous version had its main routine at module level, so importing it
started a collection run. It hardcoded TEST_DURATION_SECONDS = 300, had no
awareness of trading hours (left overnight it would have written thousands of
identical stale snapshots), wrote one 121 KB pretty-printed JSON file per poll,
logged nothing durable, and only raised when *zero* instruments parsed -- a PSX
field reordering that broke half the symbols would have been saved as a valid
snapshot.

This version:
  * is a normal script with main() behind an __main__ guard
  * takes its runtime from the command line and defaults to "run until the
    current session closes"
  * refuses to poll a closed market, and can sleep until the next open
  * appends gzipped JSONL through psx_core.storage (7.3x smaller, 15 files
    instead of 61,668)
  * writes a human log and a machine-readable poll ledger under logs/
  * delegates parsing to psx_core.feed, which subscribes the ECLEAR broker
    feed (MKT-FEED socket) and raises rather than writing a degraded snapshot

Usage
-----
    python src/collect_kmiall_snapshots.py --status
    python src/collect_kmiall_snapshots.py --duration 60
    python src/collect_kmiall_snapshots.py --wait-for-open
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import feed, logs, paths, sessions, storage, universe

LOGGER_NAME = "collector"
DEFAULT_INTERVAL = 5.0

# Abort the run after this many consecutive failed polls. A single transient
# network error is normal; twelve in a row (one minute at the default interval)
# means the feed or the connection is broken and continuing only fills the log.
MAX_CONSECUTIVE_FAILURES = 12

# Per-poll retry delays. Kept short so a retry cannot overrun the poll slot.
RETRY_BACKOFF = (0.5, 1.5)

_STOP_REQUESTED = False


def _request_stop(signum, frame) -> None:  # noqa: ARG001
    """Handle Ctrl+C by finishing the current poll and closing cleanly."""
    global _STOP_REQUESTED
    _STOP_REQUESTED = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect KMIALL intraday snapshots from PSX Terminal.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL,
        help="Seconds between polls.",
    )
    parser.add_argument(
        "--duration", type=float, default=None,
        help="Stop after this many seconds. Default: run until the session closes.",
    )
    parser.add_argument(
        "--max-polls", type=int, default=None,
        help="Stop after this many successful polls.",
    )
    parser.add_argument(
        "--market", default=feed.DEFAULT_MARKET,
        help="Market block to read from the page.",
    )
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="Per-request HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--min-instruments", type=int, default=feed.MIN_EXPECTED_INSTRUMENTS,
        help="Refuse a snapshot parsing fewer instruments than this.",
    )
    parser.add_argument(
        "--wait-for-open", action="store_true",
        help="If the market is closed, sleep until the next open instead of exiting.",
    )
    parser.add_argument(
        "--ignore-schedule", action="store_true",
        help="Poll regardless of trading hours. For testing only.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch and parse but write no snapshots.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Print stored-snapshot counts and exit.",
    )
    parser.add_argument(
        "--compact", metavar="DATE",
        help="Recompress one trading date's file (YYYY-MM-DD) and exit.",
    )

    return parser.parse_args(argv)


def poll_once(
    http: requests.Session,
    symbols: list[str],
    args: argparse.Namespace,
) -> dict:
    """
    Fetch, parse and project one snapshot. Retries transient network errors.

    Raises the last exception if every attempt fails, so the caller decides
    whether one bad poll matters.
    """
    attempts = 1 + len(RETRY_BACKOFF)
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            market_data = feed.fetch_snapshot(
                http,
                market=args.market,
                timeout=args.timeout,
                min_instruments=args.min_instruments,
            )
            return feed.build_universe_snapshot(market_data, symbols, args.market)
        except (requests.RequestException, feed.FeedError) as exc:
            last_error = exc
            if attempt < len(RETRY_BACKOFF):
                time.sleep(RETRY_BACKOFF[attempt])

    assert last_error is not None
    raise last_error


def _deadline(args: argparse.Namespace, started: datetime) -> datetime | None:
    """
    When this run must stop: the earlier of --duration and the session close.

    Returning None means "run until stopped", which only happens with
    --ignore-schedule and no --duration.
    """
    candidates: list[datetime] = []

    if args.duration is not None:
        candidates.append(started + timedelta(seconds=args.duration))

    if not args.ignore_schedule:
        close = sessions.leg_end(started)
        if close is not None:
            candidates.append(close.astimezone(timezone.utc))

    return min(candidates) if candidates else None


def run_session(
    args: argparse.Namespace,
    symbols: list[str],
    logger,
) -> dict:
    """Poll on a fixed grid until the deadline, the poll cap or Ctrl+C."""
    started = datetime.now(timezone.utc)
    trading_date = sessions.trading_date(started).isoformat()
    stop_at = _deadline(args, started)

    logger.info(
        "Collecting %s | %d symbols | interval %.1fs | until %s",
        args.market,
        len(symbols),
        args.interval,
        stop_at.astimezone(sessions.PKT).strftime("%Y-%m-%d %H:%M:%S PKT")
        if stop_at
        else "stopped",
    )
    if args.dry_run:
        logger.info("Dry run: snapshots will be parsed but not written.")

    http = requests.Session()
    grid_origin = time.monotonic()

    polls = written = failures = 0
    consecutive_failures = 0
    instrument_counts: list[int] = []

    try:
        while True:
            now = datetime.now(timezone.utc)

            if _STOP_REQUESTED:
                logger.info("Stop requested; finishing.")
                break
            if stop_at is not None and now >= stop_at:
                logger.info("Deadline reached.")
                break
            if args.max_polls is not None and polls >= args.max_polls:
                logger.info("Poll cap of %d reached.", args.max_polls)
                break
            if not args.ignore_schedule and not sessions.is_open(now):
                logger.info("Market is closed; stopping.")
                break

            polls += 1
            poll_started = time.monotonic()

            try:
                snapshot = poll_once(http, symbols, args)
            except Exception as exc:
                failures += 1
                consecutive_failures += 1
                logger.warning("Poll %d failed: %s", polls, exc)
                logs.poll_record(
                    LOGGER_NAME,
                    {
                        "poll": polls,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                    trading_date,
                )
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    logger.error(
                        "%d consecutive failures; aborting.", consecutive_failures
                    )
                    break
            else:
                consecutive_failures = 0
                instrument_counts.append(snapshot["marketInstrumentCount"])

                if not args.dry_run:
                    storage.append_snapshot(snapshot)
                    written += 1

                elapsed = time.monotonic() - poll_started
                logs.poll_record(
                    LOGGER_NAME,
                    {
                        "poll": polls,
                        "ok": True,
                        "generatedAt": snapshot["generatedAt"],
                        "instruments": snapshot["marketInstrumentCount"],
                        "available": snapshot["quoteAvailable"],
                        "open": snapshot["quoteOpen"],
                        "suspended": snapshot["quoteSuspended"],
                        "parser": snapshot["parser"],
                        "bytes": snapshot["sourceBytes"],
                        "seconds": round(elapsed, 3),
                        "written": not args.dry_run,
                    },
                    trading_date,
                )

                if polls == 1 or polls % 12 == 0:
                    logger.info(
                        "Poll %d | %d instruments | %d/%d quotes "
                        "(%d open, %d suspended) | %s parser | %.2fs",
                        polls,
                        snapshot["marketInstrumentCount"],
                        snapshot["quoteAvailable"],
                        snapshot["universeCount"],
                        snapshot["quoteOpen"],
                        snapshot["quoteSuspended"],
                        snapshot["parser"],
                        elapsed,
                    )

            # Fixed grid rather than sleep(interval): the latter adds request
            # time to every gap, so a 5s interval drifts to 6s and the dataset
            # loses ticks over a six-hour session.
            target = grid_origin + polls * args.interval
            remaining = target - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
    finally:
        http.close()

    return {
        "polls": polls,
        "written": written,
        "failures": failures,
        "trading_date": trading_date,
        "min_instruments": min(instrument_counts) if instrument_counts else 0,
        "max_instruments": max(instrument_counts) if instrument_counts else 0,
    }


def command_status() -> int:
    """Print what is on disk. The first thing to run when resuming work."""
    paths.enable_utf8_stdout()

    counts = storage.count_snapshots()
    total = sum(counts.values())

    print(f"Snapshot directory : {paths.SNAPSHOT_DIR}")
    print(f"Trading dates      : {len(counts)}")
    print(f"Snapshots          : {total:,}")

    if counts:
        print()
        print(f"{'date':<12} {'snapshots':>10} {'weekday':>10} {'expected':>10}")
        for date_string, count in counts.items():
            day = datetime.fromisoformat(date_string).date()
            legs = sessions.legs_for(day)
            expected = sum(
                int(
                    (
                        datetime.combine(day, leg.end)
                        - datetime.combine(day, leg.start)
                    ).total_seconds()
                    // DEFAULT_INTERVAL
                )
                for leg in legs
            )
            print(
                f"{date_string:<12} {count:>10,} {day.strftime('%a'):>10} "
                f"{expected:>10,}"
            )

    now = datetime.now(timezone.utc)
    print()
    print(f"Now                : {sessions.to_pkt(now):%Y-%m-%d %H:%M:%S} PKT")
    print(f"Market open        : {sessions.is_open(now)}")
    if sessions.is_open(now):
        print(f"Session closes     : {sessions.leg_end(now):%H:%M:%S} PKT")
    else:
        print(f"Next open          : {sessions.next_open(now):%Y-%m-%d %H:%M:%S} PKT")

    return 0


def command_compact(trading_date: str) -> int:
    paths.enable_utf8_stdout()
    try:
        before, after = storage.compact_day(trading_date)
    except FileNotFoundError:
        print(f"No snapshot file for {trading_date}")
        return 1
    saved = before - after
    print(
        f"{trading_date}: {before:,} -> {after:,} bytes "
        f"({saved:,} saved, {before / after:.2f}x)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.status:
        return command_status()
    if args.compact:
        return command_compact(args.compact)

    paths.ensure_dirs()
    logger = logs.get_logger(LOGGER_NAME)

    signal.signal(signal.SIGINT, _request_stop)

    try:
        symbols = universe.load()
    except universe.UniverseError as exc:
        logger.error("%s", exc)
        return 2

    membership = universe.check_membership()
    logger.info(
        "Universe: %d symbols, %d tagged %s",
        membership["total"],
        membership["tagged_kmiall"],
        universe.KMIALL_INDEX_TAG,
    )

    now = datetime.now(timezone.utc)

    if not args.ignore_schedule and not sessions.is_open(now):
        opens_at = sessions.next_open(now)
        if not args.wait_for_open:
            logger.error(
                "Market is closed. Next open %s. "
                "Pass --wait-for-open to sleep until then, or --ignore-schedule "
                "to poll anyway.",
                opens_at.strftime("%Y-%m-%d %H:%M:%S PKT"),
            )
            return 3

        wait_seconds = (opens_at.astimezone(timezone.utc) - now).total_seconds()
        logger.info(
            "Market closed. Sleeping %.1f hours until %s.",
            wait_seconds / 3600.0,
            opens_at.strftime("%Y-%m-%d %H:%M:%S PKT"),
        )
        while wait_seconds > 0 and not _STOP_REQUESTED:
            time.sleep(min(wait_seconds, 30.0))
            wait_seconds = (
                opens_at.astimezone(timezone.utc) - datetime.now(timezone.utc)
            ).total_seconds()
        if _STOP_REQUESTED:
            logger.info("Stopped before the session opened.")
            return 0

    result = run_session(args, symbols, logger)

    logger.info(
        "Done. %d polls, %d written, %d failed. Instruments %d-%d.",
        result["polls"],
        result["written"],
        result["failures"],
        result["min_instruments"],
        result["max_instruments"],
    )

    if result["written"]:
        path = storage.day_file(result["trading_date"])
        logger.info("Snapshots: %s (%.1f MB)", path, path.stat().st_size / 1e6)

    if result["polls"] and result["failures"] == result["polls"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())




