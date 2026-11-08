#!/usr/bin/env python3
"""CLOUD-ONLY intraday study: the current bot plus nine KMIALL long rules.

Owner request 2026-11-08: backtest the current intraday signal bot and ten
additional long strategies on the last three years of KMIALLSHR data, and
report the results without changing the live bot.

Data honesty first (SO-3). This repository has three years of DAILY bars and
only the captured intraday sessions in the R2 band store. There is no
three-year 5m/15m archive, so a three-year intraday result cannot be produced
without inventing bars. This script therefore replays every stored session it
can fetch, names the actual session set in the report, and never pads it.

What is replayed, per stored session:

  * the current bot's one minute Kalman flip arm, with the owner's fixed
    +2.00% target and -1.00% stop (src/signals/kalman_trend.py). The later
    four-frame VWAP pullback arm needs a 40-day 1D VWAP history that the band
    store does not hold, so it is reported as not evaluable rather than
    approximated;
  * strategies 1 to 9 from the owner's specification, on strict completed
    5m, 15m and 1h buckets. A bucket with a missing minute is a hole, never
    a padded candle;
  * strategy 10 is NOT tested: the tape carries best bid/ask only, not the
    top five levels or a reliable aggressor sequence, and the script refuses
    to fabricate either.

Common law for every tested strategy: long only, one trade per strategy per
day, entry at the first one minute open after the signal bar closes, target
+2.00%, stop -1.00%, stop wins a same-bar tie, exit at the band close, costs
and slippage through config.net_return (both sides plus 15% CGT on gains).

Run only in GitHub Actions. The guard refuses any other host.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src import config  # noqa: E402
from src.data import band_state, tape_bars  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI, band_bounds, is_trading_day, session_bands,
)
from src.signals.kalman_trend import filter_series  # noqa: E402
from src.signals.mtf_vwap import Frame, completed  # noqa: E402

MIN5 = timedelta(minutes=5)
MIN15 = timedelta(minutes=15)
MIN60 = timedelta(minutes=60)
MIN1 = timedelta(minutes=1)

#: The same execution-safety floor the live scanner uses, applied to traded
#: value accumulated up to the decision time (never the whole day, which
#: would be look-ahead).
MIN_TURNOVER = config.MIN_SESSION_TRADED_VALUE
MIN_PRICE = config.MIN_PRICE

#: Relative volume needs the same 5m slot on prior sessions. The spec asks
#: for 20; the store rarely holds 20, so five is the minimum that can speak
#: and the report states how many sessions were actually used.
MIN_PRIOR_SESSIONS = 5
MAX_PRIOR_SESSIONS = 20

TARGET = config.TARGET_PCT
STOP = config.KALMAN_STOP_PCT

STRATEGY_NAMES = (
    "current_kalman_flip",
    "1_ema_rsi_pullback",
    "2_vwap_reclaim_relvol",
    "3_kalman_vwap_rs",
    "4_donchian_atr_breakout",
    "5_supertrend_adx_volume",
    "6_bollinger_squeeze",
    "7_rsi_ema50_reversal",
    "8_opening_range_vwap",
    "9_relative_strength_rotation",
    "10_order_book_imbalance",
)

STRATEGY_LABELS = {
    "current_kalman_flip": "Current bot: 1m Kalman Trend fresh flip",
    "1_ema_rsi_pullback": "EMA 20/50 + RSI pullback",
    "2_vwap_reclaim_relvol": "VWAP reclaim + relative volume",
    "3_kalman_vwap_rs": "Kalman 1H/15M + VWAP + relative strength",
    "4_donchian_atr_breakout": "Donchian breakout + ATR + relative volume",
    "5_supertrend_adx_volume": "Supertrend + ADX + volume expansion",
    "6_bollinger_squeeze": "Bollinger squeeze + volume breakout",
    "7_rsi_ema50_reversal": "RSI reversal + EMA 50 support",
    "8_opening_range_vwap": "Opening range breakout + VWAP",
    "9_relative_strength_rotation": "Relative strength rotation",
    "10_order_book_imbalance": "Order book imbalance + VWAP + intensity",
}

#: Prior-session 5m volumes, keyed by (symbol, band index, slot). Filled only
#: after a session has been scored, so a day can never read its own future.
_prior_volumes: dict[tuple[str, int, int], list[float]] = defaultdict(list)

STRATEGY_NOTES = {
    "current_kalman_flip": (
        "Replays the live candidate's one minute fresh-flip arm with the "
        "owner's fixed +2%/-1% law. The four-frame VWAP pullback arm is not "
        "evaluated: its 1D frame needs 40 completed daily bars and the band "
        "store holds only the captured sessions."),
    "1_ema_rsi_pullback": (
        "The 40-50 RSI pullback is the minimum 15m RSI over the last four "
        "bars, followed by a cross above 50. The optional 1H EMA50 filter is "
        "not added as a separate gate."),
    "2_vwap_reclaim_relvol": (
        "The reclaim bar is a 5m close above session VWAP after the prior 5m "
        "close was at or below it; the following 5m bar closing above VWAP is "
        "the hold. A separate retest is not required."),
    "3_kalman_vwap_rs": (
        "The market leg of RS20 is the equal-weight mean return of the "
        "captured KMIALL symbols, not the KMIALLSHR index level. The 15M and "
        "1H Kalman filters use the same Q/R/threshold as the live 1m filter."),
    "4_donchian_atr_breakout": (
        "ATR must expand against its prior 20-bar average. The suggested "
        "0.25%-0.90% normalized ATR band is not used as a hard gate, as the "
        "specification says it is a research range."),
    "5_supertrend_adx_volume": (
        "The continuation variant is tested: any bullish Supertrend with "
        "ADX above 20, +DI above -DI and the volume floor qualifies. The "
        "separate 'controlled pullback' qualifier is not enforced."),
    "6_bollinger_squeeze": (
        "Squeeze is 15m band width below its own 20th percentile over the "
        "previous 100 observations. '1H not bearish' means 1H close above "
        "the 1H EMA50."),
    "7_rsi_ema50_reversal": (
        "The 15m RSI must have touched 30-45 in the last five bars and cross "
        "back above 45. The 1H positive trend is 1H close above the 1H EMA50."),
    "8_opening_range_vwap": (
        "The opening range is the first complete 15m bar at the band open. "
        "A session whose tape starts after the open has no opening range and "
        "cannot signal that day."),
    "9_relative_strength_rotation": (
        "RS8 and 1H RS use the equal-weight mean of the captured KMIALL "
        "symbols as the market. Standardisation is cross-sectional at each "
        "15m timestamp, and the next 5m bar must close above the prior high."),
}


def _day_from_name(path: Path) -> date | None:
    for token in path.stem.split("_"):
        if token.isdigit() and len(token) == 8:
            try:
                return datetime.strptime(token, "%Y%m%d").date()
            except ValueError:
                return None
    return None


def _rsi(close: pd.Series, period: int = 14) -> np.ndarray:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out = out.where(avg_loss > 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out.to_numpy(dtype=float)


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         period: int = 14) -> np.ndarray:
    prior = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prior),
                                           np.abs(low - prior)))
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()


def _adx(high: np.ndarray, low: np.ndarray, close: np.ndarray,
         period: int = 14) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    up = np.diff(high, prepend=high[0])
    down = -np.diff(low, prepend=low[0])
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    atr = _atr(high, low, close, period)
    atr_safe = np.where(atr > 0, atr, np.nan)
    pdi = 100.0 * pd.Series(plus_dm).ewm(alpha=1.0 / period,
                                        adjust=False).mean().to_numpy() / atr_safe
    ndi = 100.0 * pd.Series(minus_dm).ewm(alpha=1.0 / period,
                                         adjust=False).mean().to_numpy() / atr_safe
    diff = np.abs(pdi - ndi)
    denom = np.where((pdi + ndi) > 0, pdi + ndi, np.nan)
    dx = 100.0 * diff / denom
    adx = pd.Series(dx).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()
    return adx, pdi, ndi


def _supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                period: int = 10, multiplier: float = 3.0
                ) -> tuple[np.ndarray, np.ndarray]:
    atr = _atr(high, low, close, period)
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    n = len(close)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)
    if n == 0:
        return trend, final_lower
    final_upper[0] = upper[0]
    final_lower[0] = lower[0]
    trend[0] = 1
    for i in range(1, n):
        if not math.isfinite(atr[i]):
            final_upper[i] = final_upper[i - 1]
            final_lower[i] = final_lower[i - 1]
            trend[i] = trend[i - 1]
            continue
        final_upper[i] = (upper[i] if (upper[i] < final_upper[i - 1]
                                       or close[i - 1] > final_upper[i - 1])
                          else final_upper[i - 1])
        final_lower[i] = (lower[i] if (lower[i] > final_lower[i - 1]
                                       or close[i - 1] < final_lower[i - 1])
                          else final_lower[i - 1])
        if trend[i - 1] == 1:
            trend[i] = -1 if close[i] < final_lower[i] else 1
        else:
            trend[i] = 1 if close[i] > final_upper[i] else -1
    return trend, final_lower


def _kalman_states(frames: list[Frame]) -> np.ndarray:
    closes = [f.close for f in frames]
    if len(closes) < 2:
        return np.zeros(len(closes), dtype=int)
    trace = filter_series(closes, config.KALMAN_Q, config.KALMAN_R,
                          config.KALMAN_FLIP_THRESHOLD)
    return np.array([row["state"] for row in trace], dtype=int)


def _indicators5(frames: list[Frame]) -> dict:
    close = np.array([f.close for f in frames], dtype=float)
    high = np.array([f.high for f in frames], dtype=float)
    low = np.array([f.low for f in frames], dtype=float)
    volume = np.array([f.volume for f in frames], dtype=float)
    return {
        "close": close, "high": high, "low": low, "volume": volume,
        "rsi": _rsi(pd.Series(close), 14),
        "completion": [f.timestamp + MIN5 for f in frames],
    }


def _indicators15(frames: list[Frame]) -> dict:
    close_s = pd.Series([f.close for f in frames], dtype=float)
    high = np.array([f.high for f in frames], dtype=float)
    low = np.array([f.low for f in frames], dtype=float)
    close = close_s.to_numpy()
    volume = np.array([f.volume for f in frames], dtype=float)
    ema20 = close_s.ewm(span=20, adjust=False).mean().to_numpy()
    ema50 = close_s.ewm(span=50, adjust=False).mean().to_numpy()
    atr = _atr(high, low, close, 14)
    upper = high.copy()
    donchian = pd.Series(upper).rolling(20).max().shift(1).to_numpy()
    mid = close_s.rolling(20).mean()
    std = close_s.rolling(20).std(ddof=0)
    bb_upper = (mid + 2.0 * std).to_numpy()
    width = ((mid + 2.0 * std) - (mid - 2.0 * std)) / mid.replace(0.0, np.nan)
    width_np = width.to_numpy()
    q20 = pd.Series(width_np).shift(1).rolling(100).quantile(0.20).to_numpy()
    atr_avg = pd.Series(atr).shift(1).rolling(20).mean().to_numpy()
    adx, pdi, ndi = _adx(high, low, close, 14)
    st_trend, st_line = _supertrend(high, low, close, 10, 3.0)
    return {
        "close": close, "high": high, "low": low, "volume": volume,
        "ema20": ema20, "ema50": ema50,
        "rsi": _rsi(close_s, 14),
        "atr": atr, "atr_avg": atr_avg,
        "donchian": donchian, "bb_upper": bb_upper,
        "bb_width": width_np, "bb_q20": q20,
        "adx": adx, "pdi": pdi, "ndi": ndi,
        "st_trend": st_trend, "st_line": st_line,
        "kalman": _kalman_states(frames),
        "completion": [f.timestamp + MIN15 for f in frames],
    }


def _indicators60(frames: list[Frame]) -> dict:
    close_s = pd.Series([f.close for f in frames], dtype=float)
    return {
        "close": close_s.to_numpy(),
        "ema50": close_s.ewm(span=50, adjust=False).mean().to_numpy(),
        "kalman": _kalman_states(frames),
        "completion": [f.timestamp + MIN60 for f in frames],
    }


def _vwap(frames: list[Frame]) -> list[float | None]:
    total_value = 0.0
    total_volume = 0.0
    out: list[float | None] = []
    for f in frames:
        if f.volume > 0:
            total_volume += f.volume
            total_value += ((f.high + f.low + f.close) / 3.0) * f.volume
        out.append(total_value / total_volume if total_volume > 0 else None)
    return out


def _turnover(frames: list[Frame]) -> np.ndarray:
    out = []
    running = 0.0
    for f in frames:
        running += f.close * f.volume
        out.append(running)
    return np.array(out, dtype=float)


def _latest_index(ind: dict, completion: datetime,
                  band_open: datetime, require_band: bool) -> int | None:
    stamps = ind["completion"]
    index = bisect.bisect_right(stamps, completion) - 1
    if index < 0:
        return None
    if require_band and stamps[index] - MIN15 < band_open:
        return None
    return index


def _latest_index60(ind: dict, completion: datetime) -> int | None:
    index = bisect.bisect_right(ind["completion"], completion) - 1
    return index if index >= 0 else None


def _prev_local(band: dict, sym: str, t5: datetime, j: int) -> int | None:
    """The previous 5m bar, only when it is the immediately preceding slot."""
    if j <= 0:
        return None
    frames = band["f5"][sym]
    if frames[j - 1].timestamp != t5 - MIN5:
        return None
    return j - 1


def _simulate(band: dict, sym: str, completion: datetime,
              max_entry: float | None = None) -> dict | None:
    rows = band["rows"].get(sym) or []
    if not rows:
        return None
    stamps = [bar.timestamp for bar in rows]
    index = bisect.bisect_left(stamps, completion)
    if index >= len(rows):
        return None
    entry_bar = rows[index]
    if entry_bar.timestamp + MIN5 > band["close"]:
        return None
    entry = float(entry_bar.open)
    if entry <= 0 or not math.isfinite(entry):
        return None
    if max_entry is not None and entry > max_entry:
        return None
    target = entry * (1.0 + TARGET)
    stop = entry * (1.0 - STOP)
    exit_price = None
    exit_time = None
    reason = None
    for bar in rows[index + 1:]:
        if bar.timestamp >= band["close"]:
            break
        if bar.open <= stop:
            exit_price, exit_time, reason = bar.open, bar.timestamp, "stop_gap"
            break
        if bar.open >= target:
            exit_price, exit_time, reason = bar.open, bar.timestamp, "target_gap"
            break
        if bar.low <= stop and bar.high >= target:
            exit_price, exit_time, reason = stop, bar.timestamp, "stop"
            break
        if bar.low <= stop:
            exit_price, exit_time, reason = stop, bar.timestamp, "stop"
            break
        if bar.high >= target:
            exit_price, exit_time, reason = target, bar.timestamp, "target"
            break
    if exit_price is None:
        last = rows[-1]
        exit_price = float(last.close)
        exit_time = last.timestamp + MIN1
        reason = ("session_end" if exit_time >= band["close"] - MIN1
                  else "tape_end")
    if exit_time is None or exit_time <= entry_bar.timestamp:
        return None
    gross = (float(exit_price) / entry) - 1.0
    net = config.net_return(gross)
    if net is None:
        return None
    return {
        "symbol": sym,
        "signal_time": completion.isoformat(),
        "entry_time": entry_bar.timestamp.isoformat(),
        "entry": round(entry, 4),
        "target": round(target, 4),
        "stop": round(stop, 4),
        "exit_time": exit_time.isoformat(),
        "exit": round(float(exit_price), 4),
        "exit_reason": reason,
        "gross": round(gross, 6),
        "net": net,
        "hold_minutes": round((exit_time - entry_bar.timestamp).total_seconds()
                              / 60.0, 2),
    }


def _metrics(trades: list[dict]) -> dict:
    nets = [float(row["net"]) for row in trades if row.get("net") is not None]
    if not nets:
        return {"trades": 0}
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value <= 0]
    equity = np.concatenate(([0.0], np.cumsum(nets)))
    peak = np.maximum.accumulate(equity)
    drawdown = equity - peak
    reasons = defaultdict(int)
    for row in trades:
        reasons[row.get("exit_reason") or "unknown"] += 1
    return {
        "trades": len(nets),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(nets), 4),
        "expectancy": round(statistics.mean(nets), 6),
        "median": round(statistics.median(nets), 6),
        "total_net": round(sum(nets), 6),
        "avg_win": round(statistics.mean(wins), 6) if wins else None,
        "avg_loss": round(statistics.mean(losses), 6) if losses else None,
        "profit_factor": (round(sum(wins) / abs(sum(losses)), 4)
                          if losses and sum(losses) != 0 else None),
        "best": round(max(nets), 6),
        "worst": round(min(nets), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "avg_hold_minutes": round(statistics.mean(
            [float(row.get("hold_minutes") or 0.0) for row in trades]), 2),
        "exit_reasons": dict(sorted(reasons.items())),
    }


def _build_day(path: Path, day: date, universe: set[str]) -> dict:
    end = datetime.combine(day, datetime.max.time(), tzinfo=KARACHI)
    tape = tape_bars.build(path, universe, end, day=day)
    bands = []
    for band_index, band_def in enumerate(session_bands(day)):
        opens, closes = band_bounds(day, band_def)
        band = {
            "day": day, "index": band_index, "open": opens, "close": closes,
            "rows": {}, "f5": {}, "f15": {}, "f60": {},
            "vwap5": {}, "vwap15": {},
            "turnover5": {}, "turnover15": {},
            "ts5": {}, "ts15": {}, "at5": {},
            "slots": [], "or_high": {}, "or_low": {},
        }
        for sym in universe:
            raw = tape.bars.get(sym) or []
            rows = [bar for bar in raw
                    if bar.timestamp >= opens
                    and bar.timestamp + MIN1 <= closes]
            if len(rows) < 20:
                continue
            f5 = completed(rows, 5, opens, closes)
            f15 = completed(rows, 15, opens, closes)
            f60 = completed(rows, 60, opens, closes)
            if not f5:
                continue
            band["rows"][sym] = rows
            band["f5"][sym] = f5
            band["f15"][sym] = f15
            band["f60"][sym] = f60
            band["vwap5"][sym] = _vwap(f5)
            band["vwap15"][sym] = _vwap(f15)
            band["turnover5"][sym] = _turnover(f5)
            band["turnover15"][sym] = _turnover(f15)
            band["ts5"][sym] = {frame.timestamp: i for i, frame in enumerate(f5)}
            band["ts15"][sym] = {frame.timestamp: i
                                 for i, frame in enumerate(f15)}
            for i, frame in enumerate(f5):
                band["at5"].setdefault(frame.timestamp, []).append((sym, i))
            if f15 and f15[0].timestamp == opens:
                band["or_high"][sym] = f15[0].high
                band["or_low"][sym] = f15[0].low
        band["slots"] = sorted({frame.timestamp for frames in band["f5"].values()
                                for frame in frames})
        bands.append((band, tape))
    return {"day": day, "path": path, "tape": tape, "bands": bands}


def _append_history(day_data: dict, histories: dict, offsets: dict) -> None:
    for band, _tape in day_data["bands"]:
        off5, off15, off60 = {}, {}, {}
        for sym, frames in band["f5"].items():
            off5[sym] = len(histories["5"][sym])
            histories["5"][sym].extend(frames)
            offsets[(day_data["day"], band["index"], sym, "5")] = off5[sym]
        for sym, frames in band["f15"].items():
            off15[sym] = len(histories["15"][sym])
            histories["15"][sym].extend(frames)
            offsets[(day_data["day"], band["index"], sym, "15")] = off15[sym]
        for sym, frames in band["f60"].items():
            off60[sym] = len(histories["60"][sym])
            histories["60"][sym].extend(frames)
            offsets[(day_data["day"], band["index"], sym, "60")] = off60[sym]
        band["off5"], band["off15"], band["off60"] = off5, off15, off60


def _append_relvol(day_data: dict) -> None:
    for band, _tape in day_data["bands"]:
        for sym, frames in band["f5"].items():
            for frame in frames:
                slot = int((frame.timestamp - band["open"]).total_seconds() // 300)
                _prior_volumes[(sym, band["index"], slot)].append(frame.volume)


def _relvol(band: dict, sym: str, j: int) -> float | None:
    """Volume of this 5m slot against the same slot on prior sessions."""
    frame = band["f5"][sym][j]
    slot = int((frame.timestamp - band["open"]).total_seconds() // 300)
    prior = _prior_volumes.get((sym, band["index"], slot), [])[-MAX_PRIOR_SESSIONS:]
    if len(prior) < MIN_PRIOR_SESSIONS:
        return None
    average = sum(prior) / len(prior)
    return frame.volume / average if average > 0 else None


def _rs_table(day_data: dict, histories: dict, ind15: dict) -> dict:
    table: dict[str, dict[datetime, dict]] = defaultdict(dict)
    for band, _tape in day_data["bands"]:
        for sym, frames in band["f15"].items():
            off = band["off15"].get(sym)
            if off is None:
                continue
            values = ind15[sym]
            close = values["close"]
            for local, frame in enumerate(frames):
                g = off + local
                entry = {
                    "close": float(close[g]),
                    "ema20": float(values["ema20"][g]),
                    "turnover": float(band["turnover15"][sym][local]),
                }
                for look, key in ((4, "ret4"), (8, "ret8"), (20, "ret20")):
                    entry[key] = (float(close[g] / close[g - look] - 1.0)
                                  if g >= look and close[g - look] > 0 else None)
                table[sym][frame.timestamp] = entry
    for key in ("ret4", "ret8", "ret20"):
        means: dict[datetime, list[float]] = defaultdict(list)
        for sym, rows in table.items():
            for timestamp, entry in rows.items():
                value = entry[key]
                if value is not None:
                    means[timestamp].append(value)
        average = {timestamp: sum(values) / len(values)
                   for timestamp, values in means.items()}
        for rows in table.values():
            for timestamp, entry in rows.items():
                value = entry[key]
                entry["rs_" + key] = (value - average[timestamp]
                                      if value is not None else None)
    return table


def _evaluate(day_data: dict, histories: dict, ind5: dict, ind15: dict,
              ind60: dict, rs: dict) -> list[dict]:
    trades: list[dict] = []
    taken = {name: False for name in STRATEGY_NAMES}
    for band, _tape in day_data["bands"]:
        for t5 in band["slots"]:
            completion = t5 + MIN5
            if completion + MIN5 > band["close"]:
                continue
            candidates: dict[str, list[dict]] = defaultdict(list)
            for sym, j in band["at5"].get(t5, []):
                if all(taken[name] for name in STRATEGY_NAMES
                       if name != "10_order_book_imbalance"):
                    break
                offsets = band["off5"].get(sym)
                if offsets is None or sym not in ind5 or sym not in ind15:
                    continue
                g5 = offsets + j
                c5 = float(ind5[sym]["close"][g5])
                h5 = float(ind5[sym]["high"][g5])
                l5 = float(ind5[sym]["low"][g5])
                rsi5 = float(ind5[sym]["rsi"][g5])
                vwap = band["vwap5"][sym][j]
                turnover = float(band["turnover5"][sym][j])
                if c5 < MIN_PRICE or turnover < MIN_TURNOVER:
                    continue
                prev = _prev_local(band, sym, t5, j)
                prev_high = (float(ind5[sym]["high"][g5 - 1])
                             if prev is not None else None)
                prev_close = (float(ind5[sym]["close"][g5 - 1])
                              if prev is not None else None)
                prev_low = (float(ind5[sym]["low"][g5 - 1])
                            if prev is not None else None)
                prev2_close = (float(ind5[sym]["close"][g5 - 2])
                               if prev is not None and prev > 0 else None)
                relvol = _relvol(band, sym, j)
                relvol_prev = (_relvol(band, sym, prev)
                                if prev is not None else None)
                i15 = _latest_index(ind15[sym], completion, band["open"], True)
                i60 = (_latest_index60(ind60[sym], completion)
                       if sym in ind60 else None)
                if i15 is not None:
                    g15 = i15
                    c15 = float(ind15[sym]["close"][g15])
                    h15 = float(ind15[sym]["high"][g15])
                    l15 = float(ind15[sym]["low"][g15])
                    ema20 = float(ind15[sym]["ema20"][g15])
                    ema50 = float(ind15[sym]["ema50"][g15])
                    rsi15 = float(ind15[sym]["rsi"][g15])
                    rsi15_prev = (float(ind15[sym]["rsi"][g15 - 1])
                                  if g15 >= 1 else float("nan"))
                    atr15 = float(ind15[sym]["atr"][g15])
                    atr_avg = float(ind15[sym]["atr_avg"][g15])
                    donchian = float(ind15[sym]["donchian"][g15])
                    bb_upper = float(ind15[sym]["bb_upper"][g15])
                    bb_width = float(ind15[sym]["bb_width"][g15])
                    bb_q20 = float(ind15[sym]["bb_q20"][g15])
                    adx = float(ind15[sym]["adx"][g15])
                    pdi = float(ind15[sym]["pdi"][g15])
                    ndi = float(ind15[sym]["ndi"][g15])
                    st_trend = int(ind15[sym]["st_trend"][g15])
                    kal15 = int(ind15[sym]["kalman"][g15])
                    t15 = ind15[sym]["completion"][g15] - MIN15
                    rsi_recent1 = (min(float(ind15[sym]["rsi"][g])
                                       for g in range(g15 - 3, g15 + 1))
                                   if g15 >= 3 else None)
                    rsi_recent7 = (min(float(ind15[sym]["rsi"][g])
                                       for g in range(g15 - 4, g15 + 1))
                                   if g15 >= 4 else None)
                else:
                    continue
                c60 = ema50_60 = None
                kal60 = None
                if i60 is not None:
                    c60 = float(ind60[sym]["close"][i60])
                    ema50_60 = float(ind60[sym]["ema50"][i60])
                    kal60 = int(ind60[sym]["kalman"][i60])
                rs_row = rs.get(sym, {}).get(t15)
                rs20 = rs_row.get("rs_ret20") if rs_row else None
                score_base = c5

                # Strategy 1: EMA 20/50 trend, RSI pullback, 5m trigger.
                if (not taken["1_ema_rsi_pullback"]
                        and math.isfinite(ema20) and math.isfinite(ema50)
                        and ema20 > ema50
                        and l15 <= ema20 * 1.005
                        and c15 >= ema50 * 0.998
                        and rsi15 > 50.0 and rsi15_prev <= 50.0
                        and math.isfinite(rsi15_prev)
                        and rsi_recent1 is not None
                        and 40.0 <= rsi_recent1 <= 50.0
                        and prev_high is not None and c5 > prev_high):
                    score = (rsi15 - 50.0) + 100.0 * (ema20 / ema50 - 1.0)
                    candidates["1_ema_rsi_pullback"].append(
                        {"sym": sym, "score": score, "price": score_base})

                # Strategy 2: 5m VWAP reclaim, volume, then the next bar holds.
                vwap_prev = (band["vwap5"][sym][prev]
                             if prev is not None else None)
                vwap_prev2 = (band["vwap5"][sym][prev - 1]
                              if prev is not None and prev >= 1 else None)
                if (not taken["2_vwap_reclaim_relvol"]
                        and vwap is not None and vwap_prev is not None
                        and vwap_prev2 is not None and prev is not None
                        and prev >= 1
                        and prev_close is not None and prev_close > 0
                        and prev2_close is not None and prev2_close > 0
                        and prev_close > vwap_prev
                        and prev2_close <= vwap_prev2
                        and c5 > vwap
                        and relvol_prev is not None and relvol_prev >= 1.5
                        and 50.0 <= float(ind5[sym]["rsi"][g5 - 1]) <= 70.0):
                    candidates["2_vwap_reclaim_relvol"].append(
                        {"sym": sym, "score": relvol_prev or 0.0,
                         "price": score_base})

                # Strategy 3: 1H and 15M Kalman up, above VWAP, RS20 positive.
                if (not taken["3_kalman_vwap_rs"]
                        and kal60 == 1 and kal15 == 1
                        and vwap is not None and c5 > vwap
                        and rs20 is not None and rs20 > 0
                        and prev_high is not None and c5 > prev_high):
                    score = 100.0 * rs20 + 100.0 * (c5 / vwap - 1.0)
                    candidates["3_kalman_vwap_rs"].append(
                        {"sym": sym, "score": score, "price": score_base})

                # Strategy 4: 15m Donchian breakout with ATR expansion.
                if (not taken["4_donchian_atr_breakout"]
                        and math.isfinite(donchian) and donchian > 0
                        and c15 > donchian
                        and c15 <= donchian * 1.0075
                        and c60 is not None and ema50_60 is not None
                        and c60 > ema50_60
                        and relvol is not None and relvol >= 1.5
                        and atr15 > atr_avg
                        and c5 > donchian):
                    score = (relvol or 0.0) + (atr15 / atr_avg
                                               if atr_avg > 0 else 0.0)
                    candidates["4_donchian_atr_breakout"].append(
                        {"sym": sym, "score": score, "price": score_base,
                         "max_entry": donchian * 1.0075})

                # Strategy 5: Supertrend direction, ADX strength, volume.
                if (not taken["5_supertrend_adx_volume"]
                        and st_trend == 1 and adx > 20.0 and pdi > ndi
                        and relvol is not None and relvol >= 1.3
                        and prev_high is not None and c5 > prev_high):
                    candidates["5_supertrend_adx_volume"].append(
                        {"sym": sym, "score": adx, "price": score_base})

                # Strategy 6: squeeze, close above upper band, volume.
                if (not taken["6_bollinger_squeeze"]
                        and math.isfinite(bb_q20) and bb_width < bb_q20
                        and math.isfinite(bb_upper) and c15 > bb_upper
                        and c15 <= bb_upper * 1.01
                        and relvol is not None and relvol >= 1.5
                        and c60 is not None and ema50_60 is not None
                        and c60 > ema50_60
                        and c5 > bb_upper):
                    candidates["6_bollinger_squeeze"].append(
                        {"sym": sym, "score": relvol, "price": score_base,
                         "max_entry": bb_upper * 1.01})

                # Strategy 7: 1H up, RSI recovery at EMA 50, higher low.
                if (not taken["7_rsi_ema50_reversal"]
                        and c60 is not None and ema50_60 is not None
                        and c60 > ema50_60
                        and math.isfinite(ema50) and ema50 > 0
                        and l15 <= ema50 * 1.005
                        and rsi_recent7 is not None
                        and 30.0 <= rsi_recent7 <= 45.0
                        and rsi15 > 45.0 and rsi15_prev <= 45.0
                        and math.isfinite(rsi15_prev)
                        and prev_high is not None and prev_low is not None
                        and l5 > prev_low and c5 > prev_high):
                    candidates["7_rsi_ema50_reversal"].append(
                        {"sym": sym, "score": rsi15 - 45.0, "price": score_base})

                # Strategy 8: opening range high, above VWAP, volume.
                or_high = band["or_high"].get(sym)
                if (not taken["8_opening_range_vwap"]
                        and or_high is not None and or_high > 0
                        and c5 > or_high and vwap is not None and c5 > vwap
                        and relvol is not None and relvol >= 1.5):
                    candidates["8_opening_range_vwap"].append(
                        {"sym": sym, "score": relvol, "price": score_base,
                         "max_entry": or_high * 1.005})

            for name in STRATEGY_NAMES:
                if name in ("current_kalman_flip", "9_relative_strength_rotation",
                            "10_order_book_imbalance"):
                    continue
                if taken[name] or not candidates[name]:
                    continue
                candidates[name].sort(key=lambda row: (-row["score"], row["sym"]))
                for candidate in candidates[name]:
                    trade = _simulate(band, candidate["sym"], completion,
                                      candidate.get("max_entry"))
                    if trade is None:
                        continue
                    trade.update({"strategy": name, "day": band["day"].isoformat(),
                                  "score": round(candidate["score"], 4)})
                    trades.append(trade)
                    taken[name] = True
                    break

            # Strategy 9: rank the cross-section at each completed 15m bar,
            # then wait for the next 5m bar to confirm continuation.
            if (not taken["9_relative_strength_rotation"]
                    and int((completion - band["open"]).total_seconds()) % 900 == 0):
                t15 = completion - MIN15
                pool = []
                for sym, rows in rs.items():
                    row = rows.get(t15)
                    if not row:
                        continue
                    if sym not in band["ts5"] or sym not in band["off5"]:
                        continue
                    if (row.get("rs_ret4") is None or row.get("rs_ret8") is None
                            or not math.isfinite(row["ema20"])
                            or row["close"] <= row["ema20"]
                            or row["turnover"] < MIN_TURNOVER):
                        continue
                    j2 = band["ts5"].get(sym, {}).get(completion)
                    if j2 is None or j2 <= 0:
                        continue
                    prev_j = band["ts5"][sym].get(completion - MIN5)
                    if prev_j is None or prev_j != j2 - 1:
                        continue
                    close2 = float(ind5[sym]["close"][band["off5"][sym] + j2])
                    high_prev = float(ind5[sym]["high"][band["off5"][sym] + prev_j])
                    if close2 <= high_prev:
                        continue
                    pool.append({"sym": sym, "row": row, "close": close2})
                if len(pool) >= 3:
                    r8 = np.array([row["row"]["rs_ret8"] for row in pool])
                    r4 = np.array([row["row"]["rs_ret4"] for row in pool])
                    std8 = float(r8.std())
                    std4 = float(r4.std())
                    if std8 > 0 and std4 > 0:
                        for row in pool:
                            z8 = (row["row"]["rs_ret8"] - float(r8.mean())) / std8
                            z4 = (row["row"]["rs_ret4"] - float(r4.mean())) / std4
                            row["score"] = 0.60 * z8 + 0.40 * z4
                        pool.sort(key=lambda row: (-row["score"], row["sym"]))
                        top = pool[0]
                        trade = _simulate(band, top["sym"], completion + MIN5)
                        if trade is not None:
                            trade.update({"strategy": "9_relative_strength_rotation",
                                          "day": band["day"].isoformat(),
                                          "score": round(float(top["score"]), 4)})
                            trades.append(trade)
                            taken["9_relative_strength_rotation"] = True

    # The current bot's one minute flip arm, across both Friday bands.
    if not taken["current_kalman_flip"]:
        flips = []
        for band, _tape in day_data["bands"]:
            for sym, rows in band["rows"].items():
                start = 0
                for i in range(1, len(rows)):
                    if rows[i].timestamp - rows[i - 1].timestamp != MIN1:
                        start = i
                segment = rows[start:]
                if len(segment) < 20:
                    continue
                closes = [bar.close for bar in segment]
                trace = filter_series(closes, config.KALMAN_Q, config.KALMAN_R,
                                      config.KALMAN_FLIP_THRESHOLD)
                running = 0.0
                for i, bar in enumerate(segment):
                    running += bar.close * bar.volume
                    if not trace[i]["flip_up"] or i < 19:
                        continue
                    signal_time = bar.timestamp + MIN1
                    if signal_time >= band["close"] - timedelta(
                            minutes=config.KALMAN_LAST_ENTRY_MINUTES):
                        continue
                    if bar.close < MIN_PRICE or running < MIN_TURNOVER:
                        continue
                    flips.append({"sym": sym, "score": abs(trace[i]["slope"]),
                                  "time": signal_time, "band": band})
        if flips:
            flips.sort(key=lambda row: (row["time"], -row["score"], row["sym"]))
            top = flips[0]
            trade = _simulate(top["band"], top["sym"], top["time"])
            if trade is not None:
                trade.update({"strategy": "current_kalman_flip",
                              "day": day_data["day"].isoformat(),
                              "score": round(top["score"], 8)})
                trades.append(trade)
    return trades


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/backtest_eleven_intraday.py")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default="data/feed_capture/capture_*.ndjson")
    parser.add_argument("--from-store", type=int, default=0, metavar="DAYS")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trades", type=Path, required=True)
    args = parser.parse_args(argv)

    started = time.perf_counter()
    store_report = {"fetched": [], "absent": []}
    if args.from_store > 0:
        from scripts.kalman_grid_fit import collect_from_store

        store_report = collect_from_store(args.from_store)
        print(f"band store: fetched {len(store_report['fetched'])} session(s)")
        for line in store_report["absent"][:10]:
            print(f"band store: absent {line}")

    from scripts.intraday_pipeline import load_kmiall

    universe = set(load_kmiall())
    pattern = Path(args.input)
    paths = sorted(pattern.parent.glob(pattern.name))
    days = []
    for path in paths:
        day = _day_from_name(path)
        if day is None or not path.is_file() or not is_trading_day(day):
            continue
        if "_synthetic_" in path.name:
            continue
        days.append((day, path))
    if not days:
        print("No captured intraday sessions are available. Nothing is invented "
              "(SO-3). The session tapes live in the R2 band store; dispatch "
              "with --from-store 20 inside Actions.")
        return 1

    histories = {"5": defaultdict(list), "15": defaultdict(list),
                 "60": defaultdict(list)}
    offsets: dict = {}
    coverage = []
    all_trades: list[dict] = []
    scored_days = 0
    for day, path in sorted(days):
        print(f"building {day.isoformat()} from {path.name}", flush=True)
        day_data = _build_day(path, day, universe)
        _append_history(day_data, histories, offsets)
        ind5 = {sym: _indicators5(frames)
                for sym, frames in histories["5"].items() if frames}
        ind15 = {sym: _indicators15(frames)
                 for sym, frames in histories["15"].items() if frames}
        ind60 = {sym: _indicators60(frames)
                 for sym, frames in histories["60"].items() if frames}
        rs = _rs_table(day_data, histories, ind15)
        trades = _evaluate(day_data, histories, ind5, ind15, ind60, rs)
        all_trades.extend(trades)
        _append_relvol(day_data)
        scored_days += 1
        coverage.append({
            "day": day.isoformat(),
            "capture": path.name,
            "characters": path.stat().st_size,
            "symbols_with_bars": day_data["tape"].symbols_with_bars,
            "bars": day_data["tape"].priced_bars + day_data["tape"].carried_bars,
            "carried_share": round(
                day_data["tape"].carried_bars
                / max(1, day_data["tape"].priced_bars
                      + day_data["tape"].carried_bars), 4),
            "first_observation": (day_data["tape"].first_observation.isoformat()
                                  if day_data["tape"].first_observation else None),
            "volume_available": day_data["tape"].volume_available,
        })
        print(f"scored {day_data['day'].isoformat()}: {len(trades)} trade(s)",
              flush=True)

    if not scored_days:
        print("Captures were found but no session held usable bars. Nothing is "
              "scored (SO-3).")
        return 1

    by_strategy = defaultdict(list)
    for trade in all_trades:
        by_strategy[trade["strategy"]].append(trade)

    report_strategies = {}
    for name in STRATEGY_NAMES:
        label = STRATEGY_LABELS[name]
        if name == "10_order_book_imbalance":
            report_strategies[name] = {
                "label": label,
                "status": "not_tested",
                "reason": ("The capture carries last price, best bid, best ask, "
                           "print sizes and print-side evidence, but not the top "
                           "five bid and ask levels or a reliable sequence of "
                           "aggressor-classified trades. OBI and the 60-second "
                           "trade-intensity comparison cannot be computed "
                           "without fabricating the missing book (SO-3)."),
            }
            continue
        rows = by_strategy.get(name, [])
        metrics = _metrics(rows)
        report_strategies[name] = {
            "label": label,
            "status": "tested" if metrics.get("trades") else "tested_no_trades",
            "note": STRATEGY_NOTES.get(name, ""),
            **metrics,
        }

    session_days = [row["day"] for row in coverage]
    report = {
        "generated": datetime.now(KARACHI).isoformat(),
        "study": "eleven_intraday_study_v1",
        "requested_window": "last three years of KMIALLSHR",
        "data_reality": (
            "The repository holds three years of DAILY bars and only the "
            "captured intraday sessions. No three-year 5m/15m archive exists, "
            "so this report is the honest intraday sample: every stored session "
            "that could be fetched, never a padded date range."),
        "law": {
            "direction": "long only",
            "target_pct": TARGET,
            "stop_pct": STOP,
            "entry": "first 1m open after the signal bar closes",
            "exit": "target, stop, or the band close; stop wins a same-bar tie",
            "one_trade_per_strategy_per_day": True,
            "cost_model": {
                "round_trip": round(config.round_trip_cost(), 6),
                "cost_side_bps": config.COST_SIDE_BPS,
                "slippage_side_bps": config.SLIPPAGE_SIDE_BPS,
                "cgt_rate": config.CGT_RATE,
            },
            "selection": ("the first slot with a valid setup; when several "
                          "symbols qualify at that slot the highest setup score "
                          "is taken"),
        },
        "data": {
            "sessions": session_days,
            "session_count": len(session_days),
            "first_session": session_days[0] if session_days else None,
            "last_session": session_days[-1] if session_days else None,
            "universe_symbols": len(universe),
            "store": store_report,
            "coverage": coverage,
        },
        "strategies": report_strategies,
        "trades": sorted(all_trades, key=lambda row: (row["day"],
                                                      row["strategy"],
                                                      row["signal_time"])),
        "limitations": [
            "A three-year intraday backtest is impossible with the data on this "
            "repository; the stored sessions are the whole intraday sample.",
            "The current bot's pullback arm is not tested because the 1D VWAP "
            "frame needs 40 completed daily bars, which the band store does not "
            "hold. Its flip arm is tested.",
            "Strategy 10 is not tested because the feed lacks top-five depth and "
            "a reliable aggressor sequence.",
            "Relative volume and the cross-sectional market return use only the "
            "stored sessions, so early sessions have no signal and the sample "
            "is smaller than the rule assumes.",
            "The 2% target may be larger than one session's typical range; the "
            "exit distribution reports how often it was reached.",
        ],
        "replay_seconds": round(time.perf_counter() - started, 2),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.trades.parent.mkdir(parents=True, exist_ok=True)
    if all_trades:
        frame = pd.DataFrame(all_trades)
        frame.to_csv(args.trades, index=False)
    else:
        args.trades.write_text(
            "strategy,day,symbol,signal_time,entry_time,entry,target,stop,"
            "exit_time,exit,exit_reason,gross,net,hold_minutes,score\n",
            encoding="utf-8")
    print(json.dumps({name: report_strategies[name].get("trades", 0)
                      for name in STRATEGY_NAMES}, indent=2))
    print(f"report: {args.out}")
    print(f"trades: {args.trades}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
