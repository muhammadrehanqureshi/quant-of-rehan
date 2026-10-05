"""
Tests for the KMIALL universe refresher (src/refresh_universe.py).

v4.0.0: the source of truth is the owner's ECLEAR broker terminal
(GetShariahSymbol = the compliance list; ScripServlet for names).
These tests pin:

  * fetch_fundamentals records: compliant by construction, sorted;
  * build_universe: shariah members, sorted by symbol;
  * refresh(): refuses a degenerate parse, writes only real changes,
    reports added/removed;
  * idempotence: a second refresh over an unchanged source writes
    nothing.

The refresher's records no longer carry listedIn tags from a page
scrape - membership IS the compliance list - so the old
soft-404/record-regex tests retired with their source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import refresh_universe as ru


def _records(*symbols: str) -> list[dict]:
    return [
        {
            "symbol": s,
            "isShariahCompliant": True,
            "listedIn": ["KMIALLSHR", "ALLSHR"],
            "name": f"Company {s}",
        }
        for s in symbols
    ]


SAMPLE = _records("ABOT", "MEBL", "NNAR", "MLCF")


class TestBuildUniverse:
    def test_sorted_by_symbol(self):
        universe = ru.build_universe(SAMPLE)
        syms = [r["symbol"] for r in universe]
        assert syms == sorted(syms)
        assert "ABOT" in syms and "MLCF" in syms

    def test_non_compliant_excluded(self):
        records = [dict(r) for r in SAMPLE]
        records[0]["isShariahCompliant"] = False
        syms = [r["symbol"] for r in ru.build_universe(records)]
        assert "ABOT" not in syms


class TestFetchFundamentalsShape:
    def test_records_carry_symbol_compliance_name(self, monkeypatch):
        monkeypatch.setattr(
            ru.broker_feed, "fetch_shariah_symbols",
            lambda timeout=30.0: {"AASM", "BECO"},
        )
        monkeypatch.setattr(
            ru.broker_feed, "fetch_scrips",
            lambda timeout=30.0: {
                "AASM": {"name": "Aas Ltd", "sector": "X", "sector_slug": "x"},
            },
        )
        records = ru.fetch_fundamentals()
        by_sym = {r["symbol"]: r for r in records}
        assert by_sym["AASM"]["isShariahCompliant"] is True
        assert by_sym["AASM"]["name"] == "Aas Ltd"
        # ScripServlet miss degrades the NAME only, never the membership.
        assert by_sym["BECO"]["name"] == ""
        assert [r["symbol"] for r in records] == ["AASM", "BECO"]

    def test_empty_shariah_list_raises(self, monkeypatch):
        monkeypatch.setattr(
            ru.broker_feed, "fetch_shariah_symbols",
            lambda timeout=30.0: set(),
        )
        with pytest.raises(RuntimeError, match="zero members"):
            ru.fetch_fundamentals()


class TestRefresh:
    @pytest.fixture
    def universe_file(self, tmp_path):
        return tmp_path / "kmiall_tickers.json"

    def test_refuses_degenerate_parse(self, universe_file):
        junk = [
            {"symbol": f"S{i}", "isShariahCompliant": True,
             "listedIn": ["KMIALLSHR"]}
            for i in range(3)
        ]
        with pytest.raises(RuntimeError, match="refusing"):
            ru.refresh(junk, universe_file=universe_file)
        assert not universe_file.exists()

    def test_writes_addition_and_reports_it(self, universe_file):
        report = ru.refresh(
            SAMPLE, universe_file=universe_file, min_members=2
        )
        assert report["changed"] is True
        assert report["added"] == ["ABOT", "MEBL", "MLCF", "NNAR"]
        assert report["removed"] == []
        stored = json.loads(universe_file.read_text(encoding="utf-8"))
        assert {r["symbol"] for r in stored} == {
            "ABOT", "MEBL", "MLCF", "NNAR",
        }

    def test_reports_removals(self, universe_file):
        ru.refresh(SAMPLE, universe_file=universe_file, min_members=2)
        # NNAR leaves the compliance list.
        mutated = [r for r in SAMPLE if r["symbol"] != "NNAR"]
        report = ru.refresh(
            mutated, universe_file=universe_file, min_members=1
        )
        assert report["removed"] == ["NNAR"]
        assert report["changed"] is True

    def test_idempotent_no_change_no_write(self, universe_file):
        ru.refresh(SAMPLE, universe_file=universe_file, min_members=2)
        first = universe_file.read_text(encoding="utf-8")
        report = ru.refresh(
            SAMPLE, universe_file=universe_file, min_members=2
        )
        assert report["changed"] is False
        assert universe_file.read_text(encoding="utf-8") == first
