"""Redundancy layer: 1-minute OHLC bar capture via GetOHLCData (read-only).

The MKT-FEED socket (feed_capture.py) is the primary order-flow bank. This
poller adds a slower but robust second bank of genuine intraday bars from the
broker's public read tier (no session, no credentials, GET only):

    https://vt.eclear.com.pk/pero/GetOHLCData?scrip=SYM&market=REG
        &check=symbol&interval=1

Each response carries the FULL day's 1-minute bars for the symbol (rows
`SYM;REG;open;high;low;close;HH:MM` joined by '|'), so even a slow rotation
never loses bars: every pass re-fetches the whole day and only new bar times
are banked.

These hosts reject the default Python TLS hello; they accept a legacy
SECLEVEL=1 context (verified live 2026-10-06). Requests are paced 1.2s+.

Banked data (gitignored under /data/):
    data/feed_capture/ohlc_YYYYMMDD.ndjson   {ts, symbol, bars:[...]}
    data/feed_capture/ohlc_status.json       liveness heartbeat

Usage (from repo root):
    python -m src.data.ohlc_poller                  # run until Ctrl+C
    python -m src.data.ohlc_poller --once           # one full pass, exit
    python -m src.data.ohlc_poller --limit 5        # first N symbols only
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KARACHI = timezone(timedelta(hours=5))  # SO-8

from src.data.feed_capture import load_universe, UNIVERSE_FILE  # noqa: E402
from src.data.capture_health import status_view  # noqa: E402
from src.data.registry import availability, Availability  # noqa: E402

OHLC_HOSTS = ["vt.eclear.com.pk", "nxg1.eclear.com.pk", "nxg2.eclear.com.pk"]
OHLC_PATH = "/pero/GetOHLCData"
PACING_SECONDS = 1.3
CAPTURE_DIR = ROOT / "data" / "feed_capture"
STATUS_PATH = CAPTURE_DIR / "ohlc_status.json"


def make_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_ciphers("ALL:@SECLEVEL=1")
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_bars(opener: urllib.request.OpenerDirector, symbol: str,
               interval: int = 1) -> list[dict] | None:
    """Return [{t,o,h,l,c}] for today, or None on failure."""
    for host in OHLC_HOSTS:
        url = (f"https://{host}{OHLC_PATH}?scrip={symbol}"
               f"&market=REG&check=symbol&interval={interval}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9.0"})
            with opener.open(req, timeout=15) as resp:
                text = resp.read().decode("utf-8", "replace")
            break
        except OSError:
            continue
    else:
        return None
    bars = []
    for row in text.split("|"):
        parts = row.strip().split(";")
        # row: SYM;REG;open;high;low;close;HH:MM
        if len(parts) != 7 or parts[0] != symbol:
            continue
        try:
            bars.append({"t": parts[6], "o": float(parts[2]),
                         "h": float(parts[3]), "l": float(parts[4]),
                         "c": float(parts[5])})
        except ValueError:
            continue
    return bars or None


class OhlcPoller:
    def __init__(self, symbols: list[str], once: bool = False, limit: int | None = None):
        self.symbols = symbols[:limit] if limit else symbols
        self.once = once
        self.opener = make_opener()
        self.seen: dict[str, set[str]] = {}
        self.counters = {"passes": 0, "symbols_ok": 0, "symbols_err": 0,
                         "bars": 0, "errors": 0}
        self.last_error: str | None = None
        self.last_symbol_at: str | None = None
        self.running = False
        self.started_at = now().isoformat()
        self._fh = None
        self._fh_day = None

    def _open_file(self) -> None:
        day = now().strftime("%Y%m%d")
        if self._fh is not None and day == self._fh_day:
            return
        if self._fh is not None:
            self._fh.close()
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        self._fh = open(CAPTURE_DIR / f"ohlc_{day}.ndjson", "a", encoding="utf-8")
        self._fh_day = day

    def bank(self, symbol: str, bars: list[dict]) -> None:
        seen = self.seen.setdefault(symbol, set())
        fresh = [b for b in bars if b["t"] not in seen]
        if not fresh:
            return
        record = {"ts": now().isoformat(timespec="milliseconds"),
                  "symbol": symbol, "bars": fresh}
        self._open_file()
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._fh.flush()
        seen.update(b["t"] for b in fresh)
        self.counters["bars"] += len(fresh)

    def write_status(self) -> None:
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        status = {
            "pid": os.getpid() if self.running else None,
            "running": self.running,
            "started_at": self.started_at,
            "updated_at": now().isoformat(),
            "universe_size": len(self.symbols),
            "counters": self.counters,
            "last_symbol_at": self.last_symbol_at,
            "last_error": self.last_error,
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

    def run_pass(self) -> None:
        self.counters["passes"] += 1
        last_status = time.monotonic()
        for symbol in self.symbols:
            bars = fetch_bars(self.opener, symbol)
            if bars is None:
                self.counters["symbols_err"] += 1
                self.last_error = f"fetch failed: {symbol}"
            else:
                self.counters["symbols_ok"] += 1
                self.bank(symbol, bars)
                self.last_symbol_at = f"{symbol} {len(bars)}b"
            time.sleep(PACING_SECONDS)
            if time.monotonic() - last_status >= 20:
                self.write_status()
                last_status = time.monotonic()
        self.write_status()

    def run(self) -> None:
        self.running = True
        self.write_status()
        while True:
            try:
                self.run_pass()
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # keep polling no matter what
                self.counters["errors"] += 1
                self.last_error = f"{type(exc).__name__}: {exc}"
                self.write_status()
                time.sleep(10)
            if self.once:
                break


def now() -> datetime:
    return datetime.now(KARACHI)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only 1m OHLC capture")
    parser.add_argument("--once", action="store_true", help="one pass then exit")
    parser.add_argument("--limit", type=int, default=None,
                        help="only the first N symbols (testing)")
    parser.add_argument("--symbols-file", type=Path, default=UNIVERSE_FILE)
    parser.add_argument("--status", action="store_true",
                        help="print the saved heartbeat and its liveness")
    args = parser.parse_args(argv)

    if args.status:
        if not STATUS_PATH.is_file():
            print("no ohlc_status.json yet: the poller has not run")
            return 1
        saved = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        print(json.dumps(status_view(saved), indent=1))
        return 0

    symbols = load_universe(args.symbols_file)
    # SO-3: this poller IS the forward-capture path that moves intraday_ohlcv
    # from UNAVAILABLE toward AVAILABLE; until weeks are banked it stays
    # DEGRADED and every consumer must keep labeling it so.
    intraday = availability("intraday_ohlcv")
    print(f"registry: intraday_ohlcv = {intraday.value} "
          f"(this poller banks genuine bars forward; no historical claims)")
    if intraday is Availability.UNAVAILABLE:
        print("no banked intraday archive yet: captured bars are forward-only")
    poller = OhlcPoller(symbols, once=args.once, limit=args.limit)
    print(f"{now():%Y-%m-%d %H:%M:%S} OHLC capture starting: "
          f"{len(poller.symbols)} symbols, pacing {PACING_SECONDS}s")
    try:
        poller.run()
    except KeyboardInterrupt:
        print(f"{now():%H:%M:%S} stopped by owner (Ctrl+C)")
    finally:
        poller.close()
    print(f"banked {poller.counters['bars']} bars over "
          f"{poller.counters['passes']} pass(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

