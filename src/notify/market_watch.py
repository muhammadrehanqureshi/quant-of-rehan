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
send, without any clock the agent or a workflow waits on. TheOwner order 2026-10-24: the owner's "post market closing" email (16:49
Friday, 15:49 Mon-Thu) is an event of its own, and the loop is the only
work live at that minute, so it emails the end of the post-market
window too. The texts are the owner's sentences, and the
market-email.yml cron jobs stay exactly as they are as a backstop, and
src/notify/owner_email.py's comment ledger keeps each event exactly
once per Karachi day whichever path arrives first.

Nothing here sleeps, waits, rewords the owner's texts, or invents a
state: a send only happens for the phase the session law names at this
instant, and the ledger supplies the exactly-once guarantee across
restarts, double drivers and late fires.

SO-8: every moment this module speaks of is Karachi, Asia/Karachi, UTC+5,
built only through src/data/sessions.py's own helpers (as_karachi,
now_karachi, band_bounds, post_market_window) and never a local or
naive clock here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

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
    "post-close": "The market is post-closed. Quant is offline now.",
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
    mirrors them into the owner's six email events, in the order the
    day lays them out.

    Owner order 2026-10-26: the pre-market email fires when the pre
    market OPENS, 09:15 PKT Monday to Thursday (his words: "even though
    the pre market opens on Monday at 09:15"), not on the scanner's own
    PRE_MARKET state edge at 09:00. sessions.pre_email_due() is that
    window's one answer, the same helper the email crons and the
    catch-up roadmap read, so all three paths agree by construction.
    Friday keeps the 09:00 minute the earlier orders gave it.
    """
    phase, state = memory
    k = sessions.as_karachi(moment)
    if not sessions.session_bands(k.date()):
        return None
    if sessions.pre_email_due(k):
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
        # POST_CLOSE with the market CLOSED happens twice, and both are
        # owner events: right after the last close (before the
        # post-market window) this is the close email, and at or after
        # the window's end (15:49 / 16:49) this is post-close (owner
        # order 2026-10-24). The post window's own edge says which is
        # which, straight from the session law.
        k = sessions.as_karachi(moment)
        window = sessions.post_market_window(k.date())
        if window is not None:
            # The window is band-shaped, so band_bounds builds both of
            # its instants inside the one law (SO-8).
            _p_open, p_close = sessions.band_bounds(k.date(), window)
            if k >= p_close:
                return "post-close", ""
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

    Owner order 2026-10-23 ("a retry that doesn't retry is a fail you
    didn't take seriously"): a send whose attempt hit a raised exception
    used to be silently dropped with the edge now behind it, so a relay
    outage at the exact minute of the break stayed silent for the rest
    of the phase. A failed attempt now books a retry two minutes out,
    and observe() keeps attempting that same event inside the same phase
    until the send lands, the ledger says it is already delivered, or
    the phase itself ends. The ledger still keeps it exactly once.
    """

    RETRY_SECONDS = 120.0

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
        # The instant the next retry of the failed send may run, or None
        # when nothing is in flight.
        self._retry_at: datetime | None = None

    def observe(self, moment: datetime | None = None) -> list[str]:
        """Look once, mail once, on the edge. Returns the markers mailed.

        Never raises for a failed send and never raises instead of a
        scan: an email is the loop's passenger, never its reason to run.
        A failure is logged with its exception and retried
        RETRY_SECONDS later, inside the same phase, until it lands.
        """
        k = moment if moment is not None else self._clock()
        memory = (sessions.market_phase(k).value,
                  sessions.market_state_at(k).value)
        mailed: list[str] = []
        changed = memory != self._last_memory
        if changed:
            self._last_memory = memory
            self._retry_at = None
        elif not (self._retry_at is not None and self._retry_at <= k):
            # Unchanged phase and no retry due: the edge fired once, so
            # this is not another attempt.
            return mailed
        entry = event_for(memory, k)
        if entry is None:
            return mailed
        event, label = entry
        marker = ledger_key(event, label, k.date().isoformat())
        try:
            if self._sender(event, label, k.date().isoformat()):
                mailed.append(marker)
                # Delivered: nothing left in flight for this edge.
                self._retry_at = None
            else:
                # The ledger says already delivered; the event is out.
                self._retry_at = None
        except Exception as exc:  # noqa: BLE001 - email is a passenger
            LOGGER.error("market email '%s' failed: %s: %s",
                         marker, type(exc).__name__, exc)
            self._retry_at = k + timedelta(seconds=self.RETRY_SECONDS)
        return mailed
