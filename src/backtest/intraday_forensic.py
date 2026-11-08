"""Forensic layer for the eleven strategy intraday study.

This module is research-only. It does not change the live signal engine, the
live target or stop, the notifications or the broker path.

The layer exists because the first study treated every one minute bar as an
executable price. A minute with no fresh print, and a minute carrying the
previous close, is a market observation but not a trade. The original replay
also skipped the entry minute when looking for the stop or target and dated a
last print at the session close boundary. Those are execution defects, not
strategy findings.

The functions here enforce the stricter law:

* a signal frame used by the strict run holds only fresh, non-carried minutes;
* an entry is the first fresh minute open at or after the signal completes,
  never a carried or stale minute;
* the entry minute's own high and low count, with the stop winning a tie;
* an exit is the first genuine print beyond a level, or the last genuine
  print before the close, never the carried close of a quiet minute;
* a trade that cannot be executed is reported as a rejection, not silently
  dropped;
* target first, net wins and net expectancy are reported separately;
* a complete session is a capture that starts before the regular open and
  ends at the regular close. The current sample has only six of them.

The module never writes a file and never touches a network.
"""
from __future__ import annotations

import bisect
import math
import random
import statistics
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src import config
from src.data.sessions import (
    KARACHI,
    band_bounds,
    is_trading_day,
    post_market_window,
    pre_market_windows,
    session_bands,
)
from src.data.tape_bars import TapeBar, TapeBars
from src.signals.mtf_vwap import Frame

MIN1 = timedelta(minutes=1)
MIN5 = timedelta(minutes=5)
MIN15 = timedelta(minutes=15)
MIN60 = timedelta(minutes=60)

TARGET = config.TARGET_PCT
STOP = config.KALMAN_STOP_PCT
ROUND_TRIP_COST = config.round_trip_cost()
CGT_RATE = config.CGT_RATE
REQUIRED_COMPLETE_SESSIONS = 60
PREFERRED_COMPLETE_SESSIONS = 100

#: A candidate that the corrected execution refused. The list is reset per
#: run so a rejection can never be mistaken for a trade.
REJECTIONS: list[dict] = []


def reset_rejections() -> None:
    REJECTIONS.clear()


def _reject(band: Mapping, symbol: str, completion: datetime,
            reason: str, detail: str = "") -> None:
    REJECTIONS.append({
        "day": band["day"].isoformat(),
        "symbol": symbol,
        "signal_time": completion.isoformat(),
        "reason": reason,
        "detail": detail,
    })


def _fresh(bar: TapeBar) -> bool:
    return not getattr(bar, "carried", False) and getattr(bar, "prints", 0) > 0


def _fresh_open(bar: TapeBar) -> bool:
    return _fresh(bar) and bool(getattr(bar, "open_is_print", False))


def _bar_exit_time(bar: TapeBar) -> datetime:
    return (getattr(bar, "last_print_time", None)
            or bar.timestamp + MIN1)


def _bar_info(bar: TapeBar) -> dict:
    return {
        "timestamp": bar.timestamp.isoformat(),
        "open": round(float(bar.open), 6),
        "high": round(float(bar.high), 6),
        "low": round(float(bar.low), 6),
        "close": round(float(bar.close), 6),
        "volume": round(float(bar.volume), 6),
        "prints": int(getattr(bar, "prints", 0)),
        "carried": bool(getattr(bar, "carried", False)),
        "open_is_print": bool(getattr(bar, "open_is_print", False)),
        "first_print_time": (getattr(bar, "first_print_time", None).isoformat()
                             if getattr(bar, "first_print_time", None) else None),
        "last_print_time": (getattr(bar, "last_print_time", None).isoformat()
                            if getattr(bar, "last_print_time", None) else None),
    }


