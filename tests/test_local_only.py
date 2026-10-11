"""Tests for the SO-4 local-only guard and its governance check.

Owner order 2026-10-11: backtesting runs only on the owner's PC, and the
GitHub Actions minutes are reserved for the market-hours scans. These tests
hold the guard itself, hold every declared entry point to calling it, and
prove the governance checker catches a script that stops calling it.
"""

from __future__ import annotations

import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.ci.local_only import (  # noqa: E402
    LOCAL_ONLY_SCRIPTS,
    guard_local_only,
    running_in_github_actions,
)


class TestCiDetection(unittest.TestCase):
    def test_actions_is_detected(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            self.assertTrue(running_in_github_actions())

    def test_the_pc_is_not_actions(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(running_in_github_actions())

    def test_an_explicit_no_is_respected(self):
        for value in ("", "false", "False", "0", "no", "  "):
            with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": value}):
                self.assertFalse(running_in_github_actions(), msg=value)

    def test_anything_else_counts_as_actions(self):
        # A false negative would spend cloud minutes, so refuse when unsure.
        for value in ("1", "TRUE", "yes", "on"):
            with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": value}):
                self.assertTrue(running_in_github_actions(), msg=value)


class TestGuard(unittest.TestCase):
    def test_local_run_passes_through(self):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        with mock.patch.dict(os.environ, env, clear=True):
            guard_local_only("scripts/smoke_backtest.py")   # must not raise

    def test_a_ci_run_is_refused(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(SystemExit) as caught:
                guard_local_only("scripts/smoke_backtest.py")
        reason = str(caught.exception)
        self.assertIn("SO-4", reason)
        self.assertIn("the end-to-end backtest smoke run", reason)
        self.assertIn("python scripts/smoke_backtest.py", reason)
        self.assertIn("never runs here", reason)

    def test_an_undeclared_script_still_refuses(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaises(SystemExit) as caught:
                guard_local_only("scripts/not_declared.py")
        self.assertIn("local-only", str(caught.exception))


class TestDeclaredEntryPoints(unittest.TestCase):
    def test_every_declared_script_exists_and_carries_the_guard(self):
        for rel, task in sorted(LOCAL_ONLY_SCRIPTS.items()):
            with self.subTest(script=rel):
                p = ROOT / rel
                self.assertTrue(p.is_file(), f"{rel} ({task}) is missing")
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertIn(f'guard_local_only("{rel}")', text)

    def test_every_declared_script_parses(self):
        for rel in sorted(LOCAL_ONLY_SCRIPTS):
            with self.subTest(script=rel):
                ast.parse((ROOT / rel).read_text(encoding="utf-8",
                                                  errors="replace"))

    def test_the_guard_is_the_first_statement_of_main(self):
        """A guard anywhere else could be reached after the expensive work."""
        for rel in sorted(LOCAL_ONLY_SCRIPTS):
            with self.subTest(script=rel):
                text = (ROOT / rel).read_text(encoding="utf-8",
                                              errors="replace")
                tree = ast.parse(text)
                main = next(n for n in tree.body
                            if isinstance(n, ast.FunctionDef) and n.name == "main")
                body = main.body
                if isinstance(body[0], ast.Expr) and isinstance(
                        body[0].value, ast.Constant
                ) and isinstance(body[0].value.value, str):
                    body = body[1:]
                call = body[0]
                self.assertIsInstance(call, ast.Expr)
                self.assertIsInstance(call.value, ast.Call)
                self.assertEqual(call.value.func.id, "guard_local_only")
                self.assertEqual(call.value.args[0].value, rel)

    def test_no_workflow_runs_a_local_only_script(self):
        workflows = ROOT / ".github" / "workflows"
        for wf in sorted(workflows.glob("*.yml")):
            text = wf.read_text(encoding="utf-8", errors="replace")
            for rel in LOCAL_ONLY_SCRIPTS:
                with self.subTest(workflow=wf.name, script=rel):
                    self.assertNotIn(Path(rel).name, text)


class TestGovernanceCatchesARemovedGuard(unittest.TestCase):
    """The checker must object when the guard disappears from a script."""

    def test_a_script_without_the_guard_is_reported(self):
        import check_governance as cg
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "unguarded_backtest.py"
            script.write_text("def main():\n    return 0\n", encoding="utf-8")
            errors: list = []
            with mock.patch.object(cg, "ROOT", script.parent), \
                 mock.patch.object(cg, "LOCAL_ONLY_SCRIPTS",
                                   {script.name: "an unguarded backtest"}):
                cg.check_local_only(errors)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("[SO-4]", errors[0])
        self.assertIn("guard_local_only", errors[0])
        self.assertIn("market-hours scan budget", errors[0])

    def test_a_declared_but_missing_script_is_reported(self):
        import check_governance as cg
        errors: list = []
        with mock.patch.object(cg, "LOCAL_ONLY_SCRIPTS",
                               {"scripts/gone_backtest.py": "a deleted backtest"}):
            cg.check_local_only(errors)
        self.assertTrue(any("does not exist" in e for e in errors), errors)

    def test_a_workflow_invoking_a_backtest_is_reported(self):
        import check_governance as cg
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "nightly.yml").write_text(
                "jobs:\n  b:\n    steps:\n      - run: python scripts/smoke_backtest.py\n",
                encoding="utf-8")
            errors: list = []
            with mock.patch.object(cg, "ROOT", Path(tmp)), \
                 mock.patch.object(cg, "LOCAL_ONLY_SCRIPTS",
                                   {"scripts/smoke_backtest.py": "the smoke run"}):
                cg.check_local_only(errors)
        self.assertTrue(any("nightly.yml" in e and "[SO-4]" in e for e in errors),
                        errors)

    def test_the_shipped_repository_passes(self):
        import check_governance as cg
        errors: list = []
        cg.check_local_only(errors)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
