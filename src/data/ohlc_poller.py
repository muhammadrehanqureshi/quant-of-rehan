"""Redundancy layer: 1-minute OHLC bar capture via GetOHLCData (read-only).

The MKT-FEED socket (feed_capture.py) is the primary order-flow bank. This
poller adds a slower but robust second bank of genuine intraday bars from the
broker's public read tier (no session, no credentials, GET only):

    https://vt.eclear.com.pk/pero/GetOHLCData?scrip=SYM&market=REG
        &check=symbol&interval=1

Each response carries the FULL day's 1-minute bars for the symbol (rows
`SYM;REG;open;high;low;close;HH:MM` joined by '|'), so even a slow rotation
never loses bars: every pass re-fetches the whole day and only new bar times
are banked. That is why the 16:45 PKT pass (after the close) is essential: it
is the pass the end-of-day finalize step reads, and it must be allowed to
fetch the finished session rather than be skipped as "outside hours".

When the source has no bars to serve it answers HTTP 200 with a bare
`SYM;MKT;` acknowledgement instead of data (measured live 2026-10-09 during
the session, for every symbol, interval, market, header and cookie variant).
That envelope is rejected as a failed symbol, so symbol coverage collapses,
the low-coverage flag is written, and no scan or outcome can run - the
capture path stays fail-closed and never invents bars.

These hosts reject the default Python TLS hello; they accept a legacy
SECLEVEL=1 context (verified live 2026-10-06). Requests are paced 1.2s+.

Banked data (gitignored under /data/):
    data/feed_capture/ohlc_YYYYMMDD.ndjson   {ts, symbol, bars:[...]}
    data/feed_capture/ohlc_status.json       liveness heartbeat

Usage (from repo root):
    python -m src.data.ohlc_poller                  # run until Ctrl+C
    python -m src.data.ohlc_poller --once           # one full pass, exit
    python -m src.data.ohlc_poller --limit 5        # first N symbols only
    python -m src.data.ohlc_poller --status          # show heartbeat health
    python -m src.data.ohlc_poller --probe OGDC      # ask the source now, print what it really returns
"""

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# SO-8: every timestamp this poller writes is Karachi wall clock, i.e.
# Asia/Karachi UTC+5, pinned here as a fixed offset (no DST in Karachi).
KARACHI = timezone(timedelta(hours=5))  # Asia/Karachi = UTC+5, SO-8

from src.data.feed_capture import load_universe, UNIVERSE_FILE  # noqa: E402
from src.data.sessions import is_trading_day  # noqa: E402
from src.data.capture_health import status_view  # noqa: E402
from src.data.registry import availability, Availability  # noqa: E402

OHLC_HOSTS = ["vt.eclear.com.pk", "nxg1.eclear.com.pk", "nxg2.eclear.com.pk"]
OHLC_PATH = "/pero/GetOHLCData"
PACING_SECONDS = 1.3
MIN_CAPTURE_COVERAGE = 0.80
CAPTURE_DIR = ROOT / "data" / "feed_capture"
STATUS_PATH = CAPTURE_DIR / "ohlc_status.json"
LOW_COVERAGE_FLAG = CAPTURE_DIR / "ohlc_low_coverage.flag"


def make_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def fetch_body(opener: urllib.request.OpenerDirector, symbol: str,
               interval: int = 1) -> tuple[str, bytes] | None:
    """Return (host, raw_body) from the first mirror that answers, or None."""
    for host in OHLC_HOSTS:
        url = (f"https://{host}{OHLC_PATH}?scrip={symbol}"
               f"&market=REG&check=symbol&interval={interval}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9.0"})
            with opener.open(req, timeout=15) as resp:
                return host, resp.read()
        except OSError:
            continue
    return None


def acknowledged_without_bars(text: str) -> bool:
    """True for the source's bare "SYM;MKT;" envelope, which carries no bars.

    Measured live on 2026-10-09, inside the Friday session: the servlet
    answers HTTP 200 and echoes "<scrip>;<market>;" with zero OHLC rows for
    every symbol (even a nonexistent scrip), every interval, every market
    value, every header set and with and without cookies. That envelope is a
    rejection, never an empty set of genuine bars, so a pass receiving it
    must count the symbol as failed and leave the coverage gate closed.
    """
    rows = [row.strip() for row in text.split("|") if row.strip()]
    if not rows:
        return True
    return len(rows) == 1 and rows[0].count(";") == 2 and rows[0].endswith(";")


