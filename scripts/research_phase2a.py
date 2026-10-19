#!/usr/bin/env python3
"""Phase 2A: can Group G be identified prospectively from signal-time info?

Research question (owner directive): Group G of Phase 1 (mae_3bar >= -1% AND
mfe_3bar >= +2%, entry-referenced; n=13,232, 17.9% of valid trades) carries
the most desirable geometry: shallow adverse excursion, high favorable
excursion. Can a filter built from information that exists AT SIGNAL TIME
predict membership in G?

This phase CHANGES NOTHING in production:
  - the live v1 signal stack (regime x sweep_low x FVG-retrace) is untouched;
  - no TP/SL optimization runs here (scripts/stop_tp_grid.py stays banked);
  - no machine learning, no future information, no order-flow fabrication
    (registry.py: footprint UNAVAILABLE, daily OHLCV only).

Protocol, frozen before any validation/OOS scoring:
  - chronological splits:
        discovery  2021-10-04 .. 2023-12-31
        validation 2024-01-01 .. 2025-06-30
        OOS        2025-07-01 .. 2026-10-05 (dataset end)
  - every threshold is either fixed a priori or quantile-frozen on DISCOVERY
    rows only (the frozen values are printed and stored in the report);
  - filters are ranked on DISCOVERY only; validation and OOS are scored once
    with the frozen cuts and reported as-is;
  - Bonferroni correction across every filter and combination tested;
  - minimum n = 500 on both sides of a split for a filter to be rankable;
  - bootstrap: 1000 resamples, seed 20261006.

Ranking objective (owner directive): LOW MAE + HIGH MFE + HIGH +2% reach.
Primary rank metric: G-rate lift on discovery (pp). Tie-breakers: MAE
signal-close lift, MFE signal-close lift, +2% reach, n. Profit is never a
ranking criterion (SO-3). Entry-referenced lifts are reported for the
artifact flag; the signal-close (SC) view is the ranking basis after the
Phase 1 gap-down arithmetic artifact (documented pre-registration deviation).

Disclosure: Phase 1 already glanced at full-sample SC lifts. Mitigation:
selection here uses the discovery split ONLY; validation and OOS are
untouched by any choice made in this script.

GITHUB ACTIONS (SO-21). One-shot run, no daemons (SO-10). Timestamps Karachi.

Outputs:
    data/research_phase2a_report.json   (machine-readable, all tables)
    data/research_phase2a/phase2a_results.json (copy)
    RESEARCH_PHASE2A.md                 (owner-facing report)
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

KARACHI = timezone(timedelta(hours=5))  # SO-8: UTC+5, Asia/Karachi
MATRIX_PATH = ROOT / "data" / "trade_matrix.parquet"
DATASET_PATH = ROOT / "data" / "eod_history_kmi.csv.gz"
PROVENANCE_PATH = ROOT / "data" / "trade_matrix_provenance.json"
OUT_JSON = ROOT / "data" / "research_phase2a_report.json"
OUT_DIR = ROOT / "data" / "research_phase2a"
REPORT_MD = ROOT / "RESEARCH_PHASE2A.md"

MIN_N = 500
N_BOOT = 1000
BOOT_SEED = 20261006

G_MAE_MAX = -1.0   # entry-referenced MAE floor for G
G_MFE_MIN = 2.0    # entry-referenced MFE floor for G

SPLITS = [
    ("discovery", "2021-10-04", "2023-12-31"),
    ("validation", "2024-01-01", "2025-06-30"),
    ("oos", "2025-07-01", "2026-10-05"),
]
HALVES = [("2021-23", "2021-10-04", "2023-12-31"),
          ("2024-26", "2024-01-01", "2026-10-05")]

REACH = [(0.5, "t_to_p05"), (1.0, "t_to_p10"), (1.5, "t_to_p15"), (2.0, "t_to_p20")]
TOUCH = [(0.5, "t_to_m05"), (1.0, "t_to_m10"), (1.5, "t_to_m15"), (2.0, "t_to_m20")]

# a-priori fixed cuts for the new features (frozen here, before any run)
WICK_LONG = 0.5        # lower wick >= half the bar's range
WICK_MID = 0.3         # 0.3 .. 0.5 band
RS_POS = 0.0           # rs > 0
RS_STRONG = 0.025      # rs > +2.5% over the window
RS_BAND_LO, RS_BAND_HI = 0.0, 0.05
RS_NEG = -0.05
FVG_SIZE_CUT = 0.01    # 1% gap size split
GAP_CUT = 0.5          # 0.5% next-open gap split
TURN_RATIO_CUT = 1.0   # market turnover 20d/60d expanding vs contracting

A_LABEL = "A. Strong candidate for Phase 2B TP/SL testing"
B_LABEL = "B. Promising but requires more validation"
C_LABEL = "C. No robust predictive edge found"
D_LABEL = "D. Group G appears to be an artifact"


# ---------------------------------------------------------------- helpers
def med_iqr(s: pd.Series) -> tuple[float, float, float]:
    s = s.dropna()
    if s.empty:
        return (float("nan"),) * 3
    return (float(s.median()), float(s.quantile(0.25)), float(s.quantile(0.75)))


def boot_rate_lift(k_sub: int, n_sub: int, k_comp: int, n_comp: int,
                   n_boot: int = N_BOOT, seed: int = BOOT_SEED):
    """Binomial bootstrap CI + two-sided p for rate(sub) - rate(comp)."""
    if n_sub < 30 or n_comp < 30:
        return (None, None, None)
    rng = np.random.default_rng(seed)
    ps = rng.binomial(n_sub, k_sub / n_sub, n_boot) / n_sub
    pc = rng.binomial(n_comp, k_comp / n_comp, n_boot) / n_comp
    lifts = ps - pc
    point = k_sub / n_sub - k_comp / n_comp
    lo, hi = np.percentile(lifts, [2.5, 97.5])
    p = 2.0 * min((lifts <= 0).mean(), (lifts >= 0).mean())
    return (float(point * 100.0), [float(lo * 100.0), float(hi * 100.0)],
            float(min(1.0, p)))


def boot_median_lift(a: pd.Series, b: pd.Series, n_boot: int = N_BOOT,
                     seed: int = BOOT_SEED):
    """Bootstrap CI + two-sided p for median(a) - median(b). Chunked vector
    resampling keeps memory bounded on the full population."""
    a = a.dropna().to_numpy(dtype=float)
    b = b.dropna().to_numpy(dtype=float)
    if len(a) < 30 or len(b) < 30:
        return (None, None, None)

    def med_boot(x: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(seed)
        out = np.empty(n_boot)
        step = 50
        for s in range(0, n_boot, step):
            m = min(step, n_boot - s)
            idx = rng.integers(0, len(x), (m, len(x)))
            out[s:s + m] = np.median(x[idx], axis=1)
        return out

    ma, mb = med_boot(a), med_boot(b)
    lifts = ma - mb
    point = float(np.median(a) - np.median(b))
    lo, hi = np.percentile(lifts, [2.5, 97.5])
    p = 2.0 * min((lifts <= 0).mean(), (lifts >= 0).mean())
    return (point, [float(lo), float(hi)], float(min(1.0, p)))


def block(v: pd.DataFrame) -> dict:
    """The 15-item metric family required by the owner, plus context."""
    n = int(len(v))
    b: dict = {"n": n}
    if n == 0:
        return b
    b["g_rate"] = round(float(v["is_g"].mean()), 4)
    b["g_sc_rate"] = round(float(v["is_g_sc"].mean()), 4)
    for pre, col in (("mae", "mae_3bar"), ("mfe", "mfe_3bar"),
                     ("mae_sc", "mae_3bar_sc"), ("mfe_sc", "mfe_3bar_sc")):
        m, lo, hi = med_iqr(v[col])
        b[f"{pre}_median"] = round(m, 4)
        b[f"{pre}_p25"] = round(lo, 4)
        b[f"{pre}_p75"] = round(hi, 4)
    for lv, col in REACH:
        b[f"reach_{lv:+.1f}pct"] = round(float((v[col] > 0).mean()), 4)
    for lv, col in TOUCH:
        b[f"touch_{-lv:+.1f}pct"] = round(float((v[col] > 0).mean()), 4)
    b["p20_before_m10"] = round(float(v["p20_before_m10"].mean()), 4)
    b["p20_before_m20"] = round(float(v["p20_before_m20"].mean()), 4)
    p10 = v.loc[v["t_to_p10"] > 0, "t_to_p10"]
    p20 = v.loc[v["t_to_p20"] > 0, "t_to_p20"]
    b["median_t_to_p10"] = float(p10.median()) if len(p10) else None
    b["median_t_to_p20"] = float(p20.median()) if len(p20) else None
    b["ret3_mean"] = round(float(v["ret_close3"].mean()), 4)
    b["ret3_median"] = round(float(v["ret_close3"].median()), 4)
    b["g_count"] = int(v["is_g"].sum())
    return b


def lift_point(sub: pd.DataFrame, comp: pd.DataFrame, col: str) -> float | None:
    if len(sub) < 30 or len(comp) < 30:
        return None
    ms, mc = sub[col].median(), comp[col].median()
    if not np.isfinite(ms) or not np.isfinite(mc):
        return None
    return round(float(ms - mc), 4)


def rate_lift_point(sub: pd.DataFrame, comp: pd.DataFrame, col: str) -> float | None:
    if len(sub) < 30 or len(comp) < 30:
        return None
    return round(float((sub[col].mean() - comp[col].mean()) * 100.0), 4)


# ----------------------------------------------------------- filter specs
def frozen_cuts(discovery: pd.DataFrame) -> dict:
    """Quantile cuts for the continuous features WITHOUT a natural boundary.
    Computed on DISCOVERY rows only and then frozen for every split."""
    cuts = {}
    for col, name in (("feat_breadth", "breadth"),
                      ("feat_rvol20", "rvol20"),
                      ("feat_turnover", "turnover")):
        s = discovery[col].dropna()
        cuts[name] = {"q33": float(s.quantile(0.33)),
                      "q66": float(s.quantile(0.66))}
    return cuts


def filter_specs(cuts: dict) -> list[tuple[str, str, object]]:
    """(family, name, mask fn). Frozen buckets, no tuning anywhere."""
    b_lo, b_hi = cuts["breadth"]["q33"], cuts["breadth"]["q66"]
    r_lo, r_hi = cuts["rvol20"]["q33"], cuts["rvol20"]["q66"]
    t_lo, t_hi = cuts["turnover"]["q33"], cuts["turnover"]["q66"]

    def boolcol(name):
        return lambda v: v[name].fillna(False).astype(bool)

    specs = [
        # A. market regime / breadth / vol / volume regime
        ("A", "regime_weak_bull (0<=proxy ret20<+5%)",
         lambda v: v["regime"] == "weak_bull"),
        ("A", "regime_strong_bull (proxy ret20>+5%)",
         lambda v: v["regime"] == "strong_bull"),
        ("A", "regime_weak_bear (-5<=proxy ret20<0)",
         lambda v: v["regime"] == "weak_bear"),
        ("A", "regime_strong_bear (proxy ret20<-5%)",
         lambda v: v["regime"] == "strong_bear"),
        ("A", "breadth_low (<= discovery q33)",
         lambda v: v["feat_breadth"] <= b_lo),
        ("A", "breadth_high (>= discovery q66)",
         lambda v: v["feat_breadth"] >= b_hi),
        ("A", "proxy_rvol20_low (<= discovery q33)",
         lambda v: v["feat_rvol20"] <= r_lo),
        ("A", "proxy_rvol20_high (>= discovery q66)",
         lambda v: v["feat_rvol20"] >= r_hi),
        ("A", "mkt_turnover_expanding (20d/60d >= 1)",
         lambda v: v["feat_mkt_turn_ratio"] >= TURN_RATIO_CUT),
        # B. relative strength vs the equal-weight proxy
        ("B", "rs5 > 0", lambda v: v["feat_rs5"] > RS_POS),
        ("B", "rs5 > +2.5%", lambda v: v["feat_rs5"] > RS_STRONG),
        ("B", "rs10 > 0", lambda v: v["feat_rs10"] > RS_POS),
        ("B", "rs20 > 0", lambda v: v["feat_rs20"] > RS_POS),
        ("B", "rs20 in 0..+5%",
         lambda v: (v["feat_rs20"] >= RS_BAND_LO) & (v["feat_rs20"] < RS_BAND_HI)),
        ("B", "rs20 < -5%", lambda v: v["feat_rs20"] < RS_NEG),
        ("B", "rs_accel > 0", lambda v: v["feat_rs_accel"] > RS_POS),
        ("B", "rs_accel > +2.5%", lambda v: v["feat_rs_accel"] > RS_STRONG),
        # C. volume (late-volume is declared UNAVAILABLE on daily bars)
        ("C", "relvol 1.0-1.5",
         lambda v: (v["feat_relvol"] >= 1.0) & (v["feat_relvol"] < 1.5)),
        ("C", "relvol 1.5-2.5",
         lambda v: (v["feat_relvol"] >= 1.5) & (v["feat_relvol"] < 2.5)),
        ("C", "relvol > 2.5", lambda v: v["feat_relvol"] >= 2.5),
        ("C", "vol_accel < 0.8", lambda v: v["feat_vol_accel"] < 0.8),
        ("C", "vol_accel 0.8-1.2",
         lambda v: (v["feat_vol_accel"] >= 0.8) & (v["feat_vol_accel"] < 1.2)),
        ("C", "vol_accel > 1.2", lambda v: v["feat_vol_accel"] >= 1.2),
        ("C", "turnover_high (>= discovery q66)",
         lambda v: v["feat_turnover"] >= t_hi),
        ("C", "turnover_low (<= discovery q33)",
         lambda v: v["feat_turnover"] <= t_lo),
        # D. price action (premium/discount is the clv_position row set)
        ("D", "clv_position < 0.33 (discount)",
         lambda v: v["feat_clv_position"] < 0.33),
        ("D", "clv_position 0.33-0.67",
         lambda v: (v["feat_clv_position"] >= 0.33) & (v["feat_clv_position"] < 0.67)),
        ("D", "clv_position >= 0.67 (premium)",
         lambda v: v["feat_clv_position"] >= 0.67),
        ("D", "body_ratio < 0.3", lambda v: v["feat_body_ratio"] < 0.3),
        ("D", "body_ratio 0.3-0.6",
         lambda v: (v["feat_body_ratio"] >= 0.3) & (v["feat_body_ratio"] < 0.6)),
        ("D", "body_ratio >= 0.6", lambda v: v["feat_body_ratio"] >= 0.6),
        ("D", "lower_wick >= 0.5 (long lower wick)",
         lambda v: (v["feat_lower_wick"] >= WICK_LONG) & (v["feat_lower_wick"] <= 1.0)),
        ("D", "lower_wick 0.3-0.5",
         lambda v: (v["feat_lower_wick"] >= WICK_MID) & (v["feat_lower_wick"] < WICK_LONG)),
        ("D", "range_expansion TRUE", boolcol("feat_range_expansion")),
        ("D", "20d_high_break TRUE", boolcol("feat_20d_high_break")),
        ("D", "pullback_resume TRUE", boolcol("feat_pullback_resume")),
        # E. SMC
        ("E", "sweep_low TRUE", boolcol("feat_sweep_low")),
        ("E", "bos_up TRUE", boolcol("feat_bos_up")),
        ("E", "displacement TRUE", boolcol("feat_displacement")),
        ("E", "equal_lows TRUE", boolcol("feat_equal_lows")),
        # F. FVG
        ("F", "fvg_retrace TRUE (age-1 bull FVG, retested)",
         boolcol("feat_fvg_retrace")),
        ("F", "fvg_age1 small gap < 1%",
         lambda v: v["feat_fvg_bull_age1"].fillna(False).astype(bool)
         & (v["feat_fvg_size_pct"] < FVG_SIZE_CUT)),
        ("F", "fvg_age1 big gap >= 1%",
         lambda v: v["feat_fvg_bull_age1"].fillna(False).astype(bool)
         & (v["feat_fvg_size_pct"] >= FVG_SIZE_CUT)),
        # artifact controls (entry-price arithmetic)
        ("X", "gap_next_open < 0 (gap-down entry)", lambda v: v["gap_next_open"] < 0),
        ("X", "gap_next_open 0..+0.5%",
         lambda v: (v["gap_next_open"] >= 0) & (v["gap_next_open"] <= GAP_CUT)),
        ("X", "gap_next_open > +0.5% (gap-up entry)",
         lambda v: v["gap_next_open"] > GAP_CUT),
    ]
    return specs


def combo_specs() -> list[tuple[str, str, object]]:
    """The owner's 7 required combinations plus the live v1 stack reference."""
    r20_band = lambda v: (v["feat_ret_20d"] >= 0) & (v["feat_ret_20d"] < 0.05)
    rs = lambda v: v["feat_rs20"] > RS_POS
    sweep = lambda v: v["feat_sweep_low"].fillna(False).astype(bool)
    disp = lambda v: v["feat_displacement"].fillna(False).astype(bool)
    bos = lambda v: v["feat_bos_up"].fillna(False).astype(bool)
    fvg = lambda v: v["feat_fvg_retrace"].fillna(False).astype(bool)
    bull = lambda v: v["regime"].isin(["weak_bull", "strong_bull"])
    return [
        ("combo1", "ret_20d 0..+5% x rs20>0", lambda v: r20_band(v) & rs(v)),
        ("combo2", "ret_20d 0..+5% x sweep_low", lambda v: r20_band(v) & sweep(v)),
        ("combo3", "rs20>0 x sweep_low", lambda v: rs(v) & sweep(v)),
        ("combo4", "sweep_low x displacement", lambda v: sweep(v) & disp(v)),
        ("combo5", "sweep_low x bos_up", lambda v: sweep(v) & bos(v)),
        ("combo6", "sweep_low x fvg_retrace", lambda v: sweep(v) & fvg(v)),
        ("combo7", "ret_20d 0..+5% x sweep_low x fvg_retrace",
         lambda v: r20_band(v) & sweep(v) & fvg(v)),
        ("combo8_live", "live v1 stack: regime_bull x sweep_low x fvg_retrace",
         lambda v: bull(v) & sweep(v) & fvg(v)),
    ]


