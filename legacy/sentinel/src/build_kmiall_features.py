"""
KMIALL feature engine v1.

What this replaces
------------------
The previous file was not a program. It was a 390-line string literal,
`script = r'''...'''`, followed by:

    out = Path("/mnt/data/build_kmiall_features.py")
    out.write_text(script, encoding="utf-8")

`/mnt/data` is a Linux sandbox path. On Windows the write failed, so running
the file produced no engine and no features -- the embedded engine had never
executed once, and `data/processed/kmiall_features_v1.csv` did not exist.

Beyond being unrunnable, the embedded engine had eight substantive defects.
All are fixed here:

F1  Ranked every symbol at a timestamp, including suspended ones.
    `df.groupby("timestamp")[col].transform(pct_rank)` ranked all 311 rows.
    Suspended symbols carry a stale price, so their momentum is exactly 0 and
    they landed in the middle of the momentum percentile, displacing real
    movers upward and downward around them. 34 of 311 symbols are suspended in
    the archived data -- 11% of every cross-section was noise. Ranking now
    happens only over rows that pass `tradable`.

F2  Nulled scores for `~quote_available` but not for suspended-with-quote.
    A suspended symbol still publishes a quote, so it kept a composite score.
    The gate is now `tradable`.

F3  `fillna(0)` on percentage inputs. `short_term_price_score` and
    `momentum_score_raw` substituted 0 for missing momentum. Zero is not
    neutral for a signed, clipped score -- it is better than every decliner.
    A symbol with no data outranked a symbol that was genuinely falling.
    Missing inputs now stay missing and the blend renormalizes over what is
    present.

F4  Ranked a clipped value. `relative_volume_score` clipped relative volume at
    10, then ranked it; every symbol above 10x tied at the same percentile.
    The rank now uses the unclipped value; the clip survives only where it
    belongs, inside the linear `liquidity_score`.

F5  `liquidity_score_raw` treated an unknown relative volume as 0, the worst
    possible value, so every row before the expanding baseline sat at the
    bottom of the liquidity rank. Substituting NaN instead is not enough
    either: liquidity was a linear blend of a trade count and a share volume,
    magnitudes apart, so a row that lost one input was not comparable to a row
    that kept it. Liquidity is now blended in rank space, where every input is
    a percentile in [0, 1] and dropping one is safe.

F6  `pct_rank`'s docstring claimed a single valid observation gets 0.5. It gets
    1.0: rank 1 of count 1. A percentile over one or two names is meaningless
    either way, so a cross-section thinner than MIN_CROSS_SECTION now yields a
    neutral 0.5 and says so, instead of manufacturing a false extreme.

F7  `volume_acceleration` was `volume_1m / average_volume_1m`, which is the
    definition of `relative_volume_1m` in the dataset builder. It was a
    duplicate column under a second name. Removed.

F8  Silent weight redistribution. Renormalizing over present components is
    right per row, but it also meant a component with *zero* coverage across
    the entire dataset vanished without a word: `momentum_5m_pct` is 0%
    covered on 4.9 minutes of data, so 18% of the composite silently
    redistributed to the other eight and the score still looked complete.
    Every row now carries `score_weight_coverage`, the fraction of intended
    weight actually behind its score, and a component that is globally dead is
    reported as a DEAD COMPONENT in the report and the summary JSON.

F9  Relative volume was double-counted. It carried 0.18 of the composite in
    its own right and another 0.45 of liquidity's 0.10, so its true weight was
    0.225 while the published table said 0.18. Liquidity now measures depth
    only -- how much is trading -- and the surge relative to baseline is
    carried once, by rank_relative_volume.

`safe_div` also returned inf for a scalar zero divisor -- its guard only fired
for Series. All division goes through `frames.safe_divide`.

This is a feature layer. It produces no BUY/SELL signal and places no orders.

Usage
-----
    python src/build_kmiall_features.py
    python src/build_kmiall_features.py --top 30
    python src/build_kmiall_features.py --input data/processed/kmiall_intraday.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import frames, paths

# A percentile over a handful of names says nothing. Below this many valid
# observations in a timestamp's cross-section, every rank is set to neutral.
MIN_CROSS_SECTION = 20

# Classical technical-indicator windows (v0.17.0, adaptive v0.17.1).
# The collector cadence is no longer fixed: the cloud pass polls every
# ~15 minutes while a local collector runs at 5 seconds - so windows
# are sized to the BARS THAT EXIST per (session, symbol), bounded by
# the dense-data values. A symbol needs >= ~7 polls before any
# indicator appears; before that the columns stay NaN (honest
# absence - the blend renormalizes and the vetoes pass).
TECH_WINDOW = 120   # cost cap on the trailing chunk (dense local data)

# Composite weights. Rebalanced to sum to exactly 1.00 (blend()
# renormalises regardless, but the published table should not lie).
# The ToWatch event layer was REMOVED on 2026-09-14 - it was a
# third-party watchlist, not a measured signal, and its refresh was
# the site of two live crashes that morning.
COMPONENTS: dict[str, float] = {
    "rank_momentum_1m": 0.09,
    "rank_momentum_5m": 0.03,
    "rank_short_term_price": 0.05,
    "rank_relative_volume": 0.11,
    "rank_liquidity": 0.06,
    "rank_book_strength": 0.05,
    "rank_range_position": 0.02,
    "rank_spread_quality": 0.02,
    "rank_trade_activity": 0.02,
    "rank_news_sentiment_pct": 0.03,
    "rank_announcement_flag": 0.02,
    "rank_unusual_notice": 0.02,
    # PSX trend-following additions.
    "rank_relative_strength": 0.07,
    "rank_volume_trend": 0.04,
    "rank_circuit_breaker": 0.05,
}

# Source column ranked into each component. rank_liquidity is absent on
# purpose: it is blended from the two depth ranks below, in rank space.
# The ToWatch event components are ALSO absent: they are direct
# magnitude transforms (see add_event_features), not cross-sectional
# ranks - a 5.2x surge is 5.2x regardless of what other stocks did
# today, and a breakdown must score LOW for a long-only book.
RANK_SOURCES: dict[str, str] = {
    "rank_momentum_1m": "momentum_1m_pct",
    "rank_momentum_5m": "momentum_5m_pct",
    "rank_short_term_price": "short_term_price_score",
    "rank_relative_volume": "relative_volume_1m",
    "rank_trades_depth": "trades_depth",
    "rank_volume_depth": "volume_depth",
    "rank_book_strength": "book_strength",
    "rank_range_position": "range_position_score",
    "rank_spread_quality": "spread_quality",
    "rank_trade_activity": "trade_activity_score",
    "rank_news_sentiment_pct": "news_sentiment_pct",
    "rank_announcement_flag": "announcement_flag",
    "rank_unusual_notice": "announcement_is_unusual",
    # PSX trend-following: relative strength vs KSE-100 and volume trend.
    "rank_relative_strength": "relative_strength_vs_index",
    "rank_volume_trend": "volume_trend_confirmation",
    # PSX circuit breaker: upper circuit is the strongest
    # trend signal. A stock at/near upper circuit is
    # overwhelmed by buying pressure regardless of volume.
    "rank_circuit_breaker": "circuit_breaker_pct",
}

# What each composite component is derived from, for the coverage report.
# The ToWatch event components are direct magnitude transforms, listed
# here explicitly since they have no RANK_SOURCES entry.
COMPONENT_SOURCES: dict[str, str] = {
    **{name: source for name, source in RANK_SOURCES.items()},
    "rank_liquidity": "trades_depth + volume_depth (rank space)",
}

# ---------------------------------------------------------------------------
# Advanced-math components (src/advanced_math.py) and their weights.
#
# The MASTER composite is a z-score blend: each component below is
# standardised cross-sectionally per timestamp (magnitude preserved,
# unlike percentile ranks) then weighted and squashed into (0, 1).
# It runs ALONGSIDE feature_rank_score_adjusted as master_score; the
# decision engine prefers it when present. Weights sum to 1.0.
# ---------------------------------------------------------------------------
from advanced_math import (  # noqa: E402
    zscore_by_group,
)
from technical_indicators import (  # noqa: E402
    ema_alignment_score,
    rsi,
    rsi_position_score,
)

# NOTE (v0.17.0): weights sum to EXACTLY 1.0 (the table had drifted to
# 1.08 before - harmless because blend() renormalizes, but a broken
# invariant; rescaled proportionally when the four classical
# technical-indicator components joined).
MASTER_COMPONENTS: dict[str, float] = {
    # v0.18.2 RE-WEIGHTING - fitted on the leak-free IC audit (450
    # candidates, 7 sessions, walk-forward features, real cost stack).
    # The old table tilted the composite toward momentum extremes:
    # kalman carried the largest weight (0.1105) with IC -0.20, gap
    # chasing -0.27, short-term extension -0.19 - the top of the old
    # ranking systematically bought the day's most extended names,
    # which mean-revert into the stop on PSX. The features that
    # actually predicted net winners: VWAP position (+0.32), volume
    # trend (+0.27), relative volume (+0.25), trade activity (+0.21),
    # spread quality (+0.17). Composite IC: +0.124 -> +0.423.
    # In-sample caveat: refit at ~20 live outcomes.
    # v3.1.1: z_kalman_trend and z_bollinger_position retired by
    # owner's order; their 3% mass redistributed to the two top tape
    # components (vwap, volume trend) so the table still sums to 1.0.
    # v3.2.0: the volatility/VR estimators (z_variance_ratio 0.05,
    # z_parkinson_vol 0.01, z_gk_vol 0.01) are retired by owner's
    # order; their 7% redistributed to the top tape components
    # (vwap, volume trend, relative volume). Table still sums to 1.0.
    "z_vwap_ratio": 0.25,
    "z_volume_trend": 0.20,
    "z_relative_volume_1m": 0.15,
    "z_trade_activity": 0.10,
    "z_spread_quality": 0.08,
    "z_orb": 0.05,
    "z_atr": 0.03,
    "z_vpvr": 0.0,
    "z_relative_strength": 0.03,
    "z_momentum_1m": 0.02,
    "z_book_strength": 0.02,
    "z_rsi_position": 0.02,
    "z_baseline_volume_ratio": 0.01,
    "z_short_term_price": 0.01,
    "z_sector_breadth": 0.01,
    "z_sector_flow": 0.01,
    "z_gap": 0.005,
    "z_circuit_breaker": 0.003,
    "z_ema_alignment": 0.002,
}

# A score built on less than this fraction of its intended weight is too thin
# to compare against one built on most of it. Recorded, not enforced.
MIN_WEIGHT_COVERAGE = 0.60

NUMERIC_COLUMNS = [
    "price", "change", "change_pct", "change_fraction", "volume", "trades",
    "value", "high", "low", "bid", "ask", "bid_volume", "ask_volume",
    "spread", "spread_pct", "price_position_range", "distance_from_high_pct",
    "distance_from_low_pct", "price_change_pct_5s", "momentum_1m_pct",
    "momentum_5m_pct", "volume_delta", "new_volume", "trades_delta",
    "new_trades", "volume_reset_or_anomaly", "trades_reset_or_anomaly",
    "volume_1m", "volume_5m", "trades_1m", "trades_5m",
    "average_volume_1m", "relative_volume_1m", "trade_value_per_trade",
    "order_book_imbalance", "breadth_advancers", "breadth_decliners",
    "breadth_unchanged", "breadth_total", "breadth_ratio", "breadth_pct",
    "news_sentiment_pct",
    "announcement_flag",
    "announcement_is_unusual",
    "announcement_count",
    # PSX trend-following features.
    "relative_strength_vs_index",
    "volume_trend_confirmation",
    "circuit_breaker_pct",
    # Classical technical indicators (v0.17.0).
    "rsi14",
    "ema_alignment",
]

BOOLEAN_COLUMNS = [
    "quote_available", "is_open", "tradable", "bid_available",
    "ask_available", "high_available", "low_available",
    "usable_price", "usable_book", "usable_momentum",
    "volume_reset_or_anomaly", "trades_reset_or_anomaly",
]

REQUIRED_COLUMNS = [
    "timestamp", "symbol", "trading_date", "session_id",
    "quote_available", "tradable", "price",
]


class FeatureError(RuntimeError):
    """Raised when the input dataset cannot support the feature layer."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def coerce_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Coerce a freshly-built dataset frame to its real dtypes.

    The tail of load_dataset, split out so the replay harness can run
    the identical coercion on an in-memory frame instead of round-
    tripping through a CSV once per replay step.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise FeatureError(
            "Input dataset is missing required columns: "
            + ", ".join(missing)
            + "\nRebuild it with src/build_intraday_dataset.py."
        )

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    if df["timestamp"].isna().any():
        # Unparseable timestamps would form no groupby key at all, so those
        # rows would silently receive NaN ranks instead of failing.
        raise FeatureError(
            f"{int(df['timestamp'].isna().sum())} rows have an unparseable "
            "timestamp. The dataset is corrupt; rebuild it."
        )

    for column in NUMERIC_COLUMNS:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    for column in BOOLEAN_COLUMNS:
        if column in df.columns:
            df[column] = frames.coerce_bool(df[column])

    return df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)


