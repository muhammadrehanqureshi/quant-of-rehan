#!/usr/bin/env python3
"""Ops alerts to the owner's channels, deduped to one per day.

Owner order 2026-10-08: GitHub failure emails per run are unwanted. The
scheduled workflows therefore stay GREEN and report through this channel
instead; the relay's /notify with kind "ops" dedupes on (UTC date, text),
so repeated failing slots cost at most ONE message per day. Owner order
2026-10-22: Telegram is no longer an owner channel, so a relay refusal
falls through to the owner email issue (one email per day as well).

Also implements the capture-health check: when the intraday capture pass
cannot substantiate coverage, ohlc_poller leaves
data/feed_capture/ohlc_low_coverage.flag behind; this script turns that
flag into exactly one deduped alert and clears the flag. A healthy pass
leaves no flag and this script stays silent.

Usage (from repo root, CI):
    python scripts/ops_alert.py --capture-health          # flag-gated
    python scripts/ops_alert.py --text "daily signal push failed; ..."
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.sessions import now_karachi  # noqa: E402
from src.notify import owner_email  # noqa: E402
from src.notify.schedule_runner import load_relay_admin_token  # noqa: E402
FLAG = ROOT / "data" / "feed_capture" / "ohlc_low_coverage.flag"
DEFAULT_RELAY = "https://quant-of-rehan-relay.mrmrehanqureshi.workers.dev"


def relay_url() -> str:
    configured = os.environ.get("RELAY_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    path = ROOT / "data" / "relay_url.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip().rstrip("/")
    return DEFAULT_RELAY


def run_url() -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
    if repository and run_id:
        return f"\nRun details: https://github.com/{repository}/actions/runs/{run_id}"
    return ""


def capture_health_message() -> str:
    coverage = ""
    cause = ""
    source = ""
    try:
        detail = json.loads(FLAG.read_text(encoding="utf-8"))
        coverage = (f" (coverage {detail.get('coverage', 0):.1%}, "
                    f"{detail.get('symbols_ok', 0)}/{detail.get('universe', 0)} symbols)")
        cause = str(detail.get("cause") or "").strip()
        source = str(detail.get("source") or "").strip()
    except (OSError, ValueError):
        pass
    # What the owner loses depends on WHICH source was thin. A servlet pass
    # that came back empty left the slot with nothing to scan at all; a thin
    # tape still hands the scan real bars, and the scan then reports its own
    # coverage. Saying the wrong one of those was the same mistake as naming a
    # cause the pass never measured, so it is read from the flag, not assumed.
    if source:
        consequence = ("The scan still ran on the bars the tape held and "
                       "reported its own coverage; nothing was fabricated "
                       "and nothing was padded. Production remains disabled. "
                       "This alert repeats at most once per day.")
    else:
        consequence = ("No scan or outcome ran for this slot. Paper "
                       "observations pause; production remains disabled. "
                       "This alert repeats at most once per day.")
    return (
        "Quant of Rehan capture degraded"
        + coverage + ".\n"
        + (f"Source: {source}\n" if source else "")
        # The cause is the one the capture pass MEASURED, carried here in the
        # flag. This message used to assert a single diagnosis (the source
        # serving no bars) whether or not that was what the pass had found,
        # so the owner could be told the wrong reason for a real outage.
        + (f"Measured cause: {cause}\n" if cause else "")
        + consequence
        + run_url()
    )


# SO-3: mirror the contract the tests already pin. The tests patch these
# symbols by their own names, so the fallback is a pure shell.


def _email_fallback(text: str) -> bool:
    """Last leg of send(): owner_email, exactly once per day (2026-10-22)."""
    marker = f"ops-alert:{now_karachi().date().isoformat()}"
    try:
        return bool(owner_email.send(text, marker))
    except (RuntimeError, requests.RequestException) as exc:
        print(f"ops alert email fallback failed: {exc}")
        return False


def send(text: str) -> bool:
    """Deliver one deduped ops alert through the best available channel.

    Order 2026-10-22: Telegram is no longer an owner channel. The relay's
    /notify with kind "ops" stays the primary path (it still dedupes on
    UTC date + text), and any refusal it gives falls through to the owner
    email issue, which is the transport the market broadcasts themselves
    already use. Both legs are deduped per day, so a day with a bad relay
    cannot fan out into a day of duplicate messages.
    """
    # One resolver with the rest of the notification path (env, then repo
    # .env). This script is the one that reports failures, so it must not be
    # the one that silently cannot speak.
    try:
        token = load_relay_admin_token()
    except RuntimeError as exc:
        print(f"ops relay path refused: {exc}")
        return _email_fallback(text)
    try:
        response = requests.post(
            relay_url() + "/notify",
            json={"kind": "ops", "text": text},
            headers={"x-admin-token": token},
            timeout=20,
        )
        if response.status_code == 200 and response.json().get("ok"):
            if response.json().get("deduped"):
                print("ops alert deduped (already sent today)")
            else:
                print("ops alert delivered")
            return True
        print(f"ops alert delivery failed: HTTP {response.status_code}")
        return _email_fallback(text)
    except (requests.RequestException, ValueError) as exc:
        print(f"ops alert delivery failed: {exc}")
        return _email_fallback(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="deduped ops alert (one per day)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture-health", action="store_true",
                      help="alert only if the low-coverage flag exists")
    mode.add_argument("--text", help="send this deduped ops alert")
    args = ap.parse_args(argv)

    if args.capture_health:
        if not FLAG.is_file():
            print("capture healthy: no alert needed")
            return 0
        send(capture_health_message())
        try:
            FLAG.unlink()
        except OSError:
            pass
        return 0

    send(args.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
