"""The terminal window: the Quant of Rehan desk on a real backend.

Owner orders of 2026-11-03, in sequence: JARVIS HUD looks; buying and
selling volume must be measured and never fall; the terminal must never
claim the market is closed while it is open; the home board is the top
three scrips of volume by the venue's own count. Every screen here is
backed by `src.desktop.bridge`, which reads the real backend. A value the
backend does not carry prints as a dash, never as a zero.
"""

from __future__ import annotations

import base64
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
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
FEED_RESTART_CAP = 24
LAG_EVERY_TICKS = 15

#: Engine states that describe the market, not a trade; the signal card
#: must not print MARKET_CLOSED as the latest signal.
MARKET_STATES = ("MARKET_CLOSED", "MARKET_OPEN", "SCANNING",
                 "CANDIDATE_FOUND", "DATA_BLOCKED")

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
    arrow = "\u25b2" if value >= 0 else "\u25bc"
    return f"{arrow} {abs(value):.2f}%"


def _volume(value) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def _millions(value) -> str:
    if value is None:
        return "-"
    return f"{value / 1_000_000:.1f}M"


def _age(value) -> str:
    if value is None:
        return "-"
    return f"{int(value)}s"


def _ago(seconds) -> str:
    if not isinstance(seconds, (int, float)):
        return "unknown age"
    if seconds < 90:
        return f"{int(seconds)}s old"
    if seconds < 5400:
        return f"{int(seconds // 60)}m old"
    return f"{seconds / 3600:.1f}h old"


def _greeting(moment) -> str:
    hour = moment.hour
    if hour < 5:
        return "Working late, Mr. Rehan."
    if hour < 12:
        return "Good morning, Mr. Rehan."
    if hour < 17:
        return "Good afternoon, Mr. Rehan."
    return "Good evening, Mr. Rehan."


def _share(value) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.0f}%"


class TaskThread(QThread):
    """Runs one callable off the UI thread."""

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


