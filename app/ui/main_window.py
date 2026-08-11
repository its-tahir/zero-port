"""The ZeroPort window.

This file owns layout, state and user intent. Every OS operation is delegated
to :class:`ScanWorker` on its own thread, so nothing here can block the UI.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QBrush,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import APP_SITE, APP_VERSION
from app.config.config_manager import ConfigManager
from app.models.port_info import PortEntry, TerminationOutcome, TerminationResult
from app.services.scan_worker import ScanWorker
from app.ui import styles
from app.ui.dialogs import (
    ConfirmStopDialog,
    CustomDescriptionsDialog,
    NoticeDialog,
    ProcessDetailsDialog,
    hairline,
    micro,
)
from app.ui.panels import StatePanel
from app.ui.port_table import ENTRY_ROLE, PortTableView
from app.ui.widgets import CaretComboBox

INTERVALS = ((2, "AUTO · 2S"), (5, "AUTO · 5S"), (10, "AUTO · 10S"), (30, "AUTO · 30S"))
STATUS_CLEAR_MS = 6000

# Comfortably past a stop's graceful + forced timeouts, so a shutdown during a
# termination waits it out instead of killing the thread.
SHUTDOWN_WAIT_MS = 9000


class TexturedWidget(QWidget):
    """Paints the near-black base with its grain and dot grid."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QBrush(styles.background_tile()))
        painter.end()


