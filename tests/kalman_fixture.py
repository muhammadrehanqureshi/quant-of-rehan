"""Synthetic tape for the one running law, used by plumbing tests only.

Owner order 2026-11-16: the only strategy is the Kalman Trend with the 5, 15
and 30 minute VWAP frames (owner order 2026-11-19 keeps all three) and the
z-score price-VWAP spread. Its entry needs
the 5 minute spread stretched below its trailing mean while the slower frames
remain above VWAP, so this tape is shaped for exactly that:

  * minutes 0 to 89 rise 0.016 a minute from 103.00 to 104.42, the uptrend;
  * minutes 90 to 119 ease 0.04 a minute to 103.22, the measured 5m dip;
  * minutes 120 to 129 turn up 0.02 a minute to 103.42, the entry close;
  * from minute 130 up 0.30 a minute, so the owner's +2% target taken at the
    entry near 103.75 is honestly touched inside the capture.

The day's high is 104.46 and its low 103.17, so the entry at 103.42 stands
0.25 above the low and 1.04 below the high: the owner's order of 2026-11-25
(an entry closer to the day's low than to its day's high) holds on this tape.

The numbers are a fixture, never a data claim or performance evidence. A
consumer that needs the real trend reads it from its own tape; the plumbing
tests patch the trend filter and say so.
"""
from datetime import timedelta

#: Minutes of rising tape before the dip.
FLAT_UNTIL = 90
#: Minutes the dip lasts.
DROP_MINUTES = 30
#: The first minute the tape turns back up.
TURN_START = FLAT_UNTIL + DROP_MINUTES
#: The first minute of the hard climb that reaches the paper target.
TAIL_START = TURN_START + 10
#: A capture long enough to hold all three frames and the target run.
FULL_MINUTES = 150


def setup_values(minute: int) -> tuple:
    """(open, high, low, close, volume) for one minute of the fixture."""
    if minute < FLAT_UNTIL:
        price = 103.00 + 0.016 * minute
    elif minute < TURN_START:
        price = 104.424 - 0.04 * (minute - FLAT_UNTIL + 1)
    elif minute < TAIL_START:
        price = 103.224 + 0.02 * (minute - TURN_START + 1)
    else:
        price = 103.45 + 0.30 * (minute - TAIL_START + 1)
    return (round(price - 0.02, 4), round(price + 0.04, 4),
            round(price - 0.05, 4), price, 15000)


def setup_rows(scanner, opens, count: int = FULL_MINUTES):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]
