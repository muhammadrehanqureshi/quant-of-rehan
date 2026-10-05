"""Scream on Telegram when named pipeline stages failed (v4.2.2).

Generic sibling of scripts/apk_alert.py: any workflow can map its
steps' outcomes into STAGES ("Label=ENV_NAME" comma-separated) and
call this as a final always() step. The job still ends green - no
failure email (owner's law) - but a failure SCREAMS where the owner
actually lives. Silence would leave a broken healer broken for a
week; the 2026-10-01 keep-alive push failure sat invisible for that
exact reason.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    stages = []
    for spec in os.environ.get("STAGES", "").split(","):
        spec = spec.strip()
        if "=" in spec:
            label, env_name = spec.split("=", 1)
            stages.append((label, os.environ.get(env_name)))
    bad = [label for label, outcome in stages if outcome == "failure"]
    if not bad:
        print("all stages green")
        return 0

    msg = (
        "The Sentinel: pipeline FAILED at: " + ", ".join(bad)
        + ". Job stayed green (no email) - fix before it matters."
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
