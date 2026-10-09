"""Acceptance tests for the schedule layer of the rebuild.

Owner acceptance list (2026-10-09) covered here:
  TEST 12  Monday-Thursday open state begins at 09:32 Asia/Karachi
  TEST 13  Friday open state begins at 09:17 Asia/Karachi
  TEST 14  Monday-Thursday close state begins at 15:30 Asia/Karachi
  TEST 15  Friday close state begins at 16:30 Asia/Karachi
  TEST 16  the open/close texts are the owner's exact words, one per edge
  TEST 17  every GitHub Actions cron lands inside the session (scan) or
           strictly after the close (finalize) once converted to PKT
  TEST 18  every Cloudflare cron matches a session edge exactly
  TEST 19  the scanner refuses to run outside the configured session

Parsing the two schedule files is deliberate: a cron string that is merely
present is not evidence that the timings are right.
"""

from __future__ import annotations

import re
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import (  # noqa: E402
    KARACHI, MSG_MARKET_CLOSED, MSG_MARKET_OPEN, close_time, is_market_open,
    open_time,
)
from scripts.intraday_pipeline import session_legal  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "intraday-capture.yml"
WRANGLER = ROOT / "cloud" / "wrangler.toml"

MONDAY = date(2026, 10, 5)
TUESDAY = date(2026, 10, 6)
WEDNESDAY = date(2026, 10, 7)
THURSDAY = date(2026, 10, 8)
FRIDAY = date(2026, 10, 9)


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KARACHI)


