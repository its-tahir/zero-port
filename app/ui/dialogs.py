"""Dialogs: confirm a stop, inspect a process, edit port names, report failures.

They share one skeleton — micro-label, headline, lime hairline, body, actions —
so the app never feels like it borrowed a dialog from somewhere else.
"""

from __future__ import annotations

from typing import Dict, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models.port_info import PortEntry
from app.ui import styles


def hairline(color=None, height: int = 1) -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.NoFrame)
    line.setFixedHeight(height)
    line.setStyleSheet(f"background: {styles.rgba(color or styles.LINE)};")
    return line


def micro(text: str, color=None) -> QLabel:
    label = QLabel(text)
    label.setFont(styles.micro_label(8))
    label.setStyleSheet(f"color: {styles.rgba(color or styles.TEXT_FAINT)};")
    return label


class BaseDialog(QDialog):
    """Shared shell: quiet kicker, headline, lime rule, body, action row."""

    def __init__(
        self,
        parent,
        kicker: str,
        headline: str,
        width: int = 460,
        scrollable: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"ZeroPort — {headline}")
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setStyleSheet(f"QDialog {{ background: {styles.rgba(styles.SURFACE)}; }}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(0)

        outer.addWidget(micro(kicker))
        outer.addSpacing(10)

        title = QLabel(headline)
        title.setFont(styles.sans(16, styles.DEMI))
        title.setStyleSheet(f"color: {styles.rgba(styles.TEXT)};")
        outer.addWidget(title)

        outer.addSpacing(14)
        rule = hairline(styles.ACCENT)
        rule.setFixedWidth(28)
        outer.addWidget(rule)
        outer.addSpacing(18)

        self.body = QVBoxLayout()
        self.body.setSpacing(0)
        if scrollable:
            # A command line can be 2 KB long; the dialog must not grow past
            # the screen because of it.
            holder = QWidget()
            holder.setLayout(self.body)
            area = QScrollArea()
            area.setWidget(holder)
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setMaximumHeight(500)
            area.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            area.setStyleSheet("QScrollArea, QScrollArea > QWidget { background: transparent; }")
            outer.addWidget(area)
        else:
            outer.addLayout(self.body)

        outer.addSpacing(20)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(10)
        self.actions.addStretch(1)
        outer.addLayout(self.actions)

    # ------------------------------------------------------------- utilities

    def add_paragraph(self, text: str, color=None, top: int = 0) -> QLabel:
        if top:
            self.body.addSpacing(top)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(styles.sans(10))
        label.setStyleSheet(f"color: {styles.rgba(color or styles.TEXT_MUTED)};")
        self.body.addWidget(label)
        return label

    def add_field(self, name: str, value: str, mono: bool = False) -> None:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 13)
        layout.setSpacing(5)

        layout.addWidget(micro(name))

        label = QLabel(value if value else "—")
        label.setFont(styles.mono(10) if mono else styles.sans(10))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setStyleSheet(
            f"color: {styles.rgba(styles.TEXT if value else styles.TEXT_GHOST)};"
        )
        layout.addWidget(label)

        self.body.addWidget(row)

    def add_button(
        self, text: str, object_name: str, default: bool = False
    ) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAutoDefault(False)
        button.setDefault(default)
        self.actions.addWidget(button)
        return button


class ConfirmStopDialog(BaseDialog):
    """The only destructive confirmation in the product."""

    def __init__(self, parent, entry: PortEntry) -> None:
        super().__init__(parent, "Confirm", "Stop process?", width=440)

        self.add_field("Port", str(entry.port), mono=True)
        self.add_field("Process", entry.process.display_name)
        self.add_field("PID", str(entry.pid), mono=True)

        if entry.shares_process:
            others = ", ".join(str(p) for p in entry.sibling_ports)
            self.add_paragraph(
                f"This process is also listening on {others}. "
                "Stopping it will release those ports too.",
                styles.VIOLET,
            )
            self.body.addSpacing(12)

        self.add_paragraph(
            "This will terminate the process currently using this port. "
            "Unsaved work in that process will be lost."
        )

        cancel = self.add_button("CANCEL", "ghostButton", default=True)
        confirm = self.add_button("STOP PROCESS", "dangerButton")
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)


