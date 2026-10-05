"""
Market-feed access for The Sentinel.

v4.0.0 - the feed is the owner's ECLEAR broker terminal (read-only).
psxterminal.com is retired: the broker is a paid, regulated business
and its data tier is authoritative. `psx_core.broker_feed` speaks the
wire (MKT-FEED socket on 8484, no auth; ScripServlet master list;
EXS-FEED index) and this module keeps the public contract every
caller already holds:

  fetch_snapshot(http, market, timeout, min_instruments)
      -> {requestTime, receiveTime, bytes, parser, instruments, index}
      instruments[symbol] = {
          market, status, symbol, price, change, changePercent,
          volume, trades, value, high, low, bid, ask, bidVol, askVol,
          timestamp }
      changePercent stays a FRACTION (0.00563 = +0.563%), exactly as
      the retired feed delivered it - normalization to a true percent
      remains the dataset builder's job (normalize_change_percent).

The http session parameter is accepted and ignored: the broker feed is
a raw socket plus its own HTTP endpoints, not a scraped page. Callers
pass their session unchanged, so no call site moves.

Scope: fetch_snapshot subscribes the broker's own shariah symbol list
(GetShariahSymbol) plus the stored KMIALL universe - the bot's whole
world. Full-market reach is unnecessary; the bot trades KMIALL only.

Hard rails (inherited from the psxterminal era, unchanged in spirit):
a degenerate capture raises rather than writing a silently empty or
half-delivered snapshot. The previous collector's lesson - a field
reordering that broke half the symbols must never reach disk - applies
equally to a socket that delivers half the burst.
"""

from __future__ import annotations

import math
import time

from . import broker_feed, universe

MARKET_URL = "eclear://nxg1.eclear.com.pk:8484/MKT-FEED"  # identity only

# The broker feed serves the REG market only (rejected otherwise in
# fetch_snapshot); kept as a module constant so call sites that read
# feed.DEFAULT_MARKET keep working unchanged.
DEFAULT_MARKET = "REG"

# The stored KMIALL universe carried 311 symbols at v4.0.0; the broker's
# shariah list is a similar size. 200 leaves room for genuinely untraded
# names on a thin session while still catching a broken subscribe or a
# truncated burst.
MIN_EXPECTED_INSTRUMENTS = 200

# Instrument status codes seen in the feed (broker field [6]).
STATUS_OPEN = "OPN"
STATUS_SUSPENDED = "SUS"

# Seconds the socket listens after subscribing. The server pushes the
# current state of every subscribed scrip on subscribe and refreshes on
# every trade; live probes delivered the burst well inside this window.
LISTEN_SECONDS = 4.0

# ScripServlet master cache (broker_feed holds the real cache); a warm
# snapshot needs one socket listen and zero HTTP calls.
_MASTER_MIN = 300


class FeedError(RuntimeError):
    """Raised when the feed cannot be fetched or parsed to a usable state."""


def parse_number(value: object) -> float | None:
    """Parse a feed numeric, mapping null/undefined/non-finite to None."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if text in ("", "null", "undefined", "NaN"):
            return None
        value = text
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_int(value: object) -> int | None:
    number = parse_number(value)
    return None if number is None else int(number)


def normalize_change_percent(fraction: float | None) -> float | None:
    """
    Convert the feed's `changePercent` fraction to a true percent.

    The feed sends 0.00563 to mean +0.563%. Verified two ways in the
    psxterminal era (reconstruction ratio 1.0000, and the field's
    observed range spanning exactly the +/-10% circuit breaker); the
    broker feed stores the same fraction by construction
    (change / previous close). The scale contract is unchanged.
    """
    return None if fraction is None else fraction * 100.0


def _subscribe_symbols() -> list[str]:
    """
    The subscription set: the stored KMIALL universe plus the broker's
    own shariah list. Both are cheap (one local file, one HTTP call,
    the latter cached inside broker_feed). The union keeps the snapshot
    stable across a universe refresh lag: a symbol that joined KMIALL
    yesterday ticks today even if the stored file is one refresh behind.
    """
    symbols: dict[str, None] = {}
    try:
        stored = universe.load(shariah_only=False, exclude_etf_sectors=False)
    except Exception:  # noqa: BLE001 - a missing/corrupt file must not
        stored = []    # kill the snapshot; the shariah list still rides
    for symbol in stored:
        symbols[symbol.strip().upper()] = None
    try:
        for symbol in sorted(broker_feed.fetch_shariah_symbols()):
            symbols[symbol] = None
    except Exception:  # noqa: BLE001 - list is an addition, not a gate
        pass
    if not symbols:
        raise FeedError(
            "empty subscription set: universe file missing and the "
            "broker shariah list unreachable"
        )
    return list(symbols)


def fetch_snapshot(
    session=None,
    market: str = "REG",
    timeout: float = 30.0,
    min_instruments: int = MIN_EXPECTED_INSTRUMENTS,
) -> dict:
    """
    Fetch and parse one market snapshot from the broker feed.

    Raises FeedError rather than returning a partially parsed result, so
    a silently degraded snapshot never reaches disk.
    """
    del session  # compatibility: the broker feed carries its own session

    if market != "REG":
        raise FeedError(
            f"market {market!r} not served by the broker feed integration "
            "(the bot trades REG only)"
        )

    symbols = _subscribe_symbols()
    listen = max(timeout, LISTEN_SECONDS) if timeout < LISTEN_SECONDS else LISTEN_SECONDS

    try:
        data = broker_feed.subscribe_snapshot(
            symbols,
            listen_seconds=listen,
            min_instruments=min_instruments,
        )
    except broker_feed.BrokerFeedError as exc:
        raise FeedError(str(exc)) from exc

    # Belt and braces: the contract layer re-checks the floor even when
    # the wire layer's own rail is bypassed (e.g. a monkeypatched
    # subscribe in tests, or a future wire change).
    got = len(data.get("instruments") or {})
    if got < min_instruments:
        raise FeedError(
            f"degenerate capture: {got} instruments < floor {min_instruments}"
        )

    return data


def build_universe_snapshot(
    market_data: dict,
    symbols: list[str],
    market: str = "REG",
) -> dict:
    """Project a full-market snapshot down to the KMIALL universe."""
    instruments = market_data["instruments"]

    quotes: dict[str, dict] = {}
    unavailable: list[str] = []

    for symbol in symbols:
        quote = instruments.get(symbol)
        if quote is None:
            unavailable.append(symbol)
        else:
            quotes[symbol] = quote

    open_count = sum(
        1 for quote in quotes.values() if quote["status"] == STATUS_OPEN
    )

    return {
        "generatedAt": market_data["receiveTime"],
        "source": "ECLEAR broker feed (read-only)",
        "market": market,
        "universeCount": len(symbols),
        "quoteAvailable": len(quotes),
        "quoteUnavailable": len(unavailable),
        "quoteOpen": open_count,
        "quoteSuspended": len(quotes) - open_count,
        "quoteUnavailableSymbols": unavailable,
        "requestTime": market_data["requestTime"],
        "receiveTime": market_data["receiveTime"],
        "sourceBytes": market_data["bytes"],
        "parser": market_data.get("parser", "eclear-mkt-feed"),
        "marketInstrumentCount": len(instruments),
        "quotes": quotes,
        "index": market_data.get("index"),
    }
