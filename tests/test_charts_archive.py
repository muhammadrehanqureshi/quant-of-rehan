"""The durable archive and any-day tape serving, held to their promises.

The point of these tests is the thing the owner asked for: Charts of Rehan has
to work at his convenience, not only while the exchange is open. That means a
finished session is stored once, precisely, and read back later without a
recorder running. So what is checked here is:

  * a stored session reads back bar for bar, with the venue's volume
    semantics, the print count and the carried flag intact;
  * every stored bar can be traced to the capture file it came from, by name,
    size, mtime and hash, and the archive can prove its own files are unaltered;
  * a manifest that recorded nothing for a tape that is not empty is a defect
    and is rebuilt rather than trusted;
  * a symbol the tape never printed has no file at all, which is the honest
    shape of "there is no data" (SO-3).

Nothing here touches the network, the owner's real capture directory or the
wall clock: every capture is a temporary file written in the venue's own row
shape, and every clock is pinned to a fixed mid-session Monday.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data import tape_bars  # noqa: E402

from charts.archive import (  # noqa: E402
    CAPTURE_DIR_ENV, DEFAULT_CAPTURE_DIRS, SIBLING_CAPTURE_DIR, SessionArchive,
    capture_candidates, discover_capture_dirs, identify,
)
from charts.adapters.tape import (  # noqa: E402
    TapeSource, _symbols_from, read_universe,
)
from charts.ratelimit import UpstreamError  # noqa: E402

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY = date(2026, 10, 12)
MONDAY_OPEN = datetime(2026, 10, 12, 9, 32, tzinfo=KARACHI)
MONDAY_1100 = datetime(2026, 10, 12, 11, 0, tzinfo=KARACHI)
TUESDAY_OPEN = datetime(2026, 10, 13, 9, 32, tzinfo=KARACHI)
TUESDAY_1100 = datetime(2026, 10, 13, 11, 0, tzinfo=KARACHI)
WEDNESDAY_1100 = datetime(2026, 10, 14, 11, 0, tzinfo=KARACHI)


def tick(symbol: str, price, volume, at: datetime,
         tick_time: str | None = None) -> dict:
    """One MKT-FEED row in the shape the recorder banks."""
    return {"scrip": f"{symbol}:REG", "last": "" if price is None else str(price),
            "volume": None if volume is None else str(volume),
            "tick_time": tick_time or f"{at:%H:%M:%S}"}


def frame(at: datetime, *rows: dict) -> dict:
    return {"kind": "MKT-FEED*x", "ts": at.isoformat(), "ticks": list(rows)}


def session_records(symbols: tuple[str, ...] = ("OGDC", "PPL"),
                    minutes: int = 3, start: datetime = MONDAY_OPEN) -> list[dict]:
    """A small session: `minutes` one-minute bars for each symbol.

    Volume is the venue's own running counter, rising by 100 shares a minute,
    which is what makes the stored volume semantics checkable.
    """
    records: list[dict] = []
    for index in range(minutes):
        moment = start + timedelta(minutes=index + 1)
        rows = []
        for position, symbol in enumerate(symbols):
            price = 100.0 + index + position
            rows.append(tick(symbol, price, 1000 * (index + 1),
                             moment, f"{moment:%H:%M:05d}"))
        records.append(frame(moment + timedelta(seconds=10), *rows))
    return records


class ArchiveCase(unittest.TestCase):
    """A temporary capture directory, a temporary archive, a pinned clock."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="charts-archive-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.captures = self.tmp / "captures"
        self.captures.mkdir()
        self.archive_dir = self.tmp / "archive"
        self.capture = self.captures / "capture_20261012.ndjson"
        self.universe = self.tmp / "universe.json"
        self.universe.write_text(json.dumps(["OGDC", "PPL"]), encoding="utf-8")

    # ------------------------------------------------------------- helpers
    def write_tape(self, records: list[dict] | None = None,
                   path: Path | None = None) -> Path:
        target = path or self.capture
        target.write_text(
            "\n".join(json.dumps(record) for record in records
                      if record is not None) + "\n", encoding="utf-8")
        return target

    def build(self, day: date = MONDAY, as_of: datetime = MONDAY_1100):
        """A real TapeBars for the temporary capture, via the one builder."""
        return tape_bars.build(self.capture, ["OGDC", "PPL"], as_of, day=day)

    def archive(self) -> SessionArchive:
        return SessionArchive(self.archive_dir)

    def source(self, clock: datetime = MONDAY_1100, **kwargs) -> TapeSource:
        fields = dict(clock=lambda: clock, universe_path=self.universe,
                      capture_dirs=(self.captures,),
                      archive_dir=self.archive_dir)
        fields.update(kwargs)
        return TapeSource(**fields)

    def patched_capture(self):
        """Point the builder's canonical name at this test's capture file."""
        return mock.patch("src.data.tape_bars.capture_path",
                          side_effect=lambda day: (
                              self.capture if day == MONDAY
                              else self.captures / f"capture_{day:%Y%m%d}.ndjson"))


