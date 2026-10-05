"""
PSX KMIALL BOT
Advanced math layer (v3.2.0, the whitelist law).

One helper survives: the cross-sectional z-score with logistic
squashing that turns raw tape measurements into comparable (0, 1)
blend components.

RETIRED by owner's orders (v3.1.1 and v3.2.0): the Kalman trend
filter, Parkinson volatility, Garman-Klass volatility, and the
pairwise-correlation helpers. No production path uses them; the
library keeps only what the whitelisted rulebook needs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Z-scores
# ---------------------------------------------------------------------------

def zscore_by_group(
    values: pd.Series,
    groups: pd.Series,
    *,
    min_count: int = 20,
) -> pd.Series:
    """
    Cross-sectional z-score within each group, mapped through the
    logistic function into (0, 1).

    A group with fewer than min_count valid observations yields 0.5 for
    every member (neutral, mirroring the rank engine's MIN_CROSS_SECTION
    behaviour) rather than a false extreme.

    Parameters
    ----------
    values : Series
        The measurement to standardize.
    groups : Series
        Group key per row (e.g. the snapshot timestamp).
    """
    def _z(chunk: pd.Series) -> pd.Series:
        count = chunk.notna().sum()
        if count < min_count:
            return pd.Series(0.5, index=chunk.index)
        mean = chunk.mean()
        std = chunk.std(ddof=1)
        if not np.isfinite(std) or std < 1e-12:
            return pd.Series(0.5, index=chunk.index)
        z = (chunk - mean) / std
        # Logistic squashing: z=0 -> 0.5, z=+2 -> 0.88, z=-2 -> 0.12.
        # Keeps outliers from pinning every other symbol at the median.
        return (1.0 / (1.0 + np.exp(-np.clip(z, -10, 10))))

    return values.groupby(groups, sort=False).transform(_z)
