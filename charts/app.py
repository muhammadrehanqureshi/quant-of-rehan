"""The command line entry point: a foreground chart service, nothing else.

This process is the whole runtime. It is started by a human, it serves until
it is stopped, and it leaves nothing behind: no schedule, no daemon, no
watcher, no autostart entry. That is deliberate, because it is the shape the
project's machine rule asks for (AGENTS.md: the owner's PC runs what he asks
for, and only while he asks for it).

It refuses two situations outright rather than being clever about them:

* **GitHub Actions.** The Actions minutes are reserved for the market-hours
  scans, so the chart service declines to start there (``GITHUB_ACTIONS`` is
  set on every runner). Tests import the modules directly; they never start
  ``main``.
* **A public bind without saying so.** The default host is loopback. Binding
  to anything else needs ``--allow-public-bind`` on the command line, because
  a chart service opened to a network is a decision, not a default.

Usage::

    python -m charts --source replay --symbols REPLAY1 --once   # one pass
    python -m charts --source tape --port 8787                  # the real one
    python -m charts --sessions                    # what can be charted
    python -m charts --build-archive latest        # store a session for good

The last two are the 24/7 pair: a session is stored once, precisely, and every
later look at it (a Saturday, a week later, a research pass) reads the archive
instead of a recorder that is not running.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from charts import __version__, sessions
from charts import resolutions as ladder
from charts.adapters import SOURCES
from charts.adapters.replay import ReplaySource
from charts.adapters.tape import TapeSource, read_universe
from charts.archive import discover_capture_dirs
from charts.contract import RESOLUTION_MINUTE
from charts.http import ChartServer
from charts.ingest import Ingestor
from charts.persistent import PersistentBarStore
from charts.store import BarStore

LOGGER = logging.getLogger("charts.app")

#: The service's own defaults. The port is high and uncommon so it does not
#: collide with a development server or another tool on this machine.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788
# The broker feed's measured per-symbol snapshot median is about 30 seconds.
# A faster local poll cannot produce a new broker observation.
DEFAULT_INTERVAL = 30.0

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC = ROOT / "web" / "dist"
DEFAULT_HISTORY_DATABASE = ROOT / "data" / "charts" / "history.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m charts",
        description="Charts of Rehan: serve chart bars and the built web app.",
    )
    parser.add_argument("--source", choices=sorted(SOURCES), default="tape",
                        help="where bars come from (default: tape)")
    parser.add_argument("--symbols", default="",
                        help="comma separated symbols to keep warm; empty "
                             "means serve exactly what a chart asks for")
    parser.add_argument("--resolution", default="",
                        help="force one resolution (default: the source's "
                             "finest)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help="seconds between checks per watched symbol "
                             f"(default: {DEFAULT_INTERVAL:g})")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port (default: {DEFAULT_PORT})")
    parser.add_argument("--static", default=str(DEFAULT_STATIC),
                        help="directory of the built web app to serve")
    parser.add_argument("--database", default="",
                        help="local SQLite history path; replay is memory-only unless explicitly set")
    parser.add_argument("--cors", default="",
                        help="comma separated extra origins allowed to call "
                             "the API (the Vite dev server is always allowed)")
    parser.add_argument("--tape-dir", action="append", default=[],
                        metavar="DIR", dest="tape_dir",
                        help="where to look for capture_YYYYMMDD.ndjson "
                             "recording files (repeatable; default: this "
                             "project's own data directories, plus the parent "
                             "recorder directory when it holds captures)")
    parser.add_argument("--archive-dir", default="",
                        help="where the durable session archive lives "
                             "(default: data/archive)")
    parser.add_argument("--day", default="",
                        help="serve this session (YYYY-MM-DD) instead of the "
                             "Karachi day of the clock")
    parser.add_argument("--sessions", action="store_true",
                        help="list every session this service can draw, with "
                             "its identity, then exit")
    parser.add_argument("--build-archive", default="", metavar="DAY",
                        help="read one session from its capture and store it "
                             "in the durable archive (YYYY-MM-DD, or 'today' "
                             "or 'latest'), then exit")
    parser.add_argument("--allow-public-bind", action="store_true",
                        help="required when --host is not a loopback address")
    parser.add_argument("--once", action="store_true",
                        help="poll once, print the health report as JSON, "
                             "and exit (the runnable example mode)")
    parser.add_argument("--log-level", default="INFO",
                        help="logging level (default: INFO)")
    parser.add_argument("--version", action="version",
                        version=f"charts-of-rehan {__version__}")
    return parser


def _symbols(text: str) -> list[str]:
    seen: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        symbol = chunk.strip().upper()
        if symbol and symbol not in seen:
            seen.append(symbol)
    return seen


def _tape_dirs(args) -> tuple[Path, ...]:
    """Where the capture files are, explicitly or by discovery.

    An explicit ``--tape-dir`` replaces discovery entirely, so an operator who
    names a directory gets exactly that directory and nothing else. With no
    flag, discovery is the documented order in ``charts/archive.py``: the
    environment, this project's own directories, then the parent recorder
    directory only if it actually holds captures. Discovery lives here and not
    in the library, so the library's search is predictable to a test.
    """
    explicit = tuple(Path(item) for item in (args.tape_dir or []))
    return explicit or discover_capture_dirs()


def _source_for(args, clock=None):
    # The clock is resolved at call time, never captured at import: a caller
    # that patches the session law (a test, the offline demo) must get the
    # clock it patched rather than the one that was bound when this module
    # was first imported.
    clock = clock or sessions.law.now_karachi
    if args.source == "tape":
        return TapeSource(clock=clock, capture_dirs=_tape_dirs(args),
                          archive_dir=args.archive_dir or None,
                          day=args.day or None)
    if args.source == "portal":
        return SOURCES["portal"](clock=clock)
    return ReplaySource(symbols=_symbols(args.symbols) or ["REPLAY1", "REPLAY2"],
                        clock=clock)


class Refused(Exception):
    """A command that cannot run, carrying the sentence to print."""


def _fail(message: str) -> int:
    """One sentence on stderr and a failure exit code, never a traceback."""
    print(f"charts: {message}", file=sys.stderr)
    return 2


def _resolve_day(source: TapeSource, text: str):
    """``today``, ``latest`` or a date, as a day the archive understands."""
    wanted = (text or "").strip().lower()
    if wanted in ("today", "current"):
        return source.today()
    if wanted in ("latest", "last"):
        sessions_seen = source.sessions()
        if not sessions_seen:
            raise Refused(
                "no capture file and no archived session exists yet, so "
                "there is no latest session to store")
        return sessions_seen[0]["day"]
    return wanted


def _warm_symbols(args) -> list[str]:
    # Only keep explicitly requested symbols warm. A chart adds its selected
    # symbol when it loads, so polling the entire 319-name universe would
    # needlessly rebuild the capture while the owner watches one chart.
    return _symbols(args.symbols)


def check_environment(args) -> str | None:
    """Return the sentence that stops this process, or None to continue.

    The GitHub Actions refusal covers the service itself. Serving is the
    cloud-minute spend SO-12 reserves for the market-hours scans, so a runner
    never starts the listener. The bounded commands (--sessions,
    --build-archive, --once) answer from local files and exit, and CI has to
    run them to prove them.
    """
    serving = not (args.sessions or args.build_archive or args.once)
    if serving and os.environ.get("GITHUB_ACTIONS"):
        return ("this is a foreground chart service and GitHub Actions "
                "minutes belong to the market-hours scans; run it on the "
                "owner's machine instead")
    host = args.host.strip().lower()
    loopback = (host in ("127.0.0.1", "::1", "localhost")
                or host.startswith("127."))
    if not loopback and not args.allow_public_bind:
        return (f"refusing to bind {args.host}: that is not a loopback "
                f"address; add --allow-public-bind if you mean it")
    if not 1 <= args.port <= 65535:
        return f"port {args.port} is outside 1 to 65535"
    if args.source not in SOURCES:
        return f"unknown source {args.source}"
    return None


def _store_for(args) -> BarStore:
    """Choose durable history for real feeds and memory for synthetic replay."""
    database = str(args.database).strip()
    if database:
        return PersistentBarStore(database)
    if args.source in ("tape", "portal"):
        return PersistentBarStore(DEFAULT_HISTORY_DATABASE)
    return BarStore()


def build(args) -> tuple[BarStore, Ingestor, ChartServer]:
    """Assemble the service. Pure wiring, so a test can call it directly."""
    source = _source_for(args)
    capabilities = source.capabilities()
    resolution = args.resolution or (
        RESOLUTION_MINUTE if RESOLUTION_MINUTE in capabilities.resolutions
        else capabilities.resolutions[0])
    try:
        resolution = ladder.normalise(resolution)
    except ValueError:
        raise SystemExit(
            f"source {source.name} does not serve {resolution}; it serves "
            f"{', '.join(capabilities.resolutions)}")
    if resolution not in capabilities.resolutions:
        raise SystemExit(
            f"source {source.name} does not serve {resolution}; it serves "
            f"{', '.join(capabilities.resolutions)}")
    store = _store_for(args)
    ingestor = Ingestor(store, source, resolution=resolution,
                        interval_seconds=args.interval)
    static = Path(args.static) if args.static else None
    when = sessions.market_context()
    cors = tuple(_symbols(args.cors)) + ("http://localhost:5173",
                                         "http://127.0.0.1:5173")
    server = ChartServer((args.host, args.port), store=store,
                         ingestor=ingestor, source=source,
                         static_dir=static, allow_origins=cors,
                         default_resolution=resolution)
    for symbol in _warm_symbols(args):
        store.register_symbol(symbol, source=source.name)
        ingestor.watch(symbol)
    LOGGER.info("source %s serves %s at %s", source.name, resolution,
                capabilities.source.label)
    LOGGER.info("market %s (%s) on the Karachi clock, trading day: %s",
                when.phase, when.state, when.trading_day)
    return store, ingestor, server


def summary(server: ChartServer, store: BarStore) -> dict:
    """The one screen report: what this process is and what it has."""
    return {"health": server.health(),
            "symbols": [row.get("symbol") for row in store.symbols()]}


def _require_tape(args, source) -> TapeSource:
    if not isinstance(source, TapeSource):
        raise Refused(
            f"--sessions and --build-archive belong to the tape source, "
            f"which owns the durable session archive; --source is "
            f"{args.source}")
    return source


def _maintenance(args) -> int:
    """``--sessions`` and ``--build-archive``: two commands, no server.

    Both exist so the 24/7 promise is a thing the owner does once, on demand,
    rather than a background process. Neither starts a listener, neither
    registers anything, and both print JSON a shell can read.
    """
    try:
        source = _require_tape(args, _source_for(args))
        if args.sessions:
            print(json.dumps({"capture_dirs": [str(item)
                                              for item in source.capture_dirs],
                              "archive_dir": str(source.archive.root),
                              "sessions": source.sessions(hashes=bool(
                                  args.build_archive))},
                             indent=2, sort_keys=True))
            if not args.build_archive:
                return 0
        wanted = _resolve_day(source, args.build_archive)
    except Refused as refusal:
        return _fail(str(refusal))
    try:
        summary = source.archive_session(wanted)
    except Exception as exc:  # noqa: BLE001 - reported, never a traceback
        return _fail(f"cannot archive {wanted}: {exc}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    refusal = check_environment(args)
    if refusal:
        print(f"charts: {refusal}", file=sys.stderr)
        return 2
    if args.sessions or args.build_archive:
        return _maintenance(args)
    store, ingestor, server = build(args)
    try:
        if args.once:
            ingestor.step()
            print(json.dumps(summary(server, store), indent=2, sort_keys=True))
            return 0
        ingestor.start()
        host, port = server.server_address[:2]
        LOGGER.info("serving on http://%s:%s (API at /api, UI at /)", host, port)
        LOGGER.info("this process is the whole runtime; stop it with Ctrl+C")
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            LOGGER.info("stopping on request")
        return 0
    finally:
        server.shutdown_sources()
        server.server_close()
        close_store = getattr(store, "close", None)
        if callable(close_store):
            close_store()


if __name__ == "__main__":
    raise SystemExit(main())
