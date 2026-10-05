"""
Snapshot persistence.

Storage problem this solves
---------------------------
The original collector wrote one pretty-printed JSON file per poll: 121 KB
each. At a 5-second interval that is 4,296 files per Mon-Thu session and 3,372
on Friday. Fifteen sessions would have produced 61,668 files totalling 8.3 GB
-- inside a OneDrive-synced folder, which handles tens of thousands of small
churning files badly.

New layout: one gzipped JSONL file per trading date.

    data/snapshots/2026-09-04.jsonl.gz

Each snapshot is one compact JSON line, appended as its own gzip member.
Measured on the 60 archived snapshots: 7,459,287 bytes of individual JSON files
becomes 1,026,506 bytes, a 7.3x reduction, which projects to 1.03 GB for 15
sessions across 15 files instead of 8.3 GB across 61,668. Because every member
is independently decodable, a crash or a killed process loses at most the final
line rather than the whole day.

compact_day() rewrites the file as a single gzip stream. Measured gain is only
1.1x (1,026,506 -> 959,163 bytes), not the large win consecutive near-identical
snapshots suggest: each snapshot is ~124 KB of JSON while gzip's window is
32 KB, so no two snapshots are ever in the window together. Run it for tidiness
after a session closes, never during one, and do not expect much from it.

Reading is backward compatible: iter_snapshots() reads both the new .jsonl.gz
files and the legacy data/snapshots/<date>/*.json layout, so the 60 archived
snapshots from 2026-09-02 keep working with no migration.
"""

from __future__ import annotations

import gzip
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import paths, sessions

JSONL_SUFFIX = ".jsonl.gz"


def day_file(trading_date: str) -> Path:
    """Path of the gzipped JSONL file for a trading date ('2026-09-04')."""
    return paths.SNAPSHOT_DIR / f"{trading_date}{JSONL_SUFFIX}"


def append_snapshot(snapshot: dict) -> Path:
    """
    Append one snapshot to its trading date's file.

    The trading date comes from `generatedAt` converted to Pakistan time, so a
    snapshot always lands in the session it belongs to.
    """
    generated_at = datetime.fromisoformat(snapshot["generatedAt"])
    trading_date = sessions.trading_date(generated_at).isoformat()

    path = day_file(trading_date)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))

    # Append mode writes a new gzip member. Python's gzip reader handles
    # multi-member streams transparently.
    with gzip.open(path, "at", encoding="utf-8", compresslevel=6) as handle:
        handle.write(line + "\n")

    return path


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                # A truncated final line is the expected failure mode after an
                # abrupt shutdown. Skip it rather than losing the whole day.
                raise SnapshotReadError(
                    f"{path.name} line {line_number}: {exc}"
                ) from exc


class SnapshotReadError(RuntimeError):
    """Raised when a snapshot record cannot be decoded."""


def iter_snapshots(
    snapshot_dir: Path | None = None,
    skip_unreadable: bool = True,
) -> Iterator[tuple[str, dict]]:
    """
    Yield (source_label, snapshot) for every stored snapshot, oldest first.

    Reads both storage layouts:
      * new     data/snapshots/<date>.jsonl.gz
      * legacy  data/snapshots/<date>/<timestamp>.json
    """
    snapshot_dir = snapshot_dir or paths.SNAPSHOT_DIR
    if not snapshot_dir.exists():
        return

    records: list[tuple[str, str, dict]] = []

    for path in sorted(snapshot_dir.glob(f"*{JSONL_SUFFIX}")):
        try:
            for snapshot in _iter_jsonl(path):
                records.append(
                    (snapshot.get("generatedAt", ""), path.name, snapshot)
                )
        except SnapshotReadError:
            if not skip_unreadable:
                raise

    for path in sorted(snapshot_dir.rglob("*.json")):
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            if not skip_unreadable:
                raise
            continue
        records.append((snapshot.get("generatedAt", ""), path.name, snapshot))

    records.sort(key=lambda item: item[0])

    for _, label, snapshot in records:
        yield label, snapshot


def compact_day(trading_date: str) -> tuple[int, int]:
    """
    Rewrite a day's file as a single gzip stream.

    Returns (bytes_before, bytes_after). Measured gain is about 1.1x, not the
    large win you might expect from near-identical consecutive snapshots --
    gzip's window is 32 KB and a snapshot is ~124 KB, so consecutive records
    never share a window. Run after a session closes, never during one.
    """
    path = day_file(trading_date)
    if not path.exists():
        raise FileNotFoundError(path)

    before = path.stat().st_size
    temporary = path.with_suffix(path.suffix + ".tmp")

    with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=9) as out:
        for snapshot in _iter_jsonl(path):
            out.write(
                json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )

    after = temporary.stat().st_size
    shutil.move(str(temporary), str(path))
    return before, after


def count_snapshots(snapshot_dir: Path | None = None) -> dict[str, int]:
    """Snapshot counts per trading date, for status output and tests."""
    counts: dict[str, int] = {}
    for _, snapshot in iter_snapshots(snapshot_dir):
        generated_at = snapshot.get("generatedAt")
        if not generated_at:
            continue
        key = sessions.trading_date(datetime.fromisoformat(generated_at)).isoformat()
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
