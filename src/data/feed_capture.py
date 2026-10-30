"""Read-only broker feed capture daemon (ECLEAR mobile feed socket).

Banks genuine PSX intraday tick data from the broker's own feed socket, as
mapped by legacy/sentinel/eclear_recon/RECON_REPORT.md (verified live). This
is the Path A recorder described in DATA_SOURCING.md section 4.

THE OWNER'S READ-ONLY LAW (RECON_REPORT.md, binding):
    No order, cancel, modify, withdrawal, or account-mutation message may
    ever be sent. This daemon speaks exactly three outgoing frame types,
    enforced by guard(): the MKT-FEED subscription, the EXS-FEED index
    subscription and the HELLO heartbeat. No login, no credentials, no
    session, nothing else. The class of a mistake this code could make is
    "connect and read", nothing more.

Wire protocol (RECON_REPORT.md, verified live 2026-09-25):
    server -> Welcome*%
    client -> MKT-FEED|SYM1:REG;SYM2:REG;...;%   (subscribe, no auth needed)

    The per-symbol MARKET SUFFIX in that frame is not cosmetic, and its
    absence is why this capture banked no ticks for weeks. Measured live on
    the KST feed, 2026-10-12, same socket, same second, eight symbols:

        MKT-FEED|TREET;PRL;CNERGY;...;%          -> 0 MKT-FEED frames in 18s
        MKT-FEED|TREET:REG;PRL:REG;...;%         -> 17 MKT-FEED frames in 18s

    Bare symbols still get the index, movers and market-stats frames, so the
    capture looked alive while the tape it exists to record stayed empty.
    REG is the regular equity market, the one the strategy trades (the same
    panel scope src/data/market_snapshot.py uses on the company pages).

    client -> HELLO|%                        (keepalive every 5s, both ways)
    Messages are separated by '%', the type is separated from the payload
    by '*', MKT-FEED rows are separated by '||' and fields by ';'.

    Tick field map, VERIFIED against the live wire on 2026-10-12 and
    corrected here. The older map read field [2] as the last price, field
    [3] as the bid and field [6] as the ask, which is wrong on the wire this
    machine receives: [6] carries the market status flag and [2] carries a
    quantity, so the quote rule in src/data/tick_volume.py could never fire
    (it read "OPN" as an ask price) and every row was left unclassified.
    Nothing here guesses: each index below was checked against the exchange's
    own numbers on 5064 live rows before it was named.

        [0]  scrip            e.g. TREET
        [1]  market           REG, the regular equity market
        [2]  bid size         shares resting at the bid
        [3]  bid              best bid price
        [4]  ask              best ask price
        [5]  ask size         shares resting at the ask
        [6]  status           OPN (open) or SUS (suspended)
        [7]  change sign      see below, NOT a trade side
        [8]  change           points, and [10] - [18] equals it
        [9]  tick time        time of the last print in [10]
        [10] last             last traded price
        [11] flag             a space on every live row seen so far
        [12] avg              average traded price
        [13] high             day high
        [14] low              day low
        [15] total trades     cumulative count
        [16] total volume     cumulative shares, the venue's own running total
        [17] last-trade vol   size of the print in [10]
        [18] close            previous day's close
        [19] open             today's open

    Evidence for [3]/[4]/[10]: on 5064 live rows the last price sat exactly
    at [4] on 2184 rows and exactly at [3] on 1122, and [10] - [18] equalled
    field [8] within a paisa on 4882 of 4994 rows where all three arrived.
    Both are statements about the venue's own numbers, not about a guess.

    Field [7] is the sign of the day's change (field [8]), NOT the side of a
    trade: '+' is a stock up on the day, '-' is down and '=' is flat. Across
    all 902 MKT-FEED rows banked on 2026-10-12 it matched sign(field[8]) with
    zero exceptions, so it carries no information about who bought. Nothing
    in this 20-field layout does; src/data/tick_volume.py records that
    finding and derives the split from where the prints in [10] actually
    traded, at [3] or at [4].

WHAT THIS STREAM ACTUALLY IS (measured 2026-10-12): a per-symbol snapshot
cycle, several symbols per frame, not a trade by trade tape. A row carries
the symbol's running session total (field [16]) plus the size of the last
print seen (field [17]), so the sizes of consecutive last prints do not add
up to the volume the total moved; the increments of [16] are what the venue
says was traded between two snapshots, and src/data/tick_volume.py splits
those increments, never the print sizes. It is banked because it is genuine
exchange data and the most specific thing available, and because a
per-symbol snapshot still answers "what is this stock doing right now";
which side those shares were on is read from where each print traded, and
where that is not observable the split says so instead of guessing.

Banked data (gitignored under /data/):
    data/feed_capture/capture_YYYYMMDD.ndjson  one JSON object per message
    data/feed_capture/status.json              liveness heartbeat for watchers

All timestamps are Karachi time (SO-8), zoneinfo Asia/Karachi.

Usage (from repo root):
    python -m src.data.feed_capture                 # run until Ctrl+C
    python -m src.data.feed_capture --duration 60   # bounded test run
    python -m src.data.feed_capture --status        # print status.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import socket
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.data.capture_health import status_view

from src import config  # noqa: E402
from src.data import eligibility  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KARACHI = timezone(timedelta(hours=5))  # SO-8: Karachi, UTC+5, forever

FEED_HOSTS = ["nxg1.eclear.com.pk", "nxg2.eclear.com.pk", "nxg.eclear.com.pk"]
FEED_PORT = 8484

# The read-only law, enforced. Every frame this program sends must start
# with one of these prefixes. There is deliberately no auth frame and no
# way to express one.
ALLOWED_OUTGOING_PREFIXES = ("MKT-FEED|", "EXS-FEED|", "HELLO|")
HEARTBEAT = "HELLO|%"
HEARTBEAT_SECONDS = 5.0

#: The KMIALL universe for the subscription, tracked in the repository. The
#: legacy sentinel copy (data/legacy_sentinel/data/kmiall_tickers.json) is
#: gitignored, so a fresh checkout has no universe file and the recorder died
#: at start with FileNotFoundError while the caller kept reporting success:
#: measured 2026-10-14 on a GitHub Actions runner, five consecutive 30 second
#: cycles faulted without a single bar. Both files carry the same 319 KMIALLSHR
#: members (verified equal symbol for symbol), so this is the same subscription
#: on every machine, and it is the exact list src/scripts/intraday_pipeline
#: loads, so the tape banks bars for what the scanner scans (SO-3).
UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
CAPTURE_DIR = ROOT / "data" / "feed_capture"
STATUS_PATH = CAPTURE_DIR / "status.json"

# Named tick fields (index -> name) per the field map above.
#: The market a subscription must name to receive per-trade ticks. A tick
#: row echoes it in field [1] ("REG") and keeps its scrip bare in field [0],
#: so the tape and the ranking table still speak the same symbol names.
MARKET_CODE = "REG"

TICK_FIELDS = {
    0: "scrip", 1: "market", 2: "bid_size", 3: "bid", 4: "ask",
    5: "ask_size", 6: "status", 7: "change_sign", 8: "change",
    9: "tick_time", 10: "last", 11: "flag", 12: "avg", 13: "high",
    14: "low", 15: "trades", 16: "volume", 17: "last_volume",
    18: "close", 19: "open",
}


def now_karachi() -> datetime:
    return datetime.now(KARACHI)


def guard(frame: str) -> str:
    """Raise unless the frame is one of the three allowed read-only types."""
    for prefix in ALLOWED_OUTGOING_PREFIXES:
        if frame.startswith(prefix) and frame.endswith("%"):
            return frame
    raise RuntimeError(
        f"READ-ONLY GUARD: refusing to send frame {frame[:60]!r}; "
        f"allowed prefixes are {ALLOWED_OUTGOING_PREFIXES}"
    )


def load_universe(path: Path = UNIVERSE_FILE) -> list[str]:
    """KMIALL symbols for the subscription. Refuses to guess (SO-3).

    ETFs are never subscribed (owner order 2026-10-15): the scan universe
    excludes them by name, and the capture must match what the scanner
    ranks or the exclusions would differ between collection and use. Since
    2026-10-16 that exclusion is asked of src/data/eligibility.py, the same
    service the scan and the historical dataset use, so the recorder cannot
    subscribe to a symbol the scanner would refuse (or the reverse).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"KMIALL universe file not found: {path}; refusing to subscribe "
            f"to an invented list"
        )
    records = json.loads(path.read_text(encoding="utf-8"))
    symbols = [
        r["symbol"] for r in records
        if r.get("symbol") and "KMIALLSHR" in (r.get("listedIn") or [])
    ]
    screened = eligibility.screen(symbols, universe=symbols)
    if not screened.eligible:
        raise ValueError(f"No eligible KMIALLSHR members in {path}")
    return sorted(set(screened.eligible))


