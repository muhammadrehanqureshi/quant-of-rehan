"""The archive reader, against a synthetic partition it writes itself.

The real archive is 239 MB of gitignored parquet, so this test proves the
reader on the same schema the builder writes: one timeframe folder, one year
per file, the eight stored columns, epoch seconds and the session flag.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data import intraday_history as archive
from src.data.sessions import KARACHI


def _epoch(hour: int, minute: int) -> int:
    return int(datetime(2026, 11, 2, hour, minute, tzinfo=KARACHI).timestamp())


def _frame() -> pd.DataFrame:
    rows = []
    for symbol in ("OGDC", "PPL"):
        for hour, minute, regular in ((9, 20, False), (9, 35, True),
                                      (15, 25, True)):
            rows.append({
                "symbol": symbol,
                "ts": _epoch(hour, minute),
                "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 500, "regular": regular,
            })
    return pd.DataFrame(rows)


class ArchiveTest(unittest.TestCase):
    def test_available_load_and_session_helpers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "5m").mkdir()
            _frame().to_parquet(root / "5m" / "5m-2026.parquet", index=False)

            self.assertEqual(list(archive.available("5m", root)), [2026])
            table = archive.load("5m", years=[2026], symbols=["OGDC"],
                                 regular_only=True, root=root)
            self.assertEqual(len(table), 2)
            self.assertEqual(set(table["symbol"].astype(str)), {"OGDC"})
            self.assertTrue(bool(table["regular"].all()))

            stamps = archive.karachi_index(table)
            self.assertEqual(stamps[0].strftime("%Y-%m-%d %H:%M"),
                             "2026-11-02 09:35")
            self.assertEqual(len(archive.sessions(table)), 1)

            every_bar = archive.load("5m", years=[2026], root=root)
            self.assertEqual(len(every_bar), 6)
            self.assertEqual(int((~every_bar["regular"]).sum()), 2)

    def test_one_day_partition_uses_karachi_midnight(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "1D").mkdir()
            midnight = int(datetime(2026, 11, 2, tzinfo=KARACHI).timestamp())
            pd.DataFrame([{
                "symbol": "OGDC", "ts": midnight, "open": 100.0,
                "high": 101.0, "low": 99.0, "close": 100.5,
                "volume": 6000, "regular": True,
            }]).to_parquet(root / "1D" / "1D-2026.parquet", index=False)
            self.assertEqual(archive.TIMEFRAMES, ("5m", "15m", "30m", "60m", "1D"))
            table = archive.load("1D", years=[2026], root=root)
            self.assertEqual(len(table), 1)
            self.assertEqual(archive.karachi_index(table)[0].strftime("%Y-%m-%d %H:%M"),
                             "2026-11-02 00:00")

    def test_a_missing_year_is_named_not_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "5m").mkdir()
            _frame().to_parquet(root / "5m" / "5m-2026.parquet", index=False)
            with self.assertRaises(FileNotFoundError):
                archive.load("5m", years=[2025], root=root)

    def test_manifest_reads_the_builders_record(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "manifest-2026.json").write_text(
                json.dumps({"year": 2026, "ok": True}), encoding="utf-8")
            self.assertEqual(archive.manifest(2026, root)["year"], 2026)
            with self.assertRaises(FileNotFoundError):
                archive.manifest(2025, root)


if __name__ == "__main__":
    unittest.main()
