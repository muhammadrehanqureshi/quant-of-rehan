"""Synthetic Kalman trend for plumbing tests, never performance evidence.

The tape runs flat for the warm-up, then climbs gently: the filter's slope
walks up from zero, the trend flips UP and the flip's own stop stays inside
the maximum-risk band, so every fixture consumer (the 43-bar momentum
scan, the 4-minute schedule fires and the pipeline's mid-session scan) can
honestly produce a candidate. Consumers read the old ICT fixture's shape,
(op, hi, lo, close, volume) or the MinuteBar list built from it.
"""
from datetime import timedelta

RISE_START = 20


def setup_values(minute: int) -> tuple:
    """Minutes 0-18 are flat at 100.10; from minute 19 the close climbs 0.03."""
    if minute < RISE_START:
        return (100.05, 100.20, 99.95, 100.10, 10000)
    price = 100.10 + 0.03 * (minute - RISE_START + 1)
    return (price - 0.02, price + 0.04, price - 0.05, price, 15000)


def setup_rows(scanner, opens, count=43):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]
