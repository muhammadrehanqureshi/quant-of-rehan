"""The tape bar path: prints for OHLC, the venue's counter for volume.

Owner order 2026-10-14: the scanner must stop depending on the eClear OHLC
servlet, which serves nothing now. These tests hold the bar builder
(src/data/tape_bars.py) to its own promises:

  * a minute's open, high, low and close come from the prices the tape
    carried, in arrival order;
  * volume comes from the venue's running counter and from nothing else;
  * a quiet minute may carry the previous close, but only across a gap the
    tape was genuinely watching, and never past the last observation;
  * nothing is invented: a backwards counter, a priceless row, a repeated
    snapshot and the volume traded before the tape arrived are each measured
    and reported rather than flattened into bars.

They also hold the wiring: the scanner loads tape bars through the same
SessionData shape and the same quality gates as the servlet capture, a thin
capture is DATA BLOCKED rather than a market NO TRADE, and the pipeline
prefers the tape while still reading a servlet capture from disk.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import tape_bars  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402

MONDAY = date(2026, 10, 12)
OPEN = datetime(2026, 10, 12, 9, 32, tzinfo=KARACHI)


def tick(symbol: str, price, volume, at: datetime,
         tick_time: str | None = None, high=None, low=None) -> dict:
    """One MKT-FEED row in the shape src/data/feed_capture.py banks."""
    row = {
        "scrip": f"{symbol}:REG",
        "last": "" if price is None else str(price),
        "volume": None if volume is None else str(volume),
        "tick_time": tick_time or f"{at:%H:%M:%S}",
    }
    if high is not None:
        row["high"] = str(high)
    if low is not None:
        row["low"] = str(low)
    return row


def frame(at: datetime, *rows: dict, kind: str = "MKT-FEED") -> dict:
    return {"kind": f"{kind}*x", "ts": at.isoformat(),
            "ticks": list(rows)}


class TapeCaptureFixture(unittest.TestCase):
    def write(self, records: list[dict]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False,
                                             encoding="utf-8")
        for record in records:
            handle.write(json.dumps(record) + "\n")
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def build(self, records: list[dict], symbols: list[str],
              as_of: datetime):
        return tape_bars.build(self.write(records), symbols, as_of)


class TestPrintsBecomeBars(TapeCaptureFixture):
    def test_one_minute_of_prints_is_one_bar(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 1000, minute, "09:33:05",
                               high=101.0, low=99.0)),
            frame(minute + timedelta(seconds=20),
                  tick("OGDC", 101.5, 1400, minute, "09:33:25",
                       high=101.0, low=99.0)),
            frame(minute + timedelta(seconds=40),
                  tick("OGDC", 99.5, 1900, minute, "09:33:45",
                       high=101.0, low=99.0)),
        ], ["OGDC"], minute + timedelta(minutes=1))

        rows = tape.bars["OGDC"]
        self.assertEqual(len(rows), 1)
        bar = rows[0]
        self.assertEqual(bar.timestamp, minute)
        self.assertEqual((bar.open, bar.high, bar.low, bar.close),
                         (100.0, 101.5, 99.5, 99.5))
        self.assertEqual(bar.prints, 3)
        self.assertFalse(bar.carried)

    def test_volume_is_the_venue_counter_difference(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 5000, minute, "09:33:05")),
            frame(minute + timedelta(seconds=30),
                  tick("OGDC", 100.0, 8000, minute, "09:33:05")),
            frame(minute + timedelta(seconds=50),
                  tick("OGDC", 100.5, 9500, minute, "09:33:50")),
        ], ["OGDC"], minute + timedelta(minutes=1))

        bar = tape.bars["OGDC"][0]
        # 5000 was traded before the tape saw the symbol, so it is reported as
        # that symbol's opening counter value and never counted as a bar's
        # volume. The bar holds the two windows the tape actually watched.
        self.assertEqual(tape.pre_tape_volume, {"OGDC": 5000})
        self.assertEqual(bar.volume, 4500.0)
        self.assertTrue(tape.volume_available)

    def test_a_running_total_that_goes_backwards_is_not_negative_volume(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 9000, minute)),
            frame(minute + timedelta(seconds=30), tick("OGDC", 100.0, 4000,
                                                       minute + timedelta(seconds=30),
                                                       "09:33:30")),
        ], ["OGDC"], minute + timedelta(minutes=1))

        self.assertEqual(tape.bars["OGDC"][0].volume, 0.0)
        self.assertEqual(tape.counter_resets, 1)
        self.assertTrue(any("backwards" in note for note in tape.notes))

    def test_a_row_without_a_price_is_counted_not_guessed(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([
            frame(minute, tick("OGDC", None, 1000, minute)),
            frame(minute + timedelta(seconds=30),
                  tick("OGDC", 250.0, 1200, minute, "09:33:30")),
        ], ["OGDC"], minute + timedelta(minutes=1))

        self.assertEqual(tape.priceless_rows, 1)
        self.assertEqual(tape.bars["OGDC"][0].open, 250.0)

    def test_future_rows_and_other_symbols_are_left_out(self):
        tape = self.build([
            frame(OPEN + timedelta(minutes=1), tick("OGDC", 100.0, 1000,
                                                    OPEN + timedelta(minutes=1))),
            frame(OPEN + timedelta(minutes=9), tick("OGDC", 130.0, 9000,
                                                    OPEN + timedelta(minutes=9))),
            frame(OPEN + timedelta(minutes=1), tick("PRL", 50.0, 1000,
                                                    OPEN + timedelta(minutes=1))),
        ], ["OGDC"], OPEN + timedelta(minutes=2))

        self.assertEqual(list(tape.bars), ["OGDC"])
        self.assertEqual([bar.close for bar in tape.bars["OGDC"]], [100.0])


class TestQuietMinutes(TapeCaptureFixture):
    def test_a_quiet_minute_carries_the_previous_close(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 1000, minute)),
            frame(minute + timedelta(minutes=2),
                  tick("OGDC", 102.0, 4000, minute + timedelta(minutes=2))),
        ], ["OGDC"], minute + timedelta(minutes=3))

        rows = tape.bars["OGDC"]
        self.assertEqual([row.timestamp for row in rows],
                         [minute, minute + timedelta(minutes=1),
                          minute + timedelta(minutes=2)])
        self.assertTrue(rows[1].carried)
        self.assertEqual((rows[1].open, rows[1].high, rows[1].low,
                          rows[1].close), (100.0, 100.0, 100.0, 100.0))
        self.assertEqual(rows[1].volume, 0.0)
        self.assertEqual(rows[1].prints, 0)

    def test_a_hole_wider_than_the_carry_bound_is_left_as_a_hole(self):
        minute = OPEN + timedelta(minutes=1)
        after_outage = minute + timedelta(
            seconds=config.TAPE_CARRY_MAX_GAP_SECONDS + 60)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 1000, minute)),
            frame(after_outage, tick("OGDC", 102.0, 4000, after_outage)),
        ], ["OGDC"], after_outage + timedelta(minutes=1))

        rows = tape.bars["OGDC"]
        self.assertEqual(len(rows), 2, "an outage is not a flat line")
        self.assertEqual(tape.carried_bars, 0)
        self.assertEqual(tape.hole_symbols, ("OGDC",))
        self.assertTrue(any("hole" in note for note in tape.notes))

    def test_a_repeated_snapshot_still_means_the_tape_was_watching(self):
        minute = OPEN + timedelta(minutes=5)
        repeated = tick("OGDC", 100.0, 1000, minute, "09:37:00")
        tape = self.build([
            frame(minute, repeated),
            frame(minute + timedelta(seconds=20), dict(repeated)),
            frame(minute + timedelta(seconds=40), dict(repeated)),
        ], ["OGDC"], minute + timedelta(minutes=1))

        self.assertEqual(tape.repeated_rows, 2)
        rows = tape.bars["OGDC"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].prints, 1, "a repeat is not a new print")

    def test_nothing_is_written_after_the_last_observation(self):
        minute = OPEN + timedelta(minutes=1)
        as_of = minute + timedelta(minutes=20)
        tape = self.build([
            frame(minute, tick("OGDC", 100.0, 1000, minute)),
        ], ["OGDC"], as_of)

        self.assertEqual(len(tape.bars["OGDC"]), 1)
        self.assertEqual(tape.bars["OGDC"][0].timestamp, minute)


class TestHonestLabels(TapeCaptureFixture):
    def test_the_source_says_where_the_bars_came_from(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([frame(minute, tick("OGDC", 100.0, 1000, minute))],
                          ["OGDC"], minute + timedelta(minutes=1))
        self.assertIn("MKT-FEED tape", tape.source)
        self.assertIn("volume counter", tape.source)
        self.assertIn("prints for open", tape.source)

    def test_a_tape_without_the_counter_cannot_support_a_volume_scan(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([frame(minute, tick("OGDC", 100.0, None, minute))],
                          ["OGDC"], minute + timedelta(minutes=1))

        self.assertFalse(tape.volume_available)
        self.assertTrue(any("no venue volume counter" in note
                            for note in tape.notes))

    def test_the_summary_is_measured_and_readable(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([frame(minute, tick("OGDC", 100.0, 1000, minute))],
                          ["OGDC"], minute + timedelta(minutes=1))
        summary = tape.as_dict()

        for key in ("source", "symbols_with_bars", "bars", "priced_bars",
                    "carried_bars", "carried_share", "counter_rows",
                    "volume_available", "pre_tape_volume_total", "notes",
                    "venue_extreme_violations"):
            self.assertIn(key, summary)
        self.assertEqual(summary["symbols_with_bars"], 1)

    def test_a_flag_is_left_only_when_the_tape_is_thin(self):
        minute = OPEN + timedelta(minutes=1)
        tape = self.build([frame(minute, tick("OGDC", 100.0, 1000, minute))],
                          ["OGDC"], minute + timedelta(minutes=1))
        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            with mock.patch.object(tape_bars, "LOW_COVERAGE_FLAG", flag):
                self.assertIsNone(
                    tape_bars.write_low_coverage_flag(tape, 1, cause="one of one"))
                written = tape_bars.write_low_coverage_flag(tape, 100,
                                                            cause="thin tape")
            self.assertIsNotNone(written)
            self.assertTrue(flag.is_file())
            payload = json.loads(flag.read_text(encoding="utf-8"))
        self.assertIn("tape", payload["source"])
        self.assertEqual(payload["universe"], 100)
        self.assertIn("thin tape", payload["cause"])


class TestScannerReadsTheTape(TapeCaptureFixture):
    def _tape_file(self, minutes: int, symbols: list[str]) -> tuple[Path, datetime]:
        records = []
        for index in range(minutes):
            at = OPEN + timedelta(minutes=index)
            for symbol in symbols:
                price = 100.0 + index * 0.1
                records.append(frame(at, tick(symbol, price, 1000 * (index + 1),
                                              at, high=price + 0.2,
                                              low=price - 0.2)))
        return self.write(records), OPEN + timedelta(minutes=minutes)

    def test_the_tape_loader_produces_the_same_session_shape(self):
        path, as_of = self._tape_file(40, ["OGDC", "PRL"])
        session = scanner.load_tape_bars(path, ["OGDC", "PRL"], as_of)

        self.assertEqual(set(session.bars), {"OGDC", "PRL"})
        self.assertEqual(len(session.bars["OGDC"]), 40)
        self.assertTrue(session.volume_available)
        self.assertIn("MKT-FEED tape", session.source)
        self.assertTrue(session.notes)

    def test_the_same_gates_apply_and_pass_on_a_healthy_tape(self):
        path, as_of = self._tape_file(40, ["OGDC", "PRL"])
        session = scanner.load_tape_bars(path, ["OGDC", "PRL"], as_of)
        quality = scanner.assess_quality(session, ["OGDC", "PRL"])

        self.assertEqual(quality.status, "OK", quality.reason)
        self.assertEqual(quality.symbols_with_bars, 2)
        self.assertEqual(quality.symbols_with_history, 2)
        self.assertAlmostEqual(quality.history_coverage, 1.0)
        self.assertIn("MKT-FEED tape", quality.source)

    def test_a_thin_capture_is_data_blocked_not_a_market_no_trade(self):
        """The bar path made this a real case: fresh bars, no history."""
        path, as_of = self._tape_file(5, ["OGDC", "PRL"])
        session = scanner.load_tape_bars(path, ["OGDC", "PRL"], as_of)
        quality = scanner.assess_quality(session, ["OGDC", "PRL"])
        result = scanner.select_one(session, quality)

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertEqual(result.status, scanner.DATA_BLOCKED)
        self.assertIn("bar history", quality.reason)
        self.assertIn(str(config.MIN_BARS_PER_SYMBOL), quality.reason)
        self.assertEqual(quality.symbols_with_history, 0)
        self.assertIsNone(result.candidate)

    def test_coverage_and_staleness_are_still_measured_the_same_way(self):
        path, as_of = self._tape_file(40, ["OGDC"])
        session = scanner.load_tape_bars(path, ["OGDC", "PRL", "LUCK"], as_of)
        quality = scanner.assess_quality(session, ["OGDC", "PRL", "LUCK"])
        self.assertAlmostEqual(quality.coverage, 1 / 3, places=4)
        self.assertIn("incomplete", quality.reason)

        stale = scanner.load_tape_bars(path, ["OGDC"], as_of + timedelta(minutes=30))
        stale_quality = scanner.assess_quality(stale, ["OGDC"])
        self.assertEqual(stale_quality.status, scanner.DATA_BLOCKED)
        self.assertIn("stale", stale_quality.reason)

    def test_the_blocked_message_names_the_tape(self):
        path, as_of = self._tape_file(5, ["OGDC"])
        session = scanner.load_tape_bars(path, ["OGDC"], as_of)
        quality = scanner.assess_quality(session, ["OGDC"])
        text = scanner.scan_blocked_message(quality)

        self.assertIn("SCAN BLOCKED", text)
        self.assertIn("MKT-FEED tape", text)
        self.assertIn("Bar history:", text)
        self.assertIn("DATA failure", text)

    def test_the_format_is_read_from_the_file(self):
        tape_path, as_of = self._tape_file(2, ["OGDC"])
        self.assertEqual(scanner.detect_capture_format(tape_path),
                         scanner.FORMAT_TAPE)

        poller = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False,
                                             encoding="utf-8")
        poller.write(json.dumps({"ts": as_of.isoformat(), "symbol": "OGDC",
                                 "bars": [{"t": "09:33", "o": 1, "h": 1, "l": 1,
                                           "c": 1, "v": 1}]}) + "\n")
        poller.close()
        self.addCleanup(lambda: Path(poller.name).unlink(missing_ok=True))
        self.assertEqual(scanner.detect_capture_format(Path(poller.name)),
                         scanner.FORMAT_POLLER)

    def test_the_one_door_loads_either_format(self):
        tape_path, as_of = self._tape_file(25, ["OGDC"])
        session = scanner.load_session(tape_path, ["OGDC"], as_of)
        self.assertIn("MKT-FEED tape", session.source)


class TestPipelinePrefersTheTape(TapeCaptureFixture):
    """Both capture dirs are redirected to one temporary root, so the choice is
    decided by what is on disk rather than by what happens to exist locally."""

    def _redirect(self, pipeline, root: Path):
        """Point the servlet dir and the tape dir at one temporary root."""
        return mock.patch.multiple(
            pipeline,
            DATA_DIR=root,
            tape_capture_path=lambda day: root / f"capture_{day:%Y%m%d}.ndjson",
        )

    def test_the_tape_wins_when_it_exists(self):
        import scripts.intraday_pipeline as pipeline

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tape = root / "capture_20261012.ndjson"
            poller = root / "ohlc_20261012.ndjson"
            tape.write_text("{}\n", encoding="utf-8")
            poller.write_text("{}\n", encoding="utf-8")
            with self._redirect(pipeline, root):
                self.assertEqual(pipeline.resolve_capture(MONDAY), tape)

    def test_a_servlet_capture_on_disk_is_still_read(self):
        import scripts.intraday_pipeline as pipeline

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            poller = root / "ohlc_20261012.ndjson"
            poller.write_text("{}\n", encoding="utf-8")
            with self._redirect(pipeline, root):
                self.assertEqual(pipeline.resolve_capture(MONDAY), poller)

    def test_with_no_capture_the_tape_path_is_named_honestly(self):
        import scripts.intraday_pipeline as pipeline

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self._redirect(pipeline, root):
                resolved = pipeline.resolve_capture(MONDAY)
            self.assertEqual(resolved.name, "capture_20261012.ndjson")
            self.assertFalse(resolved.exists())

    def test_the_observation_says_which_capture_spoke(self):
        import scripts.intraday_pipeline as pipeline

        path, as_of = self._observation_tape()
        session = scanner.load_session(path, ["OGDC"], as_of)
        label = pipeline.capture_label(path, session)

        self.assertEqual(label["format"], scanner.FORMAT_TAPE)
        self.assertIn("MKT-FEED tape", label["source"])
        self.assertTrue(label["notes"])

    def _observation_tape(self) -> tuple[Path, datetime]:
        records = []
        for index in range(30):
            at = OPEN + timedelta(minutes=index)
            records.append(frame(at, tick("OGDC", 100.0 + index, 500 * index,
                                          at)))
        return self.write(records), OPEN + timedelta(minutes=30)


class TestTheAlertQuotesItsSource(unittest.TestCase):
    def test_a_tape_flag_says_what_still_ran(self):
        import scripts.ops_alert as ops_alert

        payload = {"coverage": 0.1, "symbols_ok": 10, "universe": 100,
                   "source": tape_bars.SOURCE,
                   "cause": "the tape held bars for 10 of 100 KMIALL symbols"}
        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            flag.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(ops_alert, "FLAG", flag):
                text = ops_alert.capture_health_message()

        self.assertIn("capture degraded", text)
        self.assertIn("10/100 symbols", text)
        self.assertIn("Source:", text)
        self.assertIn("still ran on the bars the tape held", text)
        self.assertNotIn("No scan or outcome ran", text)

    def test_a_servlet_flag_still_says_the_slot_was_lost(self):
        import scripts.ops_alert as ops_alert

        with tempfile.TemporaryDirectory() as temp_dir:
            flag = Path(temp_dir) / "ohlc_low_coverage.flag"
            flag.write_text(json.dumps({"coverage": 0.0, "symbols_ok": 0,
                                        "universe": 319}), encoding="utf-8")
            with mock.patch.object(ops_alert, "FLAG", flag):
                text = ops_alert.capture_health_message()

        self.assertIn("No scan or outcome ran for this slot", text)
        self.assertNotIn("Measured cause:", text)


if __name__ == "__main__":
    unittest.main()
