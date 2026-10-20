"""Authoritative ICT/SMC intraday scanner (historical import path retained).

The momentum strategy is removed from the decision path. Capture validation
and the public SessionData/ScanResult contracts stay stable for all runners.
Only causal sweep -> structure shift -> FVG -> retest candidates can enter.
The old RSI diagnostic remains solely for reproducing the HCAR postmortem.
Asia/Karachi, UTC+5. Signal-only, no broker orders and no assured returns.
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
from src.signals import smc

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
    #: The population a ranking can actually use: a symbol needs BOTH enough
    #: bars to be scored AND a bar inside the staleness window, or the trace it
    #: contributes is dead. Reported next to the whole-universe coverage, which
    #: keeps its own floor (redesign 2026-10-15, see src/config.py).
    rankable_symbols: int = 0
    #: The volume leaders, which are the symbols a candidate can come from.
    #: A ranking off stale leaders is what the freshness floor guarded against,
    #: so it is the leaders that must be fresh (measured: 19 to 20 of 20 at
    #: every instant of the real 2026-10-13 session tape).
    leader_symbols: int = 0
    leaders_fresh: int = 0
    leaders_fresh_share: float = 0.0
    #: True when the capture is simply younger than the strategy needs: the
    #: bar source has not been alive for MIN_BARS_PER_SYMBOL minutes yet, so no
    #: ranking can exist. A runner pauses on this; it is not a fault.
    warming_up: bool = False
    warmup_minutes_remaining: float = 0.0
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
            "rankable_symbols": self.rankable_symbols,
            "leader_symbols": self.leader_symbols,
            "leaders_fresh": self.leaders_fresh,
            "leaders_fresh_share": round(self.leaders_fresh_share, 4),
            "warming_up": self.warming_up,
            "warmup_minutes_remaining": round(self.warmup_minutes_remaining, 2),
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
                if stamp + timedelta(minutes=1) > as_of:
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
            if bar.timestamp + timedelta(minutes=1) <= as_of
        ]
        for symbol, rows in tape.bars.items()
    }
    bars = {symbol: rows for symbol, rows in bars.items() if rows}
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

    # The population a ranking can use: scored symbols that also printed inside
    # the staleness window. A symbol with 40 bars whose last print was half an
    # hour ago is still not a candidate, and a symbol with a fresh print but 3
    # bars cannot be scored, so neither half alone is the measure.
    rankable = sum(
        1 for rows in session.bars.values()
        if len(rows) >= config.MIN_BARS_PER_SYMBOL
        and session.as_of - rows[-1].timestamp
        <= timedelta(minutes=config.STALENESS_MINUTES)
    )

    # The leader slice: the symbols with the most session traded value, which
    # is where a candidate comes from. Freshness on these is the honest guard
    # against ranking and entering off prices that stopped moving. A symbol
    # that traded nothing has no value to rank on and is not a leader.
    traded = sorted(
        ((sym, sum(bar.volume or 0.0 for bar in rows))
         for sym, rows in session.bars.items()
         if len(rows) >= config.MIN_BARS_PER_SYMBOL),
        key=lambda item: (-item[1], item[0]),
    )
    leaders = traded[:config.LEADER_SLICE]
    leaders_fresh = sum(
        1 for sym, _value in leaders
        if session.as_of - session.bars[sym][-1].timestamp
        <= timedelta(minutes=config.STALENESS_MINUTES)
    )
    leader_share = leaders_fresh / max(len(leaders), 1)

    # A capture younger than the bars it is asked to hold: no symbol can carry
    # MIN_BARS_PER_SYMBOL one-minute bars before that many minutes of tape
    # exist, so this is a warm-up with a countdown rather than a data failure.
    # Measured 2026-10-14 (run 38530614304): a runner starting mid-band was
    # below the history floor for its first cycles and each one was counted as
    # a coverage fault, which is what made a working tape look like a dead one.
    span_minutes = ((session.as_of - oldest).total_seconds() / 60.0
                    if oldest is not None else 0.0)
    # `with_bars > 0` matters: a capture that produced nothing at all is a dead
    # source, not a countdown, and the runner already reports it as the
    # source fault it is (scripts/scan_loop.py raises on a tape with no bars).
    warming_up = (with_bars > 0
                  and ready == 0
                  and history_coverage < config.MIN_HISTORY_COVERAGE_PCT
                  and span_minutes < config.WARMUP_GRACE_MINUTES)
    warmup_left = max(0.0, config.WARMUP_GRACE_MINUTES - span_minutes)

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
            rankable_symbols=rankable, leader_symbols=len(leaders),
            leaders_fresh=leaders_fresh, leaders_fresh_share=leader_share,
            warming_up=warming_up,
            warmup_minutes_remaining=(warmup_left if warming_up else 0.0),
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
        # Below the floor because the capture is young: a countdown, not a
        # failure. The wording still names the bar history and the bar count,
        # because that is what a reader has to act on either way.
        if warming_up:
            return blocked(
                f"bar history: only {ready}/{with_bars} captured symbols "
                f"({history_coverage:.1%}) hold the "
                f"{config.MIN_BARS_PER_SYMBOL} bars the strategy needs, below "
                f"the {config.MIN_HISTORY_COVERAGE_PCT:.0%} floor; the bar "
                f"source has been alive {span_minutes:.0f} of the "
                f"{config.WARMUP_GRACE_MINUTES} minutes this needs, so the scan "
                f"is WARMING UP and resumes on its own in about "
                f"{warmup_left:.0f} minute(s)")
        return blocked(
            f"bar history: only {ready}/{with_bars} captured symbols "
            f"({history_coverage:.1%}) hold the {config.MIN_BARS_PER_SYMBOL} "
            f"bars the strategy needs, below the "
            f"{config.MIN_HISTORY_COVERAGE_PCT:.0%} floor, so a ranking built "
            f"now would say nothing about the market")
    # Freshness is judged where it decides something: the leader slice a
    # candidate can come from, and the count of symbols a ranking can use at
    # all. The illiquid tail (symbols that print less often than the staleness
    # window) is counted and reported rather than allowed to block a market
    # that has hundreds of rankable symbols (SO-3, redesign 2026-10-15).
    if len(leaders) and leader_share < config.MIN_LEADER_FRESH_SHARE:
        stale_leaders = [sym for sym, _value in leaders
                         if session.as_of - session.bars[sym][-1].timestamp
                         > timedelta(minutes=config.STALENESS_MINUTES)]
        return blocked(
            f"stale leaders: {len(leaders) - leaders_fresh} of the top "
            f"{len(leaders)} traded symbols have no bar within "
            f"{config.STALENESS_MINUTES:g} minutes of the scan time "
            f"({', '.join(stale_leaders[:8])}); a candidate would be chosen "
            f"from prices that stopped moving")
    rankable_share = rankable / max(with_bars, 1)
    if (rankable < config.MIN_RANKABLE_SYMBOLS
            and rankable_share < config.MIN_RANKABLE_SHARE):
        return blocked(
            f"too few rankable symbols: {rankable} of {with_bars} captured "
            f"symbols hold the {config.MIN_BARS_PER_SYMBOL} bars and a bar "
            f"within {config.STALENESS_MINUTES:g} minutes "
            f"({rankable_share:.0%}), so a ranking could not describe a "
            f"market; {len(stale)} captured symbols are idle longer than that "
            f"(whole-universe fresh coverage {fresh_coverage:.1%})")
    if age is not None and age > config.STALENESS_MINUTES:
        return blocked(
            f"newest bar is {age:.1f} minutes old, above the "
            f"{config.STALENESS_MINUTES:g} minute freshness limit")
    if not session.volume_available:
        return blocked(
            "the source carries no volume, and this strategy requires volume "
            "confirmation; a price-only proxy would be a different strategy, so "
            "the scan is blocked instead of guessed")

    return QualityReport(
        status="OK",
        reason=(f"coverage, freshness, history, structure and volume present; "
                f"{rankable} of {with_bars} captured symbols rankable, "
                f"{leaders_fresh}/{len(leaders)} of the volume leaders fresh, "
                f"{len(stale)} symbol(s) idle longer than "
                f"{config.STALENESS_MINUTES:g} minutes"),
        coverage=coverage, fresh_coverage=fresh_coverage, symbols_expected=expected,
        symbols_with_bars=with_bars, symbols_missing=missing,
        symbols_stale=tuple(sorted(stale)), newest_bar=newest, oldest_bar=oldest,
        data_age_minutes=age, duplicate_bars=session.duplicate_bars,
        malformed_bars=malformed, impossible_ohlc=impossible,
        zero_volume_bars=zero_volume, volume_available=True,
        symbols_with_history=ready, history_coverage=history_coverage,
        rankable_symbols=rankable, leader_symbols=len(leaders),
        leaders_fresh=leaders_fresh, leaders_fresh_share=leader_share,
        source=session.source, notes=session.notes,
    )


# ------------------------------------------------------------ market context

def market_context(session: SessionData) -> dict:
    """Breadth and direction of the whole captured KMIALL universe."""
    returns: dict[str, float] = {}
    session_open = datetime.combine(session.day, time(*open_time(session.day)),
                                    tzinfo=session.as_of.tzinfo)
    for sym, rows in session.bars.items():
        completed = [bar for bar in rows if session_open <= bar.timestamp
                     and bar.timestamp + timedelta(minutes=1) <= session.as_of]
        if not completed or completed[0].open <= 0:
            continue
        returns[sym] = completed[-1].close / completed[0].open - 1.0
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
                  f"{config.MIN_BREADTH:.0%} breadth reference (context only)")
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

def secondary_confirmation(rows: list[MinuteBar]) -> dict:
    """Return causal breakout/RSI confirmation diagnostics for completed bars."""
    count = config.BREAKOUT_CONFIRMATION_BARS
    prior = rows[-count - 1:-1]
    prior_close_high = max((bar.close for bar in prior), default=None)
    rsi14 = _wilder_rsi([bar.close for bar in rows])
    breakout = prior_close_high is not None and rows[-1].close > prior_close_high
    rsi_pass = rsi14 is not None and rsi14 >= config.MIN_CONFIRMATION_RSI
    return {
        "breakout_bars": count,
        "prior_close_high": prior_close_high,
        "breakout_passed": breakout,
        "rsi14": rsi14,
        "rsi_passed": rsi_pass,
        "passed": breakout and rsi_pass,
    }


def _wilder_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI using only completed closes; None when data is insufficient."""
    if period < 1 or len(closes) < period + 1:
        return None
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        return None
    changes = [closes[index] - closes[index - 1]
               for index in range(1, len(closes))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def score_symbol(symbol: str, rows: list[MinuteBar], session: SessionData) -> dict | None:
    """Historical API name, now evaluates only the ICT/SMC sequence."""
    return smc.candidate(symbol, rows, session)


def rank_candidates(session: SessionData,
                    ai_prior: dict[str, float] | None = None) -> list[dict]:
    """Rank confirmed setups; the old daily-model prior has no entry authority."""
    ranked = [row for symbol in sorted(session.bars)
              if (row := score_symbol(symbol, session.bars[symbol], session)) is not None]
    return sorted(ranked, key=lambda row: (-row["score"], row["symbol"]))


def select_one(session: SessionData, quality: QualityReport,
               ai_prior: dict[str, float] | None = None,
               ai_status: dict | None = None) -> ScanResult:
    """At most one fully confirmed long, never a momentum/RSI fallback."""
    coverage = f"{quality.symbols_with_bars}/{quality.symbols_expected} ({quality.coverage:.1%})"
    if quality.status == DATA_BLOCKED:
        return ScanResult(DATA_BLOCKED, quality.reason, quality, {}, coverage_text=coverage)
    context = market_context(session)
    context["ai"] = {"active": False, "reason": "ICT/SMC rules do not use the daily momentum prior"}
    ranked = rank_candidates(session)
    # Broad panic is a risk veto; ordinary weak breadth is not a momentum
    # entry filter on this reversal strategy.
    if context.get("median_return") is None or context["median_return"] < config.MAX_MARKET_DROP:
        return ScanResult(NO_TRADE, "market not supportive: broad selloff or unknown context",
                          quality, context, ranked=ranked, coverage_text=coverage)
    if not ranked:
        return ScanResult(NO_TRADE, "no symbol passed the ICT/SMC sweep, MSS, FVG and retest gates",
                          quality, context, ranked=[], coverage_text=coverage)
    return ScanResult(TRADE, "confirmed sell-side sweep, bullish MSS, FVG retest in discount",
                      quality, context, candidate=ranked[0], ranked=ranked,
                      coverage_text=coverage)


# ------------------------------------------------------------------- messages

def target_price(entry: float) -> float:
    """The +2% target is always measured from the ACTUAL entry price."""
    return round(entry * (1.0 + config.TARGET_PCT), 4)


def signal_message(candidate: dict, market: dict, entry: float,
                   entry_time: datetime) -> str:
    stop = candidate["stop_loss"]
    return (
        "QUANT LONG SIGNAL - PAPER REFERENCE\n\n"
        f"Symbol: {candidate['symbol']}\n"
        f"Entry price: {entry:.4f}\n"
        f"Target: {target_price(entry):.4f} (+{config.TARGET_PCT * 100:.1f}% gross)\n"
        f"Stop Loss: {stop:.4f}\n"
        "Reason: sell-side sweep, bullish structure shift, FVG first retest in discount\n"
        f"Strategy: {config.SCANNER_VERSION}\n"
        f"Entry time: {entry_time:%H:%M:%S} PKT\n"
        "Entry is the completed retest close, not a confirmed executable fill.\n"
        "ONE TRADE ONLY. Target is not a guaranteed return."
    )


def no_trade_message(quality: QualityReport, market: dict) -> str:
    return ("NO TRADE\n\n"
            f"KMIALL scanned: {quality.symbols_with_bars}/{quality.symbols_expected}\n"
            f"Market: {market.get('status', 'UNKNOWN')}\n"
            f"Market context: {market.get('reason', 'unavailable')}\n"
            "Reason: no actionable ICT/SMC setup with structural risk and 2% target room.\n"
            f"Source: {quality.source}")


def scan_blocked_message(quality: QualityReport) -> str:
    newest = quality.newest_bar.isoformat() if quality.newest_bar else "none"
    lines = [
        "SCAN BLOCKED",
        "",
        f"KMIALL coverage: {quality.symbols_with_bars}/{quality.symbols_expected}"
        f" ({quality.coverage:.1%})",
        f"Bar history: {quality.symbols_with_history} symbol(s) hold the "
        f"{config.MIN_BARS_PER_SYMBOL} bars the strategy needs",
        f"Rankable now: {quality.rankable_symbols} symbol(s) (scored and "
        f"fresh), of which {quality.leaders_fresh}/{quality.leader_symbols} "
        f"are volume leaders",
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
    if quality.warming_up:
        # A young bar source is not a failure and must not read like one: the
        # scan resumes by itself once the bars exist (redesign 2026-10-15).
        lines.append(
            f"Warming up: about {quality.warmup_minutes_remaining:.0f} more "
            f"minute(s) of bars and the scan resumes on its own.")
        lines.append("No trade issued. The bar source is still filling, not "
                     "broken.")
        return "\n".join(lines)
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
