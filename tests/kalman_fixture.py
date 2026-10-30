"""Synthetic Kalman trend for plumbing tests, never performance evidence.

The tape runs flat for the warm-up, then climbs gently until the pipeline's
mid-session anchor (the 10:00 scan prices the last completed gentle bar as the
entry), then climbs faster so the +2% paper target is honestly touched inside
the same 60 minute capture. The filter's slope walks up from zero, the trend
flips UP, the flip's own stop stays inside the maximum-risk band, and the
accelerated tail only moves bars AFTER that entry, so every fixture consumer
(the 43-bar momentum scan, the 4-minute schedule fires and the pipeline's
mid-session scan) still sees the same fresh flip it always did. Consumers read
the old ICT fixture's shape, (op, hi, lo, close, volume) or the MinuteBar list
built from it.
"""
from datetime import timedelta

RISE_START = 20
#: Bars after this minute steepen (below, 0.16 per minute) so the paper
#: target, taken at the mid-session anchor's own close, is actually reached
#: inside the capture the same tests read again at their second fire.
RISE_ACCEL = 43


def setup_values(minute: int) -> tuple:
    """Minutes 0-18 flat at 100.10, then 0.03 up to the anchor bar 42,
    then 0.16 per minute after it."""
    if minute < RISE_START:
        return (100.05, 100.20, 99.95, 100.10, 10000)
    if minute < RISE_ACCEL:
        price = 100.10 + 0.03 * (minute - RISE_START + 1)
    else:
        # 0.03 x 23 gentle bars put the close at 100.79 here; the tail adds
        # 0.16 per minute, so bar 55's high is already past +2% of the
        # anchor entry while the anchor bar itself is unchanged.
        price = 100.79 + 0.16 * (minute - (RISE_ACCEL - 1))
    return (price - 0.02, price + 0.04, price - 0.05, price, 15000)


def setup_rows(scanner, opens, count=43):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]
