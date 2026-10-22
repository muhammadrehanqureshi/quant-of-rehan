"""The broker tape adapter: this project's own one-minute bars, for any day.

The tape is the only source in this system with genuine intraday prices: the
read-only MKT-FEED recorder banks the venue's prints, and
``src/data/tape_bars.py`` turns them into one-minute open/high/low/close bars
with the venue's own running volume counter differenced per minute. Nothing
here re-implements any of that. The adapter wraps it, caches the built day,
and reports the tape's own honesty notes (a symbol that started late, a
minute the tape could not price, a counter reset) straight into the chart
payload.

Three things make this adapter usable at any hour of any day, which is what a
charting service is actually for:

* **Any session, not just today.** ``history`` takes a day. A finished session
  is served from the durable archive (``charts/archive.py``) when it has been
  written, and otherwise is built from that day's own capture file and then
  archived, so the second look at a session costs nothing and needs no
  recorder running.
* **Today is served live.** Today's capture is fresher than anything written
  to disk earlier, so today is always built from the file, and the archive is
  only consulted for today when the capture is unreadable (a moved recording,
  a fresh checkout, a machine that was reinstalled). That fallback is the
  difference between an empty chart at 02:00 and yesterday's real prices.
* **Where the data lives is configurable, and named in the answer.** The
  capture directory, the archive directory and the universe file are all
  resolved in a documented order, and whichever one answered is reported, so
  a chart never shows bars without saying which file they came from.

Caching matters: building a day is a pass over a capture file that has
measured 44 MB in a real session, and a live chart polls. The cache key is
the file's identity (path, size, modification time in nanoseconds), so a
recorder appending rows invalidates it exactly when the file changes and not
on a timer.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import index_feed  # noqa: E402
from src.data import tape_bars  # noqa: E402
from src.data import tick_volume  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

from charts import resolutions as ladder  # noqa: E402

from charts.archive import (  # noqa: E402
    DEFAULT_ARCHIVE_DIR, DEFAULT_CAPTURE_DIRS, SessionArchive,
    capture_candidates, identify,
)
from charts.adapters.base import Capabilities  # noqa: E402
from charts.contract import (  # noqa: E402
    RESOLUTION_MINUTE, SOURCE_TAPE, Bar, SourceInfo,
)
from charts.ratelimit import UpstreamError  # noqa: E402

#: The KMIALL universe, in the order it is looked for: this project's own copy
#: first, then the parent project's (the extraction-era convenience, and the
#: same order the capture directories are searched in). A deployment that has
#: neither can still be read, because the tape itself names the symbols it
#: carries; see `symbols_in_capture`.
UNIVERSE_CANDIDATES = (
    ROOT / "src" / "data" / "universe_kmiall.json",
    ROOT.parent / "quant-of-rehan" / "src" / "data" / "universe_kmiall.json",
)

#: The historical alias, kept because the entry point and the tests name it.
UNIVERSE = UNIVERSE_CANDIDATES[0]

SOURCE = SourceInfo(
    id=SOURCE_TAPE,
    label="broker MKT-FEED tape (prints for open, high, low, close; the "
          "venue's own running volume counter)",
    delay_seconds=0,
    note="read-only subscription; the venue's own counter for volume",
)

SOURCE_ARCHIVE = SourceInfo(
    id=SOURCE_TAPE,
    label="broker MKT-FEED tape, archived session (this project's own file)",
    delay_seconds=0,
    note="read from the durable session archive on disk; the session is "
         "closed, so nothing in it can change",
)

#: The two index names the owner asked for. The exchange's own levels come
#: from the capture's EXS-FEED index frames (src/data/index_feed.py): the
#: same read-only recording the tape reads banks the real published KSE100
#: and all-shares index several times a minute. When a session's capture
#: holds no index frames, the service falls back to computing an equal-weight
#: proxy from the session's own constituents and says so in every payload.
INDEX_KSE100 = "KSE100"
INDEX_KMIALLSHR = "KMIALLSHR"
INDEX_SYMBOLS = (INDEX_KSE100, INDEX_KMIALLSHR)
INDEX_WEIGHT_LIMIT = 100

SOURCE_INDEX = SourceInfo(
    id="exchange_index",
    label="the exchange's own published index, read from the broker feed's "
          "EXS-FEED frames (the real KSE100 / all-shares level)",
    delay_seconds=0,
    note="the level is the exchange's own: value, session high and low and "
         "the day's change come straight from the index frames the recorder "
         "banked, at the minute those frames arrived",
)

SOURCE_INDEX_PROXY = SourceInfo(
    id="computed_index",
    label="computed index proxy from this session's tape constituents "
          "(not the exchange's official index)",
    delay_seconds=0,
    note="no index frame was banked for this session, so KSE100 is the "
         "equal-weight return of the session's 100 largest constituents by "
         "traded value; KMIALLSHR is the equal-weight return of every symbol "
         "the tape printed. The level starts at 1000 at the first bucket of "
         "each session; this is a chart of the session's own breadth, never "
         "an official index level.",
)


def _bar_in_session(bar: Bar) -> bool:
    """True when this bar's stamp sits inside one of the day's bands."""
    try:
        return ladder.in_session(datetime.fromisoformat(bar.t))
    except ValueError:
        return False

#: A guard against a corrupt file that would otherwise name millions of
#: symbols: a capture cannot honestly carry more than this.
MAX_DERIVED_SYMBOLS = 5000


#: The key names a symbol catalogue is written under, lowercased for
#: comparison. The tracked KMIALL snapshot writes ``symbol``; a hand-made list
#: may write ``SYMBOL`` or ``scrip``; a research export may write ``ticker``.
#: All of them are the same fact, and reading only one of them is how a chart
#: silently finds nothing in a file that was right there.
SYMBOL_KEYS = ("symbol", "scrip", "ticker", "code")


def _symbols_from(raw) -> list[str]:
    """Symbols out of any shape a catalogue file is actually written in.

    A list of names, a list of records (any of ``SYMBOL_KEYS``, in any case),
    or a mapping of name to anything. It never invents a symbol and never
    stringifies a record: a record with no recognisable key contributes
    nothing, which is the honest reading of a file this service cannot use.
    """
    if isinstance(raw, dict):
        if any(key in raw for key in ("symbols", "universe", "members")):
            for key in ("symbols", "universe", "members"):
                if key in raw:
                    return _symbols_from(raw[key])
        items = list(raw.items())
    elif isinstance(raw, (list, tuple, set)):
        items = [(None, item) for item in raw]
    else:
        return []

    seen: list[str] = []
    for key, item in items:
        symbol = ""
        if isinstance(item, dict):
            lowered = {str(name).lower(): value for name, value in item.items()}
            for candidate in SYMBOL_KEYS:
                value = lowered.get(candidate)
                if isinstance(value, str) and value.strip():
                    symbol = value
                    break
        elif isinstance(item, str):
            symbol = item
        if not symbol and isinstance(key, str):
            # A catalogue written as ``{symbol: record}`` names the symbol in
            # its key, which is just as much a symbol list as a list of rows.
            symbol = key
        # A catalogue may spell a symbol the way the feed does, ``OGDC:REG``;
        # the market suffix is not part of the symbol.
        symbol = symbol.strip().upper().split(":", 1)[0].strip()
        if symbol and symbol.isalnum() and symbol not in seen:
            seen.append(symbol)
    return seen


def read_universe(path: Path | None = None,
                  candidates: tuple[Path, ...] | list[Path] | None = None,
                  ) -> list[str]:
    """The symbols this deployment knows about, tolerantly read.

    ``path`` pins one file. With no argument, the documented candidates are
    tried in order and the first file that yields symbols wins, so the same
    call works in the parent project and in this standalone tree. An empty
    answer is a real answer: the caller falls back to the symbols the tape
    itself carried, which is the honest list for a session.
    """
    tried = [path] if path is not None else list(candidates or UNIVERSE_CANDIDATES)
    for candidate in tried:
        symbols = _symbols_from(_read_json(candidate))
        if symbols:
            return symbols
    return []


def _read_json(path: Path | None):
    if path is None:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def symbols_in_capture(path: Path,
                       limit: int = MAX_DERIVED_SYMBOLS) -> list[str]:
    """The symbols a capture file actually carries, from its own rows.

    This is the last resort when no universe file can be read, and it is
    honest rather than clever: the symbols it returns are exactly the ones the
    tape printed, parsed by the one module that already knows the capture
    format (``src/data/tick_volume.py``), so the bar builder and this listing
    can never disagree about what a row means.
    """
    found: set[str] = set()
    try:
        for row in tick_volume.iter_ticks(path):
            symbol = str(row.get("scrip", "")).split(":", 1)[0].strip().upper()
            if symbol:
                found.add(symbol)
            if len(found) >= limit:
                break
    except Exception:  # noqa: BLE001 - a listing may not kill a chart
        return sorted(found)
    return sorted(found)


class TapeSource:
    """One session's broker tape, exposed as minute bars, by day."""

    name = SOURCE_TAPE

    def __init__(self, *, clock=now_karachi, universe_path: Path | None = None,
                 capture_dirs=None, archive_dir: Path | str | None = None,
                 day: date | str | None = None) -> None:
        self._clock = clock
        self._universe_path = Path(universe_path) if universe_path else None
        self._capture_dirs = tuple(Path(item) for item in
                                   (capture_dirs or DEFAULT_CAPTURE_DIRS))
        self._archive = SessionArchive(archive_dir or DEFAULT_ARCHIVE_DIR)
        self._day_override = _as_date(day)
        self._cache: dict[str, tuple[tuple, "tape_bars.TapeBars"]] = {}
        self._derived: dict[str, list[str]] = {}
        #: Immutable archive rows, cached per (day, symbol). A finished
        #: session never changes, so this is safe for the process lifetime.
        self._bars_cache: dict[tuple[str, str], list[Bar]] = {}
        #: Sub-minute bars, built once per capture identity and resolution.
        self._ticks: dict[str, tuple[tuple, dict[str, list[Bar]]]] = {}
        #: The exchange's own index minutes, cached per capture identity.
        #: Keyed like the tape cache: a growing live file has a new
        #: (day, path, size, mtime), so today's newest frames arrive.
        self._index_cache: dict[str, tuple[tuple, dict[str, list[Bar]]]] = {}
        #: Order-print reports, cached per (day, symbol) file identity, the
        #: same identity rule the bar and index caches use.
        self._prints_cache: dict[tuple[str, str], tuple[tuple, dict]] = {}

    # ------------------------------------------------------- configuration
    @property
    def archive(self) -> SessionArchive:
        return self._archive

    @property
    def capture_dirs(self) -> tuple[Path, ...]:
        return self._capture_dirs

    def session_day(self) -> date:
        """The session this adapter describes by default."""
        return self._day_override or self._clock().date()

    def today(self) -> date:
        return self._clock().date()

    def capture_for(self, day: date | str) -> Path | None:
        """The capture file for a day, searched in the documented order."""
        session = _as_date(day)
        if session is None:
            return None
        found = capture_candidates(session, self._capture_dirs)
        return found[0] if found else None

    def live_capture_name(self, day: date | str | None = None) -> str:
        """The capture file name behind a live session, for the payload."""
        path = self.capture_for(day or self.session_day())
        return path.name if path is not None else ""

    def has_day(self, day: date | str) -> bool:
        session = _as_date(day)
        if session is None:
            return False
        return (self.capture_for(session) is not None
                or self._archive.manifest(session) is not None)

    # -------------------------------------------------------- capabilities
    def capabilities(self) -> Capabilities:
        # The tape is the one source that can answer every rung: ticks for
        # seconds, minutes for every intraday fold, and its archive for
        # daily, weekly and monthly groups.
        return Capabilities(
            source=SOURCE,
            resolutions=(RESOLUTION_MINUTE,) + tuple(
                item for item in ladder.RESOLUTION_IDS if item != "1m"),
            live=True, local=True)

    def catalog(self, day: date | str | None = None,
                facts: bool = False) -> list[dict]:
        """The universe, plus whatever the session actually saw.

        With ``facts`` each row also carries what the session itself holds for
        that symbol: how many bars, the first and last minute it printed, and
        its last close. That is what lets a watchlist say "this symbol has no
        bars in the session you are looking at" instead of showing a blank
        price, and it costs one cached pass over the tape, not one call per
        symbol.
        """
        session = _as_date(day) or self.session_day()
        # A live catalogue with no recording yet would report zero bars for
        # every symbol while the chart itself falls back to the newest stored
        # session. Facts follow the same fallback, so the watchlist and the
        # chart describe one session instead of two.
        facts_session = session
        if (facts and self.capture_for(session) is None
                and self._archive.manifest(session) is None):
            stored = [day for day in self._available_days()
                      if self._archive.symbols(day)]
            if stored:
                facts_session = stored[-1]
        index_rows = []
        for symbol in INDEX_SYMBOLS:
            rail = self.source_info(symbol, day=session)
            index_rows.append({"symbol": symbol, "source": rail.id,
                               "listed": True, "index": True})
        rows = [{"symbol": symbol, "source": SOURCE_TAPE, "listed": True}
                for symbol in self._universe_for(
                    session, self.capture_for(session))[0]]
        known = {row["symbol"] for row in rows}
        for symbol in self._archive.symbols(session):
            if symbol not in known:
                rows.append({"symbol": symbol, "source": SOURCE_TAPE,
                             "listed": False})
                known.add(symbol)
        try:
            tape = self._day(session)
        except UpstreamError:
            tape = None
        if tape is not None:
            for symbol in sorted(tape.bars):
                if symbol not in known:
                    rows.append({"symbol": symbol, "source": SOURCE_TAPE,
                                 "listed": False})
                    known.add(symbol)
        if not facts:
            return rows + index_rows
        for row in rows:
            row.update(self._facts_for(facts_session, row["symbol"]))
        rows.sort(key=lambda row: (not row.get("bars", 0), row["symbol"]))
        for row in index_rows:
            row.update(self._facts_for(facts_session, row["symbol"]))
        # The indexes stay at the end in the wire catalogue; the UI lifts them
        # to the top where a reader expects them. Keeping the traded symbols
        # first here preserves the documented ordering for existing clients.
        return rows + index_rows

    def _facts_for(self, session: date, symbol: str) -> dict:
        """What the chartable session holds for one symbol, measured.

        The catalogue used to report the raw capture's rows here, including a
        Friday's post-close prints; the chart itself filters those through the
        session law. A watchlist then said 128 bars to 12:34 while the chart
        drew 93 bars to 11:59. Facts now go through the same reader the chart
        uses, so the count, the last minute and the close are the series the
        reader will actually see.
        """
        symbol = symbol.strip().upper()
        if symbol in INDEX_SYMBOLS:
            # The chart serves the exchange's own level first (see history);
            # the watchlist must report the series the chart will actually
            # draw, so the facts go through the same reader. The computed
            # proxy is the fallback only when no index frame was banked.
            try:
                real = self._exchange_index(symbol, session, "1m")
            except UpstreamError:
                real = None
            rows = real
            if rows is None:
                try:
                    rows = self._index_intraday(symbol, session, "1m")
                except UpstreamError:
                    rows = []
            return self._facts_from_rows(rows, session)
        try:
            rows = self._minute_history(symbol, session)
        except UpstreamError:
            rows = []
        return self._facts_from_rows(rows, session)

    @staticmethod
    def _facts_from_rows(rows: Sequence[Bar], session: date) -> dict:
        """One measured report from the bars the chart will draw.

        The catalogue used to carry only the count, the two minutes and the
        last close. A TradingView-style watchlist also shows the day's change
        and its range, so the open, the measured high and low and the session's
        own volume sum ride along: the reader's previous close is the
        session's first stamp, which is exactly what this tape saw.
        """
        if not rows:
            return {"bars": 0, "first": None, "last": None, "open": None,
                    "high": None, "low": None, "close": None, "volume": None,
                    "day": session.isoformat()}
        return {"bars": len(rows), "first": rows[0].t, "last": rows[-1].t,
                "open": rows[0].o,
                "high": round(max(row.h for row in rows), 4),
                "low": round(min(row.l for row in rows), 4),
                "close": rows[-1].c,
                "volume": round(sum(row.v for row in rows), 4),
                "day": session.isoformat()}

    # ---------------------------------------------------------- the universe
    def _universe_for(self, day: date, capture: Path | None) -> tuple[list[str], list[str]]:
        """The symbol list to read a capture against, and why.

        Returns ``(symbols, notes)``. The universe file wins when it can be
        read; otherwise the capture's own rows are used, with the reason
        written down, because refusing to chart a session over a missing
        symbol list would hide real prices behind a configuration detail.
        """
        symbols = read_universe(self._universe_path)
        if symbols:
            return symbols, []
        if capture is None:
            return [], []
        cached = self._derived_symbols(capture)
        if not cached:
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"the KMIALL universe is missing or empty and {capture.name} "
                f"carries no readable symbol, so there is no symbol list to "
                f"read this tape against and no honest way to guess one "
                f"(SO-3; the recorder itself refuses to subscribe in this "
                f"state)")
        note = (f"no KMIALL universe file could be read, so this session's "
                f"symbols are the {len(cached)} the tape itself carried "
                f"({capture.name})")
        return cached, [note]

    # ------------------------------------------------------------ prints
    def prints_for(self, symbol: str, day: date | str | None = None,
                   limit: int = 3000) -> dict:
        """The tape's own order prints for one symbol, by day.

        The events and the totals are the venue's own facts (the same capture
        the candle bars are built from), so a chart can draw the orders as
        they came and name how many there were. A growing live file is
        re-read when its identity changes, exactly like the bar cache.
        """
        wanted = symbol.strip().upper()
        session = _as_date(day) or self.session_day()
        path = self.capture_for(session)
        if path is None:
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"no broker tape is banked for {session.isoformat()}, so "
                f"there are no order prints to show; the chart for this "
                f"session is served from the archive, which keeps bars, "
                f"not the print tape")
        try:
            stat = path.stat()
        except OSError as exc:
            raise UpstreamError(UpstreamError.CONNECTION,
                                f"cannot stat {path.name}: {exc}") from exc
        identity = (str(path), stat.st_size, stat.st_mtime_ns, limit)
        key = (session.isoformat(), wanted)
        cached = self._prints_cache.get(key)
        if cached is not None and cached[0] == identity:
            return cached[1]
        report = tape_bars.prints(path, wanted, session,
                                  as_of=self._clock(), limit=limit)
        self._prints_cache[key] = (identity, report)
        return report

    # ------------------------------------------------------------- reading
    def _day(self, day: date) -> "tape_bars.TapeBars":
        """The built tape for `day`, cached on the capture file's identity."""
        path = self.capture_for(day)
        if path is None:
            searched = ", ".join(str(item) for item in self._capture_dirs)
            archived = self._archive.manifest(day) is not None
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"no broker tape is banked for {day.isoformat()} "
                f"({tape_bars.capture_path(day).name} was not found in "
                f"{searched})"
                + ("; that session is in the archive and is served from "
                   "there" if archived else
                   "; start the read-only recorder to fill it, or archive a "
                   "session you already have"))
        try:
            stat = path.stat()
        except OSError as exc:
            raise UpstreamError(UpstreamError.CONNECTION,
                                f"cannot stat {path.name}: {exc}") from exc
        key = (day.isoformat(), str(path), stat.st_size, stat.st_mtime_ns)
        cached = self._cache.get(day.isoformat())
        if cached is not None and cached[0] == key:
            return cached[1]
        universe, notes = self._universe_for(day, path)
        if not universe:
            raise UpstreamError(
                UpstreamError.EMPTY_ACK,
                f"the KMIALL universe is missing and {path.name} carries no "
                f"readable symbol, so there is no symbol list to read the "
                f"tape against and no honest way to guess one (SO-3; the "
                f"recorder itself refuses to subscribe in this state)")
        tape = tape_bars.build(path, universe, self._clock(), day=day)
        if not tape.rows_seen:
            # The catalogue named none of the symbols this tape printed, which
            # means the file that answered is not this session's list (a
            # different market, a different exchange's export, a catalogue
            # whose keys changed shape). Showing an empty chart here would be
            # a lie about a tape that holds real prints, so the tape's own
            # symbols are used instead and the swap is written down. Measured
            # rather than assumed: the second build only happens when the
            # first one read no row at all.
            derived = self._derived_symbols(path)
            if derived:
                tape = tape_bars.build(path, derived, self._clock(), day=day)
                notes.append(
                    f"the symbol list at {self._universe_path_text()} was the "
                    f"file that answered, but none of its symbols appear in "
                    f"{path.name}, so this session is read against the "
                    f"{len(derived)} symbol(s) the tape itself carried")
        for line in notes:
            if line not in tape.notes:
                tape.notes.append(line)
        self._cache[day.isoformat()] = (key, tape)
        return tape

    def _universe_path_text(self) -> str:
        """Which file answered the universe question, for a note."""
        if self._universe_path is not None:
            return str(self._universe_path)
        for candidate in UNIVERSE_CANDIDATES:
            if candidate.is_file():
                return str(candidate)
        return "the documented candidates"

    def _derived_symbols(self, capture: Path) -> list[str]:
        """The symbols a capture carries, derived once and remembered."""
        cached = self._derived.get(str(capture))
        if cached is None:
            cached = symbols_in_capture(capture)
            self._derived[str(capture)] = cached
        return cached

    @staticmethod
    def _bars_for(tape: "tape_bars.TapeBars", symbol: str) -> list[Bar]:
        rows = tape.bars.get(symbol.strip().upper(), [])
        return [Bar.build(t=row.timestamp, o=row.open, h=row.high,
                          l=row.low, c=row.close, v=row.volume)
                for row in rows]

    @staticmethod
    def _notes(tape: "tape_bars.TapeBars", symbol: str) -> list[str]:
        """The tape's measured caveats, narrowed to this symbol.

        A caveat that names a symbol belongs to that symbol. A caveat that
        names no symbol at all is about the whole session (which catalogue
        was read, which file answered, what the tape's first observation
        was), so it belongs to every chart drawn from that session: dropping
        it would hide the reason a series looks the way it does.
        """
        symbol = symbol.strip().upper()
        lines = [line for line in tape.notes
                 if symbol in line or not _names_a_symbol(line, tape)]
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

    def archive_summary(self, day: date | str):
        return self._archive.summary(day)

    def sessions(self, *, hashes: bool = False) -> list[dict]:
        """Every session this service can draw, newest first.

        A session is listed when a capture file exists for it (today, or a
        day whose recording is still on disk) or when it is in the archive,
        so the answer is exactly "what can be charted right now", not a
        guess about what might have been recorded.
        """
        rows: dict[str, dict] = {}
        for directory in self._capture_dirs:
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("capture_*.ndjson")):
                day = _day_from_capture_name(path.name)
                if day is None:
                    continue
                entry = rows.setdefault(day, {"day": day, "captures": [],
                                              "archived": False})
                entry["captures"].append(path)

        for summary in self._archive.sessions():
            entry = rows.setdefault(summary["day"], {"day": summary["day"],
                                                     "captures": [],
                                                     "archived": False})
            entry["archived"] = True
            entry["archive"] = summary

        today = self.today().isoformat()
        out: list[dict] = []
        for day in sorted(rows, reverse=True):
            entry = rows[day]
            newest = entry["captures"][-1] if entry["captures"] else None
            row: dict = {
                "day": day,
                "current": day == today,
                "archived": bool(entry.get("archived")),
                "capture": None,
                "archive": entry.get("archive"),
                "sources": [str(path) for path in entry["captures"]] or
                           ([str(self._archive.day_dir(day))]
                            if entry.get("archived") else []),
            }
            if newest is not None:
                facts = identify(newest, hash_file=hashes)
                row["capture"] = facts
            out.append(row)
        return out

    def archive_session(self, day: date | str, *, force: bool = False) -> dict:
        """Build one session from its capture and store it durably.

        This is the command the owner runs to keep a recording: it reads the
        capture exactly as a chart would, writes every symbol to the archive
        with the capture's own hash, and reports what it stored. Nothing about
        it is scheduled.
        """
        session = _as_date(day)
        if session is None:
            raise UpstreamError(UpstreamError.SCHEMA_CHANGE,
                                f"{day!r} is not a calendar day")
        capture = self.capture_for(session)
        tape = self._day(session)
        facts = identify(capture) if capture is not None else None
        summary = self._archive.write(
            tape, capture=facts, force=force,
            built_at=self._clock().isoformat(timespec="seconds"))
        return summary.as_dict()

    # ------------------------------------------------------------- the wire
    def history(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
                limit: int = 500, day: date | str | None = None) -> list[Bar]:
        """Bars at any rung of the timeframe ladder.

        Minutes and coarser rungs are folds of the tape's own minute bars.
        Seconds are built from the capture's tick rows and therefore exist
        only while that session's recording file is on disk: an archived day
        that kept minutes cannot honestly produce a one-second candle, and
        this method returns no bars rather than an invented one.
        """
        canonical = ladder.normalise(resolution)
        spec = ladder.spec_for(canonical)
        symbol = symbol.strip().upper()
        session = _as_date(day) or self.session_day()
        if symbol in INDEX_SYMBOLS:
            # The exchange's own published level first: the EXS-FEED frames
            # the recorder banks carry the real index. A session whose
            # capture holds no index frames falls back to the computed
            # proxy, and the facts say which one answered.
            real = self._exchange_index(symbol, session, canonical)
            if real is not None and (not spec.calendar or day is not None):
                return self._cal_tail(real, limit)
            # On a calendar rung with no day asked for, the exchange's own
            # chain is the whole daily series, like the symbols' own
            # calendar path: a default daily chart is the history of every
            # capture this service holds, not today's one bar amputated.
            if spec.calendar:
                chain = self._exchange_index_calendar(symbol, canonical)
                if chain:
                    return self._cal_tail(chain, limit)
            if spec.calendar:
                rows = self._index_calendar(symbol, canonical)
                if day is not None:
                    wanted = ladder.calendar_key(
                        datetime(session.year, session.month, session.day, 12,
                                 tzinfo=ladder.law.KARACHI), canonical)
                    rows = [bar for bar in rows if ladder.calendar_key(
                        datetime.fromisoformat(bar.t), canonical) == wanted]
                return self._cal_tail(rows, limit)
            return self._cal_tail(
                self._index_intraday(symbol, session, canonical), limit)
        if spec.calendar:
            bars = self._calendar_history(symbol, canonical, session, day)
            return self._cal_tail(bars, limit)
        if spec.subminute:
            rows = self._tick_day(session, canonical).get(symbol, [])
            return self._cal_tail(rows, limit)
        bars = self._minute_history(symbol, session)
        folded = ladder.aggregate(bars, canonical)
        return self._cal_tail(folded, limit)

    @staticmethod
    def _cal_tail(bars: list[Bar], limit: int) -> list[Bar]:
        return bars[-limit:] if limit and limit > 0 else bars

    def _minute_history(self, symbol: str, session: date) -> list[Bar]:
        """One session's one-minute bars, from the archive or the capture."""
        symbol = symbol.strip().upper()
        if session != self.today():
            # A finished session: the archive is the durable answer. A day
            # whose manifest exists but holds no file for this symbol is an
            # honest empty series, not an error.
            if self._archive.manifest(session) is not None:
                return self._cached_archive(session, symbol)
            # A build from that day's capture is the fallback (and then it is
            # stored, so this cost is paid once).
            bars = [bar for bar in self._bars_for(self._day(session), symbol)
                    if _bar_in_session(bar)]
            self._archive_session_best_effort(session)
            return bars
        try:
            tape = self._day(session)
        except UpstreamError:
            # Today's recording is missing: the archive is the only honest
            # answer left, and the payload says which session it is showing.
            if self._archive.manifest(session) is None:
                raise
            return self._cached_archive(session, symbol)
        return [bar for bar in self._bars_for(tape, symbol)
                if _bar_in_session(bar)]

    def _cached_archive(self, session: date, symbol: str) -> list[Bar]:
        key = (session.isoformat(), symbol)
        found = self._bars_cache.get(key)
        if found is not None:
            return list(found)
        rows = [bar for bar in self._archive.read(session, symbol)
                if _bar_in_session(bar)]
        self._bars_cache[key] = list(rows)
        return rows

    def _available_days(self) -> list[date]:
        """Every day this deployment can draw, oldest first."""
        found: set[date] = set()
        for text in self._archive.days():
            try:
                found.add(date.fromisoformat(text))
            except ValueError:
                continue
        for directory in self._capture_dirs:
            if not directory.is_dir():
                continue
            for path in directory.glob("capture_*.ndjson"):
                text = _day_from_capture_name(path.name)
                if text is None:
                    continue
                try:
                    found.add(date.fromisoformat(text))
                except ValueError:
                    continue
        today = self.today()
        if self.capture_for(today) is not None:
            found.add(today)
        return sorted(day for day in found if day <= today)

    def _calendar_days(self, session: date, resolution: str,
                       explicit: bool) -> list[date]:
        available = self._available_days()
        if session not in available and self._archive.manifest(session) \
                is not None:
            available.append(session)
            available.sort()
        if resolution == "1D":
            # A named day is one daily bar. Without a day, the chart is a
            # daily *series*: returning only today's session would make the
            # history disappear the moment the recorder started working.
            return [session] if explicit else available
        if not explicit:
            return available
        wanted = ladder.calendar_key(
            datetime(session.year, session.month, session.day, 12,
                     tzinfo=ladder.law.KARACHI), resolution)
        selected = [day for day in available if ladder.calendar_key(
            datetime(day.year, day.month, day.day, 12,
                     tzinfo=ladder.law.KARACHI), resolution) == wanted]
        if session not in selected:
            selected.append(session)
            selected.sort()
        return selected

    def _calendar_history(self, symbol: str, resolution: str,
                          session: date, day) -> list[Bar]:
        days = self._calendar_days(session, resolution, explicit=day is not None)
        rows: list[Bar] = []
        missing: UpstreamError | None = None
        for item in days:
            try:
                rows.extend(self._minute_history(symbol, item))
            except UpstreamError as exc:
                if item == session:
                    missing = exc
        if not rows and missing is not None:
            raise missing
        return ladder.aggregate(rows, resolution)

    # ------------------------------------------------------------ sub-minute
    def _tick_day(self, session: date, resolution: str) -> dict[str, list[Bar]]:
        """Second or ten-second bars for every symbol the tick file printed.

        Built once per capture identity and cached: the file is read in one
        pass, volume comes from the venue's own running counter differenced
        across buckets, and a row outside the session bands is dropped. A
        row with no price contributes nothing rather than a guessed one.
        """
        path = self.capture_for(session)
        if path is None:
            return {}
        try:
            stat = path.stat()
        except OSError:
            return {}
        key = (session.isoformat(), resolution, str(path),
               stat.st_size, stat.st_mtime_ns)
        cached = self._ticks.get(session.isoformat())
        if cached is not None and cached[0] == key:
            return cached[1]
        buckets: dict[str, dict[datetime, dict]] = {}
        previous_total: dict[str, float] = {}
        for row in tick_volume.iter_ticks(path):
            symbol = str(row.get("scrip", "")).split(":", 1)[0].strip().upper()
            if not symbol:
                continue
            moment = tape_bars._moment(row, session)
            if moment is None or not ladder.in_session(moment):
                continue
            start = ladder.bucket_start(moment, resolution)
            price = tape_bars._number(row.get("last"))
            if start is None or price is None or price <= 0:
                continue
            total = tape_bars._number(row.get("volume"))
            delta = 0.0
            if total is not None and total > 0:
                prior = previous_total.get(symbol)
                if prior is not None and total >= prior:
                    delta = float(int(total) - int(prior))
                previous_total[symbol] = total
            bucket = buckets.setdefault(symbol, {}).get(start)
            if bucket is None:
                buckets[symbol][start] = {
                    "o": price, "h": price, "l": price, "c": price,
                    "v": delta,
                }
            else:
                bucket["h"] = max(bucket["h"], price)
                bucket["l"] = min(bucket["l"], price)
                bucket["c"] = price
                bucket["v"] += delta
        built: dict[str, list[Bar]] = {}
        for symbol, series in buckets.items():
            built[symbol] = [
                Bar.build(t=start, o=data["o"], h=data["h"],
                          l=data["l"], c=data["c"], v=data["v"])
                for start, data in sorted(series.items())
            ]
        self._ticks[session.isoformat()] = (key, built)
        return built

    # ------------------------------------------------------------- indexes
    def _exchange_index_minutes(self, session: date) -> dict[str, list[Bar]]:
        """The exchange's own index minutes for a session, from the capture.

        Built from the EXS-FEED frames the recorder banked and cached per
        capture identity, so a live file re-reads as it grows and a finished
        session reads once. There is no archive fallback for the index: the
        archive keeps symbols, and the index frames live only in a capture.
        """
        path = self.capture_for(session)
        if path is None:
            return {}
        try:
            stat = path.stat()
        except OSError:
            return {}
        key = (session.isoformat(), str(path), stat.st_size, stat.st_mtime_ns)
        cached = self._index_cache.get(session.isoformat())
        if cached is not None and cached[0] == key:
            return cached[1]
        built: dict[str, list[Bar]] = {}
        for name, rows in ((INDEX_KSE100,
                            index_feed.minute_bars(path, session, INDEX_KSE100)),
                           (INDEX_KMIALLSHR,
                            index_feed.minute_bars(path, session, INDEX_KMIALLSHR))):
            bars: list[Bar] = []
            for row in rows:
                start = row["t"]
                if not ladder.in_session(start):
                    continue
                bars.append(Bar.build(
                    t=start, o=row["o"], h=row["h"], l=row["l"],
                    c=row["c"], v=row["v"] or 0.0))
            if bars:
                built[name] = bars
        self._index_cache[session.isoformat()] = (key, built)
        return built

    def _exchange_index(self, symbol: str, session: date,
                        resolution: str) -> list[Bar] | None:
        """The exchange's own index bars at `resolution`, or None to fall back.

        Minutes are the read path's own grain; every coarser intraday rung is
        folded through the one `ladder.aggregate` rule; calendar rungs chain
        the sessions the captures hold. None means "this session's capture
        holds no index frames": the caller then says so and serves the
        computed proxy instead, labelled as a proxy.
        """
        minutes = self._exchange_index_minutes(session)
        base = minutes.get(symbol)
        if not base:
            return None
        spec = ladder.spec_for(resolution)
        if spec.id == "1m" or minutes is None:
            return base
        if spec.calendar:
            chain = self._exchange_index_calendar(symbol, resolution)
            if not chain:
                return base
            wanted = ladder.calendar_key(
                datetime(session.year, session.month, session.day, 12,
                         tzinfo=ladder.law.KARACHI), resolution)
            day_rows = [bar for bar in chain
                        if ladder.calendar_key(
                            datetime.fromisoformat(bar.t), resolution) == wanted]
            return day_rows or base
        return ladder.aggregate(base, resolution)

    def _exchange_index_calendar(self, symbol: str,
                                 resolution: str) -> list[Bar]:
        """Chain every capture's real index minute into calendar bars."""
        days = [day for day in self._available_days()
                if self.capture_for(day) is not None]
        days.sort()
        parts: list[Bar] = []
        for day in days:
            minutes = self._exchange_index_minutes(day).get(symbol, [])
            if minutes:
                parts.extend(minutes)
        return ladder.aggregate(parts, resolution)

    def _index_intraday(self, symbol: str, session: date,
                        resolution: str) -> list[Bar]:
        """One session of a transparent equal-weight index proxy."""
        spec = ladder.spec_for(resolution)
        if spec.subminute:
            base = self._tick_day(session, resolution)
        else:
            base = {}
            for name in self._index_universe(session):
                try:
                    rows = self._minute_history(name, session)
                except UpstreamError:
                    continue
                folded = ladder.aggregate(rows, resolution)
                if folded:
                    base[name] = folded
        if not base:
            return []
        names = self._index_members(symbol, base)
        if not names:
            return []
        times: set[datetime] = set()
        for name in names:
            for bar in base[name]:
                times.add(datetime.fromisoformat(bar.t))
        rows = {name: {datetime.fromisoformat(bar.t): bar
                       for bar in base[name]} for name in names}
        level = 1000.0
        previous: dict[str, float] = {}
        out: list[Bar] = []
        for moment in sorted(times):
            present = [(name, rows[name][moment]) for name in names
                       if moment in rows[name]]
            if not present:
                continue
            if not previous:
                previous = {name: bar.o for name, bar in present}
            ratios: list[float] = []
            values = {"o": [], "h": [], "l": [], "c": []}
            volume = 0.0
            for name, bar in present:
                base_price = previous.get(name, bar.o)
                if base_price <= 0:
                    continue
                values["o"].append(bar.o / base_price)
                values["h"].append(bar.h / base_price)
                values["l"].append(bar.l / base_price)
                values["c"].append(bar.c / base_price)
                volume += bar.v
            if not values["c"]:
                continue
            mean = {key: sum(items) / len(items)
                    for key, items in values.items()}
            opened = level * mean["o"]
            high = level * max(mean["h"], mean["o"], mean["c"], mean["l"])
            low = level * min(mean["l"], mean["o"], mean["c"], mean["h"])
            close = level * mean["c"]
            out.append(Bar.build(t=moment, o=round(opened, 4),
                                 h=round(max(high, opened, close), 4),
                                 l=round(min(low, opened, close), 4),
                                 c=round(close, 4), v=round(volume, 4)))
            for name, bar in present:
                previous[name] = bar.c
            level = close
        return out

    def _index_members(self, symbol: str, base: dict[str, list[Bar]]) -> list[str]:
        names = sorted(base)
        if symbol == INDEX_KMIALLSHR:
            return names
        ranked = sorted(
            names,
            key=lambda name: sum(bar.v * bar.c for bar in base[name]),
            reverse=True,
        )
        return ranked[:INDEX_WEIGHT_LIMIT]

    def _index_universe(self, session: date) -> list[str]:
        """The symbols to read for an index, derived from what the day holds."""
        if self._archive.manifest(session) is not None:
            return self._archive.symbols(session)
        try:
            return self._universe_for(session, self.capture_for(session))[0]
        except UpstreamError:
            return []

    def _index_calendar(self, symbol: str, resolution: str) -> list[Bar]:
        """A chained daily index across every session this service can draw."""
        days = self._available_days()
        if not days:
            return []
        level = 1000.0
        daily: list[Bar] = []
        for day in days:
            intraday = self._index_intraday(symbol, day, "1m")
            if not intraday:
                continue
            scale = level / 1000.0
            scaled = [Bar.build(t=bar.t, o=bar.o * scale, h=bar.h * scale,
                                l=bar.l * scale, c=bar.c * scale, v=bar.v)
                      for bar in intraday]
            day_bar = ladder.aggregate(scaled, "1D")
            if not day_bar:
                continue
            daily.append(day_bar[0])
            level = day_bar[0].c
        return ladder.aggregate(daily, resolution)

    def latest(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
               since: str | None = None, day: date | str | None = None,
               ) -> list[Bar]:
        """The newest bars, filtered to those at or after `since` when given."""
        bars = self.history(symbol, resolution, day=day)
        if since:
            bars = [bar for bar in bars if bar.t >= since]
        return bars

    def notes(self, symbol: str, *, day: date | str | None = None) -> list[str]:
        session = _as_date(day) or self.session_day()
        symbol = symbol.strip().upper()
        if symbol in INDEX_SYMBOLS:
            exchange = self._exchange_index(symbol, session, "1m")
            if exchange:
                first, last = exchange[0], exchange[-1]
                return [
                    f"the exchange's own published {symbol} level, read from "
                    f"the broker feed's EXS-FEED index frames the recorder "
                    f"banked ({len(exchange)} minute(s), "
                    f"{first.t[11:16]} to {last.t[11:16]} Karachi)",
                    "the level, the session high and low and the day's change "
                    "are the index frames' own numbers, at the minute each "
                    "frame arrived; frames stop when the recorder stopped",
                ]
            capture = self.capture_for(session)
            if capture is None and self._archive.manifest(session) is not None:
                lines = [f"the index frames live in the capture files, and the "
                         f"archive keeps no index series, so {session.isoformat()} "
                         f"has no exchange index to serve"]
            else:
                lines = [f"no EXS-FEED index frame was banked for "
                         f"{session.isoformat()} in "
                         f"{capture.name if capture else 'any capture'}"]
            members = len(self._index_universe(session))
            lines.append(
                f"no exchange level is available, so {symbol} is a computed "
                f"proxy from this session's tape")
            if symbol == INDEX_KSE100:
                return lines + [
                    f"{INDEX_KSE100} is the equal-weight "
                    f"return of the {min(INDEX_WEIGHT_LIMIT, members)} "
                    f"constituents with the largest traded value in this "
                    f"session, selected from the {members} symbols the tape "
                    f"printed",
                    "this is not the exchange's official KSE100 level; it is "
                    "a transparent breadth chart of the session's own tape, "
                    "with the level set to 1000 at its first bucket",
                ]
            return [
                f"{INDEX_KMIALLSHR} is a computed proxy: the equal-weight "
                f"return of every one of the {members} symbols the tape "
                f"printed in this session",
                "this is not the exchange's official KMIALLSHR level; it is "
                "a transparent breadth chart of the session's own tape, "
                "with the level set to 1000 at its first bucket",
            ]
        summary = self._archive.summary(session)
        archived_session = session != self.today() and summary is not None
        if archived_session and self._archive.has(session, symbol):
            lines = [f"this is the archived {session.isoformat()} session "
                     f"({summary.bars:,} bars over {summary.symbols} symbols, "
                     f"stored {summary.built_at or 'earlier'})"]
            capture = summary.capture or {}
            if capture.get("sha256"):
                lines.append(f"built from {capture.get('name')}, "
                             f"sha256 {capture['sha256'][:16]}...")
            return lines
        try:
            tape = self._day(session)
        except UpstreamError:
            return []
        return self._notes(tape, symbol)

    def served_from_archive(self, symbol: str, *,
                            day: date | str | None = None) -> bool:
        """Did this symbol's series for this day come from the archive?

        True exactly when the read path reads the archive: a finished day that
        the archive holds this symbol in. Today is never served from the
        archive unless today's capture is unreadable, so a chart of the
        running session is not labelled a stored one.
        """
        session = _as_date(day) or self.session_day()
        symbol = symbol.strip().upper()
        if symbol in INDEX_SYMBOLS:
            if self._exchange_index(symbol, session, "1m") is not None:
                return self.capture_for(session) is not None \
                    and session != self.today()
            return (session != self.today()
                    and self._archive.manifest(session) is not None)
        return session != self.today() and self._archive.has(session, symbol)

    def source_info(self, symbol: str, *, day: date | str | None = None) -> SourceInfo:
        """Which source answers for this symbol on this day, and its words."""
        if symbol.strip().upper() in INDEX_SYMBOLS:
            session = _as_date(day) or self.session_day()
            if self._exchange_index(symbol, session, "1m") is not None:
                return SOURCE_INDEX
            return SOURCE_INDEX_PROXY
        return (SOURCE_ARCHIVE if self.served_from_archive(symbol, day=day)
                else SOURCE)

    def session_effect(self) -> dict:
        """What the tape says about the session as a whole, for /api/health."""
        session = self.session_day()
        try:
            tape = self._day(session)
        except UpstreamError as exc:
            archived = self._archive.summary(session)
            return {"available": False, "detail": exc.detail,
                    "day": session.isoformat(),
                    "archive": archived.as_dict() if archived else None,
                    "archive_days": len(self._archive.days()),
                    "capture_dirs": [str(item) for item in self._capture_dirs]}
        return {"available": True,
                "day": session.isoformat(),
                "symbols_with_bars": tape.symbols_with_bars,
                "priced_bars": tape.priced_bars,
                "carried_bars": tape.carried_bars,
                "rows_seen": tape.rows_seen,
                "volume_available": tape.volume_available,
                "path": tape.path.name if tape.path else None,
                "archive_days": len(self._archive.days()),
                "capture_dirs": [str(item) for item in self._capture_dirs],
                "first_observation": (
                    tape.first_observation.isoformat(timespec="seconds")
                    if tape.first_observation else None)}

    # ---------------------------------------------------------- internals
    def _archive_session_best_effort(self, day: date) -> None:
        """Store a finished session on the way past, and never fail a chart."""
        capture = self.capture_for(day)
        try:
            tape = self._day(day)
            self._archive.write(
                tape, capture=identify(capture) if capture else None,
                built_at=self._clock().isoformat(timespec="seconds"))
        except Exception:  # noqa: BLE001 - an archive write may not break a read
            return


def _names_a_symbol(line: str, tape: "tape_bars.TapeBars") -> bool:
    """Does this sentence name any symbol the tape carried?"""
    return any(symbol in line for symbol in tape.bars)


def _day_from_capture_name(name: str) -> str | None:
    """``capture_20261016.ndjson`` to ``2026-10-16``, or None."""
    stem = name
    if stem.startswith("capture_"):
        stem = stem[len("capture_"):]
    if stem.endswith(".ndjson"):
        stem = stem[: -len(".ndjson")]
    digits = "".join(character for character in stem if character.isdigit())
    if len(digits) != 8:
        return None
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


def _as_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise UpstreamError(UpstreamError.SCHEMA_CHANGE,
                            f"{text!r} is not a YYYY-MM-DD day") from exc
