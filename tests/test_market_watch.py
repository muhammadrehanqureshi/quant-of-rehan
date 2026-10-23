"""The market event emails ride the session loop's own phase table.

Owner order 2026-10-23: the Friday break email never arrived because
GitHub's scheduled fires were silent on that day (the run history shows
zero schedule events for the whole repository, and the previous day's
fires landed five hours late). The band loop is the one worker that is
alive at every event minute, so it sends the emails now, from
src/notify/market_watch.py, with the ledger keeping each one exactly
once. These tests pin the mapping from the session law's own phases and
states to the owner's five events, and the facts a stalled cron can no
longer break: one attempt per edge, the reopen label for the Friday
second band, no attempt without a session, and a failed send that never
raises into the scan.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from src.data.sessions import KARACHI
from src.notify.market_watch import (
    EVENT_TEXTS,
    MarketEventWatcher,
    event_for,
    ledger_key,
)


def pkt(hour: int, minute: int = 0, day="2026-10-23") -> datetime:
    """An aware Karachi instant (2026-10-23 is a Friday; 26th a Monday)."""
    return datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00") \
        .replace(tzinfo=KARACHI)


class EventMappingTest(unittest.TestCase):
    """Phase and state pairs map to the owner's five events, or None."""

    def test_the_five_events_map_from_the_session_law_itself(self):
        friday = "2026-10-23"
        cases = [
            ("pre", pkt(9, 0, friday)),          # PRE_MARKET begins
            ("open", pkt(9, 17, friday)),         # band 1 opens
            ("break", pkt(12, 1, friday)),        # the midday break
            ("open", pkt(14, 32, friday)),        # band 2 opens (reopen)
            ("close", pkt(16, 30, friday)),       # the last close
            ("post", pkt(16, 32, friday)),        # POST_MARKET begins
        ]
        from src.data.sessions import market_phase, market_state_at
        for event, moment in cases:
            with self.subTest(event=event, at=moment.isoformat()):
                pair = (market_phase(moment).value,
                        market_state_at(moment).value)
                entry = event_for(pair, moment)
                self.assertIsNotNone(entry)
                self.assertEqual(entry[0], event)

    def test_the_friday_second_band_opens_as_reopen(self):
        from src.data.sessions import market_phase, market_state_at
        for (event, label), moment in (
            (("open", ""), pkt(9, 17)),         # band 1: no label
            (("open", "reopen"), pkt(14, 32)),  # band 2: the reopen label
        ):
            with self.subTest(event=event, at=moment.isoformat()):
                pair = (market_phase(moment).value,
                        market_state_at(moment).value)
                self.assertEqual(event_for(pair, moment), (event, label))

    def test_monday_thursday_carries_no_reopen_label(self):
        from src.data.sessions import market_phase, market_state_at
        monday = pkt(9, 32, day="2026-10-26")
        pair = (market_phase(monday).value, market_state_at(monday).value)
        self.assertEqual(event_for(pair, monday), ("open", ""))

    def test_no_event_without_a_session(self):
        from src.data.sessions import market_phase, market_state_at
        saturday = pkt(10, 0, day="2026-10-24")
        pair = (market_phase(saturday).value, market_state_at(saturday).value)
        self.assertIsNone(event_for(pair, saturday))

    def test_the_morning_gap_is_silent(self):
        # 09:15 to 09:32 on a Monday is CLOSED and never emailed: the
        # break text belongs to the Friday midday break alone.
        from src.data.sessions import market_phase, market_state_at
        gap = pkt(9, 20, day="2026-10-26")
        pair = (market_phase(gap).value, market_state_at(gap).value)
        self.assertIsNone(event_for(pair, gap))

    def test_the_texts_are_the_owner_booked_sentences(self):
        self.assertEqual(EVENT_TEXTS["open"],
                         "Market is open. Quant is online now.")
        self.assertEqual(EVENT_TEXTS["break"],
                         "Market is on a break. Quant is sleeping until "
                         "the market reopens.")
        self.assertEqual(EVENT_TEXTS["close"],
                         "Market is closed. Quant is sleeping now.")


