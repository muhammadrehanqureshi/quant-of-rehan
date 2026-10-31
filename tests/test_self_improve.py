"""The self-improvement engine under test (owner order, the mission).

The mission's integrity rules are the tests themselves: the registry counts
every trial, the labeler books the stop first under the mission's own costs,
the nested split is strictly chronological, a variant that fails discovery
never sees validation, and nothing is ever promoted to the live path while
the flag is OFF.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.research import experiment_registry as registry  # noqa: E402
from src.research.outcome_labeler import (  # noqa: E402
    LabelParams, label_candidates, label_summary, net_after_costs)


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "experiments.jsonl"
        self.reg = registry.Registry(self.path)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def test_the_registry_appends_and_never_rewrites(self):
        self.reg.append({"hypothesis": "one", "decision": "KILL",
                         "params": {"a": 1}, "results": {"n": 0}})
        self.reg.append({"hypothesis": "two", "decision": "KEEP",
                         "params": {"a": 2}, "results": {"n": 1}})
        rows = self.reg.rows()
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["decision"], "KILL")
        # The row missing every other field is still one explicit record.
        self.assertIn("code_hash", rows[0])
        self.assertEqual(self.reg.count(), 2)

    def test_one_sided_p_and_holm(self):
        self.assertLess(registry.one_sided_p(0.95, 200), 1e-6)
        self.assertGreater(registry.one_sided_p(0.5, 200), 0.4)
        self.assertIsNone(registry.one_sided_p(0.5, 0))
        adjusted = registry.holm_adjusted({"a": 0.02, "b": 0.002})
        # Holm step-down, smallest first, descending multipliers: the
        # smallest p doubles (two tested claims), the largest stands alone.
        self.assertAlmostEqual(adjusted["b"], 0.004, places=9)
        self.assertAlmostEqual(adjusted["a"], 0.02, places=9)
        self.assertGreaterEqual(adjusted["a"], adjusted["b"])

    def test_code_and_data_hash_name_what_the_run_saw(self):
        digest = registry.code_hash(ROOT)
        self.assertIn(":", digest)
        self.assertGreater(len(digest.split(":")[1]), 0)
        here = registry.data_hash(Path(__file__))
        self.assertGreater(len(here), 12)


class LabelerTests(unittest.TestCase):
    def setUp(self) -> None:
        # Two days, base price 100: a signal at the close of day T enters
        # at the OPEN of T+1, so a 01-01 signal owns the 01-02 bar.
        self.panel = pd.DataFrame([
            {"symbol": "ABC", "date": pd.Timestamp("2026-01-01"),
             "open": 99.0, "high": 100.5, "low": 98.5, "close": 100.0,
             "volume": 1000},
            {"symbol": "ABC", "date": pd.Timestamp("2026-01-02"),
             "open": 100.0, "high": 103.0, "low": 97.0, "close": 101.0,
             "volume": 1500},
        ])
        self.params = LabelParams(tp=0.02, sl=0.01, max_hold=10)

    def _candidates(self, symbol="ABC", day="2026-01-01"):
        return pd.DataFrame([
            {"symbol": symbol, "signal_date": pd.Timestamp(day), "score": 80.0},
        ])

    def test_costs_are_the_missions_own(self):
        # 22.4 bps fees plus 10 bps slippage, both sides, before CGT.
        self.assertAlmostEqual(net_after_costs(0.02, self.params) / 0.01,
                               (0.02 - 0.00648) * 0.85 / 0.01, places=6)
        # A loss carries the costs and no CGT.
        self.assertAlmostEqual(net_after_costs(-0.01, self.params),
                               -0.01 - 0.00648, places=9)

    def test_the_stop_wins_when_one_bar_touches_both(self):
        # Entry 100: target 102 touched (high 103) and stop 99 touched
        # (low 97) on the SAME bar. The pessimistic order books the stop.
        labels = label_candidates(self.panel, self._candidates(), self.params)
        self.assertEqual(labels.loc[0, "outcome"], "SL")
        self.assertAlmostEqual(labels.loc[0, "exit"], 99.0, places=6)
        self.assertEqual(labels.loc[0, "bars_held"], 1)

    def test_gap_through_stop_fills_at_the_open(self):
        # Entry 100 at the 01-02 open (stop 99, target 102); the NEXT bar
        # opens 98.5, below the stop, and never reaches the target (its
        # high is 100.5): the fill is that open, the engine's own
        # gap-through law, never a better fake price.
        panel = pd.concat([self.panel, pd.DataFrame([
            {"symbol": "ABC", "date": pd.Timestamp("2026-01-03"),
             "open": 98.5, "high": 100.5, "low": 97.0, "close": 98.0,
             "volume": 1600},
        ])], ignore_index=True)
        panel.loc[1, "low"] = 100.0  # the entry bar never touches the stop
        panel.loc[1, "high"] = 101.0  # and it never reaches the target
        labels = label_candidates(panel, self._candidates(), self.params)
        self.assertEqual(labels.loc[0, "outcome"], "SL")
        self.assertAlmostEqual(labels.loc[0, "entry"], 100.0, places=6)
        self.assertAlmostEqual(labels.loc[0, "exit"], 98.5, places=6)
        self.assertAlmostEqual(labels.loc[0, "gross_ret"], -0.015, places=6)
        self.assertEqual(labels.loc[0, "bars_held"], 2)

    def test_target_fills_at_its_own_price(self):
        # Remove the stop touch (low at 100) so the bar only reaches the
        # target: the limit books 102.00 exactly, never the 103 high.
        panel = self.panel.copy()
        panel.loc[1, "low"] = 100.0
        labels = label_candidates(panel, self._candidates(), self.params)
        self.assertEqual(labels.loc[0, "outcome"], "TP")
        self.assertAlmostEqual(labels.loc[0, "exit"], 102.0, places=6)
        self.assertAlmostEqual(labels.loc[0, "entry"], 100.0, places=6)

    def test_a_candidate_with_no_next_bar_is_named_not_faked(self):
        labels = label_candidates(self.panel,
                                  self._candidates("ABC", "2026-01-02"),
                                  self.params)
        self.assertEqual(labels.loc[0, "label"], "NO_ENTRY")
        # And the summary counts it, never hides it (SO-3).
        summary = label_summary(labels)
        self.assertEqual(summary.get("no_entry"), 1)
        self.assertEqual(summary.get("n"), 0)

    def test_the_label_summary_carries_the_mission_scorecard(self):
        panel = self.panel.copy()
        panel.loc[1, "low"] = 100.0  # a clean target hit, no stop touch
        labels = label_candidates(panel, self._candidates(), self.params)
        summary = label_summary(labels)
        self.assertEqual(summary["wins"], 1)
        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["cost_side_bps"], 32.4)
        self.assertAlmostEqual(summary["net_expectancy"], 0.011492, places=6)
        self.assertIn("bootstrap_lower_2.5", summary)


class SearchEngineTests(unittest.TestCase):
    """The search loop's own integrity, on the real split bounds."""

    def test_the_nested_split_is_strictly_chronological(self):
        import scripts.self_improve as si
        splits = si._split_dates(pd.Series(pd.to_datetime(
            ["2022-01-01", "2026-10-29"])))
        discovery_end = pd.Timestamp(splits["discovery"][1])
        validation_start = pd.Timestamp(splits["validation"][0])
        validation_end = pd.Timestamp(splits["validation"][1])
        test_start = pd.Timestamp(splits["test"][0])
        self.assertLess(discovery_end, validation_start)
        self.assertLess(validation_end, test_start)
        self.assertEqual(str(test_start.date()).replace("-", ""),
                         config.SELF_IMPROVE_TEST_START.replace("-", ""))

    def test_the_kill_rule_runs_before_validation(self):
        import scripts.self_improve as si
        killed, why = si._kill({"n": 10, "win_rate": 0.9,
                                "net_expectancy": 0.01}, "tiny")
        self.assertTrue(killed)
        self.assertIn("trades", why)
        killed, why = si._kill({"n": 500, "win_rate": 0.40,
                                "net_expectancy": 0.01}, "weak")
        self.assertTrue(killed)
        self.assertIn("win rate", why)

    def test_the_grid_pre_registers_every_variant(self):
        import scripts.self_improve as si
        names = [variant["name"] for variant in si.pre_registered_variants()]
        self.assertGreaterEqual(len(names), 12)
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("baseline-deployed-law", names)

    def test_no_variant_touches_the_live_scanner_module(self):
        source = (ROOT / "scripts" / "self_improve.py").read_text(
            encoding="utf-8")
        self.assertNotIn("momentum_scanner", source)
        self.assertNotIn("kalman_trend", source)
        self.assertNotIn("KALMAN_FLIP", source)


