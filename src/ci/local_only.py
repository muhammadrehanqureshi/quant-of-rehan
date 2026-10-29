"""SO-21, SO-4 and SO-12 enforcement: one law per machine.

SO-21 (owner order 2026-10-19, superseding SO-4): the owner's PC is not used
at all. Backtests, walk-forward runs and research now execute on GitHub
Actions minutes, which are free because the repository is public. The order
was given while the machine idled above 80 C with nothing but this editor
open, so the ceiling is not "a little": even two percent is too much.

Owner order 2026-10-19, verbatim: "Don't use my PC at all, keep the usage at
the very minimum, even 2% is too much. Since github action minutes are
unlimited now because my repo is public so now you will do backtesting also
on github action minutes, don't hammer my PC, my temps are literally at more
than 80 degree celcius and only freebuff is open right now and nothing else,
DON'T HAMMER OR USE MY PC AT ALL!!!"

The guard below is that sentence in code. It refuses every declared backtest
entry point anywhere that is not a GitHub Actions job, so a session cannot
decide on its own that a quick local run would be fine.

SO-4 (owner order 2026-10-11, superseded 2026-10-19): backtests and history
research were local work only, with the Actions minutes reserved for the
market-hours scans. That is history now: the public repository makes the
minutes free, and the owner's heat budget makes local compute unacceptable.

SO-12 (owner order 2026-10-14): recurring work is cloud work. The scanner
always runs on GitHub Actions minutes and on the Cloudflare relay, the owner's
PC is used only for a backtest he asks for, and neither this agent nor the
repository leaves a resident process on his machine. Where SO-4 keeps cloud
work off the PC, SO-12 keeps the PC out of cloud work: the two guards below
are mirror images, and a script belongs to exactly one of them.

SO-13 (owner order 2026-10-14, later amended 2026-10-19): the cloud cadence
is every second for each PSX band (30 seconds was the 2026-10-14 figure), run
by .github/workflows/intraday-session.yml through scripts/scan_loop.py, on the
free minutes of the public repository.
The 4-minute cadence still names the local tick's own triggers, and that tick
is cloud-only recurring work like everything else in this table.

Owner order 2026-10-14, verbatim: "the 4 minute scanner should always be
running on github action minutes and on cloudflare. you can only use my pc
when i tell you to backtest, apart from that you or quant of rehan will never
hammer my pc."

Owner order 2026-10-11: "you will only do the backtesting on my local PC,
github actions minutes are strictly for market hours for the usual market
scans every 4 minutes."

Before SO-21 the rule ran the other way and lived only in prose, so nothing
refused a run. This module makes it enforceable in the direction the owner
chose: every declared entry point calls guard_cloud_backtest as the first
statement of its main(), and scripts/check_governance.py fails a pull request
in which one of them forgets to, or in which a scheduled workflow invokes one.

Why the guard sits in the command line entry points rather than inside
src/backtest/*: the test suite runs in GitHub Actions and exercises the
engine on tiny fixtures, which is a unit test, not a backtest. What must
never happen is a real run (the 5-year panel, a parameter sweep, a model
fit) spending cloud minutes that belong to the market-hours scans.
"""

from __future__ import annotations

import os

# Backtest entry points, relative to the repo root. check_governance.py
# verifies that each one calls guard_cloud_backtest and that any workflow
# invoking one is manual dispatch, never a schedule. History: this table was
# named LOCAL_ONLY_SCRIPTS before SO-21, when the direction of the rule was
# the opposite.
BACKTEST_SCRIPTS = {
    "scripts/backtest_smc.py": "the causal ICT/SMC minute-bar replay",
    "scripts/smoke_backtest.py": "the end-to-end backtest smoke run",
    "scripts/backtest_optimize.py": "the staged parameter search",
    "scripts/walk_forward_check.py": "the walk-forward validation",
    "scripts/stop_tp_grid.py": "the stop and target grid sweep",
    "scripts/build_trade_matrix.py": "the trade matrix build",
    "scripts/entry_metrics.py": "the entry edge study",
    "scripts/event_study.py": "the event study",
    "scripts/condition_scan.py": "the condition scan",
    "scripts/hcar_postmortem.py": "the HCAR post-mortem and rejected-candidate outcome audit",
    "scripts/train_signal_model.py": "the AI prior fit",
    "scripts/research_phase1.py": "phase 1 research",
    "scripts/research_phase2a.py": "phase 2a research",
    "scripts/research_phase2b.py": "phase 2b research",
    "scripts/build_eod_history.py": "the 5-year EOD history crawl",
    "scripts/build_backtest_dataset.py":
        "the ten-year mkt_summary OHLCV crawl",
    "scripts/backtest_10y.py": "the ten-year whole-panel backtest",
}

REFUSAL = (
    "REFUSED (SO-21): {task} is backtest work and it runs on GitHub Actions "
    "minutes, never on the owner's PC. The public repository makes those "
    "minutes free, and the owner's order of 2026-10-19 is that his machine "
    "is not used at all. Run it there: gh workflow run backtest.yml -f "
    "script={script}"
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


def guard_cloud_backtest(script: str) -> None:
    """Stop a backtest that is starting anywhere but a GitHub Actions job.

    Call as the first statement of main(). On the PC this exits before the
    script imports pandas, opens a dataset or spins a single core, which is
    the whole point of SO-21. SystemExit prints the reason and no traceback,
    like the cloud-only guards below.
    """
    if running_in_github_actions():
        return
    task = BACKTEST_SCRIPTS.get(script, "this backtest")
    raise SystemExit(REFUSAL.format(task=task, script=script))


# --------------------------------------------------------------------- SO-12

#: Recurring or resident work belongs to the cloud, never to the owner's PC.
#: Each entry is a real entry point that a scheduler would otherwise run on
#: this machine, with the words the refusal prints. The mirror of
#: BACKTEST_SCRIPTS above: those scripts are refused on the PC, and so are
#: these, unless the owner's own instruction opens one.
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
    "REFUSED (SO-12): {task} is cloud-only work. The KMIALL scanner runs on "
    "GitHub Actions minutes and on the Cloudflare relay, every second per "
    "PSX band (SO-13, owner order 2026-10-19), and the owner's PC is used only "
    "for a backtest he asks for, so nothing recurring runs here. If the owner "
    "has asked for this exact local run, say so in the shell: "
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
    traceback, like guard_cloud_backtest above.
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
