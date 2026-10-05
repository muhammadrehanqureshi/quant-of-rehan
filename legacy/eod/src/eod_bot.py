"""
Sentinel-EOD - the end-of-day next-day predictor.

THE STRATEGY (owner's design, 2026-09-16):
  * every PSX session at ~15:20, score the KMIALL cross-section on
    late-day surge quality and pick the best candidates;
  * the owner buys at the close (paper here);
  * the next morning the tracer watches each pick: +2.0% above the
    entry = win (sold), -1.0% below = stop (sold), neither by 11:30 =
    force-close at market;
  * every outcome is recorded net of the real PSX cost stack
    (broker 0.15% or 0.03/share < 20 PKR, 16% SST on commission,
    ~0.05% levies, 15% CGT on gains - same math as the Sentinel).

WHY A RANKING, NOT A GATE: the stock can go up OR down next day; no
indicator promises otherwise. The system's job is to (a) rank the
cross-section by the features that best carried overnight drift, and
(b) TRACE every pick so the ledger learns which features actually
pay. The weekly re-fit upgrades the weights from evidence, not opinion.

THE DEAD-STOCK GATE (v2.1.0, owner's standing concern): the strategy
buys the LAST HALF HOUR and needs next-day continuation - a candidate
that is not visibly RISING in the final hour is a dead stock no matter
how pretty its daily picture. The Sep-16 ledger proves it: all three
winners were rising (+0.33..+0.75% late); both fade-outs (GLAXO, FABL)
flatlined. So positive verified late momentum is a HARD requirement,
not a weighted hint - a candidate without it is never picked.

STATE (all JSON, all committed by the workflow after every run):
    data/picks/YYYY-MM-DD.json     the evening pick set + entry context
    data/tracker.json              open picks being traced this morning
    data/ledger.jsonl              closed outcomes, net of costs
    data/heartbeat.json            stamped by every real run
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- Strategy constants (the owner's design + PSX reality) --------------
TARGET_PCT = 2.0          # sell into strength
STOP_PCT = -1.0           # hard stop (owner mandate 2026-09-18: 1.0%)
FORCE_CLOSE_MIN_UTC = 375  # 11:30 PKT (06:30 UTC)
MAX_POSITIONS = 1         # ONE call per day (owner rule, 2026-09-17)

# v3.0.0 owner simplification (mirrors the Sentinel's cleanup): the
# memory overlays are OUT of the production pick path. The clean
# engine reads the tape only: final-hour momentum, weight coverage,
# extension (streak + persistence discounts), liquidity. The per-
# symbol lock memory, the rolling market lesson and the ledger-refit
# weight overrides stay in the repo as research tools - set this to
# True to re-arm them on a pick run.
MEMORY_LAYERS_ENABLED = False
REFIT_WEIGHT_FLOOR = 0.02  # a learned weight can never reach zero

# --- Window persistence (v2.2.2) ------------------------------------------
# The owner's window (15:00-15:23) is analysis time, so the bot reads
# the tape TWICE: once at the window-open (:00) and once at the
# analysis read (:21). A candidate that kept RISING between the two
# reads is confirmed; one that faded was a flash. This discount only
# ever demotes rising-then-fading names - a positive drift below the
# threshold costs nothing.
PERSISTENCE_MIN_PCT = 0.15   # drift above this starts costing rank
PERSISTENCE_MAX_DISCOUNT = 0.15  # ... up to 15% of the score, at +1.15%

# --- Self-learning override (v2.2.0) --------------------------------------
# The weekly refit (src/weekly_refit.py) measures which features the
# LEDGER says actually separate winners from losers and writes
# data/refit.json. The runner feeds that here; every live weight is
# the base weight x the learned multiplier, floored and re-normalized
# so no feature can ever be silenced completely.
def store_window_open(snapshot: dict, today: str, repo_root: Path) -> Path:
    """Persist the window-open cross-section (the :00 data read).

    This is the RAW material for the persistence feature: the analysis
    read at :21 compares each candidate against this file to measure
    what the tape did DURING the owner's window. Date-stamped like the
    reference - a stale read must never feed the comparison.
    """
    path = repo_root / "data" / "window_open.json"
    save_json(path, {
        "_date": today,
        "utc": datetime.now(timezone.utc).isoformat(),
        "quotes": snapshot.get("quotes") or {},
    })
    return path


def persistence_discount(
    picks: list[dict], window_open: dict | None
) -> list[dict]:
    """Rank-adjust the picks by their drift WITHIN the window (v2.2.2).

    For each pick: drift = analysis price vs the :00 window-open price.
    Positive drift beyond PERSISTENCE_MIN_PCT discounts the score (the
    move is already spending itself inside the window); drift at or
    below zero costs nothing - a name that backed off then re-surged
    into the analysis read is the GOOD shape. The measured drift always
    travels on the pick for the owner to see, whatever the discount.
    """
    if not window_open or not picks:
        return picks
    for p in picks:
        q = (window_open.get("quotes") or {}).get(p["symbol"])
        p0 = q.get("price") if q else None
        if not p0 or p0 <= 0:
            p["window_drift_pct"] = None
            continue
        drift = (p["entry_price"] / p0 - 1.0) * 100.0
        p["window_drift_pct"] = round(drift, 3)
        if drift > PERSISTENCE_MIN_PCT:
            frac = min((drift - PERSISTENCE_MIN_PCT) / 1.0, 1.0)
            p["persistence_discount"] = round(
                PERSISTENCE_MAX_DISCOUNT * frac, 4
            )
    for p in picks:  # re-rank by whatever the discount changed
        p["score"] = round(
            p["score"] * (1.0 - p.get("persistence_discount", 0.0)), 4
        )
    picks.sort(key=lambda p: p["score"], reverse=True)
    return picks


def apply_weight_overrides(
    overrides: dict | None,
) -> dict[str, float] | None:
    """Merge refit.json's learned weights over WEIGHTS. Returns the
    live weight dict (or None when there is nothing to apply)."""
    if not overrides:
        return None
    learned = overrides.get("weights") or {}
    if not any(k in WEIGHTS for k in learned):
        return None  # nothing learned applies to this book
    live = {}
    for key, base in WEIGHTS.items():
        lw = learned.get(key)
        live[key] = (
            max(REFIT_WEIGHT_FLOOR, float(lw))
            if isinstance(lw, (int, float)) and lw > 0 else base
        )
    total = sum(live.values())
    live = {k: v / total for k, v in live.items()}
    # Floor AFTER normalization too: the floored keys keep exactly the
    # floor and the free keys absorb the deficit, so no feature can be
    # diluted into silence by the renormalize itself.
    floored = {k: max(REFIT_WEIGHT_FLOOR, v) for k, v in live.items()}
    deficit = 1.0 - sum(floored.values())
    free = [k for k, v in floored.items() if v > REFIT_WEIGHT_FLOOR + 1e-12]
    if free and abs(deficit) > 1e-12:
        free_sum = sum(floored[k] for k in free)
        for k in free:
            floored[k] += deficit * floored[k] / free_sum
    return floored

# PSX lot: 500 shares - candidates above this price are unbuyable at
# small capital; the picker skips them honestly.
MAX_PRICE_PKR = 400.0

# Late-surge quality weights. v2.1.5 expands the layer with the
# multi-session indicators (owner's order: rich analysis, computed on
# every stock in the cross-section - the window is 15 minutes, the
# computation takes under a second). sector_flow ACTIVE since v2.1.0
# (the sector map feeds it - a hot sector carries its stocks).
WEIGHTS = {
    "close_position": 0.20,      # where in the day range it closed (0..1)
    "volume_surge": 0.15,        # today's volume vs its 20-session norm
    "late_momentum": 0.20,       # last-hour drift (the ledger-proven one)
    "day_momentum": 0.05,        # full-day change
    "sector_flow": 0.10,         # sector's share of market traded value
    "multi_day_momentum": 0.10,  # 5-session cumulative run + green streak
    "breakout_10d": 0.05,        # closing at/near a 10-session high
    "book_pressure": 0.08,       # the live bid/ask wall (bulls vs bears NOW)
    "aggression": 0.04,          # who crossed the spread today (buyers/sellers)
    "vpvr": 0.03,                # v3.5.0 volume profile: close vs the POC
}

# --- Order-book & tape-reading constants (v2.1.6) ------------------------
# The feed carries the live book: bid, ask, bidVol, askVol, trades. Two
# features read it:
#
# BOOK PRESSURE - where the resting liquidity leans. A big quiet buyer
# parks size on the bid; a quiet big seller stacks the ask. We read the
# imbalance logarithmically (a 10:1 wall counts like ~4.6:1, not 10:1)
# so one lucky print can't fake conviction.
BOOK_MIN_BID_ASK_VOL = 2_000   # thinner than this, the book says nothing
#
# AGGRESSION - who was impatient today: trades vs volume (trades per
# share). Real PSX tapes run ~0.0002 (few block prints - patient/
# absorbing) to ~0.004 (constant small hitting - frantic chase). High
# intensity into a rising close = bulls attacking; near-zero on a
# rising tape = one quiet big player absorbing everything offered.
AGGRESSION_CALM_TPS = 0.0002
AGGRESSION_FRANTIC_TPS = 0.004

# --- Range-sufficiency gate (v2.1.5) -------------------------------------
# The strategy needs +2% NET next day. A stock whose average daily
# high-low range is 1.5% cannot pay that target even on its best day -
# picking it would be buying a lottery ticket with dead volatility.
# The average intraday range over stored sessions must clear this
# floor; fewer than MIN_HISTORY_FOR_RANGE sessions = warm-up, pass
# (missing data never blocks - doctrine).
MIN_DAY_RANGE_PCT = 3.0
MIN_HISTORY_FOR_RANGE = 3

MIN_ABS_PRICE = 20.0      # stay out of the 0.03/share flat-fee tier
LOCKED_MIN_PCT = 9.0      # >= +9% on the day = circuit-locked, unbuyable
MIN_DAY_VALUE = 20e6      # PKR 20M traded today - exit liquidity floor
MIN_AVG_VALUE = 25e6      # PKR 25M average daily - sustained tradability

# --- Dead-stock gate (the "is this stock alive?" test) -------------------
# The pick is bought 2 minutes before the close and must carry overnight.
# The ledger's only losses were candidates FLAT in the final hour - the
# daily picture looked fine, the tape was already dead. Rule: the last
# hour's verified drift must be positive and meaningful.
MIN_LATE_MOMENTUM_PCT = 0.1   # < +0.1% in the final hour = dead, refused
MIN_WEIGHT_COVERAGE = 0.70    # < 70% of weight verifiable = no pick

# --- Streak risk-adjustment (the FPJM trap, owner's clarified design) -----
# NOT A BAN. The owner's order: decisions from data, nothing dropped
# randomly - a streaking name (even FPJM on day 4) stays pickable when
# the data says it is the best live candidate. What the data says about
# vertical runs: the marginal probability of overnight continuation
# decays as the cumulative run grows - each extra +1% already on the
# tape is more of the move consumed. So streaks cost RANK, not
# ELIGIBILITY: a modest discount per cumulative point above the fresh-
# move allowance. If the discounted candidate is still the best on the
# board, it is picked - with the streak flag shown in the signal so the
# owner holds the final data-informed call. The hand curve below is the
# cold-start prior; the ledger refit owns it as outcomes accumulate.
STREAK_FREE_RUN_PCT = 10.0    # cumulative run up to here costs nothing
STREAK_PENALTY_PER_PCT = 0.015  # each +1% beyond that: -1.5% of score
STREAK_MAX_DISCOUNT = 0.60    # never discounts below 40% of its score


# --- Cost model (identical to the Sentinel's; PKR per side) -------------
def side_cost(price: float, shares: int) -> float:
    """One side's cost in PKR: broker + SST + levies."""
    value = price * shares
    if price >= 20:
        broker = value * 0.0015
    else:
        broker = 0.03 * shares
    sst = broker * 0.16
    levies = value * 0.0005
    return broker + sst + levies


