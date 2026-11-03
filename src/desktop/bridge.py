"""The desktop terminal's data core: Qt free, so CI tests it without PySide6.

Every function here reads the same backend the cloud runs, through the same
modules, and returns plain dataclasses and dicts:

  * live quotes from today's banked capture (`quote_rows`) or from one frame
    just banked by the capture thread (`quote_from_update`);
  * the market session law (`session_status`, `session_progress`);
  * feed health from the recorder's own heartbeat (`feed_health`), which is
    what keeps a connected socket from being shown as a healthy feed;
  * the local session record (`trade_decision`);
  * measured order flow for the leaders (`order_flow_rows`), with the
    inferred basis carried in the payload. The registry at
    src/data/registry.py is the authority on what may be claimed.

Nothing here invents a number: a missing field is None and the UI prints a
dash. No function places an order or talks to a broker.
"""

from __future__ import annotations

from src.data.registry import REGISTRY  # SO-3: the data dependency

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KARACHI = timezone(timedelta(hours=5))   # SO-8

APP_DIR = (Path(os.environ.get("APPDATA") or str(Path.home()))
           / "QuantOfRehan")
CAPTURE_ROOT = Path(os.environ.get("QOR_CAPTURE_DIR")
                     or (ROOT / "data" / "feed_capture"))
SETTINGS_NAME = "settings.json"

DEFAULT_SETTINGS = {
    "window_geometry": "",
    "window_state": "",
    "auto_start_feed": True,
    "max_symbols": 80,
}


def settings_path(directory: Path | None = None) -> Path:
    return (directory or APP_DIR) / SETTINGS_NAME


def load_settings(directory: Path | None = None) -> dict:
    """Settings merged over the defaults; an unreadable file is ignored."""
    settings = dict(DEFAULT_SETTINGS)
    path = settings_path(directory)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if isinstance(saved, dict):
        for key in DEFAULT_SETTINGS:
            if key in saved:
                settings[key] = saved[key]
        for key, value in saved.items():
            settings.setdefault(key, value)
    return settings


def save_settings(settings: dict, directory: Path | None = None) -> Path:
    """Atomic write: a crash mid-save never leaves half a settings file."""
    path = settings_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


@dataclass(frozen=True)
class QuoteRow:
    """One symbol's latest observation, ready for the live table."""

    symbol: str
    last: float | None
    change_pct: float | None
    volume: int | None
    bid: float | None
    ask: float | None
    spread: float | None
    age_seconds: float | None
    status: str

    def as_dict(self) -> dict:
        return asdict(self)


def _now(now: datetime | None) -> datetime:
    moment = now or datetime.now(KARACHI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KARACHI)
    return moment.astimezone(KARACHI)


def quote_from_update(quote: dict, now: datetime | None = None) -> QuoteRow:
    """One live quote (feed_capture.relay_quote_updates shape) as a row."""
    bid = quote.get("bid")
    ask = quote.get("ask")
    spread = (round(ask - bid, 4)
              if isinstance(bid, (int, float)) and isinstance(ask, (int, float))
              and ask >= bid else None)
    observed = quote.get("observed_at")
    age = None
    if observed:
        try:
            stamp = datetime.fromisoformat(str(observed))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=KARACHI)
            age = max(0.0, (_now(now) - stamp).total_seconds())
        except ValueError:
            age = None
    volume = quote.get("volume")
    return QuoteRow(
        symbol=str(quote.get("symbol", "")).upper(),
        last=quote.get("price"),
        change_pct=quote.get("change_pct"),
        volume=int(volume) if isinstance(volume, (int, float)) else None,
        bid=bid, ask=ask, spread=spread, age_seconds=age,
        status=str(quote.get("status") or "UNKNOWN"),
    )


def capture_for(day: datetime | None, capture_root: Path | None = None) -> Path:
    moment = _now(day)
    root = capture_root or CAPTURE_ROOT
    return root / f"capture_{moment:%Y%m%d}.ndjson"


