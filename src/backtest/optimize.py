"""Staged local parameter search with in-sample AND out-of-sample reporting.

SO-4: this runs on the owner's PC and nowhere else. Nothing here opens a socket.

Two things this module refuses to do
------------------------------------
1. **It never reports an in-sample number alone.** Every candidate carries an
   ``in_sample`` metric block and, when the walk-forward split is evaluable, an
   ``out_of_sample`` block beside it. The owner's target may be scored on the
   in-sample figure, but the out-of-sample figure is printed next to it in the
   same row, so an overfit gap is visible rather than hidden.
2. **It never silently books fake data as a result.** The evaluator reproduces
   the engine's circuit-band screen (``DEFAULT_INVALID_BAND``): a trade whose
   adjacent-print chain moves further than any PSX band is an unadjusted
   corporate action or a corrupt print, so it is flagged and excluded from the
   metrics rather than counted as a win.

Why there is a second evaluator
-------------------------------
``src/backtest/engine.py`` is the authority and stays so, but it costs about
0.30 ms per signal (an O(n) index lookup per signal), which makes a 100-point
sweep take roughly 25 minutes. ``evaluate_paths`` walks a precomputed forward
-path matrix instead and does the same arithmetic vectorised. The two are held
together by ``cross_check``, which runs both on the same signals and fails if
they disagree on outcome, exit price or net return. A test asserts that
agreement on every run, so the fast path can never quietly drift from the
authoritative one.

Staging
-------
Stage 1 sweeps the exit law (``tp`` x ``sl`` x ``max_hold``) against the shipped
scanner thresholds -- cheap, and it answers "is this reward:risk geometry even
viable?". Stage 2 freezes the best exit geometry from stage 1 and sweeps the
scanner's own parameters (weights, score floor, relative-volume floor, traded
-value floor), rebuilding signals for each point.

Usage::

    from src.backtest.optimize import run_staged_search, ExitLaw
    report = run_staged_search(frame, target=0.90)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from itertools import product
from typing import Callable

import numpy as np
import pandas as pd

from src import config
from src.backtest.daily_strategy import (ScannerParams, build_path_matrix,
                                         build_signals)
from src.backtest.engine import (DEFAULT_CGT_RATE, DEFAULT_COST_SIDE_BPS,
                                 DEFAULT_INVALID_BAND)
from src.backtest.walkforward import walk_forward_splits

#: The owner's universal exit law (TP +2% / SL -1%, 2:1).
OWNER_LAW = (0.02, 0.01, 3)

#: Progress callback: ``(done, total, current_item) -> None``. ``current_item``
#: is whatever the sweep is on at that moment (an ExitLaw, a ScannerParams, or
#: a label string), so a caller can log it without depending on its type.
ProgressFn = Callable[[int, int, object], None]

#: Below this many trades a rate is noise, not a measurement. The repo's own
#: research protocol uses min_n = 500; candidates under it are still reported,
#: but flagged.
DEFAULT_MIN_TRADES = 500

# Search grids as module constants so the report's protocol block can never
# drift from what the sweep actually ran.
EXIT_TP_GRID: tuple[float, ...] = (0.005, 0.010, 0.015, 0.020, 0.030, 0.050)
EXIT_SL_GRID: tuple[float, ...] = (0.005, 0.010, 0.020, 0.030, 0.050, 0.080)
EXIT_HOLD_GRID: tuple[int, ...] = (1, 2, 3, 5, 10)
#: Score floors reach 96 on purpose: if a 90% win rate exists anywhere, it is
#: at the far selective corner, and the search must actually go there.
SCAN_SCORE_GRID: tuple[float, ...] = (0.0, 40.0, 55.0, 70.0, 85.0, 92.0, 96.0)
SCAN_RELVOL_GRID: tuple[float, ...] = (0.0, 1.5, 2.5, 4.0)
SCAN_VALUE_GRID: tuple[float, ...] = (0.0, 5e6, 2e7)


@dataclass(frozen=True)
class ExitLaw:
    """TP / SL / max-hold geometry. tp and sl are fractions, not percents."""

    tp: float
    sl: float
    max_hold: int

    def __post_init__(self) -> None:
        if self.tp <= 0 or self.sl <= 0:
            raise ValueError("tp and sl must be positive fractions")
        if self.max_hold < 1:
            raise ValueError("max_hold must be >= 1")

    @property
    def reward_risk(self) -> float:
        return self.tp / self.sl

    def as_dict(self) -> dict:
        return {"tp": self.tp, "sl": self.sl, "max_hold": self.max_hold,
                "reward_risk": round(self.reward_risk, 4)}


@dataclass
class Metrics:
    """Trade statistics. Field names mirror the engine's own summary keys."""

    n_trades: int = 0
    win_rate: float = float("nan")
    tp_rate: float = float("nan")
    sl_rate: float = float("nan")
    timeout_rate: float = float("nan")
    expectancy_net: float = float("nan")
    median_net: float = float("nan")
    avg_win_net: float = float("nan")
    avg_loss_net: float = float("nan")
    profit_factor_gross: float = float("nan")
    max_drawdown: float = float("nan")
    final_equity: float = float("nan")
    avg_bars_held: float = float("nan")
    n_data_invalid: int = 0
    n_missing_exit: int = 0
    n_symbols: int = 0
    note: str = ""

    @property
    def is_meaningful(self) -> bool:
        return self.n_trades >= DEFAULT_MIN_TRADES

    def as_dict(self) -> dict:
        out = asdict(self)
        for key, value in list(out.items()):
            if isinstance(value, float):
                out[key] = None if not np.isfinite(value) else round(value, 6)
        out["is_meaningful"] = self.is_meaningful
        return out


