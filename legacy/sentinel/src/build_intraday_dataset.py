"""
Build the KMIALL intraday dataset from stored snapshots.

One row per (symbol, snapshot). Every KMIALL symbol gets a row in every
snapshot; symbols with no quote are retained explicitly as unavailable so the
row grid stays rectangular and coverage stays measurable.

Defects fixed relative to the previous version
----------------------------------------------
D1  change_pct was copied straight from the feed's `changePercent`, which is a
    FRACTION (0.00563 = +0.563%), into a column named like a percent and sitting
    beside genuine percents (momentum_1m_pct, price_change_pct_5s). Now scaled
    through feed.normalize_change_percent(). Both scales are emitted --
    change_pct (true percent) and change_fraction (raw feed value) -- so the
    scale is never again ambiguous.

D2  `status` (OPN/SUS) was dropped entirely. Suspended symbols keep a stale
    non-zero price and volume, so downstream they looked perfectly tradable:
    13 of 300 KMIALL symbols in the 2026-09-02 archive were suspended with
    volume > 0. Now carried as `status`, with `is_open` and `tradable` flags,
    and excluded from breadth.

D3  Every per-symbol sequential operation was grouped by symbol alone. Harmless
    with one day of snapshots, silently corrupting from day two: the overnight
    price gap became a "5-second" move, and day two's opening volume was
    discarded as a counter reset. Now grouped by session_id (tick-to-tick) or
    trading_date (cumulative counters), which are different boundaries --
    Friday has two legs but one cumulative day.

D14 Unavailable rows omitted the bid/ask/high/low availability keys entirely,
    so those columns came out object-dtype with True/False/NaN. Now every row
    carries every key.

D15 volume_valid, trades_valid, bid_delta and ask_delta were computed and then
    dropped by the column selection. Removed.

D18 A bare `except Exception:` around timestamp parsing swallowed real errors.
    Narrowed, and unparseable timestamps are now counted and reported.

Usage
-----
    python src/build_intraday_dataset.py
    python src/build_intraday_dataset.py --limit 20      # first N snapshots
    python src/build_intraday_dataset.py --date 2026-09-02
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import feed, frames, paths, sessions, storage, universe as universe_mod

# ============================================================
# SETTINGS
# ============================================================

LOOKBACK_1M_SECONDS = 60
LOOKBACK_5M_SECONDS = 300

# Choose the most recent observation at least this many seconds back, and
# accept it only when the elapsed time is within this tolerance. Deliberately
# not a rolling first/last: that would let a 20-second gap masquerade as a
# 1-minute return. Matches the independent validator's interpretation.
LOOKBACK_TOLERANCE_SECONDS = 2.5


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def safe_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_datetime(value):
    """Parse a snapshot timestamp, returning None only for genuinely bad input."""
    if not value:
        return None
    try:
        return pd.to_datetime(value, utc=True)
    except (ValueError, TypeError, pd.errors.ParserError):
        # Previously a bare `except Exception`, which also swallowed
        # KeyboardInterrupt-adjacent and programming errors.
        return None


# ============================================================
# TIME-LOOKBACK FEATURES
# ============================================================

def calculate_time_lookback_momentum(group, seconds):
    """
    Momentum over a real elapsed interval, not a fixed number of rows.

    For each observation, walk backwards to the most recent one at least
    `seconds` old, accept it only if the elapsed time is within
    LOOKBACK_TOLERANCE_SECONDS of the request, and return
    (current / previous - 1) * 100.

    `group` must be a single (symbol, session) block. Called per session so a
    lookback can never reach across an overnight gap or the Friday lunch break
    and report it as a 1- or 5-minute return.
    """
    group = group.sort_values("timestamp")

    times = group["timestamp"].tolist()
    prices = pd.to_numeric(group["price"], errors="coerce").tolist()

    result = np.full(len(group), np.nan, dtype=float)

    for i, current_time in enumerate(times):
        current_price = prices[i]
        if pd.isna(current_price) or current_price <= 0:
            continue

        best_index = None
        for j in range(i - 1, -1, -1):
            if (current_time - times[j]).total_seconds() >= seconds:
                best_index = j
                break

        if best_index is None:
            continue

        previous_price = prices[best_index]
        if pd.isna(previous_price) or previous_price <= 0:
            continue

        elapsed = (current_time - times[best_index]).total_seconds()
        if abs(elapsed - seconds) > LOOKBACK_TOLERANCE_SECONDS:
            continue

        result[i] = ((current_price / previous_price) - 1.0) * 100.0

    return result


def add_time_features(group):
    """
    Momentum and rolling volume/trade sums for one (symbol, session) block.

    The rolling windows are time-based ("60s"), so they would already have been
    safe across a day boundary. The momentum lookbacks would not have been --
    that is why this runs per session rather than per symbol.
    """
    group = group.sort_values("timestamp").copy()

    group["momentum_1m_pct"] = calculate_time_lookback_momentum(
        group, LOOKBACK_1M_SECONDS
    )
    group["momentum_5m_pct"] = calculate_time_lookback_momentum(
        group, LOOKBACK_5M_SECONDS
    )

    indexed = group.set_index("timestamp")

    for column, source, window in (
        ("volume_1m", "new_volume", "60s"),
        ("volume_5m", "new_volume", "300s"),
        ("trades_1m", "new_trades", "60s"),
        ("trades_5m", "new_trades", "300s"),
    ):
        group[column] = (
            indexed[source].rolling(window, min_periods=1).sum().to_numpy()
        )

    return group


# ============================================================
# MARKET BREADTH
# ============================================================

def calculate_breadth(group):
    """
    KMIALL advance/decline breadth for one snapshot timestamp.

    Only OPEN symbols count. A suspended symbol holds its last traded price and
    a frozen change_pct forever, so including them pinned a constant bloc of
    fake advancers or decliners into the market filter -- the exact signal the
    strategy uses to decide whether to trade at all.

    breadth_pct is the percentage of counted quotes that are advancing, not net
    breadth. The validator relies on that definition.
    """
    valid = group[
        group["quote_available"]
        & group["is_open"]
        & group["change_pct"].notna()
    ]

    if valid.empty:
        return pd.Series(
            {
                "breadth_advancers": 0,
                "breadth_decliners": 0,
                "breadth_unchanged": 0,
                "breadth_total": 0,
                "breadth_ratio": np.nan,
                "breadth_pct": np.nan,
                "market_vw_change_pct": np.nan,
                "market_vw_value": np.nan,
                "market_vw_slope_30m": np.nan,
                "market_off_low_pct": np.nan,
            }
        )

    advancers = int((valid["change_pct"] > 0).sum())
    decliners = int((valid["change_pct"] < 0).sum())
    unchanged = int((valid["change_pct"] == 0).sum())
    total = int(len(valid))

    # Money-weighted market lens (2026-09-11 lesson). Equal-weight breadth
    # answers "is the average stock up?" - during a cap-weighted reversal
    # the average stock is NOT up (42% breadth at 15:00) while the index
    # is +1600 points off the low on the heavyweights. Weighting each
    # open symbol's change by its traded value reads where the money
    # actually is; the 30-minute slope (added in add_breadth) reads the
    # direction of that money.
    vw_change = np.nan
    vw_value = np.nan
    off_low = np.nan
    if total > 0:
        vals = valid["value"]
        weights = vals.where(vals.notna() & (vals > 0))
        if weights.notna().any():
            vw_value = float(weights.sum())
            vw_change = float(
                (valid["change_pct"] * weights).sum() / weights.sum()
            )
        # Median distance off the session low (percent). On a normal day
        # the average stock sits 0.2-1.1% off its low all afternoon
        # (measured, Sep 2026); during the 2026-09-11 V-recovery the
        # median sat 3.9-4.7% off its low - the whole board bouncing.
        # This is the shape-of-the-market detector that equal-weight
        # breadth cannot see.
        prices = pd.to_numeric(valid["price"], errors="coerce")
        lows = pd.to_numeric(valid["low"], errors="coerce")
        off_lows = ((prices - lows) / lows * 100.0).where(
            (prices > 0) & (lows > 0)
        )
        if off_lows.notna().any():
            off_low = float(off_lows.median())

    return pd.Series(
        {
            "breadth_advancers": advancers,
            "breadth_decliners": decliners,
            "breadth_unchanged": unchanged,
            "breadth_total": total,
            "breadth_ratio": advancers / decliners if decliners > 0 else np.nan,
            "breadth_pct": (advancers / total) * 100.0,
            "market_vw_change_pct": vw_change,
            "market_vw_value": vw_value,
            "market_vw_slope_30m": np.nan,  # filled by add_breadth
            "market_off_low_pct": off_low,
        }
    )


# ============================================================
# LOAD
# ============================================================

# Column groups, declared once so the schema, the dtype pass and the validator
# cannot drift apart.

BOOLEAN_COLUMNS = [
    "quote_available",
    "is_open",
    "tradable",
    "bid_available",
    "ask_available",
    "high_available",
    "low_available",
    "volume_reset_or_anomaly",
    "trades_reset_or_anomaly",
    "usable_price",
    "usable_book",
    "usable_momentum",
]

COLUMNS = [
    "timestamp",
    "receive_time",
    "trading_date",
    "session_id",
    "symbol",
    "quote_available",
    "status",
    "is_open",
    "tradable",
    "price",
    "change",
    "change_pct",
    "change_fraction",
    "volume",
    "trades",
    "value",
    "high",
    "low",
    "bid",
    "ask",
    "bid_volume",
    "ask_volume",
    "quote_timestamp",
    "bid_available",
    "ask_available",
    "high_available",
    "low_available",
    "spread",
    "spread_pct",
    "price_position_range",
    "distance_from_high_pct",
    "distance_from_low_pct",
    "price_change_pct_5s",
    "momentum_1m_pct",
    "momentum_5m_pct",
    "volume_delta",
    "new_volume",
    "trades_delta",
    "new_trades",
    "volume_reset_or_anomaly",
    "trades_reset_or_anomaly",
    "volume_1m",
    "volume_5m",
    "trades_1m",
    "trades_5m",
    "average_volume_1m",
    "relative_volume_1m",
    "trade_value_per_trade",
    "order_book_imbalance",
    "usable_price",
    "usable_book",
    "usable_momentum",
    "breadth_advancers",
    "breadth_decliners",
    "breadth_unchanged",
    "breadth_total",
    "breadth_ratio",
    "breadth_pct",
    "market_vw_change_pct",
    "market_vw_value",
    "market_vw_slope_30m",
    "market_off_low_pct",
]

# Every key an unavailable row must still carry, so the resulting columns are
# real bool/float dtypes rather than object columns full of NaN (D14).
_EMPTY_QUOTE = {
    "status": "",
    "is_open": False,
    "tradable": False,
    "price": None,
    "change": None,
    "change_pct": None,
    "change_fraction": None,
    "volume": None,
    "trades": None,
    "value": None,
    "high": None,
    "low": None,
    "bid": None,
    "ask": None,
    "bid_volume": None,
    "ask_volume": None,
    "quote_timestamp": None,
    "bid_available": False,
    "ask_available": False,
    "high_available": False,
    "low_available": False,
    "spread": None,
    "spread_pct": None,
}


def quote_to_row(quote: dict) -> dict:
    """Flatten one feed quote into dataset columns."""
    price = safe_float(quote.get("price"))
    change = safe_float(quote.get("change"))
    high = safe_float(quote.get("high"))
    low = safe_float(quote.get("low"))
    bid = safe_float(quote.get("bid"))
    ask = safe_float(quote.get("ask"))

    # The feed sends changePercent as a fraction. Keep both scales explicitly
    # so nothing downstream has to guess which one it is holding (D1).
    change_fraction = safe_float(quote.get("changePercent"))
    change_pct = feed.normalize_change_percent(change_fraction)

    status = (quote.get("status") or "").strip().upper()
    is_open = status == feed.STATUS_OPEN

    bid_available = bid is not None and bid > 0
    ask_available = ask is not None and ask > 0
    high_available = high is not None and high > 0
    low_available = low is not None and low > 0

    spread = None
    spread_pct = None
    if bid_available and ask_available and ask >= bid:
        spread = ask - bid
        # Denominator is the bid, not the mid. Kept as-is: the validator and the
        # existing archive both assume bid, and changing it silently would make
        # old and new rows incomparable. Bid-based spread_pct runs slightly high
        # versus the mid-based convention.
        spread_pct = (spread / bid) * 100.0

    return {
        "status": status,
        "is_open": is_open,
        # Tradable means the strategy is allowed to act on this row: quoted,
        # open, and carrying a real price. A suspended symbol keeps a stale
        # price and volume, so price alone is not enough.
        "tradable": is_open and price is not None and price > 0,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "change_fraction": change_fraction,
        "volume": safe_float(quote.get("volume")),
        "trades": safe_int(quote.get("trades")),
        "value": safe_float(quote.get("value")),
        "high": high,
        "low": low,
        "bid": bid,
        "ask": ask,
        "bid_volume": safe_float(quote.get("bidVol")),
        "ask_volume": safe_float(quote.get("askVol")),
        # The source quote timestamp, kept raw. Never silently substituted for
        # the receive timestamp: the two differ by seconds to hours.
        "quote_timestamp": safe_float(quote.get("timestamp")),
        "bid_available": bid_available,
        "ask_available": ask_available,
        "high_available": high_available,
        "low_available": low_available,
        "spread": spread,
        "spread_pct": spread_pct,
    }


def load_rows(symbols, limit=None, date_filter=None):
    """Read every stored snapshot into flat rows."""
    rows = []
    invalid = []
    snapshot_count = 0
    availability = defaultdict(int)

    for label, snapshot in storage.iter_snapshots():
        generated_at = parse_datetime(snapshot.get("generatedAt"))
        receive_time = parse_datetime(snapshot.get("receiveTime"))
        quotes = snapshot.get("quotes", {})

        if generated_at is None:
            invalid.append({"source": label, "reason": "Invalid generatedAt"})
            continue
        if not isinstance(quotes, dict):
            invalid.append({"source": label, "reason": "quotes is not an object"})
            continue

        if date_filter is not None:
            if sessions.trading_date(generated_at).isoformat() != date_filter:
                continue

        snapshot_count += 1
        if limit is not None and snapshot_count > limit:
            snapshot_count -= 1
            break

        for symbol in symbols:
            quote = quotes.get(symbol)

            base = {
                "timestamp": generated_at,
                "receive_time": receive_time,
                "symbol": symbol,
                "quote_available": quote is not None,
            }

            if quote is None:
                rows.append({**base, **_EMPTY_QUOTE})
            else:
                availability[symbol] += 1
                rows.append({**base, **quote_to_row(quote)})

        if snapshot_count % 250 == 0:
            print(f"  read {snapshot_count:,} snapshots")

    return rows, invalid, snapshot_count, availability


# ============================================================
# FEATURES
# ============================================================

def add_price_position_features(df):
    """Where the price sits inside the day's range, and distance from the extremes."""
    range_size = df["high"] - df["low"]

    # The raw PSX high/low are preserved. A price outside its own reported
    # high/low is a source anomaly (158 such rows in the 2026-09-02 archive);
    # rather than clip the price or manufacture a position, the derived feature
    # is left unavailable so the validator keeps flagging it.
    valid_range = (
        df["high_available"]
        & df["low_available"]
        & df["price_valid"]
        & (df["high"] > df["low"])
        & (df["price"] >= df["low"])
        & (df["price"] <= df["high"])
    )

    df["price_position_range"] = np.nan
    df.loc[valid_range, "price_position_range"] = (
        df.loc[valid_range, "price"] - df.loc[valid_range, "low"]
    ) / range_size.loc[valid_range]

    valid_high = df["high_available"] & df["price_valid"] & (df["high"] > 0)
    valid_low = df["low_available"] & df["price_valid"] & (df["low"] > 0)

    df["distance_from_high_pct"] = np.nan
    df["distance_from_low_pct"] = np.nan

    df.loc[valid_high, "distance_from_high_pct"] = (
        (df.loc[valid_high, "price"] / df.loc[valid_high, "high"]) - 1.0
    ) * 100.0
    df.loc[valid_low, "distance_from_low_pct"] = (
        (df.loc[valid_low, "price"] / df.loc[valid_low, "low"]) - 1.0
    ) * 100.0

    return df