def quote_rows(capture: Path | None = None, now: datetime | None = None,
               limit: int | None = None, max_age_seconds: float = 900.0
               ) -> list[QuoteRow]:
    """Latest observation per REG symbol from a banked capture, newest first.

    Reads backwards only, stopping once the tail is older than the window,
    so a 90 MB session file costs a bounded read rather than a full parse.
    A symbol whose newest row is older than the window is left out: a stale
    quote dressed as a live one is the failure this table exists to avoid.
    """
    from src.data import broker_market

    moment = _now(now)
    path = capture or capture_for(moment)
    if not path.is_file():
        return []
    latest: dict[str, QuoteRow] = {}
    for record in broker_market._newest_records(path):
        if not isinstance(record, dict):
            continue
        kind = str(record.get("kind", ""))
        if not kind.startswith("MKT-FEED"):
            continue
        try:
            stamp = datetime.fromisoformat(str(record.get("ts", "")))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=KARACHI)
        age = (moment - stamp.astimezone(KARACHI)).total_seconds()
        if age > max_age_seconds:
            break
        for tick in broker_market._tick_rows(record):
            symbol = str(tick.get("scrip", "")).strip().upper().split(":", 1)[0]
            if (not symbol or symbol in latest
                    or str(tick.get("market", "")).strip().upper() != "REG"):
                continue
            price = broker_market._number(tick.get("last"))
            close = broker_market._number(tick.get("close"))
            volume = broker_market._number(tick.get("volume"))
            bid = broker_market._number(tick.get("bid"))
            ask = broker_market._number(tick.get("ask"))
            latest[symbol] = QuoteRow(
                symbol=symbol,
                last=price if price and price > 0 else None,
                change_pct=((price - close) / close * 100.0
                            if price and close and close > 0 else None),
                volume=int(volume) if volume is not None and volume >= 0 else None,
                bid=bid, ask=ask,
                spread=(round(ask - bid, 4)
                        if bid and ask and ask >= bid else None),
                age_seconds=round(age, 1),
                status=broker_market._symbol_status(tick.get("status")),
            )
    rows = sorted(latest.values(),
                  key=lambda row: (-(row.volume or 0), row.symbol))
    return rows[:limit] if limit else rows


def session_status(now: datetime | None = None) -> dict:
    """The one session law's answer, as the relay and the phone read it."""
    from src.data import sessions

    return sessions.market_state(now)


def session_progress(now: datetime | None = None) -> tuple[float, str]:
    """(fraction of the live band elapsed, band label) for the HUD gauge."""
    state = session_status(now)
    band = state.get("live_band")
    if not band:
        return 0.0, str(state.get("phase") or "CLOSED")
    moment = _now(now)
    def minutes(text: str) -> int:
        hour, minute = (int(part) for part in str(text).split(":", 1))
        return hour * 60 + minute
    start, end = minutes(band["open"]), minutes(band["close"])
    current = moment.hour * 60 + moment.minute + moment.second / 60.0
    if end <= start:
        return 0.0, f"{band['open']}-{band['close']}"
    fraction = (current - start) / (end - start)
    return max(0.0, min(1.0, fraction)), f"{band['open']}-{band['close']}"


