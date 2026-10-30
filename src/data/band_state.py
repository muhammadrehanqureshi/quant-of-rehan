"""Survive a GitHub Actions runner: one object per trading day.

Measured fact this module exists for: nothing of this project survives a
GitHub runner. The day's broker tape, the paper session state, the loop
health and the split basis all live in local files that die with the job, so
every band started from scratch and the finalize after band 2 could never
see band 1's prints. This module is the fix: the first cycle of a band
RESTORES the day's files from Cloudflare R2 if the local machine has none,
and the loop PUSHES them back every 10 cycles and at shutdown, so the next
band starts where the previous one ended and a mid-band crash loses at
most ten minutes of prints rather than the whole morning.

SO-3: nothing here invents a state. A restore writes only files the relay
actually sent; a push uploads only files that really exist on disk; every
failure is reported as a reason, never swallowed, and never changes a scan.

Credentials: CF_API_TOKEN and CF_ACCOUNT_ID (z environment or the gitignored
repo .env), the same account the worker runs in. The bucket is
TAPE_CACHE_BUCKET (default quant-of-rehan-tape). The module is inactive on a
PC where those are absent - it then just reports why, and never blocks a
local run (SO-4: only scanner work touches this PC, and persisting R2 state
is not even needed on the PC that holds the tapes itself).

Billing honesty (the owner's standing term: never a paid service): one
trading day is about 45 MB of tape, so 22 sessions add about 1 GB to the
10 GB free tier; retention deletes finished objects after RETENTION_DAYS,
which keeps the account under ~2 GB forever and keeps the R2 bill at
$0.00/month for this workload.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

#: Objects older than this many days are deleted on a successful push. Four
#: and a half weeks of sessions stays under two gigabytes forever, far inside
#: R2's free 10 GB tier (see the module comment for the arithmetic).
RETENTION_DAYS = 45

#: Cycle interval: the loop pushes after every Nth successful cycle at a 30
#: second cadence, so a crash re-loses at most N cycles of printing, i.e.
#: five minutes of broker tape.
PUSH_EVERY_CYCLES = 10

#: The one bucket. Buoyed up by ensure_bucket on first push.
BUCKET_NAME = "quant-of-rehan-tape"

_API_BASE = "https://api.cloudflare.com/client/v4"


def _credential() -> tuple[str, str] | None:
    """CF_API_TOKEN + CF_ACCOUNT_ID, three sources, first match wins.

    1. the process environment (what GitHub Actions passes from the repo
       secrets CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID),
    2. the gitignored repo .env, and finally
    3. the app's own C:\\Users\\rehan\\.freebuff\\cloudflare.env, which holds
       the one qor-relay-deployer token this project runs on.
    Never logged, never committed (SO-5). The third source is read-only:
    this module only ever READS the credential file, it never copies one
    secret into another file.
    """
    token = os.environ.get("CF_API_TOKEN", "").strip()
    account = os.environ.get("CF_ACCOUNT_ID", "").strip()
    if token and account:
        return token, account
    candidates = [ROOT / ".env",
                  Path("C:/Users/rehan/.freebuff/cloudflare.env")]
    for env_path in candidates:
        if not (token and account) and env_path.is_file():
            try:
                text = env_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if not token:
                m_tok = re.search(r"^CF_API_TOKEN=(.*)$", text, re.M)
                token = m_tok.group(1).strip() if m_tok else ""
            if not account:
                m_acct = re.search(r"^CF_ACCOUNT_ID=(.*)$", text, re.M)
                account = m_acct.group(1).strip() if m_acct else ""
            if token and account:
                break
    if token and account:
        return token, account
    return None


def _bucket() -> str:
    return os.environ.get("TAPE_CACHE_BUCKET", BUCKET_NAME)


def bucket_url() -> str:
    creds = _credential()
    return f"{_API_BASE}/accounts/{creds[1]}/r2/buckets/{_bucket()}/objects" if creds else ""


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


# ------------------------------------------------------------- day files


def capture_path(day: date) -> Path:
    from src.data import tick_volume

    return tick_volume.capture_path(day)


def state_paths(day: date) -> list[tuple[str, Path]]:
    """Everything the next band needs, as (remote key, local path).

    The tape under day=/capture.ndjson.gz; the small state under day=/...
    names. Files that do not exist locally are simply not pushed.
    """
    from src.config import SESSION_JOURNAL_FILE, SESSION_STATE_FILE

    capture = capture_path(day)
    return [
        (f"day={day.isoformat()}/capture.ndjson.gz", capture),
        (f"day={day.isoformat()}/session_state.json", ROOT / SESSION_STATE_FILE),
        (f"day={day.isoformat()}/session_journal.jsonl", ROOT / SESSION_JOURNAL_FILE),
        (f"day={day.isoformat()}/loop_health.json", ROOT / "data" / "scan_loop_health.json"),
        (f"day={day.isoformat()}/capture_status.json", ROOT / "data" / "feed_capture" / "status.json"),
        (f"day={day.isoformat()}/ohlc_status.json", ROOT / "data" / "feed_capture" / "ohlc_status.json"),
        (f"day={day.isoformat()}/low_coverage.flag", ROOT / "data" / "feed_capture" / "ohlc_low_coverage.flag"),
    ]


# ------------------------------------------------------------- R2 plumbing


def _call(requests_like: Callable = None, method: str = "", url: str = "",
          *, headers: dict, data: bytes | None = None,
          params: dict | None = None, timeout: int = 120) -> dict:
    """One R2 API call, classified. Never raises."""
    import requests as _rq

    requests_like = requests_like or _rq
    try:
        if method == "GET":
            r = requests_like.get(url, headers=headers, params=params, timeout=timeout)
        elif method == "PUT":
            r = requests_like.put(url, headers=headers, data=data, timeout=timeout)
        elif method == "DELETE":
            r = requests_like.delete(url, headers=headers, timeout=timeout)
        else:
            return {"ok": False, "reason": f"_VERB_UNKNOWN::{method}"}
    except Exception as exc:  # noqa: BLE001 - a classified fault, not a crash
        return {"ok": False, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    return {"ok": 200 <= r.status_code < 300, "status": r.status_code, "body": r.content}


def ensure_bucket() -> dict:
    """Create the bucket if absent; skip cleanly when R2 is not enabled."""
    creds = _credential()
    if creds is None:
        return {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"}
    token, account = creds
    import requests as _rq

    url = _API_BASE + f"/accounts/{account}/r2/buckets"
    listing = _rq.get(url, headers=_headers(token), params={"limit": 50}, timeout=60)
    body = listing.json() if listing.status_code == 200 else {}
    names = [b.get("name", "") for b in (body.get("result") or {}).get("buckets", [])]
    if listing.status_code == 403 or "enable" in str(body.get("errors", "")).lower():
        return {"ok": False, "reason": "R2 is not enabled on this account (error 10042); "
                                       "add a payment method at dash.cloudflare.com R2"}
    if _bucket() in names:
        return {"ok": True, "reason": "bucket exists"}
    made = _rq.put(f"{url}/{_bucket()}", headers=_headers(token), timeout=60)
    ok = 200 <= made.status_code < 300
    return {"ok": ok, "reason": "bucket created" if ok else
            f"bucket create HTTP {made.status_code}: {made.text[:120]}"}


def _push_key(day: date, key: str, local: Path, creds: tuple[str, str]) -> dict:
    """PUT one local file as one R2 object. Contract keys and payload:
    capture files are gzipped; the small states are raw JSON."""
    if not local.is_file():
        return {"ok": True, "reason": f"absent locally: {local.name}",
                "key": key, "skipped": True}
    url = bucket_url() + "/" + quote(key, safe="")
    if key.endswith(".gz"):
        raw = gzip.compress(local.read_bytes(), compresslevel=6)
    else:
        raw = local.read_bytes()
    headers = _headers(creds[0])
    headers["content-type"] = "application/octet-stream"
    result = _call(method="PUT", url=url, headers=headers, data=raw, timeout=600)
    result["key"] = key
    result["bytes"] = len(raw)
    if result["ok"]:
        result["reason"] = f"uploaded {len(raw)} bytes"
    else:
        result["reason"] = f"HTTP {result.get('status')}"
    return result


def push(day: date = None) -> dict:
    """Push the day's whole state. Best effort; returns a summary dict.

    The bucket is ensured BEFORE anything is uploaded, so the first push of
    a new account creates quant-of-rehan-tape itself and a failure to do so
    (R2 not enabled, bad token) is a named reason, not a silent half push.
    """
    creds = _credential()
    if creds is None:
        return {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"}
    ensured = ensure_bucket()
    if not ensured.get("ok"):
        return {"ok": False, "reason": f"bucket not ensured: {ensured.get('reason')}"}
    day = day or _today()
    parts = []
    for key, local in state_paths(day):
        parts.append(_push_key(day, key, local, creds))
    ok = all(p.get("ok") for p in parts if not p.get("skipped"))
    prune_info = prune(creds) if ok else {"ok": False, "reason": "push incomplete; pruning skipped"}
    return {"ok": ok, "day": day.isoformat(),
            "reason": "; ".join(p.get("reason", "") for p in parts)[:400],
            "prune": prune_info.get("reason", ""),
            "days": prune_info.get("days", [])}


def restore(day: date = None) -> dict:
    """Restore the day's state where the local file is missing.

    A file the local machine already has stands (a band that crashed later
    in the session re-downloads nothing it already holds). Never writes
    anything the relay did not send (SO-3).
    """
    creds = _credential()
    if creds is None:
        return {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"}
    day = day or _today()
    notes = []
    restored = []
    for key, local in state_paths(day):
        if local.is_file():
            notes.append(f"local exists: {local.name}")
            continue
        url = bucket_url() + "/" + quote(key, safe="")
        result = _call(method="GET", url=url, headers=_headers(creds[0]), timeout=600)
        if result.get("status") == 404:
            notes.append(f"{local.name}: nothing pushed yet today")
            continue
        if result["ok"]:
            local.parent.mkdir(parents=True, exist_ok=True)
            payload = result["body"]
            if key.endswith(".gz"):
                payload = gzip.decompress(payload)
            local.write_bytes(payload)
            restored.append(local.name)
            notes.append(f"restored {local.name} ({len(payload)} bytes)")
        else:
            notes.append(f"{local.name}: HTTP {result.get('status')}")
    return {"ok": True, "restored": restored, "reason": "; ".join(notes)[:400]}


def fetch_capture(day: date) -> dict:
    """Download ONLY the day's tape from the store, when it is absent locally.

    The research jobs (the Kalman grid fit) need the captured tape, and a
    fresh GitHub runner holds none: the store is the only copy between the
    session that wrote it and the next job that reads it. Unlike restore(),
    this touches exactly one key, so a research job never writes a past day's
    session state over its own. Never invents a file (SO-3): a 404 is a
    named absence, not an empty capture.
    """
    creds = _credential()
    if creds is None:
        return {"ok": False, "reason": "no CF_API_TOKEN/CF_ACCOUNT_ID credential"}
    local = capture_path(day)
    if local.is_file() and local.stat().st_size > 0:
        return {"ok": True, "reason": f"local exists: {local.name}", "present": True}
    key = f"day={day.isoformat()}/capture.ndjson.gz"
    url = bucket_url() + "/" + quote(key, safe="")
    result = _call(method="GET", url=url, headers=_headers(creds[0]), timeout=600)
    if result.get("status") == 404:
        return {"ok": False, "reason": f"nothing stored for {day.isoformat()}", "present": False}
    if not result["ok"]:
        return {"ok": False, "reason": f"HTTP {result.get('status')}", "present": False}
    payload = gzip.decompress(result["body"])
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(payload)
    return {"ok": True, "reason": f"restored {local.name} ({len(payload)} bytes)",
            "present": True}


def prune(creds: tuple[str, str] | None = None, days: int = RETENTION_DAYS) -> dict:
    """DELETE every object in the bucket older than `days` days."""
    creds = creds or _credential()
    if creds is None:
        return {"ok": False, "reason": "no credential"}
    import requests as _rq

    url = _API_BASE + f"/accounts/{creds[1]}/r2/buckets/{_bucket()}/objects"
    listed = _rq.get(url, headers=_headers(creds[0]), params={"limit": 200}, timeout=90)
    body = listed.json() if listed.status_code == 200 else {}
    objects = (body.get("result") or [])
    keys = [o.get("key", "") for o
            in ((objects.get("objects") if isinstance(objects, dict) else objects) or [])]
    from src.data.sessions import now_karachi

    cutoff = (now_karachi().date() - timedelta(days=days)).isoformat()
    deleted = []
    for key in keys:
        m = re.match(r"day=(\d{4}-\d{2}-\d{2})/", key)
        this_day = m.group(1) if m else None
        if this_day and this_day < cutoff:
            r = _rq.delete(url + "/" + quote(key, safe=""),
                           headers=_headers(creds[0]), timeout=90)
            if r.status_code < 300:
                deleted.append(key)
    return {"ok": True, "reason": f"pruned {len(deleted)} object(s)", "days": deleted[:20]}


def _today() -> date:
    from src.data.sessions import now_karachi

    return now_karachi().date()


# ------------------------------------------------------------- loop hooks


def restore_best_effort(day: date | None = None) -> None:
    """Called once at the top of a band loop; logs, never raises."""
    try:
        result = restore(day)
        (result.get("restored") or []) and print(
            f"band state restored: {', '.join(result['restored'])}")
        if not result.get("ok"):
            print(f"band state restore skipped: {result.get('reason')}")
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(f"band state restore failed: {type(exc).__name__}: {exc}")


def push_best_effort(day: date | None = None) -> None:
    """Called every PUSH_EVERY_CYCLES cycles and at the loop's finally."""
    try:
        result = push(day)
        if not result.get("ok"):
            print(f"band state push did not fully succeed: {result.get('reason')}")
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(f"band state push failed: {type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    """Status and manual push/restore for the day, for inspection."""
    import argparse

    parser = argparse.ArgumentParser(description="band state in Cloudflare R2")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--day", type=str, default=None)
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.day) if args.day else None
    if args.push:
        print(json.dumps(push(day), indent=2))
        return 0
    if args.restore:
        print(json.dumps(restore(day), indent=2))
        return 0
    creds = _credential()
    print(json.dumps({
        "credential": bool(creds), "bucket": _bucket(),
        "paths": [{"key": k, "local": str(p), "exists": p.is_file(),
                   "bytes": (p.stat().st_size if p.is_file() else None)}
                  for k, p in state_paths(day or _today())]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
