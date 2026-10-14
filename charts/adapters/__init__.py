"""The adapter layer: every source behind the same small protocol.

Adding a source means writing one file here, not touching the store, the
ingestion loop or the HTTP layer. The registry below is the only place that
knows all of them, so the CLI can name them by string and a test can inject
its own.
"""

from __future__ import annotations

from charts.adapters.base import BarSource, Capabilities
from charts.adapters.portal import PortalSource
from charts.adapters.replay import ReplaySource
from charts.adapters.tape import TapeSource

#: The sources the CLI can start, by the name a human types.
SOURCES = {
    "tape": TapeSource,
    "portal": PortalSource,
    "replay": ReplaySource,
}

__all__ = ["BarSource", "Capabilities", "PortalSource", "ReplaySource",
           "SOURCES", "TapeSource"]
