"""
Tests for the advanced-math library (v3.2.0) - only the z-score
helper survives the whitelist law.
"""

from __future__ import annotations

import pandas as pd
import pytest

from advanced_math import zscore_by_group


class TestZScore:
    def test_preserves_magnitude(self):
        # Two groups; in the second, one value is far beyond the other.
        values = pd.Series(
            [1.0, 2.0, 1.5, 1.2, 1.1, 100.0, 1.0, 1.1, 0.9, 1.2, 1.05, 1.15]
        )
        groups = pd.Series(["a"] * 6 + ["b"] * 6)
        out = zscore_by_group(values, groups, min_count=5)
        # The 100 in group a is ~2 sigma above its group: the logistic
        # maps that near (but not to) 1, and the rest of the group
        # sits below the 0.5 neutral.
        assert out.iloc[5] > 0.8
        assert out.iloc[1] < 0.5

    def test_small_group_is_neutral(self):
        values = pd.Series([1.0, 100.0])
        groups = pd.Series(["a", "a"])
        out = zscore_by_group(values, groups, min_count=5)
        # Fewer than min_count observations: neutral 0.5, never a
        # false extreme.
        assert out.iloc[0] == 0.5
        assert out.iloc[1] == 0.5

    def test_zero_variance_group_is_neutral(self):
        values = pd.Series([3.0, 3.0, 3.0, 3.0, 3.0])
        groups = pd.Series(["a"] * 5)
        out = zscore_by_group(values, groups, min_count=5)
        assert (out == 0.5).all()

    def test_grouped_independently(self):
        values = pd.Series([1.0, 2.0, 100.0, 200.0])
        groups = pd.Series(["a", "a", "b", "b"])
        out = zscore_by_group(values, groups, min_count=2)
        # Same relative position within each group.
        assert out.iloc[1] == pytest.approx(out.iloc[3])

    def test_nan_passthrough(self):
        values = pd.Series([1.0, None, 3.0, 2.0, 2.5, 1.5])
        groups = pd.Series(["a"] * 6)
        out = zscore_by_group(values, groups, min_count=5)
        assert pd.isna(out.iloc[1])
