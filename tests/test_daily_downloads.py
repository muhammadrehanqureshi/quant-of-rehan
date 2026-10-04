"""Offline tests for the PSX Daily Downloads fetcher pieces (no network)."""

from __future__ import annotations

import gzip
import io
import sys
import unittest
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.psx_daily_downloads import (  # noqa: E402
    iter_weekdays,
    parse_closing_lis,
    _decompress,
)

LIS = (
    "02OCT2026|OGDC|0820|Oil & Gas Dev|313.01|315.95|311.8|314.62|1836867|313.39|||\n"
    "02OCT2026|786|0813|786 Invest Ltd|20.4|20.9|19.81|20.64|29098|20.67|||\n"
    "02OCT2026|HBL|0807|Habib Bank|110.09|110.35|109.09|110.01|1599420|110.09|||\n"
    "badline-with-too-few-fields\n"
    "02OCT2026|OGDC|0820|Oil & Gas Dev|1|1|1|1|1|1|||\n"          # dup symbol
    "02OCT2026|BADNUM|0000|Broken|a|b|c|d|e|||\n"                  # unparseable
)


class TestParseClosingLis(unittest.TestCase):
    def test_rows_fields_and_skip_counts(self):
        rows, info = parse_closing_lis(LIS)
        self.assertEqual(len(rows), 3)
        self.assertEqual(info["rows"], 3)
        self.assertEqual(info["lines_malformed"], 2)   # short line + bad numerics
        self.assertEqual(info["duplicate_symbols"], 1)
        ogdc = next(r for r in rows if r["symbol"] == "OGDC")
        self.assertEqual(ogdc["date"], "2026-10-02")
        self.assertEqual(ogdc["open"], 313.01)
        self.assertEqual(ogdc["high"], 315.95)
        self.assertEqual(ogdc["low"], 311.8)
        self.assertEqual(ogdc["close"], 314.62)
        self.assertEqual(ogdc["volume"], 1836867.0)
        self.assertAlmostEqual(ogdc["rate2"], 313.39)

    def test_numeric_symbol_ticker_preserved(self):
        rows, _ = parse_closing_lis(LIS)
        self.assertTrue(any(r["symbol"] == "786" for r in rows))

    def test_zero_prices_kept_as_printed(self):
        rows, _ = parse_closing_lis(
            "02OCT2026|XDEC|40|Suspended thing|0.0|0|0|325.74|0|324.88|||\n")
        self.assertEqual(rows[0]["open"], 0.0)
        self.assertEqual(rows[0]["close"], 325.74)   # never fabricated (SO-3)


class TestDecompress(unittest.TestCase):
    def test_zip_payload(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("closing11.lis", LIS)
        self.assertEqual(_decompress(buf.getvalue()), LIS)

    def test_gzip_payload(self):
        self.assertEqual(_decompress(gzip.compress(LIS.encode())), LIS)

    def test_unknown_payload_returns_none(self):
        self.assertIsNone(_decompress(b"<html>404 page</html>"))


class TestWeekdayWalker(unittest.TestCase):
    def test_skips_weekends_inclusive(self):
        days = iter_weekdays("2026-10-02", "2026-10-06")  # Fri..Tue
        self.assertEqual(days, [date(2026, 10, 2), date(2026, 10, 5),
                                date(2026, 10, 6)])

    def test_reversed_range_raises(self):
        with self.assertRaises(ValueError):
            iter_weekdays("2026-10-06", "2026-10-02")


if __name__ == "__main__":
    unittest.main()