class IdentifyTest(ArchiveCase):

    def test_identity_names_the_file_and_hashes_its_bytes(self):
        self.write_tape(session_records())
        facts = identify(self.capture)
        self.assertEqual(facts["name"], "capture_20261012.ndjson")
        self.assertEqual(facts["bytes"], self.capture.stat().st_size)
        self.assertEqual(facts["mtime_ns"], self.capture.stat().st_mtime_ns)
        self.assertEqual(len(facts["sha256"]), 64)
        self.assertEqual(identify(self.capture)["sha256"], facts["sha256"])

    def test_a_changed_file_has_a_changed_hash(self):
        self.write_tape(session_records())
        before = identify(self.capture)["sha256"]
        self.write_tape(session_records(minutes=4))
        self.assertNotEqual(identify(self.capture)["sha256"], before)

    def test_hashing_can_be_skipped_and_says_so(self):
        self.write_tape(session_records())
        self.assertEqual(identify(self.capture, hash_file=False)["sha256"], "")


class CaptureLookupTest(ArchiveCase):

    def test_the_configured_directories_are_searched_then_the_builder(self):
        elsewhere = self.tmp / "second"
        elsewhere.mkdir()
        for directory in (elsewhere, self.captures):
            (directory / self.capture.name).write_text("{}\n", encoding="utf-8")
        with self.patched_capture():
            found = capture_candidates(MONDAY, (elsewhere, self.captures))
        # A caller that names its directories gets exactly those files in
        # that order; the builder's own location is the last candidate, so
        # repository-local history can never stand in for an explicitly
        # named recording directory.
        self.assertEqual([path.parent for path in found],
                         [elsewhere, self.captures])

    def test_a_day_with_no_file_anywhere_is_an_empty_list(self):
        with self.patched_capture():
            self.assertEqual(capture_candidates(MONDAY, (self.captures,)), [])

    def test_discovery_puts_the_environment_directory_first(self):
        with mock.patch.dict("os.environ", {CAPTURE_DIR_ENV: str(self.tmp)}):
            found = discover_capture_dirs()
        self.assertEqual(found[0], self.tmp)
        for own in DEFAULT_CAPTURE_DIRS:
            self.assertIn(own, found)
        # The extraction-era convenience is only ever offered when it holds
        # captures, so a deployment cannot silently search an empty directory.
        if not SIBLING_CAPTURE_DIR.is_dir():
            self.assertNotIn(SIBLING_CAPTURE_DIR, found)