class SparkDots(QWidget):
    """A dotted mini chart: one column of 2px dots per point."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._values: list = []
        self._colour = PALETTE["green"]
        self.setFixedHeight(28)

    def set_series(self, values: list, rising: bool) -> None:
        self._values = list(values or [])
        self._colour = PALETTE["green"] if rising else PALETTE["red"]
        self.update()

    # Qt calls paintEvent by framework convention; Python never does.
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        if len(self._values) < 2:
            return
        painter = QPainter(self)
        width, height = self.width(), self.height()
        lo, hi = min(self._values), max(self._values)
        span = (hi - lo) or 1.0
        gap_x = max(2, (width - 4) // len(self._values))
        baseline = height - 3
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._colour))
        for index, value in enumerate(self._values):
            x = 2 + index * gap_x
            top = 2 + int((baseline - 2) * (1.0 - (value - lo) / span))
            for y in range(baseline, top - 2, -4):
                painter.drawRect(x, y, 2, 2)


def _board(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame(objectName="board")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 10)
    layout.setSpacing(6)
    layout.addWidget(QLabel(title, objectName="sectionLabel"))
    return frame, layout


def _metric_row(layout: QVBoxLayout, name: str) -> QLabel:
    row = QHBoxLayout()
    row.setSpacing(10)
    label = QLabel(name, objectName="sectionLabel")
    label.setFixedWidth(150)
    value = QLabel("-", objectName="valueMono")
    value.setWordWrap(True)
    row.addWidget(label)
    row.addWidget(value, 1)
    layout.addLayout(row)
    return value


class MainWindow(QMainWindow):
    """The terminal: status line, six real pages, one clock."""

    PAGES = ("HOME", "LIVE MARKET", "ORDER FLOW", "SIGNALS",
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
        self._feed_restarts = 0
        self._start_feed_allowed = start_feed
        self._tick_count = 0
        self._flow = bridge.FlowMemory()
        self._last_health: dict | None = None
        self._lag: dict = {}

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self._build_topbar())
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
        bodybox.setContentsMargins(14, 10, 14, 8)
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

        self._seed_flow()
        self._seed_banked()
        if start_feed:
            self.start_feed()

    # --------------------------------------------------------------- chrome
    def _build_topbar(self) -> QWidget:
        bar = QFrame(objectName="topbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 4, 12, 4)
        row.setSpacing(8)

        self.link_chip = QLabel("LINK -", objectName="chip")
        self.phase_chip = QLabel("-", objectName="chip")
        row.addWidget(self.link_chip)
        row.addWidget(self.phase_chip)
        row.addStretch(1)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("\u25c6  Q U A N T  O F  R E H A N  \u25c6",
                       objectName="brand")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(title)
        brand.addWidget(QLabel("P S X ' S   K M I A L L   I N D E X",
                               objectName="brandSub",
                               alignment=Qt.AlignmentFlag.AlignCenter))
        row.addLayout(brand)
        row.addStretch(1)

        self.index_chip = QLabel("KSE100 -", objectName="chip")
        self.clock = QLabel("-", objectName="clock")
        row.addWidget(self.index_chip)
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
        flags = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                 if align_right else Qt.AlignmentFlag.AlignLeft
                 | Qt.AlignmentFlag.AlignVCenter)
        item.setTextAlignment(flags)
        if colour is not None:
            item.setForeground(QColor(colour))

    # ------------------------------------------------------------ overview
    def _build_overview(self) -> QWidget:
        page = QWidget()
        columns = QHBoxLayout(page)
        columns.setSpacing(10)

        left = QWidget()
        left.setFixedWidth(330)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        core, core_layout = _board("\u25c6 QUANT CORE")
        self.core_state = QLabel("-", objectName="stat")
        self.core_greeting = QLabel("-", objectName="note")
        self.core_session = QLabel("-", objectName="note")
        self.core_session.setWordWrap(True)
        core_layout.addWidget(self.core_state)
        core_layout.addWidget(self.core_greeting)
        core_layout.addWidget(self.core_session)
        left_layout.addWidget(core)

        tele, tele_layout = _board("\u25c6 TELEMETRY")
        self.tele = {}
        for name in ("LINK", "FEED", "PHASE", "NEXT", "SCAN", "FLOW", "T"):
            self.tele[name] = _metric_row(tele_layout, name)
        left_layout.addWidget(tele)

        buying, buying_layout = _board("\u25c6 BUYING NOW  (TAPE MEASURED)")
        self.buying_rows = []
        for _ in range(3):
            line = QLabel("-", objectName="valueMono")
            buying_layout.addWidget(line)
            self.buying_rows.append(line)
        self.buying_note = QLabel("-", objectName="note")
        self.buying_note.setWordWrap(True)
        buying_layout.addWidget(self.buying_note)
        left_layout.addWidget(buying)
        left_layout.addStretch(1)
        columns.addWidget(left)

        right = QVBoxLayout()
        right.setSpacing(10)

        status, status_layout = _board("\u25c6 QUANT STATUS")
        head = QHBoxLayout()
        self.status_chip = QLabel("-", objectName="chipCyan")
        self.status_where = QLabel("-", objectName="note")
        self.status_count = QLabel("TODAY 0/0", objectName="note")
        self.status_count.setStyleSheet(
            "color: %s; font-weight: 700;" % PALETTE["green"])
        head.addWidget(self.status_chip)
        head.addSpacing(6)
        head.addWidget(self.status_where, 1)
        head.addWidget(self.status_count)
        status_layout.addLayout(head)
        self.status_detail = QLabel("-", objectName="note")
        self.status_detail.setWordWrap(True)
        status_layout.addWidget(self.status_detail)
        right.addWidget(status)

        signal, signal_layout = _board(
            "\u25c6 LATEST SIGNAL  (LOCAL ENGINE RECORD)")
        self.signal_headline = QLabel("-", objectName="statSmall")
        self.signal_detail = QLabel("-", objectName="valueMono")
        self.signal_detail.setWordWrap(True)
        self.signal_meta = QLabel("-", objectName="note")
        self.signal_meta.setWordWrap(True)
        signal_layout.addWidget(self.signal_headline)
        signal_layout.addWidget(self.signal_detail)
        signal_layout.addWidget(self.signal_meta)
        right.addWidget(signal)

        flow, flow_layout = _board(
            "\u25c6 TOP 3 SCRIPS OF VOLUME  -  B/S/T MONEY FLOW")
        index_row = QHBoxLayout()
        index_row.setSpacing(8)
        self.index_big = QLabel("-", objectName="statSmall")
        self.index_change = QLabel("-", objectName="valueMono")
        self.index_spark = SparkDots()
        self.index_spark.setFixedWidth(220)
        index_row.addWidget(self.index_big)
        index_row.addWidget(self.index_change)
        index_row.addStretch(1)
        index_row.addWidget(self.index_spark)
        flow_layout.addLayout(index_row)
        flow_layout.addSpacing(4)

        header = QHBoxLayout()
        header.setSpacing(8)
        for caption, width, align in (("#", 24, Qt.AlignmentFlag.AlignLeft),
                                      ("SCRIP", 92, Qt.AlignmentFlag.AlignLeft),
                                      ("PRICE", 92, Qt.AlignmentFlag.AlignRight),
                                      ("BUY", 118, Qt.AlignmentFlag.AlignRight),
                                      ("SELL", 118, Qt.AlignmentFlag.AlignRight),
                                      ("TOTAL", 128, Qt.AlignmentFlag.AlignRight),
                                      ("CHART", 110, Qt.AlignmentFlag.AlignRight)):
            label = QLabel(caption, objectName="sectionLabel")
            label.setFixedWidth(width)
            label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(label)
        flow_layout.addLayout(header)

        self.flow_rows = []
        for rank in range(1, 4):
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            cells = {
                "rank": QLabel(str(rank), objectName="note"),
                "symbol": QLabel("-", objectName="valueMono"),
                "price": QLabel("-", objectName="valueMono"),
                "buy": QLabel("-", objectName="valueMono"),
                "sell": QLabel("-", objectName="valueMono"),
                "total": QLabel("-", objectName="valueMono"),
                "chart": SparkDots(),
            }
            cells["rank"].setFixedWidth(24)
            cells["symbol"].setFixedWidth(92)
            cells["price"].setFixedWidth(92)
            cells["price"].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells["buy"].setFixedWidth(118)
            cells["buy"].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells["buy"].setStyleSheet(f"color: {PALETTE['green']};")
            cells["sell"].setFixedWidth(118)
            cells["sell"].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells["sell"].setStyleSheet(f"color: {PALETTE['red']};")
            cells["total"].setFixedWidth(128)
            cells["total"].setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            cells["chart"].setFixedWidth(110)
            row_layout.addWidget(cells["rank"])
            row_layout.addWidget(cells["symbol"])
            row_layout.addWidget(cells["price"])
            row_layout.addWidget(cells["buy"])
            row_layout.addWidget(cells["sell"])
            row_layout.addWidget(cells["total"])
            row_layout.addWidget(cells["chart"])
            flow_layout.addLayout(row_layout)
            self.flow_rows.append(cells)

        self.flow_note = QLabel("-", objectName="note")
        self.flow_note.setWordWrap(True)
        flow_layout.addStretch(1)
        flow_layout.addWidget(self.flow_note)
        right.addWidget(flow, 1)
        columns.addLayout(right, 1)
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
            "read-only Eclear snapshot wire; sides are not carried by the "
            "wire, so every measured or inferred figure is labelled where "
            "it appears.", objectName="note")
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
        self.order_note = QLabel(
            "measured from the banked tape per print window. the BUY and "
            "SELL columns here are INFERRED (print at the ask or bid, then "
            f"the tick rule). the registry records Level-2 as {depth}. the "
            "home page's B/S uses the same window rule, accumulated for the "
            "session and never decreasing.", objectName="note")
        self.order_note.setWordWrap(True)
        layout.addWidget(self.order_note)
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
        panel, panel_layout = _board("\u25c6 LOCAL ENGINE RECORD")
        self.engine_state = QLabel("-", objectName="statSmall")
        self.engine_detail = QLabel("-", objectName="valueMono")
        self.engine_detail.setWordWrap(True)
        self.engine_meta = QLabel("-", objectName="note")
        self.engine_meta.setWordWrap(True)
        self.engine_age = QLabel("-", objectName="note")
        self.engine_age.setWordWrap(True)
        panel_layout.addWidget(self.engine_state)
        panel_layout.addWidget(self.engine_detail)
        panel_layout.addWidget(self.engine_meta)
        panel_layout.addWidget(self.engine_age)
        layout.addWidget(panel)
        run_panel, run_layout = _board("\u25c6 RUN ONE LOCAL SCAN")
        note = QLabel(
            "Runs the existing engine once on the day's banked tape. The "
            "cloud session loop remains the authority; NO TRADE is a valid "
            "answer. The market phase above is the session law's, never the "
            "record's.", objectName="note")
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
        panel, panel_layout = _board("\u25c6 READ-ONLY FEED")
        self.health_state = QLabel("-", objectName="statSmall")
        panel_layout.addWidget(self.health_state)
        self.health_cells = {}
        for name in ("STATE", "HEARTBEAT AGE", "LAST FRAME", "MESSAGES",
                     "TICKS", "RECONNECTS", "ERRORS", "UNIVERSE",
                     "WATCHDOG"):
            self.health_cells[name] = _metric_row(panel_layout, name)
        layout.addWidget(panel)
        panel2, layout2 = _board("\u25c6 RECORDER")
        self.recorder_cells = {}
        for name in ("CAPTURE FILE", "FILE SIZE", "SESSION", "WIRE LAG",
                     "WIRE FRAME AGE"):
            self.recorder_cells[name] = _metric_row(layout2, name)
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
        panel, panel_layout = _board("\u25c6 TERMINAL")
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
        if self._live:
            return
        task = TaskThread(lambda: bridge.quote_rows(limit=400), self)
        task.done.connect(self._seed_done)
        task.failed.connect(self._task_failed)
        self._tasks.add(task)
        task.start()

    def _seed_done(self, rows: list) -> None:
        for row in rows:
            if row.symbol and row.symbol not in self._live:
                self._live[row.symbol] = row
        self._render_live()

    def _seed_flow(self) -> None:
        """Day-cumulative state and charts from today's tape, once."""

        def run():
            from src.data import tick_volume

            # Session-cumulative board: the newest tape of the day is used
            # even when the feed has been quiet, and its age is labelled.
            rows = bridge.quote_rows(limit=400,
                                     max_age_seconds=6 * 3600)
            capture = bridge.capture_for(None)
            flows = (tick_volume.session_flow(capture)
                     if capture.is_file() else {})
            symbols = [row.symbol for row in rows[:8]]
            series, index_values, _note = bridge.spark_series(symbols)
            return {"rows": rows, "flows": flows, "series": series,
                    "index": index_values}

        task = TaskThread(run, self)
        task.done.connect(self._seed_flow_done)
        task.failed.connect(self._task_failed)
        self._tasks.add(task)
        task.start()

    def _seed_flow_done(self, payload: dict) -> None:
        self._flow.seed(payload.get("rows") or [],
                        payload.get("flows") or {},
                        series=payload.get("series") or {},
                        index_values=payload.get("index") or [])
        self._render_flow()

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

    def stop_feed(self) -> None:
        feed, self._feed = self._feed, None
        if feed is not None:
            feed.stop()

    def _on_quotes(self, quotes: list) -> None:
        self._flow.observe(quotes)
        for quote in quotes:
            row = bridge.quote_from_update(quote)
            if row.symbol:
                self._live[row.symbol] = row
        self._render_live()
        self._render_flow()

    def _on_index(self, payload: dict) -> None:
        self._index = payload
        self._flow.observe_index(payload.get("value"))
        self._render_index()

    def _on_market(self, payload: dict) -> None:
        return None

    # -------------------------------------------------------------- renders
    def _render_index(self) -> None:
        value = self._index.get("value")
        change = self._index.get("change")
        pct = self._index.get("change_pct")
        if isinstance(value, (int, float)):
            self.index_big.setText(f"KSE100  {value:,.2f}")
            if isinstance(change, (int, float)):
                sign = "+" if change >= 0 else ""
                arrow = "\u25b2" if change >= 0 else "\u25bc"
                colour = (PALETTE["green"] if change >= 0
                          else PALETTE["red"])
                text = f"{arrow} {sign}{change:,.2f}"
                if isinstance(pct, (int, float)):
                    text += f"  ({sign}{pct:.2f}%)"
                self.index_change.setText(text)
                self.index_change.setStyleSheet(f"color: {colour};")
                chip = f"KSE100 {value:,.2f}  {sign}{change:,.2f}"
            else:
                self.index_change.setText("-")
                chip = f"KSE100 {value:,.2f}"
            self.index_chip.setText(chip)
        else:
            self.index_big.setText("KSE100  -")
            self.index_change.setText("-")
            self.index_chip.setText("KSE100 -")

    def _render_live(self) -> None:
        limit = int(self.settings.get("max_symbols", 80))
        rows = sorted(self._live.values(),
                      key=lambda row: (-(row.volume or 0), row.symbol))[:limit]
        table = self.table
        table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            change_colour = None
            if isinstance(row.change_pct, (int, float)):
                change_colour = (PALETTE["green"] if row.change_pct >= 0
                                 else PALETTE["red"])
            age_colour = None
            if isinstance(row.age_seconds, (int, float)) and \
                    row.age_seconds > 120:
                age_colour = PALETTE["faint"]
            self._cell(table, index, 0, row.symbol)
            self._cell(table, index, 1, _dash(row.last),
                       align_right=True, colour=PALETTE["bright"])
            self._cell(table, index, 2, _pct(row.change_pct),
                       align_right=True, colour=change_colour)
            self._cell(table, index, 3, _dash(row.bid), align_right=True)
            self._cell(table, index, 4, _dash(row.ask), align_right=True)
            self._cell(table, index, 5, _dash(row.spread, 2),
                       align_right=True)
            self._cell(table, index, 6, _volume(row.volume),
                       align_right=True)
            self._cell(table, index, 7, _age(row.age_seconds),
                       align_right=True, colour=age_colour)
        self.live_count.setText(f"{len(self._live)} symbols banked today")
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().upper()
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            visible = not needle or (item is not None
                                     and needle in item.text())
            self.table.setRowHidden(index, not visible)

    def _render_flow(self) -> None:
        """Top three scrips by venue volume, with measured money flow."""
        rows = self._flow.rows(limit=12)
        charts = self._flow.chart_series(limit=8)
        top = rows[:3]
        for index, cells in enumerate(self.flow_rows):
            if index < len(top):
                row = top[index]
                cells["symbol"].setText(row["symbol"])
                cells["price"].setText(_dash(row.get("price")))
                measured = ((row.get("buy_volume") or 0)
                            + (row.get("sell_volume") or 0))
                cells["buy"].setText(
                    _volume(row.get("buy_volume")) if measured else "-")
                cells["sell"].setText(
                    _volume(row.get("sell_volume")) if measured else "-")
                cells["total"].setText(_volume(row.get("volume")))
                series = charts.get(row["symbol"]) or []
                cells["chart"].set_series(
                    series,
                    rising=len(series) > 1 and series[-1] >= series[0])
            else:
                cells["symbol"].setText("-")
                cells["price"].setText("-")
                cells["buy"].setText("-")
                cells["sell"].setText("-")
                cells["total"].setText("-")
                cells["chart"].set_series([], rising=True)
        index_series = self._flow.index_series()
        self.index_spark.set_series(
            index_series,
            rising=len(index_series) > 1
            and index_series[-1] >= index_series[0])
        buying = [row for row in rows
                  if (row.get("buy_volume") or 0) > 0]
        buying.sort(key=lambda row: -(row.get("buy_volume") or 0))
        for index, line in enumerate(self.buying_rows):
            if index < len(buying):
                row = buying[index]
                line.setText(
                    f"{row['symbol']}   {_millions(row.get('buy_volume'))} "
                    f"bought   {_share(row.get('buy_share'))} of the tape")
            else:
                line.setText("-")
        self.buying_note.setText(
            "measured buying volume this session, largest first"
            if rows else "waiting for the tape")
        last_frame = ((self._last_health or {}).get("last_frame_at")
                      or "-")
        self.flow_note.setText(
            f"{self._flow.basis_note()}   last frame {last_frame}")

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
            values_rows.append((
                str(row.get("symbol", "-")),
                _dash(row.get("obi_top1")),
                _dash(row.get("cvd_inferred"), 0),
                _dash(row.get("buy_volume_inferred"), 0),
                _dash(row.get("sell_volume_inferred"), 0),
                _dash(row.get("session_vwap")),
                _dash(row.get("spread")),
                _dash(row.get("windows"), 0),
            ))
        table = self.flow_table
        table.setRowCount(len(values_rows))
        for row_index, values in enumerate(values_rows):
            for column, text in enumerate(values):
                self._cell(table, row_index, column, text,
                           align_right=column > 0)
        for index, row in enumerate(rows):
            colour = (PALETTE["green"] if (row.get("volume_delta") or 0) >= 0
                      else PALETTE["red"])
            item = table.item(index, 2)
            if item is not None:
                item.setForeground(QColor(colour))
        self.flow_button.setEnabled(True)
        if rows:
            self.statusBar().showMessage(
                f"order flow: {len(rows)} symbols, inferred sides, "
                "registry basis attached", 6000)

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
        self._tick_count += 1
        moment = datetime.now(bridge.KARACHI)
        state = bridge.session_status(moment)
        phase = state.get("phase", "-")
        live = bool(state.get("market_open"))

        self.phase_chip.setText(f"{phase} {'ONLINE' if live else 'CLOSED'}")
        self.phase_chip.setObjectName("chipLive" if live else "chip")
        self.phase_chip.style().unpolish(self.phase_chip)
        self.phase_chip.style().polish(self.phase_chip)

        fraction, _label = bridge.session_progress(moment)
        self.sessionbar.setValue(int(fraction * 1000))
        self.clock.setText(f"{moment:%Y-%m-%d  %H:%M:%S}  PKT")

        self._watchdog_feed(state)
        health = self._render_feed_health()
        self._last_health = health

        self.core_state.setText("SCANNING" if live else "STANDBY")
        self.core_greeting.setText(_greeting(moment))
        band = state.get("live_band") or {}
        event = state.get("next_event") or {}
        bits = []
        if band:
            bits.append(f"band {band.get('open', '-')}-{band.get('close', '-')}")
        if event:
            bits.append(f"{event.get('event', '')} {event.get('at_pk', '')}")
        self.core_session.setText("  |  ".join(bits) or "-")

        self.status_chip.setText("ONLINE" if live else "CLOSED")
        self.status_where.setText(
            f"Karachi {moment:%Y-%m-%d %H:%M} PKT")
        self.status_detail.setText(
            ("Market is trading; the read-only tape is being banked."
             if live else
             "The market is closed; the terminal reads the banked tape."))

        self.tele["LINK"].setText("UP" if live else "IDLE")
        self.tele["FEED"].setText(
            f"{health['state']}   {self._age_text(health)}")
        self.tele["PHASE"].setText(phase)
        self.tele["NEXT"].setText(
            f"{event.get('event', '')} {event.get('at_pk', '')}".strip()
            if event else "-")
        self.tele["SCAN"].setText("1S LIVE" if live else "OFF-SESSION")
        scrips = self._flow.row_count()
        self.tele["FLOW"].setText(
            f"{'ON' if scrips else 'WAITING'}   {scrips} scrips")
        lag = self._lag
        self.tele["T"].setText(
            f"{lag.get('median', '-')}s median wire lag"
            if lag.get("median") is not None else "-")

        self._render_decision()
        self._render_flow()
        self._render_health(health, state, lag)
        if not self._live:
            self._seed_banked()

    @staticmethod
    def _age_text(health: dict) -> str:
        age = health.get("age_seconds")
        if isinstance(age, (int, float)):
            return f"{age:.0f}s"
        return "-"

    def _watchdog_feed(self, state: dict) -> None:
        if not state.get("market_open"):
            return
        if self._feed is not None and self._feed.isRunning():
            return
        if self._feed is not None:
            dead, self._feed = self._feed, None
            dead.stop()
        if not self._start_feed_allowed:
            return
        if not self.settings.get("auto_start_feed", True):
            return
        if self._feed_restarts >= FEED_RESTART_CAP:
            return
        self._feed_restarts += 1
        self.start_feed()
        self.statusBar().showMessage(
            f"feed watchdog: restart {self._feed_restarts}/"
            f"{FEED_RESTART_CAP}", 10000)

    def _render_feed_health(self) -> dict:
        health = bridge.feed_health()
        label = str(health["state"])
        states = {"FRESH": ("chipLive", "LIVE"),
                  "CONNECTED": ("chipCyan", "CONNECTED"),
                  "STALE": ("chipWarn", "LAGGING"),
                  "DEAD": ("chipRisk", "OFFLINE"),
                  "UNKNOWN": ("chip", "UNKNOWN")}
        chip_object, chip_word = states.get(label, ("chip", label))
        text = chip_word
        age = health.get("age_seconds")
        if isinstance(age, (int, float)):
            text = f"{chip_word} {age:.0f}s"
        self.link_chip.setText(text)
        self.link_chip.setObjectName(chip_object)
        self.link_chip.style().unpolish(self.link_chip)
        self.link_chip.style().polish(self.link_chip)
        return health

    def _render_health(self, health: dict, state: dict, lag: dict) -> None:
        label = str(health.get("state"))
        colour = (PALETTE["green"] if label == "FRESH"
                  else PALETTE["red"] if label in ("DEAD", "STALE")
                  else PALETTE["gold"])
        self.health_state.setText(f"{label}")
        self.health_state.setStyleSheet(f"color: {colour};")
        counters = health.get("counters") or {}
        self.health_cells["STATE"].setText(
            f"{health.get('detail') or '-'}")
        self.health_cells["HEARTBEAT AGE"].setText(
            self._age_text(health))
        self.health_cells["LAST FRAME"].setText(
            str(health.get("last_frame_at") or "-"))
        self.health_cells["MESSAGES"].setText(
            f"{counters.get('messages', 0):,}")
        self.health_cells["TICKS"].setText(
            f"{counters.get('ticks', 0):,}")
        self.health_cells["RECONNECTS"].setText(
            f"{counters.get('reconnects', 0)}")
        self.health_cells["ERRORS"].setText(
            f"{counters.get('errors', 0)}")
        self.health_cells["UNIVERSE"].setText(
            f"{health.get('universe_size') or '-'}")
        self.health_cells["WATCHDOG"].setText(
            f"{self._feed_restarts} restarts this session")
        capture = bridge.capture_for(None)
        self.recorder_cells["CAPTURE FILE"].setText(str(capture))
        self.recorder_cells["FILE SIZE"].setText(
            f"{capture.stat().st_size / 1024 / 1024:.1f} MB"
            if capture.is_file() else "no file yet")
        self.recorder_cells["SESSION"].setText(
            f"{state.get('phase', '-')}   band "
            f"{(state.get('live_band') or {}).get('open', '-')}-"
            f"{(state.get('live_band') or {}).get('close', '-')}")
        if self._tick_count % LAG_EVERY_TICKS == 0 or not self._lag:
            self._lag = bridge.wire_lag()
        lag = self._lag
        if lag.get("median") is not None:
            self.recorder_cells["WIRE LAG"].setText(
                f"median {lag['median']}s   p95 {lag['p95']}s   "
                f"worst {lag['max']}s   ({lag.get('prints')} prints)")
        else:
            self.recorder_cells["WIRE LAG"].setText(
                "no banked frame to measure yet")
        self.recorder_cells["WIRE FRAME AGE"].setText(
            f"{lag.get('newest_age')}s" if lag.get("newest_age")
            is not None else "-")

    def _render_decision(self) -> None:
        record = bridge.session_record()
        state = str(record.get("state") or "-")
        is_trade = state not in MARKET_STATES
        headline = state if is_trade else "NO TRADE TODAY"
        colour = (PALETTE["green"] if state.startswith(("TARGET", "EXITED"))
                  else PALETTE["red"] if state.startswith(("HOLDING",
                                                           "STOP"))
                  else PALETTE["cyan_hi"])
        self.signal_headline.setText(headline)
        self.signal_headline.setStyleSheet(f"color: {colour};")
        self.engine_state.setText(headline)
        self.engine_state.setStyleSheet(f"color: {colour};")

        bits = []
        if record.get("symbol"):
            bits.append(f"{record['symbol']}")
            if record.get("entry_price") is not None:
                bits.append(f"entry {_dash(record.get('entry_price'))}")
            if record.get("target_price") is not None:
                bits.append(f"target {_dash(record.get('target_price'))}")
            if record.get("stop_loss") is not None:
                bits.append(f"stop {_dash(record.get('stop_loss'))}")
            if record.get("exit_price") is not None:
                bits.append(f"exit {_dash(record.get('exit_price'))}")
        self.signal_detail.setText("  |  ".join(bits) or "-")
        self.engine_detail.setText("  |  ".join(bits) or "-")

        recorded = record.get("recorded_at")
        written = "-"
        if recorded:
            try:
                written = datetime.fromisoformat(recorded).strftime("%H:%M")
            except ValueError:
                written = "-"
        age_text = _ago(record.get("record_age_seconds"))
        self.signal_meta.setText(
            f"engine record: {state}, written {written} PKT ({age_text})"
            f"   |   trades {record.get('trades_today')}   scans "
            f"{record.get('scans')}   finalized "
            f"{'yes' if record.get('finalized') else 'no'}")
        self.engine_meta.setText(
            f"day {record.get('day')}   trades today "
            f"{record.get('trades_today')}   scans {record.get('scans')}   "
            f"finalized {'yes' if record.get('finalized') else 'no'}")
        self.engine_age.setText(
            f"record state {state}, written {written} PKT ({age_text}). "
            "The engine writes this file when it runs; the market phase "
            "above is the session law's, not this record's.")
        self.status_count.setText(
            f"TODAY {record.get('trades_today') or 0}/"
            f"{record.get('scans') or 0}")
        if record.get("last_reason"):
            self.signal_meta.setText(
                self.signal_meta.text() + f"   |   {record['last_reason']}")

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
