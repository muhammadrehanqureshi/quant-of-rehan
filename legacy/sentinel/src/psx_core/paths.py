"""
Canonical filesystem layout, anchored to the repository root.

Every path in the project must come from this module. Seventeen scripts
previously used bare relative paths such as Path("data/kmiall_tickers.json"),
which silently resolved against the caller's working directory and broke
whenever a script was run from anywhere other than the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# src/psx_core/paths.py -> src/psx_core -> src -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SRC_DIR = PROJECT_ROOT / "src"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
REPORTS_DIR = PROJECT_ROOT / "reports"
TESTS_DIR = PROJECT_ROOT / "tests"

SNAPSHOT_DIR = DATA_DIR / "snapshots"
PROCESSED_DIR = DATA_DIR / "processed"

# --- Universe -------------------------------------------------------------
UNIVERSE_FILE = DATA_DIR / "kmiall_tickers.json"

# --- Pipeline outputs -----------------------------------------------------
INTRADAY_CSV = PROCESSED_DIR / "kmiall_intraday.csv"
INTRADAY_PARQUET = PROCESSED_DIR / "kmiall_intraday.parquet"
INTRADAY_SUMMARY = PROCESSED_DIR / "kmiall_intraday_summary.json"
VALIDATION_JSON = PROCESSED_DIR / "kmiall_intraday_validation_report.json"
VALIDATION_TXT = REPORTS_DIR / "kmiall_intraday_validation_report.txt"

FEATURES_CSV = PROCESSED_DIR / "kmiall_features_v1.csv"
FEATURES_PARQUET = PROCESSED_DIR / "kmiall_features_v1.parquet"
FEATURES_SUMMARY = PROCESSED_DIR / "kmiall_feature_summary.json"
FEATURES_REPORT = REPORTS_DIR / "kmiall_feature_engine_v1.txt"

# --- Decision / portfolio ---------------------------------------------------
PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
DECISIONS_LEDGER = LOGS_DIR / "decisions.jsonl"


def ensure_dirs() -> None:
    """Create every directory the pipeline writes to."""
    for directory in (
        DATA_DIR,
        LOGS_DIR,
        REPORTS_DIR,
        SNAPSHOT_DIR,
        PROCESSED_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def enable_utf8_stdout() -> None:
    """
    Force UTF-8 on stdout/stderr.

    The validator prints U+2713 (check mark). On Windows the default console
    encoding is cp1252, which cannot encode it, so the validator died with
    UnicodeEncodeError before writing its report. Callers that print any
    non-ASCII character must call this first.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Redirected to a stream that cannot be reconfigured;
                # printing will still succeed with the replacement handler
                # wherever the stream itself supports it.
                pass


def bootstrap_import_path() -> None:
    """
    Put src/ on sys.path so `from psx_core import ...` works when a script
    is executed directly (python src/collect_kmiall_snapshots.py).
    """
    src = str(SRC_DIR)
    if src not in sys.path:
        sys.path.insert(0, src)