def net_return_pct(entry: float, exit_price: float) -> float:
    """Net % return of a full round trip (500-share lot)."""
    shares = 500
    buy_cost = side_cost(entry, shares)
    sell_cost = side_cost(exit_price, shares)
    gross = (exit_price - entry) * shares
    return (gross - buy_cost - sell_cost) / (entry * shares) * 100.0


# --- Scoring -------------------------------------------------------------
def close_position_score(high: float, low: float, price: float) -> float | None:
    """0 = closed on the low, 1 = closed on the high. None if no range."""
    if high is None or low is None or high <= low or price is None:
        return None
    return (price - low) / (high - low)


def volume_surge_ratio(volume: float | None, baseline: float | None) -> float | None:
    if not volume or not baseline or baseline <= 0:
        return None
    return volume / baseline


def avg_day_range_pct(session_history: list[dict] | None) -> float | None:
    """Average intraday (high-low)/close % over stored sessions.
    None while history is too thin to judge (warm-up)."""
    if not session_history or len(session_history) < MIN_HISTORY_FOR_RANGE:
        return None
    ranges = [
        (s["h"] - s["l"]) / s["c"] * 100.0
        for s in session_history[-10:]
        if s.get("h") and s.get("l") and s.get("c") and s["c"] > 0 and s["h"] > s["l"]
    ]
    if len(ranges) < MIN_HISTORY_FOR_RANGE:
        return None
    return sum(ranges) / len(ranges)