def feed_health(status_path: Path | None = None,
                now: datetime | None = None) -> dict:
    """Classify the feed in the owner's four steps, never from a socket alone.

    CONNECTED (the recorder says it is running), RECEIVING (its last frame is
    inside the heartbeat staleness bound), FRESH (a frame inside 90 seconds)
    and COVERAGE (how many symbols its universe asks for). A file that is
    missing or stale reports DEAD, which is what the System Health page must
    be able to say.
    """
    from src.data import live_card

    # The recorder's heartbeat lives in the capture root, which the frozen
    # build redirects to %APPDATA% (app.py). Reading the repo default here
    # made a running feed report DEAD; the capture root is the one truth.
    path = status_path or (CAPTURE_ROOT / "status.json")
    moment = _now(now)
    if not path.is_file():
        return {"state": "DEAD", "detail": "no recorder heartbeat yet",
                "counters": {}, "age_seconds": None, "universe_size": None}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"state": "DEAD", "detail": f"heartbeat unreadable: {type(exc).__name__}",
                "counters": {}, "age_seconds": None, "universe_size": None}
    stamp = None
    try:
        stamp = datetime.fromisoformat(str(saved.get("updated_at", "")))
    except ValueError:
        pass
    age = None
    if stamp is not None:
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=KARACHI)
        age = max(0.0, (moment - stamp.astimezone(KARACHI)).total_seconds())
    counters = saved.get("counters") or {}
    if not saved.get("running"):
        state = "DEAD"
        detail = "the recorder is not running"
    elif age is None:
        state = "UNKNOWN"
        detail = "the heartbeat carries no readable time"
    elif age > live_card.TAPE_STALE_SECONDS * 4:
        state = "DEAD"
        detail = f"no heartbeat for {age:.0f}s"
    elif age > 90:
        state = "STALE"
        detail = f"last frame {age:.0f}s ago"
    else:
        state = "FRESH"
        detail = f"last frame {age:.0f}s ago, {counters.get('messages', 0)} messages banked"
    return {"state": state, "detail": detail, "counters": counters,
            "age_seconds": None if age is None else round(age, 1),
            "universe_size": saved.get("universe_size"),
            "last_frame_at": saved.get("last_frame_at"),
            "last_error": saved.get("last_error")}


def trade_decision(day=None, state=None) -> dict:
    """The local engine's record for the day, as the Signals page shows it."""
    if state is None:
        from src.signals.trade_state import SessionState

        state = SessionState.load(day)
    return {
        "day": state.day,
        "state": state.state,
        "symbol": state.symbol,
        "entry_price": state.entry_price,
        "entry_time": state.entry_time,
        "target_price": state.target_price,
        "stop_loss": state.stop_loss,
        "exit_price": state.exit_price,
        "exit_time": state.exit_time,
        "return_pct": state.return_pct,
        "target_hit": state.target_hit,
        "stop_hit": state.stop_hit,
        "exit_reason": state.exit_reason,
        "trades_today": state.trades_today,
        "finalized": state.finalized,
        "last_reason": state.last_reason,
        "scans": state.scans,
    }


def _capture_file(capture: Path | None = None,
                  now: datetime | None = None) -> Path:
    return capture or capture_for(_now(now))


def _finite(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _parse_stamp(value) -> datetime | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=KARACHI)
    return stamp


