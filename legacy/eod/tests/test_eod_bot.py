"""
Sentinel-EOD tests - the strategy's contract:

  * scoring: winners on top, junk filtered (thin, sub-20 PKR, no data);
  * the DEAD-STOCK GATE: flat final-hour tape is never picked
    (the Sep-16 ledger's only losses), positive late momentum required;
  * tracing: +2% win, -1% stop, band = hold, force-close after 11:30,
    prices must MOVE UP from entry (the buy-at-close rule);
  * net returns: the real cost stack, both tiers;
  * ledger: append + summary round-trip.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import eod_bot  # noqa: E402
from eod_bot import (  # noqa: E402
    MIN_LATE_MOMENTUM_PCT,
    MIN_WEIGHT_COVERAGE,
    TARGET_PCT,
    FORCE_CLOSE_MIN_UTC,
    net_return_pct,
    pick_top,
    score_symbol,
    streak_discount,
    trace_pick,
    append_ledger,
    ledger_summary,
)


def ts(h: int, m: int) -> datetime:
    return datetime(2026, 9, 17, h, m, tzinfo=timezone.utc)


# ----------------------------- scoring -----------------------------------
def _row(**kw):
    base = {
        "symbol": "TEST",
        "price": 100.0,
        "high": 101.0,
        "low": 96.0,
        "volume": 5_000_000,
        "value": 400_000_000.0,
        "change_pct": 2.5,
        "late_momentum_pct": 1.0,
        "avg_volume_20": 4_000_000,
    }
    base.update(kw)
    return base


def test_pick_top_orders_by_score_and_drops_junk():
    rows = [
        _row(symbol="WEAK", late_momentum_pct=0.2, change_pct=-2.0,
             high=102.0, low=95.0),         # alive but falling day
        _row(symbol="STRONG", late_momentum_pct=1.8, change_pct=4.0,
             high=104.5, low=100.0, price=104.0),  # surging, closes near HIGH
        _row(symbol="THIN", avg_volume_20=50_000),          # illiquid
        _row(symbol="PENNY", price=12.0),                    # flat-fee tier
        _row(symbol="PENNY2", price=50.0, avg_volume_20=100_000),  # thin avg
        _row(symbol="LOCKED", change_pct=10.05),             # circuit lock
        _row(symbol="NODATA", price=None),                   # dead feed row
    ]
    picks = pick_top(rows)
    names = [p["symbol"] for p in picks]
    assert names[0] == "STRONG"
    assert "THIN" not in names and "PENNY" not in names and "NODATA" not in names
    assert "LOCKED" not in names  # upper-circuit names are unbuyable


def test_memory_layers_default_off_and_clean_pick_unaffected():
    """v3.0.0 owner simplification: the per-symbol memory, market
    lessons and refit weights are OUT of the production pick path by
    default - the clean engine reads the tape only. A symbol with a
    poison record in the memory cache still picks on its own tape
    strength when the layers are disarmed."""
    assert eod_bot.MEMORY_LAYERS_ENABLED is False
    eod_bot._LOCK_MEMORY_CACHE = {"POISON": {"n": 4, "win_pct": 0.0, "net": -6.9}}
    try:
        picks = pick_top([_row(symbol="POISON")])
    finally:
        eod_bot._LOCK_MEMORY_CACHE = None
    assert len(picks) == 1 and picks[0]["symbol"] == "POISON"
    assert picks[0]["lock_memory_flag"] is None


def test_score_symbol_needs_volume_baseline():
    row = _row()
    del row["avg_volume_20"]
    assert score_symbol(row) is None  # no baseline -> not scorable
    row["avg_volume_20"] = 4_000_000
    s = score_symbol(row)
    assert s is not None and 0.0 <= s <= 1.0


def test_score_symbol_rewards_late_surge_over_late_fade():
    surging = score_symbol(_row(symbol="A", late_momentum_pct=2.0,
                                change_pct=4.0, high=105.0, low=100.0))
    fading = score_symbol(_row(symbol="B", late_momentum_pct=-2.0,
                               change_pct=-3.0, high=101.0, low=95.0))
    assert surging > fading


def test_score_symbol_uses_sector_flow_when_present():
    no_flow = score_symbol(_row(symbol="A", sector_flow_score=None))
    with_flow = score_symbol(_row(symbol="A", sector_flow_score=0.8))
    assert with_flow > no_flow  # the v2.1.0-activated feature pulls up


# ------------- the MULTI-SESSION LAYER (v2.1.5, 20-indicator depth) -------
def _hist(*chgs, hi_lo_scale=0.05):
    """Session records from daily changes; range scales with |chg| so
    default records pass the 3% range gate (|chg|>=4% -> ~5-9%)."""
    price = 100.0
    out = []
    for c in chgs:
        price = price * (1 + c / 100.0)
        half = price * hi_lo_scale
        out.append({"chg": c, "c": round(price, 2),
                    "h": round(price + half, 2), "l": round(price - half, 2)})
    return out


def test_multi_day_momentum_rising_beats_flat():
    from eod_bot import multi_day_momentum_score
    assert multi_day_momentum_score(_hist(2, 2, 2, 2)) > multi_day_momentum_score(_hist(-1, 0, 1, 0))
    assert multi_day_momentum_score(_hist(2, 2, 2)) is not None
    assert multi_day_momentum_score([{"chg": 1.0}]) is None  # too thin


def test_breakout_10d_scores_new_high():
    from eod_bot import breakout_10d_score
    hist = _hist(1, 1, 1, 1, 1)
    last_close = hist[-1]["c"]
    assert breakout_10d_score(last_close * 1.001, hist) == 1.0   # new high
    assert breakout_10d_score(last_close * 0.99, hist) == 0.6    # near high
    assert breakout_10d_score(last_close * 0.9, hist) == 0.0     # mid-range
    assert breakout_10d_score(100.0, [{"c": 100}] * 4) is None   # thin


def test_range_gate_refuses_dead_volatility():
    """A stock that travels ~1% a day can never pay a 2% net target -
    refused once enough history proves it. Thin history = warm-up pass."""
    tight = _hist(0.2, 0.2, 0.2, 0.2, hi_lo_scale=0.005)  # ~1% ranges
    row = _row(symbol="DEAD", session_history=tight)
    assert score_symbol(row) is None
    assert score_symbol(_row(symbol="WARM", session_history=tight[:2])) is not None


# ------------- the ORDER-BOOK LAYER (v2.1.6, bulls vs bears) --------------
def test_book_pressure_reads_bid_and_ask_walls():
    """The quiet big buyer parks size on the bid -> score > 0.5; the
    quiet big seller stacks the ask -> < 0.5; symmetric book = 0.5."""
    from eod_bot import book_pressure_score
    bull = book_pressure_score({"bidVol": 50_000, "askVol": 5_000})
    bear = book_pressure_score({"bidVol": 5_000, "askVol": 50_000})
    fair = book_pressure_score({"bidVol": 20_000, "askVol": 20_000})
    assert bull > 0.75 and bear < 0.25 and fair == pytest.approx(0.5)
    # log dampening: 3:1 maps to 0.75 (a linear scale would need 6:1);
    # anything beyond 10:1 saturates at maximal conviction
    assert book_pressure_score({"bidVol": 30_000, "askVol": 10_000}) == pytest.approx(0.75, abs=0.02)
    assert book_pressure_score({"bidVol": 300_000, "askVol": 10_000}) == 1.0


def test_book_pressure_thin_book_stays_silent():
    """A book with both sides under the floor says nothing - None, so
    the feature abstains instead of voting on noise."""
    from eod_bot import book_pressure_score
    assert book_pressure_score({"bidVol": 500, "askVol": 800}) is None
    assert book_pressure_score({}) is None
    assert book_pressure_score(None) is None


def test_aggression_reads_the_impatient_tape():
    """Few large prints (absorbing) score low; constant small hitting
    (attacking) scores high; no trades data abstains."""
    from eod_bot import aggression_score
    absorbing = aggression_score({"trades": 500, "volume": 5_000_000})
    attacking = aggression_score({"trades": 400_000, "volume": 5_000_000})
    assert absorbing < 0.2 and attacking == 1.0
    assert aggression_score({"volume": 5_000_000}) is None


def test_book_features_flow_into_scoring_and_cards():
    """A bid-wall bull tape outscores the identical chart with an ask
    wall; the published card carries both reads."""
    bull = _row(symbol="BULL", quote={"bidVol": 60_000, "askVol": 6_000,
                                       "trades": 500, "volume": 3_000_000})
    bear = _row(symbol="BEAR", quote={"bidVol": 6_000, "askVol": 60_000,
                                       "trades": 500, "volume": 3_000_000})
    assert score_symbol(bull) > score_symbol(bear)
    card = pick_top([bull])[0]
    assert card["book_pressure"] > 0.75 and card["aggression"] is not None


def test_multi_session_features_raise_coverage_and_score():
    """With history attached (all sectors flowing), coverage reaches 1.0;
    a surging 5-day runner closing at a new high outscores the same tape
    without history."""
    from eod_bot import weight_coverage_of
    row = _row(symbol="A", sector_flow_score=0.5,
               session_history=_hist(1, 2, 1, 2, 2))
    assert weight_coverage_of(row) == pytest.approx(1.0)
    s_with = score_symbol(row)
    s_without = score_symbol(_row(symbol="A", sector_flow_score=0.5))
    assert s_with > s_without


def test_pick_top_with_session_history_end_to_end():
    """Full pipeline: history records flow through the streak discount
    AND the multi-session features. STRONG closes at a 10-session high
    (breakout verified) and rides a green streak - it must outrank the
    identical tape with no history."""
    strong = _row(symbol="STRONG", late_momentum_pct=1.5, change_pct=3.0,
                  price=110.0, high=110.5, low=108.0,
                  session_history=_hist(1, 2, 1, 2, 2))
    flat = _row(symbol="FLAT", late_momentum_pct=1.5, change_pct=3.0,
                price=110.0, high=110.5, low=108.0)
    picks = pick_top([flat, strong], close_history={
        "STRONG": _hist(1, 2, 1, 2, 2), "FLAT": _hist(1, 2, 1, 2, 2)})
    assert picks and picks[0]["symbol"] == "STRONG"


def test_close_history_session_records_and_map():
    """update_close_history stores full records; session_history_map
    returns prior sessions newest-last, today excluded."""
    from run_eod import update_close_history, session_history_map
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        import run_eod
        run_eod.CLOSE_HISTORY = Path(td) / "h.json"
        day1 = {"A": {"changePercent": 0.05, "price": 105.0,
                      "high": 106.0, "low": 103.0, "volume": 900}}
        update_close_history(day1, "2026-09-16")
        update_close_history(day1, "2026-09-16")  # idempotent
        update_close_history({"A": {"changePercent": -0.01, "price": 104.0,
                                    "high": 105.0, "low": 102.0, "volume": 800}},
                             "2026-09-17")
        m = session_history_map(
            run_eod.load_json(run_eod.CLOSE_HISTORY, {}), "2026-09-17"
        )
        assert m["A"][-1]["chg"] == 5.0          # 16th is the most recent prior
        assert m["A"][-1]["c"] == 105.0          # full record, not bare change


# ------------- the DEAD-STOCK GATE (v2.1.0) -------------------------------
def test_dead_tape_flat_final_hour_is_refused():
    """The Sep-16 GLAXO/FABL pattern: fine daily picture, dead final hour.
    Under the v2.1.0 gate this candidate is NEVER picked."""
    glaxo = _row(symbol="GLAXO", late_momentum_pct=-0.03, change_pct=2.7)
    assert pick_top([glaxo]) == []


def test_unverifiable_late_momentum_is_refused():
    """No reference -> late momentum is None -> the gate cannot verify
    liveness, and refuses rather than guessing."""
    assert pick_top([_row(symbol="X", late_momentum_pct=None)]) == []


def test_weak_but_positive_late_momentum_still_refused():
    """+0.05% final hour is positive but below the +0.1% liveness bar."""
    row = _row(symbol="X", late_momentum_pct=MIN_LATE_MOMENTUM_PCT - 0.05)
    assert pick_top([row]) == []


def test_alive_tape_passes_the_gate():
    row = _row(symbol="X", late_momentum_pct=MIN_LATE_MOMENTUM_PCT + 0.05)
    picks = pick_top([row])
    assert len(picks) == 1 and picks[0]["symbol"] == "X"


def test_low_coverage_candidate_refused():
    """Without high/low the close-position weight (30%) is unverifiable;
    below the 70% coverage floor the score is guesswork -> refused."""
    row = _row(symbol="X")
    del row["high"]
    del row["low"]
    # sanity: coverage genuinely below the floor without close_position
    from eod_bot import weight_coverage_of
    assert weight_coverage_of(row) < MIN_WEIGHT_COVERAGE
    assert pick_top([row]) == []


def test_full_coverage_candidate_kept():
    row = _row(symbol="X", sector_flow_score=0.5,
               session_history=_hist(1, 2, 1, 2, 2))
    from eod_bot import weight_coverage_of
    assert weight_coverage_of(row) == pytest.approx(1.0)
    assert len(pick_top([row])) == 1


# ------------- STREAK RISK-ADJUSTMENT (v2.1.2, the FPJM trap) -------------
# Owner's clarified design: data-weighted ranking, NOT bans. A streaking
# name stays pickable; exhaustion risk discounts its rank and flags the
# signal. Only a lock TODAY is unbuyable (no sellers - physics).

def test_streak_discount_zero_below_free_run():
    """A fresh surge (<= +10% cumulative 4-session run) costs nothing -
    that is exactly the move this strategy hunts."""
    d, reason = streak_discount(2.0, [2.0, 2.0, 2.0])
    assert d == 0.0 and reason == ""


def test_streak_discount_grows_with_cumulative_run():
    """Each +1% beyond the free run costs 1.5% of score: a +16% run
    discounts ~9%, a +25% runner ~22.5% (capped at 60%)."""
    d16, _ = streak_discount(2.0, [4.0, 5.0, 5.0])   # run 16 -> 6 over
    d25, _ = streak_discount(4.0, [7.0, 7.0, 7.0])   # run 25 -> 15 over
    assert 0.08 < d16 < 0.10
    assert 0.20 < d25 <= 0.225


def test_streak_discount_caps_and_flags_lock_history():
    """The FPJM case: +9.9 lock inside history. Heavy discount, flagged,
    but NEVER refused - if it is still the best name, it is the pick."""
    d, reason = streak_discount(2.0, [9.9, 1.0, 1.0])
    assert d > 0.0
    assert "near-lock" in reason and "discounted" in reason
    # even a huge run cannot discount below 40% of the raw score
    dmax, _ = streak_discount(10.0, [9.9, 9.0, 9.0])
    assert dmax <= 0.60


def test_streak_missing_history_never_penalizes():
    assert streak_discount(2.0, None) == (0.0, "")
    assert streak_discount(2.0, []) == (0.0, "")


def test_pick_top_keeps_streaker_but_flags_it():
    """End to end: a strong late-surge candidate with a lock in history
    is PICKED (not banned), carrying raw_score + streak_flag. If the
    streaker beats a clean candidate by enough, it still wins the rank."""
    fpjm = _row(symbol="FPJM", late_momentum_pct=2.5, change_pct=8.0,
                high=110.0, low=99.0, price=108.5)
    picks = pick_top([fpjm], close_history={"FPJM": _hist(9.9, 1.0, 1.0)})
    assert len(picks) == 1 and picks[0]["symbol"] == "FPJM"  # NOT banned
    assert picks[0]["streak_flag"] and "streak" in picks[0]["streak_flag"]
    assert picks[0]["raw_score"] > picks[0]["score"]     # discounted


def test_pick_top_clean_candidate_outranks_heavy_streaker():
    """The law working as designed: between a clean surge and an exhausted
    +30% runner with similar tape quality, the CLEAN name wins the rank."""
    clean = _row(symbol="CLEAN", late_momentum_pct=2.0, change_pct=4.0,
                 high=105.0, low=100.0, price=104.5)
    runner = _row(symbol="RUNNER", late_momentum_pct=2.5, change_pct=10.0,
                  high=115.0, low=103.0, price=114.0)
    picks = pick_top(
        [runner, clean],
        close_history={"RUNNER": [9.9, 9.5, 9.5]},
    )
    assert picks[0]["symbol"] == "CLEAN"


def test_close_history_idempotent_and_maps_prior():
    """update_close_history twice on one day stores once; the prior map
    excludes today and orders newest-last."""
    from run_eod import update_close_history, session_history_map
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        import run_eod
        run_eod.CLOSE_HISTORY = Path(td) / "h.json"
        day1 = {"A": {"changePercent": 0.05, "price": 105.0,
                      "high": 106.0, "low": 103.0, "volume": 900}}
        day2 = {"A": {"changePercent": -0.01, "price": 104.0,
                      "high": 105.0, "low": 102.0, "volume": 800}}
        update_close_history(day1, "2026-09-16")
        update_close_history(day1, "2026-09-16")  # rescue run: no dup
        update_close_history(day2, "2026-09-17")
        m = session_history_map(
            run_eod.load_json(run_eod.CLOSE_HISTORY, {}), "2026-09-17"
        )
        assert m["A"][-1]["chg"] == 5.0  # today (17th) excluded, 16th newest


# ----------------------------- tracing -----------------------------------
def _pick(entry=100.0):
    return {
        "symbol": "TEST",
        "pick_date": "2026-09-17",
        "entry_price": entry,
        "score": 0.7,
    }


def test_trace_win_at_target():
    snap = {"quotes": {"TEST": {"price": 100.0 * (1 + TARGET_PCT / 100)}}}
    out = trace_pick(_pick(), snap, ts(5, 0))
    assert out is not None and out["outcome"] == "WIN"


# -- v2.2.6: touch exits (the poll price is 15-minute-blind) ----------------

def test_trace_touch_target_fills_while_poll_price_faded():
    """The poll says 100.8 (inside the band) but the session's day-high
    touched the 102.0 target between polls - a resting limit order
    filled on that touch. The ledger must claim it AT the target."""
    snap = {"quotes": {"TEST": {"price": 100.8, "high": 102.05, "low": 99.9}}}
    out = trace_pick(_pick(), snap, ts(5, 0))
    assert out is not None and out["outcome"] == "WIN"
    assert out["exit_price"] == 100.0 * (1 + TARGET_PCT / 100)
    assert out["via_touch"] is True


def test_trace_touch_stop_when_both_extremes_touched():
    """Both extremes touched and the poll price sits mid-band: print
    order is unknowable at poll granularity, so the adverse-selection
    rule (stop outranks) holds - we never claim a win we can't prove."""
    snap = {"quotes": {"TEST": {"price": 100.0, "high": 102.3, "low": 98.8}}}
    out = trace_pick(_pick(), snap, ts(5, 0))
    assert out is not None and out["outcome"] == "STOP"
    assert out["exit_price"] == 99.0  # the stop fill, not the poll price


