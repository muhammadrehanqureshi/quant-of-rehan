"""The broker tape adapter: this project's own one-minute bars.

The tape is the only source in this system with genuine intraday prices: the
read-only MKT-FEED recorder banks the venue's prints, and
``src/data/tape_bars.py`` turns them into one-minute open/high/low/close bars
with the venue's own running volume counter differenced per minute. Nothing
here re-implements any of that. The adapter wraps it, caches the built day,
and reports the tape's own honesty notes (a symbol that started late, a
minute the tape could not price, a counter reset) straight into the chart
payload.

Caching matters: building a day is a pass over a capture file that has
measured 44 MB in a real session, and a live chart polls. The cache key is
the file's identity (path, size, modification time in nanoseconds), so a
recorder appending rows invalidates it exactly when the file changes and not
on a timer.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import tape_bars  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

from charts.adapters.base import Capabilities  # noqa: E402
from charts.contract import (  # noqa: E402
    RESOLUTION_MINUTE, SOURCE_TAPE, Bar, SourceInfo,
)
from charts.ratelimit import UpstreamError  # noqa: E402

UNIVERSE = ROOT / "src" / "data" / "universe_kmiall.json"

SOURCE = SourceInfo(
    id=SOURCE_TAPE,
    label="broker MKT-FEED tape (prints for open, high, low, close; the "
          "venue's own running volume counter)",
    delay_seconds=0,
    note="read-only subscription; the venue's own counter for volume",
)


def read_universe(path: Path = UNIVERSE) -> list[str]:
    """The KMIALL symbols this project scans, tolerantly read."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("symbols") or raw.get("universe") or []
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for item in raw:
        symbol = str(item).strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen


class TapeSource:
    """One day's broker tape, exposed as minute bars per symbol."""

    name = SOURCE_TAPE

    def __init__(self, *, clock=now_karachi, universe_path: Path = UNIVERSE):
        self._clock = clock
        self._universe_path = universe_path
        self._cache: dict[str, tuple[tuple, "tape_bars.TapeBars"]] = {}

    # -------------------------------------------------------- capabilities
    def capabilities(self) -> Capabilities:
        return Capabilities(source=SOURCE, resolutions=(RESOLUTION_MINUTE,),
                            live=True, local=True)

    def catalog(self) -> list[dict]:
        """The universe, plus whatever the day's tape actually saw."""
        rows = [{"symbol": symbol, "source": SOURCE_TAPE,
                 "listed": True} for symbol in read_universe(self._universe_path)]
        known = {row["symbol"] for row in rows}
        try:
            tape = self._day(self._clock().date())
        except UpstreamError:
            return rows
        for symbol in sorted(tape.bars):
            if symbol not in known:
                rows.append({"symbol": symbol, "source": SOURCE_TAPE,
                             "listed": False})
        return rows

    # ------------------------------------------------------------- reading
    def _day(self, day: date) -> "tape_bars.TapeBars":
        """The built tape for `day`, cached on the capture file's identity."""
        path = tape_bars.capture_path(day)
        if not path.is_file():
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"no broker tape is banked for {day.isoformat()} at "
                f"{path.name}; start the read-only recorder to fill it")
        try:
            stat = path.stat()
        except OSError as exc:
            raise UpstreamError(UpstreamError.CONNECTION,
                                f"cannot stat {path.name}: {exc}") from exc
        key = (day.isoformat(), stat.st_size, stat.st_mtime_ns)
        cached = self._cache.get("day")
        if cached is not None and cached[0] == key:
            return cached[1]
        universe = read_universe(self._universe_path)
        if not universe:
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"the KMIALL universe at {self._universe_path.name} is "
                f"missing or empty, so there is no symbol list to read the "
                f"tape against and no honest way to guess one (SO-3; the "
                f"recorder itself refuses to subscribe in this state)")
        tape = tape_bars.build(path, universe, self._clock(), day=day)
        self._cache["day"] = (key, tape)
        return tape

    @staticmethod
    def _bars_for(tape: "tape_bars.TapeBars", symbol: str) -> list[Bar]:
        rows = tape.bars.get(symbol.strip().upper(), [])
        return [Bar.build(t=row.timestamp, o=row.open, h=row.high,
                          l=row.low, c=row.close, v=row.volume)
                for row in rows]

    @staticmethod
    def _notes(tape: "tape_bars.TapeBars", symbol: str) -> list[str]:
        """The tape's measured caveats, narrowed to this symbol."""
        symbol = symbol.strip().upper()
        lines = [line for line in tape.notes if symbol in line]
        if symbol in tape.started_after_open:
            lines.append(
                f"{symbol} printed its first tape row after the session "
                f"opened, so the earliest minutes of the day are not in this "
                f"series")
        pre = tape.pre_tape_volume.get(symbol)
        if pre:
            lines.append(
                f"{pre:,} shares traded before the tape first saw {symbol}; "
                f"they are not attributed to any minute bar")
        return lines

    def history(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
                limit: int = 500) -> list[Bar]:
        if resolution != RESOLUTION_MINUTE:
            raise UpstreamError(
                UpstreamError.SCHEMA_CHANGE,
                f"the broker tape serves {RESOLUTION_MINUTE} bars only, "
                f"not {resolution}")
        tape = self._day(self._clock().date())
        bars = self._bars_for(tape, symbol)
        return bars[-limit:] if limit else bars

    def latest(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
               since: str | None = None) -> list[Bar]:
        """The newest bars, filtered to those at or after `since` when given."""
        bars = self.history(symbol, resolution)
        if since:
            bars = [bar for bar in bars if bar.t >= since]
        return bars

    def notes(self, symbol: str) -> list[str]:
        try:
            tape = self._day(self._clock().date())
        except UpstreamError:
            return []
        return self._notes(tape, symbol)

    def session_effect(self) -> dict:
        """What the tape says about the session as a whole, for /api/health."""
        try:
            tape = self._day(self._clock().date())
        except UpstreamError as exc:
            return {"available": False, "detail": exc.detail}
        return {"available": True,
                "symbols_with_bars": tape.symbols_with_bars,
                "priced_bars": tape.priced_bars,
                "carried_bars": tape.carried_bars,
                "rows_seen": tape.rows_seen,
                "volume_available": tape.volume_available,
                "path": tape.path.name if tape.path else None,
                "first_observation": (
                    tape.first_observation.isoformat(timespec="seconds")
                    if tape.first_observation else None)}
