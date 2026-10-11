"""Live PSX market-state probe: a secondary witness, never the authority.

SO-8: the session law in src/data/sessions.py decides whether the market is
open. This module exists only to VERIFY that law against the exchange's own
Data Portal, so a delayed open, an unscheduled closure or a halt is *noticed*
instead of assumed away. It never replaces the law and never builds a market
time of its own.

What it reads
-------------
``https://dps.psx.com.pk/`` serves its market panel server rendered: one
``glide__slide`` block per market segment, keyed by ``data-key``, each carrying
a ``State`` stat. ``data-key="REG"`` is the Regular (equity) market, the one
this strategy trades. Captured from the live portal on 2026-10-10 (a Saturday)::

    data-key="REG" -> Closed      data-key="MTS" -> Suspended
    BNB, DFC, CSF, ODL, SQR, SIF, NDM all -> Closed

The portal's own word is passed through untouched as ``raw_state`` and is
labelled as the portal's. Only the mapping to that word is ours.

Hard rules (each one is a test)
-------------------------------
* exactly one bounded request, a strict timeout, no retries;
* every failure -- DNS, TLS, timeout, HTTP status, decoding, a missing panel,
  a state word we do not recognise -- returns UNKNOWN and **never raises**;
* an unrecognised state is never guessed into OPEN or CLOSED;
* a probe result may never authorise a trade on its own (SO-8).

Usage::

    python -m src.data.market_probe --show
    python -m src.data.market_probe --show --timeout 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402
from src.data.sessions import now_karachi  # noqa: E402

# The portal answers a browser, not a script. Same header the working
# snapshot fetcher in src/data/market_snapshot.py already uses.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: The equity market. Everything the strategy trades settles here.
REGULAR_SEGMENT = "REG"

# One market segment block; a block only counts if it carries a State stat.
SEGMENT_BLOCK = re.compile(
    r'data-key="(?P<key>[A-Z0-9]{2,6})"(?P<body>.*?)(?=data-key="|\Z)', re.S)
STATE_STAT = re.compile(
    r'__label">State</div>\s*<div[^>]*>(?P<state>[^<]{0,40})</div>', re.S)

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"
STATUS_UNKNOWN = "UNKNOWN"

#: Words the portal may print for a live session. Anything not listed here and
#: not in CLOSED_STATES is UNKNOWN by design: we do not infer.
OPEN_STATES = frozenset({"open", "trading", "in progress", "live"})

#: Words that mean the exchange is not trading right now.
CLOSED_STATES = frozenset({
    "closed", "not opened", "pre-open", "pre open", "post close", "post-close",
    "opening auction", "closing auction", "closing", "suspended", "halted",
    "break", "settlement",
})


@dataclass(frozen=True)
class MarketProbe:
    """One bounded observation of the portal, or a stated reason it is absent."""

    status: str
    raw_state: str | None
    segment: str
    url: str
    checked_at: str
    latency_ms: int
    note: str
    source: str = "dps.psx.com.pk market panel"

    @property
    def verified(self) -> bool:
        """True only when the portal gave us a state we actually understand."""
        return self.status in (STATUS_OPEN, STATUS_CLOSED)

    @property
    def is_open(self) -> bool | None:
        """Tri-state: True, False, or None when the portal could not be read."""
        if self.status == STATUS_OPEN:
            return True
        if self.status == STATUS_CLOSED:
            return False
        return None

    def as_dict(self) -> dict:
        payload = {
            "status": self.status,
            "raw_state": self.raw_state,
            "is_open": self.is_open,
            "verified": self.verified,
            "segment": self.segment,
            "source": self.source,
            "url": self.url,
            "checked_at": self.checked_at,
            "latency_ms": self.latency_ms,
            "note": self.note,
        }
        return payload


def parse_market_panel(html: str) -> dict[str, str]:
    """Every ``data-key`` that carries a State stat, in document order.

    A block without a State stat is not a market segment and is skipped, so an
    unrelated ``data-key`` elsewhere on the page can never masquerade as one.
    """
    panel: dict[str, str] = {}
    if not html:
        return panel
    for match in SEGMENT_BLOCK.finditer(html):
        stat = STATE_STAT.search(match.group("body"))
        if stat is None:
            continue
        panel.setdefault(match.group("key"),
                         " ".join(stat.group("state").split()))
    return panel


def parse_regular_state(html: str, segment: str = REGULAR_SEGMENT) -> str | None:
    """The portal's own State word for the equity market, or None."""
    return parse_market_panel(html).get(segment)


def classify_state(raw_state: str | None) -> tuple[str, str]:
    """Map the portal's word to a status plus a note that quotes the word.

    An unrecognised word is UNKNOWN, never a guess in either direction.
    """
    if raw_state is None:
        return (STATUS_UNKNOWN,
                f"no State stat found for the {REGULAR_SEGMENT} market segment")
    word = " ".join(str(raw_state).split())
    if not word:
        return (STATUS_UNKNOWN,
                f"the {REGULAR_SEGMENT} market State stat was empty")
    key = word.lower()
    if key in OPEN_STATES:
        return STATUS_OPEN, f"portal reports Regular market State {word!r}"
    if key in CLOSED_STATES:
        return STATUS_CLOSED, f"portal reports Regular market State {word!r}"
    return (STATUS_UNKNOWN,
            f"unrecognised Regular market State {word!r}; not guessed")


def probe_market_state(timeout: float | None = None,
                       url: str | None = None) -> MarketProbe:
    """Observe the portal once. Never raises; a failure is a stated UNKNOWN.

    `timeout` overrides config.PSX_PROBE_TIMEOUT_SECONDS, which exists so a
    scheduled job can tighten the call without a code change.
    """
    started = time.monotonic()
    target = (url or config.PSX_PROBE_URL).strip()
    limit = float(config.PSX_PROBE_TIMEOUT_SECONDS if timeout is None else timeout)
    checked = now_karachi().isoformat(timespec="seconds")

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    def unknown(note: str, raw_state: str | None = None) -> MarketProbe:
        return MarketProbe(STATUS_UNKNOWN, raw_state, REGULAR_SEGMENT, target,
                           checked, elapsed_ms(), note)

    try:
        request = urllib.request.Request(target,
                                        headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=limit) as response:
            body = response.read(int(config.PSX_PROBE_MAX_BYTES))
        html = body.decode("utf-8", "replace")
        raw_state = parse_regular_state(html)
        status, note = classify_state(raw_state)
        return MarketProbe(status, raw_state, REGULAR_SEGMENT, target, checked,
                           elapsed_ms(), note)
    except urllib.error.HTTPError as exc:
        return unknown(f"portal answered HTTP {exc.code}")
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        return unknown(f"portal unreachable ({type(reason).__name__})")
    except Exception as exc:  # noqa: BLE001 - reported, never invented
        return unknown(f"portal probe failed ({type(exc).__name__})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Live PSX market-state probe (verification only, SO-8)")
    parser.add_argument("--show", action="store_true",
                        help="print the probe result as JSON")
    parser.add_argument("--timeout", type=float, default=None,
                        help="override the configured request timeout in seconds")
    args = parser.parse_args(argv)
    if not args.show:
        parser.error("choose --show")

    probe = probe_market_state(timeout=args.timeout)
    print(json.dumps(probe.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
