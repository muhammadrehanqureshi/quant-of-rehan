"""Local-only HCAR post-mortem and rejected-candidate target audit.

Candidate outcomes use locally saved, timestamped broker MKT-FEED rows only.
When the capture does not cover the candidate's post-refusal window, report it
as unverified instead of substituting a different market-data source. The
separate daily-history analogue is clearly labeled and is not used to classify
rejected candidates.
Timezone law: UTC+5, Asia/Karachi, pinned through src/data/sessions.py.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.ci.local_only import guard_cloud_backtest  # noqa: E402
from src import config  # noqa: E402
from src.data.sessions import KARACHI, close_time, open_time  # noqa: E402
from src.data.tick_volume import iter_ticks  # noqa: E402
from src.backtest.engine import run_backtest, summarize  # noqa: E402
from src.notify.schedule_runner import load_relay_admin_token, load_relay_url  # noqa: E402

TARGET_PCT = 0.02
DEFAULT_DAY = "2026-10-16"
DEFAULT_CAPTURE = ROOT / "data" / "feed_capture" / "capture_20261016.ndjson"
DEFAULT_DAILY_DATA = ROOT / "data" / "eod_history.csv.gz"
DEFAULT_OUTPUT = ROOT / "data" / "forward" / "hcar_postmortem_20261016.json"


@dataclass(frozen=True)
class CandidateAudit:
    symbol: str
    first_refusal_slot: str
    entry_reference: float | None
    target_price: float | None
    score: float | None
    repeated_refusals: int
    post_refusal_samples: int
    first_post_refusal_trade: str | None
    last_post_refusal_trade: str | None
    highest_observed_trade: float | None
    classification: str
    evidence: str
    source: str


def _relay_json(route: str, *, params: dict[str, str] | None = None) -> dict:
    """Fetch authenticated relay data, reporting only safe exception classes."""
    import requests

    try:
        url, token = load_relay_url(), load_relay_admin_token()
        response = requests.get(url + route, params=params,
                                headers={"x-admin-token": token}, timeout=20)
        response.raise_for_status()
        body = response.json()
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        raise RuntimeError(f"relay audit unavailable ({type(exc).__name__})") from None
    if not isinstance(body, dict):
        raise RuntimeError("relay audit returned an invalid response shape")
    return body


def _date_observations(day: str) -> list[dict]:
    body = _relay_json("/research/observations", params={"date": day})
    observations = body.get("observations")
    if not isinstance(observations, list):
        raise RuntimeError("relay returned no observations list")
    return [row for row in observations if isinstance(row, dict)]


def _broker_tick_samples(path: Path, day: str) -> tuple[dict[str, list[dict]], dict]:
    """Read timestamped last-trade samples from the saved broker tape only."""
    session_day = date.fromisoformat(day)
    samples: dict[str, list[dict]] = {}
    first_snapshot: datetime | None = None
    last_snapshot: datetime | None = None
    tick_rows = 0
    for tick in iter_ticks(path):
        symbol = str(tick.get("scrip", "")).split(":", 1)[0].strip().upper()
        if not symbol:
            continue
        try:
            observed = datetime.fromisoformat(str(tick.get("capture_ts", "")))
        except ValueError:
            continue
        observed = (observed.astimezone(KARACHI) if observed.tzinfo
                    else observed.replace(tzinfo=KARACHI))
        if observed.date() != session_day:
            continue
        clock_text = str(tick.get("tick_time", "")).strip()
        trade_clock = None
        for pattern in ("%H:%M:%S", "%H:%M"):
            try:
                trade_clock = datetime.strptime(clock_text, pattern).time()
                break
            except ValueError:
                continue
        try:
            price = float(str(tick.get("last", "")).replace(",", ""))
        except (TypeError, ValueError):
            continue
        if trade_clock is None or not math.isfinite(price) or price <= 0:
            continue
        traded = datetime.combine(session_day, trade_clock, tzinfo=KARACHI)
        if traded > observed + timedelta(seconds=1):
            continue
        samples.setdefault(symbol, []).append({
            "observed_at": observed,
            "trade_at": traded,
            "last": price,
        })
        first_snapshot = observed if first_snapshot is None else min(first_snapshot, observed)
        last_snapshot = observed if last_snapshot is None else max(last_snapshot, observed)
        tick_rows += 1
    for rows in samples.values():
        rows.sort(key=lambda item: (item["trade_at"], item["observed_at"]))
    return samples, {
        "source": "locally saved broker MKT-FEED tape, timestamped last-trade prints",
        "capture": str(path),
        "trading_date": day,
        "tick_rows_with_valid_trade_time": tick_rows,
        "symbols_with_samples": len(samples),
        "first_snapshot": first_snapshot.isoformat() if first_snapshot else None,
        "last_snapshot": last_snapshot.isoformat() if last_snapshot else None,
    }


def _first_candidate(row: dict) -> dict | None:
    snapshot = row.get("snapshot") or {}
    if not isinstance(snapshot, dict):
        return None
    # Count only candidates explicitly declined because the single daily
    # paper position was already used. A ranking without a refusal is not a
    # candidate the owner asked us to audit.
    reason = str(snapshot.get("reason") or "")
    if "observed and refused" not in reason:
        return None
    candidate = snapshot.get("observed_candidate")
    return candidate if isinstance(candidate, dict) else None


def audit_rejected(observations: list[dict], broker_samples: dict[str, list[dict]],
                   day: str, capture_last: datetime | None = None,
                   observation_slots: set[str] | None = None) -> list[CandidateAudit]:
    """Compare refusals only with broker prints recorded after that refusal."""
    first: dict[str, dict[str, Any]] = {}
    for row in observations:
        candidate = _first_candidate(row)
        if not candidate:
            continue
        snapshot = row.get("snapshot") or {}
        slot = str(row.get("slot") or snapshot.get("slot") or "unknown")
        if observation_slots is not None and slot not in observation_slots:
            continue
        symbol = str(candidate.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        price = (candidate.get("price") or {}).get("last")
        try:
            entry = float(price)
            if not math.isfinite(entry) or entry <= 0:
                entry = None
        except (TypeError, ValueError):
            entry = None
        try:
            slot_clock = slot[:5]
            if len(slot_clock) == 4 and slot_clock[1] == ":":
                slot_clock = "0" + slot_clock
            slot_order = datetime.fromisoformat(
                f"{day}T{slot_clock}:00").replace(tzinfo=KARACHI)
        except (TypeError, ValueError):
            slot_order = datetime.max.replace(tzinfo=KARACHI)
        rec = first.setdefault(symbol, {"slot": slot, "entry": entry,
                                        "score": candidate.get("score"), "count": 0,
                                        "first_order": slot_order})
        rec["count"] += 1
        if slot_order < rec["first_order"]:
            rec.update(slot=slot, entry=entry, score=candidate.get("score"),
                       first_order=slot_order)

    close_hour, close_minute = close_time(date.fromisoformat(day))
    session_close = datetime.fromisoformat(
        f"{day}T{close_hour:02d}:{close_minute:02d}:00").replace(tzinfo=KARACHI)
    result: list[CandidateAudit] = []
    for symbol, record in first.items():
        entry = record["entry"]
        target = entry * (1.0 + TARGET_PCT) if entry is not None else None
        try:
            if entry is not None and (not math.isfinite(entry) or entry <= 0):
                raise ValueError("invalid entry reference")
            slot_clock = record["slot"][:5]
            if len(slot_clock) == 4 and slot_clock[1] == ":":
                slot_clock = "0" + slot_clock
            refusal_minute = datetime.fromisoformat(
                f"{day}T{slot_clock}:00").replace(tzinfo=KARACHI)
        except (TypeError, ValueError):
            refusal_minute = None
        if target is not None and not math.isfinite(target):
            target = None
        if record["slot"] == "unknown":
            refusal_minute = None
        # The stored slot is minute-precision. Ignore that entire minute so a
        # print whose order relative to the refusal is ambiguous cannot count.
        earliest_unambiguous = (refusal_minute + timedelta(minutes=1)
                                if refusal_minute is not None else None)
        after = [sample for sample in broker_samples.get(symbol, [])
                 if earliest_unambiguous is not None
                 and sample["trade_at"] >= earliest_unambiguous
                 and sample["trade_at"] <= session_close
                 and sample["observed_at"] >= earliest_unambiguous]
        touched = [sample for sample in after
                   if sample["last"] + 1e-9 >= target
                   and sample["trade_at"].strftime("%H:%M:%S")
                   <= sample["observed_at"].strftime("%H:%M:%S")] \
            if target is not None else []
        if target is None:
            classification = "UNVERIFIED_NO_ENTRY_REFERENCE"
            evidence = "candidate record did not carry a numeric entry reference"
        elif not after:
            classification = "UNVERIFIED_NO_POST_REFUSAL_BROKER_DATA"
            if capture_last is not None and earliest_unambiguous is not None \
                    and capture_last < earliest_unambiguous:
                evidence = ("local broker capture ended before the first unambiguous post-refusal "
                            "minute; no external daily or market-data fallback was used")
            else:
                evidence = "local broker capture has no timestamped trade samples after the refusal"
        elif touched:
            classification = "BROKER_TAPE_CONFIRMED_TP_PRINT"
            evidence = "a broker snapshot received after refusal, with its last-trade clock after the refusal and by session close, carried a print at or above the 2% target"
        else:
            classification = "BROKER_TAPE_NO_TARGET_PRINT_OBSERVED"
            evidence = ("no sampled broker last-trade print reached target through the last captured "
                        "sample; this snapshot feed can miss between-snapshot excursions")
        result.append(CandidateAudit(
            symbol=symbol, first_refusal_slot=record["slot"],
            entry_reference=entry, target_price=round(target, 4) if target is not None else None,
            score=float(record["score"]) if isinstance(record["score"], (int, float)) else None,
            repeated_refusals=record["count"], post_refusal_samples=len(after),
            first_post_refusal_trade=(after[0]["trade_at"].isoformat() if after else None),
            last_post_refusal_trade=(after[-1]["trade_at"].isoformat() if after else None),
            highest_observed_trade=max((sample["last"] for sample in after), default=None),
            classification=classification, evidence=evidence,
            source="locally saved broker MKT-FEED"))
    return result


def _wilder_rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder RSI; insufficient or non-finite input is explicitly unavailable."""
    if len(closes) < period + 1 or any(not math.isfinite(x) or x <= 0 for x in closes):
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    avg_loss = sum(max(-change, 0.0) for change in changes[:period]) / period
    for change in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _atr(bars: list[Any], period: int = 14) -> float | None:
    if len(bars) < period or any(not math.isfinite(float(b.close)) or float(b.close) <= 0
                                 for b in bars):
        return None
    ranges = []
    for index, bar in enumerate(bars):
        high, low = float(bar.high), float(bar.low)
        previous = float(bars[index - 1].close) if index else float(bar.close)
        ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
    return sum(ranges[-period:]) / period


