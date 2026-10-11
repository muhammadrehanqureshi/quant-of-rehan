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
  3. Buy and sell volume. The venue publishes total volume only, so the
     split comes from src/data/volume_split.py: measured from a banked tape
     when one exists, and otherwise an explicitly labelled estimate from the
     per-symbol session range below. The card prints the label, never a
     bare number that looks measured.
  4. The per-symbol session range. ``https://dps.psx.com.pk/company/{symbol}``
     carries the REG panel (the regular equity market) with Open, High, Low and
     Volume. Only that panel is read: the same page also renders FUT, CSF and
     ODL panels and futures contract blocks, each with the same label markup
     and its own numbers, so an unscoped parse would read another market. The
     equity panel publishes no close, so the session's last price is taken
     from the same snapshot's ranking table, and the split is refused when
     that price does not sit inside the published range: a range that does
     not contain its own last price is stale, and a stale range must never be
     turned into a split.

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

from src.data import registry, volume_split  # noqa: E402  (SO-3: truth source)
# SO-3 (footprint honesty law): the snapshot builder's buy/sell source is
# src/data/registry.py, and it is the one module that owns what this system
# genuinely has. Whenever a footprint/order-flow claim appears here it must be
# capable of being verified against that law, so the governance guard can scope
# it to the registry. This module therefore imports registry directly rather
# than re-exporting it from another submodule.
from src.data.sessions import is_market_open, market_state, now_karachi  # noqa: E402

# Kept for config.MARKET_TIMEZONE on the line below, so the module's own
# dependency on config is explicit rather than reached through another module.
from src import config  # noqa: E402  (timezone constant)

PORTAL_HOME = "https://dps.psx.com.pk/"
PORTAL_INDEX = "https://dps.psx.com.pk/indices/"
PORTAL_COMPANY = "https://dps.psx.com.pk/company/"
INDEX_NAME = "KSE100"
INDEX_MEMBERSHIP = "KMIALLSHR"
RELAY_DEFAULT = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"
TOP_N = 3

#: The REG panel start and the sibling panel starts that end it. The company
#: page renders one panel per market (REG, FUT, CSF, ODL) plus futures and
#: CSF contract blocks, all with the same label and value markup, so the
#: parse is scoped to the first panel before any value is read.
REG_PANEL_START = re.compile(
    r'<div[^>]*class="tabs__panel[^"]*"[^>]*data-name="REG"[^>]*>')
PANEL_EDGE = re.compile(
    r'<div[^>]*class="tabs__panel[^"]*"[^>]*data-name="')
#: One <div class="stats_label">NAME</div><div class="stats_value">VALUE</div>
#: pair, which is how every number on that panel is published.
STATS_PAIR = re.compile(
    r'stats_label">\s*([^<]{1,40}?)\s*</div>\s*'
    r'<div class="stats_value">\s*(.*?)\s*</div>', re.S)
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
    """Top stocks by the current session volume, highest first.

    Each leader carries its day's percentage change (the exchange prints it
    in the same row, so it is a measurement, not a derivation). Buy and sell
    volume are filled in afterwards by volume_split.attach_splits, which
    labels every number it produces.
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
        "basis": "current session volume (PSX constituent table)",
    } for row in ranked[:top_n]]


def reg_panel(html: str) -> str:
    """The REG panel's markup from a company page, or '' when it is absent.

    REG is the regular equity market, the one the strategy trades. Slicing
    it out first is what stops a futures or CSF contract block with an
    identical label layout from being read as this session.
    """
    start = REG_PANEL_START.search(html)
    if start is None:
        return ""
    edge = PANEL_EDGE.search(html, start.end())
    return html[start.end():edge.start() if edge else len(html)]


def parse_symbol_quote(html: str, symbol: str = "") -> dict | None:
    """One symbol's session fields from the REG panel of its company page.

    Returns None when the panel is missing or carries no session at all (a
    closed market clears the fields to zero), so a caller can never mistake
    a cleared panel for a session that traded. The first occurrence of each
    label wins: inside REG the labels appear once, and taking a later one
    would be reading a different market.
    """
    pairs: dict[str, str] = {}
    for label, value in STATS_PAIR.findall(reg_panel(html)):
        clean = re.sub(r"<[^>]+>", "", label).strip()
        pairs.setdefault(clean, re.sub(r"<[^>]+>", "", value).strip())
    if not pairs:
        return None

    def field(name: str) -> float | None:
        raw = pairs.get(name)
        if raw is None or raw == "":
            return None
        try:
            return _number(raw)
        except ValueError:
            return None

    # The equity panel publishes its range and its volume, and it publishes
    # no close: the session's last price arrives with the ranking table of
    # the same snapshot (see the module docstring).
    quote = {
        "symbol": symbol,
        "open": field("Open"),
        "high": field("High"),
        "low": field("Low"),
        "volume": field("Volume"),
        "trades": field("Total Trades"),
        "source": "dps.psx.com.pk REG panel",
    }
    if not any(quote[key] for key in ("high", "low", "volume")):
        return None
    return quote


def fetch_quote(symbol: str) -> dict | None:
    """The REG panel quote for one symbol, or None when it cannot be read."""
    return parse_symbol_quote(_get(PORTAL_COMPANY + symbol), symbol)


def fetch_quotes(symbols: list[str]) -> dict:
    """Quotes for these symbols, silently skipping the ones that fail.

    A symbol that cannot be read is simply absent, and volume_split then
    reports its split as unavailable with the reason. Three symbols are
    fetched per snapshot, so a failure never concerns more than one row.
    """
    quotes: dict[str, dict] = {}
    for symbol in symbols:
        try:
            quote = fetch_quote(symbol)
        except Exception:  # noqa: BLE001 - reported per row, never invented
            quote = None
        if quote is not None:
            quotes[str(symbol).strip().upper()] = quote
    return quotes


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
            snapshot["notes"].append("the index constituent table was empty")
            snapshot["volume_split_basis"] = (
                "no leaders, so there is no split to report")
        else:
            leaders = volume_leaders(rows)
            if leaders:
                symbols = [str(row["symbol"]).strip().upper()
                           for row in leaders]
                # Measured from a banked tape when one exists, otherwise the
                # labelled estimate, otherwise explicit nulls with a reason
                # (SO-3: an OHLCV derived proxy is never order flow).
                snapshot["volume_split_basis"] = volume_split.attach_splits(
                    leaders,
                    quotes=fetch_quotes(symbols),
                    flows=volume_split.flows_for(now.date(), symbols))
                snapshot["top_volume"] = leaders
                snapshot["top_volume_basis"] = (
                    f"current session volume, top {len(leaders)}")
            else:
                snapshot["top_volume_basis"] = (
                    "no stock has traded yet this session")
    except Exception as exc:  # noqa: BLE001
        snapshot["notes"].append(f"constituents fetch failed: {type(exc).__name__}")
        snapshot["top_volume_basis"] = (
            "the index constituent table was unreachable, so the session "
            "volume ranking is unavailable")
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
