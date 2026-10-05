"""
ECLEAR broker feed client (read-only).

Source of truth for every price the bot consumes. The owner's standing
order: the broker is a paid, regulated business - its data tier is the
primary feed. psxterminal.com is retired everywhere.

Wire surfaces (all verified live 2026-09-25, market hours):

  MKT-FEED  nxg1.eclear.com.pk:8484, no auth. Subscribe exactly as the
            official app does: "MKT-FEED|" + "SYM:REG;" per symbol + "%"
            (the app's Logs.ActiveWatchList.toString() override joins with
            semicolons; my first probes failed with brackets because the
            plain Java list shape was assumed). Rows arrive as
                MKT-FEED*<tick>||<tick>||...%
            fields semicolon-joined per FeedClient.java's bean setters:
              [0] scrip   [1] market  [2] bidVol  [3] bid    [4] ask
              [5] askVol  [6] state   [7] dir     [8] change
              [9] lastTradeTime "HH:MM:SS"        [10] last price
              [11] flag   [12] avg (VWAP)         [13] high
              [14] low    [15] total trades       [16] total volume
              [17] lastTradeVol  [18] prev close  [19] open
  EXS-FEED  rides the same socket: EXS-FEED*<ts>^KSE100;<price>;<chg>;
            <high>;<chg?>;<low>;<...>^$<ts>^ALLSHR;...^$...
            (decompiled reader: $-groups, ^-split, ; fields).
  ScripServlet  nxg2 /pero/ScripServlet -> JSON [{market, symbol,
            symbolName, sectorName, approved}]; the scrip master:
            universe, company names and sectors in one 286 KB call.
  GetOHLCData  vt host /pero/GetOHLCData -> "SYM;REG;o;h;l;c;HH:MM|..."
            bars, oldest first, intervals 1/5/15/30/60.

Rules honoured here: READ-ONLY (no order endpoints exist in this
module by construction), no credentials, no session, app-shaped
traffic, and every quote is normalized into the exact schema the
bot's datasets already speak (market/status/symbol/price/... with
changePercent as a FRACTION, matching the retired psxterminal feed).
"""

from __future__ import annotations

import json
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

# --- endpoints ------------------------------------------------------------
FEED_HOSTS = ("nxg1.eclear.com.pk", "nxg.eclear.com.pk", "nxg2.eclear.com.pk")
FEED_PORT = 8484
SCRIP_URL = "https://nxg2.eclear.com.pk/pero/ScripServlet"
SCRIP_URL_ALT = "https://nxg1.eclear.com.pk/pero/ScripServlet"
OHLC_URL = "https://vt.eclear.com.pk/pero/GetOHLCData"
SHARIAH_URL = "https://nxg2.eclear.com.pk/pero/GetShariahSymbol?check=1"

USER_AGENT = "okhttp/4.9.3"  # the official app's own identity
HTTP_TIMEOUT = 30.0

PKT = timezone(timedelta(hours=5))

# The broker lists 554 approved REG scrips (2026-09-25) and 485 ticked in
# a 35 s listen during live hours. 350 catches a broken socket or a
# half-delivered burst without rejecting genuine market shrinkage - the
# same rail the retired psxterminal feed used.
MIN_EXPECTED_INSTRUMENTS = 350

# ScripServlet cache TTL: the master list moves only on listing events.
SCRIP_TTL_SECONDS = 6 * 3600.0

STATUS_OPEN = "OPN"
STATUS_SUSPENDED = "SUS"

# nxg2's (and at times nxg1's) load balancer rejects the default Python
# TLS hello with an immediate UNEXPECTED_EOF; the curl-like cipher order
# below handshakes cleanly against both hosts (verified live 2026-09-25
# and re-verified 2026-09-26). Every HTTPS surface in this module -
# ScripServlet, GetShariahSymbol, GetOHLCData - rides this session.
_CIPHERS = ":".join([
    "ECDHE-RSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "AES128-GCM-SHA256",
    "AES256-GCM-SHA384",
    "ECDHE-RSA-AES128-SHA",
    "ECDHE-RSA-AES256-SHA",
    "AES128-SHA",
    "AES256-SHA",
])


