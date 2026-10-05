"""
The trailing-stop audit (the PSO question).

Replays every Rule T exit - a trade closed because the ARMED trailing
stop (arm at +1.0%, trail 0.5%, 2-poll confirmation) fired - against
the stored snapshot tape:

  * peak gain after arming (what the trade was worth at its best);
  * kept gain (what the trail actually locked);
  * gain left on the table (peak - kept);
  * whether the +2.0% target was ever touched on the path (Rule 0
    means a touch closes AT target - so a wider trail that survives
    to the touch converts the exit into a full TP win);
  * scenario table: the actual 0.5% trail vs 1.0% / 1.5% trails and
    no trail (pure TP/SL), scored on every auditable Rule T trade.

Only trades whose snapshot tape survives locally are auditable; the
count of un-auditable trades is reported honestly, never skipped
silently. Read-only: opens nothing, writes nothing but stdout.

Usage:
    python scripts/audit_trailing_stops.py
"""

from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from psx_core import paths  # noqa: E402

TRAIL_ARM_PCT = 1.0     # config: trailing_stop_activation_pct
TRAIL_PCTS = [0.5, 1.0, 1.5, None]  # None = no trail (pure TP/SL)
TP_PCT = 2.0
SL_PCT = -1.0


def load_positions() -> list[dict]:
    book = json.loads(
        (paths.DATA_DIR / "portfolio.json").read_text(encoding="utf-8")
    )
    return [p for p in book if p.get("status") == "CLOSED"]


def day_tape(trading_date: str) -> dict[str, list[tuple[int, float]]]:
    """{symbol: [(epoch_ts, price), ...]} from one day's snapshot file."""
    path = paths.SNAPSHOT_DIR / f"{trading_date}.jsonl.gz"
    if not path.exists():
        return {}
    tape: dict[str, list[tuple[int, float]]] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                snap = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = snap.get("generatedAt")
            try:
                when = int(
                    datetime.fromisoformat(
                        str(ts).replace("Z", "+00:00")
                    ).timestamp()
                )
            except (ValueError, TypeError):
                continue
            for sym, q in (snap.get("quotes") or {}).items():
                price = (q or {}).get("price")
                if isinstance(price, (int, float)) and price > 0:
                    tape.setdefault(sym, []).append((when, float(price)))
    for sym in tape:
        tape[sym].sort()
    return tape


def parse_ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def trading_dates_between(start: datetime, end: datetime) -> list[str]:
    """Trading-date strings touched by [start, end] in PKT terms."""
    from psx_core import sessions

    dates: list[str] = []
    day = sessions.trading_date(start)
    last = sessions.trading_date(end)
    cursor = start
    while day != last and len(dates) < 5:
        dates.append(day.isoformat())
        cursor = cursor + timedelta(days=1)
        day = sessions.trading_date(cursor.replace(hour=0, minute=0))
    dates.append(last.isoformat())
    return dates


def replay(rule_t: dict) -> dict | None:
    """Reconstruct one Rule T trade's path. None = tape unavailable."""
    entry_ts = parse_ts(rule_t.get("entry_ts"))
    exit_ts = parse_ts(rule_t.get("exit_ts"))
    if entry_ts is None or exit_ts is None:
        return None
    symbol = rule_t["symbol"]
    entry = float(rule_t["entry_price"])
    target = float(rule_t.get("target_price") or entry * (1 + TP_PCT / 100))

    tape: dict[str, list[tuple[int, float]]] = {}
    for date in trading_dates_between(entry_ts, exit_ts):
        tape.update(day_tape(date))
    path = [
        (ts, price)
        for ts, price in tape.get(symbol, [])
        if entry_ts.timestamp() <= ts <= exit_ts.timestamp() + 5
    ]
    if len(path) < 3:
        return None

    arm_level = entry * (1 + TRAIL_ARM_PCT / 100)
    armed_peak: float | None = None
    touch_target = False
    for _, price in path:
        if price >= target:
            touch_target = True
        if price >= arm_level:
            armed_peak = price if armed_peak is None else max(armed_peak, price)

    peak_gain = (
        (armed_peak / entry - 1) * 100 if armed_peak else None
    )
    kept_gain = float(rule_t.get("pnl_pct") or 0.0)
    return {
        "symbol": symbol,
        "entry": entry,
        "exit": float(rule_t.get("exit_price") or 0.0),
        "kept": kept_gain,
        "peak": peak_gain,
        "left": (peak_gain - kept_gain) if peak_gain else None,
        "touch_target": touch_target,
        "n_points": len(path),
    }


