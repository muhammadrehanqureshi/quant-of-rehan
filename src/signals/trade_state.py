"""Explicit, persisted trade state machine with the one-trade-per-day lock.

Owner spec (2026-10-09): one trade per market day, and a process restart must
never let the bot forget that it already traded. The state therefore lives on
disk (data/forward/session_state.json) and is keyed by the Karachi trading
date. A new Karachi trading date starts a fresh state; history is preserved by
appending every finished session to data/forward/session_journal.jsonl.

States:

    MARKET_CLOSED -> MARKET_OPEN -> SCANNING -> CANDIDATE_FOUND
                  -> TRADE_ENTERED -> TARGET_MONITORING -> TARGET_HIT
                  -> TRADE_CLOSED -> DAILY_LOCKED
    any state     -> DATA_BLOCKED (data failure, no trade, retried next slot)

Only one transition into TRADE_ENTERED is allowed per trading day, and once
the day is DAILY_LOCKED no further entry is possible until the next session.
Nothing here can place an order: it records a paper position only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from src import config  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402


class State:
    MARKET_CLOSED = "MARKET_CLOSED"
    MARKET_OPEN = "MARKET_OPEN"
    SCANNING = "SCANNING"
    CANDIDATE_FOUND = "CANDIDATE_FOUND"
    TRADE_ENTERED = "TRADE_ENTERED"
    TARGET_MONITORING = "TARGET_MONITORING"
    TARGET_HIT = "TARGET_HIT"
    TRADE_CLOSED = "TRADE_CLOSED"
    DAILY_LOCKED = "DAILY_LOCKED"
    DATA_BLOCKED = "DATA_BLOCKED"

    ALL = (MARKET_CLOSED, MARKET_OPEN, SCANNING, CANDIDATE_FOUND, TRADE_ENTERED,
           TARGET_MONITORING, TARGET_HIT, TRADE_CLOSED, DAILY_LOCKED, DATA_BLOCKED)

    # States in which a new entry is allowed (subject to the daily lock).
    ENTRY_OPEN = (MARKET_OPEN, SCANNING, CANDIDATE_FOUND)

    # States that represent a position that is open or was taken today.
    IN_POSITION = (TRADE_ENTERED, TARGET_MONITORING)

    # Terminal for the day.
    TERMINAL = (TRADE_CLOSED, DAILY_LOCKED)


@dataclass
class SessionState:
    """One trading day's state. Persisted after every transition."""

    day: str
    state: str = State.MARKET_CLOSED
    trades_today: int = 0
    symbol: str | None = None
    entry_price: float | None = None
    entry_time: str | None = None
    entry_score: float | None = None
    target_price: float | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    return_pct: float | None = None
    target_hit: bool = False
    stop_loss: float | None = None
    stop_hit: bool = False
    exit_reason: str | None = None
    scans: int = 0
    coverage: float | None = None
    symbols_scanned: int | None = None
    symbols_expected: int | None = None
    blocked_reason: str | None = None
    last_reason: str | None = None
    scanner_version: str = config.SCANNER_VERSION
    history: list[dict] = field(default_factory=list)

    # Scheduler bookkeeping (local 4-minute runner, scripts/kmiall_tick.py).
    # These exist so a tick that is repeated -- a manual run, a Task Scheduler
    # retry, a laptop waking from sleep -- is idempotent instead of duplicating
    # work or spamming the app card.
    last_tick_slot: str | None = None
    last_card_signature: str | None = None
    # Same idempotence for the relay's research archive: a verdict that has not
    # changed is not POSTed again, so a per-second cadence cannot burn the
    # relay's daily KV write quota re-storing one identical snapshot (this is
    # what stopped observation archival mid-session on 2026-10-27).
    last_archive_signature: str | None = None
    finalized: bool = False

    # ------------------------------------------------------------- persistence
    @classmethod
    def path(cls) -> Path:
        return ROOT / config.SESSION_STATE_FILE

    @classmethod
    def journal_path(cls) -> Path:
        return ROOT / config.SESSION_JOURNAL_FILE

    @classmethod
    def load(cls, day: date | None = None, path: Path | None = None) -> "SessionState":
        """Load today's state, or a fresh one when the day has turned over."""
        today = (day or now_karachi().date()).isoformat()
        target = path or cls.path()
        if target.is_file():
            try:
                saved = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            if saved.get("day") == today:
                known = {f for f in cls.__dataclass_fields__}
                return cls(**{k: v for k, v in saved.items() if k in known})
        return cls(day=today)

    def save(self, path: Path | None = None) -> Path:
        target = path or self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")
        tmp.replace(target)
        return target

    def append_journal(self, record: dict, path: Path | None = None) -> Path:
        target = path or self.journal_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return target

    # ------------------------------------------------------- scheduler helpers
    def card_is_new(self, text: str) -> bool:
        """Has the verdict on the app card actually changed?

        A 4-minute scanner recomputes the same answer many times a session.
        Republishing an identical card would be noise, so the signature of the
        last published card is kept and compared.
        """
        return self.card_signature(text) != self.last_card_signature

    @staticmethod
    def card_signature(text: str) -> str:
        import hashlib

        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def note_card(self, text: str) -> None:
        self.last_card_signature = self.card_signature(text)

    def archive_is_new(self, signature: str) -> bool:
        """Has what would be archived actually changed since the last POST?"""
        return signature != self.last_archive_signature

    def note_archive(self, signature: str) -> None:
        self.last_archive_signature = signature

    def claimed_slot(self, slot: str) -> bool:
        """Has this exact scan slot already been scanned today?

        Used by the local tick runner to make one invocation per slot, even if
        the scheduler fires twice or the owner runs it by hand mid-slot.
        """
        return self.last_tick_slot == slot

    def note_tick(self, slot: str) -> None:
        self.last_tick_slot = slot

    # ---------------------------------------------------------------- queries
    @property
    def trade_taken(self) -> bool:
        return self.trades_today >= config.MAX_TRADES_PER_DAY

    def can_enter(self) -> bool:
        """A new entry needs an open slot AND an unused daily allowance."""
        return (self.state in State.ENTRY_OPEN
                and not self.trade_taken
                and self.trades_today < config.MAX_TRADES_PER_DAY)

    def in_position(self) -> bool:
        return self.state in State.IN_POSITION

    def locked_for_day(self) -> bool:
        return self.state in State.TERMINAL or self.trade_taken

    def to_dict(self) -> dict:
        return asdict(self)

    # ------------------------------------------------------------- transitions
    def begin_session(self) -> None:
        if self.state in (State.MARKET_CLOSED, State.DATA_BLOCKED):
            self.state = State.MARKET_OPEN

    def begin_scan(self) -> None:
        self.scans += 1
        if self.state in (State.MARKET_OPEN, State.DATA_BLOCKED, State.SCANNING):
            self.state = State.SCANNING

    def note_candidate(self, symbol: str, score: float) -> None:
        self.state = State.CANDIDATE_FOUND
        self.symbol = symbol
        self.entry_score = score

    def block(self, reason: str, coverage: float | None = None,
              scanned: int | None = None, expected: int | None = None) -> None:
        """Data failure: no trade, recorded so the next slot reports the same
        honest reason (it never masquerades as a market NO TRADE)."""
        self.blocked_reason = reason
        self.last_reason = reason
        if coverage is not None:
            self.coverage = coverage
        if scanned is not None:
            self.symbols_scanned = scanned
        if expected is not None:
            self.symbols_expected = expected
        if not self.trade_taken:
            self.state = State.DATA_BLOCKED

    def no_trade(self, reason: str, coverage: float | None = None,
                 scanned: int | None = None, expected: int | None = None) -> None:
        self.last_reason = reason
        self.blocked_reason = None
        if coverage is not None:
            self.coverage = coverage
        if scanned is not None:
            self.symbols_scanned = scanned
        if expected is not None:
            self.symbols_expected = expected
        if not self.trade_taken:
            self.state = State.SCANNING

    def enter(self, symbol: str, entry_price: float, entry_time: datetime,
              score: float, stop_loss: float | None = None) -> None:
        """Record the paper entry and lock the day to this one trade."""
        import math

        if not math.isfinite(entry_price) or entry_price <= 0:
            raise ValueError("entry must be finite and positive")
        if stop_loss is not None and (not math.isfinite(stop_loss)
                                      or not 0 < stop_loss < entry_price):
            raise ValueError("structural stop must be positive and below entry")
        if not self.can_enter():
            raise RuntimeError(
                f"entry refused: state {self.state}, trades_today "
                f"{self.trades_today} of {config.MAX_TRADES_PER_DAY}")
        self.state = State.TRADE_ENTERED
        self.trades_today += 1
        self.symbol = symbol
        self.entry_price = float(entry_price)
        self.entry_time = entry_time.isoformat()
        self.entry_score = float(score)
        self.target_price = round(float(entry_price) * (1.0 + config.TARGET_PCT), 4)
        self.target_hit = False
        self.stop_loss = stop_loss
        self.stop_hit = False
        self.exit_reason = None
        self.scanner_version = config.SCANNER_VERSION
        self.last_reason = "entered one KMIALL long, daily lock engaged"
        self.state = State.TARGET_MONITORING

    def mark_target_hit(self, exit_price: float, hit_at: datetime) -> None:
        self.state = State.TARGET_HIT
        self.target_hit = True
        self.exit_reason = "TARGET_HIT"
        self.exit_price = float(exit_price)
        self.exit_time = hit_at.isoformat()
        if self.entry_price:
            self.return_pct = round(self.exit_price / self.entry_price - 1.0, 6)
        self.last_reason = "target hit, paper position closed"

    def mark_stop_hit(self, exit_price: float, hit_at: datetime,
                      ambiguous: bool = False) -> None:
        """A structural failure closes the paper position, never resets its lock."""
        self.state = State.TRADE_CLOSED
        self.stop_hit = True
        self.exit_reason = "STOP_AMBIGUOUS" if ambiguous else "STOP_HIT"
        self.exit_price = float(exit_price)
        self.exit_time = hit_at.isoformat()
        self.return_pct = round(self.exit_price / self.entry_price - 1.0, 6)
        self.last_reason = "structural stop hit, paper position closed"

    def close_day(self, last_price: float | None, closed_at: datetime) -> None:
        """Close out the session: value the position if it is still open, then
        lock the day. The bot stays online and reports the close."""
        if self.in_position():
            self.state = State.TRADE_CLOSED
            if last_price is not None:
                self.exit_price = float(last_price)
                self.exit_time = closed_at.isoformat()
                self.exit_reason = "CLOSED_AT_SESSION_END"
                if self.entry_price:
                    self.return_pct = round(self.exit_price / self.entry_price - 1.0, 6)
            else:
                self.exit_reason = "UNVERIFIABLE"
            self.last_reason = "closed at session end without reaching target"
        self.state = State.DAILY_LOCKED
        return None

    def session_record(self) -> dict:
        """The persisted record for this market session (owner spec 26)."""
        return {
            "date": self.day,
            "trades_taken": self.trades_today,
            "trade_status": self.state,
            "symbol": self.symbol,
            "entry": self.entry_price,
            "entry_time": self.entry_time,
            "target": self.target_price,
            "target_hit": self.target_hit,
            "stop_loss": self.stop_loss,
            "stop_hit": self.stop_hit,
            "exit_reason": self.exit_reason,
            "exit": self.exit_price,
            "exit_time": self.exit_time,
            "return_pct": self.return_pct,
            "scans": self.scans,
            "coverage": self.coverage,
            "symbols_scanned": self.symbols_scanned,
            "symbols_expected": self.symbols_expected,
            "blocked_reason": self.blocked_reason,
            "last_reason": self.last_reason,
            "entry_score": self.entry_score,
            "scanner_version": self.scanner_version,
        }
