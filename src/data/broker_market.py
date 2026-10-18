"""Fresh market-card values from the banked, read-only eClear feed.

The scheduled scan already keeps this capture alive and publishes the card to
the relay. This reader uses only fresh EXS-FEED index frames, REG MKT-STATS
market-wide state, and REG MKT-FEED rows for the tracked KMIALL universe.
Unknown or stale evidence stays unknown; a suspended symbol is never promoted
to a market-wide halt.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_DIR = ROOT / "data" / "feed_capture"
UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
KARACHI = timezone(timedelta(hours=5))
MAX_FEED_AGE_SECONDS = 90.0


def _number(value) -> float | None:
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _moment(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=KARACHI)
    return stamp.astimezone(KARACHI)


def _fresh_stamp(value, now: datetime,
                 max_age_seconds: float = MAX_FEED_AGE_SECONDS
                 ) -> tuple[datetime, float] | None:
    stamp = _moment(value)
    if stamp is None or stamp.date() != now.date():
        return None
    age = (now - stamp).total_seconds()
    if age < -5.0 or age > max_age_seconds:
        return None
    return stamp, max(0.0, age)


def parse_index_frame(raw: str) -> dict | None:
    """KSE100 from the feed's EXS-FEED groups, not another index group."""
    if not raw.startswith("EXS-FEED*"):
        return None
    body = raw.split("*", 1)[1]
    chosen = None
    for group in body.split("$"):
        head = group.split("^")
        if len(head) < 2:
            continue
        fields = head[1].split(";")
        if fields[0].strip().upper() == "KSE100":
            chosen = (head[0].strip(), fields)
            break
    if chosen is None:
        return None
    stamp_text, fields = chosen
    if len(fields) < 3:
        return None
    price, change = _number(fields[1]), _number(fields[2])
    if price is None or change is None or price <= 0:
        return None
    previous = price - change
    if previous <= 0:
        return None
    try:
        stamp = datetime.strptime(stamp_text, "%m/%d/%Y %I:%M:%S %p")
    except ValueError:
        return None
    stamp = stamp.replace(tzinfo=KARACHI)
    return {
        "symbol": "KSE100",
        "value": price,
        "change": change,
        "change_pct": change / previous * 100.0,
        "as_of": stamp.isoformat(timespec="seconds"),
        "source": "eClear EXS-FEED",
    }


def parse_market_status_frame(raw: str) -> tuple[str, str] | None:
    """Return the REG segment's recognized status and original status word."""
    if not raw.startswith("MKT-STATS*"):
        return None
    for segment in raw.split("*", 1)[1].split("|"):
        fields = segment.strip().split(";")
        if len(fields) < 2 or fields[0].strip().upper() != "REG":
            continue
        word = fields[1].strip().upper()
        if word in {"OPEN", "OPN", "TRADING", "LIVE"}:
            return "OPEN", fields[1].strip()
        if word in {"HALT", "HALTED", "SUS", "SUSPENDED", "PAUSED"}:
            return "HALTED", fields[1].strip()
        if word in {"CLOSED", "CLOSE", "CLS"}:
            return "CLOSED", fields[1].strip()
        return "UNKNOWN", fields[1].strip()
    return None


def _universe_symbols() -> set[str]:
    records = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    return {str(row.get("symbol", "")).strip().upper()
            for row in records
            if "KMIALLSHR" in (row.get("listedIn") or [])
            and row.get("symbol")}


def _newest_records(path: Path):
    """Yield appended NDJSON records newest-first without reading the whole tape."""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        position = handle.tell()
        carry = b""
        while position:
            size = min(65536, position)
            position -= size
            handle.seek(position)
            block = handle.read(size) + carry
            lines = block.split(b"\n")
            carry = lines[0]
            for line in reversed(lines[1:]):
                if line.strip():
                    try:
                        yield json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
        if carry.strip():
            try:
                yield json.loads(carry)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return


def _tick_rows(record: Mapping) -> list[Mapping]:
    ticks = record.get("ticks") or []
    raw = str(record.get("raw", ""))
    if raw:
        # Reparse genuine MKT-FEED rows so old captures written before the
        # frame separator repair recover all symbols from their raw evidence.
        from src.data.feed_capture import parse_message

        parsed = parse_message(raw) or {}
        recovered = parsed.get("ticks") or []
        if recovered:
            ticks = recovered
    return [tick for tick in ticks if isinstance(tick, Mapping)]