def load_dataset(path: Path) -> pd.DataFrame:
    """Read the intraday dataset and coerce it back to its real dtypes."""
    if not path.exists():
        raise FeatureError(
            f"Input dataset not found: {path}\n"
            "Run: python src/build_intraday_dataset.py"
        )

    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    return coerce_dtypes(df)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def blend(
    df: pd.DataFrame,
    weights: dict[str, float],
) -> tuple[pd.Series, pd.Series]:
    """
    Weighted mean over the components present on each row.

    Returns (value, available_weight). A row with no component present gets
    NaN, never 0 -- fixes F3, where substituting 0 for a missing signed
    percentage ranked a symbol with no data above every genuine decliner.
    """
    total: pd.Series | None = None
    available: pd.Series | None = None

    for column, weight in weights.items():
        values = df[column]
        contribution = values.fillna(0.0) * weight
        present = values.notna().astype(float) * weight

        total = contribution if total is None else total + contribution
        available = present if available is None else available + present

    assert total is not None and available is not None
    return frames.safe_divide(total, available), available


def cross_sectional_rank(
    df: pd.DataFrame,
    source_column: str,
    eligible: pd.Series,
) -> pd.Series:
    """
    Percentile rank of `source_column` within each timestamp.

    Only `eligible` rows take part, so a suspended symbol neither receives a
    rank nor shifts anyone else's (F1). A cross-section with fewer than
    MIN_CROSS_SECTION valid observations yields a neutral 0.5 rather than the
    false extremes a two-name percentile produces (F6).
    """
    values = df[source_column].where(eligible)
    grouped = values.groupby(df["timestamp"], sort=False)

    ranks = grouped.rank(pct=True, method="average")
    counts = grouped.transform("count")

    thin = counts < MIN_CROSS_SECTION
    return ranks.where(~thin, 0.5).where(values.notna())


# ---------------------------------------------------------------------------
# Feature blocks
# ---------------------------------------------------------------------------

def add_quality_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-row usability. Every gate starts from `tradable`, so a suspended
    symbol is never eligible for anything (F2).
    """
    df["feature_price_ok"] = df["tradable"] & df["usable_price"]

    df["feature_book_ok"] = (
        df["feature_price_ok"]
        & df["usable_book"]
        & df["bid"].gt(0)
        & df["ask"].gt(0)
        & df["ask"].ge(df["bid"])
    )

    df["feature_range_ok"] = (
        df["feature_price_ok"]
        & df["high_available"]
        & df["low_available"]
        & df["high"].gt(df["low"])
        & df["price"].ge(df["low"])
        & df["price"].le(df["high"])
    )

    df["feature_spread_ok"] = (
        df["feature_book_ok"]
        & df["spread_pct"].notna()
        & df["spread_pct"].ge(0)
    )

    return df


def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Momentum and short-term price action, on tradable rows only."""
    ok = df["feature_price_ok"]

    df["momentum_1m_clipped"] = df["momentum_1m_pct"].where(ok).clip(-5, 5)
    df["momentum_5m_clipped"] = df["momentum_5m_pct"].where(ok).clip(-8, 8)

    # Renormalized, not fillna(0): with momentum_5m at 0% coverage this is
    # momentum_1m alone, which is the truth, rather than half a signal diluted
    # toward a fabricated zero (F3).
    df["momentum_score"], df["momentum_score_weight"] = blend(
        df,
        {"momentum_1m_clipped": 0.55, "momentum_5m_clipped": 0.45},
    )

    df["tick_change_clipped"] = df["price_change_pct_5s"].where(ok).clip(-2, 2)
    df["day_change_clipped"] = df["change_pct"].where(ok).clip(-10, 10)

    df["short_term_price_score"], _ = blend(
        df,
        {"tick_change_clipped": 0.60, "day_change_clipped": 0.40},
    )

    df["range_position_score"] = (
        df["price_position_range"].where(df["feature_range_ok"]).clip(0, 1)
    )

    return df


def add_volume_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Activity and liquidity.

    `volume_acceleration` from the old engine is gone: it computed
    volume_1m / average_volume_1m, which is exactly how the dataset builder
    defines relative_volume_1m (F7).
    """
    ok = df["feature_price_ok"]

    # Ranked unclipped so the top tail keeps its order (F4).
    df["relative_volume_1m"] = df["relative_volume_1m"].where(ok)

    # v3.5.0 - Volume Profile Visible Range (the owner's order). For each
    # (trading_date, symbol) window: bucket the window's ticks into price
    # bins, sum the volume per bin, and score where the CURRENT price sits
    # inside that profile - at/above the point of control (the heaviest-
    # traded price) is institutional acceptance; far below it is churn.
    # Score is (0, 1]: 1.0 at the POC, falling linearly to the profile's
    # low tail. This is the classic VPVR 'visible range' read: the
    # profile covers exactly the trailing window we can see.
    df["vpvr_score"] = np.nan

    df["trade_activity_score"] = (
        df["trades_1m"].where(ok).clip(lower=0)
        + 0.5 * df["trades_5m"].where(ok).clip(lower=0)
    )

    # Liquidity is depth: how much is actually trading. The surge in volume
    # relative to its own baseline is a separate thing, already carried at 18%
    # by rank_relative_volume. The old engine put relative volume inside
    # liquidity as well, at 0.45 of its 0.10, so relative volume really
    # weighed 0.225 while the weights table said 0.18 (F9). Removed, and the
    # remaining 0.30/0.25 renormalized to 0.55/0.45 so liquidity is unchanged
    # in scale.
    df["trades_depth"] = df["trades_1m"].where(ok).clip(lower=0)
    df["volume_depth"] = df["volume_1m"].where(ok).clip(lower=0)

    return df


def add_book_features(df: pd.DataFrame) -> pd.DataFrame:
    """Order-book strength and spread quality."""
    df["book_strength"] = (
        df["order_book_imbalance"].where(df["feature_book_ok"]).clip(-1, 1)
    )

    # Tighter is better, mapped into (0, 1].
    df["spread_quality"] = (
        1.0 / (1.0 + df["spread_pct"].where(df["feature_spread_ok"]).clip(0, 20))
    )

    return df


def add_market_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Breadth-derived market state, the input to the strategy's market filter.

    Breadth counts OPEN symbols only -- the dataset builder excludes suspended
    ones, which previously pinned a constant bloc of fake advancers and
    decliners into every reading.
    """
    df["market_breadth_strength"] = df["breadth_pct"].clip(0, 100) / 100.0

    df["market_net_breadth"] = frames.safe_divide(
        df["breadth_advancers"] - df["breadth_decliners"],
        df["breadth_total"],
    )

    df["market_broadly_weak"] = (
        df["breadth_decliners"].gt(df["breadth_advancers"])
        & df["breadth_decliners"].ge(0.65 * df["breadth_total"])
    ).fillna(False)

    df["market_broadly_strong"] = (
        df["breadth_advancers"].gt(df["breadth_decliners"])
        & df["breadth_advancers"].ge(0.65 * df["breadth_total"])
    ).fillna(False)

    return df


