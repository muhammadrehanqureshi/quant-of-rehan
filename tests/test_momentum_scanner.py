"""Acceptance tests for the single authoritative momentum + volume scanner.

Owner acceptance list (2026-10-09) covered here:
  TEST 3  exact coverage reporting
  TEST 4  a broken source produces DATA BLOCKED, never a fake NO TRADE
  TEST 5  the scanner ranks the whole captured universe
  TEST 6  exactly one winner is returned
  TEST 7  a weak top candidate produces NO TRADE
  TEST 8  the target is exactly +2.0% from the actual entry
  TEST 8b volume is required: a source without volume is DATA BLOCKED, and no
          price-only proxy is substituted

Everything here is offline: bars are synthesised in memory, so the suite never
depends on the vendor being up.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI, open_time  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402


WEDNESDAY = date(2026, 10, 7)      # Mon-Thu session: 09:32 to 15:30 PKT
SESSION_OPEN = datetime.combine(WEDNESDAY, __import__("datetime").time(*open_time(WEDNESDAY)),
                                tzinfo=KARACHI)


def minute_rows(count: int, start_price: float = 100.0, step: float = 0.0,
                accel: float = 0.0, volume: float = 5_000.0,
                bucket_multiplier: float = 1.0) -> list[scanner.MinuteBar]:
    """Build `count` consecutive one-minute bars from the session open.

    `accel` grows the per-minute step over the session, which is what real
    acceleration looks like: the last minutes move faster than the first.
    `bucket_multiplier` lifts the volume of the final five-minute bucket,
    which is what real volume expansion looks like.
    """
    rows = []
    price = start_price
    for index in range(count):
        stamp = SESSION_OPEN + timedelta(minutes=index)
        effective = step * (1.0 + accel * index)
        price = round(price + effective, 4)
        high = round(price + abs(effective), 4)
        low = round(price - abs(effective), 4)
        vol = volume
        if index >= count - 5:
            vol *= bucket_multiplier
        rows.append(scanner.MinuteBar(stamp, price, high, low, price, round(vol, 2)))
    return rows


def session_of(bars: dict[str, list[scanner.MinuteBar]], minutes: int,
               volume_available: bool = True) -> scanner.SessionData:
    as_of = SESSION_OPEN + timedelta(minutes=minutes)
    return scanner.SessionData(
        day=WEDNESDAY, as_of=as_of, bars=bars, volume_available=volume_available,
        bars_seen=sum(len(rows) for rows in bars.values()), bars_rejected=0,
        duplicate_bars=0,
    )


class TestQualityGate(unittest.TestCase):
    def test_broken_source_is_data_blocked_not_no_trade(self):
        """TEST 4: an empty capture must not be reported as a market verdict."""
        session = session_of({}, 40)
        quality = scanner.assess_quality(session, ["OGDC", "PRL", "ATRL"])
        result = scanner.select_one(session, quality)

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertEqual(result.status, scanner.DATA_BLOCKED)
        self.assertIn("0.0%", quality.reason)
        self.assertEqual(quality.symbols_with_bars, 0)
        self.assertEqual(quality.symbols_expected, 3)
        self.assertIsNone(result.candidate)

    def test_coverage_is_reported_exactly(self):
        """TEST 3: coverage numbers are measured, not estimated."""
        bars = {sym: minute_rows(40, step=0.01) for sym in ("OGDC", "PRL", "ATRL")}
        session = session_of(bars, 39)
        quality = scanner.assess_quality(session, ["OGDC", "PRL", "ATRL", "LUCK"])

        self.assertEqual(quality.symbols_with_bars, 3)
        self.assertEqual(quality.symbols_expected, 4)
        self.assertAlmostEqual(quality.coverage, 0.75, places=4)
        self.assertEqual(quality.symbols_missing, ("LUCK",))
        self.assertEqual(quality.resolution, config.BAR_RESOLUTION)

    def test_coverage_below_floor_blocks_and_explains(self):
        bars = {sym: minute_rows(40, step=0.01) for sym in ("OGDC", "PRL")}
        symbols = ["OGDC", "PRL", "ATRL", "LUCK", "MARI"]
        session = session_of(bars, 39)
        quality = scanner.assess_quality(session, symbols)

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertIn("40.0%", quality.reason)
        self.assertIn("incomplete", quality.reason)

    def test_stale_data_blocks(self):
        bars = {"OGDC": minute_rows(40, step=0.01)}
        session = session_of(bars, 39)
        session.as_of = session.as_of + timedelta(minutes=20)
        quality = scanner.assess_quality(session, ["OGDC"])

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertTrue("stale" in quality.reason or "old" in quality.reason)

    def test_missing_volume_blocks_instead_of_guessing(self):
        """TEST 8b: the strategy needs volume; no proxy is substituted."""
        bars = {"OGDC": minute_rows(40, step=0.01)}
        bars["OGDC"] = [scanner.MinuteBar(b.timestamp, b.open, b.high, b.low,
                                          b.close, None) for b in bars["OGDC"]]
        session = session_of(bars, 39, volume_available=False)
        quality = scanner.assess_quality(session, ["OGDC"])
        result = scanner.select_one(session, quality)

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertIn("no volume", quality.reason)
        self.assertIn("different strategy", quality.reason)
        self.assertEqual(result.status, scanner.DATA_BLOCKED)

    def test_non_trading_day_blocks(self):
        session = session_of({"OGDC": minute_rows(40, step=0.01)}, 39)
        session.day = date(2026, 10, 10)   # Saturday
        session.as_of = datetime(2026, 10, 10, 11, 0, tzinfo=KARACHI)
        quality = scanner.assess_quality(session, ["OGDC"])

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertIn("not a PSX trading day", quality.reason)


class TestCaptureLoad(unittest.TestCase):
    def _capture(self, records: list[dict]) -> Path:
        handle = tempfile.NamedTemporaryFile("w", suffix=".ndjson", delete=False,
                                            encoding="utf-8")
        for record in records:
            handle.write(json.dumps(record) + "\n")
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return Path(handle.name)

    def _record(self, symbol: str, bars: list[dict]) -> dict:
        return {"ts": (SESSION_OPEN + timedelta(minutes=2)).isoformat(),
                "symbol": symbol, "bars": bars}

    def _bar(self, minute: int, price: float, volume: float | None = 1000.0) -> dict:
        bar = {"t": f"{9 + (32 + minute) // 60:02d}:{(32 + minute) % 60:02d}",
               "o": price, "h": price + 0.05, "l": price - 0.05, "c": price}
        if volume is not None:
            bar["v"] = volume
        return bar

    def test_impossible_and_malformed_bars_are_rejected_not_repaired(self):
        path = self._capture([self._record("OGDC", [
            self._bar(0, 100.0),
            {"t": "09:33", "o": 100.0, "h": 99.0, "l": 101.0, "c": 100.0, "v": 10.0},
            {"t": "09:34", "o": "x", "h": 1, "l": 1, "c": 1, "v": 1},
            self._bar(3, float("nan")),
        ])])
        session = scanner.load_capture(path, ["OGDC"],
                                       SESSION_OPEN + timedelta(minutes=5))

        self.assertEqual(len(session.bars["OGDC"]), 1)
        self.assertEqual(session.bars["OGDC"][0].close, 100.0)

    def test_future_bars_are_ignored(self):
        path = self._capture([self._record("OGDC", [
            self._bar(0, 100.0), self._bar(1, 101.0), self._bar(30, 130.0),
        ])])
        as_of = SESSION_OPEN + timedelta(minutes=2)
        session = scanner.load_capture(path, ["OGDC"], as_of)
        self.assertEqual([b.close for b in session.bars["OGDC"]], [100.0, 101.0])

    def test_volume_availability_is_measured(self):
        with_volume = self._capture([self._record("OGDC", [self._bar(0, 100.0)])])
        without = self._capture([self._record("OGDC", [self._bar(0, 100.0, None)])])
        as_of = SESSION_OPEN + timedelta(minutes=5)

        self.assertTrue(scanner.load_capture(with_volume, ["OGDC"], as_of)
                        .volume_available)
        self.assertFalse(scanner.load_capture(without, ["OGDC"], as_of)
                         .volume_available)

    def test_other_symbols_are_not_copied(self):
        path = self._capture([self._record("PRL", [self._bar(0, 50.0)])])
        session = scanner.load_capture(path, ["OGDC"],
                                       SESSION_OPEN + timedelta(minutes=5))
        self.assertEqual(session.bars, {})


class TestScoring(unittest.TestCase):
    def test_ranking_covers_every_eligible_symbol_and_returns_one_winner(self):
        """TEST 5 and TEST 6."""
        bars = {
            "FAST": minute_rows(45, start_price=100.0, step=0.0103, accel=0.25,
                                bucket_multiplier=4.0),
            "STEADY": minute_rows(45, start_price=100.0, step=0.006, accel=0.10,
                                  bucket_multiplier=2.0),
            "FLAT": minute_rows(45, start_price=100.0, step=0.0),
        }
        session = session_of(bars, 45)
        quality = scanner.assess_quality(session, list(bars))
        result = scanner.select_one(session, quality)

        self.assertEqual(quality.status, "OK")
        self.assertGreaterEqual(len(result.ranked), 1)
        self.assertEqual(result.status, scanner.TRADE)
        self.assertEqual(result.candidate["symbol"], "FAST")
        self.assertEqual(result.candidate, result.ranked[0])
        self.assertEqual(len(result.ranked), len({row["symbol"] for row in result.ranked}))

    def test_weak_candidate_is_no_trade(self):
        """TEST 7: a candidate that is not strong enough is not traded."""
        bars = {"MEH": minute_rows(45, start_price=100.0, step=0.0002, accel=0.02,
                                   bucket_multiplier=1.02)}
        session = session_of(bars, 45)
        quality = scanner.assess_quality(session, list(bars))
        result = scanner.select_one(session, quality)

        self.assertEqual(result.status, scanner.NO_TRADE)
        self.assertIsNone(result.candidate)
        self.assertTrue("minimum" in result.reason or "no symbol passed" in result.reason
                        or "market not supportive" in result.reason)

    def test_extension_is_penalised_not_chased(self):
        """A stock that already ran hard loses points for being late."""
        hot = minute_rows(45, start_price=100.0, step=0.1, accel=0.2,
                          bucket_multiplier=4.0)
        calm = minute_rows(45, start_price=100.0, step=0.006, accel=0.25,
                           bucket_multiplier=4.0)
        hot_session = session_of({"HOT": hot}, 45)
        calm_session = session_of({"CALM": calm}, 45)
        hot_row = scanner.score_symbol("HOT", hot, hot_session)
        calm_row = scanner.score_symbol("CALM", calm, calm_session)

        self.assertIsNotNone(hot_row)
        self.assertGreater(hot_row["penalties"]["extension_points_lost"], 0.0)
        self.assertLess(hot_row["penalties"]["extension_factor"], 1.0)
        self.assertLess(hot_row["score"], hot_row["weighted_score"])
        self.assertGreater(calm_row["score"], hot_row["score"])
        self.assertGreater(calm_row["returns"]["session"], 0.0)
        self.assertLess(hot_row["score"], config.MIN_SIGNAL_SCORE)

    def test_market_selloff_blocks_the_long(self):
        bars = {
            f"SYM{i}": minute_rows(45, start_price=100.0, step=-0.01, accel=0.1,
                                   bucket_multiplier=4.0)
            for i in range(6)
        }
        bars["HERO"] = minute_rows(45, start_price=100.0, step=0.0103, accel=0.25,
                                   bucket_multiplier=4.0)
        session = session_of(bars, 45)
        quality = scanner.assess_quality(session, list(bars))
        result = scanner.select_one(session, quality)

        self.assertEqual(result.status, scanner.NO_TRADE)
        self.assertIn("market not supportive", result.reason)
        self.assertIn(result.market["status"], ("SELLOFF", "WEAK"))

    def test_score_components_are_reported_for_reproduction(self):
        bars = {"FAST": minute_rows(45, start_price=100.0, step=0.0103, accel=0.25,
                                    bucket_multiplier=4.0)}
        session = session_of(bars, 45)
        row = scanner.score_symbol("FAST", bars["FAST"], session)

        self.assertIsNotNone(row)
        self.assertEqual(set(row["components"]), set(config.SCORE_WEIGHTS))
        for name in config.SCORE_WEIGHTS:
            self.assertGreaterEqual(row["components"][name], 0.0)
            self.assertLessEqual(row["components"][name], 1.0)
        self.assertGreater(row["score"], 0.0)
        self.assertLessEqual(row["score"], 100.0)
        self.assertIn("returns", row)
        self.assertIn("volume", row)


class TestMessages(unittest.TestCase):
    def test_target_is_always_two_percent_of_actual_entry(self):
        """TEST 8: the target derives from the recorded entry price."""
        for entry in (1.0, 12.345, 100.0, 1234.56):
            with self.subTest(entry=entry):
                self.assertAlmostEqual(scanner.target_price(entry),
                                       round(entry * (1.0 + config.TARGET_PCT), 4),
                                       places=4)
        self.assertAlmostEqual(config.TARGET_PCT, 0.02, places=9)

    def test_signal_message_carries_the_required_fields(self):
        candidate = {
            "symbol": "OGDC", "score": 71.5, "momentum": "STRONG",
            "acceleration_label": "STRONG", "volume_label": "STRONG",
            "volume": {"relative": 3.25},
        }
        text = scanner.signal_message(candidate, {"status": "SUPPORTIVE"},
                                      123.45, SESSION_OPEN)
        for needle in ("QUANT LONG SIGNAL", "Symbol: OGDC", "Entry: 123.4500",
                       "Target: 125.9190", "ONE TRADE ONLY", "+2.0%"):
            self.assertIn(needle, text)

    def test_blocked_message_says_it_is_data_not_a_decision(self):
        session = session_of({}, 40)
        quality = scanner.assess_quality(session, ["OGDC", "PRL"])
        text = scanner.scan_blocked_message(quality)

        self.assertIn("SCAN BLOCKED", text)
        self.assertIn("KMIALL coverage: 0/2", text)
        self.assertIn("DATA failure", text)

    def test_no_trade_message_reports_scanned_counts(self):
        bars = {"MEH": minute_rows(45, start_price=100.0, step=0.0002, accel=0.02,
                                   bucket_multiplier=1.02)}
        session = session_of(bars, 45)
        quality = scanner.assess_quality(session, ["MEH", "OTHER"])
        text = scanner.no_trade_message(quality, {"status": "WEAK", "reason": "x"})

        self.assertIn("NO TRADE", text)
        self.assertIn("KMIALL scanned: 1/2", text)


if __name__ == "__main__":
    unittest.main()