class ProcessDetailsDialog(BaseDialog):
    """Everything we know about one listener, for when the name means nothing."""

    def __init__(self, parent, entry: PortEntry) -> None:
        super().__init__(
            parent,
            "Process details",
            entry.process.display_name,
            width=560,
            scrollable=True,
        )

        self.add_field("Description", entry.description)
        self.add_field("Port", str(entry.port), mono=True)
        self.add_field(
            "Listening on",
            "\n".join(entry.endpoint_labels) or entry.address,
            mono=True,
        )
        self.add_field("PID", str(entry.pid) if entry.has_pid else "", mono=True)
        self.add_field("Status", entry.status)

        if entry.shares_process:
            self.add_field(
                "All ports for this PID",
                ", ".join(str(p) for p in entry.owned_ports),
                mono=True,
            )

        self.add_field("User", entry.process.username or "")
        self.add_field("Executable", entry.process.exe or "", mono=True)
        self.add_field("Command", entry.process.cmdline or "", mono=True)

        if entry.protected:
            self.add_paragraph(
                entry.protection_reason
                + "  ZeroPort will not stop this process.",
                styles.TEXT_FAINT,
            )
        elif not entry.process.accessible:
            self.add_paragraph(
                "Some details are unavailable because this process runs at a higher "
                "privilege level.",
                styles.TEXT_FAINT,
            )

        copy = self.add_button("COPY", "ghostButton")
        close = self.add_button("CLOSE", "ghostButton", default=True)
        copy.clicked.connect(lambda: self._copy(entry))
        close.clicked.connect(self.accept)

    def _copy(self, entry: PortEntry) -> None:
        from PySide6.QtGui import QGuiApplication

        lines = [
            f"Port      {entry.port} ({entry.protocol})",
            f"Address   {entry.address}",
            f"Process   {entry.process.display_name}",
            f"PID       {entry.pid if entry.has_pid else '-'}",
            f"Service   {entry.description}",
            f"Exe       {entry.process.exe or '-'}",
            f"Command   {entry.process.cmdline or '-'}",
        ]
        QGuiApplication.clipboard().setText("\n".join(lines))


class NoticeDialog(BaseDialog):
    """A single message the user must acknowledge — errors and refusals."""

    def __init__(self, parent, headline: str, message: str, kicker: str = "Notice") -> None:
        super().__init__(parent, kicker, headline, width=420)
        self.add_paragraph(message)
        close = self.add_button("OK", "ghostButton", default=True)
        close.clicked.connect(self.accept)

    @staticmethod
    def show_error(parent, headline: str, message: str) -> None:
        NoticeDialog(parent, headline, message, kicker="Unable to continue").exec()


class CustomDescriptionsDialog(BaseDialog):
    """Name your own ports. Saved straight into config.json."""

    def __init__(self, parent, mappings: Mapping[str, str], config_path: str) -> None:
        super().__init__(parent, "Settings", "Custom port names", width=520)

        self.add_paragraph(
            "Give a port your own label. Custom names override everything ZeroPort "
            "works out on its own."
        )
        self.body.addSpacing(16)

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("mappingTable")
        self.table.setHorizontalHeaderLabels(["PORT", "DESCRIPTION"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setFont(styles.micro_label(8))
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Fixed
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 90)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(200)
        self.table.setFont(styles.mono(10))
        self.body.addWidget(self.table)

        for port, label in sorted(mappings.items(), key=lambda kv: int(kv[0])):
            self._append_row(port, label)
        self._append_row("", "")

        self.body.addSpacing(10)
        hint = micro(f"Stored in  {config_path}")
        hint.setStyleSheet(f"color: {styles.rgba(styles.TEXT_GHOST)};")
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.addWidget(hint)

        add = self.add_button("ADD ROW", "ghostButton")
        remove = self.add_button("REMOVE", "ghostButton")
        cancel = self.add_button("CANCEL", "ghostButton")
        save = self.add_button("SAVE", "refreshButton", default=True)

        add.clicked.connect(lambda: self._append_row("", "", focus=True))
        remove.clicked.connect(self._remove_selected)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)

    def _append_row(self, port: str, label: str, focus: bool = False) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(port))
        self.table.setItem(row, 1, QTableWidgetItem(label))
        self.table.setRowHeight(row, 28)
        if focus:
            self.table.setCurrentCell(row, 0)
            self.table.editItem(self.table.item(row, 0))

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def mappings(self) -> Dict[str, str]:
        """Valid rows only — junk is dropped silently, as the config loader does."""
        result: Dict[str, str] = {}
        for row in range(self.table.rowCount()):
            port_item = self.table.item(row, 0)
            label_item = self.table.item(row, 1)
            if port_item is None or label_item is None:
                continue
            raw_port = port_item.text().strip()
            label = label_item.text().strip()
            if not raw_port or not label:
                continue
            try:
                port = int(raw_port)
            except ValueError:
                continue
            if 0 < port <= 65535:
                result[str(port)] = label
        return result
