"""Run the whole chart pipeline with no network and no browser.

    python examples/charts_demo.py

It uses the labelled replay source, so nothing here touches the exchange, the
owner's tape or the portal. The point is to show the path a bar takes and to
prove each stage with a real object rather than a description:

    source -> ingestor -> store -> payload builder -> the wire JSON

Two behaviours that matter in production are made visible on purpose:

* the replay series is given a deliberate two minute hole, so the session
  law's gap reporting appears in the output; and
* the second poll rewrites its newest bar, exactly as the minute still
  forming does in a live session, so the store's revision counter appears
  too.

The last block shows a source that cannot answer being classified as a named
failure rather than quietly becoming an empty chart.

The session moment is pinned to one mid-session trading day, and passed to
both the source and the payload builder, so the example prints the same
numbers at 03:00 and at noon instead of an empty chart before the open. The
demo is a demonstration of the pipeline; a live service reads the real clock
instead (the source and the builder both default to it).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from charts.adapters.replay import ReplaySource  # noqa: E402
from charts.contract import RESOLUTION_MINUTE, Bar  # noqa: E402
from charts.ingest import Ingestor  # noqa: E402
from charts.ratelimit import UpstreamError  # noqa: E402
from charts.service import build_payload  # noqa: E402
from charts.store import BarStore  # noqa: E402

#: One Monday, well inside the session: the day this demo always describes.
DEMO_MOMENT = datetime.fromisoformat("2026-10-12T11:00:00+05:00")


def demo_clock() -> datetime:
    return DEMO_MOMENT


class RevisingReplay(ReplaySource):
    """Replay, except that its newest bar is rewritten on the second poll.

    This is the honest simulation of a live minute: the exchange keeps
    printing into the bar that is still forming, the source republishes it,
    and the store replaces the row instead of duplicating it.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.polls = 0

    def latest(self, symbol, resolution=RESOLUTION_MINUTE, since=None):
        bars = super().latest(symbol, resolution, since=since)
        self.polls += 1
        if bars and self.polls > 1:
            last = bars[-1]
            amended = Bar.build(t=last.t, o=last.o, h=last.h + 1.0,
                                l=last.l, c=last.c, v=last.v + 500)
            bars = [*bars[:-1], amended]
        return bars


def main() -> int:
    store = BarStore()
    source = RevisingReplay(symbols=["REPLAY1"], gaps=(4, 5),
                            clock=demo_clock)
    ingestor = Ingestor(store, source, resolution=RESOLUTION_MINUTE)
    ingestor.watch("REPLAY1")

    stored = ingestor.step()
    first = build_payload(store, source, "REPLAY1", RESOLUTION_MINUTE,
                          moment=DEMO_MOMENT)
    print(f"poll 1 stored {stored} bar(s); the series now holds "
          f"{len(first.bars)} bar(s)")

    ingestor.step()
    payload = build_payload(store, source, "REPLAY1", RESOLUTION_MINUTE,
                            moment=DEMO_MOMENT)
    series = store.series("REPLAY1", RESOLUTION_MINUTE)
    print(f"poll 2 stored no new minute but rewrote the forming one: "
          f"{len(payload.bars)} bar(s), "
          f"{series.revisions if series else 0} revision(s) counted")

    body = payload.as_dict()
    body["ok"] = True
    print("\nthe newest three bars on the wire:")
    print(json.dumps(body["bars"][-3:], indent=2))
    print("\ngaps the session law measured (the deliberate hole):")
    print(json.dumps(body["gaps"], indent=2))
    print("\nnotes that travel with the chart:")
    for note in body["notes"]:
        print(f"  - {note}")

    class DeadSource(ReplaySource):
        def latest(self, symbol, resolution=RESOLUTION_MINUTE, since=None):
            raise UpstreamError(UpstreamError.TIMEOUT,
                                "the demo source was told to be unreachable")

    dead = Ingestor(store, DeadSource(symbols=["DEAD1"]),
                    resolution=RESOLUTION_MINUTE)
    dead.watch("DEAD1")
    dead.step()
    print("\nthe dead source was classified, not swallowed:")
    print(json.dumps(dead.health()["errors"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
