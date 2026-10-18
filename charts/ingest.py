"""The ingestion loop: poll a source, store the bars, fan them out.

One thread polls one source for the symbols a chart is actually watching,
upserts what it finds into the store, and publishes a small event per symbol
to every subscriber. The broker source publishes per-symbol snapshots at
roughly 30-second median intervals, so this loop never polls that source faster
than useful. The HTTP layer never talks to a source directly, which keeps a
slow upstream from becoming a slow page.

Two details are worth more than they look:

* **Bounded subscriber queues, drop oldest.** A phone that stops reading
  cannot make the poller block, and cannot make the service grow without
  limit. The dropped-event count is published in the payload notes, so a
  consumer can tell that it missed something instead of silently showing a
  stale chart.
* **Failures are classified, never swallowed.** Each symbol's last error is
  recorded with its category (TIMEOUT, EMPTY_ACK and the rest), and the loop
  keeps the other symbols moving. A symbol that fails every poll is visible
  in ``/api/health`` and in the payload's notes, which is the difference
  between a degraded chart and an empty one.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from charts import sessions
from charts.adapters.base import BarSource
from charts.contract import Bar
from charts.ratelimit import UpstreamError
from charts.store import BarStore


@dataclass
class Subscription:
    """One consumer's event queue, with its own drop counter."""

    symbol: str
    inbox: "queue.Queue[dict]" = field(default_factory=lambda: queue.Queue(64))
    dropped: int = 0

    def publish(self, event: dict) -> None:
        try:
            self.inbox.put_nowait(event)
        except queue.Full:
            # Drop the oldest event so the newest state still arrives: a
            # chart wants the present, not a backlog.
            try:
                self.inbox.get_nowait()
                self.inbox.put_nowait(event)
            except queue.Empty:  # pragma: no cover - racing consumer
                pass
            self.dropped += 1


class Ingestor:
    """Polling loop with subscribers, health, and a testable single step."""

    def __init__(self, store: BarStore, source: BarSource, *,
                 resolution: str, interval_seconds: float = 30.0,
                 clock=sessions.law.as_karachi,
                 sleep=time.sleep):
        self.store = store
        self.source = source
        self.resolution = resolution
        # Do not poll a broker tape faster than its measured per-symbol
        # cadence. Deterministic local sources may use shorter intervals.
        minimum = 30.0 if source.name == "broker_tape" else 0.1
        self.interval_seconds = max(minimum, float(interval_seconds))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.RLock()
        self._watch: dict[str, float] = {}          # symbol -> last request
        self._subs: list[Subscription] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._errors: dict[str, dict] = {}
        self.polls = 0
        self.last_poll_at: str = ""
        self.last_error: str = ""

    # ------------------------------------------------------------ watching
    def watch(self, symbol: str) -> None:
        """Mark a symbol as wanted; the poller keeps it fresh for a while."""
        key = symbol.strip().upper()
        with self._lock:
            self._watch[key] = time.monotonic()

    def unwatch(self, symbol: str) -> None:
        with self._lock:
            self._watch.pop(symbol.strip().upper(), None)

    def watched(self) -> list[str]:
        with self._lock:
            return sorted(self._watch)

    def _keep_watching(self, seconds: float = 900.0) -> None:
        """Drop symbols nobody has asked about for a while.

        A chart that closes its tab must not keep the poller working all day,
        and the project's own law is that nothing here runs without a reason.
        """
        cutoff = time.monotonic() - seconds
        with self._lock:
            for symbol, touched in list(self._watch.items()):
                if touched < cutoff and symbol not in self._subscribed():
                    del self._watch[symbol]

    # --------------------------------------------------------- subscribers
    def subscribe(self, symbol: str) -> Subscription:
        subscription = Subscription(symbol=symbol.strip().upper())
        with self._lock:
            self._subs.append(subscription)
        self.watch(symbol)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            if subscription in self._subs:
                self._subs.remove(subscription)

    def _subscribed(self) -> set[str]:
        return {subscription.symbol for subscription in self._subs}

    def _fan_out(self, symbol: str, bars: list[Bar]) -> None:
        with self._lock:
            targets = [sub for sub in self._subs if sub.symbol == symbol]
        if not targets:
            return
        event = {
            "event": "bars",
            "symbol": symbol,
            "resolution": self.resolution,
            "as_of": self._clock().isoformat(timespec="seconds"),
            "bars": [bar.as_dict() for bar in bars],
        }
        for subscription in targets:
            subscription.publish(event)

    # ------------------------------------------------------------ the loop
    def step(self) -> int:
        """One polling pass over every watched symbol. Returns rows stored.

        Kept public and free of sleeps so a test can drive the whole
        ingestion path deterministically, one pass at a time.
        """
        stored = 0
        symbols = self.watched()
        for symbol in symbols:
            try:
                bars = self.source.latest(symbol, self.resolution)
            except UpstreamError as exc:
                self._record_error(symbol, exc)
                continue
            except Exception as exc:  # noqa: BLE001 - classified, not hidden
                self._record_error(symbol, UpstreamError(
                    UpstreamError.CONNECTION, f"{type(exc).__name__}: {exc}"))
                continue
            if not bars:
                self._record_error(symbol, UpstreamError(
                    UpstreamError.EMPTY_ACK,
                    "the source answered with no bars for this symbol"))
                continue
            stamp = self._clock().isoformat(timespec="seconds")
            observed_at = getattr(self.source, "observation_at", None)
            observed = observed_at(symbol) if callable(observed_at) else stamp
            stored += self.store.upsert(symbol, self.resolution, bars,
                                        self.source.capabilities().source,
                                        updated_at=stamp,
                                        observed_at=observed or stamp)
            self._clear_error(symbol)
            self._fan_out(symbol, bars)
        with self._lock:
            self.polls += 1
            self.last_poll_at = self._clock().isoformat(timespec="seconds")
        self._keep_watching()
        return stored

    def _record_error(self, symbol: str, exc: UpstreamError) -> None:
        with self._lock:
            self._errors[symbol] = {"category": exc.category,
                                    "detail": exc.detail,
                                    "at": self._clock().isoformat(
                                        timespec="seconds")}
            self.last_error = f"{symbol} {exc.category}"
        self.store.note(symbol, self.resolution,
                        f"{exc.category}: {exc.detail}")

    def _clear_error(self, symbol: str) -> None:
        with self._lock:
            self._errors.pop(symbol, None)

    def errors(self) -> dict[str, dict]:
        with self._lock:
            return {symbol: dict(detail)
                    for symbol, detail in self._errors.items()}

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="charts-ingest",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                with self._lock:
                    self.last_error = f"{type(exc).__name__}: {exc}"
            self._stop.wait(self.interval_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)

    def health(self) -> dict:
        with self._lock:
            return {"polls": self.polls,
                    "last_poll_at": self.last_poll_at,
                    "watched": sorted(self._watch),
                    "subscribers": len(self._subs),
                    "dropped_events": sum(sub.dropped for sub in self._subs),
                    "errors": self.errors(),
                    "interval_seconds": self.interval_seconds,
                    "resolution": self.resolution,
                    "source": self.source.capabilities().source.as_dict()}