def completed_strict(rows: Sequence[TapeBar], minutes: int,
                     session_open: datetime,
                     as_of: datetime) -> list[Frame]:
    """Aggregate fresh one minute bars into completed frames only.

    A bucket is emitted only when every minute exists and every minute has at
    least one fresh print. A carried or stale minute is a hole, never a
    carried close that quietly completes a 5m, 15m or 1h candle.
    """
    if minutes <= 1:
        raise ValueError("minutes must be greater than one")
    buckets: dict[int, list[TapeBar]] = {}
    for bar in rows:
        if bar.timestamp < session_open:
            continue
        if bar.timestamp + MIN1 > as_of:
            continue
        offset = int((bar.timestamp - session_open).total_seconds() // 60)
        if offset < 0:
            continue
        buckets.setdefault(offset // minutes, []).append(bar)

    out: list[Frame] = []
    for index in sorted(buckets):
        group = sorted(buckets[index], key=lambda bar: bar.timestamp)
        if len(group) != minutes:
            continue
        start = group[0].timestamp
        if any(bar.timestamp != start + timedelta(minutes=position)
               for position, bar in enumerate(group)):
            continue
        if any(not _fresh(bar) for bar in group):
            continue
        if any(bar.volume is None or not math.isfinite(bar.volume)
               or bar.volume < 0 for bar in group):
            continue
        out.append(Frame(
            timestamp=start,
            open=group[0].open,
            high=max(bar.high for bar in group),
            low=min(bar.low for bar in group),
            close=group[-1].close,
            volume=sum(float(bar.volume) for bar in group),
        ))
    return out


def _vwap(frames: Sequence[Frame]) -> list[float | None]:
    total_value = 0.0
    total_volume = 0.0
    out: list[float | None] = []
    for frame in frames:
        if frame.volume > 0:
            total_volume += frame.volume
            total_value += ((frame.high + frame.low + frame.close) / 3.0) * frame.volume
        out.append(total_value / total_volume if total_volume > 0 else None)
    return out


def _turnover(frames: Sequence[Frame]) -> list[float]:
    running = 0.0
    out: list[float] = []
    for frame in frames:
        running += frame.close * frame.volume
        out.append(running)
    return out


def strict_bands(day_data: Mapping) -> list[tuple[dict, TapeBars]]:
    """Copy the day's bands with strict signal frames.

    Entry and exit selection already rejects carried and stale bars. This
    stricter copy also keeps carried and stale minutes out of the 5m, 15m and
    1h indicators, so a signal cannot be manufactured by a quiet close.
    """
    out: list[tuple[dict, TapeBars]] = []
    for band, tape in day_data["bands"]:
        fresh = {
            "day": band["day"], "index": band["index"],
            "open": band["open"], "close": band["close"],
            "rows": band["rows"], "rows_strict": {},
            "f5": {}, "f15": {}, "f60": {},
            "vwap5": {}, "vwap15": {},
            "turnover5": {}, "turnover15": {},
            "ts5": {}, "ts15": {}, "at5": {},
            "slots": [], "or_high": {}, "or_low": {},
        }
        for sym, rows in band["rows"].items():
            f5 = completed_strict(rows, 5, fresh["open"], fresh["close"])
            f15 = completed_strict(rows, 15, fresh["open"], fresh["close"])
            f60 = completed_strict(rows, 60, fresh["open"], fresh["close"])
            if not f5:
                continue
            fresh["rows_strict"][sym] = [bar for bar in rows if _fresh(bar)]
            fresh["f5"][sym] = f5
            fresh["f15"][sym] = f15
            fresh["f60"][sym] = f60
            fresh["vwap5"][sym] = _vwap(f5)
            fresh["vwap15"][sym] = _vwap(f15)
            fresh["turnover5"][sym] = _turnover(f5)
            fresh["turnover15"][sym] = _turnover(f15)
            fresh["ts5"][sym] = {frame.timestamp: i for i, frame in enumerate(f5)}
            fresh["ts15"][sym] = {frame.timestamp: i for i, frame in enumerate(f15)}
            for i, frame in enumerate(f5):
                fresh["at5"].setdefault(frame.timestamp, []).append((sym, i))
            if f15 and f15[0].timestamp == fresh["open"]:
                fresh["or_high"][sym] = f15[0].high
                fresh["or_low"][sym] = f15[0].low
        fresh["slots"] = sorted({frame.timestamp for frames in fresh["f5"].values()
                                 for frame in frames})
        out.append((fresh, tape))
    return out


def simulate_executable(band: Mapping, sym: str, completion: datetime,
                        max_entry: float | None = None) -> dict | None:
    """Simulate one trade with a genuinely executable price path.

    The entry is the first minute at or after the signal completion whose
    first observation is a fresh print. A carried or stale minute is skipped,
    never entered. The entry minute is included in the exit scan. The stop
    wins a same-bar tie. A last-print exit is dated from the print itself.
    """
    rows = band["rows"].get(sym) or []
    if not rows:
        _reject(band, sym, completion, "no_rows")
        return None
    stamps = [bar.timestamp for bar in rows]
    start = bisect.bisect_left(stamps, completion)
    entry_bar: TapeBar | None = None
    entry = None
    reason = None
    for bar in rows[start:]:
        if bar.timestamp + MIN1 > band["close"]:
            reason = "no_executable_bar_before_close"
            break
        if not _fresh_open(bar):
            continue
        price = float(bar.open)
        if not math.isfinite(price) or price <= 0:
            continue
        if max_entry is not None and price > max_entry:
            reason = "max_entry_exceeded"
            break
        entry_bar = bar
        entry = price
        break
    if entry_bar is None or entry is None:
        _reject(band, sym, completion, reason or "no_executable_bar")
        return None

    entry_time = getattr(entry_bar, "first_print_time", None) or entry_bar.timestamp
    if entry_time < completion:
        entry_time = completion
    target = entry * (1.0 + TARGET)
    stop = entry * (1.0 - STOP)
    exit_price: float | None = None
    exit_bar: TapeBar | None = None
    exit_reason: str | None = None
    same_bar = False
    ambiguous = False

    def check(bar: TapeBar, first: float) -> str | None:
        nonlocal exit_price, exit_bar, exit_reason, same_bar, ambiguous
        if first <= stop:
            exit_price, exit_bar, exit_reason = first, bar, "stop_gap"
            return exit_reason
        if first >= target:
            exit_price, exit_bar, exit_reason = first, bar, "target_gap"
            return exit_reason
        if bar.low <= stop and bar.high >= target:
            exit_price, exit_bar, exit_reason = stop, bar, "stop"
            same_bar = True
            ambiguous = True
            return exit_reason
        if bar.low <= stop:
            exit_price, exit_bar, exit_reason = stop, bar, "stop"
            return exit_reason
        if bar.high >= target:
            exit_price, exit_bar, exit_reason = target, bar, "target"
            return exit_reason
        return None

    check(entry_bar, entry)
    if exit_bar is None:
        index = rows.index(entry_bar)
        for bar in rows[index + 1:]:
            if bar.timestamp >= band["close"]:
                break
            if not _fresh(bar):
                continue
            first = getattr(bar, "first_print_price", None)
            if first is None:
                first = float(bar.open)
            if check(bar, float(first)) is not None:
                break

    if exit_bar is None:
        last = None
        for bar in reversed(rows):
            if bar.timestamp >= band["close"]:
                continue
            if not _fresh(bar):
                continue
            last = bar
            break
        if last is None:
            _reject(band, sym, completion, "no_genuine_exit")
            return None
        exit_price = float(last.close)
        exit_bar = last
        exit_reason = ("session_end" if last.timestamp + MIN1 >= band["close"]
                       else "tape_end")

    exit_time = _bar_exit_time(exit_bar)
    if exit_time <= entry_time:
        _reject(band, sym, completion, "non_positive_holding_time")
        return None
    gross = (float(exit_price) / entry) - 1.0
    net = config.net_return(gross)
    if net is None:
        _reject(band, sym, completion, "unvalued_trade")
        return None
    net_before_cgt = round(gross - ROUND_TRIP_COST, 6)
    cgt = round(max(0.0, net_before_cgt) * CGT_RATE, 6)
    return {
        "symbol": sym,
        "signal_time": completion.isoformat(),
        "entry_time": entry_time.isoformat(),
        "entry": round(entry, 4),
        "target": round(target, 4),
        "stop": round(stop, 4),
        "exit_time": exit_time.isoformat(),
        "exit": round(float(exit_price), 4),
        "exit_reason": exit_reason,
        "gross": round(gross, 6),
        "net_before_cgt": net_before_cgt,
        "cgt": cgt,
        "net": net,
        "hold_minutes": round((exit_time - entry_time).total_seconds() / 60.0, 2),
        "same_bar": same_bar,
        "ambiguous": ambiguous,
        "entry_delay_seconds": round((entry_time - completion).total_seconds(), 2),
        "entry_bar": _bar_info(entry_bar),
        "exit_bar": _bar_info(exit_bar),
        "entry_price_source": "first fresh print of the first executable minute",
        "exit_price_source": ("first fresh print beyond the level"
                              if exit_reason in ("stop_gap", "target_gap")
                              else ("level inside a fresh minute"
                                    if exit_reason in ("stop", "target")
                                    else "last fresh print before the close")),
    }


def _session_bounds(day: date) -> tuple[datetime, datetime]:
    bands = session_bands(day)
    if not bands:
        raise ValueError(f"{day.isoformat()} has no session")
    first = band_bounds(day, bands[0])[0]
    last = band_bounds(day, bands[-1])[1]
    return first, last


def _expected_minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def session_quality(day_data: Mapping, raw_path: Path,
                    raw: Mapping, universe_size: int) -> dict:
    """Per-session and per-symbol data quality for one captured session."""
    day = day_data["day"]
    tape: TapeBars = day_data["tape"]
    bands = day_data["bands"]
    all_bars = [bar for _band, _tape in bands
                for rows in _band["rows"].values() for bar in rows]
    if not all_bars:
        all_bars = [bar for rows in tape.bars.values() for bar in rows]
    session_open, session_close = _session_bounds(day)
    observations = [value for value in tape.observed_at.values() if value]
    last_observation = max(observations) if observations else None
    first_observation = tape.first_observation
    capture_complete = bool(
        first_observation is not None and last_observation is not None
        and first_observation <= session_open
        and last_observation + MIN1 >= session_close
    )

    band_quality: list[dict] = []
    symbol_rows: list[dict] = []
    for band, _tape in bands:
        band_open = band["open"]
        band_close = band["close"]
        band_expected = _expected_minutes(band_open, band_close)
        band_first = min((tape.observed_at[sym] for sym in band["rows"]
                          if tape.observed_at.get(sym)), default=None)
        band_last = max((tape.observed_at[sym] for sym in band["rows"]
                         if tape.observed_at.get(sym)), default=None)
        band_complete = bool(
            band_first is not None and band_last is not None
            and band_first <= band_open and band_last + MIN1 >= band_close
        )
        band_bars = []
        for sym, rows in band["rows"].items():
            in_band = [bar for bar in rows
                       if band_open <= bar.timestamp
                       and bar.timestamp + MIN1 <= band_close]
            fresh = [bar for bar in in_band if _fresh(bar)]
            stale = [bar for bar in in_band
                     if not getattr(bar, "carried", False) and not _fresh(bar)]
            carried = [bar for bar in in_band if getattr(bar, "carried", False)]
            minutes = {bar.timestamp for bar in in_band}
            missing = max(0, band_expected - len(minutes))
            first_bar = in_band[0].timestamp if in_band else None
            last_bar = in_band[-1].timestamp if in_band else None
            first_fresh = fresh[0].timestamp if fresh else None
            last_fresh = fresh[-1].timestamp if fresh else None
            full = bool(
                first_fresh is not None and last_fresh is not None
                and first_fresh <= band_open and last_fresh + MIN1 >= band_close
                and missing == 0 and not carried and not stale
            )
            symbol_rows.append({
                "symbol": sym,
                "band": band["index"],
                "first_bar": first_bar.isoformat() if first_bar else None,
                "last_bar": last_bar.isoformat() if last_bar else None,
                "first_genuine": first_fresh.isoformat() if first_fresh else None,
                "last_genuine": last_fresh.isoformat() if last_fresh else None,
                "minute_bars": len(in_band),
                "fresh_bars": len(fresh),
                "stale_bars": len(stale),
                "carried_bars": len(carried),
                "missing_minutes": missing,
                "volume_bars": sum(1 for bar in fresh if bar.volume > 0),
                "complete_band": full,
            })
            band_bars.append((len(in_band), len(fresh), len(stale), len(carried),
                              missing, full))
        band_quality.append({
            "index": band["index"],
            "open": band_open.isoformat(),
            "close": band_close.isoformat(),
            "first_observation": band_first.isoformat() if band_first else None,
            "last_observation": band_last.isoformat() if band_last else None,
            "capture_complete": band_complete,
            "symbols": len(band["rows"]),
            "symbols_complete": sum(1 for _b, _f, _s, _c, _m, ok in band_bars
                                    if ok),
            "minute_bars": sum(row[0] for row in band_bars),
            "fresh_bars": sum(row[1] for row in band_bars),
            "stale_bars": sum(row[2] for row in band_bars),
            "carried_bars": sum(row[3] for row in band_bars),
            "missing_minutes": sum(row[4] for row in band_bars),
            "expected_minutes": band_expected,
        })

    minute_bars = sum(len(rows) for rows in tape.bars.values())
    fresh_bars = sum(1 for bar in all_bars if _fresh(bar))
    stale_bars = sum(1 for bar in all_bars
                     if not getattr(bar, "carried", False) and not _fresh(bar))
    carried_bars = sum(1 for bar in all_bars if getattr(bar, "carried", False))
    stale_open_bars = sum(1 for bar in all_bars
                          if not getattr(bar, "carried", False)
                          and not getattr(bar, "open_is_print", False))
    return {
        "day": day.isoformat(),
        "weekday": day.strftime("%A"),
        "trading_day": is_trading_day(day),
        "capture": raw_path.name,
        "bytes": raw_path.stat().st_size if raw_path.is_file() else None,
        "sha256": _sha256(raw_path),
        "first_observation": (first_observation.isoformat()
                              if first_observation else None),
        "last_observation": (last_observation.isoformat()
                             if last_observation else None),
        "session_open": session_open.isoformat(),
        "session_close": session_close.isoformat(),
        "capture_complete": capture_complete,
        "complete": capture_complete,
        "status": "complete" if capture_complete else "partial",
        "symbols_with_bars": tape.symbols_with_bars,
        "universe": universe_size,
        "universe_coverage": round(tape.symbols_with_bars
                                   / max(1, universe_size), 4),
        "minute_bars": minute_bars,
        "fresh_bars": fresh_bars,
        "stale_bars": stale_bars,
        "carried_bars": carried_bars,
        "stale_open_bars": stale_open_bars,
        "carried_share": round(carried_bars / max(1, minute_bars), 4),
        "stale_share": round(stale_bars / max(1, minute_bars), 4),
        "volume_available": tape.volume_available,
        "counter_rows": tape.counter_rows,
        "counter_resets": tape.counter_resets,
        "counter_gaps": tape.counter_gaps,
        "raw_tick_rows": raw.get("tick_rows"),
        "raw_symbols": raw.get("symbols"),
        "duplicate_consecutive_rows": raw.get("duplicate_consecutive_rows"),
        "out_of_order_records": raw.get("out_of_order_records"),
        "raw_print_lag": raw.get("new_print_lag_seconds"),
        "circuit_caps": raw.get("circuit_caps", []),
        "symbols_started_after_open": list(tape.started_after_open),
        "hole_symbols": list(tape.hole_symbols),
        "venue_extreme_violations": tape.venue_extreme_violations,
        "bands": band_quality,
        "symbols": symbol_rows,
    }


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (moment.astimezone(KARACHI) if moment.tzinfo
            else moment.replace(tzinfo=KARACHI))


def market_session_audit(day: date, trades: Sequence[Mapping]) -> dict:
    """Check every trade against the PSX calendar and session bands."""
    bands = []
    pre = pre_market_windows(day)
    post = post_market_window(day)
    for band_def in session_bands(day):
        opens, closes = band_bounds(day, band_def)
        rows = []
        for trade in trades:
            entry = _parse(trade.get("entry_time"))
            exit_ = _parse(trade.get("exit_time"))
            in_entry = bool(entry and opens <= entry < closes)
            in_exit = bool(exit_ and opens <= exit_ < closes)
            at_close = bool(exit_ and exit_ == closes)
            rows.append({
                "symbol": trade.get("symbol"),
                "strategy": trade.get("strategy"),
                "entry_time": trade.get("entry_time"),
                "exit_time": trade.get("exit_time"),
                "entry_in_band": in_entry,
                "exit_in_band": in_exit,
                "exit_at_close_boundary": at_close,
            })
        bands.append({
            "index": len(bands),
            "open": opens.isoformat(),
            "close": closes.isoformat(),
            "trades": rows,
        })
    pre_rows = [{"open": band_bounds(day, b)[0].isoformat(),
                 "close": band_bounds(day, b)[1].isoformat()} for b in pre]
    post_row = ({"open": band_bounds(day, post)[0].isoformat(),
                 "close": band_bounds(day, post)[1].isoformat()}
                if post else None)
    outside = 0
    close_boundary = 0
    for trade in trades:
        entry = _parse(trade.get("entry_time"))
        exit_ = _parse(trade.get("exit_time"))
        valid = False
        for band_def in session_bands(day):
            opens, closes = band_bounds(day, band_def)
            if entry and opens <= entry < closes:
                valid = True
            if exit_ and opens <= exit_ < closes:
                valid = True
        if not valid:
            outside += 1
        if exit_ and any(exit_ == band_bounds(day, b)[1]
                         for b in session_bands(day)):
            close_boundary += 1
    return {
        "day": day.isoformat(),
        "weekday": day.strftime("%A"),
        "trading_day": is_trading_day(day),
        "bands": bands,
        "pre_market_windows": pre_rows,
        "post_market_window": post_row,
        "trades": len(trades),
        "outside_band": outside,
        "exit_at_close_boundary": close_boundary,
        "opening_auction_used": False,
        "closing_auction_used": False,
        "timezone": "Asia/Karachi UTC+05:00, no daylight saving",
    }


def normalise_scaled_trade(trade: dict, scale: float | None) -> dict | None:
    """Return a copy with a clearly documented price scale correction."""
    if not scale or not math.isfinite(scale) or scale <= 0:
        return None
    out = dict(trade)
    for key in ("entry", "exit", "target", "stop"):
        if out.get(key) is not None:
            out[key] = round(float(out[key]) * scale, 6)
    out["price_scale_applied"] = scale
    out["gross"] = trade.get("gross")
    out["net"] = trade.get("net")
    return out


def price_evidence(tape: TapeBars, trade: Mapping,
                   daily_close: float | None = None) -> dict:
    """Trace a trade back to the bars and classify any suspicious price."""
    symbol = str(trade.get("symbol") or "")
    bars = tape.bars.get(symbol) or []
    entry_time = _parse(trade.get("entry_time"))
    exit_time = _parse(trade.get("exit_time"))
    entry_bar = next((bar for bar in bars if bar.timestamp == entry_time), None)
    exit_bar = next((bar for bar in bars if bar.timestamp == exit_time), None)
    if exit_bar is None and exit_time is not None:
        exit_bar = next((bar for bar in bars
                         if bar.timestamp == exit_time - MIN1), None)
    strict = [bar for bar in bars if _fresh(bar)]
    closes = [float(bar.close) for bar in strict if bar.close > 0]
    median = statistics.median(closes) if closes else None
    entry_price = float(trade["entry"]) if trade.get("entry") is not None else None
    exit_price = float(trade["exit"]) if trade.get("exit") is not None else None
    ratio = (entry_price / median
             if entry_price and median and median > 0 else None)
    scale = None
    if ratio is not None and (ratio >= 50.0 or ratio <= 0.02):
        scale = median / entry_price if entry_price else None
    low, high = tape.venue_extremes.get(symbol, (None, None))
    above_venue = bool(high is not None and entry_price is not None
                       and entry_price > high * 1.001)
    below_venue = bool(low is not None and exit_price is not None
                       and exit_price < low * 0.999)
    entry_carried = bool(entry_bar and getattr(entry_bar, "carried", False))
    exit_carried = bool(exit_bar and getattr(exit_bar, "carried", False))
    entry_stale = bool(entry_bar and not _fresh(entry_bar))
    exit_stale = bool(exit_bar and not _fresh(exit_bar))
    same_bar_omitted = bool(
        entry_bar and entry_bar.low <= float(trade.get("stop") or 0)
        and entry_bar.high >= float(trade.get("target") or 0)
    )
    gap_bps = None
    if trade.get("exit_reason") == "stop_gap" and entry_price:
        stop = float(trade.get("stop") or 0)
        gap_bps = round((stop - float(trade.get("exit") or stop))
                        / entry_price * 10000.0, 2)
    daily_ratio = (float(trade["entry"]) / daily_close
                   if daily_close and trade.get("entry") else None)
    classification = "genuine_print"
    action = "retained"
    notes = []
    if scale:
        classification = "decimal_scaling"
        action = "price scale corrected, trade retained"
        notes.append(f"entry is {ratio:.1f} times the session median fresh close")
    elif entry_carried or exit_carried:
        classification = "carried_bar_execution"
        action = "flagged, retained in the original ledger"
        notes.append("original replay entered or exited on a carried bar")
    elif entry_stale or exit_stale:
        classification = "stale_bar_execution"
        action = "flagged, retained in the original ledger"
        notes.append("original replay entered or exited on a minute with no fresh print")
    elif above_venue or below_venue:
        classification = "outside_venue_day_range"
        action = "flagged, no silent removal"
        notes.append("price sits outside the venue's own day high or low")
    elif same_bar_omitted:
        classification = "entry_minute_tie_omitted"
        action = "flagged, retained; corrected run applies stop-first"
        notes.append("entry minute touched both levels and the original skipped it")
    elif trade.get("exit_reason") == "stop_gap":
        classification = "genuine_gap_through_stop"
        notes.append(f"gap through the stop of {gap_bps or 0:.1f} bps")
    corrected = normalise_scaled_trade(dict(trade), scale)
    return {
        "symbol": symbol,
        "strategy": trade.get("strategy"),
        "day": trade.get("day"),
        "signal_time": trade.get("signal_time"),
        "entry_time": trade.get("entry_time"),
        "exit_time": trade.get("exit_time"),
        "entry": trade.get("entry"),
        "exit": trade.get("exit"),
        "exit_reason": trade.get("exit_reason"),
        "net": trade.get("net"),
        "gross": trade.get("gross"),
        "classification": classification,
        "action": action,
        "notes": notes,
        "retained": True,
        "entry_bar": _bar_info(entry_bar) if entry_bar else None,
        "exit_bar": _bar_info(exit_bar) if exit_bar else None,
        "session_median_fresh_close": round(median, 6) if median else None,
        "price_ratio_to_median": round(ratio, 4) if ratio else None,
        "inferred_price_scale": scale,
        "venue_day_low": low,
        "venue_day_high": high,
        "above_venue_day_high": above_venue,
        "below_venue_day_low": below_venue,
        "daily_close": daily_close,
        "daily_ratio": round(daily_ratio, 4) if daily_ratio else None,
        "gap_bps_beyond_stop": gap_bps,
        "same_bar_omitted": same_bar_omitted,
        "carried_entry": entry_carried,
        "carried_exit": exit_carried,
        "stale_entry": entry_stale,
        "stale_exit": exit_stale,
        "corrected_prices": ({"entry": corrected["entry"],
                              "exit": corrected["exit"],
                              "target": corrected["target"],
                              "stop": corrected["stop"]}
                             if corrected else None),
    }


def bootstrap_ci(values: Sequence[float], seed: int = 20261108,
                 draws: int = 4000) -> dict | None:
    values = [float(value) for value in values if value is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(values, k=len(values)))
                   for _ in range(draws))
    return {
        "low": round(means[int(0.025 * len(means))], 6),
        "high": round(means[int(0.975 * len(means)) - 1], 6),
        "method": "percentile bootstrap of the mean",
        "draws": draws,
    }


def one_metrics(trades: Sequence[Mapping]) -> dict:
    """Gross, cost, CGT, target-first and win metrics for one arm."""
    trades = [trade for trade in trades if trade.get("net") is not None]
    if not trades:
        return {"trades": 0, "wins": 0, "losses": 0, "target_first": 0,
                "target_first_rate": None, "win_rate": None,
                "gross_expectancy": None, "net_before_cgt_expectancy": None,
                "net_expectancy": None, "net_total": 0.0, "gross_total": 0.0,
                "cgt_total": 0.0, "cost_total": 0.0, "profit_factor": None,
                "profit_factor_gross": None, "max_drawdown": None,
                "gross_max_drawdown": None, "avg_win": None, "avg_loss": None,
                "median": None, "best": None, "worst": None,
                "avg_hold_minutes": None, "ci95": None, "exit_reasons": {},
                "gap_loss_distribution": {}, "same_bar_ties": 0,
                "tape_end": 0, "carried_entry": 0, "carried_exit": 0,
                "stale_entry": 0}
    nets = [float(t["net"]) for t in trades]
    gross = [float(t.get("gross") or 0.0) for t in trades]
    before = [float(t.get("net_before_cgt") or 0.0) for t in trades]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value <= 0]
    target_first = [t for t in trades
                    if t.get("exit_reason") in ("target", "target_gap")]
    equity = []
    running = 0.0
    for value in nets:
        running += value
        equity.append(running)
    peak = equity[0] if equity else 0.0
    drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        drawdown = min(drawdown, value - peak)
    reasons = Counter(str(t.get("exit_reason") or "unknown") for t in trades)
    gap_bins = Counter()
    for trade in trades:
        if trade.get("exit_reason") != "stop_gap" or not trade.get("entry"):
            continue
        stop = float(trade.get("stop") or 0.0)
        exit_ = float(trade.get("exit") or stop)
        excess = (stop - exit_) / float(trade["entry"]) * 10000.0
        if excess <= 50:
            gap_bins["0-50bps"] += 1
        elif excess <= 100:
            gap_bins["50-100bps"] += 1
        elif excess <= 250:
            gap_bins["100-250bps"] += 1
        else:
            gap_bins["over-250bps"] += 1
    gross_equity = []
    running = 0.0
    for value in gross:
        running += value
        gross_equity.append(running)
    gross_peak = gross_equity[0] if gross_equity else 0.0
    gross_drawdown = 0.0
    for value in gross_equity:
        gross_peak = max(gross_peak, value)
        gross_drawdown = min(gross_drawdown, value - gross_peak)
    return {
        "trades": len(nets),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(nets), 4),
        "target_first": len(target_first),
        "target_first_rate": round(len(target_first) / len(nets), 4),
        "gross_expectancy": round(statistics.mean(gross), 6),
        "net_before_cgt_expectancy": round(statistics.mean(before), 6),
        "net_expectancy": round(statistics.mean(nets), 6),
        "net_total": round(sum(nets), 6),
        "gross_total": round(sum(gross), 6),
        "cgt_total": round(sum(float(t.get("cgt") or 0.0) for t in trades), 6),
        "cost_total": round(ROUND_TRIP_COST * len(nets), 6),
        "median": round(statistics.median(nets), 6),
        "avg_win": round(statistics.mean(wins), 6) if wins else None,
        "avg_loss": round(statistics.mean(losses), 6) if losses else None,
        "profit_factor": (round(sum(wins) / abs(sum(losses)), 4)
                          if losses and sum(losses) != 0 else None),
        "profit_factor_gross": (
            round(sum(v for v in gross if v > 0)
                  / abs(sum(v for v in gross if v <= 0)), 4)
            if any(v <= 0 for v in gross)
            and sum(v for v in gross if v <= 0) != 0 else None),
        "max_drawdown": round(drawdown, 6),
        "gross_max_drawdown": round(gross_drawdown, 6),
        "best": round(max(nets), 6),
        "worst": round(min(nets), 6),
        "avg_hold_minutes": round(statistics.mean(
            [float(t.get("hold_minutes") or 0.0) for t in trades]), 2),
        "ci95": bootstrap_ci(nets),
        "exit_reasons": dict(sorted(reasons.items())),
        "gap_loss_distribution": dict(sorted(gap_bins.items())),
        "same_bar_ties": sum(1 for t in trades if t.get("same_bar")),
        "tape_end": sum(1 for t in trades if t.get("exit_reason") == "tape_end"),
        "carried_entry": sum(1 for t in trades
                             if t.get("entry_bar", {}).get("carried")),
        "carried_exit": sum(1 for t in trades
                            if t.get("exit_bar", {}).get("carried")),
        "stale_entry": sum(1 for t in trades
                           if t.get("entry_bar")
                           and not t["entry_bar"].get("prints")),
    }