class UniverseReadingTest(ArchiveCase):
    """A catalogue file is written in more than one shape, and all of them read."""

    def test_a_list_of_names(self):
        self.assertEqual(_symbols_from(["ogdc", "PPL"]), ["OGDC", "PPL"])

    def test_a_list_of_records_in_any_case(self):
        self.assertEqual(
            _symbols_from([{"SYMBOL": "AASM"}, {"symbol": "ABOT"},
                           {"listedIn": ["KMIALLSHR"], "name": "x"}]),
            ["AASM", "ABOT"])

    def test_a_mapping_of_name_to_record(self):
        # The key names the symbol whatever its value holds, so a snapshot
        # rewritten as a mapping still reads as a symbol list.
        self.assertEqual(_symbols_from({"OGDC": {"high": 1}, "PPL": None}),
                         ["OGDC", "PPL"])

    def test_a_snapshot_that_carries_its_own_heading(self):
        self.assertEqual(_symbols_from({"symbols": [{"scrip": "Z:REG"}]}), ["Z"])

    def test_a_feed_style_symbol_loses_its_market_suffix(self):
        self.assertEqual(_symbols_from(["OGDC:REG"]), ["OGDC"])

    def test_junk_contributes_nothing_rather_than_a_guess(self):
        for junk in ("not a catalogue", 12, [{"nope": "x"}], {}, []):
            self.assertEqual(_symbols_from(junk), [])

    def test_the_first_candidate_that_yields_symbols_wins(self):
        empty = self.tmp / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        full = self.tmp / "full.json"
        full.write_text(json.dumps([{"symbol": "PPL"}]), encoding="utf-8")
        self.assertEqual(read_universe(candidates=(empty, full)), ["PPL"])
        self.assertEqual(read_universe(candidates=(empty,)), [])


