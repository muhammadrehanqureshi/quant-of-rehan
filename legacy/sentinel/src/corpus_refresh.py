"""Incremental 180-day corpus refresh - the learning base stays alive.

The backtest corpus (data/backtest/eod_corpus.json, 305 KMIALL
symbols, open/close/volume from the PSX Data Portal) was rebuilt by
hand; nothing on GitHub appended to it, so the learning base froze at
its build date. This module appends the missing sessions from the
same DPS endpoint, incrementally and merge-safe:

  * only symbols' NEW dates are folded - existing rows never change;
  * the per-symbol lock table is then RE-MINED over the grown corpus
    (the grind-6 law) so the proven/banned lists move with the market;
  * every step is best-effort: a DPS outage costs one day of
    learning, never the session.

Called from the cloud close-out daily; also runnable by hand:
    python src/corpus_refresh.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "backtest" / "eod_corpus.json"
LOCK_REPORT = ROOT / "data" / "backtest" / "per_symbol_lock_report.json"

COST = 0.848   # the grind-6 cost stack, % per round trip
TP, SL = 2.0, -1.0
LOCK_CHG = 9.9
PROVEN_MIN_N = 8
PROVEN_MIN_WIN = 70.0
BANNED_MIN_N = 3
BANNED_MAX_WIN = 50.0


def _load_corpus() -> dict:
    try:
        return json.loads(CORPUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def incremental(max_days_back: int = 10, budget_s: float = 180.0) -> int:
    """Fold any missing recent sessions into the corpus. Returns the
    number of NEW trading days added (0 = already current).

    v2.7.1 budget: the close-out and the sweep pay Actions minutes.
    The refetch stops at `budget_s` - a partial refresh still lands
    its sessions (each symbol is independent), and the next run picks
    up the rest. 313 serial DPS fetches at ~0.9s = ~5 min unwrapped;
    the budget keeps the worst case bounded."""
    try:
        import requests

        from scan_positive_opens import fetch_eod_rows
    except Exception:  # noqa: BLE001
        return 0

    corpus = _load_corpus()
    if not corpus:
        return 0

    newest = max(
        (r["date"] for rows in corpus.values() for r in rows),
        default=None,
    )
    if newest is None:
        return 0
    from datetime import datetime as _dt

    newest_d = _dt.strptime(newest, "%Y-%m-%d").date()
    today = date.today()
    stale_days = (today - newest_d).days
    if stale_days <= 0:
        return 0  # current

    # Backfill window: the gap since the newest stored session.
    window_start = newest_d + timedelta(days=1)
    window_end = today
    if (window_end - window_start).days > max_days_back:
        # The corpus went very stale (repo idle): refetch a bounded
        # window anyway - partial freshness beats none.
        window_start = window_end - timedelta(days=max_days_back)

    universe_path = paths.UNIVERSE_FILE
    try:
        universe = json.loads(universe_path.read_text(encoding="utf-8"))
        symbols = (
            [u["symbol"] for u in universe]
            if isinstance(universe, list)
            else list(universe)
        )
    except (OSError, json.JSONDecodeError):
        symbols = sorted(corpus.keys())

    import time as _time

    _t0 = _time.monotonic()
    added = set()
    with requests.Session() as http:
        for sym in symbols:
            if _time.monotonic() - _t0 > budget_s:
                break  # minutes budget spent; next run finishes the job
            try:
                rows = fetch_eod_rows(sym, http)
            except Exception:  # noqa: BLE001
                continue
            if not rows:
                continue
            hist = corpus.setdefault(sym, [])
            have = {h["date"] for h in hist}
            for r in rows:
                d = r["date"].isoformat()
                if d in have or not (window_start <= r["date"] <= window_end):
                    continue
                hist.append(
                    {
                        "date": d,
                        "open": r["open"],
                        "close": r["close"],
                        "volume": r["volume"],
                    }
                )
                added.add(d)
            hist.sort(key=lambda h: h["date"])
            time.sleep(0.05)  # polite pacing; network-bound

    if added:
        CORPUS.write_text(json.dumps(corpus), encoding="utf-8")
        # Any genuinely new session also extends the corpus-wide date
        # set even for symbols that failed this pass (they carry the
        # next refresh).
    return len(added)


def remine_lock_table() -> dict:
    """Re-mine the per-symbol lock table over the CURRENT corpus (the
    grind-6 law: TP+2/SL-1 at the 9.9% lock, net of the cost stack).
    Writes per_symbol_lock_report.json for lessons.py to read."""
    corpus = _load_corpus()
    if not corpus:
        return {}
    table: dict[str, dict] = {}
    for sym, rows in corpus.items():
        rows = sorted(rows, key=lambda r: r["date"])
        trades = []
        for i in range(1, len(rows) - 1):
            r, pc = rows[i], rows[i - 1]
            if not r.get("close") or not pc.get("close"):
                continue
            chg = (r["close"] / pc["close"] - 1) * 100
            if chg < LOCK_CHG:
                continue
            nc = rows[i + 1].get("close")
            if not nc:
                continue
            entry = r["close"]
            if nc >= entry * (1 + TP / 100):
                trades.append((r["date"], "TP", TP - COST))
            elif nc <= entry * (1 + SL / 100):
                trades.append((r["date"], "SL", SL - COST))
            else:
                trades.append((r["date"], "time", (nc / entry - 1) * 100 - COST))
        if not trades:
            continue
        wins = sum(1 for _, o, _ in trades if o == "TP")
        table[sym] = {
            "n": len(trades),
            "wins": wins,
            "win_pct": wins / len(trades) * 100,
            "net": sum(n for _, _, n in trades),
            "dates": [d for d, _, _ in trades],
        }
    LOCK_REPORT.parent.mkdir(parents=True, exist_ok=True)
    LOCK_REPORT.write_text(
        json.dumps(table, indent=1, sort_keys=True), encoding="utf-8"
    )
    return table


def main() -> int:
    paths.enable_utf8_stdout()
    added = incremental()
    print(f"corpus: +{added} new session(s)")
    table = remine_lock_table()
    proven = sum(
        1 for s in table.values()
        if s["n"] >= PROVEN_MIN_N and s["win_pct"] >= PROVEN_MIN_WIN
    )
    banned = sum(
        1 for s in table.values()
        if s["n"] >= BANNED_MIN_N
        and s["win_pct"] < BANNED_MAX_WIN
        and s["net"] < 0
    )
    print(f"lock table re-mined: {len(table)} symbols "
          f"({proven} proven, {banned} banned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
