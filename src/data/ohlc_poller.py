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
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# SO-8: every timestamp this poller writes is Karachi wall clock, i.e.
# Asia/Karachi UTC+5, pinned here as a fixed offset (no DST in Karachi).
KARACHI = timezone(timedelta(hours=5))  # Asia/Karachi = UTC+5, SO-8

from src import config  # noqa: E402
from src.data.feed_capture import load_universe, UNIVERSE_FILE  # noqa: E402
from src.data.sessions import is_trading_day  # noqa: E402
from src.data.capture_health import status_view  # noqa: E402
from src.data.registry import availability, Availability  # noqa: E402

OHLC_HOSTS = ["vt.eclear.com.pk", "nxg1.eclear.com.pk", "nxg2.eclear.com.pk"]
OHLC_PATH = "/pero/GetOHLCData"
PACING_SECONDS = 1.3
#: One request per symbol, sequential and polite. This is the allowance on top
#: of the pacing sleep for TLS, the request itself and the parse, used to size
#: a pass budget. Calibrated on the measured CI pass over this universe: 741s
#: for 319 symbols is 2.32s per symbol, i.e. about 1s of work per request on
#: top of the 1.3s pacing sleep.
REQUEST_ALLOWANCE_SECONDS = 1.0
MIN_CAPTURE_COVERAGE = 0.80
#: How many consecutive symbols a pass may come back empty-handed for before
#: it stops treating the source as "this symbol" and starts treating it as
#: "the source": after this many, the pass probes the first mirror only and
#: asks once per symbol. All three mirrors are the same servlet, so during a
#: vendor outage probing all of them on every symbol is three times the load
#: on a source that is already down, which the pacing law here forbids.
DEGRADED_STREAK_BEFORE_SOLE_HOST = 3
#: How each of the source's two refusals is named in a log line. The cause
#: belongs beside the symbol: measured live on 2026-10-12, every one of 41
#: consecutive failing passes wrote "fetch failed: <symbol>", which reads
#: like one bad scrip while the truth was that the whole endpoint answered
#: `SYM;REG;` with no rows for every symbol, on every mirror, all session.
FAILURE_READING = {"no_bars": "the source answered but served no bars",
                   "unreachable": "no mirror answered"}
#: Exit status for a pass that stopped at its own budget. Distinct on purpose:
#: a caller can tell "the source served nothing" (coverage fail-closed, still
#: exit 0) from "we ran out of the time the cadence allows" (a partial pass).
EXIT_PASS_INCOMPLETE = 3
CAPTURE_DIR = ROOT / "data" / "feed_capture"
STATUS_PATH = CAPTURE_DIR / "ohlc_status.json"
LOW_COVERAGE_FLAG = CAPTURE_DIR / "ohlc_low_coverage.flag"


def make_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx))


def ask_host(opener: urllib.request.OpenerDirector, host: str, symbol: str,
             interval: int = 1) -> bytes | None:
    """One read-only request to one mirror: its body, or None if it did not answer."""
    url = (f"https://{host}{OHLC_PATH}?scrip={symbol}"
           f"&market=REG&check=symbol&interval={interval}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.9.0"})
        with opener.open(req, timeout=15) as resp:
            return resp.read()
    except OSError:
        return None


def fetch_body(opener: urllib.request.OpenerDirector, symbol: str,
               interval: int = 1,
               hosts: list[str] | None = None) -> tuple[str, bytes] | None:
    """Return (host, raw_body) from the first mirror that answers, or None."""
    for host in (OHLC_HOSTS if hosts is None else hosts):
        body = ask_host(opener, host, symbol, interval)
        if body is not None:
            return host, body
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


def parse_bars(text: str, symbol: str) -> list[dict]:
    """The rows in `text` that belong to exactly this symbol, malformed dropped."""
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
    return bars


class BarsFetch(NamedTuple):
    """One symbol's answer, and the two different ways it can be missing.

    `status` is one of:
      "ok"          - a mirror served genuine rows for this symbol;
      "no_bars"     - a mirror ANSWERED but none served a usable row (the
                      measured bare `SYM;MKT;` acknowledgement, an empty body,
                      rows that belong to another symbol, or rows that are all
                      malformed);
      "unreachable" - no mirror answered at all (connection or TLS level).

    Those two failures want different answers, so they are never collapsed
    into one. "unreachable" is about the wire, "no_bars" is the source itself
    saying it has nothing, and the coverage gate treats both as a failed
    symbol, which is what keeps a source outage fail-closed.
    """
    bars: list[dict] | None
    status: str
    host: str | None