def market_symbol(symbol: str, market: str = MARKET_CODE) -> str:
    """One symbol as the feed wants it: SYMBOL:MARKET (see the module header).

    A symbol that already names a market is left alone, so a subscription
    built from an already-qualified list cannot become SYM:REG:REG.
    """
    text = str(symbol).strip().upper()
    if not market or ":" in text:
        return text
    return f"{text}:{market.strip().upper()}"


def build_subscribe_frame(symbols: list[str],
                         market: str = MARKET_CODE) -> str:
    """The one subscription frame: MKT-FEED|SYM1:REG;SYM2:REG;...;%

    The market qualifier is required for per-trade ticks; without it the feed
    answers with index, movers and stats frames only (see the module header
    for the live measurement).
    """
    qualified = [market_symbol(symbol, market) for symbol in symbols]
    return guard("MKT-FEED|" + ";".join(qualified) + ";%")


def parse_message(text: str) -> dict | None:
    """Best-effort parse of one wire message into a bankable record.

    Rows inside an MKT-FEED frame are separated by '||'. The capture used to
    split them on '$', which never appears on this wire, so every frame was
    read as one row: the first symbol's fields were mapped correctly and the
    other nine symbols in the same frame were left in the unnamed numeric
    slots, banked but unusable. Measured on the 2026-10-12 capture: 902 rows
    arrived, 64 were parsed. Both separators are accepted now, so the old
    fixtures and the live wire both read as whole frames.
    """
    if "*" not in text:
        return None
    kind, payload = text.split("*", 1)
    record = {"kind": kind, "raw": text}
    is_tick_frame = kind.startswith("MKT-FEED")
    rows = _split_rows(payload) if is_tick_frame else [payload]
    ticks = []
    for row in rows:
        if not row or ";" not in row:
            continue
        fields = row.split(";")
        # Positional fields are always kept. The NAMED fields are only
        # applied to MKT-FEED rows: the same file also carries EXS-FEED,
        # MKT-Movers and MKT-STATS frames whose semicolon lists are a
        # different layout, and naming them with the tick map labelled a
        # market-stats row as a trade with a 45,745,000 share buy (found
        # while building the buy/sell split, 2026-10-10).
        tick = {str(i): v for i, v in enumerate(fields)}
        if is_tick_frame:
            for idx, name in TICK_FIELDS.items():
                if idx < len(fields):
                    tick[name] = fields[idx]
        ticks.append(tick)
    if ticks:
        record["ticks"] = ticks
    return record


