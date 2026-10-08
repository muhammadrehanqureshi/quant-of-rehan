"""Frozen forward evaluation and machine-readable signal eligibility gate."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import numpy as np

from src.signals.intraday_engine import TP_PCT, SL_PCT, RULE_VERSION

COST_SIDE_BPS = 22.4
SLIPPAGE_SIDE_BPS = 10.0
CGT_RATE = 0.15
DISCOVERY_SESSIONS = 60
VALIDATION_SESSIONS = 60
OOS_SESSIONS = 60
MIN_DISCOVERY_TRADES = 30
MIN_VALIDATION_TRADES = 30
MIN_OOS_TRADES = 40
BOOTSTRAP_SEED = 20261008
BOOTSTRAP_SAMPLES = 5000
NET_CI_LEVEL = 0.95


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


def _metrics(rows: list[dict]) -> dict:
    trades = [r for r in rows if r.get("net_return") is not None]
    if not trades:
        return {"sessions": len(rows), "trades": 0}
    net = np.asarray([float(r["net_return"]) for r in trades], dtype=float)
    gross = np.asarray([float(r["gross_return"]) for r in trades], dtype=float)
    wins = net[net > 0]
    losses = net[net <= 0]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    boot = rng.choice(net, size=(BOOTSTRAP_SAMPLES, len(net)), replace=True).mean(axis=1)
    lower = float(np.quantile(boot, 1.0 - NET_CI_LEVEL))
    equity = np.cumprod(1.0 + np.asarray([
        float(r["net_return"]) if r.get("net_return") is not None else 0.0
        for r in rows
    ]))
    peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))
    dd = 1.0 - np.concatenate(([1.0], equity)) / peak
    symbols = Counter(str(r["candidate"]["symbol"]) for r in trades)
    total_symbols = sum(symbols.values())
    top10 = sum(n for _s, n in symbols.most_common(10)) / total_symbols
    return {
        "sessions": len(rows),
        "trades": len(trades),
        "tp_first_rate": float(np.mean([r["label"] == "TP_FIRST" for r in trades])),
        "adverse_first_rate": float(np.mean([r["label"] in ("SL_FIRST", "SL_AMBIG") for r in trades])),
        "timeout_rate": float(np.mean([r["label"] == "TIMEOUT" for r in trades])),
        "gross_expectancy": float(gross.mean()),
        "net_expectancy": float(net.mean()),
        "net_expectancy_ci95_lower": lower,
        "average_win": None if len(wins) == 0 else float(wins.mean()),
        "average_loss": None if len(losses) == 0 else float(losses.mean()),
        "median_trade": float(np.median(net)),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else None,
        "maximum_drawdown": float(dd.max()),
        "trade_frequency": len(trades) / max(len(rows), 1),
        "average_holding_minutes": float(np.mean([r["minutes_held"] for r in trades])),
        "median_time_to_target_minutes": _median_target_time(trades),
        "top_10_symbol_pick_share": top10,
        "unique_symbols": len(symbols),
        "symbol_pick_counts": dict(symbols),
    }


def _median_target_time(trades: list[dict]) -> float | None:
    values = [r["minutes_held"] for r in trades if r["label"] == "TP_FIRST"]
    return None if not values else float(np.median(values))


def evaluate_gate(daily_rows: list[dict]) -> dict:
    """Evaluate one frozen chronological D/V/OOS window once it is complete.

    First 60 sessions are discovery, next 60 validation, final 60 locked OOS.
    No later rows are used to re-open or tune the gate.
    """
    rows = sorted(daily_rows, key=lambda r: r["date"])
    unique = []
    seen = set()
    for row in rows:
        d = str(row["date"])
        if d not in seen:
            seen.add(d)
            unique.append(row)
    required = DISCOVERY_SESSIONS + VALIDATION_SESSIONS + OOS_SESSIONS
    if len(unique) < required:
        return {
            "rule_version": RULE_VERSION,
            "status": "RESEARCH_NOT_READY",
            "eligible": False,
            "paper_observation_enabled": True,
            "live_signal_enabled": False,
            "sessions_required": required,
            "sessions_collected": len(unique),
            "reason": "complete the frozen 60/60/60 chronological paper window",
        }

    window = unique[:required]
    discovery = window[:DISCOVERY_SESSIONS]
    validation = window[DISCOVERY_SESSIONS:DISCOVERY_SESSIONS + VALIDATION_SESSIONS]
    oos_rows = window[-OOS_SESSIONS:]
    metrics = {
        "discovery": _metrics(discovery),
        "validation": _metrics(validation),
        "oos": _metrics(oos_rows),
    }
    enough = (
        metrics["discovery"].get("trades", 0) >= MIN_DISCOVERY_TRADES
        and metrics["validation"].get("trades", 0) >= MIN_VALIDATION_TRADES
        and metrics["oos"].get("trades", 0) >= MIN_OOS_TRADES
    )
    economic = enough and all(
        metrics[name]["net_expectancy"] > 0 for name in ("discovery", "validation", "oos")
    )
    oos = metrics["oos"]
    profit_factor = oos.get("profit_factor")
    # No losing trades makes profit factor mathematically undefined, which is
    # at least as strong as the minimum ratio when the independent OOS CI is
    # also positive. Keep the report value null rather than serializing infinity.
    profit_factor_ok = profit_factor is None or profit_factor >= 1.10
    oos_clear = (
        enough
        and oos.get("net_expectancy_ci95_lower", float("-inf")) > 0
        and profit_factor_ok
        and oos.get("top_10_symbol_pick_share", 1) <= 0.60
    )
    passed = economic and oos_clear
    return {
        "rule_version": RULE_VERSION,
        "status": "ELIGIBLE_FOR_SIGNAL" if passed else "LOCKED_OOS_FAILED",
        "eligible": passed,
        "paper_observation_enabled": True,
        "live_signal_enabled": passed,
        "window_locked": True,
        "window_sessions": required,
        "window_start": window[0]["date"],
        "window_end": window[-1]["date"],
        "thresholds": {
            "discovery_trades": MIN_DISCOVERY_TRADES,
            "validation_trades": MIN_VALIDATION_TRADES,
            "oos_trades": MIN_OOS_TRADES,
            "oos_net_ci95_lower_min": 0.0,
            "oos_profit_factor_min": 1.10,
            "top_10_symbol_share_max": 0.60,
            "cost_side_bps": COST_SIDE_BPS,
            "slippage_side_bps": SLIPPAGE_SIDE_BPS,
        },
        "metrics": metrics,
        "reason": "frozen OOS criteria passed" if passed else
                  "frozen evidence/economic criteria failed; no automatic promotion",
    }