def _require_columns(paths: pd.DataFrame, law: ExitLaw) -> None:
    missing = [f"{name}{k}" for k in range(1, law.max_hold + 1)
               for name in ("o", "h", "l", "c")]
    absent = [c for c in missing if c not in paths.columns]
    if absent:
        raise ValueError(
            f"path matrix lacks {absent[:6]}... for max_hold={law.max_hold}; "
            f"build it with a horizon of at least {law.max_hold}")


def break_even_win_rate(
    law: ExitLaw,
    *,
    cost_side_bps: float = DEFAULT_COST_SIDE_BPS,
    cgt_rate: float = DEFAULT_CGT_RATE,
) -> float:
    """The win rate at which this geometry's expectancy is exactly zero.

    Conservative in one deliberate way: every loser is assumed to fill at the
    full stop, so the figure is a FLOOR on the accuracy the geometry needs. A
    win nets ``(tp - round_trip) * (1 - cgt)``; a loss costs
    ``sl + round_trip`` (no tax credit on a loss). Solving
    ``p * net_win - (1 - p) * net_loss = 0`` gives the break-even.

    This is the number that decides whether an accuracy target is even
    meaningful: a tiny target against a wide stop needs an accuracy so close to
    100% that no filter can supply it.
    """
    costs = 2.0 * float(cost_side_bps) / 1e4
    if law.tp <= costs:
        return 1.0  # a single win cannot cover the round trip at all
    net_win = (law.tp - costs) * (1.0 - float(cgt_rate))
    net_loss = law.sl + costs
    return float(net_loss / (net_win + net_loss))


