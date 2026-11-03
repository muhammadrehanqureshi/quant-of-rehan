"""The terminal window: a dense trading desk, live from the banked tape.

Design laws from the owner's order (2026-11-03, reworked after review): flat
panels, monospaced data columns, a compact top bar with a thin session bar,
and every page filled from the banked capture before the live feed says a
word. A value the backend does not carry prints as a dash, never as a zero.
Every screen shown here is backed by `src.desktop.bridge`, which reads the
real backend; the order-flow page carries its registry basis on itself.
"""

from __future__ import annotations

import base64
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.data.registry import REGISTRY  # SO-3: declare the data dependency
from src.desktop import bridge
from src.desktop.feed_worker import FeedThread
from src.desktop.theme import PALETTE, stylesheet

LIVE_COLUMNS = ("SYMBOL", "LAST", "CHG %", "BID", "ASK", "SPREAD",
                "VOLUME", "AGE")
FLOW_COLUMNS = ("SYMBOL", "OBI", "CVD", "BUY", "SELL", "VWAP",
                "SPREAD", "WINDOWS")
TOP_COLUMNS = ("SYMBOL", "LAST", "CHG %", "VOLUME")

#: right-aligned columns by index, per table shape
LIVE_RIGHT = (1, 2, 3, 4, 5, 6, 7)
FLOW_RIGHT = (1, 2, 3, 4, 5, 6, 7)
TOP_RIGHT = (1, 2, 3)

FEED_RESTART_CAP = 24


def _dash(value, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


def _pct(value) -> str:
    if not isinstance(value, (int, float)):
        return "-"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _volume(value) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def _age(value) -> str:
    if value is None:
        return "-"
    return f"{int(value)}s"


class TaskThread(QThread):
    """Runs one callable off the UI thread (a scan, an order-flow read)."""

    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - reported in the status bar
            self.failed.emit(f"{type(exc).__name__}: {exc}")


def _tile(title: str) -> tuple[QFrame, QGridLayout]:
    """A raised stat tile: small gold caption over one or two lines of data."""
    frame = QFrame(objectName="panel")
    layout = QGridLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(2)
    layout.addWidget(QLabel(title, objectName="sectionLabel"), 0, 0)
    return frame, layout


def _panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 12)
    layout.setSpacing(4)
    layout.addWidget(QLabel(title, objectName="sectionLabel"))
    return frame, layout