# ---------------------------------------------------------------------------
# Advanced features - sector context, baselines, and the z-score master score
# ---------------------------------------------------------------------------

def load_sector_context(
) -> tuple[dict[str, str], dict[str, float], dict[str, dict[str, float]]]:
    """
    Load the symbol->sector map, the per-sector foreign net flow, and
    the full investor x sector matrix (v0.10.0).

    All are one-off fetch products (build_sector_map.py,
    fetch_foreign_flow.py). Missing files degrade to empty dicts and
    the sector components stay neutral, which the coverage report
    shows as dead weight rather than a crash.

    The matrix is keyed {investor: {sector_display_name: net_usd}};
    per-sector components may read ANY investor class's view (e.g.
    Mutual Funds net into Cement) - "which institutions are pumping
    and dumping what".
    """
    import json as _json

    symbol_to_sector: dict[str, str] = {}
    sector_flow: dict[str, float] = {}
    flow_matrix: dict[str, dict[str, float]] = {}

    sector_map_path = paths.DATA_DIR / "sector_map.json"
    if sector_map_path.exists():
        try:
            raw = _json.loads(sector_map_path.read_text(encoding="utf-8"))
            symbol_to_sector = raw.get("symbolToSector", {}) or {}
        except (json.JSONDecodeError, OSError):
            pass

    flow_path = paths.DATA_DIR / "foreign_flow.json"
    if flow_path.exists():
        try:
            raw = _json.loads(flow_path.read_text(encoding="utf-8"))
            sector_flow = raw.get("foreignNetBySectorUsd", {}) or {}
            flow_matrix = raw.get("netMatrixUsd", {}) or {}
        except (json.JSONDecodeError, OSError):
            pass

    return symbol_to_sector, sector_flow, flow_matrix


def load_event_context() -> tuple[dict, dict]:
    """
    Load the two event-feed datasets:

      news_sentiment.json   - per-symbol headline sentiment [-1, +1]
      announcements.json    - per-symbol notice flags (count, unusual)

    Missing files degrade to empty dicts; their components report as
    missing weight in the coverage tables instead of crashing.
    """
    def _load(name: str, key: str) -> dict:
        path = paths.DATA_DIR / name
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            data = raw.get(key, {})
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    return (
        _load("news_sentiment.json", "bySymbol"),
        _load("announcements.json", "bySymbol"),
    )


# Map the sector slug from the map file to the display name used in the
# FIPI/LIPI table. Both derive from the same site taxonomy.
_SECTOR_SLUG_TO_FLOW_NAME = {
    "cement": "Cement",
    "commercial-banks": "Commercial Banks",
    "technology-and-communication": "Technology and Communication",
    "oil-and-gas-exploration-companies": "Oil and Gas Exploration Companies",
    "oil-and-gas-marketing-companies": "Oil and Gas Marketing Companies",
    "power-generation-and-distribution": "Power Generation and Distribution",
    "food-and-personal-care-products": "Food and Personal Care Products",
    "textile-composite": "Textile Composite",
    "fertilizer": "Fertilizer",
    "automobile-assembler": "Auto & Allied",
    "pharmaceuticals": "Pharmaceuticals",
    "insurance": "Insurance",
    "engineering": "Engineering",
    "chemical": "Chemical",
    "refinery": "Refinery",
    "transport": "Transport",
    "paper-board-and-packaging": "Paper & Packaging",
    "miscellaneous": "Miscellaneous",
}

# The remaining sectors on the site have no direct FIPI/LIPI row (the
# table aggregates them into "All other Sectors"); their flow reads as
# neutral 0.0 rather than missing, because no-news IS the news there.


def add_sector_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Join sector context onto each row:

      sector                      -- the symbol's sector slug
      sector_breadth              -- fraction of this sector's KMIALL
                                      members advancing at this timestamp
      sector_net_flow_usd         -- FIPI/LIPI net foreign flow of the
                                      sector (slow, per-session)
      sector_money_flow_pct       -- WHERE TODAY'S RUPEES ARE GOING,
                                      live: the sector's share of the
                                      whole market's traded value in
                                      the recent window, versus that
                                      sector's typical share. > 1 =
                                      money is pouring into this
                                      sector NOW; < 1 = it is being
                                      avoided. Computed per timestamp
                                      from cumulative `value` deltas
                                      (causal: each timestamp's flow
                                      uses only value printed up to
                                      it), so a replay slice at any
                                      moment sees exactly what a live
                                      rebuild saw.
    """
    symbol_to_sector, sector_flow, flow_matrix = load_sector_context()

    if symbol_to_sector:
        df["sector"] = df["symbol"].map(symbol_to_sector).fillna("unknown")
    else:
        df["sector"] = "unknown"

    # --- Live sector money flow (per timestamp, causal) --------------
    # value is cumulative per day. Per (symbol, trading_date), take the
    # first-difference across timestamps; a timestamp's sector flow =
    # sum of its members' value deltas. The window is the timestamp
    # itself (each poll is ~5s of new prints): flow share per sector
    # per poll, then an exponentially-weighted mean over recent polls
    # gives the "where is money going NOW" read without spanning a
    # session boundary (grouped per trading_date).
    if "value" in df.columns and df["feature_price_ok"].any():
        try:
            v = pd.to_numeric(df["value"], errors="coerce")
            by_sym_day = df.groupby(
                ["symbol", "trading_date"], sort=False
            )
            # Shift within each (symbol, day) chain: value delta at
            # each timestamp vs the previous print, NaN-safe.
            prev_v = by_sym_day["value"].shift(1)
            flow = (v - pd.to_numeric(prev_v, errors="coerce")).clip(lower=0)
            flow = flow.where(flow.notna() & (flow < 1e12))
            work = pd.DataFrame({
                "timestamp": df["timestamp"],
                "trading_date": df["trading_date"],
                "sector": df["sector"],
                "flow": flow,
            }).dropna(subset=["flow"])
            if not work.empty:
                # Per timestamp: each sector's share of total flow.
                grp = work.groupby(
                    ["trading_date", "timestamp", "sector"], sort=False
                )["flow"].sum().rename("sector_flow")
                totals = work.groupby(
                    ["trading_date", "timestamp"], sort=False
                )["flow"].sum().rename("total_flow")
                shares = (
                    grp / totals
                ).rename("share").reset_index()
                # EWMA of each sector's share across the day's polls,
                # recent polls weighted ~3x heavier. Typical share =
                # the sector's member count / universe (a sector with
                # 40 of 300 names "typically" trades ~13% of value;
                # a 25% share means real concentration).
                shares = shares.sort_values("timestamp")
                ewma = (
                    shares.groupby(
                        ["trading_date", "sector"], sort=False
                    )["share"]
                    .transform(lambda s: s.ewm(alpha=0.1).mean())
                )
                shares["ewma_share"] = ewma
                # Latest EWMA share per sector, and the sector's
                # "typical" share = member count / universe size (a
                # sector with 40 of 300 names typically trades ~13%
                # of value; a 25% EWMA share is real concentration).
                sec_ewma = shares.groupby("sector")["ewma_share"].last()
                typical = (
                    df.groupby("sector")["symbol"].nunique()
                    / df["symbol"].nunique()
                )
                # Map each ROW to its sector's flow ratio (the row's
                # sector, not its symbol - sec_ratio is keyed by
                # sector slug).
                sec_ratio = sec_ewma / typical.reindex(sec_ewma.index).replace(0, np.nan)
                df["sector_money_flow_pct"] = df["sector"].map(
                    sec_ratio.to_dict()
                )
            else:
                df["sector_money_flow_pct"] = np.nan
        except Exception:
            df["sector_money_flow_pct"] = np.nan
    else:
        df["sector_money_flow_pct"] = np.nan

    # Sector breadth: per timestamp, fraction of tradable members with
    # change_pct > 0. Computed from the frame itself, no extra fetch.
    # Factorized join: map timestamp and sector to integer codes once,
    # then a single groupby means lookup - no per-row Python, no
    # tz-aware merge fragility.
    advancing = df["change_pct"].gt(0) & df["tradable"]
    df["_adv"] = advancing.astype(float)

    ts_codes, _ = pd.factorize(df["timestamp"], sort=False)
    sector_codes, sector_values = pd.factorize(df["sector"], sort=False)
    composite_key = ts_codes.astype("int64") * (len(sector_values) + 1) + sector_codes
    df["_key"] = composite_key

    key_means = df.groupby("_key", sort=False)["_adv"].mean()
    df["sector_breadth"] = df["_key"].map(key_means)
    df["sector_breadth"] = pd.to_numeric(df["sector_breadth"], errors="coerce")
    df.drop(columns=["_adv", "_key"], inplace=True)

    # Sector flow: slug -> FIPI display name -> net USD.
    # v0.10.0: prefer the investor x sector MATRIX's Foreign row - it is
    # complete (zero cells are explicit em-dashes) and sums exactly to
    # the investor table's Foreign net. The page's "By sector" table is
    # only a fallback: on single-day pages it DROPS inactive sectors, so
    # a missing entry there stays NaN (unknown), never zero. With the
    # matrix present, a missing cell IS a measured zero.
    foreign_matrix = (
        flow_matrix.get("Foreign") if flow_matrix else None
    )
    if foreign_matrix:
        df["sector_net_flow_usd"] = df["sector"].map(
            lambda slug: foreign_matrix.get(
                _SECTOR_SLUG_TO_FLOW_NAME.get(slug, ""), 0.0
            )
        )
    elif sector_flow:
        df["sector_net_flow_usd"] = df["sector"].map(
            lambda slug: sector_flow.get(
                _SECTOR_SLUG_TO_FLOW_NAME.get(slug, ""), np.nan
            )
        )
    else:
        df["sector_net_flow_usd"] = np.nan

    # Institutional flow per sector: the five institutional investor
    # classes summed from the matrix - "which institutions are pumping
    # or dumping which sector". Available for guards, lessons and the
    # leaderboard; deliberately NOT a new blend component (the master
    # score stays centred).
    if flow_matrix:
        inst_by_sector: dict[str, float] = {}
        for investor in (
            "Foreign",
            "Mutual Funds",
            "Banks / DFI",
            "Insurance",
            "NBFC",
        ):
            for sec_name, net in (flow_matrix.get(investor) or {}).items():
                inst_by_sector[sec_name] = (
                    inst_by_sector.get(sec_name, 0.0) + float(net)
                )
        df["sector_inst_flow_usd"] = df["sector"].map(
            lambda slug: inst_by_sector.get(
                _SECTOR_SLUG_TO_FLOW_NAME.get(slug, ""), np.nan
            )
        )
    else:
        df["sector_inst_flow_usd"] = np.nan

    return df


def add_baseline_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    baseline_volume_ratio: today's cumulative volume vs. the cross-day
    EMA baseline of full-day volume. None (NaN) until the baseline has
    at least MIN_DAYS of sessions behind it.
    """
    from baselines import VolumeBaselines

    baselines = VolumeBaselines()

    # The latest snapshot of each symbol carries the running day volume
    # in `volume`; map ratio per symbol then broadcast to all its rows.
    latest = df[df["feature_price_ok"]].sort_values("timestamp").groupby("symbol").tail(1)
    ratios: dict[str, float] = {}
    for _, row in latest.iterrows():
        ratio = baselines.baseline_volume_ratio(row["symbol"], row.get("volume"))
        if ratio is not None and np.isfinite(ratio):
            ratios[row["symbol"]] = ratio

    df["baseline_volume_ratio"] = df["symbol"].map(ratios)
    return df


