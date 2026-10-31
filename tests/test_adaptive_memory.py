"""The quant's measured memory (owner order 2026-10-31) under test.

The laws under test are the three the memory speaks with:

  * an hour bucket whose closed entries averaged below the floor over at
    least the minimum vetoes a fresh entry THERE, saying what it saw;
  * a symbol whose most recent entries each stopped out vetoes that
    symbol, and one good session clears the streak;
  * a confirmed entry into a falling tape is refused, whatever the flip
    said, because the quant does not go against the market.

And the honesty laws around them (SO-3): an empty history vetoes
nothing and says so, an unverified outcome is not a trade, and nothing
here writes history anywhere.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals import adaptive_memory  # noqa: E402


def trade_row(day: str, symbol: str, label: str, net: float,
              entry: datetime | None = None) -> dict:
    """One gate row, in the shape session_history.session_rows emits."""
    row = {
        "date": day,
        "label": label,
        "net_return": net,
        "symbol": symbol,
        "candidate": {"symbol": symbol},
    }
    if entry is not None:
        row["entry_time"] = entry.isoformat()
    return row


def band_open(day: str) -> datetime:
    """A 09:32 PKT Monday stamp, tz aware, the weekday band's own open."""
    return datetime.fromisoformat(f"{day}T09:32:00+05:00").astimezone(KARACHI)


