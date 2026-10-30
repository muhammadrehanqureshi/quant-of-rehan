"""Push the daily fail-closed signal status to the relay (app card).

GITHUB ACTIONS (SO-21). Reads the 5-year dataset and the relay URL/admin
token, which arrive as workflow secrets (SO-5). Delivery path:

    POST {relay}/signals  {signals: text}   -> phone app card (x-admin-token)

Owner order 2026-10-29: the retired chat channel is gone entirely;
intraday notifications travel as owner email from the Actions jobs
(src/notify/owner_email.py), and the daily push carries the app card
only.

READINESS: no rule has demonstrated positive net expectancy under a valid
one-winner evaluation. Candidate delivery is disabled; the live payload
states NO TRADE ENGINE READY.

Guardrails:
  - signals are generated for TODAY only after the 15:30 close (the daily
    signal is a close-of-day decision; intraday pushing would be pretending
    to trade the same bar);
  - the same session's verdict is never pushed twice: the local journal
    (data/signal_push_log.jsonl) AND the relay's stored signal card are
    both checked before any send;
  - relay failures fail CLOSED (exit 1): the signal is not lost, the owner
    reruns the command.

Usage (from repo root):
    python -m src.signals.signal_push            # post-close push for today
    python -m src.signals.signal_push --dry-run  # show, do not send
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.sessions import is_market_open, now_karachi  # noqa: E402
# SO-8: every session/market decision here comes from src/data/sessions.py,
# which pins Asia/Karachi UTC+5; this module never builds a market time
# itself. The 15:30 close and the 09:32/09:17 opens live there only.
from src.data.registry import availability  # noqa: E402
from src.notify.schedule_runner import load_relay_url  # noqa: E402
from src.signals.engine import run  # noqa: E402

DATASET = ROOT / "data" / "eod_history_kmi.csv.gz"
LOG = ROOT / "data" / "signal_push_log.jsonl"
# No candidate rule has demonstrated positive net expectancy under a valid
# one-winner evaluation. Keep production delivery alive, but fail closed.
PRODUCTION_SIGNAL_ENABLED = False
NO_TRADE_NOTE = (
    "NO TRADE ENGINE READY. The current rules are research-only: no tested "
    "one-winner strategy has demonstrated positive net expectancy. "
    "Intraday captures are data collection, not intraday signals."
)


def read_admin_token() -> str:
    """RELAY_ADMIN_TOKEN: environment first, then repo .env (SO-5: never
    printed, never logged). The env path is how GitHub Actions supplies the
    secret; the .env path is the owner's PC."""
    tok = os.environ.get("RELAY_ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and line.split("=", 1)[0].strip() == "RELAY_ADMIN_TOKEN":
                return line.split("=", 1)[1].strip()
    raise RuntimeError("RELAY_ADMIN_TOKEN missing (env and .env)")


def _hint_for(status: int, body: dict) -> str:
    """Turn a relay refusal into a sentence the owner can act on.

    Owner bug report, 2026-10-10: the scheduled job reported only "the daily
    signal push failed" through the alert channel, with no cause. The relay answers
    with a specific status and message, and each one has exactly one fix, so
    the fix is named here instead of being buried in a GitHub log nobody
    reads.
    """
    detail = str(body.get("error", ""))
    if status == 403:
        return ("the relay refused the admin token (HTTP 403). The GitHub "
                "secret RELAY_ADMIN_TOKEN no longer matches the worker "
                "binding; rotate both from the same value")
    if status == 503:
        return "the relay is up but its backing store is unavailable (HTTP 503)"
    return f"the relay refused {detail or 'the request'} (HTTP {status})"


def post_json(url: str, path: str, payload: dict, token: str,
              timeout_s: float = 30.0, attempts: int = 3) -> dict:
    """POST with bounded retries, then a specific, actionable failure.

    A transient network error (the API-downtime case) is retried with a
    short backoff; a refusal from the relay is NOT retried, because the
    same request will be refused again and the owner needs the reason.
    """
    import time

    import requests

    last: str = ""
    for attempt in range(1, attempts + 1):
        try:
            r = requests.post(url + path, json=payload, timeout=timeout_s,
                              headers={"x-admin-token": token})
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
        else:
            try:
                body = r.json()
            except ValueError:
                body = {}
            if r.status_code == 200 and body.get("ok"):
                return body
            raise RuntimeError(f"relay {path} refused: {_hint_for(r.status_code, body)} "
                               f"[HTTP {r.status_code} {json.dumps(body)[:120]}]")
        if attempt < attempts:
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"relay {path} unreachable after {attempts} attempts: {last}")


def relay_preflight(url: str, token: str, timeout_s: float = 15.0) -> str:
    """Answer "can a push work right now?" before spending a fetch on it.

    Checks the relay is alive and that it accepts this admin token, because
    a token that has been rotated on one side produces a failure that looks
    like a broken push and is otherwise only discoverable after the whole
    EOD fetch has run. Returns "" when the relay is ready, else the reason.
    """
    import requests

    try:
        health = requests.get(url + "/health", timeout=timeout_s).json()
    except (requests.RequestException, ValueError) as exc:
        return f"the relay did not answer /health ({type(exc).__name__})"
    if not health.get("ok"):
        return "the relay answered /health with a fault"
    try:
        r = requests.get(url + "/signals", timeout=timeout_s,
                         headers={"x-admin-token": token})
    except requests.RequestException as exc:
        return f"the relay did not answer /signals ({type(exc).__name__})"
    if r.status_code == 200 and r.json().get("ok"):
        return ""
    if r.status_code == 403:
        return ("the relay refused this admin token (HTTP 403): the GitHub "
                "secret and the worker binding disagree")
    return f"the relay refused /signals with HTTP {r.status_code}"


