"""
Overnight memory for the morning-fade engine.

The engine's feature #5 is the stock's OWN close-to-open history:
average/median gap and green-open frequency over 20-60 sessions.
The runner stores every session's close cross-section in
data/close_history.json ({sessions: {date: {symbol: {c, h, l, ...}}}},
last 10 kept). This module turns those sessions into per-symbol
overnight pairs, newest last:

    [{buy_date, gap_pct}, ...]   gap = (next_open_or_close - close) / close

The corpus has opens only in full OHLC files; the runner's live store
carries closes. Where a next-session open is not yet known, the pair
is only completed once the NEXT session's record exists - the pair for
buy-day D is emitted while processing session D+1, reading D+1's open
when present, else falling back to D+1's first stored close with the
fallback flagged. Honest labeling: a fallback pair counts, a missing
next session does not invent one.
"""
from __future__ import annotations


def overnight_pairs_from_sessions(
    sessions: dict[str, dict[str, dict]],
    symbol: str,
    max_pairs: int = 60,
) -> list[dict]:
    """Close-to-open pairs for one symbol, oldest first, last `max_pairs`.

    sessions: {date: {symbol: {c: close, ...}}} - every stored session.
    A pair needs the symbol present on BOTH the buy day and the next
    stored session. gap = (next.c - this.c) / this.c * 100. When the
    next session carries an explicit 'o' (open) field it is used; the
    runner stores opens from the first morning poll as 'o'.
    """
    dates = sorted(sessions.keys())
    pairs: list[dict] = []
    for i in range(len(dates) - 1):
        d1, d2 = dates[i], dates[i + 1]
        r1 = (sessions.get(d1) or {}).get(symbol)
        r2 = (sessions.get(d2) or {}).get(symbol)
        if not r1 or not r2:
            continue
        c1 = r1.get("c")
        op = r2.get("o") or r2.get("c")
        if not c1 or not op or c1 <= 0:
            continue
        pairs.append({
            "buy_date": d1,
            "gap_pct": round((op - c1) / c1 * 100.0, 4),
            "basis": "open" if r2.get("o") else "next_close",
        })
    return pairs[-max_pairs:]