class WatcherTest(unittest.TestCase):
    """One attempt per edge; the ledger keys carry the day and label."""

    def setUp(self):
        self.sent: list[tuple[str, str, str]] = []

    def sender(self, event, label, day):
        self.sent.append((event, label, day))
        return True

    def test_a_phase_edge_sends_exactly_once(self):
        watcher = MarketEventWatcher(sender=self.sender)
        mailed = watcher.observe(pkt(12, 1))
        self.assertEqual(mailed, ["market-break:2026-10-23"])
        self.assertEqual(self.sent, [("break", "", "2026-10-23")])
        # The same phase held again one second later is not another edge.
        self.assertEqual(watcher.observe(pkt(12, 1)), [])

    def test_a_restart_inside_the_same_phase_does_not_reattempt(self):
        watcher = MarketEventWatcher(sender=self.sender)
        watcher.observe(pkt(12, 1))
        again = MarketEventWatcher(sender=self.sender)
        # A fresh watcher (a new band job) attempts once: the ledger, not
        # the watcher, refuses the duplicate.
        again.observe(pkt(12, 2))
        self.assertEqual(self.sent[-1][0], "break")

    def test_a_failed_send_never_raises(self):
        def breaker(event, label, day):
            raise RuntimeError("503 from the GitHub API")

        watcher = MarketEventWatcher(sender=breaker)
        self.assertEqual(watcher.observe(pkt(12, 1)), [])

    def test_a_failed_send_is_retried_inside_the_phase(self):
        # Owner order 2026-10-23: the break edge fired while the relay
        # was down and the send was dropped with it, so the phase stayed
        # silent for the rest of the break. A failed attempt now books a
        # retry two minutes out and lands it while the phase holds.
        holder = {"now": pkt(12, 1)}
        outcomes = [RuntimeError("503 from the GitHub API"), True]

        def flaky(event, label, day):
            step = outcomes.pop(0)
            if isinstance(step, Exception):
                raise step
            self.sent.append((event, label, day))
            return True

        watcher = MarketEventWatcher(sender=flaky,
                                     clock=lambda: holder["now"])
        self.assertEqual(watcher.observe(), [])
        self.assertEqual(self.sent, [])
        holder["now"] = pkt(12, 2)  # before the retry window: silent
        self.assertEqual(watcher.observe(), [])
        self.assertEqual(self.sent, [])
        holder["now"] = pkt(12, 4)  # the retry fires and lands
        self.assertEqual(watcher.observe(), ["market-break:2026-10-23"])
        self.assertEqual(self.sent, [("break", "", "2026-10-23")])

    def test_the_retry_stops_when_the_ledger_says_delivered(self):
        # A False send means the ledger already carries the marker (another
        # path emailed it): the event is out, so no retry is ever booked.
        holder = {"now": pkt(12, 1)}

        def delivered(event, label, day):
            return False

        watcher = MarketEventWatcher(sender=delivered,
                                     clock=lambda: holder["now"])
        self.assertEqual(watcher.observe(), [])
        holder["now"] = pkt(12, 30)  # deep into the phase
        self.assertEqual(watcher.observe(), [])

    def test_the_ledger_key_carries_the_label(self):
        self.assertEqual(ledger_key("open", "", "2026-10-23"),
                         "market-open:2026-10-23")
        self.assertEqual(ledger_key("open", "reopen", "2026-10-23"),
                         "market-open:2026-10-23:reopen")


class ScanLoopPassengerTest(unittest.TestCase):
    """The loop calls the watcher on every cycle, whatever it decides.

    A cycle that waits through a break still observes it: a 'wait' is a
    phase the owner is emailed about, not a silence.
    """

    def test_the_loop_passes_the_watcher_its_moment(self):
        import sys
        ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(ROOT / "scripts"))
        from scan_loop import LoopConfig, ScanLoop

        observed = []

        class Recorder:
            def observe(self, moment):
                observed.append(moment)

        loop = ScanLoop(LoopConfig(dry_run=True))
        loop.market_events = Recorder()
        moment = pkt(12, 1)
        loop.run_decided("wait", "12:00", moment)
        self.assertEqual(observed, [moment])


if __name__ == "__main__":
    unittest.main()
