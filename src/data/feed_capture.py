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
    client -> MKT-FEED|SYM1;SYM2;...;%       (subscribe, no auth needed)
    client -> HELLO|%                        (keepalive every 5s, both ways)
    Messages are separated by '%', the type is separated from the payload
    by '*', MKT-FEED rows are separated by '$' and fields by ';'.
    Tick field map (from the mobile app's FeedClient.java):
        [0] scrip [1] market [2] last [3] bid [6] ask [7] direction
        [8] change [9] last-trade time [11] flag [12] avg [13] high
        [14] low [15] total trades [16] total volume [17] last-trade vol
        [18] close [19] open

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
import os
import socket
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.data.capture_health import status_view

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

UNIVERSE_FILE = ROOT / "data" / "legacy_sentinel" / "data" / "kmiall_tickers.json"
CAPTURE_DIR = ROOT / "data" / "feed_capture"
STATUS_PATH = CAPTURE_DIR / "status.json"

# Named tick fields (index -> name) per the field map above.
TICK_FIELDS = {
    0: "scrip", 1: "market", 2: "last", 3: "bid", 6: "ask", 7: "direction",
    8: "change", 9: "tick_time", 11: "flag", 12: "avg", 13: "high",
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
    """KMIALL symbols for the subscription. Refuses to guess (SO-3)."""
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
    if not symbols:
        raise ValueError(f"No KMIALLSHR members in {path}")
    return sorted(set(symbols))


def build_subscribe_frame(symbols: list[str]) -> str:
    """The one subscription frame: MKT-FEED|SYM1;SYM2;...;%"""
    return guard("MKT-FEED|" + ";".join(symbols) + ";%")


def parse_message(text: str) -> dict | None:
    """Best-effort parse of one wire message into a bankable record."""
    if "*" not in text:
        return None
    kind, payload = text.split("*", 1)
    record = {"kind": kind, "raw": text}
    is_tick_frame = kind.startswith("MKT-FEED")
    rows = payload.split("$") if is_tick_frame else [payload]
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


class CaptureSession:
    """One capture run: connect, subscribe, bank, reconnect as needed."""

    def __init__(self, symbols: list[str], duration: float | None = None):
        self.symbols = symbols
        self.subscribe_frame = build_subscribe_frame(symbols)
        self.duration = duration
        self.deadline = None if duration is None else time.time() + duration
        self.counters = {"messages": 0, "ticks": 0, "reconnects": 0, "errors": 0}
        self.last_frame_at: str | None = None
        self.last_error: str | None = None
        self.running = False
        self.started_at = now_karachi().isoformat()
        self._fh = None
        self._fh_day = None

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
                        help="KMIALL universe json (default: stored file)")
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

