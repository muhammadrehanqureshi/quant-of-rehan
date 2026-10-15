"""The PSX Data Portal adapter: the session snapshot, and nothing finer.

Measured on 2026-10-14 before this adapter was written, so the shape below is
what the source actually serves rather than what its documentation promises:

* ``GET https://dps.psx.com.pk/timeseries/eod/{symbol}`` returns an HTML
  shell (404 with JSON headers too), so the portal's old JSON EOD endpoint is
  gone. This project's own data memo already records that, which is why no
  daily history is claimed here.
* ``GET https://dps.psx.com.pk/timeseries/int/{symbol}`` is a 404: there is
  no public intraday series.
* ``GET https://dps.psx.com.pk/company/{symbol}`` carries the REG panel with
  Open, High, Low, Volume and Total Trades, the last price in
  ``class="quote__close"``, and the portal's own publication stamp in
  ``class="quote__date"`` ("As of Wed, Oct 14, 2026 3:21 PM").

So this adapter serves exactly one resolution, ``session``: a single bar for
the trading day so far. It never claims to be a minute series, and it states
the portal's own delay in the payload. The panel parsing is delegated to
``src/data/market_snapshot.parse_symbol_quote``, the project's tested reader,
rather than being re-implemented here (SO-8: one authority per question).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data import market_snapshot  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

from charts import sessions  # noqa: E402
from charts.adapters.base import Capabilities  # noqa: E402
from charts.contract import (  # noqa: E402
    RESOLUTION_SESSION, SOURCE_PORTAL, Bar, SourceInfo,
)
from charts.ratelimit import (  # noqa: E402
    CircuitBreaker, Ledger, TokenBucket, UpstreamError, retry_call,
)

COMPANY_URL = "https://dps.psx.com.pk/company/{symbol}"

#: The portal's own published delay: its pages say data is delayed five
#: minutes unless indicated otherwise. Carried so the chart can say it.
PORTAL_DELAY_SECONDS = 300

SOURCE = SourceInfo(
    id=SOURCE_PORTAL,
    label="PSX Data Portal company page (REG session panel)",
    delay_seconds=PORTAL_DELAY_SECONDS,
    note="the portal publishes a session snapshot, not an intraday series",
)

_LAST_PRICE = re.compile(r'quote__close[^>]*>\s*(?:Rs\.?)?\s*([0-9][0-9,.]*)')
_AS_OF = re.compile(r'quote__date[^>]*>\s*\^?\s*As of\s*([^<]+)')

#: Four requests a second at most, one at a time in hand: the project's own
#: memo asks for politeness, and a chart poll is never urgent.
BUCKET = TokenBucket(rate_per_second=0.4, burst=1)
BREAKER = CircuitBreaker(fail_threshold=3, reset_after_seconds=90.0)


@dataclass(frozen=True)
class SessionSnapshot:
    """One trading day's snapshot, with the portal's own stamp."""

    symbol: str
    last: float | None
    as_of_note: str
    quote: dict


def _number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = text.strip().replace(",", "").replace("Rs.", "").replace("Rs", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_company_page(html: str, symbol: str) -> SessionSnapshot:
    """Read the session snapshot out of a company page, or say why not."""
    quote = market_snapshot.parse_symbol_quote(html, symbol)
    if not quote:
        raise UpstreamError(
            UpstreamError.EMPTY_ACK,
            f"the portal served a company page for {symbol} with no usable "
            f"REG session panel: the market may be shut, or the page changed")
    found = _LAST_PRICE.search(html)
    stamp = _AS_OF.search(html)
    return SessionSnapshot(
        symbol=symbol.strip().upper(),
        last=_number(found.group(1) if found else None),
        as_of_note=(stamp.group(1).strip() if stamp else ""),
        quote=quote,
    )


class PortalSource:
    """The portal, as a politely paced session-snapshot source."""

    name = SOURCE_PORTAL

    def __init__(self, *, clock=now_karachi, http=None,
                 bucket: TokenBucket | None = None,
                 breaker: CircuitBreaker | None = None,
                 sleep=None):
        import time

        self._clock = clock
        self._bucket = bucket or BUCKET
        self._breaker = breaker or BREAKER
        self._sleep = sleep or time.sleep
        self._ledger = Ledger()
        self._session = http
        self._pages: dict[str, tuple[str, dict]] = {}

    # -------------------------------------------------------- capabilities
    def capabilities(self) -> Capabilities:
        return Capabilities(source=SOURCE, resolutions=(RESOLUTION_SESSION,),
                            live=True, local=False)

    def catalog(self) -> list[dict]:
        from charts.adapters.tape import read_universe

        return [{"symbol": symbol, "source": SOURCE_PORTAL, "listed": True}
                for symbol in read_universe()]

    # ------------------------------------------------------------- fetching
    def _http(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers.update({
                "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/124.0 Safari/537.36"),
                "accept": "text/html,application/xhtml+xml",
            })
        return self._session

    def _fetch(self, symbol: str) -> SessionSnapshot:
        """One bounded, paced, retried request for one symbol's page."""
        def call() -> SessionSnapshot:
            wait = self._bucket.acquire()
            if wait:
                self._sleep(wait)
            self._ledger.record_attempt()
            try:
                response = self._http().get(COMPANY_URL.format(symbol=symbol),
                                            timeout=(5, 15))
            except Exception as exc:  # noqa: BLE001 - named below, never silent
                name = type(exc).__name__
                category = (UpstreamError.TIMEOUT if "Timeout" in name
                            else UpstreamError.CONNECTION)
                raise UpstreamError(category,
                                    f"{symbol}: {name}") from exc
            if response.status_code == 429:
                raise UpstreamError(UpstreamError.RATE_LIMITED,
                                    f"{symbol}: the portal asked us to slow "
                                    f"down", status=429)
            if response.status_code >= 400:
                raise UpstreamError(
                    UpstreamError.HTTP_ERROR,
                    f"{symbol}: HTTP {response.status_code}",
                    status=response.status_code)
            return parse_company_page(response.text, symbol)

        return retry_call(
            call, attempts=3, base_delay=0.6, max_delay=6.0,
            breaker=self._breaker, sleep=self._sleep,
            on_retry=lambda attempt, exc, delay: self._ledger.record_retry(exc),
        )

    # ------------------------------------------------------------- reading
    def snapshot(self, symbol: str) -> SessionSnapshot:
        return self._fetch(symbol)

    def history(self, symbol: str, resolution: str = RESOLUTION_SESSION, *,
                limit: int = 500) -> list[Bar]:
        if resolution != RESOLUTION_SESSION:
            raise UpstreamError(
                UpstreamError.SCHEMA_CHANGE,
                f"the portal serves a single {RESOLUTION_SESSION} bar, not "
                f"{resolution}; use the broker tape for minute bars")
        snapshot = self._fetch(symbol)
        bar = self._session_bar(snapshot)
        return [bar] if bar else []

    def latest(self, symbol: str, resolution: str = RESOLUTION_SESSION, *,
               since: str | None = None) -> list[Bar]:
        bars = self.history(symbol, resolution)
        if since:
            bars = [bar for bar in bars if bar.t >= since]
        return bars

    def _session_bar(self, snapshot: SessionSnapshot) -> Bar | None:
        quote = snapshot.quote
        high = _number(str(quote.get("high") or ""))
        low = _number(str(quote.get("low") or ""))
        opened = _number(str(quote.get("open") or ""))
        volume = _number(str(quote.get("volume") or ""))
        last = snapshot.last
        if high is None or low is None:
            return None
        # A shut or cleared panel publishes zeroes; that is not a bar.
        if high <= 0 or low <= 0:
            return None
        start = sessions.session_window(self._clock())
        if start is None:
            return None
        open_price = opened if opened is not None else last
        close_price = last if last is not None else opened
        if open_price is None or close_price is None:
            return None
        return Bar.build(t=start[0], o=open_price, h=high, l=low,
                         c=close_price, v=volume or 0.0)

    def notes(self, snapshot: SessionSnapshot | None) -> list[str]:
        lines = list(self._ledger.notes())
        if snapshot is not None:
            if snapshot.as_of_note:
                lines.append(
                    f"the portal's own stamp for this snapshot: "
                    f"{snapshot.as_of_note}")
            lines.append(
                f"the portal publishes with a delay of about "
                f"{PORTAL_DELAY_SECONDS // 60} minutes and serves a session "
                f"snapshot, not an intraday series")
        return lines

    def session_bar_for(self, symbol: str) -> tuple[Bar | None, list[str]]:
        """The session bar plus the notes that explain it, for the API."""
        snapshot = self._fetch(symbol)
        return self._session_bar(snapshot), self.notes(snapshot)
