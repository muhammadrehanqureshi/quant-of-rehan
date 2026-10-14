"""The HTTP surface, driven over a real socket on an ephemeral port.

Nothing here is mocked: a real server, a real request, a real response. The
tests cover the parts a consumer depends on:

  * the REST routes and their shapes, including the two error doors that must
    never be confused (a missing symbol is the caller's 400, an unknown
    symbol is a 404);
  * the upstream error taxonomy mapped onto status codes with Retry-After;
  * CORS as an allow list rather than a wildcard;
  * the built web app being served, with the single page app fallback;
  * Server-Sent Events: a snapshot first, then the live bars event.

The source is the deterministic replay source, so the numbers are fixed and
no test touches an exchange.
"""

from __future__ import annotations

import http.client
import json
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.adapters.replay import ReplaySource  # noqa: E402
from charts.http import ChartServer  # noqa: E402
from charts.ingest import Ingestor  # noqa: E402
from charts.ratelimit import UpstreamError  # noqa: E402
from charts.store import BarStore  # noqa: E402


class ServerCase(unittest.TestCase):
    """A running server per test, on a free port, cleaned up after."""

    def make_server(self, *, source=None, symbols=("REPLAY1",),
                    static_dir: Path | None = None) -> ChartServer:
        source = source or ReplaySource(symbols=list(symbols))
        store = BarStore()
        ingestor = Ingestor(store, source, resolution="1m",
                            interval_seconds=2.0)
        for symbol in symbols:
            store.register_symbol(symbol, source=source.name)
            ingestor.watch(symbol)
        server = ChartServer(("127.0.0.1", 0), store=store, ingestor=ingestor,
                             source=source, static_dir=static_dir)
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()

        def stop() -> None:
            server.shutdown()
            server.shutdown_sources()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(stop)
        self.ingestor = ingestor
        self.store = store
        return server

    def get(self, server: ChartServer, path: str, *, headers=None):
        port = server.server_address[1]
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                         headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                return response.status, response.headers, body
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def body(self, server: ChartServer, path: str, *, headers=None) -> dict:
        status, _, raw = self.get(server, path, headers=headers)
        self.assertLess(status, 400, f"{path} answered {status}: {raw[:200]!r}")
        return json.loads(raw)


class RouteTest(ServerCase):

    def test_health_names_the_service_the_clock_and_the_source(self):
        server = self.make_server()
        body = self.body(server, "/api/health")
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "charts-of-rehan")
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["market"]["timezone"], "Asia/Karachi")
        self.assertEqual(body["source"]["id"], "replay")
        self.assertIn("karachi_now", body)

    def test_symbols_lists_the_catalogue(self):
        server = self.make_server()
        body = self.body(server, "/api/symbols")
        self.assertTrue(body["ok"])
        self.assertIn("REPLAY1", [row["symbol"] for row in body["symbols"]])

    def test_bars_returns_an_ascending_series_with_market_facts(self):
        server = self.make_server()
        self.ingestor.step()
        body = self.body(server, "/api/bars?symbol=REPLAY1")
        self.assertTrue(body["ok"])
        self.assertEqual(body["resolution"], "1m")
        self.assertEqual(body["bar_count"], len(body["bars"]))
        self.assertGreater(body["bar_count"], 50)
        stamps = [row["t"] for row in body["bars"]]
        self.assertEqual(stamps, sorted(stamps))
        self.assertIn("phase", body["market"])
        self.assertIn("notes", body)
        self.assertIn("ingest", body)

    def test_bars_are_never_cached(self):
        server = self.make_server()
        status, headers, _ = self.get(server, "/api/bars?symbol=REPLAY1")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])

    def test_a_missing_symbol_is_the_callers_error(self):
        server = self.make_server()
        status, _, raw = self.get(server, "/api/bars")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"]["code"], "MISSING_SYMBOL")

    def test_an_unknown_symbol_is_a_not_found(self):
        server = self.make_server()
        status, _, raw = self.get(server, "/api/bars?symbol=NOSUCH")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "UNKNOWN_SYMBOL")

    def test_a_bad_limit_is_refused(self):
        server = self.make_server()
        status, _, raw = self.get(server, "/api/bars?symbol=REPLAY1&limit=soon")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(raw)["error"]["code"], "BAD_LIMIT")

    def test_an_unsupported_resolution_is_refused_with_the_offer(self):
        server = self.make_server()
        status, _, raw = self.get(server,
                                  "/api/bars?symbol=REPLAY1&resolution=1d")
        self.assertEqual(status, 400)
        detail = json.loads(raw)["error"]
        self.assertEqual(detail["code"], "UNSUPPORTED_RESOLUTION")
        self.assertIn("1m", detail["detail"])

    def test_an_unknown_route_is_a_json_404(self):
        server = self.make_server()
        status, _, raw = self.get(server, "/api/nothing")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "NO_ROUTE")

    def test_a_portal_like_rate_limit_becomes_503_with_retry_after(self):
        class Limited(ReplaySource):
            def catalog(self):
                raise UpstreamError(UpstreamError.RATE_LIMITED,
                                    "the portal asked us to slow down")

        server = self.make_server(source=Limited(symbols=["REPLAY1"]))
        status, headers, raw = self.get(server, "/api/bars?symbol=NOWHERE")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(raw)["error"]["code"], "RATE_LIMITED")
        self.assertEqual(headers["Retry-After"], "30")

    def test_a_timeout_becomes_504(self):
        class Slow(ReplaySource):
            def catalog(self):
                raise UpstreamError(UpstreamError.TIMEOUT,
                                    "the source did not answer")

        server = self.make_server(source=Slow(symbols=["REPLAY1"]))
        status, _, raw = self.get(server, "/api/bars?symbol=NOWHERE")
        self.assertEqual(status, 504)
        self.assertEqual(json.loads(raw)["error"]["code"], "TIMEOUT")


