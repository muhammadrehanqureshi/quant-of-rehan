"""Buy versus sell volume for the card's volume leaders.

The card carries B and S only when the relay measured the pair at the wire
and tagged it ``quote_rule``. A range position, a tape slice or a price move
is never turned into a side. Without that measured pair the row carries null
B and S, the whole known total as U, and a short reason.

Owner order 2026-11-06: "BUYING and SELLING have to be correct, always."
The rule that follows is strict: an unmeasured share is not distributed to
either side, and a positive U is never hidden.

The one measured path is a pair already on the row. ``attach_splits`` copies
it through, computes the unclassified remainder, and leaves ``flow_complete``
true only when B + S equals the row's total. Every other row is explicit
unavailable, with U equal to its total.

The legacy method tags below exist only so an old range or tape pair can be
recognised and refused. They are not producers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from src.data import tick_volume
from src.data.registry import Availability, availability

#: Per-row method tags, so the app can label a number honestly.
METHOD_MEASURED = "measured_tape"
METHOD_TAPE_COUNTS = "tape_counts"
METHOD_RANGE = "range_position"
METHOD_WIRE = "quote_rule"
METHOD_NONE = "unavailable"

#: Footnote labels, keyed by method. The wire label is the only one a live
#: producer can set; the rest remain for recognising retired rows.
METHOD_LABELS = {
    METHOD_MEASURED: "B/S measured from the session tape",
    METHOD_TAPE_COUNTS: ("B/S counted from the session's own trade tape, "
                         "covering part of the session"),
    METHOD_RANGE: "B/S estimated from the day's range, not order flow",
    METHOD_WIRE: "B/S measured at the wire from the broker feed",
}

#: Weakest first. A live row can only carry METHOD_WIRE, so this ordering
#: matters only if an old row is ever shown beside a measured one.
METHOD_STRENGTH_ORDER = (METHOD_RANGE, METHOD_TAPE_COUNTS, METHOD_MEASURED,
                         METHOD_WIRE)

#: The registry's footprint verdict. It is UNAVAILABLE, so no derived range
#: or tape pair may stand as B/S; only the relay's measured pair is copied.
FOOTPRINT = availability("footprint")


@dataclass(frozen=True)
class Split:
    """One symbol's measured pair, with the method that produced it."""

    buy: int
    sell: int
    volume: int
    method: str
    note: str = ""

    @property
    def fraction(self) -> float:
        """Share of the classified volume that is buying, 0.0 to 1.0."""
        return 0.0 if self.volume <= 0 else self.buy / self.volume

    def as_fields(self) -> dict:
        """The fields the card reads, ready to merge into a leader row."""
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


def split_for(row: Mapping, *, quotes: Mapping | None = None,
              flows: Mapping | None = None) -> tuple[Split | None, str]:
    """One leader row's measured pair, plus the reason when there is none.

    A B or S number is accepted only when the row already carries the relay's
    own measured pair, tagged METHOD_WIRE. The published range, a banked tape
    and a price move are deliberately not consulted: none proves the side of
    the venue's whole-session counter.
    """
    if str(row.get("split_method") or "") != METHOD_WIRE:
        if FOOTPRINT is Availability.UNAVAILABLE:
            return None, ("footprint is UNAVAILABLE and the row has no "
                          "measured order-flow pair")
        return None, "no measured order-flow pair; the total is unclassified"
    total = _number(row.get("volume"))
    buy = _number(row.get("buy_volume"))
    sell = _number(row.get("sell_volume"))
    if buy is None or sell is None:
        return None, "the measured pair is missing a side"
    b, s = int(round(buy)), int(round(sell))
    if b < 0 or s < 0:
        return None, "the measured pair is negative"
    if total is not None and b + s > int(round(total)):
        return None, "the measured pair exceeds the venue total"
    return Split(buy=b, sell=s, volume=b + s, method=METHOD_WIRE,
                 note="measured at the wire"), ""


def attach_splits(leaders: list[dict], *, quotes: Mapping | None = None,
                  flows: Mapping | None = None) -> str:
    """Fill B, S and U on leader rows in place.

    A measured pair is copied through and U is the rest of the row's total.
    Every other row gets explicit null B/S, split_method unavailable, and U
    equal to the whole total. The card therefore never prints a guessed side
    or hides an unclassified share.
    """
    for row in leaders:
        row.pop("split_volume", None)
        split, reason = split_for(row, quotes=quotes, flows=flows)
        total = _number(row.get("volume"))
        total_int = max(0, int(round(total))) if total is not None else None
        if split is None:
            row["buy_volume"] = None
            row["sell_volume"] = None
            row["classified_volume"] = None
            row["unclassified_volume"] = total_int
            row["flow_complete"] = (None if total_int is None
                                    else total_int == 0)
            row["split_method"] = METHOD_NONE
            row["split_source"] = reason or "no split available"
            continue
        row.update(split.as_fields())
        row["split_source"] = METHOD_LABELS[split.method]
        row["classified_volume"] = split.buy + split.sell
        row["unclassified_volume"] = (
            max(0, total_int - row["classified_volume"])
            if total_int is not None else None)
        row["flow_complete"] = (None if row["unclassified_volume"] is None
                                else row["unclassified_volume"] == 0)
    return summarise(leaders)


def summarise(rows: Iterable[Mapping]) -> str:
    """One honest sentence for the card footnote, or the unavailable line."""
    rows = list(rows)
    available = [row for row in rows if row.get("buy_volume") is not None]
    if not available:
        return "B/S unavailable: the wire has not measured a pair"
    present = {str(row.get("split_method") or METHOD_NONE)
               for row in available}
    chosen = METHOD_MEASURED
    for method in METHOD_STRENGTH_ORDER:
        if method in present:
            chosen = method
            break
    text = METHOD_LABELS.get(chosen, METHOD_LABELS[METHOD_MEASURED])
    if len(available) < len(rows):
        text += f" ({len(available)} of {len(rows)})"
    return text


def flows_for(day: date, symbols: Iterable[str]) -> dict:
    """Diagnostic tape flows for these symbols, when a capture exists.

    B/S does not read this mapping: a tape slice cannot prove the venue's
    whole-session pair. It remains for the capture diagnostics that call it.
    """
    path = tick_volume.capture_path(day)
    if not path.is_file():
        return {}
    return tick_volume.session_flow(path, symbols)