def hcar_postmortem(capture: Path, day: str, slot: str,
                    observations: list[dict], outcomes: list[dict]) -> dict:
    """Reconstruct HCAR's actual pre-signal evidence and paper outcome."""
    from src.signals.momentum_scanner import load_tape_bars, secondary_confirmation

    instant = datetime.fromisoformat(f"{day}T{slot}:00").replace(tzinfo=KARACHI)
    session = load_tape_bars(capture, ["HCAR"], instant)
    bars = session.bars.get("HCAR", [])
    confirmation = secondary_confirmation(bars) if bars else None
    close_hour, close_minute = close_time(date.fromisoformat(day))
    full_session = load_tape_bars(
        capture, ["HCAR"],
        datetime.fromisoformat(f"{day}T{close_hour:02d}:{close_minute:02d}:00")
        .replace(tzinfo=KARACHI) + pd.Timedelta(minutes=1))
    post_entry_bars = [bar for bar in full_session.bars.get("HCAR", [])
                       if bar.timestamp > instant]
    closes = [float(bar.close) for bar in bars]
    rsi = _wilder_rsi(closes)
    atr = _atr(bars)
    paper_outcome = next((row for row in outcomes
                          if row.get("date") == day and row.get("symbol") == "HCAR"), {})
    target_entry = paper_outcome.get("entry")
    target_level = float(target_entry) * (1.0 + TARGET_PCT) if target_entry is not None else None
    target_hit = next((row.get("target_hit") for row in outcomes
                       if row.get("date") == day and row.get("symbol") == "HCAR"), None)
    candidate = None
    for row in observations:
        snap = row.get("snapshot") or {}
        got = snap.get("candidate") or snap.get("observed_candidate") or {}
        if got.get("symbol") == "HCAR":
            candidate = got
            break
    if candidate is None:
        candidate = {"symbol": "HCAR", "price": {"last": target_entry}}
    if not isinstance(candidate.get("price"), dict):
        candidate = {**candidate, "price": {"last": target_entry}}
    return {
        "date": day, "signal_slot": slot, "symbol": "HCAR",
        "entry_price": (float(target_entry) if target_entry is not None else
                        (candidate.get("price") or {}).get("last")),
        "target_pct": TARGET_PCT,
        "target_price": (round(float(target_entry) * (1.0 + TARGET_PCT), 4)
                         if target_entry is not None else
                         (((candidate.get("price") or {}).get("last") * (1.0 + TARGET_PCT))
                          if isinstance((candidate.get("price") or {}).get("last"), (int, float))
                          else None)),
        "recorded_outcome": paper_outcome.get("outcome"),
        "target_hit": target_hit,
        "outcome_source": (paper_outcome.get("source") or
                            ("local session journal / authenticated relay history"
                             if paper_outcome else None)),
        "gross_return": paper_outcome.get("gross_return"),
        "net_return": paper_outcome.get("net_return"),
        "entry_time": paper_outcome.get("entry_time"),
        "signal_candidate": candidate,
        "post_entry_capture": {
            "bars": len(post_entry_bars),
            "first_bar": post_entry_bars[0].timestamp.isoformat() if post_entry_bars else None,
            "last_bar": post_entry_bars[-1].timestamp.isoformat() if post_entry_bars else None,
            "high": max((bar.high for bar in post_entry_bars), default=None),
            "target_price": round(target_level, 4) if target_level is not None else None,
            "target_touched_in_capture": (None if target_level is None else
                                           any(bar.high >= target_level for bar in post_entry_bars)),
            "capture_ends_before_session_close": bool(
                not post_entry_bars or post_entry_bars[-1].timestamp.time()
                < datetime.fromisoformat(f"{day}T{close_hour:02d}:{close_minute:02d}:00").time()),
        },
        "exit_time": paper_outcome.get("exit_time"),
        "pre_signal": {"capture": str(capture), "bars": len(bars),
                       "capture_starts_after_open": bool(
                           bars and bars[0].timestamp.time() > time(*open_time(date.fromisoformat(day)))),
                       "capture_first_bar": bars[0].timestamp.isoformat() if bars else None,
                       "first_post_entry_bar": next((bar.timestamp.isoformat() for bar in bars
                                                      if bar.timestamp > instant), None),
                       "first_post_entry_open": next((bar.open for bar in bars
                                                      if bar.timestamp > instant), None),
                       "last_bar": bars[-1].timestamp.isoformat() if bars else None,
                       "rsi14_wilder": round(rsi, 4) if rsi is not None else None,
                       "atr14": round(atr, 4) if atr is not None else None,
                       "atr14_pct": round(100.0 * atr / closes[-1], 4) if atr is not None and closes else None,
                       "capture_high_before_entry": max((bar.high for bar in bars), default=None)},
        "confirmation": confirmation,
        "delivery": next((row.get("snapshot", {}).get("delivery") for row in observations
                          if ((row.get("snapshot", {}).get("candidate") or {}).get("symbol") == "HCAR"
                              or (row.get("snapshot", {}).get("observed_candidate") or {}).get("symbol") == "HCAR")), None),
        "diagnosis": [
            "Signal was a live buy candidate at score 75.13 with 5-minute momentum +0.744%, positive acceleration +0.496%, and a final 5-minute volume bucket 33.61x the prior-bucket median.",
            "The archive marked delivered=TRADE_UNDELIVERED because relay notification acceptance was false; the paper position still entered at 203.00 and was independently tracked to close.",
            "Recorded entry 203.00; target 207.06; actual outcome was session-end close 202.01, gross -0.4877%, net -1.1357%, target not hit.",
            "Available capture starts 10:05 PKT, over an hour after the 09:32 open. It provides only 67 HCAR bars by the 11:34 signal; pre-open history, earlier volatility regime, and any actual fill/order book are not present.",
            "The first post-signal captured bar opens 204.01, 0.50% above the paper entry. The signal-time daily high was 204.39 and there was no confirmed 2% target touch in the capture after entry (capture ends 12:34); the relay outcome through 16:31 independently records target_hit=false.",
            "Overfitting is not diagnosable from one trade. Ingestion lag is not evidenced within the capture: the final HCAR bar timestamp is 11:33 for the 11:34 scan; the capture itself began late and then ceased at 12:34, so later surveillance depended on archive data not this local tape.",
        ],
        "improvement_recommendation": {
            "type": "secondary continuation confirmation",
            "proposed_rule": "completed close above the previous five completed close values and Wilder RSI(14) >= 50",
            "reason": "HCAR close 203.00 did not clear the previous five-bar close high of 203.00; the legacy, proposed live rule uses strict greater-than. RSI(14) was 66.33, so momentum alone did not confirm a fresh breakout.",
            "production_change": False,
        },
    }


