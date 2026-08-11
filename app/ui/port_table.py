"""The port table: model, filter, delegate and view.

Rows are painted by a single delegate rather than assembled from widgets, so a
list of a few hundred listeners stays cheap to render and the visual language
stays exactly where it was designed.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import (
    QAbstractTableModel,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    QRect,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QFontMetrics, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
)

from app.models.port_info import PortEntry
from app.ui import styles

ENTRY_ROLE = Qt.ItemDataRole.UserRole + 1
SORT_ROLE = Qt.ItemDataRole.UserRole + 2

COL_PORT, COL_PROCESS, COL_PID, COL_ADDRESS, COL_DESCRIPTION, COL_STATUS, COL_ACTION = range(7)

HEADERS = ("PORT", "PROCESS", "PID", "ADDRESS", "DESCRIPTION", "STATUS", "ACTION")

ROW_HEIGHT = 40
CELL_PADDING = 12


class PortTableModel(QAbstractTableModel):
    """Holds the current scan result. Rebuilt wholesale on every refresh."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._entries: List[PortEntry] = []

    # ------------------------------------------------------------- interface

    def set_entries(self, entries: List[PortEntry]) -> None:
        self.beginResetModel()
        self._entries = list(entries)
        self.endResetModel()

    def entry_at(self, row: int) -> Optional[PortEntry]:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    # ------------------------------------------------------- Qt model plumbing

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return HEADERS[section]
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self._entries[index.row()]
        column = index.column()

        if role == ENTRY_ROLE:
            return entry

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(entry, column)

        if role == SORT_ROLE:
            return self._sort_key(entry, column)

        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(entry, column)

        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # ---------------------------------------------------------------- content

    @staticmethod
    def _display(entry: PortEntry, column: int) -> str:
        if column == COL_PORT:
            return str(entry.port)
        if column == COL_PROCESS:
            return entry.process.name or "—"
        if column == COL_PID:
            return str(entry.pid) if entry.has_pid else "—"
        if column == COL_ADDRESS:
            return entry.address
        if column == COL_DESCRIPTION:
            return entry.description
        if column == COL_STATUS:
            return entry.status
        return ""

    @staticmethod
    def _sort_key(entry: PortEntry, column: int):
        if column == COL_PORT:
            return entry.port
        if column == COL_PID:
            return entry.pid if entry.has_pid else -1
        if column == COL_PROCESS:
            return (entry.process.name or "￿").lower()
        if column == COL_ADDRESS:
            return entry.address.lower()
        if column == COL_DESCRIPTION:
            return entry.description.lower()
        if column == COL_STATUS:
            return entry.status
        return int(entry.can_stop)

    @staticmethod
    def _tooltip(entry: PortEntry, column: int) -> Optional[str]:
        if column == COL_PID and entry.shares_process:
            ports = ", ".join(str(p) for p in entry.owned_ports)
            return f"PID {entry.pid} is listening on {len(entry.owned_ports)} ports: {ports}"
        if column == COL_PROCESS and entry.process.exe:
            return entry.process.exe
        if column == COL_DESCRIPTION:
            return entry.process.cmdline or entry.description
        if column == COL_ADDRESS:
            return f"{entry.protocol} · {entry.address}:{entry.port}"
        if column == COL_ACTION and entry.protected:
            return entry.protection_reason or "Protected system process."
        if column == COL_STATUS and not entry.has_pid:
            return "Windows did not report an owning process for this socket."
        return None


