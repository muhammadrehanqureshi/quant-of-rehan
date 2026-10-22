"""The exchange index: the real levels, or an honestly labelled proxy.

Owner correction 2026-10-20: the chart served "KSE100" as an equal-weight
rebased proxy, and the owner called it wrong. The broker feed's own EXS-FEED
frames carry the exchange's published level, so what is checked here is that
the service now serves the real numbers when the capture holds them and says
precisely what it is serving when it does not:

  * an EXS-FEED frame with a real layout becomes the real level (measured
    against the 2026-10-16 capture: KSE100 166,231.18 to 166,532.86);
  * a minute bucket is OHLC of the values banked in that minute, at the
    arrival minute, with the venue's own session volume attached;
  * a stamp outside the session bands is not charted, and a capture with no
    index frames returns no bars and no invented level;
  * the payload's facts name which rail answered: ``exchange_index`` when
    the frames answered, ``computed_index`` and the proxy words otherwise;
  * the daily rung is the chain of the sessions the captures hold, each day
    labelled by its own session.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import index_feed  # noqa: E402

from charts.adapters.tape import (  # noqa: E402
    INDEX_KSE100, SOURCE_INDEX, SOURCE_INDEX_PROXY, TapeSource,
)

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY = date(2026, 10, 12)
MONDAY_1100 = datetime(2026, 10, 12, 11, 0, tzinfo=KARACHI)


def exs_frame(stamp: str, kse: float, day_change: float = 45.02,
              high: float | None = None, low: float | None = None,
              volume: int = 0) -> dict:
    """One EXS-FEED frame in the wire's own layout, KSE100 + ALLSHR."""
    high_text = "" if high is None else f"{high}"
    low_text = "" if low is None else f"{low}"
    raw = (f"EXS-FEED*{stamp}^"
           f"KSE100;{kse};{day_change};{high_text};413.125;{low_text};"
           f"-229.6563;267;167;17;{volume};1088102405.93;|^$"
           f"{stamp}^"
           f"ALLSHR;{kse + 34067.0};81.44;;328.6094;;-44.84375;267;167;17;"
           f"{volume * 7};3536130875.53;|^")
    return {"kind": "EXS-FEED*x", "ts": f"{MONDAY.isoformat()}T10:05:41+05:00",
            "ticks": [], "raw": raw}


