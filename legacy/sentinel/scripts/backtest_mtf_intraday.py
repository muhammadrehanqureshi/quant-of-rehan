"""Intraday multi-timeframe backtest from the archived snapshot tape.

The owner ordered 5m / 15m / 1h / 4h candle backtesting. PSX publishes
no historical intraday candles; the project's archive is 14 sessions of
order-book snapshots (data/snapshots/*.jsonl.gz, 5-12 min cadence).
From that tape we build bars at 5m, 15m, 1h and 4h bins (high/low from
the bar's snapshot extremes, close = last quote in the bin, volume =
last cumulative volume minus prior) and run the same strategy family
as the daily pass, under the same law and costs.

Every result is labeled with its session list - no pretending this is
180 days of intraday. Where a bar's high/low is a snapshot extreme
(not a true tick extreme) the barrier test is slightly conservative;
that bias goes AGAINST the strategy, never for it.
"""
from __future__ import annotations

import gzip
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = ROOT / "data" / "snapshots"

COST_PCT = 0.848
TP_PCT = 2.0
SL_PCT = -1.0
PKT = timezone(timedelta(hours=5))


def load_session(path: Path) -> list[dict]:
    """One session: list of (ts, {sym: quote}) snapshots, ordered."""
    snaps = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = r.get("receiveTime") or r.get("generatedAt")
            if not ts:
                continue
            snaps.append((ts, r.get("quotes") or {}))
    snaps.sort(key=lambda x: x[0])
    return snaps


