"""
Shared fixtures.

Nothing here touches the network. The collector's poll path is exercised
against a fake requests.Session, and the parsers against the HTML that was
archived in data/ when the feed was reverse-engineered, so the suite runs
identically whether or not PSX is open.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    """
    Redirect psx_core.storage at a temporary directory.

    storage.day_file() reads paths.SNAPSHOT_DIR at call time, so patching the
    module attribute is enough and no test ever writes into data/snapshots.
    """
    from psx_core import paths

    directory = tmp_path / "snapshots"
    directory.mkdir()
    monkeypatch.setattr(paths, "SNAPSHOT_DIR", directory)
    return directory


@pytest.fixture(autouse=True)
def quarantine_writers(tmp_path, monkeypatch):
    """
    No test may ever write production files.

    2026-09-20: three suites were found regenerating STATUS.md,
    SIGNALS.md, corporate_actions.json and gate_refit.json in the REAL
    tree during a plain pytest run (fixtures isolated most paths but a
    few writer calls bypassed them). This autouse fixture points every
    writer module's module-level path constant at a throwaway directory
    BEFORE any test code runs. Read-paths for archived fixtures
    (snapshots, announcements HTML, the EOD source mirror) are left on
    the real tree, and any test that monkeypatches its own paths still
    wins - autouse fixtures run first, later patches override.
    """
    out = tmp_path / "quarantine"
    (out / "data").mkdir(parents=True)

    import cloud_bot
    import corporate_actions
    import gate_refit
    import morning_report
    import notify

    monkeypatch.setattr(notify, "NOTIFIED_PATH", out / "data" / "notified.json")
    monkeypatch.setattr(notify, "SIGNALS_PATH", out / "SIGNALS.md")
    monkeypatch.setattr(notify, "STATUS_PATH", out / "STATUS.md")
    monkeypatch.setattr(notify, "PORTFOLIO_PATH", out / "data" / "portfolio.json")
    monkeypatch.setattr(corporate_actions, "OUTPUT", out / "data" / "corporate_actions.json")
    monkeypatch.setattr(gate_refit, "GATE_REFIT", out / "data" / "gate_refit.json")
    monkeypatch.setattr(gate_refit, "GATE_HISTORY", out / "data" / "refit_history.jsonl")
    monkeypatch.setattr(cloud_bot, "_ALERT_FILE", out / "data" / "feed_alerts.json")
    monkeypatch.setattr(morning_report, "STATE_FILE", out / "data" / "morning_report_state.json")


def make_quote(
    symbol: str = "ABOT",
    price: float = 100.0,
    *,
    status: str = "OPN",
    change: float = 0.5,
    change_percent: float = 0.005,
    volume: int = 1_000,
    trades: int = 10,
) -> dict:
    """A quote shaped like psx_core.feed._build_quote's output."""
    return {
        "symbol": symbol,
        "status": status,
        "price": price,
        "change": change,
        "changePercent": change_percent,
        "volume": volume,
        "trades": trades,
        "value": price * volume,
        "high": price * 1.01,
        "low": price * 0.99,
        "bid": price - 0.05,
        "ask": price + 0.05,
        "bidVolume": 500,
        "askVolume": 500,
        "timestamp": 1_756_790_000,
    }


def make_snapshot(
    generated_at: datetime | None = None,
    symbols: tuple[str, ...] = ("ABOT", "MEBL"),
) -> dict:
    """A universe snapshot shaped like feed.build_universe_snapshot's output."""
    moment = (generated_at or datetime(2026, 9, 2, 5, 30, tzinfo=timezone.utc))
    stamp = moment.isoformat()
    quotes = {symbol: make_quote(symbol) for symbol in symbols}

    return {
        "generatedAt": stamp,
        "source": "PSX Terminal",
        "market": "REG",
        "universeCount": len(symbols),
        "quoteAvailable": len(quotes),
        "quoteUnavailable": 0,
        "quoteOpen": len(quotes),
        "quoteSuspended": 0,
        "quoteUnavailableSymbols": [],
        "requestTime": stamp,
        "receiveTime": stamp,
        "sourceBytes": 123_456,
        "parser": "fast",
        "marketInstrumentCount": 500,
        "quotes": quotes,
    }


@pytest.fixture
def archived_html() -> list[Path]:
    """The archived PSX Terminal pages, if they are still in data/."""
    candidates = sorted((PROJECT_ROOT / "data").glob("*.html"))
    if not candidates:
        pytest.skip("No archived HTML in data/")
    return candidates
