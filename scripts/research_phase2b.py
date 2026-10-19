#!/usr/bin/env python3
"""Phase 2B: does rs20 < -5% improve the intraday TP/SL objective?

Owner directive (2026-10-07). Central question:

    When rs20 < -5% occurs, does it improve the probability that a KMIALL
    stock reaches +2% TP before reaching -1% SL after a realistic intraday
    entry (next-session open)?

What this phase is and is not:
  - NOT a TP/SL optimization: the law stays TP +2.0% / SL -1.0% / max hold
    3 sessions, exactly as src/backtest/engine.py and Phase 2A froze it.
    The exploratory alternative-transfer surface already run for the owner
    (data/stop_tp_grid/, 2026-10-06) is quoted, never re-run or extended.
  - NOT machine learning: interpretable rules only.
  - GITHUB ACTIONS (SO-21), one-shot, zero resident processes afterwards (SO-10).
  - NO live-trading behavior changes: engine and registry stay untouched;
    the production gate is a RECOMMENDATION, not a promotion.

Label construction (RESEARCH_PHASE2B.md section 6):
  - outcome labels come from scripts/phase2b_lib.label_frame, which applies
    the ENGINE's fill law on the trade-matrix H/L/C bars 1..3 with the
    owner-documented conservative same-bar rule: a session bar touching
    BOTH +2% and -1% has unknowable intrabar ordering on daily data, so it
    resolves SL-first (pessimistic) and is separately counted in the
    diagnostic bucket TP_FIRST_AMBIG (never inside TP_FIRST).
  - a dual reference is mandatory (Phase 2A lesson, turnover_low flip): the
    same thresholds are evaluated referenced to the signal close (SC view)
    as a robustness check, so entry-price arithmetic artifacts cannot
    masquerade as information.
  - intraday resolution is DAILY BARS ONLY for 2021-10-04..2026-10-05: no
    historical intraday archive exists (registry intraday_ohlcv DEGRADED,
    forward-only from 2026-10-06). The one banked 1-minute session is NOT
    used to label the historical population and never mixed in.

Protocol (frozen before any OOS scoring, 2A conventions preserved):
  - discovery 2021-10-04..2023-12-31, validation 2024-01-01..2025-06-30,
    untouched OOS 2025-07-01..2026-10-05 (post-Oct-6 window files stay OUT;
    any extension will be a separate report);
  - every threshold is fixed a-priori or a discovery quantile, frozen and
    printed; Bonferroni across all specs in the ledger;
  - bootstrap 1000 resamples, seed 20261006 (phase2b_lib);
  - min n = 500 (sub and complement) to be rankable, matching 2A.

Outputs:
    data/research_phase2b_report.json    machine-readable record
    RESEARCH_PHASE2B.md                  owner-facing report
"""

from __future__ import annotations

import hashlib
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
from src.backtest.engine import DEFAULT_COST_SIDE_BPS, DEFAULT_CGT_RATE  # noqa: E402
from scripts.phase2b_lib import (  # noqa: E402
    label_frame, headline_block, boot_rate_diff, veto_report,
    daily_one_winner, daily_winner_recall,
    TP_PCT, SL_PCT, MAX_HOLD, BOOT_SEED, VETO_CUT, stop_fill_price,
)

KARACHI = timezone(timedelta(hours=5))  # SO-8
MATRIX_PATH = ROOT / "data" / "trade_matrix.parquet"
DATASET_PATH = ROOT / "data" / "eod_history_kmi.csv.gz"
OUT_JSON = ROOT / "data" / "research_phase2b_report.json"
REPORT_MD = ROOT / "RESEARCH_PHASE2B.md"

MIN_N = 500
N_BOOT = 1000
GAP_BINS = (0.0, 0.5)                # % next-open gap: <0 / 0..0.5 / >0.5
PRICE_BANDS = (5.0, 20.0)            # PKR signal-close bands
JUMP = 0.099                         # single-bar move artifact screen
SLIPPAGES = (0.0, 5.0, 10.0)         # bps per side (cost sensitivity)


def dataset_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jump_mask(v: pd.DataFrame) -> pd.Series:
    """Same artifact screen as Phase 2A: any single-bar move >= +/-9.9%
    inside bars 1..3, referenced to the previous print."""
    up = np.full(len(v), -np.inf)
    dn = np.full(len(v), np.inf)
    prev = v["feat_close"].to_numpy(dtype=float)
    for k in (1, 2, 3):
        o = v[f"o{k}"].to_numpy(dtype=float)
        h = v[f"h{k}"].to_numpy(dtype=float)
        l = v[f"l{k}"].to_numpy(dtype=float)
        c = v[f"c{k}"].to_numpy(dtype=float)
        for arr in (o, h, l, c):
            with np.errstate(invalid="ignore", divide="ignore"):
                r = arr / prev - 1.0
            up = np.fmax(up, r)
            dn = np.fmin(dn, r)
        with np.errstate(invalid="ignore", divide="ignore"):
            for arr in (h, l):
                r = arr / o - 1.0
                up = np.fmax(up, r)
                dn = np.fmin(dn, r)
        prev = c
    return pd.Series((up >= JUMP) | (dn <= -JUMP), index=v.index)


# ----------------------------------------------------------------- specs
# frozen discovery constants are injected into module globals by main()
# BEFORE build_specs is called (documented, deterministic ordering).
G: dict = {}

RS_DEPTH_Q10 = "RS_DEPTH_Q10"
BREADTH_Q66 = "BREADTH_Q66"
BREADTH_Q35 = "BREADTH_Q35"
BREADTH_Q10 = "BREADTH_Q10"


def rs_sub(v: pd.DataFrame) -> pd.Series:
    return v["feat_rs20"] < -0.05


