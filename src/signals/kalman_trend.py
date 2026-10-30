"""The Kalman Trend, the owner's sole intraday strategy (owner order 2026-10-30).

The owner's order: remove the ICT/SMC strategy from quant of Rehan intraday,
and introduce the Kalman Trend only, as the sole strategy for the intraday
signals. Owner-confirmed scope:

  * bars: the intraday PSX band feed, the same captured tape bars the
    scanner already loads (src/data/tape_bars.py);
  * parameters: grid-fit in GitHub Actions (scripts/kalman_grid_fit.py),
    never on the owner's PC;
  * rules: NEW simpler rules - the Kalman's flip is the entry, and the
    TP/SL come from the owner's law for every name (+2% target, -1%
    stop, one call a day; no sweep, no structure shift, no FVG, no
    retest, no ceiling);
  * delivery: unchanged - the same relay, cadence and emails.

One filter per symbol, causal, nothing looks ahead:

  A local-level plus slope state vector [level, slope] steps through the
  completed one-minute closes in log space, and a single scalar update
  folds each new close in. `q` is the per-bar process noise on the slope
  and `r` the observation noise (both dimensionless log-price variance).
  The trend is the sign of the estimated slope, with a hysteresis band:
  the state only moves off its previous sign when the slope crosses the
  threshold, so one noisy print cannot flip the view.

The flip is the entry; the owner's TP/SL law is the whole plan:
  entry  - the bar the trend flips UP (and only while the flip is fresh,
           KALMAN_SETUP_BARS bars old at most);
  stop   - entry minus the owner's fixed -1% (owner answer 2026-10-30:
           "I only one call a day with 2% TP and -1% SL"), the same
           number for every name;
  exit   - the target (owner's +TARGET_PCT) or the stop, whichever the
           tape touches first. The one-call-a-day lock and the paper
           state machine already carry it (src/signals/trade_state.py).

There is no reward-risk floor gate on a flip entry: the owner's TP/SL law
(TP +TARGET_PCT, the flip's own stop) is the plan, the round-trip cost of
src/config rides every row, and EXPECTANCY is measured by the Actions
grid fit and delivered as evidence - never as one scan's veto (SO-3: the
owner asked for the flip alone, not for a second hidden strategy).

NOT a live draw of institutional intent, never a probability of winning
(SO-3). Every signal is a paper reference marked entry_basis, and the
modelled round-trip cost of src/config stands between it and the owner.
Asia/Karachi, UTC+5. Signal-only: no broker orders (SO-1).
"""
from __future__ import annotations

import math
from datetime import timedelta
from statistics import median

from src import config
from src.data.sessions import band_bounds, current_band


def _bump(tally: dict | None, key: str) -> None:
    """Count one rejection reason, when the caller wants the why."""
    if tally is not None:
        tally[key] = tally.get(key, 0) + 1


def filter_series(closes: list[float], q: float, r: float,
                  threshold: float) -> list[dict[str, float]]:
    """Run the causal level+slope Kalman over log closes.

    Returns one record per bar: the posterior level, slope, the trend state
    AFTER that bar (-1, 0, +1 with the hysteresis band) and whether the
    state's move to +1 was the fresh flip of that bar. Level and slope are
    log-price units: exp(level) is the price, exp(slope) the per-minute
    drift. No observation ahead of the bar is ever read.
    """
    level, slope = math.log(closes[0]), 0.0
    p11, p12, p22 = 1.0, 0.0, 1.0
    state = 0
    out = []
    for close in closes:
        # predict: level += slope, slope unchanged; P = F P F' + Q.
        level, slope = level + slope, slope
        p11_old, p12_old, p22_old = p11, p12, p22
        # F = [[1,1],[0,1]] pre-multiplied, plus Q = diag(0, q).
        p11 = p11_old + 2 * p12_old + p22_old
        p22 = p22_old + q
        p12 = p12_old + p22_old
        # update: one scalar observation of the level.
        innovation = math.log(close) - level
        s_den = p11 + r
        k1, k2 = p11 / s_den, p12 / s_den
        level += k1 * innovation
        slope += k2 * innovation
        p11 -= k1 * p11
        p12, p22 = p12 - k1 * p12, p22 - k2 * p12
        # hysteresis: the state only re-crosses through the threshold.
        if slope > threshold:
            new_state = 1
        elif slope < -threshold:
            new_state = -1
        else:
            new_state = state
        flip_up = new_state == 1 and state != 1
        state = new_state
        out.append({"level": level, "slope": slope, "state": state,
                    "flip_up": flip_up})
    return out


