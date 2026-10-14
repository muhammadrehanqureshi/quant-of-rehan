"""The session facts a chart needs, from the one law that owns them.

`src/data/sessions.py` is the single authority on PSX hours, bands, holidays
and phases (SO-8, one authority per question). This module does not restate
those facts and does not keep a second table that could drift from them; it
calls the authority and shapes the answer into the chart contract's
``MarketContext``.

Everything here is server side on purpose. The browser receives the resolved
phase and the next event in the payload instead of computing them from its
own clock, so the chart, the phone app, the relay and the scanners can never
disagree about whether the exchange is trading.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import sessions as law  # noqa: E402

from charts.contract import MarketContext  # noqa: E402


def _band_of(moment: datetime) -> dict | None:
    band = law.current_band(moment)
    if band is None:
        return None
    return {"open": f"{band.open[0]:02d}:{band.open[1]:02d}",
            "close": f"{band.close[0]:02d}:{band.close[1]:02d}"}


def _next_event(moment: datetime) -> dict | None:
    """The next band edge today, or the next trading day's open.

    The chart shades the coming break or close with this, and the phone's
    card shows the same sentence, so the two cannot drift.
    """
    for step in range(0, 8):
        candidate = law.as_karachi(moment) + law.timedelta(days=step)
        probe_day = candidate.date()
        if not law.is_trading_day(probe_day):
            continue
        for band in law.session_bands(probe_day):
            opened = law.band_bounds(probe_day, band)[0]
            closed = law.band_bounds(probe_day, band)[1]
            if step == 0 and opened > moment:
                return {"event": "OPEN", "at": opened.isoformat(
                    timespec="seconds")}
            if step == 0 and closed > moment:
                return {"event": "CLOSE", "at": closed.isoformat(
                    timespec="seconds")}
            if step > 0:
                return {"event": "OPEN", "at": opened.isoformat(
                    timespec="seconds")}
    return None


def market_context(moment: datetime | None = None) -> MarketContext:
    """The session facts for `moment` (Karachi clock), or now."""
    now = law.as_karachi(moment)
    phase = law.market_phase(now)
    state = law.market_state_at(now)
    return MarketContext(
        phase=str(getattr(phase, "value", phase)),
        state=str(getattr(state, "value", state)),
        trading_day=law.is_trading_day(now.date()),
        timezone=str(law.KARACHI),
        band=_band_of(now),
        next_event=_next_event(now),
        as_of=now.isoformat(timespec="seconds"),
    )


def session_window(moment: datetime | None = None) -> tuple[datetime, datetime] | None:
    """Today's session bounds, or None on a non trading day."""
    now = law.as_karachi(moment)
    if not law.is_trading_day(now.date()):
        return None
    return law.session_bounds(now.date())


def expected_minutes(moment: datetime | None = None,
                     *, now_only: bool = True) -> list[datetime]:
    """Every minute the exchange is expected to print, up to `moment`.

    A chart draws its gaps from this: a minute inside the session with no bar
    is a gap, and a minute outside the session is not a gap at all. The
    Friday midday break is therefore never reported as missing data, which is
    the whole point of asking the session law instead of assuming a
    continuous day.
    """
    now = law.as_karachi(moment)
    minutes: list[datetime] = []
    for band in law.session_bands(now.date()):
        opened, closed = law.band_bounds(now.date(), band)
        cursor = opened
        while cursor <= closed:
            if not now_only or cursor <= now:
                minutes.append(cursor)
            cursor += law.timedelta(minutes=1)
    return minutes
