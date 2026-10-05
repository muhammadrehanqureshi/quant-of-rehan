"""
Pre-approve Freebuff MCP connectors (github, cloudflare) by writing the
sidecar state the orchestrator's own approveLaunch/approveTools would
write. Hash algorithms extracted from the app's bundled orchestrator:

  canonical(v): compact JSON, object keys recursively sorted
  sha256(x)   : "sha256:" + hexdigest
  launchHash  : sha256(canonical(fingerprint))
  manifestHash: sha256(canonical(tools sorted by name, description
                sanitized (invisible chars stripped, 2048 cap + ellipsis
                marker), annotations null when absent))

Fingerprints (from fingerprintOf in the orchestrator):
  stdio: {transport, command, args, cwd, envNames(sorted keys)}
  http : {transport, url(origin+path+search), headerNames(sorted),
          authMode: "bearer" when an Authorization header exists}

Sidecar (approved state, mirroring approveLaunch + approveTools):
  enabled true, generation bumped, launchHash + manifestHash set,
  allowedTools = full tool list, approvedManifest = sanitized tools.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

HOME = os.path.expanduser("~")
AGENTS = os.path.join(HOME, ".agents", "mcp.json")
SIDECAR = os.path.join(HOME, ".freebuff", "mcp.json")
VENV_PY = r"C:\Users\rehan\OneDrive\Desktop\PSX-KMIALL-Bot\.venv\Scripts\python.exe"
BRIDGE = os.path.join(HOME, ".freebuff", "cloudflare_mcp_server.py")
GITHUB_BRIDGE = os.path.join(HOME, ".freebuff", "github_mcp_server.py")
INVISIBLE = re.compile(
    "[­᠎​-‏‪-‮⁠-⁤⁦-⁩﻿]"
    "|[󠀀-󠁿]"
)


def canonical(v):
    # Mirror of the orchestrator's canonical4: compact JSON, object
    # keys sorted, arrays in order, nulls KEPT (JS filters only
    # undefined, which has no Python equivalent in parsed JSON).
    if v is None or not isinstance(v, (dict, list)):
        return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ",".join(canonical(x) for x in v) + "]"
    items = sorted(v.items(), key=lambda kv: kv[0])
    return "{" + ",".join(
        json.dumps(k, ensure_ascii=False) + ":" + canonical(x)
        for k, x in items) + "}"


def sha256(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def sanitize_description(text):
    stripped = INVISIBLE.sub("", text or "")
    if len(stripped) > 2048:
        stripped = stripped[:2048] + "…[truncated]"
    return stripped


def manifest_hash(tools):
    # JS builds {name, description, inputSchema, annotations} where a
    # missing annotations is undefined -> canonical4 DROPS the key.
    # Python must omit it too (not emit null) for identical hashes.
    normalized = []
    for t in tools:
        item = {
            "name": t.get("name"),
            "description": sanitize_description(t.get("description")),
            "inputSchema": t.get("inputSchema"),
        }
        if t.get("annotations") is not None:
            item["annotations"] = t["annotations"]
        normalized.append(item)
    normalized.sort(key=lambda t: t["name"])
    return sha256(canonical(normalized))


def fingerprint_github(entry):
    from urllib.parse import urlsplit
    parts = urlsplit(entry["url"])
    url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    if parts.query:
        url += "?" + parts.query
    headers = entry.get("headers", {})
    return {
        "transport": "http",
        "url": url,
        "headerNames": sorted(headers.keys()),
        "authMode": "bearer" if any(
            h.lower() == "authorization" for h in headers) else "none",
    }


def fingerprint_stdio(entry):
    return {
        "transport": "stdio",
        "command": entry["command"],
        "args": entry["args"],
        "cwd": None,
        "envNames": sorted(entry.get("env", {}).keys()),
    }


def mcp_roundtrip(messages, env=None, server=BRIDGE):
    """Feed newline-delimited JSON-RPC to an MCP stdio server; collect
    responses keyed by request id."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    lines = "\n".join(json.dumps(m) for m in messages) + "\n"
    out = subprocess.run(
        [VENV_PY, server], input=lines, capture_output=True,
        text=True, encoding="utf-8", timeout=120, env=full_env,
    )
    replies = {}
    for line in out.stdout.splitlines():
        try:
            msg = json.loads(line)
            if isinstance(msg.get("id"), int):
                replies[msg["id"]] = msg
        except json.JSONDecodeError:
            continue
    return replies


