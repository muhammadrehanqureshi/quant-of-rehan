"""Per-symbol lock memory for the evening pick (v2.3.2).

WHERE THE DATA COMES FROM: the Sentinel's grind-6 forensics
(backtest_grind6_persymbol.py) measured every KMIALL symbol's own
lock-continuation record across 175 sessions - the table committed in
the Sentinel repo at data/backtest/per_symbol_lock_report.json. A copy
ships in this repo (data/backtest/per_symbol_lock_report.json) and is
best-effort refreshed from the Sentinel's raw URL when a token is
available; a stale or missing file degrades to NO-OP (never breaks a
pick run).

WHAT IT DOES TO THE RANKING (the owner's EOD doctrine: data-weighted,
not bans):
  * proven continuers (win >= 70% on n >= 8 locks - SGPL 79.6%/44,
    KPUS 84.6%/39, BTL 87.0%/23, FIL 92.9%/14): rank BONUS, scaled by
    record strength, capped;
  * chronic fakes (win < 50% on n >= 3, negative net): heavy rank
    DISCOUNT - a one-evening strong tape cannot outvote a record that
    never pays;
  * zero-win fakes (n >= 3, win == 0%): refused the pick entirely -
    0.0% is not a ranking question, it is a verdict;
  * unknown symbols: untouched - no evidence, no adjustment.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "backtest" / "per_symbol_lock_report.json"

# The Sentinel repo's committed copy (public to the owner's account;
# the token is the repo's own Actions token when running on GitHub).
SENTINEL_RAW_URL = (
    "https://raw.githubusercontent.com/"
    "muhammadrehanqureshi/the-sentinel/master/"
    "data/backtest/per_symbol_lock_report.json"
)

# Tuning (mirrors the Sentinel's split; the EOD pick is a next-day
# hold, so the same lock-continuation evidence applies).
PROVEN_MIN_N = 8
PROVEN_MIN_WIN = 0.70
FAKE_MIN_N = 3
FAKE_MAX_WIN = 0.50
BONUS_MAX = 0.15          # +15% rank, at the strongest records
BONUS_PER_WIN_POINT = 0.25  # win-rate points above 70% -> bonus share
FAKE_DISCOUNT = 0.30      # -30% rank for chronic fakes
STALE_DAYS = 10           # older than this = ignore (no stale lessons)


def _age_days(path: Path) -> float | None:
    try:
        return (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 86400.0
    except OSError:
        return None


def refresh_report(token: str | None = None, timeout: float = 15.0) -> bool:
    """Best-effort sync of the per-symbol report from the Sentinel repo.

    Returns True when a fresh copy was written. Never raises: a failed
    refresh leaves the committed copy in place (pick runs offline-safe).
    """
    try:
        req = urllib.request.Request(SENTINEL_RAW_URL)
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict) or not parsed:
            return False
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(parsed), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001 - offline-safe by design
        return False


def load_memory(path: Path | None = None) -> dict[str, dict]:
    """The per-symbol table, or {} when missing/stale/unparseable."""
    p = path or REPORT_PATH
    if not p.exists():
        return {}
    age = _age_days(p)
    if age is not None and age > STALE_DAYS:
        return {}
    try:
        table = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return table if isinstance(table, dict) else {}


def classify(record: dict) -> str:
    """One record -> 'proven' | 'fake' | 'zero_win' | 'neutral'."""
    try:
        n = int(record.get("n", 0))
        win = float(record.get("win_pct", 0.0)) / 100.0
        net = float(record.get("net", 0.0))
    except (TypeError, ValueError):
        return "neutral"
    if n >= PROVEN_MIN_N and win >= PROVEN_MIN_WIN:
        return "proven"
    if n >= FAKE_MIN_N and win == 0.0:
        return "zero_win"
    if n >= FAKE_MIN_N and win < FAKE_MAX_WIN and net < 0.0:
        return "fake"
    return "neutral"


def memory_factor(
    symbol: str, memory: dict[str, dict] | None = None
) -> tuple[float, str]:
    """The ranking adjustment for one symbol: (multiplier, flag).

    multiplier > 1 = bonus (proven continuer), < 1 = discount (fake),
    0 = refuse (zero-win fake), 1 = untouched. Flag is a human-readable
    line for the card; '' when neutral.
    """
    table = memory if memory is not None else load_memory()
    record = table.get(symbol)
    if not record:
        return 1.0, ""
    kind = classify(record)
    n = record.get("n", 0)
    win = record.get("win_pct", 0.0)
    net = record.get("net", 0.0)
    if kind == "proven":
        # Strength = how far past the 70% floor, scaled to the 30-point
        # gap to a perfect record; bonus 5%..15%.
        strength = min(1.0, (win / 100.0 - PROVEN_MIN_WIN) / (1.0 - PROVEN_MIN_WIN))
        bonus = min(BONUS_MAX, 0.05 + 0.10 * strength)
        return 1.0 + bonus, (
            f"lock-memory: {win:.1f}% win over {n} locks "
            f"({net:+.1f}% net) - rank bonus +{bonus * 100:.0f}%"
        )
    if kind == "zero_win":
        return 0.0, f"lock-memory: 0% win over {n} locks - refused"
    if kind == "fake":
        return 1.0 - FAKE_DISCOUNT, (
            f"lock-memory: {win:.1f}% win over {n} locks "
            f"({net:+.1f}% net) - rank discounted {FAKE_DISCOUNT * 100:.0f}%"
        )
    return 1.0, ""
