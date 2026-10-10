#!/usr/bin/env python3
"""Train the ONE AI signal model. Offline, reproducible, honest about its fit.

Rebuild 2026-10-10. This is the only writer of models/kmiall_signal_v1.json.

What it does:

  1. loads the frozen KMIALL event study (data/event_study/events.parquet);
  2. proves that the LIVE featurizer (src/signals/ai_model.panel_features) and
     the RESEARCH featurizer that built that table agree, row for row, on a
     random sample -- if they disagree the training stops, because a model
     trained on one definition and served another is worthless;
  3. fits an L2 logistic regression in numpy (no sklearn dependency) on data
     before the cut date, and measures it on data after it, chronologically;
  4. writes the artifact only with its own provenance: train window, row
     counts, holdout AUC / log-loss / Brier / decile lift, dataset hashes.

Eligibility, and what it means. The artifact is marked eligible ONLY when the
holdout AUC beat 0.50 and the holdout is large enough to mean something. An
ineligible artifact is still written -- it is evidence that the model was
tried -- but the live gate stays inactive and says so. Nothing here tunes a
threshold until something looks good; the configuration is fixed before the
holdout is scored.

Usage:
    python scripts/train_signal_model.py
    python scripts/train_signal_model.py --train-cut 2023-01-01 --check-only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import now_karachi  # noqa: E402
from src.signals import ai_model  # noqa: E402

EVENTS = ai_model.EVENTS_PATH
PANEL = ai_model.PANEL_PATH
OUT = ai_model.MODEL_PATH

MIN_HOLDOUT_ROWS = 5_000
L2 = 1.0
ITERATIONS = 40
EQUIVALENCE_ROWS = 500
EQUIVALENCE_TOL = 5e-3


# ------------------------------------------------------------------- metrics

def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Rank-based AUC. Ties get the average rank (Mann-Whitney U)."""
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p), dtype=float)
    sorted_p = p[order]
    index = 0
    while index < len(p):
        end = index
        while end + 1 < len(p) and sorted_p[end + 1] == sorted_p[index]:
            end += 1
        ranks[order[index:end + 1]] = (index + end) / 2.0 + 1.0
        index = end + 1
    positives = y == 1
    n_pos = float(positives.sum())
    n_neg = float(len(y) - n_pos)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2.0)
                 / (n_pos * n_neg))