def scenario_gain(run: dict, trail_pct: float | None) -> float:
    """
    % P&L the trade would have booked under a trail width, replayed
    on the observed path's two decisive facts: the armed peak and the
    target touch. A wider trail survives to the target touch; a narrow
    one exits near peak*(1-width). The stop side is identical in all
    scenarios (these trades ARMED, so the SL never fired first).
    """
    entry = run["entry"]
    if run["touch_target"]:
        # Survives to the touch (or was already past it): books TP.
        # The actual trail would only reach the touch if the drawdown
        # from peak stayed inside the width - approximated by whether
        # the actual kept exit is at/below the trail of the peak.
        if trail_pct is None:
            return TP_PCT
        peak_price = entry * (1 + (run["peak"] or 0) / 100)
        trail_exit = peak_price * (1 - trail_pct / 100)
        if trail_exit >= entry * (1 + TP_PCT / 100) or trail_pct >= TP_PCT:
            return TP_PCT
        # Narrower than the target distance: books the trail level.
        return (trail_exit / entry - 1) * 100
    if run["peak"] is None:
        return run["kept"]
    peak_price = entry * (1 + run["peak"] / 100)
    if trail_pct is None:
        # No trail: rides to the session close (the force-close level
        # IS the actual exit only when the trail did not fire earlier).
        # Honest bound: worst case the day closes at the trail's own
        # exit; best case the close beats it. Use the actual exit as
        # the conservative estimate.
        return run["kept"]
    trail_exit = peak_price * (1 - trail_pct / 100)
    return max((trail_exit / entry - 1) * 100, SL_PCT)


def main() -> int:
    positions = load_positions()
    rule_t = [
        p for p in positions
        if str(p.get("exit_reason", "")).startswith("Rule T:")
    ]
    other_exits = len(positions) - len(rule_t)
    print("=" * 72)
    print("TRAILING-STOP AUDIT (Rule T exits vs the snapshot tape)")
    print("=" * 72)
    print(f"closed trades in book : {len(positions)}")
    print(f"Rule T (armed trail)  : {len(rule_t)}")
    print(f"other exits           : {other_exits}")

    runs: list[dict] = []
    un_auditable = 0
    for trade in rule_t:
        run = replay(trade)
        if run is None:
            un_auditable += 1
        else:
            runs.append(run)

    print(f"auditable on local tape: {len(runs)}  "
          f"(un-auditable: {un_auditable} - snapshot file not stored locally)")

    if not runs:
        print("\nNothing auditable - the local snapshot archive does not")
        print("cover any Rule T trade. Keep snapshots; rerun after the")
        print("next armed-trail exit.")
        return 0

    print()
    print(f"{'sym':6s} {'kept%':>7s} {'peak%':>7s} {'left%':>7s} "
          f"{'touched TP':>10s} {'pts':>4s}")
    for run in sorted(runs, key=lambda r: -(r["left"] or 0)):
        print(f"{run['symbol']:6s} {run['kept']:7.2f} "
              f"{run['peak'] if run['peak'] is not None else float('nan'):7.2f} "
              f"{run['left'] if run['left'] is not None else float('nan'):7.2f} "
              f"{str(run['touch_target']):>10s} {run['n_points']:4d}")

    armed = [r for r in runs if r["peak"] is not None]
    if armed:
        avg_kept = sum(r["kept"] for r in armed) / len(armed)
        avg_peak = sum(r["peak"] for r in armed) / len(armed)
        avg_left = sum(r["left"] for r in armed) / len(armed)
        print()
        print(f"armed-trail trades: {len(armed)}")
        print(f"avg kept gain     : {avg_kept:+.2f}%")
        print(f"avg peak gain     : {avg_peak:+.2f}%")
        print(f"avg left on table : {avg_left:+.2f}%")

        print()
        print("Scenario comparison (avg booked % per trade, same paths):")
        for trail in TRAIL_PCTS:
            label = f"trail {trail:.1f}%" if trail else "no trail "
            gains = [scenario_gain(r, trail) for r in runs]
            print(f"  {label}: {sum(gains) / len(gains):+.2f}%")

    touched = sum(1 for r in runs if r["touch_target"])
    if runs:
        print()
        print(f"Rule T trades whose path touched the +2% target: "
              f"{touched}/{len(runs)}")
        print("(a touch closes AT target under Rule 0 - every one of")
        print(" these is a trade a wider trail might have converted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
