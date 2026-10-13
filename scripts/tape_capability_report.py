"""Tape capability report: what the broker snapshot feed can actually support.

Measured on the live wire (2026-10-13, 09:51:53 to 10:28 PKT, 314 symbols,
2045 frames) rather than assumed from the field map, because the difference
decides what a dashboard may claim:

  * the feed is a per-symbol SNAPSHOT cycle, about 30s between two snapshots
    of the same symbol, carrying best bid and ask WITH sizes, the venue's own
    cumulative trade and volume counters, the day's open/high/low/close and
    average, and the last print with its size and time;
  * it is NOT a trade-by-trade tape. A 30s window can hold many prints while
    only the last one's size is visible, so the deduplicated set of visible
    print sizes covered 0.42 of the venue's own volume delta at the median
    (p25 0.23, p75 0.83), and only 0.03 to 0.20 on the busiest names;
  * the side of a print is inferred from where it traded (at the ask means
    buy-side, at the bid sell-side): 64.6% of prints landed exactly on one
    side, and 23.4% of volume increments could not be attributed at all.

Every generator is summed only over increments of the venue's cumulative
volume, never over raw print sizes: the same print is echoed by consecutive
snapshots, so a naive sum double counts it and can even exceed the total
traded (a fund in the 2026-10-13 window summed to 4.41x its own delta).

SO-3 is why this exists: nothing may be presented as order flow that the
venue did not actually publish, and this report is the measurement that a
footprint or order-flow claim has to survive.

Usage (from repo root):
    python scripts/tape_capability_report.py
    python scripts/tape_capability_report.py --file data/feed_capture/capture_20261012.ndjson
    python scripts/tape_capability_report.py --top 12 --json data/tape_capability.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.feed_capture import TICK_FIELDS  # noqa: E402

CAPTURE_DIR = ROOT / "data" / "feed_capture"
KARACHI = timezone(timedelta(hours=5))       # SO-8: Karachi, UTC+5, forever
MARKET = "REG"                               # the regular equity market

#: name -> wire index, so a capture written before the names were added still
#: reads: the 2026-10-12 file carries both, but only the index map is stable.
NAME_TO_INDEX = {name: index for index, name in TICK_FIELDS.items()}

#: The universe this feed is tracked against (src/data/registry.py), used only
#: to report coverage in the summary.
DEFAULT_UNIVERSE = 319


def field(tick: dict, name: str) -> str:
    """One tick field by name, falling back to the wire index."""
    if name in tick and tick[name] is not None:
        return str(tick[name]).strip()
    index = NAME_TO_INDEX.get(name)
    if index is None or str(index) not in tick:
        return ""
    return str(tick[str(index)]).strip()


def number(tick: dict, name: str) -> float:
    """A numeric field, 0.0 when absent or unparseable (never a guess)."""
    try:
        return float(field(tick, name) or 0)
    except ValueError:
        return 0.0


def today_karachi() -> date:
    """The session day this report is being asked about (SO-8)."""
    return datetime.now(KARACHI).date()


def newest_capture(today: date | None = None) -> Path | None:
    """The newest capture file whose own date is not in the future.

    A file's name carries its session date, and this machine has previously
    run with its clock a month ahead, which left a capture_20261211.ndjson
    behind. Picking by name, or by modification time alone, lets that leftover
    win and report an empty session as if it were the latest one, so files
    dated after today are skipped whenever an honest one exists. With nothing
    but future-dated files the newest by time is still returned, so the report
    runs and says what it found rather than refusing.
    """
    files = list(CAPTURE_DIR.glob("capture_*.ndjson"))
    if not files:
        return None
    day = today or today_karachi()

    def session_date(path: Path) -> date | None:
        try:
            return datetime.strptime(path.stem.split("_")[1], "%Y%m%d").date()
        except (IndexError, ValueError):
            return None

    dated = [(session_date(path), path) for path in files]
    honest = [item for item in dated
              if item[0] is not None and item[0] <= day]
    if honest:
        return max(honest)[1]
    return max(dated, key=lambda item: item[1].stat().st_mtime)[1]


def moment(value) -> datetime | None:
    """A capture timestamp, or None when the record did not carry one."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def symbol_rows(path: Path) -> tuple[dict[str, list[tuple]], dict[str, int]]:
    """(per-symbol snapshot rows, frame kind counts) from one capture file."""
    per_symbol: dict[str, list[tuple]] = defaultdict(list)
    frames: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            kind = str(record.get("kind", ""))
            frames[kind] += 1
            if kind != "MKT-FEED":
                continue
            at = moment(record.get("ts"))
            for tick in record.get("ticks", ()):
                symbol = field(tick, "scrip")
                if not symbol or field(tick, "market") != MARKET:
                    continue
                per_symbol[symbol].append((at, tick))
    return per_symbol, frames