class MainWindow(QMainWindow):
    """The terminal: top bar, navigation, six real pages, one clock."""

    PAGES = ("OVERVIEW", "LIVE MARKET", "ORDER FLOW", "SIGNALS",
             "SYSTEM HEALTH", "SETTINGS")

    def __init__(self, start_feed: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Quant of Rehan")
        self.resize(1280, 800)
        self.setStyleSheet(stylesheet())
        self.settings = bridge.load_settings()
        self._live: dict[str, bridge.QuoteRow] = {}
        self._feed: FeedThread | None = None
        self._tasks: set[TaskThread] = set()
        self._index: dict = {}
        self._market: dict = {}
        self._feed_restarts = 0

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.topbar = self._build_topbar()
        outer.addWidget(self.topbar)
        self.sessionbar = QProgressBar(objectName="sessionbar")
        self.sessionbar.setTextVisible(False)
        self.sessionbar.setRange(0, 1000)
        outer.addWidget(self.sessionbar)

        payload = QHBoxLayout()
        payload.setContentsMargins(0, 0, 0, 0)
        payload.setSpacing(0)

        self.nav = QListWidget(objectName="nav")
        self.nav.addItems(self.PAGES)
        self.nav.setFixedWidth(170)
        self.nav.currentRowChanged.connect(self._show_page)
        payload.addWidget(self.nav)

        body = QWidget()
        bodybox = QVBoxLayout(body)
        bodybox.setContentsMargins(16, 10, 16, 8)
        bodybox.setSpacing(10)
        self.stack = QStackedWidget()
        bodybox.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_live_market())
        self.stack.addWidget(self._build_order_flow())
        self.stack.addWidget(self._build_signals())
        self.stack.addWidget(self._build_health())
        self.stack.addWidget(self._build_settings())
        payload.addWidget(body, 1)
        outer.addLayout(payload, 1)

        self.setStatusBar(QStatusBar())
        self.nav.setCurrentRow(0)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._tick()

        self._seed_banked()
        if start_feed:
            self.start_feed()

    # --------------------------------------------------------------- chrome
    def _build_topbar(self) -> QWidget:
        bar = QFrame(objectName="topbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(14)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(QLabel("QUANT OF REHAN", objectName="brand"))
        brand.addWidget(QLabel("SIGNAL ONLY. NO ORDERS LEAVE THIS MACHINE.",
                               objectName="brandSub"))
        row.addLayout(brand)
        row.addStretch(1)
        self.market_chip = QLabel("-", objectName="chip")
        self.feed_chip = QLabel("FEED -", objectName="chip")
        self.index_chip = QLabel("", objectName="valueMono")
        row.addWidget(self.index_chip)
        row.addStretch(1)
        row.addWidget(self.market_chip)
        row.addWidget(self.feed_chip)
        self.clock = QLabel("-", objectName="clock")
        row.addWidget(self.clock)
        return bar

    # ------------------------------------------------------ table plumbing
    @staticmethod
    def _style_table(table: QTableWidget, widths: tuple[int, ...],
                     stretch_column: int) -> None:
        header = table.horizontalHeader()
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setShowGrid(True)
        if widths:
            for column, width in enumerate(widths):
                header.setSectionResizeMode(
                    column, QHeaderView.ResizeMode.Interactive)
                if width:
                    table.setColumnWidth(column, width)
            header.setSectionResizeMode(
                stretch_column, QHeaderView.ResizeMode.Stretch)
        else:
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    @staticmethod
    def _cell(table: QTableWidget, row: int, column: int, text: str,
              *, align_right: bool = False, colour: str | None = None,
              ) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        if item.text() != text:
            item.setText(text)
        flags = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter \
            if align_right else Qt.AlignmentFlag.AlignLeft | \
            Qt.AlignmentFlag.AlignVCenter
        item.setTextAlignment(flags)
        if colour is not None:
            item.setForeground(QColor(colour))

    def _fill_table(self, table: QTableWidget, rows: list[tuple],
                    right: tuple[int, ...]) -> None:
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, text in enumerate(values):
                self._cell(table, row_index, column, text,
                           align_right=column in right)

    # ------------------------------------------------------------ overview
    def _build_overview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("OVERVIEW", objectName="pageTitle"))
        head.addStretch(1)
        layout.addLayout(head)

        tiles = QHBoxLayout()
        tiles.setSpacing(10)

        index_tile, index_layout = _tile("KSE100")
        self.index_stat = QLabel("-", objectName="stat")
        self.index_sub = QLabel("index value on the EXS-FEED wire",
                                objectName="note")
        index_layout.addWidget(self.index_stat, 1, 0)
        index_layout.addWidget(self.index_sub, 2, 0)
        tiles.addWidget(index_tile, 3)

        session_tile, session_layout = _tile("SESSION")
        self.session_stat = QLabel("-", objectName="stat")
        self.session_sub = QLabel("-", objectName="note")
        self.session_sub.setWordWrap(True)
        session_layout.addWidget(self.session_stat, 1, 0)
        session_layout.addWidget(self.session_sub, 2, 0)
        tiles.addWidget(session_tile, 3)

        feed_tile, feed_layout = _tile("FEED")
        self.feed_stat = QLabel("-", objectName="stat")
        self.feed_sub = QLabel("-", objectName="note")
        self.feed_sub.setWordWrap(True)
        feed_layout.addWidget(self.feed_stat, 1, 0)
        feed_layout.addWidget(self.feed_sub, 2, 0)
        tiles.addWidget(feed_tile, 3)

        decision_tile, decision_layout = _tile("TODAY'S RECORD")
        self.decision_stat = QLabel("-", objectName="stat")
        self.decision_sub = QLabel("-", objectName="note")
        self.decision_sub.setWordWrap(True)
        decision_layout.addWidget(self.decision_stat, 1, 0)
        decision_layout.addWidget(self.decision_sub, 2, 0)
        tiles.addWidget(decision_tile, 3)
        layout.addLayout(tiles)

        top_panel, top_layout = _panel("TOP VOLUME  -  BANKED AND LIVE")
        self.top_table = QTableWidget(0, len(TOP_COLUMNS))
        self.top_table.setHorizontalHeaderLabels(TOP_COLUMNS)
        self._style_table(self.top_table, (120, 110, 90, 0), 3)
        self.top_table.setFixedHeight(31 + 5 * 26)
        top_layout.addWidget(self.top_table)
        top_layout.addStretch(1)
        layout.addWidget(top_panel)

        detail = QLabel("-", objectName="note")
        detail.setWordWrap(True)
        self.overview_detail = detail
        layout.addWidget(detail)
        layout.addStretch(1)
        return page

    # --------------------------------------------------------- live market
    def _build_live_market(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("LIVE MARKET", objectName="pageTitle"))
        head.addStretch(1)
        self.live_count = QLabel("-", objectName="note")
        head.addWidget(self.live_count)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter symbol")
        self.filter.setFixedWidth(200)
        self.filter.textChanged.connect(self._apply_filter)
        head.addWidget(self.filter)
        layout.addLayout(head)
        self.table = QTableWidget(0, len(LIVE_COLUMNS))
        self.table.setHorizontalHeaderLabels(LIVE_COLUMNS)
        self._style_table(
            self.table, (110, 110, 90, 110, 110, 90, 130, 80), 6)
        layout.addWidget(self.table, 1)
        self.live_note = QLabel(
            "read-only Eclear snapshot wire. sides are not carried by the "
            "wire; anything inferred is labelled where it is shown.",
            objectName="note")
        layout.addWidget(self.live_note)
        return page

    # ---------------------------------------------------------- order flow
    def _build_order_flow(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("ORDER FLOW", objectName="pageTitle"))
        head.addStretch(1)
        self.flow_button = QPushButton("RECOMPUTE FROM TAPE")
        self.flow_button.clicked.connect(self._refresh_order_flow)
        head.addWidget(self.flow_button)
        layout.addLayout(head)
        self.flow_table = QTableWidget(0, len(FLOW_COLUMNS))
        self.flow_table.setHorizontalHeaderLabels(FLOW_COLUMNS)
        self._style_table(self.flow_table, (110, 90, 110, 110, 110, 100,
                                            90, 0), 7)
        layout.addWidget(self.flow_table, 1)
        depth = str(getattr(REGISTRY["footprint"].availability, "value",
                            "UNAVAILABLE")).upper()
        self.flow_note = QLabel(
            "measured from the banked tape. sides are INFERRED (print at "
            "the ask or bid, then the tick rule). depth is top of book "
            f"only; the registry records Level-2 as {depth}.",
            objectName="note")
        self.flow_note.setWordWrap(True)
        layout.addWidget(self.flow_note)
        return page

    # ------------------------------------------------------------- signals
    def _build_signals(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("SIGNALS", objectName="pageTitle"))
        head.addStretch(1)
        layout.addLayout(head)
        panel, panel_layout = _panel("LOCAL ENGINE RECORD")
        self.signal_state = QLabel("-", objectName="levelState")
        self.signal_line = QLabel("-", objectName="valueMono")
        self.signal_line.setWordWrap(True)
        self.signal_extra = QLabel("-", objectName="note")
        self.signal_extra.setWordWrap(True)
        panel_layout.addWidget(self.signal_state)
        panel_layout.addWidget(self.signal_line)
        panel_layout.addWidget(self.signal_extra)
        layout.addWidget(panel)
        run_panel, run_layout = _panel("RUN ONE LOCAL SCAN")
        note = QLabel(
            "Runs the existing engine once on the day's banked tape. The "
            "cloud session loop remains the authority; NO TRADE is a valid "
            "answer.", objectName="note")
        note.setWordWrap(True)
        run_layout.addWidget(note)
        self.scan_button = QPushButton("RUN ONE SCAN")
        self.scan_button.clicked.connect(self._run_scan)
        run_layout.addWidget(self.scan_button)
        self.scan_result = QLabel("-", objectName="valueMono")
        self.scan_result.setWordWrap(True)
        run_layout.addWidget(self.scan_result)
        layout.addWidget(run_panel)
        layout.addStretch(1)
        return page

    # -------------------------------------------------------------- health
    def _build_health(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("SYSTEM HEALTH", objectName="pageTitle"))
        head.addStretch(1)
        layout.addLayout(head)
        panel, panel_layout = _panel("READ-ONLY FEED")
        self.health_state = QLabel("-", objectName="levelState")
        self.health_detail = QLabel("-", objectName="valueMono")
        self.health_detail.setWordWrap(True)
        panel_layout.addWidget(self.health_state)
        panel_layout.addWidget(self.health_detail)
        self.health_counters = QLabel("-", objectName="note")
        self.health_counters.setWordWrap(True)
        panel_layout.addWidget(self.health_counters)
        layout.addWidget(panel)
        panel2, layout2 = _panel("RECORDER")
        self.recorder_label = QLabel("-", objectName="valueMono")
        self.recorder_label.setWordWrap(True)
        layout2.addWidget(self.recorder_label)
        self.recorder_path = QLabel("-", objectName="note")
        self.recorder_path.setWordWrap(True)
        layout2.addWidget(self.recorder_path)
        layout.addWidget(panel2)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ settings
    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(QLabel("SETTINGS", objectName="pageTitle"))
        head.addStretch(1)
        layout.addLayout(head)
        panel, panel_layout = _panel("TERMINAL")
        self.auto_feed = QCheckBox(
            "start the read-only feed when the window opens")
        self.auto_feed.setChecked(bool(self.settings.get("auto_start_feed",
                                                         True)))
        panel_layout.addWidget(self.auto_feed)
        row = QHBoxLayout()
        row.addWidget(QLabel("symbols in the live table", objectName="note"))
        self.max_symbols = QSpinBox()
        self.max_symbols.setRange(5, 400)
        self.max_symbols.setValue(int(self.settings.get("max_symbols", 80)))
        row.addWidget(self.max_symbols)
        row.addStretch(1)
        panel_layout.addLayout(row)
        save = QPushButton("SAVE SETTINGS")
        save.clicked.connect(self._save_settings)
        panel_layout.addWidget(save)
        path = QLabel(f"settings file: {bridge.settings_path()}",
                      objectName="note")
        path.setWordWrap(True)
        panel_layout.addWidget(path)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- actions
    def _show_page(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

    def _seed_banked(self) -> None:
        """Fill the tables from the banked tape before the live feed speaks.

        The live session overrides any symbol it reports; the bank only
        supplies the symbols the live frame has not carried yet, so the
        overview and live market are real data from the first second.
        """
        if self._live:
            return
        task = TaskThread(lambda: bridge.quote_rows(limit=400), self)
        task.done.connect(self._seed_done)
        task.failed.connect(self._task_failed)
        self._tasks.add(task)
        task.start()
        task2 = TaskThread(lambda: bridge.order_flow_rows(limit=12), self)
        task2.done.connect(self._render_order_flow)
        task2.failed.connect(self._task_failed)
        self._tasks.add(task2)
        task2.start()

    def _seed_done(self, rows: list) -> None:
        for row in rows:
            if row.symbol and row.symbol not in self._live:
                self._live[row.symbol] = row
        self._render_live()

    def start_feed(self) -> None:
        if self._feed is not None:
            return
        from src.data import feed_capture

        symbols = feed_capture.load_universe()
        self._feed = FeedThread(symbols, self)
        self._feed.quotes.connect(self._on_quotes)
        self._feed.index.connect(self._on_index)
        self._feed.market.connect(self._on_market)
        self._feed.failed.connect(lambda text: self.statusBar().showMessage(
            f"feed failed: {text}", 15000))
        self._feed.start()
        self.statusBar().showMessage(
            f"read-only feed started for {len(symbols)} KMIALL symbols",
            8000)

    def stop_feed(self) -> None:
        feed, self._feed = self._feed, None
        if feed is not None:
            feed.stop()

    def _on_quotes(self, quotes: list) -> None:
        for quote in quotes:
            row = bridge.quote_from_update(quote)
            if row.symbol:
                self._live[row.symbol] = row
        self._render_live()

    def _on_index(self, payload: dict) -> None:
        self._index = payload
        self._render_index()

    def _on_market(self, payload: dict) -> None:
        self._market = payload

    # -------------------------------------------------------------- renders
    def _render_index(self) -> None:
        value = self._index.get("value")
        change = self._index.get("change")
        pct = self._index.get("change_pct")
        if isinstance(value, (int, float)):
            self.index_stat.setText(f"{value:,.2f}")
            text = "-"
            if isinstance(change, (int, float)):
                sign = "+" if change >= 0 else ""
                colour = (PALETTE["green"] if change >= 0
                          else PALETTE["red"])
                text = f"{sign}{change:,.2f}"
                if isinstance(pct, (int, float)):
                    text += f"  ({sign}{pct:.2f}%)"
                self.index_sub.setStyleSheet(
                    f"color: {colour}; font-weight: 600;")
        else:
            self.index_stat.setText("-")
            text = "index on the EXS-FEED wire"
            self.index_sub.setStyleSheet("")
        self.index_sub.setText(text)
        chip = self.index_chip
        if isinstance(change, (int, float)):
            sign = "+" if change >= 0 else ""
            colour = (PALETTE["green"] if change >= 0 else PALETTE["red"])
            chip.setText(f"KSE100 {value:,.2f}  {sign}{change:,.2f}")
            chip.setStyleSheet(f"color: {colour}; font-family: 'Cascadia "
                               "Mono', Consolas, monospace; font-size: 14px;"
                               " font-weight: 600;")
        elif isinstance(value, (int, float)):
            chip.setText(f"KSE100 {value:,.2f}")
            chip.setStyleSheet("color: %s; font-family: 'Cascadia Mono',"
                               " Consolas, monospace; font-size: 14px;"
                               % PALETTE["bright"] + "; font-weight: 600;")
        else:
            chip.setText("")

    def _render_live(self) -> None:
        limit = int(self.settings.get("max_symbols", 80))
        rows = sorted(self._live.values(),
                      key=lambda row: (-(row.volume or 0), row.symbol))[:limit]
        table = self.table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                row.symbol, _dash(row.last), _pct(row.change_pct),
                _dash(row.bid), _dash(row.ask), _dash(row.spread, 2),
                _volume(row.volume), _age(row.age_seconds),
            )
            change_colour = None
            if isinstance(row.change_pct, (int, float)):
                change_colour = (PALETTE["green"] if row.change_pct >= 0
                                 else PALETTE["red"])
            age_colour = None
            if isinstance(row.age_seconds, (int, float)) and \
                    row.age_seconds > 120:
                age_colour = PALETTE["faint"]
            self._cell(table, index, 0, values[0])
            self._cell(table, index, 1, values[1], align_right=True,
                       colour=PALETTE["bright"])
            self._cell(table, index, 2, values[2], align_right=True,
                       colour=change_colour)
            self._cell(table, index, 3, values[3], align_right=True)
            self._cell(table, index, 4, values[4], align_right=True)
            self._cell(table, index, 5, values[5], align_right=True)
            self._cell(table, index, 6, values[6], align_right=True)
            self._cell(table, index, 7, values[7], align_right=True,
                       colour=age_colour)
        self.live_count.setText(f"{len(self._live)} symbols banked today")
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().upper()
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            visible = not needle or (item is not None
                                     and needle in item.text())
            self.table.setRowHidden(index, not visible)

    def _refresh_order_flow(self) -> None:
        self.flow_button.setEnabled(False)
        self.statusBar().showMessage("recomputing order flow from the tape...")
        task = TaskThread(lambda: bridge.order_flow_rows(limit=12), self)
        task.done.connect(self._render_order_flow)
        task.failed.connect(self._task_failed)
        task.finished.connect(lambda: self.flow_button.setEnabled(True))
        self._tasks.add(task)
        task.start()

    def _render_order_flow(self, rows: list) -> None:
        rows = rows or []
        values_rows = []
        for row in rows:
            cvd = row.get("cvd_inferred")
            buy = row.get("buy_volume_inferred")
            sell = row.get("sell_volume_inferred")
            values_rows.append((
                str(row.get("symbol", "-")),
                _dash(row.get("obi_top1")),
                _dash(cvd, 0),
                _dash(buy, 0),
                _dash(sell, 0),
                _dash(row.get("session_vwap")),
                _dash(row.get("spread")),
                _dash(row.get("windows"), 0),
            ))
        self._fill_table(self.flow_table, values_rows, FLOW_RIGHT)
        for index, row in enumerate(rows):
            colour = (PALETTE["green"] if (row.get("volume_delta") or 0) >= 0
                      else PALETTE["red"])
            self._cell(self.flow_table, index, 2,
                       self.flow_table.item(index, 2).text(),
                       align_right=True, colour=colour)
        self.flow_button.setEnabled(True)
        if rows:
            self.statusBar().showMessage(
                f"order flow: {len(rows)} symbols, inferred sides, "
                "registry basis attached", 6000)
        return None

    def _run_scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.scan_result.setText("scanning...")

        def run():
            from scripts import intraday_pipeline

            moment = datetime.now(bridge.KARACHI)
            return intraday_pipeline.run_scan(moment.strftime("%H:%M"))

        task = TaskThread(run, self)
        task.done.connect(self._scan_done)
        task.failed.connect(self._task_failed)
        task.finished.connect(lambda: self.scan_button.setEnabled(True))
        self._tasks.add(task)
        task.start()

    def _scan_done(self, payload: dict) -> None:
        status = payload.get("status", "?")
        reason = payload.get("reason", "")
        candidate = payload.get("candidate") or {}
        self.scan_result.setText(
            f"{status}: {reason}" + (
                f" | {candidate.get('symbol', '')} entry "
                f"{candidate.get('entry_price', '-')}" if candidate else ""))
        self._render_decision()

    def _task_failed(self, text: str) -> None:
        self.statusBar().showMessage(f"task failed: {text}", 15000)

    def _save_settings(self) -> None:
        self.settings["auto_start_feed"] = self.auto_feed.isChecked()
        self.settings["max_symbols"] = self.max_symbols.value()
        self.settings["window_geometry"] = base64.b64encode(
            bytes(self.saveGeometry())).decode("ascii")
        self.settings["window_state"] = base64.b64encode(
            bytes(self.saveState())).decode("ascii")
        bridge.save_settings(self.settings)
        self.statusBar().showMessage("settings saved", 5000)

    # ---------------------------------------------------------------- tick
    def _tick(self) -> None:
        moment = datetime.now(bridge.KARACHI)
        state = bridge.session_status(moment)
        phase = state.get("phase", "-")
        live = bool(state.get("market_open"))
        self.market_chip.setText(f"{phase} {'ONLINE' if live else 'CLOSED'}")
        self.market_chip.setObjectName("chipLive" if live else "chip")
        self.market_chip.style().unpolish(self.market_chip)
        self.market_chip.style().polish(self.market_chip)

        fraction, label = bridge.session_progress(moment)
        self.sessionbar.setValue(int(fraction * 1000))
        self.sessionbar.setToolTip(label)

        self.clock.setText(f"{moment:%Y-%m-%d  %H:%M:%S} PKT")

        self.session_stat.setText(phase)
        event_bits = []
        condition = state.get("condition_text") or ""
        if condition:
            event_bits.append(condition)
        event = state.get("next_event")
        if event:
            event_bits.append(
                f"{event.get('event', '')} at {event.get('at_pk', '')}")
        self.session_sub.setText(" | ".join(event_bits) or "-")

        self._watchdog_feed(state)
        self._render_feed_health(state)

        self._render_index()
        self._render_leaders()
        self._render_decision()
        self._render_overview_detail(state)
        self._seed_banked()

    def _watchdog_feed(self, state: dict) -> None:
        """Restart a feed that died while the market is open, with a cap.

        This is a state check on the one second clock, not a wait: if the
        thread exited and the session is live, one bounded restart per gap.
        """
        if not state.get("market_open"):
            return
        if self._feed is not None and self._feed.isRunning():
            return
        if self._feed is not None:
            dead, self._feed = self._feed, None
            dead.stop()
        if not self.settings.get("auto_start_feed", True):
            return
        if self._feed_restarts >= FEED_RESTART_CAP:
            return
        self._feed_restarts += 1
        self.start_feed()
        self.statusBar().showMessage(
            f"feed watchdog: restart {self._feed_restarts}/"
            f"{FEED_RESTART_CAP}", 10000)

    def _render_feed_health(self, state: dict) -> None:
        health = bridge.feed_health()
        label = str(health["state"])
        self.feed_chip.setText(f"FEED {label}")
        states = {"FRESH": "chipLive", "CONNECTED": "chip",
                  "STALE": "chipRisk", "DEAD": "chipRisk",
                  "COVERAGE": "chipRisk", "UNKNOWN": "chip"}
        self.feed_chip.setObjectName(states.get(label, "chip"))
        self.feed_chip.style().unpolish(self.feed_chip)
        self.feed_chip.style().polish(self.feed_chip)

        self.feed_stat.setText(label)
        self.feed_stat.setStyleSheet(
            "color: %s;" % (PALETTE["green"] if label == "FRESH"
                            else PALETTE["red"] if label in ("DEAD", "STALE")
                            else PALETTE["gold"]))
        counters = health.get("counters") or {}
        if isinstance(health.get("age_seconds"), (int, float)):
            self.feed_sub.setText(
                f"{health['detail']} | messages "
                f"{counters.get('messages', 0):,} | ticks "
                f"{counters.get('ticks', 0):,} | reconnects "
                f"{counters.get('reconnects', 0)} | errors "
                f"{counters.get('errors', 0)}")
        else:
            self.feed_sub.setText(str(health.get("detail") or "-"))

        self.health_state.setText(label)
        self.health_state.setStyleSheet(
            "color: %s; letter-spacing: 2px;" % (
                PALETTE["green"] if label == "FRESH"
                else PALETTE["red"] if label in ("DEAD", "STALE")
                else PALETTE["gold"]))
        self.health_detail.setText(str(health.get("detail") or "-"))
        self.health_counters.setText(
            f"messages {counters.get('messages', 0):,}   ticks "
            f"{counters.get('ticks', 0):,}   reconnects "
            f"{counters.get('reconnects', 0)}   errors "
            f"{counters.get('errors', 0)}   universe "
            f"{health.get('universe_size') or '-'}")
        self.recorder_label.setText(
            f"last frame {health.get('last_frame_at') or '-'}   executor "
            f"{health.get('last_error') or 'clean'}")
        self.recorder_path.setText(f"capture root: {bridge.CAPTURE_ROOT}")

    def _render_leaders(self) -> None:
        leaders = sorted(self._live.values(),
                         key=lambda row: -(row.volume or 0))[:5]
        rows = []
        for row in leaders:
            colour = None
            if isinstance(row.change_pct, (int, float)):
                colour = (PALETTE["green"] if row.change_pct >= 0
                          else PALETTE["red"])
            rows.append(colour)
        self.top_table.setRowCount(5)
        for index in range(5):
            if index < len(leaders):
                row = leaders[index]
                self._cell(self.top_table, index, 0, row.symbol)
                self._cell(self.top_table, index, 1, _dash(row.last),
                           align_right=True, colour=PALETTE["bright"])
                self._cell(self.top_table, index, 2, _pct(row.change_pct),
                           align_right=True, colour=rows[index])
                self._cell(self.top_table, index, 3, _volume(row.volume),
                           align_right=True)
            else:
                self._cell(self.top_table, index, 0, "-")
                self._cell(self.top_table, index, 1, "-", align_right=True)
                self._cell(self.top_table, index, 2, "-", align_right=True)
                self._cell(self.top_table, index, 3, "-", align_right=True)

    def _render_decision(self) -> None:
        record = bridge.trade_decision()
        state = str(record.get("state") or "-")
        self.decision_stat.setText(state)
        self.decision_stat.setStyleSheet(
            "color: %s;" % (PALETTE["green"] if state.upper().startswith(
                ("TARGET", "EXITED")
            ) else PALETTE["gold"] if state.upper() == "HOLDING"
            else PALETTE["bright"]))
        bits = []
        if record.get("symbol"):
            bits.append(f"{record['symbol']} entry "
                        f"{_dash(record.get('entry_price'))}")
        if record.get("target_price") is not None:
            bits.append(f"target {_dash(record.get('target_price'))}")
        if record.get("stop_loss") is not None:
            bits.append(f"stop {_dash(record.get('stop_loss'))}")
        if record.get("exit_reason"):
            bits.append(str(record["exit_reason"]))
        self.decision_sub.setText(" | ".join(bits)
                                  or (record.get("last_reason") or "-"))
        self.signal_state.setText(state)
        self.signal_state.setStyleSheet(
            "color: %s; letter-spacing: 2px;" % (
                PALETTE["green"] if state.upper().startswith(
                    ("TARGET", "EXITED")
                ) else PALETTE["gold"] if state.upper() == "HOLDING"
                else PALETTE["bright"]))
        self.signal_line.setText(" | ".join(bits) or "-")
        self.signal_extra.setText(
            f"day {record.get('day')}   trades today "
            f"{record.get('trades_today')}   scans {record.get('scans')}   "
            f"finalized {'yes' if record.get('finalized') else 'no'}")

    def _render_overview_detail(self, state: dict) -> None:
        health = bridge.feed_health()
        bits = []
        if state.get("next_event"):
            event = state["next_event"]
            bits.append(f"next: {event.get('event', '')} at "
                        f"{event.get('at_pk', '')}")
        if self._live:
            bits.append(f"{len(self._live)} symbols on the tape today")
        bits.append(str(health.get("detail") or "-"))
        self.overview_detail.setText(" | ".join(bits))

    # -------------------------------------------------------------- window
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.stop_feed()
        for task in list(self._tasks):
            task.wait(3000)
        geometry = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        self.settings["window_geometry"] = geometry
        try:
            bridge.save_settings(self.settings)
        except OSError:
            pass
        super().closeEvent(event)