def fetch_bars_ex(opener: urllib.request.OpenerDirector, symbol: str,
                  interval: int = 1,
                  hosts: list[str] | None = None) -> BarsFetch:
    """Fetch one symbol, preferring any mirror that actually serves bars.

    A mirror that answers with the bare acknowledgement (or with no usable row)
    does NOT end the search: the next mirror is asked, so one degraded host can
    never mask a host that is serving bars. That distinction matters because a
    slot that silently loses a symbol still writes a coverage figure, and a
    coverage figure produced by a masking mirror is a lie about the source.
    The first mirror that yields bars wins, and `host` names it so a fallback
    is visible rather than silent.
    """
    answered = False
    for host in (OHLC_HOSTS if hosts is None else hosts):
        body = ask_host(opener, host, symbol, interval)
        if body is None:
            continue
        answered = True
        text = body.decode("utf-8", "replace")
        if acknowledged_without_bars(text):
            continue
        bars = parse_bars(text, symbol)
        if bars:
            return BarsFetch(bars, "ok", host)
    return BarsFetch(None, "no_bars" if answered else "unreachable", None)


def fetch_bars(opener: urllib.request.OpenerDirector, symbol: str,
               interval: int = 1,
               hosts: list[str] | None = None) -> list[dict] | None:
    """Return [{t,o,h,l,c}] for today, or None when no mirror serves bars."""
    return fetch_bars_ex(opener, symbol, interval, hosts).bars


def capture_coverage_ok(symbols_with_data: int, universe_size: int) -> bool:
    """Fail closed when the collector cannot substantiate broad market coverage."""
    return (universe_size > 0 and
            symbols_with_data / universe_size >= MIN_CAPTURE_COVERAGE)


def nominal_pass_seconds(symbol_count: int) -> float:
    """Nominal wall clock for one full sequential pass over N symbols.

    An estimate, never a promise: it is used to size a budget and to explain a
    shortfall in the log. The KMIALL universe (319 symbols) needs about seven
    minutes at the source's own pacing, which is why a four-minute cadence
    cannot contain a complete pass and no timeout setting can change that.
    """
    return max(0, int(symbol_count)) * (PACING_SECONDS + REQUEST_ALLOWANCE_SECONDS)


def capture_budget_seconds(cadence_seconds: float,
                           reserve_seconds: float | None = None,
                           floor_seconds: float = 60.0) -> float:
    """Seconds a capture may spend inside one cadence, reserving work time.

    `reserve_seconds` defaults to config.CAPTURE_BUDGET_RESERVE_SECONDS and is
    the room left for the scan that follows the capture. The floor keeps a
    silly cadence from producing a zero-second budget.
    """
    if reserve_seconds is None:
        reserve_seconds = config.CAPTURE_BUDGET_RESERVE_SECONDS
    return max(float(floor_seconds), float(cadence_seconds) - float(reserve_seconds))


