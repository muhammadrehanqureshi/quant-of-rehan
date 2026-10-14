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
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from charts import __version__, sessions
from charts.adapters import SOURCES
from charts.adapters.replay import ReplaySource
from charts.adapters.tape import TapeSource, read_universe
from charts.http import ChartServer
from charts.ingest import Ingestor
from charts.store import BarStore

LOGGER = logging.getLogger("charts.app")

#: The service's own defaults. The port is high and uncommon so it does not
#: collide with a development server or another tool on this machine.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788
DEFAULT_INTERVAL = 15.0

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATIC = ROOT / "web" / "dist"


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
                        help="seconds between polls per watched symbol "
                             f"(default: {DEFAULT_INTERVAL:g})")
    parser.add_argument("--host", default=DEFAULT_HOST,
                        help=f"bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"port (default: {DEFAULT_PORT})")
    parser.add_argument("--static", default=str(DEFAULT_STATIC),
                        help="directory of the built web app to serve")
    parser.add_argument("--cors", default="",
                        help="comma separated extra origins allowed to call "
                             "the API (the Vite dev server is always allowed)")
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


def _source_for(args, clock=sessions.law.now_karachi):
    if args.source == "tape":
        return TapeSource(clock=clock)
    if args.source == "portal":
        return SOURCES["portal"](clock=clock)
    return ReplaySource(symbols=_symbols(args.symbols) or ["REPLAY1", "REPLAY2"],
                        clock=clock)


def _warm_symbols(args) -> list[str]:
    wanted = _symbols(args.symbols)
    if not wanted and args.source == "tape":
        # The universe is only read when the tape is the source: the other
        # sources carry their own catalogue and must not silently inherit it.
        wanted = read_universe()
    return wanted


def check_environment(args) -> str | None:
    """Return the sentence that stops this process, or None to continue."""
    if os.environ.get("GITHUB_ACTIONS"):
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


def build(args) -> tuple[BarStore, Ingestor, ChartServer]:
    """Assemble the service. Pure wiring, so a test can call it directly."""
    source = _source_for(args)
    capabilities = source.capabilities()
    resolution = args.resolution or capabilities.resolutions[0]
    if resolution not in capabilities.resolutions:
        raise SystemExit(
            f"source {source.name} does not serve {resolution}; it serves "
            f"{', '.join(capabilities.resolutions)}")
    store = BarStore()
    ingestor = Ingestor(store, source, resolution=resolution,
                        interval_seconds=max(2.0, args.interval))
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
    store, ingestor, server = build(args)
    if args.once:
        ingestor.step()
        print(json.dumps(summary(server, store), indent=2, sort_keys=True))
        ingestor.stop()
        server.server_close()
        return 0
    ingestor.start()
    host, port = server.server_address[:2]
    LOGGER.info("serving on http://%s:%s (API at /api, UI at /)", host, port)
    LOGGER.info("this process is the whole runtime; stop it with Ctrl+C")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        LOGGER.info("stopping on request")
    finally:
        server.shutdown_sources()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