class FlagAndHygieneTests(unittest.TestCase):
    def test_the_engine_ships_behind_an_off_by_default_flag(self):
        self.assertFalse(config.SELF_IMPROVE_ARM,
                         "the mission: OFF by default, promotion through "
                         "the gate only")

    def test_nothing_here_sleeps_or_waits_on_a_clock(self):
        for rel in ("src/research/experiment_registry.py",
                    "src/research/outcome_labeler.py",
                    "scripts/self_improve.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("time.sleep", source, rel)
            self.assertNotIn("asyncio.sleep", source, rel)

    def test_the_em_dash_ban_holds_in_every_new_file(self):
        for rel in ("src/research/experiment_registry.py",
                    "src/research/outcome_labeler.py",
                    "scripts/self_improve.py"):
            source = (ROOT / rel).read_text(encoding="utf-8")
            for banned in ("\u2014", "\u2013"):
                self.assertNotIn(banned, source, rel)


class DemotionTests(unittest.TestCase):
    def test_the_existing_rules_demote_a_failing_window(self):
        import scripts.self_improve as si
        outcomes = [{"net_return": 0.001}] * 15 + \
                   [{"net_return": -0.02}] * 5
        verdict = si.demotion_check(outcomes)
        self.assertTrue(verdict["demote"])
        self.assertIn("net", verdict["reason"])
        # Streak and drawdown thresholds are the existing law's numbers.
        self.assertEqual(si.DEMOTION_RULES["max_losing_streak"], 8)
        self.assertEqual(si.DEMOTION_RULES["max_drawdown"], 0.10)

    def test_a_healthy_window_stands(self):
        import scripts.self_improve as si
        outcomes = [{"net_return": 0.001}] * 20
        self.assertFalse(si.demotion_check(outcomes)["demote"])


if __name__ == "__main__":
    unittest.main()
