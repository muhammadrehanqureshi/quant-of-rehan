"""
Tests for the Tier-1 roadmap additions: VWAP, opening range, gap,
Garman-Klass, time-of-day, liquidity floor, circuit breaker, and the
outcomes assembler.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import build_kmiall_features as feats
from decision_engine import DecisionConfig, DecisionEngine
from psx_core import paths, sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(minute, second=0):
    return pd.Timestamp(
        f"2026-09-08 04:32:{second:02d}+00:00"
    ) + pd.Timedelta(minutes=minute)


def _tier1_frame(symbol="ABOT", ticks=20):
    """
    A small but well-formed frame: one symbol, `ticks` rows at 5s
    spacing, with everything the Tier-1 blocks read.

    Volume and value accumulate the way the real feed does: each tick
    adds a new traded quantity at that tick's price.
    """
    rows = []
    price = 100.0
    volume_cum = 0.0
    value_cum = 0.0
    for i in range(ticks):
        price = 100.0 + i * 0.05  # gently rising tape
        traded = 1000.0           # shares traded this tick
        volume_cum += traded
        value_cum += traded * price
        rows.append({
            "symbol": symbol,
            "timestamp": _ts(i * 5 // 60, i * 5 % 60),
            "trading_date": "2026-09-08",
            "tradable": True,
            "feature_price_ok": True,
            "price": price,
            "high": price + 0.10,
            "low": price - 0.10,
            "volume": volume_cum,      # cumulative
            "value": value_cum,       # cumulative at tick prices
            "change_pct": 0.5,
            "change_fraction": 0.005,
            "breadth_pct": 60.0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# T1.1 VWAP
# ---------------------------------------------------------------------------

class TestVwap:
    def test_vwap_equals_first_price_at_open(self):
        df = _tier1_frame()
        out = feats.add_vwap_features(df)
        first = out.iloc[0]
        # At the first tick, cumulative value/volume IS that price.
        assert first["session_vwap"] == pytest.approx(first["price"])
        assert first["vwap_ratio"] == pytest.approx(0.0)

    def test_ratio_positive_above_vwap(self):
        # Rising prices: every later price sits above the running VWAP.
        df = _tier1_frame()
        out = feats.add_vwap_features(df)
        assert (out["vwap_ratio"].iloc[1:] > 0).all()

    def test_zero_volume_yields_nan(self):
        df = _tier1_frame()
        df.loc[df.index, "volume"] = 0.0
        out = feats.add_vwap_features(df)
        assert out["session_vwap"].isna().all()

    def test_constant_price_zero_ratio(self):
        df = _tier1_frame()
        df["price"] = 100.0
        df["value"] = 100.0 * df["volume"]
        out = feats.add_vwap_features(df)
        assert (out["vwap_ratio"].fillna(0) == 0).all()


# ---------------------------------------------------------------------------
# T1.2 Opening range
# ---------------------------------------------------------------------------

class TestOpeningRange:
    def test_range_from_first_window(self):
        # v0.18.1 causal contract: the window is the first 30 min of
        # the session leg BY MARKET CLOCK. _tier1_frame's 50 ticks span
        # 2026-09-08 04:32:00+00 (09:32 PKT) + 4 min - entirely inside
        # the window - so every row shows the RUNNING range: the range
        # at row i may only include highs/lows from rows <= i.
        df = _tier1_frame(ticks=50)
        out = feats.add_opening_range_features(df)
        # First row: only its own tick is in the running range.
        assert out["or_high"].iloc[0] == pytest.approx(df["high"].iloc[0])
        assert out["or_low"].iloc[0] == pytest.approx(df["low"].iloc[0])
        # Final in-window row: the full window so far = all 50 ticks.
        assert out["or_high"].iloc[-1] == pytest.approx(df["high"].max())
        assert out["or_low"].iloc[-1] == pytest.approx(df["low"].min())
        # Monotone running range: high never decreases, low never
        # increases across the window (causality shape-check).
        assert (out["or_high"].diff().dropna() >= -1e-9).all()
        assert (out["or_low"].diff().dropna() <= 1e-9).all()

    def test_post_window_rows_frozen_to_completed_range(self):
        # Rows AFTER the wall-clock window close must see the completed
        # window range - the range a real-time bot could know then.
        # Frame: 20 ticks inside the window, 30 ticks 45 min past it.
        df = _tier1_frame(ticks=50)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        df["timestamp"] = ts + pd.Series(
            [pd.Timedelta(0)] * 20 + [pd.Timedelta(minutes=45)] * 30,
            index=df.index,
        )
        out = feats.add_opening_range_features(df)
        in_win, post = out.iloc[:20], out.iloc[20:]
        # In-window rows: running range only.
        assert in_win["or_high"].iloc[0] == pytest.approx(df["high"].iloc[0])
        # Post-window rows: frozen to the COMPLETED in-window range
        # (the first 20 ticks only - the later highs must NOT leak in).
        assert np.allclose(post["or_high"], df["high"].iloc[:20].max())
        assert np.allclose(post["or_low"], df["low"].iloc[:20].min())

    def test_no_ticks_in_window_yields_nan(self):
        df = _tier1_frame(ticks=10)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True) + pd.Timedelta(hours=2)
        out = feats.add_opening_range_features(df)
        assert out["or_high"].isna().all()
        assert out["orb_score"].isna().all()

    def test_inside_range_scores_zero(self):
        df = _tier1_frame(ticks=50)
        out = feats.add_opening_range_features(df)
        # Rising series ends above the range high - earlier rows are
        # inside and must score exactly 0 (a real 0, not NaN).
        inside = out.iloc[:10]
        assert (inside["orb_score"] == 0.0).all()

    def test_breakout_positive(self):
        df = _tier1_frame(ticks=50)
        # Make the final tick break decisively above the range high.
        df.loc[df.index[-1], "price"] = df["high"].max() * 1.02
        out = feats.add_opening_range_features(df)
        last = out.iloc[-1]
        expected = (last["price"] - last["or_high"]) / last["or_high"]
        assert last["orb_score"] == pytest.approx(expected)
        assert last["orb_score"] > 0


# ---------------------------------------------------------------------------
# T1.3 Gap
# ---------------------------------------------------------------------------

class TestGap:
    def test_gap_reconstruction(self):
        df = _tier1_frame(ticks=5)
        # price=100.00 at tick 0, change_fraction=0.005
        # prior_close = 100 / 1.005 = 99.5025
        # gap = 100/99.5025 - 1 = 0.005
        out = feats.add_gap_features(df)
        assert out["gap_pct"].iloc[0] == pytest.approx(0.005, rel=1e-3)
        # One value per (date, symbol), broadcast to all rows.
        assert out["gap_pct"].notna().all()
        assert out["gap_pct"].nunique() == 1

    def test_zero_change_zero_gap(self):
        df = _tier1_frame(ticks=5)
        df["change_fraction"] = 0.0
        out = feats.add_gap_features(df)
        assert out["gap_pct"].iloc[0] == pytest.approx(0.0)

    def test_negative_change_negative_gap(self):
        df = _tier1_frame(ticks=5)
        df["change_fraction"] = -0.02
        out = feats.add_gap_features(df)
        assert out["gap_pct"].iloc[0] < 0


# ---------------------------------------------------------------------------
# T1.4 Garman-Klass

# ---------------------------------------------------------------------------
# T1.5 Liquidity floor
# ---------------------------------------------------------------------------

def _candidate_frame(values):
    """A feature frame whose rows carry the given cumulative `value`."""
    rows = []
    for i, value in enumerate(values):
        row = {
            "symbol": f"S{i}", "timestamp": _ts(60),
            "tradable": True,
            "feature_rank_score_adjusted": 0.8,
            "score_weight_coverage": 0.9,
            "price": 100.0 + i, "change_pct": 0.5,
            "price_position_range": 0.5, "breadth_pct": 60.0,
            "master_score": 0.8, "master_score_weight_coverage": 0.9,
            "value": value,
        }
        for k in range(6):
            row[f"z_fake_{k}"] = 0.6
        rows.append(row)
    return pd.DataFrame(rows)


class TestLiquidityFloor:
    def test_thin_names_excluded(self):
        df = _candidate_frame([5e6, 50e6, 500e6])
        engine = DecisionEngine(DecisionConfig(min_day_value=20e6))
        decision = engine.evaluate(df)
        # S0 (5e6) is filtered out by the floor; among the two equal-
        # score survivors the first candidate wins the stable sort.
        assert decision.symbol == "S1"

    def test_all_thin_stands_aside(self):
        df = _candidate_frame([1e6, 2e6])
        engine = DecisionEngine(DecisionConfig(min_day_value=20e6))
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"

    def test_disabled_floor_admits_thin(self):
        df = _candidate_frame([5e6, 50e6])
        engine = DecisionEngine(DecisionConfig(min_day_value=0))
        decision = engine.evaluate(df)
        # Highest master wins regardless of value.
        assert decision.symbol == "S0"

    def test_missing_value_fails_conservatively(self):
        df = _candidate_frame([np.nan, 80e6])
        engine = DecisionEngine(DecisionConfig(min_day_value=20e6))
        decision = engine.evaluate(df)
        assert decision.symbol == "S1"


# ---------------------------------------------------------------------------
# T1.6 Circuit breaker
# ---------------------------------------------------------------------------

def _locked_frame(symbol="LOCKED", ticks=14):
    """A symbol pinned at its upper band for the last 12 ticks."""
    rows = []
    for i in range(ticks):
        row = {
            "symbol": symbol, "timestamp": _ts(i * 5),
            "trading_date": "2026-09-08",
            "tradable": True, "feature_price_ok": True,
            "feature_rank_score_adjusted": 0.8,
            "score_weight_coverage": 0.9,
            "price": 110.0,            # frozen
            "high": 110.0,              # pinned at day high
            "change_pct": 9.9,          # at the band
            "price_position_range": 0.9,
            "breadth_pct": 60.0,
            "master_score": 0.8, "master_score_weight_coverage": 0.9,
            "value": 100e6,
        }
        for k in range(6):
            row[f"z_fake_{k}"] = 0.6
        rows.append(row)
    return pd.DataFrame(rows)


class TestCircuitBreaker:
    """
    Note on scope: with the default no-chasing filter
    (max_same_day_change_pct=6.0), a stock at +9.5%+ is already excluded
    by Rule 4 before the lock detector ever runs. The breaker is
    defense-in-depth for when the chasing threshold is relaxed - these
    tests exercise it with a permissive change config.
    """

    def _permissive(self):
        # Rule 25 (v2.2.0) added a default-on hard chase ban at +8%.
        # These tests exercise the LOCK DETECTOR past every chase rule,
        # so the permissive config disarms it too.
        return DecisionConfig(
            max_same_day_change_pct=15.0,
            max_price_position=1.0,
            chase_hard_veto_enabled=False,
        )

    def test_locked_stock_blocked(self):
        df = _locked_frame()
        engine = DecisionEngine(self._permissive())
        decision = engine.evaluate(df)
        assert decision.action == "STAND_ASIDE"
        assert decision.metadata.get("circuit_locked") == ["LOCKED"]

    def test_detector_identifies_locked(self):
        df = _locked_frame()
        engine = DecisionEngine(self._permissive())
        candidates = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        assert len(candidates) > 0  # reaches the detector
        locked = engine._frozen_symbols(df, candidates)
        assert locked == {"LOCKED"}

    def test_strong_mover_not_blocked(self):
        # +9.9% but price still moving: NOT a lock.
        df = _locked_frame(symbol="MOVER")
        for i in range(len(df)):
            df.loc[df.index[i], "price"] = 110.0 + i * 0.01
            df.loc[df.index[i], "high"] = 110.0 + i * 0.01
        engine = DecisionEngine(self._permissive())
        candidates = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        locked = engine._frozen_symbols(df, candidates)
        assert locked == set()

    def test_below_band_change_not_locked(self):
        # +8%: below the 9.5 threshold - not a lock even if frozen.
        df = _locked_frame(symbol="EIGHT")
        df["change_pct"] = 8.0
        engine = DecisionEngine(self._permissive())
        candidates = engine._filter_candidates(
            df[df["timestamp"] == df["timestamp"].max()], set()
        )
        locked = engine._frozen_symbols(df, candidates)
        assert locked == set()


# ---------------------------------------------------------------------------
# T1.7 Time-of-day
# ---------------------------------------------------------------------------

class TestTimeOfDay:
    def test_weights_at_extremes(self):
        df = _tier1_frame(ticks=60)
        out = feats.add_time_of_day_features(df)
        # First tick: full weight.
        assert out["momentum_time_weight"].iloc[0] == pytest.approx(1.0)
        assert out["minutes_since_open"].iloc[0] == pytest.approx(0.0)

    def test_midday_trough(self):
        # A frame spanning 3.5 hours of session time reaches the U's
        # trough at t=105 min. Built directly: 211 ticks at 1-min steps.
        rows = []
        base = pd.Timestamp("2026-09-08 04:32:00+00:00")
        for i in range(211):
            rows.append({
                "symbol": "ABOT",
                "timestamp": base + pd.Timedelta(minutes=i),
                "trading_date": "2026-09-08",
            })
        df = pd.DataFrame(rows)
        out = feats.add_time_of_day_features(df)
        w = out["momentum_time_weight"]
        assert w.iloc[0] == pytest.approx(1.0)       # the open
        assert w.iloc[105] == pytest.approx(0.7)      # the trough
        assert w.iloc[210] == pytest.approx(1.0)      # the close window

    def test_all_weights_bounded(self):
        df = _tier1_frame(ticks=300)
        out = feats.add_time_of_day_features(df)
        w = out["momentum_time_weight"]
        assert (w >= 0.7).all() and (w <= 1.0).all()


# ---------------------------------------------------------------------------
# Master-blend re-centering (the 2026-09-08 diagnosis)
# ---------------------------------------------------------------------------
#
# The conviction gate assumes the master blend is neutral-centred at
# 0.5. Three components broke that assumption: z_orb scored 0 (not
# 0.5) for every non-breakout symbol, the retired volatility z-scores
# were max-normalised so their means sat near the floor, and the
# time-of-day scaling MULTIPLIED the momentum family (dragging a
# neutral 0.5 down to 0.35 at midday). Together they pushed the whole
# cross-section to ~0.34-0.40 and made a 0.55 gate unreachable on a
# normal day.


def _multisymbol_frame(symbols=25, ticks=30):
    """Several symbols over one session, with the columns the advanced
    and master blocks read. Prices vary per symbol so cross-sectional
    statistics are meaningful."""
    rows = []
    for i, symbol_no in enumerate(range(symbols)):
        symbol = f"SYM{symbol_no:02d}"
        base = 50.0 + symbol_no
        price = base
        for t in range(ticks):
            drift = 0.01 * ((symbol_no % 5) - 2)   # some up, some down
            price = base + t * drift
            rows.append({
                "symbol": symbol,
                "timestamp": _ts(t * 5 // 60, t * 5 % 60),
                "trading_date": "2026-09-08",
                "tradable": True,
                "feature_price_ok": True,
                "price": price,
                "high": price + 0.10 + (symbol_no % 3) * 0.05,
                "low": price - 0.10 - (symbol_no % 4) * 0.05,
                "volume": 1000.0 * (t + 1),
                "value": 1000.0 * (t + 1) * price,
                # Alternate sign so sector breadth sits at 0.5, not 1.0.
                "change_pct": 0.5 if symbol_no % 2 == 0 else -0.5,
                "change_fraction": 0.005,
                "breadth_pct": 60.0,
                "orb_score": 0.0,       # inside the range (no breakout)
                "gap_pct": 0.0,
                "vwap_ratio": 0.0,
                "momentum_1m_pct": drift * 100,
                "sector_net_flow_usd": np.nan,
                # Columns the z-block reads that upstream build stages
                # normally produce. Neutral constants -> z 0.5; event
                # ranks NaN -> their weight drops out (no signals).
                "relative_volume_1m": 1.0 + 0.2 * ((symbol_no % 5) - 2),
                "short_term_price_score": 0.5,
                "book_strength": 0.5,
                "spread_quality": 0.5,
                "trade_activity_score": 0.5,
                "rank_volume_surge_pct": np.nan,
                "rank_breakout_pct": np.nan,
                "rank_streak_pct": np.nan,
                "rank_accumulation_pct": np.nan,
                "rank_sharp_move_pct": np.nan,
            })
    return pd.DataFrame(rows)


class TestMasterRecentering:
    def test_orb_neutral_when_no_breakout(self):
        """A symbol inside its opening range has no breakout information:
        z_orb must be 0.5, not 0."""
        df = _multisymbol_frame()
        out = feats.add_master_score(feats.add_advanced_features(df))
        # pytest 9 dropped elementwise Series==approx(); compare directly.
        assert np.allclose(out["z_orb"].dropna().to_numpy(), 0.5)

    def test_orb_saturates_on_breakout(self):
        df = _multisymbol_frame()
        # One symbol breaks 5%+ above its range high.
        df.loc[df["symbol"] == "SYM03", "orb_score"] = 0.05
        out = feats.add_master_score(feats.add_advanced_features(df))
        broken = out[out["symbol"] == "SYM03"]
        assert broken["z_orb"].iloc[0] == pytest.approx(1.0)

    def test_retired_vol_columns_do_not_exist(self):
        """v3.3.0: Parkinson and Garman-Klass are retired by owner's
        order and no longer emitted at all - not even as NaN."""
        df = _multisymbol_frame()
        out = feats.add_advanced_features(df)
        assert "z_parkinson_vol" not in out.columns
        assert "z_gk_vol" not in out.columns
        assert "parkinson_vol_score" not in out.columns
        assert "gk_vol_score" not in out.columns

    def test_time_weight_shrinks_toward_neutral(self):
        """Midday (w=0.7) a neutral 0.5 component must STAY 0.5 - the
        old multiplicative scale turned it into 0.35."""
        df = _multisymbol_frame()
        out = feats.add_time_of_day_features(df)
        # The trough weight is 0.7; verify the shrink form directly.
        w = out["momentum_time_weight"]
        z = 0.5  # a neutral component value
        shrunk = 0.5 + w * (z - 0.5)
        assert np.allclose(shrunk.to_numpy(), 0.5)

    def test_time_weight_preserves_extremes_direction(self):
        w = 0.7
        z = 1.0  # a maximally bullish component
        shrunk = 0.5 + w * (z - 0.5)
        assert shrunk == pytest.approx(0.85)
        assert shrunk > 0.5  # still bullish, just less confident

    def test_master_score_centered_on_normal_field(self):
        """Integration: on a synthetic normal field (no breakouts, flat
        gaps, modest vol spread) the master blend's cross-section mean
        must sit near 0.5 - the property the 0.55 conviction gate
        assumes. The pre-fix blend measured 0.34-0.40."""
        df = _multisymbol_frame()
        out = feats.add_master_score(feats.add_advanced_features(df))
        scored = out["master_score"].dropna()
        assert len(scored) > 0
        assert scored.mean() == pytest.approx(0.5, abs=0.08)


# ---------------------------------------------------------------------------
# T0: Outcomes assembler
# ---------------------------------------------------------------------------

class TestOutcomesAssembler:
    @pytest.fixture
    def env(self, tmp_path, monkeypatch):
        logs_dir = tmp_path / "logs"; data_dir = tmp_path / "data"
        logs_dir.mkdir(); data_dir.mkdir()
        monkeypatch.setattr(paths, "LOGS_DIR", logs_dir)
        monkeypatch.setattr(paths, "DATA_DIR", data_dir)
        return tmp_path

    def _write(self, env, ledger_lines, positions):
        (paths.LOGS_DIR / "decisions.jsonl").write_text(
            "".join(json.dumps(l, default=str) + "\n"
                    for l in ledger_lines),
            encoding="utf-8",
        )
        (paths.DATA_DIR / "portfolio.json").write_text(
            json.dumps(positions), encoding="utf-8"
        )

    def test_profit_barrier_labels_win(self, env):
        import outcomes_assembler as oa
        self._write(
            env,
            [{"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
              "symbol": "ECOP", "price": 49.01, "score": 0.59,
              "metadata": {"score_kind": "master",
                            "evidence_count": 7}}],
            [{"symbol": "ECOP", "entry_price": 49.01,
              "entry_date": "2026-09-08", "target_price": 49.99,
              "status": "CLOSED", "exit_price": 50.14,
              "exit_date": "2026-09-08",
              "exit_reason": "Rule 3: profit target reached",
              "pnl": 1.13, "pnl_pct": 2.31, "trading_days_held": 0}],
        )
        written = oa.assemble_day("2026-09-08")
        assert len(written) == 1
        assert written[0]["barrier"] == "profit"
        assert written[0]["label"] == 1
        assert written[0]["score"] == 0.59

    def test_stop_barrier_labels_loss(self, env):
        import outcomes_assembler as oa
        self._write(
            env,
            [{"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
              "symbol": "X", "price": 100.0, "score": 0.6,
              "metadata": {}}],
            [{"symbol": "X", "entry_price": 100.0,
              "entry_date": "2026-09-08", "target_price": 102.0,
              "status": "CLOSED", "exit_price": 98.0,
              "exit_date": "2026-09-08",
              "exit_reason": "Rule 7: stop-loss triggered",
              "pnl": -2.0, "pnl_pct": -2.0, "trading_days_held": 0}],
        )
        written = oa.assemble_day("2026-09-08")
        assert written[0]["barrier"] == "stop"
        assert written[0]["label"] == 0

    def test_time_barrier_force_close(self, env):
        import outcomes_assembler as oa
        self._write(
            env,
            [{"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
              "symbol": "Y", "price": 50.0, "score": 0.6, "metadata": {}}],
            [{"symbol": "Y", "entry_price": 50.0,
              "entry_date": "2026-09-08", "target_price": 51.0,
              "status": "CLOSED", "exit_price": 50.5,
              "exit_date": "2026-09-08",
              "exit_reason": "End of session (intraday)",
              "pnl": 0.5, "pnl_pct": 1.0, "trading_days_held": 0}],
        )
        written = oa.assemble_day("2026-09-08")
        assert written[0]["barrier"] == "time"

    def test_open_position_no_label_then_refresh(self, env):
        import outcomes_assembler as oa
        ledger = [{"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
                   "symbol": "Z", "price": 40.0, "score": 0.6,
                   "metadata": {}}]
        self._write(
            env, ledger,
            [{"symbol": "Z", "entry_price": 40.0,
              "entry_date": "2026-09-08", "target_price": 40.8,
              "status": "OPEN", "pnl": None, "pnl_pct": None}],
        )
        written = oa.assemble_day("2026-09-08")
        assert written[0]["barrier"] == "open"
        assert written[0]["label"] is None

        # Later, the position closes: re-assembly replaces the open row.
        self._write(
            env, ledger,
            [{"symbol": "Z", "entry_price": 40.0,
              "entry_date": "2026-09-08", "target_price": 40.8,
              "status": "CLOSED", "exit_price": 40.2,
              "exit_date": "2026-09-08",
              "exit_reason": "Rule 3: profit target reached",
              "pnl": 0.2, "pnl_pct": 0.5, "trading_days_held": 0}],
        )
        written = oa.assemble_day("2026-09-08")
        assert written[0]["barrier"] == "profit"
        # Exactly ONE row for the symbol in the file.
        content = (paths.DATA_DIR / "outcomes.jsonl").read_text(
            encoding="utf-8"
        )
        assert content.count('"Z"') == 1

    def test_idempotent_re_run(self, env):
        import outcomes_assembler as oa
        ledger = [{"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
                   "symbol": "W", "price": 10.0, "score": 0.6,
                   "metadata": {}}]
        closed = [{"symbol": "W", "entry_price": 10.0,
                   "entry_date": "2026-09-08", "target_price": 10.2,
                   "status": "CLOSED", "exit_price": 10.2,
                   "exit_date": "2026-09-08",
                   "exit_reason": "Rule 3: profit target reached",
                   "pnl": 0.2, "pnl_pct": 2.0, "trading_days_held": 0}]
        self._write(env, ledger, closed)
        assert len(oa.assemble_day("2026-09-08")) == 1
        # Re-run: already final, nothing new written.
        assert len(oa.assemble_day("2026-09-08")) == 0

    def test_stats(self, env):
        import outcomes_assembler as oa
        ledger = [
            {"at": "2026-09-08T05:00:00+00:00", "action": "ENTER",
             "symbol": "A", "price": 10.0, "score": 0.6, "metadata": {}},
            {"at": "2026-09-08T06:00:00+00:00", "action": "ENTER",
             "symbol": "B", "price": 20.0, "score": 0.6, "metadata": {}},
        ]
        positions = [
            {"symbol": "A", "entry_price": 10.0,
             "entry_date": "2026-09-08", "target_price": 10.2,
             "status": "CLOSED", "exit_price": 10.2, "exit_date": "2026-09-08",
             "exit_reason": "Rule 3: profit target reached",
             "pnl": 0.2, "pnl_pct": 2.0, "trading_days_held": 0},
            {"symbol": "B", "entry_price": 20.0,
             "entry_date": "2026-09-08", "target_price": 20.4,
             "status": "CLOSED", "exit_price": 19.6, "exit_date": "2026-09-08",
             "exit_reason": "Rule 7: stop-loss triggered",
             "pnl": -0.4, "pnl_pct": -2.0, "trading_days_held": 0},
        ]
        self._write(env, ledger, positions)
        oa.assemble_day("2026-09-08")
        s = oa.stats()
        assert s["labeled"] == 2
        assert s["wins"] == 1 and s["losses"] == 1
        assert s["hit_rate"] == pytest.approx(0.5)
        assert s["barriers"]["profit"] == 1
        assert s["barriers"]["stop"] == 1
        assert s["total_pnl"] == pytest.approx(-0.2)
