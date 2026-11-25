"""Synthetic tape for the one running law, used by plumbing tests only.

Owner order 2026-11-25: the only strategy is the Kalman Trend with the 5, 15
and 30 minute VWAP frames (owner order 2026-11-19 keeps all three), the
z-score of the price minus VWAP spread, and an entry price closer to that
day's low than to that day's high. This tape is shaped for exactly that: a
gap-up open that sells off, a recovery, a measured 5m dip and a turn back up
into an entry that still stands in the lower half of the day's range.

  * minutes 0 to 9 slide 0.44 a minute from 105.40 to 101.44, the opening
    selloff that puts the day's high at 105.44;
  * minutes 10 to 75 recover 1.90 to 102.90, the uptrend all three Kalman
    frames read;
  * minutes 76 to 105 ease 0.90 to 102.00, the measured 5m dip;
  * minutes 106 to 115 turn up 0.06 a minute to 102.60, the entry close at
    11:28 from the 09:32 open;
  * from minute 116 up 0.30 a minute, so the owner's +2% target taken at the
    entry of 102.60 is honestly touched inside the capture.

At that entry the day's high is 105.44 and its low 100.95, so the entry stands
1.65 above the low and 2.84 below the high: the owner's order of 2026-11-25
holds. The session VWAP is 102.22, below the entry, so the 15 and 30 minute
frames still close above their own VWAP.

The numbers are a fixture, never a data claim or performance evidence. A
consumer that needs the real trend reads it from its own tape; the plumbing
tests patch the trend filter and say so.
"""
from datetime import timedelta

#: Minutes of the opening selloff.
CRASH_END = 10
#: The first minute of the recovery from the selloff.
RISE_START = 10
#: The first minute after the recovery.
RISE_END = 76
#: The first minute after the measured 5m dip.
DIP_END = 106
#: The first minute of the turn back up into the entry.
TURN_START = 106
#: The first minute after the entry close (11:28 from the 09:32 open).
ENTRY_END = 116
#: The first minute of the hard climb that reaches the paper target.
TAIL_START = 116
#: A capture long enough to hold all three frames and the target run.
FULL_MINUTES = 150


def setup_values(minute: int) -> tuple:
    """(open, high, low, close, volume) for one minute of the fixture."""
    if minute < CRASH_END:
        price = 105.40 - 0.44 * minute
    elif minute < RISE_END:
        price = 101.00 + 1.90 * (minute - RISE_START) / (RISE_END - RISE_START)
    elif minute < DIP_END:
        price = 102.90 - 0.90 * (minute - RISE_END + 1) / (DIP_END - RISE_END)
    elif minute < ENTRY_END:
        price = 102.00 + 0.06 * (minute - TURN_START + 1)
    else:
        price = 102.60 + 0.30 * (minute - TAIL_START + 1)
    return (round(price - 0.02, 4), round(price + 0.04, 4),
            round(price - 0.05, 4), price, 15000)


def setup_rows(scanner, opens, count: int = FULL_MINUTES):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]


def entry_view_stub(symbol, rows, session=None, session_rows=None):
    """A legal z-score entry for PLUMBING tests, built from the tape's close.

    Owner order 2026-11-25 put a second market condition on the entry (closer
    to the day's low than to the day's high) on top of the Kalman states and
    the frame VWAPs. A plumbing test is about what the pipeline does with a
    signal, not about whether one tape clears every market gate, so it stubs
    the law's own evaluation here and lets tests/test_kalman_zscore_vwap.py
    hold the gates themselves.
    """
    from src.signals import kalman_zscore_vwap as zlaw

    if not rows:
        return None, "zscore_5m_not_ready"
    close = float(rows[-1].close)
    high = max(float(bar.high) for bar in rows)
    low = min(float(bar.low) for bar in rows)
    # A tape that has not moved is not a setup: the plumbing fixtures carry one
    # moving name and a flat tail, and only the moving name may be called.
    if close <= 0 or (high - low) / close < 0.002:
        return None, "zscore_not_stretched_below_mean"
    frames = {f"{minutes}m": {"close": round(close, 6),
                              "vwap": round(close - 0.10, 6),
                              "kalman_state": 1, "above_vwap": True,
                              "spread_z": -1.8, "bars": 24}
              for minutes in (5, 15, 30)}
    return {
        "rule": zlaw.ZSCORE_VERSION,
        "symbol": symbol,
        "side": "LONG",
        "close": round(close, 6),
        "signal_minutes": 5,
        "z": -1.8,
        "z_min": 1.0,
        "spread": -0.30,
        "spread_mean": 0.0,
        "spread_sigma": 0.17,
        "spread_samples": 20,
        "day": {"high": round(close * 1.03, 6),
                "low": round(close * 0.99, 6),
                "close": round(close, 6),
                "position": 0.33, "side": "LOW", "bars": len(rows)},
        "frames": frames,
    }, "ok"
