"""Tests for the SO-4 local-only guard, the SO-12 cloud-only guard, and the
governance checks behind both.

Owner order 2026-10-11: backtesting runs only on the owner's PC, and the
GitHub Actions minutes are reserved for the market-hours scans. Owner order
2026-10-14: the 4-minute scanner always runs on GitHub Actions minutes and on
the Cloudflare relay, and the owner's PC is used only for a backtest he asks
for. These tests hold both guards, hold every declared entry point to calling
its own, and prove the governance checker catches one that stops.
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
    CLOUD_ONLY_DAEMONS,
    LOCAL_ONLY_SCRIPTS,
    OWNER_REQUEST_ENV,
    guard_local_only,
    guard_owner_requested,
    owner_requested_local_run,
    running_in_github_actions,
)

#: A local shell: no Actions marker, and the owner has not asked for anything.
LOCAL_SHELL = {
    k: v for k, v in os.environ.items()
    if k not in ("GITHUB_ACTIONS", OWNER_REQUEST_ENV)
}


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


class TestCloudOnlyGuard(unittest.TestCase):
    """SO-12: recurring work never starts on the owner's PC by itself."""

    def test_a_local_start_is_refused_by_default(self):
        with mock.patch.dict(os.environ, LOCAL_SHELL, clear=True):
            with self.assertRaises(SystemExit) as caught:
                guard_owner_requested("scripts/kmiall_tick.py")
        reason = str(caught.exception)
        self.assertIn("SO-12", reason)
        self.assertIn("the 4-minute KMIALL scanner tick", reason)
        self.assertIn("GitHub Actions minutes", reason)
        self.assertIn("Cloudflare relay", reason)
        self.assertIn(OWNER_REQUEST_ENV, reason)

    def test_the_cloud_is_where_the_work_belongs(self):
        env = dict(LOCAL_SHELL, GITHUB_ACTIONS="true")
        with mock.patch.dict(os.environ, env, clear=True):
            guard_owner_requested("scripts/kmiall_tick.py")   # must not raise

    def test_the_owners_own_request_opens_that_one_run(self):
        env = dict(LOCAL_SHELL,
                   **{OWNER_REQUEST_ENV: "scripts/kmiall_tick.py"})
        with mock.patch.dict(os.environ, env, clear=True):
            guard_owner_requested("scripts/kmiall_tick.py")   # must not raise

    def test_a_request_for_one_run_does_not_open_another(self):
        env = dict(LOCAL_SHELL, **{OWNER_REQUEST_ENV: "scripts/scan_loop.py"})
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(SystemExit):
                guard_owner_requested("scripts/kmiall_tick.py")

    def test_a_plain_yes_covers_a_declared_run(self):
        for value in ("1", "true", "YES", "on"):
            env = dict(LOCAL_SHELL, **{OWNER_REQUEST_ENV: value})
            with mock.patch.dict(os.environ, env, clear=True):
                guard_owner_requested("scripts/kmiall_tick.py")

    def test_an_undeclared_run_still_refuses(self):
        with mock.patch.dict(os.environ, LOCAL_SHELL, clear=True):
            with self.assertRaises(SystemExit) as caught:
                guard_owner_requested("scripts/not_declared.py")
        self.assertIn("this recurring run", str(caught.exception))

    def test_paths_are_normalised_across_shells(self):
        for value in (r"scripts\kmiall_tick.py", "./scripts/kmiall_tick.py",
                      "scripts/kmiall_tick.py"):
            with mock.patch.dict(os.environ,
                                 {OWNER_REQUEST_ENV: value}, clear=True):
                self.assertTrue(
                    owner_requested_local_run("scripts/kmiall_tick.py"), value
                )

    def test_an_empty_request_is_not_a_request(self):
        for value in ("", "  "):
            with mock.patch.dict(os.environ,
                                 {OWNER_REQUEST_ENV: value}, clear=True):
                self.assertFalse(owner_requested_local_run("scripts/scan_loop.py"))