def add_sequential_features(df):
    """
    Tick-to-tick and cumulative-counter features, grouped correctly (D3).

    Two different boundaries, and conflating them is the bug:

      session_id    price_change_pct_5s. A tick-to-tick return must never span
                    a gap. Grouped by symbol alone, the first tick of day two
                    reported the overnight gap as a 5-second move, and the
                    first Friday-afternoon tick reported the lunch break.

      trading_date  volume/trades deltas. These counters are cumulative from
                    the day's open and run continuously across the Friday lunch
                    break, so they must NOT be split per leg -- doing so would
                    zero out the first afternoon tick. They do reset overnight,
                    so they must be split per day: grouped by symbol alone, the
                    day-two opening delta was (day 2 cumulative - day 1 final),
                    a large negative, flagged as a reset, and discarded.
    """
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    by_session = frames.session_groupby(df)
    df["price_change_pct_5s"] = by_session["price"].pct_change() * 100.0

    by_day = frames.day_groupby(df)
    df["volume_delta"] = by_day["volume"].diff()
    df["trades_delta"] = by_day["trades"].diff()

    # A negative delta on a cumulative counter means the feed reset or
    # corrected. Treat the increment as zero rather than propagating a negative.
    df["volume_reset_or_anomaly"] = (
        df["volume_delta"].notna() & (df["volume_delta"] < 0)
    )
    df["trades_reset_or_anomaly"] = (
        df["trades_delta"].notna() & (df["trades_delta"] < 0)
    )

    df["new_volume"] = df["volume_delta"].where(df["volume_delta"] >= 0, 0.0)
    df["new_trades"] = df["trades_delta"].where(df["trades_delta"] >= 0, 0.0)

    return df


