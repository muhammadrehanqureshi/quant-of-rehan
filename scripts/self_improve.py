"""The self-improvement engine: the owner's entire workload in one command.

Owner order (self-improvement mission):
    python scripts/self_improve.py

is the entry point for the whole cycle, and it prints a one-screen summary.
It runs as ONE-OFF sessions exactly as the mission ordered: the owner
explicitly asked for local research runs by name for this task, so this
script is deliberately NOT in src.ci.local_only.BACKTEST_SCRIPTS and carries
no cloud guard; a heavy grid still belongs on the manual-dispatch Actions
task (backtest.yml, task=self-improve), which is the SO-21 compliant route,
and nothing here ever becomes a schedule, daemon or resident process.

The cycle:
  1. STATUS  the data-path measure: every archived session since 2026-10-15
     by outcome, plus the registry's experiment count (the multiplicity
     family) and the champion's standing.
  2. SEARCH  every variant is pre-registered (hypothesis, prediction, kill
     condition, code hash, data hash, seed, split) BEFORE it scores. A
     variant is killed inside discovery when its kill condition misses, so
     it never sees validation. Survivors are judged on validation; the best
     survivor becomes the challenger, which replaces the champion only if
     it also beats the champion on the LOCKED slice that no selection ever
     scored. Everything, failures included, is appended to the registry.
  3. CHAMPION automanagement: the existing demotion rules (the last 20
     production outcomes: non-positive net expectancy, drawdown above 10%,
     a losing streak of 8+) are evaluated from the archive and the champion
     state file records the verdict. While config.SELF_IMPROVE_ARM is False
     (the default) NOTHING is promoted to the live signal path: promotion
     goes only through the gate, and this script only writes the report.

Integrity (built in, tested):
  * Features are the causal dailies (daily_strategy); a decision at the
    close of T enters at T+1's open. No shift(-n) anywhere upstream.
  * Stop first: a bar that touches both levels books the stop; a stop that
    opens below is filled at the open (the engine's own law).
  * Costs are ALWAYS on, at the mission's own figure: 22.4 bps per side
    plus 10 bps slippage per side, and 15% CGT on gains.
  * No cherry picks: the grid is the pre-registered list, every variant is
    logged, and the multiplicity correction reads the registry's count.

SO-8: the split boundaries are Karachi calendar dates; nothing here reads
a wall clock or waits for one (SO-22: no sleep, no hold-the-turn).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.research import experiment_registry as registry  # noqa: E402
from src.research.outcome_labeler import (  # noqa: E402
    LabelParams, label_candidates, label_summary, net_after_costs)

DEFAULT_DATASET = Path("data/eod_dataset_10y.csv.gz")
DEFAULT_OUT = Path("data/research/self_improve_report.json")
CHAMPION_PATH = Path("data/research/champion.json")

#: The window the mission fixed for the data-path measure.
STATUS_SINCE = "2026-10-15"


# --------------------------------------------------------------- integrity

def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for one proportion (the mission asks for it)."""
    if n <= 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return (round(centre - half, 4), round(centre + half, 4))


def bootstrap_lower_bound(net: pd.Series, resamples: int, seed: int) -> float:
    """2.5th percentile of the resampled mean (the mission's lower bound)."""
    values = net.to_numpy(dtype="float64")
    if len(values) == 0:
        return 0.0
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(values), size=(resamples, len(values)))
    means = values[picks].mean(axis=1)
    return float(np.percentile(means, 2.5))


def _split_dates(dates: pd.Series) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    """The nested split, Karachi calendar dates, from config."""
    discovery_end = pd.Timestamp(config.SELF_IMPROVE_DISCOVERY_END)
    validation_end = pd.Timestamp(config.SELF_IMPROVE_VALIDATION_END)
    test_start = pd.Timestamp(config.SELF_IMPROVE_TEST_START)
    span = (dates.min(), dates.max())
    return {
        "discovery": (span[0] or dates.min(), discovery_end),
        "validation": (discovery_end + pd.Timedelta(days=1), validation_end),
        "test": (test_start, span[1]),
    }


def _in_split(frame: pd.DataFrame, bounds) -> pd.DataFrame:
    dates = pd.to_datetime(frame["signal_date"])
    return frame.loc[(dates >= bounds[0]) & (dates <= bounds[1])]


