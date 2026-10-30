"""Ten-year, whole-universe mean-reversion backtest (the snapback rule).

SO-21: this run lives on GitHub Actions minutes, never on the owner's PC;
guard_cloud_backtest below refuses to start it anywhere else. Owner
order 2026-10-19: his machine is off for backtest work, and the public
repository makes Actions minutes free.

Pipeline (all on data/eod_dataset_10y.csv.gz, the mkt_summary OHLCV panel
built by scripts/build_backtest_dataset.py - the dataset is gitignored and
this job builds it rather than inventing it, SO-3):

1. Score every (symbol, session) with src/backtest/mean_reversion.py:
   RSI(2) oversold inside an uptrend, alive relative volume, real traded
   value. Signal decided at the close of session T, entry at the open of
   T+1, the same entry law the deployed scanner analogue uses.
2. Simulate every signal with src/backtest/engine.run_backtest under the
   MeanRevParams exit law (target, stop and max-hold exits, LEVEL_1
   costs, capital-gains tax on winners, and the corporate-action screen
   that refuses to book band-breaking prints).
3. Re-price the engine trade list through the portfolio risk layer:
   each entry is sized so a stop-out loses exactly RISK_FRACTION times
   the equity in force on its entry date, entries are capped on
   concurrent open positions, and a kill switch stops admitting new
   entries once realized equity has drawn down more than
   PORTFOLIO_KILL_SWITCH_PCT from its running high-water mark. Skipped
   entries stay on the trades file, flagged, never deleted to flatter
   the headline.
4. Report honestly: counts, win rate, expectancy, profit factor,
   chronological equity, max drawdown, and the win/loss arithmetic the
   owner's 90% goal needs, printed next to what the run delivered.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.ci.local_only import guard_cloud_backtest  # noqa: E402

import pandas as pd

from src.backtest.engine import run_backtest
from src.backtest.mean_reversion import MeanRevParams, build_signals

RISK_FRACTION_PER_TRADE = 0.005   # stop-out loss, fraction of entry equity
MAX_CONCURRENT_POSITIONS = 5      # simultaneous open entry windows
PORTFOLIO_KILL_SWITCH_PCT = 0.02  # stop entering below HWM-2% equity


def risk_curve(trades: pd.DataFrame, stop_frac: float) \
        -> tuple[pd.DataFrame, dict]:
    """Re-price each engine trade through the portfolio risk law.

    Entry i (processed chronologically) is sized at
        notional_i = equity_entry * RISK_FRACTION_PER_TRADE / stop_frac
    where stop_frac is the PLANNED stop distance as a fraction of the
    entry price (a strategy level from MeanRevParams.stop_loss, not
    inferred after the fact from exit outcomes), so a stop-out loses
    exactly RISK_FRACTION_PER_TRADE times the equity in force on the
    entry date. On the trade's exit the realized PnL is
        equity += notional_i * net_ret_i
    (net_ret already carries LEVEL_1 costs and capital-gains tax via the
    engine's corporate-action screen and honest cost model).

    Concurrency: entries whose entry/exit windows overlap a new entry's
    entry date count as open positions against
    MAX_CONCURRENT_POSITIONS; excess entries are skipped and flagged,
    not silently admitted.
    Kill switch: while realized equity is below its running high-water
    mark minus PORTFOLIO_KILL_SWITCH_PCT, no entry goes through.

    Boundary the risk layer is honest about: the engine simulates every
    signal as its own round trip, so no intra-bar capital reallocation,
    averaging or re-sizing is modelled here. The re-priced curve answers
    portfolio-level questions (max exposure, max drawdown, kill-switch
    behaviour) on the per-trade answers the engine produced, no more.
    """
    if not (0 < stop_frac < 0.5):
        raise ValueError(
            "stop_frac must be a planned stop-loss fraction in (0, 0.5); "
            "the risk sizing refuses it rather than guessing a stop width")
    summary = {
        "risk_fraction_per_trade": RISK_FRACTION_PER_TRADE,
        "max_concurrent_positions": MAX_CONCURRENT_POSITIONS,
        "portfolio_kill_switch_pct": PORTFOLIO_KILL_SWITCH_PCT,
        "stop_frac_used": stop_frac,
        "n_entered": 0,
        "n_skipped_cap": 0,
        "n_skipped_kill": 0,
        "n_skipped_invalid": 0,
        "n_skipped_unknown": 0,
        "final_equity": 1.0,
        "max_drawdown": 0.0,
        "equity_curve_points": 0,
    }
    frame = trades.copy()
    if frame.empty:
        # An empty engine trade list is a clean, reportable empty result
        # for the summary writer, not a crash (the engine emits an
        # untyped empty frame when no signal ever filled).
        return frame, summary
    if "entry_date" not in frame.columns or "exit_date" not in frame.columns:
        raise ValueError(
            "trade frame lacks entry_date/exit_date; the risk layer "
            "cannot re-price it")
    frame["entry_dt"] = pd.to_datetime(frame["entry_date"], errors="coerce")
    frame["exit_dt"] = pd.to_datetime(frame["exit_date"], errors="coerce")
    frame["risk_taken"] = False
    frame["risk_skip_reason"] = ""
    frame["sizing_notional"] = float("nan")
    frame = frame.sort_values("entry_dt", kind="mergesort")
    equity = 1.0
    hwm = 1.0
    live: list[tuple] = []   # (exit_dt, position index)
    curve: list[tuple] = []

    for i in frame.index.tolist():
        row = frame.loc[i]
        entry = row["entry_dt"]
        if pd.isna(entry) or pd.isna(row["exit_dt"]):
            frame.at[i, "risk_skip_reason"] = "unknown_entry_or_exit"
            summary["n_skipped_unknown"] += 1
            continue
        # settle every open position whose exit is at/before this entry
        settled = [(dt, idx) for (dt, idx) in live if dt <= entry]
        for dt, idx in sorted(settled):
            equity += float(frame.at[idx, "sizing_notional"]) \
                * float(frame.at[idx, "net_ret"])
            curve.append((dt, equity))
            hwm = max(hwm, equity)
            live = [x for x in live if x != (dt, idx)]
        if bool(row["data_invalid"]):
            frame.at[i, "risk_skip_reason"] = "data_invalid"
            summary["n_skipped_invalid"] += 1
            continue
        if len(live) >= MAX_CONCURRENT_POSITIONS:
            frame.at[i, "risk_skip_reason"] = "concurrency_cap"
            summary["n_skipped_cap"] += 1
            continue
        if equity < hwm * (1.0 - PORTFOLIO_KILL_SWITCH_PCT):
            frame.at[i, "risk_skip_reason"] = "kill_switch"
            summary["n_skipped_kill"] += 1
            continue
        notional = equity * RISK_FRACTION_PER_TRADE / stop_frac
        frame.at[i, "sizing_notional"] = notional
        frame.at[i, "risk_taken"] = True
        summary["n_entered"] += 1
        live.append((row["exit_dt"], i))

    # close out whatever is still open at the end
    for dt, idx in sorted(live):
        equity += float(frame.at[idx, "sizing_notional"]) \
            * float(frame.at[idx, "net_ret"])
        curve.append((dt, equity))
        hwm = max(hwm, equity)
    equity = round(float(equity), 6)
    # Drawdown is measured from the STARTING equity 1.0, the same
    # "capital in front" convention src/backtest/engine.summarize uses,
    # so a first trade that loses directly is visible as drawdown.
    dd = 0.0
    eq_values = [1.0] + [p[1] for p in curve]
    eqs = pd.Series(eq_values)
    dd = float(1.0 - (eqs / eqs.cummax()).min())
    summary.update({
        "final_equity": equity,
        "max_drawdown": round(dd, 6),
        "equity_curve_points": len(curve),
    })
    return frame, summary


def per_year(trades: pd.DataFrame) -> dict:
    """Exit-year grouped view of counts, win rate, expectancy, PF."""
    valid = trades.loc[~trades["data_invalid"].astype(bool)].copy()
    if valid.empty:
        return {}
    valid["year"] = pd.to_datetime(valid["exit_date"]).dt.year.astype(int)
    out: dict[str, object] = {}
    for year, rows in valid.groupby("year"):
        net = rows["net_ret"]
        gross_w = float(rows.loc[rows["gross_ret"] > 0, "gross_ret"].sum())
        gross_l = -float(rows.loc[rows["gross_ret"] <= 0, "gross_ret"].sum())
        out[str(int(year))] = {
            "trades": int(len(rows)),
            "win_rate": round(float((net > 0).mean()), 4),
            "expectancy_net": round(float(net.mean()), 6),
            "profit_factor_gross": (round(gross_w / gross_l, 4)
                                    if gross_l > 0 else "inf"),
        }
    return out


def breakeven_table(params: MeanRevParams,
                    trades: pd.DataFrame) -> dict:
    """The explicit arithmetic the 90% goal would need, next to reality.

    For a fixed bracket take-profit tp and stop-loss sl the break-even
    (costless) win rate is not negotiable:
        p_be = sl / (sl + tp)
    With realized per-trade averages a* and |l*| the realized edge is
        edge per trade = p_mean * a* - (1 - p_mean) * |l*|
    whose honest ceiling under a 90% goal, at the SAME per-loss size,
    needs (1 - p)*|l*| < p*a*: the loss cohort must shrink to the point
    where its stop-driven depth no longer swamps the snapback target.
    For an achievable target (+tp on a daily bar) and a REAL stop
    (-sl), that survey is exactly what run_backtest measured.
    """
    if trades.empty:
        return {"note": "no trades"}
    valid = trades.loc[~trades["data_invalid"].astype(bool)]
    if valid.empty:
        return {"note": "all trades data-invalid"}
    tp = params.take_profit
    sl = params.stop_loss
    win = float((valid["net_ret"] > 0).mean())
    losers = valid.loc[valid["net_ret"] <= 0, "net_ret"]
    winners = valid.loc[valid["net_ret"] > 0, "net_ret"]
    return {
        "target_take_profit_pct": round(tp * 100.0, 4),
        "target_stop_loss_pct": round(sl * 100.0, 4),
        "break_even_win_rate_gross": round(sl / (sl + tp), 4),
        "realized_win_rate": round(win, 4),
        "surplus_over_break_even": round(win - sl / (sl + tp), 4),
        "n_trades_used": int(len(valid)),
        "avg_loss_net": round(float(losers.mean()), 6) if len(losers) else 0.0,
        "avg_win_net": round(float(winners.mean()), 6) if len(winners) else 0.0,
        "note": (
            "The 90% goal is an arithmetic claim, not a preference: a "
            "tp=+{tp}% / sl=-{sl}% bracket has break-even win rate "
            "p_be=sl/(sl+tp)={p_be:.1f}%, and pushing above that needs the "
            "win-rate pool to be far larger than the winning cohort can pay "
            "for the per-loss depth the stop enforces. This run reports the "
            "realized pair (win rate, per-loss depth) so the owner can read "
            "the exact gap to 90% rather than a hedged on-trade story (SO-3)."
        ).format(
            tp=round(tp * 100.0, 2), sl=round(sl * 100.0, 2),
            sl_o_tp=(sl / tp),
            p_be=(100.0 * sl / (sl + tp)),
        ),
    }


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/backtest_mean_reversion.py")
    ap = argparse.ArgumentParser(
        description="Ten-year KMIALL mean-reversion backtest")
    ap.add_argument("--dataset", type=Path,
                    default=Path("data/eod_dataset_10y.csv.gz"))
    ap.add_argument("--out", type=Path,
                    default=Path("data/backtest_mean_reversion_report.json"))
    ap.add_argument("--rsi-entry", type=float, default=10.0)
    ap.add_argument("--tp", type=float, default=0.01)
    ap.add_argument("--sl", type=float, default=0.03)
    ap.add_argument("--max-hold", type=int, default=4)
    args = ap.parse_args(argv)

    if not args.dataset.is_file():
        print(f"::error::{args.dataset} is missing. Dispatch the "
              "'mean-reversion' task so the workflow builds the ten-year "
              "panel first; this job never invents data (SO-3).")
        return 1

    df = pd.read_csv(args.dataset, parse_dates=["date"])
    need = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = need - set(df.columns)
    if missing:
        print(f"::error::dataset missing column(s): {sorted(missing)}")
        return 1

    params = MeanRevParams(
        rsi_entry=args.rsi_entry,
        take_profit=args.tp,
        stop_loss=args.sl,
        max_hold=args.max_hold,
    )
    signals = build_signals(df, params)
    trades_df, summary = run_backtest(
        df, signals,
        tp=params.take_profit,
        sl=params.stop_loss,
        max_hold=params.max_hold,
        touch_mode="hl",
    )
    trades_df, risk_summary = risk_curve(trades_df, params.stop_loss)
    summary["n_signals"] = len(signals)
    summary["params"] = params.as_dict()
    summary["risk_summary"] = risk_summary
    summary["breakeven_arithmetic"] = breakeven_table(params, trades_df)
    summary["per_year"] = per_year(trades_df) if len(trades_df) else {}

    # dataset summary side-file from the same crawl that produced the
    # panel, next to the results that claim it (SO-3)
    side = args.dataset.with_suffix("").with_suffix(".summary")
    if side.is_file():
        summary["dataset_summary"] = json.loads(side.read_text("utf-8"))
    if len(trades_df):
        trades_path = args.out.with_name(args.out.stem + "_trades.csv")
        trades_df.to_csv(trades_path, index=False)
        summary["trades_file"] = trades_path.name

    args.out.write_text(json.dumps(summary, indent=2, default=str),
                        encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