def evaluate_paths(
    paths: pd.DataFrame,
    law: ExitLaw = ExitLaw(*OWNER_LAW),
    *,
    cost_side_bps: float = DEFAULT_COST_SIDE_BPS,
    cgt_rate: float = DEFAULT_CGT_RATE,
    invalid_band: float = DEFAULT_INVALID_BAND,
) -> Metrics:
    """Vectorised equivalent of ``engine.run_backtest`` for a fixed exit law.

    Mirrors the engine's conservatism exactly: entry at the next bar's open, the
    stop resolved before the target on every bar, a stop gap-through filled at
    the open (worse), a target filled at exactly ``tp_price`` (never better),
    and a timeout at the last available close.
    """
    n = len(paths)
    if n == 0:
        return Metrics(note="no signals")
    _require_columns(paths, law)
    H = law.max_hold

    entry = paths["entry"].to_numpy(dtype="float64")
    o = np.column_stack([paths[f"o{k}"].to_numpy(dtype="float64") for k in range(1, H + 1)])
    h = np.column_stack([paths[f"h{k}"].to_numpy(dtype="float64") for k in range(1, H + 1)])
    low = np.column_stack([paths[f"l{k}"].to_numpy(dtype="float64") for k in range(1, H + 1)])
    c = np.column_stack([paths[f"c{k}"].to_numpy(dtype="float64") for k in range(1, H + 1)])

    has_ord = all(f"ord{k}" in paths.columns for k in range(1, H + 1))
    if has_ord:
        ordinals = np.column_stack(
            [paths[f"ord{k}"].to_numpy(dtype="int64") for k in range(1, H + 1)])

    valid = (np.isfinite(o) & np.isfinite(h) & np.isfinite(low) & np.isfinite(c)
             & (o > 0) & (low > 0) & (c > 0))
    # First bar that is missing/defective; bars are contiguous by construction,
    # so every bar before it is usable and nothing after it can be trusted.
    first_bad = np.where(~valid, np.arange(H)[None, :], H).min(axis=1)
    eff = np.minimum(H, first_bad)

    tp_price = entry * (1.0 + law.tp)
    sl_price = entry * (1.0 - law.sl)
    in_range = np.arange(H)[None, :] < eff[:, None]

    stop_hit = in_range & (low <= sl_price[:, None])
    tp_hit = in_range & (h >= tp_price[:, None])
    hit = stop_hit | tp_hit
    any_hit = hit.any(axis=1)
    rows = np.arange(n)
    first_k = np.where(any_hit, hit.argmax(axis=1), 0)

    # Hit branch: the stop wins any bar where both levels are touched.
    took_stop = stop_hit[rows, first_k]
    exit_hit = np.where(took_stop, np.minimum(o[rows, first_k], sl_price), tp_price)
    held_hit = first_k + 1

    # Timeout branch: exit at the last bar that actually exists.
    last_k = np.maximum(eff - 1, 0)
    exit_timeout = c[rows, last_k]
    held_timeout = eff

    exit_price = np.where(any_hit, exit_hit, exit_timeout)
    bars_held = np.where(any_hit, held_hit, held_timeout)
    outcome = np.where(any_hit, np.where(took_stop, "SL", "TP"), "TIMEOUT")

    good = np.isfinite(exit_price) & (exit_price > 0)
    n_missing = int((~good).sum())

    gross = np.where(good, exit_price / entry - 1.0, np.nan)

    # --- circuit-band screen (mirrors engine.run_backtest) ----------------
    worst = np.zeros(n)
    prev = paths["prior_close"].to_numpy(dtype="float64") if "prior_close" in paths.columns \
        else np.full(n, np.nan)
    for k in range(H):
        usable = in_range[:, k]
        o_k, c_k = o[:, k], c[:, k]
        with np.errstate(invalid="ignore", divide="ignore"):
            m_open = np.abs(o_k / prev - 1.0)
            m_body = np.abs(c_k / o_k - 1.0)
            m_direct = np.abs(c_k / prev - 1.0)
        for move in (m_open, m_body, m_direct):
            worst = np.where(usable & np.isfinite(move),
                             np.maximum(worst, move), worst)
        prev = np.where(usable, c_k, prev)
    data_invalid = (worst > invalid_band) | ~np.isfinite(gross)

    costs = 2.0 * float(cost_side_bps) / 1e4
    net = gross - costs
    net = np.where(net > 0, net * (1.0 - float(cgt_rate)), net)
    net = np.where(data_invalid, np.nan, net)

    keep = np.isfinite(net)
    metrics = Metrics(n_trades=int(keep.sum()), n_data_invalid=int(data_invalid.sum()),
                      n_missing_exit=n_missing)
    if metrics.n_trades == 0:
        metrics.note = "no trades survived the data-quality screen"
        return metrics

    kept_net = net[keep]
    kept_gross = gross[keep]
    wins = kept_net[kept_net > 0]
    losses = kept_net[kept_net <= 0]
    gross_win = kept_gross[kept_gross > 0].sum()
    gross_loss = -kept_gross[kept_gross <= 0].sum()

    # Realised equity is chronological. Order by the exit session when the
    # ordinals are present, else fall back to signal order.
    if has_ord:
        exit_ord = np.where(any_hit, ordinals[rows, first_k],
                            ordinals[rows, last_k])[keep]
        order = np.argsort(exit_ord, kind="mergesort")
    else:
        order = np.arange(metrics.n_trades)
    curve = np.concatenate(([1.0], np.cumprod(1.0 + kept_net[order])))
    peak = np.maximum.accumulate(curve)

    metrics.win_rate = float((kept_net > 0).mean())
    kept_outcome = outcome[keep]
    metrics.tp_rate = float((kept_outcome == "TP").mean())
    metrics.sl_rate = float((kept_outcome == "SL").mean())
    metrics.timeout_rate = float((kept_outcome == "TIMEOUT").mean())
    metrics.expectancy_net = float(kept_net.mean())
    metrics.median_net = float(np.median(kept_net))
    metrics.avg_win_net = float(wins.mean()) if wins.size else 0.0
    metrics.avg_loss_net = float(losses.mean()) if losses.size else 0.0
    metrics.profit_factor_gross = (float(gross_win / gross_loss)
                                   if gross_loss > 0 else float("inf"))
    metrics.final_equity = float(curve[-1])
    metrics.max_drawdown = float(np.max(1.0 - curve / peak))
    metrics.avg_bars_held = float(bars_held[keep].mean())
    if "symbol" in paths.columns:
        metrics.n_symbols = int(pd.Series(paths["symbol"].to_numpy()[keep]).nunique())
    return metrics