class StoringASessionTest(ArchiveCase):

    def test_a_session_reads_back_bar_for_bar(self):
        self.write_tape(session_records())
        archive = self.archive()
        summary = archive.write(self.build(), capture=identify(self.capture),
                                built_at=MONDAY_1100.isoformat())
        self.assertEqual(summary.day, "2026-10-12")
        self.assertEqual(summary.symbols, 2)
        self.assertEqual(summary.bars, 6)

        bars = archive.read(MONDAY, "OGDC")
        self.assertEqual([bar.t for bar in bars],
                         ["2026-10-12T09:33:00+05:00", "2026-10-12T09:34:00+05:00",
                          "2026-10-12T09:35:00+05:00"])
        self.assertEqual([bar.o for bar in bars], [100.0, 101.0, 102.0])
        # The venue's own running counter, differenced per minute: the opening
        # value is reported as what traded before the tape saw the symbol and
        # is never spread across bars, so the first minute carries no delta.
        self.assertEqual([bar.v for bar in bars], [0.0, 1000.0, 1000.0])

    def test_the_stored_row_keeps_what_the_wire_does_not_need(self):
        self.write_tape(session_records())
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        rows = [json.loads(line) for line in
                archive.symbol_path(MONDAY, "OGDC").read_text(
                    encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual([row["prints"] for row in rows], [1, 1, 1])
        self.assertEqual([row["carried"] for row in rows], [False] * 3)
        self.assertEqual(rows[0]["t"], "2026-10-12T09:33:00+05:00")

    def test_the_manifest_identifies_the_capture_and_hashes_every_file(self):
        self.write_tape(session_records())
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        raw = archive.manifest(MONDAY)
        assert raw is not None
        self.assertEqual(raw["capture"]["name"], "capture_20261012.ndjson")
        self.assertEqual(len(raw["capture"]["sha256"]), 64)
        self.assertEqual(sorted(raw["symbol_files"]), ["OGDC", "PPL"])
        self.assertEqual(archive.verify(MONDAY), [])

    def test_a_tampered_symbol_file_is_caught_by_verify(self):
        self.write_tape(session_records())
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        path = archive.symbol_path(MONDAY, "OGDC")
        path.write_text(path.read_text(encoding="utf-8").replace("100", "999"),
                        encoding="utf-8")
        self.assertIn("OGDC: hash mismatch", archive.verify(MONDAY))

    def test_a_malformed_stored_row_is_refused_not_skipped(self):
        self.write_tape(session_records())
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        path = archive.symbol_path(MONDAY, "OGDC")
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[1] = '{"t": "2026-10-12T09:34:00+05:00", "o": 1, "h": 0.5, "l": 2, "c": 1}'
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            archive.read(MONDAY, "OGDC")
        self.assertIn("line 2", str(caught.exception))

    def test_a_symbol_the_tape_never_printed_has_no_file_at_all(self):
        self.write_tape(session_records(symbols=("OGDC",)))
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        self.assertFalse(archive.has(MONDAY, "PPL"))
        self.assertEqual(archive.read(MONDAY, "PPL"), [])
        self.assertEqual(archive.symbols(MONDAY), ["OGDC"])

    def test_storing_the_same_capture_twice_does_not_churn_the_archive(self):
        self.write_tape(session_records())
        archive = self.archive()
        tape = self.build()
        first = archive.write(tape, capture=identify(self.capture))
        second = archive.write(tape, capture=identify(self.capture))
        self.assertEqual(first.builds, 1)
        self.assertEqual(second.builds, 1)
        self.assertEqual(second.bars, first.bars)

    def test_a_record_of_nothing_for_a_real_tape_is_rebuilt(self):
        """An empty manifest over a non-empty tape is a defect, not an answer."""
        self.write_tape([])
        empty = tape_bars.build(self.capture, ["OGDC", "PPL"], MONDAY_1100,
                                day=MONDAY)
        archive = self.archive()
        archive.write(empty, capture=identify(self.capture))
        self.assertEqual(archive.summary(MONDAY).bars, 0)

        self.write_tape(session_records())
        healed = archive.write(self.build(), capture=identify(self.capture))
        self.assertGreater(healed.bars, 0)
        self.assertEqual(healed.builds, 2)

    def test_an_explicit_rebuild_is_forced(self):
        self.write_tape(session_records())
        archive = self.archive()
        tape = self.build()
        archive.write(tape, capture=identify(self.capture))
        again = archive.write(tape, capture=identify(self.capture), force=True)
        self.assertEqual(again.builds, 2)

    def test_days_and_sessions_read_newest_first(self):
        self.write_tape(session_records())
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        sunday = self.captures / "capture_20261011.ndjson"
        self.write_tape(session_records(start=MONDAY_OPEN - timedelta(days=1)),
                        path=sunday)
        archive.write(tape_bars.build(sunday, ["OGDC", "PPL"], MONDAY_1100,
                                      day=date(2026, 10, 11)),
                      capture=identify(sunday))
        self.assertEqual(archive.days(), ["2026-10-12", "2026-10-11"])
        self.assertEqual([row["day"] for row in archive.sessions()],
                         ["2026-10-12", "2026-10-11"])

    def test_a_limit_returns_the_newest_bars(self):
        self.write_tape(session_records(minutes=5))
        archive = self.archive()
        archive.write(self.build(), capture=identify(self.capture))
        newest = archive.read(MONDAY, "OGDC", limit=2)
        self.assertEqual([bar.o for bar in newest], [103.0, 104.0])


class AnyDayServingTest(ArchiveCase):
    """The 24/7 promise: a past session is served without a recorder."""

    def test_the_session_list_names_what_can_be_drawn(self):
        self.write_tape(session_records())
        with self.patched_capture():
            rows = self.source().sessions()
        self.assertEqual([row["day"] for row in rows], ["2026-10-12"])
        self.assertEqual(rows[0]["current"], True)
        self.assertEqual(rows[0]["archived"], False)
        self.assertEqual(rows[0]["capture"]["name"], "capture_20261012.ndjson")
        self.assertEqual(rows[0]["capture"]["sha256"], "")

    def test_a_past_session_is_built_from_its_capture_and_then_stored(self):
        self.write_tape(session_records())
        with self.patched_capture():
            source = self.source(clock=TUESDAY_1100)
            bars = source.history("OGDC", "1m", day=MONDAY)
            self.assertEqual(len(bars), 3)
            # Looking at it once stored it, so the next look needs no capture.
            self.assertTrue(self.archive().has(MONDAY, "OGDC"))
            self.capture.unlink()
            again = source.history("OGDC", "1m", day=MONDAY)
        self.assertEqual([bar.c for bar in again], [bar.c for bar in bars])

    def test_a_past_session_reads_from_the_archive_when_it_is_stored(self):
        self.write_tape(session_records())
        self.archive().write(self.build(), capture=identify(self.capture))
        self.capture.unlink()
        with self.patched_capture():
            bars = self.source(clock=TUESDAY_1100).history("OGDC", "1m",
                                                           day=MONDAY)
            info = self.source(clock=TUESDAY_1100).source_info("OGDC", day=MONDAY)
        self.assertEqual(len(bars), 3)
        self.assertIn("archived session", info.label)

    def test_an_archived_session_says_which_file_it_came_from(self):
        self.write_tape(session_records())
        self.archive().write(self.build(), capture=identify(self.capture))
        self.capture.unlink()
        with self.patched_capture():
            lines = self.source(clock=TUESDAY_1100).notes("OGDC", day=MONDAY)
        text = " ".join(lines)
        self.assertIn("archived 2026-10-12 session", text)
        self.assertIn("capture_20261012.ndjson", text)
        self.assertIn("sha256", text)

    def test_a_past_day_with_neither_capture_nor_archive_is_named(self):
        self.write_tape(session_records())
        with self.patched_capture():
            source = self.source(clock=TUESDAY_1100)
            with self.assertRaises(UpstreamError) as caught:
                source.history("OGDC", "1m", day=date(2026, 10, 8))
        self.assertEqual(caught.exception.category, UpstreamError.EMPTY_ACK)
        self.assertIn("2026-10-08", caught.exception.detail)

    def test_today_with_no_capture_falls_back_and_the_payload_says_so(self):
        from charts.contract import ChartPayload
        from charts.service import build_payload
        from charts.store import BarStore

        self.write_tape(session_records())
        self.archive().write(self.build(), capture=identify(self.capture))
        self.capture.unlink()
        with self.patched_capture():
            source = self.source(clock=TUESDAY_1100)
            payload = build_payload(BarStore(), source, "OGDC", "1m",
                                    moment=TUESDAY_1100)
        self.assertIsInstance(payload, ChartPayload)
        self.assertEqual(len(payload.bars), 3)
        self.assertEqual(payload.session.day, "2026-10-12")
        self.assertFalse(payload.session.current)
        self.assertTrue(payload.session.archived)
        self.assertTrue(payload.session.volume_available)
        self.assertIn("newest stored session", payload.notes[0])
        # The fallback is a session the reader can check, not a silent swap.
        self.assertEqual(payload.session.capture["name"],
                         "capture_20261012.ndjson")

    def test_the_session_effect_reports_the_archive_beside_the_capture(self):
        self.write_tape(session_records())
        self.archive().write(self.build(), capture=identify(self.capture))
        with self.patched_capture():
            effect = self.source().session_effect()
        self.assertTrue(effect["available"])
        self.assertEqual(effect["symbols_with_bars"], 2)
        self.assertEqual(effect["archive_days"], 1)
        self.assertEqual(effect["capture_dirs"], [str(self.captures)])

    def test_archiving_a_finished_day_through_the_adapter(self):
        self.write_tape(session_records())
        with self.patched_capture():
            summary = self.source(clock=TUESDAY_1100).archive_session(MONDAY)
        self.assertEqual(summary["day"], "2026-10-12")
        self.assertEqual(summary["bars"], 6)
        self.assertEqual(len(summary["capture"]["sha256"]), 64)

    def test_archiving_something_that_is_not_a_day_is_refused(self):
        with self.patched_capture():
            with self.assertRaises(UpstreamError) as caught:
                self.source().archive_session("last Tuesday")
        self.assertEqual(caught.exception.category, UpstreamError.SCHEMA_CHANGE)

    def test_a_daily_series_keeps_every_session_it_can_draw(self):
        """1D without a named day is history, not just today's candle."""
        self.write_tape(session_records())
        tuesday = self.captures / "capture_20261013.ndjson"
        self.write_tape(session_records(start=TUESDAY_OPEN), path=tuesday)
        with self.patched_capture():
            source = self.source(clock=WEDNESDAY_1100)
            daily = source.history("OGDC", "1D")
            one_day = source.history("OGDC", "1D", day=MONDAY)
        self.assertEqual([bar.t[:10] for bar in daily],
                         ["2026-10-12", "2026-10-13"])
        self.assertEqual(len(one_day), 1)
        self.assertEqual(one_day[0].t[:10], "2026-10-12")

    def test_the_catalogue_carries_per_symbol_facts_when_asked(self):
        self.write_tape(session_records())
        with self.patched_capture():
            rows = self.source().catalog(facts=True)
        by_symbol = {row["symbol"]: row for row in rows}
        self.assertEqual(by_symbol["OGDC"]["bars"], 3)
        self.assertEqual(by_symbol["OGDC"]["close"], 102.0)
        self.assertEqual(by_symbol["OGDC"]["day"], "2026-10-12")
        self.assertEqual(by_symbol["OGDC"]["first"], "2026-10-12T09:33:00+05:00")
        self.assertEqual(by_symbol["PPL"]["bars"], 3)

    def test_catalogue_facts_match_the_chartable_series(self):
        """A pre-open print is in the capture but not in the chart.

        The watchlist and the chart must describe one series. Reporting the
        raw capture counted rows the session law excludes, so the list showed
        a later bar and a larger count than the chart could ever draw.
        """
        before_open = datetime(2026, 10, 12, 9, 20, tzinfo=KARACHI)
        self.write_tape([
            frame(before_open, tick("OGDC", 99.0, 500, before_open,
                                    "09:20:00")),
            *session_records(),
        ])
        with self.patched_capture():
            source = self.source()
            rows = {
                row["symbol"]: row
                for row in source.catalog(facts=True)
            }
            bars = source.history("OGDC", "1m", day=MONDAY)
        self.assertEqual(rows["OGDC"]["bars"], len(bars))
        self.assertEqual(rows["OGDC"]["last"], bars[-1].t)
        self.assertEqual(rows["OGDC"]["close"], bars[-1].c)
        self.assertEqual(rows["OGDC"]["first"], "2026-10-12T09:33:00+05:00")

    def test_the_catalogue_without_facts_keeps_its_old_shape(self):
        self.write_tape(session_records())
        with self.patched_capture():
            rows = self.source().catalog()
        self.assertNotIn("bars", rows[0])
        self.assertIn("listed", rows[0])

    def test_a_symbol_with_no_bars_in_the_session_reports_zero_not_a_price(self):
        self.write_tape(session_records(symbols=("OGDC",)))
        with self.patched_capture():
            rows = self.source().catalog(facts=True)
        by_symbol = {row["symbol"]: row for row in rows}
        self.assertEqual(by_symbol["PPL"]["bars"], 0)
        self.assertIsNone(by_symbol["PPL"]["close"])
        # The list is ordered with the symbols that traded first, so a reader
        # sees what the session holds before what it does not.
        self.assertEqual(rows[0]["symbol"], "OGDC")


class ReadUniverseInTheTapeAdapterTest(ArchiveCase):

    def test_a_missing_universe_is_an_empty_list_not_an_exception(self):
        missing = self.tmp / "nope.json"
        self.assertEqual(read_universe(candidates=(missing,)), [])

    def test_the_tape_falls_back_to_its_own_symbols_when_none_match(self):
        """A catalogue that names none of the tape's symbols is not its list."""
        wrong = self.tmp / "wrong.json"
        wrong.write_text(json.dumps(["NASDAQ1", "NASDAQ2"]), encoding="utf-8")
        self.write_tape(session_records())
        with self.patched_capture():
            source = TapeSource(clock=lambda: MONDAY_1100,
                                universe_path=wrong,
                                capture_dirs=(self.captures,),
                                archive_dir=self.archive_dir)
            bars = source.history("OGDC", "1m")
            notes = source.notes("OGDC")
        self.assertEqual(len(bars), 3)
        text = " ".join(notes)
        self.assertIn("none of its symbols appear", text)
        self.assertIn(str(wrong), text)