#: Row separators inside a tick frame. '||' is what the live wire uses
#: (measured 2026-10-12); '$' is the separator the original recon report
#: named, kept so an existing capture or fixture still parses.
ROW_SEPARATORS = ("||", "$")


def _split_rows(payload: str) -> list[str]:
    """Split one tick frame's payload into its per-symbol rows."""
    for separator in ROW_SEPARATORS:
        if separator in payload:
            return payload.split(separator)
    return [payload]


def _finite_number(value) -> float | None:
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def relay_quote_updates(record: dict) -> dict:
    """Extract only observations present in one captured broker frame."""
    from src.data import broker_market

    raw = str(record.get("raw", ""))
    observed_at = str(record.get("ts", ""))
    kind = str(record.get("kind", ""))
    update: dict = {"quotes": [], "index": None, "market_feed": None}
    if kind.startswith("MKT-FEED"):
        ticks = record.get("ticks") or parse_message(raw) or {}
        if isinstance(ticks, dict):
            ticks = ticks.get("ticks") or []
        for tick in ticks:
            if not isinstance(tick, dict) or str(tick.get("market", "")).strip().upper() != "REG":
                continue
            symbol = str(tick.get("scrip", "")).strip().upper().split(":", 1)[0]
            if not symbol or not symbol.isalnum():
                continue
            price = _finite_number(tick.get("last"))
            if price is None or price <= 0:
                continue
            close = _finite_number(tick.get("close"))
            change = _finite_number(tick.get("change"))
            change_pct = (change / close * 100.0
                          if change is not None and close is not None and close > 0
                          else None)
            volume = _finite_number(tick.get("volume"))
            quote = {
                "symbol": symbol,
                "price": price,
                "bid": _finite_number(tick.get("bid")),
                "ask": _finite_number(tick.get("ask")),
                "change": change,
                "change_pct": change_pct,
                "volume": int(volume) if volume is not None and volume >= 0 else None,
                "high": _finite_number(tick.get("high")),
                "low": _finite_number(tick.get("low")),
                "status": ("OPEN" if str(tick.get("status", "")).strip().upper()
                           in {"OPN", "OPEN", "TRADING", "LIVE"} else
                           "SUSPENDED" if str(tick.get("status", "")).strip().upper()
                           in {"SUS", "SUSPENDED", "HALT", "HALTED"} else "UNKNOWN"),
                "source_tick_time": str(tick.get("tick_time", "")).strip(),
                "observed_at": observed_at,
                "source": "eClear MKT-FEED REG",
            }
            update["quotes"].append(quote)
    elif kind.startswith("EXS-FEED"):
        update["index"] = broker_market.parse_index_frame(raw)
    elif kind.startswith("MKT-STATS"):
        status = broker_market.parse_market_status_frame(raw)
        if status is not None:
            update["market_feed"] = {
                "status": status[0],
                "raw_status": status[1],
                "as_of": observed_at,
                "source": "eClear REG market feed",
            }
    update["captured_at"] = observed_at
    return update


