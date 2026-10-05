"""
Tests for psx_core.universe - the KMIALL universe loader.
"""

from __future__ import annotations

import json

import pytest

from psx_core import paths, universe


class TestLoadRecords:
    def test_loads_standard_format(self, tmp_path):
        data = [
            {"symbol": "ABOT", "isShariahCompliant": True, "listedIn": ["KMIALLSHR"]},
            {"symbol": "MEBL", "isShariahCompliant": True, "listedIn": ["KMIALLSHR"]},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        records = universe.load_records(path)
        assert len(records) == 2
        assert records[0]["symbol"] == "ABOT"

    def test_deduplicates_symbols(self, tmp_path):
        data = [
            {"symbol": "ABOT", "listedIn": []},
            {"symbol": "ABOT", "listedIn": ["KMIALLSHR"]},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        records = universe.load_records(path)
        assert len(records) == 1

    def test_legacy_dict_format(self, tmp_path):
        data = {"ABOT": {"isShariahCompliant": True}, "MEBL": {}}
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        records = universe.load_records(path)
        assert len(records) == 2
        symbols = {r["symbol"] for r in records}
        assert symbols == {"ABOT", "MEBL"}

    def test_bare_string_list(self, tmp_path):
        data = ["ABOT", "MEBL"]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        records = universe.load_records(path)
        assert len(records) == 2

    def test_missing_file_raises(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(universe.UniverseError, match="not found"):
            universe.load_records(path)

    def test_invalid_json_raises(self, tmp_path):
        path = tmp_path / "universe.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(universe.UniverseError, match="not valid JSON"):
            universe.load_records(path)

    def test_empty_list_raises(self, tmp_path):
        path = tmp_path / "universe.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(universe.UniverseError, match="no symbols"):
            universe.load_records(path)

    def test_skips_items_without_symbols(self, tmp_path):
        data = [None, 42, {"no_key": True}]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(universe.UniverseError, match="no symbols"):
            universe.load_records(path)

    def test_symbol_normalised_uppercase(self, tmp_path):
        data = [{"symbol": "abot"}]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        records = universe.load_records(path)
        assert records[0]["symbol"] == "ABOT"


class TestLoad:
    def test_returns_symbol_list(self, tmp_path):
        data = [
            {"symbol": "ABOT", "isShariahCompliant": True,
             "listedIn": ["KMIALLSHR"]},
            {"symbol": "MEBL", "isShariahCompliant": True,
             "listedIn": ["KMIALLSHR"]},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        symbols = universe.load(path)
        assert symbols == ["ABOT", "MEBL"]

    def test_preserves_order(self, tmp_path):
        data = [
            {"symbol": "MEBL", "isShariahCompliant": True},
            {"symbol": "ABOT", "isShariahCompliant": True},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert universe.load(path) == ["MEBL", "ABOT"]

    def test_drops_non_compliant(self, tmp_path):
        # The compliance filter is the default: missing, None, and false
        # flags all exclude the symbol.
        data = [
            {"symbol": "ABOT", "isShariahCompliant": True},
            {"symbol": "MEBL", "isShariahCompliant": False},
            {"symbol": "NOFLAG"},
            {"symbol": "NULLFLAG", "isShariahCompliant": None},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert universe.load(path) == ["ABOT"]

    def test_raw_load_keeps_everything(self, tmp_path):
        data = [
            {"symbol": "ABOT", "isShariahCompliant": True},
            {"symbol": "MEBL", "isShariahCompliant": False},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        raw = universe.load(path, shariah_only=False)
        assert raw == ["ABOT", "MEBL"]

    def test_etf_sector_symbols_excluded(self, tmp_path, monkeypatch):
        # A compliant symbol mapped to the ETF sector is still dropped.
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        (tmp_path / "sector_map.json").write_text(json.dumps({
            "symbolToSector": {"ETFONE": "exchange-traded-funds"},
        }), encoding="utf-8")
        data = [
            {"symbol": "ETFONE", "isShariahCompliant": True},
            {"symbol": "ABOT", "isShariahCompliant": True},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert universe.load(path) == ["ABOT"]

    def test_reit_sector_symbols_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        (tmp_path / "sector_map.json").write_text(json.dumps({
            "symbolToSector": {"IREITX": "real-estate-investment-trust"},
        }), encoding="utf-8")
        data = [
            {"symbol": "IREITX", "isShariahCompliant": True},
            {"symbol": "ABOT", "isShariahCompliant": True},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        assert universe.load(path) == ["ABOT"]


class TestLoadSet:
    def test_returns_set(self, tmp_path):
        data = [
            {"symbol": "ABOT", "isShariahCompliant": True},
            {"symbol": "MEBL", "isShariahCompliant": True},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = universe.load_set(path)
        assert result == {"ABOT", "MEBL"}


class TestCheckMembership:
    def test_counts_tagged(self, tmp_path):
        data = [
            {"symbol": "ABOT", "listedIn": ["KMIALLSHR"]},
            {"symbol": "MEBL", "listedIn": ["KMIALLSHR"]},
            {"symbol": "OLD", "listedIn": ["OTHER"]},
        ]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = universe.check_membership(path)
        assert result["total"] == 3
        assert result["tagged_kmiall"] == 2
        assert "OLD" in result["untagged"]

    def test_empty_listed_in_not_tagged(self, tmp_path):
        data = [{"symbol": "A", "listedIn": []}]
        path = tmp_path / "universe.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        result = universe.check_membership(path)
        assert result["tagged_kmiall"] == 0
