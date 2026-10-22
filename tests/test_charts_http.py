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
no test touches an exchange. Its clock is pinned to one mid-session trading
moment and the server reads the same moment, so a run at 03:00 pre-open and a
run at noon see the same chart: the day, the session minutes and the market
context all agree instead of following the wall clock.
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.adapters.replay import ReplaySource  # noqa: E402
from charts.adapters.tape import TapeSource  # noqa: E402
from charts.contract import SCHEMA_VERSION  # noqa: E402
from charts.http import ChartServer  # noqa: E402
from charts.ingest import Ingestor  # noqa: E402
from charts.ratelimit import UpstreamError  # noqa: E402
from charts.store import BarStore  # noqa: E402

#: A Monday well inside the PSX session. Every clock in this module points
#: at it, so the whole suite is indifferent to the hour it runs at.
SESSION_MOMENT = datetime.fromisoformat("2026-10-12T11:00:00+05:00")

#: The day the tape fixtures in this module belong to, and the minute the
#: session law calls the open on it (the tape's first bar is one minute later).
SESSION_DAY = SESSION_MOMENT.date()
SESSION_OPEN = datetime.fromisoformat("2026-10-12T09:32:00+05:00")


def session_clock() -> datetime:
    return SESSION_MOMENT


def tuesday_clock() -> datetime:
    """The next trading day, so Monday is a finished session."""
    return SESSION_MOMENT + timedelta(days=1)


class ServerCase(unittest.TestCase):
    """A running server per test, on a free port, cleaned up after."""

    def make_server(self, *, source=None, symbols=("REPLAY1",),
                    static_dir: Path | None = None,
                    clock=session_clock) -> ChartServer:
        source = source or ReplaySource(symbols=list(symbols), clock=clock)
        store = BarStore()
        ingestor = Ingestor(store, source, resolution="1m",
                            interval_seconds=2.0)
        for symbol in symbols:
            store.register_symbol(symbol, source=source.name)
            ingestor.watch(symbol)
        server = ChartServer(("127.0.0.1", 0), store=store, ingestor=ingestor,
                             source=source, static_dir=static_dir,
                             clock=clock)
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
        # The version travels with the answer, so a consumer can refuse a
        # shape it does not know; the literal pin lives in the contract test.
        self.assertEqual(body["schema_version"], SCHEMA_VERSION)
        self.assertEqual(body["market"]["timezone"], "Asia/Karachi")
        self.assertEqual(body["source"]["id"], "replay")
        self.assertIn("karachi_now", body)
        # The server reads the clock it was given, so the session it reports
        # is the one the bars in this suite are from.
        self.assertEqual(body["market"]["phase"], "OPEN")
        self.assertEqual(body["market"]["band"],
                         {"open": "09:32", "close": "15:30"})
        self.assertTrue(body["karachi_now"].startswith("2026-10-12T11:00:00"))

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

    def test_an_encoded_parent_path_cannot_escape_the_build(self):
        server = self.make_server(static_dir=self.root)
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        # The client must not normalise this away: %2e%2e is the attack, and
        # the server has to decode it before deciding what file it names.
        connection.request("GET", "/%2e%2e/%2e%2e/pyproject.toml")
        response = connection.getresponse()
        self.assertEqual(response.status, 404)
        self.assertEqual(json.loads(response.read())["error"]["code"],
                         "NOT_FOUND")

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