class _TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *a, **kw):
        ctx = create_urllib3_context(ciphers=_CIPHERS)
        ctx.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
        kw["ssl_context"] = ctx
        return super().init_poolmanager(*a, **kw)


_HTTP = requests.Session()
_HTTP.mount("https://", _TLSAdapter())
_HTTP.headers["User-Agent"] = USER_AGENT


class BrokerFeedError(RuntimeError):
    """Raised when the broker feed cannot be fetched or parsed."""


# ---------------------------------------------------------------------------
# Scrip master (universe + names + sectors)
# ---------------------------------------------------------------------------

_scrip_cache: dict = {"fetchedAt": 0.0, "scrips": {}}


def _slugify(name: str) -> str:
    """Sector display name -> slug ('EXCHANGE TRADED FUNDS' ->
    'exchange-traded-funds'). Matches the slugs the universe loader's
    ETF/REIT exclusion list expects."""
    out = []
    for ch in name.lower():
        out.append(ch if (ch.isascii() and ch.isalnum()) else "-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def fetch_scrips(force: bool = False, timeout: float = HTTP_TIMEOUT) -> dict:
    """
    {symbol: {name, sector, sector_slug}} for every approved REG scrip.

    Cached in memory for SCRIP_TTL_SECONDS. Raises BrokerFeedError when
    both hosts fail - a stale master must never masquerade as current.
    """
    age = time.time() - _scrip_cache["fetchedAt"]
    if not force and _scrip_cache["scrips"] and age < SCRIP_TTL_SECONDS:
        return _scrip_cache["scrips"]

    last_error: Exception | None = None
    for url in (SCRIP_URL, SCRIP_URL_ALT):
        try:
            resp = _HTTP.get(
                f"{url}?ScripLoadDateTime=&IsReLoad=1", timeout=timeout
            )
            resp.raise_for_status()
            rows = json.loads(resp.text)
            scrips: dict[str, dict] = {}
            for row in rows:
                if row.get("market") != "REG":
                    continue
                if row.get("approved") != "Approved":
                    continue
                symbol = str(row.get("symbol") or "").strip().upper()
                if not symbol or symbol in scrips:
                    continue
                sector = str(row.get("sectorName") or "").strip()
                scrips[symbol] = {
                    "name": str(row.get("symbolName") or "").strip(),
                    "sector": sector,
                    "sector_slug": _slugify(sector) if sector else "",
                }
            # Validated INSIDE the loop but checked through last_error so
            # a degenerate master falls through to the second host
            # instead of short-circuiting the fallback.
            if len(scrips) < 300:
                last_error = BrokerFeedError(
                    f"ScripServlet returned only {len(scrips)} approved "
                    "REG scrips"
                )
                continue
            _scrip_cache["fetchedAt"] = time.time()
            _scrip_cache["scrips"] = scrips
            return scrips
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            continue
    raise BrokerFeedError(f"ScripServlet unreachable: {last_error}")


def fetch_shariah_symbols(timeout: float = HTTP_TIMEOUT) -> set[str]:
    """
    The broker's own shariah universe ('ShariaSymbol=AASM:REG;...'),
    the cross-check that refresh_universe runs against the stored list.
    """
    resp = _HTTP.get(SHARIAH_URL, timeout=timeout)
    resp.raise_for_status()
    symbols: set[str] = set()
    for part in resp.text.split("=", 1)[1].split(";"):
        sym = part.strip().split(":")[0].strip().upper()
        if sym:
            symbols.add(sym)
    return symbols


# ---------------------------------------------------------------------------
# MKT-FEED socket
# ---------------------------------------------------------------------------

def _parse_tick_time(value: str) -> int:
    """'HH:MM:SS' server time (PKT) -> epoch seconds for today's PKT date."""
    try:
        hh, mm, ss = (int(p) for p in value.strip().split(":"))
    except ValueError:
        return 0
    now = datetime.now(PKT)
    stamp = now.replace(hour=hh % 24, minute=mm % 60, second=ss % 60,
                        microsecond=0)
    return int(stamp.timestamp())


def parse_tick_row(row: str) -> dict | None:
    """
    One semicolon-joined MKT-FEED row -> a psxterminal-schema quote.

    changePercent is stored as a FRACTION (change / prev close), the
    scale convention the retired feed used; normalization to a true
    percent stays in the dataset builder. Traded value is volume x VWAP
    (the avg field IS the day's volume-weighted average, so the product
    is the traded value by definition, not an approximation).
    """
    fields = row.strip().split(";")
    if len(fields) < 20 or not fields[0].strip():
        return None
    # Live rows carry a PLAIN symbol in field 0 ("OGDC;REG;...") - the
    # SYM:REG shape is the SUBSCRIBE format, not the tick format. My
    # first parser assumed otherwise and parsed nothing.

    def num(text: str) -> float | None:
        try:
            value = float(text.strip())
        except (TypeError, ValueError):
            return None
        return value if value == value else None  # NaN guard

    symbol = fields[0].strip().upper()
    if not symbol:
        return None

    price = num(fields[10])
    change = num(fields[8])
    prev_close = num(fields[18])
    volume = num(fields[16]) or 0.0
    avg = num(fields[12])

    change_pct = None
    if change is not None and prev_close not in (None, 0.0):
        change_pct = change / prev_close

    value = None
    if volume and avg is not None:
        value = volume * avg

    return {
        "market": fields[1].strip() or "REG",
        "status": fields[6].strip(),
        "symbol": symbol,
        "price": price,
        "change": change,
        "changePercent": change_pct,
        "volume": volume,
        "trades": int(num(fields[15]) or 0),
        "value": value,
        "high": num(fields[13]),
        "low": num(fields[14]),
        "bid": num(fields[3]),
        "ask": num(fields[4]),
        "bidVol": num(fields[2]),
        "askVol": num(fields[5]),
        "timestamp": _parse_tick_time(fields[9]),
    }


def parse_exs_message(text: str) -> dict | None:
    """
    EXS-FEED*<ts>^KSE100;...^$<ts>^ALLSHR;...^$...  -> KSE100 index quote
    in the exact schema the snapshot's 'index' layer has always carried
    (changePercent normalized to a true percent).

    v4.0.1: group order is NOT guaranteed - a closed-market capture put
    ALLSHR first and KSE100 elsewhere, and the first-group read returned
    the wrong index. Scan the $-groups and prefer the KSE100 one; fall
    back to the first group only when it carries no named index.
    """
    try:
        body = text.split("*", 1)[1]
        groups = body.split("$")
        chosen = None
        for group in groups:
            head = group.split("^")
            if len(head) < 2:
                continue
            name = head[1].split(";")[0].strip().upper()
            if name == "KSE100":
                chosen = head
                break
            if chosen is None and name:
                chosen = head
        if chosen is None:
            return None
        fields = chosen[1].split(";")
        price = float(fields[1])
        change = float(fields[2])
        high = float(fields[3])
        low = float(fields[5])
    except (IndexError, ValueError):
        return None
    prev = price - change
    change_pct = (change / prev) * 100.0 if prev else None
    # The message timestamp is the server's local wall clock.
    timestamp = 0
    try:
        stamp = body.split("^")[0].strip()
        ts = datetime.strptime(stamp, "%m/%d/%Y %I:%M:%S %p").replace(
            tzinfo=PKT
        )
        timestamp = int(ts.timestamp())
    except ValueError:
        pass
    return {
        "symbol": fields[0].strip() or "KSE100",
        "status": None,
        "price": price,
        "change": change,
        "changePercent": change_pct,
        "high": high,
        "low": low,
        "timestamp": timestamp,
    }


def subscribe_snapshot(
    symbols: list[str],
    listen_seconds: float = 3.0,
    min_instruments: int = MIN_EXPECTED_INSTRUMENTS,
) -> dict:
    """
    One connect-subscribe-listen pass over the feed socket.

    Returns the same shape fetch_snapshot always returned (requestTime,
    receiveTime, bytes, parser, instruments, index) so every existing
    caller and dataset keeps its contract. Raises BrokerFeedError on a
    degenerate capture - a silently empty snapshot must never reach disk.
    """
    wanted = [f"{s.strip().upper()}:REG" for s in symbols if s.strip()]
    if not wanted:
        raise BrokerFeedError("empty symbol list for subscription")
    subscribe = "MKT-FEED|" + "".join(s + ";" for s in wanted) + "%"

    request_time = datetime.now(timezone.utc)
    instruments: dict[str, dict] = {}
    index: dict | None = None
    received = 0

    last_error: OSError | None = None
    for host in FEED_HOSTS:
        try:
            sock = socket.create_connection((host, FEED_PORT), timeout=10)
            break
        except OSError as exc:
            last_error = exc
            continue
    else:
        raise BrokerFeedError(f"feed socket unreachable: {last_error}")

    try:
        sock.settimeout(2.0)
        try:
            banner = sock.recv(4096)
            if b"Welcome" not in banner:
                raise BrokerFeedError(
                    f"unexpected feed banner: {banner[:60]!r}"
                )
        except socket.timeout:
            pass  # some servers send the banner late; subscribe anyway
        sock.sendall(subscribe.encode())

        buf = b""
        deadline = time.time() + listen_seconds
        last_beat = time.time()
        while time.time() < deadline:
            try:
                chunk = sock.recv(262144)
                if chunk:
                    buf += chunk
                    received += len(chunk)
            except socket.timeout:
                pass
            except OSError:
                break
            if time.time() - last_beat >= 5:
                try:
                    sock.sendall(b"HELLO|%")
                except OSError:
                    break
                last_beat = time.time()
            while b"%" in buf:
                raw, buf = buf.split(b"%", 1)
                text = raw.decode("utf-8", "replace").strip()
                if text.startswith("MKT-FEED"):
                    payload = text.split("*", 1)[1] if "*" in text else ""
                    for row in payload.split("||"):
                        if ";" not in row:
                            continue
                        quote = parse_tick_row(row)
                        if quote is not None:
                            instruments[quote["symbol"]] = quote
                elif text.startswith("EXS-FEED") and index is None:
                    index = parse_exs_message(text)
    finally:
        try:
            sock.close()
        except OSError:
            pass

    receive_time = datetime.now(timezone.utc)

    if not instruments:
        raise BrokerFeedError(
            "MKT-FEED produced no instruments - market closed, subscribe "
            "format changed, or the burst has not started. Refusing an "
            "empty snapshot."
        )
    if len(instruments) < min_instruments:
        raise BrokerFeedError(
            f"only {len(instruments)} instruments ticked, expected at "
            f"least {min_instruments}. Refusing a degraded snapshot."
        )

    return {
        "requestTime": request_time.isoformat(),
        "receiveTime": receive_time.isoformat(),
        "bytes": received,
        "parser": "eclear-mkt-feed",
        "instruments": instruments,
        "index": index,
    }


# ---------------------------------------------------------------------------
# OHLC bars (multi-timeframe features)
# ---------------------------------------------------------------------------

def fetch_ohlc(
    symbol: str,
    interval: int = 5,
    timeout: float = HTTP_TIMEOUT,
) -> list[dict]:
    """
    Today's bars for one symbol: [{open, high, low, close, time}...],
    oldest first. interval in {1, 5, 15, 30, 60} minutes.
    """
    if interval not in (1, 5, 15, 30, 60):
        raise ValueError(f"unsupported OHLC interval: {interval}")
    resp = _HTTP.get(
        OHLC_URL,
        params={
            "scrip": symbol.upper(),
            "market": "REG",
            "check": "symbol",
            "interval": interval,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    bars: list[dict] = []
    for part in resp.text.split("|"):
        fields = part.strip().split(";")
        if len(fields) != 7 or fields[0].upper() != symbol.upper():
            continue
        try:
            bars.append({
                "open": float(fields[2]),
                "high": float(fields[3]),
                "low": float(fields[4]),
                "close": float(fields[5]),
                "time": fields[6].strip(),
            })
        except ValueError:
            continue
    return bars
