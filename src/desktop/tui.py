"""The Quant of Rehan console: the HUD as a real terminal application.

Owner order 2026-11-03 (final): the desk must open in the terminal like the
console he already runs, and it must read the relay the cloud keeps fed,
not a capture that only exists while some window is open. Every number on
screen comes from the same public surface the console reads: GET /quotes
each second (price, volume, high, low and the relay's own buy/sell split),
GET /market every five seconds (KSE100 and the volume leaders), GET /health
every fifteen seconds (session law, feed state, next event).

Buying and selling never fall. The day split takes the relay's pair and
holds each side at its session high-water mark; the sixty second board
adds only positive poll deltas, sided by the price move or the last side
when the price held. The engine record is shown with the time it was
written, and the market phase always comes from the session law, never
from that record.

Karachi is Asia/Karachi, the one fixed offset this system speaks, UTC+5,
with no daylight saving; every clock on the frame is that instant.

The registry is consulted for what the desk honestly has: true bid/ask
footprint is UNAVAILABLE on this wire, so the split shown is the relay's
range estimate, in words, on the page itself.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.data.registry import Availability, availability

RELAY_URL = os.environ.get("QOR_RELAY") or \
    "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"
KARACHI = timezone(timedelta(hours=5))
USER_AGENT = "QuantOfRehan-Terminal/2.0"

ROOT = Path(__file__).resolve().parents[2]
SESSION_STATE = ROOT / "data" / "forward" / "session_state.json"

PAGES = ("HOME", "SCANNER", "ORDER FLOW", "SIGNALS", "HEALTH", "SETTINGS")
SORTS = ("PRICES RISING FAST", "MORE BUYERS & LESS SELLERS",
         "BIG BUYING NOW (LIVE FLOW)")

GREEN = (46, 204, 113)
RED = (229, 72, 77)
CYAN = (43, 184, 217)
GOLD = (224, 169, 62)
WHITE = (234, 243, 247)
DIM = (127, 163, 176)
FAINT = (78, 110, 122)

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def paint(text, colour, bold: bool = False) -> str:
    red, green, blue = colour
    weight = "1;" if bold else ""
    return f"\x1b[{weight}38;2;{red};{green};{blue}m{text}\x1b[0m"


def plain(text: str) -> str:
    return ANSI.sub("", text)


def width_of(text: str) -> int:
    return len(plain(text))


def clip(text: str, width: int) -> str:
    """Trim to a visible width without cutting an escape sequence in half."""
    if width_of(text) <= width:
        return text
    out: list[str] = []
    visible = 0
    index = 0
    while index < len(text) and visible < width:
        match = ANSI.match(text, index)
        if match:
            out.append(match.group(0))
            index = match.end()
            continue
        out.append(text[index])
        index += 1
        visible += 1
    out.append("\x1b[0m")
    return "".join(out)


def pad(text: str, width: int, align: str = "left") -> str:
    if width_of(text) > width:
        text = clip(text, width)
    space = max(0, width - width_of(text))
    if align == "right":
        return " " * space + text
    if align == "center":
        left = space // 2
        return " " * left + text + " " * (space - left)
    return text + " " * space


def rule(width: int, char: str = "\u2500") -> str:
    return char * max(0, width)


def boxed(title: str, lines: list[str], width: int, colour=CYAN) -> list[str]:
    inner = max(1, width - 4)
    head = "\u250c\u2500 " + title + " " + \
        rule(max(0, inner - width_of(title) - 1), "\u2500") + "\u2510"
    out = [paint(head, colour)]
    for line in lines:
        out.append(paint("\u2502 ", colour) + pad(line, inner) +
                   paint(" \u2502", colour))
    out.append(paint("\u2514" + rule(inner + 2, "\u2500") + "\u2518", colour))
    return out


def money(value) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if abs(value) >= 1_000_000:
        return f"PKR {value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"PKR {value / 1_000:.0f}K"
    return f"PKR {value:,.0f}"


def shares(value) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.2f}M shares"
    if abs(value) >= 1_000:
        return f"{value / 1_000:.2f}K shares"
    return f"{value:,.0f} shares"


def count(value) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    return f"{int(value):,}"


def pct_text(value) -> tuple[str, tuple[int, int, int]]:
    if not isinstance(value, (int, float)):
        return "-", FAINT
    arrow = "\u25b2" if value >= 0 else "\u25bc"
    return f"{arrow} {abs(value):.2f}%", (GREEN if value >= 0 else RED)


def spark(values) -> str:
    levels = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    clean = [value for value in values if isinstance(value, (int, float))]
    if len(clean) < 2:
        return ""
    lo, hi = min(clean), max(clean)
    span = (hi - lo) or 1.0
    return "".join(levels[max(1, min(8, int((v - lo) / span * 7) + 1))]
                   for v in clean)


def _range_split(price, volume, high, low):
    """The same range-position estimate the relay publishes, for rows that
    arrive without a split pair. Never a tape claim, only the estimate."""
    if not isinstance(volume, (int, float)) or volume <= 0:
        return None, None
    if not all(isinstance(item, (int, float)) for item in (price, high, low)):
        return None, None
    span = high - low
    if span <= 0:
        return int(volume * 0.5), int(volume) - int(volume * 0.5)
    position = (price - low) / span
    position = min(1.0, max(0.0, position))
    buy = int(round(volume * position))
    return buy, int(volume) - buy


class FlowTracker:
    """Session state for every scrip, from every poll of the relay.

    The day pair is the relay's own split, held at each side's high-water
    mark, so neither can fall. The sixty second board adds only positive
    volume deltas, sided by the price move against the previous poll (or
    the last side when the price held), which is the console's executed
    buying rule. Nothing here subtracts.
    """

    def __init__(self) -> None:
        self.day: dict[str, dict] = {}
        self.window: dict[str, deque] = {}
        self.seconds = 60.0

    def observe(self, quotes, now: datetime) -> None:
        for quote in quotes or []:
            try:
                self._one(quote, now)
            except Exception:  # noqa: BLE001 - one bad row never stops it
                continue

    def _one(self, quote, now: datetime) -> None:
        symbol = str(quote.get("symbol") or "").strip().upper()
        price = quote.get("price")
        if not symbol or not isinstance(price, (int, float)) or price <= 0:
            return
        volume = quote.get("volume")
        volume = int(volume) if isinstance(volume, (int, float)) else None
        buy_relay = quote.get("buy_volume")
        sell_relay = quote.get("sell_volume")
        high = quote.get("high")
        low = quote.get("low")
        state = self.day.get(symbol)
        if state is None:
            if not isinstance(buy_relay, (int, float)) or \
                    not isinstance(sell_relay, (int, float)):
                buy_relay, sell_relay = _range_split(price, volume, high, low)
            state = self.day[symbol] = {
                "symbol": symbol, "price": price, "volume": volume or 0,
                "buy": int(buy_relay) if isinstance(buy_relay, (int, float))
                else 0,
                "sell": int(sell_relay) if isinstance(sell_relay, (int, float))
                else 0,
                "change_pct": quote.get("change_pct"), "side": "B",
                "high": high, "low": low, "series": [price],
                "baseline": bool(volume),
            }
            self.window[symbol] = deque()
            return
        previous_volume = state["volume"]
        previous_price = state["price"]
        if isinstance(high, (int, float)):
            state["high"] = high
        if isinstance(low, (int, float)):
            state["low"] = low
        if not isinstance(buy_relay, (int, float)) or \
                not isinstance(sell_relay, (int, float)):
            buy_relay, sell_relay = _range_split(
                price, state["volume"] or None, state.get("high"),
                state.get("low"))
        if isinstance(buy_relay, (int, float)):
            state["buy"] = max(state["buy"], int(buy_relay))
        if isinstance(sell_relay, (int, float)):
            state["sell"] = max(state["sell"], int(sell_relay))
        state["price"] = price
        state["change_pct"] = quote.get("change_pct")
        delta = 0
        if volume is not None:
            if not state.get("baseline"):
                # the first running total is the day's baseline, never a
                # single poll's trade, so it is adopted without attribution
                state["volume"] = volume
                state["baseline"] = True
            elif volume >= previous_volume:
                delta = volume - previous_volume
                state["volume"] = volume
            # a running total that falls is never attributed or adopted
        if delta > 0:
            if price > previous_price:
                state["side"] = "B"
            elif price < previous_price:
                state["side"] = "S"
            value = delta * price
            self.window[symbol].append(
                (now, delta, value if state["side"] == "B" else 0.0,
                 value if state["side"] == "S" else 0.0))
        if price != previous_price:
            series = state["series"]
            series.append(price)
            del series[:-30]
        self._trim(symbol, now)

    def _trim(self, symbol: str, now: datetime) -> None:
        window = self.window.get(symbol)
        if not window:
            return
        edge = now - timedelta(seconds=self.seconds)
        while window and window[0][0] < edge:
            window.popleft()

    def rows(self, sort: str = "", now: datetime | None = None) -> list[dict]:
        moment = now or datetime.now(KARACHI)
        out = []
        for symbol, state in self.day.items():
            self._trim(symbol, moment)
            window = self.window.get(symbol) or ()
            bought = sum(item[2] for item in window)
            sold = sum(item[3] for item in window)
            moved = sum(item[1] for item in window)
            out.append({
                "symbol": symbol, "price": state["price"],
                "change_pct": state["change_pct"], "volume": state["volume"],
                "buy_volume": state["buy"], "sell_volume": state["sell"],
                "high": state.get("high"), "low": state.get("low"),
                "bought": state["buy"] * state["price"],
                "sold": state["sell"] * state["price"],
                "bought_60": bought, "sold_60": sold, "shares_60": moved,
                "series": list(state["series"]),
            })
        if sort == "PRICES RISING FAST":
            out.sort(key=lambda row: -(row["change_pct"] or -999))
        elif sort == "MORE BUYERS & LESS SELLERS":
            out.sort(key=lambda row: -((row["buy_volume"] or 0)
                                       - (row["sell_volume"] or 0)))
        elif sort == "BIG BUYING NOW (LIVE FLOW)":
            out.sort(key=lambda row: -row["bought_60"])
        else:
            out.sort(key=lambda row: -(row["volume"] or 0))
        return out


def _age_seconds(stamp, now: datetime) -> float | None:
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KARACHI)
    return max(0.0, (now - moment).total_seconds())


class Desk:
    """One poll's worth of the relay's truth, plus the local engine record."""

    def __init__(self) -> None:
        self.flow = FlowTracker()
        self.quotes: list = []
        self.market: dict = {}
        self.health: dict = {}
        self.record: dict = {}
        self.link_ms = None
        self.polled_at = None
        self.error = ""

    def observe(self, quotes, now: datetime, link_ms=None) -> None:
        self.quotes = quotes or []
        self.polled_at = now
        self.link_ms = link_ms
        self.flow.observe(self.quotes, now)

    def feed_age(self, now: datetime) -> float | None:
        ages = [_age_seconds(row.get("observed_at"), now)
                for row in self.quotes]
        ages = [age for age in ages if age is not None]
        return min(ages) if ages else None

    def fresh_count(self, now: datetime, limit: float = 60.0) -> int:
        total = 0
        for row in self.quotes:
            age = _age_seconds(row.get("observed_at"), now)
            if age is not None and age <= limit:
                total += 1
        return total

    def phase(self) -> dict:
        return self.health.get("market_state") or {}

    def index(self) -> dict:
        return self.market.get("index") or {}


def load_record(path: Path | None = None) -> dict:
    """The engine's session record with the moment it was written."""
    target = path or SESSION_STATE
    if not target.is_file():
        return {"state": "NO RECORD"}
    try:
        saved = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"state": "NO RECORD"}
    if not isinstance(saved, dict):
        return {"state": "NO RECORD"}
    try:
        written = target.stat().st_mtime
        saved["recorded_at"] = datetime.fromtimestamp(
            written, KARACHI).isoformat(timespec="seconds")
        saved["record_age"] = max(
            0.0, (datetime.now(KARACHI).timestamp() - written))
    except OSError:
        saved["recorded_at"] = None
        saved["record_age"] = None
    return saved


