"""
Tests for the site-data builders after the v4.0.0 broker cutover.

The sector map and company names come from the broker's ScripServlet
(one call each; see psx_core.broker_feed for the client tests). Here:
the builders' output shapes, which the rest of the bot consumes, plus
the volume baselines (unrelated to the feed, unchanged).

The foreign-flow parser tests retired with psxterminal.com's
/fipilipi page; NCCPL's own site WAF-blocks programmatic access and
the layer was advisory-only.
"""

from __future__ import annotations

import json

import pytest

from psx_core import paths


# ---------------------------------------------------------------------------
# Sector map builder (broker-sourced)
# ---------------------------------------------------------------------------

from build_sector_map import crawl


class TestSectorMapCrawl:
    def test_groups_by_slug(self, monkeypatch):
        monkeypatch.setattr(
            "build_sector_map.broker_feed.fetch_scrips",
            lambda timeout=30.0: {
                "LUCK": {"name": "Lucky Cement", "sector": "Cement",
                         "sector_slug": "cement"},
                "OGDC": {"name": "Oil and Gas Dev", "sector": "Oil and Gas",
                         "sector_slug": "oil-and-gas"},
                "FFC": {"name": "Fauji Fert", "sector": "Cement",
                        "sector_slug": "cement"},
            },
        )
        result = crawl()
        assert result["sectors"]["cement"] == ["FFC", "LUCK"]
        assert result["symbolToSector"]["OGDC"] == "oil-and-gas"

    def test_unknown_sector_lands_in_unknown(self, monkeypatch):
        monkeypatch.setattr(
            "build_sector_map.broker_feed.fetch_scrips",
            lambda timeout=30.0: {
                "X": {"name": "X", "sector": "", "sector_slug": ""},
            },
        )
        result = crawl()
        assert result["symbolToSector"]["X"] == "unknown"


# ---------------------------------------------------------------------------
# Company names builder (broker-sourced)
# ---------------------------------------------------------------------------

from build_company_names import crawl as crawl_names


class TestCompanyNamesCrawl:
    def test_names_from_scrip_master(self, monkeypatch):
        monkeypatch.setattr(
            "build_company_names.broker_feed.fetch_scrips",
            lambda timeout=30.0: {
                "LUCK": {"name": "Lucky Cement Limited", "sector": "Cement",
                         "sector_slug": "cement"},
                "BLANK": {"name": "", "sector": "S", "sector_slug": "s"},
            },
        )
        result = crawl_names()
        assert result["names"]["LUCK"] == "Lucky Cement Limited"
        assert "BLANK" not in result["names"]
        assert result["failedSymbols"] == []


# ---------------------------------------------------------------------------
# Volume baselines (unchanged by the feed cutover)
# ---------------------------------------------------------------------------

from baselines import VolumeBaselines


@pytest.fixture
def baseline_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    return tmp_path / "volume_baselines.json"


class TestVolumeBaselines:
    def test_first_session_initializes(self, baseline_file):
        b = VolumeBaselines(path=baseline_file)
        b.record_session("2026-09-04", {"LUCK": (1_000_000.0, 5_000.0)})
        assert b.baseline_volume("LUCK") == 1_000_000.0
        assert b.baseline_days("LUCK") == 1

    def test_ema_update(self, baseline_file):
        b = VolumeBaselines(path=baseline_file)
        b.record_session("2026-09-04", {"LUCK": (1_000_000.0, 5_000.0)})
        b.record_session("2026-09-05", {"LUCK": (3_000_000.0, 15_000.0)})
        assert b.baseline_volume("LUCK") == pytest.approx(1_500_000.0)

    def test_reliable_after_min_days(self, baseline_file):
        b = VolumeBaselines(path=baseline_file)
        for day in range(1, 5):
            b.record_session(f"2026-09-0{day}", {"LUCK": (1_000_000.0, 5_000.0)})
        assert b.is_reliable("LUCK") is True

    def test_ratio_computed(self, baseline_file):
        b = VolumeBaselines(path=baseline_file)
        for day in range(1, 5):
            b.record_session(f"2026-09-0{day}", {"LUCK": (1_000_000.0, 5_000.0)})
        assert b.baseline_volume_ratio("LUCK", 500_000.0) == pytest.approx(0.5)

    def test_unknown_symbol_is_none(self, baseline_file):
        b = VolumeBaselines(path=baseline_file)
        assert b.baseline_volume_ratio("NOPE", 100.0) is None