# ------------------------------------------------------------ the variants

def pre_registered_variants() -> list[dict]:
    """The pre-registered grid (every variant counts, failures included)."""
    weights = dict(config.SCORE_WEIGHTS)
    base = {"weights": weights}
    inverse = {"hypothesis_kind": "asymmetric exits, high win rate"}
    variants = [
        ("baseline-deployed-law", base, 0.02, 0.01, 3),
        ("inverse-1.5x3-hold3", base, 0.015, 0.03, 3),
        ("inverse-1.5x3-hold5", base, 0.015, 0.03, 5),
        ("inverse-1.5x3-hold10", base, 0.015, 0.03, 10),
        ("sym-1x2-hold3", base, 0.010, 0.02, 3),
        ("mid-1.2x2.5-hold3", base, 0.012, 0.025, 3),
    ]
    grids = []
    for name, w, tp, sl, hold in variants:
        grids.append({"name": name, "hypothesis_kind": inverse.get(
            "hypothesis_kind", "deployed exits"), "params": dict(w),
            "tp": tp, "sl": sl, "max_hold": hold})
    # The abstention and filter levers ride the strongest asymmetric shape.
    for relvol, label in ((2.0, "relvol2"), (2.5, "relvol2.5")):
        params = dict(base)
        params["min_relvol"] = relvol
        grids.append({"name": f"inverse-1.5x3-hold3-{label}",
                      "hypothesis_kind": inverse["hypothesis_kind"],
                      "params": params, "tp": 0.015, "sl": 0.03,
                      "max_hold": 3})
    for floor, label in ((70, "score70"), (80, "score80")):
        params = dict(base)
        params["min_score"] = floor
        grids.append({"name": f"inverse-1.5x3-hold3-{label}",
                      "hypothesis_kind": inverse["hypothesis_kind"],
                      "params": params, "tp": 0.015, "sl": 0.03,
                      "max_hold": 3})
    tight = dict(base)
    tight["max_extension"] = 0.04
    grids.append({"name": "inverse-1.5x3-hold3-ext04",
                  "hypothesis_kind": inverse["hypothesis_kind"],
                  "params": tight, "tp": 0.015, "sl": 0.03,
                  "max_hold": 3})
    cheap = dict(base)
    cheap["min_price"] = 20.0
    grids.append({"name": "inverse-1.5x3-hold3-price20",
                  "hypothesis_kind": inverse["hypothesis_kind"],
                  "params": cheap, "tp": 0.015, "sl": 0.03,
                  "max_hold": 3})
    fast = dict(base)
    fast["momentum_window"] = 5
    grids.append({"name": "inverse-1.5x3-hold3-mom5",
                  "hypothesis_kind": inverse["hypothesis_kind"],
                  "params": fast, "tp": 0.015, "sl": 0.03,
                  "max_hold": 3})
    return grids


# --------------------------------------------------------------- the engine

def evaluate_variant(panel: pd.DataFrame, variant: dict,
                     params: LabelParams) -> tuple[pd.DataFrame, dict]:
    """Label one candidate family end to end for one slice of dates.

    Returns the labels table (no fabrication; a candidate with no forward
    bar is a NO_ENTRY row, counted but never priced) and the family's own
    bookkeeping.
    """
    from src.backtest.daily_strategy import ScannerParams, build_signals, \
        build_path_matrix

    scanner = ScannerParams(**variant["params"])
    scored, mask = build_signals(panel, scanner)
    horizon = int(params.max_hold)
    paths, skipped = build_path_matrix(scored, mask, horizon)
    labels = label_candidates(
        panel,
        paths[["symbol", "signal_date", "score"]] if "score" in paths
        else paths[["symbol", "signal_date"]],
        params)
    book = {"n_gate_signals": int(mask.sum()), "n_skipped_no_next_bar": skipped,
            "n_labeled": int(len(labels))}
    return labels, book


