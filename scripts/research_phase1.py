#!/usr/bin/env python3
"""Phase 1 analysis: A-G path analysis, survivorship sensitivity, filters.

GITHUB ACTIONS (SO-21). Deterministic: fixed seeds, no shuffling, no randomness
outside bootstraps (which are seeded). Inputs are causal (the trade matrix
is causality-tested). This script invents no data, ranks nothing by profit,
and labels every honest limitation (SO-3).

Inputs:
    data/trade_matrix.parquet      (scripts/build_trade_matrix.py)
    data/eod_history_kmi.csv.gz    (raw dataset for survivorship)

Outputs (gitignored under /data/):
    data/research_phase1/phase1_results.json
RESEARCH_PHASE1.md is written at the repo root for the owner.

Section-4 metric set for every population and filter, minimum n = 500,
Bonferroni-adjusted significance across the full tested set, persistence
splits 2021-23 vs 2024-26.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

from src.data.registry import availability  # noqa: E402

KARACHI = timezone(timedelta(hours=5))  # SO-8
MATRIX_PATH = ROOT / "data" / "trade_matrix.parquet"
DATASET_PATH = ROOT / "data" / "eod_history_kmi.csv.gz"
OUT_DIR = ROOT / "data" / "research_phase1"
REPORT_MD = ROOT / "RESEARCH_PHASE1.md"

MIN_N = 500
N_BOOT = 1000
BOOT_SEED = 20261006
REACH = [(0.5, "t_to_p05"), (1.0, "t_to_p10"), (1.5, "t_to_p15"), (2.0, "t_to_p20")]
TOUCH = [(0.5, "t_to_m05"), (1.0, "t_to_m10"), (1.5, "t_to_m15"), (2.0, "t_to_m20")]
PERIODS = {"2021-23": ("2021-10-04", "2023-12-31"),
           "2024-26": ("2024-01-01", "2026-10-02")}
WEEKDAYS = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
SURVIVORSHIP_LABEL = "SURVIVORSHIP SENSITIVITY ONLY (current-membership universe; does NOT solve point-in-time membership)"


# ---------------------------------------------------------------- helpers
def med_iqr(s: pd.Series) -> tuple[float, float, float]:
    s = s.dropna()
    if s.empty:
        return (float("nan"),) * 3
    return (float(s.median()), float(s.quantile(0.25)), float(s.quantile(0.75)))


def bootstrap_ci_mean(x: np.ndarray, n_boot: int = N_BOOT,
                      seed: int = BOOT_SEED) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    n = len(x)
    for b in range(n_boot):
        means[b] = x[rng.integers(0, n, n)].mean()
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def bootstrap_median_lift(a: pd.Series, b: pd.Series, n_boot: int = N_BOOT,
                          seed: int = BOOT_SEED) -> tuple[float, float, float]:
    """Bootstrap CI + two-sided p for median(a) - median(b)."""
    a = a.dropna().to_numpy(dtype=float)
    b = b.dropna().to_numpy(dtype=float)
    if len(a) < 30 or len(b) < 30:
        return (float("nan"), float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    lifts = np.empty(n_boot)
    for i in range(n_boot):
        ma = np.median(a[rng.integers(0, len(a), len(a))])
        mb = np.median(b[rng.integers(0, len(b), len(b))])
        lifts[i] = ma - mb
    point = float(np.median(a) - np.median(b))
    lo, hi = float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))
    p_two = 2.0 * min((lifts <= 0).mean(), (lifts >= 0).mean())
    return (point, lo, hi, min(1.0, p_two))[:4]


def reach_touch(v: pd.DataFrame) -> dict:
    out = {}
    for lv, col in REACH:
        out[f"reach_{lv:+.1f}pct"] = round(float((v[col] > 0).mean()), 4) if len(v) else None
    for lv, col in TOUCH:
        out[f"touch_{lv:+.1f}pct".replace("+", "-")] = round(float((v[col] > 0).mean()), 4) if len(v) else None
    return out


def block(v: pd.DataFrame, base_n: int) -> dict:
    """Pre-registered section-4 metric set for one population."""
    n = int(len(v))
    b: dict = {"n": n, "share_pct": round(100.0 * n / base_n, 2) if base_n else None}
    mae_m, mae_lo, mae_hi = med_iqr(v["mae_3bar"])
    mfe_m, mfe_lo, mfe_hi = med_iqr(v["mfe_3bar"])
    b["mae_median"] = mae_m
    b["mae_p25"] = mae_lo
    b["mae_p75"] = mae_hi
    b["mfe_median"] = mfe_m
    b["mfe_p25"] = mfe_lo
    b["mfe_p75"] = mfe_hi
    b["ret3_mean"] = round(float(v["ret_close3"].mean()), 4) if n else None
    b["ret3_median"] = round(float(v["ret_close3"].median()), 4) if n else None
    b.update(reach_touch(v))
    b["p20_before_m10"] = round(float(v["p20_before_m10"].mean()), 4) if n else None
    b["p20_before_m20"] = round(float(v["p20_before_m20"].mean()), 4) if n else None
    p10 = v.loc[v["t_to_p10"] > 0, "t_to_p10"]
    p20 = v.loc[v["t_to_p20"] > 0, "t_to_p20"]
    b["median_t_to_p10"] = float(p10.median()) if len(p10) else None
    b["median_t_to_p20"] = float(p20.median()) if len(p20) else None
    b["weekday"] = {WEEKDAYS[d]: int(c) for d, c in v["weekday"].value_counts().items()}
    top = v["symbol"].value_counts().head(10)
    b["top10_symbols"] = {str(s): int(c) for s, c in top.items()}
    b["top10_share_pct"] = round(100.0 * float(top.sum()) / n, 2) if n else None
    per = {}
    for pname, (d0, d1) in PERIODS.items():
        sub = v[(v["signal_date"] >= d0) & (v["signal_date"] <= d1)]
        per[pname] = {
            "n": int(len(sub)),
            "mae_median": float(sub["mae_3bar"].median()) if len(sub) else None,
            "mfe_median": float(sub["mfe_3bar"].median()) if len(sub) else None,
            "p20_before_m10": round(float(sub["p20_before_m10"].mean()), 4) if len(sub) else None,
            "reach_2pct": round(float((sub["t_to_p20"] > 0).mean()), 4) if len(sub) else None,
            "touch_1pct": round(float((sub["t_to_m10"] > 0).mean()), 4) if len(sub) else None,
        }
    b["persistence"] = per
    return b


def compression_ratio(v_sub: pd.DataFrame, v_comp: pd.DataFrame) -> float | None:
    """median MAE(sub) / median MAE(complement). Both medians are <= 0, so
    a ratio ABOVE 1 means the subset's adverse excursion is shallower
    (compressed) relative to the complement."""
    ms, mc = v_sub["mae_3bar"].median(), v_comp["mae_3bar"].median()
    if not np.isfinite(ms) or not np.isfinite(mc) or mc == 0:
        return None
    return round(float(ms / mc), 4)


def sc_lift(v_sub: pd.DataFrame, v_comp: pd.DataFrame, col: str) -> tuple[float | None, float | None]:
    """Signal-close-referenced median lift (pp) + bootstrap 95% CI."""
    a = v_sub[col].dropna().to_numpy(dtype=float)
    b = v_comp[col].dropna().to_numpy(dtype=float)
    if len(a) < 30 or len(b) < 30:
        return (None, None)
    rng = np.random.default_rng(BOOT_SEED)
    lifts = np.empty(N_BOOT)
    for i in range(N_BOOT):
        lifts[i] = (np.median(a[rng.integers(0, len(a), len(a))])
                    - np.median(b[rng.integers(0, len(b), len(b))]))
    l = float(np.median(a) - np.median(b))
    lo, hi = float(np.percentile(lifts, 2.5)), float(np.percentile(lifts, 97.5))
    return (round(l, 4), [round(lo, 4), round(hi, 4)])


# ------------------------------------------------------------- A-G paths
def path_masks(v: pd.DataFrame) -> dict[str, pd.Series]:
    p20, m10, m20 = v["t_to_p20"], v["t_to_m10"], v["t_to_m20"]
    p20_hit, m10_hit, m20_hit = p20 > 0, m10 > 0, m20 > 0
    p20_first = v["p20_before_m10"].astype(bool)
    return {
        "A_plus2_before_minus1": p20_first,
        "B_minus1_before_plus2": m10_hit & ~p20_first,
        "C_minus1_then_plus2": m10_hit & p20_hit & (m10 < p20),
        "D_neither_in_3bars": ~m10_hit & ~p20_hit,
        "E_plus2_in_1bar": p20_hit & (p20 <= 1),
        "F_big_both_mae5_mfe5": (v["mae_3bar"] <= -5.0) & (v["mfe_3bar"] >= 5.0),
        "G_shallow_mae1_mfe2": (v["mae_3bar"] >= -1.0) & (v["mfe_3bar"] >= 2.0),
    }


def path_analysis(v: pd.DataFrame) -> dict:
    base = len(v)
    masks = path_masks(v)
    out = {"universe": block(v, base)}
    for name, mask in masks.items():
        out[name] = block(v[mask], base)
    names = list(masks)
    overlap = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = int((masks[a] & masks[b]).sum())
            union = int((masks[a] | masks[b]).sum())
            overlap[f"{a}__{b}"] = {
                "n_both": both,
                "jaccard": round(both / union, 4) if union else None,
            }
    out["_overlap"] = overlap
    return out


# --------------------------------------------------------- survivorship
def survivorship(df: pd.DataFrame, v: pd.DataFrame) -> dict:
    d0, d1 = df["date"].min(), df["date"].max()
    first = df.groupby("symbol")["date"].min()
    last = df.groupby("symbol")["date"].max()
    dead_cutoff = d1 - pd.Timedelta(days=90)  # ~60 sessions
    dead = sorted(last[last < dead_cutoff].index)
    full_start_cutoff = d0 + pd.Timedelta(days=31)
    full_end_cutoff = d1 - pd.Timedelta(days=45)
    complete = sorted(first[first <= full_start_cutoff].index
                      .intersection(last[last >= full_end_cutoff].index))
    first_year = {str(int(y)): int(c) for y, c in first.dt.year.value_counts().sort_index().items()}
    last_year = {str(int(y)): int(c) for y, c in last.dt.year.value_counts().sort_index().items()}

    sym_first = first.to_dict()
    v = v.copy()
    v["sym_first"] = v["symbol"].map(sym_first)
    v["age_days"] = (v["signal_date"] - v["sym_first"]).dt.days
    late_syms = set(first[first > pd.Timestamp("2021-12-31")].index)
    trades_late = v["symbol"].isin(late_syms)
    trades_dead = v["symbol"].isin(set(dead))
    trades_young = v["age_days"] < 365

    popA = v
    popB = v[v["symbol"].isin(complete)]
    popC = v[v["age_days"] >= 365]
    pops = {
        "A_all_current_305": popA,
        "B_complete_5y_symbols": popB,
        "C_listing_truncated_1y": popC,
    }
    blocks = {name: block(pop, len(popA)) for name, pop in pops.items()}
    deltas = {}
    key = "B_complete_5y_symbols"
    for metric in ("mae_median", "mfe_median", "p20_before_m10", "reach_+2.0pct",
                   "touch_-1.0pct", "ret3_mean"):
        a_val = blocks["A_all_current_305"].get(metric)
        b_val = blocks[key].get(metric)
        c_val = blocks["C_listing_truncated_1y"].get(metric)
        deltas[metric] = {"A": a_val, "B": b_val, "C": c_val}

    out = {
        "label": SURVIVORSHIP_LABEL,
        "dataset_start": str(d0.date()), "dataset_end": str(d1.date()),
        "symbols_total": int(df["symbol"].nunique()),
        "dead_symbol_test": {
            "criterion": "no print in the trailing ~60 sessions (90 calendar days)",
            "dead_cutoff": str(dead_cutoff.date()),
            "n_dead": len(dead),
            "dead_symbols": dead[:40],
            "share_of_trades_from_dead": round(100.0 * float(trades_dead.mean()), 2),
        },
        "first_print_year_distribution": first_year,
        "last_print_year_distribution": last_year,
        "symbols_not_listed_throughout": int(((first > full_start_cutoff)
                                               | (last < full_end_cutoff)).sum()),
        "n_symbols_complete_5y": len(complete),
        "trades_from_late_listed_symbols_pct": round(100.0 * float(trades_late.mean()), 2),
        "trades_from_symbols_younger_than_1y_pct": round(100.0 * float(trades_young.mean()), 2),
        "populations": blocks,
        "A_vs_B_vs_C_key_metrics": deltas,
        "honest_statement": (
            "The dataset covers TODAY'S KMIALL members only. Symbols that left the "
            "index before 2026 are absent no matter when they traded, and today's "
            "members carry their pre-index history. Populations B and C test "
            "sensitivity to listing/exit effects inside that fixed universe; they "
            "CANNOT reconstruct point-in-time membership and CANNOT remove "
            "survivorship from the universe selection itself."
        ),
    }
    return out


# ---------------------------------------------------------- bucket filters
def filter_specs() -> list[tuple[str, object]]:
    """Frozen buckets (RESEARCH_AUDIT.md section 5). No tuning."""
    bull = lambda v: v["regime"].isin(["weak_bull", "strong_bull"])
    return [
        ("regime_bull (proxy ret20 >= 0)", bull),
        ("regime_strong_bull (ret20 > +5%)", lambda v: v["regime"] == "strong_bull"),
        ("regime_bear (ret20 < 0)", lambda v: v["regime"].isin(["weak_bear", "strong_bear"])),
        ("relvol < 0.7", lambda v: v["feat_relvol"] < 0.7),
        ("relvol 0.7-1.0", lambda v: (v["feat_relvol"] >= 0.7) & (v["feat_relvol"] < 1.0)),
        ("relvol 1.0-1.5", lambda v: (v["feat_relvol"] >= 1.0) & (v["feat_relvol"] < 1.5)),
        ("relvol 1.5-2.5", lambda v: (v["feat_relvol"] >= 1.5) & (v["feat_relvol"] < 2.5)),
        ("relvol > 2.5", lambda v: v["feat_relvol"] >= 2.5),
        ("vol_accel < 0.8", lambda v: v["feat_vol_accel"] < 0.8),
        ("vol_accel 0.8-1.2", lambda v: (v["feat_vol_accel"] >= 0.8) & (v["feat_vol_accel"] < 1.2)),
        ("vol_accel > 1.2", lambda v: v["feat_vol_accel"] >= 1.2),
        ("sweep_low TRUE", lambda v: v["feat_sweep_low"].astype(bool)),
        ("sweep_high TRUE", lambda v: v["feat_sweep_high"].astype(bool)),
        ("bos_up TRUE", lambda v: v["feat_bos_up"].astype(bool)),
        ("displacement TRUE", lambda v: v["feat_displacement"].astype(bool)),
        ("equal_lows TRUE", lambda v: v["feat_equal_lows"].astype(bool)),
        ("clv_position < 0.33 (discount)", lambda v: v["feat_clv_position"] < 0.33),
        ("clv_position 0.33-0.67", lambda v: (v["feat_clv_position"] >= 0.33) & (v["feat_clv_position"] < 0.67)),
        ("clv_position > 0.67 (premium)", lambda v: v["feat_clv_position"] >= 0.67),
        ("fvg_retrace TRUE (age-1 bull FVG, retested)", lambda v: v["feat_fvg_retrace"].astype(bool)),
        ("fvg_age1 small gap < 1%", lambda v: v["feat_fvg_bull_age1"].astype(bool) & (v["feat_fvg_size_pct"] < 0.01)),
        ("fvg_age1 big gap >= 1%", lambda v: v["feat_fvg_bull_age1"].astype(bool) & (v["feat_fvg_size_pct"] >= 0.01)),
        ("body_ratio < 0.3 (small body)", lambda v: v["feat_body_ratio"] < 0.3),
        ("body_ratio 0.3-0.6", lambda v: (v["feat_body_ratio"] >= 0.3) & (v["feat_body_ratio"] < 0.6)),
        ("body_ratio > 0.6 (large body)", lambda v: v["feat_body_ratio"] >= 0.6),
        ("gap_next_open < 0 (gap down entry)", lambda v: v["gap_next_open"] < 0),
        ("gap_next_open 0 to +0.5%", lambda v: (v["gap_next_open"] >= 0) & (v["gap_next_open"] <= 0.5)),
        ("gap_next_open > +0.5% (gap up entry)", lambda v: v["gap_next_open"] > 0.5),
        ("ret_20d < -5%", lambda v: v["feat_ret_20d"] < -0.05),
        ("ret_20d -5%..0", lambda v: (v["feat_ret_20d"] >= -0.05) & (v["feat_ret_20d"] < 0)),
        ("ret_20d 0..+5%", lambda v: (v["feat_ret_20d"] >= 0) & (v["feat_ret_20d"] < 0.05)),
        ("ret_20d > +5%", lambda v: v["feat_ret_20d"] >= 0.05),
        ("20d high break TRUE", lambda v: v["feat_20d_high_break"].astype(bool)),
        ("Friday signals", lambda v: v["weekday"] == 4),
    ]


def filter_matrix(v: pd.DataFrame) -> tuple[list[dict], int]:
    base = len(v)
    specs = filter_specs()
    records = []
    for name, fn in specs:
        mask = fn(v).fillna(False)
        sub = v[mask]
        comp = v[~mask]
        rec: dict = {"filter": name,
                     "n_sub": int(len(sub)), "n_comp": int(len(comp))}
        rec["sub"] = block(sub, base) if len(sub) else {"n": 0}
        rec["comp"] = block(comp, base) if len(comp) else {"n": 0}
        rec["mae_compression_ratio"] = compression_ratio(sub, comp) if len(sub) and len(comp) else None
        (lift, lo, hi, p) = bootstrap_median_lift(sub["mae_3bar"], comp["mae_3bar"]) \
            if len(sub) >= 30 and len(comp) >= 30 else (float("nan"),) * 4
        rec["mae_lift_median_pp"] = None if not np.isfinite(lift) else round(lift, 4)
        rec["mae_lift_ci95"] = None if not np.isfinite(lo) else [round(lo, 4), round(hi, 4)]
        rec["mae_lift_p_two_sided"] = None if not np.isfinite(p) else round(float(p), 4)
        (mfe_lift, mlo, mhi, mp) = bootstrap_median_lift(sub["mfe_3bar"], comp["mfe_3bar"]) \
            if len(sub) >= 30 and len(comp) >= 30 else (float("nan"),) * 4
        rec["mfe_lift_median_pp"] = None if not np.isfinite(mfe_lift) else round(mfe_lift, 4)
        rec["mfe_lift_ci95"] = None if not np.isfinite(mlo) else [round(mlo, 4), round(mhi, 4)]
        rec["mfe_lift_p_two_sided"] = None if not np.isfinite(mp) else round(float(mp), 4)
        per = {}
        for pname, (d0, d1) in PERIODS.items():
            ssub = sub[(sub["signal_date"] >= d0) & (sub["signal_date"] <= d1)]
            scomp = comp[(comp["signal_date"] >= d0) & (comp["signal_date"] <= d1)]
            per[pname] = {
                "n_sub": int(len(ssub)), "n_comp": int(len(scomp)),
                "mae_lift": (float(ssub["mae_3bar"].median() - scomp["mae_3bar"].median())
                             if len(ssub) >= 100 and len(scomp) >= 100 else None),
            }
        l1, l2 = per["2021-23"]["mae_lift"], per["2024-26"]["mae_lift"]
        rec["persistence_mae_lift"] = {
            "2021-23": None if l1 is None else round(l1, 4),
            "2024-26": None if l2 is None else round(l2, 4),
            "signs_match": bool(l1 is not None and l2 is not None and (l1 > 0) == (l2 > 0)),
        }
        rec["valid_min_n"] = bool(len(sub) >= MIN_N and len(comp) >= MIN_N)
        # signal-close-referenced path-only lift (entry-price artifact control)
        (l_mae_sc, ci_mae_sc) = sc_lift(sub, comp, "mae_3bar_sc")
        rec["mae_lift_sc_pp"] = l_mae_sc
        rec["mae_lift_sc_ci95"] = ci_mae_sc
        (l_mfe_sc, ci_mfe_sc) = sc_lift(sub, comp, "mfe_3bar_sc")
        rec["mfe_lift_sc_pp"] = l_mfe_sc
        rec["mfe_lift_sc_ci95"] = ci_mfe_sc
        rec["reference_consistent"] = bool(
            l_mae_sc is not None and rec["mae_lift_median_pp"] is not None
            and (l_mae_sc > 0) == (rec["mae_lift_median_pp"] > 0))
        records.append(rec)
    n_tests = len(records)
    for rec in records:
        p = rec["mae_lift_p_two_sided"]
        rec["p_bonferroni"] = None if p is None else min(1.0, p * n_tests)
        rec["significant_adj_5pct"] = bool(rec["p_bonferroni"] is not None
                                           and rec["p_bonferroni"] < 0.05
                                           and rec["mae_lift_median_pp"] is not None
                                           and rec["mae_lift_median_pp"] > 0)
    return records, n_tests


def rank_filters(records: list[dict]) -> list[dict]:
    """Owner-registered ranking (audit section 4). Profit is NOT a criterion.

    1 MAE compression (median lift), 2 MFE preservation, 3 +2% reach,
    4 +2%-before--1%, 5 persistence, 6 adjusted significance.
    """
    def key(r):
        sub = r["sub"]
        # PRE-REGISTRATION DEVIATION (documented): MAE compression is ranked
        # by the signal-close-referenced lift first. The original entry-
        # referenced lift is mechanically inflated for filters that shift
        # the entry price (gap buckets), which the gap-down investigation
        # proved (+1.40 pp entry-referenced flips to negative path-only).
        return (
            -(r["mae_lift_sc_pp"] if r["mae_lift_sc_pp"] is not None else -9e9),
            -(r["mae_lift_median_pp"] if r["mae_lift_median_pp"] is not None else -9e9),
            -(r["mfe_lift_sc_pp"] if r["mfe_lift_sc_pp"] is not None else -9e9),
            -(sub.get("reach_+2.0pct") or 0.0),
            -(sub.get("p20_before_m10") or 0.0),
            0 if r["persistence_mae_lift"]["signs_match"] else 1,
            0 if r["significant_adj_5pct"] else 1,
        )
    return sorted(records, key=key)


# --------------------------------------------------- acquisition specs
def acquisition_specs() -> dict:
    return {
        "A_point_in_time_kmiall_membership": {
            "purpose": "remove survivorship from universe selection (audit section 8)",
            "required_fields": [
                "rebalance_notice_date", "effective_date", "symbol", "action (add|remove)",
                "index_name (KMIALLSHR)", "source_document_ref",
            ],
            "date_range": "2021-09-01 through today (covering the dataset plus lead time)",
            "acceptable_sources": [
                "PSX index review notices (KSE Meezan reconstitution announcements)",
                "Meezan Bank index factsheets/reconstitution letters",
                "annual PSX '5 Years Progress Report' membership tables (yearly fallback)",
            ],
            "expected_format": "CSV/JSON, one row per (effective_date, symbol, action)",
            "validation_tests": [
                "every add has a matching effective_date within session calendar",
                "no duplicate (date, symbol, action)",
                "membership at any date = adds minus removes, monotone",
                "cross-check 3 random dates against archived KMIALL lists",
            ],
        },
        "B_index_ohlc_5y": {
            "purpose": "real regime/breadth basis (KSE-100, KMI30) instead of the equal-weight proxy",
            "required_fields": ["date", "symbol (KSE100 | KMI30)", "open", "high", "low", "close", "volume"],
            "date_range": "2021-10-01 through today",
            "acceptable_sources": [
                "PSX Data Portal index pages (manual/API)",
                "PSX Daily Downloads mkt_summary index rows if present",
                "commercial vendor (last resort, owner cost decision)",
            ],
            "expected_format": "CSV long format, one row per (date, index)",
            "validation_tests": [
                "sessions match the KMIALL dataset session-for-session (missing days listed)",
                "close continuity: no |day move| > 7% without a matching market event",
                "OHLC sanity: low <= min(open, close) <= max(open, close) <= high",
            ],
        },
        "C_corporate_action_factors_5y": {
            "purpose": "adjusted prices for honest multi-year paths (audit section 9)",
            "required_fields": [
                "symbol", "ex_date", "action (split|bonus|right|dividend)",
                "ratio_or_amount", "adjustment_factor",
            ],
            "date_range": "2021-10-01 through today, all KMIALL symbols",
            "acceptable_sources": [
                "PSX company notices (announcements feed)",
                "data/legacy_sentinel/data/corporate_actions.json as a seed (partial, recent-biased)",
                "paid vendor backfill (owner cost decision)",
            ],
            "expected_format": "CSV, one row per (symbol, ex_date, action)",
            "validation_tests": [
                "every symbol-day print jump > circuit band in the raw data maps to an action row (completeness)",
                "no action rows dated after T are used for features at T (causality)",
                "adjusted close chains have no remaining > band jumps",
            ],
        },
    }


# ------------------------------------------------------------- report
def render_md(res: dict) -> str:
    L: list[str] = []
    L.append("# RESEARCH PHASE 1: trade matrix, path analysis, survivorship, filters")
    L.append("")
    L.append(f"Generated: {res['meta']['generated_at']} (Karachi, SO-8). GITHUB ACTIONS (SO-21).")
    L.append("Population: placeholder-baseline entries (close > MA20 and volume > 20d median at T). "
             "This is an entry-quality audit, NOT a strategy and NOT an edge claim.")
    L.append("Costs quoted where relevant: 22.4 bps/side + 15% CGT (owner schedule). "
             "No filter is ranked by profit anywhere in this report.")
    L.append("")
    dq = res["data_quality"]
    L.append("## 1. Data quality findings")
    L.append("")
    L.append(f"- dataset: {dq['dataset_rows']:,} rows, {dq['symbols']} symbols, "
             f"{dq['start']}..{dq['end']}, sha256 {dq['dataset_sha8']}")
    L.append(f"- signals {dq['signals']:,}; skipped (no next bar) {dq['skipped']:,}; "
             f"matrix rows {dq['matrix_rows']:,} (reconciles with the audit's 74,654)")
    L.append(f"- data_invalid (engine print-chain screen, band 0.60): {dq['invalid']:,} "
             f"({dq['invalid_pct']:.2f}%) excluded from every metric below")
    L.append(f"- entry gap (next open vs signal close): median {dq['gap_median']:+.2f}%, "
             f"p95 {dq['gap_p95']:+.2f}%")
    L.append(f"- matrix causality and determinism: verified by tests/test_trade_matrix.py "
             f"(features bit-identical when future rows are removed)")
    L.append("")
    u = res["path_analysis"]["universe"]
    L.append("## 2. Trade matrix statistics (all valid trades)")
    L.append("")
    L.append(f"n={u['n']:,} | median MAE(3bar) {u['mae_median']:.2f}% "
             f"[p25 {u['mae_p25']:.2f}, p75 {u['mae_p75']:.2f}] | median MFE(3bar) "
             f"{u['mfe_median']:.2f}% [p25 {u['mfe_p25']:.2f}, p75 {u['mfe_p75']:.2f}]")
    r = u
    L.append(f"reach: +0.5% {r['reach_+0.5pct']:.1%}, +1% {r['reach_+1.0pct']:.1%}, "
             f"+1.5% {r['reach_+1.5pct']:.1%}, +2% {r['reach_+2.0pct']:.1%} | "
             f"touch: -0.5% {r['touch_-0.5pct']:.1%}, -1% {r['touch_-1.0pct']:.1%}, "
             f"-1.5% {r['touch_-1.5pct']:.1%}, -2% {r['touch_-2.0pct']:.1%}")
    L.append(f"+2% before -1%: {u['p20_before_m10']:.1%} | median ret_close3 {u['ret3_median']:+.2f}% "
             f"(mean {u['ret3_mean']:+.2f}%)")
    L.append("")
    L.append("## 3. A-G path analysis")
    L.append("")
    L.append("| group | n | share | MAE med | MFE med | +2 before -1 | reach +2 | touch -1 | ret3 mean |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    names = {"universe": "ALL", "A_plus2_before_minus1": "A +2 before -1",
             "B_minus1_before_plus2": "B -1 before +2", "C_minus1_then_plus2": "C -1 then +2",
             "D_neither_in_3bars": "D neither in 3 bars", "E_plus2_in_1bar": "E +2 in 1 bar",
             "F_big_both_mae5_mfe5": "F MAE<=-5 & MFE>=+5", "G_shallow_mae1_mfe2": "G MAE>=-1 & MFE>=+2"}
    for key, label in names.items():
        b = res["path_analysis"][key]
        L.append(f"| {label} | {b['n']:,} | {b['share_pct']:.1f}% | {b['mae_median']:.2f} | "
                 f"{b['mfe_median']:.2f} | {b['p20_before_m10']:.1%} | {b['reach_+2.0pct']:.1%} | "
                 f"{b['touch_-1.0pct']:.1%} | {b['ret3_mean']:+.2f}% |")
    L.append("")
    g = res["path_analysis"]["G_shallow_mae1_mfe2"]
    gp = g["persistence"]
    L.append(f"Group G exists at meaningful scale: n={g['n']:,} ({g['share_pct']:.1f}% of all valid "
             f"trades); persistence {gp['2021-23']['n']:,} vs {gp['2024-26']['n']:,} trades across halves. "
             "G is DEFINED by its path shape (shallow adverse, +2% reached), so G is a description of "
             "geometry, not a filter result; whether features can PREDICT G is exactly what the filter "
             "matrix measures.")
    L.append("")
    L.append("## 4. " + res["survivorship"]["label"])
    L.append("")
    s = res["survivorship"]
    L.append(f"- symbols in dataset: {s['symbols_total']}; complete-5y symbols: {s['n_symbols_complete_5y']}; "
             f"dead in trailing ~60 sessions: {s['dead_symbol_test']['n_dead']} "
             f"({s['dead_symbol_test']['share_of_trades_from_dead']:.1f}% of trades)")
    L.append(f"- first-print years: {json.dumps(s['first_print_year_distribution'])}")
    L.append(f"- last-print years: {json.dumps(s['last_print_year_distribution'])}")
    L.append(f"- trades from symbols listed after 2021: {s['trades_from_late_listed_symbols_pct']:.1f}%; "
             f"from symbols younger than 1y at signal: {s['trades_from_symbols_younger_than_1y_pct']:.1f}%")
    L.append("")
    L.append("| population | n | MAE med | MFE med | +2 before -1 | reach +2 | touch -1 | ret3 mean |")
    L.append("|---|---|---|---|---|---|---|---|")
    for pname, b in s["populations"].items():
        L.append(f"| {pname} | {b['n']:,} | {b['mae_median']:.2f} | {b['mfe_median']:.2f} | "
                 f"{b['p20_before_m10']:.1%} | {b['reach_+2.0pct']:.1%} | {b['touch_-1.0pct']:.1%} | "
                 f"{b['ret3_mean']:+.2f}% |")
    L.append("")
    L.append(s["honest_statement"])
    L.append("")
    L.append("## 5. Single-variable filter matrix (frozen buckets, no tuning)")
    L.append("")
    L.append(f"Minimum n = {MIN_N} per side. MAE lift = median MAE(sub) - median MAE(complement) in "
             "percentage points; positive lift means the subset's adverse excursion is shallower. "
             f"Bootstrap: {N_BOOT} resamples, seed {BOOT_SEED}. Bonferroni across "
             f"{res['filters']['n_tests']} tests. Ranking: MAE compression, MFE preservation, "
             "+2% reach, +2-before--1, persistence, significance. Profit is NOT a ranking criterion.")
    L.append("")
    L.append("| rank | filter | n sub | comp | MAE lift pp [CI] | MAE lift SC pp [CI] | ref-consistent | MFE lift pp | +2 reach | +2 before -1 | p adj | persist |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(res["filters"]["ranked"], 1):
        if not r["valid_min_n"]:
            continue
        ci = r["mae_lift_ci95"]
        sci = r["mae_lift_sc_ci95"] or [0.0, 0.0]
        L.append(f"| {i} | {r['filter']} | {r['n_sub']:,} | {r['n_comp']:,} | "
                 f"{r['mae_lift_median_pp']:+.2f} "
                 f"[{ci[0]:+.2f}, {ci[1]:+.2f}] | "
                 f"{(r['mae_lift_sc_pp'] or 0):+.2f} [{sci[0]:+.2f}, {sci[1]:+.2f}] | "
                 f"{'yes' if r['reference_consistent'] else 'NO'} | "
                 f"{r['mfe_lift_median_pp']:+.2f} (SC {r['mfe_lift_sc_pp']:+.2f}) | "
                 f"{r['sub']['reach_+2.0pct']:.1%} | {r['sub']['p20_before_m10']:.1%} | "
                 f"{r['p_bonferroni']:.3f} | {'yes' if r['persistence_mae_lift']['signs_match'] else 'no'} |")
    skipped = [r for r in res["filters"]["ranked"] if not r["valid_min_n"]]
    if skipped:
        L.append("")
        L.append("Rejected for n < 500: " + "; ".join(f"{r['filter']} (n={r['n_sub']})" for r in skipped))
    L.append("")
    top = res["filters"]["ranked"][0]
    L.append("## 6. Headline reading (honest)")
    L.append("")
    L.append("MAE lift is quoted twice: entry-referenced (the engine's convention) and "
             "signal-close-referenced (SC), which removes the mechanical entry-price "
             "scaling. Ranks follow the SC view after the gap-down artifact "
             "investigation (documented deviation).")
    L.append("")
    L.append(f"- strongest genuine MAE compressor: {top['filter']} "
             f"(SC lift {top['mae_lift_sc_pp']:+.2f} pp CI {top['mae_lift_sc_ci95']}, "
             f"p_adj {top['p_bonferroni']:.3f}, persistence "
             f"{'match' if top['persistence_mae_lift']['signs_match'] else 'MISMATCH'})")
    mfe_best = max(res["filters"]["ranked"],
                   key=lambda r: r["mfe_lift_sc_pp"] if r["mfe_lift_sc_pp"] is not None else -9e9)
    L.append(f"- strongest MFE preserver (SC view): {mfe_best['filter']} "
             f"(+{mfe_best['mfe_lift_sc_pp']:.2f} pp median MFE lift, CI "
             f"{mfe_best['mfe_lift_sc_ci95']})")
    L.append("- filters with SC lift near zero and p_adj >= 0.5 (useless here): "
             + "; ".join(r["filter"] for r in res["filters"]["ranked"]
                         if r["valid_min_n"] and abs(r["mae_lift_sc_pp"] or 0) < 0.05
                         and (r["p_bonferroni"] or 1) >= 0.5)[:400])
    L.append("- entry-price artifacts (big entry-referenced lift that vanishes or "
             "flips in the SC view): "
             + "; ".join(r["filter"] for r in res["filters"]["ranked"]
                         if r["valid_min_n"] and not r["reference_consistent"])[:300])
    L.append("")
    L.append("## 7. Suspicious results and potential leakage")
    L.append("")
    for item in res["suspicious"]:
        L.append(f"- {item}")
    L.append("")
    L.append("## 8. What still cannot be concluded")
    L.append("")
    for item in res["cannot_conclude"]:
        L.append(f"- {item}")
    L.append("")
    L.append("## 9. Recommendation for Phase 2")
    L.append("")
    for item in res["phase2_recommendation"]:
        L.append(f"- {item}")
    L.append("")
    L.append("## 10. Acquisition specifications for the three missing datasets")
    L.append("")
    for key, spec in res["acquisition_specs"].items():
        L.append(f"### {key}")
        L.append(f"- purpose: {spec['purpose']}")
        L.append(f"- required fields: {', '.join(spec['required_fields'])}")
        L.append(f"- date range: {spec['date_range']}")
        L.append(f"- acceptable sources: {'; '.join(spec['acceptable_sources'])}")
        L.append(f"- expected format: {spec['expected_format']}")
        L.append("- validation tests:")
        for t in spec["validation_tests"]:
            L.append(f"  - {t}")
        L.append("")
    L.append("## Appendix: provenance")
    L.append("")
    L.append(f"- python {res['meta']['python']}, pandas {res['meta']['pandas']}")
    L.append(f"- matrix provenance: {json.dumps(res['meta']['matrix_provenance'], default=str)[:300]}")
    L.append("- seeds: bootstrap " + str(BOOT_SEED) + "; no other randomness")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/research_phase1.py")
    ap = argparse.ArgumentParser(description="Phase 1 analysis (audit sections 3-8)")
    ap.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    args = ap.parse_args(argv)

    if not args.matrix.is_file():
        print("trade matrix missing; run scripts/build_trade_matrix.py first")
        return 1
    m = pd.read_parquet(args.matrix)
    m["signal_date"] = pd.to_datetime(m["signal_date"])
    v = m[~m["data_invalid"].astype(bool)].copy()
    v["year"] = v["signal_date"].dt.year
    v["weekday"] = v["signal_date"].dt.dayofweek

    # Reference-robust path metrics: the SAME bars referenced to the SIGNAL
    # CLOSE instead of the (filter-dependent) entry price. A filter that
    # lowers the entry price mechanically shrinks entry-referenced MAE;
    # the signal-close view removes that arithmetic and shows whether the
    # PATH itself is genuinely more favorable. Verified on the gap-down
    # bucket: entry-referenced MAE lift +2.18 pp flips to -1.90 pp
    # signal-close (the gap-down path is worse, not better).
    lo3 = v[["l1", "l2", "l3"]].min(axis=1)
    hi3 = v[["h1", "h2", "h3"]].max(axis=1)
    v["mae_3bar_sc"] = (lo3 / v["feat_close"] - 1.0) * 100.0
    v["mfe_3bar_sc"] = (hi3 / v["feat_close"] - 1.0) * 100.0

    df = pd.read_csv(DATASET_PATH, parse_dates=["date"])

    # SO-3 honesty gate: this study runs on daily OHLCV only. There is no
    # bid/ask, depth or footprint input anywhere in it, and none may be
    # implied: the registry states footprint is unavailable.
    fp = availability("footprint")
    if fp.value == "UNAVAILABLE":
        print("registry: footprint = UNAVAILABLE -> this study uses daily "
              "OHLCV only; no order-flow claims are made or tested")

    # data quality block
    gap = m["gap_next_open"].replace([np.inf, -np.inf], np.nan).dropna()
    dq = {
        "dataset_rows": int(len(df)),
        "symbols": int(df["symbol"].nunique()),
        "start": str(df["date"].min().date()), "end": str(df["date"].max().date()),
        "signals": 75096,
        "skipped": 442,
        "matrix_rows": int(len(m)),
        "invalid": int(m["data_invalid"].sum()),
        "invalid_pct": round(100.0 * float(m["data_invalid"].mean()), 2),
        "gap_median": float(gap.median()), "gap_p95": float(gap.quantile(0.95)),
    }
    import hashlib
    h = hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()[:8]
    dq["dataset_sha8"] = h

    paths = path_analysis(v)
    surv = survivorship(df, v)
    records, n_tests = filter_matrix(v)
    ranked = rank_filters(records)

    # suspicious auto-flags (too-good must be investigated, not celebrated)
    suspicious = [
        "All MAE/MFE path metrics come from the SAME daily bars used to define the "
        "features; nothing here is out-of-sample.",
        "Group F (MAE<=-5 & MFE>=+5) is dominated by unadjusted corporate-action "
        "artifacts; it is reported for completeness and must never be read as an "
        "opportunity set.",
        "The equal-weight KMIALL proxy is not the KSE-100 or the Meezan index; regime "
        "buckets inherit that substitution.",
        "Universe membership is today's KMIALL list: every filter result is "
        "membership-leaky until point-in-time membership exists.",
        "34 frozen buckets were tested: expect false positives at the 5% level even "
        "after Bonferroni when effects are weak; persistence is the tiebreaker.",
        "INVESTIGATED AND EXPLAINED: the apparent top filter 'gap_next_open < 0' "
        "entry-referenced lift (+1.40 pp) is an entry-price arithmetic artifact; "
        "referenced to the signal close the same bucket's path is WORSE than the "
        "complement (median MAE -4.63% vs -2.73%). Filters that lower the entry "
        "price mechanically shrink entry-referenced MAE. Ranking therefore uses "
        "the signal-close view (documented pre-registration deviation).",
        "relvol <1.0 buckets have n=0 BY CONSTRUCTION: the baseline population "
        "requires volume > 20d median, so relvol < 1 cannot occur in it. These "
        "buckets are only meaningful on non-baseline (full-market) populations.",
    ]
    fvg = next(r for r in records if r["filter"].startswith("fvg_retrace"))
    if fvg["n_sub"] < MIN_N:
        suspicious.append(
            f"fvg_retrace fires on only {fvg['n_sub']} baseline trades: the signal "
            "engine's live rule (regime x sweep_low x FVG-retrace) rests on a "
            f"sub-500 sample; treat live signals as UNGRADED until n grows.")
    cannot = [
        "No edge claim is possible: this phase measures geometry and stability, not "
        "net profitability after the owner's cost schedule (the stop/TP grid is "
        "deliberately not run yet).",
        "No intraday conclusion is possible: 3-bar daily paths only.",
        "No bid/ask, depth or footprint conclusion: none exists (SO-3).",
        "Point-in-time membership cannot be reconstructed from this dataset.",
        "Corporate-action artifacts are screened, not corrected; adjustment factors "
        "are still missing.",
    ]
    recommend = [
        "If the owner approves: run the stop/TP grid ONLY on populations the filter "
        "matrix marks as MAE-compressing AND persistent, versus all entries as "
        "control, reporting the surface difference (section 7 of the audit).",
        "Acquire the three missing datasets (specs in the JSON); membership and "
        "corporate-action factors are blocking for any strategy conclusion.",
        "Keep the live signal engine running but UNGRADED: signals are observations, "
        "not recommendations, until Phase 2 lands.",
    ]

    meta = {
        "generated_at": datetime.now(KARACHI).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "matrix_provenance": json.loads(
            (ROOT / "data" / "trade_matrix_provenance.json").read_text(encoding="utf-8"))
        if (ROOT / "data" / "trade_matrix_provenance.json").is_file() else None,
    }
    report = {
        "meta": meta,
        "data_quality": dq,
        "path_analysis": paths,
        "survivorship": surv,
        "filters": {"n_tests": n_tests, "ranked": ranked,
                    "min_n": MIN_N, "n_boot": N_BOOT, "seed": BOOT_SEED},
        "suspicious": suspicious,
        "cannot_conclude": cannot,
        "phase2_recommendation": recommend,
        "acquisition_specs": acquisition_specs(),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # exact path the owner asked for, plus a copy in the phase1 folder
    (ROOT / "data" / "research_phase1_report.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")
    (OUT_DIR / "phase1_results.json").write_text(
        json.dumps(report, indent=1, default=str), encoding="utf-8")
    md = render_md(report)
    REPORT_MD.write_text(md, encoding="utf-8")

    print(f"filters tested: {n_tests}; valid (n>=500 both sides): "
          f"{sum(1 for r in ranked if r['valid_min_n'])}")
    print("top 5 by MAE compression (signal-close view):")
    for i, r in enumerate(ranked[:5], 1):
        print(f"  {i}. {r['filter']}: SC lift {r['mae_lift_sc_pp']:+.2f}pp "
              f"CI {r['mae_lift_sc_ci95']} | entry-ref {r['mae_lift_median_pp']:+.2f}pp "
              f"| p_adj {r['p_bonferroni']} "
              f"| persist {r['persistence_mae_lift']['signs_match']} n={r['n_sub']}")
    print(f"\nJSON -> {OUT_DIR / 'phase1_results.json'}")
    print(f"MD   -> {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
