"""Scream on Telegram when the APK pipeline failed (v4.2.1).

A silent green mask (2026-10-01: the bootstrap run "succeeded" with
zero artifacts for 6 hours) is worse than a red X. The workflow keeps
every step non-fatal, reads the recorded outcomes here, and a failure
SCREAMS on Telegram while the job still ends green (no failure email,
owner's law).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

STAGES = [
    ("sdk setup", "SDK_OUTCOME"),
    ("gradle build", "BUILD_OUTCOME"),
    ("artifact upload", "UPLOAD_OUTCOME"),
    ("telegram delivery", "DELIVER_OUTCOME"),
]


def main() -> int:
    outcomes = [(name, os.environ.get(env)) for name, env in STAGES]
    bad = [name for name, outcome in outcomes if outcome == "failure"]
    if not bad:
        print("APK pipeline green")
        return 0

    msg = (
        "APK build FAILED at: " + ", ".join(bad)
        + ". Job stayed green (no email)."
    )
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                data=json.dumps({"chat_id": chat, "text": msg}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as exc:  # noqa: BLE001 - best effort
            print("alert failed (non-fatal):", exc)
    print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
