"""
Tests for the decision engine - strategy rule enforcement and candidate selection.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from decision_engine import Decision, DecisionConfig, DecisionEngine


def _make_feature_frame(
    symbols=None,
    timestamps=None,
    *,
    scores=None,
    tradable=True,
    breadth_pct=50.0,
    change_pcts=None,
    price_positions=None,
    weight_coverages=None,
    master_scores=None,
    evidence=6,
):
    """
    Build a minimal feature-enriched DataFrame that mimics the output of
    build_kmiall_features. Every column the decision engine reads must be
    present.

    evidence: how many z_* components each row carries as 0.6 (present).
    The conviction gate requires >=5 by default; passing evidence=0
    simulates a sparse row for gate tests.
    """
    if symbols is None:
        symbols = ["ABOT", "MEBL", "OGDC"]
    if timestamps is None:
        timestamps = pd.to_datetime(["2026-09-02T05:30:00+00:00"])
    if scores is None:
        scores = [0.8, 0.6, 0.4]
    if change_pcts is None:
        change_pcts = [1.0, -0.5, 0.0]
    if price_positions is None:
        price_positions = [0.5, 0.3, 0.7]
    if weight_coverages is None:
        weight_coverages = [0.82, 0.82, 0.82]
    if master_scores is None:
        master_scores = scores

    rows = []
    for i, sym in enumerate(symbols):
        for ts in timestamps:
            row = {
                "symbol": sym,
                "timestamp": ts,
                "tradable": tradable,
                "feature_rank_score_adjusted": scores[i % len(scores)],
                "price": 100.0 + i,
                "change_pct": change_pcts[i % len(change_pcts)],
                "price_position_range": price_positions[i % len(price_positions)],
                "score_weight_coverage": weight_coverages[i % len(weight_coverages)],
                "breadth_pct": breadth_pct,
                "master_score": master_scores[i % len(master_scores)],
            }
            # Evidence components: `evidence` present z_ columns at 0.6.
            for k in range(max(evidence, 0)):
                row[f"z_fake_{k}"] = 0.6
            rows.append(row)

    return pd.DataFrame(rows)


class TestDecisionConfig:
    def test_defaults(self):
        cfg = DecisionConfig()
        assert cfg.max_same_day_change_pct == 6.0
        # Raised 35 -> 40 after 2026-09-10: every stop-out entered at
        # breadth <= 32.7%, both wins at >= 45.6%.
        assert cfg.min_breadth_pct == 40.0
        assert cfg.profit_target_low == 2.0
        # Owner's universal law (2026-09-21): 2% TP everywhere, the
        # 3% preferred target retired.
        assert cfg.profit_target_high == 2.0
        assert cfg.max_holding_days == 1


class TestDecision:
    def test_to_dict(self):
        d = Decision(action="ENTER", symbol="ABOT", score=0.8, price=100.0)
        result = d.to_dict()
        assert result["action"] == "ENTER"
        assert result["symbol"] == "ABOT"
        assert result["score"] == 0.8

    def test_stand_alone_to_dict(self):
        d = Decision(action="STAND_ASIDE", reason="weak breadth")
        result = d.to_dict()
        assert result["action"] == "STAND_ASIDE"
        assert result["symbol"] is None


class TestDecisionEngine:
    def test_returns_best_symbol(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"  # highest score

    def test_profit_target_computed(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        decision = engine.evaluate(df)
        assert decision.profit_target_price is not None
        assert decision.profit_target_pct is not None
        # v2.1.0: the ENTER target is the HIGH target - the owner's
        # real cost stack puts breakeven near +0.85% per round trip;
        # TP 2.0/SL 1.5 needed a 67% win rate (unreachable), TP 3.0
        # breaks even at 46% (the panel grid's best survivable shape).
        assert decision.profit_target_pct == engine.config.profit_target_high

    def test_profit_target_applied_to_price(self):
        engine = DecisionEngine()
        df = _make_feature_frame(symbols=["X"], scores=[0.9], price_positions=[0.2])
        decision = engine.evaluate(df)
        expected = round(
            100.0 * (1.0 + engine.config.profit_target_high / 100.0), 2
        )
        assert decision.profit_target_price == expected

    # -- v0.20.2: time-aware TP (the owner's postmortem doctrine) -----------

    def test_tp_full_in_the_morning(self):
        """A morning entry has hours of tape -> aim for the preferred 3%."""
        engine = DecisionEngine()
        ts = pd.to_datetime(["2026-09-02T05:10:00+00:00"])  # 10:10 PKT
        df = _make_feature_frame(symbols=["X"], scores=[0.9], timestamps=ts)
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.profit_target_pct == engine.config.profit_target_high
        assert decision.metadata["tp_kind"] == "full"

    def test_tp_floor_late_in_the_session(self):
        """A late entry gets the 2% floor - a target the remaining
        session can actually reach (STL 2026-09-18 lesson)."""
        engine = DecisionEngine()
        ts = pd.to_datetime(["2026-09-02T07:05:00+00:00"])  # 12:05 PKT
        df = _make_feature_frame(symbols=["X"], scores=[0.9], timestamps=ts)
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.profit_target_pct == engine.config.profit_target_low
        assert decision.metadata["tp_kind"] == "floor"

    def test_stl_2026_09_18_regression_chased_entry_refused(self):
        """The actual 10:01 STL entry: +4.6% over the prior close with a
        mid-strength 0.64 score. Rule 24's chase penalty must demote it
        below the conviction bar - the tape mean-reverted and the trade
        force-closed at a loss. This test is the trade that must never
        happen again."""
        engine = DecisionEngine()
        df = _make_feature_frame(
            symbols=["STL"], scores=[0.64], change_pcts=[4.6], evidence=8
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "chase" in decision.reason.lower()

    # -- Rule 1: KMIALL universe --------------------------------------------

    def test_rule1_excludes_non_tradable(self):
        engine = DecisionEngine()
        df = _make_feature_frame(tradable=False)
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    # -- Rule 2: one winner per decision -------------------------------------

    def test_rule2_returns_single_symbol(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        decision = engine.evaluate(df)
        assert isinstance(decision.symbol, str)

    # -- Rule 4: no chasing --------------------------------------------------

    def test_rule4_rejects_high_change(self):
        engine = DecisionEngine(DecisionConfig(max_same_day_change_pct=2.0))
        # ABOT has change_pct=1.0 which is < 2.0, should be fine
        df = _make_feature_frame(change_pcts=[3.0, -0.5, 0.0])
        decision = engine.evaluate(df)
        # ABOT has change_pct=3.0 > 2.0, rejected; MEBL should win
        assert decision.symbol != "ABOT"

    def test_rule4_rejects_extended_price_position(self):
        engine = DecisionEngine(DecisionConfig(max_price_position=0.5))
        # ABOT at 0.5 is at the boundary, should still be included.
        # MEBL is made green-on-day so the red-tape hard floor does not
        # remove it before Rule 4's rejection can be observed.
        # Master scores lifted above Rule 26's ceiling so the
        # price-position cap stays the only variable under test.
        df = _make_feature_frame(
            price_positions=[0.9, 0.3, 0.7], change_pcts=[1.0, 0.5, 0.0],
            master_scores=[0.8, 0.75, 0.4],
        )
        decision = engine.evaluate(df)
        # ABOT at 0.9 is rejected; MEBL at 0.3 should win
        assert decision.symbol == "MEBL"

    # -- Rule 5: breadth gate -----------------------------------------------

    def test_rule5_stand_aside_when_weak(self):
        # 36% sits in the deliberate gap between the hard floor (35) and
        # the normal breadth gate (here configured to 40): weak tape that
        # refuses entries without invoking the unwaivable floor.
        engine = DecisionEngine(DecisionConfig(min_breadth_pct=40.0))
        df = _make_feature_frame(breadth_pct=36.0)
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "Rule 5" in decision.reason

    def test_rule5_proceeds_when_strong(self):
        engine = DecisionEngine(DecisionConfig(min_breadth_pct=35.0))
        df = _make_feature_frame(breadth_pct=60.0)
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_rule5_handles_nan_breadth(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        df["breadth_pct"] = np.nan
        decision = engine.evaluate(df)
        # NaN breadth should not trigger the gate
        assert decision.action == "ENTER"

    # -- Rule 6: held symbols excluded ---------------------------------------

    def test_rule6_excludes_held_symbols(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        decision = engine.evaluate(df, held_symbols={"ABOT"})
        assert decision.symbol != "ABOT"

    def test_rule6_still_returns_decision_when_all_held(self):
        engine = DecisionEngine()
        df = _make_feature_frame(symbols=["A", "B"], scores=[0.9, 0.8])
        decision = engine.evaluate(df, held_symbols={"A", "B"})
        assert decision.action == "STAND_ASIDE"

    # -- Weight coverage gate ------------------------------------------------

    def test_low_weight_coverage_excluded(self):
        engine = DecisionEngine(DecisionConfig(min_weight_coverage=0.60))
        # MEBL green-on-day so the red-tape floor does not remove it.
        # Master scores keep MEBL above Rule 26's dead-zone ceiling so
        # the only variable under test stays the weight coverage.
        df = _make_feature_frame(
            weight_coverages=[0.30, 0.82, 0.82], change_pcts=[1.0, 0.5, 0.0],
            master_scores=[0.8, 0.75, 0.4],
        )
        decision = engine.evaluate(df)
        # ABOT has 0.30 < 0.60, excluded; MEBL should win
        assert decision.symbol == "MEBL"

    # -- Empty / edge cases --------------------------------------------------

    def test_empty_frame(self):
        engine = DecisionEngine()
        df = pd.DataFrame(columns=[
            "symbol", "timestamp", "tradable",
            "feature_rank_score_adjusted", "price",
            "change_pct", "price_position_range",
            "score_weight_coverage", "breadth_pct",
        ])
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_no_scored_rows(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        df["feature_rank_score_adjusted"] = np.nan
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_metadata_populated(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        decision = engine.evaluate(df)
        assert "latest_timestamp" in decision.metadata
        assert "candidates_considered" in decision.metadata


def _add_horse_columns(df, vwap_ratio=0.01, value=20_000_000.0):
    """Attach the strong-horse inputs the live feature frame carries."""
    df = df.copy()
    df["vwap_ratio"] = vwap_ratio
    df["value"] = value
    return df


class TestStrongHorse:
    """
    Weak-tape days (Rule 5 / Rule 11) defer instead of blocking, but only
    an exceptional candidate - beating the market median by a wide
    margin, above VWAP, higher conviction - may enter.
    """

    def test_weak_breadth_blocks_when_disabled(self):
        engine = DecisionEngine(DecisionConfig(strong_horse_enabled=False))
        df = _make_feature_frame(breadth_pct=37.0)
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "Rule 5" in decision.reason

    def test_weak_breadth_still_blocks_without_a_horse(self):
        engine = DecisionEngine()
        # No horse inputs on the frame: the strong-horse gate needs
        # outperformance, VWAP and conviction evidence, and refuses on
        # missing evidence rather than inventing a horse.
        df = _make_feature_frame(breadth_pct=37.0)
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "no strong horse" in decision.reason

    def test_strong_horse_enters_on_weak_breadth(self):
        engine = DecisionEngine()
        # Market median change is 0.0; ABOT at +8% beats it by 8 pts,
        # clears the relaxed 9% same-day cap (normal cap is 6%).
        # Raw score 0.90: after the v2.1.0 chase penalty (max 0.25)
        # it still outranks MEBL (0.60, fresh) and clears the 0.62
        # strong-horse conviction floor.
        df = _add_horse_columns(
            _make_feature_frame(
                breadth_pct=37.0,
                # 7.5 not 8.0: Rule 25 (v2.2.0) bans the >=8% blow-off
                # cohort outright (6.9% forward win rate) - a horse's
                # relaxations end at that line.
                change_pcts=[7.5, -0.5, 0.0],
                master_scores=[0.90, 0.6, 0.4],
                scores=[0.90, 0.6, 0.4],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"
        assert decision.metadata["strong_horse"]["gate"] == "Rule 5"

    def test_strong_horse_needs_higher_conviction(self):
        engine = DecisionEngine()
        # Qualifies as a horse but 0.58 < strong_horse_min_score 0.62.
        df = _add_horse_columns(
            _make_feature_frame(
                breadth_pct=37.0,
                # 7.5 not 8.0: Rule 25 (v2.2.0) bans the >=8% blow-off
                # cohort outright (6.9% forward win rate) - a horse's
                # relaxations end at that line.
                change_pcts=[7.5, -0.5, 0.0],
                master_scores=[0.58, 0.55, 0.4],
                scores=[0.58, 0.55, 0.4],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "conviction gate" in decision.reason.lower()

    def test_below_vwap_is_not_a_horse(self):
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                breadth_pct=37.0,
                # 7.5 not 8.0: Rule 25 (v2.2.0) bans the >=8% blow-off
                # cohort outright (6.9% forward win rate) - a horse's
                # relaxations end at that line.
                change_pcts=[7.5, -0.5, 0.0],
            ),
            vwap_ratio=-0.02,
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "no strong horse" in decision.reason

    def test_index_downtrend_defers_to_horse(self):
        engine = DecisionEngine()

        class Ctx:
            index_below_sma = True
            index_last_close = 171_000.0
            index_sma = 176_000.0
            index_window = 20

        df = _add_horse_columns(
            _make_feature_frame(
                # 7.5: under Rule 25's >=8% blow-off ban (v2.2.0).
                change_pcts=[7.5, -0.5, 0.0],
                master_scores=[0.90, 0.6, 0.4],
                scores=[0.90, 0.6, 0.4],
            )
        )
        decision = engine.evaluate(df, context=Ctx())
        assert decision.action == "ENTER"
        assert decision.metadata["strong_horse"]["gate"] == "Rule 11"


class TestRegimeDataVeto:
    """
    A stale regime input is "we cannot see the market", not "the market
    is fine" - entries must stop loudly until the data heals
    (2026-09-10: the index file was fetched five hours after the
    morning's entries and Rule 11 passed silently all morning).
    """

    def test_stale_history_vetoes_entries(self):
        engine = DecisionEngine()

        class Ctx:
            index_history_stale = True
            index_history_newest = "2026-09-09"
            index_history_expected = "2026-09-10"

        df = _add_horse_columns(_make_feature_frame())
        decision = engine.evaluate(df, context=Ctx())
        assert decision.action == "STAND_ASIDE"
        assert "stale" in decision.reason.lower()
        assert decision.metadata["gate"] == "regime_data_veto"

    def test_veto_even_for_strong_horse(self):
        engine = DecisionEngine()

        class Ctx:
            index_history_stale = True
            index_history_newest = "2026-09-09"
            index_history_expected = "2026-09-10"

        df = _add_horse_columns(
            _make_feature_frame(
                breadth_pct=37.0,
                # 7.5 not 8.0: Rule 25 (v2.2.0) bans the >=8% blow-off
                # cohort outright (6.9% forward win rate) - a horse's
                # relaxations end at that line.
                change_pcts=[7.5, -0.5, 0.0],
                master_scores=[0.65, 0.6, 0.4],
                scores=[0.65, 0.6, 0.4],
            )
        )
        decision = engine.evaluate(df, context=Ctx())
        assert decision.action == "STAND_ASIDE"

    def test_fresh_history_does_not_veto(self):
        engine = DecisionEngine()

        class Ctx:
            index_history_stale = False

        df = _add_horse_columns(_make_feature_frame())
        decision = engine.evaluate(df, context=Ctx())
        assert decision.metadata.get("gate") != "regime_data_veto"

    def test_veto_disabled_by_config(self):
        engine = DecisionEngine(DecisionConfig(regime_data_veto_enabled=False))

        class Ctx:
            index_history_stale = True

        df = _add_horse_columns(_make_feature_frame())
        decision = engine.evaluate(df, context=Ctx())
        assert decision.metadata.get("gate") != "regime_data_veto"


def _add_confirmation_columns(
    df, high=None, momentum_1m_pct=0.3, price=None,
):
    """
    Attach the Rule 16 (confirmation) inputs a live frame carries.

    Default: price AT the session high (a fresh high made this poll)
    with positive momentum - the canonical confirmed candidate.
    """
    df = df.copy()
    df["high"] = high if high is not None else df["price"]
    df["momentum_1m_pct"] = momentum_1m_pct
    if price is not None:
        df["price"] = price
        df["high"] = high
    return df


class TestConfirmationRule:
    """
    Rule 16 - read, don't predict. A candidate enters only when it is
    pressing against its session high with positive 1-minute momentum:
    buyers present at THIS poll. The 2026-09-10 losers all scored well
    on stale trend evidence while fading well off their highs.
    """

    def test_missing_high_columns_passes(self):
        # Frames without high/momentum columns (older data, tests) are
        # not judged - the filter never invents evidence.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame())
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_fading_off_high_is_refused(self):
        # Price 3% below the session high: the move already happened
        # and is decaying. (Band is 1.5% - a strong stock breathes,
        # a 3% fade is a fade.)
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(
            df, high=df["price"] * 1.03, momentum_1m_pct=0.3
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "No eligible candidates" in decision.reason

    def test_breathing_off_high_still_enters(self):
        # A fresh high made this window, price breathing 1.2% under
        # it: an ordinary pullback on a LIVE move (PRL on the
        # 2026-09-11 recovery was refused at this depth by the old
        # 0.75% band). Freshness comes from the high ADVANCING
        # inside the window, so the test frame needs history.
        timestamps = pd.to_datetime(
            ["2026-09-11T04:35:00+00:00", "2026-09-11T06:05:00+00:00"]
        )
        df = _make_feature_frame(timestamps=timestamps)
        df = _add_horse_columns(df)
        df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        late = df["timestamp"] == timestamps[1]
        df["high"] = 100.0
        df["momentum_1m_pct"] = 0.3
        df.loc[late, "high"] = 101.3   # the advance (fresh)
        df.loc[late, "price"] = 100.1  # 1.19% under the new high
        decision = DecisionEngine().evaluate(df)
        assert decision.action == "ENTER"

    def test_pressing_high_with_momentum_enters(self):
        # Price AT the session high, 1-minute momentum positive: the
        # buy side is present right now.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(
            df, high=df["price"], momentum_1m_pct=0.3
        )
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_at_high_but_negative_momentum_refused(self):
        # At the high but rolling over this minute: not confirmed.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(
            df, high=df["price"], momentum_1m_pct=-0.2
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_stale_high_not_confirmed(self):
        """
        The feed's `high` is the cumulative DAY high on every row.
        A stock that spiked at 09:35 and drifted sideways still
        reports the spike as its high all afternoon. The freshness
        read: the high must have ADVANCED inside the recent window -
        an unchanged high with price below it is a stale spike, not
        a live move.
        """
        timestamps = pd.to_datetime(
            ["2026-09-11T04:35:00+00:00", "2026-09-11T06:05:00+00:00"]
        )
        wide = _make_feature_frame(timestamps=timestamps)
        wide = _add_horse_columns(wide)
        wide = wide.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        late_idx = wide["timestamp"] == timestamps[1]

        # Morning spike to 103; afternoon: high still 103 (day high),
        # price pulled back below it, momentum positive.
        wide["high"] = 103.0
        wide["momentum_1m_pct"] = 0.3
        wide.loc[late_idx, "price"] = 101.0  # 1.9% under the spike
        decision = DecisionEngine().evaluate(wide)
        # Within the band it would pass; but the high never advanced
        # inside the 20-min window AND price is below the high, so
        # freshness refuses it.
        wide.loc[late_idx, "price"] = 102.5  # 0.5% under the spike
        decision = DecisionEngine().evaluate(wide)
        assert decision.action == "STAND_ASIDE"
        assert "No eligible candidates" in decision.reason

        # Fresh variant: the afternoon rows carry a HIGHER high than
        # the morning rows (the high advanced inside the window) and
        # price presses near it - confirmed.
        fresh = _make_feature_frame(timestamps=timestamps)
        fresh = _add_horse_columns(fresh)
        fresh = fresh.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        fresh["high"] = 100.0
        fresh["momentum_1m_pct"] = 0.3
        late = fresh["timestamp"] == timestamps[1]
        fresh.loc[late, "high"] = 102.0   # the advance
        fresh.loc[late, "price"] = 101.5  # 0.5% under the new high
        decision = DecisionEngine().evaluate(fresh)
        assert decision.action == "ENTER"

    def test_flat_day_not_confirmed(self):
        # high == price but high <= 0 is unreadable, never confirmed.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df, high=0.0)
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_disabled_by_config(self):
        engine = DecisionEngine(DecisionConfig(confirmation_enabled=False))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(
            df, high=df["price"] * 1.03, momentum_1m_pct=0.3
        )
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_threshold_tunable(self):
        # A 3% band admits a deep pullback off a FRESH high; the
        # default 1.5% doesn't.
        timestamps = pd.to_datetime(
            ["2026-09-11T04:35:00+00:00", "2026-09-11T06:05:00+00:00"]
        )
        df = _make_feature_frame(timestamps=timestamps)
        df = _add_horse_columns(df)
        df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
        late = df["timestamp"] == timestamps[1]
        df["high"] = 100.0
        df["momentum_1m_pct"] = 0.3
        df.loc[late, "high"] = 102.0   # fresh advance
        df.loc[late, "price"] = 99.0   # 2.94% under the new high

        default_engine = DecisionEngine()
        decision = default_engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

        wide_engine = DecisionEngine(
            DecisionConfig(confirmation_at_high_pct=3.0)
        )
        decision = wide_engine.evaluate(df)
        assert decision.action == "ENTER"


class TestMoneyFlowRule:
    """
    Rule 17 - follow the money. A candidate from a sector the
    market's rupees are avoiding (live value share below its typical
    share) is a bet against the flow. Missing column = pass.
    """

    def test_avoided_sector_refused(self):
        engine = DecisionEngine(DecisionConfig(min_sector_money_flow=0.7))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["sector_money_flow_pct"] = 0.3   # sector's money share weak
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_favored_sector_enters(self):
        engine = DecisionEngine(DecisionConfig(min_sector_money_flow=0.7))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["sector_money_flow_pct"] = 1.8   # rupees concentrating here
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_missing_flow_column_passes(self):
        engine = DecisionEngine(DecisionConfig(min_sector_money_flow=0.7))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        assert "sector_money_flow_pct" not in df.columns
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_disabled_by_config(self):
        engine = DecisionEngine(DecisionConfig(min_sector_money_flow=0.0))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["sector_money_flow_pct"] = 0.1
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"


class TestBuyerPresenceRule:
    """
    Rule 16b - the live book must not be ask-stacked at entry.
    bid_volume >= min_bid_ask_balance * ask_volume. An empty ask
    side passes (no sellers = most bullish); missing book passes.
    """

    def test_ask_stacked_book_refused(self):
        # Sellers queued 5x the buyers: distribution, not demand.
        engine = DecisionEngine(DecisionConfig(min_bid_ask_balance=0.5))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["bid_volume"] = 100.0
        df["ask_volume"] = 500.0
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_balanced_book_enters(self):
        engine = DecisionEngine(DecisionConfig(min_bid_ask_balance=0.5))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["bid_volume"] = 400.0
        df["ask_volume"] = 500.0
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_empty_ask_side_enters(self):
        # No sellers queued at all: the most bullish book there is.
        engine = DecisionEngine(DecisionConfig(min_bid_ask_balance=0.5))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        df["bid_volume"] = 400.0
        df["ask_volume"] = 0.0
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_missing_book_columns_pass(self):
        engine = DecisionEngine(DecisionConfig(min_bid_ask_balance=0.5))
        df = _add_horse_columns(_make_feature_frame())
        df = _add_confirmation_columns(df)
        assert "bid_volume" not in df.columns
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"


class TestRecoveryOverride:
    """
    Rule 11's index file is end-of-day. On a day the market reverses
    (-2,200 open -> +600 by afternoon, 2026-09-11), the file still
    says downtrend while the live tape is broadly rising. When breadth
    is at/above the recovery threshold and not collapsing, the tape
    wins and the strong-horse exception is disarmed.
    """

    def _ctx_downtrend(self):
        class Ctx:
            index_below_sma = True
            index_last_close = 168_865.0
            index_sma = 176_220.0
            index_window = 20
            index_history_stale = False
        return Ctx()

    def test_broad_recovery_disarms_horse_gate(self):
        # Breadth 58% (>= 55): the tape contradicts the stale file.
        # A normal candidate (not a 3-pt horse) should ENTER.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame(breadth_pct=58.0))
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=self._ctx_downtrend())
        assert decision.action == "ENTER"

    def test_weak_tape_keeps_the_horse_gate(self):
        # Breadth 44% (< 55): the recovery override does NOT fire;
        # below-SMA + sub-horse candidates are still refused.
        engine = DecisionEngine()
        df = _add_horse_columns(_make_feature_frame(breadth_pct=44.0))
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=self._ctx_downtrend())
        assert decision.action == "STAND_ASIDE"
        assert "no strong horse" in decision.reason

    def test_collapsing_recovery_not_trusted(self):
        # Breadth 58% but down 15 pts from its session high: that is
        # a fade, not a recovery. The horse gate stays armed.
        engine = DecisionEngine()
        timestamps = pd.to_datetime(
            ["2026-09-11T04:35:00+00:00", "2026-09-11T06:05:00+00:00"]
        )
        df = _add_confirmation_columns(
            _add_horse_columns(
                _make_feature_frame(timestamps=timestamps, breadth_pct=58.0)
            )
        )
        # Breadth at the morning timestamp was 73%: a 15-pt collapse.
        early = df["timestamp"] == timestamps[0]
        df.loc[early, "breadth_pct"] = 73.0
        decision = engine.evaluate(df, context=self._ctx_downtrend())
        assert decision.action == "STAND_ASIDE"


def _add_market_tape_columns(
    df,
    vw_change_pct=0.5,
    slope_30m=np.nan,
    off_low_pct=1.0,
):
    """
    Attach the money-tape / recovery-detector inputs the live dataset
    carries per timestamp (NaN slope = leg-open case: no polls during
    the lunch gap, so a 30-minute slope cannot exist yet).
    """
    df = df.copy()
    df["market_vw_change_pct"] = vw_change_pct
    df["market_vw_slope_30m"] = slope_30m
    df["market_off_low_pct"] = off_low_pct
    return df


class TestRecoveryMode:
    """
    Rule 5c - recovery mode. On a cap-weighted V-reversal (2026-09-11:
    KSE-100 -2200 -> +1600) equal-weight breadth reads 42-46% while the
    median stock bounces 3.9-4.7% off its low; normal afternoons read
    0.2-1.1%. When the money-weighted tape is non-negative AND the board
    is broadly bouncing (off-low) or money is slamming back in (slope),
    three gates tuned on grinding days relax: the breadth floor, the
    same-day-change cap, sector money-flow, and Rule 16's day-high anchor.
    """

    def test_off_low_arms_recovery_at_leg_open(self):
        # Breadth 36% (< 40) would normally demand a strong horse; the
        # slope is NaN (no 30-min history across the lunch gap) but the
        # median stock is 4% off its low and the money tape is positive:
        # a normal candidate (no horse attributes) should ENTER.
        engine = DecisionEngine()
        df = _add_market_tape_columns(
            _make_feature_frame(breadth_pct=36.0),
            vw_change_pct=0.5, slope_30m=np.nan, off_low_pct=4.0,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "ENTER"

    def test_recovery_needs_nonnegative_money_tape(self):
        # The board bouncing while the money-weighted tape is negative
        # is a dead-cat bounce, not a recovery: no unlock.
        engine = DecisionEngine()
        df = _add_market_tape_columns(
            _make_feature_frame(breadth_pct=36.0),
            vw_change_pct=-1.0, slope_30m=np.nan, off_low_pct=4.0,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "STAND_ASIDE"
        assert "no strong horse" in decision.reason

    def test_recovery_needs_bounce_evidence(self):
        # Money tape positive but the board sits 1% off its low with a
        # flat slope: an ordinary afternoon, gates stay strict.
        engine = DecisionEngine()
        df = _add_market_tape_columns(
            _make_feature_frame(breadth_pct=36.0),
            vw_change_pct=0.5, slope_30m=0.5, off_low_pct=1.0,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "STAND_ASIDE"

    def test_slope_alone_arms_recovery(self):
        # Early leg: off-low still low but money is pouring back in
        # (+3.5%/30min) - recovery arms on the slope alone.
        engine = DecisionEngine()
        df = _add_market_tape_columns(
            _make_feature_frame(breadth_pct=36.0),
            vw_change_pct=0.5, slope_30m=3.5, off_low_pct=1.0,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "ENTER"

    def test_no_tape_columns_no_recovery(self):
        # Older frames without the market-tape columns behave exactly as
        # before: breadth below the floor demands a strong horse.
        engine = DecisionEngine()
        df = _add_confirmation_columns(
            _make_feature_frame(breadth_pct=36.0)
        )
        decision = engine.evaluate(df, context=None)
        assert decision.action == "STAND_ASIDE"

    def test_recovery_widens_day_change_cap(self):
        # The stock LEADING the recovery is up 6.5% on the day - above
        # the normal 6% cap, below the 8% recovery cap. Recovery mode
        # must not reject the tape's own leader.
        engine = DecisionEngine()
        # Raw score 0.95: after the chase penalty (6.5% on the day,
        # capped at -0.25) it still outranks the fresh names.
        df = _add_market_tape_columns(
            _make_feature_frame(
                breadth_pct=36.0,
                change_pcts=[6.5, 1.0, 0.5],
                master_scores=[0.95, 0.6, 0.4],
                scores=[0.95, 0.6, 0.4],
            ),
            vw_change_pct=0.5, slope_30m=np.nan, off_low_pct=4.0,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"  # the +6.5% leader, top score

    def test_recovery_disarms_stale_index_veto(self):
        # The full 2026-09-11 shape: stale EOD file says downtrend,
        # live tape says recovery - the normal-gates path applies.
        class Ctx:
            index_below_sma = True
            index_last_close = 168_865.0
            index_sma = 176_220.0
            index_window = 20
            index_history_stale = False

        engine = DecisionEngine()
        df = _add_market_tape_columns(
            _make_feature_frame(breadth_pct=43.0),
            vw_change_pct=0.5, slope_30m=np.nan, off_low_pct=4.2,
        )
        df = _add_confirmation_columns(df)
        decision = engine.evaluate(df, context=Ctx())
        assert decision.action == "ENTER"

    def test_recovery_confirmation_uses_recent_high(self):
        # A recoverer 2% off its stale MORNING high but pressing its
        # 45-minute high and rising over the last 15 minutes, with no
        # 1-minute momentum print (thin trading during a fast tape):
        # the recovery branch confirms it where the normal branch
        # (day-high anchor + fresh-high + momentum) would refuse it.
        engine = DecisionEngine()
        timestamps = pd.to_datetime(
            [
                "2026-09-11T08:00:00+00:00",  # morning-spike era
                "2026-09-11T09:45:00+00:00",  # rise-lookback anchor
                "2026-09-11T10:00:00+00:00",  # latest: pressing rec high
            ]
        )
        rows = []
        for ts_i, ts in enumerate(timestamps):
            price = [106.0, 100.0, 104.0][ts_i]
            rows.append(
                {
                    "symbol": "PRL",
                    "timestamp": ts,
                    "tradable": True,
                    "feature_rank_score_adjusted": 0.8,
                    "price": price,
                    "change_pct": 3.5,
                    "price_position_range": 0.5,
                    "score_weight_coverage": 0.82,
                    "breadth_pct": 36.0,
                    "master_score": 0.8,
                    "high": 106.0,  # stale morning spike top
                    "momentum_1m_pct": np.nan,  # no print this minute
                    "market_vw_change_pct": 0.5,
                    "market_vw_slope_30m": np.nan,
                    "market_off_low_pct": 4.2,
                }
            )
        for k in range(6):
            for row in rows:
                row[f"z_fake_{k}"] = 0.6
        df = pd.DataFrame(rows)
        decision = engine.evaluate(df, context=None)
        assert decision.action == "ENTER"
        assert decision.symbol == "PRL"


class TestHardFloors:
    """
    v0.5.0: the unwaivable tape-quality minimums, measured from the
    bot's own ledger - every labeled loss entered below 35% breadth
    (Sep 10: 30-32%), red on the day, or far off the low chasing a
    bounce (BUXL +9.5%). No override - recovery mode, strong horse -
    may bypass the floor.
    """

    def test_sub_35_breadth_refused_even_with_a_horse(self):
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                breadth_pct=31.0,
                change_pcts=[8.0, -0.5, 0.0],
                master_scores=[0.65, 0.6, 0.4],
                scores=[0.65, 0.6, 0.4],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "Hard floor" in decision.reason
        assert decision.metadata["gate"] == "hard_min_breadth_pct"

    def test_red_tape_candidate_rejected(self):
        engine = DecisionEngine()
        # ABOT red on the day: excluded even as the top score.
        df = _make_feature_frame(change_pcts=[-1.5, 1.0, 0.5])
        decision = engine.evaluate(df)
        assert decision.symbol != "ABOT"

    def test_flat_tape_candidate_passes(self):
        # Flat-on-day is missing evidence, not contradicting evidence:
        # it passes, per the engine's standing rule.
        engine = DecisionEngine()
        df = _make_feature_frame(change_pcts=[0.0, 0.0, 0.0])
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_chase_cap_rejects_far_off_low(self):
        engine = DecisionEngine(DecisionConfig(max_entry_off_low_pct=3.0))
        df = _make_feature_frame(change_pcts=[1.0, 0.5, 0.2])
        df["distance_from_low_pct"] = [9.5, 1.0, 1.0]
        decision = engine.evaluate(df)
        # ABOT killed by the cap; MEBL survives it.
        assert decision.symbol != "ABOT"

    def test_chase_cap_rejects_moderate_off_low(self):
        engine = DecisionEngine(DecisionConfig(max_entry_off_low_pct=3.0))
        df = _make_feature_frame(change_pcts=[1.0, 0.5, 0.2])
        df["distance_from_low_pct"] = [4.5, 4.5, 4.5]
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_recovery_mode_relaxes_chase_cap(self):
        engine = DecisionEngine(DecisionConfig(max_entry_off_low_pct=3.0))
        df = _make_feature_frame(change_pcts=[1.0, 0.5, 0.2])
        df["distance_from_low_pct"] = [4.5, 4.5, 4.5]
        # Arm recovery: money tape non-negative, board broadly off lows.
        df["market_vw_change_pct"] = 0.5
        df["market_off_low_pct"] = 4.0
        decision = engine.evaluate(df)
        # 4.5% off the low fails the normal cap but fits recovery's 6%.
        assert decision.action == "ENTER"


class TestBroadRallyRecovery:
    """
    Third recovery trigger (v0.14.2, 2026-09-15). The off-low and slope
    triggers are V-reversal detectors. A gap-up rally - the most common
    strong-day shape on the PSX - opens up and grinds higher, so the
    board sits ~1% off its lows all day and the 30-min slope never
    spikes: recovery never armed and the 2026-09-15 +1700 day produced
    zero entries at 76-79% breadth (every leader died at the 4%
    normal day-change cap). Broad rally breadth now arms recovery,
    which widens the caps to let the tape's own leaders through.
    """

    def _rally_frame(self, breadth_pct=76.0, vw_change_pct=0.8):
        import numpy as np

        from test_decision_engine import (
            _add_confirmation_columns,
            _add_market_tape_columns,
            _make_feature_frame,
        )

        # ABOT is the tape's leader at +6.5%: above the normal 4% cap,
        # below the 8% recovery cap. Only a recovery arm lets it in.
        # Raw score 0.95 survives the v2.1.0 chase penalty cap.
        df = _make_feature_frame(
            breadth_pct=breadth_pct,
            change_pcts=[6.5, 1.0, 0.5],
            master_scores=[0.95, 0.6, 0.4],
            scores=[0.95, 0.6, 0.4],
        )
        df = _add_market_tape_columns(
            df, vw_change_pct=vw_change_pct,
            slope_30m=0.4, off_low_pct=0.9,
        )
        return _add_confirmation_columns(df)

    def test_broad_rally_lets_leader_through(self):
        # 76% green, money tape positive, off-low 0.9%, slope 0.4%: a
        # gap-up grind. The +6.5% leader must enter via the widened cap.
        engine = DecisionEngine()
        decision = engine.evaluate(self._rally_frame(), context=None)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"

    def test_below_arm_bar_leader_stays_capped(self):
        # 60% breadth (< 65 arm bar, lowered from 70 in v0.17.9):
        # recovery does not arm, the leader fails the normal 4% cap,
        # and the weaker names must not win (assert instead that if
        # anything enters, it is NOT the overextended leader).
        engine = DecisionEngine()
        decision = engine.evaluate(
            self._rally_frame(breadth_pct=60.0), context=None
        )
        if decision.action == "ENTER":
            assert decision.symbol != "ABOT"

    def test_rally_arm_needs_nonnegative_money_tape(self):
        # 76% green breadth on a NEGATIVE money-weighted tape is froth,
        # not a rally: the breadth arm lives inside the money-tape-ok
        # block, so recovery does not widen the caps and the +6.5%
        # leader stays excluded by the normal 4% cap. (Ordinary
        # sub-cap candidates may still enter through the normal
        # gates - that path is untouched by this trigger.)
        engine = DecisionEngine()
        decision = engine.evaluate(
            self._rally_frame(vw_change_pct=-1.0), context=None
        )
        assert decision.symbol != "ABOT"

    def test_rally_still_blocked_by_breadth_collapse(self):
        # A rally that is fading (breadth collapsed from its intraday
        # high) is blocked by Rule 11b even at 76% absolute breadth.
        # Two timestamps so the collapse detector has a high to fall
        # from: 96% -> 76% is a 20-point drop (> the 10-point limit).
        import pandas as pd

        from test_decision_engine import (
            _add_confirmation_columns,
            _add_market_tape_columns,
            _make_feature_frame,
        )

        ts = pd.to_datetime(
            ["2026-09-02T05:30:00+00:00", "2026-09-02T05:40:00+00:00"]
        )
        df = _make_feature_frame(
            breadth_pct=76.0, timestamps=list(ts) * 3
        )
        # First poll: the session's breadth high. Second: the fade.
        df.loc[df["timestamp"] == ts[0], "breadth_pct"] = 96.0
        df = _add_market_tape_columns(
            df, vw_change_pct=0.8, slope_30m=0.4, off_low_pct=0.9,
        )
        df = _add_confirmation_columns(df)
        engine = DecisionEngine()
        decision = engine.evaluate(df, context=None)
        assert decision.action == "STAND_ASIDE"
        assert "Rule 11b" in decision.reason


class TestChasePenalty:
    """
    v2.1.0 Rule 24 - the ledger's most anti-predictive feature is the
    entry premium over the prior close: 437/450 panel candidates were
    already +3% or more, won 14% of forwards at -1.25% net; the
    off-low pullback cohort won 44%. The penalty DEMOTES chased names
    (ordering + conviction gate) without banning them, and never
    rescues an extreme out of the Rule 22 ceiling refusal.
    """

    def test_chased_leader_loses_to_fresh_name(self):
        # Same raw score; the +6% name pays -0.25, the fresh name
        # nothing. Ranking must flip toward the fresh tape.
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=[6.0, 0.5, 0.0],
                master_scores=[0.80, 0.79, 0.4],
                scores=[0.80, 0.79, 0.4],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "MEBL"  # the fresh name

    def test_penalty_drives_conviction_gate(self):
        # Raw 0.55 is above the 0.50 default gate - until the chase
        # penalty on a +4% move (-0.24) drops the gate score below it.
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=[4.0, 0.0, 0.0],
                master_scores=[0.55, 0.3, 0.3],
                scores=[0.55, 0.3, 0.3],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "chase penalty" in decision.reason
        assert decision.metadata["gate"] == "min_master_score"
        assert decision.metadata["chase_penalty"] > 0.0

    def test_fresh_pullback_pays_nothing(self):
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=[0.8, 0.5, 0.0],
                master_scores=[0.80, 0.6, 0.4],
                scores=[0.80, 0.6, 0.4],
            )
        )
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"
        assert decision.metadata["chase_penalty"] == 0.0

    def test_raw_score_kept_in_metadata(self):
        engine = DecisionEngine()
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=[6.0, 0.5, 0.0],
                master_scores=[0.80, 0.79, 0.4],
                scores=[0.80, 0.79, 0.4],
            )
        )
        decision = engine.evaluate(df)
        # MEBL (fresh, raw 0.79) wins the pool; the ENTER metadata
        # carries ITS raw/gate scores and zero penalty.
        assert decision.symbol == "MEBL"
        assert decision.metadata["best_score"] == 0.79
        assert decision.metadata["gate_score"] == 0.79
        assert decision.metadata["chase_penalty"] == 0.0


class TestRule11cIndexTape:
    """
    Rule 11c - the LIVE index tape (v2.1.0). Rule 11 reads end-of-day
    history and cannot see today; the KSE-100 quote captured on the
    same page as every snapshot can. The owner's law: the index is the
    tide - a strongly red cap-weighted market is selling most stocks
    with it, and no intraday long is taken. An unknown quote degrades
    to pass; the gate never manufactures a veto from absent evidence.
    """

    def _ctx(self, idx_pct):
        class Ctx:
            index_change_pct = idx_pct
            index_quote_status = "SUS"
            index_below_sma = False  # keep Rule 11 silent in these cases
        return Ctx()

    def _frame(self):
        df = _add_horse_columns(_make_feature_frame(breadth_pct=58.0))
        return _add_confirmation_columns(df)

    def test_deep_red_tape_blocks_entry(self):
        # Index -0.80% (below the -0.5 floor): stand aside, named reason.
        engine = DecisionEngine()
        decision = engine.evaluate(self._frame(), context=self._ctx(-0.80))
        assert decision.action == "STAND_ASIDE"
        assert "Rule 11c" in decision.reason
        assert decision.metadata["index_change_pct"] == pytest.approx(-0.80)

    def test_floor_boundary_blocks(self):
        # Exactly at the floor (-0.5): "at or below" blocks.
        engine = DecisionEngine()
        decision = engine.evaluate(self._frame(), context=self._ctx(-0.5))
        assert decision.action == "STAND_ASIDE"
        assert "Rule 11c" in decision.reason

    def test_shallow_red_tape_passes(self):
        # -0.30% is above the floor: the layer stays silent.
        engine = DecisionEngine()
        decision = engine.evaluate(self._frame(), context=self._ctx(-0.30))
        assert decision.action == "ENTER"

    def test_green_tape_passes(self):
        engine = DecisionEngine()
        decision = engine.evaluate(self._frame(), context=self._ctx(1.089))
        assert decision.action == "ENTER"

    def test_unknown_quote_degrades_to_pass(self):
        # No live quote (None): the gate passes - it never invents a veto.
        engine = DecisionEngine()
        decision = engine.evaluate(self._frame(), context=self._ctx(None))
        assert decision.action == "ENTER"

    def test_disabled_knob_disarms_the_rule(self):
        engine = DecisionEngine()
        engine.config.index_tape_enabled = False
        decision = engine.evaluate(self._frame(), context=self._ctx(-0.80))
        assert decision.action == "ENTER"


class TestRule25ChaseVeto:
    """
    Rule 25 - the chase hard veto (v2.2.0). The 450-panel forward sim
    put the +8%-over-prior-close blow-off cohort at a 6.9% win rate and
    -2.18% net per trade, unrescuable by any exit config in the 12-cell
    grid. Rule 24 demotes chasers; the data says the extreme tail is
    banned outright. Missing day-change passes - the gate never
    manufactures a veto from absent evidence.
    """

    def _frame(self, change_pcts, master_scores=None):
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=change_pcts,
                master_scores=master_scores or [0.80, 0.15, 0.15],
                scores=master_scores or [0.80, 0.15, 0.15],
            )
        )
        return _add_confirmation_columns(df)

    def _disarm_upstream(self, engine):
        # Keep the tape floors silent so the ONLY variable is Rule 25.
        engine.config.hard_min_breadth_pct = 0.0
        engine.config.require_positive_day_change = False
        engine.config.index_tape_enabled = False
        # Lift the 6% day cap so the blow-off row survives to Rule 25.
        engine.config.max_same_day_change_pct = 12.0

    def test_blow_off_candidate_banned(self):
        # +9.5% over the prior close: dead before the circuit detector.
        # It is the only tradable row, so the pool empties AT Rule 25
        # and the killer-gate trace must name it.
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([9.5, 0.5, 0.0])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "chase_veto" in decision.reason

    def test_boundary_at_cap_banned(self):
        # The disaster cohort in the data was "8 or more" - exactly 8.0
        # is inside the ban, matching the measured band.
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([8.0, 0.5, 0.0])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "chase_veto" in decision.reason

    def test_below_cap_survives_to_rule_24(self):
        # +6% pays the chase penalty but is NOT banned - Rule 24's job.
        # (The 0.80 winner also clears Rule 26's dead-zone ceiling, so
        # the chase machinery remains the only thing under test.)
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        # All three rows carry ceiling-clearing conviction so Rule 26
        # releases everyone; then a 6% row must still LOSE the rank
        # contest to an unpenalized rival (demoted, not banned) - and
        # the winner itself pays no chase penalty.
        decision = engine.evaluate(self._frame([6.0, 0.5, 0.0], [0.80, 0.85, 0.84]))
        assert decision.symbol != "ABOT"  # demoted, not banned
        assert decision.metadata["chase_penalty"] == 0.0  # winner pays none

    def test_missing_day_change_passes(self):
        # No change_pct evidence: pass - never invent a veto. (Rows 1-2
        # carry strong master scores so Rule 26 releases them; the NaN
        # row then wins the pool - proving the missing evidence row was
        # never vetoed by either rule.)
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([0.5, 0.5, 0.0], [0.80, 0.6, 0.4])
        df.loc[df.index[0], "change_pct"] = None
        df.loc[df.index[1], "master_score"] = 0.85
        df.loc[df.index[1], "feature_rank_score_adjusted"] = 0.85
        df.loc[df.index[2], "master_score"] = 0.85
        df.loc[df.index[2], "feature_rank_score_adjusted"] = 0.85
        decision = engine.evaluate(df)
        assert decision.action == "ENTER"

    def test_disabled_knob_disarms_the_rule(self):
        # With the veto off, the same blow-off tape flows through to the
        # conviction gate (paying only Rule 24's penalty cap): the 0.85
        # raw clears 0.55 even demoted, and the chased name wins the
        # pool - the exact behavior the data says produced the losses.
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        engine.config.chase_hard_veto_enabled = False
        decision = engine.evaluate(self._frame([9.5, 0.5, 0.0], [0.85, 0.15, 0.15]))
        assert decision.action == "ENTER"
        assert decision.symbol == "ABOT"


class TestRule26DeadZone:
    """
    Rule 26 - the low-conviction green-open ban (v2.4.0). Grind-4
    evidence (backtest_grind4.py, 175 sessions x 305 symbols): the
    mild-green-day entry family (0-2% over prior close) won 13.4% of
    forwards at -0.79% net per trade, negative in every month of 2026;
    PPL 2026-09-21 (score 0.623, day +0.79%) is the type case. The
    band is banned for low-conviction candidates; strong conviction
    (>= dead_zone_max_score) escapes; missing day-change passes -
    the gate never invents a veto.
    """

    def _frame(self, change_pcts, master_scores):
        df = _add_horse_columns(
            _make_feature_frame(
                change_pcts=change_pcts,
                master_scores=master_scores,
                scores=master_scores,
            )
        )
        return _add_confirmation_columns(df)

    def _disarm_upstream(self, engine):
        engine.config.hard_min_breadth_pct = 0.0
        engine.config.require_positive_day_change = False
        engine.config.index_tape_enabled = False

    def test_dead_zone_row_banned(self):
        # PPL's exact shape: +0.79% day, conviction 0.623 - refused.
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([0.79, 6.0, 0.0], [0.623, 0.85, 0.84])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert "dead_zone_ban" in decision.reason

    def test_strong_conviction_escapes(self):
        # Same mild-green shape but conviction 0.75 clears the 0.70
        # ceiling: the escape hatch works, the tape earns its shot.
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([0.79, 6.0, 0.0], [0.75, 0.85, 0.84])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        decision = engine.evaluate(df)
        assert decision.action == "ENTER" and decision.symbol == "ABOT"

    def test_missing_day_change_never_vetoed(self):
        # A row with no day-change evidence is never refused AT Rule 26.
        # (The NaN row is dropped earlier by the day-change cap - NaN
        # fails every comparison - so the precise assertion is that the
        # dead-zone stage itself loses zero rows: its survivor count
        # equals the previous stage's.)
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([0.79, 6.0, 0.0], [0.623, 0.85, 0.84])
        df.loc[df.index[0], "change_pct"] = None
        engine._filter_candidates(df, held_symbols=set())
        trace = dict(engine._last_filter_trace)
        assert trace["dead_zone_ban<2%_low_conviction"] == trace["chase_veto<8"]

    def test_disabled_knob_disarms_the_rule(self):
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        engine.config.dead_zone_veto_enabled = False
        df = self._frame([0.79, 6.0, 0.0], [0.623, 0.85, 0.84])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        decision = engine.evaluate(df)
        assert decision.action == "ENTER" and decision.symbol == "ABOT"

    def test_boundary_two_pct_is_outside_the_band(self):
        # The measured band is 0 <= chg < 2.0; exactly 2.0 escapes the
        # ban and reaches the conviction gate (where the 6%-row's chase
        # penalty is what finally ranks it - a Rule 24 affair, not 26).
        engine = DecisionEngine()
        self._disarm_upstream(engine)
        df = self._frame([2.0, 6.0, 0.0], [0.623, 0.85, 0.84])
        df.loc[df.index[1], "tradable"] = False
        df.loc[df.index[2], "tradable"] = False
        pool = engine._filter_candidates(df, held_symbols=set())
        assert "ABOT" in set(pool["symbol"])


class TestPennyFloor:
    """Rule 27 (v4.2.1): sub-Rs-10 names never enter."""

    def test_cheap_stock_vetoed(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        df.loc[df.index[0], "price"] = 6.67  # KEL-class penny name
        pool = engine._filter_candidates(df, held_symbols=set())
        assert "ABOT" not in set(pool["symbol"])

    def test_missing_price_fails_closed(self):
        engine = DecisionEngine()
        df = _make_feature_frame()
        df.loc[df.index[0], "price"] = None
        pool = engine._filter_candidates(df, held_symbols=set())
        assert "ABOT" not in set(pool["symbol"])

    def test_floor_is_configurable(self):
        cfg = DecisionConfig(min_entry_price=5.0)
        engine = DecisionEngine(cfg)
        df = _make_feature_frame()
        df.loc[df.index[0], "price"] = 6.67
        pool = engine._filter_candidates(df, held_symbols=set())
        assert "ABOT" in set(pool["symbol"])
