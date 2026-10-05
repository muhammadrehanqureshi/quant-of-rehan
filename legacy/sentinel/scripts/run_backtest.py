"""Full backtest sweep: every stored session through the CURRENT rules.

Calls the replay engine in-process (no fragile stdout parsing) at 300s
decide intervals; exits always walk full 5-second resolution. Designed
for GitHub Actions; also runs locally. Results are written
incrementally to data/backtest/results.json and COMMITTED after each
session, so an interrupted sweep loses nothing and resumes cleanly.
"""
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import replay as replay_mod  # noqa: E402

OUT = ROOT / "data" / "backtest" / "results.json"
LOG = ROOT / "data" / "backtest" / "sweep.log"
INTERVAL_S = 300.0

# Optional rulebook tag: `--tag v2.2.0` replays the CURRENT rules into
# results-v2.2.0.json instead of the baseline file. The baseline's
# done-set is keyed by date alone - without tags, a new rulebook could
# NEVER be replayed (every session is already "done" from the last
# sweep under the old rules). 2026-09-21: the first tagged sweep is
# the Rule 25 + Rule 11c rulebook versus the 2026-09-20 baseline.
_args = sys.argv[1:]
TAG: str | None = None
if "--tag" in _args:
    _i = _args.index("--tag")
    TAG = _args[_i + 1] if _i + 1 < len(_args) else None
    _args = _args[:_i] + _args[_i + 2 :]
if TAG:
    OUT = ROOT / "data" / "backtest" / f"results-{TAG}.json"
GIT_COMMIT = "--commit" in _args


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        fh.write(f"{stamp} {msg}\n")


def load_results(path: Path | None = None) -> list:
    path = path or OUT
    if path.exists():
        try:
            return __import__("json").loads(
                path.read_text(encoding="utf-8")
            )
        except (ValueError, OSError):
            return []
    return []


def save_results(results: list, path: Path | None = None) -> None:
    path = path or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        __import__("json").dumps(results, indent=2), encoding="utf-8"
    )


# The contributor graph must show ONLY Mr. Rehan, ever - every
# automated commit (local or cloud) is authored as the repo owner.
GIT_IDENTITY = [
    "-c", "user.name=Mr. Rehan",
    "-c", "user.email=111383512+muhammadrehanqureshi@users.noreply.github.com",
]


def commit_progress() -> None:
    """Durable per-session commit (cloud runs); no-op if nothing new."""
    subprocess.run(
        ["git", "add", "data/backtest"],
        cwd=str(ROOT), capture_output=True,
    )
    dirty = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(ROOT), capture_output=True,
    ).returncode
    if dirty:
        subprocess.run(
            ["git", *GIT_IDENTITY, "commit", "-m",
             "Cloud backtest: incremental sweep progress"],
            cwd=str(ROOT), capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=str(ROOT), capture_output=True)


def main() -> int:
    dates = replay_mod.stored_dates()
    done = {r.get("date") for r in load_results()}
    pending = [d for d in dates if d not in done]

    # HARD GUARD: multi-session sweeps are hours of CPU and belong on
    # GitHub Actions (cloud-backtest.yml). Locally, only an explicit
    # --allow-local unlocks them - this bot must never hammer the
    # owner's PC by accident.
    import os
    on_cloud = os.environ.get("GITHUB_ACTIONS") == "true"
    if not on_cloud and len(pending) > 1 and "--allow-local" not in sys.argv:
        print(
            f"Refusing to replay {len(pending)} sessions locally - that is "
            "hours of CPU. Trigger the 'cloud backtest sweep' workflow on "
            "GitHub instead, or pass --allow-local to override."
        )
        return 1

    log(
        f"sweep start{f' (rulebook {TAG})' if TAG else ''}: "
        f"{len(dates)} sessions, {len(done)} already done"
    )
    results = load_results()

    for d in dates:
        if d in done:
            continue
        t0 = time.time()
        log(f"replaying {d} ...")
        try:
            report = replay_mod.replay_date(
                d, quiet=True, decide_interval_s=INTERVAL_S
            )
        except Exception as exc:  # noqa: BLE001
            log(f"{d}: FAILED {exc!r}")
            continue
        rep = report.to_dict()
        rep["date"] = d
        if TAG:
            rep["rulebook_tag"] = TAG
        rep["decide_interval_s"] = INTERVAL_S
        rep["runtime_s"] = round(time.time() - t0, 1)
        results = [r for r in results if r.get("date") != d] + [rep]
        results.sort(key=lambda r: r.get("date", ""))
        save_results(results)
        n_trades = len(report.trades)
        log(f"{d}: done in {rep['runtime_s']}s, {n_trades} virtual trades")
        if GIT_COMMIT:
            commit_progress()

    log("sweep complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
