"""Signal push helpers: text assembly and dedup (no network in tests)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.signals.signal_push import build_signal_text, UNGRADED_NOTE  # noqa: E402
from src.signals.engine import Signal  # noqa: E402


def sig(sym="OGDC", date="2026-10-05", close=314.62):
    return Signal(
        symbol=sym, name="Oil & Gas Dev", signal_date=date, close=close,
        entry_plan="entry next open, max hold 3 bars",
        tp_price=round(close * 1.02, 2), sl_price=round(close * 0.99, 2),
        regime="weak_bull", regime_ret20=0.031, sweep_low=True,
        fvg_age=1, fvg_low=300.0, fvg_mid=305.0, fvg_size_pct=0.02,
        relvol=1.4, displacement=False, bos_up=True, clv_position=0.42,
        equal_lows=False,
    )


class TestSignalPush(unittest.TestCase):
    def test_text_contains_plan_and_ungraded_note(self):
        text = build_signal_text([sig()], "2026-10-05")
        self.assertIn("BUY OGDC", text)
        self.assertIn("TP 320.91", text)
        self.assertIn("SL 311.47", text)
        self.assertIn("UNGRADED", UNGRADED_NOTE)
        self.assertIn("UNGRADED", text)

    def test_no_signal_day_is_honest(self):
        text = build_signal_text([], "2026-10-05")
        self.assertIn("No signal today", text)
        self.assertIn("UNGRADED", text)

    def test_line_is_ascii_safe(self):
        text = sig().line()
        text.encode("ascii")  # Windows console safety


if __name__ == "__main__":
    unittest.main()