class MainWindow(QMainWindow):
    request_scan = Signal()
    request_stop = Signal(object)
    request_custom = Signal(dict)

    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self.config = config

        self._entries: List[PortEntry] = []
        self._scan_in_flight = False
        self._rescan_queued = False
        self._had_first_result = False
        self._dialog_depth = 0
        self._status_token = 0
        self._pending_stop: Optional[PortEntry] = None
        self._error_message: Optional[str] = None

        self.setWindowTitle("ZeroPort")
        self.setMinimumSize(850, 500)
        self.resize(*self.config.window_size)

        self._build_ui()
        self._build_worker()
        self._build_shortcuts()

        if self.config.window_maximized:
            self.setWindowState(Qt.WindowState.WindowMaximized)

        self.stack.setCurrentWidget(self.state_panel)
        self.state_panel.show_scanning()
        self._apply_interval(
            self.config.refresh_interval if self.config.auto_refresh else 0
        )
        if self.config.load_error:
            self.set_status(self.config.load_error)
        QTimer.singleShot(0, self.refresh)

    # --------------------------------------------------------------- assembly

    def _build_ui(self) -> None:
        root = TexturedWidget()
        self.setCentralWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(34, 22, 34, 16)
        layout.setSpacing(0)

        layout.addLayout(self._build_header())
        layout.addSpacing(18)
        layout.addWidget(hairline(styles.LINE))
        layout.addSpacing(22)
        layout.addLayout(self._build_toolbar())
        layout.addSpacing(16)
        layout.addWidget(self._build_scan_bar())
        layout.addSpacing(4)

        self.table = PortTableView()
        self.table.stop_requested.connect(self.confirm_stop)
        self.table.details_requested.connect(self.show_details)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.delegate.set_custom_ports(
            int(p) for p in self.config.custom_descriptions
        )

        self.state_panel = StatePanel()
        self.state_panel.action_triggered.connect(self._on_state_action)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.state_panel)
        layout.addWidget(self.stack, 1)

        layout.addSpacing(10)
        layout.addLayout(self._build_footer())

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)

        brand = QLabel('TN<span style="color:%s;">.</span>' % styles.ACCENT.name())
        brand.setTextFormat(Qt.TextFormat.RichText)
        brand.setFont(styles.sans(15, styles.BOLD))
        brand.setStyleSheet(f"color: {styles.rgba(styles.TEXT)};")
        row.addWidget(brand)

        row.addStretch(1)

        wordmark = QLabel("ZeroPort")
        wordmark.setFont(styles.sans(13, styles.MEDIUM))
        wordmark.setStyleSheet(f"color: {styles.rgba(styles.TEXT_MUTED)};")
        row.addWidget(wordmark)

        return row

    def _build_toolbar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        stat = QVBoxLayout()
        stat.setSpacing(4)
        stat.addWidget(micro("Local ports"))

        count_row = QHBoxLayout()
        count_row.setSpacing(8)
        self.count_label = QLabel("—")
        self.count_label.setFont(styles.sans(24, styles.DEMI))
        self.count_label.setStyleSheet(f"color: {styles.rgba(styles.ACCENT)};")
        count_row.addWidget(self.count_label)

        self.count_caption = micro("Listening", styles.TEXT_FAINT)
        self.count_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom
        )
        self.count_caption.setContentsMargins(0, 0, 0, 5)
        count_row.addWidget(self.count_caption)
        count_row.addStretch(1)
        stat.addLayout(count_row)

        stat_holder = QWidget()
        stat_holder.setLayout(stat)
        stat_holder.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addWidget(stat_holder, 0, Qt.AlignmentFlag.AlignBottom)

        row.addStretch(1)

        self.search = QLineEdit()
        self.search.setObjectName("searchField")
        self.search.setPlaceholderText("Search ports, processes, PID…")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(280)
        self.search.setMaximumWidth(400)
        self.search.textChanged.connect(self._on_search_changed)
        row.addWidget(self.search, 0, Qt.AlignmentFlag.AlignBottom)

        self.interval_box = CaretComboBox()
        self.interval_box.setObjectName("intervalBox")
        self.interval_box.setToolTip("How often ZeroPort rescans on its own")
        for seconds, label in INTERVALS:
            self.interval_box.addItem(label, seconds)
        self.interval_box.addItem("AUTO · OFF", 0)
        self.interval_box.currentIndexChanged.connect(self._on_interval_changed)
        row.addWidget(self.interval_box, 0, Qt.AlignmentFlag.AlignBottom)

        self.settings_button = QPushButton("NAMES")
        self.settings_button.setObjectName("ghostButton")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("Give your own names to ports")
        self.settings_button.clicked.connect(self.edit_custom_descriptions)
        row.addWidget(self.settings_button, 0, Qt.AlignmentFlag.AlignBottom)

        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignBottom)

        return row

    def _build_scan_bar(self) -> QProgressBar:
        bar = QProgressBar()
        bar.setObjectName("scanBar")
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setFixedHeight(3)
        bar.setStyleSheet(
            f"QProgressBar {{ background: {styles.rgba(styles.LINE)};"
            f" border: none; }}"
            f"QProgressBar::chunk {{ background: {styles.rgba(styles.ACCENT, 0.75)}; }}"
        )
        bar.setVisible(False)
        self.scan_bar = bar
        return bar

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.status_label = micro("", styles.TEXT_FAINT)
        row.addWidget(self.status_label)
        row.addStretch(1)

        # The footer mark keeps its real casing — it is a domain, not a label.
        for text in (f"v{APP_VERSION}", APP_SITE):
            mark = QLabel(text)
            font = styles.mono(8)
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
            mark.setFont(font)
            mark.setStyleSheet(f"color: {styles.rgba(styles.TEXT_GHOST)};")
            row.addWidget(mark)
        return row

    def _build_worker(self) -> None:
        self.thread = QThread(self)
        self.thread.setObjectName("zeroport-scan")
        self.worker = ScanWorker(self.config.custom_descriptions)
        self.worker.moveToThread(self.thread)

        self.request_scan.connect(self.worker.run_scan)
        self.request_stop.connect(self.worker.run_stop)
        self.request_custom.connect(self.worker.set_custom_descriptions)

        self.worker.scan_finished.connect(self._on_scan_finished)
        self.worker.scan_failed.connect(self._on_scan_failed)
        self.worker.stop_finished.connect(self._on_stop_finished)

        self.thread.start()

        self.auto_timer = QTimer(self)
        self.auto_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self.auto_timer.timeout.connect(self._on_auto_tick)

        # A scan takes ~70 ms. Showing the bar immediately would flash a lime
        # line across the window every few seconds for no reason, so it only
        # appears if a scan is actually slow enough to be worth reporting.
        self.scan_bar_timer = QTimer(self)
        self.scan_bar_timer.setSingleShot(True)
        self.scan_bar_timer.timeout.connect(lambda: self.scan_bar.setVisible(True))

    def _build_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.refresh)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.search.setFocus)
        QShortcut(QKeySequence("Escape"), self, activated=self._clear_search)

    # --------------------------------------------------------------- scanning

    def refresh(self) -> None:
        """Ask for a fresh scan, coalescing overlapping requests."""
        if self._scan_in_flight:
            self._rescan_queued = True
            return
        self._scan_in_flight = True
        self._show_progress(True)
        self.refresh_button.setEnabled(False)
        self.request_scan.emit()

    def _show_progress(self, busy: bool) -> None:
        """Reveal the scan bar only if the work outlasts a glance."""
        if busy:
            if not self.scan_bar.isVisible():
                self.scan_bar_timer.start(250)
        else:
            self.scan_bar_timer.stop()
            self.scan_bar.setVisible(False)

    def _on_auto_tick(self) -> None:
        # Never rescan under an open dialog — the row the user is reading
        # must not move.
        if self._dialog_depth == 0 and not self._scan_in_flight:
            self.refresh()

    def _on_scan_finished(self, entries: List[PortEntry]) -> None:
        self._scan_in_flight = False
        self._had_first_result = True
        self._show_progress(False)
        self.refresh_button.setEnabled(True)

        self._error_message = None
        self._entries = entries
        self.table.set_entries(entries)
        self._update_view_state()

        if self._rescan_queued:
            self._rescan_queued = False
            QTimer.singleShot(0, self.refresh)

    def _on_scan_failed(self, message: str) -> None:
        self._scan_in_flight = False
        self._rescan_queued = False
        self._show_progress(False)
        self.refresh_button.setEnabled(True)

        # Drop the previous result: showing stale rows as if they were current
        # is worse than showing nothing.
        self._error_message = message
        self._entries = []
        self.table.set_entries([])
        self._update_view_state()

    def _update_view_state(self) -> None:
        if self._error_message:
            self.count_label.setText("—")
            self.count_caption.setText("Listening")
            self.state_panel.show_error(self._error_message)
            self.stack.setCurrentWidget(self.state_panel)
            return

        total = len(self._entries)
        visible = self.table.visible_count()
        query = self.search.text().strip()

        if query and total:
            self.count_label.setText(str(visible))
            self.count_caption.setText(f"of {total} listening")
        else:
            self.count_label.setText(str(total))
            self.count_caption.setText("Listening")

        if total == 0:
            self.state_panel.show_empty()
            self.stack.setCurrentWidget(self.state_panel)
        elif visible == 0:
            self.state_panel.show_no_matches(query)
            self.stack.setCurrentWidget(self.state_panel)
        else:
            self.stack.setCurrentWidget(self.table)

    # --------------------------------------------------------------- controls

    def _on_search_changed(self, text: str) -> None:
        self.table.proxy.set_query(text)
        if self._had_first_result:
            self._update_view_state()

    def _clear_search(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.search.clearFocus()

    def _on_interval_changed(self, _index: int) -> None:
        seconds = int(self.interval_box.currentData())
        self._apply_interval(seconds, persist=True)

    def _apply_interval(self, seconds: int, persist: bool = False) -> None:
        index = self.interval_box.findData(seconds)
        if index >= 0 and index != self.interval_box.currentIndex():
            self.interval_box.blockSignals(True)
            self.interval_box.setCurrentIndex(index)
            self.interval_box.blockSignals(False)

        if seconds > 0:
            self.auto_timer.start(seconds * 1000)
        else:
            self.auto_timer.stop()

        if persist:
            self.config.set_refresh(seconds > 0, seconds or None)

    def _on_state_action(self) -> None:
        """One button, three panels — dispatch on which panel is showing."""
        if self.state_panel.state == StatePanel.NO_MATCHES:
            self.search.clear()
        else:
            self.refresh()

    # ------------------------------------------------------------ stop action

    def confirm_stop(self, entry: PortEntry) -> None:
        if not entry.can_stop:
            with self._modal():
                NoticeDialog(
                    self, *self._refusal(entry), kicker="Not allowed"
                ).exec()
            return

        if self._pending_stop is not None:
            self.set_status(
                f"Still stopping {self._pending_stop.process.display_name} — "
                "one at a time."
            )
            return

        with self._modal():
            confirmed = ConfirmStopDialog(self, entry).exec() == ConfirmStopDialog.DialogCode.Accepted

        if not confirmed:
            return

        self._pending_stop = entry
        self.set_status(f"Stopping {entry.process.display_name} (PID {entry.pid})…")
        self._show_progress(True)
        self.request_stop.emit(entry)

    @staticmethod
    def _refusal(entry: PortEntry) -> tuple[str, str]:
        """Say why a row cannot be stopped — not every reason is protection."""
        if not entry.has_pid:
            return (
                "No process to stop",
                "Windows did not report which process owns this socket, so "
                "ZeroPort has nothing to act on.",
            )
        if not entry.process.exists:
            return (
                "Process already gone",
                "This process has exited. Refresh to update the list.",
            )
        return (
            "Protected process",
            entry.protection_reason
            or "This process is protected by Windows and cannot be stopped here.",
        )

    def _on_stop_finished(self, entry: PortEntry, result: TerminationResult) -> None:
        self._pending_stop = None
        if not self._scan_in_flight:
            self._show_progress(False)

        if result.outcome is TerminationOutcome.STOPPED:
            released = ", ".join(str(p) for p in entry.owned_ports)
            self.set_status(f"Stopped {entry.process.display_name} · released {released}")
        elif result.outcome is TerminationOutcome.ALREADY_EXITED:
            self.set_status(result.message)
        else:
            with self._modal():
                NoticeDialog.show_error(self, "Unable to stop this process", result.message)

        self.refresh()

    # ---------------------------------------------------------------- details

    def show_details(self, entry: PortEntry) -> None:
        with self._modal():
            ProcessDetailsDialog(self, entry).exec()

    def edit_custom_descriptions(self) -> None:
        with self._modal():
            dialog = CustomDescriptionsDialog(
                self, self.config.custom_descriptions, str(self.config.path)
            )
            accepted = dialog.exec() == CustomDescriptionsDialog.DialogCode.Accepted

        if not accepted:
            return

        mappings = dialog.mappings()
        self.config.set_custom_descriptions(mappings)
        self.request_custom.emit(self.config.custom_descriptions)
        self.table.delegate.set_custom_ports(int(p) for p in self.config.custom_descriptions)
        self.set_status(f"Saved {len(mappings)} custom port name(s)")
        self.refresh()

    def _show_context_menu(self, position) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        entry = index.data(ENTRY_ROLE) or self.table.selected_entry()
        if entry is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {styles.rgba(styles.SURFACE_RAISED)};"
            f" border: 1px solid {styles.rgba(styles.LINE_STRONG)}; padding: 4px; }}"
            f"QMenu::item {{ padding: 7px 18px; color: {styles.rgba(styles.TEXT_MUTED)}; }}"
            f"QMenu::item:selected {{ background: {styles.rgba(styles.ACCENT_SOFT)};"
            f" color: {styles.rgba(styles.TEXT)}; }}"
            f"QMenu::item:disabled {{ color: {styles.rgba(styles.TEXT_GHOST)}; }}"
        )

        # Actions belong to the menu, and the menu is disposed of after use —
        # otherwise every right-click leaves one behind for the window's life.
        details = QAction("Process details", menu)
        details.triggered.connect(lambda: self.show_details(entry))
        menu.addAction(details)

        copy_port = QAction(f"Copy port {entry.port}", menu)
        copy_port.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(str(entry.port))
        )
        menu.addAction(copy_port)

        if entry.has_pid:
            copy_pid = QAction(f"Copy PID {entry.pid}", menu)
            copy_pid.triggered.connect(
                lambda: QGuiApplication.clipboard().setText(str(entry.pid))
            )
            menu.addAction(copy_pid)

        menu.addSeparator()
        stop = QAction("Stop process", menu)
        stop.setEnabled(entry.can_stop)
        stop.triggered.connect(lambda: self.confirm_stop(entry))
        menu.addAction(stop)

        menu.exec(self.table.viewport().mapToGlobal(position))
        menu.deleteLater()

    # ----------------------------------------------------------------- status

    def set_status(self, message: str) -> None:
        self._status_token += 1
        token = self._status_token
        self.status_label.setText(message)

        def clear() -> None:
            if token == self._status_token:
                self.status_label.setText("")

        QTimer.singleShot(STATUS_CLEAR_MS, clear)

    class _ModalGuard:
        """Suspends auto-refresh for as long as a dialog is on screen."""

        def __init__(self, window: "MainWindow") -> None:
            self._window = window

        def __enter__(self) -> None:
            self._window._dialog_depth += 1

        def __exit__(self, *_exc) -> None:
            self._window._dialog_depth -= 1

    def _modal(self) -> "MainWindow._ModalGuard":
        return MainWindow._ModalGuard(self)

    # ---------------------------------------------------------------- teardown

    def closeEvent(self, event) -> None:
        self.auto_timer.stop()
        geometry = self.normalGeometry()
        self.config.set_window_state(
            geometry.width(), geometry.height(), self.isMaximized()
        )

        # quit() cannot interrupt a slot that is already running, and a stop
        # can legitimately block for graceful + forced timeouts. Wait past that
        # worst case rather than calling QThread::terminate(), which on Windows
        # kills the thread mid-bytecode while it holds the GIL and open process
        # handles.
        self.thread.quit()
        if not self.thread.wait(SHUTDOWN_WAIT_MS):
            # Nothing safe is left to do, and destroying a running QThread is
            # a hard abort. Leave immediately instead; there is no state to
            # flush — the config was already saved above.
            os._exit(0)
        super().closeEvent(event)
