"""
Tests for psx_core.frames - pandas helpers for session columns, grouping,
safe division, and boolean coercion.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from psx_core import frames, sessions


def _make_df(
    symbols=("ABOT",),
    timestamps=None,
    prices=None,
    sessions_override=None,
):
    """Minimal snapshot-shaped frame for testing frame operations."""
    if timestamps is None:
        timestamps = pd.to_datetime(["2026-09-02 04:35:00+00:00"] * 2)
    if prices is None:
        prices = [100.0, 101.0]

    rows = []
    for sym in symbols:
        for ts, price in zip(timestamps, prices):
            rows.append({"symbol": sym, "timestamp": ts, "price": price})

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# add_session_columns
# ---------------------------------------------------------------------------

class TestAddSessionColumns:
    def test_adds_trading_date_and_session_id(self):
        ts = pd.to_datetime([
            "2026-09-02 04:35:00+00:00",
            "2026-09-02 04:40:00+00:00",
        ])
        df = _make_df(timestamps=ts, prices=[100, 101])
        result = frames.add_session_columns(df)
        assert "trading_date" in result.columns
        assert "session_id" in result.columns
        assert result["trading_date"].iloc[0] == "2026-09-02"

    def test_raises_on_missing_timestamp_column(self):
        df = pd.DataFrame({"symbol": ["A"], "price": [1.0]})
        with pytest.raises(KeyError, match="timestamp"):
            frames.add_session_columns(df)

    def test_empty_frame_returns_empty_columns(self):
        df = pd.DataFrame(columns=["symbol", "timestamp", "price"])
        result = frames.add_session_columns(df)
        assert "trading_date" in result.columns
        assert "session_id" in result.columns
        assert len(result) == 0

    def test_friday_session_gap_creates_new_leg(self):
        """A gap > SESSION_GAP_SECONDS within one trading date splits the leg."""
        ts = pd.to_datetime([
            "2026-09-04 04:20:00+00:00",  # Fri morning ~09:20 PKT
            "2026-09-04 04:50:00+00:00",  # Fri morning ~09:50 PKT
            "2026-09-04 09:35:00+00:00",  # Fri afternoon ~14:35 PKT (after lunch)
        ])
        df = _make_df(timestamps=ts, prices=[100, 101, 102])
        result = frames.add_session_columns(df)
        session_ids = result["session_id"].unique()
        # Should have at least 2 legs on Friday
        assert len(session_ids) >= 2

    def test_does_not_mutate_original(self):
        ts = pd.to_datetime(["2026-09-02 04:35:00+00:00"])
        df = _make_df(timestamps=ts, prices=[100])
        original_cols = set(df.columns)
        frames.add_session_columns(df)
        assert set(df.columns) == original_cols


# ---------------------------------------------------------------------------
# session_groupby / day_groupby
# ---------------------------------------------------------------------------

class TestSessionGroupby:
    def test_requires_session_id(self):
        df = pd.DataFrame({"symbol": ["A"], "price": [1.0]})
        with pytest.raises(KeyError, match="session_id"):
            frames.session_groupby(df)

    def test_groups_by_symbol_and_session(self):
        ts = pd.to_datetime([
            "2026-09-02 04:35:00+00:00",
            "2026-09-02 04:40:00+00:00",
        ])
        df = _make_df(timestamps=ts, prices=[100, 101])
        df = frames.add_session_columns(df)
        grouped = frames.session_groupby(df)
        # Should have groups = number of unique (symbol, session_id)
        assert len(grouped) == df["session_id"].nunique()


class TestDayGroupby:
    def test_requires_trading_date(self):
        df = pd.DataFrame({"symbol": ["A"], "price": [1.0]})
        with pytest.raises(KeyError, match="trading_date"):
            frames.day_groupby(df)

    def test_groups_by_symbol_and_date(self):
        ts = pd.to_datetime([
            "2026-09-02 04:35:00+00:00",
            "2026-09-02 04:40:00+00:00",
        ])
        df = _make_df(timestamps=ts, prices=[100, 101])
        df = frames.add_session_columns(df)
        grouped = frames.day_groupby(df)
        assert len(grouped) == df["trading_date"].nunique()


# ---------------------------------------------------------------------------
# safe_divide
# ---------------------------------------------------------------------------

class TestSafeDivide:
    def test_normal_division(self):
        num = pd.Series([10.0, 20.0, 30.0])
        den = pd.Series([2.0, 4.0, 5.0])
        result = frames.safe_divide(num, den)
        pd.testing.assert_series_equal(result, pd.Series([5.0, 5.0, 6.0]))

    def test_zero_divisor_yields_nan(self):
        num = pd.Series([10.0, 20.0])
        den = pd.Series([0.0, 5.0])
        result = frames.safe_divide(num, den)
        assert np.isnan(result.iloc[0])
        assert result.iloc[1] == 4.0

    def test_nan_in_denominator(self):
        num = pd.Series([10.0, 20.0])
        den = pd.Series([np.nan, 5.0])
        result = frames.safe_divide(num, den)
        assert np.isnan(result.iloc[0])

    def test_no_inf_in_output(self):
        num = pd.Series([1.0, -1.0, 0.0])
        den = pd.Series([0.0, 0.0, 1.0])
        result = frames.safe_divide(num, den)
        assert not np.any(np.isinf(result))


# ---------------------------------------------------------------------------
# coerce_bool
# ---------------------------------------------------------------------------

class TestCoerceBool:
    def test_already_bool(self):
        s = pd.Series([True, False, True])
        result = frames.coerce_bool(s)
        assert result.dtype == bool
        pd.testing.assert_series_equal(result, s)

    def test_string_true_false(self):
        s = pd.Series(["True", "False", "true", "false"])
        result = frames.coerce_bool(s)
        assert result.dtype == bool
        assert result.tolist() == [True, False, True, False]

    def test_numeric_0_1(self):
        s = pd.Series([1, 0, 1.0, 0.0])
        result = frames.coerce_bool(s)
        assert result.dtype == bool
        assert result.tolist() == [True, False, True, False]

    def test_nan_becomes_false(self):
        s = pd.Series([True, None, "False"])
        result = frames.coerce_bool(s)
        assert result.dtype == bool
        assert result.tolist() == [True, False, False]

    def test_object_bool(self):
        s = pd.Series([True, False, None])
        result = frames.coerce_bool(s)
        assert result.dtype == bool
