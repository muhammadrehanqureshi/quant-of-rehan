"""Offline tests for Karachi-pinned sessions and the notification scheduler."""

from __future__ import annotations

import json
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
    is_market_open,
    is_trading_day,
    next_event,
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


class TestOwnerTexts(unittest.TestCase):
    def test_texts_are_exactly_as_ordered(self):
        self.assertEqual(MSG_MARKET_OPEN,
                         "Quant is online now.")
        self.assertEqual(MSG_MARKET_CLOSED,
                         "Quant is sleeping now.")


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
                               Path(self._tmp.name) / "notify_log.jsonl"):
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


if __name__ == "__main__":
    unittest.main()