def journal(event: str, ok: bool, detail: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "ts": now_karachi().isoformat(timespec="seconds"),
            "event": event, "ok": ok, "detail": detail,
        }, ensure_ascii=False) + "\n")


def already_sent(signal_date: str) -> bool:
    if not LOG.is_file():
        return False
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("event") == f"push {signal_date}" and rec.get("ok"):
            return True
    return False


def relay_already_has(url: str, token: str, signal_date: str) -> bool:
    """True when the relay's stored signal card already carries this
    session's verdict. Server-side dedupe: the Actions workspace journal is
    ephemeral, so repeated runs (evening + morning safety net) must check
    the durable state on the relay before resending."""
    import requests
    try:
        r = requests.get(url + "/signals", headers={"x-admin-token": token},
                         timeout=15)
        text = str(r.json().get("signals", ""))
    except Exception:
        return False  # cannot see the relay; the journal gate still applies
    return relay_has_session_alert(text, signal_date)


def relay_has_session_alert(text: str, signal_date: str) -> bool:
    """Prevent the post-close daily job from replacing an intraday card."""
    markers = (f"QoR signals {signal_date}",
               f"INTRADAY ALERT {signal_date}")
    return any(marker in text for marker in markers)


def build_signal_text(signals, signal_date: str) -> str:
    lines = [f"QoR signals {signal_date} (Karachi):"]
    if not signals:
        lines.append("NO TRADE")
        lines.append(NO_TRADE_NOTE)
    else:
        for s in signals:
            lines.append(s.line())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Push today's signals to the relay")
    ap.add_argument("--dry-run", action="store_true", help="print, do not send")
    ap.add_argument("--dataset", type=Path, default=DATASET)
    args = ap.parse_args(argv)

    now = now_karachi()
    today = now.date().isoformat()
    # --dry-run is read-only and may run any time (owner inspection); a real
    # push is a close-of-day decision and refuses during market hours.
    if not args.dry_run and is_market_open(now):
        print(f"market is OPEN ({now:%H:%M} PKT): the daily signal is a "
              f"close-of-day decision. Run this after the 15:30 close.")
        return 1
    if not args.dataset.is_file():
        print(f"dataset missing: {args.dataset}")
        return 1

    fp = availability("footprint")
    if fp.value == "UNAVAILABLE":
        print("registry: footprint UNAVAILABLE -> signals use daily OHLCV "
              "layers only; no order-flow claim is attached (SO-3)")

    df = pd.read_csv(args.dataset, parse_dates=["date"])
    last_session = df["date"].max().date().isoformat()
    if last_session != today:
        print(f"note: dataset's newest session is {last_session}, not today "
              f"({today}); the EOD top-up must run first. Continuing with "
              f"{last_session} data.")
        signal_date_label = last_session
    else:
        signal_date_label = today

    # dedupe on the SIGNAL's date, not the runtime date: a morning safety
    # net the day after must never resend the same session's verdict
    if not args.dry_run and already_sent(signal_date_label):
        print(f"signals for {signal_date_label} were already delivered; "
              f"nothing sent twice.")
        return 0

    # The daily FVG/sweep stack and the Phase 2B rankers have not passed the
    # economic and one-winner gates. Do not emit candidates while disabled.
    # Keep run() available for local research and dry-run experiments only.
    if PRODUCTION_SIGNAL_ENABLED:
        signals, _feat = run(df)
        today_signals = [s for s in signals if s.signal_date == signal_date_label]
    else:
        today_signals = []
    text = build_signal_text(today_signals, signal_date_label)

    print(text)
    if args.dry_run:
        print("\nDRY RUN: nothing sent.")
        return 0

    # Owner order 2026-10-08: a day without signals is a quiet day. The
    # "No signal today" notice is retired: no relay card rewrite, no phone
    # buzz, no email. Silence IS the no-signal verdict.
    if not today_signals:
        journal(f"push {signal_date_label}", True,
                "0 signal(s); quiet day, nothing pushed (owner order "
                "2026-10-08)")
        print(f"quiet day: 0 signals for {signal_date_label}; "
              f"nothing pushed (the app card stays silent).")
        return 0

    token = read_admin_token()
    url = load_relay_url()
    blocked = relay_preflight(url, token)
    if blocked:
        # Fail before the expensive work with the real reason, and journal it
        # so the next scheduled slot can see what happened.
        journal(f"preflight {signal_date_label}", False, blocked)
        print(f"relay preflight failed: {blocked}\n"
              f"the signal is NOT lost; rerun once the relay is fixed.")
        return 1
    if relay_already_has(url, token, signal_date_label):
        journal(f"push {signal_date_label}", True,
                "relay already holds this session's verdict; nothing resent")
        print(f"relay already holds the {signal_date_label} verdict; "
              f"nothing sent twice.")
        return 0
    try:
        post_json(url, "/signals", {"signals": text}, token)
    except RuntimeError as exc:
        journal(f"push {signal_date_label}", False, str(exc))
        print(f"FAILED: {exc}\nsignal NOT lost: rerun the command to retry.")
        return 1
    journal(f"push {signal_date_label}", True,
            f"{len(today_signals)} signal(s), app card")
    print(f"delivered: {len(today_signals)} signal(s) -> app card.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
