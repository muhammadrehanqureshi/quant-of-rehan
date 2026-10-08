"""Phase 2B shared library: outcome labels, lifts, vetoes, ranking.

The research layer for Phase 2B (RESEARCH_PHASE2B.md). Everything here is
derived from EXISTING Phase 1/2A machinery, unchanged:

  - entry convention is the engine's (src/backtest/engine.py): decided at
    the close of T, executed at the OPEN of the next session, TP +2.0% /
    SL -1.0% off the entry, 3-session holding cap;
  - fills follow the engine: TP is a limit order that fills exactly (+2%)
    even when price gapped above it; SL fills at the stop or at the open
    when the bar gapped through it; a session bar that touches BOTH levels
    has unknowable intrabar ordering without intraday data, so the tie is
    resolved CONSERVATIVELY as SL-first (the owner's documented rule).
  - no future information is used anywhere: features were already frozen
    causally by scripts/build_trade_matrix.py (tests there assert it).

PSX units: percent rates are stored as fractions (0.02 = +2%).
Bootstrap seed 20261006 is the Phase 2A convention and is kept.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TP_PCT = 2.0    # owner's law, unchanged (percent)
SL_PCT = 1.0    # owner's law, unchanged (percent)
MAX_HOLD = 3
BOOT_SEED = 20261006
N_BOOT = 1000

# The label set. TP_FIRST/SL_FIRST/NEITHER follow the conservative same-bar
# rule above. TP_FIRST_AMBIG is the diagnostic bucket (both levels inside
# one bar; ordering unknowable), counted separately and NOT part of TP_FIRST.
LABELS = ("TP_FIRST", "SL_FIRST", "NEITHER", "TP_FIRST_AMBIG")

# Market-veto proposal 1: breadth q20 frozen on discovery rows (computed by
# scripts/research_phase2b.py and pasted here once, never refit on later
# periods; measured value 0.3750 on the frozen 2A matrix).
VETO_CUT = 0.3750


def stop_fill_price(entry: float, open_price: float) -> float:
    """Daily stop execution: fill at the open when it gaps below the stop."""
    stop = entry * (1.0 - SL_PCT / 100.0)
    if np.isfinite(open_price) and open_price < stop:
        return float(open_price)
    return float(stop)


def label_row(entry: float, highs: list[float], lows: list[float]) -> tuple[str, int, int]:
    """Label one (entry, highs 1..k, lows 1..k) trade path.

    Returns (label, bar_of_first_tp_touch, bar_of_first_sl_touch); touch
    bars are 0 when that level was never reached. The SAME-BAR tie rule is
    conservative: when a bar touches both levels the label is SL_FIRST and
    the diagnostic TP_FIRST_AMBIG bucket only applies when the tie happens
    at the FIRST touching bar.
    """
    tp = entry * (1.0 + TP_PCT / 100.0)
    sl = entry * (1.0 - SL_PCT / 100.0)
    p_bar = 0
    s_bar = 0
    for k, (h, l) in enumerate(zip(highs, lows), start=1):
        if not (np.isfinite(h) and np.isfinite(l) and np.isfinite(entry) and entry > 0):
            break
        ph = h >= tp
        slh = l <= sl
        if ph and not p_bar:
            p_bar = k
        if slh and not s_bar:
            s_bar = k
        if p_bar and s_bar:
            break
    if not p_bar and not s_bar:
        return "NEITHER", 0, 0
    if p_bar == s_bar:
        # both levels inside one bar: conservative SL resolution
        return "TP_FIRST_AMBIG", p_bar, s_bar
    if s_bar and (not p_bar or s_bar < p_bar):
        return "SL_FIRST", p_bar, s_bar
    return "TP_FIRST", p_bar, s_bar


def label_frame(v: pd.DataFrame) -> pd.DataFrame:
    """Attach label / touch-bar columns to the valid matrix rows.

    v must carry entry_price and h1..h3 / l1..l3. Nothing else is touched.
    """
    out = v.copy()
    labels: list[str] = []
    pbars: list[int] = []
    sbars: list[int] = []
    for row in out.itertuples(index=False):
        lab, pb, sb = label_row(float(row.entry_price),
                                [getattr(row, f"h{k}") for k in (1, 2, 3)],
                                [getattr(row, f"l{k}") for k in (1, 2, 3)])
        labels.append(lab)
        pbars.append(pb)
        sbars.append(sb)
    out["label"] = labels
    out["t_tp_first"] = pbars
    out["t_sl_first"] = sbars
    # MAE / MFE (percent, entry-referenced) within the hold window
    lows = out[["l1", "l2", "l3"]].min(axis=1)
    highs = out[["h1", "h2", "h3"]].max(axis=1)
    out["mae_entry"] = (lows / out["entry_price"] - 1.0) * 100.0
    out["mfe_entry"] = (highs / out["entry_price"] - 1.0) * 100.0
    return out


def tp_first(x: pd.DataFrame) -> float:
    """TP-first probability, honest bucket: ambiguous rows are NOT counted."""
    if len(x) == 0:
        return float("nan")
    return float((x["label"] == "TP_FIRST").mean())


def sl_first(x: pd.DataFrame) -> float:
    """SL-first-and-same-bar probability (the conservative losing bucket)."""
    if len(x) == 0:
        return float("nan")
    m = x["label"].isin(["SL_FIRST", "TP_FIRST_AMBIG"])
    return float(m.mean())


def neither(x: pd.DataFrame) -> float:
    if len(x) == 0:
        return float("nan")
    return float((x["label"] == "NEITHER").mean())


def ambiguous(x: pd.DataFrame) -> float:
    if len(x) == 0:
        return float("nan")
    return float((x["label"] == "TP_FIRST_AMBIG").mean())


def boot_rate_diff(k_sub: int, n_sub: int, k_comp: int, n_comp: int,
                   seed: int = BOOT_SEED, n_boot: int = N_BOOT):
    """Bootstrap CI + two-sided p for rate(sub) - rate(comp); 2A convention.

    Independent reseeding per comparison family keeps the CIs deterministic
    and reproducible (fixed seed, fixed order).
    """
    if n_sub == 0 or n_comp == 0:
        return (float("nan"), (float("nan"), float("nan")), float("nan"))
    rng = np.random.default_rng(seed)
    ps = rng.binomial(n_sub, k_sub / n_sub, n_boot) / n_sub
    pc = rng.binomial(n_comp, k_comp / n_comp, n_boot) / n_comp
    diff = ps - pc
    point = k_sub / n_sub - k_comp / n_comp
    lo, hi = np.percentile(diff, [2.5, 97.5])
    p = 2.0 * min((diff <= 0).mean(), (diff >= 0).mean())
    return (float(point), (float(lo), float(hi)), float(min(1.0, p)))


def headline_block(x: pd.DataFrame) -> dict:
    """The seven mandated numbers for a population, n-guarded."""
    n = int(len(x))
    b: dict = {"n": n}
    if n == 0:
        return b
    lab = x["label"]
    b["tp_first"] = round(float((lab == "TP_FIRST").mean()), 4)
    b["sl_first"] = round(float((lab == "SL_FIRST").mean()), 4)
    b["neither"] = round(float((lab == "NEITHER").mean()), 4)
    b["ambiguous_same_bar"] = round(float((lab == "TP_FIRST_AMBIG").mean()), 4)
    b["mae_median"] = round(float(x["mae_entry"].median()), 4)
    b["mfe_median"] = round(float(x["mfe_entry"].median()), 4)
    tp_times = x.loc[x["label"] == "TP_FIRST", "t_tp_first"]
    sl_times = x.loc[x["label"].isin(["SL_FIRST", "TP_FIRST_AMBIG"]), "t_sl_first"]
    b["median_t_tp"] = None if tp_times.empty else float(tp_times.median())
    b["median_t_sl"] = None if sl_times.empty else float(sl_times.median())
    return b


# ---------------------------------------------------------------- market veto
def veto_mask(v: pd.DataFrame, cut: float = VETO_CUT) -> pd.Series:
    """Market-veto proposal 1: breadth <= cut means NO candidate accepted.

    cut is a FIXED DISCOVERY-time constant (breadth q20 = 0.4011), never
    refit on other periods. Returns the vetoed-row mask.
    """
    return v["feat_breadth"] <= cut



def veto_report(v: pd.DataFrame, cut: float = VETO_CUT) -> dict:
    """How a breadth veto would have behaved, honest buckets only.

    Reports rates in vetoed vs passing bands and (on OOS) the count and TP
    share of vetoed rows. It is a RESEARCH instrument: no live behavior
    changes until the owner approves a specific rule.
    """
    m = veto_mask(v, cut)
    out = {"cut": cut, "n_vetoed": int(m.sum()), "n_pass": int((~m).sum())}
    if m.sum():
        out["vetoed"] = headline_block(v[m])
    if (~m).sum():
        out["pass"] = headline_block(v[~m])
    return out


# ------------------------------------------------------- one-winner ranking
def rank_and_pick(day: pd.DataFrame,
                  keys: tuple = ("feat_turnover", "feat_rs20"),
                  ascending: tuple = (False, True)) -> str:
    """The one-winner rule for ONE day's eligible candidates.

    Frozen default order: liquidity (turnover) first, then rs20 depth.
    Ties keep the day's first row (data already symbol-sorted). An empty
    day yields the NO-TRADE sentinel. Alternative key orders exist ONLY as
    labeled exploratory comparisons in the research runner.
    """
    if len(day) == 0:
        return "NO_TRADE"
    order = day.sort_values(list(keys), ascending=list(ascending), kind="mergesort")
    return f"PICK:{order.index[0]}"


def daily_one_winner(v: pd.DataFrame,
                     keys: tuple = ("feat_turnover", "feat_rs20"),
                     ascending: tuple = (False, True)) -> pd.DataFrame:
    """Apply rank_and_pick to every signal date; returns the pick table."""
    rows = []
    for d, day in v.groupby("signal_date", sort=True):
        pick = rank_and_pick(day, keys, ascending)
        rows.append({"signal_date": d, "n_candidates": int(len(day)), "pick": pick})
    return pd.DataFrame(rows)


def daily_winner_recall(v: pd.DataFrame, picks: pd.DataFrame) -> dict:
    """How often the one-winner pick was a TP_FIRST row (honest buckets).

    Selection recall on the FULL valid sample: not a live-day rate claim.
    Ambiguous rows are NOT counted as wins (conservative).
    """
    pick_by_day = dict(zip(picks["signal_date"], picks["pick"]))
    n_days = 0
    n_with_bad_data = 0
    n_good_days = 0
    n_picked_good = 0
    for d, day in v.groupby("signal_date", sort=True):
        n_days += 1
        if not (day["label"] == "TP_FIRST").any() and not (day["label"] == "TP_FIRST_AMBIG").any():
            continue
        n_good_days += 1
        chosen = pick_by_day.get(d, "NO_TRADE")
        if not str(chosen).startswith("PICK:"):
            n_with_bad_data += 1
            continue
        pick_pos = int(str(chosen).split(":", 1)[1])
        row = day.loc[pick_pos]
        if row["label"] == "TP_FIRST":
            n_picked_good += 1
    return {"n_days": n_days, "n_good_days": n_good_days,
            "n_picked_good": n_picked_good,
            "pick_recall": (n_picked_good / n_good_days) if n_good_days else None}
