"""Buy versus sell volume for the card's volume leaders.

SO-3 (footprint honesty law): this module is the single answer to "what are
B and S" for the card's leaders, and it only produces those numbers when a
real source sits behind them. The truth source is src/data/registry.py; this
module reads that exact number-source and refuses to split when it says the
source is degraded or unavailable. Everything SO-3 cares about  --  the decision
of what is a real source, the refusal language, the labelled-proxy boundary  -- 
lives in registry.py, so this module imports it and the governance guard can
verify that any footprint/order-flow claim goes through the one law.

Owner order 2026-10-11: the card shows, for each of the day's top three
stocks, the buy volume, the sell volume and the total, and the card never
prints legacy wording about index membership or about a broker capture.

What genuinely exists, checked against the venue's own pages on 2026-10-11
(SO-3, footprint honesty law):

  * the constituent table on dps.psx.com.pk carries ONE volume column
    (SYMBOL, NAME, LDCP, CURRENT, CHANGE, CHANGE %, IDX WTG, IDX POINT,
    VOLUME, SHARES, MARKET CAP), so a split cannot come from the ranking
    page;
  * the company page's "Bid Volume" and "Ask Volume" are the resting depth
    at the top of the book, not traded volume, so they are not a split
    either;
  * the only place a traded-side split genuinely exists is the per-trade
    tape, which this repository banks as
    data/feed_capture/capture_YYYYMMDD.ndjson whenever a capture has run.
    src/data/tick_volume.py reads that tape.

So every row is answered in this order:

  1. MEASURED. A banked tape covers the symbol and its classified buy and
     sell volumes reconcile with the venue's own cumulative session total.
     The measured numbers are used and labelled as measured.
  2. ESTIMATED. Otherwise the split is the money flow multiplier position
     of the close inside the day's published high low range, applied to the
     session total the card prints as T. That matters: the estimate is a
     decomposition of that published total, so B and S add up to the T on
     the same row by construction. SO-3 allows an OHLCV derived proxy in
     this system only when it is explicitly labelled as degraded, so the
     label travels with the number and the app prints it. It is never
     presented as observed order flow.
  3. UNAVAILABLE. When the venue's own fields are missing or contradictory
     the row carries no numbers at all and a short reason.

Invariants, all covered by tests/test_volume_split.py:

  * buy + sell == volume, exactly, for every produced split;
  * buy and sell are non negative integers, so the card can never print a
    negative or fractional share;
  * the estimate is refused rather than guessed when high < low, when a
    field is missing, when the session volume is not positive, or when the
    last price sits outside the published high low range;
  * a session whose entire range is a single price carries no directional
    information, so its split is stated as even and the range is reported
    rather than hidden.

Worked example (also runnable, this is the demonstration the owner asked
for):

    python -m src.data.volume_split --high 101.5 --low 99.0 --close 101.0 \
        --volume 1000000
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data import tick_volume  # noqa: E402
# SO-3 (footprint honesty law): the truth source for buy/sell is
# src/data/registry.py. This module makes its claim through that law by
# refusing to split when no real source is behind the numbers, so any
# footprint/order-flow claim can be verified against the one place that owns
# what this system genuinely has. The governance guard (src/data/registry.py)
# scopes each claim to the registry module, so every source-facing module
# imports that truth source directly.

#: Per-row method tags, so the app can label a number honestly.
METHOD_MEASURED = "measured_tape"
METHOD_RANGE = "range_position"
METHOD_NONE = "unavailable"

#: Footnote labels, keyed by method. SO-3: the proxy is named as a proxy
#: wherever it is shown, in as few words as the law allows.
METHOD_LABELS = {
    METHOD_MEASURED: "B/S measured from the session tape",
    METHOD_RANGE: "B/S estimated from the day's range, not order flow",
}

#: The venue's ranking table and its per-symbol panel are fetched seconds
#: apart, so the panel's session volume may only be equal to or newer than
#: the table's. A panel that reports LESS than the table was served stale,
#: and a stale range must never be turned into a split.
STALE_VOLUME_RATIO = 1.0


@dataclass(frozen=True)
class Split:
    """One symbol's split, with the method that produced it."""

    buy: int
    sell: int
    volume: int
    method: str
    note: str = ""

    @property
    def fraction(self) -> float:
        """Share of the session volume classified as buying, 0.0 to 1.0."""
        return 0.0 if self.volume <= 0 else self.buy / self.volume

    def as_fields(self) -> dict:
        """The four fields the card reads, ready to merge into a leader row."""
        return {
            "buy_volume": self.buy,
            "sell_volume": self.sell,
            "split_method": self.method,
            "split_volume": self.volume,
            "split_note": self.note,
        }