# ---------------------------------------------------------------------------
# Tier-1 features (ROADMAP.md): VWAP, opening range, gap, Garman-Klass,
# time-of-day. All computed from data already collected - no new fetches.
# ---------------------------------------------------------------------------

# Opening range window: the first 30 minutes of the session's FIRST
# leg, by the MARKET CLOCK (v0.18.1 fix). The old row-count window
# (first 360 rows) silently stretched across hours for thinly traded
# names - their first 360 rows can span the whole session - so every
# full-day backtest transform read an or_high containing FUTURE
# prices. The live bot was unaffected (it transforms past-only
# frames), but every panel/sweep number computed before v0.18.1
# carried that leak. Wall-clock makes live and backtest identical.
OPENING_RANGE_MINUTES = 30


def add_vwap_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Running session VWAP per symbol and the price-vs-VWAP ratio.

    The feed's `value` and `volume` are cumulative for the day, so the
    VWAP at any tick is simply value/volume at that tick - no windowing
    needed. vwap_ratio = price/vwap - 1: positive = trading above the
    institutional average, the classic "buyers in control" read.

    Session-scoped: each trading_date computes its own VWAP.
    """
    eligible = df["feature_price_ok"]
    volume = pd.to_numeric(df["volume"], errors="coerce")
    value = pd.to_numeric(df["value"], errors="coerce")

    vwap = frames.safe_divide(value, volume)
    # A stale cumulative volume from before the session reset would
    # poison the VWAP: only trust rows with positive running volume.
    vwap = vwap.where(volume.gt(0))
    df["session_vwap"] = vwap.where(eligible)

    ratio = frames.safe_divide(df["price"], df["session_vwap"]) - 1.0
    df["vwap_ratio"] = ratio.where(eligible)
    return df


def add_opening_range_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Opening-range high/low per symbol per session; the breakout score
    is how far above the range high the current price trades (0 inside
    the range, negative allowed only as 0 - a fade is simply no signal).

    The window is the first OPENING_RANGE_MINUTES of the session's
    first leg, by the market clock. Causality by construction:

      * rows INSIDE the window get the running range (only past rows
        of the window contribute - expanding over prior rows);
      * rows AFTER the window get the completed window range (the
        window has closed by wall clock, so this is not hindsight);
      * symbols with no rows inside the window get NaN (no invented
        evidence).

    A symbol that starts ticking at 09:45 contributes only from its
    first tick - the range is built from whatever the collector saw,
    but bounded by the wall-clock window, never by row counts.
    """
    from datetime import datetime as _dt, time as _time, timedelta as _td

    from psx_core import sessions as _sessions

    eligible = df["feature_price_ok"]

    ts = pd.to_datetime(df["timestamp"], utc=True)
    pkt = ts.dt.tz_convert(_sessions.PKT)
    day = pkt.dt.date

    # Window end per trading day: first leg's open + 30 min.
    leg_open: dict = {}
    for d in pd.unique(day):
        legs = _sessions.legs_for(d)
        leg_open[d] = legs[0].start if legs else None

    def _win_end(d):
        start = leg_open.get(d)
        if start is None:
            return None
        return _dt.combine(d, start, tzinfo=_sessions.PKT) + _td(minutes=OPENING_RANGE_MINUTES)

    win_end = day.map(lambda d: _win_end(d))
    # In-window: PKT instant strictly before the window close (and the
    # day has a session at all).
    in_window = pd.Series(
        [we is not None and p < we for p, we in zip(pkt, win_end)],
        index=df.index,
    )

    ordered = df.assign(_ts=ts, _in_win=in_window).sort_values("timestamp")

    def _range_for(group: pd.DataFrame) -> pd.DataFrame:
        # group: one (trading_date, symbol), timestamp-ordered.
        hi = pd.to_numeric(group["high"], errors="coerce")
        lo = pd.to_numeric(group["low"], errors="coerce")
        hi = hi.where(group["_in_win"] & group["feature_price_ok"])
        lo = lo.where(group["_in_win"] & group["feature_price_ok"])
        # Running range for in-window rows (past rows only - causal).
        run_hi = hi.expanding().max()
        run_lo = lo.expanding().min()
        # Completed window range for post-window rows (window closed).
        final_hi = hi.max()
        final_lo = lo.min()
        out_hi = run_hi.where(group["_in_win"], final_hi)
        out_lo = run_lo.where(group["_in_win"], final_lo)
        return pd.DataFrame({"or_high": out_hi, "or_low": out_lo}, index=group.index)

    ranges = (
        ordered.loc[ordered["feature_price_ok"] | ordered["_in_win"]]
        .groupby(["trading_date", "symbol"], sort=False)
        .apply(_range_for)
    )
    if ranges.empty:
        df["or_high"] = np.nan
        df["or_low"] = np.nan
        df["orb_score"] = np.nan
        return df

    # apply() wraps the result in a (trading_date, symbol) MultiIndex on
    # top of the original row index; the last level IS the row index.
    ranges.index = ranges.index.get_level_values(-1)
    df = df.merge(ranges, left_index=True, right_index=True, how="left")

    # Breakout score: distance above the range high as a fraction of it.
    above = frames.safe_divide(df["price"] - df["or_high"], df["or_high"])
    df["orb_score"] = above.where(above.gt(0)).where(eligible).fillna(0.0)
    # Inside the range is a legitimate 0 (no breakout), not missing.
    df.loc[df["or_high"].isna(), "orb_score"] = np.nan
    return df