class FlowMemory:
    """Session-cumulative, monotonic buy/sell attribution from live frames.

    The owner's law (PRL report, 2026-11-03): a scrip's buying volume,
    selling volume and total volume can only grow during a session; a
    figure that drops is a bug, and a method that re-attributes the day
    by the price's position in the range is the bug he caught. The window
    rules here are the repository's own, from src/data/tick_volume.py:
    each positive increment of the venue's running total is one window,
    attributed by print evidence (at the ask, at the bid, else the tick
    rule). A window without evidence, one spanning a gap of more than
    MAX_WALL_SECONDS of tape, or shares counted before the terminal
    started are reported as unclassified rather than guessed. A running
    total that goes backwards is reported, never attributed. Nothing in
    this class ever subtracts from buy, sell or total.
    """

    def __init__(self) -> None:
        self._day = None
        self._state: dict[str, dict] = {}
        self._index: list[float] = []

    def observe(self, quotes) -> None:
        """Feed one live batch (feed_capture.relay_quote_updates shape)."""
        for quote in quotes or []:
            try:
                self._observe_one(quote)
            except Exception:  # noqa: BLE001 - one bad quote never stops it
                continue

    def observe_index(self, value) -> None:
        number = _finite(value)
        if number is None or number <= 0:
            return
        if not self._index or self._index[-1] != number:
            self._index.append(number)
        if len(self._index) > 240:
            del self._index[:120]

    def seed(self, rows, flows, series=None, index_values=None) -> int:
        """Day-cumulative state from today's banked tape, before the feed.

        rows are the newest QuoteRows (volume and print per symbol), flows
        are tick_volume.SymbolFlow measured over the whole day, and the
        series pair seed the charts. A symbol the live feed already
        observed keeps its own counts: seeding never lowers anything.
        """
        seeded = 0
        for row in rows:
            symbol = str(row.symbol).upper()
            if symbol in self._state:
                continue
            flow = (flows or {}).get(symbol)
            self._state[symbol] = {
                "symbol": symbol,
                "volume": row.volume,
                "price": row.last,
                "bid": row.bid,
                "ask": row.ask,
                "buy": int(flow.buy_volume or 0) if flow else 0,
                "sell": int(flow.sell_volume or 0) if flow else 0,
                "unclassified": (int(getattr(flow, "unclassified_volume", 0)
                                     or 0) if flow else 0),
                "gaps": 0,
                "backward": 0,
                "observed": None,
                "series": list((series or {}).get(symbol) or [])[-240:],
            }
            seeded += 1
        if index_values:
            self._index = list(index_values)[-240:]
        return seeded

    def row_count(self) -> int:
        return len(self._state)

    def rows(self, limit: int | None = None) -> list[dict]:
        """The session's scrips, venue total first; monotonic by law."""
        ordered = sorted(self._state.values(),
                         key=lambda state: (-(state["volume"] or 0),
                                            state["symbol"]))
        selected = ordered[:limit] if limit else ordered
        out = []
        for state in selected:
            buy, sell = state["buy"], state["sell"]
            total = state["volume"]
            share = (buy / (buy + sell)) if (buy + sell) > 0 else None
            out.append({
                "symbol": state["symbol"],
                "price": state["price"],
                "volume": total,
                "buy_volume": buy,
                "sell_volume": sell,
                "buy_share": round(share, 3) if share is not None else None,
                "unclassified": state["unclassified"],
                "gaps": state["gaps"],
                "backward": state["backward"],
                "basis": "tape-measured window attribution",
            })
        return out

    def chart_series(self, limit: int = 8, points: int = 24) -> dict:
        """Downsampled price series for the top scrips' dotted charts."""
        rows = self.rows(limit)
        out = {}
        for row in rows:
            values = self._state[row["symbol"]]["series"]
            if len(values) <= points:
                out[row["symbol"]] = list(values)
                continue
            step = len(values) / points
            out[row["symbol"]] = [values[int(index * step)]
                                  for index in range(points)]
        return out

    def index_series(self, points: int = 24) -> list[float]:
        values = self._index
        if len(values) <= points:
            return list(values)
        step = len(values) / points
        return [values[int(index * step)] for index in range(points)]

    def basis_note(self) -> str:
        unclassified = sum(state["unclassified"]
                           for state in self._state.values())
        backward = sum(state["backward"] for state in self._state.values())
        note = ("B and S are measured window attribution from the banked "
                "tape (print at the ask, at the bid, else the tick rule); "
                "T is the venue's running total. Buy, sell and total only "
                "grow during a session.")
        if unclassified:
            note += (f" {unclassified:,} shares are counted as "
                     "unattributed (outages and no-evidence windows), "
                     "never split by guess.")
        if backward:
            note += (f" {backward} running totals went backwards and were "
                     "reported, not attributed.")
        return note

    def _observe_one(self, quote) -> None:
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            return
        observed = _parse_stamp(quote.get("observed_at"))
        volume = _finite(quote.get("volume"))
        price = _finite(quote.get("price"))
        bid = _finite(quote.get("bid"))
        ask = _finite(quote.get("ask"))
        day = observed.date() if observed else self._day
        if day is not None and self._day is not None and day != self._day:
            self._state.clear()   # a new session restarts every counter
            self._index.clear()
        if day is not None:
            self._day = day
        state = self._state.get(symbol)
        if state is None:
            # First sight of the symbol: the running total becomes the
            # baseline, so the venue total shows at once while every share
            # before now stays unattributed rather than guessed.
            self._state[symbol] = {
                "symbol": symbol, "volume": volume, "price": price,
                "bid": bid, "ask": ask, "buy": 0, "sell": 0,
                "unclassified": 0, "gaps": 0, "backward": 0,
                "observed": observed, "series":
                ([price] if price is not None else []),
            }
            return
        prev_observed = state["observed"]
        prev_price = state["price"]
        got_total = volume is not None and volume > 0
        if not got_total:
            # The row carries no running total: no window of its own, but
            # it is still the newest print evidence.
            state["price"], state["bid"], state["ask"] = price, bid, ask
            state["observed"] = observed or state["observed"]
            return
        previous_volume = state["volume"]
        state["price"], state["bid"], state["ask"] = price, bid, ask
        state["observed"] = observed or state["observed"]
        if previous_volume is None:
            state["volume"] = volume
            return
        delta = int(volume) - int(previous_volume)
        if delta < 0:
            # A running total that went backwards cannot be split, and the
            # displayed total must never fall: report it, keep the high
            # water mark, and measure later windows from it.
            state["backward"] += 1
            return
        state["volume"] = volume
        if delta == 0:
            return   # the feed repeats whole snapshots; one change is one
        from src.data import tick_volume

        gap = None
        if observed is not None and prev_observed is not None:
            gap = max(0.0, (observed - prev_observed).total_seconds())
        if gap is not None and gap > tick_volume.MAX_WINDOW_SECONDS:
            state["gaps"] += 1
            state["unclassified"] += delta   # an outage is not a side
        else:
            from src.data import tick_volume

            side, _how = tick_volume._trade_side(
                {"last": price, "bid": bid, "ask": ask},
                {"last": prev_price})
            if side == "B":
                state["buy"] += delta
            elif side == "S":
                state["sell"] += delta
            else:
                state["unclassified"] += delta
        if price is not None:
            series = state["series"]
            if not series or series[-1] != price:
                series.append(price)
            if len(series) > 240:
                del series[:120]




