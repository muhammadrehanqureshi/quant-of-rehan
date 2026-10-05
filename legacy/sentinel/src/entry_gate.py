"""
PSX KMIALL BOT
Entry gate - the daily 3-entry cap, persisted so it survives restarts.

Why this exists
---------------
The 3-signal-per-session rule previously lived only as a counter inside
live.py's main loop. Three defects fell out of that placement:

  1. It never reset between trading days, so after the third entry the
     bot stopped deciding forever (until manually restarted).
  2. Restarting the process mid-session reset the counter to zero and
     allowed three more entries -- the cap wasn't real.
  3. Only the live runner enforced it. pipeline.py's decide stage had
     no cap at all, which is how 30 ENTERs landed in the ledger on
     2026-09-04 against a strategy that allows 3.

The gate is a small JSON state file keyed by trading date:

    data/entry_gate.json
    {"date": "2026-09-08", "entries": 2}

Every runner (live loop, pipeline decide stage, one-off scripts) asks
the same gate before executing an ENTER, and the gate records the entry
after it happens. A restart mid-day reloads the count from disk, so the
cap holds across process boundaries.

Usage
-----
    from entry_gate import EntryGate

    gate = EntryGate()                  # data/entry_gate.json
    gate = EntryGate(path=...)         # explicit file (tests)

    if gate.allows_entry(today):       # False once 3 entries recorded
        ...
        gate.record_entry(today)       # persists immediately

    gate.entries_today(today)          # read-only count
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from psx_core import paths, sessions


DEFAULT_MAX_ENTRIES_PER_DAY = 1  # the owner's one-call-per-day law


class EntryGate:
    """
    Persistent per-day entry counter.

    Parameters
    ----------
    path : Path or None
        Where to persist. Default: data/entry_gate.json.
    max_entries_per_day : int
        The daily cap. Default 3.
    """

    def __init__(
        self,
        path: Path | None = None,
        max_entries_per_day: int = DEFAULT_MAX_ENTRIES_PER_DAY,
    ) -> None:
        # v2.1.1: sandboxed default under pytest - same airtight guard
        # as Portfolio's. A default-constructed gate in the test suite
        # must never read or burn the owner's real entry counter.
        if path is not None:
            self.path = path
        elif "PYTEST_CURRENT_TEST" in os.environ:
            self.path = paths.DATA_DIR / "entry_gate.test-sandbox.json"
        else:
            self.path = paths.DATA_DIR / "entry_gate.json"
        self.max_entries_per_day = max_entries_per_day
        self._state: dict[str, object] = self._load()

    # -- Persistence ---------------------------------------------------------

    def _load(self) -> dict[str, object]:
        if not self.path.exists():
            return {"date": None, "entries": 0}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return {"date": None, "entries": 0}
            entries = raw.get("entries", 0)
            if not isinstance(entries, int) or entries < 0:
                entries = 0
            return {"date": raw.get("date"), "entries": entries}
        except (json.JSONDecodeError, OSError):
            # Unreadable state is treated as an empty day. The alternative --
            # refusing to run -- would stop the bot over a cosmetic file.
            return {"date": None, "entries": 0}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._state, indent=2), encoding="utf-8"
        )

    # -- Core API ------------------------------------------------------------

    def entries_today(self, trading_date: str) -> int:
        """How many entries have been recorded for this trading date."""
        if self._state.get("date") == trading_date:
            return int(self._state.get("entries", 0))
        return 0

    def allows_entry(self, trading_date: str) -> bool:
        """True if fewer than max_entries_per_day entries are on the day."""
        return self.entries_today(trading_date) < self.max_entries_per_day

    def record_entry(self, trading_date: str) -> int:
        """
        Record one entry for the trading date and persist immediately.

        Rolling the date forward in the same write is what makes the gate
        reset overnight without a running process: the first record_entry
        (or entries_today) of the new day replaces the stale date key.
        """
        if self._state.get("date") != trading_date:
            self._state = {"date": trading_date, "entries": 0}
        self._state["entries"] = int(self._state.get("entries", 0)) + 1
        self._save()
        return int(self._state["entries"])

    # -- Convenience ----------------------------------------------------------

    @staticmethod
    def today_key(moment: datetime | None = None) -> str:
        """Trading-date key for 'now' (or a given moment), as YYYY-MM-DD."""
        moment = moment or datetime.now(timezone.utc)
        return sessions.trading_date(moment).isoformat()


def load_max_entries_from_config(
    config_path: Path | None = None,
) -> int:
    """
    Read max_entries_per_day from config.json, falling back to 1
    (the owner's one-call-per-day law).

    A configured 0 is HONORED, not corrected: 0 is the owner's entry
    pause - the engine keeps deciding and logging what it would have
    done while no entry can execute. (2026-09-21: the old loader
    rejected 0 and silently fell back to 3, which would have turned a
    pause order into a fake pause - the silent-success class the
    quality doctrine bans.)

    Kept separate from EntryGate.__init__ so the gate stays usable in
    tests without a config file.
    """
    if config_path is None:
        config_path = paths.PROJECT_ROOT / "config.json"
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        value = cfg.get("max_entries_per_day", DEFAULT_MAX_ENTRIES_PER_DAY)
        if isinstance(value, int) and value >= 0:
            return value
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return DEFAULT_MAX_ENTRIES_PER_DAY