class TapeRoutesTest(ServerCase):
    """The any-day routes, driven over a socket against a real capture file.

    The replay source cannot answer these questions (it has no sessions), so
    this class runs a server on a temporary tape, a temporary archive and a
    pinned clock: the same wiring a real deployment uses, with none of the
    owner's files and none of the wall clock.
    """

    def setUp(self) -> None:
        self.tmp = Path(mkdtemp(prefix="charts-http-tape-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.captures = self.tmp / "captures"
        self.captures.mkdir(parents=True)
        self.archive_dir = self.tmp / "archive"
        self.capture = self.captures / "capture_20261012.ndjson"
        self.universe = self.tmp / "universe.json"
        self.universe.write_text(json.dumps(["OGDC", "PPL"]),
                                 encoding="utf-8")
        self.capture.write_text(
            "\n".join(json.dumps(row) for row in self.rows()) + "\n",
            encoding="utf-8")

    def rows(self, minutes: int = 4) -> list[dict]:
        return self.rows_for(SESSION_MOMENT.date(), minutes)

    def rows_for(self, day, minutes: int = 4) -> list[dict]:
        out: list[dict] = []
        for index in range(minutes):
            moment = (datetime(day.year, day.month, day.day, 9, 32,
                               tzinfo=SESSION_MOMENT.tzinfo)
                      + timedelta(minutes=index + 1))
            base = 200.0 if day < SESSION_DAY else 100.0
            out.append({
                "kind": "MKT-FEED*x", "ts": moment.isoformat(),
                "ticks": [
                    {"scrip": f"{symbol}:REG", "last": str(base + index),
                     "volume": str(1000 * (index + 1)),
                     "tick_time": f"{moment:%H:%M:%S}"}
                    for symbol in ("OGDC", "PPL")],
            })
        return out

    def taping_server(self, *, day=None, clock=session_clock):
        source = TapeSource(clock=clock,
                            universe_path=self.universe,
                            capture_dirs=(self.captures,),
                            archive_dir=self.archive_dir, day=day)
        patches = [
            mock.patch("src.data.tape_bars.capture_path",
                       side_effect=lambda probe: (
                           self.capture if probe == SESSION_DAY
                           else self.captures / f"capture_{probe:%Y%m%d}.ndjson")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        # The server reads the same clock the source does, so the session the
        # payload labels is the one the tape was built for.
        return self.make_server(source=source, symbols=("OGDC", "PPL"),
                                clock=clock)

    def test_days_merge_packs_the_last_two_sessions_on_one_chart(self):
        # A second capture, an older session, so "days=2" has two sessions
        # to merge: exactly the TradingView-style multi-day intraday chart.
        older = self.captures / "capture_20261009.ndjson"
        older.write_text("\n".join(json.dumps(row) for row in
                                   self.rows_for(datetime(
                                       2026, 10, 9).date())) + "\n",
                         encoding="utf-8")
        server = self.taping_server()
        body = self.body(server, "/api/bars?symbol=OGDC&days=2")
        self.assertTrue(body["ok"])
        self.assertEqual(body["bar_count"], 8)
        stamps = [row["t"] for row in body["bars"]]
        self.assertEqual(stamps, sorted(stamps))
        days = {row["t"][:10] for row in body["bars"]}
        self.assertEqual(days, {"2026-10-09", "2026-10-12"})
        # The newest session owns the session block, as a chart of today does.
        self.assertEqual(body["session"]["day"], "2026-10-12")
        self.assertTrue(body["session"]["current"])
        text = " ".join(body["notes"])
        self.assertIn("merged 2 session(s)", text)
        self.assertIn("session break", text)

    def test_days_merge_on_a_calendar_rung_ignores_the_merge(self):
        older = self.captures / "capture_20261009.ndjson"
        older.write_text("\n".join(json.dumps(row) for row in
                                   self.rows_for(datetime(
                                       2026, 10, 9).date())) + "\n",
                         encoding="utf-8")
        server = self.taping_server()
        body = self.body(server,
                         "/api/bars?symbol=OGDC&days=4&resolution=1d")
        self.assertTrue(body["ok"])
        self.assertEqual(body["bar_count"], 2)
        self.assertEqual([row["t"][:10] for row in body["bars"]],
                         ["2026-10-09", "2026-10-12"])

    def test_days_without_a_session_store_is_the_callers_400(self):
        server = self.make_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/bars?symbol=REPLAY1&days=3")
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "UNSUPPORTED_DAY")

    def test_a_bad_days_value_is_the_callers_400(self):
        server = self.taping_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/bars?symbol=OGDC&days=next")
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "BAD_DAYS")

    def test_sessions_lists_what_this_service_can_draw(self):
        server = self.taping_server()
        body = self.body(server, "/api/sessions")
        self.assertTrue(body["ok"])
        self.assertEqual(body["today"], "2026-10-12")
        self.assertEqual(body["timezone"], "Asia/Karachi")
        self.assertEqual([row["day"] for row in body["sessions"]],
                         ["2026-10-12"])
        self.assertTrue(body["sessions"][0]["current"])
        self.assertFalse(body["sessions"][0]["archived"])

    def test_todays_session_named_by_hand_is_labelled_as_today(self):
        server = self.taping_server(day="2026-10-12")
        body = self.body(server, "/api/bars?symbol=OGDC&day=2026-10-12")
        self.assertEqual(body["bar_count"], 4)
        self.assertEqual(body["session"]["day"], "2026-10-12")
        self.assertEqual(body["source"]["id"], "broker_tape")
        self.assertTrue(body["session"]["current"])
        self.assertFalse(body["session"]["archived"])
        self.assertIn("recording file", body["session"]["note"])
        # The recording that answered is named, so the reader can check it.
        self.assertEqual(body["session"]["source"],
                         "capture_20261012.ndjson")

    def test_a_finished_session_names_its_file_and_hash(self):
        server = self.taping_server(clock=tuesday_clock)
        body = self.body(server, "/api/bars?symbol=OGDC&day=2026-10-12")
        self.assertEqual(body["bar_count"], 4)
        self.assertFalse(body["session"]["current"])
        self.assertTrue(body["session"]["archived"])
        self.assertIn("archived 2026-10-12 session", body["session"]["note"])
        text = " ".join(body["notes"])
        self.assertIn("capture_20261012.ndjson", text)
        self.assertIn("sha256", text)
        self.assertEqual(body["session"]["capture"]["name"],
                         "capture_20261012.ndjson")
        self.assertEqual(len(body["session"]["capture"]["sha256"]), 64)

    def test_a_named_day_honours_the_volume_answer(self):
        server = self.taping_server(day="2026-10-12")
        body = self.body(server, "/api/bars?symbol=OGDC&day=2026-10-12")
        # This fixture carries a venue counter, so the pane is real data;
        # a capture with no counter answers false and the pane is not drawn.
        self.assertTrue(body["session"]["volume_available"])

    def test_a_named_day_with_no_data_is_an_error_not_an_empty_chart(self):
        server = self.taping_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/bars?symbol=OGDC&day=2026-10-08")
        response = connection.getresponse()
        self.assertEqual(response.status, 502)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "EMPTY_ACK")
        self.assertIn("2026-10-08", body["error"]["detail"])

    def test_a_malformed_day_is_the_callers_400(self):
        server = self.taping_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/bars?symbol=OGDC&day=Friday")
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "BAD_DAY")

    def test_a_day_query_on_a_source_without_sessions_is_refused(self):
        server = self.make_server()
        connection = http.client.HTTPConnection("127.0.0.1",
                                                server.server_address[1],
                                                timeout=10)
        self.addCleanup(connection.close)
        connection.request("GET", "/api/bars?symbol=REPLAY1&day=2026-10-12")
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        body = json.loads(response.read())
        self.assertEqual(body["error"]["code"], "UNSUPPORTED_DAY")

    def test_symbols_without_facts_keeps_the_plain_shape(self):
        server = self.taping_server()
        body = self.body(server, "/api/symbols")
        self.assertIn("OGDC", [row["symbol"] for row in body["symbols"]])
        self.assertNotIn("bars", body["symbols"][0])

    def test_symbols_with_facts_says_what_the_session_holds(self):
        server = self.taping_server()
        body = self.body(server, "/api/symbols?facts=1")
        rows = {row["symbol"]: row for row in body["symbols"]}
        self.assertEqual(rows["OGDC"]["bars"], 4)
        self.assertEqual(rows["OGDC"]["close"], 103.0)
        self.assertEqual(body["day"], None)

    def test_symbols_for_a_named_day_reports_that_days_bars(self):
        server = self.taping_server()
        body = self.body(server, "/api/symbols?day=2026-10-12")
        rows = {row["symbol"]: row for row in body["symbols"]}
        self.assertEqual(rows["PPL"]["bars"], 4)
        self.assertEqual(body["day"], "2026-10-12")

    def test_health_reports_the_tape_and_the_archive_size(self):
        server = self.taping_server()
        body = self.body(server, "/api/health")
        self.assertEqual(body["tape"]["available"], True)
        self.assertEqual(body["tape"]["symbols_with_bars"], 2)
        self.assertEqual(body["tape"]["archive_days"], 0)
        self.assertEqual(body["schema_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