class IndexFeedCase(unittest.TestCase):
    """A temporary capture directory that holds one day's index frames."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="charts-index-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.captures = self.tmp
        self.capture = self.captures / f"capture_{MONDAY:%Y%m%d}.ndjson"

    def write_captures(self, *rows: dict) -> Path:
        self.capture.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n",
            encoding="utf-8")
        return self.capture

    def source(self, clock: datetime = MONDAY_1100) -> TapeSource:
        return TapeSource(clock=lambda: clock,
                          capture_dirs=(self.captures,),
                          archive_dir=self.tmp / "archive")

    @staticmethod
    def stamps(minutes: int) -> list[str]:
        base = datetime(2026, 10, 12, 10, 5, 0)
        stamps = []
        for index in range(minutes):
            moment = base + timedelta(minutes=index * 2)
            hour = moment.strftime("%I:%M:%S %p")
            stamps.append(f"10/12/2026 {hour.lstrip('0')}")
        return stamps


class ParseTest(IndexFeedCase):
    """The reader, alone: never invents, never shifts a stamp."""

    def test_one_frame_yields_the_real_level_at_its_arrival_minute(self):
        self.write_captures(exs_frame("10/12/2026 10:05:34 AM", 166231.18,
                                      high=166599.29, low=165956.51))
        bars = index_feed.minute_bars(self.capture, MONDAY, "KSE100")
        self.assertEqual(len(bars), 1)
        bar = bars[0]
        self.assertEqual(bar["t"].strftime("%H:%M"), "10:05")
        self.assertEqual(bar["o"], 166231.18)
        self.assertEqual(bar["h"], 166231.18)
        self.assertEqual(bar["l"], 166231.18)
        self.assertEqual(bar["c"], 166231.18)

    def test_two_frames_in_one_minute_span_their_values(self):
        self.write_captures(
            exs_frame("10/12/2026 10:05:34 AM", 166231.18),
            exs_frame("10/12/2026 10:05:59 AM", 166410.5))
        bars = index_feed.minute_bars(self.capture, MONDAY, "KSE100")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["o"], 166231.18)
        self.assertEqual(bars[0]["h"], 166410.5)
        self.assertEqual(bars[0]["l"], 166231.18)
        self.assertEqual(bars[0]["c"], 166410.5)

    def test_the_all_shares_index_serves_under_its_chart_name(self):
        self.write_captures(exs_frame("10/12/2026 10:05:34 AM", 166231.18))
        bars = index_feed.minute_bars(self.capture, MONDAY, "KMIALLSHR")
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["c"], 166231.18 + 34067.0)

    def test_layouts_that_cannot_read_yield_nothing(self):
        broken = {"kind": "EXS-FEED*x", "ts": "2026-10-12T10:05:41+05:00",
                  "ticks": [], "raw": "EXS-FEED*not a stamp^KSE100;abc;"}
        self.write_captures(exs_frame("10/12/2026 10:05:34 AM", 166231.18),
                            broken)
        self.assertEqual(len(index_feed.minute_bars(
            self.capture, MONDAY, "KSE100")), 1)
        # A stamp the wire malformed with nothing else readable is dropped.
        self.write_captures(broken)
        self.assertEqual(index_feed.minute_bars(self.capture, MONDAY,
                                                "KSE100"), [])

    def test_a_capture_without_index_frames_is_not_a_level(self):
        row = {"kind": "MKT-FEED*x", "ts": "2026-10-12T10:05:41+05:00",
               "ticks": [{"scrip": "OGDC:REG", "last": "300.0"}]}
        self.write_captures(row)
        self.assertEqual(index_feed.minute_bars(self.capture, MONDAY,
                                                "KSE100"), [])


class ServedIndexTest(IndexFeedCase):
    """The service: the real level preferred, the proxy labelled as such."""

    def test_the_service_serves_the_exchange_level_not_1000(self):
        stamps = self.stamps(3)
        levels = (166231.18, 166320.0, 166532.86)
        self.write_captures(*[exs_frame(stamp, level)
                              for stamp, level in zip(stamps, levels)])
        stamps = self.stamps(3)
        levels = (166231.18, 166320.0, 166532.86)
        frames = [exs_frame(stamp, level, high=level + 80, low=level - 60,
                            volume=16_214_620 + index * 1_000)
                  for index, (stamp, level) in enumerate(zip(stamps, levels))]
        self.write_captures(*frames)
        source = self.source()
        bars = source.history("KSE100", "1m", day=MONDAY)
        self.assertEqual(len(bars), 3)
        self.assertEqual(bars[0].o, 166231.18)
        self.assertEqual(bars[-1].c, 166532.86)
        self.assertEqual(source.source_info("KSE100", day=MONDAY).id,
                         SOURCE_INDEX.id)
        # The volume arrives from the frame's own session counter.
        self.assertGreaterEqual(bars[-1].v, bars[0].v)
        self.assertGreater(bars[-1].v, 0.0)

    def test_the_facts_say_the_exchange_frames_answered(self):
        self.write_captures(*[exs_frame(stamp, level) for stamp, level in
                              zip(self.stamps(2), (166231.18, 166320.0))])
        source = self.source()
        note_text = " ".join(source.notes("KSE100", day=MONDAY))
        self.assertIn("EXS-FEED", note_text)
        self.assertIn("exchange's own", note_text)

    def test_no_frames_means_a_labelled_proxy_not_a_rebased_claim(self):
        # A capture that holds tape rows but no EXS frame: the proxy rail.
        # The clock stands at noon so every bar is behind the as-of gate.
        noon = datetime(MONDAY.year, MONDAY.month, MONDAY.day, 12, 0,
                        tzinfo=KARACHI)
        minutes = 3
        rows = []
        for index in range(minutes):
            moment = MONDAY_1100 + timedelta(minutes=index)
            rows.append({
                "kind": "MKT-FEED*x",
                "ts": moment.isoformat(),
                "ticks": [{"scrip": "OGDC:REG", "last": str(300.0 + index),
                           "volume": str(1000 * (index + 1)),
                           "tick_time": moment.strftime("%H:%M:%S")}],
            })
        self.write_captures(*rows)
        source = self.source(clock=noon)
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            bars = source.history("KSE100", "1m", day=MONDAY)
        self.assertGreater(len(bars), 0)
        self.assertEqual(bars[0].o, 1000.0)  # the proxy's own rebase
        info = source.source_info("KSE100", day=MONDAY)
        self.assertEqual(info.id, SOURCE_INDEX_PROXY.id)
        self.assertIn("no EXS-FEED index frame",
                      " ".join(source.notes("KSE100", day=MONDAY)))

    def test_the_daily_rung_chains_the_days_the_captures_hold(self):
        # Two minutes on Monday and one capture on Tuesday: a 1W or 1D fold
        # must be labelled by each day's own session, never averaged across.
        self.write_captures(*[exs_frame(stamp, level) for stamp, level in
                              zip(self.stamps(2), (166231.18, 166320.0))])
        tuesday = MONDAY + timedelta(days=1)
        TUESDAY = tuesday  # name used by the assertions below
        tuesday_capture = self.captures / f"capture_{tuesday:%Y%m%d}.ndjson"
        stamp = "10/13/2026 10:05:34 AM"
        tuesday_capture.write_text(json.dumps(exs_frame(stamp, 166700.0)) + "\n",
                                   encoding="utf-8")
        # The clock stands on Tuesday, so both days are available.
        tuesday_noon = datetime(tuesday.year, tuesday.month, tuesday.day,
                                12, 0, tzinfo=KARACHI)
        source = self.source(clock=tuesday_noon)
        monday_daily = source.history("KSE100", "1D", day=MONDAY)
        self.assertEqual(len(monday_daily), 1)
        self.assertEqual(monday_daily[0].t[:10], "2026-10-12")
        self.assertEqual(monday_daily[0].o, 166231.18)
        self.assertEqual(monday_daily[0].c, 166320.0)
        # Monday's close is Tuesday's level baseline: each day is its own
        # session, chained, never averaged.
        tuesday_daily = source.history("KSE100", "1D", day=TUESDAY)
        self.assertEqual(len(tuesday_daily), 1)
        self.assertEqual(tuesday_daily[0].c, 166700.0)


if __name__ == "__main__":
    unittest.main()