def summarise(symbol: str, seq: list[tuple]) -> dict:
    """One symbol's capability row, computed only from venue increments."""
    seq.sort(key=lambda row: (row[0] is None, row[0]))
    volume_delta = number(seq[-1][1], "volume") - number(seq[0][1], "volume")
    trades_delta = number(seq[-1][1], "trades") - number(seq[0][1], "trades")
    visible = 0.0
    steps = 0
    sides = {"buy": 0.0, "sell": 0.0, "unknown": 0.0}
    at_bid = at_ask = neither = 0
    suspended = 0
    for _, tick in seq:
        if field(tick, "status") == "SUS":
            suspended += 1
        last, bid, ask = (field(tick, "last"), field(tick, "bid"),
                          field(tick, "ask"))
        if last and last == ask:
            at_ask += 1
        elif last and last == bid:
            at_bid += 1
        elif last:
            neither += 1
    for (_, previous), (_, current) in zip(seq, seq[1:]):
        step = number(current, "volume") - number(previous, "volume")
        if step <= 0:
            continue
        steps += 1
        visible += number(current, "last_volume")
        last, bid, ask = (field(current, "last"), field(current, "bid"),
                          field(current, "ask"))
        if last and last == ask:
            sides["buy"] += step
        elif last and last == bid:
            sides["sell"] += step
        else:
            sides["unknown"] += step
    gaps = []
    stamps = [at for at, _ in seq if at is not None]
    for first, second in zip(stamps, stamps[1:]):
        gaps.append((second - first).total_seconds())
    spreads = []
    for _, tick in seq:
        bid, ask = number(tick, "bid"), number(tick, "ask")
        if bid > 0 and ask >= bid:
            spreads.append(round(ask - bid, 2))
    return {
        "symbol": symbol,
        "snapshots": len(seq),
        "span_seconds": (round(gaps and sum(gaps), 1) if gaps else 0.0),
        "median_gap_seconds": round(statistics.median(gaps), 1) if gaps else None,
        "volume_delta": volume_delta,
        "trades_delta": trades_delta,
        "visible_new_print_sizes": visible,
        "print_fidelity": (visible / volume_delta) if volume_delta > 0 else None,
        "volume_steps": steps,
        "buy_volume": sides["buy"],
        "sell_volume": sides["sell"],
        "unclassified_volume": sides["unknown"],
        "prints_at_ask": at_ask,
        "prints_at_bid": at_bid,
        "prints_off_quote": neither,
        "distinct_last_prices": len({field(tick, "last") for _, tick in seq
                                     if field(tick, "last")}),
        "median_spread": (round(statistics.median(spreads), 2)
                          if spreads else None),
        "suspended_snapshots": suspended,
    }