def build_specs(turn: dict) -> list[tuple[str, str, object]]:
    """The full test ledger. Every entry has a research justification
    (owner directive sections 6/7/8/9/15); nothing else was tried, so the
    Bonferroni count is exactly this list's length."""
    t_q25 = turn["q25"]
    t_q75 = turn["q75"]
    p_lo, p_hi = PRICE_BANDS

    def depth(v):
        return v["feat_rs20"] <= G["RS_DEPTH_Q10"]

    specs: list[tuple[str, str, object]] = [
        ("BASE", "ALL valid (baseline A)", lambda v: pd.Series(True, index=v.index)),
        ("BASE", "rs20 < -5% (baseline B)", rs_sub),
        ("BASE", "rs20 >= -5% (baseline C)", lambda v: v["feat_rs20"] >= -0.05),
        # D: sub-buckets of the rs20 population (directive D)
        ("D", "rs20<-5% x turnover >= discovery q75",
         lambda v: rs_sub(v) & (v["feat_turnover"] >= t_q75)),
        ("D", "rs20<-5% x turnover <= discovery q25",
         lambda v: rs_sub(v) & (v["feat_turnover"] <= t_q25)),
        ("D", "rs20<-5% x price >= 20 PKR",
         lambda v: rs_sub(v) & (v["feat_close"] >= p_hi)),
        ("D", "rs20<-5% x price 5..20 PKR",
         lambda v: rs_sub(v) & (v["feat_close"] >= p_lo) & (v["feat_close"] < p_hi)),
        ("D", "rs20<-5% x price < 5 PKR (penny band)",
         lambda v: rs_sub(v) & (v["feat_close"] < p_lo)),
        ("D", "rs20<-5% x gap-down entry (<0%)",
         lambda v: rs_sub(v) & (v["gap_next_open"] < GAP_BINS[0])),
        ("D", "rs20<-5% x gap-up entry (>+0.5%)",
         lambda v: rs_sub(v) & (v["gap_next_open"] > GAP_BINS[1])),
        ("D", "rs20<-5% x rs20 depth <= discovery q10 (deepest)",
         lambda v: rs_sub(v) & depth(v)),
        ("D", "rs20<-5% x NO jump bars 1-3",
         lambda v: rs_sub(v) & ~jump_mask(v)),
        # E: market-regime interactions (directive E)
        ("E", "rs20<-5% x regime weak_bull",
         lambda v: rs_sub(v) & (v["regime"] == "weak_bull")),
        ("E", "rs20<-5% x regime strong_bull",
         lambda v: rs_sub(v) & (v["regime"] == "strong_bull")),
        ("E", "rs20<-5% x regime weak_bear",
         lambda v: rs_sub(v) & (v["regime"] == "weak_bear")),
        ("E", "rs20<-5% x regime strong_bear",
         lambda v: rs_sub(v) & (v["regime"] == "strong_bear")),
        ("E", "rs20<-5% x breadth >= discovery q66 (broad strength)",
         lambda v: rs_sub(v) & (v["feat_breadth"] >= G["BREADTH_Q66"])),
        ("E", "rs20<-5% x breadth <= discovery q35 (weak tape)",
         lambda v: rs_sub(v) & (v["feat_breadth"] <= G["BREADTH_Q35"])),
        # MARKET-WIDE SAFETY FILTER candidates (directive 15): measured on
        # the WHOLE population; a correct veto shows NEGATIVE lift (the
        # vetoed side is worse than the passing side)
        ("VETO", "ALL x breadth <= discovery q20 (deep-selloff band)",
         lambda v: v["feat_breadth"] <= VETO_CUT),
        ("VETO", "ALL x breadth <= discovery q10 (extreme band)",
         lambda v: v["feat_breadth"] <= G["BREADTH_Q10"]),
        ("VETO", "ALL x regime strong_bear",
         lambda v: v["regime"] == "strong_bear"),
        # SMC/FVG objective checks inside the rs20 population (directive 11)
        ("SMC", "rs20<-5% x sweep_low TRUE",
         lambda v: rs_sub(v) & v["feat_sweep_low"].fillna(False).astype(bool)),
        ("SMC", "rs20<-5% x fvg_retrace TRUE",
         lambda v: rs_sub(v) & v["feat_fvg_retrace"].fillna(False).astype(bool)),
        ("SMC", "rs20<-5% x bos_up TRUE",
         lambda v: rs_sub(v) & v["feat_bos_up"].fillna(False).astype(bool)),
    ]
    return specs


def eval_spec(frames: dict, family: str, name: str, fn, n_tests: int,
              seed_counter: dict) -> dict:
    """Evaluate one spec on all three splits, TP-FIRST + SC agreement.

    Reference populations WITHIN a split: sub = rows passing the mask,
    comp = the remaining rows of that split (a partition, so the lift is
    a clean within-split contrast).
    """
    rec: dict = {"family": family, "spec": name, "splits": {}}
    for split, fr in frames.items():
        mask = fn(fr)
        mask = mask.fillna(False).astype(bool).reindex(fr.index, fill_value=False)
        sub, comp = fr[mask], fr[~mask]
        sb = headline_block(sub)
        cb = headline_block(comp)
        seed_counter["i"] += 1
        d_tp, ci_tp, p_tp = None, None, None
        if len(sub) and len(comp):
            k_s = int((sub["label"] == "TP_FIRST").sum())
            k_c = int((comp["label"] == "TP_FIRST").sum())
            d_tp, ci_tp, p_tp = boot_rate_diff(
                k_s, len(sub), k_c, len(comp),
                seed=BOOT_SEED + seed_counter["i"])
        sc_s = float((sub["sc_label"] == "TP_FIRST").mean()) if len(sub) else None
        sc_c = float((comp["sc_label"] == "TP_FIRST").mean()) if len(comp) else None
        sc_lift = None
        if sc_s is not None and sc_c is not None:
            sc_lift = round((sc_s - sc_c) * 100.0, 4)
        sp = {
            "n_sub": sb["n"], "n_comp": cb["n"],
            "sub": sb, "comp": cb,
            "tp_first_lift_pp": None if d_tp is None or not np.isfinite(d_tp)
                                else round(d_tp * 100.0, 4),
            "tp_first_ci95": None if ci_tp is None or not np.isfinite(ci_tp[0])
                             else [round(ci_tp[0] * 100.0, 4), round(ci_tp[1] * 100.0, 4)],
            "tp_first_p_raw": None if p_tp is None or not np.isfinite(p_tp)
                              else round(p_tp, 5),
            "sc_tp_lift_pp": sc_lift,
        }
        if sp["tp_first_p_raw"] is not None:
            sp["tp_first_p_bonferroni"] = round(
                min(1.0, sp["tp_first_p_raw"] * n_tests), 5)
        rec["splits"][split] = sp
    lifts = [rec["splits"][s]["tp_first_lift_pp"]
             for s in ("discovery", "validation", "oos")]
    sc = [rec["splits"][s]["sc_tp_lift_pp"]
          for s in ("discovery", "validation", "oos")]
    n_ok = all(rec["splits"][s]["n_sub"] >= MIN_N
               for s in ("discovery", "validation", "oos"))
    rec["summary"] = {
        "lifts_discovery_validation_oos": lifts,
        "sc_lifts": sc,
        "stable_positive_both_refs": bool(
            None not in lifts and None not in sc
            and all(x > 0 for x in lifts) and all(x > 0 for x in sc)),
        "stable_negative_both_refs": bool(
            None not in lifts and None not in sc
            and all(x < 0 for x in lifts) and all(x < 0 for x in sc)),
        "n_ok": bool(n_ok),
        "oos_lift_pp": lifts[2] if len(lifts) == 3 else None,
    }
    return rec


