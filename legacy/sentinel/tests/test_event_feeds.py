"""
Tests for the event-feature joins in build_kmiall_features.

v4.0.0: the news and announcements FETCHERS retired with
psxterminal.com (the parser tests left with them). The feature columns
stay: the engine still joins whatever data/news_sentiment.json and
data/announcements.json carry - neutral when the files are absent,
which is now their steady state unless the owner places files by hand.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from psx_core import paths

import build_kmiall_features as feats


# ---------------------------------------------------------------------------
# Feature-engine event joins
# ---------------------------------------------------------------------------

class TestEventFeatureJoins:
    def _frame(self):
        return pd.DataFrame({
            "symbol": ["LEUL", "ASL", "PLAIN"] * 2,
            "timestamp": pd.to_datetime(
                ["2026-09-04T05:30:00+00:00"] * 3
                + ["2026-09-04T05:30:05+00:00"] * 3
            ),
            "tradable": True,
            "feature_price_ok": True,
            "change_pct": [1.0, 0.5, 0.0] * 2,
        })

    def test_news_sentiment_joined(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        (tmp_path / "news_sentiment.json").write_text(json.dumps({
            "bySymbol": {"ASL": {"mentions": 2, "sentiment_sum": 1.0,
                                 "sentiment": 0.5, "headlines": []}},
        }), encoding="utf-8")
        (tmp_path / "announcements.json").write_text("{}", encoding="utf-8")

        df = self._frame()
        out = feats.add_event_features(df)
        asl = out[out["symbol"] == "ASL"].iloc[0]
        assert asl["news_sentiment_pct"] == pytest.approx(50.0)
        leul = out[out["symbol"] == "LEUL"].iloc[0]
        assert np.isnan(leul["news_sentiment_pct"])

    def test_announcement_flags_joined(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        (tmp_path / "news_sentiment.json").write_text("{}", encoding="utf-8")
        (tmp_path / "announcements.json").write_text(json.dumps({
            "bySymbol": {
                "PLAIN": {"count": 2, "is_unusual": 1, "titles": []},
            },
        }), encoding="utf-8")

        df = self._frame()
        out = feats.add_event_features(df)
        plain = out[out["symbol"] == "PLAIN"].iloc[0]
        assert plain["announcement_flag"] == 1.0
        assert plain["announcement_is_unusual"] == 1.0
        assert plain["announcement_count"] == 2

    def test_missing_files_dont_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
        df = self._frame()
        out = feats.add_event_features(df)
        assert "news_sentiment_pct" in out.columns
        assert out["news_sentiment_pct"].isna().all()
        assert "announcement_flag" in out.columns
        assert out["announcement_flag"].isna().all()
        assert "towatch_signal_count" not in out.columns
