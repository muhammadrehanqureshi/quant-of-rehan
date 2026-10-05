"""One-off: deploy the updated seatbelt worker (Guard C- reference rescue).

Uploads cloud/cloudflare/seatbelt-worker.js to the sentinel-seatbelt
Worker, re-declaring ALL bindings (the PUT replaces them wholesale):
  * secret_text GITHUB_TOKEN        (stored git credential)
  * secret_text TELEGRAM_BOT_TOKEN  (EOD secrets file)
  * secret_text TELEGRAM_CHAT_ID    (EOD secrets file)
  * kv_namespace SEATBELT           (unchanged namespace)
No secret value is ever printed. Verifies by re-downloading the live
script and checking for the Guard C- marker.
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
cf = json.loads((ROOT / "data" / "cf_seatbelt.local.json").read_text())
tok, acct = cf["cf_token"], cf["account_id"]
NS_ID = cf["ns_id"]

# Secret values from their stored homes (never printed).
gh_pass = ""
for line in sys.stdin.read().splitlines():
    if line.startswith("gh_pass="):
        gh_pass = line.split("=", 1)[1].strip()
if not gh_pass:
    sys.exit("no GITHUB credential on stdin")

eod_sec = json.loads(
    (ROOT.parent / "Sentinel-EOD" / "data" / "eod_telegram_secrets.json")
    .read_text()
)
tg_token, tg_chat = eod_sec["bot_token"], str(eod_sec["chat_id"])

script = (ROOT / "cloud" / "cloudflare" / "seatbelt-worker.js").read_text(
    encoding="utf-8"
)
if "refWin" not in script or "reference_prices" not in script:
    sys.exit("local worker file does not carry Guard C- - aborting")
if "ghRanToday" not in script or "cloud-morning-report.yml" not in script:
    sys.exit("local worker file does not carry the v2.3.0 guards - aborting")

# multipart/form-data with the metadata part declaring bindings.
boundary = "----sentinel-deploy-7f3a"
metadata = {
    "main_module": "seatbelt-worker.js",
    "bindings": [
        {"type": "secret_text", "name": "GITHUB_TOKEN", "text": gh_pass},
        {"type": "secret_text", "name": "TELEGRAM_BOT_TOKEN", "text": tg_token},
        {"type": "secret_text", "name": "TELEGRAM_CHAT_ID", "text": tg_chat},
        {"type": "kv_namespace", "name": "SEATBELT", "namespace_id": NS_ID},
    ],
    "migrations": {},
}


def part(name: str, filename: str, ctype: str, body: bytes) -> bytes:
    return (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f'name="{name}"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n".encode()
        + body
        + b"\r\n"
    )


body = (
    part(
        "metadata",
        "metadata.json",
        "application/json",
        json.dumps(metadata).encode(),
    )
    + part(
        "seatbelt-worker.js",
        "seatbelt-worker.js",
        "application/javascript+module",
        script.encode(),
    )
    + f"--{boundary}--\r\n".encode()
)

req = urllib.request.Request(
    f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers/scripts/sentinel-seatbelt",
    data=body,
    method="PUT",
    headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    },
)
resp = urllib.request.urlopen(req, timeout=60)
out = json.loads(resp.read())
print("deploy success:", out["success"])
if not out["success"]:
    print(json.dumps(out.get("errors", []))[:500])
    sys.exit(1)

# Verify: the live script must now carry the guard.
vreq = urllib.request.Request(
    f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers/scripts/sentinel-seatbelt",
    headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/javascript",
    },
)
live = urllib.request.urlopen(vreq, timeout=30).read().decode("utf-8")
print("live carries Guard C-:", "refWin" in live and "reference_prices" in live)
print("live carries v2.3.0 guards:", "ghRanToday" in live and "alarm_cron_" in live)
print("live length:", len(live))

# Schedules must survive (re-check, re-create if the PUT dropped them).
sreq = urllib.request.Request(
    f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers/scripts/sentinel-seatbelt/schedules",
    headers={"Authorization": f"Bearer {tok}"},
)
scheds = json.loads(urllib.request.urlopen(sreq, timeout=30).read())
crons = [s.get("cron") for s in scheds["result"]["schedules"]]
print("crons:", crons)
if "*/2 * * * 1-5" not in crons:
    preq = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{acct}/workers/scripts/sentinel-seatbelt/schedules",
        data=json.dumps([{"cron": "*/2 * * * 1-5"}]).encode(),
        method="PUT",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json",
        },
    )
    pres = json.loads(urllib.request.urlopen(preq, timeout=30).read())
    print("cron re-created:", pres["success"])
print("OK - seatbelt updated")
