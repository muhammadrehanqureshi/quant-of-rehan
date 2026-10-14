"""The ONE authoritative scanner: fast momentum + volume expansion (2026-10-09).

This module replaces the old competing intraday signal engines. It is the only
place in the repository that decides whether a KMIALL stock is a buy
candidate. Its contract is deliberately narrow and explainable:

    SCAN ALL KMIALL
      -> per symbol: fast momentum, momentum acceleration, relative volume,
         volume acceleration, liquidity, extension and weakness penalties
      -> market context gate (breadth and median direction)
      -> rank every eligible symbol
      -> exactly ONE winner, or NO TRADE, or DATA BLOCKED

Honesty rules that are enforced here, not merely documented:

  * a data problem is NEVER reported as a market decision. Broken, stale,
    thin or volume-less data returns status DATA_BLOCKED with the measured
    numbers (owner spec section 8 and 29);
  * volume is REQUIRED. The strategy is momentum plus volume expansion, so a
    source that carries no volume cannot be traded on. The scanner refuses
    instead of substituting a price-only proxy or inventing volume;
  * every bar used must be strictly before as_of (no look-ahead), must have
    finite positive prices, must satisfy high >= max(open, close) and
    low <= min(open, close), and must not repeat a timestamp with a
    different value;
  * nothing is ever fabricated, interpolated or forward-filled.

Exact score (weights come from src/config.py):

    components, each normalized to 0..1 with a saturating half-credit scale
    sat(x, k) = max(x, 0) / (max(x, 0) + k):

      momentum            sat(ret_5m,               HALF_CREDIT_MOMENTUM_FAST)
      acceleration        sat(ret_5m - ret_prev5m,  HALF_CREDIT_ACCELERATION)
      relative_volume     sat(rel_vol - 1,         HALF_CREDIT_REL_VOLUME)
      volume_acceleration sat(bucket_ratio - 1,    HALF_CREDIT_VOLUME_ACCEL)
      liquidity           sat(traded_value,        HALF_CREDIT_TRADED_VALUE)

    score = 100 * sum(weight_i * component_i)
            * extension factor   (1.0 up to MAX_SESSION_EXTENSION of session
                                  return, then 1/(1+excess/cap), so a late
                                  runaway move cannot win on raw momentum)
            * weakness factor    (same shape for the distance below the
                                  session high, MAX_DISTANCE_FROM_HIGH)

    A symbol is only eligible when it passes every hard gate: enough bars,
    positive fast momentum, positive acceleration, a positive session return,
    relative volume above the floor, volume still accelerating, turnover
    above the liquidity floor, a fresh last bar, and a price above MIN_PRICE.

The winner is the highest score at or above MIN_SIGNAL_SCORE. Otherwise the
day is NO TRADE.

The target is ALWAYS the actual recorded entry price plus TARGET_PCT:
target_price = actual_entry_price * (1 + TARGET_PCT).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import median

from src import config
from src.data import tape_bars
from src.data.sessions import KARACHI, is_trading_day, open_time
from src.signals import ai_model

DATA_BLOCKED = "DATA_BLOCKED"
NO_TRADE = "NO_TRADE"
TRADE = "TRADE"

# Statuses of the source-level honesty registry, reported with every scan.
SOURCE_NAME = "eClear GetOHLCData public read tier (OHLC only, no volume)"


@dataclass(frozen=True)
class MinuteBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass
class SessionData:
    """Every usable bar for one session, plus what the source did or did not
    provide. `volume_available` is measured, never assumed.

    `source` names the file the bars came from and travels into the quality
    report and every message, because the system now reads two of them: the
    poller capture and the broker tape (owner order 2026-10-14). A reader must
    never have to guess which one spoke (SO-3). `notes` carries whatever that
    source could not see, in its own measured words.
    """

    day: date
    as_of: datetime
    bars: dict[str, list[MinuteBar]]
    volume_available: bool
    bars_seen: int
    bars_rejected: int
    duplicate_bars: int
    source: str = SOURCE_NAME
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class QualityReport:
    status: str
    reason: str
    coverage: float
    fresh_coverage: float
    symbols_expected: int
    symbols_with_bars: int
    symbols_missing: tuple[str, ...]
    symbols_stale: tuple[str, ...]
    newest_bar: datetime | None
    oldest_bar: datetime | None
    data_age_minutes: float | None
    duplicate_bars: int
    malformed_bars: int
    impossible_ohlc: int
    zero_volume_bars: int
    volume_available: bool
    #: Symbols holding at least MIN_BARS_PER_SYMBOL bars, and that share of the
    #: symbols the capture had any bar for. A ranking cannot be built from a
    #: shorter series, so this is measured before any market verdict is
    #: allowed (SO-3: a thin capture is a data problem, not a NO TRADE).
    symbols_with_history: int = 0
    history_coverage: float = 0.0
    resolution: str = config.BAR_RESOLUTION
    source: str = SOURCE_NAME
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        out = {
            "status": self.status,
            "reason": self.reason,
            "coverage": round(self.coverage, 4),
            "fresh_coverage": round(self.fresh_coverage, 4),
            "symbols_expected": self.symbols_expected,
            "symbols_with_bars": self.symbols_with_bars,
            "symbols_missing": list(self.symbols_missing[:20]),
            "symbols_missing_count": len(self.symbols_missing),
            "symbols_stale": list(self.symbols_stale[:20]),
            "symbols_stale_count": len(self.symbols_stale),
            "newest_bar": self.newest_bar.isoformat() if self.newest_bar else None,
            "oldest_bar": self.oldest_bar.isoformat() if self.oldest_bar else None,
            "data_age_minutes": (round(self.data_age_minutes, 2)
                                 if self.data_age_minutes is not None else None),
            "duplicate_bars": self.duplicate_bars,
            "malformed_bars": self.malformed_bars,
            "impossible_ohlc": self.impossible_ohlc,
            "zero_volume_bars": self.zero_volume_bars,
            "volume_available": self.volume_available,
            "symbols_with_history": self.symbols_with_history,
            "history_coverage": round(self.history_coverage, 4),
            "min_bars_per_symbol": config.MIN_BARS_PER_SYMBOL,
            "resolution": self.resolution,
            "source": self.source,
            "notes": list(self.notes),
            "scanner_version": config.SCANNER_VERSION,
        }
        return out


@dataclass
class ScanResult:
    status: str
    reason: str
    quality: QualityReport
    market: dict
    candidate: dict | None = None
    ranked: list[dict] = field(default_factory=list)
    coverage_text: str = ""


# --------------------------------------------------------------- capture load

def _parse_time(value: str) -> time:
    text = str(value).strip()
    if len(text) == 4 and text[1] == ":":
        text = "0" + text
    return time.fromisoformat(text)


def load_capture(path: Path, symbols: list[str], as_of: datetime) -> SessionData:
    """Load one session of bars from the poller ndjson capture.

    Accepts the poller record shape {ts, symbol, bars: [{t,o,h,l,c}]} and an
    optional per-bar volume under "v" or "volume". Rows that are malformed,
    impossible, out of session or not strictly before as_of are rejected and
    counted; they are never repaired.
    """
    universe = {sym.strip().upper() for sym in symbols}
    session_day = as_of.date()
    bars: dict[str, list[MinuteBar]] = {}
    seen: dict[str, dict[datetime, tuple]] = {}
    volume_bars = 0
    priced_bars = 0
    malformed = 0
    impossible = 0
    duplicates = 0
    seen_count = 0

    if path.is_file() and is_trading_day(session_day):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                symbol = str(record["symbol"]).strip().upper()
                captured = datetime.fromisoformat(str(record["ts"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                malformed += 1
                continue
            if symbol not in universe:
                continue
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=KARACHI)
            if captured.astimezone(KARACHI).date() != session_day:
                continue
            for item in record.get("bars", []):
                seen_count += 1
                try:
                    stamp = datetime.combine(session_day, _parse_time(item["t"]),
                                             tzinfo=as_of.tzinfo)
                    values = [float(item[k]) for k in ("o", "h", "l", "c")]
                except (KeyError, TypeError, ValueError):
                    malformed += 1
                    continue
                if stamp >= as_of:
                    continue
                if not all(math.isfinite(v) and v > 0 for v in values):
                    malformed += 1
                    continue
                op, hi, lo, close = values
                if hi < max(op, close) or lo > min(op, close) or hi < lo:
                    impossible += 1
                    continue
                raw_volume = item.get("v", item.get("volume"))
                volume = None
                if raw_volume is not None:
                    try:
                        volume = float(raw_volume)
                    except (TypeError, ValueError):
                        volume = None
                    if volume is not None and (not math.isfinite(volume) or volume < 0):
                        volume = None
                priced_bars += 1
                if volume is not None:
                    volume_bars += 1
                fingerprint = (op, hi, lo, close, volume)
                by_time = seen.setdefault(symbol, {})
                prior = by_time.get(stamp)
                if prior is not None:
                    if prior != fingerprint:
                        duplicates += 1
                    continue
                by_time[stamp] = fingerprint
                bars.setdefault(symbol, []).append(
                    MinuteBar(stamp, op, hi, lo, close, volume))

    for rows in bars.values():
        rows.sort(key=lambda bar: bar.timestamp)

    volume_available = (
        priced_bars > 0
        and volume_bars == priced_bars
        and any(bar.volume for rows in bars.values() for bar in rows)
    )
    return SessionData(
        day=session_day,
        as_of=as_of,
        bars={sym: rows for sym, rows in bars.items() if rows},
        volume_available=volume_available,
        bars_seen=seen_count,
        bars_rejected=malformed + impossible + duplicates,
        duplicate_bars=duplicates,
    )


#: Capture formats this scanner can load. "tape" is the broker MKT-FEED
#: capture (src/data/tape_bars.py); "poller" is the eClear OHLC servlet
#: capture (src/data/ohlc_poller.py), which served the system until the
#: servlet stopped answering and is kept as the secondary source.
FORMAT_TAPE = "tape"
FORMAT_POLLER = "poller"


def detect_capture_format(path: Path, lines: int = 200) -> str:
    """Which loader fits this capture file.

    The two captures share a directory and an ndjson habit but not a record
    shape: the poller writes {symbol, bars}, the tape writes {kind, ticks}.
    The answer is read from the file itself, so a renamed or copied capture
    still loads under its own rules, and only when a file holds no readable
    record at all does the file name decide (capture_* is the tape).
    """
    if path.is_file():
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= lines:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if "bars" in record:
                        return FORMAT_POLLER
                    if "ticks" in record or "kind" in record:
                        return FORMAT_TAPE
        except OSError:
            pass
    return FORMAT_TAPE if path.name.startswith("capture_") else FORMAT_POLLER


def load_tape_bars(path: Path, symbols: list[str],
                   as_of: datetime) -> SessionData:
    """Load one session of bars built from the broker tape.

    Owner order 2026-10-14: the scanner must stop depending on the eClear
    OHLC servlet, so the tape this system already subscribes to became the bar
    source. src/data/tape_bars.py builds open, high, low and close from the
    prices the tape carried and takes volume from the venue's own running
    counter. Everything after this function is the SAME path as the poller
    capture: the same SessionData shape, the same assess_quality gates and the
    same scoring, with only the source label and the tape's own measured notes
    differing, so a scan can never read one source and report the other.
    """
    tape = tape_bars.build(path, symbols, as_of)
    bars = {
        symbol: [
            MinuteBar(bar.timestamp, bar.open, bar.high, bar.low, bar.close,
                      bar.volume)
            for bar in rows
        ]
        for symbol, rows in tape.bars.items() if rows
    }
    return SessionData(
        day=tape.day,
        as_of=as_of,
        bars=bars,
        volume_available=tape.volume_available,
        bars_seen=tape.rows_seen,
        bars_rejected=tape.rows_rejected,
        duplicate_bars=tape.repeated_rows,
        source=tape.source,
        notes=tuple(tape.notes),
    )


def load_session(path: Path, symbols: list[str], as_of: datetime) -> SessionData:
    """Load a capture file with the loader that fits it.

    One door for both sources, so every caller (the scheduled scan, the
    finalize and the local tick) reads whatever capture the machine actually
    has, and the format decision is made in one tested place rather than
    repeated per caller.
    """
    if detect_capture_format(path) == FORMAT_TAPE:
        return load_tape_bars(path, symbols, as_of)
    return load_capture(path, symbols, as_of)


# ------------------------------------------------------------- quality gate

def assess_quality(session: SessionData, symbols: list[str],
                   malformed: int = 0, impossible: int = 0) -> QualityReport:
    """Measure, then block. A bad measurement never becomes a market verdict."""
    universe = [sym.strip().upper() for sym in symbols]
    expected = len(universe)
    with_bars = len(session.bars)
    coverage = with_bars / max(expected, 1)

    newest: datetime | None = None
    oldest: datetime | None = None
    stale: list[str] = []
    zero_volume = 0
    for sym, rows in session.bars.items():
        last = rows[-1].timestamp
        if newest is None or last > newest:
            newest = last
        first = rows[0].timestamp
        if oldest is None or first < oldest:
            oldest = first
        if session.as_of - last > timedelta(minutes=config.STALENESS_MINUTES):
            stale.append(sym)
        zero_volume += sum(1 for bar in rows if bar.volume == 0)
    fresh_coverage = (with_bars - len(stale)) / max(expected, 1)
    age = ((session.as_of - newest).total_seconds() / 60.0
           if newest is not None else None)
    missing = tuple(sorted(set(universe) - set(session.bars)))
    # Bar history, measured before any verdict: score_symbol refuses a symbol
    # with fewer bars than the strategy needs, so a capture that is thin in
    # every symbol would rank nothing and be reported as a market NO TRADE.
    # The bar path built from the tape made this a real case rather than a
    # theoretical one (a short capture has fresh bars but no history).
    ready = sum(1 for rows in session.bars.values()
                if len(rows) >= config.MIN_BARS_PER_SYMBOL)
    history_coverage = ready / max(with_bars, 1)

    def blocked(reason: str) -> QualityReport:
        return QualityReport(
            status=DATA_BLOCKED, reason=reason, coverage=coverage,
            fresh_coverage=fresh_coverage, symbols_expected=expected,
            symbols_with_bars=with_bars, symbols_missing=missing,
            symbols_stale=tuple(sorted(stale)), newest_bar=newest,
            oldest_bar=oldest, data_age_minutes=age,
            duplicate_bars=session.duplicate_bars, malformed_bars=malformed,
            impossible_ohlc=impossible, zero_volume_bars=zero_volume,
            volume_available=session.volume_available,
            symbols_with_history=ready, history_coverage=history_coverage,
            source=session.source, notes=session.notes,
        )

    if expected == 0:
        return blocked("KMIALL universe is empty; nothing to scan")
    if not is_trading_day(session.day):
        return blocked(f"{session.day.isoformat()} is not a PSX trading day")
    if with_bars == 0:
        return blocked(
            f"KMIALL coverage 0/{expected} (0.0%). The intraday source "
            f"returned no usable current-session bars.")
    if session.bars_seen and (
            (session.bars_rejected / session.bars_seen) > config.MAX_MALFORMED_SHARE):
        return blocked(
            f"{session.bars_rejected}/{session.bars_seen} captured bar rows were "
            f"malformed, impossible or contradictory; refusing to scan them")
    if coverage < config.MIN_COVERAGE_PCT:
        return blocked(
            f"KMIALL coverage {with_bars}/{expected} ({coverage:.1%}) is below "
            f"the {config.MIN_COVERAGE_PCT:.0%} floor. Data source incomplete.")
    if history_coverage < config.MIN_HISTORY_COVERAGE_PCT:
        return blocked(
            f"bar history: only {ready}/{with_bars} captured symbols "
            f"({history_coverage:.1%}) hold the {config.MIN_BARS_PER_SYMBOL} "
            f"bars the strategy needs, below the "
            f"{config.MIN_HISTORY_COVERAGE_PCT:.0%} floor, so a ranking built "
            f"now would say nothing about the market")
    if fresh_coverage < config.MIN_FRESH_COVERAGE_PCT:
        return blocked(
            f"stale data: {len(stale)} symbols have no bar within "
            f"{config.STALENESS_MINUTES:g} minutes of the scan time "
            f"(fresh coverage {fresh_coverage:.1%})")
    if age is not None and age > config.STALENESS_MINUTES:
        return blocked(
            f"newest bar is {age:.1f} minutes old, above the "
            f"{config.STALENESS_MINUTES:g} minute freshness limit")
    if not session.volume_available:
        return blocked(
            "the source carries no volume, and this strategy requires volume "
            "expansion; a price-only proxy would be a different strategy, so "
            "the scan is blocked instead of guessed")

    return QualityReport(
        status="OK", reason="coverage, freshness, history, structure and volume "
                           "present",
        coverage=coverage, fresh_coverage=fresh_coverage, symbols_expected=expected,
        symbols_with_bars=with_bars, symbols_missing=missing,
        symbols_stale=tuple(sorted(stale)), newest_bar=newest, oldest_bar=oldest,
        data_age_minutes=age, duplicate_bars=session.duplicate_bars,
        malformed_bars=malformed, impossible_ohlc=impossible,
        zero_volume_bars=zero_volume, volume_available=True,
        symbols_with_history=ready, history_coverage=history_coverage,
        source=session.source, notes=session.notes,
    )


# ------------------------------------------------------------ market context

def market_context(session: SessionData) -> dict:
    """Breadth and direction of the whole captured KMIALL universe."""
    returns: dict[str, float] = {}
    session_open = datetime.combine(session.day, time(*open_time(session.day)),
                                    tzinfo=session.as_of.tzinfo)
    for sym, rows in session.bars.items():
        first = next((bar for bar in rows if bar.timestamp >= session_open), None)
        if first is None or first.open <= 0:
            continue
        returns[sym] = rows[-1].close / first.open - 1.0
    if not returns:
        return {"status": "UNKNOWN", "advancers": 0, "decliners": 0,
                "breadth": 0.0, "median_return": None, "participation": 0,
                "reason": "no symbol had a usable session open"}
    advancers = sum(1 for value in returns.values() if value > 0)
    decliners = sum(1 for value in returns.values() if value < 0)
    breadth = advancers / len(returns)
    mid = float(median(returns.values()))
    supportive = breadth >= config.MIN_BREADTH and mid >= config.MAX_MARKET_DROP
    if supportive:
        status = "SUPPORTIVE"
        reason = (f"breadth {breadth:.1%} advancing with median move "
                  f"{mid:+.2%}")
    elif mid < config.MAX_MARKET_DROP:
        status = "SELLOFF"
        reason = (f"broad selloff: median KMIALL move {mid:+.2%} with breadth "
                  f"{breadth:.1%}")
    else:
        status = "WEAK"
        reason = (f"breadth {breadth:.1%} is below the "
                  f"{config.MIN_BREADTH:.0%} momentum floor")
    return {
        "status": status,
        "advancers": advancers,
        "decliners": decliners,
        "breadth": round(breadth, 4),
        "median_return": round(mid, 6),
        "participation": len(returns),
        "reason": reason,
        "proxy": "captured KMIALL cross-section, not the official index",
    }


# -------------------------------------------------------------------- scoring

def _sat(value: float, half_credit: float) -> float:
    positive = max(float(value), 0.0)
    if positive <= 0.0:
        return 0.0
    return positive / (positive + half_credit)


def _close_at(rows: list[MinuteBar], target: datetime) -> float | None:
    best: MinuteBar | None = None
    for bar in rows:
        if bar.timestamp <= target:
            best = bar
        else:
            break
    return best.close if best is not None else None


def _volume_buckets(rows: list[MinuteBar], session_open: datetime,
                    as_of: datetime) -> list[float]:
    """Complete VOLUME_WINDOW-minute volume buckets, oldest first."""
    buckets: dict[int, list[MinuteBar]] = {}
    for bar in rows:
        if bar.timestamp < session_open or bar.timestamp >= as_of:
            continue
        offset = int((bar.timestamp - session_open).total_seconds() // 60)
        buckets.setdefault(offset // config.VOLUME_WINDOW, []).append(bar)
    out = []
    for index in sorted(buckets):
        window = buckets[index]
        end = session_open + timedelta(minutes=(index + 1) * config.VOLUME_WINDOW)
        if end > as_of or len(window) != config.VOLUME_WINDOW:
            continue
        if any(bar.volume is None for bar in window):
            return []
        out.append(float(sum(bar.volume for bar in window)))
    return out


def score_symbol(symbol: str, rows: list[MinuteBar], session: SessionData) -> dict | None:
    """Score one symbol, or return None when it fails a hard gate."""
    if len(rows) < config.MIN_BARS_PER_SYMBOL:
        return None
    as_of = session.as_of
    last = rows[-1]
    if last.close < config.MIN_PRICE:
        return None
    if as_of - last.timestamp > timedelta(minutes=config.STALENESS_MINUTES):
        return None

    session_open = datetime.combine(session.day, time(*open_time(session.day)),
                                    tzinfo=as_of.tzinfo)
    first = next((bar for bar in rows if bar.timestamp >= session_open), None)
    if first is None or first.open <= 0:
        return None

    # Windows are anchored on the last COMPLETED bar, not on the scan clock, so
    # the fast leg and the previous leg always span the same number of minutes
    # and the acceleration comparison is like for like.
    fast_window, mid_window, slow_window = config.MOMENTUM_WINDOWS
    anchor = last.timestamp
    close_fast = _close_at(rows, anchor - timedelta(minutes=fast_window))
    close_mid = _close_at(rows, anchor - timedelta(minutes=mid_window))
    close_slow = _close_at(rows, anchor - timedelta(minutes=slow_window))
    close_prev = _close_at(rows, anchor - timedelta(minutes=fast_window * 2))
    if None in (close_fast, close_mid, close_slow, close_prev):
        return None

    ret_fast = last.close / close_fast - 1.0
    ret_mid = last.close / close_mid - 1.0
    ret_slow = last.close / close_slow - 1.0
    ret_previous_leg = close_fast / close_prev - 1.0
    acceleration = ret_fast - ret_previous_leg

    buckets = _volume_buckets(rows, session_open, as_of)
    if len(buckets) < 3:
        return None
    recent_volume = buckets[-1]
    prior = buckets[:-1]
    prior_median = float(median(prior))
    if prior_median <= 0 or recent_volume <= 0:
        return None
    relative_volume = recent_volume / prior_median
    volume_accel_ratio = recent_volume / prior[-1] if prior[-1] > 0 else float("inf")
    traded_value = float(sum(bar.close * (bar.volume or 0.0) for bar in rows))

    session_return = last.close / first.open - 1.0
    session_high = max(bar.high for bar in rows)
    distance_from_high = session_high / last.close - 1.0 if last.close > 0 else 1.0

    # Hard gates: a symbol that fails any of these is not a candidate at all.
    # Extension and weakness are NOT hard gates: they are graduated penalties
    # below, so a stock that has run hard can still be scored but loses points
    # for being late (owner spec section 5: do not chase extreme moves).
    gates = {
        "bars": True,
        "price_floor": True,
        "fresh": True,
        "fast_momentum_positive": ret_fast > 0,
        "accelerating": acceleration > 0,
        "session_return_positive": session_return > 0,
        "relative_volume": relative_volume >= config.MIN_RELATIVE_VOLUME,
        "volume_accelerating": volume_accel_ratio >= config.MIN_VOLUME_ACCEL_RATIO,
        "liquidity": traded_value >= config.MIN_SESSION_TRADED_VALUE,
    }
    failed = sorted(name for name, ok in gates.items() if not ok)
    if failed:
        return None

    components = {
        "momentum": _sat(ret_fast, config.HALF_CREDIT_MOMENTUM_FAST),
        "acceleration": _sat(acceleration, config.HALF_CREDIT_ACCELERATION),
        "relative_volume": _sat(relative_volume - 1.0,
                                config.HALF_CREDIT_REL_VOLUME),
        "volume_acceleration": _sat(volume_accel_ratio - 1.0,
                                    config.HALF_CREDIT_VOLUME_ACCEL),
        "liquidity": _sat(traded_value, config.HALF_CREDIT_TRADED_VALUE),
    }
    base = 100.0 * sum(config.SCORE_WEIGHTS[name] * value
                       for name, value in components.items())

    # Late and weakening moves decay the score multiplicatively rather than
    # losing a capped number of points. A capped subtraction cannot stop a
    # runaway mover from winning on saturated momentum, which is exactly the
    # "do not chase the biggest gainer" failure the owner called out. At the
    # cap the factor is 1.0; at twice the cap the score halves.
    extension_excess = max(0.0, session_return - config.MAX_SESSION_EXTENSION)
    extension_factor = 1.0 / (1.0 + extension_excess / config.MAX_SESSION_EXTENSION)
    weakness_excess = max(0.0, distance_from_high - config.MAX_DISTANCE_FROM_HIGH)
    weakness_factor = 1.0 / (1.0 + weakness_excess / config.MAX_DISTANCE_FROM_HIGH)
    score = max(0.0, min(100.0, base * extension_factor * weakness_factor))
    extension_penalty = round(base - base * extension_factor, 2)
    weakness_penalty = round(base - base * weakness_factor, 2)

    momentum_strength = ("STRONG" if ret_fast >= 0.004 else
                         "MODERATE" if ret_fast > 0 else "WEAK")
    acceleration_strength = ("STRONG" if acceleration >= 0.002 else
                             "MODERATE" if acceleration > 0 else "WEAK")
    volume_strength = ("STRONG" if volume_accel_ratio >= 1.5 else
                       "MODERATE" if volume_accel_ratio >= 1.0 else "WEAK")
    return {
        "symbol": symbol,
        "score": round(score, 2),
        "weighted_score": round(base, 2),
        "penalties": {"extension_points_lost": round(extension_penalty, 2),
                      "weakness_points_lost": round(weakness_penalty, 2),
                      "extension_factor": round(extension_factor, 4),
                      "weakness_factor": round(weakness_factor, 4),
                      "definition": "multiplicative decay on session extension and "
                                    "distance below the session high"},
        "components": {name: round(value, 4) for name, value in components.items()},
        "returns": {"fast_5m": round(ret_fast, 6), "mid_15m": round(ret_mid, 6),
                    "slow_30m": round(ret_slow, 6),
                    "previous_leg_5m": round(ret_previous_leg, 6),
                    "acceleration": round(acceleration, 6),
                    "session": round(session_return, 6)},
        "volume": {"recent_bucket": recent_volume,
                   "prior_bucket_median": prior_median,
                   "relative": round(relative_volume, 3),
                   "bucket_ratio": (round(volume_accel_ratio, 3)
                                    if math.isfinite(volume_accel_ratio) else None),
                   "traded_value_estimate": round(traded_value, 2),
                   "volume_source": "captured bar volume"},
        "price": {"last": last.close, "session_open": first.open,
                  "session_high": session_high,
                  "distance_from_high": round(distance_from_high, 6)},
        "momentum": momentum_strength,
        "acceleration_label": acceleration_strength,
        "volume_label": volume_strength,
        "last_bar": last.timestamp.isoformat(),
        "bars": len(rows),
    }


def rank_candidates(session: SessionData,
                    ai_prior: dict[str, float] | None = None) -> list[dict]:
    """Score and rank every eligible symbol in the captured universe.

    ``ai_prior`` is the optional trained daily probability per symbol
    (src/signals/ai_model.py). It is ATTACHED to every row for the record and
    never changes a rule score: the ordering here is pure rule score. The
    prior's only lever is the bounded tie-break applied in select_one.
    """
    scored = []
    for symbol in sorted(session.bars):
        row = score_symbol(symbol, session.bars[symbol], session)
        if row is not None:
            scored.append(row)
    if ai_prior:
        ai_model.attach(ai_prior, scored)
    scored.sort(key=lambda row: (-row["score"], row["symbol"]))
    return scored


# --------------------------------------------------------------- selection

def select_one(session: SessionData, quality: QualityReport,
               ai_prior: dict[str, float] | None = None,
               ai_status: dict | None = None) -> ScanResult:
    """The whole decision: DATA BLOCKED, market NO TRADE, or ONE candidate.

    The AI prior, when active, may reorder a near-tie and (only if the owner
    turned the veto on) refuse the weakest sliver of its own ranking. It can
    never create a candidate, raise a score, or override a clear rule gap.
    """
    coverage_text = (f"{quality.symbols_with_bars}/{quality.symbols_expected} "
                     f"({quality.coverage:.1%})")
    if quality.status == DATA_BLOCKED:
        return ScanResult(status=DATA_BLOCKED,
                          reason=quality.reason, quality=quality,
                          market={}, coverage_text=coverage_text)

    context = market_context(session)
    if ai_status:
        context["ai"] = ai_status
    ranked = rank_candidates(session, ai_prior)

    # The market gate is reported first: when the whole universe is falling it
    # is the dominant, honest explanation, and a momentum strategy must not
    # fight it (owner spec section 6).
    if context.get("status") != "SUPPORTIVE":
        return ScanResult(
            status=NO_TRADE,
            reason=f"market not supportive: {context.get('reason')}",
            quality=quality, market=context, ranked=ranked[:10],
            coverage_text=coverage_text)

    if not ranked:
        return ScanResult(
            status=NO_TRADE,
            reason=("KMIALL captured but no symbol passed the momentum plus "
                    "volume gates"),
            quality=quality, market=context, ranked=[], coverage_text=coverage_text)

    # Bounded AI routing, in one place and in this order:
    #   1. a near-tie between the top two rule scores may be reordered by the
    #      trained prior (never a clear rule win);
    #   2. if the owner enabled the veto, a winner sitting in the weakest sliver
    #      of the model's own ranking is refused, and the refusal is reported as
    #      the decision rather than silently turned into a lower-ranked entry.
    ai_note = ""
    if ai_prior and ai_status and ai_status.get("active"):
        index, ai_note = ai_model.tie_break_winner(ranked)
        if index == 1:
            ranked[0], ranked[1] = ranked[1], ranked[0]

    winner = ranked[0]
    if winner["score"] < config.MIN_SIGNAL_SCORE:
        return ScanResult(
            status=NO_TRADE,
            reason=(f"top score {winner['score']:.2f} on {winner['symbol']} is "
                    f"below the {config.MIN_SIGNAL_SCORE:g} minimum"),
            quality=quality, market=context, ranked=ranked[:10],
            coverage_text=coverage_text)

    passed, veto_reason = ai_model.gate(winner.get("ai_probability"),
                                        winner.get("ai_percentile"))
    if not passed:
        return ScanResult(
            status=NO_TRADE,
            reason=(f"AI veto refused {winner['symbol']} (rule score "
                    f"{winner['score']:.2f}): {veto_reason}"),
            quality=quality, market=context, ranked=ranked[:10],
            coverage_text=coverage_text)

    reason = "strongest current momentum plus volume"
    if ai_note and ai_note.startswith("AI prior promoted"):
        reason = f"strongest current momentum plus volume; {ai_note}"
    elif winner.get("ai_probability") is not None:
        reason = (f"strongest current momentum plus volume; AI prior "
                  f"{winner['ai_probability']:.3f} "
                  f"({winner['ai_percentile']:.0%} percentile)")
    return ScanResult(status=TRADE, reason=reason,
                      quality=quality, market=context, candidate=winner,
                      ranked=ranked[:10], coverage_text=coverage_text)


# ------------------------------------------------------------------- messages

def target_price(entry: float) -> float:
    """The +2% target is always measured from the ACTUAL entry price."""
    return round(entry * (1.0 + config.TARGET_PCT), 4)


def signal_message(candidate: dict, market: dict, entry: float,
                   entry_time: datetime) -> str:
    target = target_price(entry)
    return (
        "QUANT LONG SIGNAL\n\n"
        f"Symbol: {candidate['symbol']}\n"
        f"Entry: {entry:.4f}\n"
        f"Target: {target:.4f} (+{config.TARGET_PCT * 100:.1f}%)\n"
        f"Momentum: {candidate['momentum']}\n"
        f"Momentum acceleration: {candidate['acceleration_label']}\n"
        f"Volume acceleration: {candidate['volume_label']}\n"
        f"Relative volume: {candidate['volume']['relative']:.2f}\n"
        f"Market: {market.get('status', 'UNKNOWN')}\n"
        f"Reason: strongest current KMIALL momentum + volume acceleration\n"
        f"Entry time: {entry_time:%H:%M} PKT\n"
        f"Score: {candidate['score']:.2f}/100\n\n"
        "ONE TRADE ONLY.\n"
        f"Target: +{config.TARGET_PCT * 100:.1f}%."
    )


def no_trade_message(quality: QualityReport, market: dict) -> str:
    return (
        "NO TRADE\n\n"
        f"KMIALL scanned: {quality.symbols_with_bars}/{quality.symbols_expected}\n"
        f"Market: {market.get('status', 'UNKNOWN')}\n"
        f"Reason: no sufficiently strong momentum + volume candidate.\n"
        f"Detail: {market.get('reason', 'no context available')}\n"
        f"Source: {quality.source}"
    )


def scan_blocked_message(quality: QualityReport) -> str:
    newest = quality.newest_bar.isoformat() if quality.newest_bar else "none"
    lines = [
        "SCAN BLOCKED",
        "",
        f"KMIALL coverage: {quality.symbols_with_bars}/{quality.symbols_expected}"
        f" ({quality.coverage:.1%})",
        f"Bar history: {quality.symbols_with_history} symbol(s) hold the "
        f"{config.MIN_BARS_PER_SYMBOL} bars the strategy needs",
        f"Fresh coverage: {quality.fresh_coverage:.1%}",
        f"Reason: {quality.reason}",
        f"Source: {quality.source}",
        f"Resolution: {quality.resolution}",
        f"Newest bar: {newest}",
    ]
    # What the source could not see travels with the block. Two lines are
    # enough for a phone message; the full list is in the observation.
    for note in quality.notes[:2]:
        lines.append(f"Note: {note}")
    lines.append("No trade issued. This is a DATA failure, not a market decision.")
    return "\n".join(lines)


def target_hit_message(symbol: str, entry: float, target: float,
                       exit_price: float, hit_at: datetime) -> str:
    return (
        "TARGET HIT\n\n"
        f"Symbol: {symbol}\n"
        f"Entry: {entry:.4f}\n"
        f"Target: {target:.4f} (+{config.TARGET_PCT * 100:.1f}%)\n"
        f"Exit reference: {exit_price:.4f}\n"
        f"Time: {hit_at:%H:%M} PKT\n\n"
        "Paper position closed. The quant stays online and reports the close."
    )
