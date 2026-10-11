"""Acceptance tests for the persisted trade state machine and daily lock.

Owner acceptance list (2026-10-09) covered here:
  TEST 8   the target is exactly +2.0% from the actual entry
  TEST 9   after one trade no second trade can occur that day
  TEST 10  a target hit still keeps the bot online for the rest of the day
  TEST 11  a process restart does not reset the daily trade lock
  TEST 20  LIVE_TRADING_ENABLED stays false
  plus the daily reset and the DATA_BLOCKED allowance rules.

Offline only: state and journal are written to a temporary directory.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals.trade_state import SessionState, State  # noqa: E402

WEDNESDAY = date(2026, 10, 7)
ENTRY_AT = datetime(2026, 10, 7, 10, 0, tzinfo=KARACHI)
LATER = datetime(2026, 10, 7, 10, 45, tzinfo=KARACHI)


class StateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.state_path = Path(self._dir.name) / "session_state.json"
        self.journal_path = Path(self._dir.name) / "session_journal.jsonl"

    def fresh(self) -> SessionState:
        state = SessionState.load(WEDNESDAY, path=self.state_path)
        state.begin_session()
        state.begin_scan()
        return state


class TestDailyLock(StateTestCase):
    def test_entry_records_target_from_actual_entry(self):
        """TEST 8."""
        state = self.fresh()
        state.enter("OGDC", 123.45, ENTRY_AT, 71.5)

        self.assertEqual(state.trades_today, 1)
        self.assertEqual(state.symbol, "OGDC")
        self.assertAlmostEqual(state.target_price, round(123.45 * 1.02, 4), places=4)
        self.assertEqual(state.state, State.TARGET_MONITORING)

    def test_second_entry_is_refused(self):
        """TEST 9: one trade per market day, enforced by the state itself."""
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)

        self.assertFalse(state.can_enter())
        with self.assertRaises(RuntimeError):
            state.enter("PRL", 50.0, LATER, 90.0)
        self.assertEqual(state.trades_today, 1)
        self.assertEqual(state.symbol, "OGDC")

    def test_target_hit_keeps_the_bot_online_but_locked(self):
        """TEST 10."""
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)
        state.mark_target_hit(102.0, LATER)

        self.assertEqual(state.state, State.TARGET_HIT)
        self.assertTrue(state.target_hit)
        self.assertAlmostEqual(state.return_pct, 0.02, places=6)
        self.assertFalse(state.can_enter())
        self.assertTrue(state.locked_for_day())
        # the session is closed out later, still online, still locked
        state.close_day(None, LATER)
        self.assertEqual(state.state, State.DAILY_LOCKED)
        self.assertFalse(state.can_enter())

    def test_restart_does_not_reset_the_lock(self):
        """TEST 11: the daily lock survives a process restart."""
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)
        state.save(self.state_path)

        reloaded = SessionState.load(WEDNESDAY, path=self.state_path)

        self.assertEqual(reloaded.trades_today, 1)
        self.assertEqual(reloaded.symbol, "OGDC")
        self.assertEqual(reloaded.target_price, 102.0)
        self.assertFalse(reloaded.can_enter())

    def test_new_trading_day_resets_but_keeps_history(self):
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)
        state.mark_target_hit(102.0, LATER)
        state.close_day(None, LATER)
        state.save(self.state_path)
        state.append_journal(state.session_record(), self.journal_path)

        thursday = SessionState.load(date(2026, 10, 8), path=self.state_path)

        self.assertEqual(thursday.trades_today, 0)
        self.assertIsNone(thursday.symbol)
        self.assertEqual(thursday.day, "2026-10-08")
        self.assertFalse(thursday.can_enter())   # still MARKET_CLOSED
        thursday.begin_session()
        self.assertTrue(thursday.can_enter())
        thursday.save(self.state_path)
        saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["day"], "2026-10-08")
        self.assertEqual(saved["trades_today"], 0)
        # the finished session is preserved in the append-only journal
        journal = self.journal_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(json.loads(journal[0])["date"], "2026-10-07")


class TestDataBlocked(StateTestCase):
    def test_blocked_data_is_not_a_trade_and_keeps_the_allowance(self):
        state = self.fresh()
        state.block("KMIALL coverage 0/319 (0.0%)", coverage=0.0, scanned=0,
                    expected=319)

        self.assertEqual(state.state, State.DATA_BLOCKED)
        self.assertEqual(state.trades_today, 0)
        self.assertEqual(state.blocked_reason, "KMIALL coverage 0/319 (0.0%)")
        # the day is still open, so a later healthy slot can still trade
        state.begin_session()
        self.assertTrue(state.can_enter())

    def test_a_blocked_day_cannot_erase_a_taken_trade(self):
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)
        state.block("later slot saw no data")

        self.assertEqual(state.state, State.TARGET_MONITORING)
        self.assertEqual(state.trades_today, 1)

    def test_no_trade_reason_is_recorded_without_locking(self):
        state = self.fresh()
        state.no_trade("market not supportive", coverage=0.98, scanned=300,
                       expected=319)

        self.assertEqual(state.state, State.SCANNING)
        self.assertIsNone(state.blocked_reason)
        self.assertEqual(state.symbols_scanned, 300)
        self.assertTrue(state.can_enter())


class TestConfiguration(StateTestCase):
    def test_live_trading_is_disabled_and_paper_is_the_default(self):
        """TEST 20."""
        self.assertFalse(config.live_trading_enabled())
        self.assertFalse(config.LIVE_TRADING_ENABLED)
        self.assertTrue(config.PAPER_TRADING_ENABLED)
        self.assertEqual(config.MAX_TRADES_PER_DAY, 1)

    def test_config_snapshot_is_honest(self):
        snapshot = config.config_snapshot()

        self.assertEqual(snapshot["timezone"], "Asia/Karachi")
        self.assertEqual(snapshot["target_pct"], 2.0)
        self.assertEqual(snapshot["max_trades_per_day"], 1)
        self.assertFalse(snapshot["live_trading_enabled"])
        self.assertEqual(sum(snapshot["score_weights"].values()), 1.0)
        self.assertEqual(snapshot["scanner_version"], config.SCANNER_VERSION)

    def test_session_record_contains_the_required_fields(self):
        state = self.fresh()
        state.enter("OGDC", 100.0, ENTRY_AT, 70.0)
        state.mark_target_hit(102.0, LATER)
        record = state.session_record()

        for field in ("date", "trades_taken", "trade_status", "symbol", "entry",
                      "entry_time", "target", "target_hit", "exit", "exit_time",
                      "return_pct", "scans", "coverage", "scanner_version"):
            self.assertIn(field, record)
        self.assertEqual(record["trade_status"], State.TARGET_HIT)
        self.assertTrue(record["target_hit"])

    def test_journal_is_append_only(self):
        state = self.fresh()
        state.append_journal({"date": "2026-10-07", "outcome": "NO_CANDIDATE"},
                             self.journal_path)
        state.append_journal({"date": "2026-10-08", "outcome": "TARGET_HIT"},
                             self.journal_path)

        lines = self.journal_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["outcome"], "TARGET_HIT")


if __name__ == "__main__":
    unittest.main()
