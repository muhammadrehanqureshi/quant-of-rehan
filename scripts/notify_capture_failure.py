#!/usr/bin/env python3
"""Tell the owner when a scheduled KMIALL capture cannot be verified."""

from __future__ import annotations

import os

import requests


DEFAULT_RELAY = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def build_message(run_url: str = "") -> str:
    message = (
        "Quant of Rehan capture failed.\n"
        "NO TRADE: the KMIALL intraday data capture did not pass its quality "
        "check. No candidate was sent, and production remains disabled."
    )
    return f"{message}\nRun details: {run_url}" if run_url else message


def main() -> int:
    token = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    if not token:
        print("capture failure alert skipped: relay admin token is missing")
        return 1

    relay = os.environ.get("RELAY_URL", DEFAULT_RELAY).strip().rstrip("/")
    run_url = ""
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if repository and run_id:
        run_url = f"https://github.com/{repository}/actions/runs/{run_id}"

    try:
        response = requests.post(
            relay + "/notify",
            json={"kind": "signals", "text": build_message(run_url)},
            headers={"x-admin-token": token},
            timeout=20,
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            print("capture failure alert delivery failed")
            return 1
    except (requests.RequestException, ValueError):
        print("capture failure alert delivery failed")
        return 1

    print("capture failure alert delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