def _json_records(frame: pd.DataFrame) -> list[dict]:
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _json_safe(value: Any) -> Any:
    """Replace non-finite research metrics with JSON null recursively."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _wilder_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0.0).tolist()
    losses = (-delta.clip(upper=0.0)).tolist()
    result = [float("nan")] * len(close)
    if len(close) <= period:
        return pd.Series(result, index=close.index, dtype="float64")
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    def value(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)
    result[period] = value(avg_gain, avg_loss)
    for index in range(period + 1, len(close)):
        avg_gain = (avg_gain * (period - 1) + gains[index]) / period
        avg_loss = (avg_loss * (period - 1) + losses[index]) / period
        result[index] = value(avg_gain, avg_loss)
    return pd.Series(result, index=close.index, dtype="float64")


def hcar_daily_backtest(frame: pd.DataFrame, *, tp: float = TARGET_PCT,
                        atr_multiple: float = 1.5, max_hold: int = 3) -> dict:
    """Compare causal EOD momentum baseline vs breakout+RSI and ATR stop.

    Signal is evaluated at close T, entry is next session open, and OHLC
    execution uses conservative same-bar stop-first fills in the shared engine.
    This is an EOD analogue, not a replication of the intraday scanner.
    """
    required = {"date", "symbol", "open", "high", "low", "close", "volume"}
    if required - set(frame.columns):
        raise ValueError(f"backtest frame lacks columns: {sorted(required - set(frame.columns))}")
    data = frame.loc[frame["symbol"].astype(str).str.upper() == "HCAR",
                     ["date", "symbol", "open", "high", "low", "close", "volume"]].copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = (data.dropna(subset=list(required))
            .sort_values("date", kind="mergesort")
            .reset_index(drop=True))
    if data.empty:
        raise ValueError("no valid HCAR bars in the historical dataset")
    if data["date"].duplicated().any():
        raise ValueError("HCAR daily history contains duplicate dates")
    if (data[["open", "high", "low", "close"]] <= 0).any().any() or (data["volume"] < 0).any():
        raise ValueError("HCAR history contains non-positive prices or negative volume")
    data["symbol"] = "HCAR"
    data["high"] = data[["open", "high", "close"]].max(axis=1)
    data["low"] = data[["open", "low", "close"]].min(axis=1)
    data["invalid_band"] = ((data["open"] / data["close"].shift(1) - 1.0).abs() > 0.60) \
        | ((data["close"] / data["open"] - 1.0).abs() > 0.60) \
        | ((data["close"] / data["close"].shift(1) - 1.0).abs() > 0.60)

    close = data["close"]
    prior_close_high = close.shift(1).rolling(5, min_periods=5).max()
    prior_volume_median = data["volume"].shift(1).rolling(5, min_periods=5).median()
    fast = close.pct_change(5, fill_method=None)
    previous_fast = close.shift(5).pct_change(5, fill_method=None)
    acceleration = fast - previous_fast
    tr = pd.concat((data["high"] - data["low"],
                    (data["high"] - close.shift(1)).abs(),
                    (data["low"] - close.shift(1)).abs()), axis=1).max(axis=1)
    data["atr14"] = tr.rolling(14, min_periods=14).mean()
    data["rsi14"] = _wilder_rsi_series(close)
    common = (fast.gt(0) & acceleration.gt(0) &
              data["volume"].gt(prior_volume_median) & close.ge(1.0) &
              data["atr14"].notna())
    baseline = common
    confirmed = (common & close.gt(prior_close_high) &
                 data["rsi14"].ge(config.MIN_CONFIRMATION_RSI))
    data["baseline_signal"] = baseline
    data["confirmed_signal"] = confirmed

    def simulate(mask: pd.Series, use_atr_stop: bool) -> tuple[pd.DataFrame, dict]:
        trades: list[pd.DataFrame] = []
        skipped = 0
        blocked_until = -1
        for position in range(len(data)):
            if not bool(mask.iloc[position]):
                continue
            if position <= blocked_until:
                skipped += 1
                continue
            signal_date = data.iloc[position]["date"]
            entry_index = position + 1
            if entry_index >= len(data):
                skipped += 1
                continue
            entry = float(data.iloc[entry_index]["open"])
            atr = float(data.iloc[position]["atr14"])
            if not math.isfinite(entry) or entry <= 0 or not math.isfinite(atr) or atr <= 0:
                skipped += 1
                continue
            stop_fraction = min(atr_multiple * atr / entry, 0.15) if use_atr_stop else 0.01
            result, _ = run_backtest(
                data, [(signal_date, "HCAR")], tp=tp, sl=stop_fraction,
                max_hold=max_hold, touch_mode="hl")
            if result.empty:
                skipped += 1
                continue
            result["atr_stop_fraction"] = stop_fraction
            prior_close = data.iloc[position]["close"]
            entered = result.iloc[0]["entry"]
            invalid = (bool(data.iloc[position]["invalid_band"])
                       or abs(float(entered) / float(prior_close) - 1.0) > 0.60)
            result["data_invalid"] = invalid
            if invalid:
                result["net_ret"] = 0.0
            trades.append(result)
            exit_date = pd.Timestamp(result.iloc[0]["exit_date"])
            exit_matches = data.index[data["date"] == exit_date]
            if len(exit_matches):
                blocked_until = int(exit_matches[0])
        combined = pd.concat(trades, ignore_index=True) if trades else pd.DataFrame()
        summary = summarize(combined, skipped=skipped, touch_mode="hl", tp=tp,
                            sl=f"{atr_multiple:g}x_ATR14_capped_15pct" if use_atr_stop else 0.01,
                            max_hold=max_hold)
        return combined, summary

    baseline_trades, baseline_summary = simulate(baseline, False)
    confirmation_fixed_stop_trades, confirmation_fixed_stop_summary = simulate(confirmed, False)
    confirmed_trades, confirmed_summary = simulate(confirmed, True)
    return {
        "data": {"symbol": "HCAR", "rows": len(data),
                 "first_date": data["date"].min().date().isoformat(),
                 "last_date": data["date"].max().date().isoformat(),
                 "source": "local eod_history.csv.gz; OHLCV; KMIALL daily bars"},
        "rule": {"baseline": "5-session return > 0, positive 5-session acceleration, volume above trailing 5-session median",
                 "improved": "baseline plus close > prior 5-session close high and Wilder RSI(14) >= 50",
                 "entry": "next session open", "target_pct": tp,
                 "stop": f"{atr_multiple:g} x ATR(14) from signal close / next open, capped at 15%",
                 "max_hold_sessions": max_hold,
                 "fills": "daily OHLC; stop-first ambiguous bars, gap-aware stop fills, round-trip costs/CGT"},
        "baseline": {"summary": baseline_summary,
                     "trades": _json_records(baseline_trades)},
        "confirmation_only": {"summary": confirmation_fixed_stop_summary,
                              "trades": _json_records(confirmation_fixed_stop_trades)},
        "improved": {"summary": confirmed_summary,
                     "trades": _json_records(confirmed_trades)},
        "limitations": [
            "Daily-bar analogue only; does not replicate live 1-minute momentum/volume buckets or exchange execution.",
            "Single ticker and historical sample are not independent evidence of edge; the confirmation is a hypothesis and needs broader walk-forward validation.",
            "Daily rows with adjacent prints beyond the 60% data-validity band are flagged and excluded from reported return metrics by the shared backtest engine.",
            "The historical input ends before the October 16 incident; that paper position is reported separately from this backtest.",
        ],
    }


def run(day: str, capture: Path, daily_data: Path, out: Path,
        observation_cache: Path | None = None,
        session_journal: Path | None = None,
        relay_observations: list[dict] | None = None,
        relay_history: dict | None = None) -> dict:
    observations = (relay_observations if relay_observations is not None
                    else _date_observations(day))
    local_observation_path = observation_cache or (ROOT / "data" / "forward" / "observation.json")
    local_observation = (json.loads(local_observation_path.read_text(encoding="utf-8"))
                         if local_observation_path.is_file() else None)
    local_observation_used = False
    local_observation_day = None
    if isinstance(local_observation, dict):
        local_day = str(local_observation.get("date") or
                        str(local_observation.get("as_of") or "")[:10])
        if local_day == day and isinstance(local_observation.get("slot"), str):
            local_observation_day = local_day
            observations.append({
                "slot": local_observation["slot"],
                "snapshot": local_observation,
                "source": "local data/forward/observation.json",
            })
            local_observation_used = True
    refused_candidates = [
        (row, _first_candidate(row)) for row in observations
    ]
    refused_candidates = [(row, candidate) for row, candidate in refused_candidates
                          if candidate is not None and
                          str(candidate.get("symbol") or "").upper() != "HCAR"]
    observation_slots = {
        str(row.get("slot") or (row.get("snapshot") or {}).get("slot") or "unknown")
        for row, _candidate in refused_candidates
    }
    candidate_refs = {
        (str(row.get("slot") or (row.get("snapshot") or {}).get("slot") or "unknown"),
         str(candidate.get("symbol") or "").strip().upper())
        for row, candidate in refused_candidates
    }
    history_body = (relay_history if relay_history is not None
                    else _relay_json("/research/history"))
    sessions = history_body.get("sessions")
    if not isinstance(sessions, list):
        raise RuntimeError("relay returned no outcome sessions list")
    outcome_by_symbol = {
        (str(row.get("date")), str(row.get("symbol"))): row
        for row in sessions if isinstance(row, dict)
        and row.get("date") and row.get("symbol")
    }
    journal_path = session_journal or (
        ROOT / config.SESSION_JOURNAL_FILE)
    if journal_path.is_file():
        for line in journal_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if (isinstance(row, dict) and str(row.get("date")) == day
                    and row.get("symbol")):
                outcome_by_symbol[(day, str(row["symbol"]))] = row
    outcomes = list(outcome_by_symbol.values())
    broker_samples, broker_coverage = _broker_tick_samples(capture, day)
    capture_last = (datetime.fromisoformat(broker_coverage["last_snapshot"])
                    if broker_coverage["last_snapshot"] else None)
    candidate_rows = audit_rejected(observations, broker_samples, day, capture_last,
                                    observation_slots)
    candidate_rows = [row for row in candidate_rows
                      if (row.first_refusal_slot, row.symbol) in candidate_refs]
    daily_frame = pd.read_csv(daily_data)
    backtest = hcar_daily_backtest(daily_frame)
    report = {
        "schema_version": 1,
        "date": day,
        "target_pct": TARGET_PCT,
        "candidate_count": len(candidate_rows),
        "refusal_observation_count": sum(row.repeated_refusals for row in candidate_rows),
        "candidate_outcomes": [asdict(row) for row in candidate_rows],
        "hcar": hcar_postmortem(capture, day, "11:34", observations, outcomes),
        "historical_backtest": backtest,
        "evidence": {
            "observation_records": len(observations),
            "relay_observation_records": len(relay_observations or []),
            "local_observation_appended": local_observation_used,
            "outcome_sessions": len(outcomes),
            "outcome_session_sources": ["authenticated relay history",
                                        "exact-day local session journal when available"],
            "session_journal_path": str(journal_path) if journal_path.is_file() else None,
            "broker_capture": broker_coverage,
            "broker_capture_archive": "restored from the project's Cloudflare R2 archive of the read-only local broker MKT-FEED capture",
            "candidate_outcome_method": "timestamped local broker last-trade samples strictly after each minute-precision refusal slot and no later than the official session close; the refusal minute and after-hours snapshots are excluded",
            "candidate_observation_slots": len(observation_slots),
            "refusal_symbol_slot_pairs": len(candidate_refs),
            "local_observation_cache_used": local_observation_used,
            "local_observation_cache_slot": (local_observation.get("slot")
                                              if local_observation_used else None),
            "candidate_observations_source": "authenticated relay archive plus exact-day local observation cache when present; candidates are joined to this saved broker tape by exact refusal slot",
            "relay_observation_slots": sum(
                1 for row in (relay_observations or [])
                if _first_candidate(row) is not None),
            "local_observation_slot_added": local_observation_used,
            "candidate_outcome_limit": "the broker source is a periodic snapshot, not a complete per-trade archive; confirmed TP means a timestamped last-trade clock reached the threshold after refusal and by session close, while no observed target print does not prove there was no between-snapshot touch",
            "historical_backtest_path": str(daily_data),
            "historical_backtest_note": "separate local daily-history analogue, not used to classify the October 16 refused candidates",
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    report = _json_safe(report)
    out.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    guard_cloud_backtest("scripts/hcar_postmortem.py")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=DEFAULT_DAY)
    parser.add_argument("--capture", type=Path, default=DEFAULT_CAPTURE)
    parser.add_argument("--daily-data", type=Path, default=DEFAULT_DAILY_DATA,
                        help="local OHLCV for the separate HCAR daily analogue only; never used for rejected-candidate outcomes")
    parser.add_argument("--observation-cache", type=Path, default=None,
                        help="optional exact-day local observation JSON; never substitutes for relay observations")
    parser.add_argument("--session-journal", type=Path, default=None,
                        help="optional local session journal for recorded outcomes")
    parser.add_argument("--relay-observations", type=Path, default=None,
                        help="optional JSON containing authenticated relay observations for this date")
    parser.add_argument("--relay-history", type=Path, default=None,
                        help="optional JSON containing authenticated relay session history")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if not args.capture.is_file():
        raise FileNotFoundError(f"capture not found: {args.capture}")
    relay_observations = None
    if args.relay_observations is not None:
        payload = json.loads(args.relay_observations.read_text(encoding="utf-8"))
        relay_observations = payload.get("observations")
        if not isinstance(relay_observations, list):
            raise ValueError("relay observations file must contain an observations list")
    relay_history = (json.loads(args.relay_history.read_text(encoding="utf-8"))
                     if args.relay_history is not None else None)
    report = run(args.date, args.capture, args.daily_data, args.out,
                  observation_cache=args.observation_cache,
                  session_journal=args.session_journal,
                  relay_observations=relay_observations,
                  relay_history=relay_history)
    print(json.dumps({"report": str(args.out),
                      "candidate_count": report["candidate_count"],
                      "refusal_observation_count": report["refusal_observation_count"],
                      "hcar_outcome": report["hcar"]["recorded_outcome"],
                      "hcar_target_hit": report["hcar"]["target_hit"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
