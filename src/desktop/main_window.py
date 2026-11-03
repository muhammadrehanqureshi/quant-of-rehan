"""The terminal window: restrained HUD, live tables, one-second clock.

Design laws from the owner's order (2026-11-03): charcoal field, hairline
panels, green up and red risk, thin arc gauges, compact type. Every screen
shown here is backed by `src.desktop.bridge`, which reads the real backend;
a value the backend does not carry prints as a dash, never as a zero.
"""

from __future__ import annotations

import base64
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
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


def _dash(value, digits: int = 2) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}"
    return str(value)


class ArcGauge(QWidget):
    """A thin 270 degree arc: the only drawn decoration in the terminal.

    Values are pushed in, never polled; the widget repaints only when its
    value or label changes, so a live market costs no per-frame animation.
    """

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._label = "-"
        self._caption = caption
        self.setMinimumSize(132, 138)

    def set_value(self, value: float, label: str) -> None:
        if abs(value - self._value) < 0.001 and label == self._label:
            return
        self._value = max(0.0, min(1.0, value))
        self._label = label
        self.update()

    # Qt calls paintEvent by framework convention; Python never does.
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 6, -10, -22)
        span = -270 * 16
        track = QPen(QColor(PALETTE["panel_edge"]))
        track.setWidth(7)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 225 * 16, span)
        colour = PALETTE["green"] if self._value < 1.0 else PALETTE["amber"]
        active = QPen(QColor(colour))
        active.setWidth(7)
        active.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(active)
        painter.drawArc(rect, 225 * 16, int(span * self._value))
        painter.setPen(QColor(PALETTE["ink"]))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                         f"{self._value * 100:.0f}%")
        painter.setPen(QColor(PALETTE["faint"]))
        font.setPointSize(8)
        font.setBold(False)
        painter.setFont(font)
        painter.drawText(self.rect().adjusted(0, self.height() - 30, 0, 0),
                         Qt.AlignmentFlag.AlignHCenter, self._caption)
        painter.drawText(self.rect().adjusted(0, self.height() - 17, 0, 0),
                         Qt.AlignmentFlag.AlignHCenter, self._label)


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


