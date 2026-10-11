"""SO-4 enforcement: backtests and history research are local work only.

Owner order 2026-10-11: "you will only do the backtesting on my local PC,
github actions minutes are strictly for market hours for the usual market
scans every 4 minutes."

SO-4 has always said that backtesting, walk-forward validation and Monte
Carlo runs never execute in CI, but that rule lived only in prose and in
docstrings, so nothing refused a run. This module makes it enforceable:
every declared entry point calls guard_local_only as the first statement of
its main(), and scripts/check_governance.py fails a pull request in which one
of them forgets to, or in which a workflow learns to invoke one.

Why the guard sits in the command line entry points rather than inside
src/backtest/*: the test suite runs in GitHub Actions and exercises the
engine on tiny fixtures, which is a unit test, not a backtest. What must
never happen is a real run (the 5-year panel, a parameter sweep, a model
fit) spending cloud minutes that belong to the market-hours scans.
"""

from __future__ import annotations

import os

# Scripts that may run on the owner's PC only, relative to the repo root.
# check_governance.py verifies that each one calls guard_local_only and that
# no workflow file invokes one.
LOCAL_ONLY_SCRIPTS = {
    "scripts/smoke_backtest.py": "the end-to-end backtest smoke run",
    "scripts/backtest_optimize.py": "the staged parameter search",
    "scripts/walk_forward_check.py": "the walk-forward validation",
    "scripts/stop_tp_grid.py": "the stop and target grid sweep",
    "scripts/build_trade_matrix.py": "the trade matrix build",
    "scripts/entry_metrics.py": "the entry edge study",
    "scripts/event_study.py": "the event study",
    "scripts/condition_scan.py": "the condition scan",
    "scripts/train_signal_model.py": "the AI prior fit",
    "scripts/research_phase1.py": "phase 1 research",
    "scripts/research_phase2a.py": "phase 2a research",
    "scripts/research_phase2b.py": "phase 2b research",
}

REFUSAL = (
    "REFUSED (SO-4): {task} is local-only work. GitHub Actions minutes are "
    "reserved for the market-hours scans, so it never runs here. Run it on "
    "the owner's PC instead: python {script}"
)


def running_in_github_actions() -> bool:
    """True when this process is a GitHub Actions job.

    GITHUB_ACTIONS is 'true' in every Actions job and unset on the owner's
    PC. A false negative would spend cloud minutes while a false positive
    only stops a run the owner started in the wrong place, so anything that
    is not clearly a no counts as a yes.
    """
    value = os.environ.get("GITHUB_ACTIONS", "").strip().lower()
    return value not in ("", "0", "false", "no")


def guard_local_only(script: str) -> None:
    """Stop a local-only script that is running in CI.

    Call as the first statement of main(). SystemExit prints the reason and
    no traceback, because this line travels into the owner's Telegram alert
    as the reason for a failed job.
    """
    if not running_in_github_actions():
        return
    task = LOCAL_ONLY_SCRIPTS.get(script, "this backtest")
    raise SystemExit(REFUSAL.format(task=task, script=script))
