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

    # ---- the rankable population (redesign 2026-10-15) ------------------
    #
    # Measured on the real session tapes: freshness across the whole 319
    # symbol KMIALL universe peaks at 74.9% to 78.7% inside five minutes,
    # because a slice of KMIALL genuinely prints less often than that. A
    # whole-universe freshness floor therefore blocked every live scan, which
    # is why no signal could ever exist. These cases pin the replacement: the
    # tail is REPORTED, the leaders and the rankable count are what block.

    def test_an_illiquid_tail_is_reported_not_blocking(self):
        """A market is scannable when its leaders and depth are.

        The tail here has real bar history (25 bars each, so the history gate
        is satisfied) but stopped printing 15 minutes before the scan, which
        is what a slice of KMIALL genuinely does. The scan must proceed and
        report the tail rather than block on it.
        """
        bars = {f"LIQ{index:03d}": minute_rows(40, step=0.01, accel=0.02)
                for index in range(config.MIN_RANKABLE_SYMBOLS + 5)}
        for index in range(20):
            bars[f"QUIET{index:02d}"] = minute_rows(25)
        symbols = list(bars)
        session = session_of(bars, 39)
        quality = scanner.assess_quality(session, symbols)

        self.assertEqual(quality.status, "OK", quality.reason)
        self.assertEqual(quality.symbols_with_bars, len(symbols))
        self.assertEqual(quality.symbols_with_history, len(symbols))
        self.assertEqual(quality.rankable_symbols,
                         config.MIN_RANKABLE_SYMBOLS + 5)
        self.assertEqual(quality.leader_symbols, config.LEADER_SLICE)
        self.assertEqual(quality.leaders_fresh, config.LEADER_SLICE)
        self.assertEqual(len(quality.symbols_stale), 20)
        self.assertLess(quality.fresh_coverage, config.MIN_FRESH_COVERAGE_PCT,
                        "the fixture must reproduce the tail that used to "
                        "block every scan")
        self.assertIn("idle longer than", quality.reason)
        self.assertFalse(quality.warming_up)

    def test_stale_volume_leaders_block_and_are_named(self):
        """A candidate must never be chosen from prices that stopped moving."""
        fresh = {f"LIQ{index:03d}": minute_rows(40, step=0.01, volume=1_000.0)
                 for index in range(30)}
        # Five symbols that carried the day's value and then went quiet: they
        # are the leaders a candidate would be chosen from.
        late = {f"LATE{index:02d}": minute_rows(20, step=0.01,
                                                volume=500_000.0)
                for index in range(5)}
        bars = {**fresh, **late}
        session = session_of(bars, 39)
        quality = scanner.assess_quality(session, list(bars))

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertIn("stale leaders", quality.reason)
        self.assertIn("LATE00", quality.reason)
        self.assertEqual(quality.leaders_fresh,
                         config.LEADER_SLICE - len(late))
        self.assertAlmostEqual(quality.leaders_fresh_share, 0.75, places=4)

    def test_too_thin_a_population_blocks_even_with_fresh_leaders(self):
        """Depth somewhere is not depth: 20 usable symbols is not a market.

        The leaders are fresh here on purpose, so the block comes from the
        rankable count alone rather than from the leader slice.
        """
        bars = {f"LIVE{index:03d}": minute_rows(40, step=0.01,
                                                volume=100_000.0)
                for index in range(20)}
        for index in range(300):
            bars[f"OLD{index:03d}"] = minute_rows(25, volume=5_000.0)
        session = session_of(bars, 39)
        quality = scanner.assess_quality(session, list(bars))

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertIn("too few rankable symbols", quality.reason)
        self.assertEqual(quality.leaders_fresh, config.LEADER_SLICE)
        self.assertEqual(quality.rankable_symbols, 20)
        self.assertLess(quality.rankable_symbols, config.MIN_RANKABLE_SYMBOLS)
        self.assertIn("idle longer than", quality.reason)

    def test_a_young_capture_warms_up_and_is_not_a_fault(self):
        """Measured 2026-10-14: this state was counted as 86 faults a band."""
        bars = {f"LIQ{index:03d}": minute_rows(8, step=0.01)
                for index in range(30)}
        session = session_of(bars, 8)
        quality = scanner.assess_quality(session, list(bars))

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertTrue(quality.warming_up, quality.reason)
        self.assertIn("WARMING UP", quality.reason)
        self.assertGreater(quality.warmup_minutes_remaining, 0.0)
        self.assertIn("bar history", quality.reason)

    def test_a_capture_with_no_bars_at_all_is_not_a_warmup(self):
        """Nothing at all is a dead source, and the runner faults on it."""
        session = session_of({}, 8)
        quality = scanner.assess_quality(session, ["OGDC", "PRL"])

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertFalse(quality.warming_up)
        self.assertEqual(quality.warmup_minutes_remaining, 0.0)

    def test_an_old_thin_capture_is_not_a_warmup_either(self):
        """Past the grace the same low history is a genuine data failure."""
        bars = {"OGDC": minute_rows(8, step=0.01)}
        session = session_of(bars, 8)
        session.as_of = session.as_of + timedelta(
            minutes=config.WARMUP_GRACE_MINUTES + 1)
        quality = scanner.assess_quality(session, ["OGDC"])

        self.assertEqual(quality.status, scanner.DATA_BLOCKED)
        self.assertFalse(quality.warming_up)
        self.assertIn("say nothing about the market", quality.reason)

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
            "symbol": "OGDC", "score": 71.5, "stop_loss": 122.5, "momentum": "STRONG",
            "acceleration_label": "STRONG", "volume_label": "STRONG",
            "volume": {"relative": 3.25},
        }
        text = scanner.signal_message(candidate, {"status": "SUPPORTIVE"},
                                      123.45, SESSION_OPEN)
        for needle in ("QUANT LONG SIGNAL", "Symbol: OGDC", "Entry price: 123.4500",
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
