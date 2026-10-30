"""Deploy the quant-of-rehan relay worker (owner's PC only).

Owner order 2026-10-29: the owner closed his chat account for good, so
the relay no longer pairs a chat, no longer stores a chat token, and the
whole chat hop is retired. What this script still does
idempotently is deploy the worker itself:

    1. reads the Cloudflare token and account id from Desktop credentials.txt
    2. uploads cloud/worker.js as worker "quant-of-rehan-relay" with the
       admin token it generates and stores in .env as a secret binding
    3. sets the cron triggers on the SO-8 schedule (Friday is two sessions,
       so it has four edges: 09:17, 12:00, 14:32, 16:30 PKT)
    4. enables the workers.dev URL, writes data/relay_url.txt

Notifications are carried by owner email (src/notify/owner_email.py) from
the GitHub Actions jobs; nothing automated sends from this machine.

Usage:
    python cloud/pair.py deploy     # steps 1, 2, 3, 4
    python cloud/pair.py health     # live status from the edge
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
# The harmless extra wakes in the list below are safe by construction: the
# worker's scheduled() handler sends only when the Karachi minute is within
# two minutes of a real band edge, and dispatchBandScan dispatches only
# within three of a runnable window's open, so a non-edge fire returns
# without a message. Each edge is still covered by exactly one trigger, so
# nothing is sent twice.
CRONS = [
    "32,55 3,4 * * 1-4",  # Mon-Thu 08:55 PKT pre-market dispatch (owner
                          # order 2026-10-21) + 09:32 PKT band-open edge
    "30 7 * * 1-4",      # Mon-Thu 12:30 PKT afternoon scan dispatch
    "17 4 * * 5",        # Friday session 1 open 09:17 PKT
    "32 9 * * 5",        # Friday session 2 open 14:32 PKT
    "0,30,33 7,10,11 * * 1-5",  # 12:00/12:31/15:30/16:30 PKT closes,
                                # 15:33 PKT post-market dispatch wake
]


def read_creds() -> tuple[str, str]:
    """(cf_token, cf_account_id) from the Desktop sheet."""
    txt = CRED.read_text(encoding="utf-8", errors="replace")
    cf = re.findall(r"\b(cfu[a-z]_[A-Za-z0-9]{30,})\b", txt)
    acct = re.findall(r"\b([a-f0-9]{32})\b", txt)
    if not (cf and acct):
        raise SystemExit("credentials.txt missing a needed token (masked read)")
    return cf[-1], acct[-1]


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


def upload_metadata(bindings: list[dict]) -> dict:
    """The `metadata` part of a Workers script upload.

    Two fields decide whether the Durable Object is provisioned:
    `bindings` carries the namespace binding the Worker reads as env.QUOTE_HUB,
    and `exports` carries the class lifecycle entry. They are written from the
    same source here so a deploy cannot ship one without the other, which is
    what used to leave a binding pointing at a class Cloudflare had never
    provisioned.
    """
    return {
        "main_module": "worker.js",
        "compatibility_date": "2026-10-01",
        "bindings": [*bindings, {
            "type": "durable_object_namespace",
            "name": "QUOTE_HUB",
            "class_name": "QuoteHub",
        }],
        "exports": {
            "QuoteHub": {"type": "durable-object", "storage": "sqlite"},
        },
    }


def build_upload_body(meta: dict, module_name: str, source: str) -> tuple[bytes, str]:
    """One multipart/form-data body for PUT /workers/scripts/<name>.

    The API reads exactly two parts: `metadata` as application/json, and one
    part per module whose name matches the `main_module` in that metadata.
    Three details are not cosmetic:

      * the parts are separated by CRLF, and each part's body is followed by a
        CRLF before the next delimiter. A body joined with a bare \\n is a
        malformed upload, not a smaller one;
      * the boundary is checked against the module source, because a boundary
        that appears inside a part splits that part in two. A random hex
        boundary makes this vanishingly unlikely and the loop makes it
        impossible;
      * the encoding is explicit UTF-8. The worker carries the owner's
        punctuation and the metadata carries JSON, and a locale dependent
        encode would corrupt one of them.

    Returns (body, boundary) so the caller's Content-Type names the boundary
    that was actually used.
    """
    boundary = "----qor" + uuid.uuid4().hex
    while boundary in source:
        boundary = "----qor" + uuid.uuid4().hex

    def part(headers: list[tuple[str, str]], payload: bytes) -> bytes:
        head = "".join(f"{k}: {v}\r\n" for k, v in headers)
        return f"--{boundary}\r\n{head}\r\n".encode("utf-8") + payload + b"\r\n"

    fields = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    body = b"".join([
        part([("Content-Disposition",
              'form-data; name="metadata"; filename="metadata.json"'),
              ("Content-Type", "application/json")], fields),
        part([("Content-Disposition",
              f'form-data; name="{module_name}"; filename="{module_name}"'),
              ("Content-Type", "application/javascript+module")],
             source.encode("utf-8")),
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    return body, boundary


def cf_upload(cf_token: str, acct: str, bindings: list[dict]) -> None:
    js = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
    meta = upload_metadata(bindings)
    body, boundary = build_upload_body(meta, meta["main_module"], js)
    r = requests.put(
        f"{API}/accounts/{acct}/workers/scripts/{WORKER}",
        headers={"Authorization": f"Bearer {cf_token}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        data=body, timeout=60,
    )
    check(r, "worker upload")


def cf_headers() -> tuple[str, str, dict]:
    cf_token, acct = read_creds()
    return cf_token, acct, {"Authorization": f"Bearer {cf_token}"}


def deploy() -> None:
    cf_token, acct = read_creds()
    admin = env_get("RELAY_ADMIN_TOKEN") or secrets.token_urlsafe(24)
    env_set("RELAY_ADMIN_TOKEN", admin)
    bindings = [
        {"type": "secret_text", "name": "RELAY_ADMIN_TOKEN", "text": admin},
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


def health() -> None:
    r = requests.get(relay_url() + "/health", timeout=30)
    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    if cmd == "deploy":
        deploy()
    elif cmd == "health":
        health()
    else:
        print(__doc__)