class FromRowsTests(unittest.TestCase):
    def test_empty_history_vetoes_nothing_and_says_so(self):
        memory = adaptive_memory.AdaptiveMemory.from_rows([])
        self.assertEqual(memory.trades_read, 0)
        self.assertTrue(memory.honest_notes)
        self.assertIsNone(memory.entry_veto("PRL", band_open("2026-11-02")))
        self.assertIsNone(memory.market_veto(None))

    def test_unverified_and_non_trade_rows_are_not_trades(self):
        rows = [
            trade_row("2026-10-26", "PRL", "UNVERIFIED", None),
            trade_row("2026-10-27", "PRL", "UNVERIFIED", -0.01),
            trade_row("2026-10-28", "PRL", "NO_CANDIDATE", -0.01),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertEqual(memory.trades_read, 0)

    def test_stop_streak_vetoes_symbol_after_two_consecutive_stops(self):
        # The trade that started this order: PRL's first Kalman call
        # stopped out. The law needs its SECOND consecutive stop.
        rows = [
            trade_row("2026-10-29", "PRL", "SL_FIRST", -0.010,
                      band_open("2026-10-29")),
            trade_row("2026-10-30", "PRL", "SL_AMBIG", -0.004,
                      band_open("2026-10-30")),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertEqual(memory.symbol_streaks.get("PRL"), 2)
        veto = memory.entry_veto("PRL", band_open("2026-11-02"))
        self.assertIsNotNone(veto)
        self.assertIn("PRL", veto)
        self.assertIn("stop", veto)

    def test_one_good_session_clears_the_symbol_streak(self):
        rows = [
            trade_row("2026-10-28", "PRL", "SL_FIRST", -0.010,
                      band_open("2026-10-28")),
            trade_row("2026-10-29", "PRL", "TP_FIRST", 0.0195,
                      band_open("2026-10-29")),
            trade_row("2026-10-30", "PRL", "TIMEOUT", 0.001,
                      band_open("2026-10-30")),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertNotIn("PRL", memory.symbol_streaks)
        self.assertIsNone(memory.entry_veto("PRL", band_open("2026-11-02")))

    def test_symbol_streak_counts_only_that_symbol(self):
        rows = [
            trade_row("2026-10-29", "PRL", "SL_FIRST", -0.010,
                      band_open("2026-10-29")),
            trade_row("2026-10-29", "KEL", "SL_FIRST", -0.010,
                      band_open("2026-10-29")),
            trade_row("2026-10-30", "OTHER", "SL_FIRST", -0.010,
                      band_open("2026-10-30")),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertEqual(memory.symbol_streaks.get("PRL"), 1)
        self.assertIsNone(memory.entry_veto("PRL", band_open("2026-11-02")))

    def test_bucket_veto_needs_the_measured_minimum(self):
        # Two losing entries in the first quarter of the band: below the
        # default minimum of three, the hour says nothing (SO-3).
        rows = [
            trade_row("2026-10-29", "PRL", "SL_FIRST", -0.010,
                      band_open("2026-10-29") + timedelta(minutes=3)),
            trade_row("2026-10-30", "KEL", "SL_FIRST", -0.010,
                      band_open("2026-10-30") + timedelta(minutes=5)),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertLess(memory.buckets.get(
            config.ADAPTIVE_BUCKET_NAMES[0]).trades,
            config.ADAPTIVE_MIN_BUCKET_TRADES)
        self.assertIsNone(memory.entry_veto("ABC", band_open("2026-11-02")))

    def test_bucket_veto_fires_at_the_minimum_with_a_losing_expectancy(self):
        rows = [
            trade_row(f"2026-10-{26 + i}", symbol, "SL_FIRST", -0.006,
                      band_open(f"2026-10-{26 + i}") + timedelta(minutes=4))
            for i, symbol in enumerate(("PRL", "KEL", "OGDC"))
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        first_bucket = config.ADAPTIVE_BUCKET_NAMES[0]
        tip = memory.buckets[first_bucket]
        self.assertEqual(tip.trades, 3)
        self.assertLessEqual(tip.expectancy_net,
                             config.ADAPTIVE_MIN_BUCKET_NET)
        veto = memory.entry_veto("OTHER", band_open("2026-11-02")
                                 + timedelta(minutes=2))
        self.assertIsNotNone(veto)
        self.assertIn(first_bucket, veto)
        self.assertIn("-0.60%", veto)

    def test_winners_keep_the_bucket_silent(self):
        rows = [
            trade_row("2026-10-28", "PRL", "TP_FIRST", 0.019,
                      band_open("2026-10-28") + timedelta(minutes=4)),
            trade_row("2026-10-29", "KEL", "SL_FIRST", -0.010,
                      band_open("2026-10-29") + timedelta(minutes=4)),
            trade_row("2026-10-30", "OGDC", "TP_FIRST", 0.019,
                      band_open("2026-10-30") + timedelta(minutes=4)),
        ]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertIsNone(memory.entry_veto("OTHER", band_open("2026-10-31")))

    def test_unstamped_entries_file_themselves_openly(self):
        rows = [trade_row("2026-10-29", "PRL", "SL_FIRST", -0.010)]
        memory = adaptive_memory.AdaptiveMemory.from_rows(rows)
        self.assertEqual(
            memory.buckets.get(adaptive_memory.UNFILED_BUCKET).trades, 1)
        self.assertIsNone(memory.entry_veto("PRL", band_open("2026-11-02")))


class MarketLawTests(unittest.TestCase):
    def test_falling_median_vetoes_a_confirmed_entry(self):
        memory = adaptive_memory.AdaptiveMemory.from_rows([])
        veto = memory.market_veto(-0.001)
        self.assertIsNotNone(veto)
        self.assertIn("direction", veto)

    def test_flat_or_rising_median_stands(self):
        memory = adaptive_memory.AdaptiveMemory.from_rows([])
        self.assertIsNone(memory.market_veto(0.0))
        self.assertIsNone(memory.market_veto(0.002))

    def test_unknown_median_vetoes_nothing(self):
        memory = adaptive_memory.AdaptiveMemory.from_rows([])
        self.assertIsNone(memory.market_veto(None))


class BucketClockTests(unittest.TestCase):
    def test_buckets_read_from_the_band_law_se8(self):
        Monday = "2026-11-02"
        stamp = band_open(Monday) + timedelta(minutes=8)
        self.assertEqual(adaptive_memory.bucket_label(stamp),
                         config.ADAPTIVE_BUCKET_NAMES[0])
        late = band_open(Monday) + timedelta(minutes=12)
        self.assertEqual(adaptive_memory.bucket_label(late),
                         config.ADAPTIVE_BUCKET_NAMES[0])
        outside = band_open(Monday) - timedelta(minutes=30)
        self.assertEqual(adaptive_memory.bucket_label(outside),
                         adaptive_memory.UNFILED_BUCKET)


class PipelineWiringTests(unittest.TestCase):
    def test_the_one_orchestrator_consults_the_memory(self):
        source = (ROOT / "scripts" / "intraday_pipeline.py").read_text(
            encoding="utf-8")
        self.assertIn("adaptive_memory.load_cached", source)
        self.assertIn('entry_veto', source)
        self.assertIn('market_veto', source)
        self.assertIn('"adaptive"', source)

    def test_the_finalize_reads_the_learned_state_into_the_outcome(self):
        source = (ROOT / "scripts" / "intraday_pipeline.py").read_text(
            encoding="utf-8")
        self.assertIn('adaptive_snapshot = adaptive_memory.load_cached('
                      'extra=[record])', source)
        self.assertIn('"adaptive": adaptive_snapshot', source)

    def test_the_memory_never_sleeps_or_waits_on_the_clock(self):
        source = (ROOT / "src" / "signals" / "adaptive_memory.py").read_text(
            encoding="utf-8")
        self.assertNotIn("time.sleep", source)
        # The cache TTL is measured from the process's own monotonic
        # clock, never from a Karachi wall-clock event to wait for.
        self.assertIn("time.monotonic", source)


if __name__ == "__main__":
    unittest.main()
