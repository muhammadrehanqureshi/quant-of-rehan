#!/usr/bin/env python3
"""Scheduled causal scan and close-of-day forward evaluation.

All candidate observations are paper-only until the frozen evidence gate opens.
The script has no broker interface and cannot place orders.
"""
from __future__ import annotations

import argparse
import hashlib
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
    CANDIDATE_RULES, RULE_VERSION, aggregate_5m, parse_capture, scan_snapshot,
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


def universe_fingerprint(symbols: list[str]) -> str:
    payload = "\n".join(sorted(set(symbols))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def annotate_source_quality(quality: dict) -> dict:
    """Separate structural bar checks from source rights and latency evidence."""
    rights_confirmed = os.environ.get("KMIALL_DATA_RIGHTS_CONFIRMED", "").lower() == "true"
    latency_confirmed = os.environ.get("KMIALL_DATA_LATENCY_CONFIRMED", "").lower() == "true"
    universe_confirmed = os.environ.get("KMIALL_UNIVERSE_CONFIRMED", "").lower() == "true"
    return {
        **quality,
        "source": "eClear GetOHLCData public read tier",
        "source_latency": "owner-confirmed" if latency_confirmed else "unverified",
        "data_rights": "owner-confirmed" if rights_confirmed else "unverified",
        "universe_membership": "owner-confirmed-current" if universe_confirmed else "unverified-currentness",
        "production_data_ready": bool(
            quality.get("quality") == "verified"
            and rights_confirmed and latency_confirmed and universe_confirmed
        ),
    }


def signal_text(candidate: dict, market: dict, data_quality: dict,
                signal_kind: str = "PAPER SIGNAL") -> str:
    entry = float(candidate["entry_reference"])
    target = entry * 1.02
    stamp = datetime.fromisoformat(candidate["timestamp"])
    lead = (f"BUY {candidate['symbol']}" if signal_kind == "PRODUCTION SIGNAL"
            else f"PAPER CANDIDATE: {candidate['symbol']}")
    rule = CANDIDATE_RULES.get(candidate.get("rule_version", RULE_VERSION), {})
    breadth = ("breadth filter applied" if rule.get("market_gate")
               else "breadth filter omitted for candidate comparison")
    median = market.get("median_return")
    advancers = market.get("advancer_share")
    market_line = (
        "Market proxy: unavailable\n" if median is None or advancers is None else
        f"Market proxy: median {median:+.2%}, advancers {advancers:.1%}; {breadth}\n"
    )
    entry_kind = "paper reference" if signal_kind == "PAPER SIGNAL" else "signal reference"
    evidence = (
        "frozen 60/60/60 evidence gate passed"
        if signal_kind == "PRODUCTION SIGNAL"
        else "paper observation; no validated edge yet"
    )
    return (
        f"QoR signals {stamp.date().isoformat()} (Karachi):\n"
        f"{signal_kind} | KMIALL LONG ONLY\n"
        f"{lead}\n\n"
        f"Entry reference: {entry:.4f} ({entry_kind}, not executable)\n"
        f"Target: {target:.4f} (+2.00%)\n"
        f"Timestamp: {stamp:%H:%M} PKT\n"
        f"Evidence: {evidence}\n"
        f"{market_line}"
        f"Setup: {candidate['rationale']}\n"
        "Expected horizon: intraday, close by session end\n"
        f"Data: {data_quality.get('quality')}; volume unavailable; "
        "order flow unavailable\n"
        f"Rule: {candidate.get('rule_version', 'opening_range_breakout_rs_v1')}"
    )


def run_scan(slot: str, capture: Path) -> dict:
    as_of = scheduled_as_of(slot)
    symbols = load_kmiall()
    bars, raw_quality = parse_capture(capture, symbols, as_of)
    quality = annotate_source_quality(raw_quality)
    strategy_snapshots = {
        rule: scan_snapshot(bars, symbols, as_of, quality, rule_version=rule)
        for rule in CANDIDATE_RULES
    }
    has_paper_candidate = any(
        item.get("candidate") for item in strategy_snapshots.values()
    )
    snapshot = {
        "date": as_of.date().isoformat(),
        "slot": slot,
        "universe_source": "versioned current KMIALL membership snapshot",
        "universe_size": len(symbols),
        "universe_sha256": universe_fingerprint(symbols),
        "as_of": as_of.isoformat(),
        "status": "PAPER_CANDIDATE" if has_paper_candidate else "NO_TRADE",
        "reason": "registered candidates evaluated; candidate details are per rule",
        "strategies": strategy_snapshots,
        "data_quality": quality,
        "target_pct": 0.02,
        "stop_pct": 0.01,
        "volume": "unavailable; not used",
        "order_flow": "unavailable",
    }

    gate_result = None
    storage_status = "available"
    candidate = None
    signal_kind = None
    try:
        gate_result = relay_request("GET", "/research/gate").get("gate")
        snapshot["production_gate"] = gate_result
        if gate_result and gate_result.get("eligible") is True \
                and gate_result.get("live_signal_enabled") is True \
                and quality.get("production_data_ready") is True:
            selected_rule = gate_result.get("selected_rule_version")
            selected = strategy_snapshots.get(selected_rule, {})
            candidate = selected.get("candidate")
            if candidate:
                candidate["rule_version"] = selected_rule
                signal_kind = "PRODUCTION SIGNAL"
        else:
            # The original rule remains an explicitly paper-only observation
            # while the candidate library is being evaluated.
            candidate = strategy_snapshots.get(RULE_VERSION, {}).get("candidate")
            if candidate:
                candidate["rule_version"] = RULE_VERSION
                signal_kind = "PAPER SIGNAL"

        if candidate and signal_kind:
            snapshot["candidate"] = candidate
            snapshot["signal_kind"] = signal_kind
            snapshot["signal_intent"] = "one-per-day claim required before delivery"
        else:
            snapshot["signal_kind"] = "NO TRADE"
            snapshot["signal_intent"] = "no qualifying candidate at this scan"

        saved_observation = relay_request("POST", "/research/observation", {
            "date": snapshot["date"], "slot": slot, "snapshot": snapshot,
        })
        if not saved_observation.get("stored", True):
            snapshot["signal_sent"] = False
            snapshot["reason"] = "immutable observation already exists; duplicate scan not delivered"
            candidate = None
            signal_kind = None

        if candidate and signal_kind:
            claim = relay_request("POST", "/research/claim",
                                  {"date": snapshot["date"], "slot": slot})
            if claim.get("claimed"):
                selected_market = strategy_snapshots.get(
                    candidate.get("rule_version", RULE_VERSION), {}).get("market", {})
                message = signal_text(candidate, selected_market, quality, signal_kind)
                relay_request("POST", "/signals", {"signals": message})
                relay_request("POST", "/notify", {
                    "text": message, "kind": "signals",
                })
                snapshot["status"] = signal_kind
                snapshot["signal_sent"] = True
            else:
                snapshot["signal_sent"] = False
                snapshot["reason"] = "one candidate for this day was already sent"
        else:
            snapshot["signal_sent"] = False
    except (requests.RequestException, RuntimeError, ValueError):
        storage_status = "unavailable"
        gate_result = None
        snapshot["production_gate"] = {
            "status": "RESEARCH_NOT_READY", "eligible": False,
            "live_signal_enabled": False,
        }
        snapshot["signal_sent"] = False
        snapshot["reason"] += "; research relay unavailable"

    snapshot["storage_status"] = storage_status
    FORWARD_DIR.mkdir(parents=True, exist_ok=True)
    out = FORWARD_DIR / "observation.json"
    out.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({
        "date": snapshot["date"], "slot": slot, "status": snapshot["status"],
        "reason": snapshot["reason"],
        "candidate": snapshot.get("candidate"),
        "signal_kind": snapshot.get("signal_kind"),
        "production_eligible": bool(gate_result and gate_result.get("eligible")),
        "data_quality": quality,
        "candidate_statuses": {
            rule: item.get("status") for rule, item in strategy_snapshots.items()
        },
    }, indent=2, allow_nan=False))
    return snapshot

