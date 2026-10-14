"""SO-4 and SO-12 enforcement: one law per machine.

SO-4 (owner order 2026-10-11): backtests and history research are local work
only, and the GitHub Actions minutes are strictly for the market-hours scans.

SO-12 (owner order 2026-10-14): recurring work is cloud work. The 4-minute
scanner always runs on GitHub Actions minutes and on the Cloudflare relay, the
owner's PC is used only for a backtest he asks for, and neither this agent nor
the repository leaves a resident process on his machine. Where SO-4 keeps
cloud work off the PC, SO-12 keeps the PC out of cloud work: the two guards
below are mirror images, and a script belongs to exactly one of them.

Owner order 2026-10-14, verbatim: "the 4 minute scanner should always be
running on github action minutes and on cloudflare. you can only use my pc
when i tell you to backtest, apart from that you or quant of rehan will never
hammer my pc."

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


# --------------------------------------------------------------------- SO-12

#: Recurring or resident work belongs to the cloud, never to the owner's PC.
#: Each entry is a real entry point that a scheduler would otherwise run on
#: this machine, with the words the refusal prints. The mirror of
#: LOCAL_ONLY_SCRIPTS above: those scripts are refused in CI, these are refused
#: on the PC.
CLOUD_ONLY_DAEMONS = {
    "scripts/install_kmiall_tick.py":
        "the Windows task that fires the 4-minute KMIALL tick",
    "scripts/install_scheduler.py":
        "the logon task that keeps the notification runner resident",
    "scripts/kmiall_tick.py": "the 4-minute KMIALL scanner tick",
    "scripts/scan_loop.py": "the supervised always-on scan loop",
    "src/notify/schedule_runner.py":
        "the resident open and close notification runner",
}

#: The owner's own written instruction is the only thing that re-enables one
#: of these runs, and it is given per process: export the variable with the
#: script's repository path (or with 1 for any of them) in the shell that runs
#: it. Nothing sets it by accident, and it is never committed.
OWNER_REQUEST_ENV = "QOR_OWNER_REQUESTED_LOCAL_RUN"

REFUSAL_CLOUD_ONLY = (
    "REFUSED (SO-12): {task} is cloud-only work. The 4-minute scanner runs on "
    "GitHub Actions minutes and on the Cloudflare relay, and the owner's PC is "
    "used only for a backtest he asks for, so nothing recurring runs here. "
    "If the owner has asked for this exact local run, say so in the shell: "
    "{env}={script}"
)


def owner_requested_local_run(script: str | None = None) -> bool:
    """True when the owner asked for this exact local run in this shell.

    The variable holds either a script path or a plain yes. A path matches
    only its own script, so asking for one run can never unlock another; the
    separators are normalised because the same path arrives from a Windows
    shell, from Git Bash and from the repository's own tools.
    """
    value = os.environ.get(OWNER_REQUEST_ENV, "").strip()
    if not value:
        return False
    if value.lower() in ("1", "true", "yes", "on"):
        return True
    if not script:
        return False
    wanted = value.replace("\\", "/").strip("./").lower()
    return wanted == script.replace("\\", "/").strip("./").lower()


def guard_owner_requested(script: str) -> None:
    """Stop a cloud-only runner that is starting on the owner's PC (SO-12).

    Call it at the point where the process becomes real: the first statement
    of an installer's install(), and the bootstrap of a daemon's own entry
    point. GitHub Actions passes through untouched, because the cloud is
    exactly where this work is supposed to happen; a local run passes only on
    the owner's own instruction. SystemExit prints the reason and no
    traceback, like guard_local_only above.
    """
    if running_in_github_actions():
        return
    if owner_requested_local_run(script):
        return
    task = CLOUD_ONLY_DAEMONS.get(script, "this recurring run")
    raise SystemExit(
        REFUSAL_CLOUD_ONLY.format(task=task, script=script,
                                  env=OWNER_REQUEST_ENV)
    )