def add_gap_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Morning gap per symbol: first price of the session vs. the prior
    close reconstructed from the feed's changePercent.

        prior_close = price / (1 + change_fraction)

    Large positive gaps carry fade risk on PSX; the gap component is
    small weight for exactly that reason. Computed once per
    (date, symbol) at the session's first eligible tick.
    """
    eligible = df["feature_price_ok"]

    ordered = df[eligible].sort_values("timestamp")
    firsts = ordered.groupby(["trading_date", "symbol"], sort=False).head(1)

    # Vectorized: prior_close = price / (1 + change_fraction) on the
    # first eligible tick of each (date, symbol).
    price = pd.to_numeric(firsts["price"], errors="coerce")
    change_fraction = pd.to_numeric(
        firsts["change_fraction"], errors="coerce"
    )
    denom = 1.0 + change_fraction
    prior_close = np.where(
        denom.ne(0) & price.gt(0), price / denom.replace(0, np.nan), np.nan
    )
    gap_values = (
        (price / pd.Series(prior_close, index=firsts.index)) - 1.0
    )

    gap_map = {
        (d, s): v
        for (d, s), v in zip(
            zip(firsts["trading_date"], firsts["symbol"]), gap_values
        )
        if pd.notna(v)
    }
    df["gap_pct"] = [
        gap_map.get((d, s), np.nan)
        for d, s in zip(df["trading_date"], df["symbol"])
    ]
    return df


def add_time_of_day_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Minutes-since-open and the U-shaped momentum credibility curve.

    PSX intraday seasonality: the open and the close carry information;
    midday is chop. `time_weight` scales momentum-family components at
    blend time (applied in add_master_score via a per-row weight map -
    computed here, used there, kept auditable here).
    """
    # Session open per trading_date: earliest timestamp of the date.
    # Vectorized: map each row to its date's open via a merge, then
    # compute minutes and the U-curve in numpy - no per-row Python.
    opens = (
        df.groupby("trading_date")["timestamp"].min()
        .rename("session_open").reset_index()
    )
    work = df[["trading_date", "timestamp"]].merge(
        opens, on="trading_date", how="left"
    )
    mins = (
        (work["timestamp"] - work["session_open"]).dt.total_seconds() / 60.0
    )
    # U-curve via sine: w = 1 - 0.3*sin(pi * t / 210). Full weight at
    # the open (t=0) and the close (t>=210), 0.7 trough at t=105 -
    # PSX midday chop carries less momentum information.
    phase = np.clip(mins.fillna(0.0) / 210.0, 0.0, 1.0)
    w = 1.0 - 0.3 * np.sin(np.pi * phase)
    df["minutes_since_open"] = mins.to_numpy()
    df["momentum_time_weight"] = np.clip(w, 0.0, 1.0)
    return df


def add_event_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Join the two event feeds onto the frame, per symbol:

    From news_sentiment.json:
      news_sentiment_pct         -- per-symbol sentiment in [-100, +100]

    From announcements.json:
      announcement_flag          -- 1.0 if the symbol has a notice
      announcement_is_unusual     -- 1.0 if it is an unusual-movement notice
      announcement_count          -- notices for the symbol

    All values broadcast to every row of the symbol - they are daily
    facts about the symbol, not per-timestamp measurements.

    (The ToWatch feed was removed 2026-09-14: psxterminal.com's own
    watchlist, sparsely populated, and the live refresh crashed the
    decide cycle twice that morning. The bot's signals come from the
    measured tape: volume, VWAP, order book, trend - not a website's
    watch tab.)
    """
    news, announces = load_event_context()

    # --- News sentiment: [-100, +100] -----------------------------------
    if news:
        sentiments = {
            sym: entry.get("sentiment", 0.0) * 100.0
            for sym, entry in news.items()
        }
        df["news_sentiment_pct"] = df["symbol"].map(sentiments)
    else:
        df["news_sentiment_pct"] = np.nan

    # --- Announcements: event flags -------------------------------------
    if announces:
        df["announcement_flag"] = df["symbol"].map(
            {s: 1.0 for s in announces}
        )
        df["announcement_is_unusual"] = df["symbol"].map(
            {
                s: 1.0
                for s, e in announces.items()
                if e.get("is_unusual")
            }
        )
        df["announcement_count"] = df["symbol"].map(
            {s: e.get("count", 0) for s, e in announces.items()}
        )
    else:
        df["announcement_flag"] = np.nan
        df["announcement_is_unusual"] = np.nan
        df["announcement_count"] = 0

    return df


def add_trend_following_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    PSX-specific trend-following features.

    relative_strength_vs_index: the stock's price change minus the
    KSE-100 index's price change over the same window. A positive
    value means the stock is outperforming the market - it is
    genuinely trending, not just riding a market-wide move.
    The classic "be with the trend" signal: buy stocks that go UP
    MORE than the market.

    volume_trend_confirmation: whether trading volume is
    increasing during the price rise. A trend backed by rising
    volume is healthy; a trend on declining volume is a warning.
    Returns a ratio in [0, 1] where 1 = volume strongly
    confirming the trend.
    """
    eligible = df["feature_price_ok"]

    # --- Relative strength vs KSE-100 ---
    # Load the KSE-100 EOD history for index momentum.
    index_momentum = _load_index_momentum()
    if index_momentum:
        # Map each symbol's price change against the index change
        # over the same period. Positive = outperforming the market.
        stock_changes = (
            df.groupby(["trading_date", "symbol"])["change_pct"]
            .transform("mean")
            .where(eligible)
        )
        df["relative_strength_vs_index"] = (
            stock_changes - index_momentum
        ).where(eligible)
    else:
        df["relative_strength_vs_index"] = np.nan

    # --- Volume trend confirmation ---
    # Ratio of current volume_1m to its rolling average.
    # > 1 means volume is increasing (confirming the trend).
    # < 1 means volume is fading (warning sign).
    if "volume_1m" in df.columns and "average_volume_1m" in df.columns:
        vol_ratio = frames.safe_divide(
            df["volume_1m"], df["average_volume_1m"]
        )
        # Map to [0, 1]: 1.0 = volume ratio 2x or more, 0.5 = 1x,
        # 0.0 = 0.5x or less. Saturate at bounds.
        df["volume_trend_confirmation"] = (
            0.5 + 0.5 * np.tanh(
                (vol_ratio - 1.0) / 0.5
            )
        ).where(eligible)
    else:
        df["volume_trend_confirmation"] = np.nan

    # --- Circuit breaker strength (PSX-specific) ---
    # In PSX, hitting the upper circuit (10% price band) is the
    # STRONGEST possible trend signal. A stock at +9.5% or above
    # is showing overwhelming buying pressure regardless of volume.
    # This is why PSYLL can go up 10% with only 10,000 volume.
    # The circuit breaker strength = (change_pct / 10.0) capped
    # at [0, 1]. A stock at +10% scores 1.0, at +5% scores 0.5.
    if "change_pct" in df.columns:
        df["circuit_breaker_pct"] = (
            pd.to_numeric(df["change_pct"], errors="coerce")
            .clip(lower=0)
            .div(10.0)
            .clip(upper=1.0)
            .where(eligible)
        )
    else:
        df["circuit_breaker_pct"] = np.nan

    return df


def _load_index_momentum() -> float | None:
    """
    Return the KSE-100's average daily change as a proxy for
    index momentum, or None if the history file is unavailable.

    Used for relative strength calculation: a stock must outperform
    the index to score well.
    """
    try:
        import json as _json
        from psx_core import paths, sessions
        from datetime import datetime, timezone, timedelta

        hist_path = paths.DATA_DIR / "kse100_history.json"
        if not hist_path.exists():
            return None
        raw = _json.loads(hist_path.read_text(encoding="utf-8"))
        rows = raw.get("rows", [])
        if len(rows) < 20:
            return None
        # Compute the average of the last 20 daily changes.
        closes = [r["close"] for r in rows[-21:] if r.get("close")]
        if len(closes) < 20:
            return None
        changes = [
            (closes[i] / closes[i - 1] - 1.0) * 100.0
            for i in range(1, len(closes))
        ]
        avg_change = sum(changes[-20:]) / 20.0
        return avg_change
    except Exception:
        return None


