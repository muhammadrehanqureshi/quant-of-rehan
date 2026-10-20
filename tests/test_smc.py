"""Causal ICT/SMC acceptance tests, synthetic fixtures are not market evidence."""
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch

from src import config
from src.data.sessions import KARACHI
from src.signals import momentum_scanner as scanner
from src.signals import smc
from src.signals.trade_state import SessionState
from scripts.intraday_pipeline import monitor_exit, session_close_price
from src.research import session_history
from smc_fixture import setup_rows

OPEN = datetime(2026, 10, 7, 9, 32, tzinfo=KARACHI)


class SmcTest(unittest.TestCase):
    def session(self, rows=None, minutes=43):
        rows = rows if rows is not None else setup_rows(scanner, OPEN)
        return scanner.SessionData(OPEN.date(), OPEN + timedelta(minutes=minutes),
                                   {"OGDC": rows}, True, len(rows), 0, 0)

    def test_complete_sequence_returns_a_long_with_structural_stop(self):
        session = self.session()
        result = scanner.select_one(session, scanner.assess_quality(session, ["OGDC"]))
        self.assertEqual(result.status, scanner.TRADE, result.reason)
        row = result.candidate
        self.assertEqual(row["side"], "LONG")
        self.assertEqual(row["strategy"], config.SCANNER_VERSION)
        self.assertAlmostEqual(row["stop_loss"], 99.69)
        self.assertAlmostEqual(row["target"], 102.357)
        self.assertGreaterEqual(row["net_reward_risk"], config.SMC_MIN_NET_RR)
        self.assertGreater(row["setup"]["overhead_liquidity"], row["target"])
        self.assertIn("Stop Loss: 99.6900", scanner.signal_message(
            row, result.market, row["price"]["last"], session.as_of))

    def test_monotone_momentum_without_a_sweep_cannot_trade(self):
        rows = [scanner.MinuteBar(OPEN + timedelta(minutes=i), 100+i*.1,
                                  100.1+i*.1, 99.9+i*.1, 100+i*.1, 50000)
                for i in range(43)]
        self.assertIsNone(scanner.score_symbol("OGDC", rows, self.session(rows)))

    def test_no_entry_until_retest_completes(self):
        all_rows = setup_rows(scanner, OPEN)
        for minutes in (39, 40, 41, 42):
            session = self.session(all_rows, minutes)
            self.assertIsNone(scanner.score_symbol("OGDC", all_rows, session), minutes)
        session = self.session(all_rows, 43)
        self.assertIsNotNone(scanner.score_symbol("OGDC", all_rows, session))
        session.as_of -= timedelta(seconds=1)
        self.assertIsNone(scanner.score_symbol("OGDC", all_rows, session))

    def test_appending_future_prices_cannot_change_the_decision(self):
        short = self.session()
        extended = self.session(setup_rows(scanner, OPEN, 90))
        self.assertEqual(scanner.rank_candidates(short), scanner.rank_candidates(extended))

    def test_pivots_need_both_right_bars(self):
        rows = setup_rows(scanner, OPEN)
        self.assertNotIn(30, smc.confirmed_swings(rows, 32, high=False))
        self.assertIn(30, smc.confirmed_swings(rows, 33, high=False))

    def test_each_missing_confluence_refuses_entry(self):
        changes = {
            "no sweep": (39, dict(low=99.85)),
            "no reclaim": (39, dict(close=99.75)),
            "no displacement": (40, dict(close=100.1)),
            "no volume confirmation": (40, dict(volume=1000)),
            "no gap": (41, dict(low=100.15)),
            "no retest": (42, dict(low=100.7, open=100.75, close=100.8)),
            "no bullish retest": (42, dict(open=100.6)),
            "structural failure": (42, dict(low=99.6)),
        }
        for label, (index, values) in changes.items():
            with self.subTest(label=label):
                rows = setup_rows(scanner, OPEN)
                rows[index] = replace(rows[index], **values)
                self.assertIsNone(scanner.score_symbol("OGDC", rows, self.session(rows)))

    def test_target_room_and_risk_cannot_be_bypassed(self):
        rows = setup_rows(scanner, OPEN)
        rows[4] = replace(rows[4], high=102)
        self.assertIsNone(scanner.score_symbol("OGDC", rows, self.session(rows)))
        with patch.object(config, "SMC_MIN_NET_RR", 10):
            session = self.session()
            self.assertIsNone(scanner.score_symbol("OGDC", session.bars["OGDC"], session))

    def test_stale_holes_etfs_and_friday_break_refuse(self):
        session = self.session(minutes=45)
        self.assertIsNone(scanner.rank_candidates(session) or None)
        session = self.session()
        self.assertIsNone(scanner.score_symbol("MIIETF", session.bars["OGDC"], session))
        del session.bars["OGDC"][38]
        self.assertEqual(scanner.rank_candidates(session), [])
        friday = datetime(2026, 10, 9, 14, 32, tzinfo=KARACHI)
        old = setup_rows(scanner, friday - timedelta(hours=4))
        session = scanner.SessionData(friday.date(), friday + timedelta(minutes=2),
                                      {"OGDC": old}, True, len(old), 0, 0)
        self.assertEqual(scanner.rank_candidates(session), [])

    def test_first_mitigation_is_not_replayed(self):
        rows = setup_rows(scanner, OPEN)
        rows.append(replace(rows[-1], timestamp=OPEN + timedelta(minutes=43)))
        self.assertIsNone(scanner.score_symbol("OGDC", rows, self.session(rows, 44)))

    def test_no_entry_in_last_thirty_minutes_or_without_volume(self):
        session = self.session()
        session.as_of = OPEN.replace(hour=15, minute=10)
        self.assertEqual(scanner.rank_candidates(session), [])
        rows = [replace(b, volume=None) for b in setup_rows(scanner, OPEN)]
        self.assertIsNone(scanner.score_symbol("OGDC", rows, self.session(rows)))

    def test_market_veto_is_causal_and_does_not_hide_selloffs(self):
        session = self.session()
        quality = scanner.assess_quality(session, ["OGDC"])
        plain = scanner.select_one(session, quality)
        session.bars["OGDC"].append(scanner.MinuteBar(
            OPEN + timedelta(minutes=90), 100, 100, 50, 50, 50000))
        self.assertEqual(scanner.select_one(session, quality).candidate, plain.candidate)
        for i in range(4):
            session.bars[f"SYM{i}"] = [replace(b, close=98, open=100, high=101, low=97)
                                          for b in setup_rows(scanner, OPEN)]
        result = scanner.select_one(session, quality)
        self.assertEqual(result.status, scanner.NO_TRADE)
        self.assertIsNone(result.candidate)
        self.assertEqual(result.market["status"], "SELLOFF")

    def test_ai_cannot_change_smc_selection(self):
        session = self.session()
        quality = scanner.assess_quality(session, ["OGDC"])
        plain = scanner.select_one(session, quality)
        prior = scanner.select_one(session, quality, {"OGDC": 0.0}, {"active": True})
        self.assertEqual(plain.candidate, prior.candidate)
        self.assertFalse(prior.market["ai"]["active"])


