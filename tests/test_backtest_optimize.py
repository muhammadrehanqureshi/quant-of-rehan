"""Tests for the local staged backtest optimiser.

Everything here runs on synthetic bars and a temp CSV: no network, no reliance
on the shipped dataset. The centrepiece is
``TestEvaluatorMatchesEngine``, which proves the vectorised evaluator agrees
with the authoritative ``engine.run_backtest`` trade for trade.
"""

from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.backtest.daily_strategy import (ScannerParams, build_path_matrix,  # noqa: E402
                                         build_signals)
from src.backtest.dataset import load_eod_history  # noqa: E402
from src.backtest.optimize import (ExitLaw, build_oos_plan, cross_check,  # noqa: E402
                                   evaluate_paths, run_staged_search)

PERMISSIVE = ScannerParams(
    weights=dict(config.SCORE_WEIGHTS), min_score=0.0, min_relvol=0.0,
    min_traded_value=0.0, min_price=0.0, max_extension=1.0)

#: Module roots that would mean a cloud service, a remote API or a spawned
#: process. SO-4 forbids all of them on the backtest path.
FORBIDDEN_IMPORTS = {
    "requests", "urllib", "urllib3", "httpx", "http", "aiohttp", "socket",
    "ssl", "ftplib", "smtplib", "telnetlib", "xmlrpc", "asyncio",
    "boto3", "botocore", "google", "azure", "paramiko", "docker",
    "subprocess", "multiprocessing", "dask", "ray", "pyspark",
}


