"""Tests for the data-source capability registry (footprint honesty layer)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.registry import (  # noqa: E402
    Availability,
    REGISTRY,
    availability,
    degraded_keys,
    get,
    require,
    unavailable_keys,
)


class TestRegistry(unittest.TestCase):
    def test_footprint_is_unavailable(self):
        """SO-3: the system must admit footprint data does not exist."""
        self.assertIs(availability("footprint"), Availability.UNAVAILABLE)

    def test_daily_ohlcv_is_available(self):
        self.assertIs(availability("daily_ohlcv"), Availability.AVAILABLE)

    def test_intraday_is_degraded_and_labeled(self):
        self.assertIs(availability("intraday_ohlcv"), Availability.DEGRADED)
        self.assertIn("captured forward", get("intraday_ohlcv").detail.lower())

    def test_require_refuses_unavailable(self):
        with self.assertRaises(RuntimeError) as ctx:
            require("footprint")
        self.assertIn("UNAVAILABLE", str(ctx.exception))

    def test_require_passes_available(self):
        ds = require("daily_ohlcv")
        self.assertEqual(ds.key, "daily_ohlcv")

    def test_unavailable_keys_contain_footprint(self):
        self.assertIn("footprint", unavailable_keys())

    def test_degraded_keys_are_labeled(self):
        self.assertIn("intraday_ohlcv", degraded_keys())

    def test_every_entry_carries_honest_detail(self):
        for key, ds in REGISTRY.items():
            self.assertTrue(
                ds.detail and len(ds.detail) > 20,
                f"{key} must carry a real status note, not a stub",
            )

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            availability("nonexistent_source")


if __name__ == "__main__":
    unittest.main()