class ExitTest(unittest.TestCase):
    def state(self):
        state = SessionState(OPEN.date().isoformat())
        state.begin_session()
        state.enter("OGDC", 100, OPEN + timedelta(minutes=43), 80, stop_loss=99)
        return state

    def session(self, bar):
        return scanner.SessionData(OPEN.date(), bar.timestamp + timedelta(minutes=1),
                                   {"OGDC": [bar]}, True, 1, 0, 0)

    def test_stop_first_on_ambiguous_bar_and_daily_lock_stays(self):
        state = self.state()
        bar = scanner.MinuteBar(OPEN + timedelta(minutes=43), 100, 103, 98, 101, 5000)
        event = monitor_exit(state, self.session(bar))
        self.assertEqual(event[0], "STOP_AMBIGUOUS")
        self.assertEqual(state.exit_price, 99)
        self.assertFalse(state.target_hit)
        self.assertFalse(state.can_enter())
        self.assertEqual(state.trades_today, 1)

    def test_stop_gap_is_not_filled_at_a_better_price(self):
        state = self.state()
        bar = scanner.MinuteBar(OPEN + timedelta(minutes=43), 98, 100, 97, 99, 5000)
        monitor_exit(state, self.session(bar))
        self.assertEqual(state.exit_price, 98)

    def test_target_uses_reference_not_touching_bar_close(self):
        state = self.state()
        bar = scanner.MinuteBar(OPEN + timedelta(minutes=43), 100, 103, 99.5, 100.1, 5000)
        monitor_exit(state, self.session(bar))
        self.assertEqual(state.exit_price, 102)
        self.assertAlmostEqual(state.return_pct, .02)

    def test_stop_outcomes_remain_losses_in_the_research_gate(self):
        for outcome, label in (("STOP_HIT", "SL_FIRST"), ("STOP_AMBIGUOUS", "SL_AMBIG")):
            row = session_history._normalise({
                "date": OPEN.date().isoformat(), "symbol": "OGDC", "entry": 100,
                "outcome": outcome, "gross_return": -.01, "net_return": -.01648,
                "scanner_version": config.SCANNER_VERSION})
            self.assertEqual(row["label"], label)
            self.assertLess(row["net_return"], 0)

    def test_stale_symbol_cannot_be_valued_at_the_session_close(self):
        bar = scanner.MinuteBar(OPEN.replace(hour=15, minute=20), 100, 100, 100, 100, 5000)
        session = self.session(bar)
        session.as_of = OPEN.replace(hour=15, minute=31)
        self.assertIsNone(session_close_price(session, "OGDC"))
        session.bars["OGDC"] = [replace(bar, timestamp=OPEN.replace(hour=15, minute=29))]
        self.assertEqual(session_close_price(session, "OGDC"), 100)

    def test_structural_stop_persists_without_resetting_the_daily_lock(self):
        import tempfile
        from pathlib import Path

        state = self.state()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state.save(path)
            restored = SessionState.load(OPEN.date(), path)
        self.assertEqual(restored.stop_loss, 99)
        self.assertFalse(restored.can_enter())
        restored.mark_stop_hit(99, OPEN + timedelta(minutes=44))
        self.assertEqual(restored.session_record()["exit_reason"], "STOP_HIT")
        self.assertFalse(restored.can_enter())

    def test_entry_minute_before_signal_cannot_hit_a_target(self):
        state = self.state()
        bar = scanner.MinuteBar(OPEN + timedelta(minutes=42), 100, 103, 98, 100, 5000)
        self.assertIsNone(monitor_exit(state, self.session(bar)))
