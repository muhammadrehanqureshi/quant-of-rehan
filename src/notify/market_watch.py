"""The market event emails, fired by the session loop's own phase table.

Owner order 2026-10-23: the Friday break email never arrived, and the run
history shows why. GitHub's scheduled fires for this repository were
delivered hours late on 2026-10-22 (the 10:30 UTC cron landed at 15:31 UTC)
and not at all on 2026-10-23 morning, so the cron-driven market email jobs
never ran at the edge. GitHub owes nobody a punctual cron; the Cloudflare
relay's own crons dispatch the band loop on time every day, and the band
loop runs continuously through every event the owner is emailed about:

    pre   09:00 PKT (both session shapes)      PRE_MARKET begins
    open  each band's open                     WARMUP or OPEN begins
    break the Friday midday break              BREAK begins
    close each band's close                    POST_CLOSE begins
    post  after the last close                 POST_MARKET begins

So the emails now ride the loop's every-second `decide`, not GitHub's
cron: a phase the loop can already see is an email the loop itself can
send, without any clock the agent or a workflow waits on. The
market-email.yml cron jobs stay exactly as they are as a backstop, and
src/notify/owner_email.py's comment ledger keeps each event exactly once
per Karachi day whichever path arrives first.

Nothing here sleeps, waits, rewords the owner's texts, or invents a
state: a send only happens for the phase the session law names at this
instant, and the ledger supplies the exactly-once guarantee across
restarts, double drivers and late fires.

SO-8: every moment this module speaks of is Karachi, Asia/Karachi, UTC+5,
built only through src/data/sessions.py's own helpers (as_karachi,
now_karachi, band_bounds) and never a local or naive clock here.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.data import sessions
from src.data.sessions import (  # noqa: F401 - re-exported for the tests
    MSG_MARKET_CLOSED,
    MSG_MARKET_OPEN,
)

LOGGER = logging.getLogger("market_watch")

# Owner's exact texts (SO-9). Do not reword, ever. Break is the phone
# notification sentence mirrored from cloud/worker.js and the app, exactly
# as scripts/market_email.py books it; the texts live once in each entry
# point and never drift by construction, because both are taken from the
# session law's own constants where the owner fixed them.
EVENT_TEXTS = {
    "pre": "The market is pre-opened. Quant is online now.",
    "open": MSG_MARKET_OPEN,
    "break": "Market is on a break. Quant is sleeping until the market "
             "reopens.",
    "close": MSG_MARKET_CLOSED,
    "post": "The market is post-opened. Quant is online now.",
}


def band_index(moment: datetime) -> int:
    """Which of today's bands holds this instant (1-based), or 0 if none.

    The owner hears one open text per band, so the second band's open
    must not be hidden behind the first's ledger marker. Used to choose
    the reopen label: the band holding the moment writes
    ``market-open:<date>`` and a second band's edge writes
    ``market-open:<date>:reopen``. The band that is opening AT the
    instant counts here, so band 1's own open edge is index 1 and is
    never mislabelled as a reopen.
    """
    k = sessions.as_karachi(moment)
    for i, band in enumerate(sessions.session_bands(k.date()), start=1):
        start, end = sessions.band_bounds(k.date(), band)
        if start <= k < end:
            return i
    return 0


def event_for(memory: tuple[str, str], moment: datetime) -> tuple[str, str] | None:
    """The (event, label) this instant's (phase, state) speaks, or None.

    Pure and clock free, so the mapping is testable without a network.
    The loop's decide table already runs on exactly these phases; this
    mirrors them into the owner's five email events, in the order the
    day lays them out.
    """
    phase, state = memory
    if not sessions.session_bands(sessions.as_karachi(moment).date()):
        return None
    if state == sessions.MarketState.PRE_MARKET.value:
        return "pre", ""
    if phase in (sessions.MarketPhase.WARMUP.value,
                 sessions.MarketPhase.OPEN.value) and \
            state == sessions.MarketState.MARKET.value:
        return "open", "reopen" if band_index(moment) > 1 else ""
    if phase == sessions.MarketPhase.BREAK.value:
        return "break", ""
    if state == sessions.MarketState.POST_MARKET.value:
        return "post", ""
    if phase == sessions.MarketPhase.POST_CLOSE.value:
        return "close", ""
    return None


def ledger_key(event: str, label: str, day: str) -> str:
    """The exactly-once key: one event, one label, one ISO Karachi day."""
    marker = f"market-{event}:{day}"
    if label:
        marker = f"{marker}:{label.strip()}"
    return marker


class MarketEventWatcher:
    """Emails the owner on a phase edge the loop can already see.

    The watcher holds ONE thing in memory: the (phase, state) it observed
    last. An edge fires an attempt only for its own instant, so a job
    that starts mid-session just attempts the phase it finds; the ledger,
    not this class, says whether that attempt is a send or a no-op, which
    is what keeps restarts, double drivers and late fires exactly-once.
    """

    def __init__(self, sender=None, clock=None) -> None:
        # The sender is injectable so tests never speak to GitHub; the
        # default is the ledger under src/notify/owner_email.py.
        if sender is None:
            from src.notify import owner_email  # local: import cost only

            def sender(event: str, label: str, day) -> bool:
                return bool(owner_email.send(
                    EVENT_TEXTS[event], ledger_key(event, label, day)))
        self._sender = sender
        from src.data.sessions import now_karachi  # local: SO-8 only zone

        self._clock = clock or now_karachi
        self._last_memory: tuple[str, str] | None = None

    def observe(self, moment: datetime | None = None) -> list[str]:
        """Look once, mail once, on the edge. Returns the markers mailed.

        Never raises for a failed send and never raises instead of a
        scan: an email is the loop's passenger, never its reason to run.
        A failure is logged with its exception and the next cycle
        attempts it again only when the phase edge says so.
        """
        k = moment if moment is not None else self._clock()
        memory = (sessions.market_phase(k).value,
                  sessions.market_state_at(k).value)
        mailed: list[str] = []
        if memory != self._last_memory:
            self._last_memory = memory
            entry = event_for(memory, k)
            if entry is None:
                return mailed
            event, label = entry
            marker = ledger_key(event, label, k.date().isoformat())
            try:
                if self._sender(event, label, k.date().isoformat()):
                    mailed.append(marker)
            except Exception as exc:  # noqa: BLE001 - email is a passenger
                LOGGER.error("market email '%s' failed: %s: %s",
                             marker, type(exc).__name__, exc)
        return mailed