def analyse(path: Path, expected_universe: int = DEFAULT_UNIVERSE) -> dict:
    """The whole capability matrix for one banked capture file."""
    per_symbol, frames = symbol_rows(path)
    symbols = [summarise(name, seq) for name, seq in sorted(per_symbol.items())]
    with_volume = [row for row in symbols if row["volume_delta"] > 0]
    fidelities = [row["print_fidelity"] for row in with_volume
                  if row["print_fidelity"] is not None]
    gaps = [row["median_gap_seconds"] for row in symbols
            if row["median_gap_seconds"] is not None]
    buy = sum(row["buy_volume"] for row in symbols)
    sell = sum(row["sell_volume"] for row in symbols)
    unknown = sum(row["unclassified_volume"] for row in symbols)
    traded = buy + sell + unknown

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    def _round(value: float | None) -> float | None:
        return None if value is None else round(value, 3)

    return {
        "file": path.name,
        "analysed_at": datetime.now(KARACHI).isoformat(timespec="seconds"),
        "frames": dict(frames),
        "symbols": len(symbols),
        "expected_universe": expected_universe,
        "universe_coverage": (len(symbols) / expected_universe
                              if expected_universe else None),
        "median_snapshot_gap_seconds": (round(statistics.median(gaps), 1)
                                        if gaps else None),
        "median_print_fidelity": (round(statistics.median(fidelities), 3)
                                  if fidelities else None),
        "print_fidelity_p25": _round(percentile(fidelities, 0.25)),
        "print_fidelity_p75": _round(percentile(fidelities, 0.75)),
        "symbols_with_volume": len(with_volume),
        "volume_traded": traded,
        "buy_volume": buy,
        "sell_volume": sell,
        "unclassified_volume": unknown,
        "unclassified_share": (unknown / traded) if traded else None,
        "volume_steps": sum(row["volume_steps"] for row in symbols),
        "quiet_symbols": sum(1 for row in symbols if row["volume_delta"] <= 0),
        "detail": symbols,
    }


def print_summary(report: dict, top: int) -> None:
    coverage = report["universe_coverage"]
    gap = report["median_snapshot_gap_seconds"]
    print(f"tape capability: {report['file']}  (analysed {report['analysed_at']})")
    print(f"frames: {report['frames']}")
    if coverage is None:
        print(f"symbols seen: {report['symbols']}")
    else:
        print(f"symbols seen: {report['symbols']} of "
              f"{report['expected_universe']} ({coverage * 100:.1f}%)")
    print("median snapshot gap per symbol: "
          + (f"{gap}s" if gap is not None else "n/a"))
    print()
    print("print fidelity (new print sizes / venue volume delta):")
    print(f"  median {report['median_print_fidelity']}  "
          f"p25 {report['print_fidelity_p25']}  p75 {report['print_fidelity_p75']}  "
          f"over {report['symbols_with_volume']} symbols that traded")
    print(f"  incremental volume steps: {report['volume_steps']}")
    print()
    print("volume increments by inferred side:")
    traded = report["volume_traded"] or 0
    for key, label in (("buy_volume", "at the ask (buy-side)"),
                       ("sell_volume", "at the bid (sell-side)"),
                       ("unclassified_volume", "off both quotes (unknown)")):
        share = (report[key] / traded * 100) if traded else 0.0
        print(f"  {label:26s} {report[key]:14,.0f}  {share:5.1f}%")
    print()
    print(f"top {top} symbols by snapshots:")
    print(f"  {'symbol':10s} {'snaps':>6s} {'gap':>6s} {'volume':>12s} "
          f"{'visible':>12s} {'fidelity':>8s} {'prices':>6s} {'spread':>7s}")
    for row in sorted(report["detail"], key=lambda r: -r["snapshots"])[:top]:
        fidelity = (f"{row['print_fidelity']:.2f}"
                    if row["print_fidelity"] is not None else "n/a")
        print(f"  {row['symbol']:10s} {row['snapshots']:6d} "
              f"{str(row['median_gap_seconds']):>6s} "
              f"{row['volume_delta']:12,.0f} "
              f"{row['visible_new_print_sizes']:12,.0f} "
              f"{fidelity:>8s} {row['distinct_last_prices']:6d} "
              f"{str(row['median_spread']):>7s}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=None,
                        help="capture file (default: the newest capture_*.ndjson)")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the full report here")
    parser.add_argument("--top", type=int, default=10,
                        help="how many symbols to print (default 10)")
    parser.add_argument("--expected", type=int, default=DEFAULT_UNIVERSE,
                        help="tracked universe size, for coverage (default 319)")
    args = parser.parse_args(argv)

    path = args.file
    if path is None:
        path = newest_capture()
        if path is None:
            print(f"no capture file under {CAPTURE_DIR}", file=sys.stderr)
            return 2
    if not path.is_file():
        print(f"capture file not found: {path}", file=sys.stderr)
        return 2

    report = analyse(path, args.expected)
    print_summary(report, args.top)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print()
        print(f"report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