def add_windowed_features(df):
    """Momentum and rolling sums, computed per (symbol, session)."""
    blocks = [
        add_time_features(block)
        for _, block in df.groupby(["symbol", "session_id"], sort=False)
    ]
    df = pd.concat(blocks, ignore_index=True)
    return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def add_relative_volume(df):
    """
    Relative volume against the symbol's own history so far.

    The baseline excludes the current observation (shift(1) before expanding),
    so a volume spike cannot inflate its own denominator and hide itself.

    Grouped per session, not per symbol: on day two an expanding mean seeded
    with day one would make the first minutes of the session look normal
    against a full previous day of accumulated volume.
    """
    grouped = df.groupby(["symbol", "session_id"], sort=False, group_keys=False)

    df["average_volume_1m"] = grouped["volume_1m"].transform(
        lambda x: x.shift(1).expanding(min_periods=3).mean()
    )

    df["relative_volume_1m"] = frames.safe_divide(
        df["volume_1m"], df["average_volume_1m"]
    )
    # A zero baseline is not a signal, it is an absence of history.
    df.loc[df["average_volume_1m"].fillna(0) <= 0, "relative_volume_1m"] = np.nan

    return df


def add_liquidity_features(df):
    df["trade_value_per_trade"] = np.nan
    valid = df["value"].notna() & df["trades"].notna() & (df["trades"] > 0)
    df.loc[valid, "trade_value_per_trade"] = (
        df.loc[valid, "value"] / df.loc[valid, "trades"]
    )

    book_total = df["bid_volume"] + df["ask_volume"]
    valid_book = (
        df["bid_volume"].notna() & df["ask_volume"].notna() & book_total.gt(0)
    )

    df["order_book_imbalance"] = np.nan
    df.loc[valid_book, "order_book_imbalance"] = (
        df.loc[valid_book, "bid_volume"] - df.loc[valid_book, "ask_volume"]
    ) / book_total.loc[valid_book]

    return df


