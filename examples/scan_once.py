#!/usr/bin/env python3
"""Usage example: initialize the system and execute one typed scan.

Rebuild 2026-10-10. Small, complete, and safe to run on a closed market. It
shows the exact call chain a production caller uses:

    config      -> the one configuration surface
    sessions    -> the market clock and the session window
    capture     -> the on-disk bar capture (or a clearly labelled synthetic one)
    contracts   -> bar validation at the ingestion boundary
    scanner     -> the ONE scanner decides
    contracts   -> the decision, typed, with its fault if it has one
    volatility  -> the regime and edge cases of the winner

Nothing here places an order, and nothing here writes to the forward-state
files: `--dry` (the default) only reads and prints.

    python examples/scan_once.py                     # today's real capture
    python examples/scan_once.py --capture PATH      # a specific capture
    python examples/scan_once.py --synthetic         # offline demo data
    python examples/scan_once.py --json out.json     # machine-readable result

Exit codes: 0 clean decision, 1 data failure (typed fault printed), 2 usage.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import (  # noqa: E402
    KARACHI, is_trading_day, now_karachi, open_time,
)
from src.signals import ai_model  # noqa: E402
from src.signals import momentum_scanner as scanner  # noqa: E402
from src.signals import volatility  # noqa: E402
from src.signals.contracts import (  # noqa: E402
    MODEL_MODE, Bar, ScanOutcome, Verdict, validate_bar_rows,
)
from scripts.intraday_pipeline import load_kmiall  # noqa: E402

UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
CAPTURE_DIR = ROOT / "data" / "feed_capture"


def session_instant(moment: datetime) -> datetime:
    """A legal in-session instant for the demo, so the example always runs.

    Outside a live session the scanner would only be allowed to answer
    OUTSIDE_SESSION, which teaches nothing about the decision path, so the
    example pins the clock to a slot that the strategy is allowed to judge and
    says so on stdout.
    """
    day = moment.date()
    if not is_trading_day(day):
        # Not a trading day: use the most recent session instead, so the demo
        # still exercises the decision path rather than the calendar.
        while not is_trading_day(day):
            day -= timedelta(days=1)
    open_h, open_m = open_time(day)
    return (datetime(day.year, day.month, day.day, open_h, open_m,
                     tzinfo=KARACHI) + timedelta(minutes=45))


def synthetic_capture(path: Path, symbols: list[str], as_of: datetime,
                      minutes: int | None = None) -> Path:
    """A labelled fixture: one strong momentum name, the rest flat drift.

    Bars start at the SESSION OPEN, not at the scan instant: the scanner
    legitimately refuses to score a symbol whose bars are mostly outside the
    session, so a fixture that did that would demo a data failure rather than
    the decision path.
    """
    open_h, open_m = open_time(as_of.date())
    start = as_of.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    if minutes is None:
        minutes = max(25, int((as_of - start).total_seconds() // 60))
    def slope_for(minute: int, strong: bool) -> float:
        """A RAMP, not a constant.

        The scanner requires positive momentum acceleration, a positive
        session return under the extension cap, relative volume above its floor
        and volume still accelerating. A flat or uniform fixture fails those
        gates for honest reasons, so the demo fixture is built to satisfy them
        on one name and fail them on the other 318, which is exactly what a
        scan is supposed to distinguish.
        """
        if not strong:
            return 0.00005
        if minute < 15:
            return 0.0002
        if minute < 30:
            return 0.0005
        if minute < 35:
            return 0.0010
        if minute < 40:
            return 0.0016
        return 0.0030

    def volume_for(minute: int, strong: bool) -> float:
        if not strong:
            return 5000.0
        if minute < 30:
            return 5000.0
        return 20000.0 if minute < 40 else 25000.0

    with path.open("w", encoding="utf-8") as handle:
        for index, symbol in enumerate(symbols):
            strong = index == 0
            price, bars = 100.0, []
            for minute in range(minutes):
                price *= 1.0 + slope_for(minute, strong)
                stamp = start + timedelta(minutes=minute)
                bars.append({"t": stamp.strftime("%H:%M"), "o": round(price, 4),
                             "h": round(price * 1.0002, 4),
                             "l": round(price * 0.9998, 4),
                             "c": round(price, 4),
                             "v": volume_for(minute, strong)})
            handle.write(json.dumps({
                "ts": (start + timedelta(minutes=minutes - 1)).isoformat(),
                "symbol": symbol, "bars": bars}) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="one typed scan, end to end")
    parser.add_argument("--capture", type=Path, default=None)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    moment = now_karachi()
    as_of = session_instant(moment)
    symbols = load_kmiall(UNIVERSE_FILE)

    print(f"config      : paper={config.PAPER_TRADING_ENABLED} "
          f"live={config.live_trading_enabled()} "
          f"target={config.TARGET_PCT * 100:.2f}% "
          f"max_trades/day={config.MAX_TRADES_PER_DAY}")
    print(f"contracts   : validation via {MODEL_MODE}")
    print(f"clock       : now {moment:%Y-%m-%d %H:%M} PKT | "
          f"scan instant {as_of:%Y-%m-%d %H:%M} PKT")
    print(f"universe    : {len(symbols)} KMIALL symbols")

    if args.capture is not None:
        path = args.capture
        print(f"capture     : {path}")
    else:
        real = CAPTURE_DIR / f"ohlc_{as_of:%Y%m%d}.ndjson"
        if args.synthetic or not real.is_file():
            if not args.synthetic:
                print(f"capture     : {real.name} not found, using a SYNTHETIC "
                      f"fixture (never a data claim)")
            path = synthetic_capture(
                ROOT / "data" / "feed_capture"
                / f"_synthetic_{as_of:%Y%m%d}.ndjson", symbols, as_of)
            print(f"capture     : SYNTHETIC fixture at {path}")
        else:
            path = real
            print(f"capture     : {path}")

    # 1. the ingestion boundary: validate the raw rows into typed bars
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                rows.append({"symbol": "", "bars": []})
    try:
        typed_bars, ingestion = validate_bar_rows(
            rows, session_day=as_of.date(), as_of=as_of, universe=symbols)
    except Exception as exc:  # noqa: BLE001 - a source fault is an answer
        print(f"ingestion   : REFUSED {type(exc).__name__}: {exc}")
        return 1
    print(f"ingestion   : {ingestion.accepted} bars accepted for "
          f"{ingestion.symbols} symbols, {ingestion.rejected} refused "
          f"({ingestion.rejection_share:.2%})")

    # 2. the trained daily prior, if it is active (it can only ever confirm)
    ai_status = ai_model.status()
    ai_prior = ai_model.live_probabilities() if ai_status.get("active") else None
    print(f"ai prior    : active={ai_status.get('active')} "
          f"holdout_auc={ai_status.get('holdout_auc')} "
          f"symbols={0 if ai_prior is None else len(ai_prior)} "
          f"({ai_status.get('reason')})")

    # 3. the ONE scanner, unchanged
    session = scanner.load_capture(path, symbols, as_of)
    quality = scanner.assess_quality(session, symbols)
    result = scanner.select_one(session, quality, ai_prior, ai_status)

    # 4. the typed contract around the decision
    outcome = ScanOutcome.of(
        result, slot=f"{as_of:%H:%M}", as_of=as_of, universe_size=len(symbols),
        scanner_version=config.SCANNER_VERSION)
    print(f"verdict     : {outcome.summary()}")
    if outcome.quality is not None:
        q = outcome.quality
        print(f"data        : {q.symbols_with_bars}/{q.symbols_expected} "
              f"coverage volume={q.volume_available} "
              f"age={q.data_age_minutes if q.data_age_minutes is None else round(q.data_age_minutes, 1)}min")
    fault = outcome.fault()
    if fault is not None:
        print(f"fault       : {json.dumps(fault.as_dict())}")
    if outcome.is_actionable and outcome.candidate is not None:
        winner = outcome.candidate
        target = round((winner.entry_price or 0.0) * (1 + config.TARGET_PCT), 4)
        print(f"candidate   : {winner.symbol} score {winner.score:.2f} "
              f"entry {winner.entry_price} target {target} "
              f"ai={winner.ai_probability} ({winner.ai_percentile})")

    # 5. volatility regime and edge cases of the names on the board
    readings = {}
    if result.ranked:
        for row in result.ranked[:3]:
            bars = []
            for bar in session.bars.get(row["symbol"], []):
                try:
                    bars.append(Bar(symbol=row["symbol"], timestamp=bar.timestamp,
                                    open=bar.open, high=bar.high, low=bar.low,
                                    close=bar.close, volume=bar.volume))
                except ValueError:
                    continue
            reading = volatility.assess(row["symbol"], bars, as_of)
            readings[row["symbol"]] = reading.as_dict()
            print(f"volatility  : {reading.symbol} regime={reading.regime.value} "
                  f"atr={None if reading.atr_pct is None else round(reading.atr_pct, 5)} "
                  f"edges={[case.value for case in reading.edge_cases]}")

    if args.json:
        args.json.write_text(json.dumps({
            "as_of": as_of.isoformat(),
            "slot": outcome.slot,
            "verdict": outcome.verdict.value,
            "reason": outcome.reason,
            "candidate": (None if outcome.candidate is None else {
                "symbol": outcome.candidate.symbol,
                "score": outcome.candidate.score,
                "entry_price": outcome.candidate.entry_price,
                "ai_probability": outcome.candidate.ai_probability,
                "ai_percentile": outcome.candidate.ai_percentile}),
            "quality": None if outcome.quality is None else outcome.quality.as_dict(),
            "ingestion": {"accepted": ingestion.accepted,
                          "rejected": ingestion.rejected,
                          "by_reason": dict(ingestion.by_reason)},
            "volatility": readings,
            "contract_mode": MODEL_MODE,
        }, indent=2), encoding="utf-8")
        print(f"json        : {args.json}")

    return 0 if outcome.verdict is not Verdict.DATA_BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
