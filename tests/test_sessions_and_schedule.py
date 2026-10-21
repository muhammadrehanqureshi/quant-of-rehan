"""Offline tests for Karachi-pinned sessions and the notification scheduler."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data import sessions  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI,
    MSG_MARKET_CLOSED,
    MSG_MARKET_OPEN,
    MarketState,
    is_market_open,
    is_scan_window,
    is_trading_day,
    market_state_at,
    next_event,
    post_market_window,
    pre_market_window,
    session_bounds,
)


def at_karachi(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=KARACHI)


class TestKarachiPin(unittest.TestCase):
    def test_zone_is_fixed_utc_plus_five(self):
        self.assertEqual(KARACHI.utcoffset(None), timedelta(hours=5))
        # Karachi never observes DST; summer and winter share the offset.
        jan = datetime(2026, 1, 1, 12, 0, tzinfo=KARACHI)
        jul = datetime(2026, 7, 1, 12, 0, tzinfo=KARACHI)
        self.assertEqual(jan.utcoffset(), jul.utcoffset())

    def test_zone_name(self):
        self.assertEqual(KARACHI.tzname(None), "Asia/Karachi")


class TestSessionLaw(unittest.TestCase):
    def test_monday_open_close_times(self):
        o, c = session_bounds(date(2026, 10, 5))  # Monday
        self.assertEqual((o.hour, o.minute), (9, 32))
        self.assertEqual((c.hour, c.minute), (15, 30))

    def test_friday_open_close_times(self):
        o, c = session_bounds(date(2026, 10, 9))  # Friday
        self.assertEqual((o.hour, o.minute), (9, 17))
        self.assertEqual((c.hour, c.minute), (16, 30))

    def test_sunday_and_saturday_never_trade(self):
        self.assertFalse(is_trading_day(date(2026, 10, 11)))  # Sunday
        self.assertFalse(is_trading_day(date(2026, 10, 10)))  # Saturday
        self.assertFalse(is_market_open(at_karachi(2026, 10, 11, 11, 0)))

    def test_holiday_never_trades(self):
        # 2026-08-14 is on the PSX holiday list (a Friday).
        self.assertFalse(is_trading_day(date(2026, 8, 14)))

    def test_inside_monday_session(self):
        self.assertTrue(is_market_open(at_karachi(2026, 10, 5, 12, 0)))

    def test_before_and_after_open_boundary(self):
        self.assertFalse(is_market_open(at_karachi(2026, 10, 5, 9, 31, 59)))
        self.assertTrue(is_market_open(at_karachi(2026, 10, 5, 9, 32, 0)))
        self.assertFalse(is_market_open(at_karachi(2026, 10, 5, 15, 30, 0)))

    def test_machine_timezone_never_leaks_in(self):
        # Build a "now" in a very different zone; it must map to the same
        # Karachi wall clock as the equivalent Karachi-naive instant.
        nyc_like = timezone(timedelta(hours=-4))
        local = datetime(2026, 10, 5, 3, 32, tzinfo=nyc_like)  # = 11:32 PKT
        self.assertTrue(is_market_open(local))


class TestNextEvent(unittest.TestCase):
    def test_friday_morning_next_is_open_at_0917(self):
        now = at_karachi(2026, 10, 9, 8, 0)
        ev, when = next_event(now)
        self.assertEqual(ev, "OPEN")
        self.assertEqual((when.hour, when.minute), (9, 17))

    def test_monday_mid_session_next_is_close_at_1530(self):
        now = at_karachi(2026, 10, 5, 12, 0)
        ev, when = next_event(now)
        self.assertEqual(ev, "CLOSE")
        self.assertEqual((when.hour, when.minute), (15, 30))

    def test_after_close_next_is_tomorrow_open(self):
        now = at_karachi(2026, 10, 5, 16, 0)   # Monday after close
        ev, when = next_event(now)
        self.assertEqual(ev, "OPEN")
        self.assertEqual(when.date(), date(2026, 10, 6))
        self.assertEqual((when.hour, when.minute), (9, 32))

    def test_holiday_skipped_to_next_trading_day(self):
        now = at_karachi(2026, 8, 14, 8, 0)    # Friday holiday
        ev, when = next_event(now)
        self.assertEqual(ev, "OPEN")
        self.assertEqual(when.date(), date(2026, 8, 17))  # Monday


class TestMarketStateLaw(unittest.TestCase):
    """The owner's four-state law and its strict window edges (2026-10-11).

    Windows are half-open, [start, end), so an instant exactly on a boundary
    belongs to the window that starts there and never to the one ending
    there. Every case below is an edge: the first and last second of each
    window, the exact boundary instant, and the 2-minute gaps.
    """

    MONDAY = date(2026, 10, 12)
    FRIDAY = date(2026, 10, 9)

    def state(self, d, h, mi, s=0, us=0):
        return market_state_at(at_karachi(d.year, d.month, d.day, h, mi, s)
                               + timedelta(microseconds=us))

    def test_monday_to_thursday_timeline(self):
        d = self.MONDAY
        self.assertIs(self.state(d, 8, 59, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 9, 0), MarketState.PRE_MARKET)
        self.assertIs(self.state(d, 9, 14, 59), MarketState.PRE_MARKET)
        # Exactly 09:15:00: pre-market has ended, the market has not opened.
        self.assertIs(self.state(d, 9, 15), MarketState.CLOSED)
        self.assertIs(self.state(d, 9, 31, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 9, 32), MarketState.MARKET)
        self.assertIs(self.state(d, 15, 29, 59), MarketState.MARKET)
        self.assertIs(self.state(d, 15, 30), MarketState.CLOSED)
        self.assertIs(self.state(d, 15, 31, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 15, 32), MarketState.POST_MARKET)
        self.assertIs(self.state(d, 15, 48, 59), MarketState.POST_MARKET)
        self.assertIs(self.state(d, 15, 49), MarketState.CLOSED)
        self.assertIs(self.state(d, 15, 49, 0, 1), MarketState.CLOSED)
        self.assertIs(self.state(d, 23, 59, 59), MarketState.CLOSED)

    def test_friday_has_two_market_windows_and_a_later_post_market(self):
        d = self.FRIDAY
        self.assertIs(self.state(d, 9, 0), MarketState.PRE_MARKET)
        self.assertIs(self.state(d, 9, 15), MarketState.CLOSED)
        self.assertIs(self.state(d, 9, 16, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 9, 17), MarketState.MARKET)
        self.assertIs(self.state(d, 11, 59, 59), MarketState.MARKET)
        self.assertIs(self.state(d, 12, 0), MarketState.CLOSED)
        self.assertIs(self.state(d, 14, 31, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 14, 32), MarketState.MARKET)
        self.assertIs(self.state(d, 16, 29, 59), MarketState.MARKET)
        self.assertIs(self.state(d, 16, 30), MarketState.CLOSED)
        self.assertIs(self.state(d, 16, 31, 59), MarketState.CLOSED)
        self.assertIs(self.state(d, 16, 32), MarketState.POST_MARKET)
        self.assertIs(self.state(d, 16, 48, 59), MarketState.POST_MARKET)
        self.assertIs(self.state(d, 16, 49), MarketState.CLOSED)

    def test_weekend_and_holiday_are_closed_all_day(self):
        for d in (date(2026, 10, 10), date(2026, 10, 11)):
            for hour in range(24):
                self.assertIs(self.state(d, hour, 0), MarketState.CLOSED)
        # 2026-08-14 is on the published PSX holiday list and is a Friday.
        self.assertIs(self.state(date(2026, 8, 14), 11, 0),
                      MarketState.CLOSED)
        self.assertIsNone(pre_market_window(date(2026, 8, 14)))
        self.assertIsNone(post_market_window(date(2026, 8, 14)))

    def test_only_the_market_state_may_be_scanned(self):
        # OWNER 2026-10-21: MARKET scans always; the pre and post windows
        # scan too (live broker feed), and the gaps plus the weekend never do.
        self.assertTrue(is_scan_window(at_karachi(2026, 10, 12, 11, 0)))
        for moment in (at_karachi(2026, 10, 12, 9, 5),
                       at_karachi(2026, 10, 12, 15, 40),
                       at_karachi(2026, 10, 9, 16, 40)):
            self.assertTrue(is_scan_window(moment), moment)
        for moment in (at_karachi(2026, 10, 12, 9, 20),
                       at_karachi(2026, 10, 12, 15, 31),
                       at_karachi(2026, 10, 12, 15, 50),
                       at_karachi(2026, 10, 10, 11, 0)):
            self.assertFalse(is_scan_window(moment), moment)
        self.assertTrue(MarketState.MARKET.is_scan_window)
        self.assertTrue(MarketState.PRE_MARKET.is_scan_window)
        self.assertTrue(MarketState.POST_MARKET.is_scan_window)
        self.assertFalse(MarketState.CLOSED.is_scan_window)

    def test_windows_are_the_owner_windows(self):
        self.assertEqual(pre_market_window(self.MONDAY), ((9, 0), (9, 15)))
        self.assertEqual(pre_market_window(self.FRIDAY), ((9, 0), (9, 15)))
        self.assertEqual(post_market_window(self.MONDAY), ((15, 32), (15, 49)))
        self.assertEqual(post_market_window(self.FRIDAY), ((16, 32), (16, 49)))

    def test_another_zone_is_converted_before_the_decision(self):
        # 04:32 UTC is 09:32 PKT: the Monday open.
        utc = timezone.utc
        self.assertIs(market_state_at(datetime(2026, 10, 12, 4, 32,
                                               tzinfo=utc)),
                      MarketState.MARKET)
        self.assertIs(market_state_at(datetime(2026, 10, 12, 4, 31,
                                               tzinfo=utc)),
                      MarketState.CLOSED)

    def test_a_naive_datetime_is_refused(self):
        with self.assertRaises(ValueError):
            market_state_at(datetime(2026, 10, 12, 9, 32))
        with self.assertRaises(ValueError):
            is_scan_window(datetime(2026, 10, 12, 11, 0))

    def test_a_non_datetime_is_refused(self):
        for bad in ("2026-10-12 09:32", 1234, [2026, 10, 12], None.__class__):
            with self.assertRaises(TypeError, msg=bad):
                market_state_at(bad)

    def test_none_means_now_and_does_not_raise(self):
        self.assertIn(market_state_at(), tuple(MarketState))


class TestOwnerTexts(unittest.TestCase):
    def test_texts_are_exactly_as_ordered(self):
        self.assertEqual(MSG_MARKET_OPEN,
                         "Market is open. Quant is online now.")
        self.assertEqual(MSG_MARKET_CLOSED,
                         "Market is closed. Quant is sleeping now.")


class TestScheduleRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_deliver_journals_and_uses_relay(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "relay_url.txt"), \
             mock.patch.object(sr, "NOTIFY_LOG",
                               Path(self._tmp.name) / "notify_log.jsonl"):
            sr.RELAY_URL_FILE.write_text("https://relay.example/\n")
            with mock.patch.object(sr, "send_via_relay",
                                   return_value=True) as send:
                ok = sr.deliver("OPEN", "open", MSG_MARKET_OPEN)
            self.assertTrue(ok)
            self.assertEqual(send.call_args.args[1], MSG_MARKET_OPEN)
            rec = json.loads(
                sr.NOTIFY_LOG.read_text(encoding="utf-8").splitlines()[-1])
            self.assertTrue(rec["ok"])
            self.assertEqual(rec["event"], "OPEN")

    def test_missing_relay_url_fails_closed(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "absent.txt"), \
             mock.patch.object(sr, "NOTIFY_LOG",
                               Path(self._tmp.name) / "notify_log.jsonl"), \
             _no_relay_env():
            ok = sr.deliver("CLOSE", "close", MSG_MARKET_CLOSED)
        self.assertFalse(ok)

    def test_relay_failure_fails_closed(self):
        from src.notify import schedule_runner as sr
        with mock.patch.object(sr, "RELAY_URL_FILE",
                               Path(self._tmp.name) / "relay_url.txt"), \
             mock.patch.object(sr, "NOTIFY_LOG",
                               Path(self._tmp.name) / "notify_log.jsonl"):
            sr.RELAY_URL_FILE.write_text("https://relay.example/\n")
            with mock.patch.object(sr, "send_via_relay", return_value=False):
                ok = sr.deliver("OPEN", "open", MSG_MARKET_OPEN)
        self.assertFalse(ok)


def _no_relay_env():
    """An environment with RELAY_URL absent, so the file alone decides.

    The notification path reads the relay URL from the environment first, so
    a test that means to exercise the file path has to say so out loud
    instead of inheriting whatever the shell happens to export.
    """
    env = {k: v for k, v in os.environ.items() if k != "RELAY_URL"}
    return mock.patch.dict(os.environ, env, clear=True)


if __name__ == "__main__":
    unittest.main()
