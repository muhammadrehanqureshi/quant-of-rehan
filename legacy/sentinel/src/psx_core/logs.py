"""
Structured logging for the collector and pipeline scripts.

`logs/` existed but was empty: the original collector printed to a console that
nothing captured. An unattended multi-day collector needs a durable record of
every poll, every retry and every failure, because the interesting failures
(feed format change, network stall, a session that produced no ticks) are only
diagnosable after the fact.

Two sinks per run:

  * console  -- human readable, UTF-8 safe on the Windows cp1252 terminal
  * file     -- logs/<name>-<trading-date>.log, one line per event

The collector also writes a machine-readable poll ledger via `poll_record()`:
logs/collector-<date>.ndjson, one JSON object per poll. That is what to graph
when asking "did we actually get 4,296 clean ticks today, and where were the
gaps?" without re-reading a gigabyte of snapshots.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import paths, sessions

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_TIME_FORMAT = "%H:%M:%S"


def log_file_for(name: str, trading_date: str | None = None) -> Path:
    """
    The file get_logger writes to for this logger name and trading date.

    One definition so the naming convention lives in exactly one place -
    callers that want to tell the operator where the log is (the live
    runner's startup banner) cannot drift from what get_logger creates.
    """
    trading_date = trading_date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()
    return paths.LOGS_DIR / f"{name}-{trading_date}.log"


def get_logger(
    name: str,
    trading_date: str | None = None,
    level: int = logging.INFO,
    *,
    quiet_console: bool = False,
) -> logging.Logger:
    """
    Return a logger writing to both the console and logs/<name>-<date>.log.

    Idempotent: calling it twice with the same name does not duplicate handlers,
    so a long-running collector that re-derives its logger across a session
    boundary will not start emitting every line twice.

    quiet_console=True drops the console handler to WARNING - the terminal
    then shows only problems, while the file still records everything at
    DEBUG. The live runner uses this and prints its decision lines
    directly, so the console carries just the trade calls and the
    end-of-day summary.
    """
    paths.enable_utf8_stdout()
    paths.ensure_dirs()

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    trading_date = trading_date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()

    console = logging.StreamHandler()
    console.setLevel(logging.WARNING if quiet_console else level)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _TIME_FORMAT))
    logger.addHandler(console)

    log_file = log_file_for(name, trading_date)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT, "%Y-%m-%d %H:%M:%S"))
    logger.addHandler(file_handler)

    return logger


def ledger_path(name: str, trading_date: str | None = None) -> Path:
    trading_date = trading_date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()
    return paths.LOGS_DIR / f"{name}-{trading_date}.ndjson"


def poll_record(name: str, record: dict, trading_date: str | None = None) -> None:
    """Append one machine-readable event to the run's NDJSON ledger."""
    path = ledger_path(name, trading_date)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"at": datetime.now(timezone.utc).isoformat(), **record}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


