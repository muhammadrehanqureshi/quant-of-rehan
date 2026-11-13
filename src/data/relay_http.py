"""The one identity every reader of the relay sends, and its honest answers.

Measured 2026-11-12: the pre-open readiness mail said "the relay did not answer
/health (HTTP 403)" while the edge was serving the phone, the HUD and every
quote push. Cloudflare's browser integrity check refuses a default Python
User-Agent (urllib's and requests') with 403 and the body "error code: 1010",
which looks exactly like a broken relay and is not. The HUD already sends a
browser style prefix for the same reason (windows/relay.go), and
scripts/verify_market_signals.py has carried the note for months; the
Actions readers were the ones still sending the default.

So every Python reader builds its headers here. Nothing in this module decides
anything about the market, stores anything, sleeps or retries on a clock: it
is one GET and a text that names what actually happened.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

#: Browser style prefix plus the project's own name. Cloudflare's check reads
#: the prefix; an owner reading a log reads the rest.
RELAY_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "QuantOfRehan-RelayReader/1.0")


def relay_headers(extra: dict | None = None) -> dict:
    """The headers a relay read carries. *extra* is merged over them."""
    headers = {"User-Agent": RELAY_USER_AGENT, "Accept": "application/json"}
    if extra:
        headers.update(extra)
    return headers


def read_json(base: str, path: str, timeout: float = 20.0, attempts: int = 1,
              extra_headers: dict | None = None) -> tuple[dict | None, str]:
    """GET one relay route; answer (payload, "") or (None, what happened).

    The failure text names the HTTP status and the first words of the body, so
    an edge refusal (403 with "error code: 1010") is never reported as a relay
    outage again. `attempts` is a plain immediate retry, never a paced wait:
    the scheduled jobs may not sit on a clock (SO-22).
    """
    last = "unknown"
    url = base.rstrip("/") + path
    for _ in range(max(1, int(attempts))):
        request = urllib.request.Request(
            url, headers=relay_headers(extra_headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response), ""
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace").strip()[:160]
            except Exception:  # noqa: BLE001 - the body is a bonus, never required
                body = ""
            last = f"HTTP {exc.code}" + (f" {body}" if body else "")
        except Exception as exc:  # noqa: BLE001 - named for the caller
            last = type(exc).__name__
    return None, last
