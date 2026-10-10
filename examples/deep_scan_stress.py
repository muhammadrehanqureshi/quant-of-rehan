#!/usr/bin/env python3
"""Usage example: drive the core model through market edge cases, fail fast.

The shipped example (examples/scan_once.py) answers "what does the scanner
decide on a normal session?". This one answers the harder question a senior
desk asks first: what does the model do when the tape is NOT normal? It runs
the same real modules the live loop uses (src.signals.contracts for the typed
bar boundary, src.signals.volatility for the regime and edge-case reading) and
asserts a specific, pre-declared outcome for each pathological input:

    volatility spike    a quiet tape that explodes into a violent expansion
    missing data        a sample too thin to say anything
    stale feed          a newest bar that lags the scan instant
    limit lock          one price all session on zero volume, unfillable
    absent volume       bars that cannot support a volume-expansion signal
    gap open            a session that opens far from the previous close
    malformed print     an impossible OHLC bar that must be refused, not read

Two invariants are enforced beyond the readings themselves:

    * every assessment must serialise to STRICT JSON (allow_nan=False), so a
      NaN or infinity can never reach the edge or the phone app as `NaN`;
    * a malformed bar must raise at the boundary, so bad data can never be
      quietly scored.

Nothing here places an order and nothing writes state: it reads, asserts and
prints. It exits non-zero the moment an expectation is not met, which is what
makes it usable as a CI gate.

    python examples/deep_scan_stress.py
    python examples/deep_scan_stress.py --json out.json

Exit codes: 0 every expectation held, 1 an expectation failed (detail printed),
2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import KARACHI  # noqa: E402
from src.signals.contracts import (  # noqa: E402
    MODEL_MODE, Bar, InsufficientCoverage, ScanFault,
)
from src.signals.volatility import (  # noqa: E402
    MIN_BARS_FOR_VOLATILITY, EdgeCase, Regime, assess, hard_block_fault,
)

# A Monday inside the Mon-Thu band, so the clock is never the thing under test.
AS_OF = datetime(2026, 10, 12, 10, 30, tzinfo=KARACHI)

Check = Callable[[], "str | None"]


# ------------------------------------------------------------------- fixtures

def series(symbol: str, closes: Sequence[float], *, spread: float = 0.01,
           volume: float | None = 1000.0, stale_minutes: int = 0) -> list[Bar]:
    """Minute bars from a close series.

    Each bar opens at the previous close, which keeps OHLC legal and makes the
    true range read the real move rather than an artefact of the fixture. The
    last bar lands at AS_OF minus stale_minutes, so staleness is controllable.
    """
    end = AS_OF - timedelta(minutes=stale_minutes)
    bars: list[Bar] = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else closes[0]
        high = max(opened, close) + spread
        low = max(min(opened, close) - spread, 0.01)
        bars.append(Bar(
            symbol=symbol,
            timestamp=end - timedelta(minutes=len(closes) - 1 - index),
            open=opened, high=high, low=low, close=close, volume=volume,
        ))
    return bars


def flat_then_spike(symbol: str) -> list[Bar]:
    """Fifteen quiet bars, then a genuine volatility expansion."""
    closes = [100.0 + 0.01 * i for i in range(15)]
    closes += [100.0 * (1.0 + 0.012 * (i + 1)) for i in range(15)]
    bars = series(symbol, closes)
    # Widen the last bars' range so the expansion shows in the true range.
    widened: list[Bar] = []
    for index, bar in enumerate(bars):
        if index < len(bars) - 10:
            widened.append(bar)
            continue
        pad = 0.6 * (index - (len(bars) - 10) + 1)
        widened.append(Bar(symbol=bar.symbol, timestamp=bar.timestamp,
                           open=bar.open, high=bar.high + pad,
                           low=max(bar.low - pad, 0.01), close=bar.close,
                           volume=bar.volume))
    return widened


# ---------------------------------------------------------------- expectations

def expect(symbol: str, bars: list[Bar], *, regimes: frozenset[Regime] | None,
           edges: frozenset[EdgeCase] = frozenset(),
           allowed_edges: frozenset[EdgeCase] | None = None,
           untradable: bool | None = None,
           previous_close: float | None = None,
           as_of: datetime = AS_OF) -> str | None:
    """Assess one symbol and report the first violated expectation, or None."""
    reading = assess(symbol, bars, as_of=as_of, previous_close=previous_close)
    found = frozenset(reading.edge_cases)

    if regimes is not None and reading.regime not in regimes:
        return (f"regime {reading.regime.value}, expected one of "
                f"{sorted(r.value for r in regimes)}")

    missing = edges - found
    if missing:
        return f"missing edge cases {sorted(e.value for e in missing)}"

    if allowed_edges is not None:
        unexpected = found - allowed_edges
        if unexpected:
            return f"unexpected edge cases {sorted(e.value for e in unexpected)}"

    if untradable is not None and reading.is_untradable is not untradable:
        return f"is_untradable={reading.is_untradable}, expected {untradable}"

    # Strict JSON invariant: a NaN or infinity must never be serialisable out.
    try:
        json.dumps(reading.as_dict(), allow_nan=False)
    except ValueError as exc:
        return f"assessment is not strict JSON: {exc}"
    return None


def check_volatility_spike() -> str | None:
    return expect("SPIKE", flat_then_spike("SPIKE"),
                  regimes=frozenset({Regime.ELEVATED, Regime.EXTREME}),
                  edges=frozenset({EdgeCase.EXTREME_SWING}))


def check_missing_data() -> str | None:
    bars = series("THIN", [100.0, 100.2, 100.1, 100.4])
    if len(bars) >= MIN_BARS_FOR_VOLATILITY:
        return "fixture is not thin"
    return expect("THIN", bars, regimes=frozenset({Regime.UNKNOWN}),
                  edges=frozenset({EdgeCase.THIN_SAMPLE}))


def check_stale_feed() -> str | None:
    bars = series("STALE", [100.0 + 0.01 * i for i in range(30)],
                  stale_minutes=int(config.STALENESS_MINUTES) + 25)
    return expect("STALE", bars, regimes=None,
                  edges=frozenset({EdgeCase.STALE_LAST_BAR}))


def check_limit_lock() -> str | None:
    bars = series("LOCK", [50.0] * 30, spread=0.0, volume=0.0)
    return expect("LOCK", bars, regimes=frozenset({Regime.CALM}),
                  edges=frozenset({EdgeCase.ZERO_RANGE, EdgeCase.LIMIT_LOCKED}),
                  untradable=True)


def check_missing_volume() -> str | None:
    bars = series("NOVOL", [100.0 + 0.01 * i for i in range(30)], volume=None)
    return expect("NOVOL", bars, regimes=None,
                  edges=frozenset({EdgeCase.MISSING_VOLUME}))


def check_gap_open() -> str | None:
    bars = series("GAP", [110.0 + 0.01 * i for i in range(30)])
    return expect("GAP", bars, regimes=None, edges=frozenset({EdgeCase.GAP_UP}),
                  previous_close=100.0)


def check_malformed_bar_refused() -> str | None:
    """An impossible OHLC print must raise at the boundary, never be scored."""
    attempts = {
        "high below low": dict(open=100.0, high=99.0, low=101.0, close=100.0),
        "high below close": dict(open=100.0, high=100.0, low=95.0, close=103.0),
        "zero price": dict(open=0.0, high=1.0, low=0.0, close=1.0),
        "nan price": dict(open=100.0, high=float("nan"), low=99.0, close=100.0),
        "negative volume": dict(open=100.0, high=101.0, low=99.0, close=100.0,
                                volume=-5.0),
    }
    accepted: list[str] = []
    for label, kwargs in attempts.items():
        try:
            Bar(symbol="BAD", timestamp=AS_OF, **kwargs)
        except (ValueError, TypeError):
            continue
        accepted.append(label)
    if accepted:
        return f"malformed bars accepted by the boundary: {accepted}"
    return None


def check_veto_is_typed_and_off_by_default() -> str | None:
    """The veto is a typed fault and stays out of the live path until enabled."""
    reading = assess("LOCK", series("LOCK", [50.0] * 30, spread=0.0, volume=0.0),
                     as_of=AS_OF)
    saved = config.VOLATILITY_VETO_ENABLED
    try:
        config.VOLATILITY_VETO_ENABLED = False
        if hard_block_fault(reading) is not None:
            return "veto fired while disabled"
        config.VOLATILITY_VETO_ENABLED = True
        fault = hard_block_fault(reading)
        if fault is None:
            return "veto did not fire on a limit-locked name while enabled"
        # Callers branch on the class, so the fault must be the specific
        # typed member of the taxonomy, not a bare ScanFault or a ValueError.
        if not isinstance(fault, InsufficientCoverage):
            return (f"veto fault is {type(fault).__name__}, expected "
                    f"InsufficientCoverage")
        if not isinstance(fault, ScanFault):
            return "veto fault is outside the ScanFault taxonomy"
    finally:
        config.VOLATILITY_VETO_ENABLED = saved
    return None


CHECKS: tuple[tuple[str, Check], ...] = (
    ("volatility spike escalates the regime", check_volatility_spike),
    ("thin sample reports UNKNOWN, never a guess", check_missing_data),
    ("stale last bar is flagged", check_stale_feed),
    ("limit lock is untradable", check_limit_lock),
    ("absent volume is flagged", check_missing_volume),
    ("gap open is flagged", check_gap_open),
    ("malformed bar refused at the boundary", check_malformed_bar_refused),
    ("veto is typed and off by default", check_veto_is_typed_and_off_by_default),
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None,
                        help="write the strict-JSON report here as well")
    args = parser.parse_args(argv)

    print(f"schema      : {MODEL_MODE} validation")
    print(f"scan instant: {AS_OF:%Y-%m-%d %H:%M} PKT")
    print(f"thresholds  : calm<={config.ATR_CALM_PCT} elevated<="
          f"{config.ATR_ELEVATED_PCT} extreme<={config.ATR_EXTREME_PCT} "
          f"gap={config.MAX_GAP_PCT} swing={config.MAX_INTRADAY_SWING_PCT}")
    print()

    results: list[dict] = []
    failures = 0
    for name, check in CHECKS:
        detail = check()
        passed = detail is None
        failures += 0 if passed else 1
        print(f"[{'PASS' if passed else 'FAIL'}] {name}"
              + ("" if passed else f": {detail}"))
        results.append({"check": name, "passed": passed, "detail": detail})

    report = {
        "as_of": AS_OF.isoformat(),
        "validation": MODEL_MODE,
        "checks": results,
        "passed": len(results) - failures,
        "failed": failures,
    }
    if args.json is not None:
        # Strict JSON on purpose: the same guarantee the harness asserts above.
        args.json.write_text(json.dumps(report, indent=2, allow_nan=False),
                             encoding="utf-8")
        print(f"\nreport written to {args.json}")

    print(f"\n{report['passed']}/{len(results)} expectations held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