def metrics(trades: Sequence[Mapping], complete_days: Iterable[str],
            session_days: Sequence[str], strategy_names: Sequence[str]) -> dict:
    complete = set(complete_days)
    by_strategy: dict[str, list[Mapping]] = {name: [] for name in strategy_names}
    by_strategy_complete: dict[str, list[Mapping]] = {name: [] for name in strategy_names}
    for trade in trades:
        name = str(trade.get("strategy") or "")
        if name in by_strategy:
            by_strategy[name].append(trade)
            if str(trade.get("day")) in complete:
                by_strategy_complete[name].append(trade)
    all_metrics = one_metrics(trades)
    complete_trades = [t for t in trades if str(t.get("day")) in complete]
    complete_metrics = one_metrics(complete_trades)
    all_metrics["trades_per_session"] = round(
        all_metrics["trades"] / max(1, len(session_days)), 3)
    all_metrics["trades_per_complete_session"] = round(
        all_metrics["trades"] / max(1, len(complete)), 3)
    complete_metrics["trades_per_complete_session"] = round(
        complete_metrics["trades"] / max(1, len(complete)), 3)
    return {
        "all_sessions": all_metrics,
        "complete_sessions_only": complete_metrics,
        "sessions_total": len(session_days),
        "sessions_complete": len(complete),
        "complete_days": sorted(complete),
        "required_complete_sessions": REQUIRED_COMPLETE_SESSIONS,
        "preferred_complete_sessions": PREFERRED_COMPLETE_SESSIONS,
        "sample_sufficient": len(complete) >= REQUIRED_COMPLETE_SESSIONS,
        "selection_allowed": (len(complete) >= REQUIRED_COMPLETE_SESSIONS
                              and complete_metrics["trades"] >= 40),
        "strategy_10_status": "not_tested",
        "by_strategy_all": {name: one_metrics(rows)
                            for name, rows in by_strategy.items()},
        "by_strategy_complete": {name: one_metrics(rows)
                                 for name, rows in by_strategy_complete.items()},
    }