class MainWindow(QMainWindow):
    """The terminal: header, navigation, six real pages, one clock."""

    PAGES = ("OVERVIEW", "LIVE MARKET", "ORDER FLOW", "SIGNALS",
             "SYSTEM HEALTH", "SETTINGS")

    def __init__(self, start_feed: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Quant of Rehan")
        self.resize(1280, 780)
        self.setStyleSheet(stylesheet())
        self.settings = bridge.load_settings()
        self._live: dict[str, bridge.QuoteRow] = {}
        self._feed: FeedThread | None = None
        self._tasks: set[TaskThread] = set()
        self._index: dict = {}
        self._market: dict = {}

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = QListWidget(objectName="nav")
        self.nav.addItems(self.PAGES)
        self.nav.setFixedWidth(180)
        self.nav.currentRowChanged.connect(self._show_page)
        outer.addWidget(self.nav)

        body = QVBoxLayout()
        body.setContentsMargins(20, 14, 20, 10)
        body.setSpacing(12)
        outer.addLayout(body, 1)

        body.addLayout(self._build_header())
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_overview())
        self.stack.addWidget(self._build_live_market())
        self.stack.addWidget(self._build_order_flow())
        self.stack.addWidget(self._build_signals())
        self.stack.addWidget(self._build_health())
        self.stack.addWidget(self._build_settings())

        self.setStatusBar(QStatusBar())
        self.nav.setCurrentRow(0)

        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._clock.start()
        self._tick()

        if start_feed:
            self.start_feed()

    # ------------------------------------------------------------- chrome
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        brand = QVBoxLayout()
        brand.setSpacing(0)
        title = QLabel("QUANT OF REHAN", objectName="brand")
        tag = QLabel("PSX KMIALL TERMINAL / SIGNAL ONLY", objectName="brandSub")
        brand.addWidget(title)
        brand.addWidget(tag)
        row.addLayout(brand)
        row.addStretch(1)
        self.market_pill = QLabel("-", objectName="pill")
        self.feed_pill = QLabel("FEED -", objectName="pill")
        self.clock = QLabel("-", objectName="dim")
        row.addWidget(self.market_pill)
        row.addWidget(self.feed_pill)
        row.addWidget(self.clock)
        line = QFrame(objectName="hairline")
        wrapper = QHBoxLayout()
        wrapper.addWidget(line)
        outer = QVBoxLayout()
        outer.setSpacing(8)
        outer.addLayout(row)
        outer.addLayout(wrapper)
        return outer

    def _panel(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame(objectName="panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        label = QLabel(title, objectName="sectionLabel")
        layout.addWidget(label)
        return frame, layout

    # ------------------------------------------------------------ overview
    def _build_overview(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.addWidget(QLabel("OVERVIEW", objectName="pageTitle"))

        cards = QHBoxLayout()
        cards.setSpacing(12)

        gauge_panel, gauge_layout = self._panel("SESSION")
        self.session_gauge = ArcGauge("BAND ELAPSED")
        gauge_layout.addWidget(self.session_gauge)
        cards.addWidget(gauge_panel, 1)

        index_panel, index_layout = self._panel("KSE100")
        self.index_value = QLabel("-", objectName="value")
        self.index_change = QLabel("-", objectName="dim")
        index_layout.addWidget(self.index_value)
        index_layout.addWidget(self.index_change)
        index_layout.addStretch(1)
        cards.addWidget(index_panel, 2)

        state_panel, state_layout = self._panel("MARKET LAW")
        self.state_phase = QLabel("-", objectName="value")
        self.state_detail = QLabel("-", objectName="dim")
        self.state_detail.setWordWrap(True)
        state_layout.addWidget(self.state_phase)
        state_layout.addWidget(self.state_detail)
        state_layout.addStretch(1)
        cards.addWidget(state_panel, 2)
        layout.addLayout(cards)

        leaders, leaders_layout = self._panel("TOP VOLUME NOW")
        self.leader_rows = []
        for _ in range(3):
            label = QLabel("-", objectName="dim")
            leaders_layout.addWidget(label)
            self.leader_rows.append(label)
        layout.addWidget(leaders)

        decision, decision_layout = self._panel("TODAY'S DECISION (LOCAL RECORD)")
        self.decision_label = QLabel("-", objectName="value")
        self.decision_detail = QLabel("-", objectName="dim")
        self.decision_detail.setWordWrap(True)
        decision_layout.addWidget(self.decision_label)
        decision_layout.addWidget(self.decision_detail)
        layout.addWidget(decision)
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
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter symbol")
        self.filter.setFixedWidth(200)
        self.filter.textChanged.connect(self._apply_filter)
        head.addWidget(self.filter)
        layout.addLayout(head)
        self.table = QTableWidget(0, len(LIVE_COLUMNS))
        self.table.setHorizontalHeaderLabels(LIVE_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        self.live_note = QLabel(
            "read-only Eclear snapshot wire; sides are inferred where shown",
            objectName="dim")
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
        self.flow_table.verticalHeader().setVisible(False)
        self.flow_table.setAlternatingRowColors(True)
        self.flow_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.flow_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.flow_table, 1)
        depth = str(getattr(REGISTRY["footprint"].availability, "value",
                            "UNAVAILABLE")).upper()
        self.flow_note = QLabel(
            "measured from the banked tape. Sides are INFERRED (print at the "
            "ask or bid, then the tick rule). Depth is top of book only; "
            f"the registry records Level-2 as {depth}.",
            objectName="dim")
        self.flow_note.setWordWrap(True)
        layout.addWidget(self.flow_note)
        return page

    # ------------------------------------------------------------- signals
    def _build_signals(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(QLabel("SIGNALS", objectName="pageTitle"))
        panel, panel_layout = self._panel("LOCAL ENGINE RECORD")
        self.signal_state = QLabel("-", objectName="value")
        self.signal_line = QLabel("-", objectName="dim")
        self.signal_line.setWordWrap(True)
        self.signal_extra = QLabel("-", objectName="dim")
        self.signal_extra.setWordWrap(True)
        panel_layout.addWidget(self.signal_state)
        panel_layout.addWidget(self.signal_line)
        panel_layout.addWidget(self.signal_extra)
        layout.addWidget(panel)
        run_panel, run_layout = self._panel("RUN ONE LOCAL SCAN")
        note = QLabel("Runs the existing engine once on the day's banked "
                      "tape. The cloud session loop remains the authority; "
                      "NO TRADE is a valid answer.", objectName="dim")
        note.setWordWrap(True)
        run_layout.addWidget(note)
        self.scan_button = QPushButton("RUN ONE SCAN")
        self.scan_button.clicked.connect(self._run_scan)
        run_layout.addWidget(self.scan_button)
        self.scan_result = QLabel("-", objectName="dim")
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
        layout.addWidget(QLabel("SYSTEM HEALTH", objectName="pageTitle"))
        panel, panel_layout = self._panel("FEED")
        self.health_state = QLabel("-", objectName="value")
        self.health_detail = QLabel("-", objectName="dim")
        self.health_detail.setWordWrap(True)
        self.health_counters = QLabel("-", objectName="dim")
        self.health_counters.setWordWrap(True)
        panel_layout.addWidget(self.health_state)
        panel_layout.addWidget(self.health_detail)
        panel_layout.addWidget(self.health_counters)
        layout.addWidget(panel)
        panel2, layout2 = self._panel("RECORDER")
        self.recorder_label = QLabel("-", objectName="dim")
        self.recorder_label.setWordWrap(True)
        layout2.addWidget(self.recorder_label)
        layout.addWidget(panel2)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ settings
    def _build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(10)
        layout.addWidget(QLabel("SETTINGS", objectName="pageTitle"))
        panel, panel_layout = self._panel("TERMINAL")
        self.auto_feed = QCheckBox("start the read-only feed when the window opens")
        self.auto_feed.setChecked(bool(self.settings.get("auto_start_feed", True)))
        panel_layout.addWidget(self.auto_feed)
        row = QHBoxLayout()
        row.addWidget(QLabel("symbols in the live table", objectName="dim"))
        self.max_symbols = QSpinBox()
        self.max_symbols.setRange(5, 400)
        self.max_symbols.setValue(int(self.settings.get("max_symbols", 80)))
        row.addWidget(self.max_symbols)
        row.addStretch(1)
        panel_layout.addLayout(row)
        save = QPushButton("SAVE SETTINGS")
        save.clicked.connect(self._save_settings)
        panel_layout.addWidget(save)
        path = QLabel(f"settings file: {bridge.settings_path()}", objectName="dim")
        path.setWordWrap(True)
        panel_layout.addWidget(path)
        layout.addWidget(panel)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------- actions
    def _show_page(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)

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
            f"read-only feed started for {len(symbols)} KMIALL symbols", 8000)

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

    def _render_index(self) -> None:
        value = self._index.get("value")
        change = self._index.get("change")
        pct = self._index.get("change_pct")
        self.index_value.setText(f"{value:,.2f}" if isinstance(value, (int, float)) else "-")
        if isinstance(change, (int, float)):
            colour = PALETTE["green"] if change >= 0 else PALETTE["red"]
            sign = "+" if change >= 0 else ""
            self.index_change.setText(
                f'<span style="color:{colour}">{sign}{change:,.2f} '
                f'({sign}{pct:.2f}%)</span>' if isinstance(pct, (int, float))
                else f'<span style="color:{colour}">{sign}{change:,.2f}</span>')
        else:
            self.index_change.setText("-")

    def _render_live(self) -> None:
        limit = int(self.settings.get("max_symbols", 80))
        rows = sorted(self._live.values(),
                      key=lambda row: (-(row.volume or 0), row.symbol))[:limit]
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                row.symbol, _dash(row.last), _dash(row.change_pct),
                _dash(row.bid), _dash(row.ask), _dash(row.spread, 2),
                _dash(row.volume, 0), _dash(row.age_seconds, 0),
            )
            for column, text in enumerate(values):
                item = self.table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.table.setItem(index, column, item)
                if item.text() != text:
                    item.setText(text)
                if column == 2 and isinstance(row.change_pct, (int, float)):
                    item.setForeground(QColor(
                        PALETTE["green"] if row.change_pct >= 0 else PALETTE["red"]))
        self._apply_filter(self.filter.text())

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().upper()
        for index in range(self.table.rowCount()):
            item = self.table.item(index, 0)
            visible = not needle or (item is not None and needle in item.text())
            self.table.setRowHidden(index, not visible)

    def _refresh_order_flow(self) -> None:
        self.flow_button.setEnabled(False)
        self.statusBar().showMessage("recomputing order flow from the tape...")
        limit = int(self.settings.get("max_symbols", 80))
        leaders = [row.symbol for row in sorted(
            self._live.values(), key=lambda r: -(r.volume or 0))[:12]]
        task = TaskThread(lambda: bridge.order_flow_rows(
            symbols=leaders or None, limit=12), self)
        task.done.connect(self._render_order_flow)
        task.failed.connect(self._task_failed)
        task.finished.connect(lambda: self.flow_button.setEnabled(True))
        self._tasks.add(task)
        task.start()

    def _render_order_flow(self, rows: list) -> None:
        self.flow_table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = (
                row.get("symbol", "-"),
                _dash(row.get("obi_top1")),
                _dash(row.get("cvd_inferred"), 0),
                _dash(row.get("buy_volume_inferred"), 0),
                _dash(row.get("sell_volume_inferred"), 0),
                _dash(row.get("session_vwap")),
                _dash(row.get("spread")),
                _dash(row.get("windows"), 0),
            )
            for column, text in enumerate(values):
                item = self.flow_table.item(index, column)
                if item is None:
                    item = QTableWidgetItem()
                    self.flow_table.setItem(index, column, item)
                item.setText(text)
        self.statusBar().showMessage(f"order flow: {len(rows)} symbols", 6000)

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
        self.market_pill.setText(f"{phase} / {'ONLINE' if live else 'OFFLINE'}")
        self.market_pill.setObjectName("pillLive" if live else "pill")
        self.market_pill.style().unpolish(self.market_pill)
        self.market_pill.style().polish(self.market_pill)
        fraction, label = bridge.session_progress(moment)
        self.session_gauge.set_value(fraction, label)
        self.clock.setText(moment.strftime("%Y-%m-%d  %H:%M:%S PKT"))
        self.state_phase.setText(phase)
        detail = state.get("condition_text") or ""
        if state.get("next_event"):
            event = state["next_event"]
            detail = f"{detail} {event.get('event', '')} {event.get('at_pk', '')}".strip()
        self.state_detail.setText(detail or "-")
        health = bridge.feed_health()
        self.feed_pill.setText(f"FEED {health['state']}")
        self.feed_pill.setObjectName(
            "pillLive" if health["state"] == "FRESH" else
            "pillRisk" if health["state"] in ("DEAD", "STALE") else "pill")
        self.feed_pill.style().unpolish(self.feed_pill)
        self.feed_pill.style().polish(self.feed_pill)
        self.health_state.setText(health["state"])
        self.health_detail.setText(health["detail"])
        counters = health.get("counters") or {}
        self.health_counters.setText(
            f"messages {counters.get('messages', 0):,} | ticks "
            f"{counters.get('ticks', 0):,} | reconnects "
            f"{counters.get('reconnects', 0)} | errors "
            f"{counters.get('errors', 0)} | universe "
            f"{health.get('universe_size') or '-'}")
        self.recorder_label.setText(
            f"last frame {health.get('last_frame_at') or '-'} | "
            f"executor {health.get('last_error') or 'clean'}")
        self._render_index()
        self._render_leaders()
        self._render_decision()

    def _render_leaders(self) -> None:
        leaders = sorted(self._live.values(),
                         key=lambda row: -(row.volume or 0))[:3]
        for index, label in enumerate(self.leader_rows):
            if index < len(leaders):
                row = leaders[index]
                colour = (PALETTE["green"] if (row.change_pct or 0) >= 0
                          else PALETTE["red"])
                label.setText(
                    f"{index + 1}.  {row.symbol}   {_dash(row.last)}   "
                    f"{_dash(row.volume, 0)}   {_dash(row.change_pct)}%")
                label.setStyleSheet(f"color: {colour};")
            else:
                label.setText("-")

    def _render_decision(self) -> None:
        record = bridge.trade_decision()
        state = str(record.get("state") or "-")
        self.decision_label.setText(state)
        bits = []
        if record.get("symbol"):
            bits.append(f"{record['symbol']} entry {_dash(record.get('entry_price'))}")
        if record.get("target_price") is not None:
            bits.append(f"target {_dash(record.get('target_price'))}")
        if record.get("stop_loss") is not None:
            bits.append(f"stop {_dash(record.get('stop_loss'))}")
        if record.get("exit_reason"):
            bits.append(str(record["exit_reason"]))
        self.decision_detail.setText(" | ".join(bits) or
                                     (record.get("last_reason") or "-"))
        self.signal_state.setText(state)
        self.signal_line.setText(" | ".join(bits) or "-")
        self.signal_extra.setText(
            f"day {record.get('day')} | trades today {record.get('trades_today')} "
            f"| scans {record.get('scans')} | finalized "
            f"{'yes' if record.get('finalized') else 'no'}")

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
