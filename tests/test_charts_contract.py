"""The chart contract: the wire shape, validated in both directions.

These tests hold the parts a consumer would otherwise have to trust:

  * a bar that is internally inconsistent (a high below its own close) is
    refused rather than drawn;
  * a timestamp without an offset is refused, because guessing a zone is how
    a chart silently shows the wrong session (SO-8, one clock);
  * a payload with unsorted or duplicated bars is refused, because a chart
    that draws them is a chart that lies about the order of the day;
  * a payload survives a round trip through its own parser, and a payload
    missing a required field fails loudly.

They are deliberately about the contract and nothing else: no store, no
network, no clock.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from charts.contract import (  # noqa: E402
    SCHEMA_VERSION, Bar, ChartPayload, ContractError, Gap, MarketContext,
    RESOLUTIONS, SourceInfo, bars_from_rows,
)

KARACHI = timezone(timedelta(hours=5), name="Asia/Karachi")
MONDAY_1032 = datetime(2026, 10, 12, 10, 32, tzinfo=KARACHI)


def sample_payload(**overrides) -> ChartPayload:
    fields = dict(
        symbol="OGDC",
        resolution="1m",
        source=SourceInfo(id="replay", label="synthetic replay series"),
        market=MarketContext(phase="OPEN", state="MARKET", trading_day=True,
                             timezone="Asia/Karachi", band=None,
                             next_event=None, as_of="2026-10-12T10:32:00+05:00"),
        as_of="2026-10-12T10:32:00+05:00",
        bars=[Bar.build(t=MONDAY_1032, o=100, h=101, l=99, c=100.5, v=10)],
        gaps=[Gap(start="2026-10-12T10:30:00+05:00",
                  end="2026-10-12T10:31:00+05:00", minutes=2,
                  reason="test gap")],
        notes=["a note that travels with the chart"],
    )
    fields.update(overrides)
    return ChartPayload(**fields)


class BarTest(unittest.TestCase):

    def test_a_karachi_stamp_is_kept_with_its_offset(self):
        bar = Bar.build(t=MONDAY_1032, o=1, h=2, l=0.5, c=1.5, v=0)
        self.assertEqual(bar.t, "2026-10-12T10:32:00+05:00")

    def test_a_naive_timestamp_is_refused(self):
        with self.assertRaises(ContractError):
            Bar.build(t=datetime(2026, 10, 12, 10, 32), o=1, h=2, l=0.5, c=1)

    def test_a_high_below_the_close_is_refused(self):
        with self.assertRaises(ContractError):
            Bar.build(t=MONDAY_1032, o=100, h=101, l=99, c=102)

    def test_a_low_above_the_open_is_refused(self):
        with self.assertRaises(ContractError):
            Bar.build(t=MONDAY_1032, o=100, h=101, l=100.5, c=101)

    def test_a_non_positive_price_is_refused(self):
        with self.assertRaises(ContractError):
            Bar.build(t=MONDAY_1032, o=0, h=1, l=0.5, c=1)

    def test_a_non_finite_price_is_refused(self):
        with self.assertRaises(ContractError):
            Bar.build(t=MONDAY_1032, o="nan", h=1, l=0.5, c=1)

    def test_volume_defaults_to_zero_and_never_goes_negative(self):
        self.assertEqual(Bar.build(t=MONDAY_1032, o=1, h=2, l=0.5, c=1).v, 0.0)
        self.assertEqual(
            Bar.build(t=MONDAY_1032, o=1, h=2, l=0.5, c=1, v=-5).v, 0.0)
        with self.assertRaises(ContractError):
            Bar(t="2026-10-12T10:32:00+05:00", o=1, h=2, l=0.5, c=1, v=-1)


class PayloadTest(unittest.TestCase):

    def test_round_trip_keeps_everything_that_matters(self):
        original = sample_payload()
        again = ChartPayload.from_dict(original.as_dict())
        self.assertEqual(again.as_dict(), original.as_dict())
        self.assertEqual(again.schema_version, SCHEMA_VERSION)

    def test_unknown_resolution_is_refused(self):
        with self.assertRaises(ContractError):
            sample_payload(resolution="7m")

    def test_unsorted_bars_are_refused(self):
        later = Bar.build(t=datetime(2026, 10, 12, 10, 33, tzinfo=KARACHI),
                          o=1, h=2, l=0.5, c=1)
        earlier = Bar.build(t=MONDAY_1032, o=1, h=2, l=0.5, c=1)
        with self.assertRaises(ContractError):
            sample_payload(bars=[later, earlier])

    def test_two_bars_at_one_timestamp_are_refused(self):
        one = Bar.build(t=MONDAY_1032, o=1, h=2, l=0.5, c=1)
        two = Bar.build(t=MONDAY_1032, o=2, h=3, l=1.5, c=2)
        with self.assertRaises(ContractError):
            sample_payload(bars=[one, two])

    def test_a_payload_missing_a_field_is_refused(self):
        raw = sample_payload().as_dict()
        del raw["symbol"]
        with self.assertRaises(ContractError):
            ChartPayload.from_dict(raw)

    def test_a_payload_with_a_bad_bar_is_refused(self):
        raw = sample_payload().as_dict()
        raw["bars"][0]["h"] = "not a number"
        with self.assertRaises(ContractError):
            ChartPayload.from_dict(raw)

    def test_the_contract_names_every_resolution_it_accepts(self):
        self.assertEqual(
            RESOLUTIONS,
            ("1s", "10s", "1m", "5m", "10m", "15m", "30m", "1h", "4h",
             "1D", "1W", "1M", "1d", "session"))

    def test_the_schema_version_is_pinned_literally(self):
        """A bump has to be a decision, so it is written twice.

        The rest of the suite compares against the constant, which would
        follow a bump silently. This is the one place the number is written
        out: v2 added the ``session`` block (which trading day a series
        belongs to, and whether it came from the durable archive); v3 added
        the full timeframe ladder and the computed index proxies, without
        changing the session block or the bar shape.
        """
        self.assertEqual(SCHEMA_VERSION, 3)

    def test_a_v2_payload_carries_the_session_it_is_showing(self):
        from charts.contract import ChartSession

        payload = sample_payload(session=ChartSession(
            day="2026-10-12", current=False, archived=True,
            source="broker_tape", capture={"name": "capture_20261012.ndjson",
                                          "bytes": 44, "sha256": "ab" * 32},
            built_at="2026-10-12T15:31:00+05:00",
            note="this is the archived session"))
        again = ChartPayload.from_dict(payload.as_dict())
        self.assertEqual(again.session.day, "2026-10-12")
        self.assertTrue(again.session.archived)
        self.assertFalse(again.session.current)
        self.assertEqual(again.session.capture["name"],
                         "capture_20261012.ndjson")

    def test_a_pre_v2_payload_without_a_session_block_still_reads(self):
        raw = sample_payload().as_dict()
        del raw["session"]
        again = ChartPayload.from_dict(raw)
        self.assertEqual(again.session.day, "")
        self.assertEqual(len(again.bars), 1)


class RowsTest(unittest.TestCase):

    def rows(self):
        return [
            {"ts": "2026-10-12T10:33:00+05:00", "open": 2, "high": 3,
             "low": 1.5, "close": 2.5, "volume": 5},
            {"ts": "2026-10-12T10:32:00+05:00", "open": 1, "high": 2,
             "low": 0.5, "close": 1.5, "volume": 4},
        ]

    def test_rows_are_sorted_into_a_series(self):
        bars = bars_from_rows(self.rows())
        self.assertEqual([bar.t for bar in bars],
                         ["2026-10-12T10:32:00+05:00",
                          "2026-10-12T10:33:00+05:00"])

    def test_a_duplicate_minute_is_refused(self):
        rows = self.rows()
        rows.append(dict(rows[0]))
        with self.assertRaises(ContractError):
            bars_from_rows(rows)

    def test_a_malformed_row_is_refused_rather_than_skipped(self):
        with self.assertRaises(KeyError):
            bars_from_rows([{"ts": "2026-10-12T10:32:00+05:00"}])


if __name__ == "__main__":
    unittest.main()