# v3.5.0 owner's whitelist addendum: the ninth tape layer.
# VOLUME PROFILE (VISIBLE-RANGE approximation on daily bars): each of
# the last VPVR_SESSIONS sessions spreads its volume evenly across its
# own high-low range, the bins aggregate into one profile, and the
# point of control (the price the market actually did its business
# at) is located. The score reads TODAY's close against that POC:
# 1.0 at the POC (trading with the heaviest accepted volume), easing
# to 0.6 at the profile high (accepted, but extended into air) and
# falling to 0.1 at the profile low (fighting the heaviest volume =
# churn below value). Missing/thin history stays None - a missing
# measurement never becomes a synthetic neutral (the rule every
# other feature in this engine follows). Kill-switch:
# vpvr_enabled in config.json (default ON).
VPVR_SESSIONS = 10
VPVR_BINS = 24
VPVR_KILL_SWITCH = "vpvr_enabled"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _vpvr_kill_switch_off() -> bool:
    try:
        cfg = json.loads((_REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        return not bool(cfg.get(VPVR_KILL_SWITCH, True))
    except Exception:  # noqa: BLE001 - default is ON
        return False


def vpvr_score(
    price: float | None, session_history: list[dict] | None
) -> float | None:
    """(0.1, 1) - where today's close sits in the 10-session volume
    profile: 1.0 at the point of control, 0.6 at the profile high,
    ~0.1 at the profile low. None when the profile cannot be built."""
    if _vpvr_kill_switch_off():
        return None
    if price is None or not session_history:
        return None
    sessions_ = [
        s for s in session_history[-VPVR_SESSIONS:]
        if s.get("h") and s.get("l") and s.get("c")
        and s.get("vol") and s["h"] > s["l"] > 0 and s["vol"] > 0
    ]
    if len(sessions_) < 3:
        return None  # too thin to profile - no evidence, no number
    lo = min(float(s["l"]) for s in sessions_)
    hi = max(float(s["h"]) for s in sessions_)
    if hi <= lo:
        return None
    profile = [0.0] * VPVR_BINS
    width = (hi - lo) / VPVR_BINS
    for s in sessions_:
        b0 = max(0, int((s["l"] - lo) / width))
        b1 = min(VPVR_BINS - 1, int((s["h"] - lo) / width))
        per = float(s["vol"]) / (b1 - b0 + 1)
        for b in range(b0, b1 + 1):
            profile[b] += per
    poc_bin = profile.index(max(profile))
    poc_price = lo + (poc_bin + 0.5) * width
    if price >= poc_price:
        span = max(hi - poc_price, 1e-9)
        return 1.0 - 0.4 * min((price - poc_price) / span, 1.0)
    span = max(poc_price - lo, 1e-9)
    return max(1.0 - 0.9 * (poc_price - price) / span, 0.1)


def multi_day_momentum_score(session_history: list[dict] | None) -> float | None:
    """(0,1) blend of the 5-session cumulative run and the green streak.
    None while fewer than 2 prior sessions are stored."""
    if not session_history or len(session_history) < 2:
        return None
    chgs = [s.get("chg") for s in session_history[-5:] if s.get("chg") is not None]
    if not chgs:
        return None
    cum = sum(chgs)
    run_part = max(0.0, min(1.0, 0.5 + cum / 12.0))
    streak = 0
    for c in reversed(chgs):
        if c > 0:
            streak += 1
        else:
            break
    streak_part = min(1.0, streak / 3.0)
    return 0.6 * run_part + 0.4 * streak_part


def breakout_10d_score(
    price: float | None, session_history: list[dict] | None
) -> float | None:
    """1.0 closing at a 10-session high, 0.6 within 2% of it, else 0.
    None while fewer than 5 prior sessions are stored."""
    if price is None or not session_history or len(session_history) < 5:
        return None
    closes = [s["c"] for s in session_history[-10:] if s.get("c")]
    if len(closes) < 5 or not all(c > 0 for c in closes):
        return None
    hi = max(closes)
    if price >= hi:
        return 1.0
    if price >= hi * 0.98:
        return 0.6
    return 0.0


def book_pressure_score(quote: dict | None) -> float | None:
    """
    The bulls-vs-bears wall, read from the LIVE order book (v2.1.6).

    Log-scaled bid-vs-ask volume imbalance: symmetric book = 0.5, a
    bid-side wall (quiet big buyer) -> 1.0, an ask-side wall (quiet big
    seller) -> 0.0. Log dampens so a 10:1 wall counts like ~4.6:1, not
    10:1 - one lucky print can't fake conviction. Returns None when the
    book is too thin to speak (both sides under BOOK_MIN_BID_ASK_VOL):
    thin books lie.
    """
    if not quote:
        return None
    bid_vol = quote.get("bidVol")
    ask_vol = quote.get("askVol")
    if not isinstance(bid_vol, (int, float)) or not isinstance(ask_vol, (int, float)):
        return None
    if bid_vol < BOOK_MIN_BID_ASK_VOL and ask_vol < BOOK_MIN_BID_ASK_VOL:
        return None
    bv, av = max(float(bid_vol), 1.0), max(float(ask_vol), 1.0)
    log_ratio = math.log10(bv / av)  # +ve: bid wall, -ve: ask wall
    return max(0.0, min(1.0, 0.5 + log_ratio / 2.0))


def aggression_score(quote: dict | None) -> float | None:
    """
    Who CROSSED the spread today: the impatient tape (v2.1.6).

    trades per share in the [calm, frantic] band maps to (0, 1):
    frantic small-print chasing scores 1.0 (bulls paying up, herding),
    block-print calm scores 0.0 (one side quietly absorbing). Cross-
    read with late momentum and the bid wall it distinguishes retail
    FOMO from a patient professional accumulator. None when the feed
    carries no trades count.
    """
    if not quote:
        return None
    trades = quote.get("trades")
    volume = quote.get("volume")
    if not isinstance(trades, (int, float)) or not volume or volume <= 0:
        return None
    tps = trades / volume
    span = AGGRESSION_FRANTIC_TPS - AGGRESSION_CALM_TPS
    return max(0.0, min(1.0, (tps - AGGRESSION_CALM_TPS) / span))


# Live weights: WEIGHTS until (or unless) a learned refit overrides.
_LIVE_WEIGHTS: dict[str, float] | None = None


def set_live_weights(w: dict[str, float] | None) -> None:
    """Install refit-learned weights (None reverts to the base book)."""
    global _LIVE_WEIGHTS
    _LIVE_WEIGHTS = w


def _W(key: str) -> float:
    return (_LIVE_WEIGHTS or WEIGHTS)[key]


def score_symbol(row: dict) -> float | None:
    """
    Composite late-surge score in (0, 1) for one quote row.

    Missing features renormalize (weight coverage reported); a row with
    no usable price, no surge baseline, dead final-hour tape, or -
    since v2.1.5 - an average daily range too thin to ever pay the 2%
    target scores None and is never picked.
    """
    price = row.get("price")
    if price is None or price < MIN_ABS_PRICE or price > MAX_PRICE_PKR:
        return None
    day = row.get("change_pct")
    if day is not None and day >= LOCKED_MIN_PCT:
        return None  # upper-circuit lock: no sellers at the close, unbuyable
    if (row.get("value") or 0) < MIN_DAY_VALUE:
        return None
    baseline = row.get("avg_volume_20")
    if not baseline or baseline <= 0:
        return None  # no surge baseline -> surge quality unknowable
    # Average daily traded value must clear the liquidity bar, or one
    # 500-share lot IS the market.
    if baseline * price < MIN_AVG_VALUE:
        return None
    # Range-sufficiency gate: with enough history, a stock that cannot
    # travel 3% in a day cannot pay a 2% net target tomorrow.
    hist = row.get("session_history")
    avg_range = avg_day_range_pct(hist)
    if avg_range is not None and avg_range < MIN_DAY_RANGE_PCT:
        return None

    parts: list[tuple[float, float]] = []  # (weight, value)

    cps = close_position_score(row.get("high"), row.get("low"), price)
    if cps is not None:
        parts.append((_W("close_position"), cps))

    vsr = volume_surge_ratio(row.get("volume"), row.get("avg_volume_20"))
    if vsr is not None:
        parts.append((_W("volume_surge"), min(1.0, vsr / 3.0)))  # 3x = max

    late = row.get("late_momentum_pct")
    if late is not None:
        parts.append((_W("late_momentum"), max(0.0, min(1.0, 0.5 + late / 4.0))))

    if day is not None:
        parts.append((_W("day_momentum"), max(0.0, min(1.0, 0.5 + day / 8.0))))

    flow = row.get("sector_flow_score")
    if flow is not None:
        parts.append((_W("sector_flow"), max(0.0, min(1.0, flow))))

    mdm = multi_day_momentum_score(hist)
    if mdm is not None:
        parts.append((_W("multi_day_momentum"), mdm))

    brk = breakout_10d_score(price, hist)
    if brk is not None:
        parts.append((_W("breakout_10d"), brk))

    bp = book_pressure_score(row.get("quote"))
    if bp is not None:
        parts.append((_W("book_pressure"), bp))

    agg = aggression_score(row.get("quote"))
    if agg is not None:
        parts.append((_W("aggression"), agg))

    vp = vpvr_score(price, hist)
    if vp is not None:
        parts.append((_W("vpvr"), vp))

    if not parts:
        return None
    w_sum = sum(w for w, _ in parts)
    if w_sum <= 0:
        return None
    return sum(w * v for w, v in parts) / w_sum


# The CORE thesis features whose verification the coverage floor
# measures: is this surge real (price/volume/momentum/sector)? The
# enhancement layers (multi-day, breakout, book, aggression) are
# opportunistic - they ADD precision when their data exists but their
# absence must never block a pick (warm-up weeks, thin books).
CORE_WEIGHTS = (
    "close_position", "volume_surge", "late_momentum",
    "day_momentum", "sector_flow",
)


def weight_coverage_of(row: dict) -> float:
    """Fraction of CORE weight verifiable for this row (0..1). The
    MIN_WEIGHT_COVERAGE floor applies to this core only; the
    enhancement layers contribute score when present, nothing when
    absent - never a refusal."""
    coverage = 0.0
    if close_position_score(row.get("high"), row.get("low"), row.get("price")) is not None:
        coverage += WEIGHTS["close_position"]
    if volume_surge_ratio(row.get("volume"), row.get("avg_volume_20")) is not None:
        coverage += WEIGHTS["volume_surge"]
    if row.get("late_momentum_pct") is not None:
        coverage += WEIGHTS["late_momentum"]
    if row.get("change_pct") is not None:
        coverage += WEIGHTS["day_momentum"]
    if row.get("sector_flow_score") is not None:
        coverage += WEIGHTS["sector_flow"]
    core_total = sum(WEIGHTS[k] for k in CORE_WEIGHTS)
    return coverage / core_total if core_total else 0.0


def streak_discount(
    change_pct: float | None, recent_changes: list[float] | None
) -> tuple[float, str]:
    """
    The FPJM-trap risk adjustment for one candidate: (discount 0..1,
    human-readable reason). NO refusal - the owner's clarified design
    is data-weighted ranking, not bans.

    recent_changes = prior sessions' daily change %, NEWEST LAST, as
    maintained by run_eod.update_close_history. Today's own change comes
    separately (the live row); a lock TODAY is already unbuyable (the
    no-sellers rule - physics, not opinion).

    The measured quantity: cumulative run = today + the last 3
    sessions. Up to +10% total is a normal fresh surge (the exact
    thing this strategy hunts) - zero discount. Beyond that, every
    additional +1% on the tape discounts the score by 1.5%, because
    each point of existing run is more of the move already consumed.
    A +25% 4-day runner carries a ~22.5% discount - heavily penalized
    in the ranking, still eligible. Down-lock days discount too (a
    crashing tape is its own trap).
    """
    if not recent_changes:
        return 0.0, ""
    lookback = recent_changes[-3:]
    run = (change_pct or 0.0) + sum(lookback)
    over = run - STREAK_FREE_RUN_PCT
    if over <= 0:
        return 0.0, ""
    discount = min(STREAK_MAX_DISCOUNT, over * STREAK_PENALTY_PER_PCT)
    peak = max((abs(c) for c in lookback), default=0.0)
    kind = "down-lock day in history" if any(c <= -9.0 for c in lookback) else (
        "near-lock day in history" if peak >= 9.0 else "extended multi-day run"
    )
    return (
        discount,
        f"⚠ streak risk: {run:+.0f}% cumulative 4-session run ({kind}) - "
        f"score discounted {discount * 100:.0f}%",
    )


# v2.3.2: the per-symbol memory loads ONCE per pick run (the report is
# a session-scale artifact; re-reading per symbol is waste).
_LOCK_MEMORY_CACHE: dict[str, dict] | None = None


def _load_lock_memory_once() -> dict[str, dict]:
    global _LOCK_MEMORY_CACHE
    if _LOCK_MEMORY_CACHE is None:
        try:
            from lock_memory import load_memory
            _LOCK_MEMORY_CACHE = load_memory()
        except Exception:  # noqa: BLE001
            _LOCK_MEMORY_CACHE = {}
    return _LOCK_MEMORY_CACHE


def pick_top(
    cross_section: list[dict],
    top_n: int = MAX_POSITIONS,
    close_history: dict[str, list[float]] | None = None,
    min_late: float | None = None,
    window_open: dict | None = None,
    allow_degraded: bool = False,
) -> list[dict]:
    """
    Rank and return the evening pick set with full entry context.

    v2.1.0 dead-stock gate: a candidate whose final-hour drift is not
    VERIFIED POSITIVE is refused outright - the ledger's only losses
    were exactly these flat-tape names. Coverage floor on the CORE
    thesis features; the enhancement layers contribute when present.

    v2.1.2 streak risk-ADJUSTMENT: streak candidates are never banned -
    their rank is discounted by the measured exhaustion risk, and the
    flag travels with the signal so the owner decides with the data.

    v2.1.5 multi-session layer: `close_history` carries full session
    records (chg, close, high, low, volume); the streak discount reads
    the changes, the scorer reads the rest.

    v2.2.0 red-tape bar: `min_late` lets the runner raise the liveness
    requirement on hostile market days - data-weighted selectivity,
    not a ban (a surge on a red tape must prove itself harder).

    v2.2.2 window persistence: `window_open` carries the :00 read of
    the tape; picks that kept rising into the analysis read get their
    rank discounted (the move is spending itself inside the window),
    and the measured drift travels on every pick.

    v2.2.3 degraded mode: `allow_degraded=True` substitutes the
    day-change shape when the final hour is UNVERIFIABLE (reference
    capture lost) - an instrument failure must never masquerade as a
    tape verdict. Every pick carries `degraded: True` so the cards
    say exactly what evidence produced it.
    """
    bar = MIN_LATE_MOMENTUM_PCT if min_late is None else min_late
    _LOCK_MEMORY_CACHE = _load_lock_memory_once()
    # v2.4.0 - the daily market-lesson overlay from the Sentinel's
    # tape: confirmed-dead names are refused, confirmed-trending names
    # get small rank context. A failed load is a no-op.
    # v3.0.0: only loaded when the memory layers are armed - the clean
    # engine shows no learned context on the card.
    if MEMORY_LAYERS_ENABLED:
        try:
            from market_lessons import load_market_lessons as _load_mkt
            _MKT = _load_mkt()
        except Exception:  # noqa: BLE001 - offline-safe
            _MKT = {"dead": set(), "trending": set(), "last": None}
    else:
        _MKT = {"dead": set(), "trending": set(), "last": None}
    scored: list[tuple[float, float, dict, float, str, bool]] = []  # adj, raw, row, cov, reason, degraded
    for row in cross_section:
        s = score_symbol(row)
        if s is None:
            continue
        late = row.get("late_momentum_pct")
        deg = False
        if late is None:
            # v2.2.3 DEGRADED-MODE FALLBACK: an unverifiable final hour
            # (reference slot dropped -> late is None everywhere) is an
            # INSTRUMENT failure, not a tape verdict. Refusing everything
            # would publish a false "no live candidate" (the 2026-09-18
            # near-miss). Instead: fall back to the day-change shape -
            # still a close-surge, still verifiable from the feed itself
            # - and mark every pick DEGRADED so the owner knows exactly
            # what he is holding.
            day = row.get("change_pct")
            if not (allow_degraded and day is not None and day >= bar):
                continue
            late = day  # the fallback evidence; flagged on every card
            # Shadow the row with the substituted evidence so the
            # weight-coverage floor scores the evidence we actually
            # have (otherwise every degraded candidate is refused on
            # coverage and the fallback is dead code).
            row = {**row, "late_momentum_pct": day}
            deg = True
        elif late < bar:
            continue  # dead final-hour tape -> no pick
        coverage = weight_coverage_of(row)
        if coverage < MIN_WEIGHT_COVERAGE:
            continue
        prior_changes = [
            sess.get("chg")
            for sess in (close_history or {}).get(row["symbol"]) or []
            if sess.get("chg") is not None
        ]
        discount, reason = streak_discount(row.get("change_pct"), prior_changes)
        # v2.3.2 per-symbol lock memory: the symbol's OWN 175-session
        # lock record adjusts its rank - proven continuers earn a
        # bonus, chronic fakes a heavy discount, zero-win fakes are
        # refused outright (a verdict, not a ranking question).
        # Unknown symbols pass untouched. A failed memory load is a
        # no-op: learning must never break a pick run.
        # v3.0.0: retired from the production path - runs only when
        # MEMORY_LAYERS_ENABLED is armed.
        _mem_factor, _mem_flag = 1.0, ""
        if MEMORY_LAYERS_ENABLED:
            try:
                from lock_memory import memory_factor
                _mem_factor, _mem_flag = memory_factor(row["symbol"], _LOCK_MEMORY_CACHE)
            except Exception:  # noqa: BLE001 - offline-safe
                _mem_factor, _mem_flag = 1.0, ""
        # v2.4.0 market-lesson factor: dead-confirmed -> 0.0 (refused),
        # trend-confirmed -> +3% rank. None = untouched.
        # v3.0.0: same retirement - armed only with the memory layers.
        if MEMORY_LAYERS_ENABLED:
            try:
                from market_lessons import memory_factor as _mkt_factor
                _mk = _mkt_factor(row["symbol"], _MKT)
            except Exception:  # noqa: BLE001 - offline-safe
                _mk = None
            if _mk is not None:
                _mem_factor = _mem_factor * _mk if _mem_factor else _mk
                if _mk == 0.0:
                    _mem_flag = (
                        f"market lesson: dead {3}+ sessions - no overnight "
                        "fuel (rolling tape)"
                    )
                elif _mk > 1.0:
                    _mem_flag = (
                        f"market lesson: trending {3}+ sessions "
                        "(rolling tape)"
                    )
        adj = s * (1.0 - discount) * _mem_factor
        if adj <= 0.0:
            # A zero-win fake (memory factor 0.0) or market-confirmed
            # dead name is REFUSED, not demoted - with a thin candidate
            # field a score-0.0 row would still surface as "the pick".
            continue
        mem_reason = reason
        if _mem_flag:
            mem_reason = f"{reason} | {_mem_flag}" if reason else _mem_flag
        scored.append((adj, s, row, coverage, mem_reason, deg))

    scored.sort(key=lambda t: t[0], reverse=True)
    picks = []
    for adj, raw, row, coverage, reason, deg in scored[:top_n]:
        picks.append({
            "symbol": row["symbol"],
            "score": round(adj, 4),
            "raw_score": round(raw, 4),
            "entry_price": row["price"],
            "close_position": close_position_score(
                row.get("high"), row.get("low"), row["price"]
            ),
            "volume_surge": volume_surge_ratio(
                row.get("volume"), row.get("avg_volume_20")
            ),
            "change_pct": row.get("change_pct"),
            "late_momentum_pct": row.get("late_momentum_pct"),
            "book_pressure": (round(bp, 3) if (bp := book_pressure_score(row.get("quote"))) is not None else None),
            "aggression": (round(agg, 3) if (agg := aggression_score(row.get("quote"))) is not None else None),
            "multi_day": (
                round(m, 3)
                if (m := multi_day_momentum_score(row.get("session_history"))) is not None
                else None
            ),
            "breakout": (
                round(b, 3)
                if (b := breakout_10d_score(row.get("price"), row.get("session_history"))) is not None
                else None
            ),
            "vpvr": (
                round(v, 3)
                if (v := vpvr_score(row.get("price"), row.get("session_history"))) is not None
                else None
            ),
            "weight_coverage": round(coverage, 3),
            "streak_flag": reason or None,
            "lock_memory_flag": _mem_flag or None,
            "market_context": (
                ( (_MKT.get("last") or {}).get("taught") or None )
                if isinstance(_MKT, dict) else None
            ),
            "degraded": deg,
        })
    return persistence_discount(picks, window_open)


# --- Tracing (the next morning) ------------------------------------------
def trace_pick(pick: dict, snapshot: dict, now_utc: datetime) -> dict | None:
    """
    One morning tick against one open pick. Returns a closed-outcome
    dict when the pick exits, None while it stays open.

    Exit ladder (checked in order):
      * price >= entry * (1 + TARGET_PCT/100)  -> WIN (sold into strength)
      * price <= entry * (1 + STOP_PCT/100)    -> STOP
      * now past 11:30 PKT                      -> FORCE close at market
    """
    quotes = snapshot.get("quotes") or {}
    q = quotes.get(pick["symbol"])
    if not q:
        return None
    price = q.get("price")
    if price is None or price <= 0:
        return None

    entry = pick["entry_price"]
    target = entry * (1 + TARGET_PCT / 100.0)
    stop = entry * (1 + STOP_PCT / 100.0)

    # v2.2.6 touch exits: the poll's day-high/day-low cover the whole
    # session, and every EOD hold bought at the PRIOR close - so the
    # entire day is post-entry time and an extreme at/above the barrier
    # is a touch a resting order would have filled. This closes the
    # STL-class blindness (poll price +1.5% while the tape printed the
    # target between polls). Conventions match exit_frontier: a fill on
    # the touch prints at the barrier; when BOTH extremes touched and
    # the poll price sits between them, print order is unknowable at
    # 15-min granularity -> the adverse-selection rule says STOP.
    day_high = q.get("high")
    day_low = q.get("low")
    touched_target = isinstance(day_high, (int, float)) and day_high >= target
    touched_stop = isinstance(day_low, (int, float)) and day_low <= stop

    minutes = now_utc.hour * 60 + now_utc.minute
    outcome = None
    exit_price = price
    via_touch = False
    if price >= target:
        outcome = "WIN"
    elif price <= stop:
        outcome = "STOP"
    elif touched_stop:  # stop outranks an unseen-order touch (adverse selection)
        outcome = "STOP"
        if not (isinstance(day_low, (int, float)) and price <= day_low):
            exit_price = stop
            via_touch = True
    elif touched_target:
        outcome = "WIN"
        exit_price = target
        via_touch = True
    elif minutes >= FORCE_CLOSE_MIN_UTC:
        outcome = "FORCE"
    if outcome is None:
        return None

    return {
        "symbol": pick["symbol"],
        "pick_date": pick["pick_date"],
        "entry_price": entry,
        "exit_price": exit_price,
        "outcome": outcome,
        "via_touch": via_touch,
        "net_return_pct": round(net_return_pct(entry, exit_price), 3),
        "closed_at_utc": now_utc.isoformat(),
        "entry_score": pick.get("score"),
        "close_position": pick.get("close_position"),
        "volume_surge": pick.get("volume_surge"),
        # v2.2.0: the full evidence travels into the ledger, so the
        # weekly refit can learn which features actually pay.
        **{
            k: pick[k]
            for k in (
                "late_momentum_pct", "book_pressure", "aggression",
                "multi_day", "breakout", "streak_flag", "weight_coverage",
            )
            if pick.get(k) is not None
        },
    }


# --- Persistence ----------------------------------------------------------
def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def append_ledger(path: Path, outcomes: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for o in outcomes:
            fh.write(json.dumps(o, ensure_ascii=False) + "\n")
    return len(outcomes)


def ledger_summary(path: Path) -> dict:
    rows = []
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(json.loads(line))
    if not rows:
        return {"trades": 0}
    wins = sum(1 for r in rows if r["outcome"] == "WIN")
    nets = [r["net_return_pct"] for r in rows]
    return {
        "trades": len(rows),
        "wins": wins,
        "win_rate_pct": round(100.0 * wins / len(rows), 1),
        "avg_net_pct": round(sum(nets) / len(nets), 3),
        "sum_net_pct": round(sum(nets), 2),
    }