def synth(n_symbols: int = 4, n_sessions: int = 150, seed: int = 7) -> pd.DataFrame:
    """A small deterministic multi-symbol OHLCV frame with real structure."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_sessions)
    rows: list[dict] = []
    for index in range(n_symbols):
        symbol = f"SYM{index}"
        price = 50.0 + 10.0 * index
        for step, day in enumerate(dates):
            drift = 0.004 if (step % 25) < 6 else -0.001
            ret = drift + rng.normal(0.0, 0.018)
            open_ = price
            close = max(1.0, price * (1.0 + ret))
            high = max(open_, close) * (1.0 + abs(rng.normal(0.0, 0.003)))
            low = min(open_, close) * (1.0 - abs(rng.normal(0.0, 0.003)))
            base_volume = 500_000
            volume = float(base_volume * (3.0 if (step % 25) in (4, 5) else 1.0)
                           * float(np.exp(rng.normal(0.0, 0.25))))
            rows.append({"symbol": symbol, "date": day, "open": open_,
                         "high": high, "low": low, "close": close,
                         "volume": volume})
            price = close
    return pd.DataFrame(rows)


def single_symbol(rows: list[tuple], symbol: str = "TEST") -> pd.DataFrame:
    """rows: (date, open, high, low, close, volume)."""
    frame = pd.DataFrame(rows, columns=["date", "open", "high", "low",
                                        "close", "volume"])
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = symbol
    return frame


class TestExitLaw(unittest.TestCase):
    def test_rejects_nonpositive_and_zero_hold(self) -> None:
        for bad in ((0.0, 0.01, 3), (0.02, 0.0, 3), (0.02, 0.01, 0)):
            with self.assertRaises(ValueError):
                ExitLaw(*bad)

    def test_reward_risk_is_tp_over_sl(self) -> None:
        self.assertAlmostEqual(ExitLaw(0.02, 0.01, 3).reward_risk, 2.0)
        self.assertAlmostEqual(ExitLaw(0.01, 0.03, 10).reward_risk, 1.0 / 3.0)

    def test_break_even_matches_hand_arithmetic(self) -> None:
        from src.backtest.optimize import break_even_win_rate

        # costs = 2 x 22.4bps = 0.448%; CGT 15% bites only on a winning trade.
        # Owner law: net_win = (0.02-0.00448)*0.85, net_loss = 0.01+0.00448.
        self.assertAlmostEqual(break_even_win_rate(ExitLaw(0.02, 0.01, 3)),
                               0.01448 / (0.013192 + 0.01448), places=9)
        # The 90%-accuracy corner: a 0.5% target against an 8% stop.
        self.assertAlmostEqual(break_even_win_rate(ExitLaw(0.005, 0.08, 10)),
                               0.08448 / (0.000442 + 0.08448), places=9)

    def test_a_target_that_cannot_cover_costs_needs_certainty(self) -> None:
        from src.backtest.optimize import break_even_win_rate

        # A 0.1% target cannot pay a 0.448% round trip: no accuracy suffices.
        self.assertEqual(break_even_win_rate(ExitLaw(0.001, 0.01, 1)), 1.0)

    def test_a_high_accuracy_corner_is_far_from_break_even(self) -> None:
        """The counter-intuitive result the report must state plainly."""
        from src.backtest.optimize import break_even_win_rate

        owner = break_even_win_rate(ExitLaw(0.02, 0.01, 3))
        corner = break_even_win_rate(ExitLaw(0.005, 0.08, 10))
        self.assertLess(owner, 0.60)      # a modest accuracy suffices
        self.assertGreater(corner, 0.99)  # the 90% corner needs ~99.5%

    def test_missing_horizon_columns_raise(self) -> None:
        paths = pd.DataFrame({"entry": [100.0], "o1": [100.0], "h1": [101.0],
                              "l1": [99.0], "c1": [100.0]})
        with self.assertRaises(ValueError):
            evaluate_paths(paths, ExitLaw(0.02, 0.01, 3))


class TestPathMatrix(unittest.TestCase):
    def test_entry_is_the_next_bar_open(self) -> None:
        frame = single_symbol([
            ("2024-01-01", 10.0, 10.5, 9.5, 10.2, 1000),
            ("2024-01-02", 11.0, 11.5, 10.5, 11.2, 1000),
            ("2024-01-03", 12.0, 12.5, 11.5, 12.2, 1000),
        ])
        scored, mask = build_signals(frame, PERMISSIVE)
        # Force a signal on the first usable bar only.
        forced = pd.Series(False, index=scored.index)
        forced.iloc[1] = True
        paths, skipped = build_path_matrix(scored, forced, horizon=1)
        self.assertEqual(skipped, 0)
        self.assertEqual(len(paths), 1)
        self.assertAlmostEqual(paths.at[0, "entry"], 12.0)  # next bar's open

    def test_signal_on_last_bar_is_skipped_not_booked(self) -> None:
        frame = single_symbol([
            ("2024-01-01", 10.0, 10.5, 9.5, 10.2, 1000),
            ("2024-01-02", 11.0, 11.5, 10.5, 11.2, 1000),
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series(False, index=scored.index)
        forced.iloc[-1] = True
        paths, skipped = build_path_matrix(scored, forced, horizon=3)
        self.assertTrue(paths.empty)
        self.assertEqual(skipped, 1)

    def test_missing_forward_bar_stays_nan(self) -> None:
        frame = single_symbol([
            ("2024-01-01", 10.0, 10.5, 9.5, 10.2, 1000),
            ("2024-01-02", 11.0, 11.5, 10.5, 11.2, 1000),
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series(False, index=scored.index)
        forced.iloc[0] = True
        paths, _ = build_path_matrix(scored, forced, horizon=3)
        self.assertTrue(np.isfinite(paths.at[0, "o1"]))
        self.assertTrue(np.isnan(paths.at[0, "o3"]))

    def test_ordinals_exist_so_equity_can_be_chronological(self) -> None:
        scored, mask = build_signals(synth(), PERMISSIVE)
        paths, _ = build_path_matrix(scored, mask, horizon=3)
        self.assertIn("signal_ord", paths.columns)
        for step in (1, 2, 3):
            self.assertIn(f"ord{step}", paths.columns)
        self.assertTrue((paths["ord1"] > paths["signal_ord"]).all())


class TestExitSemantics(unittest.TestCase):
    """The evaluator must be conservative in the same places the engine is."""

    def test_stop_wins_when_one_bar_touches_both(self) -> None:
        # Entry 100; bar 1 spans sl(99) and tp(102) together -> SL.
        frame = single_symbol([
            ("2024-01-01", 99.0, 99.5, 98.5, 99.5, 1000),
            ("2024-01-02", 100.0, 102.5, 98.5, 101.0, 1000),
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series([True, False], index=scored.index)
        paths, _ = build_path_matrix(scored, forced, horizon=1)
        metrics = evaluate_paths(paths, ExitLaw(0.02, 0.01, 1))
        self.assertEqual(metrics.n_trades, 1)
        self.assertEqual(metrics.sl_rate, 1.0)

    def test_gap_through_the_stop_fills_at_the_open(self) -> None:
        # Signal on D0, entry at D1's open of 100, then D2 gaps below the 99
        # stop: the fill must be D2's open (96), not the stop price.
        frame = single_symbol([
            ("2024-01-01", 99.0, 99.5, 98.5, 99.5, 1000),
            ("2024-01-02", 100.0, 100.5, 99.5, 100.0, 1000),   # entry at 100
            ("2024-01-03", 96.0, 96.5, 95.0, 95.5, 1000),     # gap through stop
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series([True, False, False], index=scored.index)
        paths, _ = build_path_matrix(scored, forced, horizon=2)
        metrics = evaluate_paths(paths, ExitLaw(0.02, 0.01, 2))
        self.assertEqual(metrics.sl_rate, 1.0)
        # gross = 96/100 - 1 = -4%: far worse than the -1% stop.
        self.assertLess(metrics.expectancy_net, -0.03)

    def test_target_fills_at_exactly_tp_never_better(self) -> None:
        # Signal on D0, entry at D1's open of 100, then D2 gaps to 110, way
        # through tp=102: the fill must still be exactly 102.
        frame = single_symbol([
            ("2024-01-01", 99.0, 99.5, 98.5, 99.5, 1000),
            ("2024-01-02", 100.0, 100.5, 99.5, 100.0, 1000),   # entry at 100
            ("2024-01-03", 108.0, 110.0, 107.0, 109.0, 1000),  # gaps up
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series([True, False, False], index=scored.index)
        paths, _ = build_path_matrix(scored, forced, horizon=2)
        metrics = evaluate_paths(paths, ExitLaw(0.02, 0.01, 2))
        self.assertEqual(metrics.tp_rate, 1.0)
        self.assertGreater(metrics.expectancy_net, 0.0)
        self.assertLess(metrics.expectancy_net, 0.02)  # costs + CGT, never > tp


class TestEvaluatorMatchesEngine(unittest.TestCase):
    def test_cross_check_agrees_on_the_full_sample(self) -> None:
        frame = synth(n_symbols=5, n_sessions=160, seed=11)
        for law in (ExitLaw(0.02, 0.01, 3), ExitLaw(0.01, 0.03, 10),
                    ExitLaw(0.05, 0.02, 1), ExitLaw(0.015, 0.03, 5)):
            with self.subTest(law=law):
                result = cross_check(frame, PERMISSIVE, law, sample=10_000)
                self.assertGreater(result["compared"], 0)
                self.assertAlmostEqual(result["engine_win_rate"],
                                       result["fast_win_rate"])
                self.assertAlmostEqual(result["engine_expectancy"],
                                       result["fast_expectancy"])

    def test_cross_check_raises_rather_than_drifting(self) -> None:
        """A deliberately wrong horizon must not be silently tolerated."""
        frame = single_symbol([
            ("2024-01-01", 100.0, 100.5, 99.5, 100.0, 1000),
            ("2024-01-02", 100.0, 100.5, 99.5, 100.0, 1000),
            ("2024-01-03", 100.0, 100.5, 99.5, 100.0, 1000),
        ])
        scored, _ = build_signals(frame, PERMISSIVE)
        forced = pd.Series([True, False, False], index=scored.index)
        paths, _ = build_path_matrix(scored, forced, horizon=1)
        # horizon 1 => only o1/h1/l1/c1 exist, so max_hold=3 must refuse.
        with self.assertRaises(ValueError):
            evaluate_paths(paths, ExitLaw(0.02, 0.01, 3))


class TestCausality(unittest.TestCase):
    def test_truncating_the_future_does_not_change_past_signals(self) -> None:
        frame = synth(n_symbols=3, n_sessions=140, seed=3)
        cut = pd.Timestamp("2024-05-01")
        _, full_mask = build_signals(frame, PERMISSIVE)
        short = frame.loc[frame["date"] <= cut]
        _, short_mask = build_signals(short, PERMISSIVE)
        full = pd.Series(full_mask.to_numpy(), index=frame.index)
        past = frame["date"] <= cut
        expected = full[past].to_numpy()
        got = short_mask.to_numpy()
        self.assertEqual(len(expected), len(got))
        np.testing.assert_array_equal(expected, got)

    def test_perturbing_a_future_price_changes_nothing_earlier(self) -> None:
        frame = synth(n_symbols=2, n_sessions=120, seed=5)
        cut = pd.Timestamp("2024-04-01")
        _, base = build_signals(frame, PERMISSIVE)
        tampered = frame.copy()
        future = tampered["date"] > cut
        tampered.loc[future, "close"] = tampered.loc[future, "close"] * 1.10
        _, after = build_signals(tampered, PERMISSIVE)
        past = frame["date"] <= cut
        np.testing.assert_array_equal(base.to_numpy()[past], after.to_numpy()[past])


class TestIngestion(unittest.TestCase):
    def _write(self, rows: list[dict], universe: list[str]) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp())
        csv = tmp / "eod.csv"
        pd.DataFrame(rows).to_csv(csv, index=False)
        uni = tmp / "universe.json"
        uni.write_text(json.dumps([{"symbol": s} for s in universe]), encoding="utf-8")
        return csv, uni

    def test_every_defect_gets_its_own_counter(self) -> None:
        rows: list[dict] = []
        for day in pd.bdate_range("2024-01-01", periods=10):
            rows.append({"date": day.date().isoformat(), "symbol": "AAA",
                         "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
                         "volume": 1000})
            rows.append({"date": day.date().isoformat(), "symbol": "BBB",
                         "open": 20.0, "high": 20.5, "low": 19.5, "close": 20.2,
                         "volume": 1000})
        rows.append({"date": "2024-02-01", "symbol": "BBB", "open": 0.0,
                     "high": 0.0, "low": 0.0, "close": 20.2, "volume": 0})
        rows.append({"date": "2024-02-02", "symbol": "BBB", "open": 0.0,
                     "high": 21.0, "low": 20.0, "close": 20.5, "volume": 500})
        rows.append({"date": "2024-02-05", "symbol": "BBB", "open": 20.0,
                     "high": 21.0, "low": 20.0, "close": 20.5, "volume": ""})
        rows.append({"date": "not-a-date", "symbol": "BBB", "open": 20.0,
                     "high": 21.0, "low": 20.0, "close": 20.5, "volume": 500})
        rows.append({"date": "", "symbol": "AAA", "open": 10.0, "high": 11.0,
                     "low": 10.0, "close": 10.5, "volume": 500})
        rows.append({"date": "2024-02-06", "symbol": "BBB", "open": 20.0,
                     "high": 20.1, "low": 20.2, "close": 20.5, "volume": 500})
        rows.append({"date": "2024-01-01", "symbol": "CCC", "open": 5.0,
                     "high": 5.5, "low": 4.5, "close": 5.2, "volume": 500})

        csv, uni = self._write(rows, ["AAA", "BBB"])
        frame, report = load_eod_history(csv, universe_path=uni, min_bars=3)

        self.assertGreaterEqual(report.dropped_untraded_bar, 1)
        self.assertGreaterEqual(report.dropped_nonpositive_price, 1)
        self.assertGreaterEqual(report.dropped_null_value, 1)
        self.assertGreaterEqual(report.dropped_bad_date, 1)
        self.assertGreaterEqual(report.dropped_missing_date, 1)
        self.assertGreaterEqual(report.dropped_outside_universe, 1)  # CCC
        self.assertGreaterEqual(report.repaired_ragged_envelope, 1)
        self.assertEqual(report.rows_in, len(rows))
        self.assertEqual(report.rows_out, len(frame))
        self.assertNotIn("CCC", set(frame["symbol"]))

    def test_ragged_bar_is_widened_not_dropped(self) -> None:
        rows = [{"date": f"2024-01-{day:02d}", "symbol": "AAA", "open": 10.0,
                 "high": 9.8, "low": 10.3, "close": 10.5, "volume": 1000}
                for day in range(1, 6)]
        csv, uni = self._write(rows, ["AAA"])
        frame, report = load_eod_history(csv, universe_path=uni, min_bars=3)
        self.assertEqual(report.repaired_ragged_envelope, 5)
        self.assertEqual(len(frame), 5)  # repaired, not discarded
        self.assertTrue((frame["high"] >= frame["close"]).all())
        self.assertTrue((frame["low"] <= frame["close"]).all())

    def test_duplicate_rows_collapse(self) -> None:
        rows = [{"date": f"2024-01-{day:02d}", "symbol": "AAA", "open": 10.0,
                 "high": 10.5, "low": 9.5, "close": 10.2, "volume": 1000}
                for day in range(1, 6)]
        rows.append(dict(rows[0]))
        csv, uni = self._write(rows, ["AAA"])
        frame, report = load_eod_history(csv, universe_path=uni, min_bars=3)
        self.assertEqual(report.dropped_duplicate, 1)
        self.assertEqual(len(frame), 5)

    def test_missing_file_and_missing_columns_raise(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_eod_history("does/not/exist.csv", universe_path=None)
        tmp = Path(tempfile.mkdtemp()) / "bad.csv"
        pd.DataFrame([{"date": "2024-01-01", "symbol": "AAA"}]).to_csv(tmp, index=False)
        with self.assertRaises(ValueError):
            load_eod_history(tmp, universe_path=None)

    def test_empty_dataset_returns_an_empty_report(self) -> None:
        tmp = Path(tempfile.mkdtemp()) / "empty.csv"
        pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close",
                              "volume"]).to_csv(tmp, index=False)
        frame, report = load_eod_history(tmp, universe_path=None)
        self.assertTrue(frame.empty)
        self.assertEqual(report.rows_in, 0)
        self.assertEqual(report.retention, 1.0)


class TestStagedReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frame = synth(n_symbols=4, n_sessions=180, seed=13)
        cls.report = run_staged_search(cls.frame, target=0.90, horizon=10)

    def test_target_is_carried_through(self) -> None:
        self.assertEqual(self.report.target, 0.90)

    def test_break_even_is_reported_per_candidate(self) -> None:
        for candidate in self.report.stage1 + self.report.stage2:
            self.assertIn("break_even_win_rate", candidate)
            self.assertGreater(candidate["break_even_win_rate"], 0.0)
            self.assertLessEqual(candidate["break_even_win_rate"], 1.0)

    def test_in_sample_always_present_with_the_required_keys(self) -> None:
        self.assertTrue(self.report.stage1)
        for candidate in self.report.stage1 + self.report.stage2:
            block = candidate["in_sample"]
            for key in ("n_trades", "win_rate", "expectancy_net", "tp_rate",
                        "sl_rate", "timeout_rate", "max_drawdown"):
                self.assertIn(key, block)

    def test_out_of_sample_is_reported_beside_in_sample(self) -> None:
        plan = build_oos_plan(self.frame)
        self.assertTrue(plan["available"])
        self.assertTrue(plan["folds"])
        for candidate in self.report.stage1 + self.report.stage2:
            self.assertIsNotNone(candidate["out_of_sample"])
            self.assertIn("win_rate", candidate["out_of_sample"])
            self.assertIn("overfit_gap", candidate)
            self.assertIsNotNone(candidate["overfit_gap"])

    def test_walk_forward_folds_never_overlap(self) -> None:
        plan = build_oos_plan(self.frame)
        for fold in plan["folds"]:
            self.assertLess(max(fold["train"]), min(fold["val"]))
            self.assertLess(max(fold["val"]), min(fold["test"]))

    def test_stage2_rows_are_distinct(self) -> None:
        """Coincident parameter points must collapse, not fill the table."""
        signatures = [(c["in_sample"]["n_trades"], c["in_sample"]["win_rate"])
                      for c in self.report.stage2]
        self.assertEqual(len(signatures), len(set(signatures)))

    def test_coincident_scanner_points_are_deduplicated(self) -> None:
        from src.backtest.optimize import run_scanner_sweep

        frame = synth(n_symbols=3, n_sessions=120, seed=17)
        results = run_scanner_sweep(frame, ExitLaw(0.01, 0.03, 10), horizon=10,
                                    score_grid=(85.0,), relvol_grid=(0.0,),
                                    value_grid=(0.0, 5e6, 2e7))
        self.assertEqual(len(results), 15)  # 5 emphases x 3 value floors, no dedup
        outcomes = {(m.n_trades, round(m.win_rate, 6)) for _, _, m in results}
        self.assertLess(len(outcomes), len(results),
                        "expected at least two points to coincide on this grid")

    def test_expectancy_companion_and_verdict_are_present(self) -> None:
        self.assertIsNotNone(self.report.best_by_expectancy)
        self.assertIn("expectancy_net", self.report.best_by_expectancy["in_sample"])
        self.assertIn("in-sample", self.report.verdict.lower())
        self.assertIn("out-of-sample", self.report.verdict.lower())
        self.assertIn("break even", self.report.verdict.lower())

    def test_target_flag_matches_the_best_in_sample_win_rate(self) -> None:
        best = self.report.best_in_sample["in_sample"]["win_rate"]
        self.assertEqual(self.report.target_hit_in_sample, best >= 0.90)

    def test_report_is_json_serialisable(self) -> None:
        payload = json.dumps(self.report.as_dict(), default=str)
        self.assertGreater(len(payload), 100)
        round_trip = json.loads(json.dumps(self.report.as_dict(), default=str))
        self.assertEqual(round_trip["target"], 0.90)

    def test_empty_frame_refuses_to_optimise(self) -> None:
        with self.assertRaises(ValueError):
            run_staged_search(pd.DataFrame(), target=0.90)


class TestTypeSafety(unittest.TestCase):
    """The deliverable is required to be type-safe. No type checker is
    configured in this repo, so rather than claim a green mypy run that never
    happened, assert the property a checker would depend on: every public
    callable carries annotations, and every annotation RESOLVES (which is what
    catches typos and broken forward references).
    """

    def _modules(self):
        import importlib

        names = ["src.backtest.dataset", "src.backtest.daily_strategy",
                 "src.backtest.optimize"]
        return [importlib.import_module(name) for name in names]

    def test_every_public_callable_is_fully_annotated_and_resolves(self) -> None:
        import inspect
        import typing

        problems: list[str] = []
        for module in self._modules():
            for name, obj in vars(module).items():
                if name.startswith("_") or getattr(obj, "__module__", None) != module.__name__:
                    continue
                if inspect.isfunction(obj):
                    targets = [(name, obj)]
                elif inspect.isclass(obj):
                    targets = [(f"{name}.{attr}", member)
                               for attr, member in vars(obj).items()
                               if inspect.isfunction(member)
                               and not attr.startswith("_")]
                    # A dataclass must also have resolvable field types.
                    if hasattr(obj, "__dataclass_fields__"):
                        try:
                            typing.get_type_hints(obj)
                        except Exception as exc:  # noqa: BLE001
                            problems.append(f"{name}: field hints do not resolve: {exc}")
                    continue
                else:
                    continue

                for label, func in targets:
                    try:
                        hints = typing.get_type_hints(func)
                    except Exception as exc:  # noqa: BLE001
                        problems.append(f"{label}: hints do not resolve: {exc}")
                        continue
                    for param in inspect.signature(func).parameters.values():
                        if param.name in ("self", "cls") or param.name in hints:
                            continue
                        problems.append(f"{module.__name__}.{label}: unannotated "
                                        f"parameter {param.name!r}")
                    if "return" not in hints and func.__name__ != "__init__":
                        problems.append(f"{module.__name__}.{label}: unannotated return")
        self.assertEqual(problems, [], f"annotation gaps: {problems}")


class TestOfflineProof(unittest.TestCase):
    """SO-4: prove the backtest path cannot reach a network or a cloud service."""

    def _modules(self) -> list[Path]:
        paths = sorted((ROOT / "src" / "backtest").glob("*.py"))
        script = ROOT / "scripts" / "backtest_optimize.py"
        if script.is_file():
            paths.append(script)
        return paths

    def test_no_forbidden_imports_anywhere_on_the_path(self) -> None:
        offenders: list[str] = []
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    root = name.split(".")[0]
                    if root in FORBIDDEN_IMPORTS:
                        offenders.append(f"{path.name}:{node.lineno} imports {name}")
        self.assertEqual(offenders, [], f"network/cloud imports found: {offenders}")

    def test_only_expected_third_party_modules_are_used(self) -> None:
        allowed = {"numpy", "pandas"}
        for path in self._modules():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                third_party: set[str] = set()
                if isinstance(node, ast.Import):
                    third_party = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    third_party = {node.module.split(".")[0]}
                for name in third_party:
                    if name in {"src", "__future__", "dataclasses", "itertools",
                                "typing", "pathlib", "json", "math", "ast",
                                "tempfile", "unittest", "sys", "datetime",
                                "collections", "argparse"} | allowed:
                        continue
                    self.fail(f"{path.name} imports unexpected module {name!r}")


if __name__ == "__main__":
    unittest.main()
