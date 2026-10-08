"""Causal intraday candidate generation from timestamped one-minute OHLC.

This is a paper-research engine. It preserves chronology, builds only closed
five-minute bars, rejects stale or malformed data, applies a broad-market gate,
and returns at most one ranked long candidate. It never places an order and
does not use volume because the captured feed does not contain it.
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
                  as_of: datetime, quality: dict) -> dict:
    """Return one causal paper candidate or NO TRADE for this scan time."""
    day = as_of.date()
    if quality.get("quality") != "verified":
        return {"rule_version": RULE_VERSION, "status": "NO_TRADE",
                "reason": "market data quality gate failed", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}
    if not is_trading_day(day):
        return {"rule_version": RULE_VERSION, "status": "NO_TRADE",
                "reason": "not a PSX trading day", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}

    session_open = datetime.combine(day, time(*open_time(day)), tzinfo=as_of.tzinfo)
    elapsed = (as_of - session_open).total_seconds() / 60
    if elapsed < MIN_OBSERVATION_TIME:
        return {"rule_version": RULE_VERSION, "status": "NO_TRADE",
                "reason": "market observation period not complete", "candidate": None,
                "as_of": as_of.isoformat(), "data_quality": quality}

    five: dict[str, list[dict]] = {}
    returns: dict[str, float] = {}
    for sym in universe:
        rows = bars_by_symbol.get(sym, [])
        bars = aggregate_5m(rows, session_open, as_of)
        if len(bars) < OPENING_RANGE_BARS + 1:
            continue
        five[sym] = bars
        first_open = bars[0]["open"]
        if first_open > 0:
            returns[sym] = bars[-1]["close"] / first_open - 1.0

    coverage = len(returns) / max(len(universe), 1)
    if coverage < MIN_COVERAGE:
        return {"rule_version": RULE_VERSION, "status": "NO_TRADE",
                "reason": "insufficient complete five-minute coverage",
                "candidate": None, "as_of": as_of.isoformat(),
                "market": {"coverage": coverage}, "data_quality": quality}

    median_return = float(np.median(list(returns.values())))
    advancer_share = sum(v > 0 for v in returns.values()) / len(returns)
    market = {"proxy": "cross-sectional median and advancer share, not official KMIALL index",
              "median_return": median_return, "advancer_share": advancer_share,
              "coverage": coverage}
    if median_return < 0.001 or advancer_share < 0.55:
        return {"rule_version": RULE_VERSION, "status": "NO_TRADE",
                "reason": "broad KMIALL proxy is not supportive",
                "candidate": None, "as_of": as_of.isoformat(),
                "market": market, "data_quality": quality}

    candidates: list[Candidate] = []
    for sym, series in five.items():
        opening = series[:OPENING_RANGE_BARS]
        later = series[OPENING_RANGE_BARS:]
        opening_high = max(b["high"] for b in opening)
        prior_close = opening[-1]["close"]
        for bar in later:
            close = bar["close"]
            if prior_close <= opening_high < close:
                first_open = series[0]["open"]
                session_return = close / first_open - 1.0
                high_so_far = max(b["high"] for b in series
                                  if b["timestamp"] <= bar["timestamp"])
                distance_from_high = high_so_far / close - 1.0
                relative_strength = session_return - median_return
                if (0 < session_return <= MAX_RETURN_FROM_OPEN
                        and distance_from_high <= MAX_DISTANCE_FROM_HIGH
                        and relative_strength >= MIN_RELATIVE_STRENGTH):
                    # Higher relative strength ranks first. This rule and its
                    # thresholds are frozen before forward validation.
                    score = relative_strength
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
                        rationale=("close broke the first 30-minute range; "
                                   "market breadth supportive; relative strength "
                                   "positive; extension within anti-chasing limits"),
                    ))
                break
            prior_close = close

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
        "rule_version": RULE_VERSION,
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