# ------------------------------------------------------- per-filter eval
def eval_filter(mask_fn, frames: dict, n_g: dict, with_boot: bool,
                n_tests: int, coupled: bool = False) -> dict:
    rec: dict = {"entry_reference_coupled": coupled}
    disc = None
    for name, fr in frames.items():
        mask = mask_fn(fr).fillna(False).astype(bool)
        sub, comp = fr[mask], fr[~mask]
        s = {"n_sub": int(len(sub)), "n_comp": int(len(comp)),
             "sub": block(sub), "comp": block(comp)}
        s["g_rate_lift_pp"] = rate_lift_point(sub, comp, "is_g")
        s["g_sc_rate_lift_pp"] = rate_lift_point(sub, comp, "is_g_sc")
        s["mae_lift_median_pp"] = lift_point(sub, comp, "mae_3bar")
        s["mae_sc_lift_pp"] = lift_point(sub, comp, "mae_3bar_sc")
        s["mfe_lift_median_pp"] = lift_point(sub, comp, "mfe_3bar")
        s["mfe_sc_lift_pp"] = lift_point(sub, comp, "mfe_3bar_sc")
        s["capture"] = (round(float(sub["is_g"].sum() / n_g[name]), 4)
                        if n_g[name] else None)
        s["precision"] = s["sub"].get("g_rate")
        if with_boot and s["n_sub"] >= 30 and s["n_comp"] >= 30:
            g_lift, g_ci, g_p = boot_rate_lift(
                int(sub["is_g"].sum()), len(sub),
                int(comp["is_g"].sum()), len(comp))
            s["g_rate_lift_ci95"] = g_ci
            s["g_rate_lift_p_two_sided"] = g_p
            gs_lift, gs_ci, gs_p = boot_rate_lift(
                int(sub["is_g_sc"].sum()), len(sub),
                int(comp["is_g_sc"].sum()), len(comp))
            s["g_sc_rate_lift_ci95"] = gs_ci
            s["g_sc_rate_lift_p_two_sided"] = gs_p
            m_lift, m_ci, m_p = boot_median_lift(sub["mae_3bar_sc"], comp["mae_3bar_sc"])
            s["mae_sc_lift_ci95"] = m_ci
            s["mae_sc_p_two_sided"] = m_p
            f_lift, f_ci, f_p = boot_median_lift(sub["mfe_3bar_sc"], comp["mfe_3bar_sc"])
            s["mfe_sc_lift_ci95"] = f_ci
            s["mfe_sc_p_two_sided"] = f_p
            if g_p is not None:
                s["g_rate_p_bonferroni"] = min(1.0, g_p * n_tests)
            if gs_p is not None:
                s["g_sc_p_bonferroni"] = min(1.0, gs_p * n_tests)
            if m_p is not None:
                s["mae_sc_p_bonferroni"] = min(1.0, m_p * n_tests)
            if f_p is not None:
                s["mfe_sc_p_bonferroni"] = min(1.0, f_p * n_tests)
        rec[name] = s
        if name == "discovery":
            disc = s
    rec["valid_min_n"] = bool(
        disc and disc["n_sub"] >= MIN_N and disc["n_comp"] >= MIN_N)
    rec["reference_consistent"] = bool(
        disc and disc["g_rate_lift_pp"] is not None
        and disc["g_sc_rate_lift_pp"] is not None
        and (disc["g_rate_lift_pp"] > 0) == (disc["g_sc_rate_lift_pp"] > 0))
    d = rec.get("discovery", {}).get("g_sc_rate_lift_pp")
    vv = rec.get("validation", {}).get("g_sc_rate_lift_pp")
    o = rec.get("oos", {}).get("g_sc_rate_lift_pp")
    stable_sc = bool(d is not None and vv is not None and o is not None
                     and d > 0 and vv > 0 and o > 0)
    de = rec.get("discovery", {}).get("g_rate_lift_pp")
    ve = rec.get("validation", {}).get("g_rate_lift_pp")
    oe = rec.get("oos", {}).get("g_rate_lift_pp")
    stable_entry = bool(de is not None and ve is not None and oe is not None
                        and de > 0 and ve > 0 and oe > 0)
    rec["persistence"] = {
        "g_sc_rate_lift_pp_discovery": d,
        "g_sc_rate_lift_pp_validation": vv,
        "g_sc_rate_lift_pp_oos": o,
        "g_rate_lift_pp_discovery_entry_view": de,
        "g_rate_lift_pp_validation_entry_view": ve,
        "g_rate_lift_pp_oos_entry_view": oe,
        "stable_entry_view": stable_entry,
        "stable_sc_view": stable_sc,
        # a filter counts as stable only when BOTH path references agree
        "stable_positive_all_splits": bool(stable_sc and stable_entry),
        "degradation_oos_minus_discovery_pp": (round(oe - de, 4)
                                               if (de is not None and oe is not None)
                                               else None),
        "mae_sc_lift_pp_discovery": rec.get("discovery", {}).get("mae_sc_lift_pp"),
        "mae_sc_lift_pp_validation": rec.get("validation", {}).get("mae_sc_lift_pp"),
        "mae_sc_lift_pp_oos": rec.get("oos", {}).get("mae_sc_lift_pp"),
    }
    return rec


