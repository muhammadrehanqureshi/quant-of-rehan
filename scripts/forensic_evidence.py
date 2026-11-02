#!/usr/bin/env python3
"""Forensic evidence for the last two intraday losses.

This is a private Actions-only runner. It reads the artifacts the Actions
runner already wrote into the job's workspace and prints a compact report.
It makes no local calls and never touches the owner's PC."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="forensic evidence block from Governor Cloud runs")
    parser.add_argument("--date", required=True, type=str)
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.date)

    state = _read_json(FORWARD_DIR / "session_state.json")
    daily = _read_lines(FORWARD_DIR / "daily_outcome.json")

    report = {
        "date": day.isoformat(),
        "symbol": state.get("symbol") if state else None,
        "entry_time": state.get("entry_time") if state else None,
        "entry_price": state.get("entry_price") if state else None,
        "stop_loss": state.get("stop_loss") if state else None,
        "target_price": state.get("target_price") if state else None,
        "state": state.get("state") if state else None,
        "session_state": state,
        "daily_outcome": daily,
    }

    target_path = FORENSICS_DIR / f"forensics_{day.strftime('%Y%m%d')}.json"
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(report, indent=2, default=str),
                           encoding="utf-8")
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