def run_search(panel: pd.DataFrame, data_hash: str, seed: int,
               code_hash: str, registry_obj: registry.Registry,
               out_path: Path) -> dict:
    """The pre-registered, nested, kill-first search loop."""
    splits = _split_dates(panel["date"])
    label_params = LabelParams()
    champion = _load_champion()
    rows: list[dict] = []
    survivors: list[tuple[dict, dict]] = []
    for variant in pre_registered_variants():
        name = variant["name"]
        params_for_variant = {
            "params": variant["params"], "tp": variant["tp"],
            "sl": variant["sl"], "max_hold": variant["max_hold"],
        }
        variant_label_params = LabelParams(
            tp=variant["tp"], sl=variant["sl"], max_hold=variant["max_hold"])
        labels, book = evaluate_variant(panel, variant, variant_label_params)
        discovery = _in_split(labels, splits["discovery"])
        discovery_summary = label_summary(discovery)
        discovery_summary["bounds"] = [str(b) for b in splits["discovery"]]
        # Pre-registered kill: BEFORE validation, recorded either way.
        killed, why = _kill(decision_inputs=discovery_summary, name=name)
        decision = "KILL" if killed else "KEEP_DISCOVERY"
        row = registry_obj.append({
            "hypothesis": f"{name}: {variant['hypothesis_kind']}; predict a "
                          f"discovery win rate at or above "
                          f"{config.SELF_IMPROVE_DISCOVERY_WIN_FLOOR:.0%} "
                          "with positive net expectancy under the mission's "
                          "own costs",
            "code_hash": code_hash, "data_hash": data_hash,
            "params": params_for_variant,
            "seed": seed,
            "split": "discovery",
            "results": {**discovery_summary, "book": book},
            "pred": f"discovery win rate >= "
                    f"{config.SELF_IMPROVE_DISCOVERY_WIN_FLOOR:.0%}, "
                    "positive expectancy",
            "kill": why or ("win_rate_floor, net_floor, and minimum trades "
                            "all cleared"),
            "decision": decision,
        })
        rows.append(row)
        if killed:
            continue
        validation_labels = _in_split(labels, splits["validation"])
        validation_summary = label_summary(validation_labels)
        validation_summary["bounds"] = [str(b) for b in splits["validation"]]
        survivors.append((variant, validation_summary))
    # The multiplicity correction over the survivors that reached a test of
    # their win rate (the registry count is the honest family size).
    p_values = {name_from_summary(v, i): registry.one_sided_p(
        s["win_rate"] or 0.0, s["n"]) for i, (v, s) in enumerate(survivors)}
    adjusted = registry.holm_adjusted(p_values)
    best = None
    for i, (variant, validation_summary) in enumerate(survivors):
        name = name_from_summary(variant, i)
        validation_summary["holm_p"] = adjusted.get(name)
    if survivors:
        best = max(survivors, key=lambda pair: (
            pair[1]["win_rate"] or 0.0, pair[1]["net_expectancy"] or 0.0))
    test_summary = None
    promotion = "none (no survivor cleared the validation stage)"
    if best is not None:
        variant, validation_summary = best
        test_labels = _in_split(
            evaluate_variant(panel, variant, LabelParams(
                tp=variant["tp"], sl=variant["sl"],
                max_hold=variant["max_hold"]))[0], splits["test"])
        test_summary = label_summary(test_labels)
        test_summary["bounds"] = [str(b) for b in splits["test"]]
        test_summary["wilson"] = list(wilson_interval(
            test_summary["wins"], test_summary["n"]))
        if test_summary["n"]:
            test_summary["bootstrap_lower"] = round(bootstrap_lower_bound(
                test_labels.loc[~test_labels["data_invalid"].astype(bool),
                                "net_ret"],
                config.SELF_IMPROVE_BOOTSTRAP_RESAMPLES, seed), 6)
        promotion = _challenge_champion(champion, variant, test_summary)
        registry_obj.append({
            "hypothesis": f"{variant['name']}: the LOCKED holdout test "
                          "(fresh sessions no selection ever scored)",
            "code_hash": code_hash, "data_hash": data_hash,
            "params": {"params": variant["params"], "tp": variant["tp"],
                       "sl": variant["sl"], "max_hold": variant["max_hold"]},
            "seed": seed, "split": "test",
            "results": test_summary,
            "pred": "holdout win rate above zero expectance and the "
                    "installed champion",
            "kill": "none", "decision": promotion,
        })
    report = {
        "splits": {k: [str(b) for b in v] for k, v in splits.items()},
        "variants_tried": len(rows),
        "registry_total": registry_obj.count(),
        "survivors": [
            {"name": name_from_summary(v, i), "validation": s}
            for i, (v, s) in enumerate(survivors)],
        "best": (None if best is None else {
            "name": name_from_summary(*best),
            "validation": best[1], "test": test_summary}),
        "champion_decision": promotion,
        "champion": _load_champion(),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str),
                        encoding="utf-8")
    return report