def test_trace_stop_at_loss():
    snap = {"quotes": {"TEST": {"price": 98.0}}}
    out = trace_pick(_pick(), snap, ts(5, 0))
    assert out is not None and out["outcome"] == "STOP"


def test_trace_band_stays_open():
    snap = {"quotes": {"TEST": {"price": 100.8}}}
    assert trace_pick(_pick(), snap, ts(5, 0)) is None


def test_trace_force_close_after_deadline():
    snap = {"quotes": {"TEST": {"price": 100.4}}}
    out = trace_pick(_pick(), snap, ts(FORCE_CLOSE_MIN_UTC // 60 + 1, 0))
    assert out is not None and out["outcome"] == "FORCE"


def test_trace_ignores_price_moves_below_entry():
    """Price 0.9% BELOW entry is not a win - the band is two-sided.
    (Under the owner's 2026-09-18 mandate the stop is -1.0%, so a
    0.9% dip stays open; anything past -1.0% is a STOP.)"""
    snap = {"quotes": {"TEST": {"price": 99.1}}}
    assert trace_pick(_pick(), snap, ts(5, 0)) is None


def test_trace_missing_symbol_stays_open():
    assert trace_pick(_pick(), {"quotes": {}}, ts(5, 0)) is None


def test_all_live_card_renders_when_no_candidate():
    """The v2.1.2 contract: a refused night is a DELIVERED signal -
    'NO LIVE CANDIDATE' renders instead of silence."""
    from run_eod import render_evening_md
    md = render_evening_md([], "2026-09-19")
    assert "NO LIVE CANDIDATE" in md
    assert "This card IS today's signal" in md


def test_all_live_card_names_the_next_market_day():
    """The owner's orders (2026-09-19): a quiet night's card says the
    trade day is the NEXT MARKET DAY - never a concrete weekday (the
    bot cannot know PSX public holidays) and never 'tomorrow' (a
    Friday's tomorrow is a closed Saturday). Weekend-safe by
    construction: no wall-clock input exists to get it wrong."""
    from run_eod import render_evening_md
    md = render_evening_md([], "2026-09-18")  # a Friday pick date
    assert "NO BUYING FOR THE NEXT MARKET DAY" in md
    assert "MONDAY" not in md and "SUNDAY" not in md
    assert "tomorrow" not in md.lower()


def test_pick_window_matches_owner_spec():
    """The owner's v2.2.1 spec: analysis 15:00-15:23, signal by 15:25,
    the owner ORDERS at 15:29 - so the decision window closes at :28.
    Friday is the same shifted +1h. Nothing may decide after :28: a
    pick the owner cannot act on is noise, not a signal."""
    from run_eod import pick_window_minutes
    assert pick_window_minutes(4) == (16 * 60, 16 * 60 + 28)   # Friday
    assert pick_window_minutes(0) == (15 * 60, 15 * 60 + 28)   # Monday
    # every scheduled trigger lands INSIDE its window
    fri_s, fri_e = pick_window_minutes(4)
    assert fri_s <= 16 * 60 + 21 <= fri_e      # primary :21
    assert fri_s <= 16 * 60 + 24 <= fri_e      # backup :24
    assert fri_s <= 16 * 60 + 26 <= fri_e      # watchdog #1 :26
    assert fri_s <= 16 * 60 + 28 <= fri_e      # watchdog #2 :28 (last)
    mon_s, mon_e = pick_window_minutes(2)
    assert mon_s <= 15 * 60 + 21 <= mon_e
    assert mon_s <= 15 * 60 + 26 <= mon_e
    # and :29+ is EXCLUDED - the order minute belongs to the owner
    assert not (fri_s <= 16 * 60 + 29 <= fri_e)
    assert not (mon_s <= 15 * 60 + 29 <= mon_e)
    # the old v2.1.3 window (open through :59) is gone
    assert fri_e != 17 * 60


def test_streak_flag_renders_in_signal_card():
    """A flagged pick shows the streak warning in the card."""
    from run_eod import render_evening_md
    md = render_evening_md(
        [{"symbol": "FPJM", "score": 0.6, "entry_price": 10.0,
          "close_position": 0.9, "volume_surge": 2.0, "change_pct": 8.0,
          "late_momentum_pct": 1.5, "weight_coverage": 0.9,
          "streak_flag": "⚠ streak risk: +20% cumulative 4-session run"}],
        "2026-09-19",
    )
    assert "FPJM ⚠" in md and "streak risk" in md


# ----------------------------- costs -------------------------------------
def test_net_return_standard_tier_covers_cost_stack():
    """Full stack on 100 PKR: round trip ~0.45% -> a 2% win nets +1.55%."""
    net = net_return_pct(100.0, 102.0)
    assert net == pytest.approx(1.55, abs=0.03)


def test_net_return_penny_tier_is_heavier():
    """At 6.67 PKR the flat 0.03/share fee dominates - much smaller net."""
    net = net_return_pct(6.67, 6.67 * 1.02)
    assert 0.0 < net < 1.0


def test_net_return_negative_trade_has_no_cgt():
    """Losses carry no CGT: net = gross + round-trip costs (~-2.44)."""
    net = net_return_pct(100.0, 98.0)
    assert net == pytest.approx(-2.44, abs=0.05)


# ----------------------------- ledger ------------------------------------
def test_ledger_roundtrip(tmp_path):
    path = tmp_path / "ledger.jsonl"
    append_ledger(path, [{
        "symbol": "A", "pick_date": "2026-09-17",
        "entry_price": 100.0, "exit_price": 102.0,
        "outcome": "WIN", "net_return_pct": 1.29,
    }])
    append_ledger(path, [{
        "symbol": "B", "pick_date": "2026-09-17",
        "entry_price": 100.0, "exit_price": 98.0,
        "outcome": "STOP", "net_return_pct": -2.7,
    }])
    summary = ledger_summary(path)
    assert summary["trades"] == 2
    assert summary["wins"] == 1
    assert summary["win_rate_pct"] == 50.0
    assert summary["sum_net_pct"] == pytest.approx(-1.41, abs=0.01)


# --------------------- runner: reference & baselines ----------------------
def test_stale_reference_does_not_feed_late_momentum():
    """Yesterday's reference file must never produce today's late
    momentum - the 2026-09-17 bug that hid every surge."""
    from run_eod import build_cross_section
    snap = {"_date": "2026-09-18", "quotes": {
        "TEST": {"price": 101.0, "high": 101.5, "low": 100.0,
                 "volume": 1_000, "value": 101_000.0,
                 "changePercent": 0.01}}}
    yesterday = {"_date": "2026-09-17", "TEST": 100.0}
    rows = build_cross_section(snap, yesterday, {})
    assert rows[0]["late_momentum_pct"] is None  # stale -> refused later


def test_fresh_reference_feeds_late_momentum():
    from run_eod import build_cross_section
    snap = {"_date": "2026-09-18", "quotes": {
        "TEST": {"price": 101.0, "high": 101.5, "low": 100.0,
                 "volume": 1_000, "value": 101_000.0,
                 "changePercent": 0.01}}}
    today = {"_date": "2026-09-18", "TEST": 100.0}
    rows = build_cross_section(snap, today, {})
    assert rows[0]["late_momentum_pct"] == pytest.approx(1.0)


def test_baselines_update_after_scoring_uses_old_ema():
    """update_baselines must return the NEW EMA while the scorer saw the
    OLD one: today's 3x-volume day must not inflate its own denominator."""
    from run_eod import update_baselines
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        import run_eod
        old_base = Path(td) / "b.json"
        old_base.write_text(json.dumps(
            {"TEST": {"avg_volume_20": 1_000_000.0, "sessions": 30}}))
        run_eod.BASELINES = old_base
        new = update_baselines({"TEST": {"volume": 3_000_000}})
        # EMA alpha=1/20: 1.0M + (1/20)(3.0M - 1.0M) = 1.1M
        assert new["TEST"]["avg_volume_20"] == pytest.approx(1_100_000.0)


def test_compute_sector_flow_rewards_hot_sectors_only():
    """Two sectors, one with 4x the traded value: only the hot one scores,
    and the cold one gets nothing (not merely a low score)."""
    from run_eod import compute_sector_flow
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        import run_eod
        data_dir = Path(td) / "data"
        data_dir.mkdir()
        (data_dir / "sector_map.json").write_text(json.dumps(
            {"symbolToSector": {"AAA": "hot", "BBB": "cold"}}))
        run_eod.REPO_ROOT = Path(td)
        snap = {"quotes": {
            "AAA": {"value": 400e6}, "BBB": {"value": 100e6}}}
        flow = compute_sector_flow(snap)
        assert flow["sectorShare"].get("hot", 0) > 0
        assert "cold" not in flow["sectorShare"]


# ------------------------- v2.2.0 self-learning -------------------------
def test_apply_weight_overrides_renormalizes_and_floors():
    """Learned weights replace matching keys, floor at 0.02, and the
    live book always re-normalizes to sum 1.0."""
    import eod_bot
    live = eod_bot.apply_weight_overrides(
        {"weights": {"late_momentum": 0.50, "book_pressure": 0.001}}
    )
    assert live is not None
    assert sum(live.values()) == pytest.approx(1.0, abs=1e-6)
    assert live["late_momentum"] > eod_bot.WEIGHTS["late_momentum"]
    assert live["book_pressure"] >= eod_bot.REFIT_WEIGHT_FLOOR
    # untouched keys survive (renormalized, present, positive)
    assert 0 < live["aggression"] < 1
    # unknown refit keys are ignored; empty/None -> base book (None)
    assert eod_bot.apply_weight_overrides({"weights": {"nope": 0.4}}) is None
    assert eod_bot.apply_weight_overrides(None) is None
    assert eod_bot.apply_weight_overrides({}) is None


def test_refit_refuses_small_ledger(tmp_path):
    """Fewer than 12 closed trades: the tape hasn't spoken -> no refit."""
    import weekly_refit
    rows = [{"outcome": "WIN", "close_position": 0.9}] * 11
    assert weekly_refit.refit(rows) is None


def test_refit_rewards_feature_that_carries_winners():
    """A feature clearly present in wins and absent in losses earns a
    bigger weight; one with the reverse pattern shrinks."""
    import weekly_refit
    rows = []
    for _ in range(6):   # winners: strong late momentum
        rows.append({"outcome": "WIN", "late_momentum_pct": 1.5})
    for _ in range(6):   # losers: flat final hour
        rows.append({"outcome": "STOP", "late_momentum_pct": 0.0})
    report = weekly_refit.refit(rows)
    assert report is not None
    assert report["weights"]["late_momentum"] > (
        weekly_refit.FEATURE_MAP["late_momentum_pct"][1]
    )
    # normalization: the whole book still sums to 1 (rounding-tolerant)
    assert sum(report["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_refit_shrinks_feature_that_marks_losers():
    """A trait that shows up in losers (and not winners) is demoted."""
    import weekly_refit
    rows = []
    for _ in range(6):
        rows.append({"outcome": "WIN", "aggression": 0.1})
    for _ in range(6):
        rows.append({"outcome": "STOP", "aggression": 0.9})
    report = weekly_refit.refit(rows)
    assert report is not None
    assert report["weights"]["aggression"] < (
        weekly_refit.FEATURE_MAP["aggression"][1]
    )


def test_set_live_weights_changes_scoring_and_reverts():
    """Installing learned weights must move the score; None reverts."""
    import eod_bot
    row = {
        "symbol": "TST", "price": 100.0, "change_pct": 3.0,
        "value": 50e6, "volume": 2e6, "avg_volume_20": 1e6,
        "high": 100.5, "low": 96.0, "late_momentum_pct": 1.2,
        "quote": {"bidVol": 50_000, "askVol": 5_000},
    }
    eod_bot.set_live_weights(None)
    base = eod_bot.score_symbol(row)
    live = eod_bot.apply_weight_overrides({"weights": {"book_pressure": 0.6}})
    eod_bot.set_live_weights(live)
    boosted = eod_bot.score_symbol(row)
    eod_bot.set_live_weights(None)  # always revert for other tests
    assert base is not None and boosted is not None
    assert boosted > base  # the bid-wall stock scores higher under it


# ------------------- v2.2.2 window persistence -------------------
def test_persistence_discounts_faded_riser_not_steady():
    """A pick that rose then FADED inside the window is demoted; one
    still rising (or flat) pays nothing. Drift always travels."""
    import eod_bot
    picks = [
        {"symbol": "FADER", "score": 0.900, "entry_price": 103.45},  # +3.45 since :00
        {"symbol": "STEADY", "score": 0.890, "entry_price": 100.10},  # +0.10
    ]
    wo = {"quotes": {"FADER": {"price": 100.0}, "STEADY": {"price": 100.0}}}
    out = eod_bot.persistence_discount(picks, wo)
    fader = next(p for p in out if p["symbol"] == "FADER")
    steady = next(p for p in out if p["symbol"] == "STEADY")
    assert fader["persistence_discount"] > 0          # demoted
    assert steady.get("persistence_discount", 0) == 0  # sub-threshold: free
    assert fader["window_drift_pct"] == 3.45           # evidence visible
    assert out[0]["symbol"] == "STEADY"                # re-ranked


def test_persistence_never_promotes_and_survives_stale():
    """Discounts only ever lower scores; a stale/missing :00 read is a
    no-op, and a pick absent from the :00 read keeps its score."""
    import eod_bot
    picks = [{"symbol": "NEW", "score": 0.9, "entry_price": 105.0}]
    assert eod_bot.persistence_discount(picks, None) == picks
    assert eod_bot.persistence_discount(
        [{"symbol": "NEW", "score": 0.9, "entry_price": 105.0}],
        {"quotes": {}},
    )[0]["score"] == 0.9


# ------------------- v2.2.3 degraded mode -------------------
def test_degraded_mode_falls_back_to_day_shape():
    """When the reference capture is lost (late is None everywhere), the
    bar applies to the DAY change instead and the pick is flagged -
    an instrument failure must never masquerade as 'no live candidate'."""
    import eod_bot
    rows = [
        _row(symbol="GOOD", late_momentum_pct=None, change_pct=2.5),
        _row(symbol="FLAT", late_momentum_pct=None, change_pct=0.05),
    ]
    out = eod_bot.pick_top(rows, allow_degraded=True)
    assert [p["symbol"] for p in out] == ["GOOD"]
    assert out[0]["degraded"] is True
    assert out[0]["late_momentum_pct"] == 2.5  # the fallback evidence


def test_degraded_mode_never_fires_when_reference_exists():
    """Normal operation is untouched: a None late with the flag off is
    still refused (the dead-stock gate's meaning is preserved)."""
    import eod_bot
    rows = [_row(symbol="GOOD", late_momentum_pct=None, change_pct=2.5)]
    assert eod_bot.pick_top(rows) == []
    assert eod_bot.pick_top(rows, allow_degraded=False) == []


def test_degraded_mode_still_respects_the_bar_and_locks():
    """The fallback is NOT a free pass: sub-bar day changes are refused,
    and an upper-locked day change is still unbuyable (score_symbol)."""
    import eod_bot
    weak = [_row(symbol="WEAK", late_momentum_pct=None, change_pct=0.05)]
    assert eod_bot.pick_top(weak, allow_degraded=True) == []
    locked = [_row(symbol="LOCKED", late_momentum_pct=None, change_pct=9.99)]
    assert eod_bot.pick_top(locked, allow_degraded=True) == []


def test_degraded_flag_absent_in_normal_picks():
    """A normal (verified-late) pick carries degraded=False, never a
    missing key - cards can rely on the flag unconditionally."""
    import eod_bot
    out = eod_bot.pick_top([_row(symbol="OK", late_momentum_pct=0.8)])
    assert out and out[0]["degraded"] is False


def test_degraded_card_is_honestly_labeled():
    """A degraded pick's cards say so - SIGNALS.md carries the banner,
    the Telegram evidence line names the substitution, and a clean pick
    renders neither."""
    from run_eod import render_evening_md
    deg_pick = {
        "symbol": "GOOD", "score": 0.8, "raw_score": 0.8,
        "entry_price": 100.0, "close_position": 0.6,
        "volume_surge": 2.0, "change_pct": 2.5,
        "late_momentum_pct": 2.5, "weight_coverage": 1.0,
        "streak_flag": None, "degraded": True,
    }
    md = render_evening_md([deg_pick], "2026-09-21")
    assert "DEGRADED MODE" in md
    clean = {**deg_pick, "degraded": False, "late_momentum_pct": 0.8}
    md2 = render_evening_md([clean], "2026-09-21")
    assert "DEGRADED" not in md2


# ------------------- v2.2.3 next-market-day wording -------------------
def _card_pick():
    return {
        "symbol": "AIRLINK", "score": 0.74, "raw_score": 0.78,
        "entry_price": 129.0, "close_position": 0.62,
        "volume_surge": 3.7, "change_pct": 4.4,
        "late_momentum_pct": 0.52, "weight_coverage": 1.0,
        "streak_flag": None, "degraded": False,
    }


def test_telegram_card_says_next_market_day_not_tomorrow():
    """The owner's orders (2026-09-19): the card says 'Next market day'
    - never 'tomorrow' (a Friday's tomorrow is a closed Saturday) and
    never a concrete day name (PSX public holidays are unknowable to
    the bot)."""
    from telegram_notify import build_pick_text
    text = build_pick_text("2026-09-18", [_card_pick()], 1.81)
    assert "Tomorrow" not in text and "tomorrow" not in text
    assert "Next market day" in text
    assert "Monday" not in text and "Tuesday" not in text


def test_telegram_card_carries_degraded_banner():
    """The Telegram card matches SIGNALS.md's honesty: a degraded pick
    is labeled on both channels."""
    from telegram_notify import build_pick_text
    deg = {**_card_pick(), "degraded": True}
    assert "DEGRADED" in build_pick_text("2026-09-18", [deg], None)
    assert "DEGRADED" not in build_pick_text("2026-09-18", [_card_pick()], None)