def add_advanced_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    The z-score master score over the whitelisted tape indicators.
    Nothing is emitted for retired measurements: the feature schema is
    exactly the whitelist (v3.3.0).
    """
    # Many independent column inserts below fragment the frame; one
    # consolidating copy keeps the rest of the build fast.
    df = df.copy()
    df = add_trend_following_features(df)

    eligible = df["feature_price_ok"]

    # --- Sector / flow / baseline features ---------------------------
    df = add_sector_features(df)
    df = add_baseline_features(df)

    # --- Z-score components, per timestamp cross-section --------------
    # Missing sources stay missing (NaN): the master blend renormalizes
    # over present components and the coverage column reports the
    # truth. A neutral 0.5 here would claim weight that does not exist.
    df["z_momentum_1m"] = zscore_by_group(
        df["momentum_1m_pct"].where(eligible), df["timestamp"]
    )
    # (v3.3.0: the z_parkinson_vol / z_kalman_trend NaN placeholders
    # are gone with the retired estimators.)
    df["z_baseline_volume_ratio"] = (
        zscore_by_group(
            df["baseline_volume_ratio"].where(eligible), df["timestamp"]
        )
        .where(df["baseline_volume_ratio"].notna())
    )
    df["z_relative_volume_1m"] = zscore_by_group(
        df["relative_volume_1m"].where(eligible), df["timestamp"]
    ).where(df["relative_volume_1m"].notna())
    df["z_short_term_price"] = zscore_by_group(
        df["short_term_price_score"].where(eligible), df["timestamp"]
    ).where(df["short_term_price_score"].notna())
    df["z_book_strength"] = zscore_by_group(
        df["book_strength"].where(eligible), df["timestamp"]
    ).where(df["book_strength"].notna())
    df["z_spread_quality"] = zscore_by_group(
        df["spread_quality"].where(eligible), df["timestamp"]
    ).where(df["spread_quality"].notna())
    df["z_trade_activity"] = zscore_by_group(
        df["trade_activity_score"].where(eligible), df["timestamp"]
    ).where(df["trade_activity_score"].notna())

    # Sector components: breadth is already (0,1); flow needs scaling.
    df["z_sector_breadth"] = df["sector_breadth"].where(eligible)
    max_abs_flow = df["sector_net_flow_usd"].abs().max()
    if max_abs_flow is not None and np.isfinite(max_abs_flow) and max_abs_flow > 0:
        df["z_sector_flow"] = (
            0.5 + 0.5 * df["sector_net_flow_usd"] / max_abs_flow
        ).where(df["sector_net_flow_usd"].notna())
    else:
        df["z_sector_flow"] = np.nan

    # --- PSX trend-following z-components --------------------------------
    # Relative strength vs KSE-100: a stock outperforming the index
    # is genuinely trending, not just riding a market-wide move.
    # This is the "trend is your friend" signal - be with the trend.
    df["z_relative_strength"] = zscore_by_group(
        df["relative_strength_vs_index"].where(eligible),
        df["timestamp"],
    ).where(df["relative_strength_vs_index"].notna())
    # Volume trend: a trend backed by rising volume is healthy.
    df["z_volume_trend"] = zscore_by_group(
        df["volume_trend_confirmation"].where(eligible),
        df["timestamp"],
    ).where(df["volume_trend_confirmation"].notna())

    # Circuit breaker strength: a stock at upper circuit is
    # the strongest trend signal in PSX.
    df["z_circuit_breaker"] = zscore_by_group(
        df["circuit_breaker_pct"].where(eligible),
        df["timestamp"],
    ).where(df["circuit_breaker_pct"].notna())

    # --- Tier-1 z-components (ROADMAP.md) --------------------------------
    # VWAP ratio: squash the raw ratio into (0, 1); +2% above VWAP -> 1.
    df["z_vwap_ratio"] = (
        0.5 + df["vwap_ratio"].clip(-0.02, 0.02) / 0.04
    ).where(df["vwap_ratio"].notna())

    # Opening-range breakout: distance above the range high, mapped so
    # that NO breakout is neutral 0.5 - a symbol inside its range has no
    # breakout information, it is not "bad". A 5%+ breakout saturates
    # at 1.0. (Previously an inside-range symbol scored 0, so 6% of
    # master weight sat at the floor for ~every non-breakout name.)
    orb_scaled = df["orb_score"].clip(upper=0.05) / 0.05
    df["z_orb"] = (0.5 + 0.5 * orb_scaled).where(df["orb_score"].notna())

    # Gap: ±5% squashed to (0, 1) around 0.5. Positive gaps score above
    # neutral (gap-and-go bias) but the small weight reflects fade risk.
    df["z_gap"] = (
        0.5 + df["gap_pct"].clip(-0.05, 0.05) / 0.10
    ).where(df["gap_pct"].notna())

    # --- Classical technical indicators (v0.17.0) ------------------------
    # RSI(14), EMA stack alignment - each over the trailing
    # per-session window convention (TECH_WINDOW ticks = 10 minutes at
    # the 5s cadence; the final state per (trading_date, symbol) is
    # broadcast to its rows).
    tech_frame = (
        df[df["feature_price_ok"]]
        .sort_values("timestamp")
        .groupby(["trading_date", "symbol"])
        .tail(TECH_WINDOW)
    )
    # Average True Range (owner-ordered, v4.4.2): Wilder's ATR over the
    # per-session window, mapped to a (0,1) z-component so a name whose
    # day's typical true range is thin gets down-weighted (the tape is
    # thin for a reason) while an active tape is rewarded. NaN when the
    # window is too short to estimate volatility - never a synthetic
    # neutral (same convention as every other z-block above).
    atr_map: dict[tuple, float] = {}
    if not tech_frame.empty:
        for (d, s), chunk in tech_frame.groupby(
            ["trading_date", "symbol"], sort=False
        ):
            prices = pd.to_numeric(chunk["price"], errors="coerce")
            highs = pd.to_numeric(chunk["high"], errors="coerce")
            lows = pd.to_numeric(chunk["low"], errors="coerce")
            if len(prices) < 7:
                continue
            tr = pd.concat(
                [
                    (highs - lows).abs(),
                    (highs - prices.shift(1)).abs(),
                    (lows - prices.shift(1)).abs(),
                ],
                axis=1,
            ).max(axis=1)
            atr = tr.ewm(alpha=1.0 / 14, min_periods=7, adjust=False).mean()
            v = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else float("nan")
            atr_map[(d, s)] = v

    rsi_map: dict[tuple, float] = {}
    ema_map: dict[tuple, float] = {}
    if not tech_frame.empty:
        for (d, s), chunk in tech_frame.groupby(
            ["trading_date", "symbol"], sort=False
        ):
            prices = pd.to_numeric(chunk["price"], errors="coerce")
            n_bars = int(prices.notna().sum())
            if n_bars < 7:
                # Fewer than ~7 polls: no indicator has evidence yet.
                continue

            # Adaptive windows (bounded by the dense-data values so a
            # 5s collector and a 15-min collector both get meaningful
            # estimates at their own cadence):
            rsi_period = max(5, min(14, n_bars // 2))
            ema_slow = max(4, min(20, n_bars // 2))
            ema_fast = max(2, ema_slow // 2)

            r_series = rsi(prices, period=rsi_period)
            r_val = r_series.iloc[-1]
            rsi_map[(d, s)] = float(r_val) if pd.notna(r_val) else np.nan

            ema_map[(d, s)] = ema_alignment_score(
                prices, fast=ema_fast, slow=ema_slow
            )

    df["rsi14"] = [
        rsi_map.get((d, s), np.nan)
        for d, s in zip(df["trading_date"], df["symbol"])
    ]
    df["ema_alignment"] = [
        ema_map.get((d, s), np.nan)
        for d, s in zip(df["trading_date"], df["symbol"])
    ]

    # --- Volume Profile Visible Range (v3.5.0) ---------------------------
    # One profile per (trading_date, symbol) over the trailing window:
    # 24 price bins, tick volume summed per bin, then the FINAL price is
    # located in the profile. 1.0 at the point of control, linear falloff
    # to the profile's low; NaN when the window is too thin to profile.
    vpvr_map: dict[tuple, float] = {}
    if not tech_frame.empty:
        for (d, s), chunk in tech_frame.groupby(
            ["trading_date", "symbol"], sort=False
        ):
            prices = pd.to_numeric(chunk["price"], errors="coerce")
            volumes = pd.to_numeric(chunk["volume"], errors="coerce").fillna(0)
            both = prices.notna() & (volumes > 0)
            p = prices[both]
            v = volumes[both]
            if len(p) < 10 or p.nunique() < 3:
                continue
            lo, hi = float(p.min()), float(p.max())
            if hi <= lo:
                continue
            bins = np.clip(
                ((p - lo) / (hi - lo) * 24).astype(int), 0, 23
            )
            profile = np.zeros(24)
            np.add.at(profile, bins.to_numpy(), v.to_numpy())
            poc_bin = int(profile.argmax())
            poc_price = lo + (poc_bin + 0.5) * (hi - lo) / 24.0
            last_price = float(p.iloc[-1])
            if last_price >= poc_price:
                # At/above the POC: 1.0 at POC, easing to 0.6 at the
                # profile high (still accepted, just extended).
                span = max(hi - poc_price, 1e-9)
                vpvr_map[(d, s)] = 1.0 - 0.4 * min(
                    (last_price - poc_price) / span, 1.0
                )
            else:
                # Below the POC: 1.0 at POC falling to ~0.1 at the low
                # (fighting the heaviest volume = churn).
                span = max(poc_price - lo, 1e-9)
                vpvr_map[(d, s)] = max(
                    1.0 - 0.9 * (poc_price - last_price) / span, 0.1
                )
    df["vpvr_score"] = [
        vpvr_map.get((d, s), np.nan)
        for d, s in zip(df["trading_date"], df["symbol"])
    ]

    # Blend components: the position scores are already (0,1) and
    # hump-shaped around the healthy band; EMA alignment is 0/0.5/1.
    # Present only where their source measurement exists - no
    # synthetic neutrals (same convention as every other z-block).
    df["z_rsi_position"] = rsi_position_score(df["rsi14"]).where(
        eligible & df["rsi14"].notna()
    )
    df["z_ema_alignment"] = df["ema_alignment"].where(
        eligible & df["ema_alignment"].notna()
    )
    # VPVR joins the blend at 3% (mirrors the z_orb convention: a
    # missing window is NaN, never a synthetic neutral).
    # ATR z-component: a stock's typical daily true range, scaled so
    # the heaviest-tape names score up (more room for the 2% target) and
    # the thinnest tape scores down (price slips, hard to hit target).
    # Median-teamed so one insane print does not dominate a thin universe.
    atr_series = pd.Series(
        [atr_map.get((d, s), np.nan) for d, s in zip(df["trading_date"], df["symbol"])]
    )
    atr_median = float(atr_series.median())
    # Median is scalar across the cross-section - if every symbol's window
    # was too thin to estimate ATR (all NaN), the median is NaN too and the
    # whole column stays NaN rather than inventing a neutral. Use a scalar
    # guard rather than Series.notna() on the scalar.
    atr_median_valid = pd.notna(atr_median) and atr_median > 1e-9
    df["z_atr"] = (
        (0.5 + 0.5 * (atr_series / atr_median))
        .clip(0.0, 1.0)
        .where(eligible & atr_series.notna() & atr_median_valid)
    )
    # z_vpvr weight retired (0.03 -> 0.0) when z_atr was added so the
    # table still sums to 1.0; the column stays for schema compatibility.
    df["z_vpvr"] = np.nan

    return df


def add_master_score(df: pd.DataFrame) -> pd.DataFrame:
    """
    Weighted z-score blend. Mirrors add_composite's audit guarantees:
    per-row weight coverage, thin flags, NaN for non-tradable rows.

    The momentum-family components (z_momentum_1m, z_vwap_ratio) are
    scaled per-row by momentum_time_weight - the
    U-shaped intraday credibility curve from add_time_of_day_features:
    full weight near the open and close, 70% at the midday trough.
    """
    # Time-of-day scaling of the momentum family (T1.7). Midday
    # momentum is less credible, so the component is pulled TOWARD its
    # neutral 0.5 - NOT multiplied, which would drag the neutral point
    # itself below 0.5 (at w=0.7 a genuinely neutral 0.5 became 0.35,
    # and the whole blend sat below the 0.5 the conviction gate
    # assumes). With the shrink, 0.5 stays 0.5; an extreme 1.0 becomes
    # 0.5 + 0.5w. A missing weight (no session anchor) leaves
    # components untouched.
    if "momentum_time_weight" in df.columns:
        scale = df["momentum_time_weight"]
        for column in ("z_momentum_1m", "z_vwap_ratio"):
            if column in df.columns:
                df[column] = 0.5 + scale * (df[column] - 0.5)

    score, available_weight = blend(df, MASTER_COMPONENTS)

    df["master_score"] = score
    # Clamp: with every component dense (post-ToWatch), available can
    # equal the total and float division lands an ulp above 1.0.
    df["master_score_weight_coverage"] = (
        available_weight / sum(MASTER_COMPONENTS.values())
    ).clip(0.0, 1.0)
    df.loc[~df["feature_price_ok"], [
        "master_score", "master_score_weight_coverage",
    ]] = np.nan

    return df


# ---------------------------------------------------------------------------
# Ranking and composite
# ---------------------------------------------------------------------------

def add_rankings(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile of each component, tradable rows only."""
    # One consolidating copy: the event/quality blocks before this point
    # inserted their columns one at a time and the frame is fragmented.
    # The loop below inserts ~13 more; a defragged frame keeps those
    # inserts (and everything downstream) fast and warning-free.
    df = df.copy()

    eligible = df["feature_price_ok"]

    for rank_column, source_column in RANK_SOURCES.items():
        if source_column in df.columns:
            df[rank_column] = cross_sectional_rank(df, source_column, eligible)
        else:
            # Column not yet available (e.g., news sentiment pending data fetch).
            # Assign neutral rank 0.5 so the composite score is still computable.
            df[rank_column] = 0.5

    # Liquidity is blended in rank space, not raw space. Its inputs are a trade
    # count and a share volume, whose magnitudes differ by orders of magnitude,
    # so a linear blend that loses one input is not comparable to one that
    # keeps it -- rows with a missing input would rank systematically apart
    # from the rest of their own cross-section. Percentiles are all in [0, 1],
    # so renormalizing over the ones present is safe (F5).
    df["rank_liquidity"], _ = blend(
        df,
        {"rank_trades_depth": 0.55, "rank_volume_depth": 0.45},
    )

    return df


