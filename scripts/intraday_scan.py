"""Market-hour KMIALL observation scan using only captured bars available now.

The daily engine is UNGRADED and produces OBSERVE, never an order. This
script builds one partial daily candle per symbol from genuine minute bars,
combines it with a bounded trailing EOD window, and sends an alert only when
coverage is adequate and exactly one candidate passes the existing rule.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import is_market_open, now_karachi  # noqa: E402
from src.signals.engine import run  # noqa: E402
from src.signals.signal_push import load_relay_url, post_json, read_admin_token  # noqa: E402

MIN_COVERAGE = 0.80
MIN_HISTORY_SESSIONS = 21
MAX_BAR_AGE_MINUTES = 20


def aggregate_minute_bars(path: Path, symbols: list[str], session_day: str,
                          as_of: datetime) -> pd.DataFrame:
    """Aggregate only today's bars timestamped no later than as_of."""
    allowed = set(symbols)
    collected: dict[str, list[tuple[datetime, dict]]] = {}
    if not path.is_file():
        return pd.DataFrame(columns=["symbol", "date", "open", "high", "low",
                                     "close", "volume", "bar_time"])
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
            symbol = str(record["symbol"]).strip()
            if symbol not in allowed:
                continue
            captured = datetime.fromisoformat(record["ts"])
            if captured.date().isoformat() != session_day:
                continue
            for bar in record.get("bars", []):
                minute = datetime.combine(
                    captured.date(), time.fromisoformat(str(bar["t"])),
                    tzinfo=as_of.tzinfo)
                if minute > as_of:
                    continue
                values = {key: float(bar[key]) for key in ("o", "h", "l", "c")}
                if min(values.values()) <= 0:
                    continue
                collected.setdefault(symbol, []).append((minute, values))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue

    rows = []
    for symbol, items in collected.items():
        items.sort(key=lambda item: item[0])
        times = [item[0] for item in items]
        last_time = times[-1]
        if as_of - last_time > timedelta(minutes=MAX_BAR_AGE_MINUTES):
            continue
        bars = [item[1] for item in items]
        rows.append({
            "symbol": symbol,
            "date": pd.Timestamp(session_day),
            "open": bars[0]["o"],
            "high": max(bar["h"] for bar in bars),
            "low": min(bar["l"] for bar in bars),
            "close": bars[-1]["c"],
            # Minute feed has no volume field. Never invent one.
            "volume": float("nan"),
            "bar_time": last_time.isoformat(),
        })
    return pd.DataFrame(rows)


def candidate_for_session(signals: list, session_day: str):
    """Return one signal only; ambiguous candidate sets fail closed."""
    candidates = [signal for signal in signals
                  if signal.signal_date == session_day]
    if len(candidates) == 1:
        return candidates[0], "one candidate"
    if not candidates:
        return None, "no candidate passed the existing rule"
    return None, f"{len(candidates)} candidates; no arbitrary ranking applied"


def evaluate_scan(history: pd.DataFrame, partial: pd.DataFrame,
                  universe_size: int, session_day: str):
    coverage = len(partial) / max(universe_size, 1)
    if coverage < MIN_COVERAGE:
        return None, (f"NO TRADE: minute-bar coverage {coverage:.1%} is below "
                      f"the {MIN_COVERAGE:.0%} minimum")
    sessions = pd.to_datetime(history["date"]).dt.date.nunique()
    if sessions < MIN_HISTORY_SESSIONS:
        return None, (f"NO TRADE: only {sessions} prior EOD sessions; "
                      f"{MIN_HISTORY_SESSIONS} required")
    if partial.empty:
        return None, "NO TRADE: no fresh minute bars"

    prior = history.copy()
    prior["date"] = pd.to_datetime(prior["date"])
    prior = prior[prior["date"].dt.date.astype(str) < session_day]
    combined = pd.concat([prior, partial.drop(columns=["bar_time"], errors="ignore")],
                         ignore_index=True, sort=False)
    combined = combined.drop_duplicates(["symbol", "date"], keep="last")
    signals, _features = run(combined)
    selected, reason = candidate_for_session(signals, session_day)
    return selected, reason


def alert_text(signal, scan_time: datetime) -> str:
    price = float(signal.close)
    return (
        f"INTRADAY ALERT {signal.signal_date} (Karachi)\n"
        f"OBSERVE {signal.symbol} | reference price {price:.4f} "
        f"at {scan_time:%H:%M} PKT\n"
        f"Reference only: +2% level {price * 1.02:.4f}, "
        f"-1% level {price * 0.99:.4f}; levels are from this reference price, "
        f"not an executable fill.\n"
        f"Existing daily rule: regime {signal.regime}, sweep-low and "
        f"FVG-retrace. UNGRADED; no proven intraday edge, no order placed."
    )


def deliver_once(text: str, signal_date: str) -> bool:
    token = read_admin_token()
    relay_url = load_relay_url()
    import requests

    try:
        response = requests.get(
            relay_url + "/signals",
            headers={"x-admin-token": token},
            timeout=15,
        )
        response.raise_for_status()
        stored = str(response.json().get("signals", ""))
    except Exception as exc:
        raise RuntimeError(f"could not check relay deduplication state: {exc}") from exc
    if f"INTRADAY ALERT {signal_date}" in stored:
        print(f"relay already has an intraday alert for {signal_date}; no repeat")
        return False

    # Keep the alert in the APK card and deliver the same text to Telegram.
    post_json(relay_url, "/notify", {"text": text, "kind": "signals"}, token)
    post_json(relay_url, "/signals", {"signals": text}, token)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KMIALL market-hour observation scan")
    parser.add_argument("--bars", type=Path)
    args = parser.parse_args(argv)

    scan_time = now_karachi()
    if not is_market_open(scan_time):
        print(f"SKIPPED: market closed at {scan_time:%H:%M} PKT")
        return 0

    session_day = scan_time.date().isoformat()
    bars_path = args.bars or (
        ROOT / "data" / "feed_capture" /
        f"ohlc_{scan_time:%Y%m%d}.ndjson"
    )
    from src.data.feed_capture import load_universe
    from scripts.signal_daily import (
        UNIVERSE_LEGACY, UNIVERSE_FALLBACK, WINDOW_KMI, fetch_window,
        filter_to_universe,
    )

    universe_path = UNIVERSE_LEGACY if UNIVERSE_LEGACY.is_file() else UNIVERSE_FALLBACK
    symbols = load_universe(universe_path)
    partial = aggregate_minute_bars(bars_path, symbols, session_day, scan_time)

    # Reuse the bounded EOD fetch used by the existing daily action. Exclude
    # today's portal row so only the captured, time-bounded minute bars form T.
    fetch_window(scan_time.date() - timedelta(days=1))
    filter_to_universe()
    history = pd.read_csv(WINDOW_KMI, parse_dates=["date"])
    history = history[history["symbol"].isin(set(symbols))]
    history = history[history["date"].dt.date.astype(str) < session_day]

    selected, reason = evaluate_scan(history, partial, len(symbols), session_day)
    coverage = len(partial) / max(len(symbols), 1)
    print(f"Scan {session_day} {scan_time:%H:%M} PKT: "
          f"{len(partial)}/{len(symbols)} symbols ({coverage:.1%} coverage)")
    if selected is None:
        print(f"NO TRADE: {reason}")
        return 0

    text = alert_text(selected, scan_time)
    print(text)
    try:
        sent = deliver_once(text, session_day)
    except Exception as exc:
        print(f"DELIVERY FAILED: {type(exc).__name__}: {exc}")
        return 1
    print("Delivered to APK and Telegram." if sent else "Already delivered for today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