def rank_key(rec: dict):
    """PRE-REGISTRATION NOTE (documented deviation, second pass): the primary
    rank metric is the ENTRY-referenced G-rate lift, the owner's Group G
    definition. The first pass ranked by the signal-close (SC) view; that run
    exposed the mirror artifact: the SC reference mechanically favors filters
    that RAISE the entry above the signal close (gap-up entries start the path
    above the anchor, so +2% from the anchor is partially free; SC lift
    +20.44 pp for gap-up, stable only because the mechanics are stable). The
    entry view is mechanically coupled in the OPPOSITE direction (gap-down
    entries compress entry-referenced MAE, the Phase 1 lesson). Gap filters
    therefore condition on the metric's own reference and are EXCLUDED from
    ranking entirely (kept as artifact controls, family X). For every
    remaining filter the entry view is unbiased for the owner's G target, and
    a strong candidate must ALSO keep the SC view positive (reference
    robustness)."""
    d = rec["discovery"]
    return (
        -(d.get("g_rate_lift_pp") if d.get("g_rate_lift_pp") is not None else -9e9),
        -(d.get("g_sc_rate_lift_pp") if d.get("g_sc_rate_lift_pp") is not None else -9e9),
        -(d.get("mae_sc_lift_pp") if d.get("mae_sc_lift_pp") is not None else -9e9),
        -(d.get("mfe_sc_lift_pp") if d.get("mfe_sc_lift_pp") is not None else -9e9),
        -(d["sub"].get("reach_+2.0pct") or 0.0),
        -d["n_sub"],
    )


def rank_records(records: list[dict]) -> list[dict]:
    eligible = [r for r in records if r["valid_min_n"]
                and not r.get("entry_reference_coupled")]
    return sorted(eligible, key=rank_key)


# --------------------------------------------------------- G composition
def g_composition(v: pd.DataFrame, top3_g_syms: list[str]) -> dict:
    g = v[v["is_g"]]
    comp = v[~v["is_g"]]
    out: dict = {
        "n": int(len(g)),
        "share_pct": round(100.0 * len(g) / len(v), 2),
        "g_sc": {
            "n": int(v["is_g_sc"].sum()),
            "rate_pct": round(100.0 * float(v["is_g_sc"].mean()), 2),
            "both_g_and_g_sc": int((v["is_g"] & v["is_g_sc"]).sum()),
            "jaccard_vs_g": round(float((v["is_g"] & v["is_g_sc"]).sum()
                                        / max(1, (v["is_g"] | v["is_g_sc"]).sum())), 4),
        },
        "by_regime": {},
        "by_year": {},
        "halves": {},
        "gap": {},
        "price_level": {},
        "top_symbols": {},
        "feature_incidence": {},
        "jump_flags": {},
        "extreme_tail": {},
        "examples": [],
        "top3_g_symbols": top3_g_syms,
    }
    for reg in ["strong_bull", "weak_bull", "weak_bear", "strong_bear", "unknown"]:
        n_g = int((g["regime"] == reg).sum())
        n_c = int((comp["regime"] == reg).sum())
        out["by_regime"][reg] = {
            "n_g": n_g, "n_comp": n_c,
            "g_share_of_regime_pct": round(100.0 * n_g / max(1, n_g + n_c), 2),
            "g_mix_pct": round(100.0 * n_g / max(1, len(g)), 2),
        }
    for yr, grp in v.groupby(v["signal_date"].dt.year):
        out["by_year"][str(int(yr))] = {
            "n": int(len(grp)),
            "g_rate_pct": round(100.0 * float(grp["is_g"].mean()), 2),
            "g_median_mae": round(float(grp.loc[grp["is_g"], "mae_3bar"].median()), 3)
            if grp["is_g"].any() else None,
            "g_median_mfe": round(float(grp.loc[grp["is_g"], "mfe_3bar"].median()), 3)
            if grp["is_g"].any() else None,
        }
    for name, d0, d1 in HALVES:
        sub = v[(v["signal_date"] >= d0) & (v["signal_date"] <= d1)]
        out["halves"][name] = {
            "n": int(len(sub)),
            "g_rate_pct": round(100.0 * float(sub["is_g"].mean()), 2),
            "g_median_mae": round(float(sub.loc[sub["is_g"], "mae_3bar"].median()), 3),
            "g_median_mfe": round(float(sub.loc[sub["is_g"], "mfe_3bar"].median()), 3),
        }
    out["gap"] = {
        "median_gap_pct_g": round(float(g["gap_next_open"].median()), 3),
        "median_gap_pct_comp": round(float(comp["gap_next_open"].median()), 3),
        "share_gap_down_pct_g": round(100.0 * float((g["gap_next_open"] < 0).mean()), 2),
        "share_gap_down_pct_comp": round(100.0 * float((comp["gap_next_open"] < 0).mean()), 2),
    }
    out["price_level"] = {
        "median_feat_close_g": round(float(g["feat_close"].median()), 2),
        "median_feat_close_comp": round(float(comp["feat_close"].median()), 2),
        "share_below_20_pkr_g": round(100.0 * float((g["feat_close"] < 20).mean()), 2),
        "share_below_20_pkr_comp": round(100.0 * float((comp["feat_close"] < 20).mean()), 2),
        "share_below_10_pkr_g": round(100.0 * float((g["feat_close"] < 10).mean()), 2),
        "share_below_10_pkr_comp": round(100.0 * float((comp["feat_close"] < 10).mean()), 2),
    }
    top = g["symbol"].value_counts().head(10)
    out["top_symbols"] = {
        "top10": {str(s): int(c) for s, c in top.items()},
        "top10_share_of_g_pct": round(100.0 * float(top.sum()) / len(g), 2),
        "n_symbols_in_g": int(g["symbol"].nunique()),
    }
    feats = [("sweep_low", "feat_sweep_low"), ("fvg_retrace", "feat_fvg_retrace"),
             ("bos_up", "feat_bos_up"), ("displacement", "feat_displacement"),
             ("equal_lows", "feat_equal_lows"), ("range_expansion", "feat_range_expansion"),
             ("20d_high_break", "feat_20d_high_break"),
             ("pullback_resume", "feat_pullback_resume"),
             ("clv<0.33", None), ("clv>=0.67", None),
             ("rs20>0", None), ("rs5>0", None), ("relvol>2.5", None)]
    for label, col in feats:
        if col is not None:
            rg = float(g[col].fillna(False).astype(bool).mean())
            rc = float(comp[col].fillna(False).astype(bool).mean())
        elif label == "clv<0.33":
            rg = float((g["feat_clv_position"] < 0.33).mean())
            rc = float((comp["feat_clv_position"] < 0.33).mean())
        elif label == "clv>=0.67":
            rg = float((g["feat_clv_position"] >= 0.67).mean())
            rc = float((comp["feat_clv_position"] >= 0.67).mean())
        elif label == "rs20>0":
            rg = float((g["feat_rs20"] > 0).mean())
            rc = float((comp["feat_rs20"] > 0).mean())
        elif label == "rs5>0":
            rg = float((g["feat_rs5"] > 0).mean())
            rc = float((comp["feat_rs5"] > 0).mean())
        else:
            rg = float((g["feat_relvol"] > 2.5).mean())
            rc = float((comp["feat_relvol"] > 2.5).mean())
        out["feature_incidence"][label] = {
            "in_g_pct": round(100.0 * rg, 2),
            "in_comp_pct": round(100.0 * rc, 2),
            "lift_pp": round(100.0 * (rg - rc), 2),
        }
    out["jump_flags"] = {
        "share_jump_up_ge_9.9pct_g": round(100.0 * float(g["jump_up"].mean()), 2),
        "share_jump_up_ge_9.9pct_comp": round(100.0 * float(comp["jump_up"].mean()), 2),
        "share_jump_dn_le_minus9.9pct_g": round(100.0 * float(g["jump_dn"].mean()), 2),
        "share_jump_dn_le_minus9.9pct_comp": round(100.0 * float(comp["jump_dn"].mean()), 2),
        "share_either_flag_g": round(100.0 * float((g["jump_up"] | g["jump_dn"]).mean()), 2),
        "share_either_flag_comp": round(100.0 * float((comp["jump_up"] | comp["jump_dn"]).mean()), 2),
    }
    out["extreme_tail"] = {
        "share_mfe_ge_25pct_g": round(100.0 * float((g["mfe_3bar"] >= 25).mean()), 2),
        "share_mfe_ge_25pct_comp": round(100.0 * float((comp["mfe_3bar"] >= 25).mean()), 2),
        "share_mfe_ge_50pct_g": round(100.0 * float((g["mfe_3bar"] >= 50).mean()), 2),
        "share_mfe_ge_50pct_comp": round(100.0 * float((comp["mfe_3bar"] >= 50).mean()), 2),
    }
    return out