def add_composite(df: pd.DataFrame) -> pd.DataFrame:
    """
    Composite rank score, plus the two things that make it auditable:
    how much of the intended weight is actually behind each row, and a
    data-quality adjustment.
    """
    score, available_weight = blend(df, COMPONENTS)

    df["feature_rank_score"] = score
    df["score_weight_coverage"] = available_weight / sum(COMPONENTS.values())
    df["score_weight_thin"] = df["score_weight_coverage"] < MIN_WEIGHT_COVERAGE

    df["data_quality_score"] = (
        0.35 * df["feature_price_ok"].astype(float)
        + 0.25 * df["feature_book_ok"].astype(float)
        + 0.20 * df["feature_range_ok"].astype(float)
        + 0.20 * df["feature_spread_ok"].astype(float)
    )

    # Keeps the ranking and the confidence in it separate rather than folding
    # data quality into the rank itself.
    df["feature_rank_score_adjusted"] = df["feature_rank_score"] * (
        0.75 + 0.25 * df["data_quality_score"]
    )

    # A non-tradable row gets no score at all. The old engine only nulled rows
    # with no quote, so suspended symbols kept a composite score (F2).
    df.loc[~df["feature_price_ok"], [
        "feature_rank_score",
        "feature_rank_score_adjusted",
        "score_weight_coverage",
    ]] = np.nan
    df.loc[~df["feature_price_ok"], "score_weight_thin"] = False

    return df


def component_coverage(df: pd.DataFrame) -> dict[str, dict]:
    """
    Per-component coverage over the rows that were eligible to be ranked.

    A component at 0.0 contributes nothing anywhere and its weight has been
    silently absorbed by the others -- the failure mode F8 describes.
    """
    eligible = int(df["feature_price_ok"].sum())
    report: dict[str, dict] = {}

    for rank_column, weight in COMPONENTS.items():
        ranked = int(df.loc[df["feature_price_ok"], rank_column].notna().sum())
        report[rank_column] = {
            "source": COMPONENT_SOURCES[rank_column],
            "weight": weight,
            "ranked_rows": ranked,
            "eligible_rows": eligible,
            "coverage": round(ranked / eligible, 6) if eligible else 0.0,
            "dead": ranked == 0,
        }

    return report


# ---------------------------------------------------------------------------
# Leaderboards
# ---------------------------------------------------------------------------

# One minute at the 5-second poll interval. A single tick's leaderboard is
# mostly noise; a symbol that holds its place for a minute is worth looking at.
PERSISTENCE_TICKS = 12


def _observation(row: pd.Series) -> dict:
    def number(column: str) -> float | None:
        value = row.get(column)
        return float(value) if pd.notna(value) else None

    return {
        "symbol": str(row["symbol"]),
        "timestamp": row["timestamp"].isoformat(),
        "feature_rank_score": number("feature_rank_score"),
        "feature_rank_score_adjusted": number("feature_rank_score_adjusted"),
        "master_score": number("master_score"),
        "score_weight_coverage": number("score_weight_coverage"),
        "momentum_1m_pct": number("momentum_1m_pct"),
        "momentum_5m_pct": number("momentum_5m_pct"),
        "relative_volume_1m": number("relative_volume_1m"),
        "order_book_imbalance": number("order_book_imbalance"),
        "spread_pct": number("spread_pct"),
        "change_pct": number("change_pct"),
        "breadth_pct": number("breadth_pct"),
    }


def latest_leaderboard(df: pd.DataFrame, top: int) -> tuple[pd.Timestamp, list[dict]]:
    """Highest adjusted scores at the final timestamp."""
    latest_timestamp = df["timestamp"].max()
    latest = df[
        (df["timestamp"] == latest_timestamp)
        & df["feature_rank_score_adjusted"].notna()
    ].sort_values("feature_rank_score_adjusted", ascending=False)

    return latest_timestamp, [
        _observation(row) for _, row in latest.head(top).iterrows()
    ]


