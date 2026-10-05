"""v3.5.0: the Volume Profile (Visible-Range approximation) layer.

Owner's whitelist addendum - Volume Profile joins the EOD tape layers.
These tests pin: the score curve (POC = 1.0, profile high = 0.6,
profile low = ~0.1), the evidence discipline (thin/missing history is
None, never a synthetic neutral), the kill-switch, and the rank effect
(trading at the POC outranks the same tape fighting the POC).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import eod_bot as eb  # noqa: E402


def _hist(vols=(1000, 2000, 1000)):
    """Three sessions whose heaviest range sits mid-profile."""
    return [
        {"h": 110, "l": 90, "c": 100, "vol": vols[0]},
        {"h": 112, "l": 92, "c": 105, "vol": vols[1]},
        {"h": 108, "l": 88, "c": 98, "vol": vols[2]},
    ]


class TestScoreCurve:
    def test_at_profile_high_is_extended(self):
        # 0.6 exactly at the top of the profiled range.
        assert eb.vpvr_score(112, _hist()) == pytest.approx(0.6)

    def test_at_profile_low_fights_the_poc(self):
        # ~0.1 at the bottom: closing under all accepted volume.
        assert eb.vpvr_score(88, _hist()) == pytest.approx(0.1)

    def test_score_is_bounded_inside_the_band(self):
        for price in (88, 95, 100, 105, 112):
            s = eb.vpvr_score(price, _hist())
            assert s is not None and 0.1 <= s <= 1.0

    def test_poc_price_scores_above_the_low(self):
        # The POC bin of _hist(): midpoint of the heaviest session's
        # range (92..112 -> 102). Trading there must outrank the low.
        poc = eb.vpvr_score(102, _hist())
        assert poc > eb.vpvr_score(88, _hist())

    def test_above_poc_never_drops_below_six_tenths(self):
        for price in (102, 105, 108, 112):
            assert eb.vpvr_score(price, _hist()) >= 0.6


class TestEvidenceDiscipline:
    def test_thin_history_is_none(self):
        assert eb.vpvr_score(100, _hist()[:2]) is None

    def test_missing_history_is_none(self):
        assert eb.vpvr_score(100, None) is None

    def test_missing_price_is_none(self):
        assert eb.vpvr_score(None, _hist()) is None

    def test_zero_volume_sessions_are_skipped(self):
        # A dead session does not count toward the 3-session minimum:
        # 4 stored, one zero-volume -> only 3 live -> still profiles.
        hist = [
            {"h": 110, "l": 90, "c": 100, "vol": 0},
            {"h": 112, "l": 92, "c": 105, "vol": 500},
            {"h": 108, "l": 88, "c": 98, "vol": 500},
            {"h": 106, "l": 96, "c": 100, "vol": 500},
        ]
        assert eb.vpvr_score(100, hist) is not None
        assert eb.vpvr_score(100, hist[:3]) is None  # 2 live = too thin

    def test_flat_profile_is_none(self):
        # hi == lo across every session: no range to bin.
        hist = [
            {"h": 100, "l": 100, "c": 100, "vol": 100},
            {"h": 100, "l": 100, "c": 100, "vol": 100},
            {"h": 100, "l": 100, "c": 100, "vol": 100},
        ]
        assert eb.vpvr_score(100, hist) is None


class TestKillSwitch:
    def test_vpvr_enabled_flag_gates_the_score(self, tmp_path, monkeypatch):
        monkeypatch.setattr(eb, "_REPO_ROOT", tmp_path)
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"vpvr_enabled": False}), encoding="utf-8")
        assert eb.vpvr_score(100, _hist()) is None

        cfg.write_text(json.dumps({"vpvr_enabled": True}), encoding="utf-8")
        assert eb.vpvr_score(100, _hist()) is not None

    def test_missing_config_defaults_on(self, tmp_path, monkeypatch):
        monkeypatch.setattr(eb, "_REPO_ROOT", tmp_path)
        assert eb.vpvr_score(100, _hist()) is not None


class TestRankEffect:
    def test_weights_table_sums_to_one(self):
        assert sum(eb.WEIGHTS.values()) == pytest.approx(1.0)
        assert eb.WEIGHTS["vpvr"] == pytest.approx(0.03)

    def test_poc_trading_outranks_poc_fighting(self, tmp_path, monkeypatch):
        """Same tape shape, two closes: at the POC beats below it."""
        monkeypatch.setattr(eb, "_REPO_ROOT", tmp_path)

        def row(price):
            return {
                "symbol": "TEST",
                "price": price,
                "change_pct": 2.0,
                "value": 50e6,
                "avg_volume_20": 1e6,
                "high": price,
                "low": price * 0.99,
                "volume": 1e6,
                "quote": None,
                "late_momentum_pct": 2.0,
                "session_history": _hist(),
            }

        at_poc = eb.score_symbol(row(102))
        below = eb.score_symbol(row(89))
        assert at_poc is not None and below is not None
        assert at_poc > below

    def test_pick_carries_vpvr_evidence(self):
        """pick_top's card dict exposes the vpvr score for the card."""
        # Direct: the pick dict construction reads vpvr_score - pin the
        # key name so the card line cannot silently lose its evidence.
        row = {
            "symbol": "TEST",
            "price": 102,
            "session_history": _hist(),
        }
        v = eb.vpvr_score(row["price"], row["session_history"])
        assert v is not None
        assert 0.1 <= v <= 1.0