class CorsTest(ServerCase):

    def test_the_development_ui_origin_is_allowed(self):
        server = self.make_server()
        _, headers, _ = self.get(
            server, "/api/health",
            headers={"Origin": "http://localhost:5173"})
        self.assertEqual(headers["Access-Control-Allow-Origin"],
                         "http://localhost:5173")
        self.assertIn("Origin", headers["Vary"])

    def test_any_other_origin_is_not_allowed(self):
        server = self.make_server()
        _, headers, _ = self.get(server, "/api/health",
                                 headers={"Origin": "http://example.invalid"})
        self.assertIsNone(headers["Access-Control-Allow-Origin"])

    def test_an_extra_origin_can_be_named_by_the_operator(self):
        source = ReplaySource(symbols=["REPLAY1"])
        store = BarStore()
        ingestor = Ingestor(store, source, resolution="1m")
        server = ChartServer(("127.0.0.1", 0), store=store, ingestor=ingestor,
                             source=source, static_dir=None,
                             allow_origins=("http://localhost:1420",))
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        _, headers, _ = self.get(server, "/api/health",
                                 headers={"Origin": "http://localhost:1420"})
        self.assertEqual(headers["Access-Control-Allow-Origin"],
                         "http://localhost:1420")


class StaticTest(ServerCase):

    def setUp(self) -> None:
        self.directory = TemporaryDirectory(prefix="charts-web-")
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "index.html").write_text("<html>the app shell</html>",
                                         encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets" / "app.js").write_text("console.log('chart')",
                                                encoding="utf-8")
        self.root = root

    def test_the_shell_is_served_and_never_cached(self):
        server = self.make_server(static_dir=self.root)
        status, headers, raw = self.get(server, "/")
        self.assertEqual(status, 200)
        self.assertIn("the app shell", raw.decode("utf-8"))
        self.assertIn("no-store", headers["Cache-Control"])

    def test_a_client_side_route_falls_back_to_the_shell(self):
        server = self.make_server(static_dir=self.root)
        status, _, raw = self.get(server, "/symbol/OGDC")
        self.assertEqual(status, 200)
        self.assertIn("the app shell", raw.decode("utf-8"))

    def test_a_hashed_asset_is_cached_for_a_year(self):
        server = self.make_server(static_dir=self.root)
        status, headers, raw = self.get(server, "/assets/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", headers["Content-Type"])
        self.assertIn("immutable", headers["Cache-Control"])

    def test_without_a_build_the_api_says_so(self):
        server = self.make_server(static_dir=None)
        status, _, raw = self.get(server, "/")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(raw)["error"]["code"], "NO_UI")


class StreamTest(ServerCase):

    def open_stream(self, server: ChartServer, path: str):
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=15)
        self.addCleanup(connection.close)
        connection.request("GET", path)
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertIn("text/event-stream", response.headers["Content-Type"])
        return response

    def read_events(self, response, *, want: int, trigger=None,
                    deadline_seconds: float = 12.0) -> list[str]:
        """Read event names from an SSE response, triggering one step once."""
        names: list[str] = []
        deadline = time.time() + deadline_seconds
        triggered = False
        while len(names) < want and time.time() < deadline:
            line = response.fp.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text.startswith("event:"):
                names.append(text.split(":", 1)[1].strip())
            elif (text.startswith("data:") and not triggered
                  and trigger is not None):
                # The snapshot has arrived in full: now make the source
                # publish, which is what a live poll does.
                triggered = True
                trigger()
        return names

    def test_the_stream_sends_a_snapshot_then_live_bars(self):
        server = self.make_server()
        response = self.open_stream(server, "/api/stream?symbol=REPLAY1")
        names = self.read_events(response, want=2,
                                 trigger=lambda: self.ingestor.step())
        self.assertEqual(names[:2], ["snapshot", "bars"])

    def test_the_snapshot_carries_a_readable_payload(self):
        server = self.make_server()
        self.ingestor.step()  # a chart opening after the first poll
        response = self.open_stream(server, "/api/stream?symbol=REPLAY1")
        data = None
        while data is None:
            line = response.fp.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text.startswith("data:"):
                data = json.loads(text.split(":", 1)[1].strip())
        self.assertIsNotNone(data)
        self.assertEqual(data["symbol"], "REPLAY1")
        self.assertTrue(data["ok"])
        self.assertGreater(data["bar_count"], 0)

    def test_an_unknown_symbol_is_refused_before_the_stream_opens(self):
        server = self.make_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/stream?symbol=NOSUCH")
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "UNKNOWN_SYMBOL")


if __name__ == "__main__":
    unittest.main()