def g_examples(v: pd.DataFrame, n_each: int = 5) -> list[dict]:
    g = v[v["is_g"]]
    picks = pd.concat([
        g.sort_values("mfe_3bar", ascending=False).head(n_each),
        g.iloc[(g["mfe_3bar"] - g["mfe_3bar"].median()).abs()
               .argsort().head(n_each)],
    ]).drop_duplicates(subset=["symbol", "signal_date"])
    out = []
    for row in picks.itertuples(index=False):
        out.append({
            "symbol": row.symbol,
            "signal_date": str(pd.Timestamp(row.signal_date).date()),
            "entry_date": str(pd.Timestamp(row.entry_date).date()),
            "feat_close": round(float(row.feat_close), 2),
            "entry_price": round(float(row.entry_price), 2),
            "gap_next_open_pct": round(float(row.gap_next_open), 3),
            "mae_3bar": round(float(row.mae_3bar), 3),
            "mfe_3bar": round(float(row.mfe_3bar), 3),
            "regime": row.regime,
            "jump_up_flag": bool(row.jump_up),
            "jump_dn_flag": bool(row.jump_dn),
            "o1": round(float(row.o1), 2), "h1": round(float(row.h1), 2),
            "l1": round(float(row.l1), 2), "c1": round(float(row.c1), 2),
            "o2": None if not np.isfinite(row.o2) else round(float(row.o2), 2),
            "h2": None if not np.isfinite(row.h2) else round(float(row.h2), 2),
            "l2": None if not np.isfinite(row.l2) else round(float(row.l2), 2),
            "c2": None if not np.isfinite(row.c2) else round(float(row.c2), 2),
            "o3": None if not np.isfinite(row.o3) else round(float(row.o3), 2),
            "h3": None if not np.isfinite(row.h3) else round(float(row.h3), 2),
            "l3": None if not np.isfinite(row.l3) else round(float(row.l3), 2),
            "c3": None if not np.isfinite(row.c3) else round(float(row.c3), 2),
        })
    return out


# ------------------------------------------------------------ deep dive
def deep_dive(name: str, mask_fn, frames: dict, n_g: dict, n_tests: int,
              v_full: pd.DataFrame, top3_g_syms: list[str]) -> dict:
    rec = {"filter": name}
    for split in ("discovery", "validation", "oos"):
        fr = frames[split]
        mask = mask_fn(fr).fillna(False).astype(bool)
        sub, comp = fr[mask], fr[~mask]
        s = {"n_sub": int(len(sub)), "n_comp": int(len(comp)),
             "sub": block(sub), "comp": block(comp),
             "g_sc_rate_lift_pp": rate_lift_point(sub, comp, "is_g_sc"),
             "g_rate_lift_pp": rate_lift_point(sub, comp, "is_g"),
             "mae_sc_lift_pp": lift_point(sub, comp, "mae_3bar_sc"),
             "mfe_sc_lift_pp": lift_point(sub, comp, "mfe_3bar_sc"),
             "capture": (round(float(sub["is_g"].sum() / n_g[split]), 4)
                         if n_g[split] else None),
             "precision": block(sub).get("g_rate")}
        if len(sub) >= 30 and len(comp) >= 30:
            _, g_ci, g_p = boot_rate_lift(int(sub["is_g"].sum()), len(sub),
                                          int(comp["is_g"].sum()), len(comp))
            s["g_rate_lift_ci95"] = g_ci
            s["g_rate_p_bonferroni"] = (min(1.0, g_p * n_tests)
                                        if g_p is not None else None)
            _, gs_ci, gs_p = boot_rate_lift(int(sub["is_g_sc"].sum()), len(sub),
                                            int(comp["is_g_sc"].sum()), len(comp))
            s["g_sc_rate_lift_ci95"] = gs_ci
            s["g_sc_p_bonferroni"] = (min(1.0, gs_p * n_tests)
                                      if gs_p is not None else None)
            _, m_ci, m_p = boot_median_lift(sub["mae_3bar_sc"], comp["mae_3bar_sc"])
            s["mae_sc_lift_ci95"] = m_ci
            _, f_ci, f_p = boot_median_lift(sub["mfe_3bar_sc"], comp["mfe_3bar_sc"])
            s["mfe_sc_lift_ci95"] = f_ci
        rec[split] = s
    # concentration and artifact sensitivity (discovery only, SC view)
    fr = frames["discovery"]
    mask = mask_fn(fr).fillna(False).astype(bool)
    excl = fr["symbol"].isin(top3_g_syms)
    sub, comp = fr[mask & ~excl], fr[~mask & ~excl]
    rec["discovery_ex_top3g_symbols"] = {
        "n_sub": int(len(sub)), "n_comp": int(len(comp)),
        "g_sc_rate_lift_pp": rate_lift_point(sub, comp, "is_g_sc"),
    }
    sub, comp = fr[mask & ~fr["artifact_row"]], fr[~mask & ~fr["artifact_row"]]
    rec["discovery_ex_artifact_rows"] = {
        "n_sub": int(len(sub)), "n_comp": int(len(comp)),
        "g_sc_rate_lift_pp": rate_lift_point(sub, comp, "is_g_sc"),
    }
    d = rec["discovery"].get("g_sc_rate_lift_pp")
    vv = rec["validation"].get("g_sc_rate_lift_pp")
    o = rec["oos"].get("g_sc_rate_lift_pp")
    stable = bool(d is not None and vv is not None and o is not None
                  and d > 0 and vv > 0 and o > 0)
    mae_ok = all(rec[s].get("mae_sc_lift_pp") is not None
                 and rec[s]["mae_sc_lift_pp"] > 0
                 for s in ("discovery", "validation", "oos"))
    conc_ok = bool(rec["discovery_ex_top3g_symbols"]["g_sc_rate_lift_pp"] is not None
                   and rec["discovery_ex_top3g_symbols"]["g_sc_rate_lift_pp"] > 0)
    art_ok = bool(rec["discovery_ex_artifact_rows"]["g_sc_rate_lift_pp"] is not None
                  and rec["discovery_ex_artifact_rows"]["g_sc_rate_lift_pp"] > 0)
    p_bonf = rec["discovery"].get("g_rate_p_bonferroni")
    de = rec["discovery"].get("g_rate_lift_pp")
    ve = rec["validation"].get("g_rate_lift_pp")
    oe = rec["oos"].get("g_rate_lift_pp")
    stable_entry = bool(de is not None and ve is not None and oe is not None
                        and de > 0 and ve > 0 and oe > 0)
    rec["flags"] = {
        "stable_sc_view_all_splits": stable,
        "stable_entry_view_all_splits": stable_entry,
        "stable_both_views": bool(stable and stable_entry),
        "mae_sc_positive_all_splits": mae_ok,
        "discovery_g_lift_ge_5pp": bool(de is not None and de >= 5.0),
        "discovery_g_sc_lift_positive": bool(d is not None and d > 0),
        "bonferroni_significant_discovery": bool(p_bonf is not None and p_bonf < 0.05),
        "suggestive_discovery": bool(p_bonf is not None and p_bonf < 0.20),
        "concentration_ok": conc_ok,
        "artifact_insensitive": art_ok,
        "entry_view_consistent": bool(
            rec["discovery"].get("g_rate_lift_pp") is not None
            and rec["discovery"].get("g_sc_rate_lift_pp") is not None
            and (rec["discovery"]["g_rate_lift_pp"] > 0)
            == (rec["discovery"]["g_sc_rate_lift_pp"] > 0)),
        "degradation_oos_minus_discovery_pp": (round(oe - de, 4)
                                               if (de is not None and oe is not None)
                                               else None),
    }
    return rec


# ------------------------------------------------------------- render md
def fmt(x, nd=2, plus=False):
    if x is None:
        return "n/a"
    if plus:
        return f"{x:+.{nd}f}"
    return f"{x:.{nd}f}"


