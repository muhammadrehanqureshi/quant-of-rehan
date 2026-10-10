"""Volatility regime and edge-case detection, with the levers off by default."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals import volatility as V  # noqa: E402
from src.signals.contracts import Bar  # noqa: E402

AT = datetime(2026, 10, 9, 10, 0, tzinfo=KARACHI)


def series(count: int = 20, close: float = 100.0, span: float = 0.1,
           volume: float | None = 5000.0, drift: float = 0.0,
           start: datetime = AT, minutes: int = 1) -> list[Bar]:
    """A deterministic bar series; `span` is high-minus-low in price units."""
    bars = []
    price = close
    for index in range(count):
        price *= 1.0 + drift
        bars.append(Bar(symbol="OGDC", timestamp=start + timedelta(minutes=index * minutes),
                        open=price, high=price + span / 2, low=price - span / 2,
                        close=price, volume=volume))
    return bars


class RegimeTest(unittest.TestCase):
    def test_classify_buckets_against_the_configured_thresholds(self):
        self.assertIs(V.classify(config.ATR_CALM_PCT), V.Regime.CALM)
        self.assertIs(V.classify(config.ATR_CALM_PCT * 1.5), V.Regime.NORMAL)
        self.assertIs(V.classify(config.ATR_ELEVATED_PCT * 1.5), V.Regime.ELEVATED)
        self.assertIs(V.classify(config.ATR_EXTREME_PCT * 2), V.Regime.EXTREME)

    def test_unknown_when_there_is_nothing_to_measure(self):
        self.assertIs(V.classify(None), V.Regime.UNKNOWN)
        self.assertIs(V.classify(float("nan")), V.Regime.UNKNOWN)

    def test_calm_and_violent_sessions_are_distinguished(self):
        calm = V.assess("OGDC", series(span=0.1), AT)          # 0.10% ranges
        wild = V.assess("OGDC", series(span=3.0), AT)          # 3.00% ranges
        self.assertIs(calm.regime, V.Regime.CALM)
        self.assertIs(wild.regime, V.Regime.EXTREME)
        self.assertGreater(wild.atr_pct or 0, calm.atr_pct or 0)

    def test_realized_volatility_needs_enough_returns(self):
        self.assertIsNone(V.realized_volatility(series(count=2)))
        self.assertIsNotNone(V.realized_volatility(series(count=20, drift=0.001)))

    def test_true_range_accounts_for_a_gap(self):
        bars = series(count=3)
        bars[1] = Bar(symbol="OGDC", timestamp=bars[1].timestamp,
                      open=110.0, high=110.5, low=109.5, close=110.0,
                      volume=5000.0)
        ranges = V.true_ranges(bars)
        self.assertGreater(ranges[1], 9.0)  # the gap, not just high minus low


class EdgeCaseTest(unittest.TestCase):
    def test_a_thin_sample_is_flagged(self):
        reading = V.assess("OGDC", series(count=5), AT)
        self.assertIn(V.EdgeCase.THIN_SAMPLE, reading.edge_cases)

    def test_a_stale_last_bar_is_flagged(self):
        old = series(count=20, start=AT - timedelta(minutes=40))
        reading = V.assess("OGDC", old, AT)
        self.assertIn(V.EdgeCase.STALE_LAST_BAR, reading.edge_cases)

    def test_a_locked_session_is_untradable(self):
        bars = [Bar(symbol="OGDC", timestamp=AT + timedelta(minutes=index),
                    open=100.0, high=100.0, low=100.0, close=100.0, volume=0.0)
                for index in range(20)]
        reading = V.assess("OGDC", bars, AT + timedelta(minutes=19))
        self.assertIn(V.EdgeCase.ZERO_RANGE, reading.edge_cases)
        self.assertIn(V.EdgeCase.LIMIT_LOCKED, reading.edge_cases)
        self.assertTrue(reading.is_untradable)

    def test_a_flat_print_with_volume_is_flat_but_tradable(self):
        bars = [Bar(symbol="OGDC", timestamp=AT + timedelta(minutes=index),
                    open=100.0, high=100.0, low=100.0, close=100.0,
                    volume=5000.0) for index in range(20)]
        reading = V.assess("OGDC", bars, AT + timedelta(minutes=19))
        self.assertIn(V.EdgeCase.FLAT_BARS, reading.edge_cases)
        self.assertNotIn(V.EdgeCase.LIMIT_LOCKED, reading.edge_cases)
        self.assertFalse(reading.is_untradable)

    def test_a_gap_open_is_flagged_in_both_directions(self):
        bars = series(count=20)
        up = V.assess("OGDC", bars, AT + timedelta(minutes=19),
                      previous_close=100.0 / (1 + config.MAX_GAP_PCT * 1.5))
        self.assertIn(V.EdgeCase.GAP_UP, up.edge_cases)
        down = V.assess("OGDC", bars, AT + timedelta(minutes=19),
                        previous_close=100.0 * (1 + config.MAX_GAP_PCT * 1.5))
        self.assertIn(V.EdgeCase.GAP_DOWN, down.edge_cases)

    def test_a_violent_intraday_swing_is_flagged(self):
        bars = series(count=20, span=0.1)
        bars[-1] = Bar(symbol="OGDC", timestamp=bars[-1].timestamp, open=100.0,
                       high=112.0, low=100.0, close=111.0, volume=5000.0)
        reading = V.assess("OGDC", bars, AT + timedelta(minutes=19))
        self.assertIn(V.EdgeCase.EXTREME_SWING, reading.edge_cases)

    def test_missing_volume_is_flagged(self):
        reading = V.assess("OGDC", series(count=20, volume=None), AT)
        self.assertIn(V.EdgeCase.MISSING_VOLUME, reading.edge_cases)

    def test_no_edges_on_a_normal_session(self):
        reading = V.assess("OGDC", series(count=20, span=0.3, drift=0.0005),
                           AT + timedelta(minutes=19))
        self.assertEqual(reading.edge_cases, ())


class LeverTest(unittest.TestCase):
    def reading(self, regime: V.Regime) -> V.VolatilityAssessment:
        return V.VolatilityAssessment(symbol="OGDC", regime=regime, atr_pct=0.001,
                                      realized_vol=0.001, gap_pct=None,
                                      swing_pct=0.01, bars=20)

    def test_target_multiplier_is_a_no_op_by_default(self):
        self.assertFalse(config.VOLATILITY_AWARE_TARGETS)
        for regime in V.Regime:
            self.assertEqual(self.reading(regime).target_multiplier, 1.0)

    def test_target_multiplier_uses_the_regime_table_when_enabled(self):
        with patch.object(config, "VOLATILITY_AWARE_TARGETS", True):
            self.assertEqual(self.reading(V.Regime.CALM).target_multiplier,
                             config.TARGET_MULTIPLIER_BY_REGIME["CALM"])
            self.assertEqual(self.reading(V.Regime.EXTREME).target_multiplier,
                             config.TARGET_MULTIPLIER_BY_REGIME["EXTREME"])
            self.assertEqual(self.reading(V.Regime.UNKNOWN).target_multiplier, 1.0)

    def test_the_veto_is_off_by_default(self):
        locked = self.reading(V.Regime.CALM)
        locked = V.VolatilityAssessment(
            symbol="OGDC", regime=V.Regime.CALM, atr_pct=None, realized_vol=None,
            gap_pct=None, swing_pct=None, bars=20,
            edge_cases=(V.EdgeCase.LIMIT_LOCKED,))
        self.assertIsNone(V.hard_block_fault(locked))
        with patch.object(config, "VOLATILITY_VETO_ENABLED", True):
            fault = V.hard_block_fault(locked)
        self.assertIsNotNone(fault)
        self.assertIn("limit locked", fault.detail)

    def test_the_veto_leaves_a_normal_name_alone(self):
        with patch.object(config, "VOLATILITY_VETO_ENABLED", True):
            self.assertIsNone(V.hard_block_fault(self.reading(V.Regime.NORMAL)))

    def test_assessment_serialises_for_the_observation(self):
        payload = V.assess("OGDC", series(count=20, span=0.3), AT).as_dict()
        self.assertEqual(payload["symbol"], "OGDC")
        self.assertIn("regime", payload)
        self.assertIsInstance(payload["edge_cases"], list)


if __name__ == "__main__":
    unittest.main()