def log_loss(y: np.ndarray, p: np.ndarray) -> float:
    q = np.clip(p, 1e-12, 1 - 1e-12)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def decile_report(y: np.ndarray, p: np.ndarray, name: str) -> dict:
    base = float(y.mean())
    order = np.argsort(-p, kind="mergesort")
    top = order[:max(1, len(y) // 10)]
    top_rate = float(y[top].mean())
    return {
        "slice": name,
        "rows": int(len(y)),
        "base_rate": round(base, 5),
        "top_decile_rate": round(top_rate, 5),
        "top_decile_lift_pp": round(100 * (top_rate - base), 3),
        "auc": round(auc(y, p), 5),
        "log_loss": round(log_loss(y, p), 6),
        "brier": round(brier(y, p), 6),
    }


# ------------------------------------------------------------------ fitting

def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = L2,
                 iterations: int = ITERATIONS) -> tuple[np.ndarray, float]:
    """IRLS / Newton steps on the L2-penalised log-likelihood."""
    n, p = X.shape
    design = np.hstack([np.ones((n, 1)), X])
    weights = np.zeros(p + 1)
    penalty = l2 * np.eye(p + 1)
    penalty[0, 0] = 0.0  # never penalise the intercept
    for _ in range(iterations):
        z = design @ weights
        mu = 1.0 / (1.0 + np.exp(-np.clip(z, -35, 35)))
        variance = np.clip(mu * (1 - mu), 1e-9, None)
        gradient = design.T @ (y - mu) - penalty @ weights
        hessian = (design.T * variance) @ design + penalty
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            step = np.linalg.lstsq(hessian, gradient, rcond=None)[0]
        weights += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return weights[1:], float(weights[0])


# -------------------------------------------------------------- equivalence

def check_feature_equivalence(events: pd.DataFrame, panel: pd.DataFrame,
                              rows: int = EQUIVALENCE_ROWS) -> dict:
    """Live featurizer vs the research table it was trained on.

    This is the check that makes the model trustworthy: if the two definitions
    of a feature ever drift, the artifact would be serving inputs it was not
    trained on. It is run before every training.
    """
    live = ai_model.panel_features(panel)
    live = live.rename(columns={name: f"live_{name}" for name in ai_model.FEATURES})
    live["signal_date"] = pd.to_datetime(live["date"])
    sample = events.sample(n=min(rows, len(events)), random_state=20261010)
    merged = sample.merge(
        live[["symbol", "signal_date"] + [f"live_{n}" for n in ai_model.FEATURES]],
        on=["symbol", "signal_date"], how="inner")
    checked: list[dict] = []
    worst = 0.0
    for name in ai_model.FEATURES:
        research = merged[f"f_{name}"].astype(float)
        served = merged[f"live_{name}"].astype(float)
        both = research.notna() & served.notna()
        if both.sum() == 0:
            checked.append({"feature": name, "compared": 0, "agreement": None})
            continue
        a = research[both].to_numpy()
        b = served[both].to_numpy()
        scale = np.maximum(np.abs(a), 1e-9)
        close = np.abs(a - b) / scale < EQUIVALENCE_TOL
        agreement = float(close.mean())
        worst = max(worst, 1.0 - agreement)
        checked.append({"feature": name, "compared": int(both.sum()),
                        "agreement": round(agreement, 6)})
        # the trinary features and the booleans are compared exactly
    return {
        "sampled_rows": int(len(merged)),
        "tolerance": EQUIVALENCE_TOL,
        "worst_disagreement": round(worst, 6),
        "passed": worst < EQUIVALENCE_TOL,
        "per_feature": checked,
    }


# --------------------------------------------------------------------- main

def build_dataset(events: pd.DataFrame, train_cut: pd.Timestamp):
    working = events.copy()
    working["entry_date"] = pd.to_datetime(working["entry_date"])
    working = working[working[ai_model.TRUTH_LABEL].notna()]
    for name in ai_model.FEATURES:
        working[f"f_{name}"] = pd.to_numeric(working[f"f_{name}"], errors="coerce")
        if name == "above_ma20":
            working[f"f_{name}"] = working[f"f_{name}"].astype("float64")
    feature_columns = [f"f_{name}" for name in ai_model.FEATURES]
    train = working[working["entry_date"] < train_cut]
    holdout = working[working["entry_date"] >= train_cut]
    return working, train, holdout, feature_columns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the AI signal model")
    parser.add_argument("--events", type=Path, default=EVENTS)
    parser.add_argument("--panel", type=Path, default=PANEL)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--train-cut", default="2024-01-01")
    parser.add_argument("--check-only", action="store_true",
                        help="run the feature equivalence check and stop")
    args = parser.parse_args(argv)

    if not args.events.is_file():
        print(f"missing event study: {args.events}", file=sys.stderr)
        return 2
    events = pd.read_parquet(args.events)

    if not args.panel.is_file():
        print(f"missing daily panel: {args.panel}", file=sys.stderr)
        return 2
    panel = ai_model.load_panel(args.panel)
    print(f"panel: {len(panel):,} bars, {panel['symbol'].nunique()} symbols, "
          f"through {ai_model.panel_as_of(panel)}")

    equivalence = check_feature_equivalence(events, panel)
    print(f"feature equivalence: worst disagreement "
          f"{equivalence['worst_disagreement']:.2%} on "
          f"{equivalence['sampled_rows']} rows -> "
          f"{'PASS' if equivalence['passed'] else 'FAIL'}")
    if not equivalence["passed"]:
        offenders = [row["feature"] for row in equivalence["per_feature"]
                     if (row["agreement"] or 0) < 1 - EQUIVALENCE_TOL]
        print("disagreeing features: " + ", ".join(offenders), file=sys.stderr)
        print("refusing to train: the live featurizer does not reproduce the "
              "research definition.", file=sys.stderr)
        return 3
    if args.check_only:
        return 0

    train_cut = pd.Timestamp(args.train_cut)
    working, train, holdout, feature_columns = build_dataset(events, train_cut)
    if len(train) < 10_000 or len(holdout) < MIN_HOLDOUT_ROWS:
        print(f"insufficient data: train {len(train):,} holdout {len(holdout):,} "
              f"(need >=10,000 and >={MIN_HOLDOUT_ROWS:,})", file=sys.stderr)
        return 4

    mean = train[feature_columns].mean()
    scale = train[feature_columns].std(ddof=0).replace(0, 1.0)
    mean = mean.fillna(0.0)
    scale = scale.fillna(1.0)

    def matrix(frame: pd.DataFrame) -> np.ndarray:
        values = frame[feature_columns].astype("float64").copy()
        values = values.fillna(mean)
        return ((values - mean) / scale).to_numpy()

    X_train, y_train = matrix(train), train[ai_model.TRUTH_LABEL].astype(int).to_numpy()
    X_hold, y_hold = matrix(holdout), holdout[ai_model.TRUTH_LABEL].astype(int).to_numpy()

    coefficients, intercept = fit_logistic(X_train, y_train)

    train_scores = 1.0 / (1.0 + np.exp(-np.clip(X_train @ coefficients + intercept, -35, 35)))
    hold_scores = 1.0 / (1.0 + np.exp(-np.clip(X_hold @ coefficients + intercept, -35, 35)))

    slices = [decile_report(y_train, train_scores, "train"),
              decile_report(y_hold, hold_scores, "holdout")]
    years = holdout.assign(_p=hold_scores)
    for year, chunk in years.groupby(years["entry_date"].dt.year):
        y_year = chunk[ai_model.TRUTH_LABEL].astype(int).to_numpy()
        scores = chunk["_p"].to_numpy()
        report = decile_report(y_year, scores, str(year))
        report["auc"] = round(auc(y_year, scores), 5)
        # a single year can be too small for a decile to mean anything
        report["reliable"] = bool(len(chunk) >= MIN_HOLDOUT_ROWS)
        slices.append(report)

    holdout_report = slices[1]
    eligible = bool(
        np.isfinite(holdout_report["auc"])
        and holdout_report["auc"] > 0.5
        and holdout_report["rows"] >= MIN_HOLDOUT_ROWS
    )

    metadata = {
        "trained_at": now_karachi().isoformat(timespec="seconds"),
        "train_cut": train_cut.date().isoformat(),
        "train_window": [str(train["entry_date"].min().date()),
                         str(train["entry_date"].max().date())],
        "holdout_window": [str(holdout["entry_date"].min().date()),
                           str(holdout["entry_date"].max().date())],
        "train_rows": int(len(train)),
        "holdout": holdout_report,
        "train": slices[0],
        "slices": slices,
        "base_rate": round(float(working[ai_model.TRUTH_LABEL].mean()), 5),
        "l2": L2,
        "iterations": ITERATIONS,
        "eligible": eligible,
        "eligibility_rule": (f"holdout AUC > 0.50 and holdout rows >= "
                             f"{MIN_HOLDOUT_ROWS:,}"),
        "max_imputed_features": ai_model.MAX_IMPUTED_FEATURES,
        "events_file": str(args.events.relative_to(ROOT)),
        "events_sha256": ai_model.dataset_fingerprint(args.events),
        "panel_file": str(args.panel.relative_to(ROOT)),
        "panel_sha256": ai_model.dataset_fingerprint(args.panel),
        "panel_as_of": ai_model.panel_as_of(panel),
        "feature_equivalence": {
            "sampled_rows": equivalence["sampled_rows"],
            "worst_disagreement": equivalence["worst_disagreement"],
            "tolerance": equivalence["tolerance"],
            "passed": equivalence["passed"],
        },
        "note": ("A confirmation gate, not a strategy. Ineligible artifacts are "
                 "kept as evidence but never gate a live signal."),
    }

    model = ai_model.Model(
        features=ai_model.FEATURES,
        label=ai_model.TRUTH_LABEL,
        mean=[round(float(v), 10) for v in mean],
        scale=[round(float(v), 10) for v in scale],
        coefficients=[round(float(v), 10) for v in coefficients],
        intercept=round(float(intercept), 10),
        metadata=metadata,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(model.to_dict(), indent=2),
                        encoding="utf-8")

    print(f"\ntrained on {len(train):,} rows before {train_cut.date()}, "
          f"scored on {len(holdout):,} rows after")
    print(f"holdout: AUC {holdout_report['auc']:.4f} | log-loss "
          f"{holdout_report['log_loss']:.5f} | base {holdout_report['base_rate']:.4f} "
          f"-> top decile {holdout_report['top_decile_rate']:.4f} "
          f"(+{holdout_report['top_decile_lift_pp']:.2f} pp)")
    print(f"eligible: {eligible} ({metadata['eligibility_rule']})")
    print(f"wrote {args.out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
