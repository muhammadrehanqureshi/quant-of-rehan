"""Deploy and pair the quant-of-rehan Telegram relay (owner's PC only).

Telegram is blocked inside Pakistan (SO-9), so this machine never talks to
api.telegram.org. It talks to Cloudflare instead, which talks to Telegram.

What this script does, idempotently:
    1. reads the Cloudflare and Telegram tokens from Desktop credentials.txt
    2. uploads cloud/worker.js as worker "quant-of-rehan-relay" with secret
       bindings (bot token, an admin token it generates and stores in .env)
    3. asks the worker which chat last messaged the bot (you send it a
       message from your phone), then writes PAIRED_CHAT_ID as a binding
    4. sets the six cron triggers on the SO-8 schedule (Friday is two
       sessions, so it has four edges: 09:17, 12:00, 14:32, 16:30 PKT)
    5. enables the workers.dev URL, writes data/relay_url.txt
    6. sends one test message through the full relay path

Usage:
    python cloud/pair.py deploy      # steps 1, 2, 4, 5
    python cloud/pair.py discover    # step 3 (message the bot first)
    python cloud/pair.py test        # step 6 (needs pairing)
    python cloud/pair.py all         # deploy, discover, test
"""

from __future__ import annotations

import json
import re
import secrets
import sys
import uuid
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
CRED = Path(r"C:/Users/rehan/OneDrive/Desktop/credentials.txt")
ENV_FILE = ROOT / ".env"
RELAY_URL_FILE = ROOT / "data" / "relay_url.txt"
WORKER = "quant-of-rehan-relay"
API = "https://api.cloudflare.com/client/v4"
SUBDOMAIN = "mrmrehanqureshi"  # workers.dev subdomain of this account

# SO-8, band aware (2026-10-10). Karachi is UTC+5.
#   Mon-Thu open  09:32 PKT = 04:32 UTC | close 15:30 PKT = 10:30 UTC
#   Friday  s1    09:17 PKT = 04:17 UTC | close 12:00 PKT = 07:00 UTC
#   Friday  s2    14:32 PKT = 09:32 UTC | close 16:30 PKT = 11:30 UTC
# The Friday midday break needs two more edges than this account can hold.
# Workers Free allows 5 cron triggers per ACCOUNT, so the obvious six entry
# list is rejected with Cloudflare error 10072, and that rejection used to
# abort the deploy AFTER the script upload, leaving the schedules stale while
# the code was already live. That partial deploy is the trap this fixes.
#
# `0,32 7,9 * * 5` packs both Friday midday edges into one trigger. It also
# fires at 07:32 and 09:00 UTC, which is safe by construction: the worker's
# scheduled() handler sends only when the Karachi minute is within two minutes
# of a real band edge, so a non-edge fire returns without a message. Each edge
# is still covered by exactly one trigger, so nothing is sent twice.
CRONS = [
    "32 4 * * 1-4",      # Mon-Thu open 09:32 PKT
    "30 10 * * 1-4",     # Mon-Thu close 15:30 PKT
    "17 4 * * 5",        # Friday session 1 open 09:17 PKT
    "0,32 7,9 * * 5",    # Friday 12:00 PKT close and 14:32 PKT reopen
    "30 11 * * 5",       # Friday session 2 close 16:30 PKT
]


def read_creds() -> tuple[str, str, str]:
    """(cf_token, cf_account_id, telegram_token) from the Desktop sheet."""
    txt = CRED.read_text(encoding="utf-8", errors="replace")
    cf = re.findall(r"\b(cfu[a-z]_[A-Za-z0-9]{30,})\b", txt)
    acct = re.findall(r"\b([a-f0-9]{32})\b", txt)
    tg = re.findall(r"\b(\d{8,12}:[A-Za-z0-9_-]{30,})\b", txt)
    if not (cf and acct and tg):
        raise SystemExit("credentials.txt missing a needed token (masked read)")
    return cf[-1], acct[-1], tg[-1]


def env_get(key: str) -> str:
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return ""


def env_set(key: str, value: str) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.is_file() else []
    out, found = [], False
    for line in lines:
        if line.strip().startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def relay_url() -> str:
    return f"https://{WORKER}.{SUBDOMAIN}.workers.dev"


def check(resp: requests.Response, label: str):
    d = resp.json()
    if not d.get("success"):
        raise SystemExit(f"{label} FAILED: {str(d.get('errors'))[:200]}")
    print(f"{label}: ok")
    return d


