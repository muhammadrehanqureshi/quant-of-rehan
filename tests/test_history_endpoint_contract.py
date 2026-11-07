"""The relay's minute bars: one row per minute, built from accepted frames.

The owner's desktop build draws a full-day candlestick chart per KMIALL scrip
and its own buffer holds only about five minutes of one-second samples. The
relay therefore aggregates the accepted quote feed into minute bars and serves
them at `GET /history`.

These tests pin the parts a chart depends on, because the Worker cannot run on
this PC (SO-23): one store row per minute carrying every symbol (so a session
costs about 360 written rows, not one per symbol per minute), bars built only
from frames the session law already accepted, an honest volume definition, a
bounded retention window, and an answer that says when a day has no bars
instead of drawing an invented flat line (SO-3).
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "cloud" / "worker.js"


class HistoryEndpointContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = WORKER.read_text(encoding="utf-8")

    def test_the_public_route_exists_and_is_cors_readable(self):
        self.assertIn('path === "/history"', self.source)
        self.assertIn('hub.fetch("https://quote-hub/history?"', self.source)
        start = self.source.index(
            'if (request.method === "GET" && path === "/history")')
        end = self.source.index(
            'if (request.method === "GET" && path === "/sectors")', start)
        body = self.source[start:end]
        self.assertIn('"access-control-allow-origin": "*"', body)
        self.assertIn('"cache-control": "no-store"', body)
        options = self.source[
            self.source.index('if (request.method === "OPTIONS" &&'):]
        options = options[:options.index(
            'if (request.method === "GET" && path === "/quotes/stream")')]
        self.assertIn('path === "/history"', options)

    def test_the_route_validates_its_three_inputs(self):
        for line in (
            'const resolution = String(url.searchParams.get("resolution") || "1m");',
            'return json({ ok: false, error: "resolution must be 1m" }, 400',
            'return json({ ok: false, error: "invalid symbol" }, 400',
            'return json({ ok: false, error: "day must be YYYY-MM-DD" }, 400',
            "const HISTORY_MAX_BARS = 1000;",
            "const HISTORY_DEFAULT_BARS = 500;",
        ):
            with self.subTest(line=line):
                self.assertIn(line, self.source)

    def test_an_absent_limit_takes_the_documented_default(self):
        """Number(null) is 0, which would have served one bar, not 500."""
        for line in (
            'const askedRaw = url.searchParams.get("limit");',
            'const asked = askedRaw === null ? NaN : Number(askedRaw);',
            'const askedLimitRaw = url.searchParams.get("limit");',
            'const askedLimit = askedLimitRaw === null ? NaN : Number(askedLimitRaw);',
        ):
            with self.subTest(line=line):
                self.assertIn(line, self.source)

    def test_bars_are_one_row_per_minute_carrying_every_symbol(self):
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS quote_bars (day TEXT NOT NULL, "
            "minute INTEGER NOT NULL, payload TEXT NOT NULL", self.source)
        self.assertIn("PRIMARY KEY (day, minute))", self.source)
        start = self.source.index("  flushFormingBar() {")
        body = self.source[start:start + 3000]
        self.assertIn("const names = Object.keys(symbols);", body)
        self.assertIn("for (const name of names) {", body)
        self.assertIn(
            "payload[name] = { o: bar.o, h: bar.h, l: bar.l, c: bar.c,",
            body)
        # Exactly one INSERT per flush, keyed by the minute: a per-symbol row
        # would be about 115,000 written rows a session on its own.
        self.assertEqual(body.count("INSERT INTO quote_bars"), 1)
        self.assertIn("ON CONFLICT(day, minute) DO UPDATE", body)

    def test_the_daily_row_ceiling_and_retention_are_pinned(self):
        self.assertIn("const BAR_ROWS_PER_DAY = 1000;", self.source)
        self.assertIn("if (this.barRowsToday >= BAR_ROWS_PER_DAY) return false;",
                      self.source)
        self.assertIn("const BAR_RETENTION_DAYS = 45;", self.source)
        self.assertIn("DELETE FROM quote_bars WHERE day < ?", self.source)

    def test_a_bar_is_built_only_from_an_accepted_session_frame(self):
        start = self.source.index("const accepted = body.quotes.filter")
        end = self.source.index("quotes.set(quote.symbol, quote);", start)
        body = self.source[start:end]
        self.assertIn("frameIsTradingSession(quote)", body)
        self.assertIn("this.accumulateBar(quote);", body)
        # The call sits after the session filter and after the stale and
        # decreasing-volume refusals, so no rejected frame can shape a candle.
        self.assertLess(body.index("frameIsTradingSession(quote)"),
                        body.index("this.accumulateBar(quote)"))
        self.assertLess(body.index("newVolume < oldVolume"),
                        body.index("this.accumulateBar(quote)"))

    def test_the_ohlc_fields_and_the_karachi_stamp_are_exact(self):
        start = self.source.index("async historyAnswer(url)")
        end = self.source.index("async snapshot()", start)
        body = self.source[start:end]
        self.assertIn("t: this.barStamp(day, minute),", body)
        self.assertIn("o: Number(bar.o), h: Number(bar.h), l: Number(bar.l),",
                      body)
        self.assertIn("c: Number(bar.c), v: Math.max(0, Number(bar.v) || 0),",
                      body)
        self.assertIn("as_of: this.karachiStamp(Date.now()),", body)
        self.assertIn("return `${day}T${this.barClock(minute)}:00+05:00`;",
                      self.source)

    def test_volume_is_the_observed_increment_and_says_so(self):
        start = self.source.index("  accumulateBar(quote) {")
        body = self.source[start:start + 2200]
        self.assertIn(
            "first: before !== null && volume !== null && before <= volume "
            "? before : volume,", body)
        self.assertIn(
            "if (volume !== null) this.barVolumes.totals[symbol] = volume;",
            body)
        self.assertIn(
            "v: first !== null && last !== null ? Math.max(0, last - first) : 0",
            self.source)
        self.assertIn(
            "a minute's volume is the observed increase of the venue's "
            "cumulative day total between the first and last frame accepted "
            "in that minute", self.source)

    def test_an_empty_day_is_absent_never_a_flat_line(self):
        self.assertIn(
            "no stored minute bars for this symbol and day; nothing is filled in",
            self.source)
        self.assertIn("the relay began storing bars on 2026-11-07",
                      self.source)
        self.assertIn("forming: formingMinute !== null && bars.length > 0",
                      self.source)
        self.assertIn(
            "the last bar is the minute still forming and can change until it "
            "closes", self.source)

    def test_a_reader_can_ask_which_days_exist(self):
        self.assertIn("retention_days: BAR_RETENTION_DAYS,", self.source)
        self.assertIn("so this answer is coverage only", self.source)
        self.assertIn("GROUP BY day ", self.source)

    def test_the_new_class_loads_on_a_fresh_instance(self):
        """A deployed class change does not restart the never-idle object."""
        self.assertIn('const QUOTE_HUB_NAME = "psx-live-quotes-v4";',
                      self.source)

    def test_a_redraw_is_served_from_the_isolate_memo(self):
        """A repaint must not spend a Durable Object request every frame."""
        self.assertIn("const HISTORY_MEMO_MS = 5000;", self.source)
        self.assertIn("const HISTORY_MEMO_MAX = 32;", self.source)
        self.assertIn("historyMemo.get(cacheKey)", self.source)
        self.assertIn("historyMemo.set(cacheKey, { at: stamp, body });",
                      self.source)

    def test_the_answer_merges_stored_bars_with_the_live_minute(self):
        start = self.source.index("async historyAnswer(url)")
        end = self.source.index("async snapshot()", start)
        body = self.source[start:end]
        self.assertIn("await this.loadBarsDay(day)", body)
        self.assertIn("if (this.barForming && this.barForming.day === day)",
                      body)
        self.assertIn("const bars = all.slice(-limit);", body)


if __name__ == "__main__":
    unittest.main()
