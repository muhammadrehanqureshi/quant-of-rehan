"""
PSX KMIALL BOT
Market learner - the bot's daily class in market behavior.

The owner's standing order: both bots keep learning the market every
day - how it behaved, what people bought, what they sold, which stocks
are in trend, which are completely dead. This module is that lesson:

    data/snapshots/YYYY-MM-DD.jsonl.gz  ->  one lesson per session
                                        ->  data/market_lessons.json
                                        ->  engine + morning report
                                        ->  Sentinel-EOD (synced copy)

What each lesson records (all measurable from the stored tape, no
look-ahead, no extra HTTP):

  breadth      how many names advanced vs declined - the day's risk
               appetite in one number.
  leaders      where the real money traded (top names by traded value)
               and which way it pushed them - "what people are buying
               and selling" answered with rupees, not opinions.
  trending     names green in EVERY snapshot of the session with real
               turnover - consistent strength, not a single print.
  dead         names flat AND illiquid all session - no fuel, no trade.
  flows        NCCPL investor-type nets for the session, when the
               history has caught up.
  verdict      risk-on / mixed / risk-off from index + breadth.

The rolling store also keeps streaks: a symbol dead or trending
several sessions running is confirmed (dead_confirmed /
trend_confirmed), which is what the engines consume. Lessons roll 60
sessions; streaks recompute from the days kept.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from psx_core import paths

# Lesson tuning. Thresholds in raw quote units (changePercent on the
# feed is a fraction: 0.011 == +1.1%).
UP_TH = 0.001            # +0.1% counts as up
DOWN_TH = -0.001         # -0.1% counts as down
TREND_MIN_CHG = 0.005    # green >= 0.5% in EVERY snapshot
TREND_MIN_VALUE = 2_000_000.0   # Rs 2M session turnover minimum
DEAD_MAX_CHG = 0.004     # |day change| <= 0.4%
DEAD_MAX_VALUE = 200_000.0      # under Rs 200k turnover all session
LEADERS_N = 8            # top names by traded value
GAINER_N = 5             # top real gainers/losers (liquid only)
LIQUID_VALUE = 1_000_000.0      # Rs 1M to count as a real move
ROLL_DAYS = 60           # lessons kept in the rolling store
DEAD_STREAK_MIN = 3      # sessions dead running -> confirmed
TREND_STREAK_MIN = 3     # sessions trending running -> confirmed

LESSONS_PATH = paths.DATA_DIR / "market_lessons.json"


# ---------------------------------------------------------------------------
# One day's lesson from the stored snapshots
# ---------------------------------------------------------------------------

def _load_day_snapshots(trading_date: str) -> list[dict]:
    path = paths.DATA_DIR / "snapshots" / f"{trading_date}.jsonl.gz"
    if not path.exists():
        return []
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _flows_for(trading_date: str) -> dict | None:
    """NCCPL investor nets for the session, when the history caught up."""
    path = paths.DATA_DIR / "foreign_flow_history.jsonl"
    if not path.exists():
        return None
    try:
        rows = [
            json.loads(l)
            for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip()
        ]
    except (OSError, json.JSONDecodeError):
        return None
    row = next(
        (r for r in rows if str(r.get("date")) == trading_date), None
    )
    if not row:
        return None
    inv = row.get("byInvestor") or {}
    if not inv:
        # Legacy row: foreign net only.
        f = row.get("foreign_net_usd")
        return {"foreign_m": _m(f), "institutional_m": None,
                "retail_m": None} if f is not None else None
    return {
        "foreign_m": _m((inv.get("Foreign") or {}).get("net")),
        "institutional_m": _m(
            sum(
                float((inv.get(n) or {}).get("net") or 0.0)
                for n in (
                    "Mutual Funds", "Banks / DFI", "Insurance",
                    "Brokers", "Companies", "NBFC", "Others",
                )
            )
        ),
        "retail_m": _m((inv.get("Individuals") or {}).get("net")),
    }


def _m(v) -> float | None:
    try:
        return round(float(v) / 1e6, 1)
    except (TypeError, ValueError):
        return None


def analyze_day(trading_date: str) -> dict | None:
    """The session's lesson from the stored snapshot tape.

    Returns None when the tape is unusable (no file, no quotes) -
    learning refuses to invent a lesson from nothing.

    Feed unit notes (measured, not assumed):
      * quote changePercent is a FRACTION (-0.00378 == -0.378%);
      * the index block's changePercent is already PERCENT (0.382 ==
        +0.38% - verified against price/change: 654/172057);
      * quote `value` is CUMULATIVE for the session - the LAST
        snapshot carries the day's turnover, summing would inflate it
        by the snapshot count.
    """
    snaps = _load_day_snapshots(trading_date)
    if not snaps:
        return None

    # Per-symbol session aggregates across every stored snapshot.
    last_chg: dict[str, float] = {}
    green_snaps: dict[str, int] = defaultdict(int)
    snap_seen: dict[str, int] = defaultdict(int)
    day_value: dict[str, float] = {}
    index_chgs: list[float] = []

    for row in snaps:
        idx = row.get("index") or {}
        ic = idx.get("changePercent")
        if isinstance(ic, (int, float)):
            index_chgs.append(float(ic))  # already percent
        for sym, q in (row.get("quotes") or {}).items():
            if not isinstance(q, dict):
                continue
            if q.get("price") is None:
                continue
            snap_seen[sym] += 1
            chg = q.get("changePercent")
            if isinstance(chg, (int, float)):
                last_chg[sym] = float(chg)  # fraction
                if float(chg) > 0.0:
                    green_snaps[sym] += 1
            # Cumulative session turnover: the newest snapshot wins.
            day_value[sym] = float(q.get("value") or 0.0)

    if not last_chg:
        return None

    up = down = flat = 0
    for sym, chg in last_chg.items():
        if chg > UP_TH:
            up += 1
        elif chg < DOWN_TH:
            down += 1
        else:
            flat += 1
    total = max(1, up + down + flat)

    day_value = {
        s: v for s, v in day_value.items()
    }  # cumulative per-symbol session turnover (last snapshot)
    leaders = sorted(day_value.items(), key=lambda kv: -kv[1])[:LEADERS_N]
    liquid = {
        s: (last_chg.get(s, 0.0), v)
        for s, v in day_value.items()
        if v >= LIQUID_VALUE and s in last_chg
    }
    gainers = sorted(liquid.items(), key=lambda kv: -kv[1][0])[:GAINER_N]
    losers = sorted(liquid.items(), key=lambda kv: kv[1][0])[:GAINER_N]

    # Trending: green in every snapshot it appeared in, with turnover.
    trending = sorted(
        (
            s for s in last_chg
            if snap_seen[s] >= 2
            and green_snaps[s] == snap_seen[s]
            and last_chg[s] >= TREND_MIN_CHG
            and day_value.get(s, 0.0) >= TREND_MIN_VALUE
        ),
        key=lambda s: -day_value.get(s, 0.0),
    )[:8]

    # Dead: flat tape AND no money all session.
    dead = sorted(
        s for s, v in day_value.items()
        if v < DEAD_MAX_VALUE and abs(last_chg.get(s, 0.0)) <= DEAD_MAX_CHG
    )

    index_chg = index_chgs[-1] if index_chgs else None  # percent units
    breadth = up / total
    if index_chg is not None and index_chg >= 0.2 and breadth >= 0.55:
        verdict = "risk-on"
    elif index_chg is not None and index_chg <= -0.2 and breadth <= 0.45:
        verdict = "risk-off"
    else:
        verdict = "mixed"

    lesson = {
        "date": trading_date,
        "snapshots": len(snaps),
        "symbols": len(last_chg),
        "index_chg_pct": (
            round(index_chg, 2) if index_chg is not None else None
        ),
        "breadth_pct": round(breadth * 100, 1),
        "up": up,
        "down": down,
        "flat": flat,
        "leaders": [
            {
                "symbol": s,
                "chg_pct": round(last_chg.get(s, 0.0) * 100, 1),
                "value_m": round(v / 1e6, 1),
            }
            for s, v in leaders
        ],
        "gainers": [
            {"symbol": s, "chg_pct": round(c * 100, 1)}
            for s, (c, _v) in gainers
        ],
        "losers": [
            {"symbol": s, "chg_pct": round(c * 100, 1)}
            for s, (c, _v) in losers
        ],
        "trending": trending,
        "dead": dead,
        "flows": _flows_for(trading_date),
        "verdict": verdict,
    }
    lesson["taught"] = _taught_line(lesson)
    return lesson


def _taught_line(l: dict) -> str:
    """One human line: what the market taught today."""
    lead = ""
    if l["leaders"]:
        top = l["leaders"][0]
        lead = (
            f"; money led {top['symbol']} {top['chg_pct']:+.1f}% "
            f"(Rs {top['value_m']:.0f}M)"
        )
    idx = (
        f"index {l['index_chg_pct']:+.2f}%, "
        if l["index_chg_pct"] is not None else ""
    )
    return (
        f"{l['date']}: {l['verdict']} - {idx}breadth {l['breadth_pct']:.0f}"
        f"% up ({l['up']} adv / {l['down']} dec){lead}; "
        f"{len(l['trending'])} trending, {len(l['dead'])} dead"
    )


# ---------------------------------------------------------------------------
# The rolling store: days + streaks + confirmed lists
# ---------------------------------------------------------------------------

def update_rolling(trading_date: str, lesson: dict) -> dict:
    """Fold the day's lesson into the rolling store and recompute
    streaks. Idempotent for the same date."""
    store = _read_store()
    days = store.get("days") or {}
    days[trading_date] = lesson

    # Roll old days out.
    keep = sorted(days)[-ROLL_DAYS:]
    days = {d: days[d] for d in keep}

    dead_streak: dict[str, int] = defaultdict(int)
    trend_streak: dict[str, int] = defaultdict(int)
    for d in sorted(days):
        day = days[d]
        today_dead = set(day.get("dead") or [])
        today_trend = set(day.get("trending") or [])
        for s in set(dead_streak) | today_dead:
            dead_streak[s] = dead_streak[s] + 1 if s in today_dead else 0
        for s in set(trend_streak) | today_trend:
            trend_streak[s] = (
                trend_streak[s] + 1 if s in today_trend else 0
            )

    store = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "dead_streak": {
            s: n for s, n in dead_streak.items() if n > 0
        },
        "trend_streak": {
            s: n for s, n in trend_streak.items() if n > 0
        },
        "dead_confirmed": sorted(
            s for s, n in dead_streak.items() if n >= DEAD_STREAK_MIN
        ),
        "trend_confirmed": sorted(
            s for s, n in trend_streak.items() if n >= TREND_STREAK_MIN
        ),
        "last_date": trading_date,
    }
    LESSONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    LESSONS_PATH.write_text(
        json.dumps(store, ensure_ascii=False), encoding="utf-8"
    )
    return store


def _read_store() -> dict:
    try:
        raw = json.loads(LESSONS_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_and_store(trading_date: str) -> dict | None:
    """Analyze the session and fold it into the rolling store.

    Returns the lesson (None when the tape had nothing to teach - the
    store is left untouched so yesterday's knowledge survives).
    """
    lesson = analyze_day(trading_date)
    if lesson is None:
        return None
    update_rolling(trading_date, lesson)
    return lesson


# ---------------------------------------------------------------------------
# Engine / report reads
# ---------------------------------------------------------------------------

def load_market_lessons() -> dict:
    """The consumer view. Never raises; a missing or corrupt store
    degrades to an empty lesson (the engine trades, just uninformed).
    """
    store = _read_store()
    return {
        "dead_confirmed": set(store.get("dead_confirmed") or []),
        "trend_confirmed": set(store.get("trend_confirmed") or []),
        "last_date": store.get("last_date"),
        "last": (store.get("days") or {}).get(store.get("last_date") or ""),
        "dead_streak": store.get("dead_streak") or {},
        "trend_streak": store.get("trend_streak") or {},
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Build today's market lesson from the stored tape."
    )
    parser.add_argument(
        "--date", default=None,
        help="trading date (default: today)",
    )
    args = parser.parse_args(argv)
    from psx_core import sessions

    date = args.date or sessions.trading_date(
        datetime.now(timezone.utc)
    ).isoformat()
    lesson = build_and_store(date)
    if lesson is None:
        print(f"no usable snapshot tape for {date}; no lesson stored")
        return 1
    print(lesson["taught"])
    store = _read_store()
    print(
        f"dead_confirmed: {len(store.get('dead_confirmed') or [])} | "
        f"trend_confirmed: {len(store.get('trend_confirmed') or [])}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
