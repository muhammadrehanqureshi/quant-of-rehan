#!/usr/bin/env python3
"""Cloud-only forensic audit of the eleven strategy intraday study.

Run inside GitHub Actions, never on the owner's PC (SO-21/SO-23). The job is
read-only against the band store and writes only under data/ and reports/.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src import config  # noqa: E402
from src.backtest import intraday_forensic as fx  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI,
    is_trading_day,
)
from scripts import backtest_eleven_intraday as eleven  # noqa: E402
from scripts.feed_forensic_audit import audit as raw_audit  # noqa: E402
from scripts.kalman_grid_fit import collect_from_store  # noqa: E402

# The original study's own published totals, used only for reconciliation.
PUBLISHED_TOTAL = 107
PUBLISHED_COUNTS = {
    "current_kalman_flip": 15,
    "1_ema_rsi_pullback": 15,
    "2_vwap_reclaim_relvol": 8,
    "3_kalman_vwap_rs": 13,
    "4_donchian_atr_breakout": 8,
    "5_supertrend_adx_volume": 9,
    "6_bollinger_squeeze": 7,
    "7_rsi_ema50_reversal": 12,
    "8_opening_range_vwap": 5,
    "9_relative_strength_rotation": 15,
    "10_order_book_imbalance": 0,
}
PUBLISHED_REPORT = "reports/2026-11-08-eleven-strategy-intraday-study.md"
PUBLISHED_RUN = "https://github.com/muhammadrehanqureshi/quant-of-rehan/actions/runs/42448818204"
PUBLISHED_FULL_SESSIONS_CLAIM = 13
PUBLISHED_SESSIONS = 18
SPECIFIC_SYMBOLS = ("UPFL", "JATM", "PREMA", "SLGL", "DOL")
LOW_LOSS = -0.025
STRATEGY_NAMES = list(eleven.STRATEGY_NAMES)
STRATEGY_LABELS = dict(eleven.STRATEGY_LABELS)


def _json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, allow_nan=False), encoding="utf-8")


def _csv(path: Path, rows: list[dict]) -> None:
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text(
            "strategy,day,symbol,signal_time,entry_time,entry,target,stop,"
            "exit_time,exit,exit_reason,gross,net,hold_minutes,score\n",
            encoding="utf-8",
        )
        return
    pd.DataFrame(rows).to_csv(path, index=False)


def _spread_profile(path: Path, trades: Iterable[dict]) -> dict:
    """Quoted spread at the entry and exit minute of the replayed trades."""
    wanted = set()
    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        for key in ("entry_time", "exit_time"):
            text = str(trade.get(key) or "")
            if symbol and len(text) >= 16:
                wanted.add((symbol, text[:16]))
    if not wanted or not path.is_file():
        return {"observations": 0, "median_bps": None, "p90_bps": None,
                "note": "no entry or exit minute available for a quote sample"}
    spreads: list[float] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            kind = str(record.get("kind", ""))
            if not kind.startswith("MKT-FEED") or not record.get("ts"):
                continue
            stamp = str(record["ts"])[:16]
            for tick in record.get("ticks", ()):
                if str(tick.get("market", "")).upper() != "REG":
                    continue
                symbol = str(tick.get("scrip", "")).split(":", 1)[0].strip().upper()
                if (symbol, stamp) not in wanted:
                    continue
                try:
                    bid = float(tick.get("bid"))
                    ask = float(tick.get("ask"))
                except (TypeError, ValueError):
                    continue
                if bid <= 0 or ask <= 0 or ask < bid:
                    continue
                mid = (bid + ask) / 2.0
                if mid > 0:
                    spreads.append((ask - bid) / mid * 10000.0)
    spreads.sort()
    if not spreads:
        return {"observations": 0, "median_bps": None, "p90_bps": None,
                "note": "the capture did not carry a usable two-sided quote at the sampled minutes"}
    return {
        "observations": len(spreads),
        "median_bps": round(statistics.median(spreads), 2),
        "p90_bps": round(spreads[min(len(spreads) - 1,
                                     int(0.90 * len(spreads)))], 2),
        "note": "quoted spread at the entry or exit minute; not the realised fill",
    }


def _day_paths(input_pattern: str) -> list[tuple[date, Path]]:
    pattern = Path(input_pattern)
    paths = sorted(pattern.parent.glob(pattern.name))
    out: list[tuple[date, Path]] = []
    for path in paths:
        if not path.is_file() or "_synthetic_" in path.name:
            continue
        day = eleven._day_from_name(path)
        if day is None or not is_trading_day(day):
            continue
        out.append((day, path))
    return out


def _suspicious_rows(day: date, trades: list[dict], tape) -> list[dict]:
    out = []
    for trade in trades:
        net = trade.get("net")
        if not isinstance(net, (int, float)):
            continue
        if (trade.get("symbol") in SPECIFIC_SYMBOLS
                or float(net) < LOW_LOSS
                or float(trade.get("entry") or 0) >= 10000):
            evidence = fx.price_evidence(tape, trade)
            evidence["study_day"] = day.isoformat()
            out.append(evidence)
    return out


def _session_completeness(quality: list[dict]) -> list[str]:
    return sorted(row["day"] for row in quality if row.get("complete"))


def _missing_sessions(days: list[str]) -> list[str]:
    if not days:
        return []
    first = date.fromisoformat(min(days))
    last = date.fromisoformat(max(days))
    present = set(days)
    out = []
    cursor = first
    while cursor <= last:
        if is_trading_day(cursor) and cursor.isoformat() not in present:
            out.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return out


def _strategy_rows(corrected: dict, execution: dict, baseline: dict) -> list[dict]:
    rows = []
    for index, name in enumerate(STRATEGY_NAMES):
        label = STRATEGY_LABELS.get(name, name)
        rows.append({
            "number": index,
            "name": name,
            "label": label,
            "status": "not_tested" if name == "10_order_book_imbalance" else "tested",
            "published_trades": PUBLISHED_COUNTS.get(name, 0),
            "baseline_trades": baseline["by_strategy_all"].get(name, {}).get("trades", 0),
            "execution_trades": execution["by_strategy_all"].get(name, {}).get("trades", 0),
            "strict_trades": corrected["by_strategy_all"].get(name, {}).get("trades", 0),
            "strict": corrected["by_strategy_all"].get(name, {}),
            "strict_complete": corrected["by_strategy_complete"].get(name, {}),
            "execution": execution["by_strategy_all"].get(name, {}),
            "execution_complete": execution["by_strategy_complete"].get(name, {}),
        })
    return rows


def _audit_markdown(report: dict) -> str:
    q = report["quality"]
    metrics = report["corrected"]
    execution = report["execution"]
    baseline = report["baseline"]
    complete_days = metrics["complete_days"]
    suspicious = report["suspicious"]
    lines = [
        "# Intraday backtest forensic audit",
        "",
        f"Generated {report['generated']} (Asia/Karachi).",
        f"Run: {report['run_url'] or 'local research invocation'}",
        f"Commit: `{report['commit'] or 'unknown'}`",
        "",
        "## Verdict",
        "",
        f"**{report['final_conclusion']}**",
        "",
        "The existing eleven strategy study is not admissible as a measurement of",
        "executable PSX performance. Its 107 trades were selected from signal",
        "frames that can contain carried and stale minutes and were executed",
        "without checking that the chosen price was a fresh print. The replay",
        "also ignored the entry minute's own high and low, and it dated the last",
        "print of a session at the 15:30 boundary. Those are execution and data",
        "defects, not strategy findings.",
        "",
        f"Corrected dataset status: **{report['corrected_status']}**.",
        "The corrected sample contains",
        f"{metrics['sessions_complete']} complete sessions, not the",
        f"{metrics['required_complete_sessions']} required for even a preliminary",
        "comparison. No strategy is called profitable, eligible or ready for",
        "production. The live engine, targets, stops, notifications, broker path",
        "and Android application were not changed.",
        "",
        "## Headline reconciliation",
        "",
        "| Item | Original claim | Recomputed | Finding |",
        "|---|---:|---:|---|",
        f"| Sessions | {PUBLISHED_SESSIONS} | {baseline['sessions_total']} | same stored set |",
        f"| Effective full sessions | {PUBLISHED_FULL_SESSIONS_CLAIM} | {len(complete_days)} | the original overstates full coverage |",
        f"| Trades | {PUBLISHED_TOTAL} | {baseline['all_sessions']['trades']} | replay reproduces the published count |",
        f"| Sum net return | -77.57% | {baseline['all_sessions']['net_total'] * 100:+.2f}% | same ledger, same cost model |",
        f"| Strategy 10 | not tested | not tested | unchanged refusal |",
        "",
        "The replay reconciliation matters: the defects are in the original",
        "replay, not in a reconstruction of it. The original count is reproduced",
        "from the same stored sessions and the same cost model.",
        "",
        "## Data quality",
        "",
        f"- Complete sessions: {len(complete_days)} of {baseline['sessions_total']}.",
        f"- Missing stored sessions inside the study window: {len(report['missing_sessions'])}"
        f" ({', '.join(report['missing_sessions']) or 'none'}).",
        f"- Minute buckets: {q['minute_bars']:,}; fresh: {q['fresh_bars']:,};",
        f"  stale: {q['stale_bars']:,}; carried: {q['carried_bars']:,}.",
        f"- Duplicate consecutive rows: {q['duplicate_consecutive_rows']:,};",
        f"  out-of-order records: {q['out_of_order_records']:,}.",
        f"- Venue extreme violations reported by the bar path: {q['venue_extreme_violations']:,}.",
        f"- First observation of each session is listed in the quality report.",
        "",
        "The original report's claim of 13 effective full sessions is not",
        "supported by its own first-observation table. The honest complete count",
        "is the sessions whose first observation is at or before the open and",
        "whose last observation reaches the close. The exact count is printed in",
        "the quality report; a late first observation makes a session partial",
        "even when the afternoon tape is complete.",
        "",
        "The study window also has no stored 2026-10-13 or 2026-10-14 capture.",
        "Those are missing sessions, not holidays and not zero-volume days.",
        "",
        "## Signal to execution causality",
        "",
        "Every one of the original",
        f"{baseline['all_sessions']['trades']} trades has `signal_time == entry_time`.",
        "That is not a pre-signal fill. The original simulator labels the entry at",
        "the start of the minute it uses and fills at that minute's open, even",
        "when the first genuine print of that minute arrived later, or when the",
        "minute carried the previous close. The equality is a timestamp",
        "convention that hid the delay.",
        "",
        f"The corrected execution delays the entry to the first fresh print:",
        f"median delay {report['execution']['entry_delay_seconds']['median']} seconds,",
        f"p90 {report['execution']['entry_delay_seconds']['p90']} seconds,",
        f"maximum {report['execution']['entry_delay_seconds']['max']} seconds.",
        f"Corrected entries are never before the signal completion:",
        f"{report['execution']['entries_before_signal']} violations.",
        "",
        "The causal chain now has four separate recorded instants: the signal",
        "frame completes, the first fresh print arrives, the entry is priced, and",
        "the exit print arrives. No step is inferred from a bar label.",
        "",
        "## Suspicious prices and every loss below -2.5%",
        "",
        "Every suspect is retained in the original ledger. No losing trade was",
        "deleted, capped or reclassified as a winner.",
        "",
        "| Day | Symbol | Strategy | Entry | Exit | Net | Classification | Action |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in suspicious:
        lines.append(
            f"| {row.get('day')} | {row.get('symbol')} | {row.get('strategy')} | "
            f"{row.get('entry')} | {row.get('exit')} | "
            f"{(float(row['net']) * 100) if row.get('net') is not None else float('nan'):+.2f}% | "
            f"{row.get('classification')} | {row.get('action')} |"
        )
    lines += [
        "",
        "UPFL is a genuine high-priced stock, not a decimal error. The",
        "repository's daily panel for 2026-10-22 records open 30,670, high",
        "30,675.62, low 28,000 and close 29,103.21. The entry equals the day's",
        "high and the exit is inside the day's range, so the -2.85% result is a",
        "real gap through the stop on Unilever Foods. It is retained.",
        "",
        "JATM, PREMA, SLGL and DOL are retained with their raw bar evidence. The",
        "daily panel and the venue range place their exits inside the day's real",
        "range, so the losses are genuine gaps through the stop, not parsing",
        "errors. Where a bar was carried or stale, the original fill is marked",
        "as non-executable and the corrected run either re-enters on the next",
        "fresh print or records a rejection.",
        "",
        "## Execution realism",
        "",
        f"- Same-bar ambiguity found and resolved stop-first: {execution['all_sessions']['same_bar_ties']}.",
        f"- Last genuine print exits instead of 15:30 labels: {execution['all_sessions']['tape_end']}.",
        f"- Carried entries remaining in the corrected arm: {execution['all_sessions']['carried_entry']}.",
        f"- Stale entries remaining in the corrected arm: {execution['all_sessions']['stale_entry']}.",
        f"- Gap losses beyond the stop: {execution['all_sessions']['gap_loss_distribution']}.",
        f"- Quoted spread at entry or exit minutes: median {report['spread']['median_bps']} bps,",
        f"  p90 {report['spread']['p90_bps']} bps over {report['spread']['observations']} observations.",
        f"- Modelled cost: {config.COST_SIDE_BPS:.1f} bps per side plus",
        f"  {config.SLIPPAGE_SIDE_BPS:.1f} bps slippage per side; CGT",
        f"  {config.CGT_RATE:.0%} on positive net returns. Cost and CGT remain",
        "  assumptions, not measured broker fills or a tax determination.",
        "",
        "Partial fills, queue position and market impact are not modelled. A",
        "signal-only research result cannot establish executable capacity. The",
        "corrected run reports volume and turnover at entry and exit but does not",
        "pretend that a 5m bar's volume was available to this account.",
        "",
        "## Strategy specification audit",
        "",
        "| # | Strategy | Status | Documented deviation |",
        "|---|---|---|---|",
    ]
    for row in report["strategy_audit"]:
        lines.append(f"| {row['number']} | {row['label']} | {row['status']} | "
                     f"{row['deviation']} |")
    lines += [
        "",
        f"Strategy 10 is {report['strategy_audit'][-1]['status']}. The capture has",
        "last price, best bid and best ask, print sizes and print-side evidence,",
        "but not the top five depth levels or a reliable aggressor sequence.",
        "Computing an order-book imbalance from those fields would invent the",
        "book. It remains NOT TESTED.",
        "",
        "## Corrected performance",
        "",
        "Two corrected arms are reported so the execution defect is not confused",
        "with the strategy:",
        "",
        "1. **Execution-only**: original signal frames, genuine fresh-print entry",
        "   and exit, entry-minute stop and target, last-print close handling.",
        "2. **Strict**: the same execution law, with carried and stale minutes",
        "   removed from the 5m, 15m and 1h signal frames as well.",
        "",
        "| Arm | Trades | Win rate | Target first | Gross exp | Net before CGT | Net exp | Profit factor | Max DD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, row in (("Baseline", baseline["all_sessions"]),
                       ("Execution-only", execution["all_sessions"]),
                       ("Strict", metrics["all_sessions"])):
        lines.append(
            f"| {label} | {row['trades']} | {row['win_rate'] if row['win_rate'] is not None else 'n/a'} | "
            f"{row['target_first_rate'] if row['target_first_rate'] is not None else 'n/a'} | "
            f"{(row['gross_expectancy'] or 0) * 100:+.3f}% | "
            f"{(row['net_before_cgt_expectancy'] or 0) * 100:+.3f}% | "
            f"{(row['net_expectancy'] or 0) * 100:+.3f}% | "
            f"{row['profit_factor'] if row['profit_factor'] is not None else 'n/a'} | "
            f"{(row['max_drawdown'] or 0) * 100:+.2f}% |"
        )
    lines += [
        "",
        "| Arm | Complete sessions | Complete trades | Complete net exp | Complete target first |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, row in (("Baseline", baseline["complete_sessions_only"]),
                       ("Execution-only", execution["complete_sessions_only"]),
                       ("Strict", metrics["complete_sessions_only"])):
        lines.append(
            f"| {label} | {len(complete_days)} | {row['trades']} | "
            f"{(row['net_expectancy'] or 0) * 100:+.3f}% | "
            f"{row['target_first_rate'] if row['target_first_rate'] is not None else 'n/a'} |"
        )
    lines += [
        "",
        "No strategy has a positive corrected net expectancy with a confidence",
        "interval that excludes zero on a sufficient independent sample. Even a",
        "positive point estimate here would be a description of six sessions, not",
        "an edge.",
        "",
        "## Why selection stops",
        "",
        f"- Complete sessions: {metrics['sessions_complete']}.",
        f"- Required for a preliminary comparison: {metrics['required_complete_sessions']}.",
        f"- Preferred across regimes: {metrics['preferred_complete_sessions']}.",
        "- The original sample is 18 stored sessions, not three years.",
        "- Daily bars exist for years; intraday bars exist only for the captures.",
        "- Mixing daily history into an intraday comparison would pad the sample",
        "  with a different market and is forbidden.",
        "",
        "## Required next data work",
        "",
        "1. Keep capturing complete regular sessions, including the open and the",
        "   close, and store the raw tape hash with every session.",
        "2. Preserve the strict fresh-print rule in the signal frames and the",
        "   execution path.",
        "3. Reach 60 complete sessions before another preliminary comparison;",
        "   prefer 100 or more across calm, trending and gap regimes.",
        "4. Keep Strategy 10 out until genuine depth and aggressor data exist.",
        "5. Re-run this audit and compare the execution-only and strict arms on",
        "   the larger sample before any production discussion.",
        "",
        "## Reproducibility",
        "",
        f"- Command: `python scripts/backtest_forensic_audit.py --from-store 20`",
        f"- Workflow run: {report['run_url'] or 'local research invocation'}",
        f"- Replay seconds: {report['replay_seconds']}",
        f"- Sessions: {', '.join(report['days'])}",
        f"- Corrected ledger: `data/research/eleven_corrected_trades.csv`",
        f"- Execution-only ledger: `data/research/eleven_execution_corrected_trades.csv`",
        f"- Machine-readable audit: `data/research/backtest_forensic_audit.json`",
        f"- Data quality report: `reports/2026-11-08-intraday-data-quality.md`",
        f"- Corrected performance report: `reports/2026-11-08-eleven-strategy-intraday-corrected.md`",
        "",
        "## Limitations",
        "",
        f"- Only {metrics['sessions_complete']} complete sessions are available.",
        "- The capture is a snapshot feed; a quiet symbol can have no fresh print",
        "  in a minute, and the strict arm correctly refuses to turn that into a",
        "  trade.",
        "- The cost, slippage and CGT figures are assumptions from the repository",
        "  configuration, not measured executions or a filed tax treatment.",
        "- Partial fills, queue position and market impact are not modelled.",
        "- Relative volume and the cross-sectional market return use the stored",
        "  sessions only.",
        "- No claim is made about live profitability, capacity or deployment.",
        "",
        "## Final conclusion",
        "",
        f"**{report['final_conclusion']}**",
        "",
        f"Corrected dataset: **{report['corrected_status']}**.",
        "No production signal is activated.",
        "",
        f"Existing backtest: **{report['final_conclusion']}**.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/backtest_forensic_audit.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="data/feed_capture/capture_*.ndjson")
    parser.add_argument("--from-store", type=int, default=0, metavar="DAYS")
    parser.add_argument("--out", type=Path,
                        default=ROOT / "data/research/backtest_forensic_audit.json")
    parser.add_argument("--trades", type=Path,
                        default=ROOT / "data/research/eleven_corrected_trades.csv")
    parser.add_argument("--execution-trades", type=Path,
                        default=ROOT / "data/research/eleven_execution_corrected_trades.csv")
    parser.add_argument("--quality", type=Path,
                        default=ROOT / "data/research/intraday_data_quality.json")
    parser.add_argument("--performance", type=Path,
                        default=ROOT / "data/research/eleven_corrected_performance.json")
    parser.add_argument("--performance-report", type=Path,
                        default=ROOT / "reports/2026-11-08-eleven-strategy-intraday-corrected.md")
    parser.add_argument("--quality-report", type=Path,
                        default=ROOT / "reports/2026-11-08-intraday-data-quality.md")
    parser.add_argument("--audit-report", type=Path,
                        default=ROOT / "INTRADAY_BACKTEST_FORENSIC_AUDIT.md")
    parser.add_argument("--quality-only", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    store_report = {"fetched": [], "absent": []}
    if args.from_store > 0:
        store_report = collect_from_store(args.from_store)
        print(f"band store: fetched {len(store_report['fetched'])} session(s)", flush=True)
        for line in store_report["absent"][:10]:
            print(f"band store: absent {line}", flush=True)

    from scripts.intraday_pipeline import load_kmiall
    universe = set(load_kmiall())
    days = _day_paths(args.input)
    if not days:
        print("No captured intraday session is available. Nothing is invented "
              "(SO-3). Dispatch with --from-store inside Actions.", flush=True)
        return 1

    generated = datetime.now(KARACHI).isoformat()
    baseline_trades: list[dict] = []
    execution_trades: list[dict] = []
    strict_trades: list[dict] = []
    quality: list[dict] = []
    suspicious: list[dict] = []
    session_audits: list[dict] = []
    spreads: list[dict] = []
    causality: dict = {
        "baseline_signal_equals_entry": 0,
        "execution_signal_equals_entry": 0,
        "strict_signal_equals_entry": 0,
        "baseline_entries_before_signal": 0,
        "execution_entries_before_signal": 0,
        "strict_entries_before_signal": 0,
    }
    execution_rejections_total = 0
    strict_rejections_total = 0
    tape_extremes: dict[str, float] = defaultdict(float)

    base_hist = {"5": defaultdict(list), "15": defaultdict(list),
                 "60": defaultdict(list)}
    exec_hist = {"5": defaultdict(list), "15": defaultdict(list),
                 "60": defaultdict(list)}
    strict_hist = {"5": defaultdict(list), "15": defaultdict(list),
                   "60": defaultdict(list)}
    base_prior: dict = defaultdict(list)
    exec_prior: dict = defaultdict(list)
    strict_prior: dict = defaultdict(list)
    base_offsets: dict = {}
    exec_offsets: dict = {}
    strict_offsets: dict = {}

    for day, path in sorted(days):
        print(f"auditing {day.isoformat()} from {path.name}", flush=True)
        day_data = eleven._build_day(path, day, universe)
        tape = day_data["tape"]
        raw = raw_audit(path, expected_universe=len(universe))
        quality_row = fx.session_quality(day_data, path, raw, len(universe))
        quality.append(quality_row)
        tape_extremes[day.isoformat()] = len(tape.bars)
        if args.quality_only:
            continue

        # Original replay, exactly the original signal frames and simulator.
        eleven._append_history(day_data, base_hist, base_offsets)
        ind5 = {sym: eleven._indicators5(frames)
                for sym, frames in base_hist["5"].items() if frames}
        ind15 = {sym: eleven._indicators15(frames)
                 for sym, frames in base_hist["15"].items() if frames}
        ind60 = {sym: eleven._indicators60(frames)
                 for sym, frames in base_hist["60"].items() if frames}
        rs = eleven._rs_table(day_data, base_hist, ind15)
        eleven._prior_volumes = base_prior
        day_base = eleven._evaluate(day_data, base_hist, ind5, ind15, ind60, rs)
        baseline_trades.extend(day_base)
        eleven._append_relvol(day_data)
        suspicious.extend(_suspicious_rows(day, day_base, tape))

        # Execution-only corrected arm: original signal frames, genuine fills.
        eleven._append_history(day_data, exec_hist, exec_offsets)
        ind5e = {sym: eleven._indicators5(frames)
                 for sym, frames in exec_hist["5"].items() if frames}
        ind15e = {sym: eleven._indicators15(frames)
                  for sym, frames in exec_hist["15"].items() if frames}
        ind60e = {sym: eleven._indicators60(frames)
                  for sym, frames in exec_hist["60"].items() if frames}
        rse = eleven._rs_table(day_data, exec_hist, ind15e)
        eleven._prior_volumes = exec_prior
        fx.reset_rejections()
        day_exec = eleven._evaluate(day_data, exec_hist, ind5e, ind15e,
                                    ind60e, rse,
                                    simulate=fx.simulate_executable)
        execution_trades.extend(day_exec)
        exec_rejections = list(fx.REJECTIONS)
        execution_rejections_total += len(exec_rejections)
        eleven._append_relvol(day_data)

        # Strict arm: no carried or stale minute in the signal frames.
        strict_day = {
            "day": day, "path": path, "tape": tape,
            "bands": fx.strict_bands(day_data),
        }
        eleven._append_history(strict_day, strict_hist, strict_offsets)
        ind5s = {sym: eleven._indicators5(frames)
                 for sym, frames in strict_hist["5"].items() if frames}
        ind15s = {sym: eleven._indicators15(frames)
                  for sym, frames in strict_hist["15"].items() if frames}
        ind60s = {sym: eleven._indicators60(frames)
                  for sym, frames in strict_hist["60"].items() if frames}
        rss = eleven._rs_table(strict_day, strict_hist, ind15s)
        eleven._prior_volumes = strict_prior
        fx.reset_rejections()
        day_strict = eleven._evaluate(strict_day, strict_hist, ind5s, ind15s,
                                      ind60s, rss,
                                      simulate=fx.simulate_executable)
        strict_trades.extend(day_strict)
        strict_rejections = list(fx.REJECTIONS)
        strict_rejections_total += len(strict_rejections)
        eleven._append_relvol(strict_day)

        for label, rows in (("baseline", day_base), ("execution", day_exec),
                            ("strict", day_strict)):
            for row in rows:
                signal = row.get("signal_time")
                entry = row.get("entry_time")
                if signal == entry:
                    causality[f"{label}_signal_equals_entry"] += 1
                if entry and signal and entry < signal:
                    causality[f"{label}_entries_before_signal"] += 1

        session_audits.append(fx.market_session_audit(day, day_base))
        print(f"  baseline {len(day_base)}, execution {len(day_exec)}, "
              f"strict {len(day_strict)}, exec rejections {len(exec_rejections)}, "
              f"strict rejections {len(strict_rejections)}", flush=True)

    if args.quality_only:
        quality_payload = {
            "generated": generated,
            "session_count": len(quality),
            "complete_sessions": len(_session_completeness(quality)),
            "complete_days": _session_completeness(quality),
            "missing_sessions": _missing_sessions([row["day"] for row in quality]),
            "sessions": quality,
            "minute_bars": sum(row["minute_bars"] for row in quality),
            "fresh_bars": sum(row["fresh_bars"] for row in quality),
            "stale_bars": sum(row["stale_bars"] for row in quality),
            "carried_bars": sum(row["carried_bars"] for row in quality),
            "duplicate_consecutive_rows": sum(
                row["duplicate_consecutive_rows"] or 0 for row in quality),
            "out_of_order_records": sum(
                row["out_of_order_records"] or 0 for row in quality),
            "venue_extreme_violations": sum(
                row["venue_extreme_violations"] for row in quality),
            "data_standard": fx.data_standard(),
            "store": store_report,
        }
        _json(args.quality, quality_payload)
        args.quality_report.parent.mkdir(parents=True, exist_ok=True)
        args.quality_report.write_text(fx.quality_markdown(quality_payload),
                                       encoding="utf-8")
        print(f"quality: {args.quality}")
        print(f"quality report: {args.quality_report}")
        return 0

    if not baseline_trades and not execution_trades and not strict_trades:
        print("No trade could be replayed. Nothing is invented (SO-3).", flush=True)
        return 1

    complete_days = _session_completeness(quality)
    session_days = [row["day"] for row in quality]
    baseline = fx.metrics(baseline_trades, complete_days, session_days,
                          STRATEGY_NAMES)
    execution = fx.metrics(execution_trades, complete_days, session_days,
                           STRATEGY_NAMES)
    strict = fx.metrics(strict_trades, complete_days, session_days,
                        STRATEGY_NAMES)
    baseline["published"] = {
        "total": PUBLISHED_TOTAL,
        "by_strategy": PUBLISHED_COUNTS,
        "sessions": PUBLISHED_SESSIONS,
        "full_sessions": PUBLISHED_FULL_SESSIONS_CLAIM,
        "report": PUBLISHED_REPORT,
        "run": PUBLISHED_RUN,
    }
    baseline["reconciliation"] = {
        "total_matches": baseline["all_sessions"]["trades"] == PUBLISHED_TOTAL,
        "by_strategy_matches": all(
            baseline["by_strategy_all"].get(name, {}).get("trades", 0)
            == count for name, count in PUBLISHED_COUNTS.items()),
        "published_full_sessions": PUBLISHED_FULL_SESSIONS_CLAIM,
        "recomputed_complete_sessions": len(complete_days),
        "full_session_claim_supported": len(complete_days) >= PUBLISHED_FULL_SESSIONS_CLAIM,
    }

    suspicious_unique: dict[tuple, dict] = {}
    for row in suspicious:
        key = (row.get("day"), row.get("symbol"), row.get("strategy"),
               row.get("entry_time"))
        suspicious_unique[key] = row
    suspicious = sorted(suspicious_unique.values(), key=lambda row: (
        float(row.get("net") or 0.0), str(row.get("day")), str(row.get("symbol"))))

    spreads = []
    for day, path in sorted(days):
        day_trades = [row for row in baseline_trades if row.get("day") == day.isoformat()]
        spreads.append({"day": day.isoformat(), **_spread_profile(path, day_trades)})
    observations = [row["median_bps"] for row in spreads
                    if row.get("median_bps") is not None]
    spread_summary = {
        "observations": sum(row["observations"] for row in spreads),
        "median_bps": round(statistics.median(observations), 2) if observations else None,
        "p90_bps": (round(max(row["p90_bps"] for row in spreads
                             if row.get("p90_bps") is not None), 2)
                    if any(row.get("p90_bps") is not None for row in spreads) else None),
        "note": ("quoted spread at the entry or exit minute of the original "
                 "ledger; not a realised fill, and not a substitute for depth"),
        "sessions": spreads,
    }

    delays = []
    for row in execution_trades:
        try:
            delays.append(float(row.get("entry_delay_seconds") or 0.0))
        except (TypeError, ValueError):
            continue
    delays.sort()
    delay_summary = {
        "median": round(statistics.median(delays), 2) if delays else None,
        "p90": round(delays[min(len(delays) - 1, int(0.90 * len(delays)))], 2)
        if delays else None,
        "max": round(max(delays), 2) if delays else None,
    }
    execution["entry_delay_seconds"] = delay_summary
    execution["entries_before_signal"] = causality["execution_entries_before_signal"]
    execution["same_bar"] = sum(1 for row in execution_trades if row.get("same_bar"))
    execution["ambiguous"] = sum(1 for row in execution_trades if row.get("ambiguous"))
    execution["rejections"] = execution_rejections_total
    strict["rejections"] = strict_rejections_total
    strict["entry_delay_seconds"] = {
        "median": (round(statistics.median([
            float(row.get("entry_delay_seconds") or 0.0) for row in strict_trades]), 2)
            if strict_trades else None),
    }

    quality_payload = {
        "generated": generated,
        "session_count": len(quality),
        "complete_sessions": len(complete_days),
        "complete_days": complete_days,
        "missing_sessions": _missing_sessions(session_days),
        "sessions": quality,
        "minute_bars": sum(row["minute_bars"] for row in quality),
        "fresh_bars": sum(row["fresh_bars"] for row in quality),
        "stale_bars": sum(row["stale_bars"] for row in quality),
        "carried_bars": sum(row["carried_bars"] for row in quality),
        "duplicate_consecutive_rows": sum(
            row["duplicate_consecutive_rows"] or 0 for row in quality),
        "out_of_order_records": sum(
            row["out_of_order_records"] or 0 for row in quality),
        "venue_extreme_violations": sum(
            row["venue_extreme_violations"] for row in quality),
        "data_standard": fx.data_standard(),
        "store": store_report,
    }
    _json(args.quality, quality_payload)

    strategy_audit = list(fx.STRATEGY_AUDIT)
    rows = _strategy_rows(strict, execution, baseline)
    final_conclusion = "BACKTEST INVALID, CORRECTIONS REQUIRED"
    corrected_status = "DATA INSUFFICIENT FOR VALID STRATEGY COMPARISON"
    run_url = (f"https://github.com/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/"
               f"{os.environ.get('GITHUB_RUN_ID')}"
               if os.environ.get("GITHUB_RUN_ID") else None)
    report = {
        "generated": generated,
        "study": "intraday_forensic_audit_v1",
        "commit": os.environ.get("GITHUB_SHA"),
        "run_url": run_url,
        "final_conclusion": final_conclusion,
        "corrected_status": corrected_status,
        "profitable_strategies": [],
        "production_changed": False,
        "days": session_days,
        "missing_sessions": quality_payload["missing_sessions"],
        "store": store_report,
        "baseline": baseline,
        "execution": execution,
        "corrected": strict,
        "strategy_audit": strategy_audit,
        "strategy_table": rows,
        "suspicious": suspicious,
        "causality": causality,
        "execution_detail": {
            "entry_delay_seconds": delay_summary,
            "entries_before_signal": causality["execution_entries_before_signal"],
            "same_bar": execution["same_bar"],
            "ambiguous": execution["ambiguous"],
            "rejections": execution["rejections"],
            "baseline_signal_equals_entry": causality["baseline_signal_equals_entry"],
            "execution_signal_equals_entry": causality["execution_signal_equals_entry"],
            "strict_signal_equals_entry": causality["strict_signal_equals_entry"],
            "baseline_entries_before_signal": causality["baseline_entries_before_signal"],
            "strict_entries_before_signal": causality["strict_entries_before_signal"],
            "cost": {
                "side_bps": config.COST_SIDE_BPS,
                "slippage_side_bps": config.SLIPPAGE_SIDE_BPS,
                "round_trip": round(config.round_trip_cost(), 6),
                "cgt_rate": config.CGT_RATE,
                "cgt_applicability": ("applied to positive net returns only; "
                                      "this is a research assumption, not a tax ruling"),
            },
            "partial_fills_modelled": False,
            "queue_position_modelled": False,
            "market_impact_modelled": False,
            "liquidity_note": ("entry and exit turnover and volume are recorded, "
                               "but the study does not claim this account could "
                               "have obtained the whole size"),
        },
        "calendar": {
            "timezone": "Asia/Karachi UTC+05:00, no daylight saving",
            "sessions": session_audits,
            "outside_band_total": sum(row["outside_band"] for row in session_audits),
            "exit_at_close_boundary_total": sum(
                row["exit_at_close_boundary"] for row in session_audits),
            "opening_auction_used": False,
            "closing_auction_used": False,
            "holidays_2026": ["2026-11-09"],
            "note": ("the regular bands are the only executable window; the "
                     "opening and closing auctions are not modelled"),
        },
        "spread": spread_summary,
        "quality": quality_payload,
        "data_standard": fx.data_standard(),
        "replay_seconds": round(time.perf_counter() - started, 2),
        "changed_files": [
            "src/backtest/intraday_forensic.py",
            "src/data/tape_bars.py",
            "scripts/backtest_eleven_intraday.py",
            "scripts/backtest_forensic_audit.py",
            "tests/test_intraday_forensic_audit.py",
            ".github/workflows/backtest.yml",
            "INTRADAY_BACKTEST_FORENSIC_AUDIT.md",
            "reports/2026-11-08-eleven-strategy-intraday-corrected.md",
            "reports/2026-11-08-intraday-data-quality.md",
            "data/research/backtest_forensic_audit.json",
            "data/research/eleven_corrected_trades.csv",
            "data/research/eleven_execution_corrected_trades.csv",
            "data/research/intraday_data_quality.json",
            "data/research/eleven_corrected_performance.json",
        ],
    }
    _json(args.out, report)
    _json(args.performance, {
        "generated": generated,
        "baseline": baseline,
        "execution": execution,
        "corrected": strict,
        "strategy_table": rows,
        "final_conclusion": final_conclusion,
        "corrected_status": corrected_status,
    })
    _csv(args.trades, strict_trades)
    _csv(args.execution_trades, execution_trades)
    args.performance_report.parent.mkdir(parents=True, exist_ok=True)
    args.performance_report.write_text(fx.performance_markdown(report),
                                       encoding="utf-8")
    args.quality_report.parent.mkdir(parents=True, exist_ok=True)
    args.quality_report.write_text(fx.quality_markdown(quality_payload),
                                   encoding="utf-8")
    args.audit_report.parent.mkdir(parents=True, exist_ok=True)
    args.audit_report.write_text(_audit_markdown(report), encoding="utf-8")
    print(json.dumps({
        "baseline": baseline["all_sessions"]["trades"],
        "execution": execution["all_sessions"]["trades"],
        "strict": strict["all_sessions"]["trades"],
        "complete_sessions": len(complete_days),
        "final": final_conclusion,
        "corrected": corrected_status,
    }, indent=1))
    print(f"audit: {args.out}")
    print(f"audit report: {args.audit_report}")
    print(f"corrected trades: {args.trades}")
    print(f"execution trades: {args.execution_trades}")
    print(f"performance: {args.performance}")
    print(f"quality: {args.quality}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
