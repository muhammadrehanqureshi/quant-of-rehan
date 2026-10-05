"""
Bot A ranking layer - the owner's 8-feature book (order 2026-09-30).

Sits between the feature frame (build_kmiall_features) and the
decision: builds the ELIGIBLE pool, scores it with exactly the 8
owner-approved features, and emits the rank-1 candidate plus the full
ranked list for the signal log.

The 4 hard vetoes (the cap the owner set - everything else is score):
  1. SPREAD      - quoted spread wider than the feasibility band.
  2. NOT FEASIBLE- the stock cannot plausibly travel +2% in the time
                   left today (ATR feasibility + locked/dead tape).
  3. MARKET/SECTOR NEGATIVE - KMIALL breadth under the floor or the
                   candidate's sector net-negative on the day.
  4. TIME WINDOW - outside the session's allowed entry minutes, or
                   the stock is at/near its circuit breaker.

Everything the old rulebook gated by threshold (chase, extension,
price position, momentum, evidence count) is now a SCORE INPUT or a
rank penalty. "No trade" is the correct output of an empty or
low-quality pool - the bot never hands out the best available symbol
just because it is the best available.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- The 8 features (owner's order, 2026-09-30) ---------------------------
# Weights start as the prior blend's evidence-backed ordering, minus
# everything removed. The refit loop may re-learn them; the schema here
# is the whitelist.
FEATURES: dict[str, float] = {
    "vwap_position": 0.22,       # above VWAP, fresh reclaim > stretched
    "relative_volume": 0.18,     # time-of-day adjusted vs 20 sessions
    "orb": 0.14,                 # opening-range breakout w/ volume
    "trend_ema": 0.10,           # ONE trend measure, direction only
    "atr_feasible": 0.12,        # can it pay 2% in the time left?
    "book_strength": 0.10,       # spread + order-book
    "breadth_context": 0.08,     # sector + KMIALL breadth, positive only
    "extension_safety": 0.06,    # not done moving: off-low/VWAP distance
}

# --- The 4 vetoes ---------------------------------------------------------
VETO_SPREAD_PCT = 1.2          # quoted spread as % of price (untradeable)
VETO_MIN_DAY_VALUE_PKR = 5_000_000.0
VETO_CIRCUIT_PCT = 9.5         # at/over the breaker: never signal
VETO_FROZEN_TICKS = 12         # no price movement over N ticks = dead
VETO_MIN_BREADTH_PCT = 35.0    # market breadth floor (waived by tape mode)
VETO_SECTOR_NEG_PCT = -1.0     # sector down more than this on the day

# Extension bands (score input, not a gate): the measured anti-edge
# was buying >+6% movers near highs; mild extension is fine.
EXT_SOFT_PCT = 3.0
EXT_HARD_PCT = 6.0

# ATR feasibility: the stock's typical daily true range must cover the
# target + costs within the fraction of session left.
ATR_MIN_FRACTION = 1.1


@dataclass
class RankingResult:
    signal: dict | None
    ranked: list[dict] = field(default_factory=list)
    vetoed: list[tuple[str, str]] = field(default_factory=list)
    trace: list[tuple[str, int]] = field(default_factory=list)


def _z(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    std = s.std()
    if not std or pd.isna(std) or std == 0:
        return pd.Series(np.nan, index=s.index)
    return (s - s.mean()) / std


def _clip01(x: float | None) -> float | None:
    if x is None or pd.isna(x):
        return None
    return float(max(0.0, min(1.0, x)))


def build_features(latest: pd.DataFrame, session_fraction_left: float | None = None) -> pd.DataFrame:
    """Map the feature frame's raw columns onto the 8-feature schema.

    Maps existing columns (no new math, no look-ahead: every input is
    computed upstream from data <= now):
      vwap_position  <- z_vwap_ratio (percentile-clipped)
      relative_volume<- mean of z_relative_volume_1m / z_volume_trend /
                        z_baseline_volume_ratio (the merged trio)
      orb            <- z_orb
      trend_ema      <- ema_alignment (0..1 direction measure)
      atr_feasible   <- from day range vs remaining session (built here)
      book_strength  <- z_book_strength + z_spread_quality (merged pair)
      breadth_context<- z_sector_breadth + z_sector_flow (merged pair)
      extension_safety <- off-low/price-position/VWAP distance (inverted)
    """
    c = latest.copy()
    for col in FEATURES:
        c[col] = np.nan

    if "z_vwap_ratio" in c:
        c["vwap_position"] = 1.0 / (1.0 + np.exp(-c["z_vwap_ratio"]))  # sigmoid 0..1

    trio = [col for col in ("z_relative_volume_1m", "z_volume_trend",
                            "z_baseline_volume_ratio") if col in c]
    if trio:
        c["relative_volume"] = c[trio].mean(axis=1)

    if "z_orb" in c:
        c["orb"] = 1.0 / (1.0 + np.exp(-c["z_orb"]))

    if "ema_alignment" in c:
        c["trend_ema"] = pd.to_numeric(c["ema_alignment"], errors="coerce")

    pair = [col for col in ("z_book_strength", "z_spread_quality") if col in c]
    if pair:
        c["book_strength"] = c[pair].mean(axis=1)

    pair = [col for col in ("z_sector_breadth", "z_sector_flow") if col in c]
    if pair:
        c["breadth_context"] = c[pair].mean(axis=1)

    # ATR feasibility from what the row knows: the day's own range so
    # far as % of price, scaled by how much session is left. The
    # corpus-grade ATR(14) replaces this when the caller supplies it.
    rng = None
    if {"high", "low", "price"} <= set(c.columns):
        rng = (c["high"] - c["low"]) / c["price"] * 100.0
    if session_fraction_left is not None and rng is not None:
        # can the stock cover TP+costs in the remaining fraction, with
        # the 1.1 slack? Range-so-far / fraction-elapsed is the pace.
        frac_elapsed = max(0.05, 1.0 - session_fraction_left)
        pace = rng / frac_elapsed
        c["atr_feasible"] = (pace * session_fraction_left >= (2.0 * ATR_MIN_FRACTION)).astype(float)
        c.loc[rng.isna(), "atr_feasible"] = np.nan

    # Extension safety: distance from the day's low, and price position
    # in range. Far off the low AND near the high = the move is done.
    if {"high", "low", "price"} <= set(c.columns):
        off_low = (c["price"] - c["low"]) / c["price"] * 100.0
        pos = (c["price"] - c["low"]) / (c["high"] - c["low"]).replace(0, np.nan)
        safety = 1.0
        safety = safety - (pos.clip(0.7, 1.0) - 0.7) * 1.5     # near-high penalty
        if "change_pct" in c:
            chg = pd.to_numeric(c["change_pct"], errors="coerce")
            soft = chg > EXT_SOFT_PCT
            hard = chg > EXT_HARD_PCT
            safety = safety - soft * 0.15 - hard * 0.35        # the chase anti-edge
        c["extension_safety"] = safety.clip(0.0, 1.0)

    return c


def score_frame(c: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Weighted 8-feature score with missing-feature renormalisation.

    Adds: score_8f (0..1), score_weight_coverage (0..1),
    score_components (json-ish string for the signal log).
    """
    w = weights or FEATURES
    parts_sum = pd.Series(0.0, index=c.index)
    weight_sum = pd.Series(0.0, index=c.index)
    coverage = pd.Series(0.0, index=c.index)
    for name, wt in w.items():
        if name not in c:
            continue
        vals = pd.to_numeric(c[name], errors="coerce")
        present = vals.notna() & vals.between(0, 1.0001)
        parts_sum = parts_sum + wt * vals.fillna(0.0) * present
        weight_sum = weight_sum + wt * present
        coverage = coverage + wt * present
    c["score_8f"] = (parts_sum / weight_sum.replace(0, np.nan)).clip(0, 1)
    c["score_weight_coverage"] = (coverage / sum(w.values())).clip(0, 1)
    return c