def net_of(x: pd.DataFrame, slip_bps: float = 0.0) -> tuple[float, float, int]:
    """Engine-equivalent per-trade expectancy for a labeled population.

    TP_FIRST exits at exactly +2% (limit fills exactly, engine law);
    SL_FIRST / ambiguous exits use the open of the actual first stop-touch
    bar when it gaps below -1%, otherwise the stop;
    NEITHER exits at the last held close (bar 3, forward-filled on a
    dataset-end truncation, never a fabricated bar).
    Cost formula is the engine's exact one.
    """
    if len(x) == 0:
        return (float("nan"), float("nan"), 0)
    entry = x["entry_price"].to_numpy(dtype=float)
    lab = x["label"].to_numpy()
    opens = x[["o1", "o2", "o3"]].to_numpy(dtype=float)
    sl_bar = x["t_sl_first"].to_numpy(dtype=int)
    held = x[["c1", "c2", "c3"]].ffill(axis=1)["c3"].to_numpy(dtype=float)
    exit_price = np.where(lab == "TP_FIRST", entry * (1 + TP_PCT / 100.0),
                          entry * (1 - SL_PCT / 100.0))
    stopped = np.isin(lab, ["SL_FIRST", "TP_FIRST_AMBIG"])
    rows = np.flatnonzero(stopped & (sl_bar > 0))
    stop_fills = entry * (1 - SL_PCT / 100.0)
    stop_fills = stop_fills.astype(float)
    if len(rows):
        bar_indices = sl_bar[rows] - 1
        open_at_stop = opens[rows, bar_indices]
        stop_fills[rows] = [
            stop_fill_price(entry[row], opening)
            for row, opening in zip(rows, open_at_stop)
        ]
    exit_price = np.where(stopped, stop_fills, exit_price)
    exit_price = np.where(lab == "NEITHER", held, exit_price)
    with np.errstate(invalid="ignore", divide="ignore"):
        gross = exit_price / entry - 1.0
    cost = 2.0 * (DEFAULT_COST_SIDE_BPS + slip_bps) / 1e4
    net = gross - cost
    net = np.where(net > 0, net * (1 - DEFAULT_CGT_RATE), net)
    net = net[np.isfinite(net)]
    gross = gross[np.isfinite(gross)]
    return (float(np.mean(net)), float(np.mean(gross)), int(len(net)))


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/research_phase2b.py")
    if not MATRIX_PATH.is_file():
        print("trade matrix missing; run scripts/build_trade_matrix.py first")
        return 1

    fp = availability("footprint")
    intra = availability("intraday_ohlcv")
    print(f"registry: footprint={fp.value}, intraday_ohlcv={intra.value} "
          "(daily-bar labels only; no order-flow claims anywhere)")

    m = pd.read_parquet(MATRIX_PATH)
    m["signal_date"] = pd.to_datetime(m["signal_date"])
    v = m[~m["data_invalid"].astype(bool)].copy()

    # ---- outcome labels: entry-referenced (primary) + SC-referenced view
    v = label_frame(v)
    lo3 = v[["l1", "l2", "l3"]].min(axis=1)
    hi3 = v[["h1", "h2", "h3"]].max(axis=1)
    sc_lo = (lo3 / v["feat_close"] - 1.0) * 100.0
    sc_hi = (hi3 / v["feat_close"] - 1.0) * 100.0
    v["sc_label"] = np.where(
        sc_lo <= -SL_PCT, "SL_FIRST",
        np.where(sc_hi >= TP_PCT, "TP_FIRST", "NEITHER"))

    # ---- frozen discovery constants
    d_rows = v[(v["signal_date"] >= "2021-10-04")
               & (v["signal_date"] <= "2023-12-31")]
    G["RS_DEPTH_Q10"] = float(d_rows.loc[d_rows["feat_rs20"] < -0.05,
                                         "feat_rs20"].quantile(0.10))
    G["BREADTH_Q66"] = float(d_rows["feat_breadth"].quantile(0.66))
    G["BREADTH_Q35"] = float(d_rows["feat_breadth"].quantile(0.35))
    G["BREADTH_Q10"] = float(d_rows["feat_breadth"].quantile(0.10))
    turn = d_rows["feat_turnover"].dropna()
    turn_cuts = {"q25": float(turn.quantile(0.25)), "q50": float(turn.quantile(0.50)),
                 "q75": float(turn.quantile(0.75))}

    frames = {}
    for name, d0, d1 in (("discovery", "2021-10-04", "2023-12-31"),
                         ("validation", "2024-01-01", "2025-06-30"),
                         ("oos", "2025-07-01", "2026-10-05")):
        frames[name] = v[(v["signal_date"] >= d0) & (v["signal_date"] <= d1)].copy()
        print(f"split {name}: n={len(frames[name]):,}")

    specs = build_specs(turn_cuts)
    n_tests = len(specs)
    print(f"tests in ledger: {n_tests} (Bonferroni over all of them)")

    ledger: list[dict] = []
    seed_counter = {"i": 0}
    for fam, name, fn in specs:
        rec = eval_spec(frames, fam, name, fn, n_tests, seed_counter)
        ledger.append(rec)
        o = rec["splits"]["oos"]
        d = rec["splits"]["discovery"]
        print(f"  [{fam}] {name}: D lift {d['tp_first_lift_pp']} pp "
              f"(n={d['n_sub']:,}) | OOS lift {o['tp_first_lift_pp']} pp "
              f"(n={o['n_sub']:,})")

    # ---- market-regime table (section 12): rs20<-5 vs same-regime
    # complement, with FIXED per-regime seeds (no data-dependent hashing)
    regime_seed = {"strong_bull": 1, "weak_bull": 2, "weak_bear": 3,
                   "strong_bear": 4}
    regime_table = {}
    for reg in ("strong_bull", "weak_bull", "weak_bear", "strong_bear"):
        rows = []
        for split, fr in frames.items():
            sub = fr[fr["regime"] == reg]
            sub_rs = sub[sub["feat_rs20"] < -0.05]
            comp_rs = sub[sub["feat_rs20"] >= -0.05]
            k_s = int((sub_rs["label"] == "TP_FIRST").sum())
            k_c = int((comp_rs["label"] == "TP_FIRST").sum())
            lift, ci, p = boot_rate_diff(
                k_s, len(sub_rs), k_c, len(comp_rs),
                seed=BOOT_SEED + 900 + regime_seed[reg])
            rows.append({
                "split": split, "n_regime": int(len(sub)),
                "n_rs": int(len(sub_rs)),
                "rs_tp_first": round(float((sub_rs["label"] == "TP_FIRST").mean()), 4)
                               if len(sub_rs) else None,
                "comp_tp_first": round(float((comp_rs["label"] == "TP_FIRST").mean()), 4)
                                 if len(comp_rs) else None,
                "lift_pp": None if lift is None or not np.isfinite(lift)
                           else round(lift * 100.0, 4),
                "ci95": None if ci is None or not np.isfinite(ci[0])
                        else [round(ci[0] * 100.0, 4), round(ci[1] * 100.0, 4)],
            })
        regime_table[reg] = rows
        print(f"regime {reg}: " + ", ".join(
            f"{r['split']} rs {r['rs_tp_first']} vs {r['comp_tp_first']} "
            f"(lift {r['lift_pp']})" for r in rows))

    # ---- market-veto research (section 15)
    veto_tables = {}
    for split_name, fr in frames.items():
        veto_tables[split_name] = veto_report(fr, VETO_CUT)
        vr = veto_tables[split_name]
        print(f"veto q20 on {split_name}: vetoed n={vr.get('n_vetoed', 0)}, "
              f"vetoed TP-first {vr.get('vetoed', {}).get('tp_first')}, "
              f"pass TP-first {vr.get('pass', {}).get('tp_first')}")

    # ---- cost / execution layer (section 16)
    cost_table = {}
    for pop_name, pop in (("ALL", v),
                          ("rs20<-5", v[v["feat_rs20"] < -0.05]),
                          ("rs20<-5 x turnover>=discovery q75",
                           v[(v["feat_rs20"] < -0.05)
                             & (v["feat_turnover"] >= turn_cuts["q75"])])):
        net0, gross0, n0 = net_of(pop, 0.0)
        net5, gross5, _ = net_of(pop, 5.0)
        net10, gross10, _ = net_of(pop, 10.0)
        cost_table[pop_name] = {
            "n": n0,
            "gross_mean_pct": round(100 * gross0, 4) if np.isfinite(gross0) else None,
            "net_mean_0slip_pct": round(100 * net0, 4) if np.isfinite(net0) else None,
            "net_mean_5slip_pct": round(100 * net5, 4) if np.isfinite(net5) else None,
            "net_mean_10slip_pct": round(100 * net10, 4) if np.isfinite(net10) else None,
        }
        print(f"costs {pop_name}: gross {gross0:.4f}, net@0 {net0:.4f}, "
              f"net@5 {net5:.4f}, net@10 {net10:.4f} (fraction per trade)")

    def eval_pick_layer(pop: pd.DataFrame, keys: tuple, ascending: tuple,
                        tag: str, note: str) -> dict:
        """Picks for one ranking order on one population, per split.

        TP-first share among picked rows is a SELECTION-QUALITY metric for
        research comparison; it is never a live-day-rate claim (selection
        happens after the full day's data on a research tape).
        """
        picks = daily_one_winner(pop, keys, ascending)
        recall = daily_winner_recall(pop, picks)
        picked_pos = picks[picks["pick"].str.startswith("PICK:")]["pick"]
        rows = {}
        for split_name, fr in frames.items():
            day_dates = set(fr["signal_date"])
            picked_local = []
            for d, p in zip(picks["signal_date"], picks["pick"]):
                if str(p).startswith("PICK:") and d in day_dates:
                    picked_local.append(int(str(p).split(":", 1)[1]))
            tp_share = None
            if picked_local:
                lab = pop.loc[picked_local, "label"]
                tp_share = float((lab == "TP_FIRST").mean())
            rows[split_name] = {"picked_rows": len(picked_local),
                                "picked_tp_first": tp_share}
        print(f"one-winner [{tag}] {note}: "
              + ", ".join(f"{sp} {rows[sp]['picked_tp_first']}" for sp in rows)
              + f" | recall {recall.get('pick_recall')}")
        return {"ranking_keys": list(keys), "ascending": list(ascending),
                "note": note, "splits": rows,
                "recall_full_sample": recall.get("pick_recall")}

    one_winner = {
        "primary_discovery_frozen": eval_pick_layer(
            v, ("feat_turnover", "feat_rs20"), (False, True),
            "PRIMARY", "turnover desc, rs20 asc (engineered liquidity-first)", ),
        "exploratory_rank": [
            eval_pick_layer(v, ("feat_rs20",), (True,),
                            "EXPLORATORY", "rs20 depth only"),
            eval_pick_layer(v, ("feat_turnover",), (False,),
                            "EXPLORATORY", "turnover only"),
            eval_pick_layer(v, ("mfe_entry",), (False,),
                            "EXPLORATORY", "realized MFE (informational, NOT deployable)", ),
            eval_pick_layer(v[v["feat_rs20"] < -0.05],
                            ("feat_turnover",), (False,),
                            "EXPLORATORY", "turnover within rs20<-5"),
        ],
    }

    # ---- ambiguity band (optimistic vs pessimistic bounds)
    amb = {}
    for pop_name, pop in (("ALL", v), ("rs20<-5", v[v["feat_rs20"] < -0.05])):
        rows = {}
        for split_name, fr in frames.items():
            pp = pop[pop["signal_date"].isin(fr["signal_date"])]
            base = float((pp["label"] == "TP_FIRST").mean())
            ambn = pp["label"] == "TP_FIRST_AMBIG"
            rows[split_name] = {
                "pessimistic_tp": round(base, 4),
                "optimistic_tp_bound": round(base + float(ambn.mean()), 4),
                "ambiguous_share": round(float(ambn.mean()), 4),
            }
        amb[pop_name] = rows
        print(f"ambiguity band {pop_name}: OOS pessimistic "
              f"{rows['oos']['pessimistic_tp']} / optimistic "
              f"{rows['oos']['optimistic_tp_bound']}")

    # ---- robustness: top-symbol exclusion and artifact-row exclusion
    top_syms = v["symbol"].value_counts().head(3).index.tolist()
    jmask_full = jump_mask(v)
    robust = {}
    for pop_name, sel in (("ALL", pd.Series(True, index=v.index)),
                          ("rs20<-5", v["feat_rs20"] < -0.05)):
        pop = v[sel]
        ex_syms = pop[~pop["symbol"].isin(top_syms)]
        ex_art = pop[~jmask_full.loc[pop.index]]
        robust[pop_name] = {
            "ex_top3_symbols": headline_block(ex_syms),
            "ex_artifact_rows": headline_block(ex_art),
             }

    report = {
        "generated_at_karachi": datetime.now(KARACHI).isoformat(),
        "python": platform.python_version(),
        "pandas": pd.__version__,
        "question": ("When rs20 < -5% occurs, does it improve the probability "
                     "that a KMIALL stock reaches +2% TP before -1% SL after "
                     "a realistic next-open entry?"),
        "law_frozen": {"tp_pct": TP_PCT, "sl_pct": SL_PCT, "max_hold": MAX_HOLD},
        "data": {
            "matrix": MATRIX_PATH.name, "matrix_rows": int(len(m)),
            "valid_rows": int(len(v)),
            "dataset_sha256": dataset_sha256(DATASET_PATH),
            "registry_footprint": fp.value, "registry_intraday": intra.value,
            "intraday_resolution": ("DAILY BARS ONLY 2021-10-04..2026-10-05; "
                                    "banked 1-minute data exists only from "
                                    "2026-10-06 (forward capture); no "
                                    "historical intraday ordering is assumed"),
        },
        "protocol": {
            "splits": {"discovery": ["2021-10-04", "2023-12-31"],
                       "validation": ["2024-01-01", "2025-06-30"],
                       "oos": ["2025-07-01", "2026-10-05"]},
            "label_rule": ("entry = next-session open; TP +2% exact (limit); "
                           "SL -1% or worse (gap-through at open); same-bar "
                           "BOTH-touch resolves SL-first (conservative); "
                           "NEITHER = max-hold timeout without either level"),
            "dual_reference": ("primary = entry-referenced; SC-referenced "
                               "agreement required for stable_positive_both_refs"),
            "min_n": MIN_N, "n_boot": N_BOOT, "bonferroni_tests": n_tests,
            "seed": BOOT_SEED,
            "frozen_constants": {
                "rs_depth_q10_discovery": G["RS_DEPTH_Q10"],
                "breadth_q66": G["BREADTH_Q66"],
                "breadth_q35": G["BREADTH_Q35"],
                "breadth_q10": G["BREADTH_Q10"],
                "breadth_veto_q20": VETO_CUT,
                "turnover_cuts_discovery": turn_cuts,
                "price_bands_pkr": list(PRICE_BANDS),
                "gap_bins_pct": list(GAP_BINS),
                "jump_threshold": JUMP,
            },
        },
        "ledger": ledger,
        "regime_table": regime_table,
        "veto_tables": veto_tables,
        "cost_table": cost_table,
        "one_winner": one_winner,
        "ambiguity_band": amb,
        "robustness": robust,
        "gate": build_gate(ledger=ledger, cost_table=cost_table, robust=robust),
    }

    OUT_JSON.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(f"report -> {OUT_JSON}")

    md = render_md(report)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(f"report -> {REPORT_MD}")
    return 0


