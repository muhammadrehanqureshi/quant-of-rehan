"""One door for eligibility: may this symbol be scanned, ranked or traded?

Owner order 2026-10-15: ETFs are excluded from every path, without exception,
and owner order 2026-10-16: that exclusion must be one authoritative service
rather than a name test repeated wherever someone remembers it, must fail
closed when an instrument's classification is uncertain, and must be provable
with tests.

Three halves make one answer, in this order:

  1. the reviewed registry (src/data/etf_registry.json) for the instruments a
     human has actually looked at, carrying its source, effective date and
     review status so it can be audited rather than trusted;
  2. the exchange's own naming convention, because on PSX every exchange
     traded fund's tape symbol ends in ETF, which covers an ETF nobody has
     written down yet;
  3. the equity symbol pattern, which is the only thing that can admit a
     symbol at all.

Anything else is UNKNOWN, and UNKNOWN is refused. That is the fail-closed
rule the owner asked for: an instrument does not become eligible because its
symbol appears in a universe file, a cached list, a replay capture or a
hand-typed argument. The universe is a membership test on top of this, never a
substitute for it.

Every caller that builds a symbol list goes through `screen`: the live
universe loader (scripts/intraday_pipeline.load_kmiall), the recorder's own
subscription (src/data/feed_capture.load_universe) and the historical dataset
(src/backtest/dataset). One function, one answer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

REGISTRY_FILE = ROOT / "src" / "data" / "etf_registry.json"

KIND_EQUITY = "EQUITY"
KIND_ETF = "ETF"
KIND_UNKNOWN = "UNKNOWN"

#: The exchange's ETF naming convention: an exchange traded fund's symbol ends
#: in ETF (MIIETF, MZNPETF, and any successor). Kept as a suffix rather than a
#: list so a new fund is covered before anyone remembers to write it down.
ETF_SUFFIX = "ETF"

#: A PSX equity tape symbol: letters and digits, starting with a letter, up to
#: twelve characters (the longest symbols seen on this feed are six, so this is
#: room, not licence). Anything outside it is UNKNOWN even if a universe file
#: lists it, because an unusable symbol is not a classified instrument.
EQUITY_SYMBOL = re.compile(r"^[A-Z][A-Z0-9]{0,11}$")

#: Registry review states. Only `reviewed` may classify a symbol; anything else
#: (a pending review, a blank) falls through to UNKNOWN and is refused, which
#: is the point: a half finished edit must not quietly admit an instrument.
REVIEWED = "reviewed"


@dataclass(frozen=True)
class Classification:
    """What one symbol is, and why the system believes it."""

    symbol: str
    kind: str
    source: str
    reason: str

    @property
    def is_etf(self) -> bool:
        return self.kind == KIND_ETF

    @property
    def is_equity(self) -> bool:
        return self.kind == KIND_EQUITY

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "kind": self.kind,
                "source": self.source, "reason": self.reason}


@dataclass
class Screen:
    """The result of one eligibility pass, with its own measured coverage."""

    eligible: list[str] = field(default_factory=list)
    excluded: list[Classification] = field(default_factory=list)
    unknown: list[Classification] = field(default_factory=list)
    missing_from_universe: list[str] = field(default_factory=list)

    @property
    def counts(self) -> dict:
        return {"eligible": len(self.eligible), "excluded": len(self.excluded),
                "unknown": len(self.unknown),
                "missing_from_universe": len(self.missing_from_universe)}

    def refusal_for(self, symbol: str) -> Classification | None:
        want = str(symbol).strip().upper()
        for row in self.excluded + self.unknown:
            if row.symbol == want:
                return row
        return None

    def as_dict(self) -> dict:
        return {
            **self.counts,
            "excluded_symbols": [row.as_dict() for row in self.excluded],
            "unknown_symbols": [row.as_dict() for row in self.unknown],
            "note": ("excluded: a classified instrument the project does not trade "
                     "(an ETF). unknown: classification could not be settled, so "
                     "the symbol is refused rather than admitted."),
        }


def load_registry(path: Path | None = None) -> dict:
    """The reviewed registry, or an empty one. A missing file is reported."""
    target = Path(path) if path else REGISTRY_FILE
    if not target.is_file():
        return {"symbols": {}, "missing": str(target)}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # noqa: BLE001 - reported, not hidden
        return {"symbols": {}, "unreadable": f"{type(exc).__name__}"}
    symbols = data.get("symbols")
    return {**data, "symbols": symbols if isinstance(symbols, dict) else {}}


def classification(symbol: str, registry: dict | None = None) -> Classification:
    """What one symbol is. UNKNOWN when the answer cannot be established."""
    raw = str(symbol or "").strip().upper()
    if not raw:
        return Classification(raw, KIND_UNKNOWN, "none", "an empty symbol")
    book = registry if registry is not None else load_registry()
    entry = (book.get("symbols") or {}).get(raw)
    if isinstance(entry, dict):
        status = str(entry.get("review_status") or "").strip().lower()
        kind = str(entry.get("kind") or "").strip().upper()
        if status != REVIEWED:
            return Classification(
                raw, KIND_UNKNOWN, f"registry({status or 'no status'})",
                f"the registry entry for {raw} is not reviewed "
                f"({status or 'no review status'}), so its kind is not settled")
        if kind == KIND_ETF:
            return Classification(
                raw, KIND_ETF, entry.get("source") or "registry",
                entry.get("note") or "a reviewed ETF entry")
        if kind == KIND_EQUITY:
            return Classification(raw, KIND_EQUITY,
                                  entry.get("source") or "registry",
                                  entry.get("note") or "a reviewed equity entry")
        return Classification(
            raw, KIND_UNKNOWN, "registry(unknown kind)",
            f"the registry names {raw} as {kind or 'nothing usable'}")
    if raw.endswith(ETF_SUFFIX):
        return Classification(
            raw, KIND_ETF, "exchange naming convention",
            f"{raw} ends in {ETF_SUFFIX}, which is how PSX names an exchange "
            f"traded fund")
    if EQUITY_SYMBOL.match(raw):
        return Classification(raw, KIND_EQUITY, "PSX equity symbol pattern",
                              "a plain PSX equity symbol, no ETF marker")
    return Classification(raw, KIND_UNKNOWN, "unclassifiable symbol pattern",
                          f"{raw} is not a symbol this feed can carry as an "
                          f"equity, so it is refused")


def is_etf(symbol: str, registry: dict | None = None) -> bool:
    """The narrow question, for callers that only need the ETF test."""
    return classification(symbol, registry).is_etf


def screen(symbols, universe=None, registry: dict | None = None,
           exclude_etfs: bool | None = None) -> Screen:
    """Sort a symbol list into eligible, refused and unknown.

    `universe` is the membership the caller is working from (a set or list); a
    symbol outside it is reported as missing rather than silently eligible, so
    a stale cache that still lists an ETF is refused by the same rule as a
    fresh list.
    """
    if exclude_etfs is None:
        from src import config  # local: config imports nothing from here

        exclude_etfs = bool(config.EXCLUDE_ETFS)
    book = registry if registry is not None else load_registry()
    members = None
    if universe is not None:
        members = {str(sym).strip().upper() for sym in universe}
    result = Screen()
    for symbol in symbols:
        row = classification(symbol, book)
        if members is not None and row.symbol not in members:
            result.missing_from_universe.append(row.symbol)
            continue
        if row.is_etf and exclude_etfs:
            result.excluded.append(row)
        elif row.is_equity:
            result.eligible.append(row.symbol)
        else:
            result.unknown.append(row)
    result.eligible = sorted(dict.fromkeys(result.eligible))
    return result


def coverage(symbols, registry: dict | None = None) -> dict:
    """How much of a symbol list the classification actually settles.

    Reported, never assumed: an exclusion is only as complete as the share of
    the list whose kind is known, and the owner asked for that share to be
    measured rather than claimed.
    """
    book = registry if registry is not None else load_registry()
    rows = [classification(sym, book) for sym in symbols]
    known = [row for row in rows if row.kind != KIND_UNKNOWN]
    return {
        "symbols": len(rows),
        "classified": len(known),
        "classified_share": (len(known) / len(rows)) if rows else None,
        "etf": sum(1 for row in rows if row.kind == KIND_ETF),
        "equity": sum(1 for row in rows if row.kind == KIND_EQUITY),
        "unknown": sum(1 for row in rows if row.kind == KIND_UNKNOWN),
        "unknown_symbols": sorted(row.symbol for row in rows
                                  if row.kind == KIND_UNKNOWN),
        "registry": str(REGISTRY_FILE),
        "registry_symbols": sorted((book.get("symbols") or {})),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="eligibility and ETF exclusion")
    parser.add_argument("--symbols-file",
                        default="src/data/universe_kmiall.json")
    parser.add_argument("--report", action="store_true",
                        help="print what the exclusion settles and what it cannot")
    args = parser.parse_args(argv)

    symbols = json.loads(Path(args.symbols_file).read_text(encoding="utf-8"))
    names = [str(row.get("symbol") or "").strip().upper() for row in symbols
             if str(row.get("symbol") or "").strip()]
    result = screen(names)
    report = {"universe": args.symbols_file, **coverage(names),
              "screen": result.as_dict()}
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