class RelayQuotePublisher:
    """Coalesce broker frames and push snapshots from cloud runners only."""

    MIN_PUBLISH_SECONDS = 1.0
    # Owner order 2026-10-30: the phone's numbers must move at the broker's
    # own one-second cadence, so one failed push may never retire the feed
    # for half a minute. The old 30s cap let a single 4xx from the edge mute
    # a live session for up to 30 seconds of backoff on top of the 4-6
    # second round trips behind it, which is the "the numbers are stuck"
    # the card showed (each retry also re-posted every pending row, so a
    # stalled session got whole minutes behind). The retry still doubles
    # from its 1s floor; it just stops at 5, so the worst gap between two
    # successful pushes stays inside the card's own freshness window.
    MAX_RETRY_SECONDS = 5.0

    def __init__(self) -> None:
        self._token = ""
        self._url = ""
        self._pending_quotes: dict[str, dict] = {}
        self._pending_index: dict | None = None
        self._pending_market_feed: dict | None = None
        self._latest_captured_at: str | None = None
        self._sent_captured_at: str | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = False
        self._last_attempt = 0.0
        self._retry_seconds = 1.0
        self._thread: threading.Thread | None = None

        # The owner's PC is never a publisher. Only a cloud session runner
        # with its existing secret can start the bounded upload thread.
        if os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
            return
        self._token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
        if not self._token:
            return
        self._url = os.environ.get(
            "RELAY_URL", "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"
        ).strip().rstrip("/")
        self._thread = threading.Thread(
            target=self._run, name="cloud-relay-quote-publisher", daemon=True)
        self._thread.start()

    def observe(self, record: dict) -> None:
        if self._thread is None:
            return
        update = relay_quote_updates(record)
        with self._lock:
            if (self._latest_captured_at is None or
                    update["captured_at"] > self._latest_captured_at):
                self._latest_captured_at = update["captured_at"]
            for quote in update["quotes"]:
                self._pending_quotes[quote["symbol"]] = quote
            if update.get("index") is not None:
                self._pending_index = update["index"]
            if update.get("market_feed") is not None:
                self._pending_market_feed = update["market_feed"]
        if update["quotes"] or update.get("index") or update.get("market_feed"):
            self._wake.set()

    def _take_pending(self) -> dict | None:
        with self._lock:
            if not (self._pending_quotes or self._pending_index
                    or self._pending_market_feed or
                    self._latest_captured_at != self._sent_captured_at):
                return None
            captured_at = self._latest_captured_at
            return {
                "quotes": list(self._pending_quotes.values()),
                "index": self._pending_index,
                "market_feed": self._pending_market_feed,
                "captured_at": captured_at,
            }

    def _acknowledge(self, sent: dict) -> bool:
        with self._lock:
            for row in sent["quotes"]:
                symbol = row["symbol"]
                current = self._pending_quotes.get(symbol)
                if current and current["observed_at"] == row["observed_at"]:
                    self._pending_quotes.pop(symbol, None)
            if (sent["index"] is not None and self._pending_index == sent["index"]):
                self._pending_index = None
            if (sent["market_feed"] is not None
                    and self._pending_market_feed == sent["market_feed"]):
                self._pending_market_feed = None
            if self._latest_captured_at == sent["captured_at"]:
                self._sent_captured_at = sent["captured_at"]
            return bool(self._pending_quotes or self._pending_index
                        or self._pending_market_feed or
                        self._latest_captured_at != self._sent_captured_at)

    def _run(self) -> None:
        import requests

        while True:
            self._wake.wait()
            self._wake.clear()
            if self._stopping and self._take_pending() is None:
                return
            delay = self.MIN_PUBLISH_SECONDS - (time.monotonic() - self._last_attempt)
            if delay > 0 and not self._stopping:
                if self._wake.wait(delay):
                    self._wake.clear()
            update = self._take_pending()
            if update is None:
                if self._stopping:
                    return
                continue
            self._last_attempt = time.monotonic()
            try:
                response = requests.post(
                    self._url + "/quotes", json=update,
                    headers={"x-admin-token": self._token}, timeout=(1.0, 2.0))
                response.raise_for_status()
                body = response.json()
                if not body.get("ok"):
                    raise ValueError("relay refused quote update")
                pending = self._acknowledge(update)
                self._retry_seconds = 1.0
                if pending:
                    self._wake.set()
            except (requests.RequestException, ValueError) as exc:
                # Keep the latest failed values for a bounded retry. A newer
                # observation already queued for a symbol always wins.
                with self._lock:
                    for row in update["quotes"]:
                        current = self._pending_quotes.get(row["symbol"])
                        if (current is None or
                                current["observed_at"] < row["observed_at"]):
                            self._pending_quotes[row["symbol"]] = row
                    if self._pending_index is None:
                        self._pending_index = update["index"]
                    if self._pending_market_feed is None:
                        self._pending_market_feed = update["market_feed"]
                    if (self._latest_captured_at is None or
                            update["captured_at"] > self._latest_captured_at):
                        self._latest_captured_at = update["captured_at"]
                # Never log the request headers or response body, which may
                # contain sensitive configuration supplied by the runner.
                print(f"relay quote push failed: {type(exc).__name__}")
                if self._stopping:
                    return
                self._retry_seconds = min(self.MAX_RETRY_SECONDS,
                                          self._retry_seconds * 2.0)
                if self._wake.wait(self._retry_seconds):
                    self._wake.clear()
                self._wake.set()
            if self._stopping:
                return

    def close(self) -> None:
        if self._thread is None:
            return
        self._stopping = True
        self._wake.set()
        self._thread.join(timeout=3.5)
        self._thread = None


