#!/usr/bin/env python3
"""Cloud-only entry point for the PSX intraday 100-strategy research.

The full assignment is staged: audit, pilot, full catalog, validation and
locked test. This command currently implements the first two stages so the
data and the execution law are proven before a large sweep is allowed.

Usage:
    python scripts/intraday100.py audit --data data/history --out data/research/intraday100
    python scripts/intraday100.py pilot --data data/history --out data/research/intraday100

Nothing here may run on the owner's PC. The first statement of main() asks the
repository guard, and the workflow is manual dispatch only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.research.intraday100 import (  # noqa: E402
    CAPITAL_PKR,
    CGT_RATE,
    COST_SIDE_BPS,
    SPREAD_SIDE_BPS,
    TRADE_FRACTION,
)
from src.research.intraday100.audit import (  # noqa: E402
    audit_archive,
    data_quality_markdown,
)
from src.research.intraday100.data import load_prepared  # noqa: E402
from src.research.intraday100.engine import (  # noqa: E402
    simulate_strategy,
    summarize_trades,
)
from src.research.intraday100.features import build_features  # noqa: E402
from src.research.intraday100.pilot_strategies import PILOT_STRATEGIES  # noqa: E402

DAILY = 86400
DISCOVERY_START = date(2021, 11, 15)
DISCOVERY_END = date(2024, 6, 30)
VALIDATION_START = date(2024, 7, 1)
VALIDATION_END = date(2025, 6, 30)
TEST_START = date(2025, 7, 1)
TEST_END = date(2026, 11, 13)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _pkt_date(ts: int | float) -> date:
    return datetime.fromtimestamp(int(ts), tz=KARACHI).date()


def _period_frame(trades: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if trades is None or trades.empty:
        return pd.DataFrame()
    dates = pd.to_datetime(trades["entry_ts"], unit="s", utc=True).dt.tz_convert(KARACHI).dt.date
    return trades[(dates >= start) & (dates <= end)].copy()


def _period_summary(
    trades: pd.DataFrame,
    strategy_id: str,
    start: date,
    end: date,
    capital: float,
    fraction: float,
) -> dict[str, Any]:
    frame = _period_frame(trades, start, end)
    result = summarize_trades(frame, strategy_id, capital=capital, trade_fraction=fraction)
    result["period_start"] = start.isoformat()
    result["period_end"] = end.isoformat()
    return result


def run_audit(data_root: Path, out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    audit = audit_archive(data_root)
    (out_dir / "DATA_QUALITY_REPORT.md").write_text(
        data_quality_markdown(audit), encoding="utf-8"
    )
    (out_dir / "audit.json").write_text(
        json.dumps(_jsonable(audit), indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps({
        "stage": "audit",
        "out_dir": str(out_dir),
        "timeframes": {
            tf: {
                "rows": item.get("rows"),
                "symbols": item.get("symbols"),
                "sessions": item.get("sessions"),
            }
            for tf, item in audit["timeframes"].items()
        },
    }, indent=2))
    return audit


def _spec_payload(strategy: Any) -> dict[str, Any]:
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "family": strategy.family,
        "hypothesis": strategy.hypothesis,
        "timeframe": strategy.timeframe,
        "target_atr": strategy.rule.target_atr,
        "stop_atr": strategy.rule.stop_atr,
        "max_hold_bars": strategy.rule.max_hold_bars,
        "target_min_pct": strategy.rule.target_min * 100.0,
        "target_max_pct": strategy.rule.target_max * 100.0,
        "stop_min_pct": strategy.rule.stop_min * 100.0,
        "stop_max_pct": strategy.rule.stop_max * 100.0,
        "known_weaknesses": strategy.weaknesses,
    }


def run_pilot(
    data_root: Path,
    out_dir: Path,
    *,
    years: tuple[int, ...] | None,
    max_rows: int | None,
    include_locked_test: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    bar_seconds = 300
    frame = load_prepared(data_root, "5m", years=years, max_rows=max_rows)
    frame_end = date.max
    if not include_locked_test:
        # The locked test is not touched by the pilot. The full catalog will
        # unlock it once, after all discovery and validation choices are frozen.
        cutoff = int(datetime(VALIDATION_END.year, VALIDATION_END.month,
                              VALIDATION_END.day, 23, 59, 59, tzinfo=KARACHI).timestamp())
        frame = frame[frame["ts"] <= cutoff].copy()
        frame_end = VALIDATION_END
    frame = build_features(frame)
    if frame.empty:
        raise SystemExit("pilot frame is empty; refuse to write a fabricated result")

    all_trades: list[pd.DataFrame] = []
    summaries: list[dict[str, Any]] = []
    for strategy in PILOT_STRATEGIES:
        mask = strategy.mask(frame)
        score = strategy.score(frame)
        trades = simulate_strategy(
            frame,
            mask,
            score,
            strategy.strategy_id,
            strategy.rule,
            capital=CAPITAL_PKR,
            trade_fraction=TRADE_FRACTION,
            cost_side_bps=COST_SIDE_BPS,
            spread_side_bps=SPREAD_SIDE_BPS,
            bar_seconds=bar_seconds,
        )
        if not trades.empty:
            trades["strategy_name"] = strategy.name
            trades["family"] = strategy.family
            all_trades.append(trades)
        summary = summarize_trades(
            trades, strategy.strategy_id, capital=CAPITAL_PKR,
            trade_fraction=TRADE_FRACTION,
        )
        summary.update({
            "name": strategy.name,
            "family": strategy.family,
            "timeframe": strategy.timeframe,
            "hypothesis": strategy.hypothesis,
            "weaknesses": strategy.weaknesses,
            "discovery": _period_summary(
                trades, strategy.strategy_id, DISCOVERY_START, DISCOVERY_END,
                CAPITAL_PKR, TRADE_FRACTION,
            ),
            "validation": _period_summary(
                trades, strategy.strategy_id, VALIDATION_START, VALIDATION_END,
                CAPITAL_PKR, TRADE_FRACTION,
            ),
            "locked_test_run": bool(include_locked_test),
        })
        summaries.append(summary)
        print(f"{strategy.strategy_id}: trades={summary.get('trades', 0)} "
              f"net={summary.get('net_return_pct', 0.0):.3f}% "
              f"expectancy={summary.get('expectancy_pct', 0.0):.4f}%", flush=True)

    trades_frame = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    rankings = sorted(
        summaries,
        key=lambda s: (
            s.get("validation", {}).get("expectancy_pct", -1e9),
            s.get("net_return_pct", -1e9),
        ),
        reverse=True,
    )
    payload = {
        "stage": "pilot",
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "dataset": {
            "path": str(data_root),
            "timeframe": "5m",
            "rows_loaded": int(len(frame)),
            "symbols": int(frame["symbol"].nunique()),
            "first_date": _pkt_date(frame["ts"].min()).isoformat(),
            "last_date": _pkt_date(frame["ts"].max()).isoformat(),
            "valid_bars": int(frame["valid_bar"].sum()),
            "years": list(years) if years else "all",
            "locked_test_untouched": not include_locked_test,
            "pilot_end": frame_end.isoformat(),
        },
        "protocol": {
            "capital_pkr": CAPITAL_PKR,
            "trade_fraction": TRADE_FRACTION,
            "notional_per_trade_pkr": CAPITAL_PKR * TRADE_FRACTION,
            "max_trades_per_day": 1,
            "direction": "long_only",
            "leverage": 0,
            "entry": "next bar open after signal close, same band",
            "exit": "stop before target on the same bar; max hold; band close",
            "cost_side_bps": COST_SIDE_BPS,
            "spread_side_bps": SPREAD_SIDE_BPS,
            "round_trip_cost_pct": 2.0 * (COST_SIDE_BPS + SPREAD_SIDE_BPS) / 100.0,
            "cgt_rate": CGT_RATE,
            "splits": {
                "discovery": [DISCOVERY_START.isoformat(), DISCOVERY_END.isoformat()],
                "validation": [VALIDATION_START.isoformat(), VALIDATION_END.isoformat()],
                "locked_test": [TEST_START.isoformat(), TEST_END.isoformat()],
            },
        },
        "strategies": [_spec_payload(s) for s in PILOT_STRATEGIES],
        "summaries": summaries,
        "ranking_by_validation_expectancy": [
            {"rank": i + 1, "strategy_id": s["strategy_id"], "name": s["name"],
             "validation_expectancy_pct": s.get("validation", {}).get("expectancy_pct"),
             "validation_trades": s.get("validation", {}).get("trades"),
             "net_return_pct": s.get("net_return_pct")}
            for i, s in enumerate(rankings)
        ],
        "limitations": [
            "The pilot covers discovery and validation only; the locked test is untouched.",
            "No historical KMIALL membership; the current 319-symbol universe is applied backward.",
            "No corporate-action file; large gaps are screened conservatively, not adjusted.",
            "No historical quotes; spread and slippage are explicit proxies, not measurements.",
            "The pilot is exploratory and cannot establish a production edge on its own.",
        ],
    }

    (out_dir / "PILOT_RESULTS.json").write_text(
        json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8"
    )
    (out_dir / "PILOT_STRATEGY_SPECS.csv").write_text(
        pd.DataFrame([_spec_payload(s) for s in PILOT_STRATEGIES]).to_csv(index=False),
        encoding="utf-8",
    )
    if not trades_frame.empty:
        trades_frame.to_csv(out_dir / "PILOT_TRADES.csv", index=False)
    else:
        (out_dir / "PILOT_TRADES.csv").write_text(
            "strategy_id,symbol,signal_ts,entry_ts,exit_ts,net_return,pnl_pkr\n",
            encoding="utf-8",
        )
    _write_pilot_markdown(out_dir / "PILOT_REPORT.md", payload)
    print(json.dumps({
        "stage": "pilot",
        "out_dir": str(out_dir),
        "strategies": len(summaries),
        "trades": int(len(trades_frame)),
        "top": payload["ranking_by_validation_expectancy"][:3],
    }, indent=2))
    return payload


def _write_pilot_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append("# Pilot Report: Ten Intraday Architectures")
    lines.append("")
    lines.append("## What this run is")
    lines.append("")
    lines.append("This is the pre-baseline pilot, not the final 100-strategy ranking. "
                 "Its purpose is to prove the archive path, the causal execution law, "
                 "the cost model and the cloud runtime before the full catalog is run. "
                 "The locked test period is untouched.")
    lines.append("")
    lines.append("## Protocol")
    lines.append("")
    p = payload["protocol"]
    lines.append(f"- Capital: PKR {p['capital_pkr']:,.0f}")
    lines.append(f"- Notional per trade: PKR {p['notional_per_trade_pkr']:,.0f} "
                 f"({p['trade_fraction'] * 100:.0f}% of capital)")
    lines.append("- One trade per Karachi session day per strategy")
    lines.append("- Long only, no leverage, no overnight holding")
    lines.append(f"- Cost: {p['cost_side_bps']:.1f} bps all-in per side "
                 f"(22.4 bps commission and taxes plus 10 bps slippage) plus "
                 f"{p['spread_side_bps']:.1f} bps spread per side")
    lines.append(f"- Round trip cost: {p['round_trip_cost_pct']:.3f}% before CGT")
    lines.append(f"- CGT: {p['cgt_rate'] * 100:.0f}% on positive net returns")
    lines.append("- Entry: next bar open after the signal bar closes, same session band")
    lines.append("")
    lines.append("## Data")
    lines.append("")
    d = payload["dataset"]
    lines.append(f"- Rows loaded: {d['rows_loaded']:,}")
    lines.append(f"- Symbols: {d['symbols']}")
    lines.append(f"- Dates: {d['first_date']} to {d['last_date']}")
    lines.append(f"- Valid session bars: {d['valid_bars']:,}")
    lines.append(f"- Locked test untouched: {d['locked_test_untouched']}")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| ID | Family | Trades | Net return | Expectancy/trade | Win rate | Profit factor | Max DD | Validation expectancy | Validation trades |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in payload["summaries"]:
        v = s.get("validation", {})
        lines.append(
            f"| {s['strategy_id']} | {s['family']} | {s.get('trades', 0):,} | "
            f"{s.get('net_return_pct', 0.0):.3f}% | {s.get('expectancy_pct', 0.0):.4f}% | "
            f"{s.get('win_rate_pct', 0.0):.1f}% | "
            f"{s.get('profit_factor') if s.get('profit_factor') is not None else 'n/a'} | "
            f"{s.get('max_drawdown_pct', 0.0):.2f}% | "
            f"{v.get('expectancy_pct', 0.0):.4f}% | {v.get('trades', 0):,} |"
        )
    lines.append("")
    lines.append("## Ranking by validation expectancy")
    lines.append("")
    lines.append("| Rank | ID | Name | Validation expectancy | Validation trades |")
    lines.append("|---:|---|---|---:|---:|")
    for row in payload["ranking_by_validation_expectancy"]:
        lines.append(
            f"| {row['rank']} | {row['strategy_id']} | {row['name']} | "
            f"{row['validation_expectancy_pct'] if row['validation_expectancy_pct'] is not None else 'n/a'} | "
            f"{row['validation_trades'] if row['validation_trades'] is not None else 0} |"
        )
    lines.append("")
    lines.append("## Interpretation rules")
    lines.append("")
    lines.append("- A positive pilot result is not evidence of an edge. The sample is "
                 "small, the universe is survivorship-biased and the cost model is a proxy.")
    lines.append("- A negative pilot result is useful: it eliminates a family before the "
                 "full 100 consume cloud minutes.")
    lines.append("- No parameter was selected on the locked test, because the pilot never "
                 "read a bar after 30 June 2025.")
    lines.append("- The full catalog must report discovery, validation and one locked-test "
                 "read separately, with deflated or multiple-testing-adjusted evidence.")
    lines.append("")
    lines.append("## Limitations")
    lines.append("")
    for item in payload["limitations"]:
        lines.append(f"- {item}")
    lines.append("")
    text = "\n".join(lines) + "\n"
    for dash in ("\u2014", "\u2013", "\u2012", "\u2015", "\u2e3a", "\u2e3b"):
        text = text.replace(dash, "-")
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/intraday100.py")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="stage", required=True)

    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--data", default="data/history")
    audit_parser.add_argument("--out", default="data/research/intraday100")

    pilot_parser = sub.add_parser("pilot")
    pilot_parser.add_argument("--data", default="data/history")
    pilot_parser.add_argument("--out", default="data/research/intraday100")
    pilot_parser.add_argument("--years", default="", help="comma separated years")
    pilot_parser.add_argument("--max-rows", type=int, default=None)
    pilot_parser.add_argument("--include-locked-test", action="store_true")

    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    if args.stage == "audit":
        run_audit(Path(args.data), out_dir)
        return 0
    if args.stage == "pilot":
        years = tuple(int(y) for y in args.years.split(",") if y.strip()) or None
        run_pilot(
            Path(args.data),
            out_dir,
            years=years,
            max_rows=args.max_rows,
            include_locked_test=args.include_locked_test,
        )
        return 0
    parser.error("unknown stage")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