def spark_series(symbols=None, capture: Path | None = None,
                 minutes: int = 45, points: int = 32,
                 now: datetime | None = None) -> tuple[dict,
                                                       list, str]:
    """Recent last-price series per symbol and the index series for charts.

    Reads only the tape's tail bounded by the minutes window, then
    downsamples to at most `points` per series, so a chart costs a bounded
    read and never the day's full parse.
    """
    from src.data import broker_market

    path = _capture_file(capture, now)
    if not path.is_file():
        return {}, [], "no banked tape for today"
    moment = _now(now)
    wanted = ([str(s).strip().upper() for s in symbols]
              if symbols is not None else [])
    series: dict[str, list] = {symbol: [] for symbol in wanted}
    index_values: list = []
    for record in broker_market._newest_records(path):
        try:
            stamp = datetime.fromisoformat(str(record.get("ts", "")))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=KARACHI)
        if (moment - stamp.astimezone(KARACHI)).total_seconds() > minutes * 60:
            break
        kind = str(record.get("kind", ""))
        if kind.startswith("EXS-FEED"):
            index = broker_market.parse_index_frame(str(record.get("raw", "")))
            if index is not None and index.get("value") is not None:
                index_values.append(float(index["value"]))
            continue
        if not kind.startswith("MKT-FEED"):
            continue
        ticks = broker_market._tick_rows(record)
        by_symbol: dict[str, float | None] = {}
        for tick in ticks:
            symbol = str(tick.get("scrip", "")).strip().upper().split(":", 1)[0]
            if symbol in series and symbol not in by_symbol:
                price = broker_market._number(tick.get("last"))
                if price is not None and price > 0:
                    by_symbol[symbol] = price
        for symbol, price in by_symbol.items():
            series[symbol].append(price)
        if (all(len(series[s]) >= points for s in wanted)
                and len(index_values) >= points):
            break
    trimmed = {symbol: list(reversed(values[-points:]))
               for symbol, values in series.items()}
    note = (f"charts cover the last {minutes} minutes of the banked tape"
            if trimmed or index_values else "the tape's tail is empty")
    return trimmed, list(reversed(index_values[-points:])), note


