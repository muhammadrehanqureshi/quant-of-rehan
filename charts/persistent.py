"""SQLite durability for chart history, with no change to the wire contract.

The database is a local runtime artifact, never a repository asset. Bars and
metadata are committed together before the in-memory store is updated. SQLite
REAL columns preserve the same IEEE-754 values accepted by the existing Bar
contract, including an exact float round trip on reload. No raw feed captures,
credentials, or machine paths are stored in this database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable

from charts.contract import Bar, SourceInfo
from charts.store import BarStore


SCHEMA_VERSION = 1


class PersistentBarStore(BarStore):
    """A thread-safe BarStore whose data survives process restarts."""

    def __init__(self, database: str | Path) -> None:
        super().__init__()
        self.database = str(database)
        if self.database != ":memory:":
            Path(self.database).expanduser().resolve().parent.mkdir(
                parents=True, exist_ok=True)
        self._db_lock = threading.RLock()
        self._db = sqlite3.connect(self.database, timeout=10.0,
                                   check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA synchronous = FULL")
        if self.database != ":memory:":
            self._db.execute("PRAGMA journal_mode = WAL")
        self._initialize()
        self._load()

    def _initialize(self) -> None:
        version = int(self._db.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(
                f"unsupported Charts database schema {version}; "
                f"this version supports {SCHEMA_VERSION}")
        with self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS chart_series (
                    symbol TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_label TEXT NOT NULL,
                    source_delay INTEGER NOT NULL,
                    source_note TEXT NOT NULL,
                    revisions INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT '',
                    observed_at TEXT NOT NULL DEFAULT '',
                    notes_json TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY (symbol, resolution)
                );
                CREATE TABLE IF NOT EXISTS chart_bars (
                    symbol TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    t TEXT NOT NULL,
                    o REAL NOT NULL,
                    h REAL NOT NULL,
                    l REAL NOT NULL,
                    c REAL NOT NULL,
                    v REAL NOT NULL,
                    PRIMARY KEY (symbol, resolution, t),
                    FOREIGN KEY (symbol, resolution)
                        REFERENCES chart_series(symbol, resolution)
                        ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS chart_symbols (
                    symbol TEXT PRIMARY KEY,
                    facts_json TEXT NOT NULL
                );
            """)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _load(self) -> None:
        with self._lock, self._db_lock:
            for symbol, facts_json in self._db.execute(
                    "SELECT symbol, facts_json FROM chart_symbols"):
                facts = json.loads(facts_json)
                self._symbols[symbol] = facts
            rows = self._db.execute("""
                SELECT symbol, resolution, source_id, source_label,
                       source_delay, source_note, revisions, updated_at,
                       observed_at, notes_json
                FROM chart_series ORDER BY symbol, resolution
            """).fetchall()
            for (symbol, resolution, source_id, source_label, delay, note,
                 revisions, updated_at, observed_at, notes_json) in rows:
                source = SourceInfo(id=source_id, label=source_label,
                                    delay_seconds=delay, note=note)
                saved_bars = self._db.execute("""
                    SELECT t, o, h, l, c, v FROM chart_bars
                    WHERE symbol = ? AND resolution = ? ORDER BY t
                """, (symbol, resolution)).fetchall()
                bars = [Bar.build(t=t, o=o, h=h, l=l, c=c, v=v)
                        for t, o, h, l, c, v in saved_bars]
                super().upsert(symbol, resolution, bars, source,
                               updated_at=updated_at, observed_at=observed_at)
                series = self._series[(symbol, resolution)]
                series.revisions = revisions
                series.notes = json.loads(notes_json)

    @staticmethod
    def _source_values(source: SourceInfo) -> tuple:
        return (source.id, source.label, source.delay_seconds, source.note)

    def _save_series_metadata(self, symbol: str, resolution: str,
                              source: SourceInfo, *, revisions: int,
                              updated_at: str, observed_at: str,
                              notes: list[str]) -> None:
        self._db.execute("""
            INSERT INTO chart_series
                (symbol, resolution, source_id, source_label, source_delay,
                 source_note, revisions, updated_at, observed_at, notes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, resolution) DO UPDATE SET
                source_id=excluded.source_id,
                source_label=excluded.source_label,
                source_delay=excluded.source_delay,
                source_note=excluded.source_note,
                revisions=excluded.revisions,
                updated_at=excluded.updated_at,
                observed_at=excluded.observed_at,
                notes_json=excluded.notes_json
        """, (symbol, resolution, *self._source_values(source), revisions,
              updated_at, observed_at, json.dumps(notes, ensure_ascii=False)))

    def register_symbol(self, symbol: str, **facts) -> None:
        key = symbol.strip().upper()
        if not key:
            # Keep the base store's public error and validation behaviour.
            return super().register_symbol(symbol, **facts)
        with self._lock, self._db_lock:
            entry = dict(self._symbols.get(key, {"symbol": key}))
            entry.update({k: v for k, v in facts.items() if v is not None})
            encoded = json.dumps(entry, ensure_ascii=False, allow_nan=False)
            with self._db:
                self._db.execute("""
                    INSERT INTO chart_symbols(symbol, facts_json) VALUES (?, ?)
                    ON CONFLICT(symbol) DO UPDATE SET facts_json=excluded.facts_json
                """, (key, encoded))
            super().register_symbol(key, **facts)

    def upsert(self, symbol: str, resolution: str, bars: Iterable[Bar],
               source: SourceInfo, *, updated_at: str,
               observed_at: str = "") -> int:
        key = (symbol.strip().upper(), resolution)
        incoming = list(bars)
        with self._lock, self._db_lock:
            previous = self._series.get(key)
            known = {bar.t: bar for bar in previous.bars} if previous else {}
            revisions = previous.revisions if previous else 0
            for bar in incoming:
                old = known.get(bar.t)
                if old is not None and old != bar:
                    revisions += 1
                known[bar.t] = bar
            notes = list(previous.notes) if previous else []
            observed = observed_at or updated_at
            try:
                with self._db:
                    self._save_series_metadata(
                        key[0], key[1], source, revisions=revisions,
                        updated_at=updated_at, observed_at=observed, notes=notes)
                    self._db.executemany("""
                        INSERT INTO chart_bars(symbol, resolution, t, o, h, l, c, v)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(symbol, resolution, t) DO UPDATE SET
                            o=excluded.o, h=excluded.h, l=excluded.l,
                            c=excluded.c, v=excluded.v
                    """, [(key[0], key[1], bar.t, bar.o, bar.h, bar.l,
                           bar.c, bar.v) for bar in incoming])
            except (sqlite3.Error, TypeError, ValueError) as exc:
                raise RuntimeError(f"could not persist chart series: {exc}") from exc
            return super().upsert(key[0], key[1], incoming, source,
                                  updated_at=updated_at, observed_at=observed)

    def note(self, symbol: str, resolution: str, line: str) -> None:
        key = (symbol.strip().upper(), resolution)
        with self._lock, self._db_lock:
            previous = self._series.get(key)
            if previous is None or line in previous.notes:
                return super().note(key[0], key[1], line)
            notes = [*previous.notes, line]
            with self._db:
                self._db.execute("""
                    UPDATE chart_series SET notes_json = ?
                    WHERE symbol = ? AND resolution = ?
                """, (json.dumps(notes, ensure_ascii=False), *key))
            super().note(key[0], key[1], line)

    def clear(self) -> None:
        with self._lock, self._db_lock:
            with self._db:
                self._db.execute("DELETE FROM chart_bars")
                self._db.execute("DELETE FROM chart_series")
                self._db.execute("DELETE FROM chart_symbols")
            super().clear()

    def close(self) -> None:
        """Flush and close the local database; safe to call more than once."""
        with self._db_lock:
            connection, self._db = self._db, None
            if connection is not None:
                connection.close()
