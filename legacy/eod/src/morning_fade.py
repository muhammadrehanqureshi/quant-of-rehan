"""
Bot B morning-fade engine - the owner's restated strategy
(order 2026-09-30), replacing the lock-continuation policy:

  BUY in the last minutes before the close on late momentum, SELL in
  the first minutes of the next session (the open spikes then fades).

The 8 features (owner's order, weights = starting evidence-backed
values; the refit loop may re-learn them, the schema is the whitelist):
  1. close_position      where price sits in the day's range near close
  2. late_volume_ratio   last-30-60min volume vs the same window's
                         20-session norm (persists from the reference
                         read; falls back to full-day surge ratio)
  3. late_momentum       last-30-60min return, always paired with #4
  4. extension_safety    distance from VWAP/day-low/prev-close -
                         stretched names gap up and fade before the sell
  5. overnight_history   the stock's own close-to-open mean/median and
                         green-open frequency (20-60 sessions)
  6. book_strength       spread + liquidity in the last 30 minutes
  7. sector_context      sector strength + KMIALL direction into close
  8. range_sufficiency   ATR/range context: is the normal morning move
                         worth it after costs?

The 4 vetoes (the cap):
  1. spread too wide / book unusable at the analysis read
  2. liquidity too low (day value, avg value floor)
  3. market sharply negative into the close (KSE-100 day-change floor)
  4. stock at/into upper circuit (>= 9.5%: no sellers into the close,
     the fill is fiction)

Everything else the old policy gated (lock class, lock quality,
blow-off, streak discounts, red-tape bar) is retired from the pick
path - the honest baseline of this trade is the stock's OWN overnight
history (#5), measured per name, not a corpus-wide lock law.

Exit ladder (next session, in priority order):
  - open+5min sell: the default (time-based, the best window until
    first-minutes data proves otherwise)
  - hard stop: open <= entry*(1 - GAP_STOP_PCT) -> sell at open,
    never ride a gap-down
  - weak/flat open (open between -GAP_STOP and +OPEN_MIN_GAIN):
    sell at open+15min; the fade thesis needs a morning pop, a dead
    open gets out before the fade deepens
  - circuit: if the stock opens LOCKED UP, hold is refused too - sell
    into the first non-locked print (the owner sells strength)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --- The 8 features --------------------------------------------------------
FEATURES: dict[str, float] = {
    "close_position": 0.16,
    "late_volume_ratio": 0.14,
    "late_momentum": 0.16,
    "extension_safety": 0.14,
    "overnight_history": 0.14,
    "book_strength": 0.10,
    "sector_context": 0.08,
    "range_sufficiency": 0.08,
}

# --- The 4 vetoes ----------------------------------------------------------
VETO_SPREAD_PCT = 1.2
VETO_MIN_DAY_VALUE_PKR = 20_000_000.0
VETO_MIN_AVG_VALUE_PKR = 5_000_000.0
VETO_KSE100_PCT = -0.8          # market sharply negative into the close
VETO_CIRCUIT_PCT = 9.5
# v2.6.1: the 5th hard veto - no sub-Rs-10 names. KEL (Rs 6-7)
# produced calls the owner cannot trust: thin tapes, tick noise,
# per-share commission bite. Mirrors the intraday Rule 27.
VETO_MIN_PRICE_PKR = 10.0

# --- Strategy switch (owner's order 2026-09-30) ----------------------------
# True = the morning-fade engine picks the book (buy late momentum,
# sell first minutes). False = the legacy lock-continuation policy.
STRATEGY_SWITCH = True

# --- Entry realism ---------------------------------------------------------
AUSSION_WINDOW_MIN = 6          # 15:24-15:30 auction; analysis at ~15:21
MAX_ENTRY_PREMIUM_PCT = 0.5     # refuse if ask > mid*(1+this) at read

# --- Exit ladder -----------------------------------------------------------
OPEN_SELL_MIN = 5               # default: sell at open+5 min
WEAK_OPEN_SELL_MIN = 15
OPEN_MIN_GAIN_PCT = 0.4         # open >= +0.4%: sell at open+5
GAP_STOP_PCT = -1.0             # open <= -1%: hard stop at the open
CIRCUIT_OPEN_PCT = 9.5

# --- Extension bands (score input, not a veto) -----------------------------
EXT_SOFT_PCT = 3.0
EXT_HARD_PCT = 6.0
MIN_RANGE_PCT = 1.8             # daily range too thin to pay 2% net


def _clip01(x) -> float | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float(max(0.0, min(1.0, x)))


def overnight_history_score(pairs: list[dict]) -> float | None:
    """The stock's own overnight edge, 0..1.

    pairs: [{gap_pct}, ...] close-to-open returns, oldest last,
    20-60 rows. Score = win-frequency blended with the mean's
    distance from the cost line:
      0.5 * P(gap > 0) + 0.5 * sigmoid(mean_gap / 1.0)
    Returns None under 20 rows - the stock has not proven anything.
    """
    gaps = [p["gap_pct"] for p in pairs if p.get("gap_pct") is not None]
    if len(gaps) < 20:
        return None
    win = float(np.mean([g > 0 for g in gaps]))
    mean_gap = float(np.mean(gaps))
    sig = 1.0 / (1.0 + np.exp(-mean_gap))
    return 0.5 * win + 0.5 * sig


def build_features(rows: list[dict], kse100_pct: float | None) -> list[dict]:
    """Map raw quote rows onto the 8-feature schema (pure, no IO).

    Each row arrives from the runner with: symbol, price, high, low,
    change_pct, volume, value, avg_volume_20, late_momentum_pct,
    late_volume_ratio (or volume_surge fallback), quote (bid/ask/vols),
    sector_chg_pct, prev_close, session_history.
    """
    out = []
    for r in rows:
        f = dict(r)
        price = r.get("price")

        # 1. close position in the day's range
        hi, lo = r.get("high"), r.get("low")
        f["close_position"] = (
            (price - lo) / (hi - lo) if price and hi and lo and hi > lo else None
        )

        # 2. late volume vs the window's norm (fallback: full-day surge)
        f["late_volume_ratio"] = _clip01(
            min(1.0, (r.get("late_volume_ratio") or r.get("volume_surge") or 0) / 3.0)
        ) if (r.get("late_volume_ratio") or r.get("volume_surge")) else None

        # 3. late momentum, clipped 0..1 around 0.5 at +/-4%
        late = r.get("late_momentum_pct")
        f["late_momentum"] = _clip01(0.5 + late / 4.0) if late is not None else None

        # 4. extension safety: distance from VWAP proxy (prev close),
        # day low, and the day's run
        if price and r.get("prev_close"):
            run_pct = (price - r["prev_close"]) / r["prev_close"] * 100.0
        else:
            run_pct = None
        safety = 1.0
        if run_pct is not None:
            safety -= max(0.0, min(1.0, (run_pct - EXT_SOFT_PCT) / 3.0)) * 0.5
            if run_pct > EXT_HARD_PCT:
                safety -= 0.3
        if price and lo:
            off_low_pct = (price - lo) / price * 100.0
            safety -= max(0.0, min(1.0, (off_low_pct - 4.0) / 4.0)) * 0.2
        f["extension_safety"] = _clip01(safety)
        f["_run_pct"] = run_pct

        # 5. the stock's own overnight history
        f["overnight_history"] = overnight_history_score(r.get("overnight_pairs") or [])

        # 6. book strength: spread tightness + resting bid support
        q = r.get("quote") or {}
        bid, ask = q.get("bid"), q.get("ask")
        if price and bid and ask and ask > bid > 0:
            spread_pct = (ask - bid) / price * 100.0
            f["book_strength"] = _clip01(1.0 - spread_pct / 1.2)
            f["_spread_pct"] = spread_pct
        else:
            f["book_strength"] = None
            f["_spread_pct"] = None

        # 7. sector context: sector day-change mapped over [-1, +1.5]%
        schg = r.get("sector_chg_pct")
        f["sector_context"] = _clip01(0.5 + schg / 2.5) if schg is not None else None

        # 8. range sufficiency from the stock's own sessions
        hist = r.get("session_history") or []
        rngs = [
            (s.get("high", max(s.get("open", 0), s.get("close", 0)))
             - s.get("low", min(s.get("open", 1e9), s.get("close", 1e9))))
            / s["close"] * 100.0
            for s in hist[-20:]
            if s.get("close")
        ]
        f["range_sufficiency"] = _clip01(
            (float(np.mean(rngs)) - MIN_RANGE_PCT) / 2.0 + 0.5
        ) if rngs else None

        out.append(f)
    return out


def veto(row: dict, kse100_pct: float | None) -> str | None:
    """Return a veto reason string, or None. ONLY the 4 vetoes."""
    price = row.get("price")
    if not price or price <= 0:
        return "veto1-no-quote"
    if price < VETO_MIN_PRICE_PKR:
        return f"veto1-price<{VETO_MIN_PRICE_PKR:g}"
    if (row.get("_spread_pct") or 0) > VETO_SPREAD_PCT:
        return f"veto1-spread>{VETO_SPREAD_PCT}%"
    if (row.get("value") or 0) < VETO_MIN_DAY_VALUE_PKR:
        return "veto2-day-value"
    avg_val = (row.get("avg_volume_20") or 0) * price
    if avg_val < VETO_MIN_AVG_VALUE_PKR:
        return "veto2-avg-value"
    if kse100_pct is not None and kse100_pct <= VETO_KSE100_PCT:
        return f"veto3-kse100<={VETO_KSE100_PCT}%"
    chg = row.get("change_pct")
    if chg is not None and chg >= VETO_CIRCUIT_PCT:
        return f"veto4-circuit>={VETO_CIRCUIT_PCT}%"
    return None


def score_rows(rows: list[dict], weights: dict[str, float] | None = None) -> list[dict]:
    """Weighted 8-feature score with missing-feature renormalisation."""
    w = weights or FEATURES
    scored = []
    for f in rows:
        parts, wsum, wcov = 0.0, 0.0, 0.0
        comps = {}
        for name, wt in w.items():
            v = f.get(name)
            if v is None:
                continue
            parts += wt * v
            wsum += wt
            wcov += wt
            comps[name] = round(v, 4)
        f["score_8f"] = round(parts / wsum, 4) if wsum > 0 else None
        f["score_weight_coverage"] = round(wcov / sum(w.values()), 3)
        f["score_components"] = comps
        scored.append(f)
    return scored


def rank_and_pick(
    scored: list[dict],
    kse100_pct: float | None,
    min_score: float = 0.55,
    min_coverage: float = 0.7,
) -> tuple[dict | None, list[dict], list[tuple[str, str]]]:
    """Veto, rank, and emit AT MOST ONE pick - rank 1 if it clears
    min_score and min_coverage. Otherwise: no trade (a full citizen).
    """
    vetoed = []
    pool = []
    for f in scored:
        reason = veto(f, kse100_pct)
        if reason:
            vetoed.append((f["symbol"], reason))
        elif f["score_8f"] is not None and f["score_weight_coverage"] >= min_coverage:
            pool.append(f)
    pool.sort(key=lambda f: (-f["score_8f"], -f["score_weight_coverage"]))
    ranked = [
        {"rank": i, "symbol": f["symbol"], "score": f["score_8f"],
         "coverage": f["score_weight_coverage"],
         "components": f["score_components"]}
        for i, f in enumerate(pool, start=1)
    ]
    if not pool:
        return None, ranked, vetoed
    top = pool[0]
    if top["score_8f"] < min_score:
        return None, ranked, vetoed
    return top, ranked, vetoed


def exit_plan(entry_price: float, open_price: float) -> dict:
    """Next-morning decision from the open print (the runner executes
    the ladder as real ticks arrive; this is the plan the card shows
    and the trace enforces)."""
    gap = (open_price - entry_price) / entry_price * 100.0
    if gap <= GAP_STOP_PCT:
        return {"action": "SELL_NOW", "reason": f"gap-stop ({gap:+.2f}%)", "at_min": 0}
    if gap >= CIRCUIT_OPEN_PCT:
        return {"action": "SELL_FIRST_PRINT", "reason": "opened locked - sell strength",
                "at_min": 0}
    if gap >= OPEN_MIN_GAIN_PCT:
        return {"action": "SELL", "reason": f"green open ({gap:+.2f}%)", "at_min": OPEN_SELL_MIN}
    return {"action": "SELL", "reason": f"weak/flat open ({gap:+.2f}%)",
            "at_min": WEAK_OPEN_SELL_MIN}


def signal_record(pick: dict, trading_date: str, signal_time_pkt: str) -> dict:
    """The full signal-log row (research.SignalRecord schema)."""
    return {
        "bot": "sentinel-eod",
        "trading_date": trading_date,
        "symbol": pick["symbol"],
        "signal_time_pkt": signal_time_pkt,
        "entry_price": pick.get("entry_price") or pick.get("price"),
        "features": {k: pick.get(k) for k in FEATURES},
        "rank": 1,
        "probability": None,          # filled by the calibration layer
        "score_components": pick.get("score_components", {}),
        "exit_price": None,
        "exit_time_pkt": None,
        "exit_reason": None,
        "gross_pct": None,
        "net_pct": None,
        "next_session_prices": {},
    }
