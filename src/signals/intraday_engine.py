"""Causal KMIALL intraday signal boundary.

The live scanner must use genuine captured intraday bars and return one
winner only. This module is the stable contract used by the scanner.
"""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class IntradaySignal:
    symbol: str
    entry_price: float
    target_price: float
    score: float

    def validate(self):
        if not self.symbol or self.entry_price <= 0:
            raise ValueError("invalid signal")
        if not math.isclose(self.target_price, self.entry_price * 1.02, rel_tol=1e-12):
            raise ValueError("target must be exactly +2% from entry")