STRATEGY_AUDIT: tuple[dict, ...] = (
    {
        "number": 0,
        "name": "current_kalman_flip",
        "label": "Current bot, 1m Kalman Trend fresh flip",
        "status": "tested",
        "timeframes": "1m signal, 1m execution",
        "entry": "fresh 1m Kalman flip, next 1m open",
        "confirmation": "one live candidate per day, highest slope among a simultaneous flip",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first flip across the day's bands, then highest slope",
        "deviation": ("Only the 1m flip arm is replayed. The live four-frame VWAP "
                      "pullback arm is not tested because its 1D frame needs 40 "
                      "completed daily bars that the band store does not hold."),
        "source": "scripts/backtest_eleven_intraday.py current_kalman_flip block",
    },
    {
        "number": 1,
        "name": "1_ema_rsi_pullback",
        "label": "EMA 20/50 + RSI pullback",
        "status": "tested",
        "timeframes": "15m EMA/RSI, 5m trigger, 1h optional",
        "entry": "15m EMA20 above EMA50, 15m RSI recovers through 50 after a 40-50 pullback, 5m close above the prior high",
        "confirmation": "the 5m breakout is the trigger; the optional 1H EMA50 filter is not enforced",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying 5m slot, highest score inside that slot",
        "deviation": "The optional 1H EMA50 filter is omitted. The 5m close above the prior high is an added trigger.",
        "source": "scripts/backtest_eleven_intraday.py strategy 1 block",
    },
    {
        "number": 2,
        "name": "2_vwap_reclaim_relvol",
        "label": "VWAP reclaim + relative volume",
        "status": "tested",
        "timeframes": "5m bars, session VWAP",
        "entry": "5m close above session VWAP after the prior 5m close was at or below it",
        "confirmation": "the following 5m close above VWAP and relative volume of at least 1.5; a separate retest is not required",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest prior-slot relative volume",
        "deviation": "The separate retest in the written specification is not required.",
        "source": "scripts/backtest_eleven_intraday.py strategy 2 block",
    },
    {
        "number": 3,
        "name": "3_kalman_vwap_rs",
        "label": "Kalman 1H/15M + VWAP + relative strength",
        "status": "tested",
        "timeframes": "1h and 15m Kalman, 5m VWAP trigger",
        "entry": "1H and 15M Kalman state +1, 5m close above VWAP, positive RS20, 5m close above the prior high",
        "confirmation": "the 15m and 1h filters are completed before the 5m trigger",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest RS20 plus VWAP distance",
        "deviation": "The market leg of RS20 is the equal-weight mean of captured KMIALL symbols, not the KMIALLSHR index level.",
        "source": "scripts/backtest_eleven_intraday.py strategy 3 block",
    },
    {
        "number": 4,
        "name": "4_donchian_atr_breakout",
        "label": "Donchian breakout + ATR + relative volume",
        "status": "tested",
        "timeframes": "15m Donchian, 1h trend, 5m trigger",
        "entry": "15m close above the prior 20-bar high but within 0.75%, ATR expanding, 1h close above EMA50, relative volume at least 1.5, 5m close above the Donchian high",
        "confirmation": "the 5m entry must not exceed the Donchian high by more than 0.75%",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest relative volume plus ATR expansion",
        "deviation": "The suggested 0.25% to 0.90% normalized ATR band is not a hard gate. A 0.75% anti-chase cap is added.",
        "source": "scripts/backtest_eleven_intraday.py strategy 4 block",
    },
    {
        "number": 5,
        "name": "5_supertrend_adx_volume",
        "label": "Supertrend + ADX + volume expansion",
        "status": "tested",
        "timeframes": "15m Supertrend/ADX, 5m trigger",
        "entry": "bullish Supertrend, ADX above 20, +DI above -DI, relative volume at least 1.3, 5m close above the prior high",
        "confirmation": "the continuation variant is used",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest ADX",
        "deviation": "The separate controlled pullback qualifier is not enforced.",
        "source": "scripts/backtest_eleven_intraday.py strategy 5 block",
    },
    {
        "number": 6,
        "name": "6_bollinger_squeeze",
        "label": "Bollinger squeeze + volume breakout",
        "status": "tested",
        "timeframes": "15m Bollinger, 1h trend, 5m trigger",
        "entry": "15m band width below its prior 100-observation 20th percentile, 15m close above the upper band within 1%, 1h close above EMA50, relative volume at least 1.5, 5m close above the upper band",
        "confirmation": "the 1h 'not bearish' test is close above EMA50",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest relative volume",
        "deviation": "The written specification's 1h condition is represented only by close above EMA50.",
        "source": "scripts/backtest_eleven_intraday.py strategy 6 block",
    },
    {
        "number": 7,
        "name": "7_rsi_ema50_reversal",
        "label": "RSI reversal + EMA 50 support",
        "status": "tested",
        "timeframes": "15m RSI/EMA, 1h trend, 5m trigger",
        "entry": "15m RSI touched 30-45 in the last five bars and crossed back above 45, 1h close above EMA50, higher low, 5m close above the prior high",
        "confirmation": "the 1h trend and the higher low are both required",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, largest RSI recovery",
        "deviation": "No separate written-specification gate beyond the 1h EMA50 and the higher low is omitted.",
        "source": "scripts/backtest_eleven_intraday.py strategy 7 block",
    },
    {
        "number": 8,
        "name": "8_opening_range_vwap",
        "label": "Opening range breakout + VWAP",
        "status": "tested",
        "timeframes": "15m opening range, 5m trigger",
        "entry": "5m close above the first completed 15m high and above VWAP, relative volume at least 1.5",
        "confirmation": "a session whose tape starts after the open has no opening range and cannot signal",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "first qualifying slot, highest relative volume",
        "deviation": "The anti-chase cap allows at most 0.5% above the opening-range high.",
        "source": "scripts/backtest_eleven_intraday.py strategy 8 block",
    },
    {
        "number": 9,
        "name": "9_relative_strength_rotation",
        "label": "Relative strength rotation",
        "status": "tested",
        "timeframes": "15m cross-section, 5m confirmation",
        "entry": "15m RS8 and RS20 positive, close above EMA20, adequate turnover; the next 5m close above the prior 5m high",
        "confirmation": "the 5m confirmation is the entry trigger",
        "exit": "+2.00% target, -1.00% stop, band close",
        "ranking": "0.60 z(RS8) + 0.40 z(RS4), highest cross-sectional score, at least three names",
        "deviation": "The market is the equal-weight captured universe, not the KMIALLSHR index. The 1h RS component named in the note is not an explicit gate.",
        "source": "scripts/backtest_eleven_intraday.py strategy 9 block",
    },
    {
        "number": 10,
        "name": "10_order_book_imbalance",
        "label": "Order book imbalance + VWAP + intensity",
        "status": "not_tested",
        "timeframes": "order book and 60 second trade intensity",
        "entry": "not evaluated",
        "confirmation": "not evaluated",
        "exit": "not evaluated",
        "ranking": "not evaluated",
        "deviation": ("The capture has last price, best bid, best ask and print sizes, "
                      "but not top-five depth or a reliable aggressor sequence. "
                      "Computing imbalance would fabricate the missing book."),
        "source": "no implementation; refused by the original study",
    },
)


