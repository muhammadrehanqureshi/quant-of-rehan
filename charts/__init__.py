"""Charts of Rehan: the charting service behind the web front end.

This package is the backend half of the charting application. It is a
standard library Python service on purpose: it has to run on the owner's
machine, on a fresh checkout and inside CI without a dependency install, and
the job it does (poll a source, keep minute bars honest, hand them to a
browser) does not need a framework to do it.

The architecture in one screen::

    charts/contract.py   the wire contract, defined once, validated both ways
    charts/adapters/     one file per source, behind one small Protocol
        base.py          Capabilities + BarSource: what a source must answer
        tape.py          the broker MKT-FEED tape, this project's own bars
        portal.py        the PSX Data Portal session snapshot, politely paced
        replay.py        deterministic synthetic bars, tests and demo only
    charts/ratelimit.py  token bucket, bounded retries, circuit breaker ledger
    charts/store.py      thread safe series store, upsert, revisions, gaps
    charts/ingest.py     the polling loop and the subscriber fan-out
    charts/sessions.py   session facts, answered by src/data/sessions.py
    charts/http.py       REST, Server-Sent Events, and the built web app
    charts/app.py        the command line entry point, foreground only

Three rules come from the project's standing orders and are enforced in code
rather than in prose:

* **SO-3, no invented data.** An empty series is an empty series with a
  stated reason, never a row of zeroes. A source that answers 200 with no
  usable panel is the named failure ``EMPTY_ACK``, not a quiet empty chart.
* **SO-8, one clock.** Every timestamp is ISO 8601 carrying the Karachi
  offset, resolved server side by ``src/data/sessions.py``. The browser never
  derives a session from its own clock.
* **One authority per question.** Bars come from ``src/data/tape_bars.py``,
  session facts from ``src/data/sessions.py``, the portal panel from
  ``src/data/market_snapshot.py``. This package wraps them; it does not
  restate them.

Nothing in this package registers a schedule, a daemon or a watcher. The
service is a foreground process a human starts, and it refuses to start under
GitHub Actions, where the minutes belong to the market-hours scans.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: The service's own version, reported by /api/health. The wire schema has
#: its own version in ``charts.contract.SCHEMA_VERSION``; the two move
#: independently, because a service patch must not force a client change.
__version__ = "0.1.0"