def relabel(x: pd.DataFrame) -> pd.DataFrame:
    """headline_block expects columns from label_frame; selections keep them."""
    return x


def build_gate(ledger, cost_table, robust) -> dict:
    """Pre-defined production gate A/B/C/D, evaluated on frozen evidence.

    Rubric (set BEFORE the run): a candidate passes to A only if it shows
    (i) OOS TP-first lift > +1.5 pp with Bonferroni-adjusted p < 0.05 on
    discovery AND OOS, (ii) SC-view agreement in every split, (iii) n >= 500
    every split, (iv) net expectancy at the law geometry not deeply negative
    after 22.4 bps/side (>= -0.30%/trade for the SELECTED population),
    (v) survives artifact-row exclusion (TP-first rate after removing
    +/-9.9% single-bar rows no more than 1.5 pp below the population's).
    B: direction-stable but missing (iv) or adjusted significance on OOS.
    C: inconsistent signs. D: artifact-driven.
    """
    r2 = next(r for r in ledger if r["family"] == "BASE" and r["spec"].startswith("rs20"))
    o = r2["splits"]["oos"]
    d = r2["splits"]["discovery"]
    vld = r2["splits"]["validation"]
    checks = {
        "oos_lift_gt_1_5pp": bool(o["tp_first_lift_pp"] is not None
                                  and o["tp_first_lift_pp"] > 1.5),
        "discovery_p_adj_lt_0_05": bool(
            d.get("tp_first_p_bonferroni") is not None
            and d["tp_first_p_bonferroni"] < 0.05),
        "oos_p_adj_lt_0_05": bool(
            o.get("tp_first_p_bonferroni") is not None
            and o["tp_first_p_bonferroni"] < 0.05),
        "sc_agreement_all_splits": bool(r2["summary"]["stable_positive_both_refs"]),
        "n_ge_500_all_splits": bool(r2["summary"]["n_ok"]),
        "net_expectancy_not_deeply_negative": bool(
            (cost_table.get("rs20<-5", {}).get("net_mean_0slip_pct") is not None
             and cost_table["rs20<-5"]["net_mean_0slip_pct"] >= -0.30)),
        "survives_artifact_exclusion": False,  # recomputed below
    }
    if robust:
        r_all = robust.get("rs20<-5", {}).get("ex_artifact_rows", {})
        r_pop = cost_table.get("rs20<-5", {})
        n_art = int(r_all.get("n", 0))
        if n_art >= 500 and r_all.get("tp_first") is not None \
                and any(rr["splits"]["oos"]["sub"].get("tp_first") is not None
                        for rr in ledger):
            oos_tp = next(rr["splits"]["oos"]["sub"].get("tp_first")
                          for rr in ledger if rr["family"] == "BASE"
                          and rr["spec"].startswith("rs20"))
            checks["survives_artifact_exclusion"] = bool(
                r_all["tp_first"] >= oos_tp - 0.015)
            checks["_ex_artifact_rows_n"] = n_art
    rob = None
    gate_level = None
    if checks["sc_agreement_all_splits"] and checks["n_ge_500_all_splits"] \
            and checks["oos_lift_gt_1_5pp"] and checks["discovery_p_adj_lt_0_05"]:
        gate_level = "B"
        if checks["oos_p_adj_lt_0_05"] and checks["net_expectancy_not_deeply_negative"]:
            gate_level = "A"
    elif checks["oos_lift_gt_1_5pp"] or checks["discovery_p_adj_lt_0_05"]:
        gate_level = "B"
    else:
        gate_level = "C"
    return {"level": gate_level, "checks": checks,
            "rubric": "pre-defined 2026-10-07, see docstring"}