def add_usability_flags(df):
    """
    Which rows the strategy is allowed to act on.

    `tradable` (quoted, open, real price) is now part of every usable_* flag.
    Without it, a suspended symbol's frozen price and stale order book passed
    every usability check.
    """
    df["usable_price"] = df["quote_available"] & df["price_valid"] & df["tradable"]
    df["usable_book"] = (
        df["usable_price"]
        & df["bid_available"]
        & df["ask_available"]
        & df["spread"].notna()
    )
    df["usable_momentum"] = df["usable_price"] & df["momentum_1m_pct"].notna()
    return df


# Lookback for the money-tape slope, in minutes. 30 minutes is long
# enough to clear one-minute noise and short enough to see a V-turn
# develop while there is still session left to trade it.
VW_SLOPE_MINUTES = 30


def _add_market_slope(breadth):
    """
    Per-timestamp change of the value-weighted market change over the
    trailing window, matched by clock time (not row position) so poll
    gaps and lunch thinness cannot fake a slope.
    """
    b = breadth.sort_values("timestamp").reset_index(drop=True)
    ts = pd.to_datetime(b["timestamp"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    vals = b["market_vw_change_pct"].to_numpy(dtype=float)
    slope = np.full(len(b), np.nan)
    ts_values = ts.to_numpy()
    for i in range(len(b)):
        if not np.isfinite(vals[i]):
            continue
        target = ts_values[i] - np.timedelta64(VW_SLOPE_MINUTES, "m")
        j = int(np.searchsorted(ts_values, target, side="right") - 1)
        if j < 0 or not np.isfinite(vals[j]):
            continue
        gap_min = (ts_values[i] - ts_values[j]) / np.timedelta64(1, "m")
        # Reference row must be real (close to the window, not session
        # start masquerading as "30 minutes ago").
        if gap_min <= VW_SLOPE_MINUTES * 1.5:
            slope[i] = vals[i] - vals[j]
    b["market_vw_slope_30m"] = slope
    return b


def add_breadth(df):
    breadth = (
        df.groupby("timestamp")
        .apply(calculate_breadth, include_groups=False)
        .reset_index()
    )
    breadth = _add_market_slope(breadth)
    return df.merge(breadth, on="timestamp", how="left")


# ============================================================
# MAIN
# ============================================================

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Build the KMIALL intraday dataset from stored snapshots.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Use only the first N snapshots. For quick iteration.",
    )
    parser.add_argument(
        "--date", default=None,
        help="Restrict to one trading date (YYYY-MM-DD).",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    paths.enable_utf8_stdout()
    paths.ensure_dirs()

    print("=" * 78)
    print("BUILD KMIALL INTRADAY DATASET")
    print("=" * 78)

    symbols = universe_mod.load()
    print(f"\nKMIALL universe : {len(symbols)}")

    print("\nReading snapshots...")
    rows, invalid, snapshot_count, availability = load_rows(
        symbols, limit=args.limit, date_filter=args.date
    )

    if not rows:
        print("\nERROR: No snapshots found. Run the collector first:")
        print("  python src/collect_kmiall_snapshots.py --status")
        return 1

    print(f"Snapshots read  : {snapshot_count:,}")
    if invalid:
        print(f"Unreadable      : {len(invalid)}")

    print("\nBuilding frame...")
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df["receive_time"] = pd.to_datetime(df["receive_time"], utc=True)

    # Session columns must exist before any sequential feature is computed.
    df = frames.add_session_columns(df)

    unassigned = int(df["session_id"].isna().sum())
    if unassigned:
        raise RuntimeError(
            f"{unassigned:,} rows could not be assigned a session. "
            "This means timestamps failed to parse; investigate before trusting "
            "any sequential feature."
        )

    session_count = df["session_id"].nunique()
    day_count = df["trading_date"].nunique()
    print(f"Trading days    : {day_count}")
    print(f"Sessions        : {session_count}")

    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    df["price_valid"] = df["price"].notna() & (df["price"] > 0)

    df = add_price_position_features(df)
    df = add_sequential_features(df)

    print("Computing momentum and rolling windows...")
    df = add_windowed_features(df)

    df = add_relative_volume(df)
    df = add_liquidity_features(df)
    df = add_usability_flags(df)

    print("Computing market breadth...")
    df = add_breadth(df)

    missing = [column for column in COLUMNS if column not in df.columns]
    if missing:
        raise RuntimeError(
            "Dataset schema construction failed. Missing: " + ", ".join(missing)
        )

    df = df[COLUMNS]

    for column in BOOLEAN_COLUMNS:
        df[column] = frames.coerce_bool(df[column])

    df["quote_timestamp"] = pd.to_numeric(df["quote_timestamp"], errors="coerce")

    return write_outputs(df, args, symbols, snapshot_count, invalid, availability)


def write_outputs(df, args, symbols, snapshot_count, invalid, availability):
    print("\nSaving CSV...")
    df.to_csv(paths.INTRADAY_CSV, index=False)

    quote_rows = df[df["quote_available"]]
    open_rows = df[df["is_open"]]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "PSX Terminal",
        "universe_count": len(symbols),
        "snapshots": snapshot_count,
        "rows": len(df),
        "quote_rows": len(quote_rows),
        "unavailable_rows": len(df) - len(quote_rows),
        "open_rows": len(open_rows),
        "suspended_rows": len(quote_rows) - len(open_rows),
        "tradable_rows": int(df["tradable"].sum()),
        "unique_symbols": int(df["symbol"].nunique()),
        "unique_timestamps": int(df["timestamp"].nunique()),
        "trading_dates": sorted(df["trading_date"].dropna().unique().tolist()),
        "sessions": sorted(df["session_id"].dropna().unique().tolist()),
        "first_timestamp": df["timestamp"].min().isoformat(),
        "last_timestamp": df["timestamp"].max().isoformat(),
        "coverage_minutes": round(
            (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 60.0,
            2,
        ),
        "actual_quote_change_rows": int(
            (
                df["price_change_pct_5s"].notna()
                & (df["price_change_pct_5s"] != 0)
            ).sum()
        ),
        "volume_anomaly_rows": int(df["volume_reset_or_anomaly"].sum()),
        "trade_anomaly_rows": int(df["trades_reset_or_anomaly"].sum()),
        "usable_price_rows": int(df["usable_price"].sum()),
        "usable_book_rows": int(df["usable_book"].sum()),
        "usable_momentum_rows": int(df["usable_momentum"].sum()),
        "momentum_1m_coverage": int(df["momentum_1m_pct"].notna().sum()),
        "momentum_5m_coverage": int(df["momentum_5m_pct"].notna().sum()),
        "invalid_snapshots": invalid,
        "schema_columns": len(COLUMNS),
        "lookback_1m_seconds": LOOKBACK_1M_SECONDS,
        "lookback_5m_seconds": LOOKBACK_5M_SECONDS,
        "lookback_tolerance_seconds": LOOKBACK_TOLERANCE_SECONDS,
        "change_pct_scale": "percent (feed fraction x 100)",
        "breadth_pct_definition": "advancers / breadth_total * 100, OPEN symbols only",
        "spread_pct_denominator": "bid",
        "price_position_policy": (
            "calculated only when low <= price <= high and high > low"
        ),
    }

    paths.INTRADAY_SUMMARY.write_text(
        json.dumps(summary, indent=2, default=str), encoding="utf-8"
    )

    print("\n" + "=" * 78)
    print("DATASET SUMMARY")
    print("=" * 78)
    print(f"\nRows                     : {summary['rows']:,}")
    print(f"With quote               : {summary['quote_rows']:,}")
    print(f"Without quote            : {summary['unavailable_rows']:,}")
    print(f"Open                     : {summary['open_rows']:,}")
    print(f"Suspended                : {summary['suspended_rows']:,}")
    print(f"Tradable                 : {summary['tradable_rows']:,}")
    print(f"Unique symbols           : {summary['unique_symbols']}")
    print(f"Unique timestamps        : {summary['unique_timestamps']:,}")
    print(f"Trading dates            : {', '.join(summary['trading_dates'])}")
    print(f"Sessions                 : {', '.join(summary['sessions'])}")
    print(f"Coverage                 : {summary['coverage_minutes']:.2f} minutes")
    print(f"1m momentum coverage     : {summary['momentum_1m_coverage']:,}")
    print(f"5m momentum coverage     : {summary['momentum_5m_coverage']:,}")
    print(f"Usable price rows        : {summary['usable_price_rows']:,}")
    print(f"Usable order-book rows   : {summary['usable_book_rows']:,}")
    print(f"Usable momentum rows     : {summary['usable_momentum_rows']:,}")
    print(f"Schema columns           : {summary['schema_columns']}")

    if summary["momentum_5m_coverage"] == 0:
        print(
            "\nNOTE: momentum_5m_pct has zero coverage. The data spans "
            f"{summary['coverage_minutes']:.1f} minutes, so no observation has a "
            "5-minute history. Any model weighting this feature is weighting "
            "nothing. Collect a full session before training."
        )

    print("\n" + "=" * 78)
    print("OUTPUT FILES")
    print("=" * 78)
    print(f"\nCSV     : {paths.INTRADAY_CSV}")
    print(f"Summary : {paths.INTRADAY_SUMMARY}")

    return 0


if __name__ == "__main__":
    sys.exit(main())