def session_record(day=None, path: Path | None = None) -> dict:
    """The engine's session record, with the moment its file was written.

    The record's own state vocabulary includes market markers, so a
    MARKET_CLOSED written before the open must never be presented as the
    live phase: the file's mtime travels with the record as its age, and
    the window says plainly when the record is stale.
    """
    from src.signals.trade_state import SessionState

    target = path or SessionState.path()
    record = trade_decision(day, SessionState.load(day, target))
    recorded = None
    age = None
    if target.is_file():
        try:
            recorded = datetime.fromtimestamp(target.stat().st_mtime, KARACHI)
            age = max(0.0, (_now(None) - recorded).total_seconds())
        except OSError:
            recorded = None
    record["recorded_at"] = (recorded.isoformat(timespec="seconds")
                             if recorded is not None else None)
    record["record_age_seconds"] = (round(age, 1)
                                    if age is not None else None)
    return record


def wire_lag(capture: Path | None = None,
             now: datetime | None = None) -> dict:
    """Measured print lag on the newest banked frame, in seconds.

    Every REG row carries the exchange's own print clock and the record
    carries the moment the recorder banked it; the difference is the
    wire's lag. Reported as measured (median, p95, worst, frame age), not
    as an opinion about the feed.
    """
    from src.data import broker_market

    path = _capture_file(capture, now)
    out = {"median": None, "p95": None, "max": None,
           "newest_age": None, "prints": 0}
    if not path.is_file():
        return out
    moment = _now(now)
    for record in broker_market._newest_records(path):
        if not isinstance(record, dict):
            continue
        if not str(record.get("kind", "")).startswith("MKT-FEED"):
            continue
        stamp = _parse_stamp(record.get("ts"))
        if stamp is None:
            continue
        lags = []
        for tick in broker_market._tick_rows(record):
            clock = str(tick.get("tick_time") or "").strip()
            if not clock:
                continue
            try:
                printed = datetime.strptime(clock, "%H:%M:%S").replace(
                    year=stamp.year, month=stamp.month, day=stamp.day,
                    tzinfo=KARACHI)
            except ValueError:
                continue
            lag = (stamp - printed).total_seconds()
            if -5.0 <= lag <= 3600.0:
                lags.append(lag)
        if not lags:
            continue
        lags.sort()

        def at(fraction: float) -> float:
            index = min(len(lags) - 1, int(round(fraction * (len(lags) - 1))))
            return lags[index]

        middle = len(lags) // 2
        median = (lags[middle] if len(lags) % 2
                  else (lags[middle - 1] + lags[middle]) / 2.0)
        out = {"median": round(median, 1), "p95": round(at(0.95), 1),
               "max": round(lags[-1], 1),
               "newest_age": round(max(0.0, (moment - stamp).total_seconds()),
                                   1),
               "prints": len(lags)}
        return out
    return out


def footprint_availability() -> str:
    """The registry's own verdict on depth data, spelled the way it is shown."""
    source = REGISTRY["footprint"]
    label = getattr(source.availability, "value", "UNAVAILABLE")
    return str(label).upper()


def order_flow_rows(capture: Path | None = None, symbols=None,
                    limit: int = 12) -> list[dict]:
    """Measured flow for the leaders, every number carrying its basis.

    Missing inputs are None, never zero. The side split and CVD come from
    inferred side evidence on a snapshot wire and are labelled as inferred;
    the registry's footprint status travels in the payload (SO-3).
    """
    from src.data import order_flow as flow

    path = capture or capture_for(None)
    if not path.is_file():
        return []
    wanted = list(symbols) if symbols is not None else None
    if wanted is None:
        wanted = [row.symbol for row in quote_rows(path, limit=limit)]
    flows = flow.symbol_flow(path, wanted)
    rows = []
    for symbol, measured in flows.items():
        payload = measured.as_dict()
        payload["basis"] = {
            "sides": "inferred (print at the ask or bid, then the tick rule)",
            "footprint_registry": footprint_availability(),
            "depth": "top of book only",
        }
        rows.append(payload)
    rows.sort(key=lambda row: (-(row.get("volume_delta") or 0), row["symbol"]))
    return rows[:limit]
