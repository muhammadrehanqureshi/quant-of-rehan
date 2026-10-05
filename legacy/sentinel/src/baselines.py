"""
PSX KMIALL BOT
Cross-day volume baselines.

Why
---
relative_volume_1m in the dataset builder compares volume against an
expanding *intraday* baseline: the last N minutes of the same session.
On the first hour of trading that baseline is nearly empty, so
"relative volume" measures almost nothing, and a stock that trades 5x
its usual size looks identical to one trading its usual size.

This module maintains, per symbol, an exponentially-updated baseline of
total daily volume and total daily trades, persisted across sessions:

    data/volume_baselines.json
    {"LUCK": {"volume": 12_500_000, "trades": 8_400, "days": 21,
              "updated": "2026-09-04"}, ...}

At each session close, the live runner records that day's totals. The
value stored is an exponential moving average with alpha = 0.25 (a new
day shifts the baseline by a quarter), which adapts to regime changes
within roughly a week while staying stable against one odd session.

The feature engine consumes it as baseline_volume_ratio = today's
running volume / baseline daily volume, expected to grow through the
day (0.1 in the morning, ~1.0 at close). It is the honest way to say
"this stock is trading unusually heavily today" from cumulative feeds.

Usage
-----
    from baselines import VolumeBaselines

    baselines = VolumeBaselines()
    baselines.record_session("2026-09-04", {sym: (volume, trades)})
    ratio = baselines.baseline_volume_ratio("LUCK", volume_so_far_today)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from psx_core import paths

# Exponential update weight for one new session. 0.25 = the baseline is
# ~63% a blend of the last 5 sessions, ~87% the last 10.
ALPHA = 0.25

# Below this many observed days the baseline is marked low-confidence and
# the feature engine treats the ratio as missing rather than noise.
MIN_DAYS = 3


class VolumeBaselines:
    """Per-symbol EMA of daily total volume and trades."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (paths.DATA_DIR / "volume_baselines.json")
        self._state: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, indent=2), encoding="utf-8"
        )

    # -- Recording -----------------------------------------------------------

    def record_session(
        self,
        session_date: str,
        totals: dict[str, tuple[float, float]],
    ) -> None:
        """
        Fold one session's per-symbol (total_volume, total_trades) into
        the EMA and persist.

        A symbol seen for the first time starts its baseline at that
        day's value (days=1). Skipped days simply don't update - the EMA
        keeps its last value.
        """
        for symbol, (volume, trades) in totals.items():
            if volume is None or trades is None or volume < 0:
                continue
            entry = self._state.get(symbol)
            if entry is None:
                self._state[symbol] = {
                    "volume": float(volume),
                    "trades": float(trades),
                    "days": 1,
                    "updated": session_date,
                }
                continue

            old_volume = float(entry.get("volume", 0.0)) or float(volume)
            old_trades = float(entry.get("trades", 0.0)) or float(trades)
            self._state[symbol] = {
                "volume": (1 - ALPHA) * old_volume + ALPHA * float(volume),
                "trades": (1 - ALPHA) * old_trades + ALPHA * float(trades),
                "days": int(entry.get("days", 0)) + 1,
                "updated": session_date,
            }
        self._save()

    # -- Reading ---------------------------------------------------------------

    def baseline_volume(self, symbol: str) -> float | None:
        entry = self._state.get(symbol)
        if entry is None:
            return None
        volume = entry.get("volume")
        if volume is None or volume <= 0:
            return None
        return float(volume)

    def baseline_days(self, symbol: str) -> int:
        entry = self._state.get(symbol)
        return int(entry.get("days", 0)) if entry else 0

    def is_reliable(self, symbol: str) -> bool:
        return self.baseline_days(symbol) >= MIN_DAYS

    def baseline_volume_ratio(
        self, symbol: str, volume_so_far: float
    ) -> float | None:
        """
        Volume accumulated so far today vs. the baseline full-day volume.

        None when there is no usable baseline (new symbol, zero baseline,
        or fewer than MIN_DAYS of history) - the feature layer treats
        None as missing, never as 1.0.
        """
        if volume_so_far is None or volume_so_far < 0:
            return None
        if not self.is_reliable(symbol):
            return None
        base = self.baseline_volume(symbol)
        if base is None:
            return None
        return float(volume_so_far) / base
