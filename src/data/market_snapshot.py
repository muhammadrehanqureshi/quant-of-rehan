"""Market snapshot for the phone app: KSE100 points and the volume leaders.

Owner order 2026-10-09: the app must show the KSE100 index with its points and
percentage, plus the top three KMIALL stocks by volume, refreshed every five
minutes, and it must never claim the market is online when it is closed.

Both numbers come from the PSX Data Portal's own server rendered pages, which
are public, need no key, and are live during the session:

  1. KSE100. ``https://dps.psx.com.pk/`` carries an index panel with
     ``data-date`` (the portal's own observation time), ``data-close`` (the
     points) and the change line ``151.89 (0.09%)``. The sign is carried by
     the ``change__text--pos`` / ``change__text--neg`` class, so a down day is
     reported as a fall. Nothing is derived from the previous close.
  2. Volume leaders. ``https://dps.psx.com.pk/indices/KMIALLSHR`` is the
     KMIALLSHR constituent table: one server rendered row per member of the
     index the strategy trades, with the current session VOLUME in a
     ``data-order`` attribute. Membership comes from the page itself, so the
     universe is the exchange's list and never a hardcoded one.

Cross check, 2026-10-09: the KSE100 points and percentage parsed here matched
the anonymous eClear index feed (EXS-FEED, nxg1:8484) to the tick at the same
minute, and the constituent count matched the KMIALL universe the scanner
loads (313 symbols).

Honesty rules:
  * A page that cannot be parsed produces ``None`` plus a note, never a guess.
  * When the constituent table is unreachable the volume ranking is reported
    as unavailable rather than filled with a 30 day average, which is a
    different quantity and would be a lie about "today".
  * ``market_open`` is computed from the owner's session law in
    src/data/sessions.py (SO-8), the same law the worker and the runner use.
    SO-8: this module never builds a market time of its own. The only zone it
    ever speaks is Asia/Karachi, the fixed UTC+5 offset defined once in
    src/data/sessions.py and imported here, so nothing below can drift with
    the machine clock or with a timezone database update. The portal's own
    timestamp string is passed through untouched and is labelled as such.

Usage:
    python -m src.data.market_snapshot --show          # print the snapshot
    python -m src.data.market_snapshot --push          # store it on the relay
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data import tick_volume  # noqa: E402
from src.data.sessions import is_market_open, market_state, now_karachi  # noqa: E402

PORTAL_HOME = "https://dps.psx.com.pk/"
PORTAL_INDEX = "https://dps.psx.com.pk/indices/"
INDEX_NAME = "KSE100"
INDEX_MEMBERSHIP = "KMIALLSHR"
RELAY_DEFAULT = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"
TOP_N = 3
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# <div class="tabs__panel marketIndices__details" data-name="KSE100"
#      data-date="2026-10-09 11:28:15" data-close="167593.79">
#   <h1 class="marketIndices__price">167,593.79
#     <span class="marketIndices__change change__text--pos"><i ...></i> 151.89 (0.09%)</span>
# On a falling day PSX prints the change signed ("-5.15") AND sets the
# change__text--neg class, so the direction is read from the class and the
# magnitude from the text. The percentage is always printed unsigned.
INDEX_PANEL = re.compile(
    r'<div class="tabs__panel marketIndices__details"\s+data-name="(?P<name>[A-Z0-9]+)"'
    r'[^>]*?data-date="(?P<date>[^"]*)"[^>]*?data-close="(?P<close>[-0-9.]+)"'
    r'[^>]*>.*?<span class="marketIndices__change (?P<sign>change__text--(?:pos|neg))">'
    r'(?:<i[^>]*></i>)?\s*(?P<change>-?[0-9][0-9,]*\.?[0-9]*)\s*'
    r'\((?P<pct>-?[0-9][0-9,]*\.?[0-9]*)%\)', re.S)

# A constituent row: symbol, name, LDCP, current, change, change %, weight,
# index points, volume, shares (m), market cap (m). Values live in data-order.
CONSTITUENT_ROW = re.compile(r"<tr[^>]*>(?P<row>.*?)</tr>", re.S)
CELL = re.compile(r"<td([^>]*)>(.*?)</td>", re.S)
CELL_ORDER = re.compile(r'data-order="([^"]*)"')


def _get(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _number(text: str) -> float:
    return float(str(text).replace(",", ""))


def parse_index(html: str, name: str = INDEX_NAME) -> dict | None:
    """KSE100 points, change and percentage from the portal's index panel."""
    for match in INDEX_PANEL.finditer(html):
        if match.group("name") != name:
            continue
        sign = 1.0 if match.group("sign").endswith("pos") else -1.0
        return {
            "symbol": name,
            "value": _number(match.group("close")),
            "change": sign * abs(_number(match.group("change"))),
            "change_pct": sign * abs(_number(match.group("pct"))),
            "as_of": match.group("date"),
            "source": "dps.psx.com.pk index panel",
        }
    return None


