#!/usr/bin/env python3
"""LOCAL-ONLY staged parameter search over the 5-year PSX dataset (SO-4).

Runs on the owner's PC and nowhere else: no cloud calls, no GitHub Actions, no
external APIs. It reads one local file and writes one local JSON report.

What it does
------------
1.  Ingests ``data/eod_history.csv.gz`` through the robust loader, with a named
    counter for every row dropped or repaired.
2.  Proves the fast vectorised evaluator agrees with ``engine.run_backtest`` on
    a random sample of signals, so the sweep's numbers inherit the engine's
    authority.
3.  Stage 1: sweeps the exit law (tp x sl x max_hold) against the shipped
    scanner thresholds.
4.  Stage 2: freezes the best exit geometry and sweeps the scanner's own
    parameters.
5.  Scores the leading candidates out-of-sample on leak-free walk-forward test
    segments, and prints the in-sample figure BESIDE the out-of-sample one.

The 90% target is reported, not assumed. If the in-sample figure reaches it, the
script says so and says it is an in-sample figure. If it does not, the script
says that too, and shows the reward:risk geometry the target would demand.

Usage (from the repo root)::

    python scripts/backtest_optimize.py
    python scripts/backtest_optimize.py --target 0.90 --horizon 10
    python scripts/backtest_optimize.py --require-target   # exit 1 if missed

Exit status: 0 on a completed run; 1 only when ``--require-target`` is given and
the in-sample accuracy misses the target.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_local_only  # noqa: E402

from src import config  # noqa: E402
from src.backtest.daily_strategy import ScannerParams  # noqa: E402
from src.backtest.dataset import (DEFAULT_DATASET, DEFAULT_MIN_BARS,  # noqa: E402
                                  DEFAULT_UNIVERSE, load_eod_history)
from src.backtest.optimize import (OWNER_LAW, ExitLaw, ProgressFn,  # noqa: E402
                                   cross_check, run_staged_search)


def _pct(value: float | None) -> str:
    return "  n/a " if value is None else f"{value:6.2%}"


def _num(value: float | None) -> str:
    return "  n/a  " if value is None else f"{value:+.4f}"


def _print_table(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    header = (f"  {'candidate':<38} {'n':>7} {'win':>7} {'net/trade':>10}"
              f"  {'OOS n':>7} {'OOS win':>8} {'OOS net':>9} {'gap':>8}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for row in rows:
        inside = row["in_sample"]
        outside = row.get("out_of_sample") or {}
        gap = row.get("overfit_gap")
        print(f"  {row['label']:<38} {inside['n_trades']:>7,} "
              f"{_pct(inside['win_rate'])} {_num(inside['expectancy_net'])}"
              f"  {outside.get('n_trades', 0):>7,} "
              f"{_pct(outside.get('win_rate'))} {_num(outside.get('expectancy_net'))}"
              f" {_num(gap)}")


def _progress(label: str) -> ProgressFn:
    """A coarse progress printer: one line at every 10% of a grid."""
    state = {"next": 0}

    def report(done: int, total: int, item: object) -> None:
        if total <= 0:
            return
        mark = int(done * 10 / total)
        if mark >= state["next"]:
            state["next"] = mark + 1
            print(f"    {label}: {done}/{total} ({mark * 10:>3}%)  last: {item}")

    return report


def main(argv: list[str] | None = None) -> int:
    guard_local_only("scripts/backtest_optimize.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=ROOT / DEFAULT_DATASET)
    parser.add_argument("--universe", type=Path, default=ROOT / DEFAULT_UNIVERSE)
    parser.add_argument("--min-bars", type=int, default=DEFAULT_MIN_BARS,
                        help="Minimum sessions a symbol must have to stay in.")
    parser.add_argument("--target", type=float, default=0.90,
                        help="The accuracy the owner asked for (default 0.90).")
    parser.add_argument("--horizon", type=int, default=10,
                        help="Forward bars to precompute for the exit sweep.")
    parser.add_argument("--stage1-top", type=int, default=5,
                        help="Exit-law candidates to carry into out-of-sample.")
    parser.add_argument("--stage2-top", type=int, default=5,
                        help="Scanner candidates to carry into out-of-sample.")
    parser.add_argument("--cross-check-sample", type=int, default=2000,
                        help="Signals to re-run through the authoritative engine.")
    parser.add_argument("--require-target", action="store_true",
                        help="Exit non-zero when the target is not met in-sample.")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data" / "backtest_optimize_report.json")
    args = parser.parse_args(argv)

    print("=" * 78)
    print("QUANT OF REHAN - LOCAL STAGED PARAMETER SEARCH (no network, SO-4)")
    print("=" * 78)

    try:
        frame, ingestion = load_eod_history(args.dataset, universe_path=args.universe,
                                            min_bars=args.min_bars)
    except (FileNotFoundError, ValueError) as exc:
        print(f"\nINGESTION FAILED: {exc}")
        return 1

    report = ingestion.as_dict()
    print(f"\nDataset   : {report['source']}")
    print(f"Universe  : {report['universe_source']}")
    print(f"Rows      : {report['rows_in']:,} in -> {report['rows_out']:,} out "
          f"({report['retention']:.1%} retained)")
    print(f"Symbols   : {report['symbols_in']:,} in -> {report['symbols_out']:,} "
          f"traded")
    print(f"Window    : {report['first_date']} .. {report['last_date']} "
          f"({report['sessions']:,} sessions)")
    print("Drops     : " + ", ".join(
        f"{key.removeprefix('dropped_')}={report[key]:,}"
        for key in sorted(report) if key.startswith("dropped_")
        and report[key]))
    print(f"Repairs   : ragged_envelope={report['repaired_ragged_envelope']:,}")
    for note in report["notes"]:
        print(f"            note: {note}")

    if frame.empty:
        print("\nNothing to optimise: the ingestion step returned no rows.")
        return 1

    shipped = ScannerParams(weights=dict(config.SCORE_WEIGHTS))
    owner_law = ExitLaw(*OWNER_LAW)

    print("\nValidating the fast evaluator against the authoritative engine...")
    try:
        agreement = cross_check(frame, shipped, owner_law,
                                sample=args.cross_check_sample)
    except AssertionError as exc:
        print(f"ENGINE DISAGREEMENT: {exc}")
        print("Refusing to report a sweep whose evaluator disagrees with the engine.")
        return 1
    print(f"  compared {agreement['compared']:,} trades "
          f"(below band screen: {agreement.get('n_below_screen', 0):,})")
    print(f"  engine win rate {agreement['engine_win_rate']:.4%} vs fast "
          f"{agreement['fast_win_rate']:.4%}")
    print(f"  engine net/trade {agreement['engine_expectancy']:+.6f} vs fast "
          f"{agreement['fast_expectancy']:+.6f}  -> identical")

    print("\nRunning the staged search (stage 1: exit law; stage 2: scanner)...")
    reporter = _progress("search")   # one stateful reporter, not a new one per call
    optimisation = run_staged_search(
        frame, target=args.target, horizon=args.horizon,
        dataset_report=report, stage1_top=args.stage1_top,
        stage2_top=args.stage2_top, progress=reporter)

    _print_table("STAGE 1 - exit law (shipped scanner thresholds)", optimisation.stage1)
    frozen = optimisation.protocol["frozen_exit_law"]
    _print_table(f"STAGE 2 - scanner parameters (frozen exit law "
                 f"tp={frozen['tp']:.3f}/sl={frozen['sl']:.3f}/"
                 f"hold={frozen['max_hold']})", optimisation.stage2)

    protocol = optimisation.protocol
    print(f"\nProtocol  : min_trades={protocol['min_trades']:,}  "
          f"cost={protocol['cost_side_bps']:.2f}bps/side  "
          f"CGT={protocol['cgt_rate']:.0%}  "
          f"band_screen={protocol['invalid_band']:.0%}")
    wf = protocol["walk_forward"]
    print(f"Walk-fwd  : {wf.get('n_folds', 0)} folds x {wf.get('test_size', 0)} test "
          f"sessions over {wf.get('n_sessions', 0):,} sessions")
    if optimisation.warnings:
        for warning in optimisation.warnings:
            print(f"WARNING   : {warning}")

    print(f"\nTARGET {args.target:.0%}: "
          f"{'MET in-sample' if optimisation.target_hit_in_sample else 'NOT MET'}")
    print("\nVERDICT")
    for line in _wrap(optimisation.verdict, 74):
        print(f"  {line}")

    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "runs_locally_only": True,
        "dataset": report,
        "engine_agreement": agreement,
        "optimisation": optimisation.as_dict(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nReport -> {args.out}")

    if args.require_target and not optimisation.target_hit_in_sample:
        print(f"\n--require-target: the {args.target:.0%} target was not reached "
              f"in-sample. See the verdict above.")
        return 1
    return 0


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


if __name__ == "__main__":
    sys.exit(main())