def cross_check(frame: pd.DataFrame, params: ScannerParams, law: ExitLaw,
                *, sample: int = 400, seed: int = 20261010) -> dict:
    """Prove the vectorised evaluator agrees with the authoritative engine.

    Runs ``engine.run_backtest`` on a random sample of the same signals and
    compares outcome and net return trade by trade. Raises AssertionError on any
    disagreement, so a silent divergence between the two implementations can
    never ship.
    """
    from src.backtest.engine import run_backtest

    scored, mask = build_signals(frame, params)
    paths, _ = build_path_matrix(scored, mask, horizon=max(law.max_hold, 1))
    if paths.empty:
        return {"compared": 0, "note": "no signals to compare"}

    rng = np.random.default_rng(seed)
    take = np.sort(rng.choice(len(paths), size=min(sample, len(paths)), replace=False))
    subset = paths.iloc[take]

    signals = [(row.signal_date, row.symbol) for row in subset.itertuples(index=False)]
    trades, _ = run_backtest(_as_engine_frame(frame), signals,
                             tp=law.tp, sl=law.sl, max_hold=law.max_hold)
    fast = evaluate_paths(subset, law)

    if trades.empty:
        if fast.n_trades != 0:
            raise AssertionError(
                f"engine produced no trades but the fast path produced {fast.n_trades}")
        return {"compared": 0, "note": "no trades on either side"}

    # The engine keeps data-invalid trades in its record and excludes them from
    # metrics, so compare against the SAME screened subset it scores.
    invalid = (trades["data_invalid"].astype(bool) if "data_invalid" in trades.columns
               else pd.Series(False, index=trades.index))
    valid = trades.loc[~invalid]
    if len(valid) != fast.n_trades:
        raise AssertionError(
            f"trade counts differ after the band screen: engine {len(valid)} "
            f"(of {len(trades)} raw) vs fast {fast.n_trades}")
    if len(valid) == 0:
        return {"compared": 0, "note": "every sampled trade was data-invalid"}

    engine_win = float((valid["net_ret"] > 0).mean())
    engine_exp = float(valid["net_ret"].mean())
    if abs(engine_win - fast.win_rate) > 1e-9:
        raise AssertionError(f"win rate differs: engine {engine_win!r} vs fast {fast.win_rate!r}")
    if abs(engine_exp - fast.expectancy_net) > 1e-9:
        raise AssertionError(
            f"expectancy differs: engine {engine_exp!r} vs fast {fast.expectancy_net!r}")
    return {
        "compared": int(len(valid)),
        "n_below_screen": int(len(trades) - len(valid)),
        "engine_win_rate": round(engine_win, 6),
        "fast_win_rate": round(float(fast.win_rate), 6),
        "engine_expectancy": round(engine_exp, 6),
        "fast_expectancy": round(float(fast.expectancy_net), 6),
    }


def _as_engine_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """The engine expects [symbol, date, open, close] (+ optional high/low)."""
    keep = [c for c in ("symbol", "date", "open", "high", "low", "close")
            if c in frame.columns]
    return frame.loc[:, keep].copy()


def _split_mask(paths: pd.DataFrame, dates: set) -> np.ndarray:
    if paths.empty:
        return np.zeros(0, dtype=bool)
    signal = pd.to_datetime(paths["signal_date"])
    return signal.isin(pd.DatetimeIndex(sorted(dates))).to_numpy()


