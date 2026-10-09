"""RETIRED SCANNER (rebuild 2026-10-09). Do not use for signals.

This was the opening-range breakout candidate library. It is no longer an
active scanner: the ONE authoritative scanner is
src/signals/momentum_scanner.py, which scores fast momentum, momentum
acceleration and volume expansion, as the owner specified.

Why the file still exists: src/research/forward_validation.py (the frozen
paper-validation gate) imports the rule constants below. Nothing else in the
scheduled system imports this module, and no code path here can emit a
signal any more. Its tests were quarantined to
legacy/retired_scanners/test_intraday_engine_retired.py.

History: it preserves chronology, builds only closed five-minute bars,
rejects stale or malformed data, applies a broad-market gate, and returned at
most one ranked long candidate. It never placed an order and did not use
volume because the captured feed does not contain it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np

from src.data.sessions import KARACHI, is_trading_day, open_time

TP_PCT = 0.02
SL_PCT = 0.01
MIN_COVERAGE = 0.80
MIN_FRESH_SYMBOLS = 0.80
STALE_MINUTES = 15
OPENING_RANGE_BARS = 6
MIN_OBSERVATION_TIME = 60
MAX_RETURN_FROM_OPEN = 0.01
MAX_DISTANCE_FROM_HIGH = 0.005
MIN_RELATIVE_STRENGTH = 0.0025
MIN_WINNER_MARGIN = 0.001
RULE_VERSION = "opening_range_breakout_rs_v1"
CANDIDATE_RULES = {
    RULE_VERSION: {
        "opening_range_bars": 6, "min_relative_strength": 0.0025,
        "market_gate": True, "max_return_from_open": 0.01,
        "max_distance_from_high": 0.005,
    },
    "opening_range_breakout_no_rs_floor_v1": {
        "opening_range_bars": 6, "min_relative_strength": 0.0,
        "market_gate": True, "max_return_from_open": 0.01,
        "max_distance_from_high": 0.005,
    },
    "opening_range_60m_rs_v1": {
        "opening_range_bars": 12, "min_relative_strength": 0.0025,
        "market_gate": True, "max_return_from_open": 0.01,
        "max_distance_from_high": 0.005,
    },
    "opening_range_breakout_no_breadth_gate_v1": {
        "opening_range_bars": 6, "min_relative_strength": 0.0025,
        "market_gate": False, "max_return_from_open": 0.01,
        "max_distance_from_high": 0.005,
    },
    "opening_range_breakout_no_extension_cap_v1": {
        "opening_range_bars": 6, "min_relative_strength": 0.0025,
        "market_gate": True, "max_return_from_open": None,
        "max_distance_from_high": None,
    },
}


@dataclass(frozen=True)
class Bar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Candidate:
    symbol: str
    timestamp: str
    entry_reference: float
    target: float
    stop_reference: float
    score: float
    relative_strength: float
    session_return: float
    distance_from_high: float
    rationale: str
    data_quality: str = "verified OHLC; intraday volume unavailable"
    order_type: str = "paper reference, not executable"


def parse_capture(path: Path, symbols: Iterable[str], as_of: datetime) -> tuple[dict[str, list[Bar]], dict]:
    """Load only valid bars strictly before as_of, deduplicating exact repeats."""
    universe = set(symbols)
    collected: dict[str, dict[datetime, Bar]] = {}
    bad_rows = 0
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=KARACHI)
    session_day = as_of.date()
    if not is_trading_day(session_day):
        return {}, {"quality": "invalid", "reason": "not a PSX trading day",
                    "coverage": 0.0, "bad_rows": 0}
    if not path.is_file():
        return {}, {"quality": "invalid", "reason": "capture file missing",
                    "coverage": 0.0, "bad_rows": 0}

    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            symbol = str(rec["symbol"]).strip().upper()
            captured = datetime.fromisoformat(str(rec["ts"]))
            if symbol not in universe or captured.date() != session_day:
                continue
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=KARACHI)
            for item in rec.get("bars", []):
                t = time.fromisoformat(str(item["t"]))
                stamp = datetime.combine(session_day, t, tzinfo=as_of.tzinfo)
                if stamp >= as_of:
                    continue
                vals = [float(item[k]) for k in ("o", "h", "l", "c")]
                op, hi, lo, close = vals
                if not all(np.isfinite(v) and v > 0 for v in vals):
                    bad_rows += 1
                    continue
                if lo > min(op, close) or hi < max(op, close) or hi < lo:
                    bad_rows += 1
                    continue
                bar = Bar(symbol, stamp, op, hi, lo, close)
                by_time = collected.setdefault(symbol, {})
                prior = by_time.get(stamp)
                if prior is not None and prior != bar:
                    bad_rows += 1
                    continue
                by_time[stamp] = bar
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OverflowError):
            bad_rows += 1

    bars = {sym: sorted(rows.values(), key=lambda b: b.timestamp)
            for sym, rows in collected.items() if rows}
    coverage = len(bars) / max(len(universe), 1)
    fresh = 0
    open_dt = datetime.combine(session_day, time(*open_time(session_day)), tzinfo=as_of.tzinfo)
    for rows in bars.values():
        last = rows[-1].timestamp
        if last >= open_dt and as_of - last <= timedelta(minutes=STALE_MINUTES):
            fresh += 1
    fresh_coverage = fresh / max(len(universe), 1)
    quality = "verified" if coverage >= MIN_COVERAGE and fresh_coverage >= MIN_FRESH_SYMBOLS and bad_rows == 0 else "degraded"
    reason = "ok" if quality == "verified" else "coverage, freshness, or OHLC validation failed"
    return bars, {
        "quality": quality,
        "reason": reason,
        "coverage": round(coverage, 4),
        "fresh_coverage": round(fresh_coverage, 4),
        "symbols_with_bars": len(bars),
        "universe_size": len(universe),
        "bad_rows": bad_rows,
        "volume": "unavailable",
        "order_flow": "unavailable",
    }


def aggregate_5m(rows: list[Bar], session_open: datetime, as_of: datetime) -> list[dict]:
    """Aggregate complete, consecutive five-minute bars ending before as_of."""
    groups: dict[int, list[Bar]] = {}
    for bar in rows:
        if bar.timestamp < session_open or bar.timestamp >= as_of:
            continue
        offset = int((bar.timestamp - session_open).total_seconds() // 60)
        groups.setdefault(offset // 5, []).append(bar)
    result = []
    for bucket in sorted(groups):
        minute_bars = sorted(groups[bucket], key=lambda b: b.timestamp)
        if len(minute_bars) != 5:
            continue
        expected = [minute_bars[0].timestamp + timedelta(minutes=i) for i in range(5)]
        if [b.timestamp for b in minute_bars] != expected:
            continue
        result.append({
            "timestamp": minute_bars[-1].timestamp + timedelta(minutes=1),
            "open": minute_bars[0].open,
            "high": max(b.high for b in minute_bars),
            "low": min(b.low for b in minute_bars),
            "close": minute_bars[-1].close,
        })
    return result


def scan_snapshot(bars_by_symbol: dict[str, list[Bar]], universe: list[str],
                  as_of: datetime, quality: dict,
                  rule_version: str = RULE_VERSION) -> dict:
    """Return one causal paper candidate or NO TRADE for this scan time."""
    if rule_version not in CANDIDATE_RULES:
        raise ValueError(f"unknown candidate rule: {rule_version}")
    rule = CANDIDATE_RULES[rule_version]
    opening_range_bars = rule["opening_range_bars"]
    min_relative_strength = rule["min_relative_strength"]
    market_gate = rule["market_gate"]
    max_return_from_open = rule["max_return_from_open"]
    max_distance_from_high = rule["max_distance_from_high"]
    day = as_of.date()
    if quality.get("quality") != "verified":
        return {"rule_version": rule_version, "status": "NO_TRADE",
                "reason": "market data quality gate failed", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}
    if not is_trading_day(day):
        return {"rule_version": rule_version, "status": "NO_TRADE",
                "reason": "not a PSX trading day", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}

    session_open = datetime.combine(day, time(*open_time(day)), tzinfo=as_of.tzinfo)
    elapsed = (as_of - session_open).total_seconds() / 60
    if elapsed < max(MIN_OBSERVATION_TIME, (opening_range_bars + 1) * 5):
        return {"rule_version": rule_version, "status": "NO_TRADE",
                "reason": "market observation period not complete", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}

    five: dict[str, list[dict]] = {}
    returns: dict[str, float] = {}
    for sym in universe:
        rows = bars_by_symbol.get(sym, [])
        bars = aggregate_5m(rows, session_open, as_of)
        if len(bars) < opening_range_bars + 1:
            continue
        five[sym] = bars
        first_open = bars[0]["open"]
        if first_open > 0:
            returns[sym] = bars[-1]["close"] / first_open - 1.0

    coverage = len(returns) / max(len(universe), 1)
    if coverage < MIN_COVERAGE:
        return {"rule_version": rule_version, "status": "NO_TRADE",
                "reason": "insufficient complete five-minute coverage",
                "candidate": None, "as_of": as_of.isoformat(),
                "market": {"coverage": coverage}, "data_quality": quality}

    median_return = float(np.median(list(returns.values())))
    advancer_share = sum(v > 0 for v in returns.values()) / len(returns)
    market = {"proxy": "cross-sectional median and advancer share, not official KMIALL index",
              "median_return": median_return, "advancer_share": advancer_share,
              "coverage": coverage}
    if market_gate and (median_return < 0.001 or advancer_share < 0.55):
        return {"rule_version": rule_version, "status": "NO_TRADE",
                "reason": "broad KMIALL proxy is not supportive",
                "candidate": None, "as_of": as_of.isoformat(),
                "market": market, "data_quality": quality}

    candidates: list[Candidate] = []
    for sym, series in five.items():
        opening = series[:opening_range_bars]
        opening_high = max(b["high"] for b in opening)
        previous = series[-2]
        bar = series[-1]
        close = bar["close"]
        if not (previous["close"] <= opening_high < close):
            continue

        first_open = series[0]["open"]
        session_return = close / first_open - 1.0
        high_so_far = max(b["high"] for b in series
                          if b["timestamp"] <= bar["timestamp"])
        distance_from_high = high_so_far / close - 1.0
        relative_strength = session_return - median_return
        return_ok = (session_return > 0 and
                     (max_return_from_open is None or session_return <= max_return_from_open))
        distance_ok = (max_distance_from_high is None or
                       distance_from_high <= max_distance_from_high)
        if (as_of - bar["timestamp"] <= timedelta(minutes=5)
                and return_ok and distance_ok
                and relative_strength >= min_relative_strength):
            # Candidates must break out on a recent completed bar. Older
            # breakouts are never replayed as fresh entry references.
            score = relative_strength
            rationale = "latest completed bar broke the registered range"
            rationale += "; cross-sectional KMIALL breadth gate applied" if market_gate else "; breadth gate omitted for comparison"
            rationale += "; relative-strength floor applied" if min_relative_strength else "; no relative-strength floor"
            rationale += "; extension caps applied" if max_return_from_open is not None else "; extension caps omitted for comparison"
            candidates.append(Candidate(
                symbol=sym,
                timestamp=bar["timestamp"].isoformat(timespec="minutes"),
                entry_reference=close,
                target=close * (1.0 + TP_PCT),
                stop_reference=close * (1.0 - SL_PCT),
                score=score,
                relative_strength=relative_strength,
                session_return=session_return,
                distance_from_high=distance_from_high,
                rationale=rationale,
            ))

    candidates.sort(key=lambda c: (-c.score, c.symbol))
    selected = None
    reason = "no candidate passed breakout, market, relative-strength, and anti-chasing filters"
    if candidates:
        if len(candidates) > 1 and candidates[0].score - candidates[1].score < MIN_WINNER_MARGIN:
            reason = "top candidates too close to establish a clear winner"
        else:
            selected = asdict(candidates[0])
            reason = "one clear paper winner"
    return {
        "rule_version": rule_version,
        "status": "PAPER_CANDIDATE" if selected else "NO_TRADE",
        "reason": reason,
        "candidate": selected,
        "candidate_count": len(candidates),
        "as_of": as_of.isoformat(),
        "market": market,
        "data_quality": quality,
        "target_pct": TP_PCT,
        "stop_pct": SL_PCT,
        "volume": "unavailable; not used",
        "order_flow": "unavailable",
    }