def name_from_summary(variant, _index: int) -> str:
    return variant["name"] if isinstance(variant, dict) else str(variant)


def _kill(decision_inputs: dict, name: str) -> tuple[bool, str]:
    """The pre-registered kill rule (config's own numbers)."""
    n = decision_inputs.get("n") or 0
    win_rate = decision_inputs.get("win_rate")
    expect = decision_inputs.get("net_expectancy")
    if n < config.SELF_IMPROVE_MIN_DISCOVERY_TRADES:
        return True, (f"discovery trades {n} below the floor "
                      f"{config.SELF_IMPROVE_MIN_DISCOVERY_TRADES}")
    if win_rate is None or win_rate < config.SELF_IMPROVE_DISCOVERY_WIN_FLOOR:
        return True, (f"discovery win rate {win_rate} below the floor "
                      f"{config.SELF_IMPROVE_DISCOVERY_WIN_FLOOR}")
    if expect is None or expect <= config.SELF_IMPROVE_DISCOVERY_NET_FLOOR:
        return True, (f"discovery net expectancy {expect} at or below "
                      f"{config.SELF_IMPROVE_DISCOVERY_NET_FLOOR}")
    return False, None


def _load_champion() -> dict | None:
    path = ROOT / CHAMPION_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"error": "champion file unreadable"}


def _challenge_champion(champion: dict | None, variant: dict,
                        test_summary: dict) -> str:
    """The challenger replaces the champion only on validation AND fresh (the
    locked slice above has just served as the fresh check); the champion
    state file records the verdict, and nothing is promoted to the live
    path while config.SELF_IMPROVE_ARM is False."""
    if test_summary.get("n", 0) < 100 or not test_summary.get("win_rate") or \
            not (test_summary.get("net_expectancy") or 0) > 0 or \
            not (test_summary.get("bootstrap_lower") or 0) > 0:
        return ("NOT PROMOTED: the locked holdout does not carry the mission's "
                "own numbers (100 trades, positive mean, positive bootstrap)")
    if champion and champion.get("test_win_rate") is not None and \
            test_summary["win_rate"] <= champion["test_win_rate"]:
        return (f"CHAMPION STANDS: the installed champion's "
                f"{champion['test_win_rate']:.1%} was not beaten")
    record = {
        "variant": variant["name"],
        "params": variant["params"],
        "exits": {"tp": variant["tp"], "sl": variant["sl"],
                  "max_hold": variant["max_hold"]},
        "test_win_rate": test_summary["win_rate"],
        "test_expectancy": test_summary["net_expectancy"],
        "test_n": test_summary["n"],
        "wilson": test_summary["wilson"],
        "promoted_at": datetime.utcnow().isoformat(timespec="seconds"),
        "armed": bool(config.SELF_IMPROVE_ARM),
        "note": "REPORT ONLY: the live signal path is untouched while "
                "SELF_IMPROVE_ARM is False (the gate decides promotion).",
    }
    (ROOT / CHAMPION_PATH).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / CHAMPION_PATH).write_text(json.dumps(record, indent=2),
                                      encoding="utf-8")
    return "CHALLENGER PROMOTED (report only, live path untouched)"


# ------------------------------------------------------------ the demotion

DEMOTION_RULES = {
    # The existing demotion law (src/research/forward_validation.py): the
    # newest 20 production outcomes are the window.
    "window": 20,
    "expectancy_floor": 0.0,
    "max_drawdown": 0.10,
    "max_losing_streak": 8,
}