def github_tools(token):
    def rpc(method, params, rid, session=None, expect_reply=True):
        body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method,
                           "params": params}).encode()
        headers = {"Authorization": "Bearer " + token,
                   "Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if session:
            headers["Mcp-Session-Id"] = session
        req = urllib.request.Request(
            "https://api.githubcopilot.com/mcp/", data=body,
            headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            new_session = r.headers.get("Mcp-Session-Id") or session
            raw = r.read().decode()
        payload = None
        for line in raw.splitlines():
            if line.startswith("data:"):
                payload = json.loads(line[5:].strip())
                break
        if payload is None and raw.strip():
            payload = json.loads(raw)
        return payload, new_session

    init, session = rpc("initialize",
                        {"protocolVersion": "2025-03-26",
                         "capabilities": {},
                         "clientInfo": {"name": "preapprove",
                                        "version": "1"}}, 1)
    try:
        rpc("notifications/initialized", {}, None, session=session)
    except Exception:
        pass
    result, session = rpc("tools/list", {}, 2, session=session)
    envelope = (result or {}).get("result") or {}
    return envelope.get("tools", [])


def reduced_annotations(annotations):
    """Their sidecar schema: annotations must be ABSENT (undefined) or
    {readOnlyHint?, destructiveHint?} - booleans only. JSON null fails
    .optional() in zod, and one bad entry discards the whole sidecar."""
    if not isinstance(annotations, dict):
        return None  # caller omits the key entirely
    out = {}
    for key in ("readOnlyHint", "destructiveHint"):
        if isinstance(annotations.get(key), bool):
            out[key] = annotations[key]
    return out or None


def side_entry(config_key, launch, manifest, allowed, approved):
    # approvedManifest stored in the orchestrator's own reduced form:
    # sanitizeTools + map to {name, description, inputSchema, annotations}
    reduced = []
    for t in approved:
        item = {
            "name": t.get("name"),
            "description": sanitize_description(t.get("description")),
            "inputSchema": t.get("inputSchema"),
        }
        ann = reduced_annotations(t.get("annotations"))
        if ann is not None:
            item["annotations"] = ann
        reduced.append(item)
    return {
        "configKey": config_key,
        "enabled": True,
        "launchHash": launch,
        "manifestHash": manifest,
        "generation": 2,
        "allowedTools": allowed,
        "approvedManifest": reduced,
        "credentialBindings": {},
    }


def main():
    agents = json.load(open(AGENTS, encoding="utf-8"))
    servers = agents["mcpServers"]
    try:
        side = json.load(open(SIDECAR, encoding="utf-8"))
    except Exception:
        side = {"servers": {}}
    side.setdefault("servers", {})

    # --- cloudflare: hash + tools via the bridge --------------------
    cf_entry = servers["cloudflare"]
    cf_fp = fingerprint_stdio(cf_entry)
    cf_launch = sha256(canonical(cf_fp))
    replies = mcp_roundtrip(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "preapprove", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        env=cf_entry.get("env", {}),
    )
    cf_tools = replies[2]["result"]["tools"]
    cf_manifest = manifest_hash(cf_tools)

    # --- github: hash + tools via the local stdio bridge ------------
    gh_entry = servers["github"]
    gh_fp = fingerprint_stdio(gh_entry)
    gh_launch = sha256(canonical(gh_fp))
    replies = mcp_roundtrip(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                        "clientInfo": {"name": "preapprove", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        env=gh_entry.get("env", {}), server=GITHUB_BRIDGE,
    )
    gh_tools = replies[2]["result"]["tools"]
    gh_manifest = manifest_hash(gh_tools)

    side["servers"]["cloudflare"] = side_entry(
        "cloudflare", cf_launch, cf_manifest,
        [t["name"] for t in cf_tools], cf_tools)
    side["servers"]["github"] = side_entry(
        "github", gh_launch, gh_manifest,
        [t["name"] for t in gh_tools], gh_tools)

    json.dump(side, open(SIDECAR, "w"), indent=2, ensure_ascii=False)
    print("cloudflare: launch", cf_launch[:24], "| manifest",
          cf_manifest[:24], "| tools", len(cf_tools))
    print("github    : launch", gh_launch[:24], "| manifest",
          gh_manifest[:24], "| tools", len(gh_tools))


if __name__ == "__main__":
    main()
