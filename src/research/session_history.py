"""The session evidence the production gate reads.

The live scanner's stored sessions are normalised without relabelling their
scanner version. Historical opening-range and momentum cohorts keep their own
results; new ICT/SMC results never inherit them. Local state and relay archive
are merged by date, with the caller's current record first.
"""
from __future__ import annotations

import json
from pathlib import Path

from src import config

ROOT = Path(__file__).resolve().parents[2]
FORWARD_DIR = ROOT / "data" / "forward"
OUTCOME_FILE = "daily_outcome.json"
JOURNAL_FILE = "session_journal.jsonl"

LABEL_BY_OUTCOME = {
    "TARGET_HIT": "TP_FIRST",
    "STOP_HIT": "SL_FIRST",
    "STOP_AMBIGUOUS": "SL_AMBIG",
    "CLOSED_AT_SESSION_END": "TIMEOUT",
    "UNVERIFIABLE": "UNVERIFIED",
}
QUALITY_BY_STATUS = {"OK": "verified", "DATA_BLOCKED": "unverified"}


def _forward_dir() -> Path:
    """Resolve the shared forward-state root at call time for test isolation."""
    from src.signals import trade_state
    return trade_state.ROOT / "data" / "forward"


def _quality_of(record: dict) -> dict:
    """Map the scanner status without upgrading any source confirmation."""
    quality = dict(record.get("data_quality") or {})
    if "quality" not in quality:
        status = str(quality.get("status") or "").upper()
        quality["quality"] = QUALITY_BY_STATUS.get(status, "unknown")
    confirmations = record.get("data_confirmations") or {}
    quality["production_data_ready"] = bool(
        quality.get("quality") == "verified"
        and config.production_data_ready(confirmations)
    )
    quality["data_confirmations"] = dict(confirmations)
    return quality


def _normalise(record: dict) -> dict | None:
    """One stored record becomes one gate row, preserving its rule name."""
    day = str(record.get("date") or "").strip()
    if not day:
        return None
    symbol = record.get("symbol") or record.get("entry_symbol")
    entry = record.get("entry_price")
    if entry is None:
        entry = record.get("entry")
    outcome = str(record.get("outcome") or record.get("trade_status") or "")
    label = LABEL_BY_OUTCOME.get(
        outcome, record.get("label") or ("NO_CANDIDATE" if not symbol else outcome))
    row = {
        "date": day,
        "storage_status": record.get("storage_status") or "unknown",
        "scanner_version": record.get("scanner_version"),
        "data_quality": _quality_of(record),
        "candidate": ({"symbol": str(symbol).upper(),
                       "entry_reference": entry} if symbol else None),
        "label": label,
        "gross_return": record.get("gross_return"),
        "net_return": record.get("net_return"),
        "minutes_held": record.get("minutes_held"),
        "symbol": symbol,
        "entry": entry,
        "entry_time": record.get("entry_time"),
    }
    outcomes = record.get("outcomes_by_rule")
    if outcomes:
        row["outcomes_by_rule"] = outcomes
    return row


def _local_records() -> list[dict]:
    """Every session record this machine has, newest first."""
    directory = _forward_dir()
    records: list[dict] = []
    outcome_path = directory / OUTCOME_FILE
    if outcome_path.is_file():
        try:
            payload = json.loads(outcome_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            # Emit the contained session, not an empty wrapper that shadows it.
            outcomes = payload.get("outcomes_by_rule") or {}
            for rule_outcome in outcomes.values():
                if isinstance(rule_outcome, dict):
                    records.append({**rule_outcome,
                                    "storage_status": payload.get("storage_status")})
            if not outcomes:
                records.append(payload)
    journal_path = directory / JOURNAL_FILE
    if journal_path.is_file():
        try:
            lines = journal_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _relay_records(timeout_s: float = 20.0) -> tuple[list[dict], str]:
    """The relay's archived sessions, or ([], why not). Never raises."""
    import requests

    from src.notify.schedule_runner import (load_relay_admin_token,
                                            load_relay_url)

    try:
        url = load_relay_url()
        token = load_relay_admin_token()
    except RuntimeError as exc:
        return [], f"relay credentials unavailable: {exc}"
    try:
        response = requests.get(url + "/research/history", timeout=timeout_s,
                                headers={"x-admin-token": token})
    except requests.RequestException as exc:
        return [], f"relay unreachable: {type(exc).__name__}"
    if response.status_code != 200:
        return [], f"relay answered HTTP {response.status_code}"
    try:
        body = response.json()
    except ValueError:
        return [], "relay answered unreadable JSON"
    sessions = body.get("sessions")
    if not isinstance(sessions, list):
        return [], "relay archive carried no sessions list"
    return [row for row in sessions if isinstance(row, dict)], ""


def session_rows(extra: list[dict] | None = None, include_relay: bool = True,
                 report: dict | None = None) -> list[dict]:
    """Collect genuine session rows and report every evidence source."""
    records: list[dict] = []
    sources: list[str] = []
    dropped: list[str] = []

    if extra:
        records.extend(extra)
        sources.append(f"caller({len(extra)})")
    local = _local_records()
    records.extend(local)
    sources.append(f"local({len(local)})")
    if include_relay:
        archived, reason = _relay_records()
        records.extend(archived)
        sources.append(f"relay({len(archived)})" if not reason
                       else f"relay(unavailable: {reason})")

    by_date: dict[str, dict] = {}
    for record in records:
        row = _normalise(record)
        if row is None:
            dropped.append("record with no date")
            continue
        # Caller, local state, relay archive: the first authoritative row wins.
        by_date.setdefault(row["date"], row)

    rows = [by_date[day] for day in sorted(by_date)]
    if report is not None:
        report.update({
            "sources": sources,
            "records_read": len(records),
            "sessions_loaded": len(rows),
            "sessions_verified": sum(
                1 for row in rows
                if (row["data_quality"] or {}).get("quality") == "verified"),
            "sessions_dropped": dropped,
        })
    return rows
