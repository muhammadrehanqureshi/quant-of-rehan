"""The chart service's HTTP surface: REST, Server-Sent Events, static files.

The standard library only, on purpose. The service has to run on the owner's
machine and inside CI without a package install, and the whole API is four
routes and one event stream, so a framework would add a dependency without
adding a capability. What a framework would have given us is handled here
explicitly instead:

* **Routing** is a small table of (method, path) to handler, so an unknown
  path is a 404 with a JSON body rather than a stack trace.
* **Errors** are classified: a bad request is 400 with the contract's own
  sentence, an unknown symbol is 404, a source failure is 502/503/504 keyed
  to the upstream error category, and an unexpected exception is a 500 whose
  detail is logged and never leaked as HTML.
* **Caching** is explicit: every ``/api`` response carries
  ``Cache-Control: no-store``, because a chart that is served stale is worse
  than a chart that is slow.
* **CORS** is an allow list, never a wildcard. The development UI runs on
  Vite's own port, so that origin is allowed by default and anything else
  must be named on the command line.
* **SSE** is used instead of WebSocket because the traffic is one way:
  prices go to the browser, and the browser's questions are ordinary GETs.
  It costs no handshake protocol, no framing library, and it reconnects by
  itself in every browser.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import posixpath
import queue
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

from charts import sessions
from charts.contract import RESOLUTION_MINUTE, SCHEMA_VERSION, ContractError
from charts.ingest import Ingestor
from charts.ratelimit import UpstreamError
from charts.service import build_payload
from charts.store import BarStore

LOGGER = logging.getLogger("charts.http")

#: JSON bodies are small by construction: a series, a catalog, a health line.
MAX_QUERY_LENGTH = 2048


def error_body(code: str, detail: str) -> dict:
    return {"ok": False, "error": {"code": code, "detail": detail}}


class ChartHandler(BaseHTTPRequestHandler):
    """One request. The server instance carries the state it needs."""

    server_version = "charts-of-rehan/1"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ plumbing
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        LOGGER.info("%s - %s", self.address_string(), fmt % args)

    @property
    def state(self) -> "ChartServer":
        return self.server  # type: ignore[return-value]

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin and origin in self.state.allow_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def _send_json(self, body: dict, status: int = 200,
                   extra: dict | None = None) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, status: int, code: str, detail: str) -> None:
        self._send_json(error_body(code, detail), status=status)

    # ------------------------------------------------------------- methods
    def do_OPTIONS(self) -> None:  # noqa: N802 - the base class's own naming
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if len(self.path) > MAX_QUERY_LENGTH:
            self._send_error_json(414, "URI_TOO_LONG",
                                  "the query string is too long")
            return
        query = {key: values[-1] for key, values in
                 parse_qs(parsed.query).items()}
        try:
            if parsed.path.startswith("/api/"):
                self._route_api(parsed.path, query)
            else:
                self._serve_static(parsed.path)
        except ContractError as exc:
            self._send_error_json(400, "CONTRACT", str(exc))
        except UpstreamError as exc:
            status = {
                UpstreamError.TIMEOUT: 504,
                UpstreamError.EMPTY_ACK: 502,
                UpstreamError.SCHEMA_CHANGE: 502,
                UpstreamError.RATE_LIMITED: 503,
                UpstreamError.HTTP_ERROR: 502,
                "CIRCUIT_OPEN": 503,
            }.get(exc.category, 502)
            self._send_json(error_body(exc.category, exc.detail), status=status,
                            extra={"Retry-After": "30"})
        except Exception as exc:  # noqa: BLE001 - logged, never leaked
            LOGGER.exception("unhandled error serving %s", self.path)
            self._send_error_json(500, "INTERNAL", type(exc).__name__)

    # ----------------------------------------------------------------- API
    def _route_api(self, path: str, query: dict) -> None:
        if path == "/api/health":
            self._send_json(self.state.health())
            return
        if path == "/api/symbols":
            self._send_json({"ok": True,
                             "symbols": self.state.store.symbols() or
                             self.state.source.catalog()})
            return
        if path == "/api/bars":
            self._bars(query)
            return
        if path == "/api/stream":
            self._stream(query)
            return
        self._send_error_json(404, "NO_ROUTE", f"no route for {path}")

    def _symbol_or_error(self, query: dict) -> str | None:
        symbol = (query.get("symbol") or "").strip().upper()
        if not symbol:
            self._send_error_json(400, "MISSING_SYMBOL",
                                  "add ?symbol=SYMBOL to the request")
            return None
        if not self.state.store.has_symbol(symbol) and \
                symbol not in {row["symbol"] for row in
                               self.state.source.catalog()}:
            self._send_error_json(
                404, "UNKNOWN_SYMBOL",
                f"{symbol} is not in this service's universe")
            return None
        return symbol

    def _payload(self, symbol: str, resolution: str, limit: int) -> dict:
        """The chart payload for one symbol, via the shared builder."""
        body = build_payload(self.state.store, self.state.source, symbol,
                             resolution, limit=limit,
                             moment=self.state.moment()).as_dict()
        body["ok"] = True
        body["ingest"] = self.state.ingestor.health()
        return body

    def _bars(self, query: dict) -> None:
        symbol = self._symbol_or_error(query)
        if symbol is None:
            return
        resolution = query.get("resolution", self.state.default_resolution)
        if resolution not in self.state.source.capabilities().resolutions:
            self._send_error_json(
                400, "UNSUPPORTED_RESOLUTION",
                f"this source serves "
                f"{', '.join(self.state.source.capabilities().resolutions)}")
            return
        try:
            limit = max(1, min(5000, int(query.get("limit", "1500"))))
        except ValueError:
            self._send_error_json(400, "BAD_LIMIT",
                                  "limit must be a whole number")
            return
        self.state.ingestor.watch(symbol)
        self._send_json(self._payload(symbol, resolution, limit))

    # ----------------------------------------------------------------- SSE
    def _stream(self, query: dict) -> None:
        symbol = self._symbol_or_error(query)
        if symbol is None:
            return
        resolution = query.get("resolution", self.state.default_resolution)
        # The first payload is built before any header is written, so a
        # failure here is still an ordinary JSON error rather than half a
        # stream. Only after it exists does the response become an event
        # stream.
        initial = self._payload(symbol, resolution, 1500)
        subscription = self.state.ingestor.subscribe(symbol)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        try:
            self._write_event("snapshot", initial)
            idle = 0.0
            while True:
                try:
                    event = subscription.inbox.get(timeout=5.0)
                except queue.Empty:
                    event = None
                if event is None:
                    idle += 5.0
                    # A comment every five seconds keeps the connection warm
                    # through proxies and proves to the reader that the
                    # stream is alive even when the market is quiet.
                    self._write_raw(": keep-alive\n\n")
                    if idle >= self.state.stream_idle_seconds:
                        self._write_event("idle", {"seconds": int(idle)})
                        break
                    continue
                idle = 0.0
                self._write_event("bars", event)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.state.ingestor.unsubscribe(subscription)

    def _write_raw(self, text: str) -> None:
        self.wfile.write(text.encode("utf-8"))
        self.wfile.flush()

    def _write_event(self, name: str, body: dict) -> None:
        data = json.dumps(body, separators=(",", ":"))
        self._write_raw(f"event: {name}\ndata: {data}\n\n")

    # -------------------------------------------------------------- static
    def _serve_static(self, path: str) -> None:
        root = self.state.static_dir
        if root is None:
            self._send_error_json(
                404, "NO_UI",
                "the chart UI is not built in this deployment; run the "
                "development server or build the web app")
            return
        relative = posixpath.normpath(path).lstrip("/")
        wanted = (root / relative) if relative else (root / "index.html")
        if wanted.is_dir():
            wanted = wanted / "index.html"
        if not wanted.is_file():
            # A single page app: unknown paths render the app shell.
            wanted = root / "index.html"
            if not wanted.is_file():
                self._send_error_json(404, "NOT_FOUND", f"{path} not found")
                return
        body = wanted.read_bytes()
        kind = mimetypes.guess_type(wanted.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        # Hashed asset names may be cached; the shell must not be.
        if "assets/" in wanted.as_posix() or wanted.suffix == ".js":
            self.send_header("Cache-Control", "public, max-age=31536000, "
                                              "immutable")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class ChartServer(ThreadingHTTPServer):
    """The server object carries the shared state, not globals."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, store: BarStore,
                 ingestor: Ingestor, source, static_dir: Path | None,
                 allow_origins: tuple[str, ...] = ("http://localhost:5173",
                                                   "http://127.0.0.1:5173"),
                 default_resolution: str = RESOLUTION_MINUTE,
                 stream_idle_seconds: float = 240.0,
                 clock: Callable[[], datetime] | None = None):
        super().__init__(address, ChartHandler)
        self.store = store
        self.ingestor = ingestor
        self.source = source
        self.static_dir = static_dir
        self.allow_origins = set(allow_origins)
        self.default_resolution = default_resolution
        self.stream_idle_seconds = stream_idle_seconds
        # The one clock this server reads. None is the live Karachi now, which
        # is what a running service wants; a caller that holds a series
        # ingested on a fixed clock (tests, the offline demo) hands the same
        # clock here so the market context describes the session the bars are
        # actually from, not an unrelated day.
        self.clock = clock
        self.started_at = sessions.law.as_karachi().isoformat(timespec="seconds")

    def moment(self) -> datetime | None:
        """The session moment this server describes, or None for the now."""
        return self.clock() if self.clock is not None else None

    def health(self) -> dict:
        tape = (self.source.session_effect()
                if hasattr(self.source, "session_effect") else None)
        moment = self.moment()
        return {
            "ok": True,
            "service": "charts-of-rehan",
            "schema_version": SCHEMA_VERSION,
            "started_at": self.started_at,
            "karachi_now": (moment or sessions.law.now_karachi()).isoformat(
                timespec="seconds"),
            "market": sessions.market_context(moment).as_dict(),
            "source": self.source.capabilities().source.as_dict(),
            "resolutions": list(self.source.capabilities().resolutions),
            "tape": tape,
            "ingest": self.ingestor.health(),
            "symbols": len(self.store.symbols()),
            "series": {f"{symbol}/{resolution}": len(
                self.store.snapshot(symbol, resolution))
                for symbol in self.ingestor.watched()
                for resolution in self.source.capabilities().resolutions},
        }

    def shutdown_sources(self) -> None:
        self.ingestor.stop()
