"""ETF exclusion and the one eligibility service (owner order 2026-10-15/16).

The owner's requirement is not "an ETF was filtered somewhere": it is that one
authoritative service decides eligibility, that it fails closed when a
classification cannot be settled, and that ETFs cannot enter by any of the
routes a basket instrument could take into this system: the live scan, the
recorder's subscription, historical research and replay, a paper ledger entry,
a notification, a stale universe cache, or a second entry point that forgot
the rule.

Every test below names the route it closes. The universe file is real
(src/data/universe_kmiall.json, 317 members including the two ETFs), so the
counts are measured against the project's own data rather than a fixture.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.backtest import dataset  # noqa: E402
from src.data import eligibility  # noqa: E402
from src.data import feed_capture  # noqa: E402
from scripts import intraday_pipeline as pipeline  # noqa: E402

UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
ETF_ONE, ETF_TWO = "MIIETF", "MZNPETF"


def universe_symbols() -> list[str]:
    rows = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    return [str(row["symbol"]).strip().upper() for row in rows
            if row.get("symbol") and "KMIALLSHR" in (row.get("listedIn") or [])]


class ClassificationTest(unittest.TestCase):
    def test_a_kmiall_listed_etf_is_rejected_by_the_registry(self):
        """Route 1: the exchange's own KMIALL snapshot still lists it."""
        members = universe_symbols()
        result = eligibility.screen([ETF_ONE], universe=members)
        self.assertEqual(result.eligible, [])
        self.assertEqual([row.symbol for row in result.excluded], [ETF_ONE])
        row = result.refusal_for(ETF_ONE)
        self.assertEqual(row.kind, eligibility.KIND_ETF)
        self.assertIn("ETF", row.source + row.reason)

    def test_an_etf_outside_kmiall_is_rejected_by_the_naming_convention(self):
        """Route 2: a fund nobody has written down yet."""
        result = eligibility.screen(["SOMENEWETF", "ANOTHERETF"], universe=None)
        self.assertEqual(result.eligible, [])
        self.assertEqual(sorted(row.symbol for row in result.excluded),
                         ["ANOTHERETF", "SOMENEWETF"])
        for row in result.excluded:
            self.assertEqual(row.kind, eligibility.KIND_ETF)
            self.assertIn("convention", row.source)

    def test_a_known_equity_passes(self):
        """The filter that refuses nothing useful: real KMIALL equities."""
        members = universe_symbols()
        result = eligibility.screen(["OGDC", "TREET", "CNERGY"], universe=members)
        self.assertEqual(result.eligible, ["CNERGY", "OGDC", "TREET"])
        self.assertEqual(result.excluded, [])
        self.assertEqual(result.unknown, [])

    def test_an_instrument_the_service_cannot_settle_is_rejected(self):
        """Route 3: fail closed. Uncertain is refused, never admitted."""
        for symbol in ("1234", "A$B", "TOOLONGSYMBOL123", ""):
            with self.subTest(symbol=symbol):
                result = eligibility.screen([symbol], universe=None)
                self.assertEqual(result.eligible, [],
                                 f"{symbol!r} was admitted without a "
                                 f"classification")
                self.assertTrue(result.unknown or result.excluded)

    def test_a_half_reviewed_registry_entry_does_not_admit_anything(self):
        """A pending review is UNKNOWN, not a quiet yes."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"symbols": {
                "OGDC": {"kind": "EQUITY", "review_status": "pending",
                         "source": "half finished edit"}}}), encoding="utf-8")
            book = eligibility.load_registry(path)
        row = eligibility.classification("OGDC", book)
        self.assertEqual(row.kind, eligibility.KIND_UNKNOWN)
        self.assertIn("not reviewed", row.reason)

    def test_the_registry_carries_its_own_provenance(self):
        """An auditable exclusion: source, effective date, review status."""
        book = eligibility.load_registry()
        for symbol in (ETF_ONE, ETF_TWO):
            with self.subTest(symbol=symbol):
                entry = book["symbols"][symbol]
                for key in ("issuer", "kind", "source", "effective_date",
                            "review_status"):
                    self.assertTrue(entry.get(key), f"{symbol} has no {key}")
                self.assertEqual(entry["review_status"], "reviewed")
        self.assertTrue(book.get("as_of"))
        self.assertTrue(book.get("coverage_note"))


class EntryPointTest(unittest.TestCase):
    """The same rule at every door an ETF could walk through."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def _universe_file(self, names: list[str]) -> Path:
        path = self.tmp / "universe.json"
        path.write_text(json.dumps([
            {"symbol": name, "listedIn": ["KMIALLSHR"], "isShariahCompliant": True}
            for name in names]), encoding="utf-8")
        return path

    def test_the_recorder_never_subscribes_to_an_etf(self):
        """Route 4: the tape subscription is built from the same rule."""
        path = self._universe_file([ETF_ONE, ETF_TWO, "OGDC", "TREET"])
        subscribed = feed_capture.load_universe(path)
        self.assertEqual(subscribed, ["OGDC", "TREET"])
        frame = feed_capture.build_subscribe_frame(subscribed)
        for symbol in (ETF_ONE, ETF_TWO):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, frame)

    def test_a_replay_universe_refuses_an_etf(self):
        """Route 5: historical research and backtesting."""
        path = self._universe_file([ETF_ONE, ETF_TWO, "OGDC"])
        historical = dataset.load_universe(path)
        self.assertEqual(historical, {"OGDC"})

    def test_a_stale_universe_cache_cannot_bypass_the_rule(self):
        """Route 6: an old cache that still lists the ETFs."""
        stale = self._universe_file([ETF_ONE, ETF_TWO, "OGDC", "TREET", "LUCK"])
        for name, loader in (("feed_capture", feed_capture.load_universe),
                             ("dataset", dataset.load_universe)):
            with self.subTest(loader=name):
                symbols = set(loader(stale))
                self.assertNotIn(ETF_ONE, symbols)
                self.assertNotIn(ETF_TWO, symbols)

    def test_the_live_universe_and_the_scan_agree(self):
        """Route 7: the live scan's own universe is ETF free."""
        members = universe_symbols()
        live = pipeline.load_kmiall()
        self.assertEqual(len(live), len(members) - 2,
                         "the KMIALL Shariah snapshot minus its two ETFs")
        self.assertEqual(len(members), 319)
        self.assertEqual(len(live), 317)
        for symbol in (ETF_ONE, ETF_TWO):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, live)

    def test_a_legacy_tape_row_cannot_smuggle_an_etf_into_a_scan(self):
        """Route 8: bars are built only for the symbols the scan asked for."""
        from src.data import tape_bars
        import datetime as dt

        stamp = dt.datetime(2026, 10, 16, 10, 5, tzinfo=dt.timezone(dt.timedelta(hours=5)))
        rows = []
        for minute in range(25):
            at = stamp + dt.timedelta(minutes=minute)
            for symbol in (ETF_ONE, "OGDC"):
                rows.append({"kind": "MKT-FEED|SUB%", "ts": at.isoformat(),
                             "ticks": [{"scrip": f"{symbol}:REG",
                                        "last": f"{100 + minute:.2f}",
                                        "volume": str(1000 * (minute + 1)),
                                        "tick_time": at.strftime("%H:%M:%S"),
                                        "high": f"{100 + minute:.2f}",
                                        "low": "100.00",
                                        "trades": str(minute + 1)}]})
        capture = self.tmp / "legacy_tape.ndjson"
        capture.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                           encoding="utf-8")
        tape = tape_bars.build(capture, ["OGDC"], stamp + dt.timedelta(minutes=30))
        self.assertEqual(sorted(tape.bars), ["OGDC"],
                         "an ETF in a legacy capture reached the bar builder")

    def test_the_short_answer_and_the_service_cannot_disagree(self):
        """Route 9: config's name test is the service's own answer."""
        for symbol in (ETF_ONE, ETF_TWO, "SOMENEWETF", "OGDC", "TREET", "1234"):
            with self.subTest(symbol=symbol):
                self.assertEqual(config.is_etf_symbol(symbol),
                                 eligibility.is_etf(symbol))
        source = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
        self.assertIn("eligibility.is_etf(symbol)", source,
                      "config grew a second ETF rule of its own")


class CoverageTest(unittest.TestCase):
    def test_the_exclusion_reports_how_much_it_settles(self):
        """SO-3: the measured coverage of the classification, not a claim."""
        report = eligibility.coverage(universe_symbols())
        self.assertEqual(report["symbols"], 319)
        self.assertEqual(report["etf"], 2)
        self.assertEqual(report["equity"], 317)
        self.assertEqual(report["unknown"], 0)
        self.assertEqual(report["classified_share"], 1.0)
        self.assertEqual(report["unknown_symbols"], [])
        self.assertEqual(report["registry_symbols"], ["MIIETF", "MZNPETF"])


if __name__ == "__main__":
    unittest.main()
