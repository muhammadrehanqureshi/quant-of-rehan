"""Push the day's genuine signals to the relay (phone app + Telegram).

LOCAL ONLY (SO-4). Reads nothing but the local 5-year dataset and the
relay URL/admin token (repo .env, SO-5). Delivery path (SO-9):

    POST {relay}/signals  {signals: text}   -> phone app card (x-admin-token)
    POST {relay}/notify   {text, kind}      -> Telegram via the worker

HONESTY LABELS (SO-1/SO-3): engine v1 is UNGRADED until Phase 2 lands. The
Phase 1 matrix showed its FVG-retrace leg fires on only ~4.4k baseline
trades with NO MAE compression (SC lift -0.15 pp) and its sweep_low leg is
flat (+0.12 pp entry / -0.07 SC). Every signal therefore travels with the
UNGRADED caveat and none of this is a trade recommendation.

Guardrails:
  - signals are generated for TODAY only after the 15:30 close (the daily
    signal is a close-of-day decision; intraday pushing would be pretending
    to trade the same bar);
  - the same (date, symbol) is never pushed twice: data/signal_push_log.jsonl
    records every delivery attempt and the sent set is enforced;
  - relay failures fail CLOSED (exit 1): the signal is not lost, the owner
    reruns the command.

Usage (from repo root):
    python -m src.signals.signal_push            # post-close push for today
    python -m src.signals.signal_push --dry-run  # show, do not send
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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
UNGRADED_NOTE = ("UNGRADED engine v1 (Phase 1: no edge claim; entry filters "
                 "under review). Observation only, not a recommendation.")


def read_admin_token() -> str:
    """RELAY_ADMIN_TOKEN from repo .env (never printed, never logged)."""
    env = ROOT / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and line.split("=", 1)[0].strip() == "RELAY_ADMIN_TOKEN":
                return line.split("=", 1)[1].strip()
    raise RuntimeError("RELAY_ADMIN_TOKEN missing from .env")


def post_json(url: str, path: str, payload: dict, token: str,
              timeout_s: float = 30.0) -> dict:
    import requests
    r = requests.post(url + path, json=payload, timeout=timeout_s,
                      headers={"x-admin-token": token})
    body = r.json()
    if r.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"relay {path} refused: HTTP {r.status_code} "
                           f"{json.dumps(body)[:120]}")
    return body


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


def build_signal_text(signals, signal_date: str) -> str:
    lines = [f"QoR signals {signal_date} (Karachi):"]
    if not signals:
        lines.append("No signal today: the v1 stack (regime x sweep_low x "
                     "FVG-retrace) did not fire on today's close.")
    else:
        for s in signals:
            lines.append(s.line())
    lines.append(UNGRADED_NOTE)
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
    if not args.dry_run and already_sent(today):
        print(f"signals for {today} were already delivered today; "
              f"nothing sent twice.")
        return 0

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

    signals, _feat = run(df)
    today_signals = [s for s in signals if s.signal_date == signal_date_label]
    text = build_signal_text(today_signals, signal_date_label)

    print(text)
    if args.dry_run:
        print("\nDRY RUN: nothing sent.")
        return 0

    token = read_admin_token()
    url = load_relay_url()
    try:
        post_json(url, "/signals", {"signals": text}, token)
        post_json(url, "/notify", {"text": text, "kind": "signals"}, token)
    except RuntimeError as exc:
        journal(f"push {signal_date_label}", False, str(exc))
        print(f"FAILED: {exc}\nsignal NOT lost: rerun the command to retry.")
        return 1
    journal(f"push {signal_date_label}", True,
            f"{len(today_signals)} signal(s), app+telegram")
    print(f"delivered: {len(today_signals)} signal(s) -> app + Telegram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