def human_age(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return ""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "now"
    if minutes < 90:
        return f"{minutes} min old"
    return f"{minutes / 60:.1f} h old"


def fetch(path: str, timeout: float = 8.0) -> tuple[dict, float]:
    url = path if path.startswith("http") else RELAY_URL + path
    started = time.perf_counter()
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return payload, (time.perf_counter() - started) * 1000.0


def _top_by_volume(desk: Desk, now: datetime, limit: int = 3) -> list[dict]:
    rows = desk.flow.rows(now=now)
    return rows[:limit]


def render(desk: Desk, page: int, sort: int, size, now: datetime) -> list[str]:
    """One frame as coloured lines; pure, so tests can call it."""
    columns, lines = size
    columns = max(92, columns)
    lines = max(24, lines)
    left_w = 34
    right_w = columns - left_w - 2
    body_height = lines - 5
    out: list[str] = []

    age = desk.feed_age(now)
    fresh = desk.fresh_count(now)
    lag_text = f"{age:.0f}s" if age is not None else "-"
    state = ("LIVE" if (age is not None and age <= 8 and fresh > 100)
             else "LAGGING" if age is not None and age <= 120 else "STALE")
    state_colour = GREEN if state == "LIVE" else (
        GOLD if state == "LAGGING" else RED)
    phase = desk.phase()
    market_open = bool(phase.get("market_open"))

    left_header = paint(
        ("\u25cf " if state == "LIVE" else "\u25cb ") + state + " " +
        lag_text, state_colour, True)
    title = paint("\u25c6  Q U A N T  O F  R E H A N  \u25c6", GOLD, True)
    right_header = paint(f"KARACHI {now:%H:%M:%S} UTC+5", DIM, True)
    out.append(_three(left_header, title, right_header, columns))
    out.append(_three(paint(f"{now:%Y-%m-%d}", DIM),
                      paint("PSX'S KMIALL INDEX", CYAN),
                      paint("", CYAN), columns))
    out.append(paint(rule(columns, "\u2550"), FAINT))

    left: list[str] = []
    core_title = "\u25c6 QUANT CORE"
    left.append(paint("\u250c\u2500 ", CYAN) + paint(core_title, CYAN, True) +
                paint(" " + rule(left_w - 5 - width_of(core_title), "\u2500") +
                      "\u2510", CYAN))
    for line in _orb(market_open):
        left.append(paint("\u2502 ", CYAN) + pad(line, left_w - 4) +
                    paint(" \u2502", CYAN))
    status = paint("\u25c6 ONLINE", GREEN, True) + "  " + paint(
        "\u25c6 SCANNING" if market_open else "\u25c6 STANDBY", CYAN)
    left.append(paint("\u2502 ", CYAN) + pad(status, left_w - 4) +
                paint(" \u2502", CYAN))
    left.append(paint("\u2514" + rule(left_w - 2) + "\u2518", CYAN))

    telemetry = [
        f"{paint('LINK', FAINT)}  {paint(f'{desk.link_ms:.0f} ms' if desk.link_ms else '-', WHITE)}",
        f"{paint('FEED', FAINT)}  {paint(state + '  ' + lag_text, state_colour)}",
        f"{paint('PHASE', FAINT)} {paint(str(phase.get('phase') or '-'), WHITE)}",
        f"{paint('NEXT', FAINT)}  {paint(str((phase.get('next_event') or {}).get('event') or '-') + ' ' + str((phase.get('next_event') or {}).get('at_pk') or '')[-5:], DIM)}",
        f"{paint('SCAN', FAINT)}  {paint('1S LIVE' if market_open else 'OFF-SESSION', WHITE)}",
        f"{paint('FLOW', FAINT)}  {paint('ON', GREEN)} {len(desk.flow.day)} scrips",
        f"{paint('REQ', FAINT)}   {paint(f'{fresh}/{len(desk.quotes)} fresh', DIM)}",
    ]
    for line in boxed("\u25c6 TELEMETRY", telemetry, left_w):
        left.append(line)
    left = left[:body_height]
    while len(left) < body_height:
        left.append(" " * left_w)

    body = _page_lines(desk, page, sort, right_w, now)[:body_height]
    while len(body) < body_height:
        body.append(" " * right_w)
    for index in range(body_height):
        out.append(pad(left[index], left_w) + "  " + pad(body[index],
                                                         right_w))

    keys = (" 1 HOME  2 SCANNER  3 ORDER FLOW  4 SIGNALS  5 HEALTH  "
            "6 SETTINGS   R refresh   Q quit ")
    if page == 1:
        keys = (" UP/DOWN sort   S next sort   1 HOME  2 SCANNER  "
                "3 ORDER FLOW  4 SIGNALS  5 HEALTH  Q quit ")
    out.append(paint(rule(columns, "\u2550"), FAINT))
    out.append(paint(pad(keys, columns), FAINT))
    return out


def _three(left: str, centre: str, right: str, columns: int) -> str:
    """Left at the margin, the title on the centre line, the clock at the edge."""
    lw, cw, rw = width_of(left), width_of(centre), width_of(right)
    if lw + cw + rw + 4 > columns:
        return pad(left + " " + centre + " " + right, columns)
    start = max(lw + 2, (columns - cw) // 2)
    used = start + cw
    gap = max(2, columns - rw - used)
    return pad(left, start) + centre + pad("", gap) + right


def _orb(market_open: bool) -> list[str]:
    art = [
        "       .:::::::::.",
        "    .:::::'. .':::::.",
        "   ::::'         '::::",
        "  :::::           :::::",
        "  :::::   :::::   :::::",
        "   ::::   :::::   ::::",
        "    ':::::. . .:::::'",
        "       ':::::::::'",
    ]
    colour = CYAN if market_open else FAINT
    return [paint(line, colour) for line in art]


def _page_lines(desk: Desk, page: int, sort: int, width: int,
                now: datetime) -> list[str]:
    if page == 1:
        return _scanner_page(desk, sort, width, now)
    if page == 2:
        return _flow_page(desk, width, now)
    if page == 3:
        return _signals_page(desk, width, now)
    if page == 4:
        return _health_page(desk, width, now)
    if page == 5:
        return _settings_page(desk, width, now)
    return _home_page(desk, width, now)


def _home_page(desk: Desk, width: int, now: datetime) -> list[str]:
    lines: list[str] = []
    phase = desk.phase()
    open_now = bool(phase.get("market_open"))
    greet = ("Good morning" if now.hour < 12 else
             "Good afternoon" if now.hour < 17 else "Good evening")
    lines.append(paint(greet + ", Mr. Rehan.", WHITE, True))
    lines.append("")

    status = (f"{paint('ONLINE' if open_now else 'CLOSED', GREEN if open_now else DIM, True)}"
              f"   Karachi {now:%Y-%m-%d %H:%M} PKT")
    detail = ("Market is trading; the relay is fed every second."
              if open_now else "Market closed; the banked day stands.")
    for line in boxed("\u25c6 QUANT STATUS", [status, paint(detail, DIM)],
                      width):
        lines.append(line)
    lines.append("")

    record = desk.record
    record_lines = [paint(str(record.get("state") or "NO RECORD"), GOLD, True)]
    if record.get("day"):
        record_lines.append(paint(f"day {record['day']} (latest engine write)",
                                  DIM))
    if record.get("symbol"):
        record_lines.append(
            f"SYMBOL {paint(str(record['symbol']), WHITE, True)}   "
            f"ENTRY {record.get('entry_price') or '-'}   "
            f"EXIT {record.get('exit_price') or '-'}   "
            f"STOP {record.get('stop_loss') or '-'}")
    else:
        record_lines.append(paint("no trade in the local engine record", DIM))
    if record.get("recorded_at"):
        age_text = human_age(record.get("record_age"))
        record_lines.append(paint(
            "record written " + str(record["recorded_at"])[11:16] + " PKT" +
            (" (" + age_text + ")" if age_text else ""), FAINT))
    for line in boxed("\u25c6 LATEST SIGNAL", record_lines, width):
        lines.append(line)
    lines.append("")

    index = desk.index()
    value = index.get("value")
    change = index.get("change")
    board: list[str] = []
    index_line = "KSE100 " + paint(
        f"{value:,.2f}" if isinstance(value, (int, float)) else "-",
        WHITE, True)
    if isinstance(change, (int, float)):
        arrow = "\u25b2" if change >= 0 else "\u25bc"
        index_line += "   " + paint(
            f"{arrow} {change:+,.2f}", GREEN if change >= 0 else RED)
    board.append(index_line)
    board.append("")
    for number, row in enumerate(_top_by_volume(desk, now), start=1):
        arrow, colour = pct_text(row["change_pct"])
        board.append(
            f"{number}. {paint(row['symbol'], WHITE, True)}  "
            f"PKR {row['price']:.2f}  {paint(arrow, colour)}")
        board.append(
            f"   B={paint(count(row['buy_volume']), GREEN)}  "
            f"S={paint(count(row['sell_volume']), RED)}  "
            f"T={count(row['volume'])}")
        series = row.get("series") or []
        if series:
            board.append("   " + paint(spark(series), GREEN))
    board.append("")
    board.append(paint("B/S is a range estimate, not order flow; footprint "
                       "UNAVAILABLE.", FAINT))
    for line in boxed("\u25c6 THE INDEX & TOP 3 SCRIPS OF VOL.", board, width):
        lines.append(line)
    return lines


def _scanner_page(desk: Desk, sort: int, width: int, now: datetime) -> list[str]:
    lines = [paint("\u25c6 CUSTOM SCRIPS OF VOL.", WHITE, True),
             paint("SELECT A SORT: UP/DOWN CHOOSES IT; S CYCLES.", DIM), ""]
    for number, name in enumerate(SORTS):
        marker = paint("\u25b8 ", GREEN) if number == sort else "  "
        body = paint(name, WHITE if number == sort else CYAN, number == sort)
        lines.append("  " + marker + body)
    lines.append("")
    chosen = SORTS[sort]
    windowed = chosen == "BIG BUYING NOW (LIVE FLOW)"
    heading = pad(paint(chosen, CYAN, True), max(10, width - 32))
    lines.append(heading + pad(paint(
        "last 60 s, executed buying" if windowed else "day split, estimate",
        FAINT), 32, "right"))
    lines.append("")
    rows = desk.flow.rows(chosen, now)
    if windowed:
        rows = [row for row in rows
                if row["bought_60"] > 0 or row["sold_60"] > 0]
    else:
        rows = [row for row in rows if row["volume"]]
    rows = rows[:8]
    if not rows:
        lines.append(paint("no executed buying in the last 60 s yet"
                           if windowed
                           else "waiting for the relay's next poll", DIM))
        return lines
    flow = [(row,
             row["bought_60"] if windowed else row["bought"],
             row["sold_60"] if windowed else row["sold"],
             row["shares_60"] if windowed else row["volume"])
            for row in rows]
    scale = max(1, min(36, width - 44))
    for number, (row, bought, sold, moved) in enumerate(flow, start=1):
        arrow, colour = pct_text(row["change_pct"])
        total = bought + sold
        percent = int(round(100 * bought / total)) if total > 0 else 0
        filled = int(round(scale * percent / 100))
        bar = "\u2501" * filled
        price = paint(f"PKR {row['price']:.2f} {arrow}", colour, True)
        head = f"{number}. {paint(row['symbol'], WHITE, True)}"
        lines.append(head + pad(price, max(8, width - width_of(head)),
                                "right"))
        lines.append(f"   BOUGHT {paint(money(bought), GREEN)}"
                     f"  SOLD {paint(money(sold), RED)}  {shares(moved)}")
        lines.append("   " + paint(bar, GREEN) +
                     " " * max(0, scale - filled) + f" {percent:>3}%")
    return lines


def _flow_page(desk: Desk, width: int, now: datetime) -> list[str]:
    lines = [paint("\u25c6 ORDER FLOW  -  DAY MONEY FLOW BY VOLUME",
                   WHITE, True), ""]
    header = (pad("SCRIP", 10) + pad("PRICE", 10, "right") +
              pad("BUY", 13, "right") + pad("SELL", 13, "right") +
              pad("TOTAL", 13, "right") + pad("CHG", 10, "right"))
    lines.append(paint(header, FAINT))
    rows = desk.flow.rows(now=now)
    for row in rows[:14]:
        arrow, _colour = pct_text(row["change_pct"])
        lines.append(
            pad(row["symbol"], 10) +
            pad(f"{row['price']:.2f}", 10, "right") +
            pad(count(row["buy_volume"]), 13, "right") +
            pad(count(row["sell_volume"]), 13, "right") +
            pad(count(row["volume"]), 13, "right") +
            pad(arrow, 10, "right"))
    lines.append("")
    lines.append(paint(split_basis() + "; each side is held at its "
                       "high-water mark so neither can fall", FAINT))
    return lines


def _signals_page(desk: Desk, width: int, now: datetime) -> list[str]:
    record = desk.record
    lines = [paint("\u25c6 LOCAL ENGINE RECORD", WHITE, True),
             paint(str(record.get("state") or "NO RECORD"), GOLD, True)]
    if record.get("symbol"):
        lines.append(
            f"{record['symbol']}  entry {record.get('entry_price')}  "
            f"target {record.get('target_price')}  "
            f"stop {record.get('stop_loss')}")
    else:
        lines.append(paint("no trade recorded for today", DIM))
    lines.append(paint(
        f"day {record.get('day')}   trades {record.get('trades_today')}   "
        f"scans {record.get('scans')}   finalized "
        f"{'yes' if record.get('finalized') else 'no'}", FAINT))
    if record.get("recorded_at"):
        age_text = human_age(record.get("record_age"))
        lines.append(paint(
            "record written " + str(record["recorded_at"])[:16] +
            (" (" + age_text + ")" if age_text else ""), FAINT))
    lines.append("")
    lines.append(paint("the market phase above is the session law's; the "
                       "record is the engine's last write, not a live "
                       "claim", FAINT))
    return lines


def _health_page(desk: Desk, width: int, now: datetime) -> list[str]:
    age = desk.feed_age(now)
    phase = desk.phase()
    feed = desk.health.get("market_feed") or {}
    index = desk.index()
    lines = [
        paint("\u25c6 RELAY AND FEED", WHITE, True),
        f"{paint('relay ', FAINT)} {RELAY_URL}",
        f"{paint('link  ', FAINT)} "
        f"{f'{desk.link_ms:.0f} ms' if desk.link_ms else '-'}"
        f"   rows {len(desk.quotes)}   fresh {desk.fresh_count(now)}",
        f"{paint('feed  ', FAINT)} age "
        f"{f'{age:.0f}s' if age is not None else '-'}"
        f"   market {feed.get('status') or '-'}"
        f" age {feed.get('age_seconds') or '-'}s",
        f"{paint('phase ', FAINT)} {phase.get('phase') or '-'}"
        f"   next {(phase.get('next_event') or {}).get('event') or '-'} "
        f"{(phase.get('next_event') or {}).get('at_pk') or ''}",
        f"{paint('index ', FAINT)} "
        f"{index.get('value') if isinstance(index.get('value'), (int, float)) else '-'}"
        f"   split {index.get('source') or '-'}",
        "",
        paint("each poll reads /quotes; the terminal waits on the relay, "
              "never on a clock of its own", FAINT),
    ]
    return lines


def split_basis() -> str:
    """What the B/S pair is, in the registry's own verdict."""
    if availability("footprint") is Availability.UNAVAILABLE:
        return ("true bid/ask footprint is UNAVAILABLE (registry): B and S "
                "are the relay's range estimate, not order flow")
    return "B and S follow the feed's own split"


def _settings_page(desk: Desk, width: int, now: datetime) -> list[str]:
    return [paint("\u25c6 SETTINGS", WHITE, True),
            f"relay   {RELAY_URL}",
            "poll    1 s /quotes, 5 s /market, 15 s /health",
            "keys    1-6 pages, up/down sort, R refresh, Q quit",
            "",
            paint("set QOR_RELAY to point the terminal at another relay",
                  FAINT)]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    once = "--once" in args
    page = 0
    sort = 2
    for index, arg in enumerate(args):
        if arg == "--page" and index + 1 < len(args):
            page = max(0, min(len(PAGES) - 1, int(args[index + 1])))
        if arg == "--sort" and index + 1 < len(args):
            sort = max(0, min(len(SORTS) - 1, int(args[index + 1])))

    if os.name == "nt":
        try:
            import ctypes

            kernel = ctypes.windll.kernel32
            handle = kernel.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel.SetConsoleMode(handle, mode.value | 0x0004)
            kernel.SetConsoleOutputCP(65001)
            kernel.SetConsoleCP(65001)
        except Exception:  # noqa: BLE001 - the console keeps its defaults
            pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    desk = Desk()
    desk.record = load_record()
    now = datetime.now(KARACHI)
    next_market = 0.0
    next_health = 0.0
    next_record = 0.0

    if once:
        try:
            desk.observe(_quotes(desk), now, link_ms=desk.link_ms)
        except Exception as exc:  # noqa: BLE001 - the frame still prints
            desk.error = f"{type(exc).__name__}: {exc}"
        for path, name in (("/market", "market"), ("/health", "health")):
            try:
                value, _ = fetch(path)
                setattr(desk, name, value)
            except Exception:  # noqa: BLE001
                pass
        frame = render(desk, page, sort, _size(), datetime.now(KARACHI))
        sys.stdout.write("\n".join(frame) + "\n")
        return 0

    page = 0 if page is None else page
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    next_tick = time.monotonic()
    try:
        while True:
            now = datetime.now(KARACHI)
            stamp = time.monotonic()
            try:
                desk.observe(_quotes(desk), now, link_ms=desk.link_ms)
                desk.error = ""
            except Exception as exc:  # noqa: BLE001 - shown in the footer
                desk.error = f"relay: {type(exc).__name__}"
            if stamp >= next_market:
                next_market = stamp + 5.0
                try:
                    desk.market, _ = fetch("/market")
                except Exception:  # noqa: BLE001
                    pass
            if stamp >= next_health:
                next_health = stamp + 15.0
                try:
                    desk.health, _ = fetch("/health")
                except Exception:  # noqa: BLE001
                    pass
            if stamp >= next_record:
                next_record = stamp + 5.0
                desk.record = load_record()

            frame = render(desk, page, sort, _size(),
                           datetime.now(KARACHI))
            if desk.error:
                frame[-1] = paint(pad(" " + desk.error, _size()[0]), RED)
            sys.stdout.write("\x1b[H" + "\n".join(frame))
            sys.stdout.flush()

            while msvcrt is not None and msvcrt.kbhit():
                key = msvcrt.getwch()
                if key in ("q", "Q", "\x03"):
                    return 0
                if key in "123456":
                    page = int(key) - 1
                elif key in ("\x00", "\xe0"):
                    code = msvcrt.getwch()
                    if code == "H":
                        sort = (sort - 1) % len(SORTS)
                    elif code == "P":
                        sort = (sort + 1) % len(SORTS)
                elif key in ("s", "S"):
                    sort = (sort + 1) % len(SORTS)
            # keep the one second cadence even when a poll was slow, so the
            # poll itself never stretches the refresh into a visible lag
            next_tick += 1.0
            pause = next_tick - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                next_tick = time.monotonic()
    finally:
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()


def _quotes(desk: Desk) -> list:
    payload, link_ms = fetch("/quotes")
    desk.link_ms = link_ms
    return payload.get("quotes") or []


def _size() -> tuple[int, int]:
    try:
        columns, lines = os.get_terminal_size()
    except OSError:
        columns, lines = 120, 34
    return columns, lines


if __name__ == "__main__":
    raise SystemExit(main())
