"""The catch-up backstop: scripts/market_email.py --catch-up.

Owner order 2026-10-23: GitHub's queued crons fired five hours late and
then not at all, so the day's market emails did not go out at all. The
catch-up fire closes that gap: it walks the day's roadmap (the events in
order, derived from the session law alone) and emails only an event
whose own minute passed within the grace window and is still missing
from the ledger.

SO-8: every instant below is Karachi, built through
src/data/sessions.py's own helpers, never a local or naive clock.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.market_email as me  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.data import sessions  # noqa: E402


def pkt(day: str, hh: int, mm: int = 0, ss: int = 0) -> datetime:
    naive = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:{ss:02d}")
    return naive.replace(tzinfo=KARACHI)


DAY = "2026-10-23"  # a two-band Friday


class RoadmapTest(unittest.TestCase):
    def test_friday_roadmap_names_every_event_in_order(self):
        road = me.event_roadmap(pkt(DAY, 16, 30).date())
        self.assertEqual(
            [(event, label) for event, label, _fire in road],
            [
                ("pre", ""),
                ("open", ""),
                ("break", ""),
                ("open", "reopen"),
                ("close", ""),
                ("post", ""),
                ("post-close", ""),
            ])
        # The schedule below is watch-scheduled _that_ day.
        # fmt: off
        self.assertEqual(
            [(fire.hour, fire.minute) for _e, _l, fire in road],
            [(9, 0), (9, 17), (12, 0), (14, 32), (16, 30), (16, 32),
             (16, 49)])
        # fmt: on

    def test_weekday_roadmap_has_no_break_or_reopen(self):
        road = me.event_roadmap(pkt("2026-10-21", 16, 30).date())
        self.assertEqual(
            [(event, label) for event, label, _fire in road],
            [("pre", ""), ("open", ""), ("close", ""), ("post", ""),
             ("post-close", "")])
        self.assertEqual(
            [(fire.hour, fire.minute) for _e, _l, fire in road],
            [(9, 0), (9, 32), (15, 30), (15, 32), (15, 49)])

    def test_weekend_roadmap_is_empty(self):
        self.assertEqual(
            me.event_roadmap(pkt("2026-10-25", 10, 0).date()), [])


class CatchUpTest(unittest.TestCase):
    """catch_up() with an injected sender and an injected ledger read."""

    def _runner(self, now: datetime, ledger: set[str]):
        track: list[str] = []

        def sender(event: str, label: str, day: str) -> bool:
            key = me.ledger_key(event, label, day)
            if key in ledger:
                return False
            ledger.add(key)
            track.append(key)
            return True

        mailed = me.catch_up(now, sender=sender,
                             today_markers=lambda: set(ledger))
        return mailed, track

    def test_reopen_is_caught_up_when_the_cron_never_fired(self):
        # 14:41 PKT: the reopen's minute (14:32) passed nine minutes ago
        # and the ledger holds only the morning's own events.
        morning = {
            "market-pre:2026-10-23",
            "market-open:2026-10-23",
            "market-break:2026-10-23",
        }
        mailed, track = self._runner(pkt(DAY, 14, 41), set(morning))
        # Nothing about the morning is resent and the missing reopen is.
        self.assertEqual(mailed, ["market-open:2026-10-23:reopen"])
        self.assertEqual(track, ["market-open:2026-10-23:reopen"])

    def test_all_in_one_never_reruns_an_event_that_bled(self):
        # 13:45 PKT: the Friday Newsletter's break event at 12:00 within
        # the grace after an empty pre/open/break ledger: nothing was
        # sent, so at 13:45 the break (an hour ago) is past the grace.
        original = me.event_roadmap
        fake = [("break", "", pkt(DAY, 12, 0))]
        me.event_roadmap = lambda day: fake
        try:
            mailed, track = self._runner(pkt(DAY, 13, 45), set())
        finally:
            me.event_roadmap = original
        self.assertEqual(mailed, [])
        self.assertEqual(track, [])

    def test_break_is_caught_up_only_inside_the_grace(self):
        # 12:07 PKT: the break's minute (12:00) passed seven minutes ago
        # and the morning's own events are missing. Everything before
        # the break (pre 09:00, open 09:17) is beyond the grace and the
        # reopen/close/post are still in the day's future.
        mailed, track = self._runner(pkt(DAY, 12, 7), set())
        self.assertEqual(mailed, ["market-break:2026-10-23"])
        self.assertEqual(track, ["market-break:2026-10-23"])

    def test_close_and_post_are_caught_up_in_one_pass(self):
        # 16:35 PKT: the close (16:30) and the post window (16:32) both
        # fall inside the grace, and the day's ledger has nothing.
        mailed, track = self._runner(pkt(DAY, 16, 35), set())
        self.assertEqual(mailed, [
            "market-close:2026-10-23",
            "market-post:2026-10-23",
        ])
        self.assertEqual(track, mailed)

    def test_a_stale_or_future_minute_never_fires(self):
        # 09:05 PKT: only the pre-open (09:00) is inside the grace; the
        # moves after it are still to come and get no early email.
        mailed, track = self._runner(pkt(DAY, 9, 5), set())
        self.assertEqual(mailed, ["market-pre:2026-10-23"])
        self.assertEqual(track, ["market-pre:2026-10-23"])
        # 17:00 PKT: everything is far past the grace, EXCEPT the new
        # post-close event (booked 2026-10-24, fires 16:49): 11 minutes
        # old, it is inside the grace and the run still emails it. A
        # catch-up fire at 20:50 would keep even that silent.
        mailed, track = self._runner(pkt(DAY, 17, 0), set())
        self.assertEqual(mailed, ["market-post-close:2026-10-23"])
        self.assertEqual(track, ["market-post-close:2026-10-23"])
        # 20:50 PKT: every event including post-close is beyond the
        # grace; nothing is sent, not even the events the ledger is
        # missing. This is the 16:30 close that used to email at 20:50.
        mailed, track = self._runner(pkt(DAY, 20, 50), set())
        self.assertEqual(mailed, [])
        self.assertEqual(track, [])

    def test_an_unreadable_ledger_sends_nothing_and_stays_quiet(self):
        def sender(event, label, day):
            raise AssertionError("the sender must not be reached")

        def broken():
            raise RuntimeError("boom")

        mailed = me.catch_up(pkt(DAY, 14, 41), sender=sender,
                             today_markers=broken)
        self.assertEqual(mailed, [])


if __name__ == "__main__":
    unittest.main()