def crons_of(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    found = re.findall(r'cron:\s*"([^"]+)"', text)
    if found:
        return found
    # wrangler.toml declares crons as a plain array of quoted strings
    block = re.search(r"crons\s*=\s*\[(.*?)\]", text, re.DOTALL)
    return re.findall(r'"([^"]+)"', block.group(1)) if block else []


def parse_cron(expression: str) -> tuple[int, int, str]:
    minute, hour, _dom, _month, weekday = expression.split()
    return int(minute), int(hour), weekday


def weekdays_of(mask: str) -> list[int]:
    out: set[int] = set()
    for part in mask.split(","):
        if "-" in part:
            start, end = (int(value) for value in part.split("-"))
            out.update(range(start, end + 1))
        else:
            out.add(int(part))
    return sorted(out)


class TestSessionBoundaries(unittest.TestCase):
    def test_monday_to_thursday_boundaries(self):
        """TEST 12 and TEST 14."""
        for day in (MONDAY, TUESDAY, WEDNESDAY, THURSDAY):
            with self.subTest(day=day.isoformat()):
                self.assertEqual(open_time(day), (9, 32))
                self.assertEqual(close_time(day), (15, 30))
                self.assertFalse(is_market_open(at(day, 9, 31)))
                self.assertTrue(is_market_open(at(day, 9, 32)))
                self.assertTrue(is_market_open(at(day, 15, 29)))
                self.assertFalse(is_market_open(at(day, 15, 30)))

    def test_friday_boundaries(self):
        """TEST 13 and TEST 15."""
        self.assertEqual(open_time(FRIDAY), (9, 17))
        self.assertEqual(close_time(FRIDAY), (16, 30))
        self.assertFalse(is_market_open(at(FRIDAY, 9, 16)))
        self.assertTrue(is_market_open(at(FRIDAY, 9, 17)))
        self.assertTrue(is_market_open(at(FRIDAY, 16, 29)))
        self.assertFalse(is_market_open(at(FRIDAY, 16, 30)))

    def test_weekend_is_never_a_session(self):
        saturday = date(2026, 10, 10)
        self.assertFalse(is_market_open(at(saturday, 11, 0)))

    def test_owner_texts_are_exact(self):
        """TEST 16: the words are the owner's law and are never reworded."""
        self.assertEqual(MSG_MARKET_OPEN, "Market is open. Quant is online now.")
        self.assertEqual(MSG_MARKET_CLOSED, "Market is closed. Quant is sleeping now.")


class TestOutsideSessionGuard(unittest.TestCase):
    def test_scanner_refuses_outside_the_session(self):
        """TEST 19."""
        self.assertTrue(session_legal(at(WEDNESDAY, 10, 0)))
        self.assertTrue(session_legal(at(FRIDAY, 16, 0)))
        self.assertFalse(session_legal(at(WEDNESDAY, 9, 0)))
        self.assertFalse(session_legal(at(WEDNESDAY, 16, 0)))
        self.assertFalse(session_legal(at(FRIDAY, 16, 45)))
        self.assertFalse(session_legal(at(date(2026, 10, 10), 11, 0)))


class TestGitHubActionsSchedule(unittest.TestCase):
    def test_every_cron_is_inside_a_session_or_after_the_close(self):
        """TEST 17: cron is UTC; the converted PKT time must be legal."""
        crons = crons_of(WORKFLOW)
        self.assertGreaterEqual(len(crons), 5, "the scan cadence went missing")
        for expression in crons:
            minute, hour, mask = parse_cron(expression)
            for weekday in weekdays_of(mask):
                pkt = datetime(2026, 10, 5, hour, minute, tzinfo=KARACHI) \
                    + timedelta(hours=5, days=weekday - 1)
                day = pkt.date()
                open_hm, close_hm = open_time(day), close_time(day)
                inside = open_hm <= (pkt.hour, pkt.minute) <= close_hm
                after_close = (pkt.hour, pkt.minute) > close_hm
                with self.subTest(cron=expression, weekday=weekday,
                                  pkt=pkt.strftime("%H:%M")):
                    self.assertTrue(
                        inside or after_close,
                        f"{expression} lands at {pkt:%H:%M} PKT on "
                        f"{day.isoformat()}, which is before the "
                        f"{open_hm[0]:02d}:{open_hm[1]:02d} open")

    def test_scan_slots_appear_inside_both_sessions(self):
        crons = crons_of(WORKFLOW)
        converted = {parse_cron(expression)[:2] for expression in crons}
        monday_slots = {(hour + 5 or 24, minute) for minute, hour in converted}
        self.assertTrue(any((9, 32) <= slot <= (15, 30) for slot in monday_slots),
                        "no weekday in-session scan slot")
        self.assertTrue(any((9, 17) <= slot <= (16, 30) for slot in monday_slots),
                        "no Friday in-session scan slot")

    def test_finalize_slot_is_after_every_close(self):
        """The post-close job must not start while the market is still open."""
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("--finalize", text)
        for expression in crons_of(WORKFLOW):
            minute, hour, mask = parse_cron(expression)
            for weekday in weekdays_of(mask):
                pkt = datetime(2026, 10, 5, hour, minute, tzinfo=KARACHI) \
                    + timedelta(hours=5, days=weekday - 1)
                if f'"{expression}") FINALIZE=' in text:
                    close_hm = close_time(pkt.date())
                    with self.subTest(cron=expression):
                        self.assertGreater((pkt.hour, pkt.minute), close_hm)

    def test_concurrency_and_artifacts_are_declared(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("concurrency:", text)
        self.assertIn("group: intraday-momentum", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("upload-artifact", text)

    def test_workflow_runs_the_single_scanner(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/intraday_pipeline.py", text)
        self.assertNotIn("intraday_engine", text)


class TestCloudflareSchedule(unittest.TestCase):
    def test_worker_crons_match_the_session_edges_exactly(self):
        """TEST 18: one authoritative clock, the worker included."""
        crons = crons_of(WRANGLER)
        edges = []
        for weekday, (open_hm, close_hm) in (
            (range(1, 5), ((9, 32), (15, 30))),
            ((5,), ((9, 17), (16, 30))),
        ):
            for hour_minute in (open_hm, close_hm):
                converted = ((hour_minute[0] - 5) % 24, hour_minute[1])
                edges.append((converted, weekday, hour_minute))
        self.assertEqual(len(crons), 4, "the worker must fire exactly four edges")
        for converted, weekday, hour_minute in edges:
            minute, hour, mask = parse_cron(
                next(expression for expression in crons
                     if parse_cron(expression)[0] == converted[1]
                     and parse_cron(expression)[1] == converted[0]))
            with self.subTest(edge=hour_minute):
                self.assertEqual((hour, minute), converted)
                self.assertTrue(set(weekdays_of(mask)) == set(weekday))


if __name__ == "__main__":
    unittest.main()
