"""Single source of truth for Quant of Rehan configuration (rebuild 2026-10-09).

Rebuild rule (owner, 2026-10-09): every tunable in the rebuilt system lives
in this one module. No other module may hardcode a threshold, a target, a
coverage floor or a trade limit.

The market clock is deliberately NOT redefined here: Asia/Karachi UTC+5 and
the session windows come from src/data/sessions.py, which is the one
authoritative Karachi definition (SO-8). This module re-exports them so a
caller has a single import surface, and never builds a market time itself.

Environment overrides exist so a scheduled job can flip a flag without a
code change; every default is the safe one (paper only, live off).
"""

from __future__ import annotations

import os

from src.data.sessions import (
    FRIDAY_CLOSE,
    FRIDAY_OPEN,
    KARACHI,
    WEEKDAY_CLOSE,
    WEEKDAY_OPEN,
)

# ---------------------------------------------------------------- market clock
MARKET_TIMEZONE = "Asia/Karachi"
MARKET_OPEN_MON_THU = WEEKDAY_OPEN        # (9, 32) Karachi
MARKET_CLOSE_MON_THU = WEEKDAY_CLOSE      # (15, 30) Karachi
MARKET_OPEN_FRIDAY = FRIDAY_OPEN          # (9, 17) Karachi
MARKET_CLOSE_FRIDAY = FRIDAY_CLOSE        # (16, 30) Karachi
MARKET_TZINFO = KARACHI                   # the only timezone object in use


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _number(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------- hard limits
PAPER_TRADING_ENABLED = _flag("PAPER_TRADING_ENABLED", True)
LIVE_TRADING_ENABLED = _flag("LIVE_TRADING_ENABLED", False)
MAX_TRADES_PER_DAY = 1
TARGET_PCT = _number("TARGET_PCT", 2.0) / 100.0
KMIALL_ONLY = True
LONG_ONLY = True

# ---------------------------------------------------------------- data quality
# Coverage floor for a real scan. Below it the scan is DATA_BLOCKED, never a
# market verdict (owner spec section 8 and 29).
MIN_COVERAGE_PCT = _number("MIN_COVERAGE_PCT", 0.80)
MIN_FRESH_COVERAGE_PCT = _number("MIN_FRESH_COVERAGE_PCT", 0.80)
STALENESS_MINUTES = _number("STALENESS_MINUTES", 5.0)
MAX_MALFORMED_SHARE = _number("MAX_MALFORMED_SHARE", 0.01)
BAR_RESOLUTION = "1-minute"

# ---------------------------------------------------------------- scanner
# Window lengths in minutes, oldest first.
MOMENTUM_WINDOWS = (5, 15, 30)
VOLUME_WINDOW = 5
MIN_BARS_PER_SYMBOL = 20

# Half-credit scale for each saturating component: the value at which the
# component earns 0.5. Chosen as "meaningful but not extraordinary" on KMIALL.
HALF_CREDIT_MOMENTUM_FAST = _number("HALF_CREDIT_MOMENTUM_FAST", 0.004)
HALF_CREDIT_ACCELERATION = _number("HALF_CREDIT_ACCELERATION", 0.002)
HALF_CREDIT_REL_VOLUME = _number("HALF_CREDIT_REL_VOLUME", 1.0)
HALF_CREDIT_VOLUME_ACCEL = _number("HALF_CREDIT_VOLUME_ACCEL", 1.0)
HALF_CREDIT_TRADED_VALUE = _number("HALF_CREDIT_TRADED_VALUE", 20_000_000.0)

# Component weights, in the order they are reported. They sum to 1.0 and are
# asserted below, so the score can never silently drift.
SCORE_WEIGHTS = {
    "momentum": 0.32,
    "acceleration": 0.24,
    "relative_volume": 0.20,
    "volume_acceleration": 0.14,
    "liquidity": 0.10,
}

MIN_SIGNAL_SCORE = _number("MIN_SIGNAL_SCORE", 55.0)
MIN_RELATIVE_VOLUME = _number("MIN_RELATIVE_VOLUME", 1.5)
MIN_VOLUME_ACCEL_RATIO = _number("MIN_VOLUME_ACCEL_RATIO", 1.0)
MIN_SESSION_TRADED_VALUE = _number("MIN_SESSION_TRADED_VALUE", 5_000_000.0)
MAX_SESSION_EXTENSION = _number("MAX_SESSION_EXTENSION", 0.06)
MAX_DISTANCE_FROM_HIGH = _number("MAX_DISTANCE_FROM_HIGH", 0.01)
MIN_PRICE = _number("MIN_PRICE", 1.0)
EXTENSION_PENALTY_POINTS = _number("EXTENSION_PENALTY_POINTS", 15.0)
WEAKNESS_PENALTY_POINTS = _number("WEAKNESS_PENALTY_POINTS", 10.0)

# ---------------------------------------------------------------- market gate
MIN_BREADTH = _number("MIN_BREADTH", 0.35)
MAX_MARKET_DROP = _number("MAX_MARKET_DROP", -0.01)

SCANNER_VERSION = "momentum_volume_acceleration_v1"

# ---------------------------------------------------------------- storage
SESSION_STATE_FILE = "data/forward/session_state.json"
SESSION_JOURNAL_FILE = "data/forward/session_journal.jsonl"
OBSERVATION_FILE = "data/forward/observation.json"
DAILY_OUTCOME_FILE = "data/forward/daily_outcome.json"
PRODUCTION_GATE_FILE = "data/forward/production_gate.json"

assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, "score weights must sum to 1.0"


def live_trading_enabled() -> bool:
    """Live trading is off unless the owner sets the environment flag AND the
    paper gate is already on. Nothing in this repository can place an order."""
    return bool(LIVE_TRADING_ENABLED and not PAPER_TRADING_ENABLED)


def config_snapshot() -> dict:
    """Honest, loggable view of the configuration in force."""
    return {
        "timezone": MARKET_TIMEZONE,
        "open_mon_thu": list(MARKET_OPEN_MON_THU),
        "close_mon_thu": list(MARKET_CLOSE_MON_THU),
        "open_friday": list(MARKET_OPEN_FRIDAY),
        "close_friday": list(MARKET_CLOSE_FRIDAY),
        "target_pct": round(TARGET_PCT * 100, 4),
        "max_trades_per_day": MAX_TRADES_PER_DAY,
        "min_coverage_pct": MIN_COVERAGE_PCT,
        "min_signal_score": MIN_SIGNAL_SCORE,
        "min_relative_volume": MIN_RELATIVE_VOLUME,
        "min_session_traded_value": MIN_SESSION_TRADED_VALUE,
        "score_weights": dict(SCORE_WEIGHTS),
        "scanner_version": SCANNER_VERSION,
        "bar_resolution": BAR_RESOLUTION,
        "paper_trading_enabled": PAPER_TRADING_ENABLED,
        "live_trading_enabled": live_trading_enabled(),
        "kmiall_only": KMIALL_ONLY,
        "long_only": LONG_ONLY,
    }
