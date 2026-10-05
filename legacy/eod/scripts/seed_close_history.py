"""One-off seed: backfill the EOD's close_history.json from the 54-session
corpus so the v2.3.0 lock-history rank features work on their first day.

The live history held a single session; lock_days/green_streak would
have read every Monday candidate as a first lock (47.4% class) even
when the tape said 3rd lock (67.5% class). Records carry chg + close;
high/low stay absent (the streak features read chg only).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EOD = Path(__file__).resolve().parents[1]
CORPUS = EOD.parent / "PSX-KMIALL-Bot" / "data" / "backtest" / "eod_corpus.json"
HIST = EOD / "data" / "close_history.json"

KEEP = 10  # close_history keeps the last 10 sessions


def main() -> int:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    hist = json.loads(HIST.read_text(encoding="utf-8"))
    sessions = hist.setdefault("sessions", {})

    dates: set[str] = set()
    for rows in corpus.values():
        for r in rows:
            dates.add(r["date"])
    all_dates = sorted(dates)
    # every session strictly before today's pick candidates; the live
    # file already holds the last real session - never overwrite it.
    seed_dates = all_dates[-(KEEP + 1):-1]

    added = 0
    for d in seed_dates:
        if d in sessions:
            continue
        day = {}
        for sym, rows in corpus.items():
            for i, r in enumerate(rows):
                if r["date"] != d or i == 0:
                    continue
                prev = rows[i - 1]["close"]
                if prev and prev > 0 and r["close"]:
                    day[sym] = {
                        "chg": round((r["close"] / prev - 1.0) * 100.0, 3),
                        "c": r["close"],
                        "vol": r["volume"],
                        "seeded": True,
                    }
                break
        if day:
            sessions[d] = day
            added += 1

    for old in sorted(sessions.keys())[:-KEEP]:
        sessions.pop(old, None)

    HIST.write_text(json.dumps(hist, indent=1), encoding="utf-8")
    print(f"seeded {added} sessions; history now holds {len(sessions)}: "
          f"{sorted(sessions.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
