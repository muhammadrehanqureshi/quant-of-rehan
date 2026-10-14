"""The contract every data adapter implements.

This is the seam the whole service is built around, and it exists because of
what the reference projects teach by omission. `mnwato/tradingview-scraper`
(MIT) mixes transport, protocol frames, extraction and consumer delivery into
one stream path, and its own code has no reconnect or backoff loop. The layer
that is missing there is a source contract: a source should be able to say
what it can deliver, deliver it, and fail in a named way, without knowing
anything about who consumes it. No code is taken from that project; the
lesson from its shape is what is implemented here.

So an adapter is a small object with four abilities:

* ``capabilities()`` says which resolutions it genuinely serves and how
  delayed it is. The service never asks a daily source for minute bars, and
  never draws a 1-minute candle from a session snapshot.
* ``history(symbol, resolution, limit)`` returns past bars, oldest first.
* ``latest(symbol, resolution)`` returns the newest bar(s) only, which is
  what a live chart needs and what a polite poller should ask for.
* ``catalog()`` returns the symbols it knows, again without pretending to
  know more than it does.

Failures are ``ratelimit.UpstreamError`` with a category (TIMEOUT,
CONNECTION, RATE_LIMITED, HTTP_ERROR, SCHEMA_CHANGE, EMPTY_ACK), so an
upstream that answers 200 with no data is a *named* failure rather than an
empty chart: that distinction is exactly the one that cost this project a
day of silent capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from charts.contract import Bar, SourceInfo


@dataclass(frozen=True)
class Capabilities:
    """What an adapter honestly offers."""

    source: SourceInfo
    resolutions: tuple[str, ...]
    #: True when the adapter can be polled inside a live session.
    live: bool
    #: True when the adapter reads this machine's own banked data.
    local: bool = False

    def serves(self, resolution: str) -> bool:
        return resolution in self.resolutions


class BarSource(Protocol):
    """One data source, seen through the only interface the service uses."""

    name: str

    def capabilities(self) -> Capabilities:
        ...

    def catalog(self) -> list[dict]:
        ...

    def history(self, symbol: str, resolution: str, *,
                limit: int = 500) -> list[Bar]:
        ...

    def latest(self, symbol: str, resolution: str, *,
               since: str | None = None) -> list[Bar]:
        ...
