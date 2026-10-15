"""A labelled replay source: deterministic bars, for tests and the demo.

This adapter exists so the pipeline can be proven without a network and
without the owner's tape: the renderer's gap handling, the store's upsert and
revision counting, the SSE fan-out and the API's shapes are all exercised
here, and none of that needs a live exchange. It is deterministic: the same
symbol and the same day always produce the same series, so a test can assert
exact numbers and a screenshot can be reproduced.

One rule decides the day it draws: the session of ``as_of`` once that
session has begun, and otherwise the most recent earlier trading day. A demo
or a test therefore renders a real session at 03:00 as well as at noon
instead of an empty frame, and a holiday falls back to the last day the
exchange actually traded. The clock is injectable for exactly this reason:
with a fixed clock the same symbol and the same day produce the same series
at every hour, which is what lets a test assert exact numbers.

It is honest about itself in the one place that matters. Its source id is
``replay``, its label says synthetic, and the service refuses to start with
it unless the operator asked for it explicitly (``--source replay``). No
synthetic bar can reach the production path by accident, which is the same
rule the project's TEST canary follows.
"""

from __future__ import annotations

import random
from datetime import date, datetime

from charts import sessions
from charts.adapters.base import Capabilities
from charts.contract import (
    RESOLUTION_MINUTE, SOURCE_REPLAY, Bar, SourceInfo,
)

SOURCE = SourceInfo(
    id=SOURCE_REPLAY,
    label="synthetic replay series (tests and the offline demo)",
    delay_seconds=0,
    note="deterministic, generated on this machine; never a market print",
)


class ReplaySource:
    """A deterministic walk across the session's own minutes.

    ``clock`` decides which session it walks (see the module docstring): the
    default is the Karachi now, so a live demo follows today, and a test
    hands it a fixed moment so the numbers never move under the assertions.
    """

    name = SOURCE_REPLAY

    def __init__(self, *, symbols: list[str] | None = None,
                 start_price: float = 100.0,
                 gaps: tuple[int, ...] = (), clock=sessions.law.as_karachi):
        self._symbols = [symbol.upper() for symbol in (symbols or
                                                       ["REPLAY1", "REPLAY2"])]
        self._start = start_price
        self._gaps = set(gaps)
        self._clock = clock

    def capabilities(self) -> Capabilities:
        return Capabilities(source=SOURCE, resolutions=(RESOLUTION_MINUTE,),
                            live=True, local=True)

    def catalog(self) -> list[dict]:
        return [{"symbol": symbol, "source": SOURCE_REPLAY, "listed": True}
                for symbol in self._symbols]

    def _session_day(self, as_of: datetime) -> date:
        """The trading day this series describes, given the clock.

        Today once its session has begun; before that, and on any day the
        exchange does not trade, the most recent earlier trading day. The
        walk is bounded: a two week holiday would be a data problem of its
        own, and this source must never spin looking for a session.
        """
        today = as_of.date()
        if sessions.law.is_trading_day(today):
            first = sessions.session_minutes(today)[0]
            if first <= as_of:
                return today
        for step in range(1, 15):
            earlier = today - sessions.law.timedelta(days=step)
            if sessions.law.is_trading_day(earlier):
                return earlier
        return today

    def _series(self, symbol: str, as_of: datetime) -> list[Bar]:
        day = self._session_day(as_of)
        minute = sessions.session_minutes(day)
        if day == as_of.date():
            # Today's series grows with the clock: the part of the session
            # that has not happened yet is not a bar and not a gap either.
            minute = [moment for moment in minute if moment <= as_of]
        seed = f"{symbol.upper()}|{day.isoformat()}"
        rng = random.Random(seed)
        price = self._start
        bars: list[Bar] = []
        for index, moment in enumerate(minute):
            if index in self._gaps:
                continue  # a deliberate hole, so gap rendering is provable
            drift = rng.uniform(-0.004, 0.0045)
            opened = price
            closed = max(0.01, opened * (1.0 + drift))
            high = max(opened, closed) * (1.0 + rng.uniform(0.0, 0.003))
            low = min(opened, closed) * (1.0 - rng.uniform(0.0, 0.003))
            volume = float(rng.randint(500, 25000))
            # The last bar is the newest minute in the series. On a live
            # clock that is the minute still forming right now, the row the
            # store republishes and revises on the next poll, which is
            # exactly the behaviour the revision counter exists to show.
            bars.append(Bar.build(t=moment, o=round(opened, 2),
                                  h=round(high, 2), l=round(low, 2),
                                  c=round(closed, 2), v=volume))
            price = closed
        return bars

    def history(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
                limit: int = 500) -> list[Bar]:
        bars = self._series(symbol, self._clock())
        return bars[-limit:] if limit else bars

    def latest(self, symbol: str, resolution: str = RESOLUTION_MINUTE, *,
               since: str | None = None) -> list[Bar]:
        # The whole session, like the other sources: a chart that opens at
        # noon should see the morning, not the last three minutes of it.
        bars = self.history(symbol, resolution, limit=0)
        if since:
            bars = [bar for bar in bars if bar.t >= since]
        return bars

    def notes(self, symbol: str) -> list[str]:
        if self._gaps:
            return [f"this replay series omits minute indexes "
                    f"{sorted(self._gaps)} on purpose, to exercise gap "
                    f"reporting"]
        return []