class PortFilterProxy(QSortFilterProxyModel):
    """Instant search across every visible field of a row."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self._needles: Tuple[str, ...] = ()

    def set_query(self, text: str) -> None:
        needles = tuple(part for part in text.lower().split() if part)
        if needles == self._needles:
            return
        self._needles = needles
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        if not self._needles:
            return True
        model = self.sourceModel()
        entry = model.entry_at(source_row)
        if entry is None:
            return False
        blob = entry.search_blob
        return all(needle in blob for needle in self._needles)


class MicroHeader(QHeaderView):
    """Uppercase monospace column labels with a lime sort caret."""

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self.setSortIndicatorShown(False)
        self.setHighlightSections(False)
        self.setFixedHeight(34)
        self.setFont(styles.micro_label(8))

    def paintSection(self, painter: QPainter, rect: QRect, index: int) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        active = self.sortIndicatorSection() == index
        painter.setFont(self.font())
        painter.setPen(styles.TEXT if active else styles.TEXT_FAINT)

        align = Qt.AlignmentFlag.AlignVCenter | (
            Qt.AlignmentFlag.AlignRight
            if index == COL_ACTION
            else Qt.AlignmentFlag.AlignLeft
        )
        text_rect = rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, -6)
        painter.drawText(text_rect, align, HEADERS[index])

        if active:
            metrics = QFontMetrics(self.font())
            width = metrics.horizontalAdvance(HEADERS[index])
            caret_x = text_rect.left() + width + 7
            caret_y = text_rect.center().y() + 1
            ascending = self.sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(styles.ACCENT)
            points = (
                [QPoint(caret_x, caret_y + 2), QPoint(caret_x + 6, caret_y + 2), QPoint(caret_x + 3, caret_y - 2)]
                if ascending
                else [QPoint(caret_x, caret_y - 2), QPoint(caret_x + 6, caret_y - 2), QPoint(caret_x + 3, caret_y + 2)]
            )
            painter.drawPolygon(points)

        painter.setPen(QPen(styles.LINE_STRONG, 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        painter.restore()


class PortItemDelegate(QStyledItemDelegate):
    """Paints every cell, including the STOP affordance."""

    stop_requested = Signal(QModelIndex)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mono = styles.mono(11)
        self._mono_strong = styles.mono(12, styles.BOLD)
        self._sans = styles.sans(10)
        self._micro = styles.micro_label(8)
        self._pressed_row = -1
        self._custom_ports: set[int] = set()

    def set_custom_ports(self, ports) -> None:
        """Ports the user has named themselves, so they can be marked as such."""
        self._custom_ports = {int(p) for p in ports}

    # ------------------------------------------------------------------ paint

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(ROW_HEIGHT)
        return size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        entry: PortEntry = index.data(ENTRY_ROLE)
        if entry is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        if selected:
            painter.fillRect(rect, styles.SURFACE_SELECTED)
        elif hovered:
            painter.fillRect(rect, styles.SURFACE_HOVER)

        # Hairline separator, and a lime edge marker on the selected row.
        painter.setPen(QPen(styles.LINE, 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
        if selected and index.column() == COL_PORT:
            painter.fillRect(QRect(rect.left(), rect.top(), 2, rect.height()), styles.ACCENT)

        column = index.column()
        content = rect.adjusted(CELL_PADDING, 0, -CELL_PADDING, 0)

        if column == COL_ACTION:
            self._paint_action(painter, rect, entry, hovered)
        elif column == COL_STATUS:
            self._paint_status(painter, content, entry)
        elif column == COL_PID:
            self._paint_pid(painter, content, entry)
        else:
            self._paint_text(painter, content, index, entry, column)

        painter.restore()

    def _paint_text(self, painter, content, index, entry: PortEntry, column: int) -> None:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        if column == COL_PORT:
            font = self._mono_strong
            color = styles.TEXT
        elif column == COL_ADDRESS:
            font = self._mono
            color = styles.TEXT_FAINT
        elif column == COL_PROCESS:
            font = self._sans
            color = styles.TEXT if entry.process.name else styles.TEXT_GHOST
        else:
            font = self._sans
            color = styles.TEXT_MUTED

        if column == COL_DESCRIPTION and entry.port in self._custom_ports:
            color = styles.ACCENT

        painter.setFont(font)
        painter.setPen(color)
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(str(text), Qt.TextElideMode.ElideRight, content.width())
        painter.drawText(
            content, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided
        )

    def _paint_pid(self, painter, content, entry: PortEntry) -> None:
        x = content.left()

        # A process holding several ports gets the one violet accent in the app.
        if entry.shares_process:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(styles.VIOLET)
            painter.drawEllipse(x, content.center().y() - 1, 4, 4)
            x += 10

        painter.setFont(self._mono)
        painter.setPen(styles.TEXT_MUTED if entry.has_pid else styles.TEXT_GHOST)
        text_rect = QRect(x, content.top(), content.right() - x, content.height())
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            str(entry.pid) if entry.has_pid else "—",
        )

    def _paint_status(self, painter, content, entry: PortEntry) -> None:
        status = entry.status
        if entry.protected:
            label, dot = "PROTECTED", styles.TEXT_GHOST
        elif status == "RUNNING":
            label, dot = "RUNNING", styles.ACCENT
        elif status == "EXITED":
            label, dot = "EXITED", styles.DANGER
        else:
            label, dot = "UNKNOWN", styles.TEXT_GHOST

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        painter.drawEllipse(content.left(), content.center().y() - 2, 5, 5)

        painter.setFont(self._micro)
        painter.setPen(styles.TEXT_MUTED if label == "RUNNING" else styles.TEXT_FAINT)
        text_rect = QRect(content.left() + 13, content.top(), content.width() - 13, content.height())
        painter.drawText(
            text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label
        )

    def _paint_action(self, painter, rect: QRect, entry: PortEntry, hovered: bool) -> None:
        if not entry.can_stop:
            painter.setFont(self._micro)
            painter.setPen(styles.TEXT_GHOST)
            painter.drawText(
                rect.adjusted(0, 0, -CELL_PADDING, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                "LOCKED" if entry.protected else "—",
            )
            return

        box = self.button_rect(rect)
        border = styles.DANGER if hovered else styles.LINE_STRONG
        text_color = styles.DANGER if hovered else styles.TEXT_FAINT

        if hovered:
            painter.fillRect(box, styles.DANGER_SOFT)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(box.adjusted(0, 0, -1, -1))

        painter.setFont(self._micro)
        painter.setPen(text_color)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, "STOP")

    @staticmethod
    def button_rect(rect: QRect) -> QRect:
        width, height = 62, 24
        return QRect(
            rect.right() - CELL_PADDING - width,
            rect.center().y() - height // 2 + 1,
            width,
            height,
        )

    # ------------------------------------------------------------ interaction

    def editorEvent(self, event, model, option, index: QModelIndex) -> bool:
        if index.column() != COL_ACTION:
            return False
        entry: PortEntry = index.data(ENTRY_ROLE)
        if entry is None or not entry.can_stop:
            return False
        if event.type() not in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
        ):
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        if not self.button_rect(option.rect).contains(event.position().toPoint()):
            self._pressed_row = -1
            return False

        if event.type() == QEvent.Type.MouseButtonPress:
            self._pressed_row = index.row()
            return True

        if self._pressed_row == index.row():
            self._pressed_row = -1
            self.stop_requested.emit(index)
        return True


class PortTableView(QTableView):
    """A quiet, keyboard-friendly table over the scan results."""

    stop_requested = Signal(object)
    details_requested = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model_ = PortTableModel(self)
        self.proxy = PortFilterProxy(self)
        self.proxy.setSourceModel(self.model_)
        self.setModel(self.proxy)

        self.delegate = PortItemDelegate(self)
        self.setItemDelegate(self.delegate)
        self.delegate.stop_requested.connect(self._on_delegate_stop)

        self.setHorizontalHeader(MicroHeader(self))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.setShowGrid(False)
        self.setFrameShape(QTableView.Shape.NoFrame)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(False)
        self.setMouseTracking(True)
        self.setWordWrap(False)
        self.setSortingEnabled(True)
        self.setObjectName("portTable")
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPixel)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # Let the window's texture show through instead of a flat panel colour.
        palette = self.viewport().palette()
        palette.setColor(QPalette.ColorRole.Base, Qt.GlobalColor.transparent)
        palette.setColor(QPalette.ColorRole.Window, Qt.GlobalColor.transparent)
        self.viewport().setPalette(palette)
        self.viewport().setAutoFillBackground(False)

        header = self.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_DESCRIPTION, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        for column, width in (
            (COL_PORT, 96),
            (COL_PROCESS, 200),
            (COL_PID, 96),
            (COL_ADDRESS, 132),
            (COL_STATUS, 128),
            (COL_ACTION, 104),
        ):
            self.setColumnWidth(column, width)
        header.setSortIndicator(COL_PORT, Qt.SortOrder.AscendingOrder)

        self.doubleClicked.connect(self._on_double_clicked)

    # --------------------------------------------------------------- content

    def set_entries(self, entries: List[PortEntry]) -> None:
        """Replace the rows, keeping the user's selection and scroll position."""
        keep = self.selected_key()
        offset = self.verticalScrollBar().value()

        self.model_.set_entries(entries)

        if keep is not None:
            self.select_key(keep)
        self.verticalScrollBar().setValue(min(offset, self.verticalScrollBar().maximum()))

    def selected_entry(self) -> Optional[PortEntry]:
        indexes = self.selectionModel().selectedRows()
        if not indexes:
            return None
        return indexes[0].data(ENTRY_ROLE)

    def selected_key(self) -> Optional[Tuple]:
        entry = self.selected_entry()
        return None if entry is None else _key(entry)

    def select_key(self, key: Tuple) -> None:
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            entry = index.data(ENTRY_ROLE)
            if entry is not None and _key(entry) == key:
                self.selectionModel().setCurrentIndex(
                    index,
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Rows,
                )
                return

    def visible_count(self) -> int:
        return self.proxy.rowCount()

    # ----------------------------------------------------------- interaction

    def _on_delegate_stop(self, index: QModelIndex) -> None:
        entry = index.data(ENTRY_ROLE)
        if entry is not None:
            self.stop_requested.emit(entry)

    def _on_double_clicked(self, index: QModelIndex) -> None:
        entry = index.data(ENTRY_ROLE)
        if entry is not None:
            self.details_requested.emit(entry)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            entry = self.selected_entry()
            if entry is not None:
                self.details_requested.emit(entry)
                return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        over_button = False
        if index.isValid() and index.column() == COL_ACTION:
            entry = index.data(ENTRY_ROLE)
            if entry is not None and entry.can_stop:
                over_button = PortItemDelegate.button_rect(
                    self.visualRect(index)
                ).contains(event.position().toPoint())
        self.setCursor(
            Qt.CursorShape.PointingHandCursor if over_button else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)


def _key(entry: PortEntry) -> Tuple:
    return (entry.port, entry.protocol, entry.address, entry.pid)