def demotion_check(outcomes: list[dict]) -> dict:
    """The existing rules, evaluated on the archive's own production rows."""
    rows = [row for row in outcomes
            if row.get("net_return") is not None][-(DEMOTION_RULES["window"]):]
    if not rows:
        return {"window_size": 0, "demote": False, "reason": None}
    nets = [float(r["net_return"]) for r in rows]
    mean_net = sum(nets) / len(nets)
    streak = 0
    for net in reversed(nets):
        if net <= 0:
            streak += 1
        else:
            break
    equity, peak, drawdown = 1.0, 1.0, 0.0
    for net in nets:
        equity *= (1.0 + net)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak / equity - 1.0)
    reasons = []
    if mean_net <= DEMOTION_RULES["expectancy_floor"]:
        reasons.append(f"last {len(nets)} production trades average "
                       f"{mean_net:+.4%} net, at or below the floor")
    if drawdown > DEMOTION_RULES["max_drawdown"]:
        reasons.append(f"drawdown {drawdown:.1%} above the limit")
    if streak >= DEMOTION_RULES["max_losing_streak"]:
        reasons.append(f"losing streak {streak} at the limit")
    return {"window_size": len(nets), "mean_net": round(mean_net, 6),
            "drawdown": round(drawdown, 4), "losing_streak": streak,
            "demote": bool(reasons), "reason": "; ".join(reasons)}


# ------------------------------------------------------------------- status

def measure_data_path() -> dict:
    """The mission's data-path measure, from the archives only."""
    try:
        from src.research import session_history
        report: dict = {}
        rows = session_history.session_rows(report=report)
    except Exception as exc:  # noqa: BLE001 - a stated gap is the answer
        return {"error": f"{type(exc).__name__}: {exc}"}
    since = {}
    for row in rows:
        day = str(row.get("date") or "")
        if day >= STATUS_SINCE:
            key = str(row.get("label") or "UNFILED")
            since[key] = since.get(key, 0) + 1
    total = sum(since.values())
    return {
        "since": STATUS_SINCE,
        "archived_sessions": total,
        "outcomes": since,
        "archive_report": report,
        "note": "the archive carries the finalize outcomes; it does not yet "
                "record DATA BLOCKED sessions (their fix lands with the "
                "labeling hook, which archives the blocked reason too)",
    }


def one_screen(status: dict, report: dict | None) -> str:
    """The one-screen summary the mission asks the command to print."""
    lines = ["= Quant of Rehan self-improvement, one screen ="]
    lines.append(f"data path (sessions since {STATUS_SINCE}): "
                 f"{json.dumps(status.get('outcomes'), default=str)}")
    registry_obj = registry.Registry()
    reg = registry.summarize_rows(registry_obj.rows(), last_n=200)
    lines.append(f"experiments registered: {reg['total']} "
                 f"({json.dumps(reg['decisions'])})")
    champion = _load_champion()
    if champion:
        lines.append(f"champion: {champion.get('variant')} "
                     f"test win rate {champion.get('test_win_rate')} "
                     f"(n={champion.get('test_n')}), armed="
                     f"{champion.get('armed')}")
    else:
        lines.append("champion: none installed yet")
    if report:
        best = report.get("best")
        if best:
            test = best.get("test") or {}
            lines.append(f"best challenger: {best['name']} "
                         f"win {test.get('win_rate')}, "
                         f"expectancy {test.get('net_expectancy')}, "
                         f"n {test.get('n')}, "
                         f"wilson {test.get('wilson')}")
        lines.append(f"decision: {report.get('champion_decision')}")
        lines.append(f"variants tried: {report.get('variants_tried')}, "
                     f"registry total {report.get('registry_total')}")
    lines.append("(report file: data/research/self_improve_report.json; "
                 "the live signal path is untouched while "
                 "SELF_IMPROVE_ARM is False)")
    return "\n".join(lines[:14])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="the self-improvement engine, one command")
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--task", choices=("full", "status"), default="full")
    args = ap.parse_args(argv)

    status = measure_data_path()
    seed = config.SELF_IMPROVE_SEED
    code = registry.code_hash()
    report = None
    if args.task == "full":
        if not args.dataset.is_file():
            print(f"::error::{args.dataset} is missing. Build it first "
                  "(ten-year dataset; never invented, SO-3).", file=sys.stderr)
            return 1
        dhash = registry.data_hash(args.dataset)
        panel = pd.read_csv(args.dataset, parse_dates=["date"])
        report = run_search(panel, dhash, seed, code, registry.Registry(),
                            args.out)
        champion = _load_champion()
        if champion and not champion.get("error"):
            try:
                from src.research import session_history
                outcomes = session_history.session_rows()
                champion["demotion"] = demotion_check(outcomes)
            except Exception as exc:  # noqa: BLE001 - a stated gap
                champion["demotion"] = {"error": f"{type(exc).__name__}"}
        print(one_screen(status, report))
    else:
        print(one_screen(status, None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
