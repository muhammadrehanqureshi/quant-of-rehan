"""The timeframe ladder and the PSX session alignment it enforces."""

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

from charts import resolutions as ladder  # noqa: E402
from charts.adapters.tape import TapeSource  # noqa: E402
from charts.contract import Bar  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY = date(2026, 10, 12)
FRIDAY = date(2026, 10, 16)
MONDAY_OPEN = datetime(2026, 10, 12, 9, 32, tzinfo=KARACHI)


def bar(moment: datetime, price: float, volume: float = 10.0) -> Bar:
    return Bar.build(t=moment, o=price - 0.2, h=price + 0.5,
                     l=price - 0.6, c=price, v=volume)


class LadderTest(unittest.TestCase):

    def test_every_requested_rung_is_known(self):
        self.assertEqual(
            ladder.RESOLUTION_IDS,
            ("1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h",
             "4h", "1D", "1W", "1M"),
        )
        for resolution in ladder.RESOLUTION_IDS:
            self.assertEqual(ladder.normalise(resolution), resolution)
        self.assertEqual(ladder.normalise("1d"), "1D")
        self.assertEqual(ladder.normalise("1hour"), "1h")
        with self.assertRaises(ValueError):
            ladder.normalise("3m")

    def test_five_minute_bars_are_band_aligned_and_keep_ohlcv(self):
        rows = [bar(MONDAY_OPEN + timedelta(minutes=step), 100 + step)
                for step in range(10)]
        folded = ladder.aggregate(rows, "5m")
        self.assertEqual([row.t for row in folded],
                         ["2026-10-12T09:32:00+05:00",
                          "2026-10-12T09:37:00+05:00"])
        self.assertEqual(folded[0].o, rows[0].o)
        self.assertEqual(folded[0].h, max(row.h for row in rows[:5]))
        self.assertEqual(folded[0].l, min(row.l for row in rows[:5]))
        self.assertEqual(folded[0].c, rows[4].c)
        self.assertEqual(folded[0].v, 50.0)

    def test_the_friday_break_is_never_folded_into_a_candle(self):
        before = datetime(2026, 10, 16, 11, 59, tzinfo=KARACHI)
        after = datetime(2026, 10, 16, 14, 32, tzinfo=KARACHI)
        folded = ladder.aggregate([bar(before, 100), bar(after, 101)], "1h")
        self.assertEqual([row.t for row in folded],
                         ["2026-10-16T11:17:00+05:00",
                          "2026-10-16T14:32:00+05:00"])

    def test_bars_outside_the_session_are_dropped_not_folded(self):
        outside = datetime(2026, 10, 12, 16, 5, tzinfo=KARACHI)
        self.assertEqual(ladder.aggregate([bar(outside, 100)], "1m"), [])

    def test_expected_buckets_exclude_the_friday_break(self):
        minutes = ladder.expected_bucket_starts(FRIDAY, "5m")
        self.assertEqual(minutes[0],
                         datetime(2026, 10, 16, 9, 17, tzinfo=KARACHI))
        self.assertIn(datetime(2026, 10, 16, 14, 32, tzinfo=KARACHI), minutes)
        self.assertNotIn(datetime(2026, 10, 16, 13, 0, tzinfo=KARACHI), minutes)


class TickRungTest(unittest.TestCase):
    """Sub-minute bars come from ticks, and the index proxies are honest."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="charts-ladder-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.capture = self.tmp / "capture_20261012.ndjson"
        self.universe = self.tmp / "universe.json"
        self.universe.write_text(json.dumps(["AAA", "BBB"]), encoding="utf-8")
        self.write_capture()

    def write_capture(self) -> None:
        rows = []
        for second in range(5):
            moment = datetime(2026, 10, 12, 9, 33, second, tzinfo=KARACHI)
            for symbol, price, volume in (("AAA", 100 + second, 1000 + 100 * second),
                                          ("BBB", 200 + second, 2000 + 200 * second)):
                rows.append({
                    "kind": "MKT-FEED*x", "ts": moment.isoformat(),
                    "ticks": [{"scrip": f"{symbol}:REG", "last": str(price),
                               "volume": str(volume),
                               "tick_time": moment.strftime("%H:%M:%S")}],
                })
        self.capture.write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    def source(self, clock: datetime) -> TapeSource:
        return TapeSource(clock=lambda: clock, universe_path=self.universe,
                          capture_dirs=(self.tmp,),
                          archive_dir=self.tmp / "archive")

    def test_second_bars_are_built_from_tick_rows(self):
        source = self.source(datetime(2026, 10, 12, 10, 0, tzinfo=KARACHI))
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            bars = source.history("AAA", "1s", limit=0)
        self.assertEqual(len(bars), 5)
        self.assertEqual(bars[0].o, 100.0)
        self.assertEqual(bars[-1].c, 104.0)
        # The venue's own counter is differenced, never summed twice.
        self.assertEqual([row.v for row in bars], [0.0, 100.0, 100.0, 100.0, 100.0])

    def test_the_index_proxies_are_computed_from_the_session_tape(self):
        source = self.source(datetime(2026, 10, 12, 10, 0, tzinfo=KARACHI))
        with mock.patch("charts.adapters.tape.tape_bars.capture_path",
                        return_value=self.capture):
            all_share = source.history("KMIALLSHR", "1m", limit=0)
            top100 = source.history("KSE100", "1m", limit=0)
            notes = source.notes("KMIALLSHR")
        self.assertEqual(all_share[0].o, 1000.0)
        self.assertGreater(all_share[-1].c, 1000.0)
        self.assertEqual(len(all_share), 1)
        self.assertEqual(len(top100), 1)
        self.assertTrue(any("not the exchange's official" in line
                            for line in notes))


if __name__ == "__main__":
    unittest.main()