def data_standard() -> dict:
    return {
        "required_complete_sessions": REQUIRED_COMPLETE_SESSIONS,
        "preferred_complete_sessions": PREFERRED_COMPLETE_SESSIONS,
        "complete_definition": (
            "The capture's first observation is at or before the regular session "
            "open, its last observation is at or after the last regular close "
            "minus one minute, and every band is covered. A trading day with no "
            "stored capture is missing, never a holiday and never padded."
        ),
        "requirements": [
            "complete regular-session capture",
            "verified timestamp ordering",
            "actual fresh-print and volume evidence",
            "per-symbol coverage reporting",
            "missing-minute detection",
            "feed-staleness detection",
            "raw capture preservation and SHA-256 hashes",
            "at least 60 complete sessions before a preliminary comparison",
            "preferably 100 or more complete sessions across market regimes",
        ],
        "monitor": "python scripts/backtest_forensic_audit.py --from-store 20 --quality-only",
        "monitor_scope": "research only; no live signal, target, stop, notification or broker change",
    }


def _pct(value) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}%"


def _ci(value: dict | None) -> str:
    if not value:
        return "n/a"
    return f"{_pct(value['low'])} to {_pct(value['high'])}"


def quality_markdown(report: Mapping) -> str:
    lines = [
        "# Intraday data quality report",
        "",
        f"Generated {report['generated']} (Asia/Karachi).",
        "",
        "A complete session starts at or before the regular open and ends at or after",
        "the last regular close minus one minute. A session that starts late is",
        "partial even when it has a full afternoon tape.",
        "",
        "| Day | Weekday | Symbols | 1m bars | Fresh | Carried | Stale | Missing min | Dups | Out of order | First observation | Last observation | Complete |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|",
    ]
    for row in report["sessions"]:
        first = (row.get("first_observation") or "")[11:16]
        last = (row.get("last_observation") or "")[11:16]
        lines.append(
            f"| {row['day']} | {row['weekday']} | {row['symbols_with_bars']} | "
            f"{row['minute_bars']:,} | {row['fresh_bars']:,} | "
            f"{row['carried_bars']:,} | {row['stale_bars']:,} | "
            f"{sum(b['missing_minutes'] for b in row['bands']):,} | "
            f"{row['duplicate_consecutive_rows']} | {row['out_of_order_records']} | "
            f"{first} | {last} | {'yes' if row['complete'] else 'no'} |"
        )
    lines += [
        "",
        f"Sessions: {report['session_count']}. Complete: {report['complete_sessions']}.",
        f"Missing inside the study window: {', '.join(report['missing_sessions']) or 'none'}.",
        f"Required for selection: {report['data_standard']['required_complete_sessions']} complete sessions.",
        "",
        "Per-symbol rows for every session are in `data/research/backtest_forensic_audit.json`",
        "under each session's `symbols` list. The JSON is the evidence; this table is the",
        "session summary.",
        "",
    ]
    return "\n".join(lines)