class TestCloudOnlyEntryPoints(unittest.TestCase):
    """Every declared recurring entry point carries its own guard, in the
    place where the process becomes real rather than behind a flag."""

    @staticmethod
    def _first_statement_call(path: Path, function: str) -> str:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        node = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == function)
        body = node.body
        if (isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        return body[0].value.func.id

    def test_every_declared_daemon_exists_and_names_its_own_path(self):
        for rel, task in sorted(CLOUD_ONLY_DAEMONS.items()):
            with self.subTest(entry_point=rel):
                p = ROOT / rel
                self.assertTrue(p.is_file(), f"{rel} ({task}) is missing")
                text = p.read_text(encoding="utf-8", errors="replace")
                self.assertIn(f'guard_owner_requested("{rel}")', text)
                ast.parse(text)

    def test_the_installers_refuse_as_their_first_act(self):
        cases = (
            ("scripts/install_kmiall_tick.py", "install"),
            ("scripts/install_scheduler.py", "main"),
        )
        for rel, function in cases:
            with self.subTest(entry_point=rel):
                self.assertEqual(
                    self._first_statement_call(ROOT / rel, function),
                    "guard_owner_requested",
                )

    def test_the_guards_sit_before_the_work_they_gate(self):
        bootstraps = (
            ("scripts/kmiall_tick.py", "raise SystemExit(main())"),
            ("scripts/scan_loop.py", "raise SystemExit(main())"),
            ("src/notify/schedule_runner.py", "run_forever()"),
        )
        for rel, call in bootstraps:
            with self.subTest(entry_point=rel):
                text = (ROOT / rel).read_text(encoding="utf-8",
                                              errors="replace")
                guard_at = text.index("guard_owner_requested(")
                self.assertLess(guard_at, text.index(call),
                                "the guard must come before the work")

    def test_no_workflow_registers_local_autostart(self):
        import check_governance as cg
        workflows = ROOT / ".github" / "workflows"
        for wf in sorted(workflows.glob("*.yml")):
            text = wf.read_text(encoding="utf-8", errors="replace")
            for needle, why in cg.LOCAL_AUTOSTART_PATTERNS:
                with self.subTest(workflow=wf.name, needle=needle):
                    self.assertNotIn(needle, text, f"{wf.name} {why}")

    def test_the_shipped_repository_passes(self):
        import check_governance as cg
        errors: list = []
        cg.check_cloud_only(errors)
        self.assertEqual(errors, [])


class TestGovernanceCatchesARemovedCloudGuard(unittest.TestCase):
    """The checker must object when a recurring entry point loses its guard."""

    def test_an_unguarded_entry_point_is_reported(self):
        import check_governance as cg
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "local_tick.py"
            script.write_text("def main():\n    return 0\n", encoding="utf-8")
            errors: list = []
            with mock.patch.object(cg, "ROOT", script.parent), \
                 mock.patch.object(cg, "CLOUD_ONLY_DAEMONS",
                                   {script.name: "a local tick"}):
                cg.check_cloud_only(errors)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("[SO-12]", errors[0])
        self.assertIn("guard_owner_requested", errors[0])
        self.assertIn("hammer", errors[0])

    def test_a_declared_but_missing_entry_point_is_reported(self):
        import check_governance as cg
        errors: list = []
        with mock.patch.object(cg, "CLOUD_ONLY_DAEMONS",
                               {"scripts/gone_runner.py": "a deleted runner"}):
            cg.check_cloud_only(errors)
        self.assertTrue(any("does not exist" in e for e in errors), errors)

    def test_a_workflow_registering_a_local_task_is_reported(self):
        import check_governance as cg
        with tempfile.TemporaryDirectory() as tmp:
            wf = Path(tmp) / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "tick.yml").write_text(
                "jobs:\n  t:\n    steps:\n      - run: schtasks /create /tn q\n",
                encoding="utf-8")
            errors: list = []
            with mock.patch.object(cg, "ROOT", Path(tmp)), \
                 mock.patch.object(cg, "CLOUD_ONLY_DAEMONS", {}):
                cg.check_cloud_only(errors)
        self.assertTrue(any("tick.yml" in e and "[SO-12]" in e
                            for e in errors), errors)


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