def _symbol_status(value) -> str:
    word = str(value or "").strip().upper()
    if word in {"OPEN", "OPN", "TRADING", "LIVE"}:
        return "OPEN"
    if word in {"SUS", "SUSPENDED", "HALT", "HALTED", "PAUSED"}:
        return "SUSPENDED"
    return "UNKNOWN"


def read_market_snapshot(now: datetime | None = None, *,
                         capture_path: Path | None = None,
                         symbols: Iterable[str] | None = None) -> dict:
    """Latest fresh index/state and KMIALL leader rows from today's capture."""
    moment = now or datetime.now(KARACHI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=KARACHI)
    moment = moment.astimezone(KARACHI)
    path = capture_path or CAPTURE_DIR / f"capture_{moment:%Y%m%d}.ndjson"
    wanted = ({str(symbol).strip().upper() for symbol in symbols}
              if symbols is not None else _universe_symbols())

    latest_index: tuple[datetime, dict] | None = None
    latest_state: tuple[datetime, dict] | None = None
    latest_rows: dict[str, tuple[datetime, dict]] = {}
    if not path.is_file():
        return {"index": None, "top_volume": None,
                "market_feed": _unknown_market_state()}

    # CaptureSession appends in observation order. Walk back only as far as
    # the freshness window: rescanning a full day's tens-of-megabytes tape on
    # every 30-second publish would waste the scanner's budget.
    for record in _newest_records(path):
        if not isinstance(record, Mapping):
            continue
        kind = str(record.get("kind", ""))
        record_stamp = _moment(record.get("ts"))
        if record_stamp is None:
            continue
        if record_stamp.date() < moment.date():
            break
        if record_stamp.date() == moment.date() and (
                moment - record_stamp).total_seconds() > MAX_FEED_AGE_SECONDS:
            break
        fresh = _fresh_stamp(record.get("ts"), moment)
        if fresh is None:
            continue
        arrived, age = fresh
        raw = str(record.get("raw", ""))
        if kind.startswith("EXS-FEED"):
            index = parse_index_frame(raw)
            if index is not None and latest_index is None:
                index["feed_age_seconds"] = age
                latest_index = (arrived, index)
        elif kind.startswith("MKT-STATS"):
            state = parse_market_status_frame(raw)
            if state is not None and latest_state is None:
                status, raw_status = state
                latest_state = (arrived, {
                    "status": status,
                    "raw_status": raw_status,
                    "as_of": arrived.isoformat(timespec="seconds"),
                    "age_seconds": age,
                    "source": "eClear REG market feed",
                    "fresh": True,
                })
        elif kind.startswith("MKT-FEED"):
            for tick in _tick_rows(record):
                symbol = str(tick.get("scrip", "")).strip().upper().split(":", 1)[0]
                if (not symbol or symbol not in wanted
                        or str(tick.get("market", "")).strip().upper() != "REG"):
                    continue
                total = _number(tick.get("volume"))
                price = _number(tick.get("last"))
                if total is None or total <= 0:
                    continue
                close = _number(tick.get("close"))
                change_pct = (None if price is None or close is None or close <= 0
                              else (price - close) / close * 100.0)
                row = {
                    "symbol": symbol,
                    "volume": int(total),
                    "price": price if price is not None and price > 0 else None,
                    "change_pct": change_pct,
                    "market_status": _symbol_status(tick.get("status")),
                    "feed_as_of": arrived.isoformat(timespec="seconds"),
                    "basis": "current session volume (live REG feed)",
                }
                if symbol not in latest_rows:
                    latest_rows[symbol] = (arrived, row)

    rows = [row for _, row in latest_rows.values()]
    rows.sort(key=lambda row: (-row["volume"], row["symbol"]))

    return {
        "index": None if latest_index is None else latest_index[1],
        "top_volume": rows[:3] if rows else None,
        "market_feed": (latest_state[1] if latest_state is not None
                        else _unknown_market_state()),
    }


def _unknown_market_state() -> dict:
    return {
        "status": "UNKNOWN",
        "raw_status": None,
        "as_of": None,
        "age_seconds": None,
        "source": "eClear REG market feed",
        "fresh": False,
    }
