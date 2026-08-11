"""Small custom-painted controls.

Qt's stylesheet sub-controls (``QComboBox::down-arrow`` and friends) render
inconsistently across styles and DPI. Where the design needs an exact mark,
it is cheaper and more reliable to paint it.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QComboBox

from app.ui import styles


class CaretComboBox(QComboBox):
    """A quiet outlined selector with a lime-free caret drawn by hand."""

    PADDING = 11
    CARET_WIDTH = 7

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFont(styles.mono(9))
        self._hovered = False

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        widest = max(
            (metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())),
            default=60,
        )
        size = super().sizeHint()
        size.setWidth(widest + self.PADDING * 2 + self.CARET_WIDTH + 14)
        size.setHeight(max(size.height(), 34))
        return size

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        active = self._hovered or self.view().isVisible()
        frame = self.rect().adjusted(0, 0, -1, -1)

        painter.setPen(QPen(styles.LINE_STRONG if active else styles.LINE, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(frame)

        caret_x = frame.right() - self.PADDING - self.CARET_WIDTH
        text_rect = QRect(
            frame.left() + self.PADDING,
            frame.top(),
            caret_x - frame.left() - self.PADDING - 8,
            frame.height(),
        )

        painter.setFont(self.font())
        painter.setPen(styles.TEXT if active else styles.TEXT_MUTED)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.currentText(),
        )

        centre_y = frame.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(styles.TEXT if active else styles.TEXT_FAINT)
        painter.drawPolygon(
            [
                QPoint(caret_x, centre_y - 1),
                QPoint(caret_x + self.CARET_WIDTH, centre_y - 1),
                QPoint(caret_x + self.CARET_WIDTH // 2, centre_y + 3),
            ]
        )
        painter.end()