class OhlcPoller:
    def __init__(self, symbols: list[str], once: bool = False,
                 limit: int | None = None,
                 deadline_seconds: float | None = None):
        self.symbols = symbols[:limit] if limit else symbols
        self.once = once
        #: Stop a pass cleanly once this many seconds have been spent. None
        #: means "no budget", which is what a manual run and CI want.
        self.deadline_seconds = deadline_seconds
        #: False once any pass has stopped at its budget, so a caller can tell
        #: a complete refresh from a partial one.
        self.pass_complete = True
        self.opener = make_opener()
        self.seen: dict[str, set[str]] = {}
        self.counters = {"passes": 0, "symbols_ok": 0, "symbols_err": 0,
                         "symbols_skipped": 0, "bars": 0, "errors": 0,
                         "fallback_symbols": 0, "no_bars_symbols": 0,
                         "unreachable_symbols": 0}
        #: The mirrors this pass is willing to probe, narrowed to the first one
        #: once the whole source (not one symbol) proves silent. Reset per pass.
        self.hosts = list(OHLC_HOSTS)
        #: Consecutive symbols this pass has come back empty-handed for, across
        #: both failure modes. Drives the narrow-to-one-host politeness rule.
        self.degraded_streak = 0
        self.last_error: str | None = None
        #: The last symbol the source refused, and in which of its two ways
        #: ("no_bars" or "unreachable"), so a log line can name the cause and
        #: not only the symbol.
        self.last_failure_status: str | None = None
        #: How the LAST pass split between those two ways, with one sentence
        #: reading of it. Cumulative counters cannot explain an outage.
        self.last_pass = {"attempted": 0, "ok": 0, "no_bars": 0,
                          "unreachable": 0, "note": None}
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
            "last_pass": self.last_pass,
            "budget_seconds": self.deadline_seconds,
            "pass_complete": self.pass_complete,
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

    def budget_spent(self, started: float) -> bool:
        """True when this pass has used the time the cadence allows it."""
        return (self.deadline_seconds is not None
                and time.monotonic() - started >= self.deadline_seconds)

    def capture_symbol(self, symbol: str) -> list[dict] | None:
        """One symbol's bars, probing the mirrors politely when the source is down.

        A symbol is never silently dropped while another mirror could have
        served it: fetch_bars_ex already asks every mirror before giving up.
        What this adds is restraint in the other direction - once the source
        itself (not one symbol) has gone quiet for a few symbols running, the
        rest of the pass asks the first mirror only, once per symbol. Losing a
        symbol to a degraded mirror is a data fault; hammering a downed source
        three times per symbol is a manners fault, and this file does neither.
        """
        degraded = self.degraded_streak >= DEGRADED_STREAK_BEFORE_SOLE_HOST
        hosts = self.hosts[:1] if degraded else self.hosts
        fetch = fetch_bars_ex(self.opener, symbol, hosts=hosts)

        if fetch.status == "ok":
            self.degraded_streak = 0
            self.last_failure_status = None
            if fetch.host is not None and fetch.host != hosts[0]:
                # The first mirror did not serve this symbol and another one
                # did: say so, because a quiet fallback is how a degraded
                # mirror hides from the operator.
                self.counters["fallback_symbols"] += 1
            return fetch.bars

        self.degraded_streak += 1
        if (self.degraded_streak == DEGRADED_STREAK_BEFORE_SOLE_HOST
                and len(self.hosts) > 1):
            print(f"{now():%H:%M:%S} source quiet for {self.degraded_streak} "
                  f"symbols running (last: {symbol}, {fetch.status}): asking "
                  f"{self.hosts[0]} only for the rest of this pass, once per "
                  f"symbol, rather than every mirror")
        self.last_failure_status = fetch.status
        return None

    def run_pass(self) -> None:
        self.counters["passes"] += 1
        self.counters["symbols_skipped"] = 0
        self.pass_complete = True
        self.hosts = list(OHLC_HOSTS)
        self.degraded_streak = 0
        self.last_pass = {"attempted": 0, "ok": 0, "no_bars": 0,
                          "unreachable": 0, "note": None}
        started = time.monotonic()
        last_status = time.monotonic()
        for index, symbol in enumerate(self.symbols):
            if self.budget_spent(started):
                # Stop cleanly rather than be killed mid-write at a subprocess
                # timeout: every bar banked so far is already flushed, and the
                # status says out loud that this pass was short.
                skipped = len(self.symbols) - index
                self.counters["symbols_skipped"] = skipped
                self.pass_complete = False
                print(f"{now():%H:%M:%S} capture budget of "
                      f"{self.deadline_seconds:.0f}s spent after {index} of "
                      f"{len(self.symbols)} symbols: stopping this pass "
                      f"cleanly, {skipped} symbol(s) not refreshed "
                      f"(nominal full pass "
                      f"{nominal_pass_seconds(len(self.symbols)):.0f}s)")
                break
            bars = self.capture_symbol(symbol)
            self.last_pass["attempted"] += 1
            if bars is None:
                self.counters["symbols_err"] += 1
                status = self.last_failure_status or "unknown"
                if status in ("no_bars", "unreachable"):
                    self.counters[f"{status}_symbols"] += 1
                    self.last_pass[status] += 1
                self.last_error = (f"fetch failed: {symbol} "
                                   f"({FAILURE_READING.get(status, status)})")
            else:
                self.counters["symbols_ok"] += 1
                self.last_pass["ok"] += 1
                self.bank(symbol, bars)
                self.last_symbol_at = f"{symbol} {len(bars)}b"
            time.sleep(PACING_SECONDS)
            if time.monotonic() - last_status >= 20:
                self.write_status()
                last_status = time.monotonic()
        self.last_pass["note"] = self.read_pass()
        if self.last_pass["note"] is not None and not self.last_pass["ok"]:
            # Say the attribution out loud once per pass: the CI log and the
            # tick's captured detail both quote this line.
            print(f"{now():%H:%M:%S} {self.last_pass['note']}")
        self.write_status()

    def read_pass(self) -> str | None:
        """One sentence reading of the last pass, or None when it was clean.

        The value here is attribution. A failing pass has to say whether the
        SOURCE answered and had nothing (a vendor outage this machine cannot
        fix) or never answered at all (a wire or TLS problem on this side),
        because those two want different answers from whoever reads the log
        or the owner's alert.
        """
        stats = self.last_pass
        attempted, ok = stats["attempted"], stats["ok"]
        if attempted == 0 or ok == attempted:
            return None
        parts = []
        if stats["no_bars"]:
            parts.append(f"{stats['no_bars']} answered with no bars (the bare "
                         f"acknowledgement from every mirror)")
        if stats["unreachable"]:
            parts.append(f"{stats['unreachable']} were unreachable (no mirror "
                         f"answered)")
        detail = ", ".join(parts)
        reading = f"{attempted - ok} of {attempted} symbol(s) failed: {detail}"
        if not ok:
            reading += (". The source served nothing this pass, so the "
                        "coverage gate stays closed and no scan can run")
        return reading

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
    parser.add_argument("--deadline-seconds", type=float, default=None,
                        help="stop the pass cleanly after this many seconds "
                             "(a scheduled caller passes its own cadence "
                             "minus the time its scan needs)")
    parser.add_argument("--probe", metavar="SYMBOL", default=None,
                        help="one read-only source check: report exactly what the "
                             "endpoint returns for SYMBOL, then exit")
    args = parser.parse_args(argv)

    if args.probe:
        # Honest source check: report what the source really returned, and
        # never let a bare acknowledgement count as a healthy capture. The
        # probe follows the same mirror policy a pass does, so it cannot
        # report a mute first mirror as the whole story while a later mirror
        # is serving bars; the host it names is the host that actually served.
        probe = args.probe.strip().upper()
        opener = make_opener()
        fetch = fetch_bars_ex(opener, probe)
        if fetch.status == "unreachable":
            print(f"probe {probe}: no mirror answered: NOT capturing")
            return 1
        if fetch.status == "no_bars":
            mirrored = fetch_body(opener, probe)
            echo = (f"{mirrored[0]} answered with the bare acknowledgement "
                    f"{mirrored[1].decode('utf-8', 'replace').strip()!r}"
                    if mirrored is not None else "a mirror answered empty")
            print(f"probe {probe}: {echo} and no mirror served a usable row "
                  f"for this symbol: NOT capturing (the source is serving "
                  f"no OHLC)")
            return 1
        bars = fetch.bars
        print(f"probe {probe}: {fetch.host} served {len(bars)} bar row(s), "
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
    poller = OhlcPoller(symbols, once=args.once, limit=args.limit,
                        deadline_seconds=args.deadline_seconds)
    print(f"{now():%Y-%m-%d %H:%M:%S} OHLC capture starting: "
          f"{len(poller.symbols)} symbols, pacing {PACING_SECONDS}s")
    nominal = nominal_pass_seconds(len(poller.symbols))
    print(f"nominal full pass: {nominal:.0f}s for "
          f"{len(poller.symbols)} symbols")
    if args.deadline_seconds is not None and args.deadline_seconds < nominal:
        # Say it before the work starts, so a short pass is expected and
        # explained rather than discovered as a mysterious timeout later.
        print(f"budget {args.deadline_seconds:.0f}s is below the nominal "
              f"{nominal:.0f}s pass: this pass will be partial by design")
    try:
        poller.run()
    except KeyboardInterrupt:
        print(f"{now():%H:%M:%S} stopped by owner (Ctrl+C)")
    finally:
        poller.close()
    print(f"banked {poller.counters['bars']} bars over "
          f"{poller.counters['passes']} pass(es)")
    if args.limit is not None:
        # A --limit run is a diagnostic over a deliberately small slice, so its
        # coverage is a statement about that slice and never about the market.
        # It must therefore NOT leave the market-wide low-coverage flag behind.
        # That flag is exactly what raises the owner's degraded-capture alert,
        # and this module documents `--limit 5` as its own smoke test: without
        # this guard a five symbol check could page the owner with "0/5
        # symbols" while the tracked universe is 319, which is what happened on
        # 2026-10-12. The slice is still reported here, honestly.
        print(f"limited capture: {len(poller.symbols)} symbol(s) requested, so "
              f"no market-wide coverage is claimed and the degraded-capture "
              f"alert is left untouched")
    elif args.once and not capture_coverage_ok(
            poller.counters["symbols_ok"], len(poller.symbols)):
        coverage = poller.counters["symbols_ok"] / max(len(poller.symbols), 1)
        print(f"capture rejected: coverage {coverage:.1%} is below "
              f"{MIN_CAPTURE_COVERAGE:.0%}; no scan or outcome will run")
        if poller.last_pass["note"] is not None:
            # The cause, while the numbers are still on screen: whoever reads
            # the CI log or the tick's captured detail must not have to guess
            # which side of the wire failed.
            print(poller.last_pass["note"])
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
            # The measured cause travels with the coverage figure, so the
            # owner's alert can say WHY instead of only how little arrived.
            "cause": poller.last_pass["note"],
            "no_bars_symbols": poller.counters["no_bars_symbols"],
            "unreachable_symbols": poller.counters["unreachable_symbols"],
        }, indent=1), encoding="utf-8")
    if not poller.pass_complete:
        # A partial pass is a degraded capture, not a clean one: the caller
        # gets a distinct status so its log can carry the arithmetic.
        print(f"capture pass stopped at its {poller.deadline_seconds:.0f}s "
              f"budget: {poller.counters['symbols_skipped']} of "
              f"{len(poller.symbols)} symbol(s) were not refreshed this pass "
              f"(partial capture)")
        return EXIT_PASS_INCOMPLETE
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