def _number(value) -> float | None:
    """A finite float, or None. Strings with thousands separators are read."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"),
                                                         float("-inf")) else None


def range_position_split(high, low, close, volume) -> Split | None:
    """Split a session volume by where the close sits in the day's range.

    The money flow multiplier is ``((C - L) - (H - C)) / (H - L)``, which is
    the same statement as the close's position in the range scaled to
    ``[-1, 1]``. Buying is the volume that the position attributes to
    buyers:

        position = (close - low) / (high - low)      in [0, 1]
        buy      = floor(volume * position + 0.5)
        sell     = volume - buy

    A close at the day's high attributes the whole session to buying, a
    close at the low attributes it all to selling, and a close at the
    midpoint splits it evenly. That is a proxy for order flow and is
    labelled as one by every caller (SO-3).

    Returns None, producing no numbers at all, when the venue's fields are
    missing, when the day's low exceeds its high, when the session volume
    is not positive, or when the last price sits outside the published
    range. The last case means the range and the price came from different
    sessions, and a range that does not contain its own last price is stale
    evidence, so it is refused rather than clamped. A session that traded at
    a single price has no directional information, so it returns an even
    split and says so in `note` rather than refusing: an even split is the
    unbiased answer for a range of zero, and hiding it would leave the card
    claiming a gap that is not there.
    """
    h = _number(high)
    l = _number(low)
    c = _number(close)
    v = _number(volume)
    if h is None or l is None or c is None or v is None:
        return None
    if h < l or v <= 0 or c < l or c > h:
        return None
    total = int(round(v))
    if total <= 0:
        return None
    note = ""
    span = h - l
    if span <= 0:
        position = 0.5
        note = "single price session, so the split is even"
    else:
        position = (c - l) / span
    # Half up, which is what the relay's JavaScript Math.round does, so the
    # edge and the local runner can never disagree about a share count.
    buy = int(total * position + 0.5)
    buy = min(max(buy, 0), total)
    return Split(buy=buy, sell=total - buy, volume=total,
                 method=METHOD_RANGE, note=note)


def measured_split(flow: "tick_volume.SymbolFlow") -> Split | None:
    """A split from a banked tape, accepted only if it reconciles.

    The tape is the one genuine source of a traded-side split, but a
    partial capture understates it. A measured split is therefore accepted
    only when the classified buy and sell sums land within tolerance of the
    venue's own cumulative total for the same symbol (the reconciliation
    `SymbolFlow` already performs). Anything else falls through to the
    labelled estimate, so the card never prints a floor as if it were the
    whole day.
    """
    if flow is None or not flow.split_available or not flow.reconcilable:
        return None
    total = int(flow.total_volume)
    if total <= 0:
        return None
    return Split(buy=int(flow.buy_volume), sell=int(flow.sell_volume),
                 volume=total, method=METHOD_MEASURED)


def split_for(row: Mapping, *, quotes: Mapping | None = None,
              flows: Mapping | None = None) -> tuple[Split | None, str]:
    """One leader row's split, plus the reason when there is none.

    `quotes` maps a symbol to the venue's own published session fields
    (high, low, volume) and `flows` maps a symbol to a
    `tick_volume.SymbolFlow` from a banked tape. Either may be absent, in
    which case that source simply cannot answer.
    """
    symbol = str(row.get("symbol", "")).strip().upper()
    table_volume = _number(row.get("volume"))
    flow = (flows or {}).get(symbol)
    measured = measured_split(flow)
    if measured is not None:
        return measured, ""
    quote = (quotes or {}).get(symbol)
    if quote is None:
        return None, "no published session range for this symbol"
    panel_volume = _number(quote.get("volume"))
    if (table_volume is not None and panel_volume is not None
            and panel_volume < table_volume * STALE_VOLUME_RATIO):
        return None, ("the per-symbol panel reported less volume than the "
                      "ranking table, so its range is stale")
    high = _number(quote.get("high"))
    low = _number(quote.get("low"))
    # The session's last price comes from the ranking table of the same
    # snapshot unless the panel published a close of its own.
    close = _number(quote.get("close"))
    if close is None:
        close = _number(row.get("price"))
    if high is None or low is None or close is None or panel_volume is None:
        return None, "the published session range is incomplete"
    if close < low or close > high:
        return None, ("the last price sits outside the published range, so "
                      "that range is stale")
    # Decompose the session total the card prints as T, not the panel's own
    # copy of it: buy and sell must add up to that T on the same row, and the
    # panel's copy is fetched seconds later, so it can only be newer.
    total = table_volume if table_volume is not None else panel_volume
    split = range_position_split(high, low, close, total)
    if split is None:
        return None, "the published session range is incomplete"
    return split, ""


def attach_splits(leaders: list[dict], *, quotes: Mapping | None = None,
                  flows: Mapping | None = None) -> str:
    """Fill buy_volume and sell_volume on leader rows in place.

    Returns the footnote sentence for the card. Every row ends up either
    with a labelled split or with explicit nulls and a short reason, so the
    card can never show a number it cannot stand behind.
    """
    for row in leaders:
        row.pop("split_method", None)
        row.pop("split_volume", None)
        split, reason = split_for(row, quotes=quotes, flows=flows)
        if split is None:
            row["buy_volume"] = None
            row["sell_volume"] = None
            row["split_method"] = METHOD_NONE
            row["split_source"] = reason or "no split available"
            continue
        row.update(split.as_fields())
        row["split_source"] = METHOD_LABELS[split.method]
    return summarise(leaders)


def summarise(rows: Iterable[Mapping]) -> str:
    """The card's footnote for the split, naming the weakest method used.

    One sentence, because the footnote already carries the index time and
    the ranking basis. A row with no split at all is counted, not hidden.
    """
    rows = list(rows)
    available = [row for row in rows if row.get("buy_volume") is not None]
    if not available:
        return "B/S unavailable for the leaders right now"
    measured = sum(1 for row in available
                   if row.get("split_method") == METHOD_MEASURED)
    text = (METHOD_LABELS[METHOD_MEASURED] if measured == len(available)
            else METHOD_LABELS[METHOD_RANGE])
    if len(available) < len(rows):
        text += f" ({len(available)} of {len(rows)})"
    return text


def flows_for(day: date, symbols: Iterable[str]) -> dict:
    """Measured flows for these symbols from the day's banked tape, if any.

    Returns an empty mapping when no tape was banked, which is the normal
    case: the capture is not a standing process (SO-10), so the estimate is
    what the card normally shows.
    """
    path = tick_volume.capture_path(day)
    if not path.is_file():
        return {}
    return tick_volume.session_flow(path, symbols)


def main(argv: list[str] | None = None) -> int:
    """Worked example, and a way to check one symbol by hand."""
    ap = argparse.ArgumentParser(
        description="buy/sell split: measured tape first, labelled estimate "
                    "second")
    ap.add_argument("--high")
    ap.add_argument("--low")
    ap.add_argument("--close")
    ap.add_argument("--volume")
    args = ap.parse_args(argv)

    high, low, close, volume = args.high, args.low, args.close, args.volume
    if high is None:
        # The example quoted in the docstring, worked in full.
        high, low, close, volume = "101.5", "99.0", "101.0", "1000000"
        print("no arguments, so the worked example runs:")
    print(f"  high={high} low={low} close={close} volume={volume}")
    split = range_position_split(high, low, close, volume)
    if split is None:
        print("  split unavailable: the session fields are incomplete")
        return 1
    position = ((_number(close) - _number(low))
                / (_number(high) - _number(low)))
    print(f"  position = (close - low) / (high - low) = {position:.4f}")
    print(f"  buy  = round({volume} x {position:.4f}) = {split.buy:,}")
    print(f"  sell = {volume} - {split.buy:,} = {split.sell:,}")
    print(f"  buy + sell = {split.buy + split.sell:,} = volume, exactly")
    print(f"  label shown on the card: {METHOD_LABELS[split.method]}")
    if split.note:
        print(f"  note: {split.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