def parse_constituents(html: str) -> list[dict]:
    """One entry per row of the KMIALLSHR constituent table."""
    rows = []
    for block in CONSTITUENT_ROW.finditer(html):
        cells = CELL.findall(block.group("row"))
        if len(cells) < 9:
            continue
        symbol_cell = cells[0]
        symbol = re.search(r'data-order="([A-Z0-9]{2,12})"', symbol_cell[0])
        if not symbol:
            continue
        def ordered(index: int, signed: bool = False) -> float | None:
            found = CELL_ORDER.search(cells[index][0])
            if not found:
                return None
            try:
                value = _number(found.group(1))
            except ValueError:
                return None
            if signed and "change__text--neg" in cells[index][0]:
                value = -abs(value)
            return value

        rows.append({
            "symbol": symbol.group(1),
            "current": ordered(3),
            "change_pct": ordered(5),
            "volume": ordered(8),
        })
    return rows


def volume_leaders(rows: list[dict], top_n: int = TOP_N) -> list[dict]:
    """Top members of the index by the current session volume, highest first.

    Each leader carries its day's percentage change (the exchange prints it
    in the same row, so it is a measurement, not a derivation) and, when a
    genuine tick capture exists, its buy and sell volumes.
    """
    ranked = [row for row in rows if row["volume"] and row["volume"] > 0]
    ranked.sort(key=lambda row: (-row["volume"], row["symbol"]))
    return [{
        "symbol": row["symbol"],
        "volume": int(row["volume"]),
        "price": row["current"],
        "change_pct": row.get("change_pct"),
        "buy_volume": None,
        "sell_volume": None,
        "basis": "current session volume (PSX KMIALLSHR constituents)",
    } for row in ranked[:top_n]]


def fetch_index() -> dict | None:
    return parse_index(_get(PORTAL_HOME), INDEX_NAME)


def fetch_constituents(membership: str = INDEX_MEMBERSHIP) -> list[dict]:
    return parse_constituents(_get(PORTAL_INDEX + membership))


def build_snapshot() -> dict:
    """Assemble the snapshot the phone app renders."""
    now = now_karachi()
    snapshot: dict = {
        "as_of": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "timezone": config.MARKET_TIMEZONE,
        "market_open": is_market_open(now),
        # The phase the app renders (OPEN, BREAK, CLOSED, PRE_OPEN,
        # POST_CLOSE) comes from the one session law, never from the app.
        "market_state": market_state(now),
        "index": None,
        "kmiall_members": 0,
        "top_volume": None,
        "top_volume_basis": None,
        "volume_split_basis": None,
        "notes": [],
    }
    try:
        snapshot["index"] = fetch_index()
        if snapshot["index"] is None:
            snapshot["notes"].append("index panel not found on the portal home page")
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        snapshot["notes"].append(f"index fetch failed: {type(exc).__name__}")

    try:
        rows = fetch_constituents()
        snapshot["kmiall_members"] = len(rows)
        if not rows:
            snapshot["notes"].append(
                f"{INDEX_MEMBERSHIP} constituent table was empty")
            snapshot["volume_split_basis"] = (
                "no leaders, so there is no split to report")
        else:
            leaders = volume_leaders(rows)
            if leaders:
                # Buy/sell split from the broker tick capture, or an explicit
                # "unavailable" with the reason (SO-3: never invented).
                snapshot["volume_split_basis"] = tick_volume.attach_splits(
                    leaders, now.date())
                snapshot["top_volume"] = leaders
                snapshot["top_volume_basis"] = (
                    f"current session volume, top {len(leaders)} of "
                    f"{len(rows)} {INDEX_MEMBERSHIP} members")
            else:
                snapshot["top_volume_basis"] = (
                    "no member of the index has traded yet this session")
    except Exception as exc:  # noqa: BLE001
        snapshot["notes"].append(f"constituents fetch failed: {type(exc).__name__}")
        snapshot["top_volume_basis"] = (
            f"{INDEX_MEMBERSHIP} constituent table unreachable, so the "
            "session volume ranking is unavailable")
        snapshot["volume_split_basis"] = (
            "no volume ranking, so the buy/sell split is unavailable")
    return snapshot


def push_snapshot(snapshot: dict) -> dict:
    import requests

    token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    if not token:
        raise SystemExit("RELAY_ADMIN_TOKEN missing; run from the repo .env or CI")
    url = os.environ.get("RELAY_URL", "").strip().rstrip("/") or RELAY_DEFAULT
    response = requests.post(url + "/market", json=snapshot, timeout=30,
                             headers={"x-admin-token": token})
    body = response.json()
    if response.status_code != 200 or not body.get("ok"):
        raise SystemExit(f"relay refused /market: HTTP {response.status_code} "
                         f"{json.dumps(body)[:160]}")
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KSE100 and volume leaders")
    parser.add_argument("--show", action="store_true", help="print the snapshot")
    parser.add_argument("--push", action="store_true", help="store it on the relay")
    args = parser.parse_args(argv)
    if not (args.show or args.push):
        parser.error("choose --show or --push")

    snapshot = build_snapshot()
    if args.push:
        print(json.dumps(push_snapshot(snapshot), indent=2))
    print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