def eligible_pool(
    c: pd.DataFrame,
    breadth_pct: float | None,
    minute_of_session: float | None,
    session_start_min: float = 15.0,   # chaos window: no entries (owner doctrine)
    session_end_min: float = 330.0,    # 15:00 PKT Mon-Thu; Fri legs handled by caller
    sector_change: dict[str, float] | None = None,
    frozen_symbols: set[str] | None = None,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Apply ONLY the 4 vetoes. Everything else stays in the pool.

    Returns (pool, vetoed) where vetoed names each rejection for the
    signal log. Missing evidence never vetoes (a None breadth cannot
    prove the market negative).
    """
    vetoed: list[tuple[str, str]] = []

    def _veto(mask: pd.Series, reason: str) -> None:
        for sym in c.loc[mask, "symbol"]:
            vetoed.append((str(sym), reason))

    # Tradability basics are preconditions, not the counted vetoes:
    c = c[c["tradable"] == True]  # noqa: E712
    c = c[c["price"].notna() & (c["price"] > 0)]
    c = c[c["score_8f"].notna()]

    if "spread_pct" in c:
        m = c["spread_pct"] > VETO_SPREAD_PCT
        _veto(m, f"veto1-spread>{VETO_SPREAD_PCT}%")
        c = c[~m]

    m = c["value"].notna() & (c["value"] < VETO_MIN_DAY_VALUE_PKR)
    _veto(m, "veto2-liquidity")
    c = c[~m]

    chg = pd.to_numeric(c.get("change_pct"), errors="coerce")
    m = chg.abs() >= VETO_CIRCUIT_PCT
    _veto(m, "veto4-circuit")
    c = c[~m]

    if frozen_symbols:
        m = c["symbol"].isin(frozen_symbols)
        _veto(m, "veto2-frozen-tape")
        c = c[~m]

    if breadth_pct is not None and breadth_pct < VETO_MIN_BREADTH_PCT:
        _veto(pd.Series(True, index=c.index), f"veto3-breadth<{VETO_MIN_BREADTH_PCT}")
        c = c.iloc[0:0]

    if sector_change:
        sec = c.get("sector")
        if sec is not None:
            sec_chg = sec.map(sector_change)
            m = sec_chg.notna() & (sec_chg <= VETO_SECTOR_NEG_PCT)
            _veto(m, f"veto3-sector<={VETO_SECTOR_NEG_PCT}%")
            c = c[~m]

    if minute_of_session is not None:
        if minute_of_session < session_start_min:
            _veto(pd.Series(True, index=c.index), "veto4-time<open+15m")
            c = c.iloc[0:0]
        elif minute_of_session > session_end_min:
            _veto(pd.Series(True, index=c.index), "veto4-time>last-entry")
            c = c.iloc[0:0]

    return c, vetoed


def rank_and_pick(
    pool: pd.DataFrame,
    top: pd.Series | None = None,
    min_score: float = 0.0,
) -> RankingResult:
    """Rank the pool by score_8f; the SIGNAL is rank 1 only if its
    score clears min_score. Returns the full ranking for the log."""
    if pool.empty:
        return RankingResult(signal=None)
    ranked = pool.sort_values(["score_8f", "score_weight_coverage"],
                              ascending=[False, False])
    rows = []
    for i, (_, r) in enumerate(ranked.iterrows(), start=1):
        rows.append({
            "rank": i,
            "symbol": r["symbol"],
            "score": round(float(r["score_8f"]), 4),
            "coverage": round(float(r["score_weight_coverage"]), 3),
            "price": float(r["price"]) if pd.notna(r.get("price")) else None,
            "components": {
                k: (round(float(r[k]), 4) if pd.notna(r.get(k)) else None)
                for k in FEATURES if k in r
            },
        })
    best = rows[0]
    signal = best if best["score"] >= min_score else None
    return RankingResult(signal=signal, ranked=rows)