def performance_markdown(report: Mapping) -> str:
    metrics_ = report["corrected"]
    lines = [
        "# Corrected eleven strategy intraday performance",
        "",
        f"Generated {report['generated']} (Asia/Karachi).",
        "",
        "## Status",
        "",
        f"Existing backtest: **{report['final_conclusion']}**.",
        f"Corrected dataset: **{report['corrected_status']}**.",
        "",
        "No strategy is called profitable. The corrected sample is",
        f"{metrics_['sessions_complete']} complete sessions of the required",
        f"{metrics_['required_complete_sessions']}, so the comparison is stopped.",
        "",
        "## Corrected arms",
        "",
        "The primary corrected run uses the strict signal frames and the genuine",
        "execution path. The execution-only run keeps the original signal frames and",
        "changes only execution. Both are shown so the effect of the data defect is",
        "not confused with the effect of the strategy.",
        "",
        "| # | Strategy | Trades | Win rate | Target first | Gross exp | Net before CGT | Net exp | Profit factor | Max DD | 95% CI net |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for index, row in enumerate(report["strategy_table"]):
        lines.append(
            f"| {row['number']} | {row['label']} | {row['strict']['trades']} | "
            f"{_pct(row['strict']['win_rate'])} | {_pct(row['strict']['target_first_rate'])} | "
            f"{_pct(row['strict']['gross_expectancy'])} | "
            f"{_pct(row['strict']['net_before_cgt_expectancy'])} | "
            f"{_pct(row['strict']['net_expectancy'])} | "
            f"{row['strict']['profit_factor'] if row['strict']['profit_factor'] is not None else 'n/a'} | "
            f"{_pct(row['strict']['max_drawdown'])} | {_ci(row['strict']['ci95'])} |"
        )
    lines += [
        "",
        "Strategy 10 is not tested: the capture does not carry top-five depth or a",
        "reliable aggressor sequence.",
        "",
        "## Complete-session subset",
        "",
        "| # | Strategy | Complete trades | Net exp | Target first | 95% CI |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report["strategy_table"]:
        lines.append(
            f"| {row['number']} | {row['label']} | "
            f"{row['strict_complete']['trades']} | {_pct(row['strict_complete']['net_expectancy'])} | "
            f"{_pct(row['strict_complete']['target_first_rate'])} | "
            f"{_ci(row['strict_complete']['ci95'])} |"
        )
    lines += [
        "",
        "## What changed",
        "",
        "- Carried and stale minutes are no longer executable. The strict run also",
        "  keeps them out of the 5m, 15m and 1h signal frames.",
        "- The entry minute's own high and low are checked; the stop wins a tie.",
        "- A last-print exit is dated from the print, not from the 15:30 boundary.",
        "- A session is complete only when the capture starts before the open and",
        "  ends at the close. The original report's 13 full sessions are not",
        "  supported by its own first-observation column; five sessions are",
        "  complete, 2026-11-04 starts before the open but ends at 15:24, and",
        "  2026-11-06 is two minutes late on a Friday.",
        "- Gross, cost, CGT and net are reported separately. The 15% CGT is an",
        "  assumption, not a measured tax determination.",
        "- Costs remain the repository model: 22.4 bps per side plus 10 bps",
        "  modelled slippage per side, with 15% CGT on positive net returns.",
        "",
        "## Limitation",
        "",
        "These are descriptive corrected results on a small, partial sample. They",
        "do not establish an edge, validate a strategy or justify a production",
        "change. The next comparison is blocked until 60 complete sessions exist.",
        "",
    ]
    return "\n".join(lines)