def missing_scan_slots(day, observations: list[dict]) -> list[str]:
    """List scheduled slots without a structurally verified observation."""
    required = {"10:45", "14:45"} if day.weekday() == 4 else {
        "10:45", "12:45", "14:45",
    }
    seen = {
        str(row.get("slot", ""))
        for row in observations
        if (row.get("snapshot", {}).get("data_quality", {}).get("quality")
            == "verified")
    }
    return sorted(required - seen)


def run_finalize(capture: Path) -> dict:
    day = now_karachi().date()
    if not is_trading_day(day):
        raise RuntimeError("finalization requested on a non-trading day")
    close_h, close_m = close_time(day)
    as_of = datetime(day.year, day.month, day.day, close_h, close_m,
                     tzinfo=KARACHI) + timedelta(minutes=1)
    symbols = load_kmiall()
    bars, raw_quality = parse_capture(capture, symbols, as_of)
    quality = annotate_source_quality(raw_quality)
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

    missing_slots = missing_scan_slots(day, observations)
    if missing_slots:
        quality = {**quality, "quality": "degraded",
                   "reason": "missing scheduled paper observations: " + ", ".join(missing_slots)}
    candidates: dict[str, dict | None] = {rule: None for rule in CANDIDATE_RULES}
    for record in sorted(observations, key=lambda r: r.get("slot", "")):
        snap = record.get("snapshot", {})
        strategies = snap.get("strategies", {})
        for rule in CANDIDATE_RULES:
            candidate = strategies.get(rule, {}).get("candidate")
            if candidates[rule] is None and candidate:
                candidates[rule] = candidate

    outcomes_by_rule = {}
    for rule, candidate in candidates.items():
        if storage_status != "available":
            label = {"label": "UNVERIFIABLE", "gross_return": None,
                     "net_return": None, "minutes_held": None}
        elif candidate is None:
            label = {"label": "NO_CANDIDATE", "gross_return": None,
                     "net_return": None, "minutes_held": None}
        elif quality.get("quality") != "verified" or candidate["symbol"] not in all_5m:
            label = {"label": "UNVERIFIABLE", "gross_return": None,
                     "net_return": None, "minutes_held": None}
        else:
            label = label_candidate(candidate, all_5m[candidate["symbol"]])
        outcomes_by_rule[rule] = {"candidate": candidate, **label}

    outcome = {
        "date": day.isoformat(),
        "universe_source": "versioned current KMIALL membership snapshot",
        "universe_size": len(symbols),
        "universe_sha256": universe_fingerprint(symbols),
        "data_quality": quality,
        "storage_status": storage_status,
        "outcomes_by_rule": outcomes_by_rule,
    }
    gate = evaluate_gate([])
    rows = []
    try:
        relay_request("POST", "/research/outcome", {
            "date": day.isoformat(), "sessions": [outcome],
        })
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