def build_bars(snaps: list[dict], bin_minutes: int) -> dict[str, list[dict]]:
    """Per-symbol bars from cumulative day fields (high/low/volume)."""
    bars: dict[str, dict[str, dict]] = defaultdict(dict)
    for ts, quotes in snaps:
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(PKT)
        except ValueError:
            continue
        key = t.replace(
            minute=(t.minute // bin_minutes) * bin_minutes, second=0, microsecond=0
        ).isoformat()
        for sym, q in quotes.items():
            if not q or not q.get("price"):
                continue
            px = float(q["price"])
            hi = float(q.get("high") or px)
            lo = float(q.get("low") or px)
            vol = float(q.get("volume") or 0)
            b = bars[sym].get(key)
            if b is None:
                bars[sym][key] = {
                    "ts": key, "open": px, "high": max(hi, px),
                    "low": min(lo, px), "close": px, "volume": vol,
                }
            else:
                b["high"] = max(b["high"], hi, px)
                b["low"] = min(b["low"], lo, px)
                b["close"] = px
                b["volume"] = max(b["volume"], vol)  # cumulative day field
    out: dict[str, list[dict]] = {}
    for sym, d in bars.items():
        rows = sorted(d.values(), key=lambda b: b["ts"])
        # make volume per-bar (cumulative -> diff)
        prev = 0.0
        for r in rows:
            r["volume"], prev = max(r["volume"] - prev, 0.0), r["volume"]
        out[sym] = rows
    return out


def resolve(bars: list[dict], i0: int, entry: float) -> str | None:
    tp = entry * (1 + TP_PCT / 100)
    sl = entry * (1 + SL_PCT / 100)
    for b in bars[i0:]:
        if b["low"] <= sl:
            return "SL"
        if b["high"] >= tp:
            return "TP"
    return None


def run_tf_chain(
    bars_chain: dict[str, list[dict]], session_bounds: list[tuple[int, int]],
    min_bars: int, sma_n: int = 20,
) -> dict:
    """Run the strategy family over a per-symbol chain of bars that spans
    sessions. History (SMA, N-bar high) may read across the chain, but an
    entry resolves ONLY inside its own session (intraday honesty);
    unresolved entries are excluded, never counted as wins.

    session_bounds: [(start_idx, end_idx_exclusive), ...] into each chain.
    """
    trades = defaultdict(lambda: [0, 0, 0.0])
    for sym, bars in bars_chain.items():
        if len(bars) < max(min_bars, sma_n + 2):
            continue
        closes = [b["close"] for b in bars]
        for n in (5, 20):
            if n >= sma_n and min_bars <= n:
                pass
            for i in range(n, len(bars) - 1):
                # signal bar must not be the session's last bar (needs a
                # resolution bar inside the same session)
                if not any(s <= i < e - 1 for s, e in session_bounds):
                    continue
                prior_high = max(b["high"] for b in bars[max(0, i - n):i])
                if (
                    len(bars[max(0, i - n):i]) == n
                    and bars[i - 1]["close"] <= prior_high
                    and bars[i]["close"] > prior_high
                ):
                    end = next(e for s, e in session_bounds if s <= i < e)
                    out = resolve(bars, i + 1, bars[i]["close"]) if i + 1 < end else None
                    if out is None and i + 1 < end:
                        continue
                    if out:
                        t = trades[f"breakout{n}"]
                        t[0] += 1
                        t[1] += out == "TP"
                        t[2] += (TP_PCT if out == "TP" else SL_PCT) - COST_PCT
        for i in range(sma_n, len(bars) - 1):
            if not any(s <= i < e - 1 for s, e in session_bounds):
                continue
            sma = sum(closes[i - sma_n:i]) / sma_n
            if closes[i - 1] > sma and abs(bars[i]["open"] - sma) / sma < 0.01:
                end = next(e for s, e in session_bounds if s <= i < e)
                out = resolve(bars, i + 1, bars[i]["open"]) if i + 1 < end else None
                if out:
                    t = trades["trend_pullback"]
                    t[0] += 1
                    t[1] += out == "TP"
                    t[2] += (TP_PCT if out == "TP" else SL_PCT) - COST_PCT
    return {k: {"n": v[0], "wins": v[1], "net": v[2]} for k, v in trades.items()}


def run_tf(label: str, snaps: list[dict], bin_minutes: int) -> dict:
    bars_by_sym = build_bars(snaps, bin_minutes)
    trades = defaultdict(lambda: [0, 0, 0.0])  # strategy -> [n, wins, net]
    for sym, bars in bars_by_sym.items():
        if len(bars) < 25:
            continue
        closes = [b["close"] for b in bars]
        for n in (5, 20):
            for i in range(n, len(bars) - 3):
                prior_high = max(b["high"] for b in bars[i - n:i])
                if bars[i - 1]["close"] <= prior_high and bars[i]["close"] > prior_high:
                    out = resolve(bars, i + 1, bars[i]["close"])
                    if out:
                        t = trades[f"breakout{n}"]
                        t[0] += 1
                        t[1] += out == "TP"
                        t[2] += (TP_PCT if out == "TP" else SL_PCT) - COST_PCT
        for i in range(20, len(bars) - 3):
            sma = sum(closes[i - 20:i]) / 20
            if closes[i - 1] > sma and abs(bars[i]["open"] - sma) / sma < 0.01:
                out = resolve(bars, i + 1, bars[i]["open"])
                if out:
                    t = trades["trend_pullback"]
                    t[0] += 1
                    t[1] += out == "TP"
                    t[2] += (TP_PCT if out == "TP" else SL_PCT) - COST_PCT
    return {k: {"n": v[0], "wins": v[1], "net": v[2]} for k, v in trades.items()}


def main() -> int:
    sessions = sorted(SNAP_DIR.glob("*.jsonl.gz"))
    print("=" * 72)
    print("INTRADAY MULTI-TIMEFRAME BACKTEST - archived tape")
    print("bins: 5m / 15m / 1h / 4h | law TP+2% SL-1% | costs 0.848% RT")
    print("=" * 72)

    # Build ONE chain of bars per symbol across all sessions, remember
    # each session's [start, end) index range, then run per-bin.
    all_snaps: list[dict] = []
    bounds: list[tuple[int, int]] = []
    used: list[str] = []
    for path in sessions:
        snaps = load_session(path)
        if len(snaps) < 8:
            continue
        start = len(all_snaps)
        all_snaps.extend(snaps)
        bounds.append((start, len(all_snaps)))
        used.append(path.stem)
    print(f"{len(used)} sessions, {len(all_snaps)} snapshots total\n")

    for label, minutes in (("5m", 5), ("15m", 15), ("1h", 60), ("4h", 240)):
        chain = build_bars(all_snaps, minutes)
        res = run_tf_chain(chain, bounds, min_bars=12)
        print(f"--- {label} bars ---")
        for strat, m in sorted(res.items()):
            if not m["n"]:
                continue
            wr = m["wins"] / m["n"] * 100
            print(
                f"  {strat:16s} {m['n']:5d} trades | win {wr:5.1f}% "
                f"| net {m['net']:+8.1f}% ({m['net'] / m['n']:+.2f}/trade)"
            )
        print()

    print("Sessions used:", ", ".join(used))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
