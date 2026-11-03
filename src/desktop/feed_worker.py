"""The read-only feed thread: the same recorder the cloud runs, in a QThread.

It instantiates `src.data.feed_capture.CaptureSession`, the recorder whose
read-only guard allows exactly three outgoing frame types (MKT-FEED,
EXS-FEED, HELLO). No new socket, no second connection, no authentication:
the terminal reuses the one recorder class this repository already trusts.

Every banked frame is also handed to a Qt signal so the window can update,
while the recorder's own append-only file stays the durable record the rest
of the system reads.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QThread, Signal

from src.data import feed_capture


class _SignallingCapture(feed_capture.CaptureSession):
    """A CaptureSession that reports each banked frame to the window."""

    def __init__(self, symbols: list[str], emit) -> None:
        super().__init__(symbols, duration=None)
        self._emit = emit

    def bank(self, text: str) -> None:
        record = None
        try:
            record = feed_capture.parse_message(text)
        except Exception:  # noqa: BLE001 - a bad frame must not stop the feed
            record = None
        super().bank(text)
        if record is not None:
            self._emit(record)


class FeedThread(QThread):
    """Runs one capture session and emits the rows the window renders."""

    quotes = Signal(list)          # list of quote dicts (relay update shape)
    index = Signal(dict)           # EXS-FEED index update
    market = Signal(dict)          # MKT-STATS market state update
    failed = Signal(str)

    def __init__(self, symbols: list[str], parent=None) -> None:
        super().__init__(parent)
        self._symbols = symbols
        self._session: _SignallingCapture | None = None

    def _emit_record(self, record: dict) -> None:
        update = feed_capture.relay_quote_updates(record)
        if update.get("quotes"):
            self.quotes.emit(update["quotes"])
        if update.get("index"):
            self.index.emit(update["index"])
        if update.get("market_feed"):
            self.market.emit(update["market_feed"])

    def run(self) -> None:  # noqa: D401 - QThread entry
        try:
            session = _SignallingCapture(self._symbols, self._emit_record)
            self._session = session
            session.run()
        except Exception as exc:  # noqa: BLE001 - reported to the window
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            session = self._session
            self._session = None
            if session is not None:
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass

    def stop(self) -> None:
        """Ask the recorder to end at its next wake and wait briefly for it."""
        session = self._session
        if session is not None:
            session.deadline = time.time()
        self.wait(6000)
