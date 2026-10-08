#!/usr/bin/env python3
"""Scheduled causal scan and close-of-day forward evaluation.

All candidate observations are paper-only until the frozen evidence gate opens.
The script has no broker interface and cannot place orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import KARACHI, close_time, open_time, is_trading_day, now_karachi
from src.research.forward_validation import evaluate_gate, label_candidate
from src.signals.intraday_engine import (
    aggregate_5m, parse_capture, scan_snapshot,
)

UNIVERSE_FILE = ROOT / "src" / "data" / "universe_kmiall.json"
DATA_DIR = ROOT / "data" / "feed_capture"
FORWARD_DIR = ROOT / "data" / "forward"
RELAY_DEFAULT = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def load_kmiall(path: Path = UNIVERSE_FILE) -> list[str]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    symbols = sorted({
        str(row["symbol"]).strip().upper()
        for row in rows
        if row.get("isShariahCompliant") is True
        and "KMIALLSHR" in row.get("listedIn", [])
        and row.get("symbol")
    })
    if not symbols:
        raise RuntimeError("KMIALL/Shariah universe resolved to zero symbols")
    return symbols


def relay_url() -> str:
    configured = os.environ.get("RELAY_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    path = ROOT / "data" / "relay_url.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().rstrip("/")
    return RELAY_DEFAULT


def admin_token() -> str:
    token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    if not token:
        raise RuntimeError("RELAY_ADMIN_TOKEN missing")
    return token


def relay_request(method: str, route: str, payload: dict | None = None):
    response = requests.request(
        method, relay_url() + route, json=payload,
        headers={"x-admin-token": admin_token()},
        timeout=30,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"relay refused {route}: {result.get('error', 'unknown error')}")
    return result


def scheduled_as_of(slot: str, day=None) -> datetime:
    d = day or now_karachi().date()
    hm = tuple(int(part) for part in slot.split(":"))
    return datetime(d.year, d.month, d.day, hm[0], hm[1], tzinfo=KARACHI)


def compact_market(snapshot: dict) -> dict:
    return snapshot.get("market") or {}


def signal_text(candidate: dict, market: dict, data_quality: dict) -> str:
    entry = float(candidate["entry_reference"])
    target = entry * 1.02
    stamp = datetime.fromisoformat(candidate["timestamp"])
    return (
        f"QoR signals {stamp.date().isoformat()} (Karachi):\n"
        "KMIALL LONG SIGNAL\n\n"
        f"Symbol: {candidate['symbol']}\n"
        f"Entry reference: {entry:.4f} (paper reference, not executable)\n"
        f"Target: {target:.4f} (+2.00%)\n"
        f"Timestamp: {stamp:%H:%M} PKT\n"
        "Market: SUPPORTIVE (cross-sectional KMIALL proxy)\n"
        f"Setup: {candidate['rationale']}\n"
        "Expected horizon: intraday, close by session end\n"
        f"Data: {data_quality.get('quality')}; volume unavailable; "
        "order flow unavailable\n"
        f"Rule: {candidate.get('rule_version', 'opening_range_breakout_rs_v1')}"
    )


def run_scan(slot: str, capture: Path) -> dict:
    as_of = scheduled_as_of(slot)
    symbols = load_kmiall()
    bars, quality = parse_capture(capture, symbols, as_of)
    snapshot = scan_snapshot(bars, symbols, as_of, quality)
    snapshot["date"] = as_of.date().isoformat()
    snapshot["slot"] = slot

    gate_result = None
    storage_status = "available"
    try:
        gate_result = relay_request("GET", "/research/gate").get("gate")
        snapshot["production_gate"] = gate_result
        relay_request("POST", "/research/observation", {
            "date": snapshot["date"], "slot": slot, "snapshot": snapshot,
        })

        candidate = snapshot.get("candidate")
        if candidate and gate_result and gate_result.get("eligible") is True:
            claim = relay_request("POST", "/research/claim",
                                  {"date": snapshot["date"], "slot": slot})
            if claim.get("claimed"):
                message = signal_text(candidate, compact_market(snapshot), quality)
                relay_request("POST", "/signals", {"signals": message})
                relay_request("POST", "/notify", {"text": message, "kind": "signals"})
                snapshot["live_signal_sent"] = True
            else:
                snapshot["live_signal_sent"] = False
                snapshot["reason"] = "daily one-winner signal already claimed"
        else:
            snapshot["live_signal_sent"] = False
    except (requests.RequestException, RuntimeError, ValueError):
        # Keep the cloud capture usable even if the research routes have not
        # yet been deployed. No signal is allowed without the persistent gate.
        storage_status = "unavailable"
        gate_result = None
        snapshot["production_gate"] = {
            "status": "RESEARCH_NOT_READY", "eligible": False,
            "live_signal_enabled": False,
        }
        snapshot["live_signal_sent"] = False
        snapshot["storage_status"] = storage_status
        snapshot["reason"] += "; research relay unavailable"

    snapshot["storage_status"] = storage_status
    FORWARD_DIR.mkdir(parents=True, exist_ok=True)
    out = FORWARD_DIR / "observation.json"
    out.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "date": snapshot["date"], "slot": slot, "status": snapshot["status"],
        "reason": snapshot["reason"], "candidate": candidate,
        "production_eligible": bool(gate_result and gate_result.get("eligible")),
        "data_quality": quality,
    }, indent=2, allow_nan=False))
    return snapshot


def run_finalize(capture: Path) -> dict:
    day = now_karachi().date()
    if not is_trading_day(day):
        raise RuntimeError("finalization requested on a non-trading day")
    close_h, close_m = close_time(day)
    as_of = datetime(day.year, day.month, day.day, close_h, close_m,
                     tzinfo=KARACHI) + timedelta(minutes=1)
    symbols = load_kmiall()
    bars, quality = parse_capture(capture, symbols, as_of)
    all_5m = {sym: aggregate_5m(rows, datetime(
        day.year, day.month, day.day, *open_time(day),
        tzinfo=KARACHI), as_of) for sym, rows in bars.items()}

    storage_status = "available"
    try:
        observations = relay_request(
            "GET", f"/research/observations?date={day.isoformat()}",
        ).get("observations", [])
    except (requests.RequestException, RuntimeError, ValueError):
        observations = []
        storage_status = "unavailable"
    chosen = None
    source_snapshot = None
    for record in sorted(observations, key=lambda r: r.get("slot", "")):
        snap = record.get("snapshot", {})
        candidate = snap.get("candidate")
        if candidate:
            chosen = candidate
            source_snapshot = snap
            break

    outcome = {
        "date": day.isoformat(),
        "candidate": chosen,
        "market": None if source_snapshot is None else source_snapshot.get("market"),
        "data_quality": quality,
        "storage_status": storage_status,
    }
    if storage_status != "available":
        outcome.update({"label": "UNVERIFIABLE", "gross_return": None,
                        "net_return": None, "minutes_held": None,
                        "reason": "paper observations unavailable from persistent relay"})
    elif chosen is None:
        outcome.update({"label": "NO_CANDIDATE", "gross_return": None,
                        "net_return": None, "minutes_held": None})
    elif quality.get("quality") != "verified" or chosen["symbol"] not in all_5m:
        outcome.update({"label": "UNVERIFIABLE", "gross_return": None,
                        "net_return": None, "minutes_held": None})
    else:
        outcome.update(label_candidate(chosen, all_5m[chosen["symbol"]]))

    gate = evaluate_gate([])
    try:
        daily_record = {"date": day.isoformat(), "sessions": [outcome]}
        relay_request("POST", "/research/outcome", daily_record)
        history = relay_request("GET", "/research/history")
        rows = history.get("sessions", [])
        if not history.get("complete", True):
            raise RuntimeError("research history exceeds worker response limit")
        if not any(r.get("date") == day.isoformat() for r in rows):
            rows.append(outcome)
        gate = evaluate_gate(rows)
        relay_request("POST", "/research/gate", gate)
    except (requests.RequestException, RuntimeError, ValueError):
        storage_status = "unavailable"
        gate = evaluate_gate([])
        gate["storage_status"] = storage_status
        outcome["storage_status"] = storage_status

    FORWARD_DIR.mkdir(parents=True, exist_ok=True)
    (FORWARD_DIR / "daily_outcome.json").write_text(
        json.dumps(outcome, indent=2, allow_nan=False), encoding="utf-8")
    (FORWARD_DIR / "production_gate.json").write_text(
        json.dumps(gate, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "outcome": outcome,
        "gate": gate,
        "history_sessions": len(rows),
    }, indent=2, allow_nan=False))
    return {"outcome": outcome, "gate": gate}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Causal KMIALL intraday scan")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    parser.add_argument("--slot", choices=("10:45", "12:45", "14:45", "16:45"))
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args(argv)

    if args.scan and not args.slot:
        parser.error("--scan requires --slot")
    slot = args.slot or "16:45"
    day = now_karachi().date()
    capture = args.capture or DATA_DIR / f"ohlc_{day:%Y%m%d}.ndjson"
    if args.scan:
        run_scan(slot, capture)
    else:
        run_finalize(capture)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