class CaptureSession:
    """One capture run: connect, subscribe, bank, reconnect as needed."""

    def __init__(self, symbols: list[str], duration: float | None = None,
                 market: str = MARKET_CODE):
        self.symbols = symbols
        self.market = market
        self.subscribe_frame = build_subscribe_frame(symbols, market)
        self.duration = duration
        self.deadline = None if duration is None else time.time() + duration
        self.counters = {"messages": 0, "ticks": 0, "reconnects": 0, "errors": 0}
        self.last_frame_at: str | None = None
        self.last_error: str | None = None
        self.running = False
        self.started_at = now_karachi().isoformat()
        self._fh = None
        self._fh_day = None
        self._relay_quotes = RelayQuotePublisher()

    def _open_file(self) -> None:
        day = now_karachi().strftime("%Y%m%d")
        if self._fh is not None and day == self._fh_day:
            return
        if self._fh is not None:
            self._fh.close()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        path = CAPTURE_DIR / f"capture_{day}.ndjson"
        self._fh = open(path, "a", encoding="utf-8")
        self._fh_day = day

    def bank(self, text: str) -> None:
        # A malformed frame must never kill the capture (SO-3: the raw line
        # is still banked, honestly labeled unparsed).
        try:
            record = parse_message(text) or {"kind": "?", "raw": text}
        except Exception as exc:  # noqa: BLE001 - capture must survive
            record = {"kind": "unparsed", "raw": text,
                      "parse_error": f"{type(exc).__name__}: {exc}"}
        record["ts"] = now_karachi().isoformat(timespec="milliseconds")
        if "ticks" in record:
            self.counters["ticks"] += len(record["ticks"])
        self.counters["messages"] += 1
        self.last_frame_at = record["ts"]
        self._open_file()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._relay_quotes.observe(record)

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()

    def write_status(self) -> None:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        status = {
            "pid": os.getpid() if self.running else None,
            "running": self.running,
            "started_at": self.started_at,
            "updated_at": now_karachi().isoformat(),
            "feed_hosts": FEED_HOSTS,
            "feed_port": FEED_PORT,
            "universe_size": len(self.symbols),
            "counters": self.counters,
            "last_frame_at": self.last_frame_at,
            "last_error": self.last_error,
            "duration_seconds": self.duration,
        }
        tmp = STATUS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(status, indent=1), encoding="utf-8")
        tmp.replace(STATUS_PATH)

    def close(self) -> None:
        self.running = False
        self._relay_quotes.close()
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        self.write_status()

    def _connect(self) -> socket.socket:
        last_exc: Exception | None = None
        for host in FEED_HOSTS:
            try:
                sock = socket.create_connection((host, FEED_PORT), timeout=10)
                print(f"{now_karachi():%H:%M:%S} connected to {host}:{FEED_PORT}")
                return sock
            except OSError as exc:
                last_exc = exc
                print(f"{now_karachi():%H:%M:%S} {host} unreachable: {exc}")
        raise ConnectionError(f"all feed hosts unreachable: {last_exc}")

    def run(self) -> None:
        self.running = True
        self.write_status()
        backoff = 2.0
        while self.deadline is None or time.time() < self.deadline:
            buf = b""
            sock = None
            try:
                sock = self._connect()
                sock.settimeout(2.0)
                banner = sock.recv(4096)
                print(f"{now_karachi():%H:%M:%S} banner: {banner[:60]!r}")
                sock.sendall(self.subscribe_frame.encode())
                backoff = 2.0
                last_beat = time.time()
                last_status = 0.0
                last_tick = time.time()
                while self.deadline is None or time.time() < self.deadline:
                    try:
                        chunk = sock.recv(65536)
                        if not chunk:
                            raise ConnectionError("feed closed the socket")
                        buf += chunk
                    except socket.timeout:
                        pass
                    if time.time() - last_beat >= HEARTBEAT_SECONDS:
                        sock.sendall(guard(HEARTBEAT).encode())
                        last_beat = time.time()
                    while b"%" in buf:
                        raw, buf = buf.split(b"%", 1)
                        text = raw.decode("utf-8", "replace").strip()
                        if text:
                            self.bank(text)
                            if text.startswith("MKT-FEED"):
                                last_tick = time.time()
                    # A push that stops is not a closed socket, so the
                    # heartbeat keeps the session looking alive while the tape
                    # ages out and every later scan blocks on stale leaders.
                    # Reconnecting is the one lever that works (measured
                    # 2026-10-16: a fresh connection is answered with a full
                    # sweep every time, re-subscribing is not). This is
                    # checked OUTSIDE the frame loop on purpose: a venue that
                    # sends nothing at all would never enter that loop.
                    # Raised as a connection fault so the existing backoff owns
                    # the retry rate and a venue that is truly down is not
                    # hammered.
                    if time.time() - last_tick > config.TICK_STALL_SECONDS:
                        raise ConnectionError(
                            f"the venue pushed no market data for "
                            f"{time.time() - last_tick:.0f}s "
                            f"(limit {config.TICK_STALL_SECONDS:.0f}s); "
                            f"reconnecting for a fresh sweep")
                    if self.counters["messages"] % 50 == 0:
                        self.flush()
                    if time.time() - last_status >= 20:
                        self.write_status()
                        self.flush()
                        last_status = time.time()
            except (OSError, ConnectionError) as exc:
                self.counters["errors"] += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"{now_karachi():%H:%M:%S} feed error: {self.last_error}")
            except Exception as exc:  # noqa: BLE001 - reconnect and survive
                self.counters["errors"] += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                print(f"{now_karachi():%H:%M:%S} unexpected error: {self.last_error}")
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
            if self.deadline is not None and time.time() >= self.deadline:
                break
            self.counters["reconnects"] += 1
            self.write_status()
            print(f"{now_karachi():%H:%M:%S} reconnecting in {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only PSX feed capture")
    parser.add_argument("--duration", type=float, default=None,
                        help="stop after N seconds (default: run until Ctrl+C)")
    parser.add_argument("--status", action="store_true",
                        help="print status.json and exit")
    parser.add_argument("--symbols-file", type=Path, default=UNIVERSE_FILE,
                        help="KMIALL universe json "
                             "(default: the tracked src/data/universe_kmiall.json)")
    args = parser.parse_args(argv)

    if args.status:
        if STATUS_PATH.exists():
            saved = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
            print(json.dumps(status_view(saved), indent=1))
            return 0
        print("no status.json yet: the capture daemon has not run")
        return 1

    symbols = load_universe(args.symbols_file)
    session = CaptureSession(symbols, duration=args.duration)
    print(f"{now_karachi():%Y-%m-%d %H:%M:%S} KST feed capture starting: "
          f"{len(symbols)} KMIALL symbols")
    try:
        session.run()
    except KeyboardInterrupt:
        print(f"{now_karachi():%H:%M:%S} stopped by owner (Ctrl+C)")
    finally:
        session.close()
    print(f"banked {session.counters['messages']} messages, "
          f"{session.counters['ticks']} ticks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