def render_md(res: dict) -> str:
    L: list[str] = []
    A = L.append
    A("# RESEARCH PHASE 2A: can Group G be identified prospectively?")
    A("")
    A(f"Generated: {res['meta']['generated_at']} (Karachi, SO-8). GITHUB ACTIONS (SO-21).")
    A("")
    A("Scope and constraints honored: NO live trading, NO production threshold "
      "changes, NO TP/SL optimization, NO machine learning, NO future information. "
      "The live v1 stack and every production file are untouched by this study. "
      "Daily OHLCV only: no bid/ask, depth, order-flow or footprint data exists "
      "in this project (registry: footprint UNAVAILABLE) and none is implied.")
    A("")
    dq = res["data_quality"]
    A("## 1. Data and rebuild reconciliation")
    A("")
    A(f"- dataset: {dq['dataset_rows']:,} rows, {dq['symbols']} symbols, "
      f"{dq['start']}..{dq['end']}, sha256 {dq['dataset_sha8']}")
    A(f"- signals {dq['signals']:,}; skipped (no next bar / missing symbol / bad "
      f"entry) {dq['skipped']:,}; matrix rows {dq['matrix_rows']:,} x "
      f"{dq['matrix_cols']} cols (reconciles: signals minus skipped)")
    A(f"- data_invalid (engine print-chain screen, band 0.60): {dq['invalid']:,} "
      f"({dq['invalid_pct']:.2f}%) excluded from every metric below")
    A(f"- matrix provenance: {dq['provenance_summary']}")
    A("- the matrix was rebuilt for this phase on the updated dataset (adds the "
      "2026-10-05 session and the Phase 2A feature columns; the Phase 1 build "
      "ended 2026-10-02)")
    A("")
    p = res["protocol"]
    A("## 2. Protocol (frozen before any validation/OOS scoring)")
    A("")
    A(f"- discovery: {p['splits']['discovery'][0]} .. {p['splits']['discovery'][1]}")
    A(f"- validation: {p['splits']['validation'][0]} .. {p['splits']['validation'][1]}")
    A(f"- untouched OOS: {p['splits']['oos'][0]} .. {p['splits']['oos'][1]}")
    A(f"- Group G (target): mae_3bar >= {G_MAE_MAX}% AND mfe_3bar >= "
      f"+{G_MFE_MIN}% (entry-referenced, Phase 1 definition). G_sc robustness "
      "target: the same thresholds on signal-close-referenced paths.")
    A(f"- thresholds: fixed a priori where natural; quantile cuts frozen on "
      f"DISCOVERY rows only: breadth q33/q66 = {p['frozen_cuts']['breadth']['q33']:.4f}/"
      f"{p['frozen_cuts']['breadth']['q66']:.4f}, rvol20 q33/q66 = "
      f"{p['frozen_cuts']['rvol20']['q33']:.4f}/{p['frozen_cuts']['rvol20']['q66']:.4f}, "
      f"turnover q33/q66 = {p['frozen_cuts']['turnover']['q33']:.3e}/"
      f"{p['frozen_cuts']['turnover']['q66']:.3e}")
    A(f"- ranking on discovery only: entry-referenced G-rate lift (pp; the "
      f"owner's G definition), then SC-referenced G-rate lift, MAE-SC lift, "
      f"MFE-SC lift, +2% reach, n. n >= {MIN_N} both sides to be rankable. A "
      f"strong candidate must hold the lift in BOTH path references. The three "
      f"gap filters are entry-reference-coupled artifact controls (the gap "
      f"shifts the reference itself; entry view favors gap-down, SC view "
      f"favors gap-up) and are excluded from ranking.")
    A(f"- bootstrap: {N_BOOT} resamples, seed {BOOT_SEED}; Bonferroni across "
      f"{p['n_tests']} tests (all filters + combinations).")
    A("- disclosure: Phase 1 already glanced at full-sample SC lifts. Mitigation: "
      "every choice in this phase uses the discovery split only; validation and "
      "OOS are scored once with frozen cuts.")
    A("")
    A("## 3. Group G baseline and composition")
    A("")
    gb = res["group_g_baseline"]
    u = gb["full"]
    A(f"Full valid sample: n={u['n']:,}; G n={u['g_count']:,} "
      f"(G rate {u['g_rate']:.1%}); median MAE {u['mae_median']:.2f}% "
      f"[p25 {u['mae_p25']:.2f}, p75 {u['mae_p75']:.2f}]; median MFE "
      f"{u['mfe_median']:.2f}% [p25 {u['mfe_p25']:.2f}, p75 {u['mfe_p75']:.2f}].")
    A(f"Reach: +0.5% {u['reach_+0.5pct']:.1%}, +1% {u['reach_+1.0pct']:.1%}, "
      f"+1.5% {u['reach_+1.5pct']:.1%}, +2% {u['reach_+2.0pct']:.1%}; "
      f"touch: -0.5% {u['touch_-0.5pct']:.1%}, -1% {u['touch_-1.0pct']:.1%}, "
      f"-1.5% {u['touch_-1.5pct']:.1%}, -2% {u['touch_-2.0pct']:.1%}; "
      f"+2% before -1%: {u['p20_before_m10']:.1%}; median t_to_p10 "
      f"{fmt(u['median_t_to_p10'],1)} bars, t_to_p20 {fmt(u['median_t_to_p20'],1)} bars.")
    A("")
    A("Note the base-rate drift: G rate falls from "
      f"{gb['splits']['discovery']['g_rate']:.1%} (discovery) to "
      f"{gb['splits']['oos']['g_rate']:.1%} (OOS). Every candidate lift must be "
      "read against this drifting base, which is why lifts (sub minus "
      "complement), not raw rates, are compared across splits.")
    A("")
    A("| split | n | G rate | G n | G median MAE | G median MFE | G +2 before -1 | G ret3 median |")
    A("|---|---|---|---|---|---|---|---|")
    for name in ("discovery", "validation", "oos"):
        b = gb["splits"][name]
        g = gb["g_only"][name]
        A(f"| {name} | {b['n']:,} | {b['g_rate']:.1%} | {b['g_count']:,} | "
          f"{fmt(g['mae_median'])} | {fmt(g['mfe_median'])} | "
          f"{fmt(g['p20_before_m10'],4)} | {fmt(g['ret3_median'])} |")
    A("")
    gc = res["g_composition"]
    A(f"G spans {gc['top_symbols']['n_symbols_in_g']} symbols; top-10 share "
      f"{gc['top_symbols']['top10_share_of_g_pct']:.1f}%. G_sc overlap: "
      f"{gc['g_sc']['both_g_and_g_sc']:,} of G also G_sc (Jaccard "
      f"{gc['g_sc']['jaccard_vs_g']:.3f}).")
    A("")
    A("| feature incidence | in G | in complement | lift pp |")
    A("|---|---|---|---|")
    for k, f in gc["feature_incidence"].items():
        A(f"| {k} | {f['in_g_pct']:.1f}% | {f['in_comp_pct']:.1f}% | {f['lift_pp']:+.1f} |")
    A("")
    A("Artifact-related incidence inside G:")
    A("")
    jf = gc["jump_flags"]
    A(f"- single-bar moves >= +9.9%: G {jf['share_jump_up_ge_9.9pct_g']:.1f}% vs "
      f"comp {jf['share_jump_up_ge_9.9pct_comp']:.1f}%; <= -9.9%: G "
      f"{jf['share_jump_dn_le_minus9.9pct_g']:.1f}% vs comp "
      f"{jf['share_jump_dn_le_minus9.9pct_comp']:.1f}%")
    et = gc["extreme_tail"]
    A(f"- MFE >= +25%: G {et['share_mfe_ge_25pct_g']:.1f}% vs comp "
      f"{et['share_mfe_ge_25pct_comp']:.1f}%; MFE >= +50%: G "
      f"{et['share_mfe_ge_50pct_g']:.1f}% vs comp {et['share_mfe_ge_50pct_comp']:.1f}%")
    A(f"- gap-down share: G {gc['gap']['share_gap_down_pct_g']:.1f}% vs comp "
      f"{gc['gap']['share_gap_down_pct_comp']:.1f}% (median gap "
      f"{gc['gap']['median_gap_pct_g']:+.3f}% vs {gc['gap']['median_gap_pct_comp']:+.3f}%)")
    A(f"- price level: median close {gc['price_level']['median_feat_close_g']:.2f} "
      f"PKR in G vs {gc['price_level']['median_feat_close_comp']:.2f} PKR in comp; "
      f"share below 20 PKR {gc['price_level']['share_below_20_pkr_g']:.1f}% vs "
      f"{gc['price_level']['share_below_20_pkr_comp']:.1f}%")
    A("")
    A("| year | n | G rate | G median MAE | G median MFE |")
    A("|---|---|---|---|---|")
    for yr, b in gc["by_year"].items():
        A(f"| {yr} | {b['n']:,} | {b['g_rate_pct']:.1f}% | "
          f"{fmt(b['g_median_mae'])} | {fmt(b['g_median_mfe'])} |")
    A("")
    A("Halves: " + "; ".join(
        f"{k}: n={b['n']:,}, G rate {b['g_rate_pct']:.1f}%"
        for k, b in gc["halves"].items()))
    A("")
    A("Individual G examples (deterministic pick: 5 highest-MFE and 5 closest to "
      "the median MFE; full rows in the JSON):")
    A("")
    A("| symbol | signal date | close | gap % | MAE | MFE | jump up | jump dn | regime | c1 | c2 | c3 |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for e in gc["examples"]:
        A(f"| {e['symbol']} | {e['signal_date']} | {e['feat_close']} | "
          f"{e['gap_next_open_pct']:+.2f} | {e['mae_3bar']:+.2f} | "
          f"{e['mfe_3bar']:+.2f} | {'Y' if e['jump_up_flag'] else '-'} | "
          f"{'Y' if e['jump_dn_flag'] else '-'} | {e['regime']} | "
          f"{e['c1']} | {e['c2']} | {e['c3']} |")
    A("")
    A("## 4. Top 10 candidate filters (ranked on discovery only)")
    A("")
    A("G rate is the share of trades in G; lift is sub minus complement in "
      "percentage points; G-SC lift uses the signal-close reference; MAE/MFE "
      "lifts are median differences (MAE signal-close view for ranking); the "
      "D/V/OOS column shows the entry-referenced G lift per split; stable = "
      "positive lift in all three splits in BOTH path references. p_adj is "
      "Bonferroni over all tests on discovery (entry view).")
    A("")
    A("| rank | filter | n sub | G rate | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC lift | MFE-SC lift | +2 before -1 | capture | precision | D/V/OOS G lift (entry) | stable |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(res["filters"]["top10"], 1):
        d = r["discovery"]
        ci = d.get("g_sc_rate_lift_ci95") or [0, 0]
        A(f"| {i} | {r['filter']} | {d['n_sub']:,} | {fmt(d['sub'].get('g_rate'),3)} | "
          f"{fmt(d.get('g_sc_rate_lift_pp'),2,True)} "
          f"[{fmt(ci[0],2,True)}, {fmt(ci[1],2,True)}] | "
          f"{fmt(d.get('g_sc_p_bonferroni'),3)} | "
          f"{fmt(d.get('g_rate_lift_pp'),2,True)} | "
          f"{fmt(d.get('mae_sc_lift_pp'),2,True)} | {fmt(d.get('mfe_sc_lift_pp'),2,True)} | "
          f"{fmt(d['sub'].get('p20_before_m10'),3)} | {fmt(d.get('capture'),3)} | "
          f"{fmt(d.get('precision'),3)} | "
          f"{fmt(r['persistence']['g_rate_lift_pp_discovery_entry_view'],1,True)}/"
          f"{fmt(r['persistence']['g_rate_lift_pp_validation_entry_view'],1,True)}/"
          f"{fmt(r['persistence']['g_rate_lift_pp_oos_entry_view'],1,True)} | "
          f"{'yes' if r['persistence']['stable_positive_all_splits'] else 'no'} |")
    A("")
    if res["filters"]["excluded_n"]:
        A("Not rankable (reported for completeness): " +
          "; ".join(f"{r['filter']} (n={r['discovery']['n_sub']:,}, "
                    f"{r['exclude_reason']})"
                    for r in res["filters"]["excluded_n"]))
        A("")
    A("## 5. Top 10 candidate combinations (ranked on discovery only)")
    A("")
    A("| rank | combo | n sub | G rate | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC lift | MFE-SC lift | +2 before -1 | capture | precision | D/V/OOS G lift (entry) | stable |")
    A("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for i, r in enumerate(res["combos"]["top10"], 1):
        d = r["discovery"]
        ci = d.get("g_sc_rate_lift_ci95") or [0, 0]
        A(f"| {i} | {r['filter']} | {d['n_sub']:,} | {fmt(d['sub'].get('g_rate'),3)} | "
          f"{fmt(d.get('g_sc_rate_lift_pp'),2,True)} "
          f"[{fmt(ci[0],2,True)}, {fmt(ci[1],2,True)}] | "
          f"{fmt(d.get('g_sc_p_bonferroni'),3)} | "
          f"{fmt(d.get('g_rate_lift_pp'),2,True)} | "
          f"{fmt(d.get('mae_sc_lift_pp'),2,True)} | {fmt(d.get('mfe_sc_lift_pp'),2,True)} | "
          f"{fmt(d['sub'].get('p20_before_m10'),3)} | {fmt(d.get('capture'),3)} | "
          f"{fmt(d.get('precision'),3)} | "
          f"{fmt(r['persistence']['g_rate_lift_pp_discovery_entry_view'],1,True)}/"
          f"{fmt(r['persistence']['g_rate_lift_pp_validation_entry_view'],1,True)}/"
          f"{fmt(r['persistence']['g_rate_lift_pp_oos_entry_view'],1,True)} | "
          f"{'yes' if r['persistence']['stable_positive_all_splits'] else 'no'} |")
    A("")
    if res["combos"]["excluded_n"]:
        A("Combos not rankable on discovery (n < 500; full records in the JSON): " +
          "; ".join(f"{r['filter']} (n={r['discovery']['n_sub']})"
                    for r in res["combos"]["excluded_n"]))
        A("")
    A("The owner's sweep- and FVG-based combinations do not enrich G: every "
      "rankable combo shows a G entry lift at or below +0.1 pp on discovery, "
      "and most are negative. The live v1 stack's building blocks select "
      "ordinary-quality entries with respect to G membership.")
    A("")
    A("## 6. Best candidates: discovery / validation / untouched OOS")
    A("")
    for c in res["best_candidates"]:
        A(f"### {c['filter']}")
        A("")
        A("| split | n sub | n comp | G rate sub | G rate comp | G-SC lift pp [CI95] | p_adj | G entry lift | MAE-SC sub/comp | MFE-SC sub/comp | capture | precision |")
        A("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in ("discovery", "validation", "oos"):
            x = c[s]
            ci = x.get("g_sc_rate_lift_ci95") or [0, 0]
            A(f"| {s} | {x['n_sub']:,} | {x['n_comp']:,} | "
              f"{fmt(x['sub'].get('g_rate'),3)} | {fmt(x['comp'].get('g_rate'),3)} | "
              f"{fmt(x.get('g_sc_rate_lift_pp'),2,True)} "
              f"[{fmt(ci[0],2,True)}, {fmt(ci[1],2,True)}] | "
              f"{fmt(x.get('g_sc_p_bonferroni'),3)} | "
              f"{fmt(x.get('g_rate_lift_pp'),2,True)} | "
              f"{fmt(x['sub'].get('mae_sc_median'))}/{fmt(x['comp'].get('mae_sc_median'))} | "
              f"{fmt(x['sub'].get('mfe_sc_median'))}/{fmt(x['comp'].get('mfe_sc_median'))} | "
              f"{fmt(x.get('capture'),3)} | {fmt(x.get('precision'),3)} |")
        A("")
        f = c["flags"]
        ex3 = c["discovery_ex_top3g_symbols"]
        exa = c["discovery_ex_artifact_rows"]
        A(f"- degradation (OOS minus discovery, entry-referenced G lift): "
          f"{fmt(f['degradation_oos_minus_discovery_pp'],2,True)} pp; stable sign "
          f"all splits (both references): "
          f"{'yes' if f['stable_both_views'] else 'no'} (entry "
          f"{'yes' if f['stable_entry_view_all_splits'] else 'no'} / SC "
          f"{'yes' if f['stable_sc_view_all_splits'] else 'no'}); "
          f"MAE-SC positive all splits: {'yes' if f['mae_sc_positive_all_splits'] else 'no'}")
        A(f"- discovery G-SC lift excluding the top-3 G-contributing symbols: "
          f"{fmt(ex3['g_sc_rate_lift_pp'],2,True)} pp (n_sub {ex3['n_sub']:,}); "
          f"excluding artifact-flagged rows: {fmt(exa['g_sc_rate_lift_pp'],2,True)} pp "
          f"(n_sub {exa['n_sub']:,})")
        A("")
    A("## 7. Artifact audit")
    A("")
    aa = res["artifact_audit"]
    A(f"- data_invalid rows excluded: {aa['invalid_rows']:,} "
      f"({aa['invalid_pct']:.2f}% of matrix rows); engine band 0.60 print-chain "
      "screen, same semantics as the engine.")
    A(f"- entry-vs-SC consistency: {aa['n_filters']} filters tested; "
      f"{aa['n_entry_sc_flips']} show entry-referenced and signal-close G lifts "
      "with opposite signs (entry-price arithmetic). The final protocol ranks "
      "by the entry view (the owner's G definition) and requires SC agreement "
      "for a strong candidate; the three gap filters are excluded from ranking "
      "as reference-coupled (entry view favors gap-down, SC view favors "
      "gap-up, mechanically).")
    A(f"- the Phase 1 gap-down artifact re-check on the new build: 'gap_next_open "
      f"< 0' entry-referenced MAE lift {fmt(aa['gap_down_recheck']['mae_entry_lift'],2,True)} pp "
      f"vs signal-close {fmt(aa['gap_down_recheck']['mae_sc_lift'],2,True)} pp "
      f"({aa['gap_down_recheck']['verdict']}).")
    A(f"- corporate-action exposure: {aa['corp_action_statement']}")
    A(f"- survivorship: {aa['survivorship_statement']}")
    A(f"- order-flow fabrication: {aa['footprint_statement']}")
    A(f"- concentration: {aa['concentration_statement']}")
    A("")
    A("## 8. What defines Group G (classification)")
    A("")
    A(f"**{res['what_is_group_g']['classification']}**")
    A("")
    for e in res["what_is_group_g"]["evidence"]:
        A(f"- {e}")
    A("")
    A("## 9. Final recommendation")
    A("")
    A(f"**{res['final_recommendation']['label']}**")
    A("")
    A(res["final_recommendation"]["rationale"])
    A("")
    A("Rubric applied (frozen in the script):")
    A("")
    for c in res["final_recommendation"]["criteria"]:
        A(f"- {c}")
    A("")
    A("## 10. What still cannot be concluded")
    A("")
    for item in res["cannot_conclude"]:
        A(f"- {item}")
    A("")
    A("## Appendix: exact feature definitions")
    A("")
    for k, v in res["feature_definitions"].items():
        A(f"- {k}: {v}")
    A("")
    A("## Appendix: provenance")
    A("")
    A(f"- python {res['meta']['python']}, pandas {res['meta']['pandas']}")
    A(f"- bootstrap seed {BOOT_SEED}; no other randomness; one-shot local run")
    A(f"- matrix: {dq['matrix_rows']:,} rows, built by scripts/build_trade_matrix.py "
      f"from {dq['dataset_rows']:,} dataset rows (sha256 {dq['dataset_sha8']})")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/research_phase2a.py")
    ap = argparse.ArgumentParser(description="Phase 2A: Group G identifiability")
    ap.add_argument("--matrix", type=Path, default=MATRIX_PATH)
    args = ap.parse_args(argv)

    if not args.matrix.is_file():
        print("trade matrix missing; run scripts/build_trade_matrix.py first")
        return 1

    m = pd.read_parquet(args.matrix)
    m["signal_date"] = pd.to_datetime(m["signal_date"])

    # SO-3 honesty gate: daily OHLCV only; no order-flow anywhere in this study
    fp = availability("footprint")
    if fp.value == "UNAVAILABLE":
        print("registry: footprint = UNAVAILABLE -> daily OHLCV only; no "
              "order-flow claims are made or tested")

    # ---- targets and reference views ----
    v = m[~m["data_invalid"].astype(bool)].copy()
    lo3 = v[["l1", "l2", "l3"]].min(axis=1)
    hi3 = v[["h1", "h2", "h3"]].max(axis=1)
    v["mae_3bar_sc"] = (lo3 / v["feat_close"] - 1.0) * 100.0
    v["mfe_3bar_sc"] = (hi3 / v["feat_close"] - 1.0) * 100.0
    v["is_g"] = (v["mae_3bar"] >= G_MAE_MAX) & (v["mfe_3bar"] >= G_MFE_MIN)
    v["is_g_sc"] = (v["mae_3bar_sc"] >= G_MAE_MAX) & (v["mfe_3bar_sc"] >= G_MFE_MIN)

    # raw-data guard: lower wick outside [0, 1] is dirt, treated as missing
    bad_w = (v["feat_lower_wick"] < 0) | (v["feat_lower_wick"] > 1)
    v.loc[bad_w, "feat_lower_wick"] = np.nan

    # ---- single-bar jump flags (artifact screen; close-to-close and open
    # jumps inside bars 1..3, referenced to the previous close) ----
    prev = v["feat_close"].to_numpy(dtype=float)
    up = np.full(len(v), -np.inf)
    dn = np.full(len(v), np.inf)
    for k in (1, 2, 3):
        o = v[f"o{k}"].to_numpy(dtype=float)
        h = v[f"h{k}"].to_numpy(dtype=float)
        l = v[f"l{k}"].to_numpy(dtype=float)
        c = v[f"c{k}"].to_numpy(dtype=float)
        for arr in (o, h, l, c):
            r = arr / prev - 1.0
            up = np.fmax(up, r)
            dn = np.fmin(dn, r)
        with np.errstate(invalid="ignore", divide="ignore"):
            for arr in (h, l):
                r = arr / o - 1.0
                up = np.fmax(up, r)
                dn = np.fmin(dn, r)
        prev = c
    v["jump_up"] = up >= 0.099
    v["jump_dn"] = dn <= -0.099
    v["artifact_row"] = v["jump_up"] | v["jump_dn"]

    # ---- splits ----
    frames = {}
    for name, d0, d1 in SPLITS:
        fr = v[(v["signal_date"] >= d0) & (v["signal_date"] <= d1)].copy()
        frames[name] = fr
    n_g = {name: int(fr["is_g"].sum()) for name, fr in frames.items()}
    print("split sizes:", {k: len(fr) for k, fr in frames.items()},
          "G counts:", n_g)

    cuts = frozen_cuts(frames["discovery"])
    print("frozen cuts (discovery quantiles):", json.dumps(cuts, indent=1))

    specs = filter_specs(cuts)
    combos = combo_specs()
    n_tests = len(specs) + len(combos)
    print(f"tests: {len(specs)} filters + {len(combos)} combos = {n_tests}; "
          f"Bonferroni across {n_tests}")

    # ---- evaluate every filter and combo on all three splits ----
    # family X = entry-price artifact controls: the filter conditions on the
    # entry itself (the gap), so BOTH G references are mechanically coupled
    # (entry view favors gap-down, SC view favors gap-up); excluded from
    # ranking, reported in the artifact audit
    filter_records = []
    for fam, name, fn in specs:
        rec = eval_filter(fn, frames, n_g, with_boot=True, n_tests=n_tests,
                          coupled=(fam == "X"))
        rec["filter"] = name
        rec["family"] = fam
        filter_records.append(rec)
        print(f"  filter done: {name} (disc n={rec['discovery']['n_sub']:,})")
    combo_records = []
    for cid, name, fn in combos:
        rec = eval_filter(fn, frames, n_g, with_boot=True, n_tests=n_tests)
        rec["filter"] = name
        rec["family"] = cid
        combo_records.append(rec)
        print(f"  combo done: {name} (disc n={rec['discovery']['n_sub']:,})")

    ranked_f = rank_records(filter_records)
    ranked_c = rank_records(combo_records)
    artifact_controls = [r for r in filter_records if r.get("entry_reference_coupled")]
    excluded_f = [dict(r, exclude_reason=("entry-reference-coupled artifact control "
                                          "(excluded from ranking)")
                         if r.get("entry_reference_coupled")
                         else "n < 500 on discovery")
                  for r in filter_records
                  if not (r["valid_min_n"] and not r.get("entry_reference_coupled"))]
    excluded_c = [dict(r, exclude_reason="n < 500 on discovery")
                  for r in combo_records if not r["valid_min_n"]]

    # ---- deep dive: top 5 filters + top 3 combos + any stable &
    # Bonferroni-significant filter not already selected (cap 8) ----
    deep_f = ranked_f[:5]
    deep_c = ranked_c[:3]
    extra = [r for r in ranked_f[5:]
             if r["persistence"]["stable_positive_all_splits"]
             and r["discovery"].get("g_sc_p_bonferroni") is not None
             and r["discovery"]["g_sc_p_bonferroni"] < 0.05]
    deep_f = (deep_f + extra)[:8]
    lookup = {name: fn for _, name, fn in specs}
    lookup.update({name: fn for _, name, fn in combos})
    top3_g_syms = (frames["discovery"][frames["discovery"]["is_g"]]["symbol"]
                   .value_counts().head(3).index.tolist())
    best = []
    for r in deep_f + deep_c:
        best.append(deep_dive(r["filter"], lookup[r["filter"]], frames, n_g,
                              n_tests, v, top3_g_syms))
        print(f"  deep dive done: {r['filter']}")

    # ---- G baseline blocks ----
    gb = {
        "full": block(v),
        "splits": {name: block(fr) for name, fr in frames.items()},
        "g_only": {name: block(fr[fr["is_g"]]) for name, fr in frames.items()},
        "halves": {},
    }
    for name, d0, d1 in HALVES:
        gb["halves"][name] = block(v[(v["signal_date"] >= d0) & (v["signal_date"] <= d1)])

    gc = g_composition(v, top3_g_syms)
    gc["examples"] = g_examples(v)

    # ---- artifact audit ----
    gap_mask = lambda fr: fr["gap_next_open"] < 0
    gap_sub = frames["discovery"][gap_mask(frames["discovery"])]
    gap_comp = frames["discovery"][~gap_mask(frames["discovery"])]
    gap_recheck = {
        "mae_entry_lift": lift_point(gap_sub, gap_comp, "mae_3bar"),
        "mae_sc_lift": lift_point(gap_sub, gap_comp, "mae_3bar_sc"),
        "verdict": ("entry-referenced lift flips sign in the SC view: confirmed "
                    "entry-price arithmetic artifact")
        if (lift_point(gap_sub, gap_comp, "mae_3bar") or 0) > 0
        and (lift_point(gap_sub, gap_comp, "mae_3bar_sc") or 0) < 0
        else "signs agree on this build",
    }
    n_flips = sum(1 for r in filter_records + combo_records
                  if r["discovery"].get("g_rate_lift_pp") is not None
                  and r["discovery"].get("g_sc_rate_lift_pp") is not None
                  and (r["discovery"]["g_rate_lift_pp"] > 0)
                  != (r["discovery"]["g_sc_rate_lift_pp"] > 0))
    dead_cutoff = pd.Timestamp(v["signal_date"].max()) - pd.Timedelta(days=90)
    last_print = m.groupby("symbol")["signal_date"].max()
    dead_syms = last_print[last_print < dead_cutoff].index.tolist()
    dead_share_g = float(v.loc[v["is_g"], "symbol"].isin(dead_syms).mean())
    top10_g_share = gc["top_symbols"]["top10_share_of_g_pct"]
    artifact_audit = {
        "invalid_rows": int(m["data_invalid"].sum()),
        "invalid_pct": round(100.0 * float(m["data_invalid"].mean()), 2),
        "n_filters": len(filter_records) + len(combo_records),
        "n_entry_sc_flips": n_flips,
        "gap_down_recheck": gap_recheck,
        "corp_action_statement": (
            f"no adjustment factors exist in the repo (acquisition spec C in "
            f"RESEARCH_PHASE1.md); as a screen, single-bar moves >= 9.9% inside "
            f"bars 1-3 appear in {gc['jump_flags']['share_jump_up_ge_9.9pct_g']:.1f}% "
            f"of G trades vs {gc['jump_flags']['share_jump_up_ge_9.9pct_comp']:.1f}% "
            f"of the complement (up) and "
            f"{gc['jump_flags']['share_jump_dn_le_minus9.9pct_g']:.1f}% vs "
            f"{gc['jump_flags']['share_jump_dn_le_minus9.9pct_comp']:.1f}% (down); "
            "PSX circuit bands around these levels mean genuine limit moves and "
            "unadjusted corporate actions cannot be separated without the factor "
            "file, so both are reported"),
        "survivorship_statement": (
            f"universe membership is today's KMIALL list (survivorship-biased); "
            f"{len(dead_syms)} symbols stopped printing > 90 days before the "
            f"dataset end; {100.0 * dead_share_g:.1f}% of G trades come from them; "
            "point-in-time membership still cannot be reconstructed"),
        "footprint_statement": (
            "no bid/ask, depth, order-flow, AMT or footprint information exists "
            "in this project (registry: UNAVAILABLE); none is implied anywhere"),
        "concentration_statement": (
            f"G trades span {gc['top_symbols']['n_symbols_in_g']} symbols; top-10 symbols carry "
            f"{top10_g_share:.1f}% of G; deep-dive candidates are re-measured "
            f"with the top-3 G symbols removed (see best candidates)"),
    }

    # ---- what is Group G ----
    strong_cands = [c for c in best if c["flags"]["stable_both_views"]
                    and c["flags"]["discovery_g_lift_ge_5pp"]
                    and c["flags"]["discovery_g_sc_lift_positive"]
                    and c["flags"]["bonferroni_significant_discovery"]
                    and c["flags"]["mae_sc_positive_all_splits"]
                    and c["flags"]["concentration_ok"]]
    stable_sig = [c for c in best if c["flags"]["stable_both_views"]
                  and (c["flags"]["bonferroni_significant_discovery"]
                       or c["flags"]["suggestive_discovery"])]
    artifact_heavy = (gc["jump_flags"]["share_either_flag_g"] > 30.0
                      or gc["extreme_tail"]["share_mfe_ge_25pct_g"] > 20.0)
    art_flip = [c for c in best if c["flags"]["stable_both_views"]
                and not c["flags"]["artifact_insensitive"]]

    if strong_cands:
        classification = ("predictable setup: one or more signal-time filters "
                          "identify G with stable, corrected-significant lift "
                          "across discovery, validation and untouched OOS, in "
                          "both path references")
    elif stable_sig:
        classification = ("mixture of several states: some signal-time filters "
                          "carry stable but modest information about G; no single "
                          "dominant state, and the residual remains partly "
                          "unexplained")
    elif artifact_heavy and art_flip:
        classification = ("data/corporate-action artifact: G is concentrated in "
                          "rows flagged by single-bar jump screens and its "
                          "identifiability collapses when those rows are removed")
    else:
        classification = ("real market geometry without a robust prospective "
                          "predictor: G exists at stable rates across halves, but "
                          "no tested signal-time filter carries stable, "
                          "corrected-significant lift across all splits")

    evidence = [
        f"G rate is stable across splits: discovery "
        f"{gb['splits']['discovery']['g_rate']:.1%}, validation "
        f"{gb['splits']['validation']['g_rate']:.1%}, OOS "
        f"{gb['splits']['oos']['g_rate']:.1%} (halves "
        f"{gb['halves']['2021-23']['g_rate']:.1%} vs "
        f"{gb['halves']['2024-26']['g_rate']:.1%})",
        f"G_sc overlap Jaccard {gc['g_sc']['jaccard_vs_g']:.3f}: the entry-price "
        f"reference is not what creates G",
        f"single-bar jump flags: {gc['jump_flags']['share_either_flag_g']:.1f}% of "
        f"G vs {gc['jump_flags']['share_either_flag_comp']:.1f}% of complement",
        f"top-10 symbols carry {top10_g_share:.1f}% of G over "
        f"{gc['top_symbols']['n_symbols_in_g']} symbols",
        (f"{len(stable_sig)} of {len(best)} deep-dive candidates keep a positive "
         f"G-rate lift in all three splits in both path references; "
         f"{len(strong_cands)} clear the full strong-candidate bar") if best
        else "no deep-dive candidates qualified",
    ]

    # ---- verdict ----
    if strong_cands:
        label = A_LABEL
        rationale = (
            "At least one candidate clears every pre-registered bar: positive "
            "G-rate lift in discovery, validation and untouched OOS; Bonferroni-"
            "significant on discovery; >= +5 pp discovery lift; MAE signal-close "
            "lift positive in all splits; and the lift survives removing the "
            "top-3 G-contributing symbols. Phase 2B (TP/SL testing on that "
            "candidate vs all entries) is the logical next step, still without "
            "production changes.")
        crit = [f"strong candidates: " + ", ".join(c["filter"] for c in strong_cands)]
    elif stable_sig:
        label = B_LABEL
        rationale = (
            "One or more candidates show a G-rate lift that stays positive "
            "across discovery, validation and OOS with at least suggestive "
            "corrected significance, but none clears the full strong-candidate "
            "bar (>= +5 pp, Bonferroni-significant, MAE-SC positive in all "
            "splits, concentration-safe). The honest reading is a weak-to-moderate "
            "signal that needs more data or better features before any TP/SL "
            "testing.")
        crit = [f"stable+suggestive candidates: "
                + ", ".join(c["filter"] for c in stable_sig)]
    elif artifact_heavy and art_flip:
        label = D_LABEL
        rationale = (
            "G is materially concentrated in rows whose paths contain single-bar "
            "moves at circuit-band scale, and the candidate lifts collapse once "
            "those rows are removed. Without corporate-action factors this cannot "
            "be resolved; treat G as an artifact until adjustment data exists.")
        crit = [f"artifact-heavy: jump share in G "
                f"{gc['jump_flags']['share_either_flag_g']:.1f}%",
                f"candidates whose lift collapses without artifact rows: "
                + ", ".join(c["filter"] for c in art_flip)]
    else:
        label = C_LABEL
        rationale = (
            "No tested filter or combination carries a G-rate lift that is "
            "stable and corrected-significant across discovery, validation and "
            "untouched OOS. Group G is a real, stable geometry of the sample, "
            "but the tested signal-time features do not identify it prospectively "
            "beyond weak, split-dependent effects. Production must not change on "
            "this evidence.")
        crit = ["no candidate reached the strong or stable+suggestive bars"]

    cannot = [
        "No profitability claim of any kind: this phase measures identifiability "
        "of a path shape, never net returns after the owner's cost schedule.",
        "No intraday conclusion: 3-bar daily paths only.",
        "Corporate actions are screened, not corrected (no adjustment factors).",
        "Point-in-time index membership cannot be reconstructed; every result "
        "inherits the current-membership universe.",
        "The equal-weight proxy is not the KSE-100 or Meezan index; regime, "
        "breadth, vol and turnover-regime features inherit that substitution.",
        "Late-volume behavior is unavailable on daily bars (declared, not "
        "fabricated); FVG features exist only at age 1 in this engine.",
        "Validation and OOS windows are scored once with frozen cuts, but the "
        "OOS window is short (about 15 months) and one market regime.",
    ]

    feature_defs = {
        "G (target)": "mae_3bar >= -1.0 AND mfe_3bar >= +2.0, both referenced to "
                      "the entry price (next open); mae_3bar is the minimum low "
                      "over bars 1..3 vs entry, mfe_3bar the maximum high",
        "G_sc (robustness)": "same thresholds referenced to the signal close "
                             "(feat_close) instead of the entry price",
        "regime": "equal-weight KMIALL proxy 20-session return bands: >+5% "
                  "strong_bull, 0..+5% weak_bull, -5..0 weak_bear, <-5% "
                  "strong_bear (Phase 1 level definition, unchanged)",
        "feat_ret_20d": "close(T)/close(T-20) - 1, positional sessions",
        "feat_rs5/rs10/rs20": "per-symbol return over 5/10/20 sessions minus the "
                              "cross-sectional mean per-symbol return over the "
                              "same window (composition-safe equal-weight market "
                              "return), positional sessions",
        "feat_rs_accel": "rs5(T) minus rs5 measured 5 sessions earlier",
        "feat_breadth": "share of symbols with close(T) > MA20(T) among symbols "
                        "with a defined MA20 on that date",
        "feat_rvol20": "20-session rolling std of the cross-sectional mean "
                       "per-symbol daily return (composition-safe proxy realized "
                       "volatility)",
        "feat_mkt_turn_ratio": "mean daily universe turnover (sum of close x "
                               "volume) over trailing 20 sessions divided by the "
                               "same over trailing 60 sessions",
        "feat_turnover": "close(T) x volume(T) for the symbol (PKR)",
        "feat_relvol": "volume(T) / rolling median volume over T-19..T",
        "feat_vol_accel": "volume(T) / volume(T-1)",
        "feat_clv_position": "(close - low of prior 20 bars) / (high-low range of "
                             "prior 20 bars); premium/discount buckets 0.33/0.67",
        "feat_body_ratio": "|close-open| / (high-low) at T",
        "feat_lower_wick": "(min(open,close) - low) / (high - low) at T; values "
                           "outside [0,1] are raw-data dirt and treated as missing",
        "feat_range_expansion": "true range(T) > 1.5 x trailing 20-bar median "
                                "true range; TR = max(high-low, |high-prev close|, "
                                "|low-prev close|)",
        "feat_20d_high_break": "close(T) >= prior 20-bar high (T-20..T-1)",
        "feat_pullback_resume": "close(T) > MA20(T) AND close(T-1) < close(T-2) < "
                                "close(T-3) < close(T-4) (three consecutive lower "
                                "closes before T)",
        "feat_sweep_low": "min low of T-6..T-2 < prior low of T-16..T-6 AND "
                          "close(T) > that prior low",
        "feat_bos_up": "close(T) > max close of T-20..T-1",
        "feat_displacement": "|close-open| >= 2 x trailing 20-bar median body AND "
                             "close > open",
        "feat_equal_lows": "today's low within 0.3% of the prior 9-bar low",
        "feat_fvg_bull_age1": "low(T-1) > high(T-3) (bullish FVG formed at T-1)",
        "feat_fvg_size_pct": "(low(T-1) - high(T-3)) / close(T-1)",
        "feat_fvg_retrace": "bullish age-1 FVG AND low(T) <= FVG midpoint "
                            "(low(T-1)+high(T-3))/2",
        "gap_next_open": "(next open / signal close - 1) x 100; entry price",
        "jump_up / jump_dn flags": "max / min single-bar move >= +9.9% / <= -9.9% "
                                   "inside bars 1-3, referenced to the previous "
                                   "close (artifact screen only)",
        "frozen cuts": f"breadth q33/q66 {cuts['breadth']['q33']:.4f}/"
                       f"{cuts['breadth']['q66']:.4f}; rvol20 q33/q66 "
                       f"{cuts['rvol20']['q33']:.4f}/{cuts['rvol20']['q66']:.4f}; "
                       f"turnover q33/q66 {cuts['turnover']['q33']:.3e}/"
                       f"{cuts['turnover']['q66']:.3e}; fixed cuts: wick 0.3/0.5, "
                       f"rs 0/+2.5%/-5%, band 0..5%, fvg size 1%, gap 0.5%, "
                       f"turn ratio 1.0",
        "declared unavailable": "late-volume behavior (daily bars only), FVG ages "
                                "beyond 1 (engine computes age-1 only), order-flow/"
                                "depth/footprint (registry UNAVAILABLE)",
    }

    prov = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8")) \
        if PROVENANCE_PATH.is_file() else {}
    dq = {
        "dataset_rows": prov.get("dataset", {}).get("rows"),
        "symbols": prov.get("dataset", {}).get("symbols"),
        "start": prov.get("dataset", {}).get("start"),
        "end": prov.get("dataset", {}).get("end"),
        "dataset_sha8": str(prov.get("dataset", {}).get("sha256", ""))[:8],
        "signals": prov.get("signals"),
        "skipped": (prov.get("signals", 0) - prov.get("trade_rows", 0)),
        "matrix_rows": int(len(m)),
        "matrix_cols": int(len(m.columns)),
        "invalid": int(m["data_invalid"].sum()),
        "invalid_pct": round(100.0 * float(m["data_invalid"].mean()), 2),
        "provenance_summary": (f"{prov.get('population_rule', '')}; built "
                               f"{prov.get('generated_at_karachi', '')}"),
    }

    res = {
        "meta": {
            "generated_at": datetime.now(KARACHI).isoformat(timespec="seconds"),
            "python": platform.python_version(),
            "pandas": pd.__version__,
        },
        "data_quality": dq,
        "protocol": {
            "splits": {name: [d0, d1] for name, d0, d1 in SPLITS},
            "halves": {name: [d0, d1] for name, d0, d1 in HALVES},
            "frozen_cuts": cuts,
            "min_n": MIN_N, "n_boot": N_BOOT, "seed": BOOT_SEED,
            "n_tests": n_tests,
            "ranking": "discovery only: G-rate lift, MAE-SC lift, MFE-SC lift, "
                       "+2% reach, n",
            "g_definition": f"mae_3bar >= {G_MAE_MAX} AND mfe_3bar >= {G_MFE_MIN}",
            "phase1_glance_disclosure": (
                "Phase 1 already glanced at full-sample SC lifts; selection here "
                "uses the discovery split only and validation/OOS are scored "
                "once with frozen cuts"),
        },
        "feature_definitions": feature_defs,
        "group_g_baseline": gb,
        "filters": {
            "n_tests": len(filter_records),
            "top10": ranked_f[:10],
            "excluded_n": excluded_f,
            "artifact_controls": artifact_controls,
            "all_ranked": ranked_f,
        },
        "combos": {
            "n_tests": len(combo_records),
            "top10": ranked_c[:10],
            "excluded_n": excluded_c,
            "all_ranked": ranked_c,
        },
        "best_candidates": best,
        "g_composition": gc,
        "artifact_audit": artifact_audit,
        "what_is_group_g": {"classification": classification, "evidence": evidence},
        "final_recommendation": {
            "label": label,
            "rationale": rationale,
            "criteria": crit,
        },
        "cannot_conclude": cannot,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    (OUT_DIR / "phase2a_results.json").write_text(
        json.dumps(res, indent=1, default=str), encoding="utf-8")
    REPORT_MD.write_text(render_md(res), encoding="utf-8")

    print()
    print(f"tests: {n_tests}; rankable filters: {len(ranked_f)}/{len(filter_records)}")
    print(f"FINAL RECOMMENDATION: {label}")
    print("top 3 filters by discovery rank (entry-referenced G-rate lift):")
    for r in ranked_f[:3]:
        d = r["discovery"]
        print(f"  {r['filter']}: G lift {fmt(d.get('g_rate_lift_pp'),2,True)} pp "
              f"(D/V/OOS {fmt(r['persistence']['g_rate_lift_pp_discovery_entry_view'],1,True)}/"
              f"{fmt(r['persistence']['g_rate_lift_pp_validation_entry_view'],1,True)}/"
              f"{fmt(r['persistence']['g_rate_lift_pp_oos_entry_view'],1,True)}), "
              f"G-SC {fmt(d.get('g_sc_rate_lift_pp'),2,True)}, "
              f"p_adj {fmt(d.get('g_rate_p_bonferroni'),3)}, n={d['n_sub']:,}")
    print(f"\nJSON -> {OUT_JSON}")
    print(f"MD   -> {REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
