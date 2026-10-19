#!/usr/bin/env python3
"""Build the trade-level matrix (RESEARCH_AUDIT.md section 3, pre-registered).

GITHUB ACTIONS (SO-21). Deterministic, causal, reproducible: fixed inputs, fixed
population, no randomness, no future information in any feature column.

Population: the placeholder-baseline signals of scripts/smoke_backtest.py
(close > MA20 and volume > 20d rolling median, decided at close T). Bar 1 is
the NEXT session bar for the same symbol; entry = bar 1 open (the engine's
fill model). A signal with no later bar for its symbol is skipped, counted,
never fabricated.

Honesty labels (GOVERNANCE.md SO-3):
  - universe membership is TODAY'S KMIALL list (survivorship-biased): the
    matrix carries `member_note` on every row and `data_invalid` from the
    engine's print-chain screen (band 0.60), computed exactly as the engine;
  - every `feat_*` column uses bars up to and including T only. The test
    suite truncates the dataset at an arbitrary date and asserts the
    features of a (symbol, T) row are bit-identical (leakage guard).

Output (gitignored under /data/):  data/trade_matrix.parquet

Usage:  python scripts/build_trade_matrix.py [--dataset data/eod_history_kmi.csv.gz]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

from src.backtest.engine import DEFAULT_COST_SIDE_BPS, DEFAULT_CGT_RATE, DEFAULT_INVALID_BAND  # noqa: E402
from src.signals.engine import (  # noqa: E402
    add_features, kmiall_proxy, regime_of, TP_PCT, SL_PCT, MAX_HOLD,
)

KARACHI = timezone(timedelta(hours=5))  # SO-8
OUT_PATH = ROOT / "data" / "trade_matrix.parquet"
PROVENANCE_PATH = ROOT / "data" / "trade_matrix_provenance.json"
MEMBER_NOTE = "current-membership universe (survivorship-biased)"

LEVELS = [0.5, 1.0, 1.5, 2.0]   # favorable % levels for reach timing
HORIZONS = [1, 2, 3, 5, 10]     # close-return horizons from entry


def reached_before(target_bar: int, adverse_bar: int) -> bool:
    """True only when the target is observed strictly before adverse touch.

    Daily OHLC cannot determine order within the same bar. Same-bar ties
    therefore fail the target-first test, matching the backtest's stop-first
    convention.
    """
    return target_bar != 0 and (adverse_bar == 0 or target_bar < adverse_bar)

FEATURE_COLS = [
    "ma20", "relvol", "vol_accel", "sweep_low", "sweep_high", "bos_up",
    "displacement", "clv_position", "equal_lows", "fvg_bull_age1",
    "fvg_size_pct", "fvg_retrace", "break20", "body",
    "lower_wick", "range_expansion", "pullback_resume",  # Phase 2A
]


def dataset_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def placeholder_signals(df: pd.DataFrame) -> list[tuple]:
    from scripts.smoke_backtest import placeholder_signals as sig_fn
    return sig_fn(df)


class SymbolFrame:
    """Per-symbol numpy views: O(1) position lookups by date."""

    def __init__(self, g: pd.DataFrame, feat_g: pd.DataFrame):
        self.dates = g["date"].values.astype("datetime64[ns]")
        self.open = g["open"].to_numpy(dtype=float)
        self.high = g["high"].to_numpy(dtype=float)
        self.low = g["low"].to_numpy(dtype=float)
        self.close = g["close"].to_numpy(dtype=float)
        self.volume = g["volume"].to_numpy(dtype=float)
        self.feat = {c: feat_g[c].to_numpy() for c in FEATURE_COLS}

    def pos(self, signal_date: pd.Timestamp) -> int:
        """Index of the signal date, or -1 when absent."""
        i = int(np.searchsorted(self.dates, np.datetime64(signal_date)))
        if i < len(self.dates) and self.dates[i] == np.datetime64(signal_date):
            return i
        return -1


def build_trade_rows(df: pd.DataFrame, signals: list[tuple]) -> pd.DataFrame:
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    feat = add_features(df.copy())

    # Alignment guard: feat rows must map 1:1 onto df rows (same order).
    assert len(feat) == len(df), "feature frame misaligned with dataset"
    assert (feat["symbol"].to_numpy() == df["symbol"].to_numpy()).all()
    assert (feat["date"].to_numpy() == df["date"].to_numpy()).all()

    # feature arrays are aligned positionally, so per-symbol views keep that
    # alignment by slicing feat with the same mask df was grouped by
    frames: dict[str, SymbolFrame] = {}
    feat_by_sym = {s: g for s, g in feat.groupby("symbol", sort=False)}
    for sym, g in df.groupby("symbol", sort=False):
        frames[sym] = SymbolFrame(g, feat_by_sym[sym])

    proxy = kmiall_proxy(df)
    regime = regime_of(proxy)
    reg_map = {pd.Timestamp(d): r for d, r in regime["regime"].items()}
    ret_map = {pd.Timestamp(d): float(v) for d, v in regime["proxy_ret20"].items()}

    # ---- Phase 2A cross-sectional market state (per date, causal: a date's
    # value uses that date's rows and earlier dates ONLY) ----
    elig = feat["ma20"].notna() & feat["close"].notna()
    above = (feat.loc[elig, "close"] > feat.loc[elig, "ma20"]).astype(float)
    breadth = above.groupby(feat.loc[elig, "date"]).mean()

    # composition-safe market returns: the mean of per-symbol returns over
    # the window. A level ratio of mean closes jumps whenever symbols enter
    # or leave the panel, which is composition, not return. The regime and
    # proxy_ret20 columns keep the Phase 1 level definition; only these NEW
    # columns use the return basis.
    def cross_ret(nb: int) -> pd.Series:
        r = df.groupby("symbol", sort=False)["close"].transform(
            lambda s: s / s.shift(nb) - 1.0)
        return r.groupby(df["date"]).mean()

    mkt_ret1 = cross_ret(1)
    proxy_rvol20 = mkt_ret1.rolling(20, min_periods=20).std()
    pr5 = cross_ret(5)
    pr10 = cross_ret(10)
    pr20 = cross_ret(20)
    day_turnover = (df["close"] * df["volume"]).groupby(df["date"]).sum()
    turn_ratio = (day_turnover.rolling(20, min_periods=20).mean()
                  / day_turnover.rolling(60, min_periods=60).mean())
    breadth_map = {pd.Timestamp(d): float(x) for d, x in breadth.items()}
    rvol_map = {pd.Timestamp(d): float(x) for d, x in proxy_rvol20.items()}
    pr5_map = {pd.Timestamp(d): float(x) for d, x in pr5.items()}
    pr10_map = {pd.Timestamp(d): float(x) for d, x in pr10.items()}
    pr20_map = {pd.Timestamp(d): float(x) for d, x in pr20.items()}
    turn_map = {pd.Timestamp(d): float(x) for d, x in turn_ratio.items()}

    rows: list[dict] = []
    skipped = 0
    for signal_date, symbol in signals:
        sf = frames.get(symbol)
        if sf is None:
            skipped += 1
            continue
        t = sf.pos(pd.Timestamp(signal_date))
        if t < 0 or t + 1 >= len(sf.dates):
            skipped += 1
            continue
        o1 = sf.open[t + 1]
        if not np.isfinite(o1) or o1 <= 0:
            skipped += 1
            continue
        entry = o1
        n = len(sf.dates)
        end = min(t + 1 + MAX_HOLD, n)  # entry bar + MAX_HOLD - 1 more
        held_rows = end - (t + 1)

        rec: dict = {
            "symbol": symbol,
            "signal_date": pd.Timestamp(signal_date),
            "entry_date": pd.Timestamp(sf.dates[t + 1]),
            "entry_price": float(entry),
        }
        for k in range(1, 4):
            i = t + k
            if i < end:
                rec[f"o{k}"] = float(sf.open[i])
                rec[f"h{k}"] = float(sf.high[i])
                rec[f"l{k}"] = float(sf.low[i])
                rec[f"c{k}"] = float(sf.close[i])
            else:
                for pfx in ("o", "h", "l", "c"):
                    rec[f"{pfx}{k}"] = np.nan

        def pct(price: float) -> float:
            return (price - entry) / entry * 100.0

        # MAE / MFE (entry-referenced, %, clamped at 0.0 for flat entries)
        def extreme(mode: str, upto: int) -> float:
            vals = []
            for k in range(1, upto + 1):
                v = rec[f"l{k}"] if mode == "low" else rec[f"h{k}"]
                if np.isfinite(v):
                    vals.append(pct(v))
            if not vals:
                return np.nan
            return min(vals) if mode == "low" else max(vals)
        rec["mae_1bar"] = min(0.0, extreme("low", 1)) if np.isfinite(rec["l1"]) else np.nan
        rec["mfe_1bar"] = max(0.0, extreme("high", 1)) if np.isfinite(rec["h1"]) else np.nan
        rec["mae_3bar"] = min(0.0, extreme("low", held_rows)) if held_rows else np.nan
        rec["mfe_3bar"] = max(0.0, extreme("high", held_rows)) if held_rows else np.nan

        # first touch times (bar index from entry bar = 1; 0 = never)
        def first_touch(mode: str, level_pct: float) -> int:
            for k in range(1, held_rows + 1):
                v = rec[f"l{k}"] if mode == "low" else rec[f"h{k}"]
                if not np.isfinite(v):
                    continue
                r = pct(v)
                if (mode == "low" and r <= -level_pct) or (mode == "high" and r >= level_pct):
                    return k
            return 0
        for lv in (0.5, 1.0, 1.5, 2.0):
            key = f"{int(lv * 10):02d}"
            rec[f"t_to_p{key}"] = first_touch("high", lv)
            rec[f"t_to_m{key}"] = first_touch("low", lv)

        # Ordering flags within bars 1..3. A same-bar touch has unknown order
        # and is not counted as target-first.
        rec["p05_before_m10"] = reached_before(rec["t_to_p05"], rec["t_to_m10"])
        rec["p10_before_m10"] = reached_before(rec["t_to_p10"], rec["t_to_m10"])
        rec["p15_before_m10"] = reached_before(rec["t_to_p15"], rec["t_to_m10"])
        rec["p20_before_m10"] = reached_before(rec["t_to_p20"], rec["t_to_m10"])
        rec["m10_before_p20"] = reached_before(rec["t_to_m10"], rec["t_to_p20"])
        rec["p20_before_m20"] = reached_before(rec["t_to_p20"], rec["t_to_m20"])

        # close returns from ENTRY price at horizons (last available bar
        # stands in when the horizon runs past the dataset end: labeled by
        # holding_bars, never fabricated)
        for hz in HORIZONS:
            i = min(t + hz, n - 1)
            c = sf.close[i]
            rec[f"ret_close{hz}"] = pct(c) if np.isfinite(c) and i >= t + 1 else np.nan
        rec["gap_next_open"] = ((entry / sf.close[t] - 1.0) * 100.0
                                 if np.isfinite(sf.close[t]) and sf.close[t] > 0
                                 else np.nan)
        rec["holding_bars"] = held_rows

        # time to the MAE / MFE extreme itself
        def time_to_extreme(mode: str) -> int:
            target = extreme(mode, held_rows)
            if not np.isfinite(target) or target == 0.0:
                return 0
            for k in range(1, held_rows + 1):
                v = rec[f"l{k}"] if mode == "low" else rec[f"h{k}"]
                if np.isfinite(v) and pct(v) == target:
                    return k
            return 0
        rec["t_to_mae"] = time_to_extreme("low")
        rec["t_to_mfe"] = time_to_extreme("high")

        # ---- causal features at T (bars up to and including T ONLY) ----
        rec["feat_close"] = float(sf.close[t])
        rec["feat_ma20"] = float(sf.feat["ma20"][t])
        rec["feat_relvol"] = float(sf.feat["relvol"][t])
        rec["feat_vol_accel"] = float(sf.feat["vol_accel"][t])
        rec["feat_sweep_low"] = bool(sf.feat["sweep_low"][t])
        rec["feat_sweep_high"] = bool(sf.feat["sweep_high"][t])
        rec["feat_bos_up"] = bool(sf.feat["bos_up"][t])
        rec["feat_displacement"] = bool(sf.feat["displacement"][t])
        rec["feat_clv_position"] = float(sf.feat["clv_position"][t])
        rec["feat_equal_lows"] = bool(sf.feat["equal_lows"][t])
        rec["feat_fvg_bull_age1"] = bool(sf.feat["fvg_bull_age1"][t])
        rec["feat_fvg_size_pct"] = float(sf.feat["fvg_size_pct"][t])
        rec["feat_fvg_retrace"] = bool(sf.feat["fvg_retrace"][t])
        rec["feat_20d_high_break"] = bool(sf.feat["break20"][t])
        hl_range = float(sf.high[t]) - float(sf.low[t])
        rec["feat_body_ratio"] = (float(sf.feat["body"][t]) / hl_range
                                  if np.isfinite(hl_range) and hl_range > 0 else np.nan)
        rec["feat_ret_20d"] = (sf.close[t] / sf.close[t - 20] - 1.0
                               if t >= 20 and sf.close[t - 20] > 0 else np.nan)

        # ---- Phase 2A per-row features (all causal, bars <= T) ----
        rec["feat_lower_wick"] = float(sf.feat["lower_wick"][t])
        rec["feat_range_expansion"] = bool(sf.feat["range_expansion"][t])
        rec["feat_pullback_resume"] = bool(sf.feat["pullback_resume"][t])
        rec["feat_breadth"] = breadth_map.get(pd.Timestamp(signal_date), np.nan)
        rec["feat_rvol20"] = rvol_map.get(pd.Timestamp(signal_date), np.nan)
        rec["feat_mkt_turn_ratio"] = turn_map.get(pd.Timestamp(signal_date), np.nan)
        rec["feat_turnover"] = (float(sf.close[t]) * float(sf.volume[t])
                                if np.isfinite(sf.volume[t]) and sf.volume[t] > 0
                                else np.nan)

        # relative strength vs the equal-weight proxy; positional bar offsets,
        # the same convention as feat_ret_20d
        def ret_bars(nb: int) -> float:
            if t >= nb and np.isfinite(sf.close[t - nb]) and sf.close[t - nb] > 0:
                return float(sf.close[t] / sf.close[t - nb] - 1.0)
            return np.nan
        r5, r10 = ret_bars(5), ret_bars(10)
        d = pd.Timestamp(signal_date)
        rec["feat_ret_5d"] = r5
        rec["feat_ret_10d"] = r10
        rec["feat_rs5"] = r5 - pr5_map.get(d, np.nan)
        rec["feat_rs10"] = r10 - pr10_map.get(d, np.nan)
        rec["feat_rs20"] = rec["feat_ret_20d"] - pr20_map.get(d, np.nan)
        if t >= 10 and np.isfinite(r5):
            r5_prev = (float(sf.close[t - 5] / sf.close[t - 10] - 1.0)
                       if np.isfinite(sf.close[t - 10]) and sf.close[t - 10] > 0
                       else np.nan)
            d_prev = pd.Timestamp(sf.dates[t - 5])
            rec["feat_rs_accel"] = ((r5 - pr5_map.get(d, np.nan))
                                    - (r5_prev - pr5_map.get(d_prev, np.nan)))
        else:
            rec["feat_rs_accel"] = np.nan

        rec["regime"] = reg_map.get(d, "unknown")
        rec["proxy_ret20"] = ret_map.get(d, np.nan)
        rec["member_note"] = MEMBER_NOTE

        # engine print-chain invalid screen (band 0.60), exact semantics
        prev_print = sf.close[t] if np.isfinite(sf.close[t]) and sf.close[t] > 0 else np.nan
        worst = 0.0
        finite_ok = np.isfinite(entry)
        for i in range(t + 1, end):
            o, c = sf.open[i], sf.close[i]
            if not (np.isfinite(o) and np.isfinite(c) and o > 0):
                finite_ok = False
            start_ref = prev_print
            for p in (o, c):
                if np.isfinite(prev_print) and prev_print > 0 and np.isfinite(p) and p > 0:
                    worst = max(worst, abs(p / prev_print - 1.0))
                    prev_print = p
            if np.isfinite(start_ref) and start_ref > 0 and np.isfinite(c) and c > 0:
                worst = max(worst, abs(c / start_ref - 1.0))
        rec["data_invalid"] = bool(worst > DEFAULT_INVALID_BAND or not finite_ok)
        rows.append(rec)

    if skipped:
        print(f"signals skipped (no next bar / missing symbol / bad entry): {skipped}")
    out = pd.DataFrame(rows)
    return out.sort_values(["symbol", "signal_date"]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/build_trade_matrix.py")
    ap = argparse.ArgumentParser(description="Build the trade matrix (audit section 3)")
    ap.add_argument("--dataset", type=Path, default=ROOT / "data" / "eod_history_kmi.csv.gz")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"dataset missing: {args.dataset}")
        return 1

    df = pd.read_csv(args.dataset, parse_dates=["date"])
    print(f"dataset: {args.dataset.name}, {len(df):,} rows, "
          f"{df['symbol'].nunique()} symbols, {df['date'].min().date()}..{df['date'].max().date()}")

    signals = placeholder_signals(df)
    print(f"placeholder-baseline signals: {len(signals):,} "
          "(close>MA20 & volume>20d median at T)")

    matrix = build_trade_rows(df, signals)
    print(f"trade matrix: {len(matrix):,} rows x {len(matrix.columns)} cols; "
          f"data_invalid: {int(matrix['data_invalid'].sum()):,}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_parquet(args.out, index=False)

    prov = {
        "generated_at_karachi": datetime.now(KARACHI).isoformat(),
        "dataset": {"path": args.dataset.name,
                    "sha256": dataset_sha256(args.dataset),
                    "rows": int(len(df)),
                    "symbols": int(df["symbol"].nunique()),
                    "start": str(df["date"].min().date()),
                    "end": str(df["date"].max().date())},
        "population_rule": ("close>MA20 and volume>20d rolling median at T "
                            "(placeholder baseline, NOT a strategy)"),
        "signals": len(signals),
        "trade_rows": int(len(matrix)),
        "member_note": MEMBER_NOTE,
        "invalid_screen": f"engine print-chain screen (band {DEFAULT_INVALID_BAND}), exact semantics",
        "cost_model": {"cost_side_bps": DEFAULT_COST_SIDE_BPS, "cgt_rate": DEFAULT_CGT_RATE},
        "law_parameters": {"tp_pct": TP_PCT, "sl_pct": SL_PCT, "max_hold": MAX_HOLD},
        "determinism": ("fixed dataset + fixed rule + no randomness; re-running "
                        "reproduces identical rows"),
        "causality": ("feat_* columns use bars up to and including T only; "
                      "verified by tests/test_trade_matrix.py"),
        "phase2a_columns": (
            "added for the Group G study: feat_lower_wick, feat_range_expansion, "
            "feat_pullback_resume (per-symbol, engine add_features); "
            "feat_breadth, feat_rvol20, feat_mkt_turn_ratio (cross-sectional "
            "per date); feat_turnover (close x volume at T); feat_ret_5d/10d, "
            "feat_rs5/rs10/rs20/rs_accel (vs the equal-weight proxy)"),
    }
    PROVENANCE_PATH.write_text(json.dumps(prov, indent=2), encoding="utf-8")
    print(f"provenance -> {PROVENANCE_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
