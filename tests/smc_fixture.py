"""Synthetic ICT sequence for plumbing tests, never performance evidence."""
from datetime import timedelta


def setup_values(minute: int) -> tuple:
    # Previous high 104 is the untouched upside pool; later local high 100.4
    # is the structure level. Confirmed low 99.8 is swept at minute 39.
    special = {
        4: (101, 104, 100.9, 101.2),
        30: (100.1, 100.2, 99.8, 100.0),
        34: (100.1, 100.4, 100.0, 100.2),
        39: (100.1, 100.15, 99.7, 100.0),
        40: (100.0, 100.85, 99.95, 100.8),
        41: (100.8, 100.9, 100.5, 100.75),
        42: (100.25, 100.65, 100.20, 100.35),
    }
    if minute in special:
        return (*special[minute], 50000 if minute == 40 else 10000)
    if minute > 42:
        price = 100.5 + (minute - 42) * 0.25
        return (price, price + 0.03, price - 0.03, price, 10000)
    return (100.1, 100.2, 100.0, 100.1, 10000)


def setup_rows(scanner, opens, count=43):
    return [scanner.MinuteBar(opens + timedelta(minutes=i), *setup_values(i))
            for i in range(count)]
