"""Tests for the intraday forensic audit: execution, data quality, metrics.

These are research-only tests. They do not run the March 2026 study or touch
the live engine; they pin the corrections that separate an executable print
from a carried or stale bar.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.backtest import intraday_forensic as fx  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.data.tape_bars import TapeBar, TapeBars  # noqa: E402

DAY = date(2026, 10, 26)
OPEN = datetime(2026, 10, 26, 9, 32, tzinfo=KARACHI)
CLOSE = datetime(2026, 10, 26, 15, 30, tzinfo=KARACHI)


def bar(at: datetime, open_: float, high: float, low: float, close: float,
        prints: int = 2, carried: bool = False, open_is_print: bool = True,
        volume: float = 1000.0) -> TapeBar:
    first = at + timedelta(seconds=5) if prints else None
    last = at + timedelta(seconds=50) if prints else None
    return TapeBar(
        at, open_, high, low, close, volume, prints, carried,
        open_is_print, first, open_ if prints else None, last,
    )


def band(rows: dict[str, list[TapeBar]], close: datetime = CLOSE) -> dict:
    return {"day": DAY, "index": 0, "open": OPEN, "close": close,
            "rows": rows}


class TestExecutableEntry(unittest.TestCase):
    def test_a_carried_minute_is_not_an_entry(self):
        completion = OPEN
        carried = TapeBar(completion, 100.0, 100.0, 100.0, 100.0, 0.0, 0,
                          True)
        fresh = bar(completion + timedelta(minutes=1), 101.0, 101.2, 100.8,
                    101.0)
        trade = fx.simulate_executable(
            band({"OGDC": [carried, fresh]}), "OGDC", completion)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["entry"], 101.0)
        self.assertFalse(trade["entry_bar"]["carried"])

    def test_a_stale_minute_is_not_an_entry(self):
        completion = OPEN
        stale = bar(completion, 100.0, 100.0, 100.0, 100.0, prints=0,
                    open_is_print=False)
        fresh = bar(completion + timedelta(minutes=1), 101.0, 101.2, 100.8,
                    101.0)
        trade = fx.simulate_executable(
            band({"OGDC": [stale, fresh]}), "OGDC", completion)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["entry"], 101.0)
        self.assertEqual(trade["entry_bar"]["prints"], 2)

    def test_the_entry_minute_counts_and_the_stop_wins_a_tie(self):
        entry = bar(OPEN, 100.0, 102.5, 98.5, 100.0)
        trade = fx.simulate_executable(
            band({"OGDC": [entry]}), "OGDC", OPEN)
        self.assertIsNotNone(trade)
        self.assertTrue(trade["same_bar"])
        self.assertTrue(trade["ambiguous"])
        self.assertEqual(trade["exit_reason"], "stop")
        self.assertEqual(trade["exit"], 99.0)

    def test_a_target_in_the_entry_minute_is_a_target_first(self):
        entry = bar(OPEN, 100.0, 102.5, 99.5, 100.0)
        trade = fx.simulate_executable(
            band({"OGDC": [entry]}), "OGDC", OPEN)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], "target")
        self.assertEqual(trade["exit"], 102.0)
        self.assertFalse(trade["same_bar"])

    def test_a_gap_through_the_stop_fills_at_the_first_print(self):
        entry = bar(OPEN, 100.0, 100.2, 99.8, 100.0)
        gap = bar(OPEN + timedelta(minutes=1), 98.0, 98.5, 97.5, 98.0,
                  prints=1)
        gap = TapeBar(gap.timestamp, gap.open, gap.high, gap.low, gap.close,
                      gap.volume, gap.prints, False, True,
                      gap.timestamp + timedelta(seconds=3), 98.0,
                      gap.timestamp + timedelta(seconds=3))
        trade = fx.simulate_executable(
            band({"OGDC": [entry, gap]}), "OGDC", OPEN)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], "stop_gap")
        self.assertEqual(trade["exit"], 98.0)
        self.assertLess(trade["net"], -0.02)

    def test_a_last_print_exit_is_not_dated_at_the_close_boundary(self):
        entry = bar(OPEN, 100.0, 100.2, 99.8, 100.0)
        last = bar(CLOSE - timedelta(minutes=1), 100.0, 100.2, 99.9, 100.1)
        trade = fx.simulate_executable(
            band({"OGDC": [entry, last]}), "OGDC", OPEN)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], "session_end")
        self.assertEqual(trade["exit_time"],
                         (last.timestamp + timedelta(seconds=50)).isoformat())

    def test_a_quiet_tape_ends_at_the_last_print_not_the_session_close(self):
        entry = bar(OPEN, 100.0, 100.2, 99.8, 100.0)
        last = bar(CLOSE - timedelta(minutes=10), 100.0, 100.2, 99.9, 100.1)
        trade = fx.simulate_executable(
            band({"OGDC": [entry, last]}), "OGDC", OPEN)
        self.assertIsNotNone(trade)
        self.assertEqual(trade["exit_reason"], "tape_end")
        self.assertEqual(trade["exit_time"],
                         (last.timestamp + timedelta(seconds=50)).isoformat())


class TestStrictFrames(unittest.TestCase):
    def test_a_carried_minute_cannot_complete_a_five_minute_frame(self):
        rows = [bar(OPEN + timedelta(minutes=i), 100.0 + i, 100.5 + i,
                    99.5 + i, 100.2 + i) for i in range(5)]
        rows[2] = TapeBar(rows[2].timestamp, 100.0, 100.0, 100.0, 100.0,
                          0.0, 0, True)
        frames = fx.completed_strict(rows, 5, OPEN, OPEN + timedelta(minutes=5))
        self.assertEqual(frames, [])

    def test_five_fresh_minutes_make_one_frame(self):
        rows = [bar(OPEN + timedelta(minutes=i), 100.0 + i, 100.5 + i,
                    99.5 + i, 100.2 + i) for i in range(5)]
        frames = fx.completed_strict(rows, 5, OPEN, OPEN + timedelta(minutes=5))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].timestamp, OPEN)
        self.assertAlmostEqual(frames[0].volume, 5000.0)


class TestQualityAndPrices(unittest.TestCase):
    def test_as_dict_counts_minute_buckets_not_tape_rows(self):
        tape = TapeBars(day=DAY, minute_bars=3, priced_bars=100,
                        carried_bars=2)
        self.assertEqual(tape.as_dict()["bars"], 3)
        self.assertEqual(tape.as_dict()["minute_bars"], 3)

    def test_a_decimal_scale_is_corrected_and_the_trade_is_retained(self):
        at = OPEN
        entry_bar = bar(at, 30675.62, 30675.62, 30000.0, 30000.0)
        normals = [bar(at + timedelta(minutes=i), 30.7, 30.8, 30.6, 30.7)
                   for i in range(1, 11)]
        tape = TapeBars(day=DAY, bars={"UPFL": [entry_bar, *normals]},
                        venue_extremes={"UPFL": (29.0, 33.0)})
        trade = {
            "symbol": "UPFL", "strategy": "current_kalman_flip",
            "day": DAY.isoformat(), "signal_time": at.isoformat(),
            "entry_time": at.isoformat(), "exit_time": (at + timedelta(
                minutes=1)).isoformat(), "entry": 30675.62, "exit": 30000.0,
            "target": 31289.13, "stop": 30368.26, "exit_reason": "tape_end",
            "gross": -0.022025, "net": -0.028505,
        }
        evidence = fx.price_evidence(tape, trade)
        self.assertEqual(evidence["classification"], "decimal_scaling")
        self.assertAlmostEqual(evidence["inferred_price_scale"], 0.001, places=6)
        self.assertEqual(evidence["retained"], True)
        self.assertAlmostEqual(evidence["corrected_prices"]["entry"], 30.67562,
                               places=5)

    def test_a_complete_session_needs_an_early_start_and_a_close_observation(self):
        tape = TapeBars(day=DAY, first_observation=OPEN - timedelta(minutes=1),
                        observed_at={"OGDC": CLOSE - timedelta(minutes=1)},
                        bars={"OGDC": [bar(OPEN, 100.0, 100.0, 100.0, 100.0)]})
        rows = tape.bars["OGDC"]
        day_data = {
            "day": DAY, "tape": tape,
            "bands": [({"day": DAY, "index": 0, "open": OPEN, "close": CLOSE,
                       "rows": {"OGDC": rows}}, tape)],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".ndjson",
                                         delete=False) as handle:
            handle.write("{}\n")
            path = Path(handle.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        raw = {
            "tick_rows": 1, "symbols": 1, "duplicate_consecutive_rows": 0,
            "out_of_order_records": 0, "new_print_lag_seconds": {},
            "circuit_caps": [],
        }
        quality = fx.session_quality(day_data, path, raw, 1)
        self.assertTrue(quality["complete"])
        self.assertEqual(quality["symbols_with_bars"], 1)


class TestMetricsAndLaw(unittest.TestCase):
    def test_target_first_and_net_are_separate(self):
        target = {"net": 0.011492, "gross": 0.02, "net_before_cgt": 0.01352,
                  "cgt": 0.002028, "exit_reason": "target", "hold_minutes": 10}
        stop = {"net": -0.01648, "gross": -0.01, "net_before_cgt": -0.01648,
                "cgt": 0.0, "exit_reason": "stop", "hold_minutes": 5}
        metrics = fx.one_metrics([target, stop])
        self.assertEqual(metrics["trades"], 2)
        self.assertEqual(metrics["wins"], 1)
        self.assertEqual(metrics["target_first"], 1)
        self.assertAlmostEqual(metrics["target_first_rate"], 0.5)
        self.assertAlmostEqual(metrics["net_expectancy"],
                               (0.011492 - 0.01648) / 2)
        self.assertGreater(metrics["cgt_total"], 0.0)

    def test_sixty_complete_sessions_are_required(self):
        report = fx.metrics([], [], ["2026-10-26"],
                            ["current_kalman_flip"])
        self.assertFalse(report["sample_sufficient"])
        self.assertFalse(report["selection_allowed"])
        self.assertEqual(report["required_complete_sessions"], 60)
        self.assertEqual(fx.data_standard()["required_complete_sessions"], 60)

    def test_strategy_ten_remains_not_tested(self):
        last = fx.STRATEGY_AUDIT[-1]
        self.assertEqual(last["number"], 10)
        self.assertEqual(last["status"], "not_tested")

    def test_a_close_boundary_trade_is_outside_the_regular_band(self):
        trade = {
            "symbol": "OGDC", "strategy": "current_kalman_flip",
            "entry_time": datetime(2026, 10, 26, 15, 30,
                                   tzinfo=KARACHI).isoformat(),
            "exit_time": datetime(2026, 10, 26, 15, 30,
                                  tzinfo=KARACHI).isoformat(),
        }
        audit = fx.market_session_audit(DAY, [trade])
        self.assertEqual(audit["outside_band"], 1)
        self.assertEqual(audit["trades"], 1)

    def test_the_cost_and_cgt_law_is_the_repository_law(self):
        self.assertAlmostEqual(fx.ROUND_TRIP_COST, config.round_trip_cost())
        self.assertAlmostEqual(fx.CGT_RATE, config.CGT_RATE)
        self.assertEqual(fx.TARGET, config.TARGET_PCT)
        self.assertEqual(fx.STOP, config.KALMAN_STOP_PCT)


if __name__ == "__main__":
    unittest.main()