@dataclass
class Candidate:
    """One parameter point, scored in-sample and (when possible) out-of-sample."""

    label: str
    exit_law: ExitLaw
    scanner: ScannerParams
    in_sample: Metrics
    out_of_sample: Metrics | None = None
    oos_folds: list[dict] = field(default_factory=list)

    @property
    def target_hit(self) -> bool:
        return False  # set by the caller through target_hit_for

    def break_even(self) -> float:
        return break_even_win_rate(self.exit_law)

    def as_dict(self, target: float | None = None) -> dict:
        payload = {
            "label": self.label,
            "exit_law": self.exit_law.as_dict(),
            "break_even_win_rate": round(self.break_even(), 6),
            "scanner": self.scanner.as_dict(),
            "in_sample": self.in_sample.as_dict(),
            "out_of_sample": (None if self.out_of_sample is None
                              else self.out_of_sample.as_dict()),
            "oos_folds": self.oos_folds,
        }
        if target is not None:
            payload["target"] = target
            payload["target_hit_in_sample"] = bool(
                np.isfinite(self.in_sample.win_rate)
                and self.in_sample.win_rate >= target)
            payload["overfit_gap"] = (
                None if self.out_of_sample is None
                or not np.isfinite(self.out_of_sample.win_rate)
                else round(float(self.in_sample.win_rate
                                 - self.out_of_sample.win_rate), 6))
        return payload


