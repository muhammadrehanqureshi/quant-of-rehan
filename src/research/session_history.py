"""Load every genuine session record, so the gate scores evidence it has.

Owner defect report, 2026-10-16. ``scripts/intraday_pipeline.py`` called
``evaluate_gate([])`` -- an empty list -- on every finalize. The gate was
never wrong; it was never given anything. The observable consequence is in
``data/forward/production_gate.json``: ``sessions_collected: 0`` and
``live_signal_enabled: false`` for ever, no matter how many sessions the
system actually observed. The "collect 60 discovery and 60 validation
sessions" promise could not advance by construction.

This module is that missing input. It reads, in order:

  1. the records the caller hands it (the session being finalized right now),
  2. the local forward state: ``data/forward/daily_outcome.json`` and the
     ``data/forward/session_journal.jsonl`` ledger,
  3. the relay's two-year research archive (``GET /research/history``), which
     is what a fresh GitHub Actions runner has instead of a local file.

and normalises each record into the row shape ``evaluate_gate`` reads:

    {date, storage_status, scanner_version, outcomes_by_rule: {...},
     data_quality: {quality, production_data_ready, ...},
     candidate, label, gross_return, net_return, minutes_held}

Honesty rules (SO-3), all of them enforced here rather than trusted downstream:

  * a date is emitted once, from the newest record seen for that date;
  * ``quality`` is ``"verified"`` ONLY when that session's own scan passed its
    data-quality law. The live scanner reports that as ``status == "OK"``
    (coverage, freshness, history, structure and volume all present). A
    blocked, missing or unreadable session is emitted as ``"unverified"``, and
    the gate's own ``_valid_rows`` then refuses to spend a research session on
    it, which is exactly what the frozen gate intends;
  * ``production_data_ready`` comes from the session's own recorded
    confirmations (rights, latency, universe currentness). It is never
    inferred from a green scan;
  * the gate's ``label`` vocabulary is mapped from the live scanner's own
    outcome, one to one, with no row invented:
        TARGET_HIT             -> TP_FIRST  (the +2% target was touched after
                                              the recorded entry, from the
                                              session's own bars)
        CLOSED_AT_SESSION_END  -> TIMEOUT
        UNVERIFIABLE           -> UNVERIFIED (and net_return is None, so the
                                              row contributes no trade)
        NO_CANDIDATE           -> no candidate, so no trade
  * a record that cannot be read is dropped and reported. Nothing is guessed.

The rolling ``candidate`` field is what ``_metrics`` reads for symbol
concentration; it is built from the session's own recorded symbol.
"""

from __future__ import annotations

import json
from pathlib import Path

from src import config

ROOT = Path(__file__).resolve().parents[2]
FORWARD_DIR = ROOT / "data" / "forward"
OUTCOME_FILE = "daily_outcome.json"
JOURNAL_FILE = "session_journal.jsonl"

#: The live scanner's outcome -> the frozen gate's label vocabulary.
LABEL_BY_OUTCOME = {
    "TARGET_HIT": "TP_FIRST",
    "STOP_HIT": "SL_FIRST",
    "STOP_AMBIGUOUS": "SL_AMBIG",
    "CLOSED_AT_SESSION_END": "TIMEOUT",
    "UNVERIFIABLE": "UNVERIFIED",
}

#: The scanner's own data-quality status -> the gate's quality vocabulary.
QUALITY_BY_STATUS = {"OK": "verified", "DATA_BLOCKED": "unverified"}


def _forward_dir() -> Path:
    """The ONE forward-state directory, resolved at CALL time.

    Derived from ``trade_state.ROOT`` exactly as ``intraday_pipeline`` does, so
    a test that redirects the forward-state surface redirects this loader with
    it, and an offline test can never read or depend on the owner's real
    session records by accident.
    """
    from src.signals import trade_state

    return trade_state.ROOT / "data" / "forward"


def _quality_of(record: dict) -> dict:
    """The session's quality block, in the gate's vocabulary.

    Two shapes reach this loader and both are real. The live scanner writes
    ``QualityReport.as_dict()``, whose verdict lives under ``status``. The
    older opening-range archives stored a block already carrying ``quality``.
    A block that already speaks the gate's vocabulary is passed through
    untouched; nothing is upgraded to "verified".
    """
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
    """One stored record -> one gate row, or None when it carries no date.

    The rule name is preserved, never relabelled: a session is scored under the
    scanner version that produced it (``_own_rule`` in forward_validation), so
    a momentum outcome can never be counted as an opening-range one.
    """
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
        # A stored session may already carry its per-rule outcomes. They are
        # kept, because forwarding them untouched is the only honest way to
        # let the frozen opening-range cohorts keep their own history.
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
            # daily_outcome.json is a container: the session itself lives
            # under outcomes_by_rule. Emitting the container as well would
            # publish a second, empty row for the same day (no symbol, no
            # return), and because the first source for a date wins that
            # empty row would shadow the real one. It is only used as a
            # record itself when it carries no per-rule outcomes at all,
            # which is the shape a hand-written or older file has.
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
    """Every genuine session record, normalised for ``evaluate_gate``.

    ``extra`` is the session being finalized right now, which is not on disk
    yet when the gate is asked. ``report``, when given, is filled in with what
    was read and what was dropped, so the observation can say where the
    evidence came from instead of implying it appeared from nowhere.
    """
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
        # The FIRST source for a date wins, and the sources are ordered by how
        # authoritative they are: the session being finalized right now, then
        # this machine's own forward state, then the relay's archive. So a
        # finalize that is still in flight outranks the copy of the same day
        # already stored, and one day is never counted twice (which the gate's
        # _valid_rows would otherwise be the only thing standing between).
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