def candidate(symbol: str, rows: list, session,
              tally: dict | None = None) -> dict | None:
    """Return a candidate only on a fresh upward trend flip.

    Same call shape the scanner and its tests always used. The gates below
    are the data-honesty gates the whole system shares (ETF anonymity, the
    band clock, completed bars, positive prices, a real tape volume, the
    price and turnover floors); the STRATEGY itself is the flip and only
    the flip.
    """
    if config.is_etf_symbol(symbol) or session.as_of.tzinfo is None:
        _bump(tally, "etf_or_naive_tz")
        return None
    band = current_band(session.as_of)
    if band is None:
        _bump(tally, "no_market_band")
        return None
    opens, closes = band_bounds(session.day, band)
    if session.as_of >= closes - timedelta(
            minutes=config.KALMAN_LAST_ENTRY_MINUTES):
        _bump(tally, "near_band_close")
        return None
    # Bar timestamps denote minute OPEN, not close. An in-progress minute is
    # never evidence, even when the scan runs at HH:MM:30.
    rows = [b for b in rows if opens <= b.timestamp
            and b.timestamp + timedelta(minutes=1) <= session.as_of]
    if len(rows) < config.MIN_BARS_PER_SYMBOL:
        _bump(tally, "bars_under_strategy_minimum")
        return None
    if session.as_of - (rows[-1].timestamp + timedelta(minutes=1)) > timedelta(
            seconds=config.KALMAN_MAX_SIGNAL_AGE_SECONDS):
        _bump(tally, "stale_print")
        return None
    gap_start = 0
    for i, b in enumerate(rows):
        values = (b.open, b.high, b.low, b.close)
        if (not all(math.isfinite(v) and v > 0 for v in values)
                or b.high < max(b.open, b.close) or b.low > min(b.open, b.close)
                or b.high < b.low or b.volume is None
                or not math.isfinite(b.volume) or b.volume < 0):
            _bump(tally, "impossible_row")
            return None
        # No fabricated continuity across missing prints or the break.
        if i and b.timestamp - rows[i - 1].timestamp != timedelta(minutes=1):
            gap_start = i
    rows = rows[gap_start:]
    if len(rows) < config.MIN_BARS_PER_SYMBOL or rows[-1].close < config.MIN_PRICE:
        _bump(tally, "too_short_after_gap_or_penny")
        return None
    turnover = sum(b.close * b.volume for b in rows)
    if turnover < config.MIN_SESSION_TRADED_VALUE:
        _bump(tally, "under_min_session_traded_value")
        return None

    closes_series = [b.close for b in rows]
    trace = filter_series(closes_series, config.KALMAN_Q,
                          config.KALMAN_R, config.KALMAN_FLIP_THRESHOLD)
    last = rows[-1]
    flips = [i for i, rec in enumerate(trace) if rec["flip_up"]]
    if not flips:
        _bump(tally, "no_upward_flip_yet")
        return None
    flip_index = flips[-1]
    if (len(rows) - 1 - flip_index) > config.KALMAN_SETUP_BARS:
        _bump(tally, "flip_not_fresh")
        return None
    if trace[-1]["state"] != 1:
        _bump(tally, "trend_not_currently_up")
        return None
    entry = last.close
    flip_bar = rows[flip_index]
    # The owner's fixed -1% stop under the entry, the same number for
    # every name (owner answer 2026-10-30, 2% TP / -1% SL).
    stop = round(entry * (1 - config.KALMAN_STOP_PCT), 4)
    if entry <= stop or entry <= 0:
        _bump(tally, "stop_not_below_entry")
        return None
    target = round(entry * (1 + config.TARGET_PCT), 4)
    risk = (entry - stop) / entry
    if risk > config.KALMAN_MAX_RISK_PCT:
        _bump(tally, "risk_outside_band")
        return None
    net_reward = config.TARGET_PCT - config.round_trip_cost()
    reward_risk = net_reward / (risk + config.round_trip_cost())
    # Trend quality, measured: the slope's own size against the day's typical
    # move, and how long the up-state has held. Ranking measures setup
    # quality, never a probability of winning (SO-3).
    slope = trace[-1]["slope"]
    slope_pcts = [abs(trace[i]["slope"]) for i in range(1, len(trace))] or [0.0]
    slope_ref = median(slope_pcts) or 1e-9
    age = len(rows) - 1 - flip_index + 1
    score = min(100.0, 50 + min(20, 20 * min(1.0, abs(slope) / slope_ref))
                + min(15, age) + min(15, 5 * reward_risk))
    return {
        "symbol": symbol, "score": round(score, 2),
        "strategy": config.SCANNER_VERSION, "side": "LONG",
        "price": {"last": entry}, "stop_loss": stop, "target": target,
        "risk_pct": risk, "net_reward_risk": reward_risk,
        "setup": {
            "slope_per_minute_log": slope,
            "flip_at": flip_bar.timestamp.isoformat(),
            "flip_close": flip_bar.close,
            "trend_age_bars": age,
            "hysteresis_log_per_minute": config.KALMAN_FLIP_THRESHOLD,
            "process_noise_q": config.KALMAN_Q,
            "observation_noise_r": config.KALMAN_R,
        },
        "volume": {"traded_value_estimate": turnover,
                   "volume_source": "captured bar volume"},
        "last_bar": last.timestamp.isoformat(), "bars": len(rows),
        "entry_basis": "latest completed close on a fresh upward trend flip; "
                       "paper reference, not a fill",
    }