def cf_upload(cf_token: str, acct: str, bindings: list[dict]) -> None:
    js = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
    meta = {
        "main_module": "worker.js",
        "compatibility_date": "2026-10-01",
        "bindings": bindings,
    }
    b = uuid.uuid4().hex
    body = (
        f'--{b}\r\nContent-Disposition: form-data; name="metadata"; filename="m.json"\r\n'
        f"Content-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
        f'--{b}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\n'
        f"Content-Type: application/javascript+module\r\n\r\n{js}\r\n"
        f"--{b}--\r\n"
    ).encode()
    r = requests.put(
        f"{API}/accounts/{acct}/workers/scripts/{WORKER}",
        headers={"Authorization": f"Bearer {cf_token}",
                 "Content-Type": f"multipart/form-data; boundary={b}"},
        data=body, timeout=60,
    )
    check(r, "worker upload")


def cf_headers() -> tuple[str, str, dict]:
    cf_token, acct, _ = read_creds()
    return cf_token, acct, {"Authorization": f"Bearer {cf_token}"}


def kv_id() -> str:
    p = ROOT / "data" / "relay_kv_id.txt"
    if not p.is_file():
        raise SystemExit("data/relay_kv_id.txt missing; create the KV namespace first")
    return p.read_text(encoding="utf-8").strip()


def deploy() -> None:
    cf_token, acct, tg_token = read_creds()
    admin = env_get("RELAY_ADMIN_TOKEN") or secrets.token_urlsafe(24)
    env_set("RELAY_ADMIN_TOKEN", admin)
    bindings = [
        {"type": "secret_text", "name": "TELEGRAM_BOT_TOKEN", "text": tg_token},
        {"type": "secret_text", "name": "RELAY_ADMIN_TOKEN", "text": admin},
        {"type": "kv_namespace", "name": "RELAY_KV", "namespace_id": kv_id()},
    ]
    cf_upload(cf_token, acct, bindings)
    H = {"Authorization": f"Bearer {cf_token}"}
    check(requests.put(f"{API}/accounts/{acct}/workers/scripts/{WORKER}/schedules",
                       headers=H, json=[{"cron": c} for c in CRONS], timeout=30),
          "cron schedule")
    check(requests.post(f"{API}/accounts/{acct}/workers/scripts/{WORKER}/subdomain",
                        headers=H, json={"enabled": True, "previews_enabled": False},
                        timeout=30),
          "workers.dev url")
    RELAY_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    RELAY_URL_FILE.write_text(relay_url() + "\n", encoding="utf-8")
    print("relay url saved to data/relay_url.txt")


def discover() -> None:
    """Two-step pairing: start (bot sends the owner a code), then confirm."""
    admin = env_get("RELAY_ADMIN_TOKEN")
    if not admin:
        raise SystemExit("no admin token; run deploy first")
    H = {"x-admin-token": admin}
    r = requests.post(f"{relay_url()}/pair/start", headers=H, json={}, timeout=60)
    d = r.json()
    if not d.get("ok"):
        print(f"pair/start failed: {d.get('error')}")
        print("send the bot a message on Telegram from your phone, then rerun")
        sys.exit(2)
    print(f"pairing code sent to chat ({d.get('chat_kind')} "
          f"{d.get('chat_name') or 'unnamed'}); check the bot chat")
    code = input("enter the 4-digit code: ").strip()
    r = requests.post(f"{relay_url()}/pair/confirm", headers=H,
                      json={"code": code}, timeout=60)
    d = r.json()
    if not d.get("ok"):
        print(f"pair/confirm failed: {d.get('error')}")
        sys.exit(3)
    print(f"paired with chat {d['paired_chat'][:4]}...{d['paired_chat'][-3:]}; "
          f"confirmation message sent by the bot")


def test() -> None:
    admin = env_get("RELAY_ADMIN_TOKEN")
    if not admin:
        raise SystemExit("no admin token; run deploy first")
    r = requests.post(f"{relay_url()}/notify",
                      headers={"x-admin-token": admin},
                      json={"kind": "open",
                            "text": "quant-of-rehan relay test: delivery works."},
                      timeout=60)
    d = r.json()
    print("test send:", "DELIVERED" if d.get("ok") else f"FAILED: {d.get('error')}")


def health() -> None:
    r = requests.get(relay_url() + "/health", timeout=30)
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "deploy":
        deploy()
    elif cmd == "discover":
        discover()
    elif cmd == "test":
        test()
    elif cmd == "health":
        health()
    elif cmd == "all":
        deploy()
        discover()
        test()
    else:
        print(__doc__)
