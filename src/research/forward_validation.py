"""Frozen candidate-library research and production health gate."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any

import numpy as np

from src import config
from src.signals.intraday_engine import CANDIDATE_RULES, TP_PCT, SL_PCT, RULE_VERSION

# The cost schedule is defined once, in src/config.py, and read from there so
# the frozen gate and the live paper cycle can never drift apart. Values are
# identical to the schedule the candidate library was frozen against.
COST_SIDE_BPS = config.COST_SIDE_BPS
SLIPPAGE_SIDE_BPS = config.SLIPPAGE_SIDE_BPS
CGT_RATE = config.CGT_RATE
DISCOVERY_SESSIONS = 60
VALIDATION_SESSIONS = 60
OOS_SESSIONS = 60
MIN_DISCOVERY_TRADES = 30
MIN_VALIDATION_TRADES = 30
MIN_OOS_TRADES = 40
MIN_MONITOR_TRADES = 20
BOOTSTRAP_SEED = 20261008
BOOTSTRAP_SAMPLES = 5000
NET_CI_LEVEL = 0.95
MAX_OOS_DRAWDOWN = 0.15
MAX_OOS_LOSING_STREAK = 10
MAX_OOS_DEGRADATION = 0.50
MAX_MONITOR_DRAWDOWN = 0.10
MAX_MONITOR_LOSING_STREAK = 8


def _stamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def label_candidate(candidate: dict[str, Any], bars: list[dict]) -> dict[str, Any]:
    """Label a candidate strictly after its entry bar, stop-first on ties."""
    entry = float(candidate["entry_reference"])
    target = entry * (1.0 + TP_PCT)
    stop = entry * (1.0 - SL_PCT)
    decision = _stamp(str(candidate["timestamp"]))
    later = []
    for bar in bars:
        stamp = bar["timestamp"]
        if isinstance(stamp, str):
            stamp = _stamp(stamp)
        if stamp > decision:
            later.append((stamp, bar))
    later.sort(key=lambda item: item[0])

    label = "TIMEOUT"
    exit_price = None
    exit_time = None
    bars_held = 0
    for stamp, bar in later:
        bars_held += 1
        op, hi, lo = (float(bar[k]) for k in ("open", "high", "low"))
        stop_hit = lo <= stop
        target_hit = hi >= target
        if stop_hit:
            label = "SL_AMBIG" if target_hit else "SL_FIRST"
            exit_price = op if op < stop else stop
            exit_time = stamp
            break
        if target_hit:
            label = "TP_FIRST"
            exit_price = target
            exit_time = stamp
            break
    if exit_price is None:
        if not later:
            return {"label": "UNCLOSED", "gross_return": None, "net_return": None,
                    "bars_held": 0, "minutes_held": None}
        stamp, last = later[-1]
        exit_price = float(last["close"])
        exit_time = stamp
        bars_held = len(later)

    gross = exit_price / entry - 1.0
    cost = 2.0 * (COST_SIDE_BPS + SLIPPAGE_SIDE_BPS) / 10000.0
    net = gross - cost
    if net > 0:
        net *= 1.0 - CGT_RATE
    minutes = int((exit_time - decision).total_seconds() / 60)
    return {
        "label": label,
        "entry_reference": entry,
        "target": target,
        "stop": stop,
        "exit_price": exit_price,
        "gross_return": gross,
        "net_return": net,
        "bars_held": bars_held,
        "minutes_held": minutes,
        "slippage_bps_per_side": SLIPPAGE_SIDE_BPS,
        "cost_side_bps": COST_SIDE_BPS,
    }


def _loss_streak(values: list[float]) -> int:
    longest = current = 0
    for value in values:
        if value <= 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _metrics(rows: list[dict], ci_level: float = NET_CI_LEVEL) -> dict:
    trades = [r for r in rows if r.get("net_return") is not None
              and r.get("candidate") is not None]
    if not trades:
        return {"sessions": len(rows), "trades": 0}
    net = np.asarray([float(r["net_return"]) for r in trades], dtype=float)
    gross = np.asarray([float(r["gross_return"]) for r in trades], dtype=float)
    wins = net[net > 0]
    losses = net[net <= 0]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    block_length = max(2, int(round(len(net) ** (1.0 / 3.0))))
    block_count = math.ceil(len(net) / block_length)
    starts = rng.integers(0, len(net), size=(BOOTSTRAP_SAMPLES, block_count))
    offsets = np.arange(block_length)
    indices = (starts[:, :, None] + offsets) % len(net)
    samples = indices.reshape(BOOTSTRAP_SAMPLES, -1)[:, :len(net)]
    boot = net[samples].mean(axis=1)
    lower = float(np.quantile(boot, 1.0 - ci_level))
    equity = np.cumprod(1.0 + np.asarray([
        float(r["net_return"]) for r in rows if r.get("net_return") is not None
    ], dtype=float))
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    drawdown = 1.0 - np.concatenate(([1.0], equity)) / peak
    symbols = Counter(str(r["candidate"]["symbol"]) for r in trades)
    total_symbols = sum(symbols.values())
    picks_by_date = Counter(str(r["date"]) for r in trades)
    return {
        "sessions": len(rows),
        "trades": len(trades),
        "positive_net_trade_rate": float(np.mean(net > 0)),
        "tp_first_rate": float(np.mean([r["label"] == "TP_FIRST" for r in trades])),
        "adverse_first_rate": float(np.mean([r["label"] in ("SL_FIRST", "SL_AMBIG") for r in trades])),
        "timeout_rate": float(np.mean([r["label"] == "TIMEOUT" for r in trades])),
        "gross_total_return": float(np.prod(1.0 + gross) - 1.0),
        "net_total_return": float(np.prod(1.0 + net) - 1.0),
        "gross_expectancy": float(gross.mean()),
        "net_expectancy": float(net.mean()),
        "net_expectancy_ci_lower": lower,
        "ci_level": ci_level,
        "bootstrap_method": "circular moving-block bootstrap",
        "bootstrap_block_length_trades": block_length,
        "median_trade": float(np.median(net)),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        "maximum_drawdown": float(drawdown.max()),
        "worst_losing_streak": _loss_streak(net.tolist()),
        "average_winner": None if len(wins) == 0 else float(wins.mean()),
        "average_loser": None if len(losses) == 0 else float(losses.mean()),
        "average_holding_minutes": float(np.mean([r["minutes_held"] for r in trades])),
        "top_10_symbol_pick_share": sum(n for _, n in symbols.most_common(10)) / total_symbols,
        "max_daily_trade_count": max(picks_by_date.values()),
        "unique_symbols": len(symbols),
        "symbol_pick_counts": dict(symbols),
    }


def _valid_rows(daily_rows: list[dict]) -> list[dict]:
    rows = sorted(daily_rows, key=lambda r: str(r.get("date", "")))
    unique = []
    seen = set()
    for row in rows:
        day = str(row.get("date", ""))
        if not day or day in seen:
            continue
        seen.add(day)
        quality = row.get("data_quality") or {}
        if row.get("storage_status") == "unavailable":
            continue
        if quality and quality.get("quality") != "verified":
            continue
        unique.append(row)
    return unique


def _rule_rows(rows: list[dict], rule: str) -> list[dict]:
    result = []
    for row in rows:
        outcomes = row.get("outcomes_by_rule") or {}
        outcome = outcomes.get(rule)
        if outcome is None and rule == RULE_VERSION and "net_return" in row:
            outcome = row
        if outcome is None:
            outcome = {"candidate": None, "label": "NO_CANDIDATE",
                       "gross_return": None, "net_return": None,
                       "minutes_held": None}
        result.append({"date": row["date"], **outcome})
    return result


def _cycle_alpha(cycle_number: int, hypotheses: int = 1) -> float:
    """Spend 5% family-wise error across repeated candidate cohorts."""
    return 0.05 * 6.0 / (math.pi ** 2 * cycle_number ** 2 * hypotheses)


def _select_validation_winner(discovery: list[dict], validation: list[dict],
                              cycle_number: int) -> tuple[str | None, dict]:
    correction_level = 1.0 - _cycle_alpha(cycle_number, len(CANDIDATE_RULES))
    reports = {}
    eligible = []
    for rule in CANDIDATE_RULES:
        d_metrics = _metrics(_rule_rows(discovery, rule))
        v_metrics = _metrics(_rule_rows(validation, rule), ci_level=correction_level)
        reports[rule] = {"discovery": d_metrics, "validation": v_metrics}
        if (d_metrics.get("trades", 0) >= MIN_DISCOVERY_TRADES
                and v_metrics.get("trades", 0) >= MIN_VALIDATION_TRADES
                and d_metrics.get("net_expectancy", 0) > 0
                and v_metrics.get("net_expectancy", 0) > 0
                and v_metrics.get("net_expectancy_ci_lower", float("-inf")) > 0):
            eligible.append((v_metrics["net_expectancy_ci_lower"],
                             v_metrics["net_expectancy"], rule))
    if not eligible:
        return None, reports
    eligible.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return eligible[0][2], reports


def _oos_passes(validation: dict, oos: dict, ci_level: float) -> tuple[bool, dict]:
    pf = oos.get("profit_factor")
    checks = {
        "minimum_trade_count": oos.get("trades", 0) >= MIN_OOS_TRADES,
        "positive_net_expectancy": oos.get("net_expectancy", 0) > 0,
        "positive_adjusted_lower_bound": oos.get("net_expectancy_ci_lower", float("-inf")) > 0
            and oos.get("ci_level", 0) >= ci_level,
        "profit_factor": pf is None or pf >= 1.10,
        "symbol_concentration": oos.get("top_10_symbol_pick_share", 1) <= 0.60,
        "maximum_drawdown": oos.get("maximum_drawdown", 1) <= MAX_OOS_DRAWDOWN,
        "losing_streak": oos.get("worst_losing_streak", 999) <= MAX_OOS_LOSING_STREAK,
        "degradation": oos.get("net_expectancy", 0) >= validation.get("net_expectancy", 0) * (1.0 - MAX_OOS_DEGRADATION),
        "one_trade_per_day": oos.get("max_daily_trade_count", 0) <= 1,
    }
    return all(checks.values()), checks


def _running_state(rows: list[dict], start: int, cycle_number: int, reason: str,
                   previous_cycle: dict | None = None) -> dict:
    collected = max(0, len(rows) - start)
    status = "RESEARCH_RUNNING" if collected else "RESEARCH_INSUFFICIENT_DATA"
    if previous_cycle and previous_cycle.get("status") in {
            "PRODUCTION_DEGRADED", "PAPER_VALIDATED"}:
        status = previous_cycle["status"]
    return {
        "rule_version": "candidate_library_v1",
        "status": status,
        "research_status": "RESEARCH_RUNNING" if collected else "RESEARCH_INSUFFICIENT_DATA",
        "eligible": False,
        "paper_observation_enabled": True,
        "live_signal_enabled": False,
        "sessions_required": DISCOVERY_SESSIONS + VALIDATION_SESSIONS,
        "sessions_collected": collected,
        "cycle_number": cycle_number,
        "reason": reason,
        "previous_cycle": previous_cycle,
    }


def evaluate_gate(daily_rows: list[dict]) -> dict:
    """Compare a fixed candidate library on chronological D/V, then locked OOS.

    Invalid or unverifiable dates do not consume a research session. A failed
    candidate cohort is frozen and the next cohort starts with new dates.
    Candidate selection uses D/V only; OOS results never choose a candidate.
    """
    rows = _valid_rows(daily_rows)
    discovery_validation = DISCOVERY_SESSIONS + VALIDATION_SESSIONS
    full_window = discovery_validation + OOS_SESSIONS
    start = 0
    cycle_number = 1
    previous_cycle = None
    while len(rows) - start >= discovery_validation:
        discovery = rows[start:start + DISCOVERY_SESSIONS]
        validation = rows[start + DISCOVERY_SESSIONS:start + discovery_validation]
        selected, candidate_metrics = _select_validation_winner(
            discovery, validation, cycle_number)
        if selected is None:
            previous_cycle = {
                "status": "RESEARCH_FAILED",
                "window_start": rows[start]["date"],
                "window_end": validation[-1]["date"],
                "reason": "no pre-registered candidate passed discovery and multiplicity-adjusted validation",
                "candidate_metrics": candidate_metrics,
            }
            start += discovery_validation
            cycle_number += 1
            continue
        selected_validation = candidate_metrics[selected]["validation"]
        if len(rows) - start < full_window:
            state = _running_state(rows, start, cycle_number,
                                   "candidate selected using discovery and adjusted validation; collecting locked OOS",
                                   previous_cycle)
            state.update({"selected_rule_version": selected,
                          "validation_metrics": selected_validation,
                          "oos_sessions_required": OOS_SESSIONS,
                          "oos_sessions_collected": len(rows) - start - discovery_validation,
                          "window_start": rows[start]["date"],
                          "validation_end": validation[-1]["date"],
                          "candidate_metrics": candidate_metrics})
            return state

        oos_rows = rows[start + discovery_validation:start + full_window]
        oos_ci_level = 1.0 - _cycle_alpha(cycle_number)
        oos = _metrics(_rule_rows(oos_rows, selected), ci_level=oos_ci_level)
        passed, checks = _oos_passes(selected_validation, oos, oos_ci_level)
        production_data_ready = all(
            bool((row.get("data_quality") or {}).get("production_data_ready"))
            for row in rows[start:start + full_window]
        )
        cycle_report = {
            "status": "PAPER_VALIDATED" if passed else "RESEARCH_FAILED",
            "production_data_ready": production_data_ready,
            "selected_rule_version": selected,
            "window_start": rows[start]["date"],
            "discovery_end": discovery[-1]["date"],
            "validation_end": validation[-1]["date"],
            "oos_end": oos_rows[-1]["date"],
            "candidate_metrics": candidate_metrics,
            "oos_metrics": oos,
            "oos_checks": checks,
        }
        if not passed:
            previous_cycle = cycle_report
            start += full_window
            cycle_number += 1
            continue
        if not production_data_ready:
            cycle_report["status"] = "PAPER_VALIDATED"
            cycle_report["reason"] = (
                "statistical gate passed, but market-data rights and latency "
                "were not confirmed for every session"
            )
            previous_cycle = cycle_report
            start += full_window
            cycle_number += 1
            continue

        monitor_rows = rows[start + full_window:]
        if any(not (row.get("data_quality") or {}).get("production_data_ready")
               for row in monitor_rows):
            demotion_reason = "production data rights or latency verification was lost"
            previous_cycle = {**cycle_report, "status": "PRODUCTION_DEGRADED",
                              "demotion_reason": demotion_reason}
            start += full_window + len(monitor_rows)
            cycle_number += 1
            continue
        monitor_projection = _rule_rows(monitor_rows, selected)
        monitor_trades = [r for r in monitor_projection if r.get("net_return") is not None
                          and r.get("candidate") is not None]
        monitor_state = "PRODUCTION_ACTIVE"
        monitor_metrics = {"sessions": len(monitor_rows), "trades": len(monitor_trades)}
        demotion_reason = None
        demotion_end = None
        if len(monitor_trades) >= MIN_MONITOR_TRADES:
            recent_trades = monitor_trades[-MIN_MONITOR_TRADES:]
            monitor_metrics = _metrics(recent_trades)
            if monitor_metrics.get("net_expectancy", 0) <= 0:
                demotion_reason = "last 20 production trades have non-positive net expectancy"
            elif monitor_metrics.get("maximum_drawdown", 0) > MAX_MONITOR_DRAWDOWN:
                demotion_reason = "last 20 production trades exceeded the drawdown limit"
            elif monitor_metrics.get("worst_losing_streak", 0) >= MAX_MONITOR_LOSING_STREAK:
                demotion_reason = "last 20 production trades exceeded the losing-streak limit"
            if demotion_reason:
                demotion_end = monitor_projection.index(recent_trades[-1])
        if demotion_reason:
            monitor_state = "PRODUCTION_DEGRADED"
            previous_cycle = {**cycle_report, "status": monitor_state,
                              "monitor_metrics": monitor_metrics,
                              "demotion_reason": demotion_reason}
            start += full_window + (demotion_end + 1 if demotion_end is not None else len(monitor_rows))
            cycle_number += 1
            continue

        return {
            "rule_version": "candidate_library_v1",
            "selected_rule_version": selected,
            "status": monitor_state,
            "eligible": True,
            "paper_observation_enabled": True,
            "live_signal_enabled": True,
            "window_locked": True,
            "window_sessions": full_window,
            "window_start": cycle_report["window_start"],
            "window_end": cycle_report["oos_end"],
            "candidate_metrics": candidate_metrics,
            "metrics": {"discovery": candidate_metrics[selected]["discovery"],
                         "validation": selected_validation, "oos": oos,
                         "monitoring": monitor_metrics},
            "oos_checks": checks,
            "thresholds": {
                "discovery_sessions": DISCOVERY_SESSIONS,
                "validation_sessions": VALIDATION_SESSIONS,
                "locked_oos_sessions": OOS_SESSIONS,
                "discovery_min_trades": MIN_DISCOVERY_TRADES,
                "validation_min_trades": MIN_VALIDATION_TRADES,
                "oos_min_trades": MIN_OOS_TRADES,
                "oos_net_expectancy_adjusted_ci_lower_min": 0.0,
                "oos_profit_factor_min": 1.10,
                "oos_top_10_symbol_share_max": 0.60,
                "oos_max_drawdown": MAX_OOS_DRAWDOWN,
                "oos_max_losing_streak": MAX_OOS_LOSING_STREAK,
                "max_oos_expectancy_degradation": MAX_OOS_DEGRADATION,
                "monitor_min_trades": MIN_MONITOR_TRADES,
                "monitor_max_drawdown": MAX_MONITOR_DRAWDOWN,
                "monitor_max_losing_streak": MAX_MONITOR_LOSING_STREAK,
                "fees_bps_per_side": COST_SIDE_BPS,
                "slippage_bps_per_side": SLIPPAGE_SIDE_BPS,
                "cgt_rate": CGT_RATE,
                "target_pct": TP_PCT,
                "stop_pct": SL_PCT,
            },
            "reason": "frozen 60/60/60 evidence passed" if monitor_state == "PRODUCTION_ACTIVE" else demotion_reason,
            "production_signals_enabled": monitor_state == "PRODUCTION_ACTIVE",
        }

    if previous_cycle:
        state = _running_state(rows, start, cycle_number,
                               "previous candidate cohort is frozen; collecting a fresh discovery and validation window",
                               previous_cycle)
    else:
        state = _running_state(rows, start, cycle_number,
                               "collecting 60 discovery and 60 validation sessions for the registered candidate library")
    if len(rows) >= 60 and len(rows) - start < discovery_validation:
        state["discovery_sessions_collected"] = min(DISCOVERY_SESSIONS, len(rows) - start)
        state["validation_sessions_collected"] = max(0, len(rows) - start - DISCOVERY_SESSIONS)
    return state
