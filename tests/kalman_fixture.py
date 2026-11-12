"""Synthetic tape for the one running law, used by plumbing tests only.

Owner order 2026-11-12: the only strategy is the Kalman Trend with the three
VWAP frames and the hybrid statistical arbitrage and mean reversion model.
Its entry needs a price stretched below the 15 minute frame's VWAP while the
fast frame has turned up, so this tape is shaped for exactly that:

  * minutes 0 to 89 flat at 100.00, which is the mean the price reverts to;
  * minutes 90 to 119 down 0.10 a minute to 97.00, the washout that leaves the
    price stretched below the fifteen minute VWAP;
  * minutes 120 to 129 up 0.12 a minute to 98.20, the turn;
  * from minute 130 up 0.30 a minute, so the owner's +2% target taken at the
    entry near 98.20 is honestly touched inside the capture.

The numbers are a fixture, never a data claim or performance evidence. A
consumer that needs the real trend reads it from its own tape; the plumbing
tests patch the trend filter and say so.
"""
from datetime import timedelta

#: Minutes of flat tape before the washout.
FLAT_UNTIL = 90
#: Minutes the washout lasts.
DROP_MINUTES = 30
#: The first minute the tape turns back up.
TURN_START = FLAT_UNTIL + DROP_MINUTES
#: The first minute of the hard climb that reaches the paper target.
TAIL_START = TURN_START + 10
#: A capture long enough to hold the one hour frame and the whole target run.
FULL_MINUTES = 150


def setup_values(minute: int) -> tuple:
    """(open, high, low, close, volume) for one minute of the fixture."""
    if minute < FLAT_UNTIL:
        price = 100.00
    elif minute < TURN_START:
        price = 100.00 - 0.10 * (minute - FLAT_UNTIL + 1)
    elif minute < TAIL_START:
        price = 97.00 + 0.12 * (minute - TURN_START + 1)
    else:
        price = 98.20 + 0.30 * (minute - TAIL_START + 1)
    return (round(price - 0.02, 4), round(price + 0.04, 4),
            round(price - 0.05, 4), price, 15000)


def setup_rows(scanner, opens, count: int = FULL_MINUTES):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]
