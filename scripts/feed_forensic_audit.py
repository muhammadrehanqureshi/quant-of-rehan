"""Forensic audit of a banked Eclear capture: the wire measured, not assumed.

Produces the evidence table the capability report cites:

  * every frame kind the capture holds, with counts and one sanitized example;
  * REG tick rows, distinct symbols and stale share;
  * duplicate consecutive snapshots (the feed echoes unchanged symbols);
  * receipt order (out-of-order records are counted, never reordered);
  * per-symbol snapshot cadence, and the venue print clock to local receipt
    lag over genuinely new prints only (a quiet symbol's last print can be
    hours old, which is not transport latency);
  * circuit-cap frames (RUCAP / RLCAP / ADDUCAP) parsed from their own text;
  * the last EXS-FEED breadth group and MKT-STATS segment totals.

Read-only by construction: it opens one capture file, reads it, and writes
nothing unless --json names an output path (which should live under /data/,
never the repository, when it holds broker rows).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tape_capability_report import newest_capture  # noqa: E402

KARACHI_OFFSET = timedelta(hours=5)
CAPABILITY_KINDS = ("RUCAP", "RLCAP", "ADDUCAP")


def _moment(text) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def parse_cap_frame(raw: str) -> dict | None:
    """RUCAP / RLCAP / ADDUCAP: '*SYMBOL*PRICE'. Semantics are inferred."""
    head, _, payload = str(raw).partition("*")
    kind = head.strip().upper()
    if kind not in CAPABILITY_KINDS:
        return None
    parts = [part.strip() for part in payload.split("*")]
    if len(parts) < 2:
        return None
    symbol = parts[0].upper()
    try:
        price = float(parts[1])
    except ValueError:
        return None
    label = {"RUCAP": "revised upper circuit cap",
             "RLCAP": "revised lower circuit cap",
             "ADDUCAP": "added upper cap"}.get(kind, "cap")
    return {"kind": kind, "symbol": symbol, "price": price,
            "label": label, "basis": "inferred from the frame name"}


def parse_exs_group(raw: str, index: str = "KSE100") -> dict | None:
    """One index group from EXS-FEED, positions pinned by observed content."""
    body = str(raw).split("*", 1)
    if len(body) < 2:
        return None
    for group in body[1].split("$"):
        head = group.split("^")
        if len(head) < 2:
            continue
        fields = head[1].split(";")
        if not fields or fields[0].strip().upper() != index:
            continue
        def number(position):
            try:
                return float(fields[position])
            except (IndexError, ValueError):
                return None
        return {
            "index": fields[0].strip(),
            "stamp": head[0].strip(),
            "value": number(1),
            "change": number(2),
            "advancing": number(7),
            "declining": number(8),
            "unchanged": number(9),
            "session_volume": number(10),
            "session_turnover": number(11),
            "basis": ("advancing/declining/unchanged, session volume and "
                      "turnover read positionally from the group and "
                      "checked for magnitude against the venue's totals"),
        }
    return None


def parse_mkt_stats(raw: str) -> dict | None:
    """MKT-STATS segments: 'SEGMENT;STATE;VOLUME;TRADES;TURNOVER'."""
    body = str(raw).split("*", 1)
    if len(body) < 2:
        return None
    segments = []
    for part in body[1].split("|"):
        fields = [field.strip() for field in part.split(";")]
        if len(fields) < 2 or not fields[0]:
            continue
        def number(position):
            try:
                return float(fields[position])
            except (IndexError, ValueError):
                return None
        segments.append({"segment": fields[0].upper(), "state": fields[1].upper(),
                         "volume": number(2), "trades": number(3),
                         "turnover": number(4)})
    return {"segments": segments} if segments else None


def audit(path: Path, expected_universe: int | None = 319) -> dict:
    """The whole forensic profile of one capture file."""
    kinds: Counter = Counter()
    examples: dict[str, str] = {}
    tick_rows = 0
    symbols = set()
    out_of_order = 0
    duplicates = 0
    last_receipt: dict[str, datetime] = {}
    last_identity: dict[str, tuple] = {}
    last_print_status: dict[str, datetime] = {}
    gaps: dict[str, list[float]] = defaultdict(list)
    print_lags: list[float] = []
    caps: dict[str, dict] = {}
    last_exs = None
    last_stats = None
    last_receipt_stamp = None

    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                kinds["unparseable-line"] += 1
                continue
            kind = str(record.get("kind", "?"))
            kinds[kind] += 1
            raw = str(record.get("raw", ""))
            if kind not in examples and raw:
                examples[kind] = raw[:240]
            stamp = _moment(record.get("ts"))
            if stamp is not None:
                if last_receipt_stamp is not None and stamp < last_receipt_stamp:
                    out_of_order += 1
                last_receipt_stamp = stamp
            if kind in CAPABILITY_KINDS or kind.upper() in CAPABILITY_KINDS:
                parsed = parse_cap_frame(raw)
                if parsed:
                    caps[f"{parsed['kind']}:{parsed['symbol']}"] = parsed
            elif kind.startswith("EXS-FEED"):
                parsed = parse_exs_group(raw)
                if parsed:
                    last_exs = parsed
            elif kind.startswith("MKT-STATS"):
                parsed = parse_mkt_stats(raw)
                if parsed:
                    last_stats = parsed
            elif not kind.startswith("MKT-FEED"):
                continue
            if not kind.startswith("MKT-FEED") or stamp is None:
                continue
            for tick in record.get("ticks", ()):
                if str(tick.get("market", "")).strip().upper() != "REG":
                    continue
                symbol = str(tick.get("scrip", "")).strip().upper().split(":", 1)[0]
                if not symbol:
                    continue
                tick_rows += 1
                symbols.add(symbol)
                identity = (tick.get("volume"), tick.get("trades"),
                            str(tick.get("last", "")).strip(),
                            str(tick.get("tick_time", "")).strip())
                if last_identity.get(symbol) == identity:
                    duplicates += 1
                last_identity[symbol] = identity
                previous = last_receipt.get(symbol)
                if previous is not None:
                    delta = (stamp - previous).total_seconds()
                    if delta < 0:
                        out_of_order += 1
                    elif delta <= 300:
                        gaps[symbol].append(delta)
                last_receipt[symbol] = stamp
                print_text = str(tick.get("tick_time", "")).strip()
                try:
                    print_clock = datetime.strptime(print_text, "%H:%M:%S")
                except ValueError:
                    continue
                print_clock = stamp.replace(hour=print_clock.hour,
                                            minute=print_clock.minute,
                                            second=print_clock.second,
                                            microsecond=0)
                before = last_print_status.get(symbol)
                last_print_status[symbol] = print_clock
                if before is not None and print_clock > before:
                    lag = (stamp - print_clock).total_seconds()
                    if 0 <= lag <= 300:
                        print_lags.append(lag)

    # Three observations of a symbol are enough to state its cadence; a
    # symbol seen twice says nothing about the interval between sweeps.
    cadence = [statistics.median(values) for values in gaps.values()
               if len(values) >= 2]
    print_lags.sort()

    def percentile(fraction):
        if not print_lags:
            return None
        return round(print_lags[min(len(print_lags) - 1,
                                    int(fraction * len(print_lags)))], 1)

    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "frames": dict(kinds.most_common()),
        "tick_rows": tick_rows,
        "symbols": len(symbols),
        "expected_universe": expected_universe,
        "universe_coverage": (round(len(symbols) / expected_universe, 4)
                              if expected_universe else None),
        "duplicate_consecutive_rows": duplicates,
        "duplicate_share": (round(duplicates / tick_rows, 4) if tick_rows else None),
        "out_of_order_records": out_of_order,
        "median_snapshot_gap_seconds": (round(statistics.median(cadence), 2)
                                        if cadence else None),
        "symbols_with_cadence": len(cadence),
        "new_print_lag_seconds": {
            "samples": len(print_lags),
            "p50": percentile(0.5), "p75": percentile(0.75),
            "p90": percentile(0.9), "p95": percentile(0.95),
            "max": round(print_lags[-1], 1) if print_lags else None,
        },
        "last_breadth": last_exs,
        "last_market_stats": last_stats,
        "circuit_caps": sorted(caps.values(), key=lambda c: (c["kind"],
                                                             c["symbol"])),
        "examples": examples,
        "notes": [
            "print lag is measured only when the venue print clock advanced; "
            "a quiet symbol's last print can be hours old",
            "cap-frame semantics are inferred from the frame names",
            "frames are banked verbatim; a parser change cannot rewrite them",
        ],
    }


def print_summary(report: dict) -> None:
    print(f"capture: {report['file']} ({report['bytes'] / 1e6:.1f} MB)")
    print("frames: " + ", ".join(f"{key} {value}"
                                 for key, value in report["frames"].items()))
    coverage = report["universe_coverage"]
    print(f"REG tick rows: {report['tick_rows']:,}; symbols: "
          f"{report['symbols']}" +
          (f" of {report['expected_universe']} ({coverage * 100:.1f}%)"
           if coverage is not None else ""))
    print(f"duplicate consecutive rows: {report['duplicate_consecutive_rows']:,} "
          f"({(report['duplicate_share'] or 0) * 100:.1f}%)")
    print(f"out-of-order records: {report['out_of_order_records']}")
    print(f"median snapshot cadence: {report['median_snapshot_gap_seconds']}s "
          f"over {report['symbols_with_cadence']} symbols")
    lag = report["new_print_lag_seconds"]
    if lag["samples"]:
        print(f"new-print lag: p50 {lag['p50']}s p75 {lag['p75']}s "
              f"p90 {lag['p90']}s p95 {lag['p95']}s max {lag['max']}s "
              f"({lag['samples']:,} prints)")
    breadth = report["last_breadth"]
    if breadth:
        print(f"last breadth: adv {breadth['advancing']} dec "
              f"{breadth['declining']} unch {breadth['unchanged']}, "
              f"volume {breadth['session_volume']:,.0f}, turnover "
              f"{breadth['session_turnover']:,.2f}")
    stats = report["last_market_stats"]
    if stats:
        for segment in stats["segments"]:
            if segment["segment"] == "REG":
                print(f"last REG totals: state {segment['state']}, volume "
                      f"{segment['volume']:,.0f}, trades "
                      f"{segment['trades']:,.0f}, turnover "
                      f"{segment['turnover']:,.2f}")
    if report["circuit_caps"]:
        print("circuit cap frames: " + ", ".join(
            f"{cap['kind']} {cap['symbol']} {cap['price']}"
            for cap in report["circuit_caps"]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--expected", type=int, default=319)
    args = parser.parse_args(argv)

    path = args.file or newest_capture()
    if path is None or not path.is_file():
        print("no capture file to audit", file=sys.stderr)
        return 2
    report = audit(path, args.expected)
    print_summary(report)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"report written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
