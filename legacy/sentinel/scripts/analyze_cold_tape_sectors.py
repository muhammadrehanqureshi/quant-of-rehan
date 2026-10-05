"""Cold-tape sector-strength analyzer.

The question (raised 2026-09-14, when ATRL/NRL/PRL rallied +2..+6% while
market breadth sat at 28-33%, below the 35% hard floor):

    Should a strongly-green SECTOR be allowed past the breadth floor?

This tool gathers the evidence instead of arguing. It scans every stored
session and finds every moment where, simultaneously:
  * market breadth (OPN, change%) was below 35%, and
  * some sector with >= 3 open members was >= 70% green with an average
    change of at least +0.5%,
then measures what that sector's members actually did over the following
45 minutes (max rise, max drawdown) and to the session close.

One event per (session, sector) per 20 minutes (the first qualifying
moment) so a morning-long regime does not spam thousands of rows.

Output: console summary + JSONL rows in data/cold_tape_events.jsonl.

Run anytime: python scripts/analyze_cold_tape_sectors.py
Takes about a minute for a week of sessions; it reads snapshots only.
"""
from __future__ import annotations

import gzip
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from psx_core import paths  # noqa: E402

PKT = timezone(timedelta(hours=5))

MARKET_FLOOR = 35.0
SECTOR_MIN_MEMBERS = 3
SECTOR_GREEN_FRAC = 0.70
SECTOR_MIN_AVG_CHG_PCT = 0.5  # percent; quotes store changePercent as a fraction
FORWARD_MINUTES = 45
EVENT_DEBOUNCE_MIN = 20


def load_sessions() -> list[Path]:
    return sorted(paths.SNAPSHOT_DIR.glob("*.jsonl.gz"))


def sector_members(symbol_to_sector: dict) -> dict[str, list[str]]:
    by_sector: dict[str, list[str]] = defaultdict(list)
    for sym, sec in symbol_to_sector.items():
        by_sector[sec].append(sym)
    return dict(by_sector)


def analyze_session(path: Path, by_sector: dict[str, list[str]]) -> list[dict]:
    lines = gzip.open(path).read().decode("utf-8").strip().splitlines()
    snaps = [json.loads(l) for l in lines if l.strip()]
    if not snaps:
        return []

    events: list[dict] = []
    last_event_at: dict[str, datetime] = {}

    for idx, snap in enumerate(snaps):
        quotes = snap["quotes"]
        valid = [
            q for q in quotes.values()
            if q.get("status") == "OPN" and q.get("changePercent") is not None
        ]
        if len(valid) < 50:
            continue
        breadth = 100 * sum(1 for q in valid if q["changePercent"] > 0) / len(valid)
        if breadth >= MARKET_FLOOR:
            continue

        ts = snap.get("receiveTime") or snap.get("generatedAt")
        try:
            t = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)

        for sector, members in by_sector.items():
            prev = last_event_at.get(sector)
            if prev and (t - prev) < timedelta(minutes=EVENT_DEBOUNCE_MIN):
                continue
            mq = [
                quotes[m] for m in members
                if m in quotes
                and quotes[m].get("status") == "OPN"
                and quotes[m].get("changePercent") is not None
            ]
            if len(mq) < SECTOR_MIN_MEMBERS:
                continue
            green = sum(1 for q in mq if q["changePercent"] > 0)
            avg_chg_pct = statistics.fmean(q["changePercent"] for q in mq) * 100
            if green / len(mq) < SECTOR_GREEN_FRAC or avg_chg_pct < SECTOR_MIN_AVG_CHG_PCT:
                continue

            last_event_at[sector] = t
            # Forward measurement at 5-second resolution.
            cutoff = t + timedelta(minutes=FORWARD_MINUTES)
            fwd: list[dict] = []
            for q in mq:
                sym, p0, t0 = q["symbol"], q["price"], t
                hi, lo, p_end = p0, p0, None
                for later in snaps[idx + 1:]:
                    lq = later["quotes"].get(sym)
                    if not lq or lq.get("status") != "OPN":
                        continue
                    lt = later.get("receiveTime") or later.get("generatedAt")
                    try:
                        lt = datetime.fromisoformat(lt)
                    except (TypeError, ValueError):
                        continue
                    if lt.tzinfo is None:
                        lt = lt.replace(tzinfo=timezone.utc)
                    if lt > cutoff:
                        break
                    p = lq["price"]
                    hi, lo = max(hi, p), min(lo, p)
                    p_end = p
                fwd.append({
                    "symbol": sym,
                    "max_ret_pct": (hi - p0) / p0 * 100,
                    "min_ret_pct": (lo - p0) / p0 * 100,
                    "ret_45m_pct": None if p_end is None else (p_end - p0) / p0 * 100,
                })

            events.append({
                "session": path.stem.replace(".jsonl", ""),
                "time_pkt": t.astimezone(PKT).strftime("%H:%M:%S"),
                "market_breadth_pct": round(breadth, 1),
                "sector": sector,
                "sector_green": f"{green}/{len(mq)}",
                "sector_avg_chg_pct": round(avg_chg_pct, 2),
                "members": fwd,
            })

    return events


def summarize(events: list[dict]) -> None:
    if not events:
        print("No cold-tape hot-sector events found in stored sessions.")
        return
    maxes = [m["max_ret_pct"] for e in events for m in e["members"]]
    mins = [m["min_ret_pct"] for e in events for m in e["members"]]
    reached = sum(1 for m in maxes if m >= 2.0)
    print(f"\n{len(events)} events across stored sessions:")
    for e in events:
        best = max(m["max_ret_pct"] for m in e["members"])
        worst = min(m["min_ret_pct"] for m in e["members"])
        print(
            f"  {e['session']} {e['time_pkt']}  mkt {e['market_breadth_pct']}%  "
            f"{e['sector']:24s} {e['sector_green']} green  "
            f"avg {e['sector_avg_chg_pct']:+.2f}%  -> 45m best {best:+.2f}% / worst {worst:+.2f}%"
        )
    print(f"\nMember-polls: {len(maxes)} | median 45m best {statistics.median(maxes):+.2f}% "
          f"| median 45m worst {statistics.median(mins):+.2f}%")
    print(f"Members reaching +2.0% from event price within 45m: {reached}/{len(maxes)} "
          f"({100*reached/len(maxes):.0f}%)")


def main() -> None:
    smap = json.loads((paths.DATA_DIR / "sector_map.json").read_text(encoding="utf-8"))
    by_sector = sector_members(smap["symbolToSector"])

    all_events: list[dict] = []
    for path in load_sessions():
        ev = analyze_session(path, by_sector)
        print(f"{path.name}: {len(ev)} event(s)")
        all_events.extend(ev)

    summarize(all_events)

    out = paths.DATA_DIR / "cold_tape_events.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for e in all_events:
            f.write(json.dumps(e) + "\n")
    print(f"\nWrote {len(all_events)} rows -> {out}")


if __name__ == "__main__":
    main()