def fetch_bars(opener: urllib.request.OpenerDirector, symbol: str,
               interval: int = 1) -> list[dict] | None:
    """Return [{t,o,h,l,c}] for today, or None when the source serves no bars."""
    fetched = fetch_body(opener, symbol, interval)
    if fetched is None:
        return None
    text = fetched[1].decode("utf-8", "replace")
    if acknowledged_without_bars(text):
        return None

    bars = []
    for row in text.split("|"):
        parts = row.strip().split(";")
        # row: SYM;REG;open;high;low;close;HH:MM
        if len(parts) != 7 or parts[0] != symbol:
            continue
        try:
            values = [float(parts[i]) for i in (2, 3, 4, 5)]
        except ValueError:
            continue
        # NaN/Inf are parseable but are not prices; never bank them.
        if not all(math.isfinite(value) for value in values):
            continue
        bars.append({"t": parts[6], "o": values[0], "h": values[1],
                     "l": values[2], "c": values[3]})
    return bars or None


def capture_coverage_ok(symbols_with_data: int, universe_size: int) -> bool:
    """Fail closed when the collector cannot substantiate broad market coverage."""
    return (universe_size > 0 and
            symbols_with_data / universe_size >= MIN_CAPTURE_COVERAGE)


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
    parser.add_argument("--probe", metavar="SYMBOL", default=None,
                        help="one read-only source check: report exactly what the "
                             "endpoint returns for SYMBOL, then exit")
    args = parser.parse_args(argv)

    if args.probe:
        # Honest source check: report what the source really returned, and
        # never let a bare acknowledgement count as a healthy capture.
        probe = args.probe.strip().upper()
        opener = make_opener()
        fetched = fetch_body(opener, probe)
        if fetched is None:
            print(f"probe {probe}: no mirror answered: NOT capturing")
            return 1
        host, raw = fetched
        text = raw.decode("utf-8", "replace")
        if acknowledged_without_bars(text):
            print(f"probe {probe}: {host} answered HTTP 200 with the bare "
                  f"acknowledgement {text.strip()!r} and zero bar rows: "
                  f"NOT capturing (the source is serving no OHLC)")
            return 1
        bars = fetch_bars(opener, probe)
        if not bars:
            print(f"probe {probe}: {host} answered {len(raw)}B with no usable row "
                  f"for this symbol: NOT capturing")
            return 1
        print(f"probe {probe}: {host} served {len(bars)} bar row(s), "
              f"first={bars[0]['t']} last={bars[-1]['t']}")
        return 0

    if args.status:
        if not STATUS_PATH.is_file():
            print("no ohlc_status.json yet: the poller has not run")
            return 1
        saved = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        print(json.dumps(status_view(saved), indent=1))
        return 0

    symbols = load_universe(args.symbols_file)
    # PSX holidays and weekends: the cron fires anyway; skip cleanly so the
    # run stays green and no capture-degraded alert fires (SO-8 calendar).
    if not is_trading_day(now().date()):
        print(f"{now():%Y-%m-%d %H:%M} is not a PSX trading day: capture skipped")
        return 0
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
    if args.once and not capture_coverage_ok(
            poller.counters["symbols_ok"], len(poller.symbols)):
        coverage = poller.counters["symbols_ok"] / max(len(poller.symbols), 1)
        print(f"capture rejected: coverage {coverage:.1%} is below "
              f"{MIN_CAPTURE_COVERAGE:.0%}; no scan or outcome will run")
        # Owner order 2026-10-08: a thin capture must NOT turn the scheduled
        # run red (GitHub failure emails per run are unwanted). The run
        # stays green; the flag file tells the alert step to send ONE
        # deduped Telegram notice for the day. Data quality stays honest:
        # the scan step still sees the thin capture and reports it.
        LOW_COVERAGE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        LOW_COVERAGE_FLAG.write_text(json.dumps({
            "ts": now().isoformat(timespec="seconds"),
            "coverage": round(coverage, 4),
            "symbols_ok": poller.counters["symbols_ok"],
            "universe": len(poller.symbols),
        }, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

