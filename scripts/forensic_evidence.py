#!/usr/bin/env python3
"""Forensic evidence for the last two intraday losses.

Run this from the Actions job with the artifacts the Actions runner already
produced (session state, journal, captured bars). It reads only files that the
job has in its workspace and produces a JSON evidence block under
data/research/forensics_YYYYMMDD.json, with no local execution and no
network.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, is_dataclass, dataclass, make_dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import SESSION_STATE_FILE
from src.data.sessions import KARACHI, close_time, is_trading_day, now_karachi

FORWARD_DIR = ROOT / "data" / "forward"
FORENSICS_DIR = ROOT / "data" / "research"


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_lines(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def _minutes_to_close(day: date, moment: datetime) -> int | None:
    close_h, close_m = close_time(day)
    close_at = datetime(day.year, day.month, day.day, close_h, close_m, tzinfo=KARACHI)
    seconds = (close_at - moment).total_seconds()
    return int(seconds // 60) if seconds > 0 else None


def _entry_paths(journal: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in journal:
        symbol = row.get("symbol")
        if not symbol:
            continue
        entry = row.get("entry") or row.get("entry_price")
        if entry is None:
            continue
        rows.append({
            "symbol": symbol,
            "entry": entry,
            "entry_time": row.get("entry_time"),
            "stop_loss": row.get("stop_loss"),
            "target": row.get("target_price") or row.get("target"),
            "outcome": row.get("outcome"),
            "gross_return": row.get("gross_return"),
            "net_return": row.get("net_return"),
            "minutes_held": row.get("minutes_held"),
        })
    return rows


def _age_of_flip(bar: dict | None, entry_at: datetime | None) -> int | None:
    if not bar or entry_at is None:
        return None
    stamp = bar.get("timestamp") or bar.get("ts") or bar.get("time")
    try:
        bar_at = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    seconds = (entry_at - bar_at).total_seconds()
    return int(seconds // 60) if seconds >= 0 else None


def _entry_path_summary(state: dict) -> dict:
    entry = state.get("entry") or state.get("entry_price")
    if entry is None:
        return {"status": "NO_ENTRY"}
    stop = state.get("stop_loss")
    target = state.get("target_price") or state.get("target")
    upper = state.get("entry_upper") or entry * (1.02)
    lower = state.get("entry_lower") or entry * 0.99
    return {
        "upper": upper,
        "lower": lower,
        "stop": stop,
        "target": target,
        "entry": entry,
        "monitored": state.get("target_monitoring"),
        "retreated": state.get("retreat_to_precision"),
        "entry_basis": state.get("entry_basis"),
        "entry_time": state.get("entry_time"),
        "stop_loss": stop,
        "target_time": state.get("target_time"),
        "target_price": target,
        "exit_reason": state.get("exit_reason"),
        "exit_time": state.get("exit_time"),
        "exit_price": state.get("exit_price"),
    }


def _candidates(journal: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in journal:
        candidate = row.get("candidate")
        if bool(candidate):
            rows.append(candidate)
    return rows


def _daily_rows(journal: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for row in journal:
        if row.get("outcome"):
            rows.append(row)
    return rows


def _shadow_top5(journal: list[dict], day: date) -> list[dict]:
    rows: list[dict] = []
    for row in journal:
        shadow = row.get("shadow_top5")
        if not shadow or not isinstance(shadow, list):
            continue
        for index, candidate in enumerate(shadow[:5], start=1):
            symbol = candidate.get("symbol")
            rows.append({
                "rank": index,
                "symbol": symbol,
                "entry": candidate.get("entry") or candidate.get("price"),
                "entry_time": row.get("entry_time"),
                "outcome": candidate.get("outcome"),
                "gross_return": candidate.get("gross_return"),
                "net_return": candidate.get("net_return"),
                "traded": candidate.get("traded", False),
                "day": day.isoformat(),
            })
    return rows


def _session_days(symbols: Sequence[str]) -> list[date]:
    days: set[date] = set()
    for symbol in symbols:
        limit = 10
        stamp = datetime.now().date()
        for offset in range(limit):
            direction = date.today() - timedelta(days=offset)
            days.add(direction)
    return sorted(days)


def _minutes_until_close(day: date, at: datetime) -> int | None:
    close_h, close_m = close_time(day)
    close_at = datetime(day.year, day.month, day.day, close_h, close_m, tzinfo=KARACHI)
    seconds = (close_at - at).total_seconds()
    return int(seconds // 60) if seconds > 0 else None


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="forensic evidence block from Governor Cloud runs")
    parser.add_argument("--date", required=True, type=str)
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.date)

    try:
        state_path = FORWARD_DIR / SESSION_STATE_FILE
        state = _read_json(state_path)
        journal = _read_lines(FORWARD_DIR / "session_journal.jsonl")
        artifacts = _read_lines(FORWARD_DIR / "daily_outcome.json")
    except FileNotFoundError:
        raise

    report = {
        "date": day.isoformat(),
        "symbol": state.get("symbol") if state else None,
        "entry_time": state.get("entry_time") if state else None,
        "entry": state.get("entry_price") if state else None,
        "stop_loss": state.get("stop_loss") if state else None,
        "target": state.get("target_price") if state else None,
        "state": state.get("state") if state else None,
        "entry_paths": _entry_paths(journal),
        "entry_summary": _entry_path_summary(state or {}),
        "candidates_top5": _shadow_top5(journal, day),
        "journal_size": len(journal),
        "daily_outcome": artifacts,
        "session_logits": state.get("session_logits") if state else None,
    }

    target_path = FORENSICS_DIR / f"forensics_{day.strftime('%Y%m%d')}.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(report, indent=2, default=str),
                           encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