def persistent_leaderboard(df: pd.DataFrame, top: int) -> list[dict]:
    """
    Mean adjusted score over the final PERSISTENCE_TICKS timestamps.

    A symbol must be scored in more than half of them to appear, so one
    lucky tick cannot put a symbol at the top.
    """
    timestamps = df["timestamp"].drop_duplicates().sort_values()
    window = timestamps.tail(PERSISTENCE_TICKS)
    if window.empty:
        return []

    tail = df[
        df["timestamp"].isin(window) & df["feature_rank_score_adjusted"].notna()
    ]
    if tail.empty:
        return []

    minimum_ticks = max(1, len(window) // 2 + 1)
    grouped = tail.groupby("symbol", sort=False)

    stats = pd.DataFrame(
        {
            "ticks": grouped["feature_rank_score_adjusted"].size(),
            "mean_score": grouped["feature_rank_score_adjusted"].mean(),
            "min_score": grouped["feature_rank_score_adjusted"].min(),
            "mean_weight_coverage": grouped["score_weight_coverage"].mean(),
        }
    )
    stats = stats[stats["ticks"] >= minimum_ticks].sort_values(
        "mean_score", ascending=False
    )

    return [
        {
            "symbol": str(symbol),
            "ticks": int(row["ticks"]),
            "mean_score": round(float(row["mean_score"]), 6),
            "min_score": round(float(row["min_score"]), 6),
            "mean_weight_coverage": round(float(row["mean_weight_coverage"]), 6),
        }
        for symbol, row in stats.head(top).iterrows()
    ]


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

FEATURE_COLUMNS = [
    "feature_price_ok", "feature_book_ok", "feature_range_ok",
    "feature_spread_ok",
    "momentum_1m_clipped", "momentum_5m_clipped", "momentum_score",
    "momentum_score_weight", "tick_change_clipped", "day_change_clipped",
    "short_term_price_score", "range_position_score",
    "trade_activity_score", "trades_depth", "volume_depth",
    "rank_trades_depth", "rank_volume_depth",
    "book_strength", "spread_quality",
    "market_breadth_strength", "market_net_breadth",
    "market_broadly_weak", "market_broadly_strong",
    *COMPONENTS,
    "feature_rank_score", "score_weight_coverage", "score_weight_thin",
    "data_quality_score", "feature_rank_score_adjusted",
    # Advanced-math layer (src/advanced_math.py + context joins).
    "sector", "sector_breadth", "sector_net_flow_usd",
    "baseline_volume_ratio", "vpvr_score",
    *MASTER_COMPONENTS,
    "master_score", "master_score_weight_coverage",
    # Event-feed layer (news / announcements).
    "announcement_count",
    # PSX trend-following features.
    "relative_strength_vs_index", "volume_trend_confirmation",
]


def build_summary(
    df: pd.DataFrame,
    latest_timestamp: pd.Timestamp,
    top_latest: list[dict],
    top_persistent: list[dict],
) -> dict:
    coverage = component_coverage(df)
    scored = df["feature_rank_score"].notna()

    return {
        "rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "timestamps": int(df["timestamp"].nunique()),
        "trading_dates": sorted(df["trading_date"].dropna().unique().tolist()),
        "sessions": sorted(df["session_id"].dropna().unique().tolist()),
        "feature_columns_added": FEATURE_COLUMNS,
        "eligibility": {
            "quote_available_rows": int(df["quote_available"].sum()),
            "tradable_rows": int(df["tradable"].sum()),
            "feature_price_ok_rows": int(df["feature_price_ok"].sum()),
            "feature_book_ok_rows": int(df["feature_book_ok"].sum()),
            "feature_range_ok_rows": int(df["feature_range_ok"].sum()),
            "feature_spread_ok_rows": int(df["feature_spread_ok"].sum()),
        },
        "scoring": {
            "scored_rows": int(scored.sum()),
            "min_cross_section": MIN_CROSS_SECTION,
            "min_weight_coverage": MIN_WEIGHT_COVERAGE,
            "thin_score_rows": int(df["score_weight_thin"].sum()),
            "mean_weight_coverage": (
                round(float(df.loc[scored, "score_weight_coverage"].mean()), 6)
                if scored.any() else None
            ),
            "min_weight_coverage_observed": (
                round(float(df.loc[scored, "score_weight_coverage"].min()), 6)
                if scored.any() else None
            ),
        },
        "component_coverage": coverage,
        "dead_components": [
            name for name, stats in coverage.items() if stats["dead"]
        ],
        "market_context": {
            "broadly_weak_rows": int(df["market_broadly_weak"].sum()),
            "broadly_strong_rows": int(df["market_broadly_strong"].sum()),
            "breadth_pct_min": (
                round(float(df["breadth_pct"].min()), 4)
                if df["breadth_pct"].notna().any() else None
            ),
            "breadth_pct_max": (
                round(float(df["breadth_pct"].max()), 4)
                if df["breadth_pct"].notna().any() else None
            ),
        },
        "latest_timestamp": latest_timestamp.isoformat(),
        "top_observations": top_latest,
        "top_persistent": top_persistent,
    }


def render_report(summary: dict) -> str:
    rule = "=" * 88
    thin = "-" * 88
    lines = [
        rule,
        "PSX KMIALL FEATURE ENGINE V1",
        rule,
        "",
        "This is a FEATURE layer only. It creates no BUY/SELL signal and",
        "places no orders.",
        "",
        f"Rows                 : {summary['rows']:,}",
        f"Symbols              : {summary['symbols']:,}",
        f"Timestamps           : {summary['timestamps']:,}",
        f"Trading dates        : {', '.join(summary['trading_dates']) or 'none'}",
        f"Sessions             : {', '.join(summary['sessions']) or 'none'}",
        "",
        "ELIGIBILITY",
        thin,
    ]

    for label, value in summary["eligibility"].items():
        lines.append(f"{label:<28} {value:>10,}")

    lines += ["", "SCORING", thin]
    scoring = summary["scoring"]
    lines += [
        f"{'scored_rows':<28} {scoring['scored_rows']:>10,}",
        f"{'thin_score_rows':<28} {scoring['thin_score_rows']:>10,}"
        f"   (< {int(MIN_WEIGHT_COVERAGE * 100)}% of intended weight)",
        f"{'mean_weight_coverage':<28} {scoring['mean_weight_coverage']}",
        f"{'min_weight_coverage_observed':<28} "
        f"{scoring['min_weight_coverage_observed']}",
    ]

    lines += ["", "COMPONENT COVERAGE", thin]
    lines.append(f"{'component':<26} {'weight':>7} {'ranked':>9} {'coverage':>10}")
    for name, stats in summary["component_coverage"].items():
        flag = "  DEAD COMPONENT" if stats["dead"] else ""
        lines.append(
            f"{name:<26} {stats['weight']:>7.2f} {stats['ranked_rows']:>9,} "
            f"{stats['coverage'] * 100:>9.2f}%{flag}"
        )

    if summary["dead_components"]:
        lines += [
            "",
            "WARNING",
            thin,
            "The components below contributed to no row at all. Their weight",
            "was renormalized across the remaining components, so the composite",
            "score is NOT the score these weights describe:",
        ]
        for name in summary["dead_components"]:
            weight = summary["component_coverage"][name]["weight"]
            source = summary["component_coverage"][name]["source"]
            lines.append(
                f"  {name} ({source}) -- {weight * 100:.0f}% of intended weight"
            )
        lines.append(
            "Collect a full trading session before reading anything into the "
            "rankings."
        )

    lines += [
        "",
        "MARKET CONTEXT",
        thin,
        f"{'broadly_weak_rows':<28} "
        f"{summary['market_context']['broadly_weak_rows']:>10,}",
        f"{'broadly_strong_rows':<28} "
        f"{summary['market_context']['broadly_strong_rows']:>10,}",
        f"{'breadth_pct range':<28} "
        f"{summary['market_context']['breadth_pct_min']} .. "
        f"{summary['market_context']['breadth_pct_max']}",
        "",
        f"TOP AT LATEST TIMESTAMP ({summary['latest_timestamp']})",
        thin,
    ]

    if summary["top_observations"]:
        for index, item in enumerate(summary["top_observations"], 1):
            lines.append(
                f"{index:02d}. {item['symbol']:<10} "
                f"score={item['feature_rank_score_adjusted']:.4f} "
                f"cov={item['score_weight_coverage']:.2f} "
                f"1m={item['momentum_1m_pct']} "
                f"chg={item['change_pct']} "
                f"RV={item['relative_volume_1m']} "
                f"OBI={item['order_book_imbalance']} "
                f"spr={item['spread_pct']}"
            )
    else:
        lines.append("No scored rows at the latest timestamp.")

    lines += [
        "",
        f"MOST PERSISTENT OVER THE LAST {PERSISTENCE_TICKS} TICKS",
        thin,
    ]
    if summary["top_persistent"]:
        for index, item in enumerate(summary["top_persistent"], 1):
            lines.append(
                f"{index:02d}. {item['symbol']:<10} "
                f"mean={item['mean_score']:.4f} min={item['min_score']:.4f} "
                f"ticks={item['ticks']:>3} cov={item['mean_weight_coverage']:.2f}"
            )
    else:
        lines.append("Not enough scored ticks to measure persistence.")

    lines += [
        "",
        "IMPORTANT",
        thin,
        "The composite score is a research feature, not a trading signal.",
        "The weights are provisional and have not been validated on any",
        "historical outcome.",
        "",
        "The decision engine that eventually consumes this layer must enforce",
        "all six strategy rules:",
        "  1. KMIALL universe only",
        "  2. one winner per decision, not a basket",
        "  3. 1%-4% profit target",
        "  4. no chasing a move that has already run",
        "  5. stand aside when broad-market breadth is weak",
        "  6. maximum 3-trading-day holding period",
        "",
        "Rules 3 and 6 cannot be validated on intraday-only data. They gate",
        "the project on multi-day collection.",
        "",
        f"Features CSV : {paths.FEATURES_CSV}",
        f"Summary JSON : {paths.FEATURES_SUMMARY}",
        rule,
    ]

    return "\n".join(lines)


def write_outputs(df: pd.DataFrame, summary: dict) -> None:
    paths.ensure_dirs()

    df.to_csv(paths.FEATURES_CSV, index=False)

    paths.FEATURES_SUMMARY.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    paths.FEATURES_REPORT.write_text(render_report(summary), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the KMIALL feature layer from the intraday dataset.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", type=Path, default=paths.INTRADAY_CSV,
        help="Intraday dataset to read (.csv or .parquet).",
    )
    parser.add_argument(
        "--top", type=int, default=20,
        help="Leaderboard length.",
    )
    parser.add_argument(
        "--min-cross-section", type=int, default=MIN_CROSS_SECTION,
        help="Neutralise ranks in cross-sections thinner than this.",
    )
    return parser.parse_args(argv)


def build(df: pd.DataFrame, top: int = 20) -> tuple[pd.DataFrame, dict]:
    """Full feature pipeline. Separated from main() so tests can call it."""
    df = add_quality_flags(df)
    df = add_price_features(df)
    df = add_volume_features(df)
    df = add_book_features(df)
    df = add_market_context(df)
    df = add_trend_following_features(df)
    df = add_event_features(df)
    df = add_vwap_features(df)
    df = add_gap_features(df)
    df = add_opening_range_features(df)
    df = add_time_of_day_features(df)
    df = add_rankings(df)
    df = add_composite(df)
    df = add_advanced_features(df)
    df = add_master_score(df)

    latest_timestamp, top_latest = latest_leaderboard(df, top)
    top_persistent = persistent_leaderboard(df, top)
    summary = build_summary(df, latest_timestamp, top_latest, top_persistent)

    return df, summary


def main(argv: list[str] | None = None) -> int:
    global MIN_CROSS_SECTION

    paths.enable_utf8_stdout()
    args = parse_args(argv)
    MIN_CROSS_SECTION = args.min_cross_section

    try:
        df = load_dataset(args.input)
    except FeatureError as exc:
        print(f"ERROR: {exc}")
        return 2

    df, summary = build(df, top=args.top)
    write_outputs(df, summary)

    print("Feature engine completed.")
    print(f"Rows                 : {summary['rows']:,}")
    print(f"Symbols              : {summary['symbols']:,}")
    print(f"Timestamps           : {summary['timestamps']:,}")
    print(f"Scored rows          : {summary['scoring']['scored_rows']:,}")
    print(f"Thin-weight rows     : {summary['scoring']['thin_score_rows']:,}")
    print(f"Mean weight coverage : {summary['scoring']['mean_weight_coverage']}")

    if summary["dead_components"]:
        print()
        print("WARNING: components with zero coverage, weight redistributed:")
        for name in summary["dead_components"]:
            stats = summary["component_coverage"][name]
            print(f"  {name} ({stats['source']}) -- {stats['weight'] * 100:.0f}%")

    print()
    print(f"CSV     : {paths.FEATURES_CSV}")
    print(f"Summary : {paths.FEATURES_SUMMARY}")
    print(f"Report  : {paths.FEATURES_REPORT}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
