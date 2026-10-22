"""The durable session archive: bars on disk, precisely, for any hour.

The service has to be useful at 23:00 on a Saturday, when no exchange is open
and no recording is running. That is not a UI question, it is a storage
question, and this module is the answer: every finished session is written out
once, in full precision, next to the identity of the capture file it came
from, so a chart can be drawn months later without a live feed, without the
recorder running, and without guessing what was in the data.

What "precisely" means here, field by field:

* **The exchange minute is stored as it was stamped**, with its Karachi offset
  (SO-8), never re-derived and never rounded to a coarser grain.
* **Prices keep their full floating point value.** Nothing is formatted on the
  way in, so a research pass over the archive sees the same numbers the chart
  drew.
* **Volume keeps the venue's own counter semantics.** A bar carries the volume
  the difference of that counter produced, and a carried bar (a minute the
  tape held no row for) is flagged rather than smoothed.
* **``prints`` travels with the bar**, because "this minute traded fourteen
  times" is a different fact from "this minute traded once", and a research
  question is allowed to care.
* **The capture is identified, not assumed.** Name, byte size, modification
  time and a SHA-256 of the file are recorded in the day's manifest, so any
  bar in the archive can be traced to the exact file it was built from, and a
  later rebuild can prove whether the source changed.
* **Every symbol file is hashed too**, so a manifest can be verified without
  re-reading the tape.

Layout::

    data/archive/2026-10-16/manifest.json      the day's identity and totals
    data/archive/2026-10-16/OGDC.ndjson        one line per minute bar

The archive is written for *finished* sessions. Today's session is served
live from the recorder's own file (which is fresher than anything written
here), and it is archived when the service next sees it as a past day, or
immediately by ``python -m charts --build-archive YYYY-MM-DD``. That split is
deliberate: rewriting today's 8 MB of bars on every poll would be disk churn
for no gain, and an archive that changes while it is being read is not
research material.

Nothing in this module invents a value. A symbol the tape never printed has no
file here, which is the honest shape of "there is no data".
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from charts.contract import Bar

ROOT = Path(__file__).resolve().parents[1]

#: Bumped when the row or manifest shape changes in a way a reader must know.
ARCHIVE_VERSION = 1

#: Where the archive lives by default. ``data/`` is gitignored: the market
#: data is the owner's, never the repository's.
DEFAULT_ARCHIVE_DIR = ROOT / "data" / "archive"

#: Where a capture file is looked for by default: this project's own two
#: directories, in order. Predictable on purpose, so a caller (and a test)
#: knows exactly what was searched.
DEFAULT_CAPTURE_DIRS = (
    ROOT / "data" / "feed_capture",
    ROOT / "data" / "tape",
)

#: The extraction-era convenience: the parent project's recorder directory. It
#: is *discovered* rather than assumed (see `discover_capture_dirs`) and only
#: by the command line entry point, so library behaviour stays predictable.
SIBLING_CAPTURE_DIR = ROOT.parent / "quant-of-rehan" / "data" / "feed_capture"

#: An operator can point the service somewhere else without a flag.
CAPTURE_DIR_ENV = "CHART_TAPE_DIR"

_READ_CHUNK = 1 << 20


def identify(path: Path, *, hash_file: bool = True) -> dict:
    """The identity of a capture file: name, size, mtime and its SHA-256.

    A file being appended to while this runs is a real possibility on a live
    session, so the hash is taken over the bytes that exist at that moment and
    the size and mtime are recorded beside it: a reader can see whether the
    file moved under it.
    """
    stat = path.stat()
    digest = hashlib.sha256()
    if hash_file:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(_READ_CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
    return {"name": path.name, "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": digest.hexdigest() if hash_file else ""}


def capture_candidates(day: date, dirs: tuple[Path, ...] | list[Path],
                       ) -> list[Path]:
    """Every capture file for `day` that exists, in the order it is looked for.

    The vendored bar builder owns the naming convention *and* its own default
    location (``capture_YYYYMMDD.ndjson`` beside the parent project's data).
    The configured directories win, and the builder's own path is only the
    last candidate, so a caller that points the service at a recording
    directory gets exactly the captures that directory holds, even when a
    part of the repository keeps its own files with the same name. A caller
    using the default directories still gets both: they share the same
    directory as the builder, so the order cannot put older history above
    the working recording.
    """
    from src.data import tape_bars  # local import: keeps import cost off boot

    canonical = tape_bars.capture_path(day)
    found: list[Path] = []
    for directory in dirs:
        candidate = Path(directory) / canonical.name
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    if canonical.is_file() and canonical not in found:
        found.append(canonical)
    return found


def discover_capture_dirs() -> tuple[Path, ...]:
    """Every capture directory worth searching for this deployment.

    The project's own directories always; the parent project's recorder
    directory only when it exists and actually holds captures, because a
    convenience that silently points at an empty directory is worse than no
    convenience at all; and whatever ``CHART_TAPE_DIR`` names, which wins for
    the operator who moved the recording somewhere else. Used by the command
    line entry point, never by the library, so a test knows what it searched.
    """
    found: list[Path] = []
    from_env = os.environ.get(CAPTURE_DIR_ENV, "").strip()
    if from_env:
        found.append(Path(from_env))
    found.extend(DEFAULT_CAPTURE_DIRS)
    if SIBLING_CAPTURE_DIR.is_dir() and any(
            SIBLING_CAPTURE_DIR.glob("capture_*.ndjson")):
        found.append(SIBLING_CAPTURE_DIR)
    seen: list[Path] = []
    for item in found:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write a file whole or not at all, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent),
                                         prefix=f".{path.name}.",
                                         suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass
class ArchivedSession:
    """One archived day, as the archive and the API describe it."""

    day: str
    symbols: int = 0
    bars: int = 0
    priced_bars: int = 0
    carried_bars: int = 0
    volume_available: bool = False
    capture: dict | None = None
    built_at: str = ""
    builds: int = 0
    first_observation: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"day": self.day, "symbols": self.symbols, "bars": self.bars,
                "priced_bars": self.priced_bars,
                "carried_bars": self.carried_bars,
                "volume_available": self.volume_available,
                "capture": self.capture, "built_at": self.built_at,
                "builds": self.builds,
                "first_observation": self.first_observation,
                "notes": list(self.notes)}


class SessionArchive:
    """The archive directory, read and written. No clock, no network."""

    def __init__(self, root: Path | str = DEFAULT_ARCHIVE_DIR) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------ addresses
    def day_dir(self, day: date | str) -> Path:
        return self.root / _day_text(day)

    def symbol_path(self, day: date | str, symbol: str) -> Path:
        return self.day_dir(day) / f"{symbol.strip().upper()}.ndjson"

    def manifest_path(self, day: date | str) -> Path:
        return self.day_dir(day) / "manifest.json"

    # -------------------------------------------------------------- reading
    def days(self) -> list[str]:
        """Every archived day, newest first. A day is a directory with a manifest."""
        if not self.root.is_dir():
            return []
        found = [entry.name for entry in self.root.iterdir()
                 if entry.is_dir() and (entry / "manifest.json").is_file()]
        return sorted(found, reverse=True)

    def manifest(self, day: date | str) -> dict | None:
        path = self.manifest_path(day)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return raw if isinstance(raw, dict) else None

    def summary(self, day: date | str) -> ArchivedSession | None:
        raw = self.manifest(day)
        if raw is None:
            return None
        return ArchivedSession(
            day=str(raw.get("day", _day_text(day))),
            symbols=int(raw.get("symbols", 0)),
            bars=int(raw.get("bars", 0)),
            priced_bars=int(raw.get("priced_bars", 0)),
            carried_bars=int(raw.get("carried_bars", 0)),
            volume_available=bool(raw.get("volume_available", False)),
            capture=raw.get("capture"),
            built_at=str(raw.get("built_at", "")),
            builds=int(raw.get("builds", 0)),
            first_observation=raw.get("first_observation"),
            notes=[str(line) for line in raw.get("notes", [])],
        )

    def sessions(self) -> list[dict]:
        """Every archived day, newest first, as dictionaries for the API."""
        rows: list[dict] = []
        for day in self.days():
            summary = self.summary(day)
            if summary is not None:
                rows.append(summary.as_dict())
        return rows

    def has(self, day: date | str, symbol: str) -> bool:
        return self.symbol_path(day, symbol).is_file()

    def symbols(self, day: date | str) -> list[str]:
        directory = self.day_dir(day)
        if not directory.is_dir():
            return []
        return sorted(entry.stem for entry in directory.glob("*.ndjson"))

    def read(self, day: date | str, symbol: str,
             limit: int | None = None) -> list[Bar]:
        """The archived bars for one symbol on one day, oldest first.

        A malformed line is a ContractError rather than a skipped row: a chart
        that quietly drops a bar it cannot parse is a chart that lies about
        the day.
        """
        path = self.symbol_path(day, symbol)
        if not path.is_file():
            return []
        bars: list[Bar] = []
        with path.open("r", encoding="utf-8") as stream:
            for number, line in enumerate(stream, start=1):
                text = line.strip()
                if not text:
                    continue
                bars.append(_row_to_bar(text, path, number))
        if limit is not None and limit > 0:
            return bars[-limit:]
        return bars

    def verify(self, day: date | str) -> list[str]:
        """Re-hash every symbol file against the manifest's own hashes.

        Returns the list of mismatches, empty when the archive is intact. It
        exists so a research pass can prove the files it reads are the files
        the manifest describes.
        """
        raw = self.manifest(day)
        if raw is None:
            return [f"{_day_text(day)}: no manifest"]
        problems: list[str] = []
        for symbol, facts in sorted((raw.get("symbol_files") or {}).items()):
            path = self.symbol_path(day, symbol)
            if not path.is_file():
                problems.append(f"{symbol}: file is missing")
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != facts.get("sha256"):
                problems.append(f"{symbol}: hash mismatch")
        return problems

    # -------------------------------------------------------------- writing
    def write(self, tape, *, capture: dict | None = None,
              force: bool = False, built_at: str = "") -> ArchivedSession:
        """Archive one built session, symbol by symbol.

        ``tape`` is the vendored builder's own ``TapeBars``: this module never
        builds a bar, it only stores what that one authority produced. An
        existing manifest for the same capture hash is left alone unless
        ``force`` is set, so re-running a build cannot churn the archive.

        The one exception is a manifest that recorded *nothing* for a tape
        that is not empty: that is a broken record of a real session (an
        earlier build read the wrong symbol list, say), so it is rebuilt
        rather than trusted. A chart that answers "no bars" for a day whose
        capture holds twenty thousand of them is worse than a slow build.
        """
        day = tape.day
        existing = self.manifest(day)
        self_heal = (existing is not None and int(existing.get("bars", 0)) == 0
                     and bool(getattr(tape, "bars", None)))
        if (existing is not None and not force and not self_heal
                and capture is not None
                and (existing.get("capture") or {}).get("sha256")
                == capture.get("sha256")
                and existing.get("capture", {}).get("bytes")
                == capture.get("bytes")):
            summary = self.summary(day)
            assert summary is not None
            return summary

        symbol_files: dict[str, dict] = {}
        bars_written = 0
        priced = 0
        carried = 0
        for symbol in sorted(tape.bars):
            rows = tape.bars[symbol]
            if not rows:
                continue
            lines: list[str] = []
            for row in rows:
                lines.append(_bar_to_row(row))
                if row.carried:
                    carried += 1
                else:
                    priced += 1
            text = "\n".join(lines) + "\n"
            path = self.symbol_path(day, symbol)
            _atomic_write_text(path, text)
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            symbol_files[symbol] = {"bars": len(rows), "sha256": digest}
            bars_written += len(rows)

        manifest = {
            "archive_version": ARCHIVE_VERSION,
            "day": _day_text(day),
            "source": getattr(tape, "source", ""),
            "capture": capture,
            "built_at": built_at,
            "builds": int((existing or {}).get("builds", 0)) + 1,
            "symbols": len(symbol_files),
            "bars": bars_written,
            "priced_bars": priced,
            "carried_bars": carried,
            "volume_available": bool(getattr(tape, "volume_available", False)),
            "first_observation": (
                tape.first_observation.isoformat(timespec="seconds")
                if getattr(tape, "first_observation", None) else None),
            "notes": [str(line) for line in getattr(tape, "notes", [])],
            "session": tape.as_dict() if hasattr(tape, "as_dict") else {},
            "symbol_files": symbol_files,
        }
        _atomic_write_text(self.manifest_path(day),
                           json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        summary = self.summary(day)
        assert summary is not None
        return summary


def _day_text(day: date | str) -> str:
    return day.isoformat() if isinstance(day, date) else str(day)


def _bar_to_row(row) -> str:
    """One bar as one JSON line, at full precision.

    The minute is the tape's own stamp with its Karachi offset; nothing is
    rounded, and the two facts that describe how the bar was obtained
    (``prints`` and ``carried``) are kept beside the prices.
    """
    moment = row.timestamp
    return json.dumps({
        "t": moment.isoformat(timespec="seconds"),
        "o": row.open,
        "h": row.high,
        "l": row.low,
        "c": row.close,
        "v": row.volume,
        "prints": int(getattr(row, "prints", 0)),
        "carried": bool(getattr(row, "carried", False)),
    }, separators=(",", ":"))


def _row_to_bar(text: str, path: Path, number: int) -> Bar:
    """Read one row back into the contract's own Bar.

    The contract validates it: a stored high below its own close, or a naive
    timestamp, is refused here rather than drawn later.
    """
    try:
        raw = json.loads(text)
        return Bar.build(t=raw["t"], o=raw["o"], h=raw["h"], l=raw["l"],
                         c=raw["c"], v=raw.get("v", 0.0))
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path.name} line {number} is not a stored bar: {exc}") from exc


def build_day_bars(rows: list) -> list[Bar]:
    """Bars from already built rows, for a caller holding a ``TapeBars``."""
    return [Bar.build(t=row.timestamp, o=row.open, h=row.high, l=row.low,
                      c=row.close, v=row.volume) for row in rows]