def _fold_geometry(n_sessions: int) -> tuple[int, int, int]:
    """(n_folds, test_size, val_size) that fit the available date axis."""
    if n_sessions < 60:
        return (0, 0, 0)
    test_size = max(20, n_sessions // 12)
    val_size = max(15, n_sessions // 20)
    n_folds = max(1, min(3, (n_sessions - val_size - 1) // test_size))
    if n_sessions < n_folds * test_size + val_size + 1:
        return (0, 0, 0)
    return (n_folds, test_size, val_size)


def build_oos_plan(frame: pd.DataFrame) -> dict:
    """Walk-forward split over the dataset's sessions, or an empty plan."""
    sessions = np.sort(pd.to_datetime(frame["date"]).unique())
    n_folds, test_size, val_size = _fold_geometry(len(sessions))
    if n_folds == 0:
        return {"available": False, "reason":
                f"only {len(sessions)} sessions: too few for a leak-free split",
                "folds": []}
    folds = walk_forward_splits(list(sessions), n_folds=n_folds,
                                test_size=test_size, val_size=val_size)
    return {"available": True, "n_folds": n_folds, "test_size": test_size,
            "val_size": val_size, "n_sessions": int(len(sessions)),
            "folds": folds}


def attach_out_of_sample(candidate: Candidate, frame: pd.DataFrame,
                         plan: dict, *, horizon: int) -> Candidate:
    """Score a candidate on the untouched walk-forward test segments."""
    if not plan.get("available"):
        return candidate

    scored, mask = build_signals(frame, candidate.scanner)
    paths, _ = build_path_matrix(scored, mask, horizon=horizon)
    if paths.empty:
        return candidate

    fold_rows: list[dict] = []
    pooled: list[np.ndarray] = []
    for fold in plan["folds"]:
        test_dates = set(fold["test"])
        selected = paths.loc[_split_mask(paths, test_dates)]
        if selected.empty:
            fold_rows.append({"fold": fold["fold"], "n_trades": 0})
            continue
        metrics = evaluate_paths(selected, candidate.exit_law)
        fold_rows.append({"fold": fold["fold"], "n_trades": metrics.n_trades,
                          "win_rate": (None if not np.isfinite(metrics.win_rate)
                                       else round(metrics.win_rate, 6)),
                          "expectancy_net": (None if not np.isfinite(metrics.expectancy_net)
                                             else round(metrics.expectancy_net, 6))})
        pooled.append(selected)
    if not pooled:
        candidate.oos_folds = fold_rows
        return candidate

    everything = pd.concat(pooled, ignore_index=True)
    candidate.out_of_sample = evaluate_paths(everything, candidate.exit_law)
    candidate.oos_folds = fold_rows
    return candidate


def run_exit_sweep(frame: pd.DataFrame, params: ScannerParams,
                   *, horizon: int,
                   tp_grid: tuple[float, ...] = EXIT_TP_GRID,
                   sl_grid: tuple[float, ...] = EXIT_SL_GRID,
                   hold_grid: tuple[int, ...] = EXIT_HOLD_GRID,
                   progress: ProgressFn | None = None) -> list[tuple[ExitLaw, Metrics]]:
    """Stage 1: sweep the exit law against the shipped scanner thresholds."""
    scored, mask = build_signals(frame, params)
    paths, _ = build_path_matrix(scored, mask, horizon=horizon)
    results: list[tuple[ExitLaw, Metrics]] = []
    grid = list(product(tp_grid, sl_grid, hold_grid))
    for index, (tp, sl, hold) in enumerate(grid, start=1):
        if hold > horizon:
            continue
        law = ExitLaw(tp=tp, sl=sl, max_hold=hold)
        results.append((law, evaluate_paths(paths, law)))
        if progress is not None:
            progress(index, len(grid), law)
    return results


def run_scanner_sweep(frame: pd.DataFrame, law: ExitLaw, *, horizon: int,
                      weight_grid: tuple[tuple[str, dict[str, float]], ...] | None = None,
                      score_grid: tuple[float, ...] = SCAN_SCORE_GRID,
                      relvol_grid: tuple[float, ...] = SCAN_RELVOL_GRID,
                      value_grid: tuple[float, ...] = SCAN_VALUE_GRID,
                      progress: ProgressFn | None = None
                      ) -> list[tuple[str, ScannerParams, Metrics]]:
    """Stage 2: sweep the scanner's own parameters with the exit law frozen.

    Every point rebuilds signals, because the weights change the score and the
    score changes which bars clear the gate. Each result is tagged with the
    weight emphasis it came from, so a weight-driven difference is visible and a
    threshold-driven coincidence is traceable.
    """
    if weight_grid is None:
        weight_grid = _default_weight_grid()
    results: list[tuple[str, ScannerParams, Metrics]] = []
    grid = list(product(range(len(weight_grid)), score_grid, relvol_grid, value_grid))
    for index, (w_index, min_score, min_relvol, min_value) in enumerate(grid, start=1):
        emphasis, weights = weight_grid[w_index]
        params = ScannerParams(weights=dict(weights), min_score=min_score,
                               min_relvol=min_relvol,
                               min_traded_value=min_value)
        scored, mask = build_signals(frame, params)
        paths, _ = build_path_matrix(scored, mask, horizon=horizon)
        results.append((emphasis, params, evaluate_paths(paths, law)))
        if progress is not None:
            progress(index, len(grid), f"{emphasis} score>={min_score:g}")
    return results


def _default_weight_grid() -> tuple[tuple[str, dict[str, float]], ...]:
    """The shipped weights plus a few deliberately different emphases.

    The single-component vectors are deliberate stress points: if gating on
    momentum alone reaches the same bars as the shipped blend, the blend is not
    earning its complexity.
    """
    return (
        ("shipped", dict(config.SCORE_WEIGHTS)),
        ("mom-only", {"momentum": 1.0, "acceleration": 0.0,
                      "relative_volume": 0.0, "volume_acceleration": 0.0,
                      "liquidity": 0.0}),
        ("rvol-only", {"momentum": 0.0, "acceleration": 0.0,
                       "relative_volume": 1.0, "volume_acceleration": 0.0,
                       "liquidity": 0.0}),
        ("liq-only", {"momentum": 0.0, "acceleration": 0.0,
                      "relative_volume": 0.0, "volume_acceleration": 0.0,
                      "liquidity": 1.0}),
        ("vol-led", {"momentum": 0.15, "acceleration": 0.15,
                     "relative_volume": 0.4, "volume_acceleration": 0.3,
                     "liquidity": 0.0}),
    )


@dataclass
class OptimizationReport:
    target: float
    dataset: dict
    protocol: dict
    stage1: list[dict]
    stage2: list[dict]
    best_in_sample: dict | None
    best_out_of_sample: dict | None
    best_by_expectancy: dict | None
    target_hit_in_sample: bool
    verdict: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def run_staged_search(
    frame: pd.DataFrame,
    *,
    target: float = 0.90,
    horizon: int = 10,
    dataset_report: dict | None = None,
    stage1_top: int = 5,
    stage2_top: int = 5,
    progress: ProgressFn | None = None,
) -> OptimizationReport:
    """Run stage 1, freeze the best exit geometry, then run stage 2.

    "Best" is chosen on IN-SAMPLE win rate among candidates that clear
    ``DEFAULT_MIN_TRADES``, because the owner's target is an accuracy figure.
    Each chosen stage-1 candidate is then re-scored out-of-sample.
    """
    if frame.empty:
        raise ValueError("cannot optimise on an empty frame")
    warnings: list[str] = []
    plan = build_oos_plan(frame)
    if not plan.get("available"):
        warnings.append(f"out-of-sample evaluation unavailable: {plan.get('reason')}")

    shipped = ScannerParams(weights=dict(config.SCORE_WEIGHTS))

    # ---- stage 1: exit law ------------------------------------------------
    stage1_raw = run_exit_sweep(frame, shipped, horizon=horizon, progress=progress)
    ranked1 = sorted(
        (r for r in stage1_raw if r[1].n_trades >= DEFAULT_MIN_TRADES),
        key=lambda r: (-(r[1].win_rate if np.isfinite(r[1].win_rate) else -1.0),
                       -r[1].expectancy_net))
    if not ranked1:
        warnings.append(
            "no exit-law candidate reached "
            f"{DEFAULT_MIN_TRADES} trades; ranking includes thin samples")
        ranked1 = sorted(
            stage1_raw,
            key=lambda r: (-(r[1].win_rate if np.isfinite(r[1].win_rate) else -1.0),
                           -r[1].n_trades))

    stage1_candidates: list[Candidate] = []
    for law, metrics in ranked1[:stage1_top]:
        cand = Candidate(label=f"exit tp={law.tp:.3f}/sl={law.sl:.3f}/hold={law.max_hold}",
                         exit_law=law, scanner=shipped, in_sample=metrics)
        stage1_candidates.append(attach_out_of_sample(cand, frame, plan, horizon=horizon))

    best_law = stage1_candidates[0].exit_law

    # ---- stage 2: scanner parameters with the exit law frozen -------------
    stage2_raw = run_scanner_sweep(frame, best_law, horizon=horizon, progress=progress)
    ranked2 = sorted(
        (r for r in stage2_raw if r[2].n_trades >= DEFAULT_MIN_TRADES),
        key=lambda r: (-(r[2].win_rate if np.isfinite(r[2].win_rate) else -1.0),
                       -r[2].n_trades))
    if not ranked2:
        warnings.append(
            f"no scanner candidate reached {DEFAULT_MIN_TRADES} trades; "
            "ranking includes thin samples")
        ranked2 = sorted(
            stage2_raw,
            key=lambda r: (-(r[2].win_rate if np.isfinite(r[2].win_rate) else -1.0),
                           -r[2].n_trades))

    # Collapse results that coincide. Many parameter points land on the same
    # gate -- a score floor high enough implies all the other floors, whatever
    # the weights -- and printing the same row three times would waste the
    # report's slots. Keyed on the OUTCOME, so a coincidence is caught by its
    # effect rather than by assuming which threshold caused it.
    seen: set[tuple] = set()
    stage2_candidates: list[Candidate] = []
    for emphasis, params, metrics in ranked2:
        key = (metrics.n_trades,
               round(metrics.win_rate, 6) if np.isfinite(metrics.win_rate) else None,
               round(metrics.expectancy_net, 6)
               if np.isfinite(metrics.expectancy_net) else None)
        if key in seen:
            continue
        seen.add(key)
        cand = Candidate(
            label=(f"{emphasis} score>={params.min_score:g} "
                   f"rvol>={params.min_relvol:g} "
                   f"val>={params.min_traded_value / 1e6:g}M"),
            exit_law=best_law, scanner=params, in_sample=metrics)
        stage2_candidates.append(attach_out_of_sample(cand, frame, plan, horizon=horizon))
        if len(stage2_candidates) >= stage2_top:
            break

    everything = stage1_candidates + stage2_candidates
    graded = [c for c in everything if c.in_sample.is_meaningful]
    pool = graded or everything
    best_in = max(pool, key=lambda c: (c.in_sample.win_rate
                                       if np.isfinite(c.in_sample.win_rate) else -1.0))
    with_oos = [c for c in pool if c.out_of_sample is not None
                and np.isfinite(c.out_of_sample.win_rate)]
    best_oos = max(with_oos, key=lambda c: c.out_of_sample.win_rate) if with_oos else None
    # The accuracy ranking above can pick a near-worthless geometry (a tiny TP
    # against a wide SL is where high "hit rates" come from). Carry the
    # least-bad-expectancy candidate too, so the tradeoff is on the page.
    best_exp = max(pool, key=lambda c: (c.in_sample.expectancy_net
                                        if np.isfinite(c.in_sample.expectancy_net)
                                        else -1.0))

    target_hit = bool(np.isfinite(best_in.in_sample.win_rate)
                      and best_in.in_sample.win_rate >= target)
    verdict = _verdict(best_in, best_oos, best_exp, target,
                       plan.get("available", False))

    return OptimizationReport(
        target=target,
        dataset=dataset_report or {},
        protocol={
            "horizon": horizon,
            "min_trades": DEFAULT_MIN_TRADES,
            "cost_side_bps": DEFAULT_COST_SIDE_BPS,
            "cgt_rate": DEFAULT_CGT_RATE,
            "invalid_band": DEFAULT_INVALID_BAND,
            "stage1_grid": {"tp": EXIT_TP_GRID, "sl": EXIT_SL_GRID,
                            "max_hold": EXIT_HOLD_GRID},
            "stage2_grid": {"score": SCAN_SCORE_GRID,
                            "relvol": SCAN_RELVOL_GRID,
                            "traded_value": SCAN_VALUE_GRID},
            "frozen_exit_law": best_law.as_dict(),
            "walk_forward": {k: v for k, v in plan.items() if k != "folds"},
        },
        stage1=[c.as_dict(target) for c in stage1_candidates],
        stage2=[c.as_dict(target) for c in stage2_candidates],
        best_in_sample=best_in.as_dict(target),
        best_out_of_sample=(None if best_oos is None else best_oos.as_dict(target)),
        best_by_expectancy=best_exp.as_dict(target),
        target_hit_in_sample=target_hit,
        verdict=verdict,
        warnings=warnings,
    )


def _verdict(best_in: Candidate, best_oos: Candidate | None,
             best_exp: Candidate, target: float, oos_available: bool) -> str:
    ins = best_in.in_sample
    parts = [
        f"Best in-sample win rate {ins.win_rate:.2%} over {ins.n_trades:,} trades "
        f"(net expectancy {ins.expectancy_net:+.3%}/trade)."
    ]
    if best_in.exit_law.reward_risk > 0:
        parts.append(
            f"That is a {best_in.exit_law.reward_risk:.2f}:1 reward:risk geometry.")
    break_even = best_in.break_even()
    parts.append(
        f"With {DEFAULT_COST_SIDE_BPS:.1f}bps a side and {DEFAULT_CGT_RATE:.0%} CGT, "
        f"that geometry needs a {break_even:.2%} win rate merely to break even, "
        f"against the {ins.win_rate:.2%} it delivers.")
    owner_be = break_even_win_rate(ExitLaw(*OWNER_LAW))
    parts.append(
        f"For reference the owner's {OWNER_LAW[0]:.1%}/{OWNER_LAW[1]:.1%} law needs "
        f"{owner_be:.2%}.")
    exp_ins = best_exp.in_sample
    if best_exp is not best_in:
        parts.append(
            f"The least-negative expectancy found is {exp_ins.expectancy_net:+.3%}/trade "
            f"at {exp_ins.win_rate:.2%} accuracy ({best_exp.exit_law.reward_risk:.2f}:1) "
            "-- i.e. the accuracy ranking and the money ranking disagree, as they "
            "must whenever a win-rate target and a payoff geometry conflict.")
    if best_oos is not None:
        gap = ins.win_rate - best_oos.out_of_sample.win_rate
        parts.append(
            f"Out-of-sample (walk-forward test segments): "
            f"{best_oos.out_of_sample.win_rate:.2%} over "
            f"{best_oos.out_of_sample.n_trades:,} trades, net expectancy "
            f"{best_oos.out_of_sample.expectancy_net:+.3%}/trade. "
            f"Overfit gap: {gap:+.2%}.")
        if best_oos.out_of_sample.expectancy_net <= 0:
            parts.append("Out-of-sample expectancy is not positive, so this is "
                         "not a deployable edge.")
    elif not oos_available:
        parts.append("No out-of-sample block exists for this run, so the "
                     "in-sample figure is unverified.")
    if exp_ins.expectancy_net <= 0:
        parts.append("No parameter point in the whole grid has positive net "
                     "expectancy after costs, so no configuration here is "
                     "deployable.")
    oos_confirms = (best_oos is not None
                    and np.isfinite(best_oos.out_of_sample.win_rate)
                    and best_oos.out_of_sample.win_rate >= target)
    if ins.win_rate >= target:
        if oos_confirms:
            parts.append(
                f"The {target:.0%} target is met in-sample AND on the walk-forward "
                "test segments, so as an accuracy claim it is not overfit. It is "
                "still not an edge: the accuracy is bought with a payoff "
                "geometry whose break-even sits near certainty, and every trade "
                "loses money on average. Sixty percent accuracy with a sane "
                "payoff beats ninety percent with this one, and the engine will "
                "say so.")
        else:
            parts.append(
                f"The {target:.0%} target IS met in-sample but not out-of-sample: "
                "treat it as a fitted number, not a forecast.")
    else:
        parts.append(
            f"The {target:.0%} target is NOT met even in-sample. Reaching it "
            "would require look-ahead, capitalising on survivorship, or "
            "unadjusted corporate actions.")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    """Placeholder so ``python -m src.backtest.optimize`` gives a clear pointer."""
    print("Run the runnable entry point instead: "
          "python scripts/backtest_optimize.py --help")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
