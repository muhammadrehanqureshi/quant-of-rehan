"""The AI prior: feature equivalence, fail-closed loading, bounded routing.

The heaviest test here is the equivalence check: the live featurizer must
reproduce the research table the model was trained on. Without it the model
would be served inputs it never saw, so it is asserted rather than assumed.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI  # noqa: E402
from src.signals import ai_model  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402

HAVE_DATA = ai_model.EVENTS_PATH.is_file() and ai_model.PANEL_PATH.is_file()
HAVE_MODEL = ai_model.MODEL_PATH.is_file()


def one_session(as_of: datetime, prices: list[float], volume: float = 5_000.0,
                symbol: str = "AAA") -> scanner.SessionData:
    """A minimal in-session capture: one symbol, one bar per minute."""
    open_at = datetime.combine(as_of.date(), datetime.min.time(),
                               tzinfo=KARACHI).replace(hour=9, minute=32)
    bars = []
    for index, price in enumerate(prices):
        stamp = open_at + timedelta(minutes=index)
        bars.append(scanner.MinuteBar(stamp, price, price * 1.001,
                                      price * 0.999, price, volume))
    return scanner.SessionData(day=as_of.date(), as_of=as_of, bars={symbol: bars},
                               volume_available=True, bars_seen=len(bars),
                               bars_rejected=0, duplicate_bars=0)


class FeatureEquivalenceTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_DATA, "event study / panel data not present")
    def test_live_featurizer_reproduces_the_research_table(self):
        """The model's inputs and the research table's inputs must agree."""
        import pandas as pd

        sys.path.insert(0, str(ROOT / "scripts"))
        from train_signal_model import check_feature_equivalence

        events = pd.read_parquet(ai_model.EVENTS_PATH)
        panel = ai_model.load_panel()
        report = check_feature_equivalence(events, panel, rows=200)
        self.assertTrue(report["passed"], report)
        self.assertGreater(report["sampled_rows"], 0)
        for row in report["per_feature"]:
            if row["compared"]:
                self.assertGreaterEqual(row["agreement"], 0.995, row)

    def test_feature_list_is_the_trained_contract(self):
        self.assertEqual(len(ai_model.FEATURES), len(set(ai_model.FEATURES)))
        self.assertIn("ret1", ai_model.FEATURES)
        self.assertIn("mkt_adv", ai_model.FEATURES)


class ArtifactTest(unittest.TestCase):
    @unittest.skipUnless(HAVE_MODEL, "trained artifact not present")
    def test_artifact_matches_the_live_feature_contract(self):
        model = ai_model.load()
        self.assertIsNotNone(model)
        assert model is not None
        self.assertEqual(model.features, ai_model.FEATURES)
        self.assertEqual(model.label, ai_model.TRUTH_LABEL)
        self.assertEqual(len(model.coefficients), len(ai_model.FEATURES))
        self.assertTrue(all(sigma > 0 for sigma in model.scale))
        self.assertIn("holdout", model.metadata)
        self.assertIn("eligible", model.metadata)

    def test_missing_artifact_disables_the_model_instead_of_guessing(self):
        missing = ROOT / "models" / "definitely-not-here.json"
        self.assertIsNone(ai_model.load(missing))
        report = ai_model.status(missing)
        self.assertFalse(report["active"])
        self.assertIn("no trained artifact", report["reason"])

    def test_corrupt_artifact_disables_the_model(self):
        broken = ROOT / "models" / "_broken_test_artifact.json"
        broken.parent.mkdir(parents=True, exist_ok=True)
        try:
            broken.write_text("{not json", encoding="utf-8")
            self.assertIsNone(ai_model.load(broken))
            self.assertFalse(ai_model.status(broken)["active"])
        finally:
            broken.unlink(missing_ok=True)

    def test_feature_mismatch_disables_the_model(self):
        """An artifact whose feature list drifted must never be served."""
        payload = {
            "artifact": "quant-of-rehan-ai-signal",
            "features": ["ret1", "ret5"],
            "truth_column": ai_model.TRUTH_LABEL,
            "standardization": {"mean": [0.0, 0.0], "scale": [1.0, 1.0]},
            "coefficients": [1.0, 1.0],
            "intercept": 0.0,
            "metadata": {"eligible": True},
        }
        import json

        drifted = ROOT / "models" / "_drifted_test_artifact.json"
        drifted.parent.mkdir(parents=True, exist_ok=True)
        try:
            drifted.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(ai_model.load(drifted))
            report = ai_model.status(drifted)
            self.assertFalse(report["active"])
            self.assertIn("feature list does not match", report["reason"])
        finally:
            drifted.unlink(missing_ok=True)


class InferenceTest(unittest.TestCase):
    def make_model(self, weights: dict[str, float] | None = None,
                   eligible: bool = True) -> ai_model.Model:
        weights = weights or {}
        return ai_model.Model(
            features=ai_model.FEATURES,
            label=ai_model.TRUTH_LABEL,
            mean=[0.0] * len(ai_model.FEATURES),
            scale=[1.0] * len(ai_model.FEATURES),
            coefficients=[weights.get(name, 0.0) for name in ai_model.FEATURES],
            intercept=0.0,
            metadata={"eligible": eligible, "holdout": {"auc": 0.58},
                      "max_imputed_features": ai_model.MAX_IMPUTED_FEATURES},
        )

    def test_probability_is_monotone_in_its_feature(self):
        model = self.make_model({"ret5": 1.0})
        low = model.predict_proba({**{n: 0.0 for n in ai_model.FEATURES},
                                  "ret5": -1.0})
        high = model.predict_proba({**{n: 0.0 for n in ai_model.FEATURES},
                                   "ret5": 1.0})
        self.assertLess(low, high)
        self.assertAlmostEqual(low, 1 - high, places=6)

    def test_too_many_missing_inputs_refuses_to_answer(self):
        model = self.make_model()
        features = {name: 0.0 for name in ai_model.FEATURES}
        for name in list(ai_model.FEATURES)[: ai_model.MAX_IMPUTED_FEATURES + 1]:
            features[name] = None
        with self.assertRaises(ValueError):
            model.predict_proba(features)

    def test_percentile_ranks_inside_the_cross_section(self):
        distribution = {"AAA": 0.1, "BBB": 0.2, "CCC": 0.3}
        self.assertEqual(ai_model.percentile_of(distribution, "AAA"), 0.0)
        self.assertEqual(ai_model.percentile_of(distribution, "CCC"), 1.0)
        self.assertIsNone(ai_model.percentile_of(distribution, "ZZZ"))

    def test_live_probabilities_needs_a_model(self):
        self.assertIsNone(
            ai_model.live_probabilities(model_path=ROOT / "models" / "nope.json"))


class RoutingTest(unittest.TestCase):
    def test_gate_is_inactive_without_an_active_model(self):
        passed, reason = ai_model.gate(0.01, 0.01)
        self.assertTrue(passed)
        self.assertEqual(reason, "AI veto inactive")
        passed, reason = ai_model.gate(None, None)
        self.assertTrue(passed)

    def test_tie_break_only_acts_inside_the_band(self):
        rows = [
            {"symbol": "AAA", "score": 60.0, "ai_percentile": 0.10},
            {"symbol": "BBB", "score": 59.0, "ai_percentile": 0.90},
        ]
        index, note = ai_model.tie_break_winner(rows)
        self.assertEqual(index, 1)
        self.assertIn("promoted BBB", note)

        wide = [
            {"symbol": "AAA", "score": 70.0, "ai_percentile": 0.10},
            {"symbol": "BBB", "score": 50.0, "ai_percentile": 0.90},
        ]
        index, note = ai_model.tie_break_winner(wide)
        self.assertEqual(index, 0)
        self.assertIn("outside", note)

    def test_prior_never_invents_a_candidate(self):
        """No legal flip, no candidate: the momentum prior and its
        annotation can never conjure a row. A falling session has no
        upward flip at all, so the sole strategy and the prior agree on
        an empty roster (owner order 2026-10-30, Kalman sole strategy).
        """
        falling = one_session(
            datetime(2026, 10, 8, 10, 0, tzinfo=KARACHI),
            [100 - index * 0.05 for index in range(40)])
        plain = scanner.rank_candidates(falling)
        annotated = scanner.rank_candidates(falling, {"AAA": 0.9})
        self.assertEqual(plain, [])
        self.assertEqual(annotated, [])

    def test_annotation_adds_nothing_the_flip_rules_do_not_allow(self):
        """An attached prior annotates; it never rewrites the roster.

        On a session whose flip is strategy-legal, ranking with and
        without the momentum prior must return the identical rows: the
        prior's weight moves no name past a gate and adds no column of
        its own left behind by the flip rules (under the owner's fixed
        +2%/-1% TP/SL law the linear climb's own fresh flip is legal, so
        both modes carry the same candidate).
        """
        session = one_session(
            datetime(2026, 10, 8, 10, 0, tzinfo=KARACHI),
            [100 + index * 0.05 for index in range(40)])
        plain = scanner.rank_candidates(session)
        annotated = scanner.rank_candidates(session, {"AAA": 0.9})
        self.assertEqual(plain, annotated)
        self.assertTrue(plain, "the fixture's fresh flip stayed legal")
        for row in annotated:
            self.assertFalse(
                "ai_probability" in row or "ai_percentile" in row,
                "the prior leaked its own annotation into the ranked rows")

    def test_attach_marks_unscored_symbols_as_unavailable(self):
        rows = [{"symbol": "AAA"}, {"symbol": "BBB"}]
        ai_model.attach({"AAA": 0.4}, rows)
        self.assertEqual(rows[0]["ai_probability"], 0.4)
        self.assertIsNone(rows[1]["ai_probability"])
        self.assertIsNone(rows[1]["ai_percentile"])


if __name__ == "__main__":
    unittest.main()