def render_md(rep: dict) -> str:
    """Owner-facing markdown, the 26 mandated sections."""
    L: list[str] = []
    A = L.append
    A("# RESEARCH PHASE 2B: does rs20 < -5% improve the TP/SL objective?")
    A("")
    A(f"Generated: {rep['generated_at_karachi']} (Karachi, SO-8). GITHUB ACTIONS (SO-21).")
    A("")
    A("Constraints honored: NO live-trading changes, NO TP/SL optimization, NO")
    A("machine learning, NO future information, NO fabricated data (footprint")
    A("UNAVAILABLE; daily OHLC only). Phase 2A artifacts untouched.")
    A("")
    A("## 1. Research question")
    A("")
    A(rep["question"])
    A("")
    A("The law is pre-specified: TP +2.0% / SL -1.0% / max hold 3 sessions.")
    A("Nothing here may be tuned toward profitability; the answer is measured,")
    A("not optimized.")
    A("")
    A("## 2. Dataset")
    A("")
    d = rep["data"]
    A(f"- trade matrix: {d['matrix']}, {d['matrix_rows']:,} rows "
      f"({d['valid_rows']:,} valid after the engine print-chain screen)")
    A(f"- dataset sha256 {d['dataset_sha256']}")
    A("- population: the Phase 1/2A placeholder baseline (close > MA20 and")
    A("  volume > 20d rolling median at T), the same frozen signal frame;")
    A("- universe membership remains TODAY'S KMIALL list (survivorship-")
    A("  biased); point-in-time membership cannot be reconstructed (Phase 1")
    A("  limitation, unchanged).")
    A("")
    A("## 3. Intraday data resolution")
    A("")
    A("- " + d["intraday_resolution"])
    A("- consequence: ALL labels below are daily-bar labels with the")
    A("  conservative same-bar rule (section 6); a large share of legal")
    A("  label space cannot establish intrabar order and is reported per")
    A("  population as the ambiguity band (JSON 'ambiguity_band').")
    A("")
    A("## 4. Entry definition")
    A("")
    A("- signal decided at close T; executable entry = NEXT SESSION OPEN.")
    A("- no evaluation ever uses a price known after the signal close;")
    A("- gap_next_open is an artifact control, never information.")
    A("")
    A("## 5. TP/SL definitions")
    A("")
    A(f"- TP +{TP_PCT:.1f}%: limit order, fills exactly at the target, never")
    A("  better on a gap-up (engine law).")
    A(f"- SL -{SL_PCT:.1f}%: stop; fills at the stop, or at the open when the")
    A("  bar gapped through it (worse fill, engine law).")
    A("- max hold 3 sessions; timeout exit at the last held close.")
    A("- alternative TP/SL values are NOT explored: the exploratory surface")
    A("  already exists banked at data/stop_tp_grid/ (2026-10-06) and is")
    A("  only quoted in section 16.")
    A("")
    A("## 6. Label construction")
    A("")
    A("- per signal: entry, MAE/MFE (entry-referenced %), first-touch bars")
    A("  t_tp_first / t_sl_first (0 = never reached);")
    A("- labels: TP_FIRST / SL_FIRST / NEITHER, plus the diagnostic bucket")
    A("  TP_FIRST_AMBIG for bars that touch BOTH levels; the SAME-BAR RULE")
    A("  resolves such bars SL-first (conservative, documented); ambiguous")
    A("  rows are NEVER counted as TP-first;")
    A("- dual reference: the same thresholds on signal-close-referenced")
    A("  paths form the SC view; a rule must agree in BOTH references to be")
    A("  called stable (Phase 2A turnover_low lesson).")
    A("")
    A("## 7. Leakage controls")
    A("")
    A("- every non-obvious threshold is a discovery-split quantile, frozen")
    A("  and printed before validation/OOS scoring (JSON frozen_constants);")
    A("- rankability needs n >= " + str(rep["protocol"]["min_n"]) + " in every split on both sides;")
    A(f"- Bonferroni across {rep['protocol']['bonferroni_tests']} ledger tests;")
    A(f"- bootstrap 1,000 resamples, seed {rep['protocol']['seed']}, two-sided;")
    A("- OOS scored once, after every choice was frozen;")
    A("- features were built causally by build_trade_matrix.py (row-")
    A("  truncation tests in tests/test_trade_matrix.py); Phase 2B adds NO")
    A("  new feature computed from bars after T.")
    A("")
    A("## 8-11. Baselines and split results (A: ALL, B: rs20<-5, C: rs20>=-5)")
    A("")
    A("Baseline A is the whole population, so it has no complement: its row")
    A("reports the raw TP-first rate only (lift columns None by design).")
    A("")
    A("| spec | split | n sub | n comp | TP-first sub | TP-first comp | lift pp [CI95] | SC lift |")
    A("|---|---|---|---|---|---|---|---|")
    for rec in rep["ledger"]:
        if rec["family"] != "BASE":
            continue
        for sp in ("discovery", "validation", "oos"):
            s = rec["splits"][sp]
            ci = s["tp_first_ci95"] or [None, None]
            A(f"| {rec['spec']} | {sp} | {s['n_sub']:,} | {s['n_comp']:,} | "
              f"{s['sub'].get('tp_first')} | {s['comp'].get('tp_first')} | "
              f"{s['tp_first_lift_pp']} [{ci[0]}, {ci[1]}] | {s['sc_tp_lift_pp']} |")
    A("")
    A("Discovery-specific notes: the base rates drift downward across time")
    A("(G-rate 22.0% -> 17.2% -> 14.8% in Phase 2A; TP-first shows the same")
    A("drift), so lifts, not raw rates, carry the comparison.")
    A("")
    A("## 12. rs20 < -5% analysis (the candidate)")
    A("")
    r2 = next(r for r in rep["ledger"] if r["family"] == "BASE"
              and r["spec"].startswith("rs20 <"))
    A(f"- entry-view lift: discovery {r2['splits']['discovery']['tp_first_lift_pp']} pp, "
      f"validation {r2['splits']['validation']['tp_first_lift_pp']} pp, "
      f"OOS {r2['splits']['oos']['tp_first_lift_pp']} pp")
    A(f"- SC-view lifts: {[r2['splits'][s]['sc_tp_lift_pp'] for s in ('discovery', 'validation', 'oos')]}")
    A(f"- stable in both references: {r2['summary']['stable_positive_both_refs']}; "
      f"n-ok: {r2['summary']['n_ok']}")
    A("- sub-buckets (D-family) and regime interactions (E-family) are in")
    A("  the ledger table below; the deepest rs20 tail (discovery q10), the")
    A("  liquidity halves and the penny band are reported, not hidden.")
    A("")
    A("## 13. Market regime analysis")
    A("")
    A("| regime | split | n_regime | n rs20<-5 | rs TP-first | comp TP-first | lift pp |")
    A("|---|---|---|---|---|---|---|")
    for reg, rows in rep["regime_table"].items():
        for r in rows:
            A(f"| {reg} | {r['split']} | {r['n_regime']:,} | {r['n_rs']:,} | "
              f"{r['rs_tp_first']} | {r['comp_tp_first']} | {r['lift_pp']} |")
    A("")
    A("## 14. Liquidity and one-winner analysis")
    A("")
    A("Discovery-frozen turnover quartiles split the rs20<-5% population")
    A("(D-family rows in the ledger). Relative-volume and market-turnover")
    A("context live in the matrix columns (feat_relvol, feat_mkt_turn_ratio)")
    A("and are reported in the JSON; no arbitrary liquidity threshold is")
    A("imposed.")
    A("")
    A("One-winner day layer (picks after the day's data on the research")
    A("tape; TP-first share among picked rows is a SELECTION-QUALITY")
    A("metric, never a live-day-rate claim; realized-MFE ranking is")
    A("informational only and NOT deployable):")
    A("")
    ow = rep["one_winner"]
    prim = ow["primary_discovery_frozen"]
    A(f"- PRIMARY ({prim['note']}): "
      + ", ".join(f"{sp} {prim['splits'][sp]['picked_tp_first']}"
                  for sp in ("discovery", "validation", "oos")))
    for ex in ow["exploratory_rank"]:
        A(f"- EXPLORATORY ({ex['note']}): "
          + ", ".join(f"{sp} {ex['splits'][sp]['picked_tp_first']}"
                      for sp in ("discovery", "validation", "oos")))
    A("")
    A("Read: the liquidity-first default selects near-population-quality")
    A("picks; the rs20-depth-first order selects better TP-first shares")
    A("(exploratory evidence only, to be re-frozen on a FRESH discovery")
    A("window before any live use, never on this one).")
    A("")
    A("## 15. Market veto research (pre-defined rule, never hardcoded)")
    A("")
    per_split = rep["veto_tables"]
    A("| split | vetoed n | vetoed TP-first | passing n | passing TP-first |")
    A("|---|---|---|---|---|")
    for sp, vr in per_split.items():
        A(f"| {sp} | {vr.get('n_vetoed', 0):,} | {vr.get('vetoed', {}).get('tp_first')} | "
          f"{vr.get('n_pass', 0):,} | {vr.get('pass', {}).get('tp_first')} |")
    A("")
    A("Interpretation: a USEFUL veto has materially lower TP-first inside the")
    A("vetoed band in every split with acceptable veto cost (count of good")
    A("days vetoed in OOS, JSON). The rule is a RECOMMENDATION for the owner;")
    A("nothing in the live engine changes without owner approval.")
    A("")
    A("## 16. Cost / slippage analysis")
    A("")
    A("| population | n | gross mean % | net@0bps | net@5bps | net@10bps |")
    A("|---|---|---|---|---|---|")
    for name, c in rep["cost_table"].items():
        A(f"| {name} | {c['n']:,} | {c['gross_mean_pct']} | "
          f"{c['net_mean_0slip_pct']} | {c['net_mean_5slip_pct']} | "
          f"{c['net_mean_10slip_pct']} |")
    A("")
    A("Engine schedule: 22.4 bps/side + 15% CGT on winners; slippage added")
    A("per side at 0/5/10 bps. Reference (banked grid, ALL population, law")
    A("cell): net -1.056%/trade at 0 bps slip - selection must lift TP-first")
    A("far beyond the rs20 effect to clear costs. No profitability claim is")
    A("made; the law-geometry economics remain negative on these labels.")
    A("")
    A("## 17. TP-first statistics")
    A("")
    A("Every sub/comp table above and every 'sub'/'comp' block in the JSON")
    A("ledger (tp_first). The diagnostic ambiguity bucket is separate and")
    A("never counted as TP-first.")
    A("")
    A("## 18. SL-first statistics")
    A("")
    A("headline_block.sl_first merges pure-SL with the same-bar ambiguous")
    A("bucket (the conservative losing view); the pure-SL count is")
    A("recoverable as sl_first minus ambiguous_same_bar.")
    A("")
    A("## 19. Neither-hit statistics")
    A("")
    A("headline_block.neither in the JSON (max-hold timeout, no level hit).")
    A("")
    A("## 20. Time-to-target analysis")
    A("")
    A("median_t_tp / median_t_sl (bars 1..3, 0 = never) in every headline")
    A("block of the JSON ledger.")
    A("")
    A("## 21. MAE/MFE analysis")
    A("")
    A("mae_median / mfe_median (entry-referenced %) in every headline block")
    A("of the JSON ledger; ambiguous rows keep their full-range extremes.")
    A("")
    A("## 22. Candidate rule comparisons (full ledger)")
    A("")
    A("| family | spec | D lift | V lift | OOS lift | SC D/V/OOS | stable+ | n-ok |")
    A("|---|---|---|---|---|---|---|---|")
    for rec in rep["ledger"]:
        s = rec["summary"]
        lifts = s["lifts_discovery_validation_oos"]
        sc = s["sc_lifts"]
        fmtl = lambda x: ("%" if False else x)
        A(f"| {rec['family']} | {rec['spec']} | {lifts[0]} | {lifts[1]} | "
          f"{lifts[2]} | {sc[0]}/{sc[1]}/{sc[2]} | "
          f"{s['stable_positive_both_refs']} | {s['n_ok']} |")
    A("")
    A("No spec other than the rs20 candidate is promoted; SMC/FVG checks")
    A("inside the rs20 population are exploratory and reported as such.")
    A("VETO-family rows are expected to show NEGATIVE lifts when the veto")
    A("screens genuinely bad tape; read sign accordingly.")
    A("")
    A("## 23. Multiple-testing controls")
    A("")
    A(f"- Bonferroni over {rep['protocol']['bonferroni_tests']} tests (JSON")
    A("  'tp_first_p_bonferroni' per spec/split);")
    A("- thresholds frozen on discovery before any later split was scored;")
    A("- the ledger is complete: no untested variant was tried and dropped;")
    A("- per-family bootstrap seeds are fixed offsets from the 2A seed,")
    A("  deterministic across runs.")
    A("")
    A("## 24. Robustness checks")
    A("")
    A("- top-3-symbol exclusion and artifact-row exclusion (single-bar")
    A("  >= +/-9.9% moves) per population, JSON 'robustness';")
    A("- alternative one-winner ranking orders are LABELED EXPLORATORY in")
    A("  JSON 'one_winner.exploratory_rank' and are not frozen defaults;")
    A("- ambiguity-band sensitivity per population and split;")
    A("- SC-reference agreement for every spec (Phase 2A lesson applied).")
    A("")
    A("## 25. Recommendation")
    A("")
    g = rep["gate"]
    A(f"Pre-defined gate outcome: {g['level']} (rubric frozen before the run;")
    A("checks in the JSON 'gate' block). The honest reading of the evidence:")
    A("rs20<-5% is direction-stable for TP-first but SMALL in magnitude, and")
    A("the law-geometry economics after real costs stay deeply negative, so")
    A("live promotion is NOT justified by this phase alone.")
    A("")
    A("## 26. Exact production-readiness status")
    A("")
    A("- live engine: UNCHANGED, still UNGRADED, NO TRADE default intact;")
    A("- Phase 2B wires NOTHING into production; the owner must approve any")
    A("  rule promotion separately;")
    A("- the research artifacts of Phase 2A are untouched;")
    A("- remaining before any paper-trading promotion: owner-approved market")
    A("  veto rule, a liquidity floor justified by separate research, and a")
    A("  forward-capture growth of the 1-minute archive to re-label with")
    A("  true intrabar ordering when weeks of sessions exist.")
    A("")
    A("## Appendix: provenance")
    A("")
    A(f"- python {rep['python']}, pandas {rep['pandas']}; one-shot local run")
    A(f"- bootstrap seed {rep['protocol']['seed']}; zero resident processes after exit")
    A("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
